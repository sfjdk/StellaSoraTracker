import unittest

from stellasora_toolkit.catalog import same_item_name
from stellasora_toolkit.gacha_stats import FiveStarPull, PoolStats
from stellasora_toolkit.ui.views import _pity_color, _up_average


class GuiTests(unittest.TestCase):
    def test_up_name_comparison_normalizes_parentheses_and_spaces(self):
        self.assertTrue(same_item_name("薇洛（盛夏）", "薇洛(盛夏)"))
        self.assertFalse(same_item_name("归途", "鹿鸣"))

    def test_pity_colors_use_green_yellow_and_red_ranges(self):
        self.assertEqual(_pity_color(30), "#2e9e6b")
        self.assertEqual(_pity_color(31), "#d9a62a")
        self.assertEqual(_pity_color(61), "#c1503d")

    def test_limited_pool_up_average_ignores_off_banner_five_stars(self):
        pool = PoolStats(
            gid=0,
            total_pulls=240,
            start_time=0,
            end_time=0,
            five_stars=(
                FiveStarPull(133, "traveler", "夏花", 80, 0, 80, 11133),
                FiveStarPull(110, "traveler", "安可", 70, 0, 150, 11133),
                FiveStarPull(133, "traveler", "夏花", 90, 0, 240, 11133),
            ),
        )
        self.assertEqual(_up_average(pool), 120)

    def test_limited_pool_without_up_has_no_up_average(self):
        pool = PoolStats(
            gid=0,
            total_pulls=80,
            start_time=0,
            end_time=0,
            five_stars=(FiveStarPull(110, "traveler", "安可", 80, 0, 80, 11133),),
        )
        self.assertIsNone(_up_average(pool))


if __name__ == "__main__":
    unittest.main()
