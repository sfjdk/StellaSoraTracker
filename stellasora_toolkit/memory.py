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
    """一段可读的内存区间。"""

    base: int
    size: int
    protect: int = 0

    @property
    def end(self) -> int:
        return self.base + self.size
