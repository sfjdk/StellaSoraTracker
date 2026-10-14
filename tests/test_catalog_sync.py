import tempfile
import unittest
from pathlib import Path
from unittest import mock

from stellasora_toolkit.catalog import (
    DISC_NAMES,
    FIVE_STAR_DISCS,
    FIVE_STAR_ITEMS,
    FIVE_STAR_TRAVELERS,
    TRAVELER_NAMES,
    register_gacha_resource,
)
from stellasora_toolkit.catalog_sync import (
    _download_icon,
    audit_alignment,
    sync_catalog,
    sync_with_report,
)

# 测试专用 ID: 避开静态表与所有前向兼容区间(161-199 / 214000-214999)
TEST_TRAVELER_ID = 99
TEST_DISC_ID = 209999

_FETCHED = [
    {"id": TEST_TRAVELER_ID, "kind": "traveler", "name": "测试旅人", "icon": "/stella/assets/t.png"},
    {"id": TEST_DISC_ID, "kind": "disc", "name": "测试秘纹", "icon": "/stella/assets/d.png"},
]


def _cleanup():
    for table, ident in ((TRAVELER_NAMES, TEST_TRAVELER_ID), (DISC_NAMES, TEST_DISC_ID)):
        table.pop(ident, None)
    FIVE_STAR_TRAVELERS.discard(TEST_TRAVELER_ID)
    FIVE_STAR_DISCS.pop(TEST_DISC_ID, None)
    FIVE_STAR_ITEMS.discard(TEST_TRAVELER_ID)
    FIVE_STAR_ITEMS.discard(TEST_DISC_ID)


class AuditAlignmentTests(unittest.TestCase):
    def tearDown(self):
        _cleanup()

    def test_audit_reports_unresolved_ids_and_misjudged_five_stars(self):
        audit = audit_alignment(_FETCHED, [TEST_TRAVELER_ID, 999999])
        self.assertIn(TEST_TRAVELER_ID, audit["unresolved"])  # 回显为 "物品 #99"
        self.assertIn(999999, audit["unresolved"])
        # API 确认五星但 is_five_star_item 判定为 False -> 星级错位
        self.assertEqual({it["id"] for it in audit["misjudged"]},
                         {TEST_TRAVELER_ID, TEST_DISC_ID})
        self.assertEqual(audit["clash"], [])

    def test_audit_clears_after_registration(self):
        register_gacha_resource(TEST_TRAVELER_ID, "traveler", "测试旅人")
        register_gacha_resource(TEST_DISC_ID, "disc", "测试秘纹")
        audit = audit_alignment(_FETCHED, [TEST_TRAVELER_ID])
        self.assertNotIn(TEST_TRAVELER_ID, audit["unresolved"])
        self.assertEqual(audit["misjudged"], [])
        self.assertEqual(audit["clash"], [])

    def test_audit_detects_id_clash_between_tables(self):
        try:
            DISC_NAMES[TEST_TRAVELER_ID] = "冲突秘纹"  # 同一序号同时出现在角色表与秘纹表
            audit = audit_alignment(_FETCHED, [])
            self.assertEqual([it["id"] for it in audit["clash"]], [TEST_TRAVELER_ID])
        finally:
            DISC_NAMES.pop(TEST_TRAVELER_ID, None)


class SyncWithReportTests(unittest.TestCase):
    def tearDown(self):
        _cleanup()

    def _patch_fetch(self):
        return mock.patch(
            "stellasora_toolkit.catalog_sync._fetch_five_star_catalog",
            return_value=[dict(it) for it in _FETCHED],
        )

    def test_sync_with_report_registers_and_audits(self):
        with self._patch_fetch(), \
                mock.patch("stellasora_toolkit.catalog_sync._download_icon", return_value=False):
            messages: list[str] = []
            report = sync_with_report(None, [TEST_TRAVELER_ID], progress=messages.append)

        self.assertEqual(report["fetched_total"], 2)
        self.assertEqual(len(report["missing_before"]), 2)   # 查询: 缺什么
        self.assertEqual(len(report["registered"]), 2)       # 补全: 注册
        self.assertEqual(len(report["icon_failed"]), 2)      # 下载失败(模拟离线)
        self.assertIn(TEST_TRAVELER_ID, report["audit_before"]["unresolved"])
        self.assertEqual(report["audit_after"]["unresolved"], [])     # 对齐: 序号可回显
        self.assertEqual(report["audit_after"]["misjudged"], [])      # 对齐: 星级判定生效
        self.assertEqual(report["record_count"], 1)
        self.assertTrue(messages, "同步过程应有进度回调")

    def test_sync_with_download_success(self):
        with self._patch_fetch(), \
                mock.patch("stellasora_toolkit.catalog_sync._download_icon", return_value=True):
            report = sync_with_report(None)
        self.assertEqual(len(report["downloaded"]), 2)
        self.assertEqual(report["icon_failed"], [])

    def test_sync_catalog_keeps_legacy_signature(self):
        with self._patch_fetch(), \
                mock.patch("stellasora_toolkit.catalog_sync._download_icon", return_value=True):
            appeared, downloaded = sync_catalog(None)
        self.assertEqual(len(appeared), 2)
        self.assertEqual(len(downloaded), 2)

    def test_sync_downloads_missing_image_even_for_registered_name(self):
        """名称已注册但本地缺图的五星也要补图(图片补全与注册解耦)。"""
        known = {"id": 110, "kind": "traveler", "name": "翡冷翠", "icon": "/stella/assets/Firenze.png"}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("stellasora_toolkit.catalog_sync.asset_root", return_value=Path(tmp)), \
                    mock.patch("stellasora_toolkit.catalog_sync._fetch_five_star_catalog", return_value=[known]), \
                    mock.patch("stellasora_toolkit.catalog_sync._download_icon", return_value=True):
                report = sync_with_report(None)
        self.assertEqual(report["registered"], [])       # 名称已在静态表, 不重复注册
        self.assertEqual(len(report["downloaded"]), 1)   # 缺图 -> 补
        self.assertEqual(report["existing"], [])


class DownloadIconTests(unittest.TestCase):
    def test_rejects_non_png_payload(self):
        """站点代理失败可能返回 HTML/520, 不能写坏 .png 文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.png"
            with mock.patch("stellasora_toolkit.catalog_sync._read_url", return_value=b"<html>520</html>"):
                self.assertFalse(_download_icon("http://x", target))
            self.assertFalse(target.exists())

    def test_accepts_png_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.png"
            png = b"\x89PNG\r\n\x1a\n" + b"body"
            with mock.patch("stellasora_toolkit.catalog_sync._read_url", return_value=png):
                self.assertTrue(_download_icon("http://x", target))
            self.assertTrue(target.exists())


class FormatReportTests(unittest.TestCase):
    def _fake_report(self, unresolved_after=(), misjudged_after=(), icon_failed=()):
        return {
            "fetched_total": 2, "fetched_travelers": 1, "fetched_discs": 1,
            "record_count": 2,
            "missing_before": [{"id": TEST_TRAVELER_ID, "kind": "traveler", "name": "测试旅人"}],
            "registered": [],
            "downloaded": [],
            "existing": [],
            "icon_failed": list(icon_failed),
            "audit_before": {"unresolved": [TEST_TRAVELER_ID],
                             "misjudged": [{"id": TEST_TRAVELER_ID, "kind": "traveler"}],
                             "clash": []},
            "audit_after": {"unresolved": list(unresolved_after),
                            "misjudged": list(misjudged_after),
                            "clash": []},
        }

    def test_aligned_report_is_positive(self):
        from stellasora_toolkit.ui.window import _format_sync_report
        text, problems = _format_sync_report(self._fake_report())
        self.assertIn("回显缺失 1→0 ✔", text)
        self.assertIn("五星判定错位 1→0 ✔", text)
        self.assertIn("✔ 序号与角色已全部对齐", text)
        self.assertEqual(problems, [])

    def test_misaligned_report_lists_problems(self):
        from stellasora_toolkit.ui.window import _format_sync_report
        text, problems = _format_sync_report(
            self._fake_report(unresolved_after=[TEST_TRAVELER_ID]))
        self.assertIn("回显缺失 1→1 ✘", text)
        self.assertEqual(len(problems), 1)
        self.assertIn("无法回显", problems[0])

    def test_no_records_mentions_data_refresh(self):
        from stellasora_toolkit.ui.window import _format_sync_report
        report = self._fake_report()
        report["record_count"] = 0
        text, _ = _format_sync_report(report)
        self.assertIn("暂无本地抽卡记录", text)


if __name__ == "__main__":
    unittest.main()
