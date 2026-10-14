"""Main Qt window shared by the three reviewable UI betas."""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QFileDialog, QMessageBox, QButtonGroup,
)

from .. import app_updater
from ..catalog import same_item_name
from ..exporter import export_all, sanitize_gacha_categories
from ..service import (
    ARCHIVE_FILENAME, Snapshot, extract_snapshot, load_latest_snapshot,
    merge_gacha_categories, _write_archive,
)
from .constants import APP_VERSION
from .beta_model import demo_snapshot, overview
from .beta_styles import VARIANTS, palette, stylesheet
from .beta_views import HomeView, RecordsView, button, label, badge, scroll
from .theme import set_palette
from .widgets import Card
from .views import HelpView, _up_average
from .icons import icon


class Worker(QThread):
    progress = Signal(str)
    result = Signal(object)
    error = Signal(str)

    def __init__(self, fn, parent):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.result.emit(self.fn(self.progress.emit))
        except Exception as exc:
            self.error.emit(str(exc))


class StellaSoraApp(QMainWindow):
    # Retain the public helpers used by the original repository's regression tests.
    _same_item_name = staticmethod(same_item_name)
    _up_average_pulls = staticmethod(_up_average)

    @staticmethod
    def _pity_color(cur):
        return '#50c69f' if cur <= 30 else '#e7c65e' if cur <= 60 else '#df654f'

    @staticmethod
    def _pity_bar_width(cur, width, limit=160):
        return round(min(1, max(0,cur)/max(1,limit))*width)

    def __init__(self, output: Path, *, variant='orbit', demo=False, dark=False):
        super().__init__()
        self.output = Path(output).resolve()
        self.variant, self.demo = variant, demo
        self.page, self.record_filter = 0, 'all'
        self.record_query, self.record_all_pulls = '', False
        self._workers = set()
        self._busy = False
        self._status_text = ''
        self.snapshot = demo_snapshot() if demo else self._load_local()
        self.setWindowTitle('星塔旅人 · 招募记录工具 / UI Beta')
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parents[2] / 'assets/app_icon.ico')))
        self.resize(1360,920)
        self.setMinimumSize(960,680)
        self.build()
        self.status('当前展示演示记录，不会写入本地归档。' if demo else self._status_text or '已载入本地归档。先在游戏中打开四类招募记录，再刷新游戏数据。')

    def _load_local(self):
        archive = self.output / ARCHIVE_FILENAME
        if archive.exists():
            try:
                payload = json.loads(archive.read_text(encoding='utf-8'))
                if not isinstance(payload,dict) or not isinstance(payload.get('categories'),dict):
                    raise ValueError('归档缺少 categories 字段')
                cats = sanitize_gacha_categories(payload['categories'])
                return Snapshot([g for groups in cats.values() for g in groups],gacha_categories=cats)
            except (OSError, ValueError, TypeError) as exc:
                self._status_text = f'读取归档失败：{exc}。请检查归档文件或导入备份。'
                return Snapshot([])
        return load_latest_snapshot(self.output) or Snapshot([])

    def build(self):
        p = palette(self.variant)
        set_palette(p)
        QApplication.instance().setStyleSheet(stylesheet(self.variant))
        old = self.centralWidget()
        root = QWidget(); root.setObjectName('AppRoot')
        layout = QVBoxLayout(root); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        shell = QHBoxLayout(); shell.setSpacing(0)
        self.nav_buttons = []
        if self.variant != 'sky': shell.addWidget(self.sidebar())
        body = QVBoxLayout(); body.setSpacing(0)
        body.addWidget(self.topbar())
        self.stack = QStackedWidget()
        self.home = HomeView(self.variant,self.open_records,self.demo)
        self.records = RecordsView()
        self.records.search.blockSignals(True)
        self.records.search.setText(self.record_query)
        self.records.search.blockSignals(False)
        self.records.query = self.record_query.casefold().strip()
        self.records.all_pulls = self.record_all_pulls
        self.records.mode.setText('查看五星记录' if self.record_all_pulls else '查看全部抽卡')
        self.settings = self.settings_view()
        self.help = HelpView()
        for view in (self.home,self.records,self.settings,self.help): self.stack.addWidget(view)
        body.addWidget(self.stack,1)
        shell.addLayout(body,1)
        layout.addLayout(shell,1)
        footer = QFrame()
        footer.setStyleSheet(f'background:{p.SURFACE};border-top:1px solid {p.LINE};')
        fl = QHBoxLayout(footer); fl.setContentsMargins(20,9,20,9)
        self.status_label = label(self._status_text,11,p.MUTED)
        fl.addWidget(self.status_label,1)
        fl.addWidget(label(f'UI BETA / {self.variant.upper()}   ·   v{APP_VERSION}',10,p.MUTED))
        layout.addWidget(footer)
        self.setCentralWidget(root)
        if old: old.deleteLater()
        self.render()
        self.navigate(self.page)
        self.refresh_button.setEnabled(not self._busy)

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
        col.addWidget(label('非官方工具 · 国服 Windows',10,p.MUTED))
        return side

    def navigation(self,layout):
        for i,text in enumerate(['招募总览','招募记录','数据与设置','使用说明']):
            b = button(text,lambda _,page=i:self.navigate(page),'nav')
            b.setIcon(icon(('home','records','settings','help')[i],palette(self.variant).PRIMARY))
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
        self.refresh_button = button('刷新游戏数据',self.refresh,'primary')
        self.refresh_button.setIcon(icon('refresh',p.ON_PRIMARY))
        row.addWidget(self.refresh_button)
        outer.addLayout(row)
        if self.variant == 'sky':
            nav = QHBoxLayout(); nav.setContentsMargins(24,0,24,10); nav.setSpacing(12)
            self.navigation(nav)
            nav.addStretch()
            outer.addLayout(nav)
        return bar

    def change_variant(self,variant):
        if variant == self.variant: return
        self.record_filter = self.records.current
        self.record_query = self.records.search.text()
        self.record_all_pulls = self.records.all_pulls
        self.variant = variant
        self.build()

    def navigate(self,page):
        self.page = page
        self.stack.setCurrentIndex(page)
        for i,b in enumerate(self.nav_buttons): b.setChecked(i == page)
        self.nav_buttons[page].setFocus(Qt.OtherFocusReason)

    def open_records(self,category='all'):
        self.record_filter = category
        self.records.set_filter(category)
        self.navigate(1)

    def render(self):
        self.home.render(self.snapshot.gacha)
        self.records.current = self.record_filter
        self.records.render(self.snapshot.gacha)
        if hasattr(self,'data_summary'):
            s = overview(self.snapshot.gacha)
            self.data_summary.setText(f'{s.total_pulls:,} 条招募 · {s.total_five} 个五星 · {sum(p is not None for p in s.category_stats.values())} 类卡池')

    def status(self,text):
        self._status_text = text
        if hasattr(self,'status_label'):
            self.status_label.setText(text[:110] + ('…' if len(text)>110 else ''))
            self.status_label.setToolTip(text)

    def toggle_demo(self):
        if self._busy:
            self.status('正在处理数据，请等待当前操作完成后切换。'); return
        self.demo = not self.demo
        self._status_text = ''
        self.snapshot = demo_snapshot() if self.demo else self._load_local()
        self.build()
        self.status('演示记录仅在内存中展示，不会写入归档。' if self.demo else self._status_text or '已切换至本地记录。')

    def task(self,fn,success):
        if self._busy: return
        self._busy = True
        self.refresh_button.setEnabled(False)
        worker = Worker(fn,self)
        self._workers.add(worker)
        worker.progress.connect(self.status)
        worker.result.connect(success)
        worker.error.connect(lambda text:self.status(f'操作失败：{text}'))
        worker.finished.connect(lambda:self.finish_task(worker))
        worker.start()

    def finish_task(self,worker):
        self._workers.discard(worker)
        worker.deleteLater()
        self._busy = False
        self.refresh_button.setEnabled(True)

    def refresh(self):
        if self.demo:
            self.snapshot = demo_snapshot()
            self.render()
            self.status('演示记录已刷新。要读取自己的游戏记录，请点击「演示 · 切换本地」。')
            return
        self.status('正在读取游戏数据…')
        self.task(lambda progress:extract_snapshot(self.output,progress=progress),self.read_complete)

    def read_complete(self,snapshot):
        self.snapshot = snapshot
        self.render()
        self.status(f'读取完成 · {snapshot.pull_count:,} 条招募记录已合并到本地归档。')

    def settings_view(self):
        p = palette(self.variant)
        w = QWidget(); outer = QVBoxLayout(w); outer.setContentsMargins(0,0,0,0)
        content = QWidget(); col = QVBoxLayout(content); col.setContentsMargins(28,24,28,24); col.setSpacing(18)
        col.addWidget(label('数据与设置',25,p.TEXT,True))
        col.addWidget(label('管理本地归档、导出与软件更新',12,p.MUTED))
        appearance = Card(pad=22)
        appearance.setObjectName('ThemeSettings')
        appearance.add(label('界面主题',16,p.TEXT,True))
        appearance.add(label('选择喜欢的主题，数据和当前浏览内容会保留。',12,p.MUTED))
        themes = QHBoxLayout()
        self.theme_buttons = {}
        theme_group = QButtonGroup(appearance)
        theme_group.setExclusive(True)
        for key,name in VARIANTS.items():
            theme_button = button(name,lambda _,selected=key:self.change_variant(selected),'filter')
            theme_button.setCheckable(True)
            theme_button.setChecked(key == self.variant)
            theme_button.setAccessibleName(f'切换主题：{name}')
            self.theme_buttons[key] = theme_button
            theme_group.addButton(theme_button)
            themes.addWidget(theme_button)
        themes.addStretch()
        appearance.body().addLayout(themes)
        col.addWidget(appearance)
        local = Card(pad=22)
        local.add(label('本地归档',16,p.TEXT,True))
        path = label(str(self.output / ARCHIVE_FILENAME),12,p.PRIMARY)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path.setWordWrap(True); local.add(path)
        local.add(label('每次读取自动合并历史记录，已有记录持续保留。',12,p.MUTED))
        row = QHBoxLayout()
        for text,fn in [('打开目录',self.open_directory),('复制路径',self.copy_path),('创建备份',self.backup)]:
            b = button(text,fn,'primary' if text == '创建备份' else 'ghost')
            if text == '创建备份': b.setEnabled(not self.demo)
            row.addWidget(b)
        row.addStretch(); local.body().addLayout(row); col.addWidget(local)
        data = Card(pad=22)
        data.add(label('招募数据',16,p.TEXT,True))
        self.data_summary = label('',13,p.MUTED); data.add(self.data_summary)
        row = QHBoxLayout()
        for text,fn in [('导入 JSON 归档',self.import_archive),('导出 JSON / CSV',self.export_records)]:
            b = button(text,fn)
            b.setEnabled(not self.demo)
            row.addWidget(b)
        row.addStretch(); data.body().addLayout(row)
        if self.demo: data.add(label('演示模式不会写入归档；切换本地记录后可使用导入、导出和备份。',12,p.MUTED))
        col.addWidget(data)
        update = Card(pad=22)
        update.add(label('软件版本',16,p.TEXT,True))
        update.add(label(f'v{APP_VERSION} · UI Beta · {VARIANTS[self.variant]}',12,p.MUTED))
        row = QHBoxLayout(); row.addWidget(button('检查更新',self.check_update,'primary')); row.addStretch()
        update.body().addLayout(row); col.addWidget(update)
        col.addStretch(); outer.addWidget(scroll(content))
        return w

    def open_directory(self):
        if not self.output.exists():
            self.status('本地归档目录尚未创建；首次刷新或导出后会自动创建。'); return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output)))

    def copy_path(self):
        QApplication.clipboard().setText(str(self.output / ARCHIVE_FILENAME))
        self.status('归档路径已复制。')

    def backup(self):
        if self.demo or self._busy: return False
        source = self.output / ARCHIVE_FILENAME
        if not source.exists(): self.status('暂无本地归档，请先刷新游戏数据或导入 JSON。'); return False
        target = self.output / 'backups' / f'archive_{datetime.now():%Y%m%d_%H%M%S_%f}.json'
        try:
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
            self.status(f'备份已创建：{target.name}')
            return True
        except OSError as exc:
            self.status(f'创建备份失败：{exc}')
            return False

    def import_archive(self):
        if self.demo or self._busy: return
        path,_ = QFileDialog.getOpenFileName(self,'导入招募记录','','JSON 归档 (*.json)')
        if not path: return
        try:
            payload = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if not isinstance(payload,dict): raise ValueError('请选择本工具的 JSON 归档或导出文件')
            raw = payload.get('categories')
            if raw is None and isinstance(payload.get('groups'),list): raw = {1:payload['groups']}
            if raw is None: raise ValueError('文件中没有 categories 或 groups 招募记录')
            cats = sanitize_gacha_categories(raw)
            if not cats: raise ValueError('文件中没有有效招募记录')
            cats = merge_gacha_categories(self.snapshot.gacha_categories,cats)
            # Back up the existing archive before a user-initiated import.
            if (self.output / ARCHIVE_FILENAME).exists() and not self.backup():
                return
            _write_archive(self.output,cats)
            self.snapshot = Snapshot([g for groups in cats.values() for g in groups],gacha_categories=cats)
            self.render(); self.status(f'已导入并合并记录，共 {self.snapshot.pull_count:,} 抽。')
        except (OSError,ValueError,TypeError) as exc: self.status(f'导入失败：{exc}')

    def export_records(self):
        if self.demo or self._busy: return
        if not self.snapshot.gacha: self.status('暂无可导出的记录。'); return
        path = QFileDialog.getExistingDirectory(self,'选择导出目录',str(self.output if self.output.exists() else self.output.parent))
        if not path: return
        try:
            files = export_all(Path(path),self.snapshot.gacha,None,self.snapshot.gacha_categories)
            self.status(f'JSON / CSV 已导出：{files[0].parent}')
        except OSError as exc: self.status(f'导出失败：{exc}')

    def check_update(self):
        if self._busy: return
        self.status('正在检查软件更新…')
        self.task(lambda progress:app_updater.check_for_update(app_updater.UPDATE_MANIFEST_URL,APP_VERSION),self.update_checked)

    def update_checked(self,update):
        if update is None:
            self.status(f'当前已是最新版本 v{APP_VERSION}。'); return
        self.status(f'发现新版本 v{update.version}。')
        # Source betas cannot safely replace themselves with an upstream binary.
        # Keep the existing updater's verified download path for packaged builds.
        if not getattr(sys,'frozen',False):
            if QMessageBox.question(self,'发现新版本',f'v{update.version}\n{update.notes}\n\n打开更新下载地址？') == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(update.url))
            return
        if QMessageBox.question(self,'软件更新',f'v{update.version}\n{update.notes}\n\n下载并安装更新？') != QMessageBox.Yes: return
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0,lambda:self.task(lambda progress:app_updater.download_update(update,self.output/'updates',progress),self.install_update))

    def install_update(self,package):
        try:
            app_updater.launch_update_installer(package,Path(sys.executable))
            self.status('更新器已启动，请按提示完成更新。')
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100,self.close)
        except (OSError,ValueError) as exc: self.status(f'启动更新失败：{exc}')

    def closeEvent(self,event):
        if any(worker.isRunning() for worker in self._workers):
            self.status('正在完成当前操作，请稍后关闭窗口。')
            event.ignore()
        else: event.accept()


def get_palette_text():
    from .theme import get_palette
    return get_palette().TEXT


def run(output: Path, *, dark=False, variant=None, demo=False):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle('Fusion')
    window = StellaSoraApp(output,variant=variant or 'orbit',demo=demo)
    window.show()
    return app.exec()
