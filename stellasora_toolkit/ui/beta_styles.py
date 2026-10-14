"""Three native Qt art directions with a common semantic token contract."""
from .theme import Palette

VARIANTS = {'orbit': 'A · 星轨夜航', 'sky': 'B · 晴空工作台', 'journal': 'C · 旅人手札'}


class Orbit(Palette):
    BG = '#101c30'
    SURFACE = '#192840'
    SURFACE2 = '#233550'
    PRIMARY = '#8bceef'
    PRIMARY2 = '#b1dff5'
    ON_PRIMARY = '#102a40'
    ACCENT = '#edc987'
    OK = '#75d2b5'
    WARN = '#edc987'
    DANGER = '#f09599'
    TEXT = '#eaf2fc'
    MUTED = '#95aac3'
    LINE = '#30415b'


class Sky(Palette):
    BG = '#edf4f8'
    SURFACE = '#ffffff'
    SURFACE2 = '#e6f1f7'
    PRIMARY = '#216f94'
    PRIMARY2 = '#185676'
    ON_PRIMARY = '#ffffff'
    ACCENT = '#547ca4'
    OK = '#22806b'
    WARN = '#946218'
    DANGER = '#b14f63'
    TEXT = '#20384b'
    MUTED = '#687f91'
    LINE = '#d6e4ed'


class Journal(Palette):
    BG = '#f0edf7'
    SURFACE = '#fcfbff'
    SURFACE2 = '#e8e2f1'
    PRIMARY = '#755481'
    PRIMARY2 = '#5a4064'
    ON_PRIMARY = '#ffffff'
    ACCENT = '#a26280'
    OK = '#4b7b72'
    WARN = '#936222'
    DANGER = '#ac4e65'
    TEXT = '#41394e'
    MUTED = '#82748f'
    LINE = '#dcd3e7'


def palette(variant):
    return {'orbit': Orbit, 'sky': Sky, 'journal': Journal}[variant]()


def stylesheet(variant):
    p = palette(variant)
    radius = 16 if variant != 'journal' else 7
    return f'''
    * {{font-family: "Microsoft YaHei UI"; font-size:13px; color:{p.TEXT};}}
    QMainWindow, QWidget#AppRoot {{background:{p.BG};}}
    QWidget#Sidebar, QFrame#Topbar {{background:{p.SURFACE};}}
    QFrame#Topbar {{border-bottom:1px solid {p.LINE};}}
    QWidget#Sidebar {{border-right:1px solid {p.LINE};}}
    QLabel {{background:transparent;}}
    QLabel[role="muted"], QLabel[role="mutedSmall"] {{color:{p.MUTED};font-size:12px;}}
    QLabel[role="h1"] {{font-size:25px;font-weight:700;}}
    QLabel[role="h2"] {{font-size:16px;font-weight:600;}}
    QLabel[role="eyebrow"] {{color:{p.PRIMARY};font-family:"Bahnschrift";font-size:11px;letter-spacing:2px;}}
    QLabel[role="metricValue"] {{font-family:"Bahnschrift";font-size:31px;font-weight:600;}}
    QFrame[card="true"] {{background:{p.SURFACE};border:1px solid {p.LINE};border-radius:{radius}px;}}
    QFrame[role="divider"] {{background:{p.LINE};border:none;max-height:1px;}}
    QPushButton {{background:{p.SURFACE2};border:1px solid transparent;border-radius:8px;padding:9px 16px;font-weight:600;}}
    QPushButton:hover {{border:1px solid {p.PRIMARY};}}
    QPushButton:focus {{border:2px solid {p.PRIMARY};}}
    QPushButton[role="primary"] {{background:{p.PRIMARY};color:{p.ON_PRIMARY};}}
    QPushButton[role="primary"]:hover {{background:{p.PRIMARY2};}}
    QPushButton[role="ghost"] {{background:transparent;border:1px solid {p.LINE};}}
    QPushButton[role="nav"] {{text-align:left;background:transparent;color:{p.MUTED};padding:13px 18px;}}
    QPushButton[role="nav"]:checked {{background:{p.SURFACE2};color:{p.PRIMARY};}}
    QPushButton[role="filter"] {{background:transparent;border:1px solid {p.LINE};color:{p.MUTED};}}
    QPushButton[role="filter"]:checked, QPushButton[role="choice"]:checked {{background:{p.PRIMARY};color:{p.ON_PRIMARY};border:1px solid {p.PRIMARY};}}
    QPushButton:disabled {{color:{p.MUTED};background:{p.SURFACE2};}}
    QComboBox, QLineEdit {{background:{p.SURFACE};border:1px solid {p.LINE};border-radius:7px;padding:8px 12px;}}
    QComboBox::drop-down {{border:0;width:22px;}}
    QComboBox QAbstractItemView {{background:{p.SURFACE};selection-background-color:{p.SURFACE2};}}
    QLineEdit:focus {{border:1px solid {p.PRIMARY};}}
    QScrollArea {{background:transparent;border:0;}}
    QScrollArea > QWidget > QWidget {{background:transparent;}}
    QScrollBar:vertical {{background:transparent;width:8px;}}
    QScrollBar::handle:vertical {{background:{p.LINE};border-radius:4px;min-height:40px;}}
    QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
    QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {{background:transparent;}}
    QToolTip {{background:{p.SURFACE};color:{p.TEXT};border:1px solid {p.LINE};padding:6px;}}
    QTableWidget {{background:{p.SURFACE};alternate-background-color:{p.SURFACE2};border:1px solid {p.LINE};gridline-color:{p.LINE};}}
    QHeaderView::section {{background:{p.SURFACE2};border:0;padding:10px;font-weight:600;}}
    QDialog, QMessageBox, QInputDialog {{background:{p.SURFACE};color:{p.TEXT};}}
    '''
