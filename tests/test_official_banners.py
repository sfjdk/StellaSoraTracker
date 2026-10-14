import io
import json
import unittest
from unittest import mock

from stellasora_toolkit import server_config
from stellasora_toolkit.official_banners import (
    cache_filename, fetch_banners, parse_banners,
)


def _fake_response(payload: dict) -> mock.MagicMock:
    body = json.dumps(payload).encode("utf-8")
    response = mock.MagicMock()
    response.__enter__ = mock.MagicMock(return_value=response)
    response.__exit__ = mock.MagicMock(return_value=False)
    response.read.return_value = body
    return response


class ParseBannersTests(unittest.TestCase):
    def test_cn_limited_banner_kept_with_up_name(self):
        banners = [{
            "id": 10140, "name": "完美无缺的最终解", "bannerType": "限时旅人招募",
            "startTime": "2026-06-02T12:00:00+08:00", "endTime": "2026-06-23T10:59:59+08:00",
            "rateUp": {"fiveStar": {"entries": [{"id": 140, "name": "斯帕克拉"}]}},
        }]
        parsed = parse_banners(banners)
        self.assertIn(10140, parsed)
        self.assertEqual(parsed[10140], ("完美无缺的最终解", "2026-06-02", "2026-06-23", "斯帕克拉"))

    def test_cn_permanent_banner_filtered(self):
        banners = [{"id": 1, "name": "常驻招募", "bannerType": "常驻招募"}]
        self.assertEqual(parse_banners(banners), {})

    def test_en_permanent_banner_filtered(self):
        """国际服文案是英文: Permanent ... Banner 也要按常驻过滤, 与国服行为一致。"""
        banners = [
            {"id": 10137, "name": "With Graceful Steps", "bannerType": "Limited Trekker Banner",
             "rateUp": {"fiveStar": {"entries": [{"id": 137, "name": "Eleanor"}]}}},
            {"id": 1, "name": "Standard", "bannerType": "Permanent Trekker Banner"},
        ]
        parsed = parse_banners(banners)
        self.assertIn(10137, parsed)
        self.assertEqual(parsed[10137][3], "Eleanor")
        self.assertNotIn(1, parsed)

    def test_invalid_rows_skipped(self):
        banners = [{"name": "no id"}, {"id": "abc"}, None, {"id": 42}]
        self.assertEqual(set(parse_banners(banners)), {42})


class CacheFilenameTests(unittest.TestCase):
    def setUp(self):
        self._saved = server_config._active
        server_config.set_active(server_config.SERVER_CN)

    def tearDown(self):
        server_config._active = self._saved

    def test_cache_filename_follows_active_server(self):
        self.assertEqual(cache_filename(), "official_banners_cn.json")
        server_config.set_active(server_config.SERVER_INTL)
        self.assertEqual(cache_filename(), "official_banners_intl.json")


class FetchBannersTests(unittest.TestCase):
    def setUp(self):
        self._saved = server_config._active
        server_config.set_active(server_config.SERVER_CN)

    def tearDown(self):
        server_config._active = self._saved

    def test_url_uses_active_lang(self):
        """fetch_banners 拼出的 URL 必须带当前版本对应的 lang 参数。"""
        captured: dict = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            return _fake_response({"current": [], "upcoming": [], "ended": []})

        with mock.patch("stellasora_toolkit.official_banners.urlopen", fake_urlopen):
            fetch_banners()
        self.assertEqual(captured["url"], "https://stella.ennead.cc/api/stella/banners?lang=cn")
        server_config.set_active(server_config.SERVER_INTL)
        with mock.patch("stellasora_toolkit.official_banners.urlopen", fake_urlopen):
            fetch_banners()
        self.assertEqual(captured["url"], "https://stella.ennead.cc/api/stella/banners?lang=en")


if __name__ == "__main__":
    unittest.main()
