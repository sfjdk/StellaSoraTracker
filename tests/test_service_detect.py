import contextlib
import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from stellasora_toolkit import server_config
from stellasora_toolkit.server_config import CONFIG_FILENAME, SERVER_CN, SERVER_INTL, SERVER_JP
from stellasora_toolkit.service import detect_and_apply

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"


@contextlib.contextmanager
def temp_workdir(name: str):
    """见 tests/test_import_format.py: tempfile 建的 0o700 目录在受限沙箱里读写/清理都会被拒。"""
    directory = TEMP_ROOT / f"detect_{name}"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


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
        with _patch_running(["StellaSora.exe"]), temp_workdir("single") as tmp:
            profile, note, keys = detect_and_apply(tmp)
            self.assertEqual(profile.key, SERVER_INTL)
            self.assertIn("StellaSora.exe", note)
            self.assertIn("日服", note)          # 提示可以在设置页切日服
            # 国际服与日服共用 StellaSora.exe: 匹配到的是两个 key(同一个客户端)
            self.assertEqual(set(keys), {SERVER_INTL, SERVER_JP})
            saved = server_config.load_key(tmp / CONFIG_FILENAME)
            self.assertEqual(saved, SERVER_INTL)  # 自动切换同步持久化

    def test_persists_switched_server_json(self):
        with _patch_running(["StellaSora.exe"]), temp_workdir("persist") as tmp:
            detect_and_apply(tmp)
            payload = json.loads((tmp / CONFIG_FILENAME).read_text(encoding="utf-8"))
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
        self.assertEqual(set(keys), {SERVER_CN, SERVER_INTL, SERVER_JP})

    def test_no_client_running_silent(self):
        with _patch_running(["notepad.exe"]):
            profile, note, keys = detect_and_apply(None)
        self.assertEqual(profile.key, SERVER_CN)
        self.assertEqual(note, "")
        self.assertEqual(keys, [])


if __name__ == "__main__":
    unittest.main()
