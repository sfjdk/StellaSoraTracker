import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from stellasora_toolkit import server_config
from stellasora_toolkit.server_config import (
    CONFIG_FILENAME, ENV_KEY, PROFILES, SERVER_CN, SERVER_INTL, SERVER_JP,
    active, init_from, load_key, save_key, set_active,
)


class ResolveRunningTests(unittest.TestCase):
    def setUp(self):
        self._saved = server_config._active
        set_active(SERVER_CN)

    def tearDown(self):
        server_config._active = self._saved

    def test_single_intl_client_auto_selected(self):
        """一个 StellaSora.exe = 一个客户端, 但它同时对应国际服与日服。

        没选过日服时按国际服兜底(保持老行为), 并把两个 key 都报出来。
        """
        profile, keys = server_config.resolve_running(["explorer.exe", "StellaSora.exe"])
        self.assertEqual(profile.key, SERVER_INTL)
        self.assertEqual(set(keys), {SERVER_INTL, SERVER_JP})

    def test_jp_selection_is_kept_when_that_client_runs(self):
        set_active(SERVER_JP)
        profile, keys = server_config.resolve_running(["StellaSora.exe"])
        self.assertEqual(profile.key, SERVER_JP, "选过日服就不要再被兜底成国际服")
        self.assertEqual(set(keys), {SERVER_INTL, SERVER_JP})

    def test_single_cn_client_auto_selected(self):
        profile, keys = server_config.resolve_running(["xtlr.exe"])
        self.assertEqual(profile.key, SERVER_CN)
        self.assertEqual(keys, [SERVER_CN])

    def test_both_running_needs_manual_choice(self):
        profile, keys = server_config.resolve_running(["xtlr.exe", "StellaSora.exe"])
        self.assertIsNone(profile)  # 两个客户端都在运行 -> 需手动选择
        # 国际服与日服共用 StellaSora.exe, 所以两个客户端对应三个版本
        self.assertEqual(set(keys), {SERVER_CN, SERVER_INTL, SERVER_JP})

    def test_no_client_running(self):
        profile, keys = server_config.resolve_running(["notepad.exe"])
        self.assertIsNone(profile)
        self.assertEqual(keys, [])


class ServerProfileTests(unittest.TestCase):
    def setUp(self):
        self._saved = server_config._active
        set_active(SERVER_CN)

    def tearDown(self):
        server_config._active = self._saved

    def test_profiles_have_distinct_client_names(self):
        self.assertEqual(PROFILES[SERVER_CN].client_names, ("xtlr.exe",))
        self.assertEqual(PROFILES[SERVER_INTL].client_names, ("StellaSora.exe",))
        self.assertEqual(PROFILES[SERVER_JP].client_names, ("StellaSora.exe",))  # 与国际服共用
        self.assertEqual(PROFILES[SERVER_CN].api_lang, "cn")
        self.assertEqual(PROFILES[SERVER_INTL].api_lang, "en")
        self.assertEqual(PROFILES[SERVER_JP].api_lang, "jp")

    def test_default_is_cn(self):
        self.assertEqual(active().key, SERVER_CN)

    def test_set_active_switches_and_rejects_unknown(self):
        self.assertTrue(set_active(SERVER_INTL))
        self.assertEqual(active().key, SERVER_INTL)
        self.assertEqual(server_config.api_lang(), "en")
        self.assertTrue(set_active(SERVER_JP))
        self.assertEqual(server_config.api_lang(), "jp")
        self.assertFalse(set_active("kr"))            # 不存在的版本保持原样
        self.assertEqual(active().key, SERVER_JP)

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / CONFIG_FILENAME
            self.assertTrue(save_key(path, SERVER_INTL))
            self.assertEqual(load_key(path), SERVER_INTL)
            self.assertEqual(load_key(path.parent / "missing.json"), None)  # 缺失 -> None
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_key(path), None)  # 损坏 -> None

    def test_save_key_rejects_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / CONFIG_FILENAME
            self.assertFalse(save_key(path, "kr"))

    def test_init_from_env_takes_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / CONFIG_FILENAME
            save_key(path, SERVER_INTL)
            with mock.patch.dict(os.environ, {ENV_KEY: SERVER_CN}, clear=False):
                init_from(Path(tmp))
            self.assertEqual(active().key, SERVER_CN)  # 环境变量覆盖 server.json

    def test_init_from_uses_file_then_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / CONFIG_FILENAME
            save_key(path, SERVER_INTL)
            init_from(Path(tmp))
            self.assertEqual(active().key, SERVER_INTL)
        with tempfile.TemporaryDirectory() as tmp:
            init_from(Path(tmp))  # 无配置文件 -> 默认国服
            self.assertEqual(active().key, SERVER_CN)


if __name__ == "__main__":
    unittest.main()
