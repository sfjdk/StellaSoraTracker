"""UI integration regressions for every previously omitted feature group."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox
from stellasora_toolkit import accounts, server_config, account_config, service
from stellasora_toolkit.account_uid import UidSearch
from stellasora_toolkit.official_banners import set_active_banners
from stellasora_toolkit.ui.window import StellaSoraApp
from stellasora_toolkit.ui.beta_model import overview
from stellasora_toolkit.ui.theme import get_palette, set_palette


class FeatureParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_profile = server_config.active().key
        self.old_palette = get_palette()
        server_config.set_active('cn')
        self.window = StellaSoraApp(self.root,demo=False,online_sync=False)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        server_config.set_active(self.old_profile)
        set_palette(self.old_palette)
        set_active_banners({})
        self.tmp.cleanup()

    def import_uid(self,uid,item,time=10):
        source = self.root/f'incoming-{uid}.json'
        source.write_text(json.dumps({'uid':uid,'categories':{'1':[{'Gid':10157,'Time':time,'Ids':[item]}]}}),encoding='utf-8')
        with patch('stellasora_toolkit.ui.window.QFileDialog.getOpenFileName',return_value=(str(source),'JSON')):
            self.window._import_data()

    def test_account_uid_server_and_web_callbacks_are_reachable(self):
        callbacks = self.window.settings._cb
        for key in ('account_switch','account_new','account_rename','account_merge','account_remove',
                    'save_uid','read_uid','share','server_changed','server_auto'):
            self.assertTrue(callable(callbacks[key]),key)
        for key in ('save_url','login','register','logout','upload','open_site'):
            self.assertTrue(callable(self.window._account._cb[key]),key)
        self.assertEqual(self.window.stack.count(),5)
        self.assertEqual(set(self.window.settings._server_buttons),{'cn','intl','jp'})

    def test_uid_imports_remain_isolated_and_switch_updates_archive_path(self):
        self.import_uid('100000001',157)
        first = accounts.active_account(self.root)
        self.import_uid('100000002',133)
        second = accounts.active_account(self.root)
        self.assertNotEqual(first.key,second.key)
        self.assertEqual(self.window.snapshot.gacha[0]['Ids'],[133])
        self.window.settings._cb['account_switch'](first.key)
        self.assertEqual(self.window.snapshot.gacha[0]['Ids'],[157])
        self.assertEqual(self.window.settings._uid.text(),first.uid)
        self.assertIn(f'accounts\\{first.key}\\',self.window.settings._archive_path.text())
        self.assertTrue((accounts.data_dir(self.root,first.key)/f'{first.uid}.json').exists())
        self.assertTrue((accounts.data_dir(self.root,second.key)/f'{second.uid}.json').exists())

    def test_uid_memory_result_is_saved_to_current_account_and_share_matches(self):
        self.import_uid('100000001',157)
        self.window._on_uid_read({'search':UidSearch(uid='100000001',field_name='_uid')})
        directory = accounts.active_data_dir(self.root)
        self.assertEqual(service.load_manual_uid(directory),'100000001')
        share = json.loads((directory/'100000001.json').read_text(encoding='utf-8'))
        self.assertEqual(share['uid'],'100000001')
        self.assertEqual(share['categories']['1'][0]['Ids'],[157])

    def test_theme_preserves_unsaved_uid_and_web_login_fields(self):
        self.window.navigate(2)
        self.window.settings._uid.setText('100000123')
        self.window._account._url.setText('https://example.com')
        self.window._account._username.setText('preview-user')
        self.window._account._password.setText('not-a-real-password')
        for theme in ('sky','journal','orbit'):
            self.window.theme_buttons[theme].click()
            self.app.processEvents()
            self.assertEqual(self.window.settings._uid.text(),'100000123')
            self.assertEqual(self.window._account._url.text(),'https://example.com')
            self.assertEqual(self.window._account._password.text(),'not-a-real-password')
            self.assertEqual(self.window.stack.currentIndex(),2)

    def test_three_server_setting_and_auto_mode_are_saved(self):
        for key in ('cn','intl','jp'):
            self.window.settings._cb['server_changed'](key)
            self.assertEqual(server_config.active().key,key)
            self.assertTrue(server_config.load_manual(server_config.config_path(self.root)))
        self.window.settings._cb['server_auto']()
        self.assertFalse(server_config.load_manual(server_config.config_path(self.root)))

    def test_dynamic_banner_used_for_up_and_pity_in_new_home(self):
        set_active_banners({10170:('New banner','2026-10-01','2026-10-21','花铃')})
        stats = overview([{'Gid':10170,'Time':10,'Ids':[157,103,110,103]}])
        self.assertEqual(stats.category_stats['traveler_limited'].current_pity,3)

    def test_csv_import_and_restart_use_complete_canonical_archive(self):
        self.import_uid('100000001',157)
        directory = accounts.active_data_dir(self.root)
        (directory/'stellasora_gacha_old.json').write_text(json.dumps({'groups':[{'Gid':10157,'Time':10,'Ids':[157]}],
                                                                     'categories':{'1':[{'Gid':10157,'Time':10,'Ids':[157]}]}}),encoding='utf-8')
        csv = self.root/'incoming.csv'
        csv.write_text('Gid,Time,Id\n10157,20,133\n',encoding='gb18030')
        with patch('stellasora_toolkit.ui.window.QFileDialog.getOpenFileName',return_value=(str(csv),'CSV')):
            self.window._import_data()
        self.assertEqual(self.window.snapshot.pull_count,2)
        self.window._load_latest()
        self.assertEqual(self.window.snapshot.pull_count,2)
        self.assertEqual(self.window.snapshot.uid,'100000001')

    def test_saved_web_account_is_reflected_in_restored_account_page(self):
        account_config.save(self.root,account_config.Account(server_url='https://example.com',token='test-token',username='preview-user'))
        self.window._refresh_account_view()
        self.assertIn('preview-user',self.window._account._who.text())
        self.window.navigate(3)
        self.assertFalse(self.window._account._account_card.isHidden())

    def test_refresh_verifies_game_uid_even_when_current_uid_is_known(self):
        self.import_uid('100000001',157)
        first = accounts.active_account(self.root)
        before = service.load_archive_categories(self.root)
        with patch('stellasora_toolkit.service.detect_and_apply',return_value=(server_config.active(),'', ['cn'])), \
             patch('stellasora_toolkit.service.find_process_id',return_value=123), \
             patch('stellasora_toolkit.service.RemoteProcess'), \
             patch('stellasora_toolkit.service.Lua53Reader'), \
             patch('stellasora_toolkit.service.LuaTableDiscovery') as discovery, \
             patch('stellasora_toolkit.service.find_account_uid',return_value=UidSearch(uid='100000002',field_name='_uid')) as uid:
            discovery.return_value.read_target_field.return_value = {1:[{'Gid':10157,'Time':20,'Ids':[133]}]}
            snapshot = service.extract_snapshot(self.root,verify_uid=True)
        self.assertEqual(uid.call_count,1)
        self.assertEqual(snapshot.uid,'100000002')
        self.assertEqual(accounts.active_account(self.root).uid,'100000002')
        self.assertEqual(service.load_account_categories(self.root,first.key),before)
        self.assertEqual(snapshot.gacha[0]['Ids'],[133])

    def test_packaged_update_keeps_download_and_installer_path(self):
        from stellasora_toolkit.app_updater import AppUpdate
        import time
        update = AppUpdate(version='9.0.0',url='https://example.com/update.zip',sha256='0'*64,notes='test')
        package = self.root/'update.zip'
        with patch('stellasora_toolkit.ui.window.sys.frozen',True,create=True), \
             patch('stellasora_toolkit.ui.window.QMessageBox.question',return_value=QMessageBox.Yes), \
             patch('stellasora_toolkit.ui.window.app_updater.download_update',return_value=package) as download, \
             patch('stellasora_toolkit.ui.window.app_updater.launch_update_installer') as install:
            self.window._update_checked(update)
            for _ in range(200):
                self.app.processEvents()
                if install.called: break
                time.sleep(0.01)
            self.assertEqual(download.call_count,1)
            self.assertEqual(install.call_count,1)


if __name__=='__main__': unittest.main()
