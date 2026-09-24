"""主题令牌与全局 QSS —— 现代、干净、有品牌感。

一切颜色走这里的令牌,明暗各一套;`build_qss` 用令牌生成全局样式,QSS 里用
属性选择器(如 `QFrame[card="true"]`)区分控件形态,避免散落写死颜色。
"""
from __future__ import annotations


class Palette:
    """亮色令牌。"""
    # 基础
    BG       = "#eef1f4"
    SURFACE  = "#ffffff"
    SURFACE2 = "#eaeef2"
    # 品牌
    PRIMARY  = "#3e6c86"
    PRIMARY2 = "#2f5a72"
    ON_PRIMARY = "#ffffff"
    ACCENT   = "#7a6890"
    # 语义
    OK      = "#2e9e6b"
    WARN    = "#d9a62a"
    DANGER  = "#c1503d"
    # 文字
    TEXT    = "#1b262d"
    MUTED   = "#6b7a83"
    # 结构
    LINE    = "#e2e6ea"


class PaletteDark(Palette):
    """暗色令牌(深灰,不用纯黑)。"""
    BG       = "#171a1d"
    SURFACE  = "#1f2327"
    SURFACE2 = "#272c31"
    PRIMARY  = "#7fb0c9"
    PRIMARY2 = "#9cc6da"
    ON_PRIMARY = "#0e2b38"
    ACCENT   = "#a89cc4"
    TEXT     = "#e7ebed"
    MUTED    = "#9aa8b1"
    LINE     = "#33383d"


_cached: dict | None = {"dark": False, "pal": Palette}


def get_palette() -> Palette:
    if _cached["dark"]:
        return PaletteDark()
    return Palette()


def set_dark(dark: bool) -> None:
    _cached["dark"] = dark


def is_dark() -> bool:
    return bool(_cached["dark"])


def build_qss(p: Palette) -> str:
    """根据令牌生成全局 QSS。"""
    return f"""
    * {{ font-family:'Microsoft YaHei UI','PingFang SC',sans-serif; font-size:13px; }}
    QMainWindow, QWidget#AppRoot {{ background:{p.BG}; color:{p.TEXT}; }}
    QWidget {{ color:{p.TEXT}; }}

    /* ---- 顶栏 ---- */
    QWidget#AppHeader {{ background:{p.PRIMARY}; }}
    QLabel#AppTitle {{ color:#ffffff; font-size:19px; font-weight:600; }}
    QLabel#AppSubtitle {{ color:#d7e6ee; font-size:11px; }}
    QLabel#AppVersion {{ color:#cfdfe8; font-size:11px; }}

    /* ---- 按钮 ---- */
    QPushButton {{ border:none; border-radius:8px; font-weight:600; padding:8px 18px; color:{p.TEXT}; }}
    QPushButton[role="primary"] {{ background:{p.PRIMARY}; color:{p.ON_PRIMARY}; }}
    QPushButton[role="primary"]:hover {{ background:{p.PRIMARY2}; }}
    QPushButton[role="ghost"] {{ background:transparent; border:1px solid {p.LINE}; color:{p.TEXT}; }}
    QPushButton[role="ghost"]:hover {{ background:{p.SURFACE2}; }}
    QPushButton[role="danger"] {{ background:transparent; border:1px solid {p.DANGER}; color:{p.DANGER}; }}
    QPushButton[role="danger"]:hover {{ background:{p.DANGER}; color:#fff; }}
    QPushButton:disabled {{ background:{p.SURFACE2}; color:{p.MUTED}; }}
    /* 顶栏次级按钮:白底主字,悬停高亮 */
    QPushButton[role="header-action"] {{ background:#ffffff; color:{p.PRIMARY}; border:1px solid #ffffff; border-radius:8px; padding:9px 16px; font-weight:600; }}
    QPushButton[role="header-action"]:hover {{ background:#e7f1f7; color:{p.PRIMARY2}; }}
    /* 侧栏筛选按钮(可选中) */
    QPushButton[role="filter"] {{ text-align:left; padding:10px 14px; border-radius:8px; background:transparent; color:{p.TEXT}; font-weight:600; }}
    QPushButton[role="filter"]:hover {{ background:{p.SURFACE2}; }}
    QPushButton[role="filter"]:checked {{ background:{p.PRIMARY}; color:#ffffff; border:1px solid {p.PRIMARY}; }}

    /* ---- 卡片 ---- */
    QFrame[card="true"] {{ background:{p.SURFACE}; border:1px solid {p.LINE}; border-radius:12px; }}
    QFrame[card="true"] QWidget {{ background:transparent; }}

    /* ---- 文本角色 ---- */
    QLabel[role="h1"] {{ font-size:20px; font-weight:600; color:{p.TEXT}; }}
    QLabel[role="h2"] {{ font-size:15px; font-weight:600; color:{p.TEXT}; }}
    QLabel[role="body"] {{ font-size:12px; color:{p.TEXT}; }}
    QLabel[role="muted"] {{ font-size:12px; color:{p.MUTED}; }}
    QLabel[role="mutedSmall"] {{ font-size:11px; color:{p.MUTED}; }}
    QLabel[role="metricValue"] {{ font-size:24px; font-weight:700; color:{p.PRIMARY}; }}
    QLabel[role="pin"] {{ font-size:15px; font-weight:700; color:{p.DANGER}; }}

    /* ---- 滚动区 / 分隔线 ---- */
    QScrollArea {{ border:none; background:transparent; }}
    QScrollArea > QWidget > QWidget {{ background:transparent; }}
    QScrollBar:vertical {{ background:transparent; width:10px; margin:2px; }}
    QScrollBar::handle:vertical {{ background:{p.LINE}; border-radius:5px; min-height:30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ background:none; height:0; }}
    QFrame[role="divider"] {{ background:{p.LINE}; max-height:1px; border:none; }}

    /* ---- 选项卡导航 QTabBar ---- */
    QTabWidget::pane {{ border:none; background:transparent; }}
    QTabBar::tab {{ background:transparent; color:{p.MUTED}; padding:10px 26px; font-size:14px; font-weight:600; }}
    QTabBar::tab:selected {{ color:{p.PRIMARY}; border-bottom:3px solid {p.PRIMARY}; }}
    QTabBar::tab:hover {{ color:{p.TEXT}; }}

    QToolTip {{ background:{p.SURFACE}; color:{p.TEXT}; border:1px solid {p.LINE}; border-radius:6px; padding:4px 8px; }}
    """


def apply_theme(app) -> None:
    app.setStyleSheet(build_qss(get_palette()))
