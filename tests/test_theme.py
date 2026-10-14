"""主题回归: 输入类控件必须带显式背景色。

事故: QComboBox 之前没有任何 QSS 规则, Windows 深色系统主题下 Qt 保留原生黑底,
而全局规则又给了深色文字 —— 界面上就是一个黑条上写着看不清的字。
这里锁住"输入控件/下拉列表都有背景色"这件事, 免得以后又被删掉。
"""
import unittest

from stellasora_toolkit.ui.theme import Palette, PaletteDark, build_qss


class InputWidgetStyleTests(unittest.TestCase):
    def test_light_and_dark_both_style_inputs(self):
        for palette in (Palette, PaletteDark):
            qss = build_qss(palette)
            with self.subTest(palette=palette.__name__):
                for selector in ("QLineEdit", "QComboBox", "QAbstractItemView"):
                    self.assertIn(selector, qss, f"{selector} 缺少样式规则")
                # 输入控件与下拉列表都要用主题里的 surface 当底色
                self.assertIn(f"background:{palette.SURFACE}", qss)
                self.assertIn(f"color:{palette.TEXT}", qss)

    def test_combo_popup_is_covered(self):
        qss = build_qss(Palette)
        self.assertIn("QComboBox QAbstractItemView", qss, "下拉列表(弹出窗口)必须单独给背景")
        self.assertIn("selection-background-color", qss)

    def test_dialogs_are_covered(self):
        qss = build_qss(PaletteDark())
        for selector in ("QMessageBox", "QInputDialog"):
            self.assertIn(selector, qss, f"{selector} 缺少样式规则")

    def test_dark_and_light_differ(self):
        self.assertNotEqual(build_qss(Palette), build_qss(PaletteDark()))


class PaletteTests(unittest.TestCase):
    """不只是 QSS: 下拉列表/弹窗这些原生绘制的部分要听调色板的。"""

    def test_palette_uses_theme_tokens(self):
        from stellasora_toolkit.ui.theme import build_palette

        for palette_class in (Palette, PaletteDark):
            colors = palette_class()
            qt_palette = build_palette(colors)
            with self.subTest(palette=palette_class.__name__):
                from PySide6.QtGui import QPalette
                with self.subTest(role="Base"):
                    self.assertEqual(qt_palette.color(QPalette.ColorRole.Base).name(),
                                     colors.SURFACE.lower())
                self.assertEqual(qt_palette.color(QPalette.ColorRole.Text).name(),
                                 colors.TEXT.lower(), "文字色必须跟着主题")
                self.assertEqual(qt_palette.color(QPalette.ColorRole.Highlight).name(),
                                 colors.PRIMARY.lower())

    def test_light_palette_is_white_on_dark_text(self):
        """用户明确要求: 浅色主题下这些列表要白底黑字。"""
        from PySide6.QtGui import QPalette

        from stellasora_toolkit.ui.theme import build_palette

        qt_palette = build_palette(Palette())
        base = qt_palette.color(QPalette.ColorRole.Base)
        text = qt_palette.color(QPalette.ColorRole.Text)
        self.assertEqual(base.name(), "#ffffff")
        self.assertLess(text.lightness(), 80, "浅底必须配深字")
        self.assertGreater(base.lightness(), 200, "浅色主题下底色要够亮")


if __name__ == "__main__":
    unittest.main()
