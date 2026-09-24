import tempfile
import unittest
from pathlib import Path
from unittest import mock

from stellasora_toolkit import server_config
from stellasora_toolkit.server_config import CONFIG_FILENAME, SERVER_CN, SERVER_INTL
from stellasora_toolkit.service import detect_and_apply


def _patch_running(names: list[str]):
    return mock.patch(
        "stellasora_toolkit.service.running_processes",
        return_value=[(name, 100) for name in names],
    )


class DetectAndApplyTests(unittest.TestCase):
    def setUp(self):
        self._saved = server_config._active
        server_config.set_active(SERVER_CN)

    def tearDown(self):
        server_config._active = self._saved

    def test_auto_switches_to_single_running_client_and_persists(self):
        with _patch_running(["StellaSora.exe"]), tempfile.TemporaryDirectory() as tmp:
            profile, note, keys = detect_and_apply(Path(tmp))
            self.assertEqual(profile.key, SERVER_INTL)
            self.assertIn("自动检测到", note)
            self.assertIn("StellaSora.exe", note)
            self.assertEqual(keys, [SERVER_INTL])
            saved = server_config.load_key(Path(tmp) / CONFIG_FILENAME)
            self.assertEqual(saved, SERVER_INTL)  # 自动切换同步持久化

    def test_persists_switched_server_json(self):
        with _patch_running(["StellaSora.exe"]), tempfile.TemporaryDirectory() as tmp:
            detect_and_apply(Path(tmp))
            import json
            payload = json.loads((Path(tmp) / CONFIG_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(payload["server"], SERVER_INTL)

    def test_no_note_when_active_already_matches(self):
        with _patch_running(["xtlr.exe"]):
            profile, note, _keys = detect_and_apply(None)
        self.assertEqual(profile.key, SERVER_CN)
        self.assertEqual(note, "")

    def test_both_running_keeps_active_and_hints_choice(self):
        with _patch_running(["xtlr.exe", "StellaSora.exe"]):
            profile, note, keys = detect_and_apply(None)
        self.assertEqual(profile.key, SERVER_CN)  # 保持设置页所选/--server 指定
        self.assertIn("同时检测到", note)
        self.assertIn("读取", note)
        self.assertEqual(set(keys), {SERVER_CN, SERVER_INTL})

    def test_no_client_running_silent(self):
        with _patch_running(["notepad.exe"]):
            profile, note, keys = detect_and_apply(None)
        self.assertEqual(profile.key, SERVER_CN)
        self.assertEqual(note, "")
        self.assertEqual(keys, [])


if __name__ == "__main__":
    unittest.main()
