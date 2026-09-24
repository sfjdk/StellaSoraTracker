from __future__ import annotations

import struct
from collections.abc import Iterable

from .lua53 import Lua53Reader, TAG_SHORT_STRING, TAG_TABLE
from .memory import MemoryRegion


class LuaTableDiscovery:
    """在"某个可读的地址空间"里定位 Lua 表。

    process 只需要实现 read / try_read / regions 三个方法 —— 不绑定任何
    平台 API。Windows 端传 RemoteProcess，安卓端传 sstemulator 的后端。
    （注解在 `from __future__ import annotations` 下不求值，故不引入依赖。）
    """

    def __init__(self, process, lua: Lua53Reader):
        self.process = process
        self.lua = lua

    def _find_tstrings(self, text: str) -> list[int]:
        encoded = text.encode("utf-8")
        result: list[int] = []
        for data_address in self.process.scan(encoded):
            object_address = data_address - 24
            header = self.process.try_read(object_address, 24)
            if header is None or header[8] != 4 or header[11] != len(encoded):
                continue
            if self.process.try_read(data_address, len(encoded) + 1) != encoded + b"\0":
                continue
            result.append(object_address)
        return result

    def _find_key_nodes(self, string_addresses: Iterable[int]) -> list[int]:
        nodes: list[int] = []
        for string_address in string_addresses:
            pointer = struct.pack("<Q", string_address)
            for reference in self.process.scan(pointer):
                tag_raw = self.process.try_read(reference + 8, 4)
                if tag_raw is None or struct.unpack("<i", tag_raw)[0] != TAG_SHORT_STRING:
                    continue
                node_address = reference - 16
                if node_address % 8 == 0:
                    nodes.append(node_address)
        return nodes

    @staticmethod
    def _nearby_regions(regions: list[MemoryRegion], address: int, radius: int) -> list[MemoryRegion]:
        low, high = max(0, address - radius), address + radius
        return [region for region in regions if region.end > low and region.base < high]

    def _scan_table_headers(self) -> list[tuple[int, int, int, int]]:
        """一次全内存扫描, 收集所有 8 对齐、tt_==5 的表头。

        返回 [(表地址, lsize_node, node_ptr, node_count), ...]。
        新版本游戏里表头可能离节点数组很远(实测 ~117MB), 必须全内存扫描。
        """
        headers: list[tuple[int, int, int, int]] = []
        for region in self.process.regions():
            offset = 0
            while offset < region.size:
                take = min(4 * 1024 * 1024, region.size - offset)
                block = self.process.try_read(region.base + offset, take)
                if block is None:
                    offset += take
                    continue
                start = (-(region.base + offset)) % 8
                if start + 8 <= len(block):
                    strided = block[start + 8::8]
                    i = strided.find(b"\x05")
                    while i != -1:
                        rel = start + i * 8
                        if rel + 32 > len(block):
                            i = strided.find(b"\x05", i + 1)
                            continue
                        lsize_node = block[rel + 11]
                        if lsize_node <= 24:
                            node_ptr = struct.unpack_from("<Q", block, rel + 24)[0]
                            headers.append((region.base + offset + rel, lsize_node,
                                            node_ptr, 1 << lsize_node))
                        i = strided.find(b"\x05", i + 1)
                offset += take
        return headers

    def _tables_containing_node(
        self, node_address: int, headers: list[tuple[int, int, int, int]] | None = None,
    ) -> list[int]:
        """用一次扫描出的表头列表, 找出 node_ptr 覆盖该节点的表。"""
        if headers is None:
            headers = self._scan_table_headers()
        candidates: list[int] = []
        for addr, _lsize, node_ptr, node_count in headers:
            delta = node_address - node_ptr
            if 0 <= delta < node_count * 32 and delta % 32 == 0:
                candidates.append(addr)
        return candidates

    def find_instance_table(self, field: str, companion_fields: set[str]) -> int:
        strings = self._find_tstrings(field)
        if not strings:
            raise LookupError(f"未找到 Lua 字段字符串 {field}")
        nodes = self._find_key_nodes(strings)
        # 全内存只扫一次, 4 类/所有节点共用同一份表头数据
        headers = self._scan_table_headers()
        checked: set[int] = set()
        candidates_with_field = 0
        max_matches = 0
        best = None
        best_matches = -1
        for node in nodes:
            for table in self._tables_containing_node(node, headers):
                if table in checked:
                    continue
                checked.add(table)
                try:
                    field_value = self.lua.get_table_field_tvalue(table, field)
                    if field_value is None or field_value.tag != TAG_TABLE:
                        continue
                    candidates_with_field += 1
                    matches = sum(
                        self.lua.get_table_field_tvalue(table, name) is not None
                        for name in companion_fields
                    )
                    max_matches = max(max_matches, matches)
                    if matches > best_matches:
                        best_matches = matches
                        best = table
                    # 伴随字段为空时不应静默信任单一匹配
                    required = min(2, len(companion_fields))
                    if companion_fields and matches >= required:
                        return table
                except (OSError, ValueError):
                    continue
        # 宽松回退: 即便伴随字段匹配不足, 只要某个表确实以该字段为表值, 也采用匹配最佳的那个
        if best is not None:
            return best
        raise LookupError(
            f"找到字段 {field}，但无法确认所属的 Lua 实例表。\n\n"
            f"[诊断] 字段字符串 {len(strings)} 个 · 键节点 {len(nodes)} 个 · 候选表 {len(checked)} 个 · "
            f"其中含该字段且为表的有 {candidates_with_field} 个 · 伴随字段最高匹配 {max_matches}/{len(companion_fields)}\n\n"
            "若“含字段为表”>0，说明命中了表但伴随字段校验没通过(可能在游戏里还没打开对应的记录页)；"
            "若为 0，说明定位到的候选表都不含该字段——通常是游戏数据结构/字段名变化。\n\n"
            "请按顺序操作后再试：\n"
            "1. 登录《星塔旅人》并进入游戏主界面；\n"
            "2. 在游戏内依次打开「旅人限时 / 秘纹限时 / 旅人常驻 / 秘纹常驻」四类招募记录页面，"
            "并等待每个列表完整显示；\n"
            "3. 回到本工具点击“刷新游戏数据”。\n\n"
            "若已按上述步骤仍失败，很可能是游戏更新导致 Lua 数据结构变化，"
            "该工具需要匹配新版本后才能读取。")

    def read_target_field(self, field: str, companion_fields: set[str]):
        instance = self.find_instance_table(field, companion_fields)
        value = self.lua.get_table_field_tvalue(instance, field)
        if value is None or value.tag != TAG_TABLE:
            raise LookupError(f"Lua 字段 {field} 不是表")
        try:
            return self.lua.decode_tvalue(value)
        except (OSError, ValueError, struct.error) as err:
            raise LookupError(
                f"Lua 字段 {field} 数据格式异常，可能是游戏版本/内存布局变化"
            ) from err

