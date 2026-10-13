"""客户端语言识别测试(国际服/日服共用 StellaSora.exe, 只能看内存里的文本)。

用合成内存: 把某种语言的角色名写进去, 检测就应该报出那种语言。
"""
import contextlib
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stellasora_toolkit import catalog_sync, server_config  # noqa: E402
from stellasora_toolkit.catalog import DISC_NAMES, TRAVELER_NAMES  # noqa: E402
from stellasora_toolkit.client_lang import (  # noqa: E402
    LANG_MARKERS, LANG_TO_SERVER, detect_language,
)
from test_account_uid import LuaImage  # noqa: E402

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"


@contextlib.contextmanager
def temp_workdir(name: str):
    directory = TEMP_ROOT / f"lang_{name}"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class LanguageDetectionTests(unittest.TestCase):
    @staticmethod
    def _image_with(text: str) -> LuaImage:
        image = LuaImage()
        image.process.data[0x2000:0x2000 + len(text)] = text.encode("utf-8")
        return image

    def test_detects_cjk_languages_from_one_marker(self):
        """中日文标记判定力强: 假名/汉字不会出现在别的语言客户端里, 命中一个即可。"""
        for lang in ("cn", "jp"):
            with self.subTest(lang=lang):
                image = self._image_with(LANG_MARKERS[lang][0])
                detected, marker = detect_language(image.discovery)
                self.assertEqual(detected, lang)
                self.assertEqual(marker, LANG_MARKERS[lang][0])

    def test_english_needs_two_markers(self):
        """英文名是纯 ASCII, 资源文件名里也可能有 —— 只命中一个不算证据。"""
        one = self._image_with(LANG_MARKERS["en"][0])
        self.assertEqual(detect_language(one.discovery), ("", ""),
                         "一个英文名可能只是资源文件名, 不该据此判定国际服")
        two = self._image_with(LANG_MARKERS["en"][0] + "|" + LANG_MARKERS["en"][1])
        self.assertEqual(detect_language(two.discovery)[0], "en")

    def test_cjk_evidence_beats_english(self):
        """英文串到处都有, 但真出现假名时一定是日服。"""
        image = self._image_with(LANG_MARKERS["en"][0] + "|" + LANG_MARKERS["en"][1]
                                 + "|" + LANG_MARKERS["jp"][0])
        self.assertEqual(detect_language(image.discovery)[0], "jp")

    def test_pinned_language_is_checked_first(self):
        """内存里同时有中日文本时, 当前设置的语言优先(省一遍扫描也更符合预期)。"""
        image = self._image_with(LANG_MARKERS["cn"][0] + "|" + LANG_MARKERS["jp"][0])
        detected, _marker = detect_language(image.discovery, pinned="jp")
        self.assertEqual(detected, "jp")
        detected_cn, _marker = detect_language(image.discovery, pinned="cn")
        self.assertEqual(detected_cn, "cn")

    def test_unknown_when_no_marker_present(self):
        image = LuaImage()
        detected, marker = detect_language(image.discovery)
        self.assertEqual((detected, marker), ("", ""))

    def test_deadline_stops_the_search(self):
        image = LuaImage()
        detected, marker = detect_language(image.discovery, deadline=0.0)   # 已经过期
        self.assertEqual((detected, marker), ("", ""))

    def test_language_maps_to_server_profiles(self):
        for lang, key in LANG_TO_SERVER.items():
            with self.subTest(lang=lang):
                self.assertIn(key, server_config.PROFILES)
                self.assertEqual(server_config.PROFILES[key].api_lang, lang)


class AllRarityRegistrationTests(unittest.TestCase):
    """四星名称也要按当前语言注册, 否则切到日服后四星记录还是中文。"""

    _FETCHED = [
        {"id": 161, "kind": "traveler", "name": "Brand New", "icon": "/stella/assets/a.png",
         "rarity": 5, "five_star": True},
        {"id": 103, "kind": "traveler", "name": "Amber", "icon": "/stella/assets/b.png",
         "rarity": 4, "five_star": False},
        {"id": 214999, "kind": "disc", "name": "Meowing Cat God", "icon": "/stella/assets/c.png",
         "rarity": 5, "five_star": True},
        {"id": 211001, "kind": "disc", "name": "Morning Mist", "icon": "/stella/assets/d.png",
         "rarity": 3, "five_star": False},
    ]

    def setUp(self):
        self._saved = {
            item_id: (kind, (TRAVELER_NAMES if kind == "traveler" else DISC_NAMES).get(item_id))
            for item_id, kind in ((161, "traveler"), (103, "traveler"),
                                  (214999, "disc"), (211001, "disc"))
        }

    def tearDown(self):
        for item_id, (kind, original) in self._saved.items():
            table = TRAVELER_NAMES if kind == "traveler" else DISC_NAMES
            if original is None:
                table.pop(item_id, None)
            else:
                table[item_id] = original

    def _sync(self, directory: Path):
        """asset_root 指到临时目录: 否则真 assets 里已有头像是"已有", 不是"新下载"。"""
        assets = directory / "assets"
        with mock.patch.object(catalog_sync, "_fetch_five_star_catalog",
                               return_value=[dict(it) for it in self._FETCHED]), \
                mock.patch.object(catalog_sync, "asset_root", return_value=assets), \
                mock.patch.object(catalog_sync, "_download_icon", return_value=True):
            return catalog_sync.sync_with_report(directory / "catalog_sync_state.json")

    def test_four_star_names_are_registered_too(self):
        with temp_workdir("all_rarity") as directory:
            report = self._sync(directory)
        self.assertEqual(TRAVELER_NAMES[103], "Amber", "四星旅人也该换成当前语言的名称")
        self.assertEqual(DISC_NAMES[211001], "Morning Mist", "三星秘纹同理")
        self.assertEqual(TRAVELER_NAMES[161], "Brand New")
        self.assertEqual(DISC_NAMES[214999], "Meowing Cat God")
        # 头像只补五星: 四星不该出现在下载/失败列表里
        self.assertEqual({item["id"] for item in report["downloaded"]}, {161, 214999})
        # 报告里的"目录规模"仍按五星统计
        self.assertEqual(report["fetched_total"], 2)
        self.assertEqual(report["named_total"], 4)
        # 对齐校验只针对五星, 四星不该被算成"星级错位"
        self.assertEqual(report["audit_after"]["misjudged"], [])

    def test_appeared_only_reports_five_stars(self):
        with temp_workdir("appeared") as directory:
            assets = directory / "assets"
            with mock.patch.object(catalog_sync, "_fetch_five_star_catalog",
                                   return_value=[dict(it) for it in self._FETCHED]), \
                    mock.patch.object(catalog_sync, "asset_root", return_value=assets), \
                    mock.patch.object(catalog_sync, "_download_icon", return_value=True):
                appeared, _downloaded = catalog_sync.sync_catalog(
                    directory / "catalog_sync_state.json")
        self.assertEqual({item["id"] for item in appeared}, {161, 214999},
                         "「发现新五星」提示不该报四星")


class ManualPinTests(unittest.TestCase):
    """用户手动点选过版本后, 自动识别不能覆盖 —— 否则"点了日服又被切回国际服"。"""

    def test_auto_mode_switches(self):
        key, note = server_config.resolve_detected("intl", "jp", manual=False)
        self.assertEqual(key, "jp")
        self.assertIn("已自动切换", note)

    def test_manual_pin_is_kept(self):
        key, note = server_config.resolve_detected("jp", "en", manual=True)
        self.assertEqual(key, "jp", "手动指定过就必须保持")
        self.assertIn("手动指定", note)
        self.assertIn("自动识别", note)

    def test_same_language_is_silent(self):
        self.assertEqual(server_config.resolve_detected("jp", "jp", manual=False), ("jp", ""))
        self.assertEqual(server_config.resolve_detected("jp", "jp", manual=True), ("jp", ""))

    def test_unknown_detection_changes_nothing(self):
        self.assertEqual(server_config.resolve_detected("jp", "", manual=False), ("jp", ""))
        self.assertEqual(server_config.resolve_detected("jp", "kr", manual=True), ("jp", ""))

    def test_manual_flag_roundtrips_in_server_json(self):
        with temp_workdir("pin") as directory:
            path = server_config.config_path(directory)
            self.assertTrue(server_config.save_key(path, "jp"))                 # 点选 = 手动
            self.assertEqual(server_config.load_key(path), "jp")
            self.assertTrue(server_config.load_manual(path))
            self.assertTrue(server_config.save_key(path, "intl", manual=False))  # 自动识别写回
            self.assertFalse(server_config.load_manual(path))
            self.assertEqual(server_config.load_key(path), "intl")
            # 老文件(只有 server 字段)当作手动, 保持既有行为
            path.write_text('{"server": "jp"}', encoding="utf-8")
            self.assertFalse(server_config.load_manual(path))


if __name__ == "__main__":
    unittest.main()
