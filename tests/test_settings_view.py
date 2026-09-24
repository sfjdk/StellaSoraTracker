"""SettingsView 的构建与版本切换按钮同步(回归: refresh_server_buttons 曾吞掉 build 的尾部代码)。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from PySide6.QtWidgets import QApplication

from stellasora_toolkit import server_config
from stellasora_toolkit.ui.views import SettingsView


def _view() -> SettingsView:
    return SettingsView({
        "open": lambda: None,
        "copy": lambda: None,
        "backup": lambda: None,
        "update": lambda: None,
        "server_changed": lambda key: None,
    })


class SettingsViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._saved = server_config._active
        server_config.set_active(server_config.SERVER_CN)

    def tearDown(self):
        server_config._active = self._saved

    def test_build_renders_all_sections_and_buttons(self):
        view = _view()
        view.build("C:/archive.json", "120 抽")
        # 每个版本(GameServer)必须在设置页有对应按钮, build 成功即注册
        self.assertEqual(set(view._server_buttons), set(server_config.PROFILES))
        self.assertTrue(hasattr(view, "_summary"))

    def test_build_is_idempotent(self):
        """重复调用 build 不残留旧卡(清空布局后重建, 不应保留重复的版本卡)。"""
        view = _view()
        view.build("C:/archive.json", "")
        view.build("C:/archive.json", "")
        self.assertEqual(len(view._server_buttons), len(server_config.PROFILES))

    def test_refresh_server_buttons_follows_active(self):
        """回归: 这曾在 refresh_server_buttons 中触发 NameError(archive_path 不在作用域)。"""
        view = _view()
        view.build("C:/archive.json", "")
        server_config.set_active(server_config.SERVER_INTL)
        view.refresh_server_buttons()  # 不应抛 NameError
        self.assertTrue(view._server_buttons[server_config.SERVER_INTL].isChecked())
        self.assertFalse(view._server_buttons[server_config.SERVER_CN].isChecked())

    def test_set_summary_still_works(self):
        """build 未被切开: set_summary 使用的 _summary 必须存在。"""
        view = _view()
        view.build("C:/archive.json", "旧摘要")
        view.set_summary("新摘要")
        self.assertEqual(view._summary.text(), "新摘要")


if __name__ == "__main__":
    unittest.main()
