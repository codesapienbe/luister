from __future__ import annotations

"""Vector graphics icon factory for Luister.

Provides simple QIcon instances drawn with QPainterPath instead of bitmap
resources. Icons use 95 % opacity (≈5 % transparency) and can be recoloured via
arguments.
"""

from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPainterPath, QColor
from PyQt6.QtCore import QSize, Qt, QRectF
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QPushButton

_ICON_SIZE = QSize(32, 32)
_ALPHA = int(255 * 0.95)  # 5 % transparent
_COLOR = QColor(76, 175, 80, _ALPHA)  # default greenish  # noqa: A001


def _make_icon(path: QPainterPath, color: QColor | None = None) -> QIcon:
    pix = QPixmap(_ICON_SIZE)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillPath(path, color or _COLOR)
    painter.end()
    return QIcon(pix)


# ------------------- Shapes ------------------- #


def play_icon(color: QColor | None = None) -> QIcon:
    path = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    path.moveTo(w * 0.25, h * 0.2)
    path.lineTo(w * 0.8, h * 0.5)
    path.lineTo(w * 0.25, h * 0.8)
    path.closeSubpath()
    return _make_icon(path, color)


def stop_icon(color: QColor | None = None) -> QIcon:
    path = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    path.addRect(w * 0.25, h * 0.25, w * 0.5, h * 0.5)
    return _make_icon(path, color)


def pause_icon(color: QColor | None = None) -> QIcon:
    path = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    path.addRect(w * 0.25, h * 0.2, w * 0.15, h * 0.6)
    path.addRect(w * 0.6, h * 0.2, w * 0.15, h * 0.6)
    return _make_icon(path, color)


def arrow_left_icon(color: QColor | None = None) -> QIcon:
    path = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    path.moveTo(w * 0.7, h * 0.2)
    path.lineTo(w * 0.3, h * 0.5)
    path.lineTo(w * 0.7, h * 0.8)
    path.closeSubpath()
    return _make_icon(path, color)


def arrow_right_icon(color: QColor | None = None) -> QIcon:
    path = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    path.moveTo(w * 0.3, h * 0.2)
    path.lineTo(w * 0.7, h * 0.5)
    path.lineTo(w * 0.3, h * 0.8)
    path.closeSubpath()
    return _make_icon(path, color)


# Additional icons

def eq_icon(color: QColor | None = None) -> QIcon:
    path = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    bar_w = w / 6
    # three bars of different heights
    path.addRect(w * 0.2, h * 0.4, bar_w, h * 0.5)
    path.addRect(w * 0.45, h * 0.2, bar_w, h * 0.7)
    path.addRect(w * 0.7, h * 0.5, bar_w, h * 0.4)
    return _make_icon(path, color)


# playlist_icon removed (unused) to reduce unused code surface area


def folder_icon(color: QColor | None = None) -> QIcon:
    path = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    path.moveTo(w * 0.1, h * 0.3)
    path.lineTo(w * 0.4, h * 0.3)
    path.lineTo(w * 0.5, h * 0.45)
    path.lineTo(w * 0.9, h * 0.45)
    path.lineTo(w * 0.9, h * 0.8)
    path.lineTo(w * 0.1, h * 0.8)
    path.closeSubpath()
    return _make_icon(path, color)


# Shuffle (crossed arrows)
def shuffle_icon(color: QColor | None = None) -> QIcon:
    path = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    # first arrow: bottom-left to top-right
    path.moveTo(w * 0.2, h * 0.8)
    path.lineTo(w * 0.4, h * 0.8)
    path.lineTo(w * 0.6, h * 0.4)
    path.lineTo(w * 0.8, h * 0.4)
    # arrow head
    path.moveTo(w * 0.8, h * 0.4)
    path.lineTo(w * 0.7, h * 0.3)
    path.moveTo(w * 0.8, h * 0.4)
    path.lineTo(w * 0.7, h * 0.5)
    # second arrow: top-left to bottom-right
    path.moveTo(w * 0.2, h * 0.2)
    path.lineTo(w * 0.4, h * 0.2)
    path.lineTo(w * 0.6, h * 0.6)
    path.lineTo(w * 0.8, h * 0.6)
    # arrow head
    path.moveTo(w * 0.8, h * 0.6)
    path.lineTo(w * 0.7, h * 0.5)
    path.moveTo(w * 0.8, h * 0.6)
    path.lineTo(w * 0.7, h * 0.7)
    return _make_icon(path, color)


# Loop icon (circular arrow)
def loop_icon(color: QColor | None = None) -> QIcon:
    path = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    # draw circular loop
    rect = QRectF(w * 0.2, h * 0.2, w * 0.6, h * 0.6)
    path.addEllipse(rect)
    # arrow head at top-center pointing clockwise
    arrow_tip_x = w * 0.5
    arrow_tip_y = h * 0.15
    path.moveTo(arrow_tip_x, arrow_tip_y)
    path.lineTo(arrow_tip_x - w * 0.07, arrow_tip_y + h * 0.12)
    path.moveTo(arrow_tip_x, arrow_tip_y)
    path.lineTo(arrow_tip_x + w * 0.07, arrow_tip_y + h * 0.12)
    return _make_icon(path, color)


# double arrow versions (next/previous)


def double_right_icon(color: QColor | None = None) -> QIcon:
    # two right arrows side by side
    path = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    # first arrow
    path.moveTo(w * 0.2, h * 0.2)
    path.lineTo(w * 0.45, h * 0.5)
    path.lineTo(w * 0.2, h * 0.8)
    path.closeSubpath()
    # second arrow
    path.moveTo(w * 0.55, h * 0.2)
    path.lineTo(w * 0.8, h * 0.5)
    path.lineTo(w * 0.55, h * 0.8)
    path.closeSubpath()
    return _make_icon(path, color)


def double_left_icon(color: QColor | None = None) -> QIcon:
    # mirror of double_right
    path = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    path.moveTo(w * 0.8, h * 0.2)
    path.lineTo(w * 0.55, h * 0.5)
    path.lineTo(w * 0.8, h * 0.8)
    path.closeSubpath()
    path.moveTo(w * 0.45, h * 0.2)
    path.lineTo(w * 0.2, h * 0.5)
    path.lineTo(w * 0.45, h * 0.8)
    path.closeSubpath()
    return _make_icon(path, color)


# ---------------- Utility ------------------ #


def apply_shadow(widget: QPushButton):
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(8)
    eff.setOffset(2, 2)
    eff.setColor(QColor(0, 0, 0, 120))
    widget.setGraphicsEffect(eff)


# Slider handle icon (round dot)
def slider_handle_icon(color: QColor | None = None) -> QIcon:
    """Vector icon representing the slider handle (a circle)."""
    path = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    # draw circle at center
    radius = min(w, h) * 0.2
    cx, cy = w / 2, h / 2
    path.addEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
    return _make_icon(path, color)


# Tray icon vector (simple musical note)
def tray_icon(color: QColor | None = None) -> QIcon:
    """Vector icon for system tray: simple musical note."""
    path = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    # note head
    radius = h * 0.2
    path.addEllipse(w * 0.2, h * 0.6, radius * 2, radius * 2)
    # stem
    path.moveTo(w * 0.3, h * 0.6)
    path.lineTo(w * 0.3, h * 0.2)
    path.lineTo(w * 0.35, h * 0.2)
    path.lineTo(w * 0.35, h * 0.58)
    path.closeSubpath()
    return _make_icon(path, color)

# YouTube-style play icon: rounded rectangle with white triangle
def youtube_icon(color: QColor | None = None) -> QIcon:
    path_bg = QPainterPath()
    w, h = _ICON_SIZE.width(), _ICON_SIZE.height()
    rect_w = w * 0.92
    rect_h = h * 0.64
    rect_x = (w - rect_w) / 2
    rect_y = (h - rect_h) / 2
    radius = min(w, h) * 0.12
    path_bg.addRoundedRect(rect_x, rect_y, rect_w, rect_h, radius, radius)

    tri = QPainterPath()
    tri.moveTo(rect_x + rect_w * 0.36, rect_y + rect_h * 0.25)
    tri.lineTo(rect_x + rect_w * 0.75, rect_y + rect_h * 0.5)
    tri.lineTo(rect_x + rect_w * 0.36, rect_y + rect_h * 0.75)
    tri.closeSubpath()

    pix = QPixmap(_ICON_SIZE)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    bg_color = color or QColor(220, 45, 45, _ALPHA)
    fg_color = QColor(255, 255, 255, _ALPHA)
    painter.fillPath(path_bg, bg_color)
    painter.fillPath(tri, fg_color)
    painter.end()
    return QIcon(pix) 