# -*- coding: utf-8 -*-
"""与平台无关的内存抽象。

解析层（lua53 / discovery）只需要"一段可读地址区间"这个概念，
不应该依赖任何系统 API。原先 MemoryRegion 定义在 process.py 里，
而 process.py 在非 Windows 平台会直接抛 ImportError —— 安卓端要复用
同一套解析逻辑就绕不过去，所以把它拆到这里。

process.py 仍然重新导出这个名字，老代码 `from .process import MemoryRegion`
不受影响。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryRegion:
    """一段可读的内存区间。

    type 是 VirtualQueryEx 的 mbi.Type: MEM_PRIVATE(0x20000) 堆 /
    MEM_MAPPED(0x40000) 映射文件 / MEM_IMAGE(0x1000000) 模块映像。
    Lua 对象都在堆上, 所以全内存扫描可以跳过巨大的模块映像 —— 见 is_image。
    """

    base: int
    size: int
    protect: int = 0
    type: int = 0

    MEM_IMAGE = 0x1000000

    @property
    def end(self) -> int:
        return self.base + self.size

    @property
    def is_image(self) -> bool:
        """是不是模块映像(DLL/EXE 的代码与只读数据)。

        里面不会有 Lua 表/字符串, 却可能占掉几百 MB —— 扫描时优先跳过。
        """
        return bool(self.type & self.MEM_IMAGE)
