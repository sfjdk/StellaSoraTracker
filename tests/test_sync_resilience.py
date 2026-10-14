"""自动更新通路(卡池信息 / 五星目录 + 头像)的健壮性测试。

实测到的故障: characters/discs 返回体很大, 20 秒超时读不完就直接 0 字节, 而旧代码
只试一次、失败静默返回空 —— 界面显示"资源库无缺失", 用户以为功能坏了却说不出原因。
这里覆盖: 重试、失败计数、目录缓存兜底、卡池缓存重试、报告文案。
"""
import contextlib
import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from stellasora_toolkit import catalog_sync, official_banners

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"


@contextlib.contextmanager
def temp_workdir(name: str):
    """见 tests/test_import_format.py: 不用 tempfile, 它建的 0o700 目录在受限沙箱里删不掉。"""
    directory = TEMP_ROOT / f"sync_resilience_{name}"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _state_path(directory: Path) -> Path:
    return directory / "catalog_sync_state.json"


class ReadUrlRetryTests(unittest.TestCase):
    def test_retries_then_succeeds(self):
        calls = []

        def fake_urlopen(request, timeout=None):
            calls.append(timeout)
            if len(calls) == 1:
                raise OSError("read timed out")
            return _FakeResponse(b'{"ok": true}')

        with mock.patch.object(catalog_sync, "urlopen", fake_urlopen), \
                mock.patch.object(catalog_sync.time, "sleep"):
            payload = catalog_sync._read_url("http://x", attempts=3)

        self.assertEqual(payload, b'{"ok": true}')
        self.assertEqual(len(calls), 2, "第一次失败后应该重试")
        self.assertEqual(calls[0], catalog_sync.READ_TIMEOUT, "超时时间要够大(返回体很大)")

    def test_gives_up_after_all_attempts(self):
        calls = []

        def fake_urlopen(request, timeout=None):
            calls.append(1)
            raise OSError("read timed out")

        with mock.patch.object(catalog_sync, "urlopen", fake_urlopen), \
                mock.patch.object(catalog_sync.time, "sleep"):
            payload = catalog_sync._read_url("http://x", attempts=3)

        self.assertEqual(payload, b"")
        self.assertEqual(len(calls), 3)

    def test_progress_callback_reports_retry(self):
        messages = []

        def fake_urlopen(request, timeout=None):
            raise OSError("boom")

        with mock.patch.object(catalog_sync, "urlopen", fake_urlopen), \
                mock.patch.object(catalog_sync.time, "sleep"):
            catalog_sync._read_url("http://x", messages.append, attempts=2)

        self.assertTrue(any("重试" in message for message in messages))


class FetchFailureFlagTests(unittest.TestCase):
    def test_both_endpoints_failing_is_counted(self):
        with mock.patch.object(catalog_sync, "_read_url", return_value=b""):
            items = catalog_sync._fetch_five_star_catalog()
        self.assertEqual(items, [])
        self.assertEqual(catalog_sync.fetch_failures(), 2)

    def test_only_broken_endpoint_is_counted(self):
        characters = json.dumps([
            {"id": 139, "name": "艾蕾", "grade": 5, "icon": "/stella/assets/Eileen.png"},
        ]).encode("utf-8")

        def fake_read(url, progress=None, timeout=0, attempts=0):
            return characters if "characters" in url else b""

        with mock.patch.object(catalog_sync, "_read_url", fake_read):
            items = catalog_sync._fetch_five_star_catalog()
        self.assertEqual([item["id"] for item in items], [139])
        self.assertEqual(catalog_sync.fetch_failures(), 1)

    def test_successful_fetch_resets_the_flag(self):
        characters = json.dumps([
            {"id": 139, "name": "艾蕾", "grade": 5, "icon": "/stella/assets/Eileen.png"},
        ]).encode("utf-8")
        discs = json.dumps([
            {"id": 214062, "name": "美好，尽在昨日", "star": 5, "icon": "/stella/assets/x.png"},
        ]).encode("utf-8")

        def fake_read(url, progress=None, timeout=0, attempts=0):
            return characters if "characters" in url else discs

        with mock.patch.object(catalog_sync, "_read_url", fake_read):
            items = catalog_sync._fetch_five_star_catalog()
        self.assertEqual(sorted(item["id"] for item in items), [139, 214062])
        self.assertEqual(catalog_sync.fetch_failures(), 0)


class CatalogCacheFallbackTests(unittest.TestCase):
    _FETCHED = [{"id": 139, "kind": "traveler", "name": "艾蕾", "icon": "/stella/assets/Eileen.png"}]

    def test_successful_fetch_writes_the_cache(self):
        with temp_workdir("cache_write") as directory:
            with mock.patch.object(catalog_sync, "_fetch_five_star_catalog",
                                   return_value=[dict(it) for it in self._FETCHED]), \
                    mock.patch.object(catalog_sync, "_download_icon", return_value=True):
                catalog_sync.sync_with_report(_state_path(directory))

            cached = catalog_sync._load_catalog_cache(
                catalog_sync._catalog_cache_path(_state_path(directory)))
        self.assertEqual(cached, self._FETCHED)

    def test_failed_fetch_falls_back_to_the_cache(self):
        with temp_workdir("cache_fallback") as directory:
            state = _state_path(directory)
            catalog_sync._save_catalog_cache(catalog_sync._catalog_cache_path(state), self._FETCHED)
            assets = directory / "assets"

            with mock.patch.object(catalog_sync, "_fetch_five_star_catalog", return_value=[]), \
                    mock.patch.object(catalog_sync, "asset_root", return_value=assets), \
                    mock.patch.object(catalog_sync, "_download_icon", return_value=True):
                report = catalog_sync.sync_with_report(state)

        self.assertTrue(report["catalog_from_cache"])
        self.assertEqual(report["fetched_total"], 1)
        self.assertEqual(len(report["downloaded"]), 1, "在线查询失败时也要按缓存把头像补齐")
        self.assertEqual(catalog_sync._load_catalog_cache(None), [])

    def test_no_cache_and_failed_fetch_stays_empty(self):
        with temp_workdir("no_cache") as directory:
            with mock.patch.object(catalog_sync, "_fetch_five_star_catalog", return_value=[]):
                report = catalog_sync.sync_with_report(_state_path(directory))
        self.assertFalse(report["catalog_from_cache"])
        self.assertEqual(report["fetched_total"], 0)

    def test_broken_cache_file_is_ignored(self):
        with temp_workdir("broken_cache") as directory:
            state = _state_path(directory)
            path = catalog_sync._catalog_cache_path(state)
            path.write_text("{ this is not json", encoding="utf-8")
            with mock.patch.object(catalog_sync, "_fetch_five_star_catalog", return_value=[]):
                report = catalog_sync.sync_with_report(state)
        self.assertFalse(report["catalog_from_cache"])
        self.assertEqual(report["fetched_total"], 0)


class BannerRefreshTests(unittest.TestCase):
    _BANNERS = {10139: ("溺于温情笑意中", "2026-09-29", "2026-10-20", "艾蕾")}

    def test_retries_once_then_succeeds(self):
        calls = []

        def fake_fetch(timeout=20.0, lang=None):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("timed out")
            return dict(self._BANNERS)

        with temp_workdir("banner_retry") as directory:
            cache = directory / "official_banners_cn.json"
            with mock.patch.object(official_banners, "fetch_banners", fake_fetch), \
                    mock.patch.object(official_banners.time, "sleep"):
                ok = official_banners.refresh_from_network(cache)
            saved = official_banners.load_banners(cache)

        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)
        self.assertEqual(saved, self._BANNERS)

    def test_all_attempts_failing_returns_false(self):
        def fake_fetch(timeout=20.0, lang=None):
            raise OSError("timed out")

        with temp_workdir("banner_fail") as directory:
            cache = directory / "official_banners_cn.json"
            with mock.patch.object(official_banners, "fetch_banners", fake_fetch), \
                    mock.patch.object(official_banners.time, "sleep"):
                ok = official_banners.refresh_from_network(cache, attempts=2)
            self.assertFalse(ok)
            self.assertFalse(cache.exists(), "失败时不该写出半截缓存")


class ReportTextTests(unittest.TestCase):
    def _report(self, **overrides) -> dict:
        report = {
            "fetched_total": 1, "fetched_travelers": 1, "fetched_discs": 0,
            "record_count": 0,
            "missing_before": [], "registered": [], "downloaded": [], "existing": [],
            "icon_failed": [],
            "audit_before": {"unresolved": [], "misjudged": [], "clash": []},
            "audit_after": {"unresolved": [], "misjudged": [], "clash": []},
        }
        report.update(overrides)
        return report

    def test_cache_fallback_is_visible_in_the_text(self):
        from stellasora_toolkit.ui.window import _format_sync_report

        text, _ = _format_sync_report(self._report(catalog_from_cache=True))
        self.assertIn("上次缓存", text)

    def test_normal_report_has_no_cache_note(self):
        from stellasora_toolkit.ui.window import _format_sync_report

        text, _ = _format_sync_report(self._report())
        self.assertNotIn("上次缓存", text)


if __name__ == "__main__":
    unittest.main()
