"""刷新速度相关的测试: 在线查询快速跳过、UID 快速通道、自动导出。

用户反馈"读取速度太慢"。这里锁住三条优化:
- 记录序号都认识时不再联网(省掉两个大接口与超时重试);
- UID 探测先逐个试最可能的字段名, 命中即收工, 不再全内存扫"含 uid 的字符串";
- <uid>.json 启动时与学到 UID 后自动产出, 不用点按钮。
"""
import contextlib
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stellasora_toolkit import catalog_sync, service  # noqa: E402
from stellasora_toolkit.account_uid import find_account_uid  # noqa: E402
from test_account_uid import LuaImage  # noqa: E402

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"


@contextlib.contextmanager
def temp_workdir(name: str):
    directory = TEMP_ROOT / f"speed_{name}"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class OnlineLookupDecisionTests(unittest.TestCase):
    def test_known_ids_do_not_need_online_lookup(self):
        # 110/214001 都是静态表里认识的五星
        self.assertFalse(catalog_sync.needs_online_lookup([110, 132, 214001, 139]))

    def test_unknown_ids_need_online_lookup(self):
        self.assertTrue(catalog_sync.needs_online_lookup([110, 999999]))
        self.assertTrue(catalog_sync.needs_online_lookup([161]))       # 前向兼容区间
        self.assertTrue(catalog_sync.needs_online_lookup([214999]))    # 新秘纹区间

    def test_empty_records_do_not_need_lookup(self):
        self.assertFalse(catalog_sync.needs_online_lookup([]))

    def test_skip_online_avoids_any_network_call(self):
        with temp_workdir("skip_online") as directory:
            state = directory / "catalog_sync_state.json"
            with mock.patch.object(catalog_sync, "_fetch_five_star_catalog",
                                   side_effect=AssertionError("序号都认识时不该联网")):
                report = catalog_sync.sync_with_report(state, [110, 132, 214001])
        self.assertTrue(report["skipped_online"])
        self.assertEqual(report["fetched_total"], 0)
        self.assertEqual(report["fetch_failed"], 0)
        self.assertEqual(report["audit_after"]["unresolved"], [])

    def test_unknown_id_still_goes_online(self):
        with temp_workdir("go_online") as directory:
            state = directory / "catalog_sync_state.json"
            fetched = [{"id": 139, "kind": "traveler", "name": "艾蕾", "icon": "/stella/assets/Eileen.png"}]
            with mock.patch.object(catalog_sync, "_fetch_five_star_catalog", return_value=fetched), \
                    mock.patch.object(catalog_sync, "_download_icon", return_value=True):
                report = catalog_sync.sync_with_report(state, [999999])
        self.assertFalse(report["skipped_online"])
        self.assertEqual(report["fetched_total"], 1)

    def test_startup_sync_without_records_still_goes_online(self):
        """不带记录序号的启动同步必须照常联网, 否则发现不了新五星。"""
        with temp_workdir("startup") as directory:
            state = directory / "catalog_sync_state.json"
            with mock.patch.object(catalog_sync, "_fetch_five_star_catalog", return_value=[]) as fetch:
                report = catalog_sync.sync_catalog(state)
        self.assertTrue(fetch.called)
        self.assertEqual(len(report), 2, "sync_catalog 仍返回 (appeared, downloaded)")


class UidQuickPathTests(unittest.TestCase):
    def test_quick_field_hit_skips_the_broad_scan(self):
        image = LuaImage()
        image.table({"_uid": "100872990"})
        discovery = image.discovery

        def explode(*_args, **_kwargs):
            raise AssertionError("快速字段已命中时不该再做全量扫描")

        original = discovery._uid_like_string_objects
        discovery._uid_like_string_objects = explode
        try:
            result = find_account_uid(discovery)
        finally:
            discovery._uid_like_string_objects = original

        self.assertTrue(result.found)
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.field_name, "_uid")

    def test_two_quick_fields_disagreeing_is_reported_as_ambiguous(self):
        image = LuaImage()
        image.table({"_uid": "555000111"})
        image.table({"_sUid": "100872990"})
        result = find_account_uid(image.discovery)
        self.assertFalse(result.found, "两个快速字段打架时不能瞎选")
        self.assertTrue(result.ambiguous)

    def test_preferred_uid_resolves_quick_field_conflict(self):
        image = LuaImage()
        image.table({"_uid": "555000111"})
        image.table({"_sUid": "100872990"})
        result = find_account_uid(image.discovery, preferred="100872990")
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.field_name, "_sUid")


class AutoExportTests(unittest.TestCase):
    _CATEGORIES = {1: [{"Time": 1, "NextPackage": "", "Gid": 10139, "Ids": [212007, 139]}]}

    def test_auto_export_uses_archive_uid(self):
        with temp_workdir("auto_uid") as directory:
            service._write_archive(directory, self._CATEGORIES, uid="100872990")
            path = service.refresh_share_file(directory)
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(path.name, "100872990.json")
        self.assertEqual(list(payload), ["version", "uid", "updatedAt", "categories"])

    def test_auto_export_prefers_manual_uid(self):
        with temp_workdir("auto_manual") as directory:
            service._write_archive(directory, self._CATEGORIES, uid="111")
            service.save_manual_uid(directory, "100872990")
            path = service.refresh_share_file(directory)
        self.assertEqual(path.name, "100872990.json")

    def test_auto_export_without_uid_or_records_is_a_noop(self):
        with temp_workdir("auto_empty") as directory:
            self.assertIsNone(service.refresh_share_file(directory))       # 没记录
            service._write_archive(directory, self._CATEGORIES)            # 有记录但没 UID
            self.assertIsNone(service.refresh_share_file(directory))
            self.assertEqual([p.name for p in directory.iterdir()], [service.ARCHIVE_FILENAME])

    def test_auto_export_rewrites_a_stale_file(self):
        with temp_workdir("auto_stale") as directory:
            service._write_archive(directory, self._CATEGORIES, uid="100872990")
            path = service.write_share_file(directory, {1: []}, "100872990")   # 先写一份空的
            service.refresh_share_file(directory)                              # 再按归档刷新
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["categories"]["1"]), 1)


class SkippedReportTextTests(unittest.TestCase):
    """界面文案: 跳过在线查询时不能再说"五星目录 0 个角色"。"""

    @staticmethod
    def _report(**overrides) -> dict:
        report = {
            "fetched_total": 0, "fetched_travelers": 0, "fetched_discs": 0,
            "record_count": 70, "skipped_online": True, "fetch_failed": 0,
            "missing_before": [], "registered": [], "downloaded": [], "existing": [],
            "icon_failed": [],
            "audit_before": {"unresolved": [], "misjudged": [], "clash": []},
            "audit_after": {"unresolved": [], "misjudged": [], "clash": []},
        }
        report.update(overrides)
        return report

    def test_skipped_online_text(self):
        from stellasora_toolkit.ui.window import _format_sync_report

        text, problems = _format_sync_report(self._report())
        self.assertIn("已跳过在线查询", text)
        self.assertEqual(problems, [])

    def test_normal_report_still_reports_catalog_size(self):
        from stellasora_toolkit.ui.window import _format_sync_report

        text, _ = _format_sync_report(self._report(skipped_online=False, fetched_travelers=24,
                                                   fetched_discs=59))
        self.assertIn("24 个角色", text)


if __name__ == "__main__":
    unittest.main()
