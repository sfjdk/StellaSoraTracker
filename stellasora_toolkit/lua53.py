from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any, Protocol


TAG_NIL = 0
TAG_BOOLEAN = 1
TAG_FLOAT = 3
TAG_INTEGER = 0x13
# 可用版验证: TValue 的 tt_ 带 0x40 位(字符串对象字节为 4, 但 TValue tt_=0x44)。
TAG_SHORT_STRING = 0x44
TAG_TABLE = 0x45
TAG_LONG_STRING = 0x54
STRING_TAGS = {TAG_SHORT_STRING, TAG_LONG_STRING}


class MemoryReader(Protocol):
    def read(self, address: int, size: int) -> bytes: ...

    def try_read(self, address: int, size: int) -> bytes | None: ...

    def is_readable(self, address: int, size: int = 1) -> bool: ...


@dataclass(frozen=True)
class TValue:
    raw_value: bytes
    tag: int


class Lua53Reader:
    def __init__(self, memory: MemoryReader, max_table_entries: int = 100_000):
        self.memory = memory
        self.max_table_entries = max_table_entries

    def read_tvalue(self, address: int) -> TValue:
        raw = self.memory.read(address, 16)
        return TValue(raw[:8], struct.unpack_from("<i", raw, 8)[0])

    def _read_tvalue_or_skip(self, address: int) -> TValue | None:
        """读取 TValue; 不可读(如 Errno 299 / 部分页)时返回 None, 跳过该槽位。"""
        raw = self.memory.try_read(address, 16)
        if raw is None:
            return None
        return TValue(raw[:8], struct.unpack_from("<i", raw, 8)[0])

    def read_string(self, address: int) -> str:
        header = self.memory.read(address, 24)
        gc_tag = header[8]
        if gc_tag == 4:
            length = header[11]
        elif gc_tag == 20:
            length = struct.unpack_from("<Q", header, 16)[0]
        else:
            raise ValueError(f"0x{address:x} is not a Lua string")
        if length < 0 or length > 16 * 1024 * 1024:
            raise ValueError("invalid Lua string length")
        if length == 0:
            return ""
        if not self.memory.is_readable(address + 24, int(length)):
            raise ValueError("invalid Lua string length")
        return self.memory.read(address + 24, int(length)).decode("utf-8", errors="replace")

    def decode_tvalue(
        self,
        value: TValue,
        *,
        depth: int = 0,
        visited: set[int] | None = None,
    ) -> Any:
        raw_u64 = struct.unpack("<Q", value.raw_value)[0]
        if value.tag == TAG_NIL:
            return None
        if value.tag == TAG_BOOLEAN:
            return bool(struct.unpack("<i", value.raw_value[:4])[0])
        if value.tag == TAG_FLOAT:
            number = struct.unpack("<d", value.raw_value)[0]
            return number if math.isfinite(number) else None
        if value.tag == TAG_INTEGER:
            return struct.unpack("<q", value.raw_value)[0]
        if value.tag in STRING_TAGS:
            return self.read_string(raw_u64)
        if value.tag == TAG_TABLE:
            if depth >= 14:
                return "<max-depth>"
            visited = visited if visited is not None else set()
            if raw_u64 in visited:
                return "<cycle>"
            visited.add(raw_u64)
            try:
                return self.read_table(raw_u64, depth=depth + 1, visited=visited)
            finally:
                visited.remove(raw_u64)
        return None

    def table_header(self, address: int) -> tuple[int, int, int, int]:
        raw = self.memory.read(address, 48)
        if raw[8] != 5:
            raise ValueError(f"0x{address:x} is not a Lua table")
        lsize_node = raw[11]
        size_array = struct.unpack_from("<I", raw, 12)[0]
        array_ptr = struct.unpack_from("<Q", raw, 16)[0]
        node_ptr = struct.unpack_from("<Q", raw, 24)[0]
        if lsize_node > 24 or size_array > self.max_table_entries:
            raise ValueError("unreasonable Lua table size")
        return lsize_node, size_array, array_ptr, node_ptr

    def read_table_entries(
        self,
        address: int,
        *,
        depth: int = 0,
        visited: set[int] | None = None,
    ) -> list[tuple[Any, Any]]:
        lsize_node, size_array, array_ptr, node_ptr = self.table_header(address)
        node_count = 1 << lsize_node
        if size_array + node_count > self.max_table_entries:
            raise ValueError("Lua table exceeds entry limit")
        entries: list[tuple[Any, Any]] = []
        for index in range(size_array):
            item = self._read_tvalue_or_skip(array_ptr + index * 16)
            if item is None or item.tag == TAG_NIL:
                continue
            entries.append(
                (index + 1, self.decode_tvalue(item, depth=depth, visited=visited))
            )
        for index in range(node_count):
            node = node_ptr + index * 32
            value = self._read_tvalue_or_skip(node)
            key = self._read_tvalue_or_skip(node + 16)
            if value is None or key is None or key.tag == TAG_NIL or value.tag == TAG_NIL:
                continue
            decoded_key = self.decode_tvalue(key, depth=depth, visited=visited)
            decoded_value = self.decode_tvalue(value, depth=depth, visited=visited)
            entries.append((decoded_key, decoded_value))
        return entries

    def read_table(
        self,
        address: int,
        *,
        depth: int = 0,
        visited: set[int] | None = None,
    ) -> Any:
        entries = self.read_table_entries(address, depth=depth, visited=visited)
        if not entries:
            return []
        integer_keys = {key for key, _ in entries
                        if isinstance(key, int) and not isinstance(key, bool) and key > 0}
        if len(integer_keys) == len(entries) and integer_keys == set(range(1, len(entries) + 1)):
            values = dict(entries)
            return [values[index] for index in range(1, len(entries) + 1)]
        result: dict[Any, Any] = {}
        for key, value in entries:
            if isinstance(key, (str, int, float, bool)):
                result[key] = value
        return result

    def get_table_field_tvalue(self, table_address: int, field: str) -> TValue | None:
        lsize_node, _, _, node_ptr = self.table_header(table_address)
        for index in range(1 << lsize_node):
            node = node_ptr + index * 32
            key = self.read_tvalue(node + 16)
            if key.tag not in STRING_TAGS:
                continue
            key_ptr = struct.unpack("<Q", key.raw_value)[0]
            try:
                if self.read_string(key_ptr) == field:
                    return self.read_tvalue(node)
            except (OSError, ValueError):
                continue
        return None

