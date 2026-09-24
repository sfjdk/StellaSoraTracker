import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from stellasora_toolkit import server_config
from stellasora_toolkit.server_config import (
    CONFIG_FILENAME, ENV_KEY, PROFILES, SERVER_CN, SERVER_INTL,
    active, init_from, load_key, save_key, set_active,
)


class ResolveRunningTests(unittest.TestCase):
    def setUp(self):
        self._saved = server_config._active
        set_active(SERVER_CN)

    def tearDown(self):
        server_config._active = self._saved

    def test_single_intl_client_auto_selected(self):
        profile, keys = server_config.resolve_running(["explorer.exe", "StellaSora.exe"])
        self.assertEqual(profile.key, SERVER_INTL)
        self.assertEqual(keys, [SERVER_INTL])

    def test_single_cn_client_auto_selected(self):
        profile, keys = server_config.resolve_running(["xtlr.exe"])
        self.assertEqual(profile.key, SERVER_CN)
        self.assertEqual(keys, [SERVER_CN])

    def test_both_running_needs_manual_choice(self):
        profile, keys = server_config.resolve_running(["xtlr.exe", "StellaSora.exe"])
        self.assertIsNone(profile)  # 两个都在运行 -> 需手动选择
        self.assertEqual(set(keys), {SERVER_CN, SERVER_INTL})

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
        self.assertEqual(PROFILES[SERVER_CN].api_lang, "cn")
        self.assertEqual(PROFILES[SERVER_INTL].api_lang, "en")

    def test_default_is_cn(self):
        self.assertEqual(active().key, SERVER_CN)

    def test_set_active_switches_and_rejects_unknown(self):
        self.assertTrue(set_active(SERVER_INTL))
        self.assertEqual(active().key, SERVER_INTL)
        self.assertEqual(server_config.api_lang(), "en")
        self.assertFalse(set_active("jp"))
        self.assertEqual(active().key, SERVER_INTL)  # 非法 key 保持原样

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
            self.assertFalse(save_key(path, "jp"))

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
