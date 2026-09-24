import unittest

from stellasora_toolkit.exporter import sanitize_emblems, sanitize_gacha, sanitize_gacha_categories


class ExporterTests(unittest.TestCase):
    def test_sanitize_gacha_drops_unrelated_fields(self):
        result = sanitize_gacha({1: {"Gid": 10, "Time": 20, "Ids": [1, 2], "account": "x"}})
        self.assertEqual(result, [{"Gid": 10, "Ids": [1, 2], "Time": 20}])

    def test_sanitize_gacha_unwraps_nested_history_lists(self):
        raw = [[{"Gid": 10, "Time": 20, "Ids": [1, 2]}]]
        self.assertEqual(sanitize_gacha(raw)[0]["Ids"], [1, 2])

    def test_sanitize_gacha_keeps_categories(self):
        raw = [[{"Gid": 10, "Time": 20, "Ids": [1]}], [{"Gid": 20, "Time": 21, "Ids": [2]}]]
        result = sanitize_gacha_categories(raw)
        self.assertEqual(sorted(result), [1, 2])
        self.assertEqual(result[2][0]["Gid"], 20)

    def test_sanitize_nested_emblems(self):
        raw = {132: {3: [{"nCharId": 132, "nGemId": 301, "sName": "test", "secret": 1}]}}
        result = sanitize_emblems(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["nGemId"], 301)
        self.assertNotIn("secret", result[0])


if __name__ == "__main__":
    unittest.main()
