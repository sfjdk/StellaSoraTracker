import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import QApplication, QWidget
from stellasora_toolkit.ui.preferences import load_theme, save_theme, SETTINGS_FILENAME
from stellasora_toolkit.ui.window import StellaSoraApp
from stellasora_toolkit.ui.theme import get_palette, set_palette


class PreferenceFileTests(unittest.TestCase):
    def test_missing_or_invalid_preferences_fall_back_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(load_theme(root),'orbit')
            self.assertEqual(list(root.iterdir()),[])
            for text in ('{broken','[]','null','{"theme":"unknown"}','{"theme":[]}'):
                (root/SETTINGS_FILENAME).write_text(text,encoding='utf-8')
                self.assertEqual(load_theme(root),'orbit')
                self.assertEqual((root/SETTINGS_FILENAME).read_text(encoding='utf-8'),text)

    def test_save_preserves_other_settings_and_does_not_touch_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/SETTINGS_FILENAME).write_text(json.dumps({'theme':'orbit','future_option':42}),encoding='utf-8')
            archive = root/'stellasora_gacha_archive.json'
            archive.write_bytes(b'archive must not change')
            self.assertTrue(save_theme(root,'sky'))
            self.assertEqual(load_theme(root),'sky')
            self.assertEqual(json.loads((root/SETTINGS_FILENAME).read_text(encoding='utf-8'))['future_option'],42)
            self.assertEqual(archive.read_bytes(),b'archive must not change')

    def test_failed_atomic_replace_keeps_previous_preference_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertTrue(save_theme(root,'journal'))
            previous = (root/SETTINGS_FILENAME).read_bytes()
            with patch('pathlib.Path.replace',side_effect=OSError('disk unavailable')):
                self.assertFalse(save_theme(root,'sky'))
            self.assertEqual((root/SETTINGS_FILENAME).read_bytes(),previous)
            self.assertEqual([p.name for p in root.iterdir()],[SETTINGS_FILENAME])


class ThemeWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.previous_palette = get_palette()
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.close()
            window.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
        set_palette(self.previous_palette)
        self.tmp.cleanup()

    def window(self,**kwargs):
        window = StellaSoraApp(self.root,online_sync=False,**kwargs)
        self.windows.append(window)
        return window

    def test_sky_navigation_is_only_in_left_sidebar_at_both_sizes(self):
        window = self.window(variant='sky',demo=True)
        window.show()
        for size in ((1440,1080),(960,760)):
            window.resize(*size)
            self.app.processEvents()
            root = window.centralWidget()
            sidebar = root.findChild(QWidget,'Sidebar')
            self.assertIsNotNone(sidebar)
            self.assertEqual(len(window.nav_buttons),5)
            self.assertTrue(all(b.parentWidget()==sidebar for b in window.nav_buttons))
            self.assertLess(sidebar.mapTo(root,QPoint(sidebar.width()-1,0)).x(),
                            window.stack.mapTo(root,QPoint(0,0)).x())
            window.nav_buttons[2].click()
            self.assertEqual(window.stack.currentIndex(),2)

    def test_settings_selection_is_restored_in_new_demo_and_local_windows(self):
        first = self.window(demo=True)
        first.navigate(2)
        first.theme_buttons['sky'].click()
        first.close()
        self.assertEqual([p.name for p in self.root.iterdir()],[SETTINGS_FILENAME])
        second = self.window(demo=True)
        self.assertEqual(second.variant,'sky')
        self.assertTrue(second.theme_buttons['sky'].isChecked())
        second.close()
        local = self.window(demo=False)
        self.assertEqual(local.variant,'sky')
        self.assertIsNotNone(local.centralWidget().findChild(QWidget,'Sidebar'))

    def test_explicit_launch_override_does_not_erase_saved_choice_until_selected(self):
        self.assertTrue(save_theme(self.root,'sky'))
        window = self.window(variant='journal',demo=True)
        self.assertEqual(window.variant,'journal')
        self.assertEqual(load_theme(self.root),'sky')
        window.theme_buttons['journal'].click()
        self.assertEqual(load_theme(self.root),'journal')
        restarted = self.window(demo=True)
        self.assertEqual(restarted.variant,'journal')

    def test_save_failure_keeps_theme_switch_usable_and_reports_persistence_failure(self):
        window = self.window(demo=True)
        with patch('stellasora_toolkit.ui.window.save_theme',return_value=False):
            window.theme_buttons['sky'].click()
        self.assertEqual(window.variant,'sky')
        self.assertTrue(window.theme_buttons['sky'].isChecked())
        self.assertIn('保存失败',window.status_label.text())
        self.assertFalse((self.root/SETTINGS_FILENAME).exists())


if __name__=='__main__': unittest.main()
