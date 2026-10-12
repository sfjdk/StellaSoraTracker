"""目录(catalog)与随版本打包的资源/官方快照是否一致。

背景: assets/travelers/137.png 早就随版本打包了, 但静态名称表漏登记 137 埃莉诺 ——
抽到它时界面显示 "物品 #137", 而且 is_five_star_item() 返回 False, 五星记录/概率/
垫抽全部算错。139 艾蕾(带天井池 10139)同样是这个错。

这类"图片资源在、名称表不在"的错位必须能**离线**发现, 不能指望联网同步兜底,
所以这里直接用随包资源与 tools/stellabase_cache 的官方快照做对齐校验。
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from stellasora_toolkit import catalog_sync
from stellasora_toolkit.catalog import (
    DISC_NAMES,
    FIVE_STAR_TRAVELERS,
    TRAVELER_NAMES,
    gacha_item_kind,
    gacha_item_name,
    is_five_star_item,
    is_gacha_item,
)

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SNAPSHOT = ROOT / "tools" / "stellabase_cache"


def png_ids(folder: str) -> list[int]:
    return sorted(int(path.stem) for path in (ASSETS / folder).glob("*.png"))


class BundledResourceTests(unittest.TestCase):
    def test_every_bundled_traveler_icon_has_a_five_star_name(self):
        for item_id in png_ids("travelers"):
            with self.subTest(item_id=item_id):
                self.assertIn(item_id, TRAVELER_NAMES,
                              f"assets/travelers/{item_id}.png 没有名称, 抽到时只会显示 物品 #{item_id}")
                self.assertIn(item_id, FIVE_STAR_TRAVELERS)
                self.assertTrue(is_five_star_item(item_id))
                self.assertEqual(gacha_item_kind(item_id), "traveler")

    def test_every_bundled_disc_icon_has_a_name(self):
        for item_id in png_ids("discs"):
            with self.subTest(item_id=item_id):
                self.assertIn(item_id, DISC_NAMES,
                              f"assets/discs/{item_id}.png 没有名称, 抽到时只会显示 秘纹 #{item_id}")
                self.assertTrue(is_five_star_item(item_id))
                self.assertEqual(gacha_item_kind(item_id), "disc")

    def test_bundled_icons_are_not_empty(self):
        for folder in ("travelers", "discs"):
            for path in (ASSETS / folder).glob("*.png"):
                with self.subTest(path=path.name):
                    self.assertGreater(path.stat().st_size, 0)


class OfficialSnapshotTests(unittest.TestCase):
    """tools/stellabase_cache 是从 StellaBase 抓下来的官方快照, 必须被目录完整覆盖。"""

    def _snapshot(self, name: str) -> list[dict]:
        return json.loads((SNAPSHOT / name).read_text(encoding="utf-8"))

    def test_snapshot_travelers_are_registered(self):
        for row in self._snapshot("travelers.json"):
            item_id = int(row["id"])
            with self.subTest(item_id=item_id):
                self.assertEqual(TRAVELER_NAMES.get(item_id), row["name"])
                if int(row.get("grade") or 0) >= 5:
                    self.assertTrue(is_five_star_item(item_id))

    def test_snapshot_discs_are_registered(self):
        for row in self._snapshot("discs.json"):
            item_id = int(row["id"])
            with self.subTest(item_id=item_id):
                self.assertEqual(DISC_NAMES.get(item_id), row["name"])
                if int(row.get("star") or 0) >= 5:
                    self.assertTrue(is_five_star_item(item_id))


class ResourceManifestTests(unittest.TestCase):
    """发布清单带着每个 id 的名称, 与目录不一致说明打出来的包会显示错名字。"""

    def test_manifest_items_match_catalog(self):
        manifest = json.loads((ROOT / "resource_manifest.json").read_text(encoding="utf-8"))
        for item in manifest["items"]:
            item_id, kind = int(item["id"]), str(item["kind"])
            if "name" not in item:
                continue
            with self.subTest(item_id=item_id):
                table = TRAVELER_NAMES if kind == "traveler" else DISC_NAMES
                self.assertEqual(table.get(item_id), item["name"])
                if int(item.get("rarity") or 0) >= 5:
                    self.assertTrue(is_five_star_item(item_id))


class KnownFiveStarRegressionTests(unittest.TestCase):
    def test_newly_released_five_stars_are_known(self):
        # 137 埃莉诺 / 139 艾蕾: 2026-09 之后的限时五星, 曾经全部漏登记
        self.assertEqual(gacha_item_name(137), "埃莉诺")
        self.assertEqual(gacha_item_name(139), "艾蕾")
        for item_id in (137, 139):
            self.assertTrue(is_five_star_item(item_id))
            self.assertEqual(gacha_item_kind(item_id), "traveler")

    def test_newly_released_five_star_discs_are_known(self):
        expected = {
            214058: "夏日进行曲",
            214059: "飞吧，笼中鸟",
            214060: "荣誉时刻",
            214061: "睡前童话",
            214062: "美好，尽在昨日",
        }
        for item_id, name in expected.items():
            with self.subTest(item_id=item_id):
                self.assertEqual(gacha_item_name(item_id), name)
                self.assertTrue(is_five_star_item(item_id))
                self.assertEqual(gacha_item_kind(item_id), "disc")

    def test_boss_units_are_not_gacha_five_stars(self):
        # 魔侍巨像在角色接口里是 grade=5, 但抽不到: 不能进抽卡目录, 也不该被同步注册
        for item_id in (997, 998, 999):
            with self.subTest(item_id=item_id):
                self.assertFalse(is_gacha_item(item_id))
                self.assertFalse(is_five_star_item(item_id))


class SyncCatalogFilterTests(unittest.TestCase):
    """联网同步的过滤口径(离线, 直接喂假响应)。"""

    def test_sync_keeps_gacha_five_stars_and_drops_boss_units(self):
        payloads = {
            "characters?lang=cn": [
                {"id": 137, "name": "埃莉诺", "grade": 5, "icon": "/stella/assets/Eleanor.png"},
                {"id": 139, "name": "艾蕾", "grade": 5, "icon": "/stella/assets/Eileen.png"},
                {"id": 999, "name": "魔侍巨像", "grade": 5, "icon": "/stella/assets/Spellbound_Golem.png"},
                {"id": 103, "name": "琥珀", "grade": 4, "icon": "/stella/assets/Amber.png"},
            ],
            "discs?lang=cn": [
                {"id": 214062, "name": "美好，尽在昨日", "star": 5, "icon": "/stella/assets/outfit_4062_b.png"},
                {"id": 213026, "name": "清扫时间DA♥YO", "star": 4, "icon": "/stella/assets/outfit_3026_b.png"},
            ],
        }

        def fake_read(url, progress=None, timeout=20.0):
            for suffix, rows in payloads.items():
                if url.endswith(suffix):
                    return json.dumps(rows).encode("utf-8")
            return b""

        with mock.patch.object(catalog_sync, "_read_url", fake_read):
            items = catalog_sync._fetch_five_star_catalog()

        self.assertEqual({item["id"] for item in items}, {137, 139, 214062})
        self.assertTrue(all(item["icon"].startswith("/stella/assets/") for item in items))


if __name__ == "__main__":
    unittest.main()
