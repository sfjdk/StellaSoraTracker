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


_cached: dict | None = {"dark": False, "pal": None}


def get_palette() -> Palette:
    if _cached["pal"] is not None:
        return _cached["pal"]
    if _cached["dark"]:
        return PaletteDark()
    return Palette()


def set_dark(dark: bool) -> None:
    _cached["dark"] = dark
    _cached["pal"] = None


def set_palette(palette: Palette) -> None:
    _cached["pal"] = palette


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
    /* 单选式按钮(游戏版本): 必须一眼看出选中了哪个 —— 之前用 ghost 没有选中样式,
       点完界面毫无变化, 用户就会觉得"按钮没用"。 */
    QPushButton[role="choice"] {{ background:{p.SURFACE}; color:{p.TEXT};
        border:1px solid {p.LINE}; border-radius:8px; padding:8px 16px; font-weight:600; }}
    QPushButton[role="choice"]:hover {{ border:1px solid {p.PRIMARY}; color:{p.PRIMARY}; }}
    QPushButton[role="choice"]:checked {{ background:{p.PRIMARY}; color:{p.ON_PRIMARY};
        border:1px solid {p.PRIMARY}; }}
    QPushButton[role="choice"]:checked:hover {{ background:{p.PRIMARY2}; color:{p.ON_PRIMARY}; }}

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

    /* ---- 输入类控件 ----
       必须显式给背景色: 只设 color 的话, Windows 深色系统主题下 Qt 会保留
       原生黑色底, 于是"深字 + 黑底"直接看不清(QComboBox 就踩过这个坑)。 */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
        background:{p.SURFACE}; color:{p.TEXT};
        border:1px solid {p.LINE}; border-radius:8px;
        padding:8px 10px; min-height:18px;
        selection-background-color:{p.PRIMARY}; selection-color:{p.ON_PRIMARY};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{
        border:1px solid {p.PRIMARY};
    }}
    QLineEdit:disabled, QComboBox:disabled {{ color:{p.MUTED}; background:{p.SURFACE2}; }}
    QLineEdit::placeholder {{ color:{p.MUTED}; }}

    QComboBox {{ padding-right:26px; }}
    QComboBox::drop-down {{ subcontrol-origin:padding; subcontrol-position:center right;
        width:22px; border:none; background:transparent; }}
    QComboBox::down-arrow {{ image:none; width:0; height:0; margin-right:8px;
        border-left:5px solid transparent; border-right:5px solid transparent;
        border-top:6px solid {p.MUTED}; }}
    QComboBox:hover {{ border:1px solid {p.PRIMARY}; }}
    /* 下拉列表(弹出窗口) —— 不设的话深色系统主题下是黑底黑字。
       弹出列表是一个独立的顶层容器: 只写 QAbstractItemView 时容器本身仍是
       原生背景, 所以连容器(QFrame/QListView)一起给背景。 */
    QComboBox QAbstractItemView, QComboBox QListView, QComboBox QFrame {{
        background:{p.SURFACE}; color:{p.TEXT};
        border:1px solid {p.LINE}; border-radius:8px;
        padding:4px; outline:none;
        selection-background-color:{p.PRIMARY}; selection-color:{p.ON_PRIMARY};
        alternate-background-color:{p.SURFACE2};
    }}
    QComboBox QAbstractItemView::item {{ min-height:26px; padding:4px 8px; border-radius:6px; }}
    /* 兜底: 本项目只有 QComboBox 会用到 item view, 干脆全局给一次背景,
       免得某些平台/主题下弹出列表又变回原生黑底。 */
    QAbstractItemView, QListView {{
        background:{p.SURFACE}; color:{p.TEXT};
        border:1px solid {p.LINE}; outline:none;
        selection-background-color:{p.PRIMARY}; selection-color:{p.ON_PRIMARY};
        alternate-background-color:{p.SURFACE2};
    }}

    /* ---- 弹窗(输入/提示) ---- */
    QDialog, QMessageBox, QInputDialog {{ background:{p.BG}; color:{p.TEXT}; }}
    QMessageBox QLabel, QInputDialog QLabel {{ color:{p.TEXT}; }}
    QMessageBox QPushButton, QInputDialog QPushButton {{
        background:{p.SURFACE}; color:{p.TEXT}; border:1px solid {p.LINE};
        border-radius:8px; padding:7px 16px; font-weight:600; min-width:64px;
    }}
    QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {{ background:{p.SURFACE2}; }}
    QMessageBox QPushButton:default, QInputDialog QPushButton:default {{
        background:{p.PRIMARY}; color:{p.ON_PRIMARY}; border:1px solid {p.PRIMARY};
    }}
    """


def build_palette(p: Palette):
    """把令牌变成 Qt 调色板。

    为什么不能只靠 QSS: 下拉列表、弹窗这类"原生绘制"的部分由系统主题决定底色。
    Windows 深色主题下, 只写 QSS 的 QComboBox 会出现"系统黑底 + 我们的深色文字"
    —— 用户看到的就是一条看不清的黑条。显式给调色板才管得住。
    """
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: p.BG,
        QPalette.ColorRole.WindowText: p.TEXT,
        QPalette.ColorRole.Base: p.SURFACE,
        QPalette.ColorRole.AlternateBase: p.SURFACE2,
        QPalette.ColorRole.Text: p.TEXT,
        QPalette.ColorRole.Button: p.SURFACE,
        QPalette.ColorRole.ButtonText: p.TEXT,
        QPalette.ColorRole.Highlight: p.PRIMARY,
        QPalette.ColorRole.HighlightedText: p.ON_PRIMARY,
        QPalette.ColorRole.ToolTipBase: p.SURFACE,
        QPalette.ColorRole.ToolTipText: p.TEXT,
        QPalette.ColorRole.PlaceholderText: p.MUTED,
        QPalette.ColorRole.Link: p.PRIMARY,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(p.MUTED))
    return palette


def apply_theme(app) -> None:
    palette = get_palette()
    # Fusion 才完全听调色板的话; Windows 原生样式在深色系统主题下会自己画黑底
    app.setStyle("Fusion")
    app.setPalette(build_palette(palette))
    app.setStyleSheet(build_qss(palette))
