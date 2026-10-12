"""五个视图:首页 / 招募记录 / 设置 / 账户 / 使用说明。"""
from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QLineEdit,
    QScrollArea, QPushButton, QButtonGroup, QSizePolicy, QTabWidget, QProgressBar,
)

from ..catalog import gacha_item_name, traveler_name, gem_type_name, table_values, format_random_attr
from ..official_banners import official_pool_info
from ..service import ARCHIVE_FILENAME
from .constants import (
    GACHA_CATEGORY_ORDER, GACHA_CATEGORY_NAMES, GACHA_CATEGORY_PITY_LIMITS,
    POOL_COLORS, APP_VERSION,
)
from .theme import get_palette
from .widgets import Card, MetricCard, PityBar, UpBadge, WellBadge, AvatarLabel, WrapGrid, FlowLayout, mk_label, mk_divider


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def _scroll(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    return area


class HomeView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self._wrap = QWidget()
        self._col = QVBoxLayout(self._wrap)
        self._col.setContentsMargins(24, 20, 24, 24)
        self._col.setSpacing(16)
        outer.addWidget(_scroll(self._wrap))

    def render(self, stats) -> None:
        clear_layout(self._col)
        pal = get_palette()
        self._pool_sections(stats)

    def _pool_sections(self, stats) -> None:
        self._col.addWidget(_HomeFortuneBanner(stats))
        title = mk_label(f"四类卡池详情 · 五星记录 {stats.total_five}", role="h1")
        self._col.addWidget(title)
        for i, cat in enumerate(GACHA_CATEGORY_ORDER):
            st = stats.category_stats.get(cat)
            if st is None:
                card = Card(); card.add(mk_label(
                    "该分类暂无数据,先在游戏中打开对应招募记录再刷新。", role="muted"))
                self._col.addWidget(card)
            else:
                self._col.addWidget(self._pool_section(st, i, cat, stats))
            # 井 UP 卡: 放在旅人限时池(上一个卡池)与下一类卡池之间
            if cat == GACHA_CATEGORY_ORDER[0] and stats.well_banners:
                self._col.addWidget(_well_card(stats))

    def _pool_section(self, pool, i, cat, stats) -> QWidget:
        pal = get_palette()
        color = POOL_COLORS[i % len(POOL_COLORS)]
        card = Card(pad=0)
        body = card.body(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)
        # 彩色表头
        head = QFrame(); head.setFixedHeight(72)
        head.setStyleSheet(f"background:{color};")
        hl = QHBoxLayout(head); hl.setContentsMargins(18, 0, 18, 0)
        left = QVBoxLayout(); left.setSpacing(2)
        t = mk_label(GACHA_CATEGORY_NAMES[cat], role="body"); t.setStyleSheet(f"color:#fff;font-size:16px;font-weight:600;")
        dt = mk_label(
            f"{_fmt(pool.start_time)}  -  {_fmt(pool.end_time)}", role="mutedSmall")
        dt.setStyleSheet("color:#e6eef2;")
        left.addWidget(t); left.addWidget(dt)
        hl.addLayout(left, 1)
        # 右侧指标
        right = QHBoxLayout(); right.setSpacing(18)
        is_lim = cat in (GACHA_CATEGORY_ORDER[0], GACHA_CATEGORY_ORDER[1])
        avg = _up_average(pool) if is_lim else pool.average_pulls
        right.addWidget(_head_metric(str(pool.total_pulls), "总抽数"))
        right.addWidget(_head_metric(str(len(pool.five_stars)), "五星"))
        right.addWidget(_head_metric(("-" if avg is None else str(avg)), "UP平均" if is_lim else "平均"))
        hl.addLayout(right)
        body.addWidget(head)
        body.addWidget(mk_divider())
        # 五星磁贴区(按可用宽度自动换行,避免横向溢出被截断)
        if not pool.five_stars:
            emp = mk_label("该分类暂无五星记录。", role="muted")
            emp.setContentsMargins(18, 12, 18, 12)
            body.addWidget(emp)
        else:
            tiles = [_tile(pull, color) for pull in pool.five_stars]
            # 每个旅人限时卡池(各自 ≥120 抽) 各显示一个它自己的「井」UP 磁贴
            if cat == GACHA_CATEGORY_ORDER[0]:
                for gid in stats.well_banners:
                    wt = _well_tile(gid, color)
                    if wt is not None:
                        tiles.append(wt)
            grid = WrapGrid(tiles, tile_w=86, tile_h=112, spacing=12,
                            margins=(18, 14, 18, 14))
            body.addWidget(grid)
        return card


class RecordsView(QWidget):
    # 侧栏宽度随窗口缩放按比例自适应,并限制在合理区间
    SIDE_MIN, SIDE_MAX, SIDE_RATIO = 180, 270, 0.19

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        # 左侧筛选(宽度自适应,见 resizeEvent)
        self._side = QFrame()
        self._side.setMinimumWidth(self.SIDE_MIN)
        self._side.setMaximumWidth(self.SIDE_MAX)
        self._side.setStyleSheet(f"background:{get_palette().SURFACE}; border-right:1px solid {get_palette().LINE};")
        self._side_lay = QVBoxLayout(self._side); self._side_lay.setContentsMargins(14, 12, 14, 14); self._side_lay.setSpacing(6)
        self._side_lay.setAlignment(Qt.AlignTop)
        self._side_lay.addWidget(mk_label("招募记录", role="h2"))
        self._side_summary = mk_label("等待加载", role="mutedSmall")
        self._side_lay.addWidget(self._side_summary)
        self._side_lay.addSpacing(8)
        self._filter_buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._content_wrap = QWidget(); self._content_col = QVBoxLayout(self._content_wrap)
        self._content_col.setContentsMargins(24, 12, 24, 24); self._content_col.setSpacing(16)
        self._content_col.setAlignment(Qt.AlignTop)
        outer.addWidget(self._side)
        outer.addWidget(_scroll(self._content_wrap), 1)
        self._current = "all"
        self._records = []

    def resizeEvent(self, e) -> None:
        # 侧栏宽度 = 窗口宽度 × 比例,夹在 [SIDE_MIN, SIDE_MAX] 之间,内容区吃下剩余宽度
        w = self.width()
        side_w = max(self.SIDE_MIN, min(self.SIDE_MAX, int(w * self.SIDE_RATIO)))
        self._side.setFixedWidth(side_w)
        super().resizeEvent(e)

    def set_filter(self, value: str, btn) -> None:
        self._current = value
        for k, b in self._filter_buttons.items():
            b.setChecked(k == value)
        self.render(self._records, self._current)

    def render(self, records, category_filter="all") -> None:
        self._records = records
        self._current = category_filter
        clear_layout(self._content_col)
        from ..gacha_stats import build_banner_stats_with_shared_pity, classify_history_category
        sem = _semantic_categories(records)
        # 侧栏
        clear_layout(self._side_lay)
        self._side_lay.addWidget(mk_label("招募记录", role="h2"))
        counts = sum(len(p.five_stars) for p in build_banner_stats_with_shared_pity(records))
        self._side_lay.addWidget(mk_label(f"{counts} 个五星记录", role="mutedSmall"))
        self._side_lay.addSpacing(8)
        self._filter_buttons = {}
        self._group = QButtonGroup(self); self._group.setExclusive(True)
        options = [("all", "全部卡池")] + [(c, GACHA_CATEGORY_NAMES[c]) for c in GACHA_CATEGORY_ORDER]
        for value, name in options:
            b = QPushButton(name)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(value == self._current)
            b.setStyleSheet(_filter_style(value == self._current))
            b.clicked.connect(lambda _, v=value, bb=b: self.set_filter(v, bb))
            self._group.addButton(b)
            self._filter_buttons[value] = b
            self._side_lay.addWidget(b)
        self._side_lay.addStretch(1)
        # 内容
        cats = [self._current] if self._current != "all" else list(GACHA_CATEGORY_ORDER)
        idx = 0
        any_ = False
        for cat in cats:
            groups = sem.get(cat, [])
            if not groups:
                continue
            pools = build_banner_stats_with_shared_pity(groups)
            with_five = [p for p in pools if p.five_stars]
            if not with_five:
                continue
            any_ = True
            self._content_col.addWidget(mk_label(GACHA_CATEGORY_NAMES[cat], role="h2"))
            for pool in with_five:
                self._content_col.addWidget(_banner_card(pool, POOL_COLORS[idx % len(POOL_COLORS)]))
                idx += 1
        if not any_:
            c = Card(); c.add(mk_label("当前范围内暂无五星记录。", role="muted")); self._content_col.addWidget(c)


class SettingsView(QWidget):
    def __init__(self, callbacks: dict, parent=None):
        super().__init__(parent)
        self._cb = callbacks
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self._wrap = QWidget(); self._col = QVBoxLayout(self._wrap)
        self._col.setContentsMargins(24, 20, 24, 24); self._col.setSpacing(16)
        outer.addWidget(_scroll(self._wrap))
        self._result = mk_label("", role="muted")
        self._uid_state = mk_label("", role="muted")

    def build(self, archive_path: str, summary: str, uid: str = "") -> None:
        clear_layout(self._col)
        self._col.addWidget(mk_label("设置", role="h1"))
        self._col.addWidget(mk_label("导入、管理本地归档与软件版本", role="muted"))
        # 游戏版本(国服/国际服): 决定读取的客户端进程名与卡池/角色名称语言
        from .. import server_config
        c0 = Card()
        c0.add(mk_label("游戏版本", role="h2"))
        c0.add(mk_label(
            "选择所玩的服务器: 客户端进程名与名称语言(卡池/角色/UP 判定)会自动切换。\n"
            "已有名称在下次刷新数据时按所选语言重新补全(离线时保持上次语言)。",
            role="muted"))
        row = QHBoxLayout(); row.setSpacing(8)
        group = QButtonGroup(self); group.setExclusive(True)
        current = server_config.active()
        self._server_buttons: dict[str, QPushButton] = {}
        for _key, prof in server_config.PROFILES.items():
            b = self._btn(f"{prof.label} · {prof.client_names[0]}", "ghost",
                          lambda k=_key: self._cb.get("server_changed", lambda _: None)(k))
            b.setCheckable(True)
            b.setChecked(_key == current.key)
            group.addButton(b)
            self._server_buttons[_key] = b
            row.addWidget(b)
        row.addStretch(1)
        c0.add(_hbox(row))
        self._col.addWidget(c0)
        # 本地归档
        c1 = Card()
        c1.add(mk_label("本地归档", role="h2"))
        c1.add(mk_label("招募历史会合并保存在此文件中。", role="muted"))
        path = mk_label(archive_path, role="body")
        path.setStyleSheet(f"color:{get_palette().PRIMARY}; font-size:12px;")
        c1.add(path)
        btns = QHBoxLayout(); btns.setSpacing(8)
        btns.addWidget(self._btn("打开目录", "ghost", lambda: self._cb["open"]()))
        btns.addWidget(self._btn("复制路径", "ghost", lambda: self._cb["copy"]()))
        btns.addWidget(self._btn("创建备份", "primary", lambda: self._cb["backup"]()))
        c1.add(_hbox(btns))
        self._col.addWidget(c1)
        # 本地数据
        c2 = Card()
        c2.add(mk_label("本地数据", role="h2"))
        self._summary = mk_label(summary, role="body")
        c2.add(self._summary)
        self._col.addWidget(c2)
        # UID 与分享文件
        c3 = Card()
        c3.add(mk_label("UID 与分享文件", role="h2"))
        c3.add(mk_label(
            "网页版与分享文件用 UID 标识一份记录, 文件名就是 <UID>.json。\n"
            "导入过一次带 uid 的分享文件后工具会自动记住; 也可以在这里手填。"
            "填好后每次刷新都会额外生成 <UID>.json(格式与分享文件完全一致)。",
            role="muted"))
        self._uid = QLineEdit(); self._uid.setPlaceholderText("例如 100872990")
        self._uid.setText(uid or "")
        c3.add(self._uid)
        rowu = QHBoxLayout(); rowu.setSpacing(8)
        rowu.addWidget(self._btn("保存 UID", "ghost", self._on_save_uid))
        rowu.addWidget(self._btn("从游戏读取 UID", "ghost", self._on_read_uid))
        rowu.addWidget(self._btn("导出发送文件", "primary", self._on_share))
        rowu.addStretch(1)
        c3.add(_hbox(rowu))
        c3.add(self._uid_state)
        self._col.addWidget(c3)
        self._col.addWidget(self._result)
        self._col.addStretch(1)

    def set_uid(self, uid: str) -> None:
        """同步 UID 输入框(导入文件学到新 uid 后调用)。"""
        if hasattr(self, "_uid"):
            self._uid.setText(uid or "")

    def set_uid_state(self, text: str) -> None:
        if hasattr(self, "_uid_state"):
            self._uid_state.setText(text)

    def _on_save_uid(self) -> None:
        self._cb["save_uid"](self._uid.text())

    def _on_read_uid(self) -> None:
        self._cb["read_uid"]()

    def _on_share(self) -> None:
        self._cb["share"](self._uid.text())

    def refresh_server_buttons(self) -> None:
        """自动检测切换版本后, 让单选按钮跟随当前生效版本(与手动选择的按钮状态同步)。"""
        from .. import server_config
        current = server_config.active().key
        for key, b in getattr(self, "_server_buttons", {}).items():
            b.setChecked(key == current)

    def set_summary(self, summary: str) -> None:
        if hasattr(self, "_summary"):
            self._summary.setText(summary)

    def _btn(self, txt, role, fn) -> QPushButton:
        b = QPushButton(txt); b.setProperty("role", role)
        b.setCursor(Qt.PointingHandCursor); b.clicked.connect(fn)
        return b


class AccountView(QWidget):
    """账户页: 连服务器 / 登录注册 / 上传归档 / 退出。

    与 SettingsView 的一个关键差异: 那边每次 build() 都 clear_layout 重建
    (内容全是只读展示), 这里有一堆输入框 —— 重建会把用户正打到一半的内容
    抹掉。所以布局只在 __init__ 建一次, 状态变化走 set_state() 只改标签
    与可见性。

    回调字典:
        save_url(url)                        保存服务器地址
        login(url, username, password)       登录
        register(url, username, pw)          注册
        logout()                             退出登录
        upload(mode)                         上传归档
        open_site()                          用浏览器打开网页版
    """

    def __init__(self, callbacks: dict, parent=None):
        super().__init__(parent)
        self._cb = callbacks
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        wrap = QWidget(); col = QVBoxLayout(wrap)
        col.setContentsMargins(24, 20, 24, 24); col.setSpacing(16)
        outer.addWidget(_scroll(wrap))

        col.addWidget(mk_label("账户", role="h1"))
        col.addWidget(mk_label(
            "把抽卡记录上传到网页版, 之后在任何设备上打开浏览器都能查看。\n"
            "读取游戏内存只能在这台电脑上做, 网页端是只读的展示页。",
            role="muted"))

        # ---- 服务器地址 ----
        c0 = Card()
        c0.add(mk_label("服务器地址", role="h2"))
        c0.add(mk_label(
            "填网页版的访问地址, 例如 https://你的域名。"
            "也可以直接粘贴别人给你的分享链接, 会自动取其中的站点地址。",
            role="muted"))
        self._url = QLineEdit(); self._url.setPlaceholderText("https://你的域名")
        c0.add(self._url)
        row0 = QHBoxLayout(); row0.setSpacing(8)
        row0.addWidget(self._btn("保存地址", "ghost", self._on_save_url))
        row0.addWidget(self._btn("打开网页版", "ghost", lambda: self._cb["open_site"]()))
        row0.addStretch(1)
        c0.add(_hbox(row0))
        self._url_state = mk_label("", role="muted")
        c0.add(self._url_state)
        col.addWidget(c0)

        # ---- 未登录: 登录 / 注册 ----
        self._login_card = Card()
        self._login_card.add(mk_label("登录", role="h2"))
        self._login_card.add(mk_label(
            "用网页版注册的账号登录。", role="muted"))
        self._username = QLineEdit(); self._username.setPlaceholderText("用户名")
        self._password = QLineEdit(); self._password.setPlaceholderText("密码")
        self._password.setEchoMode(QLineEdit.Password)
        self._login_card.add(self._username)
        self._login_card.add(self._password)
        row1 = QHBoxLayout(); row1.setSpacing(8)
        row1.addWidget(self._btn("登录", "primary", self._on_login))
        row1.addStretch(1)
        self._login_card.add(_hbox(row1))

        self._login_card.add(mk_divider())
        self._login_card.add(mk_label("没有账号? 在这里注册", role="h2"))
        self._reg_username = QLineEdit()
        self._reg_username.setPlaceholderText("用户名 (3–20 字, 中文/字母/数字/下划线)")
        self._reg_password = QLineEdit(); self._reg_password.setPlaceholderText("密码 (至少 8 位)")
        self._reg_password.setEchoMode(QLineEdit.Password)
        for w in (self._reg_username, self._reg_password):
            self._login_card.add(w)
        row2 = QHBoxLayout(); row2.setSpacing(8)
        row2.addWidget(self._btn("注册", "ghost", self._on_register))
        row2.addStretch(1)
        self._login_card.add(_hbox(row2))
        col.addWidget(self._login_card)

        # ---- 已登录: 上传 / 退出 ----
        self._account_card = Card()
        self._account_card.add(mk_label("已登录", role="h2"))
        self._who = mk_label("", role="body")
        self._account_card.add(self._who)
        self._account_card.add(mk_divider())
        self._archive = mk_label("", role="muted")
        self._account_card.add(self._archive)
        row3 = QHBoxLayout(); row3.setSpacing(8)
        row3.addWidget(self._btn("上传到服务器", "primary", lambda: self._on_upload("merge")))
        row3.addWidget(self._btn("打开网页版", "ghost", lambda: self._cb["open_site"]()))
        row3.addStretch(1)
        self._account_card.add(_hbox(row3))
        self._account_card.add(mk_label(
            "上传只增不减: 服务器会把它已有的记录和这份合并, 重复的抽数会自动去掉。\n"
            "所以重装系统、换电脑之后再上传, 也不会把服务器上更早的历史冲掉。",
            role="muted"))
        row4 = QHBoxLayout(); row4.setSpacing(8)
        row4.addWidget(self._btn("退出登录", "ghost", lambda: self._cb["logout"]()))
        row4.addStretch(1)
        self._account_card.add(_hbox(row4))
        col.addWidget(self._account_card)

        # ---- 状态 ----
        c3 = Card()
        self._state = mk_label("", role="body")
        c3.add(self._state)
        col.addWidget(c3)
        col.addStretch(1)

        self.set_state(None, "")

    # ---- 事件 ----
    def _on_save_url(self) -> None:
        self._cb["save_url"](self._url.text())

    def _on_login(self) -> None:
        self._cb["login"](self._url.text(), self._username.text(),
                          self._password.text())

    def _on_register(self) -> None:
        self._cb["register"](self._url.text(), self._reg_username.text(),
                             self._reg_password.text())

    def _on_upload(self, mode: str) -> None:
        self._cb["upload"](mode)

    # ---- 状态 ----
    def set_state(self, account, archive_text: str) -> None:
        """account 为 None 或未登录时显示登录卡; 否则显示上传卡。"""
        logged_in = bool(account is not None and getattr(account, "logged_in", False))
        if account is not None and account.server_url:
            # 不要覆盖用户正在编辑的内容
            if not self._url.hasFocus() and self._url.text().strip() != account.server_url:
                self._url.setText(account.server_url)
            self._url_state.setText(f"当前: {account.server_url}")
        else:
            self._url_state.setText("尚未设置服务器地址")

        self._login_card.setVisible(not logged_in)
        self._account_card.setVisible(logged_in)
        if logged_in:
            self._who.setText(f"账号: {account.username or '(未知)'}")
        self._archive.setText(archive_text or "尚未加载本地归档")

    def set_busy(self, busy: bool) -> None:
        for b in self.findChildren(QPushButton):
            b.setEnabled(not busy)

    def set_status(self, text: str) -> None:
        self._state.setText(text)

    def clear_password(self) -> None:
        self._password.clear()
        self._reg_password.clear()

    def _btn(self, txt, role, fn) -> QPushButton:
        b = QPushButton(txt); b.setProperty("role", role)
        b.setCursor(Qt.PointingHandCursor); b.clicked.connect(fn)
        return b


class HelpView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        wrap = QWidget(); col = QVBoxLayout(wrap)
        col.setContentsMargins(24, 20, 24, 24); col.setSpacing(10)
        outer.addWidget(_scroll(wrap))
        col.addWidget(mk_label("使用说明与风险提示", role="h1"))
        col.addWidget(mk_label("面向《星塔旅人》国服 Windows 客户端的非官方抽卡记录整理工具。", role="muted"))
        _section(col, "使用方法")
        for t in [
            "1. 登录游戏进入主界面,在游戏内依次打开四类招募记录,等待每个列表显示。",
            "2. 回到工具点击刷新游戏数据。读取完成后首页和招募记录页面自动更新。",
            "3. 新角色/秘纹图片随版本内置更新,可点击“检查更新”。",
        ]:
            col.addWidget(mk_label(t, role="body"))
        _section(col, "数据与备份")
        col.addWidget(mk_label("每次刷新都会合并更新 exports/stellasora_gacha_archive.json。", role="body"))
        col.addWidget(mk_label("导出不含账号密码、Cookie、SDK token 或网络会话数据,请谨慎分享。", role="muted"))
        _section(col, "风险与免责声明", danger=True)
        for t in [
            "• 非官方个人研究工具,与运营方/开发方无关联、未经授权。",
            "• 通过 ReadProcessMemory 只读访问客户端已加载的招募历史;不注入、不改文件/内存、不发协议请求。",
            "• 游戏更新可能改变数据结构或反作弊策略,请自读服务条款并评估风险,仅对自己的账号使用。",
            "• 使用者自行承担使用后果。",
        ]:
            lb = mk_label(t, role="body")
            lb.setStyleSheet(f"color:{get_palette().DANGER if False else get_palette().MUTED};")
            col.addWidget(lb)


# ---------------- 内部小部件/工具 ----------------

def _hbox(lay) -> QWidget:
    w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(0, 0, 0, 0); l.addLayout(lay)
    return w


# ---------- 首页运势(左侧面板, 点按钮后显示, 0-100 分评定) ----------
# 分数越低越欧(平均每个五星抽得越少);0-100 映射到 大凶/凶/小吉/吉/大吉。
# 每档: (最低分, 标题, 副文案, 颜色)
_FORTUNE_TIERS = [
    (80, "大吉", "福星高照，欧气冲天！", "#c98a1e"),
    (60, "吉", "小有欧气，继续加油", "#2e9e6b"),
    (40, "小吉", "中规中矩，略有好运", "#3e6c86"),
    (20, "凶", "运气欠佳，稳住心态", "#c1503d"),
    (0,  "大凶", "非到极点，抱抱不哭", "#8a2e26"),
]


def _fortune_eval(score: int) -> tuple[str, str, str]:
    if score is None:
        return "未评定", "尚未抽取运势", "#6b7a83"
    for threshold, cat, desc, color in _FORTUNE_TIERS:
        if score >= threshold:
            return cat, desc, color
    return "大凶", "非到极点，抱抱不哭", "#8a2e26"


# ---------- 欧气档位(基于「平均每个五星抽数」, 与随机运势并存为独立内容项) ----------
# 每档: (平均抽数阈值, 标题, 副文案, 颜色)
_LUCK_RANK = [
    (30,  "双层至尊欧皇", "天选之人，一发入魂！", "#c98a1e"),
    (45,  "欧皇附体", "气运加身，多抽多中！", "#2e9e6b"),
    (70,  "转非入欧", "运气回升，稳住就出", "#3e6c86"),
    (100, "非酋", "脸有点黑，再坚持一下", "#c1503d"),
    (float("inf"), "非酋本酋", "抱抱不哭，下次一定", "#8a2e26"),
]


def _luck_rank(avg_pulls: float | None) -> tuple[str, str, str]:
    if avg_pulls is None:
        return "暂无数据", "刷新游戏数据后自动计算", "#6b7a83"
    for limit, title, desc, color in _LUCK_RANK:
        if avg_pulls <= limit:
            return title, desc, color
    return "非酋本酋", "抱抱不哭，下次一定", "#8a2e26"


def _luck_badge(stats) -> QWidget:
    """欧气档位徽标:根据平均五星抽数自动计算(欧皇/非酋等),独立于随机运势。"""
    avg = (stats.total_pulls / stats.total_five) if stats.total_five else None
    title, desc, color = _luck_rank(avg)
    card = QFrame(); card.setObjectName("LuckBadge")
    card.setStyleSheet(
        f"QFrame#LuckBadge {{ background:{get_palette().SURFACE};"
        f" border:1px solid {get_palette().LINE}; border-left:5px solid {color}; border-radius:12px; }}")
    lay = QVBoxLayout(card); lay.setContentsMargins(16, 10, 16, 10); lay.setSpacing(2)
    t = mk_label(f"今日欧气 · {title}", role="h2", wrap=False)
    t.setStyleSheet(f"color:{color}; font-weight:700;")
    d = mk_label(desc, role="mutedSmall", wrap=False)
    lay.addWidget(t); lay.addWidget(d)
    return card


def _lighten(hex_color: str, factor: float) -> str:
    r = int(hex_color[1:3], 16); g = int(hex_color[3:5], 16); b = int(hex_color[5:7], 16)
    r = min(255, round(r + (255 - r) * factor)); g = min(255, round(g + (255 - g) * factor)); b = min(255, round(b + (255 - b) * factor))
    return f"#{r:02x}{g:02x}{b:02x}"


def _darken(hex_color: str, factor: float) -> str:
    r = int(hex_color[1:3], 16); g = int(hex_color[3:5], 16); b = int(hex_color[5:7], 16)
    r = max(0, round(r * (1 - factor))); g = max(0, round(g * (1 - factor))); b = max(0, round(b * (1 - factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def _fortune_path() -> Path:
    """运势保存文件:打包后与 exe 同级,源码运行与项目根同级。"""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "fortune.json"
    return Path(__file__).resolve().parent.parent.parent / "fortune.json"


def _fortune_today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _load_fortune(day: str) -> int | None:
    """读取当天已保存的运势分;跨天(日期变化)或未保存返回 None(触发自动重置)。"""
    try:
        p = _fortune_path()
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("day") != day:
            return None
        v = int(data.get("score"))
        return v if 0 <= v <= 100 else None
    except Exception:
        return None


def _save_fortune(score: int, day: str) -> None:
    try:
        p = _fortune_path()
        p.write_text(
            json.dumps({"day": day, "score": score}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception:
        pass


class _HomeFortuneBanner(QFrame):
    """首页顶部单条横幅: 左侧欧气档位(基于平均抽数), 右侧运势按钮(点击后随机 0-100 吉凶)。"""

    def __init__(self, stats, parent=None):
        super().__init__(parent)
        self.setObjectName("HomeFortune")
        avg = (stats.total_pulls / stats.total_five) if stats.total_five else None
        luck_title, luck_desc, color = _luck_rank(avg)
        ga, gb = _darken(color, 0.35), _lighten(color, 0.12)
        self.setStyleSheet(
            f"QFrame#HomeFortune {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 {ga}, stop:1 {gb}); border-radius:16px; }}")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        outer = QHBoxLayout(self); outer.setContentsMargins(26, 20, 26, 20); outer.setSpacing(24)
        left = QVBoxLayout(); left.setSpacing(4)
        lt = mk_label(luck_title, role="h1", wrap=False)
        lt.setStyleSheet("color:#ffffff; font-size:24px; font-weight:800;")
        ld = mk_label(luck_desc, role="body", wrap=False)
        ld.setStyleSheet("color:#ffffff; font-size:14px;")
        left.addWidget(lt); left.addWidget(ld)
        if avg is not None:
            ls = mk_label(f"平均每 {avg:.1f} 抽一只五星 · 共 {stats.total_five} 只",
                          role="mutedSmall", wrap=False)
            ls.setStyleSheet("color:#ffffff; font-size:13px;")
            left.addWidget(ls)
        outer.addLayout(left, 1)
        self._btn = QPushButton("查看今日运势")
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setStyleSheet(
            "QPushButton { background:rgba(255,255,255,0.20); color:#ffffff;"
            " border:1px solid rgba(255,255,255,0.55); border-radius:9px;"
            " padding:10px 18px; font-size:14px; font-weight:700; }"
            "QPushButton:hover { background:rgba(255,255,255,0.32); }")
        self._btn.clicked.connect(self._reveal)
        outer.addWidget(self._btn, 0, Qt.AlignVCenter)
        self._res = None

    def _reveal(self) -> None:
        self._render_result(self._today_fortune())

    def _today_fortune(self) -> int:
        """取当天已保存的运势;若当天还没有则随机生成并保存。同一天内保持一致。"""
        day = _fortune_today()
        score = _load_fortune(day)
        if score is None:
            score = random.randint(0, 100)
            _save_fortune(score, day)
        return score

    def _render_result(self, score: int) -> None:
        cat, desc, color = _fortune_eval(score)
        res = QFrame(); res.setObjectName("FortuneResult")
        res.setStyleSheet(
            f"QFrame#FortuneResult {{ background:rgba(255,255,255,0.20);"
            f" border:1px solid rgba(255,255,255,0.55); border-left:4px solid {color}; border-radius:11px; }}")
        rl = QVBoxLayout(res); rl.setContentsMargins(14, 10, 14, 10); rl.setSpacing(3)
        top = QHBoxLayout(); top.setSpacing(8)
        sc = mk_label(f"{score} 分", role="h1", wrap=False)
        sc.setStyleSheet("color:#ffffff; font-size:24px; font-weight:800;")
        cl = mk_label(cat, role="h2", wrap=False)
        cl.setStyleSheet("color:#ffffff; font-size:20px; font-weight:800;")
        top.addWidget(sc); top.addWidget(cl); top.addStretch(1)
        rl.addLayout(top)
        bar = QProgressBar(); bar.setRange(0, 100); bar.setValue(score)
        bar.setFixedHeight(8); bar.setTextVisible(False)
        bar.setStyleSheet(
            f"QProgressBar {{ background:rgba(255,255,255,0.30); border:none; border-radius:4px; }}"
            f"QProgressBar::chunk {{ background:{color}; border-radius:4px; }}")
        rl.addWidget(bar)
        dl = mk_label(desc, role="mutedSmall", wrap=False)
        dl.setStyleSheet("color:rgba(255,255,255,0.92); font-size:12px;")
        rl.addWidget(dl)
        lay = self.layout()
        if self._btn is not None:
            lay.removeWidget(self._btn); self._btn.deleteLater(); self._btn = None
        if self._res is not None:
            lay.removeWidget(self._res); self._res.deleteLater()
        lay.addWidget(res, 0, Qt.AlignVCenter)
        self._res = res


class _FortunePanel(QWidget):
    """左侧运势面板:点按钮后随机生成 0-100 运评分,并按吉凶显示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(12)
        self._btn = QPushButton("查看今日运势")
        self._btn.setProperty("role", "primary")
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.clicked.connect(self._reveal)
        lay.addWidget(self._btn)

    def _reveal(self) -> None:
        self._btn.hide()
        score = random.randint(0, 100)
        cat, desc, color = _fortune_eval(score)
        self.layout().addWidget(self._build_body(score, cat, desc, color))

    def _build_body(self, score: int, cat: str, desc: str, color: str) -> QWidget:
        card = QFrame(); card.setObjectName("FortuneBody")
        card.setStyleSheet(
            f"QFrame#FortuneBody {{ background:{get_palette().SURFACE};"
            f" border:1px solid {get_palette().LINE}; border-left:5px solid {color}; border-radius:12px; }}")
        lay = QVBoxLayout(card); lay.setContentsMargins(16, 12, 16, 12); lay.setSpacing(6)
        row = QHBoxLayout(); row.setSpacing(10)
        sl = mk_label(f"{score} 分", role="h1", wrap=False)
        sl.setStyleSheet(f"color:{color}; font-size:30px; font-weight:800;")
        row.addWidget(sl)
        cl = mk_label(cat, role="h2", wrap=False)
        cl.setStyleSheet(f"color:{color}; font-size:24px; font-weight:800;")
        row.addWidget(cl)
        row.addStretch(1)
        lay.addLayout(row)
        bar = QProgressBar(); bar.setRange(0, 100); bar.setValue(score)
        bar.setFixedHeight(10); bar.setTextVisible(False)
        bar.setStyleSheet(
            f"QProgressBar {{ background:{get_palette().SURFACE2}; border:none; border-radius:5px; }}"
            f"QProgressBar::chunk {{ background:{color}; border-radius:5px; }}")
        lay.addWidget(bar)
        lay.addWidget(mk_label(desc, role="muted", wrap=False))
        return card


def _head_metric(value: str, label: str) -> QWidget:
    w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(0, 0, 0, 0); l.setSpacing(1)
    v = mk_label(value, role="body"); v.setStyleSheet("color:#fff;font-size:17px;font-weight:600;")
    t = mk_label(label, role="mutedSmall"); t.setStyleSheet("color:#dfe9ee;")
    l.addWidget(v); l.addWidget(t)
    return w


def _up_item_id(up_name: str) -> int | None:
    """按官方 UP 名找到对应的旅人物品 id(用于显示井 UP 头像)。"""
    from ..catalog import FIVE_STAR_TRAVELERS, gacha_item_name, same_item_name
    for iid in FIVE_STAR_TRAVELERS:
        if same_item_name(gacha_item_name(iid), up_name):
            return iid
    return None


def _well_card(stats) -> QWidget:
    """井 UP 卡: 显示各 120 抽达成卡池的 UP 角色头像 + 井徽标(位于上一/下一卡池之间)。"""
    card = Card(pad=16)
    head = QHBoxLayout(); head.setSpacing(8)
    head.addWidget(WellBadge())
    t = mk_label("UP 必得 · 120 抽达成", role="h2", wrap=False)
    head.addWidget(t)
    head.addStretch(1)
    card.add(_hbox(head))
    row = QHBoxLayout(); row.setSpacing(18); row.setAlignment(Qt.AlignLeft)
    for gid, total in stats.well_banners.items():
        info = official_pool_info(gid)
        iid = _up_item_id(info[3]) if info else None
        item = QWidget()
        bl = QVBoxLayout(item); bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4); bl.setAlignment(Qt.AlignCenter)
        if iid is not None:
            bl.addWidget(AvatarLabel(iid, "traveler", size=64), 0, Qt.AlignCenter)
        if info:
            nm = mk_label(info[0], role="mutedSmall", wrap=False)
            nm.setAlignment(Qt.AlignCenter)
            bl.addWidget(nm)
            un = mk_label(f"UP · {info[3]}", role="body", wrap=False)
            un.setStyleSheet(f"color:{get_palette().PRIMARY}; font-weight:700;")
            un.setAlignment(Qt.AlignCenter)
            bl.addWidget(un)
        cc = mk_label(f"井 · {total} 抽", role="mutedSmall", wrap=False)
        cc.setAlignment(Qt.AlignCenter)
        bl.addWidget(cc)
        row.addWidget(item)
    card.add(_hbox(row))
    return card


def _well_tile(gid: int, color: str) -> QWidget | None:
    """井 UP 磁贴: 指定旅人限时卡池满 120 抽一次性必得的 UP 角色(金边 + 井徽标)。"""
    info = official_pool_info(gid)
    if not info:
        return None
    iid = _up_item_id(info[3])
    if iid is None:
        return None
    w = QFrame(); w.setFixedSize(86, 112)
    w.setStyleSheet("background:#fdf6e6; border:2px solid #c98a1e; border-radius:12px;")
    l = QVBoxLayout(w); l.setContentsMargins(6, 6, 6, 6); l.setSpacing(4); l.setAlignment(Qt.AlignTop)
    av = AvatarLabel(iid, "traveler", size=64)
    l.addWidget(av)
    row = QHBoxLayout(); row.setSpacing(2)
    row.addWidget(WellBadge())
    row.addStretch(1)
    pity = mk_label("120", role="body")
    pity.setStyleSheet("color:#c98a1e;font-size:14px;font-weight:700;")
    row.addWidget(pity)
    l.addLayout(row)
    return w


def _tile(pull, color: str) -> QWidget:
    w = QFrame(); w.setFixedSize(86, 112)
    w.setStyleSheet(f"background:{get_palette().SURFACE2}; border:1px solid {get_palette().LINE}; border-radius:12px;")
    l = QVBoxLayout(w); l.setContentsMargins(6, 6, 6, 6); l.setSpacing(4); l.setAlignment(Qt.AlignTop)
    av = AvatarLabel(pull.item_id, pull.kind, size=64)
    av.setParent(w)
    l.addWidget(av)
    row = QHBoxLayout(); row.setSpacing(0)
    official = official_pool_info(pull.gid)
    if official is not None:
        from ..catalog import same_item_name
        row.addWidget(UpBadge(same_item_name(pull.name, official[3])))
    row.addStretch(1)
    pity = mk_label(str(pull.pity), role="body")
    pity.setStyleSheet(f"color:{_pity_color(pull.pity)};font-size:14px;font-weight:700;")
    row.addWidget(pity)
    l.addLayout(row)
    return w


def _banner_card(pool, color: str) -> Card:
    card = Card(pad=16)
    official = official_pool_info(pool.gid)
    std = {1: "旅人常驻招募", 2: "秘纹常驻招募"}.get(pool.gid, f"卡池 {pool.gid}")
    top = QHBoxLayout(); top.setSpacing(12)
    left = QVBoxLayout(); left.setSpacing(2)
    name = mk_label((official[0] if official else std), role="body")
    name.setStyleSheet("font-size:16px;font-weight:600;")
    sub = mk_label(
        (f"{official[1]} - {official[2]} · ID {pool.gid}" if official
         else f"{_fmt(pool.start_time)} - {_fmt(pool.end_time)}"),
        role="mutedSmall")
    left.addWidget(name); left.addWidget(sub)
    top.addLayout(left, 1)
    # 旅人限时池: 满 120 抽一次性必得 UP(井, 仅一次机会)
    if 10000 <= pool.gid < 20000 and pool.total_pulls >= 120:
        top.addWidget(WellBadge(), 0, Qt.AlignVCenter)
    total = QLabel(f"{pool.total_pulls}抽")
    total.setStyleSheet(f"background:{get_palette().PRIMARY}; color:#fff; border-radius:10px; padding:6px 14px; font-size:15px; font-weight:700;")
    total.setAlignment(Qt.AlignCenter)
    top.addWidget(total)
    card.add(_hbox(top))
    card.add(mk_divider())
    # 每条五星记录为紧凑项,内容靠左、随窗口宽度自动换行
    flow = FlowLayout(margin=0, spacing=12)
    wrap = QWidget()
    wrap.setLayout(flow)
    wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    for pull in pool.five_stars:
        flow.addWidget(_pull_item(pull, official, color))
    card.add(wrap)
    return card


def _pull_item(pull, official, color) -> QWidget:
    """单条五星记录的紧凑项: ?已垫次数 + 头像 + 名字/第N抽 + UP徽标 + 抽数。"""
    w = QWidget()
    row = QHBoxLayout(w); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(8)
    row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    # "?" + 已垫次数(该五星出现时的垫抽数)
    front = QWidget()
    fl = QHBoxLayout(front); fl.setContentsMargins(0, 0, 0, 0); fl.setSpacing(5)
    q = mk_label("?", role="body", wrap=False)
    q.setFixedSize(22, 22); q.setAlignment(Qt.AlignCenter)
    q.setStyleSheet(f"background:{color}; color:#ffffff; border-radius:11px; font-weight:800; font-size:14px;")
    fl.addWidget(q)
    ct = mk_label(f"已垫 {pull.pity}", role="mutedSmall", wrap=False)
    ct.setStyleSheet(f"color:{get_palette().TEXT}; font-weight:600;")
    fl.addWidget(ct)
    row.addWidget(front)
    av = AvatarLabel(pull.item_id, pull.kind, size=44)
    row.addWidget(av)
    col = QVBoxLayout(); col.setSpacing(2); col.setAlignment(Qt.AlignLeft)
    nm = mk_label(pull.name, role="body", wrap=False)
    nm.setStyleSheet(f"color:{get_palette().TEXT}; font-weight:600;")
    pt = mk_label(f"第 {pull.pity} 抽", role="mutedSmall", wrap=False)
    col.addWidget(nm); col.addWidget(pt)
    row.addLayout(col)
    if official is not None:
        from ..catalog import same_item_name
        row.addWidget(UpBadge(same_item_name(pull.name, official[3])), 0, Qt.AlignVCenter)
    num = mk_label(f"{pull.pity} 抽", role="pin", wrap=False)
    num.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    row.addWidget(num)
    return w


def _pity_color(cur: int) -> str:
    pal = get_palette()
    return pal.OK if cur <= 30 else (pal.WARN if cur <= 60 else pal.DANGER)


def _fmt(ts: int) -> str:
    if ts <= 0:
        return "未知日期"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y.%m.%d")
    except Exception:
        return "未知日期"


def _semantic_categories(records) -> dict:
    from ..gacha_stats import classify_history_category
    out = {c: [] for c in GACHA_CATEGORY_ORDER}
    for g in records:
        cat = classify_history_category([g])
        if cat in out:
            out[cat].append(g)
    return out


def _up_average(pool) -> int | None:
    from ..catalog import same_item_name
    up = sum(1 for pull in pool.five_stars
             if (o := official_pool_info(pull.gid)) is not None
             and same_item_name(pull.name, o[3]))
    return round(pool.total_pulls / up) if up else None


def _filter_style(selected: bool) -> str:
    from .theme import get_palette
    pal = get_palette()
    if selected:
        return (f"background:{pal.PRIMARY}; color:#ffffff; border:1px solid {pal.PRIMARY}; "
                "border-radius:8px; text-align:left; padding:10px 14px; font-weight:600;")
    return (f"background:transparent; color:{pal.TEXT}; border:1px solid transparent; "
            "border-radius:8px; text-align:left; padding:10px 14px; font-weight:600;")


def _section_header(text: str) -> QWidget:
    """统一高度的分类标题块:标题 + 底部细分隔线,保证各班次留白一致。"""
    w = QWidget()
    l = QVBoxLayout(w); l.setContentsMargins(0, 0, 0, 0); l.setSpacing(8)
    l.addWidget(mk_label(text, role="h2"))
    div = QFrame(); div.setFixedHeight(1)
    div.setStyleSheet(f"background:{get_palette().LINE}; border:none;")
    l.addWidget(div)
    return w


def _section(layout, title: str, danger=False) -> None:
    lb = mk_label(title, role="body")
    lb.setStyleSheet(f"color:{get_palette().DANGER if danger else get_palette().PRIMARY}; font-size:14px; font-weight:600; padding-top:10px;")
    layout.addWidget(lb)
