import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QTableWidget, QPushButton
from stellasora_toolkit.ui.window import StellaSoraApp
from stellasora_toolkit.ui.beta_model import demo_snapshot, overview
from stellasora_toolkit.service import ARCHIVE_FILENAME


class BetaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_demo_is_read_only_and_style_switch_preserves_records_and_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = StellaSoraApp(root,variant='orbit',demo=True)
            original = window.snapshot
            window.open_records('disc_limited')
            for variant in ('sky','journal','orbit'):
                window.change_variant(variant)
                self.app.processEvents()
                self.assertIs(window.snapshot,original)
                self.assertEqual(window.stack.currentIndex(),1)
                self.assertEqual(window.records.current,'disc_limited')
            window.refresh()
            self.assertEqual(window.snapshot.gacha,original.gacha)
            self.assertEqual(list(root.iterdir()),[])
            window.close()

    def test_settings_theme_buttons_keep_settings_open_and_preserve_record_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = StellaSoraApp(Path(tmp),variant='orbit',demo=True)
            original = window.snapshot
            window.open_records('traveler_limited')
            window.records.toggle_mode()
            window.records.search.setText('花铃')
            window.navigate(2)
            window.theme_buttons['orbit'].click()
            self.assertTrue(window.theme_buttons['orbit'].isChecked())
            for variant in ('sky','journal','orbit'):
                settings_buttons = window.settings.findChildren(QPushButton)
                self.assertIn(window.theme_buttons[variant],settings_buttons)
                window.theme_buttons[variant].click()
                self.app.processEvents()
                self.assertEqual(window.variant,variant)
                self.assertTrue(window.theme_buttons[variant].isChecked())
                self.assertEqual(window.stack.currentIndex(),2)
                self.assertIs(window.snapshot,original)
                self.assertEqual(window.records.current,'traveler_limited')
                self.assertTrue(window.records.all_pulls)
                self.assertEqual(window.records.search.text(),'花铃')
                self.assertEqual(window.records.content.itemAt(0).widget().rowCount(),2)
            self.assertFalse((Path(tmp)/ARCHIVE_FILENAME).exists())
            window.close()

    def test_loads_canonical_archive_without_timestamped_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = [{'Gid':10157,'Time':1787051539,'Ids':[103,157]}]
            (root/ARCHIVE_FILENAME).write_text(json.dumps({'categories':{'1':records}}),encoding='utf-8')
            window = StellaSoraApp(root,demo=False,online_sync=False)
            self.assertEqual(window.snapshot.gacha,records)
            self.assertEqual(window.snapshot.pull_count,2)
            window.close()

    def test_off_banner_does_not_reset_limited_pity_and_unknown_banner_keeps_hits(self):
        stats = overview([{'Gid':10157,'Time':10,'Ids':[157,103,110,103]}])
        self.assertEqual(stats.category_stats['traveler_limited'].current_pity,3)
        unknown = overview([{'Gid':10170,'Time':10,'Ids':[103,161,103]}])
        self.assertEqual(unknown.category_stats['traveler_limited'].current_pity,1)
        self.assertEqual(unknown.total_five,1)

    def test_all_pull_table_and_search_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = StellaSoraApp(Path(tmp),demo=True)
            window.open_records('traveler_limited')
            window.records.toggle_mode()
            table = window.records.findChildren(QTableWidget)[-1]
            expected = overview(demo_snapshot().gacha).category_stats['traveler_limited'].total_pulls
            self.assertEqual(table.rowCount(),expected)
            window.records.set_query('花铃')
            table = window.records.content.itemAt(0).widget()
            self.assertEqual(table.rowCount(),2)
            window.close()

    def test_refresh_uses_existing_extractor_and_surfaces_errors_without_losing_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = StellaSoraApp(Path(tmp),demo=False,online_sync=False)
            original = window.snapshot
            with patch('stellasora_toolkit.ui.controller.extract_snapshot',side_effect=RuntimeError('游戏未启动')) as extractor, patch('stellasora_toolkit.ui.controller.QMessageBox.critical'), patch('stellasora_toolkit.ui.controller.probe_running_groups',return_value=[]):
                window.refresh()
                import time
                for _ in range(200):
                    self.app.processEvents()
                    if not window._busy: break
                    time.sleep(0.01)
                self.app.processEvents()
                self.app.processEvents()
                self.assertEqual(extractor.call_count,1)
                self.assertIn('游戏未启动',window._status_text)
                self.assertIs(window.snapshot,original)
            window.close()

    def test_import_merges_deduplicates_and_backs_up_original_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = {'Gid':10157,'Time':10,'Ids':[103,157]}
            new = {'Gid':10157,'Time':20,'Ids':[103]}
            archive = root / ARCHIVE_FILENAME
            original = json.dumps({'categories':{'1':[old]}})
            archive.write_text(original,encoding='utf-8')
            imported = root / 'incoming.json'
            imported.write_text(json.dumps({'categories':{'1':[old,new]}}),encoding='utf-8')
            window = StellaSoraApp(root,demo=False,online_sync=False)
            with patch('stellasora_toolkit.ui.window.QFileDialog.getOpenFileName',return_value=(str(imported),'JSON')):
                window.import_archive()
            self.assertEqual(window.snapshot.pull_count,3)
            backup = next((root/'backups').glob('*.json'))
            self.assertEqual(backup.read_text(encoding='utf-8'),original)
            window.close()

    def test_failed_backup_prevents_import_from_replacing_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / ARCHIVE_FILENAME
            original = json.dumps({'categories':{'1':[{'Gid':1,'Time':10,'Ids':[125]}]}})
            archive.write_text(original,encoding='utf-8')
            imported = root / 'incoming.json'
            imported.write_text(json.dumps({'groups':[{'Gid':1,'Time':20,'Ids':[134]}]}),encoding='utf-8')
            window = StellaSoraApp(root,demo=False,online_sync=False)
            with patch('stellasora_toolkit.ui.window.QFileDialog.getOpenFileName',return_value=(str(imported),'JSON')), patch('stellasora_toolkit.ui.window.shutil.copy2',side_effect=OSError('磁盘不可写')):
                window.import_archive()
            self.assertEqual(archive.read_text(encoding='utf-8'),original)
            self.assertIn('创建备份失败',window._status_text)
            window.close()


if __name__ == '__main__': unittest.main()
