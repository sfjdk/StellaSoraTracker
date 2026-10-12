"""UID 查询器的性能/快速通道路径测试(沿用合成 Lua 内存镜像, 不需要真游戏)。"""
import contextlib
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stellasora_toolkit.account_uid import find_account_uid  # noqa: E402
from stellasora_toolkit.discovery import LuaTableDiscovery  # noqa: E402
from stellasora_toolkit.service import (  # noqa: E402
    load_manual_uid, load_uid_field, save_manual_uid, save_uid_field,
)
from test_account_uid import LuaImage  # noqa: E402

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"


@contextlib.contextmanager
def temp_workdir(name: str):
    directory = TEMP_ROOT / f"uid_fast_{name}"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class HeaderCacheTests(unittest.TestCase):
    def test_table_header_scan_is_cached_per_discovery(self):
        image = LuaImage()
        image.table({"_uid": "100872990"})
        calls = {"n": 0}
        original = image.process.regions

        def counting_regions():
            calls["n"] += 1
            return original()

        image.process.regions = counting_regions
        discovery = LuaTableDiscovery(image.process, image.lua)

        discovery._scan_table_headers()
        discovery._scan_table_headers()
        discovery._scan_table_headers()
        self.assertEqual(calls["n"], 1, "表头扫描(最贵的一步)只该真扫一次")

    def test_find_uid_candidates_reuses_the_cache(self):
        image = LuaImage()
        image.table({"_uid": "100872990"})
        calls = {"n": 0}
        original = image.process.regions
        image.process.regions = lambda: (calls.__setitem__("n", calls["n"] + 1), original())[1]
        discovery = LuaTableDiscovery(image.process, image.lua)

        discovery.find_uid_candidates(lambda v: True)
        discovery.find_uid_candidates(lambda v: True, names=["_uid"])
        self.assertEqual(calls["n"], 1)


class FastPathTests(unittest.TestCase):
    def test_hint_hits_without_the_broad_scan(self):
        image = LuaImage()
        image.table({"_roleId": "100872990"})
        discovery = image.discovery

        def explode(*_args, **_kwargs):
            raise AssertionError("有字段提示且命中时不该再做全量扫描")

        original = discovery._uid_like_string_objects
        discovery._uid_like_string_objects = explode      # 只允许快速通道被用到
        try:
            result = find_account_uid(discovery, preferred="100872990", field_hint="_roleId")
        finally:
            discovery._uid_like_string_objects = original

        self.assertTrue(result.found)
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.field_name, "_roleId")

    def test_wrong_hint_falls_back_to_broad_scan(self):
        image = LuaImage()
        image.table({"_uid": "100872990"})
        result = find_account_uid(image.discovery, field_hint="_nope")
        self.assertTrue(result.found)
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.field_name, "_uid")

    def test_hint_value_must_match_the_expected_uid(self):
        image = LuaImage()
        image.table({"_roleId": "555000111"})
        # 提示字段存在, 但值不是我们已知的那个 → 不能采信, 退回全量扫描
        result = find_account_uid(image.discovery, preferred="100872990", field_hint="_roleId")
        self.assertFalse(result.found)

    def test_hint_without_preference_is_accepted(self):
        image = LuaImage()
        image.table({"_gameUid": 100872990})
        result = find_account_uid(image.discovery, field_hint="_gameUid")
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.field_name, "_gameUid")


class LearnedFieldPersistenceTests(unittest.TestCase):
    def test_field_round_trips_and_keeps_manual_uid(self):
        with temp_workdir("roundtrip") as directory:
            self.assertTrue(save_manual_uid(directory, "100872990"))
            self.assertTrue(save_uid_field(directory, "_roleId"))
            self.assertEqual(load_manual_uid(directory), "100872990")
            self.assertEqual(load_uid_field(directory), "_roleId")

            # 之后再改手填 UID 不能把学到的字段名冲掉
            self.assertTrue(save_manual_uid(directory, "111222333"))
            self.assertEqual(load_uid_field(directory), "_roleId")
            # 再存字段名也不能把 UID 冲掉
            self.assertTrue(save_uid_field(directory, "_uid"))
            self.assertEqual(load_manual_uid(directory), "111222333")

    def test_broken_or_silly_field_names_are_rejected(self):
        with temp_workdir("reject") as directory:
            for bad in ("", "   ", "a/b", "x" * 40, "has space"):
                with self.subTest(bad=bad):
                    self.assertFalse(save_uid_field(directory, bad))
            self.assertEqual(load_uid_field(directory), "")

            (directory / "uid.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(load_uid_field(directory), "")
            self.assertEqual(load_manual_uid(directory), "")


if __name__ == "__main__":
    unittest.main()
