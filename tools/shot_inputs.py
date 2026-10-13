"""离屏渲染账号卡片(浅色/深色), 导成 PNG 以便人眼确认对比度。

用法: QT_QPA_PLATFORM=offscreen python tools/shot_inputs.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QButtonGroup, QComboBox, QHBoxLayout, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,

)

from stellasora_toolkit.ui import theme  # noqa: E402
from stellasora_toolkit.ui.views import _style_combo_popup  # noqa: E402
from stellasora_toolkit.ui.widgets import Card, mk_label  # noqa: E402


def build() -> QWidget:
    root = QWidget(); root.setObjectName("AppRoot")
    lay = QVBoxLayout(root); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(12)
    card = Card()
    card.add(mk_label("账号", role="h2"))
    card.add(mk_label("游戏里换了账号后点「刷新游戏数据」, 工具会按读到的 UID 自动切过去。", role="muted"))
    combo = QComboBox()
    combo.addItems(["默认账号 · 空", "UID 100872990 · 653 组", "UID 200000001 · 12 组"])
    combo.setCurrentIndex(1)
    _style_combo_popup(combo)
    card.add(combo)
    row = QWidget(); rl = QVBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0)
    edit = QLineEdit(); edit.setPlaceholderText("例如 100872990")
    rl.addWidget(edit)
    card.add(row)
    lay.addWidget(card)
    # 游戏版本单选按钮: 选中的那个必须一眼看出来
    server_card = Card()
    server_card.add(mk_label("游戏版本", role="h2"))
    server_card.add(mk_label("国际服与日服共用 StellaSora.exe —— 工具会看内存里的语言文本自动识别; "
                            "手动点选后以你的选择为准。", role="muted"))
    browser = QWidget(); bl = QHBoxLayout(browser); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(8)
    group = QButtonGroup(browser); group.setExclusive(True)
    for index, text in enumerate(["国服 · xtlr.exe", "国际服 · StellaSora.exe", "日服 · StellaSora.exe"]):
        button = QPushButton(text); button.setProperty("role", "choice"); button.setCheckable(True)
        button.setChecked(index == 2)                       # 选中"日服"
        group.addButton(button); bl.addWidget(button)
    auto = QPushButton("自动识别"); auto.setProperty("role", "ghost")
    bl.addWidget(auto); bl.addStretch(1)
    server_card.add(browser)
    server_card.add(mk_label("当前生效: 日服（手动指定）· 名称语言 jp · 点「自动识别」可交回自动判断",
                             role="muted"))
    lay.addWidget(server_card)
    root.resize(760, 420)
    return root


def sample(image_path, x, y):
    """取一个像素的颜色 —— 用来断言下拉列表不是系统黑底。"""
    from PySide6.QtGui import QImage
    color = QImage(str(image_path)).pixelColor(x, y)
    return color.name(), color.lightness()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    out_dir = ROOT / ".testtmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    for dark in (False, True):
        theme.set_dark(dark)
        theme.apply_theme(app)
        widget = build()
        widget.show()
        app.processEvents()
        tag = "dark" if dark else "light"
        target = out_dir / f"inputs_{tag}.png"
        widget.grab().save(str(target))
        # 下拉列表单独抓一张: 账号列表就是在这里读的
        combo = widget.findChild(QComboBox)
        if combo is None:
            print(f"{tag}: {target}")
            continue
        combo.showPopup()
        app.processEvents()
        combo.view().ensurePolished()
        app.processEvents()
        popup_target = out_dir / f"inputs_{tag}_popup.png"
        combo.view().grab().save(str(popup_target))
        combo.hidePopup()
        name, lightness = sample(popup_target, 4, 4)
        expected = theme.get_palette().SURFACE
        ok = name.lower() == expected.lower()
        print(f"{tag}: {target} + {popup_target}")
        print(f"    下拉列表底色 {name}（期望 {expected}）亮度={lightness} {'OK' if ok else '不一致'}")
        if not ok:
            problems.append(f"{tag}: 下拉列表底色 {name} != {expected}")
        if dark and lightness > 140:
            problems.append(f"{tag}: 深色主题下底色偏亮（{lightness}）")
        if not dark and lightness < 140:
            problems.append(f"{tag}: 浅色主题下底色偏暗（{lightness}）")
    if problems:
        print("问题: " + "; ".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
