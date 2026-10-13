from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterator


if os.name != "nt":
    raise ImportError("stellasora_toolkit.process 依赖 Windows API，仅支持 Windows")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
TH32CS_SNAPPROCESS = 0x00000002
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE_PAGE_FLAGS = {
    0x02,  # PAGE_READONLY
    0x04,  # PAGE_READWRITE
    0x08,  # PAGE_WRITECOPY
    0x20,  # PAGE_EXECUTE_READ
    0x40,  # PAGE_EXECUTE_READWRITE
    0x80,  # PAGE_EXECUTE_WRITECOPY
}
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.ReadProcessMemory.restype = wintypes.BOOL
kernel32.VirtualQueryEx.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.POINTER(MEMORY_BASIC_INFORMATION),
    ctypes.c_size_t,
]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


# MemoryRegion 已移到与平台无关的 memory.py（解析层不该依赖系统 API）。
# 这里重新导出，`from .process import MemoryRegion` 的老写法继续可用。
from .memory import MemoryRegion  # noqa: E402  (保持既有导入路径可用)


def running_processes() -> list[tuple[str, int]]:
    """一次快照返回 [(可执行文件名, PID), ...], 供进程名匹配与服务器版本探测使用。"""
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    try:
        result: list[tuple[str, int]] = []
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            result.append((entry.szExeFile, int(entry.th32ProcessID)))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return result
    finally:
        kernel32.CloseHandle(snapshot)


def find_process_id(executable: str | Iterable[str]) -> int:
    """按候选进程名找 PID(国服/国际服进程名不同, 支持一次传入多个候选)。

    executable 为单个进程名或进程名序列; 依次匹配快照, 命中任一即返回。
    """
    if isinstance(executable, str):
        names = [executable]
    else:
        names = [name for name in executable if name]
    if not names:
        raise ValueError("没有可用的进程名")
    wanted = {name.casefold() for name in names}
    for exe_name, pid in running_processes():
        if exe_name.casefold() in wanted:
            return pid
    raise ProcessLookupError(
        f"未找到游戏进程 {' 或 '.join(names)}，请先登录游戏并进入主界面"
    )


class RemoteProcess:
    def __init__(self, pid: int):
        self.pid = pid
        self.handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), f"无法只读打开进程 PID {pid}")
        self._regions: list[MemoryRegion] | None = None

    def close(self) -> None:
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "RemoteProcess":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def regions(self) -> list[MemoryRegion]:
        if self._regions is not None:
            return self._regions
        result: list[MemoryRegion] = []
        address = 0
        maximum = (1 << 47) - 1
        mbi = MEMORY_BASIC_INFORMATION()
        while address < maximum:
            queried = kernel32.VirtualQueryEx(
                self.handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
            )
            if not queried:
                break
            base = int(mbi.BaseAddress or 0)
            size = int(mbi.RegionSize)
            basic_protect = int(mbi.Protect) & 0xFF
            if (
                mbi.State == MEM_COMMIT
                and not (mbi.Protect & PAGE_GUARD)
                and basic_protect != PAGE_NOACCESS
                and basic_protect in READABLE_PAGE_FLAGS
            ):
                result.append(MemoryRegion(base, size, int(mbi.Protect), int(mbi.Type)))
            next_address = base + max(size, 0x1000)
            if next_address <= address:
                break
            address = next_address
        self._regions = result
        return result

    def region_for(self, address: int) -> MemoryRegion | None:
        for region in self.regions():
            if region.base <= address < region.end:
                return region
        return None

    def is_readable(self, address: int, size: int = 1) -> bool:
        region = self.region_for(address)
        return region is not None and address + size <= region.end

    def read(self, address: int, size: int) -> bytes:
        if size < 0 or size > 128 * 1024 * 1024:
            raise ValueError(f"invalid read size: {size}")
        buffer = ctypes.create_string_buffer(size)
        read_count = ctypes.c_size_t()
        ok = kernel32.ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(read_count),
        )
        if not ok or read_count.value != size:
            raise OSError(ctypes.get_last_error(), f"ReadProcessMemory failed at 0x{address:x}")
        return buffer.raw

    def try_read(self, address: int, size: int) -> bytes | None:
        try:
            return self.read(address, size)
        except (OSError, ValueError, MemoryError):
            return None

    def unpack(self, fmt: str, address: int):
        return struct.unpack(fmt, self.read(address, struct.calcsize(fmt)))

    def scan(self, pattern: bytes, regions: Iterator[MemoryRegion] | None = None) -> Iterator[int]:
        for address, _pattern in self.scan_any([pattern], regions):
            yield address

    def scan_any(self, patterns: Iterable[bytes],
                 regions: Iterator[MemoryRegion] | None = None) -> Iterator[tuple[int, bytes]]:
        """一次遍历内存找多个 pattern, 命中处产出 (地址, 命中的 pattern)。

        多个 pattern 各扫一遍会把读取量成倍放大(UID 探测就因此很慢): 这里同样按
        4MB 分块, 但每块只读一次, 块内把所有 pattern 找完。
        """
        wanted = [pattern for pattern in patterns if pattern]
        if not wanted:
            return
        chunk_size = 4 * 1024 * 1024
        overlap = max(len(pattern) for pattern in wanted) - 1
        for region in regions or iter(self.regions()):
            offset = 0
            tail = b""
            while offset < region.size:
                take = min(chunk_size, region.size - offset)
                block = self.try_read(region.base + offset, take)
                if block is None:
                    offset += take
                    tail = b""
                    continue
                data = tail + block
                origin = region.base + offset - len(tail)
                for pattern in wanted:
                    search_from = 0
                    while True:
                        found = data.find(pattern, search_from)
                        if found < 0:
                            break
                        yield origin + found, pattern
                        search_from = found + 1
                tail = data[-overlap:] if overlap else b""
                offset += take

