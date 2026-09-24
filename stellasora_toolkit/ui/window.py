"""主窗口:顶栏 + 指标 + 状态 + 选项卡 + 读取/更新/备份逻辑。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QTabWidget, QMessageBox, QProgressBar, QApplication,
    QFileDialog,
)

from .. import server_config
from .. import account_config, server_upload
from ..app_updater import (
    check_for_update, download_update, launch_update_installer, update_urls,
)
from ..catalog import gacha_item_name, table_values
from ..gacha_stats import build_category_stat, build_banner_stats_with_shared_pity
from ..official_banners import cache_filename, load_banners, refresh_from_network, set_active_banners
from ..service import (
    detect_and_apply, extract_snapshot, load_latest_snapshot, probe_running_keys,
    ARCHIVE_FILENAME, Snapshot,
)
from .constants import (
    GACHA_CATEGORY_ORDER, GACHA_CATEGORY_NAMES, APP_VERSION,
)
from .theme import get_palette
from .widgets import MetricCard, mk_label
from .views import AccountView, HomeView, RecordsView, SettingsView, HelpView


@dataclass
class Stats:
    total_pulls: int = 0
    total_five: int = 0
    loaded: int = 0
    batches: int = 0
    rate: str = "-"
    average: str = "-"
    date_range: str = "暂无有效时间"
    category_stats: dict = field(default_factory=dict)
    recent_five: list = field(default_factory=list)
    # 每个旅人限时卡池(抽满120抽必得井的UP): gid -> 总抽数
    well_banners: dict = field(default_factory=dict)


class _Bridge(QObject):
    done = Signal(object)
    error = Signal(object)
    notify = Signal(str, str, str)  # (kind, title, text) —— 在主线程弹消息框
    sync_done = Signal(object)      # 资源库同步完成的报告(dict)
    progress = Signal(str)          # 后台任务的进度文本(写进状态栏)
    busy = Signal(bool)             # 后台任务生命周期锁(刷新期间含同步)
    account = Signal(str, object)   # (动作, 结果或异常) —— 账户/上传的异步结果


class StellaSoraWindow(QMainWindow):
    def __init__(self, output_dir: Path):
        super().__init__()
        self._output_dir = output_dir
        # 自动检测: 恰有一个客户端在运行时启动即切换版本(两个则保持设置页所选)
        self._profile, start_note, _keys = detect_and_apply(output_dir)
        self.setWindowTitle(f"星塔旅人数据工具 · {self._profile.label}")
        self._start_note = start_note
        self._adapt_window()
        self._busy = False
        self._snapshot = None
        self._start_banner_refresh()
        self._bridge = _Bridge()
        self._bridge.done.connect(self._on_snapshot, Qt.QueuedConnection)
        self._bridge.error.connect(self._on_read_error, Qt.QueuedConnection)
        self._bridge.notify.connect(self._on_notify, Qt.QueuedConnection)
        self._bridge.sync_done.connect(self._on_sync_done, Qt.QueuedConnection)
        self._bridge.progress.connect(self._on_progress, Qt.QueuedConnection)
        self._bridge.busy.connect(self._set_busy, Qt.QueuedConnection)
        self._bridge.account.connect(self._on_account_result, Qt.QueuedConnection)

        root = QWidget(); root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        root_lay = QVBoxLayout(root); root_lay.setContentsMargins(0, 0, 0, 0); root_lay.setSpacing(0)
        root_lay.addWidget(self._build_header())
        root_lay.addWidget(self._build_metrics())
        root_lay.addLayout(self._build_status())
        self._tabs = QTabWidget()
        self._home = HomeView(); self._records = RecordsView()
        self._settings = SettingsView({
            "open": self._open_exports, "copy": self._copy_archive_path,
            "backup": self._backup_archive, "update": self._check_update,
            "server_changed": self._on_server_changed,
        })
        self._account = AccountView({
            "save_url": self._account_save_url,
            "login": self._account_login,
            "register": self._account_register,
            "logout": self._account_logout,
            "upload": self._account_upload,
            "open_site": self._account_open_site,
        })
        self._help = HelpView()
        self._tabs.addTab(self._home, "首页")
        self._tabs.addTab(self._records, "招募记录")
        self._tabs.addTab(self._settings, "设置")
        self._tabs.addTab(self._account, "账户")
        self._tabs.addTab(self._help, "使用说明")
        root_lay.addWidget(self._tabs, 1)

        self._settings.build(
            str(self._output_dir / ARCHIVE_FILENAME),
            "尚未加载本地归档",
        )
        self._refresh_account_view()
        if self._start_note:
            self._status.setText(self._start_note)
        self._load_latest()

    # ---------------- 启动后台同步: 卡池信息 + 新五星角色 ----------------
    def _start_banner_refresh(self) -> None:
        """后台加载官方限时卡池信息: 先同步读缓存(离线可用), 再由后台线程联网刷新。

        缓存按版本分文件(cache_filename), 国服/国际服互不串数据。
        """
        cache_path = self._output_dir / cache_filename()
        cached = load_banners(cache_path)
        if cached:
            set_active_banners(cached)
        threading.Thread(target=self._sync_in_background, args=(cache_path,), daemon=True).start()

    def _sync_in_background(self, cache_path: Path) -> None:
        """整合一次后台同步: 卡池信息刷新 + 检测新五星角色(注册名称/星级并下载头像)。"""
        refresh_from_network(cache_path)
        try:
            from ..catalog_sync import sync_catalog
            appeared, downloaded = sync_catalog(self._output_dir / "catalog_sync_state.json")
        except Exception:
            return  # 增强功能, 失败静默退回内置清单
        if appeared:
            names = "、".join(it["name"] for it in appeared[:6])
            more = f" 等 {len(appeared)} 项" if len(appeared) > 6 else ""
            self._bridge.notify.emit(
                "info", "检测到新五星角色",
                f"已自动检测到新五星: {names}{more}\n头像下载 {len(downloaded)} 张, 刷新游戏数据后生效。",
            )

    @staticmethod
    def _subtitle_text() -> str:
        profile = server_config.active()
        return f"四类卡池与五星记录 · {profile.label}（{profile.client_names[0]}）"

    def _refresh_server_labels(self) -> None:
        """让标题/副标题/设置页单选按钮跟随当前生效版本(自动检测可能切换了版本)。"""
        self._profile = server_config.active()
        self.setWindowTitle(f"星塔旅人数据工具 · {self._profile.label}")
        if hasattr(self, "_sub"):
            self._sub.setText(self._subtitle_text())
        if hasattr(self, "_settings"):
            self._settings.refresh_server_buttons()

    def _prompt_both_running(self) -> str | None:
        """两个客户端同时运行时弹窗选择本次读取的服务器; 取消返回 None。"""
        profiles = server_config.PROFILES
        btn_map: dict = {}
        box = QMessageBox(self)
        box.setWindowTitle("选择游戏版本")
        box.setText(
            "同时检测到 国服(xtlr.exe) 与 国际服(StellaSora.exe) 客户端在运行。\n"
            "请选择本次要读取的服务器:")
        for key in server_config.PROFILES:
            prof = profiles[key]
            btn_map[box.addButton(f"{prof.label} · {prof.client_names[0]}", QMessageBox.AcceptRole)] = key
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        key = btn_map.get(box.clickedButton())
        return key if key is not None else None

    def _on_server_changed(self, key: str) -> None:
        """设置页手动切换国服/国际服: 持久化 + 按新版本语言重新拉取卡池与名称表。"""
        if not server_config.set_active(key):
            return
        server_config.save_key(self._output_dir / server_config.CONFIG_FILENAME, key)
        self._refresh_server_labels()
        self._status.setText(
            f"已切换到 {self._profile.label} · 客户端 {self._profile.client_names[0]}，正在按该版本语言同步...")
        self._start_banner_refresh()

    # ---------------- 窗口自适应 ----------------
    MIN_W, MIN_H = 900, 620

    def _adapt_window(self) -> None:
        """按当前屏幕可用区域自动选择窗口尺寸并居中,保证不超出屏幕、可自由缩放。"""
        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen is not None else None
        if geo is not None:
            pref_w = int(geo.width() * 0.78)
            pref_h = int(geo.height() * 0.78)
            w = min(pref_w, geo.width())
            h = min(pref_h, geo.height())
        else:
            w, h = 1180, 760
        w = max(self.MIN_W, w)
        h = max(self.MIN_H, h)
        self.setMinimumSize(self.MIN_W, self.MIN_H)
        self.resize(w, h)
        self._center_on_screen()

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.left() + (geo.width() - self.width()) // 2,
                  geo.top() + (geo.height() - self.height()) // 2)

    # ---------------- 头部 ----------------
    def _build_header(self) -> QWidget:
        header = QWidget(); header.setObjectName("AppHeader"); header.setFixedHeight(64)
        lay = QHBoxLayout(header); lay.setContentsMargins(20, 0, 20, 0); lay.setSpacing(14)
        left = QVBoxLayout(); left.setSpacing(0)
        title = QLabel("星塔旅人数据工具"); title.setObjectName("AppTitle")
        self._sub = QLabel(self._subtitle_text()); self._sub.setObjectName("AppSubtitle")
        left.addWidget(title); left.addWidget(self._sub)
        lay.addLayout(left)
        # 版本号放左侧
        ver = QLabel(f"v{APP_VERSION}"); ver.setObjectName("AppVersion")
        lay.addWidget(ver)
        lay.addStretch(1)
        self._btn_import = self._hbtn("导入数据", "header-action", self._import_data)
        self._btn_open = self._hbtn("打开导出目录", "header-action", self._open_exports)
        self._btn_refresh = self._hbtn("刷新游戏数据", "primary", self.refresh)
        lay.addWidget(self._btn_import); lay.addWidget(self._btn_open); lay.addWidget(self._btn_refresh)
        return header

    def _hbtn(self, txt, role, fn) -> QPushButton:
        b = QPushButton(txt); b.setProperty("role", role)
        b.setCursor(Qt.PointingHandCursor); b.clicked.connect(fn)
        return b

    # ---------------- 指标 ----------------
    def _build_metrics(self) -> QWidget:
        wrap = QWidget(); wrap.setStyleSheet(f"background:{get_palette().SURFACE};")
        lay = QGridLayout(wrap); lay.setContentsMargins(20, 14, 20, 14); lay.setSpacing(12)
        self._m = {}
        names = ["累计抽取", "五星记录", "五星概率", "平均五星抽数", "已加载分类", "归档批次"]
        for i, n in enumerate(names):
            mc = MetricCard(n); self._m[n] = mc
            lay.addWidget(mc, i // 3, i % 3)
        for c in range(3):
            lay.setColumnStretch(c, 1)
        return wrap

    def _build_status(self) -> QVBoxLayout:
        row = QHBoxLayout(); row.setContentsMargins(24, 12, 24, 6)
        self._status = mk_label("等待读取", role="muted")
        row.addWidget(self._status); row.addStretch(1)
        self._progress = QProgressBar(); self._progress.setRange(0, 0)
        self._progress.setFixedWidth(160); self._progress.hide()
        row.addWidget(self._progress)
        lay = QVBoxLayout(); lay.addLayout(row)
        return lay

    # ---------------- 状态/数据 ----------------
    def _load_latest(self) -> None:
        snap = load_latest_snapshot(self._output_dir)
        if snap is None:
            self._status.setText("暂无本地数据,请启动并登录游戏后刷新")
            return
        self._apply_snapshot(snap)
        self._status.setText("已加载最近一次本地数据")

    def refresh(self) -> None:
        """刷新游戏数据 = 读取快照 + 资源库同步(查询缺失/自动补全/对齐校验)。

        版本规则: 一个客户端在运行 → 自动读取; 两个客户端同时运行 → 弹窗手动选择。
        同步无任何缺失/补全时不弹窗, 只有发现新五星、缺图补全或未对齐项才提示。
        """
        if self._busy:
            return
        # 两个客户端同时运行: 主线程弹窗让用户选定, 无需先启动后台任务
        if len(probe_running_keys()) == 2:
            choice = self._prompt_both_running()
            if choice is None:      # 用户取消
                self._status.setText("两种客户端均在运行, 未选择服务器, 未读取")
                return
            server_config.set_active(choice)
            server_config.save_key(self._output_dir / server_config.CONFIG_FILENAME, choice)
            self._refresh_server_labels()
            self._status.setText(f"已选择读取 {server_config.active().label}，正在读取游戏数据")
        else:
            self._status.setText("正在读取游戏数据")
        self._set_busy(True)

        def work() -> None:
            try:
                snap = extract_snapshot(self._output_dir)
                self._bridge.done.emit(snap)          # 界面先显示数据
            except Exception as err:
                self._bridge.error.emit(err)
                return
            # 快照读取后立即锁住按钮直至同步结束, 防止重复刷新
            self._bridge.busy.emit(True)
            try:
                from ..catalog_sync import sync_with_report
                record_ids = [int(i) for g in snap.gacha for i in table_values(g.get("Ids"))]
                report = sync_with_report(
                    self._output_dir / "catalog_sync_state.json", record_ids,
                    progress=lambda msg: self._bridge.progress.emit(f"刷新游戏数据 · {msg}"),
                )
            except Exception as err:
                report = {"error": str(err)}
            self._bridge.sync_done.emit(report)
        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, msg: str) -> None:
        self._status.setText(msg)

    def _on_sync_done(self, report) -> None:
        self._set_busy(False)
        if report.get("error"):
            self._status.setText("资源库同步失败")
            QMessageBox.warning(self, "刷新游戏数据", f"资源库同步失败:\n{report['error']}\n\n已退回内置清单。")
            return
        text, problems = _format_sync_report(report)
        notable = bool(
            report["missing_before"] or report["registered"] or report["downloaded"]
            or report["icon_failed"] or problems
        )
        if not notable:
            self._status.setText("刷新完成 · 资源库无缺失")
            return
        self._status.setText(f"刷新完成 · 发现缺失 {len(report['missing_before'])} 项")
        if problems:
            QMessageBox.warning(self, "刷新游戏数据(有未对齐项)", text)
        else:
            QMessageBox.information(self, "刷新游戏数据", f"发现新资源, 已自动补全:\n\n{text}")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._btn_refresh.setEnabled(not busy)
        self._progress.setVisible(busy)

    # ---------------- 账户 / 上传 ----------------
    # 所有网络操作都在后台线程里跑, 结果经 _bridge.account 回主线程。
    # 在 GUI 线程里直接 urlopen 会让窗口假死几秒 —— 用户会以为程序卡了。

    def _archive_summary(self) -> str:
        """本地归档的一句话摘要, 显示在账户页上。"""
        try:
            categories = server_upload.read_archive(self._output_dir)
        except server_upload.UploadError as err:
            return err.message
        groups = pulls = 0
        for items in categories.values():
            if not isinstance(items, list):
                continue
            groups += len(items)
            for group in items:
                pulls += len(table_values(group.get("Ids")))
        return f"本地归档：{pulls} 抽 / {groups} 组记录"

    def _refresh_account_view(self, note: str = "") -> None:
        account = account_config.load(self._output_dir)
        self._account.set_state(account, self._archive_summary())
        self._account.set_status(note or (
            f"已登录：{account.username}" if account and account.logged_in
            else "尚未登录。填好服务器地址后用网页版注册的账号登录。"))

    def _account_note(self, text: str) -> None:
        self._account.set_status(text)

    def _account_save_url(self, url: str) -> None:
        normalized = account_config.split_share_url(url)
        if not normalized:
            self._account_note("请先填写服务器地址")
            return
        previous = account_config.load(self._output_dir) or account_config.Account()
        ok = account_config.save(self._output_dir, account_config.Account(
            server_url=normalized, token=previous.token, username=previous.username))
        self._refresh_account_view(
            f"服务器地址已保存：{normalized}" if ok else "保存失败：配置目录不可写")

    def _account_login(self, url: str, username: str, password: str) -> None:
        target = account_config.split_share_url(url)
        if not (target and username.strip() and password):
            self._account_note("请填好服务器地址、用户名和密码")
            return
        self._account.set_busy(True)
        self._account_note("正在登录…")

        def work() -> None:
            try:
                result = server_upload.login(target, username.strip(), password)
            except Exception as err:                    # noqa: BLE001
                self._bridge.account.emit("login", err)
                return
            self._bridge.account.emit("login", (target, result))

        threading.Thread(target=work, daemon=True).start()

    def _account_register(self, url: str, username: str, password: str) -> None:
        target = account_config.split_share_url(url)
        if not (target and username.strip() and password):
            self._account_note("请填好服务器地址、用户名和密码")
            return
        self._account.set_busy(True)
        self._account_note("正在注册…")

        def work() -> None:
            try:
                server_upload.register(target, username.strip(), password)
            except Exception as err:                    # noqa: BLE001
                self._bridge.account.emit("register", err)
                return
            self._bridge.account.emit("register", {"username": username.strip()})

        threading.Thread(target=work, daemon=True).start()

    def _account_logout(self) -> None:
        account = account_config.load(self._output_dir)
        if account is None:
            self._refresh_account_view("本来就没有登录")
            return
        # 先清本地再通知服务端 —— 服务端连不上时本地也要能退出
        account_config.save(self._output_dir, account_config.Account(
            server_url=account.server_url))
        self._account.clear_password()
        self._refresh_account_view("已退出登录")

        def work() -> None:
            server_upload.logout(account.server_url, account.token)

        threading.Thread(target=work, daemon=True).start()

    def _account_upload(self, mode: str = "merge") -> None:
        account = account_config.load(self._output_dir)
        if account is None:
            self._account_note("请先登录")
            return
        self._account.set_busy(True)
        self._account_note("正在读取本地归档…")

        def work() -> None:
            try:
                # 传【归档】而不是本次读取的快照: 归档是与历史合并后的
                # 完整数据, 快照只有这次读到的部分
                categories = server_upload.read_archive(self._output_dir)
                self._bridge.progress.emit("正在上传抽卡记录…")
                result = server_upload.upload(account.server_url, account.token,
                                              categories, mode=mode)
            except Exception as err:                    # noqa: BLE001
                self._bridge.account.emit("upload", err)
                return
            self._bridge.account.emit("upload", result)

        threading.Thread(target=work, daemon=True).start()

    def _account_open_site(self) -> None:
        account = account_config.load(self._output_dir)
        url = account.server_url if account and account.server_url else ""
        if not url:
            self._account_note("请先填写并保存服务器地址")
            return
        QGuiApplication.clipboard().setText(url)
        try:
            if sys.platform == "win32":
                os.startfile(url)                       # noqa: S606
            else:
                subprocess.Popen(["xdg-open", url])
            self._account_note(f"已在浏览器中打开 {url}（地址也复制到了剪贴板）")
        except OSError as err:
            self._account_note(f"打不开浏览器：{err}。地址已复制到剪贴板。")

    def _on_account_result(self, action: str, payload) -> None:
        """账户操作的异步结果 —— 已在主线程。"""
        self._account.set_busy(False)
        if isinstance(payload, Exception):
            message = getattr(payload, "message", None) or str(payload)
            self._account_note(f"失败：{message}")
            # 凭据失效: 清掉 token 回到登录界面, 但保留服务器地址
            if (isinstance(payload, server_upload.UploadError)
                    and payload.is_auth_error):
                stale = account_config.load(self._output_dir)
                if stale is not None:
                    account_config.save(self._output_dir, account_config.Account(
                        server_url=stale.server_url))
                    self._refresh_account_view("登录已失效，请重新登录")
            return

        if action == "login":
            url, result = payload
            account_config.save(self._output_dir, account_config.Account(
                server_url=url, token=result["token"],
                username=str(result.get("username") or "")))
            self._account.clear_password()
            self._refresh_account_view(f"已登录：{result.get('username', '')}")
        elif action == "register":
            self._account.clear_password()
            self._account_note("注册成功，现在可以直接登录了。")
        elif action == "upload":
            added = int(payload.get("added") or 0)
            unknown = int(payload.get("unknown") or 0)
            note = (f"上传完成：新增 {added} 组，服务器现有 "
                    f"{payload.get('pulls', 0)} 抽 / {payload.get('groups', 0)} 组记录。")
            if unknown:
                note += f"\n检测到 {unknown} 个尚未登记的新物品，正在后台补名称和头像。"
            self._refresh_account_view(note)
        else:
            self._refresh_account_view()

    def _on_snapshot(self, snap) -> None:
        self._apply_snapshot(snap)
        self._refresh_server_labels()  # 后台自动检测可能已切换版本
        self._set_busy(False)
        self._status.setText(f"读取完成 · {datetime.now():%H:%M:%S}")

    def _on_read_error(self, msg) -> None:
        self._set_busy(False)
        self._status.setText("读取失败")
        QMessageBox.critical(self, "读取失败", str(msg))

    def _on_notify(self, kind: str, title: str, text: str) -> None:
        if kind == "warning":
            QMessageBox.warning(self, title, text)
        else:
            QMessageBox.information(self, title, text)
        self._status.setText("检查完成")

    def _apply_snapshot(self, snap) -> None:
        self._snapshot = snap
        from ..gacha_stats import classify_history_category
        sem = {c: [] for c in GACHA_CATEGORY_ORDER}
        for g in snap.gacha:
            cat = classify_history_category([g])
            if cat in sem:
                sem[cat].append(g)
        st = Stats()
        st.category_stats = {
            c: build_category_stat(sem[c]) for c in GACHA_CATEGORY_ORDER
        }
        # 每个旅人限时卡池是否已抽满 120(井): gid -> 总抽数
        from ..gacha_stats import build_banner_stats_with_shared_pity
        st.well_banners = {
            p.gid: p.total_pulls
            for p in build_banner_stats_with_shared_pity(sem[GACHA_CATEGORY_ORDER[0]])
            if p.gid and 10000 <= p.gid < 20000 and p.total_pulls >= 120
        }
        st.loaded = sum(1 for c in GACHA_CATEGORY_ORDER if sem[c])
        st.total_five = sum(len(s.five_stars) for s in st.category_stats.values() if s)
        st.total_pulls = sum(s.total_pulls for s in st.category_stats.values() if s)
        st.rate = f"{st.total_five / st.total_pulls * 100:.2f}%" if st.total_pulls else "-"
        st.average = str(round(st.total_pulls / st.total_five)) if st.total_five else "-"
        st.batches = len(snap.gacha)
        self._set_metrics(st)
        self._home.render(st)
        self._records.render(snap.gacha)
        # 设置页摘要
        self._settings.set_summary(
            f"{st.total_pulls} 抽 · {st.total_five} 个五星\n{st.date_range}\n归档批次 {st.batches}")
        self._status.setText("已加载最近一次本地数据")

    def _set_metrics(self, st: Stats) -> None:
        self._m["累计抽取"].set_value(str(st.total_pulls))
        self._m["五星记录"].set_value(str(st.total_five))
        self._m["五星概率"].set_value(st.rate)
        self._m["平均五星抽数"].set_value(st.average)
        self._m["已加载分类"].set_value(f"{st.loaded}/4")
        self._m["归档批次"].set_value(str(st.batches))

    def _check_update(self) -> None:
        from ..app_updater import AppUpdate  # noqa
        if not getattr(sys, "frozen", False):
            QMessageBox.information(self, "检查更新", "源码运行模式不会自动替换程序,请使用打包后的 exe。")
            return
        manifest_urls = update_urls()
        if not manifest_urls:
            QMessageBox.information(
                self, "检查更新",
                "未配置更新源。\n\n请设置环境变量 STELLASORA_UPDATE_MANIFEST_GITHUB"
                " 指向更新清单地址后重试。",
            )
            return
        self._status.setText("正在检查软件更新")
        def work() -> None:
            try:
                up = check_for_update(manifest_urls, APP_VERSION)
                if up is None:
                    self._bridge.notify.emit("info", "检查更新", f"当前已是最新版 {APP_VERSION}")
                else:
                    self._bridge.notify.emit("info", "检查更新", f"发现新版本 {up.version}")
            except Exception as e:
                self._bridge.notify.emit("warning", "检查更新失败", str(e))
        threading.Thread(target=work, daemon=True).start()

    def _open_exports(self) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(self._output_dir)
        else:
            subprocess.Popen(["xdg-open", str(self._output_dir)])

    def _copy_archive_path(self) -> None:
        QApplication.clipboard().setText(str(self._output_dir / ARCHIVE_FILENAME))
        self._status.setText("归档路径已复制")

    def _import_data(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入数据", str(self._output_dir), "抽卡数据 (*.json *.csv);;所有文件 (*)")
        if not path:
            return
        try:
            groups, categories = self._parse_import_file(Path(path))
            if not groups:
                raise ValueError("未能从文件中解析到抽卡记录,请选择桌面版导出的 JSON/CSV")
            snap = Snapshot(gacha=groups, emblems=[], files=(Path(path),), gacha_categories=categories or {1: groups})
            self._apply_snapshot(snap)
            self._status.setText(f"已导入 {Path(path).name} · {len(groups)} 条记录")
        except Exception as e:
            import traceback
            tb = "".join(traceback.format_exception_only(type(e), e))
            log_path = self._output_dir / "crash.log"
            try:
                self._output_dir.mkdir(parents=True, exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as f:
                    traceback.print_exc(file=f)
            except Exception:
                pass
            QMessageBox.critical(self, "导入失败", f"{tb}\n\n(详细堆栈已写入 {log_path.name})")

    @staticmethod
    def _parse_import_file(path: Path) -> tuple[list, dict]:
        from ..exporter import sanitize_gacha, sanitize_gacha_categories
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".csv":
            lines = [ln for ln in text.splitlines() if ln.strip()]
            if len(lines) < 2:
                return [], {}
            header = [h.strip() for h in lines[0].split(",")]
            gi = header.index("Gid") if "Gid" in header else None
            ti = header.index("Time") if "Time" in header else None
            ii = header.index("Id") if "Id" in header else None
            buckets: dict = {}
            if gi is not None and ii is not None:
                for ln in lines[1:]:
                    cols = [c.strip() for c in ln.split(",")]
                    gid = cols[gi] if gi < len(cols) else "0"
                    t = cols[ti] if ti is not None and ti < len(cols) else "0"
                    item = int(cols[ii]) if ii < len(cols) and cols[ii].isdigit() else None
                    if item is None:
                        continue
                    buckets.setdefault((gid, t), []).append(item)
            groups = [{"Gid": int(k[0] or 0), "Time": int(k[1] or 0), "Ids": v, "NextPackage": ""}
                      for k, v in buckets.items()]
            return groups, {}
        import json
        data = json.loads(text)
        # 桌面导出同时含 groups 与 categories,优先用 groups(扁平记录,避免重复计数)
        if isinstance(data, dict) and isinstance(data.get("groups"), list):
            return data["groups"], {}
        categories = sanitize_gacha_categories(data)
        groups = [g for gs in categories.values() for g in gs]
        if not groups:
            groups = sanitize_gacha(data)
        return groups, categories

    def _backup_archive(self) -> None:
        ap = self._output_dir / ARCHIVE_FILENAME
        if not ap.exists():
            QMessageBox.information(self, "创建备份", "尚未找到本地招募归档,请先刷新游戏数据。")
            return
        backup_dir = self._output_dir / "backups"; backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"{ARCHIVE_FILENAME[:-5]}_{datetime.now():%Y%m%d_%H%M%S}.json"
        try:
            shutil.copy2(ap, target)
        except OSError as e:
            QMessageBox.critical(self, "备份失败", str(e)); return
        self._status.setText(f"备份已创建:{target.name}")
        QMessageBox.information(self, "备份完成", f"已保存到:\n{target}")

    def _toggle_dark(self) -> None:
        pass


def _fmt_sync_items(items: list[dict], limit: int = 6) -> str:
    """同步报告的条目摘要: '埃莉诺(137)、夏日进行曲(214058) 等 4 项'。"""
    prefix = "、".join(f"{it['name']}({it['id']})" for it in items[:limit])
    if len(items) > limit:
        return f"{prefix} 等 {len(items)} 项"
    return prefix


def _format_sync_report(report: dict) -> tuple[str, list[str]]:
    """把同步报告拼成弹窗文本。返回 (正文, 未对齐项列表 —— 非空时弹警告框)。"""
    missing = report["missing_before"]
    query = (
        f"五星目录 {report['fetched_travelers']} 个角色 / {report['fetched_discs']} 个秘纹"
        + (" —— 均已注册 ✔" if not missing
           else f", 发现 {len(missing)} 个未注册: {_fmt_sync_items(missing)}")
    )
    bits = [f"注册名称 {len(report['registered'])} 条", f"下载头像 {len(report['downloaded'])} 张"]
    if report["existing"]:
        bits.append(f"本地已有 {len(report['existing'])} 张")
    if report["icon_failed"]:
        bits.append(f"失败 {len(report['icon_failed'])} 张")
    if not report["registered"] and not report["icon_failed"]:
        bits.append("✔")
    complete = " / ".join(bits)
    before, after = report["audit_before"], report["audit_after"]
    u0, u1 = len(before["unresolved"]), len(after["unresolved"])
    m0, m1 = len(before["misjudged"]), len(after["misjudged"])
    c1 = len(after["clash"])
    if report["record_count"]:
        align = (
            f"抽卡记录 {report['record_count']} 个序号: 回显缺失 {u0}→{u1}{' ✔' if u1 == 0 else ' ✘'}"
            f" / 五星判定错位 {m0}→{m1}{' ✔' if m1 == 0 else ' ✘'}"
            f" / ID 冲突 {c1}{' ✔' if c1 == 0 else ' ✘'}"
        )
    else:
        align = f"暂无本地抽卡记录(回显校验将在刷新游戏数据后进行) / 五星判定错位 {m0}→{m1} ✔ / ID 冲突 {c1} ✔"

    problems: list[str] = []
    if after["unresolved"]:
        ids = "、".join(f"#{i}" for i in after["unresolved"][:8])
        problems.append(f"仍有 {len(after['unresolved'])} 个序号无法回显角色名: {ids}")
    if after["misjudged"]:
        problems.append(f"{len(after['misjudged'])} 个五星条目星级判定未生效(重启后重试)")
    if after["clash"]:
        problems.append(f"{len(after['clash'])} 个序号同时在角色表与秘纹表(ID 冲突)")
    if report["icon_failed"]:
        problems.append(f"{len(report['icon_failed'])} 张头像下载失败: {_fmt_sync_items(report['icon_failed'])}")

    lines = [f"[查询缺失] {query}", f"[自动补全] {complete}", f"[对齐校验] {align}", ""]
    if problems:
        lines.append("未对齐项:")
        lines.extend(f"  • {p}" for p in problems)
    else:
        lines.append("✔ 序号与角色已全部对齐")
    return "\n".join(lines), problems


def _load_app_icon():
    """加载打包内的 app_icon 作为应用/窗口图标。"""
    from pathlib import Path
    from PySide6.QtGui import QIcon
    _meipass = getattr(sys, "_MEIPASS", None)
    root = Path(_meipass) if _meipass else Path(__file__).resolve().parent.parent.parent
    for fn in ("app_icon.ico", "app_icon.png"):
        p = root / "assets" / fn
        if p.exists():
            return QIcon(str(p))
    return QIcon()


def run(output_dir: Path, dark: bool = False) -> int:
    from PySide6.QtWidgets import QApplication
    from .theme import apply_theme, set_dark
    if dark:
        set_dark(True)
    app = QApplication(sys.argv)
    apply_theme(app)
    icon = _load_app_icon()
    if icon is not None and not icon.isNull():
        app.setWindowIcon(icon)
    win = StellaSoraWindow(output_dir.resolve())
    if icon is not None and not icon.isNull():
        win.setWindowIcon(icon)
    win.show()
    return app.exec()
