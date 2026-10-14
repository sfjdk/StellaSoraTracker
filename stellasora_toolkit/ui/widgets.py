"""可复用自定义控件:Card / MetricCard / PityBar / UpBadge / AvatarLabel / 标签辅助。"""
from __future__ import annotations

from io import BytesIO

from PySide6.QtCore import Qt, QRectF, QSize, QRect, QPoint
from PySide6.QtGui import QColor, QPainter, QPixmap, QFont
from PySide6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy,
    QLayout, QWidgetItem,
)

from .theme import get_palette


def mk_label(text="", role="body", wrap=True) -> QLabel:
    lb = QLabel(text)
    lb.setProperty("role", role)
    if wrap:
        lb.setWordWrap(True)
    return lb


def mk_divider() -> QFrame:
    dv = QFrame()
    dv.setProperty("role", "divider")
    dv.setFrameShape(QFrame.NoFrame)
    return dv


class FlowLayout(QLayout):
    """按可用宽度自动换行的流式布局(内容靠左、紧凑,随窗口自适应折行)。"""

    def __init__(self, parent=None, margin: int = 0, spacing: int = 12):
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        self._hspace = spacing
        self._vspace = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QWidgetItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int) -> QWidgetItem | None:
        if 0 <= i < len(self._items):
            return self._items[i]
        return None

    def takeAt(self, i: int) -> QWidgetItem | None:
        if 0 <= i < len(self._items):
            return self._items.pop(i)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), dry_run=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, dry_run=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, *, dry_run: bool) -> int:
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            w, h = hint.width(), hint.height()
            if line_height > 0 and x + w > rect.right() - m.right() + 1:
                x = rect.x() + m.left()
                y += line_height + self._vspace
                line_height = 0
            if not dry_run:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += w + self._hspace
            line_height = max(line_height, h)
        return y + line_height - rect.y() + m.bottom()


class Card(QFrame):
    """圆角卡片容器:提供内容布局与内边距。"""

    def __init__(self, parent=None, *, pad=16):
        super().__init__(parent)
        self.setProperty("card", True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(pad, pad, pad, pad)
        self._layout.setSpacing(8)

    def add(self, w) -> None:
        self._layout.addWidget(w)

    def body(self) -> QVBoxLayout:
        return self._layout


class MetricCard(Card):
    """指标磁贴:左侧品牌色竖条 + 数值 + 标签。"""

    def __init__(self, name: str, parent=None):
        super().__init__(parent, pad=16)
        row = QHBoxLayout()
        row.setSpacing(12)
        strip = QFrame()
        strip.setFixedWidth(4)
        strip.setStyleSheet(f"background:{get_palette().PRIMARY}; border-radius:2px;")
        row.addWidget(strip)
        col = QVBoxLayout(); col.setSpacing(2)
        self._value = mk_label("-", role="metricValue", wrap=False)
        self._name = mk_label(name, role="muted", wrap=False)
        col.addWidget(self._value); col.addWidget(self._name)
        row.addLayout(col, 1)
        self._layout.addLayout(row)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


class PityBar(QWidget):
    """垫抽进度条(细、圆角、颜色分级)。"""

    def __init__(self, parent=None, height=14):
        super().__init__(parent)
        self._h = height
        self._cur = 0
        self._limit = 160
        self._color = QColor(get_palette().OK)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_stat(self, cur: int, limit: int) -> None:
        self._cur = cur
        self._limit = max(1, limit)
        pal = get_palette()
        color = pal.OK if cur <= 30 else (pal.WARN if cur <= 60 else pal.DANGER)
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width(); h = self._h
        pal = get_palette()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(pal.SURFACE2))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        ratio = min(1.0, self._cur / self._limit)
        if ratio > 0:
            p.setBrush(self._color)
            p.drawRoundedRect(QRectF(0, 0, w * ratio, h), h / 2, h / 2)


class UpBadge(QLabel):
    """UP / 歪 徽标(正方形)。"""

    def __init__(self, is_up: bool, parent=None):
        super().__init__("UP" if is_up else "歪", parent)
        pal = get_palette()
        bg = "#24344c" if is_up else pal.DANGER
        self.setFixedSize(24, 24)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"background:{bg}; color:#ffffff; border-radius:6px; font-size:10px; font-weight:700;"
        )


class WellBadge(QLabel):
    """「井」徽标: 旅人限时池抽满 120 抽一次性必得 UP(仅一次机会)。"""

    def __init__(self, parent=None):
        super().__init__("井", parent)
        self.setFixedSize(24, 24)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "background:#c98a1e; color:#ffffff; border-radius:6px; font-size:10px; font-weight:700;"
        )


_PIXMAP_CACHE: dict[tuple[int, str], QPixmap] = {}


class AvatarLabel(QLabel):
    """从 PIL Image 显示为圆角方形头像;++ 距离无关。"""

    def __init__(self, item_id: int, kind: str, size: int = 52, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.set_text(str(item_id))
        self._pix = self._cached_pixmap(item_id, kind)

    @classmethod
    def _cached_pixmap(cls, item_id: int, kind: str) -> QPixmap | None:
        """按 (item_id, kind) 缓存解码后的位图，避免每个头像重复 PIL 解码。"""
        key = (item_id, kind)
        pix = _PIXMAP_CACHE.get(key)
        if pix is None:
            pix = cls._load(cls.resource_path(item_id, kind))
            if pix is not None:
                _PIXMAP_CACHE[key] = pix
        return pix

    @staticmethod
    def resource_path(item_id: int, kind: str) -> str:
        import sys
        from pathlib import Path
        folder = "travelers" if kind == "traveler" else "discs"
        _meipass = getattr(sys, "_MEIPASS", None)
        root = Path(_meipass) if _meipass else Path(__file__).resolve().parent.parent.parent
        return str(root / "assets" / folder / f"{item_id}.png")

    @staticmethod
    def _load(path: str) -> QPixmap | None:
        try:
            from PIL import Image, ImageOps
            from PySide6.QtGui import QImage
            im = Image.open(path).convert("RGBA")
            size = 160
            im = ImageOps.fit(im, (size - 6, size - 6), method=Image.Resampling.LANCZOS)
            buf = BytesIO(); im.save(buf, "PNG")
            qimg = QImage.fromData(buf.getvalue(), "PNG")
            return QPixmap.fromImage(qimg)
        except Exception:
            return None

    def set_text(self, text: str) -> None:
        self.setText(text)
        self.setStyleSheet(
            f"color:#ffffff; font-weight:600; background:{get_palette().PRIMARY}; border-radius:12px;"
        )

    def paintEvent(self, e):
        if self._pix is not None and not self._pix.isNull():
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            pal = get_palette()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(pal.SURFACE2))
            p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 12, 12)
            r = self._pix.rect()
            scaled = self._pix.scaled(self.width() - 6, self.height() - 6, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(3, 3, scaled)
        else:
            super().paintEvent(e)


def patience_color(cur: int) -> str:
    pal = get_palette()
    return pal.OK if cur <= 30 else (pal.WARN if cur <= 60 else pal.DANGER)


class WrapGrid(QWidget):
    """按可用宽度自动左对齐换行的磁贴网格(基于 FlowLayout)。

    磁贴固定尺寸,窗口变宽时自动排更多列,变窄时自动折行;
    内容始终靠左,高度随行数变化,配合父级 QScrollArea 纵向滚动、无横向溢出。
    """

    def __init__(self, tiles, *, tile_w: int = 86, tile_h: int = 112,
                 spacing: int = 12, margins=(18, 14, 18, 14), parent=None):
        super().__init__(parent)
        self._tiles = list(tiles)
        self._tw, self._th = tile_w, tile_h
        self._lay = FlowLayout(margin=0, spacing=spacing)
        self._lay.setContentsMargins(*margins)
        self.setLayout(self._lay)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        for t in self._tiles:
            self._lay.addWidget(t)
