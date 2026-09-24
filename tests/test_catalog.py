import unittest

from stellasora_toolkit.catalog import (
    DISC_NAMES,
    FIVE_STAR_DISCS,
    FIVE_STAR_ITEMS,
    format_attr_value,
    gacha_item_name,
    is_five_star_item,
    register_gacha_resource,
    traveler_name,
)


class CatalogTests(unittest.TestCase):
    def test_known_traveler_name(self):
        self.assertEqual(traveler_name(142), "珂赛特")
        self.assertEqual(gacha_item_name(142), "珂赛特")
        self.assertEqual(gacha_item_name(157), "花铃")

    def test_unknown_item_stays_identifiable(self):
        self.assertEqual(gacha_item_name(999999), "物品 #999999")

    def test_disc_ids_resolve_to_catalog_names(self):
        self.assertEqual(gacha_item_name(211002), "和煦")
        self.assertEqual(gacha_item_name(213026), "清扫时间DA♥YO")
        self.assertEqual(gacha_item_name(214057), "伴我航行")

    def test_registers_downloaded_five_star_disc(self):
        item_id = 299999
        try:
            register_gacha_resource(item_id, "disc", "测试秘纹")
            self.assertEqual(DISC_NAMES[item_id], "测试秘纹")
            self.assertEqual(FIVE_STAR_DISCS[item_id], "测试秘纹")
            self.assertIn(item_id, FIVE_STAR_ITEMS)
        finally:
            DISC_NAMES.pop(item_id, None)
            FIVE_STAR_DISCS.pop(item_id, None)
            FIVE_STAR_ITEMS.discard(item_id)

    def test_small_float_is_formatted_as_percent(self):
        self.assertEqual(format_attr_value(0.063), "6.3%")

    def test_forward_compatible_new_five_star_ids(self):
        self.assertTrue(is_five_star_item(161))
        self.assertTrue(is_five_star_item(214999))
        self.assertFalse(is_five_star_item(150))
        self.assertEqual(gacha_item_name(161), "旅人 #161")
        self.assertEqual(gacha_item_name(214999), "秘纹 #214999")


if __name__ == "__main__":
    unittest.main()
