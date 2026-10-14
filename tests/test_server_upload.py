# -*- coding: utf-8 -*-
"""账户配置与上传客户端的单元测试。

网络部分照抄 tests/test_official_banners.py 的做法：
patch 模块级 urlopen，不引入 responses / requests-mock。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stellasora_toolkit import account_config, server_config, server_upload  # noqa: E402


def fake_response(payload, status: int = 200):
    """造一个 urlopen 返回的上下文管理器。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    response = mock.MagicMock()
    response.read.return_value = body
    response.status = status
    response.__enter__ = mock.Mock(return_value=response)
    response.__exit__ = mock.Mock(return_value=False)
    return response


class AccountConfigTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()

    def test_roundtrip(self):
        saved = account_config.save(self.dir, account_config.Account(
            server_url="https://example.com", token="tok123", username="玩家"))
        self.assertTrue(saved)
        loaded = account_config.load(self.dir)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.server_url, "https://example.com")
        self.assertEqual(loaded.token, "tok123")
        self.assertEqual(loaded.username, "玩家")
        self.assertTrue(loaded.logged_in)

    def test_missing_file_returns_none(self):
        self.assertIsNone(account_config.load(self.dir))

    def test_corrupt_file_returns_none(self):
        account_config.config_path(self.dir).write_text("{ 不是 json", encoding="utf-8")
        self.assertIsNone(account_config.load(self.dir))

    def test_wrong_shape_returns_none(self):
        for payload in ([], {"serverUrl": 123}, {"token": "x"},
                        {"serverUrl": "", "token": "x"}):
            account_config.config_path(self.dir).write_text(
                json.dumps(payload), encoding="utf-8")
            self.assertIsNone(account_config.load(self.dir), f"payload={payload}")

    def test_clear(self):
        account_config.save(self.dir, account_config.Account(
            server_url="https://x.com", token="t"))
        self.assertTrue(account_config.clear(self.dir))
        self.assertIsNone(account_config.load(self.dir))
        # 重复清理不该抛异常
        self.assertTrue(account_config.clear(self.dir))

    def test_token_survives_server_config_write(self):
        """回归：token 必须能在切换游戏版本后存活。

        server_config.save_key() 是【整体覆写】——它只写 {"server": ...}。
        所以 token 只要和它同居一个文件，用户每次切服就会被静默抹掉，
        表现为"刚登录过，下次打开又要登录"，且没有任何错误提示。
        """
        account_config.save(self.dir, account_config.Account(
            server_url="https://example.com", token="keep-me", username="玩家"))

        # 模拟用户切换国服/国际服（设置页、自动检测、双客户端弹窗都会调这个）
        server_config.save_key(self.dir / server_config.CONFIG_FILENAME, "intl")
        self.assertEqual(server_config.load_key(
            self.dir / server_config.CONFIG_FILENAME), "intl")

        # token 必须还在
        loaded = account_config.load(self.dir)
        self.assertIsNotNone(loaded, "切服后 token 被抹掉了")
        self.assertEqual(loaded.token, "keep-me")
        self.assertTrue(loaded.logged_in)

    def test_save_leaves_no_temp_files(self):
        account_config.save(self.dir, account_config.Account(
            server_url="https://x.com", token="t"))
        leftovers = list(self.dir.glob("*.tmp"))
        self.assertEqual(leftovers, [], f"残留临时文件: {leftovers}")


class UrlNormalizeTests(unittest.TestCase):
    def test_host_gets_https(self):
        self.assertEqual(account_config.normalize_server_url("example.com"),
                         "https://example.com")

    def test_loopback_gets_http(self):
        for host in ("127.0.0.1:3456", "localhost:8000"):
            self.assertTrue(
                account_config.normalize_server_url(host).startswith("http://"),
                host)

    def test_trailing_slash_stripped(self):
        self.assertEqual(account_config.normalize_server_url("https://x.cn///"),
                         "https://x.cn")

    def test_share_url_extracts_site(self):
        self.assertEqual(
            account_config.split_share_url("https://x.cn/s/AbC123"), "https://x.cn")
        self.assertEqual(
            account_config.split_share_url("x.cn/s/AbC123"), "https://x.cn")

    def test_plain_url_unchanged(self):
        self.assertEqual(account_config.split_share_url("https://x.cn/gacha"),
                         "https://x.cn/gacha")

    def test_empty(self):
        self.assertEqual(account_config.normalize_server_url("   "), "")


class UploadClientTests(unittest.TestCase):
    def _capture(self, payload, status=200):
        """patch urlopen，返回 (fake_response, 调用记录列表)。"""
        seen: list = []
        response = fake_response(payload, status)

        def fake_urlopen(request, timeout=None):
            seen.append(request)
            return response

        return fake_urlopen, seen

    def test_login_sends_json_and_returns_token(self):
        fake, seen = self._capture({"ok": True, "token": "abc", "username": "u"})
        with mock.patch("stellasora_toolkit.server_upload.urlopen", fake):
            result = server_upload.login("https://x.cn", "u", "pw")

        self.assertEqual(result["token"], "abc")
        request = seen[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.full_url, "https://x.cn/api/login")
        self.assertIn("application/json", request.get_header("Content-type"))
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body, {"username": "u", "password": "pw"})

    def test_login_without_token_raises(self):
        fake, _ = self._capture({"ok": True})
        with mock.patch("stellasora_toolkit.server_upload.urlopen", fake):
            with self.assertRaises(server_upload.UploadError):
                server_upload.login("https://x.cn", "u", "pw")

    def test_upload_sends_bearer_and_categories(self):
        fake, seen = self._capture({"ok": True, "added": 5, "groups": 10, "pulls": 100})
        categories = {"1": [{"Gid": 10130, "Time": 1, "Ids": [1, 2]}]}
        with mock.patch("stellasora_toolkit.server_upload.urlopen", fake):
            result = server_upload.upload("https://x.cn", "tok", categories)

        self.assertEqual(result["added"], 5)
        request = seen[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer tok")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["mode"], "merge")
        self.assertEqual(body["categories"], categories)

    def test_http_error_message_is_passed_through(self):
        """服务端 message 是写给用户看的中文，必须原样透传。"""
        import urllib.error
        error = urllib.error.HTTPError(
            "https://x.cn/api/login", 401, "Unauthorized", {},
            BytesIO(json.dumps({"ok": False, "message": "密码不正确"}).encode()))

        def fake_urlopen(request, timeout=None):
            raise error

        with mock.patch("stellasora_toolkit.server_upload.urlopen", fake_urlopen):
            with self.assertRaises(server_upload.UploadError) as ctx:
                server_upload.login("https://x.cn", "u", "bad")
        self.assertEqual(ctx.exception.message, "密码不正确")
        self.assertTrue(ctx.exception.is_auth_error)

    def test_http_error_without_json_falls_back(self):
        import urllib.error
        from io import BytesIO as BIO
        error = urllib.error.HTTPError(
            "https://x.cn/api/login", 500, "Server Error", {}, BIO(b"<html>500</html>"))

        def fake_urlopen(request, timeout=None):
            raise error

        with mock.patch("stellasora_toolkit.server_upload.urlopen", fake_urlopen):
            with self.assertRaises(server_upload.UploadError) as ctx:
                server_upload.login("https://x.cn", "u", "pw")
        self.assertIn("服务器", ctx.exception.message)

    def test_non_json_response_raises_friendly_error(self):
        """被中间代理/门户页劫持时返回的是 HTML —— 不能把 HTML 当数据用。"""
        response = mock.MagicMock()
        response.read.return_value = b"<html>login portal</html>"
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        with mock.patch("stellasora_toolkit.server_upload.urlopen",
                        lambda request, timeout=None: response):
            with self.assertRaises(server_upload.UploadError) as ctx:
                server_upload.probe("https://x.cn")
        self.assertIn("无法识别", ctx.exception.message)

    def test_read_archive_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(server_upload.UploadError):
                server_upload.read_archive(Path(tmp))

    def test_read_archive_rejects_empty_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "stellasora_gacha_archive.json").write_text(
                json.dumps({"version": 1, "categories": {}}), encoding="utf-8")
            with self.assertRaises(server_upload.UploadError):
                server_upload.read_archive(Path(tmp))

    def test_read_archive_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"version": 1, "categories": {"1": [{"Gid": 1, "Ids": [1]}]}}
            (Path(tmp) / "stellasora_gacha_archive.json").write_text(
                json.dumps(payload), encoding="utf-8")
            self.assertEqual(server_upload.read_archive(Path(tmp)),
                             payload["categories"])


if __name__ == "__main__":
    unittest.main()
