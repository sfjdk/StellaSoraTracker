"""日服适配测试。

关键点: 国际服与日服**共用** StellaSora.exe —— 进程名区分不出来, 所以
1. 只有一个 StellaSora.exe 在跑时不能被当成"两个客户端";
2. 检测逻辑要沿用设置页所选(没选过才退回国际服);
3. 语言参数必须是 lang=jp(实测 cn/en/jp/tw 有效, ja/ko/zh 会 404);
4. 卡池缓存按版本分文件, 切到日服不会读到国际服的缓存。
"""
import contextlib
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stellasora_toolkit import official_banners, server_config  # noqa: E402
from stellasora_toolkit.server_config import (  # noqa: E402
    CONFIG_FILENAME, SERVER_CN, SERVER_INTL, SERVER_JP, running_client_groups,
)
from stellasora_toolkit.service import detect_and_apply, probe_running_groups  # noqa: E402

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"


@contextlib.contextmanager
def temp_workdir(name: str):
    directory = TEMP_ROOT / f"jp_{name}"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _patch_running(names: list[str]):
    return mock.patch("stellasora_toolkit.service.running_processes",
                      return_value=[(name, 100) for name in names])


class ProfileTests(unittest.TestCase):
    def test_jp_profile_exists_with_jp_language(self):
        profile = server_config.PROFILES[SERVER_JP]
        self.assertEqual(profile.label, "日服")
        self.assertEqual(profile.api_lang, "jp")
        self.assertEqual(profile.client_names, ("StellaSora.exe",))

    def test_jp_shares_the_client_with_intl(self):
        self.assertEqual(server_config.PROFILES[SERVER_JP].client_names,
                         server_config.PROFILES[SERVER_INTL].client_names)

    def test_set_and_persist_jp(self):
        saved = server_config._active
        try:
            with temp_workdir("persist") as directory:
                self.assertTrue(server_config.set_active(SERVER_JP))
                path = directory / CONFIG_FILENAME
                self.assertTrue(server_config.save_key(path, SERVER_JP))
                self.assertEqual(server_config.load_key(path), SERVER_JP)
        finally:
            server_config._active = saved

    def test_env_and_cli_accept_jp(self):
        saved = server_config._active
        try:
            with mock.patch.dict("os.environ", {server_config.ENV_KEY: "jp"}):
                profile = server_config.init_from(None)
                self.assertEqual(profile.key, SERVER_JP)
        finally:
            server_config._active = saved

    def test_banner_cache_filename_is_per_server(self):
        saved = server_config._active
        try:
            server_config.set_active(SERVER_JP)
            self.assertEqual(official_banners.cache_filename(), "official_banners_jp.json")
            server_config.set_active(SERVER_INTL)
            self.assertEqual(official_banners.cache_filename(), "official_banners_intl.json")
        finally:
            server_config._active = saved


class RunningGroupTests(unittest.TestCase):
    def test_one_shared_client_is_a_single_group(self):
        self.assertEqual(running_client_groups(["StellaSora.exe"]), [[SERVER_INTL, SERVER_JP]])

    def test_cn_alone_is_one_group(self):
        self.assertEqual(running_client_groups(["xtlr.exe"]), [[SERVER_CN]])

    def test_two_clients_are_two_groups(self):
        groups = running_client_groups(["xtlr.exe", "StellaSora.exe"])
        self.assertEqual(len(groups), 2)
        self.assertIn([SERVER_CN], groups)
        self.assertIn([SERVER_INTL, SERVER_JP], groups)

    def test_no_client(self):
        self.assertEqual(running_client_groups(["notepad.exe"]), [])

    def test_probe_groups_counts_clients_not_versions(self):
        with _patch_running(["StellaSora.exe"]):
            self.assertEqual(len(probe_running_groups()), 1, "一个 StellaSora.exe 不能被算成两个客户端")


class DetectWithJpTests(unittest.TestCase):
    def setUp(self):
        self._saved = server_config._active

    def tearDown(self):
        server_config._active = self._saved

    def test_keeps_jp_when_it_is_already_selected(self):
        server_config.set_active(SERVER_JP)
        with _patch_running(["StellaSora.exe"]), temp_workdir("keep_jp") as directory:
            profile, note, keys = detect_and_apply(directory)
        self.assertEqual(profile.key, SERVER_JP)
        self.assertEqual(note, "")
        self.assertEqual(set(keys), {SERVER_INTL, SERVER_JP})

    def test_defaults_to_intl_and_tells_how_to_switch(self):
        server_config.set_active(SERVER_CN)
        with _patch_running(["StellaSora.exe"]), temp_workdir("default_intl") as directory:
            profile, note, _keys = detect_and_apply(directory)
            saved = server_config.load_key(directory / CONFIG_FILENAME)
        self.assertEqual(profile.key, SERVER_INTL)
        self.assertIn("日服", note, "要提示用户可以切日服")
        self.assertIn("设置页", note)
        self.assertEqual(saved, SERVER_INTL)

    def test_jp_selection_survives_next_detection(self):
        """设置页存下的「日服」不会被下一次自动检测覆盖(共用进程也不能乱切)。"""
        server_config.set_active(SERVER_JP)
        with _patch_running(["StellaSora.exe"]), temp_workdir("survive") as directory:
            path = directory / CONFIG_FILENAME
            server_config.save_key(path, SERVER_JP)          # 等价于设置页点「日服」
            profile, note, _keys = detect_and_apply(directory)
            saved = json.loads(path.read_text(encoding="utf-8"))
            via_init = server_config.init_from(directory)    # 下次启动读回
        self.assertEqual(profile.key, SERVER_JP)
        self.assertEqual(note, "")
        self.assertEqual(saved["server"], SERVER_JP)
        self.assertEqual(via_init.key, SERVER_JP)

    def test_cn_still_auto_switches(self):
        server_config.set_active(SERVER_INTL)
        with _patch_running(["xtlr.exe"]), temp_workdir("cn") as directory:
            profile, note, _keys = detect_and_apply(directory)
        self.assertEqual(profile.key, SERVER_CN)
        self.assertIn("自动检测到", note)

    def test_both_clients_keeps_active(self):
        server_config.set_active(SERVER_JP)
        with _patch_running(["xtlr.exe", "StellaSora.exe"]) as _patched:
            profile, note, keys = detect_and_apply(None)
        self.assertEqual(profile.key, SERVER_JP)
        self.assertIn("同时检测到", note)
        self.assertEqual(set(keys), {SERVER_CN, SERVER_INTL, SERVER_JP})


class LanguageApiTests(unittest.TestCase):
    def test_api_lang_follows_active_profile(self):
        saved = server_config._active
        try:
            for key, lang in ((SERVER_CN, "cn"), (SERVER_INTL, "en"), (SERVER_JP, "jp")):
                server_config.set_active(key)
                with self.subTest(key=key):
                    self.assertEqual(server_config.api_lang(), lang)
        finally:
            server_config._active = saved


if __name__ == "__main__":
    unittest.main()
