"""Three theme shells around the complete master business controller."""
from __future__ import annotations
import re
import shutil
import sys
import threading
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, QUrl, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap, QDesktopServices
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QFrame,QVBoxLayout,
    QHBoxLayout,QStackedWidget,QProgressBar,QButtonGroup,QPushButton,QLineEdit,
    QComboBox,QFileDialog,QMessageBox)
from .. import accounts, server_config, app_updater
from ..catalog import same_item_name
from ..service import (Snapshot, load_latest_snapshot, active_data_dir, import_gacha_file,
                      read_import_text, refresh_share_file, effective_uid)
from ..exporter import export_all, parse_import_text
from .constants import APP_VERSION
from .controller import (StellaSoraWindow as BusinessWindow, _Bridge,
                         _format_sync_report, _fmt_sync_items)
from .beta_model import demo_snapshot, overview
from .beta_styles import VARIANTS, palette, stylesheet
from .beta_views import HomeView, RecordsView, button, label
from .theme import set_palette, build_palette
from .widgets import Card
from .views import SettingsView, AccountView, HelpView, _style_combo_popup
from .icons import icon

class StellaSoraApp(BusinessWindow):
    update_result = Signal(object)
    update_package = Signal(object)
    def __init__(self,output: Path,*,variant='orbit',demo=False,dark=False,online_sync=True):
        self.output = Path(output).resolve()
        self.variant,self.demo,self.online_sync = variant,demo,online_sync
        self.page,self.record_filter = 0,'all'
        self.record_query,self.record_all_pulls = '',False
        self._ui_ready = False
        set_palette(palette(variant))
        if demo:
            QMainWindow.__init__(self)
            self._output_dir = self.output
            self._profile = server_config.active()
            self._start_note,self._busy = '',False
            self._snapshot = demo_snapshot()
            self._bridge = _Bridge()
            self._make_views()
            self.resize(1360,920)
        else:
            server_config.init_from(self.output)
            super().__init__(self.output)
            if self._snapshot is None: self._snapshot = Snapshot([])
        self.snapshot = self._snapshot
        self._mount_shell()
        self._ui_ready = True
        self.update_result.connect(self._update_checked)
        self.update_package.connect(self._install_update)
        self.render()
        self.setWindowTitle(f'星塔旅人数据工具 · {self._profile.label}' + (' · 演示' if demo else ''))
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parents[2]/'assets/app_icon.ico')))
        self.setMinimumSize(960,680)
        self.status('演示模式 · 切换本地后可管理账号、UID 和真实归档。' if demo else '已加载本地账号归档。')

    def _make_views(self):
        self._settings = SettingsView({
            'open':self._open_exports,'copy':self._copy_archive_path,'backup':self._backup_archive,
            'save_uid':self._save_uid,'read_uid':self._read_uid_from_game,'share':self._export_share_file,
            'server_changed':self._on_server_changed,'server_auto':self._reset_server_auto,
            'account_switch':self._switch_account,'account_new':self._new_account,
            'account_rename':self._rename_account,'account_merge':self._merge_account,
            'account_remove':self._remove_account})
        self._settings.build('exports/accounts/<账号>/stellasora_gacha_archive.json','演示记录')
        self._settings.set_accounts([('demo','演示账号')],'demo')
        self._settings.set_account_state('演示模式 · 不写入账号清单')
        self._settings.set_uid_state('切换本地后可填写或读取 UID，并生成分享文件')
        self._account = AccountView({
            'save_url':self._account_save_url,'login':self._account_login,
            'register':self._account_register,'logout':self._account_logout,
            'upload':self._account_upload,'open_site':self._account_open_site})
        self._account.set_state(None,'演示模式')
        self._account.set_status('切换本地后可以连接网页版账户')
        self._help = HelpView()
        for view in (self._settings,self._account):
            for w in view.findChildren(QPushButton)+view.findChildren(QLineEdit)+view.findChildren(QComboBox):
                w.setEnabled(False)

    def _mount_shell(self):
        p = palette(self.variant)
        app = QApplication.instance()
        set_palette(p)
        app.setPalette(build_palette(p))
        app.setStyleSheet(stylesheet(self.variant))
        old = self.centralWidget()
        root = QWidget(); root.setObjectName('AppRoot')
        col = QVBoxLayout(root); col.setContentsMargins(0,0,0,0); col.setSpacing(0)
        row = QHBoxLayout(); row.setSpacing(0)
        self.nav_buttons = []
        if self.variant != 'sky': row.addWidget(self.sidebar())
        body = QVBoxLayout(); body.setSpacing(0); body.addWidget(self.topbar())
        self.stack = QStackedWidget()
        self.home = HomeView(self.variant,self.open_records,self.demo)
        self.records = RecordsView()
        self.records.current,self.records.query = self.record_filter,self.record_query.casefold().strip()
        self.records.search.blockSignals(True); self.records.search.setText(self.record_query); self.records.search.blockSignals(False)
        self.records.all_pulls = self.record_all_pulls
        self.records.mode.setText('查看五星记录' if self.record_all_pulls else '查看全部抽卡')
        self.settings = self._settings
        self._settings._col.itemAt(0).widget().setText('数据与设置')
        for key,b in self._settings._server_buttons.items():
            profile = server_config.PROFILES[key]
            b.setText(profile.label)
            b.setToolTip('客户端：'+', '.join(profile.client_names))
        self.help = self._help
        for view in (self.home,self.records,self._settings,self._account,self._help): self.stack.addWidget(view)
        body.addWidget(self.stack,1); row.addLayout(body,1); col.addLayout(row,1)
        footer = QFrame(); footer.setStyleSheet(f'background:{p.SURFACE};border-top:1px solid {p.LINE};')
        fl = QHBoxLayout(footer); fl.setContentsMargins(20,8,20,8)
        self._status = label('',11,p.MUTED); self.status_label = self._status
        fl.addWidget(self._status,1)
        self._progress = QProgressBar(); self._progress.setRange(0,0); self._progress.setFixedWidth(120); self._progress.setVisible(self._busy)
        fl.addWidget(self._progress); fl.addWidget(label(f'v{APP_VERSION}',10,p.MUTED))
        col.addWidget(footer); self.setCentralWidget(root)
        self._btn_refresh = self.refresh_button
        if old: old.deleteLater()
        self._tabs = self.stack
        self._home,self._records = self.home,self.records
        if not hasattr(self,'theme_buttons'): self._add_theme_card()
        self.navigate(self.page)
        self.refresh_button.setEnabled(not self._busy)
        _style_combo_popup(self._settings._account_pick)

    def _add_theme_card(self):
        p = palette(self.variant)
        card = Card(pad=22); card.setObjectName('ThemeSettings')
        card.add(label('界面主题',16,p.TEXT,True))
        card.add(label('切换主题会保留当前账号、筛选条件和输入内容。',12,p.MUTED))
        row = QHBoxLayout(); group = QButtonGroup(card); group.setExclusive(True)
        self.theme_buttons = {}
        for key,name in VARIANTS.items():
            b = button(name,lambda _,selected=key:self.change_variant(selected),'filter')
            b.setCheckable(True); b.setChecked(key==self.variant); group.addButton(b)
            self.theme_buttons[key] = b; row.addWidget(b)
        row.addStretch(); card.body().addLayout(row)
        self._settings._col.insertWidget(2,card)
        actions = Card(pad=18); actions.add(label('导入、导出与版本',16,p.TEXT,True))
        row = QHBoxLayout()
        for text,fn in [('导入 JSON / CSV',self._import_data),('导出 JSON / CSV',self.export_records),('检查更新',self._check_update)]:
            b = button(text,fn); b.setEnabled(not self.demo); row.addWidget(b)
        row.addStretch(); actions.body().addLayout(row)
        self._settings._col.insertWidget(3,actions)

    def change_variant(self,variant):
        if variant==self.variant: return
        oldp,newp = palette(self.variant),palette(variant)
        colors = {getattr(oldp,key).lower():getattr(newp,key) for key in
                  ('BG','SURFACE','SURFACE2','PRIMARY','PRIMARY2','ON_PRIMARY','ACCENT','OK','WARN','DANGER','TEXT','MUTED','LINE')}
        for view in (self._settings,self._account,self._help):
            for w in [view]+view.findChildren(QWidget):
                qss = w.styleSheet()
                if qss: w.setStyleSheet(re.sub(r'#[0-9a-fA-F]{6}',lambda m:colors.get(m[0].lower(),m[0]),qss))
        self.record_filter,self.record_query,self.record_all_pulls = self.records.current,self.records.search.text(),self.records.all_pulls
        self.variant = variant
        self._mount_shell(); self.render()
        self.theme_buttons[variant].setChecked(True)

    def status(self,text):
        self._status_text = text
        self._status.setText(text); self._status.setToolTip(text)

    def render(self):
        self.home.render(self.snapshot.gacha)
        self.records.render(self.snapshot.gacha)
        stats = overview(self.snapshot.gacha)
        times = [int(g.get('Time') or 0) for g in self.snapshot.gacha if g.get('Time')]
        dates = f'{datetime.fromtimestamp(min(times)):%Y.%m.%d} — {datetime.fromtimestamp(max(times)):%Y.%m.%d}' if times else '暂无有效时间'
        self._settings.set_summary(f'{stats.total_pulls:,} 抽 · {stats.total_five} 个五星 · {sum(s is not None for s in stats.category_stats.values())}/4 类卡池\n归档批次 {len(self.snapshot.gacha)} · {dates}')
        if not self.demo:
            self._refresh_account_picker(); self._refresh_uid_state(); self._refresh_account_view(); self._refresh_server_labels()
            self._settings.set_archive_path(str(active_data_dir(self.output)/'stellasora_gacha_archive.json'))

    def _apply_snapshot(self,snap):
        if not self._ui_ready: return super()._apply_snapshot(snap)
        self._snapshot = self.snapshot = snap
        self.render()

    def _load_latest(self):
        if not self._ui_ready: return super()._load_latest()
        self._apply_snapshot(load_latest_snapshot(self.output) or Snapshot([]))

    def _start_banner_refresh(self):
        if not self.demo and self.online_sync: super()._start_banner_refresh()

    def refresh(self):
        if self.demo:
            self.snapshot = self._snapshot = demo_snapshot(); self.render()
            self.status('演示记录已刷新。切换本地后可读取游戏数据。'); return
        super().refresh()

    def _on_sync_done(self,report):
        super()._on_sync_done(report)
        if self._ui_ready: self.render()

    def _on_read_error(self,msg):
        super()._on_read_error(msg)
        self.status(f'读取失败：{msg}')

    def toggle_demo(self):
        if self._busy: self.status('当前操作完成后再切换。'); return
        replacement = StellaSoraApp(self.output,variant=self.variant,demo=not self.demo,online_sync=self.online_sync)
        replacement.navigate(self.page); replacement.show()
        self._replacement = replacement
        self.close()

    def export_records(self):
        if self.demo or self._busy: return
        if not self.snapshot.gacha: self.status('暂无可导出的记录。'); return
        directory = QFileDialog.getExistingDirectory(self,'选择导出目录',str(active_data_dir(self.output)))
        if not directory: return
        try:
            export_all(Path(directory),self.snapshot.gacha,None,self.snapshot.gacha_categories,uid=self.snapshot.uid)
            self.status('JSON / CSV 已导出。')
        except OSError as exc: self.status(f'导出失败：{exc}')

    def _set_busy(self,busy):
        super()._set_busy(busy)
        if not self._ui_ready: return
        for w in self._settings.findChildren(QPushButton)+self._settings.findChildren(QLineEdit)+self._settings.findChildren(QComboBox): w.setEnabled(not busy)
        self.mode_button.setEnabled(not busy)

    def _read_uid_from_game(self):
        if self.demo or self._busy: return
        self._set_busy(True)
        super()._read_uid_from_game()

    def _on_uid_read(self,payload):
        if self.demo: return
        self._set_busy(False)
        search = payload.get('search')
        if search is not None and search.found:
            self._save_uid(search.uid)
            if effective_uid(self.output) != search.uid:
                self.status('读取到了 UID，但没有成功保存。'); return
            try:
                path = refresh_share_file(self.output)
            except OSError as exc:
                self.status(f'UID 已保存，生成分享文件失败：{exc}')
                return
            self.status(f'已读取并保存 UID {search.uid}' + (f' · 已导出 {path.name}' if path else ''))
            return
        super()._on_uid_read(payload)

    def _import_data(self):
        if self.demo or self._busy: return
        path,_ = QFileDialog.getOpenFileName(self,'导入招募记录',str(self.output),'抽卡数据 (*.json *.csv)')
        if not path: return
        try:
            source = Path(path)
            cats,uid = parse_import_text(read_import_text(source),source.suffix)
            if not cats: raise ValueError('文件中没有有效招募记录')
            target = accounts.find_by_uid(self.output,uid) if uid else accounts.active_account(self.output)
            if uid and target is None:
                current = accounts.active_account(self.output)
                if current is not None and not current.uid:
                    target = current
            directory = accounts.data_dir(self.output,target.key) if target else None
            archive = directory/'stellasora_gacha_archive.json' if directory else None
            if archive and archive.exists():
                backup = self.output/'backups'/f'{target.key}_{datetime.now():%Y%m%d_%H%M%S_%f}.json'
                backup.parent.mkdir(parents=True,exist_ok=True)
                try: shutil.copy2(archive,backup)
                except OSError as exc:
                    self.status(f'创建备份失败，已停止导入：{exc}'); return
            result = import_gacha_file(self.output,source)
            self._apply_snapshot(Snapshot([g for groups in result.categories.values() for g in groups],
                                          gacha_categories=result.categories,uid=result.uid,share_file=result.share_file))
            self.status(f'导入完成 · 新增 {result.added_pulls} 抽 · UID {result.uid or "未设置"}')
        except (OSError,ValueError,TypeError) as exc:
            self.status(f'导入失败：{exc}')

    import_archive = _import_data

    def _check_update(self):
        if self.demo or self._busy: return
        urls = app_updater.update_urls()
        if not urls:
            QMessageBox.information(self,'检查更新','未配置 GitHub 更新清单，请设置 STELLASORA_UPDATE_MANIFEST_GITHUB。')
            return
        self._set_busy(True)
        self.status('正在检查 GitHub 软件更新…')
        def work():
            try: result = app_updater.check_for_update(urls,APP_VERSION)
            except Exception as exc: result = exc
            self.update_result.emit(result)
        threading.Thread(target=work,daemon=True).start()

    def _update_checked(self,result):
        self._set_busy(False)
        if isinstance(result,Exception): self.status(f'检查更新失败：{result}'); return
        if result is None: self.status(f'当前已是最新版 v{APP_VERSION}。'); return
        self.status(f'发现新版本 v{result.version}')
        if not getattr(sys,'frozen',False):
            if QMessageBox.question(self,'发现新版本',f'v{result.version}\n{result.notes}\n\n打开下载地址？')==QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(result.url))
            return
        if QMessageBox.question(self,'软件更新',f'v{result.version}\n{result.notes}\n\n下载并安装更新？')!=QMessageBox.Yes: return
        self._set_busy(True)
        def work():
            try:
                package = app_updater.download_update(result,self.output/'updates',progress=self._bridge.progress.emit)
            except Exception as exc: package = exc
            self.update_package.emit(package)
        threading.Thread(target=work,daemon=True).start()

    def _install_update(self,package):
        self._set_busy(False)
        if isinstance(package,Exception): self.status(f'下载更新失败：{package}'); return
        try:
            app_updater.launch_update_installer(package,Path(sys.executable))
        except (OSError,ValueError) as exc:
            self.status(f'启动更新失败：{exc}'); return
        QTimer.singleShot(0,self.close)

    def closeEvent(self,event):
        if self._busy:
            self.status('正在完成当前操作，请稍后关闭窗口。'); event.ignore()
        else: event.accept()

    def brand(self):
        from PySide6.QtWidgets import QLabel
        w = QWidget(); row = QHBoxLayout(w); row.setContentsMargins(0,0,0,0); row.setSpacing(10)
        icon = QLabel(); icon.setFixedSize(34,34)
        pix = QPixmap(str(Path(__file__).resolve().parents[2] / 'assets/app_icon.png'))
        icon.setPixmap(pix.scaled(34,34,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        row.addWidget(icon)
        titles = QVBoxLayout(); titles.setSpacing(2)
        titles.addWidget(label('STELLA SORA',12,get_palette_text(),True))
        titles.addWidget(label('星塔旅人 · 招募档案',10,palette(self.variant).MUTED))
        row.addLayout(titles)
        return w

    def sidebar(self):
        p = palette(self.variant)
        side = QWidget(); side.setObjectName('Sidebar'); side.setFixedWidth(204 if self.variant == 'orbit' else 190)
        col = QVBoxLayout(side); col.setContentsMargins(16,25,16,24); col.setSpacing(8)
        col.addWidget(self.brand()); col.addSpacing(30)
        col.addWidget(label('我的档案',10,p.MUTED)); col.addSpacing(6)
        self.navigation(col)
        col.addStretch()
        info = Card(pad=12)
        info.add(label('记录留在你身边',12,p.TEXT,True))
        info.add(label('历史合并归档 · 支持备份',10,p.MUTED))
        col.addWidget(info); col.addSpacing(12)
        col.addWidget(label('非官方工具 · Windows',10,p.MUTED))
        return side

    def navigation(self,layout):
        for i,text in enumerate(['招募总览','招募记录','数据与设置','网页版账户','使用说明']):
            b = button(text,lambda _,page=i:self.navigate(page),'nav')
            b.setIcon(icon(('home','records','settings','account','help')[i],palette(self.variant).PRIMARY))
            b.setCheckable(True)
            self.nav_buttons.append(b)
            layout.addWidget(b)

    def topbar(self):
        p = palette(self.variant)
        bar = QFrame(); bar.setObjectName('Topbar')
        outer = QVBoxLayout(bar); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        row = QHBoxLayout(); row.setContentsMargins(24,16,24,16); row.setSpacing(12)
        if self.variant == 'sky':
            row.addWidget(self.brand())
        else:
            row.addWidget(label('招募记录工具',14,p.TEXT,True))
        row.addStretch()
        self.mode_button = button('演示 · 切换本地' if self.demo else '本地 · 预览演示',self.toggle_demo,'ghost')
        self.mode_button.setToolTip('演示数据仅用于 UI 预览；切换后可读取自己的本地归档。')
        row.addWidget(self.mode_button)
        self.refresh_button = button('抓取抽卡记录',self.refresh,'primary')
        self.refresh_button.setIcon(icon('refresh',p.ON_PRIMARY))
        row.addWidget(self.refresh_button)
        outer.addLayout(row)
        if self.variant == 'sky':
            nav = QHBoxLayout(); nav.setContentsMargins(24,0,24,10); nav.setSpacing(12)
            self.navigation(nav)
            nav.addStretch()
            outer.addLayout(nav)
        return bar

    def navigate(self,page):
        self.page = page
        self.stack.setCurrentIndex(page)
        for i,b in enumerate(self.nav_buttons): b.setChecked(i == page)
        self.nav_buttons[page].setFocus(Qt.OtherFocusReason)

    def open_records(self,category='all'):
        self.record_filter = category
        self.records.set_filter(category)
        self.navigate(1)

def get_palette_text():
    from .theme import get_palette
    return get_palette().TEXT

StellaSoraWindow = StellaSoraApp

def run(output: Path,*,dark=False,variant=None,demo=False):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle('Fusion')
    window = StellaSoraApp(output,variant=variant or 'orbit',demo=demo)
    window.show()
    return app.exec()
