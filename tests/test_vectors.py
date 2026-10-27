"""Tests for luister.vectors icon factory."""

import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QPushButton

from luister import vectors

ICONS = [
    "play_icon", "stop_icon", "pause_icon", "eq_icon", "folder_icon",
    "shuffle_icon", "loop_icon", "double_right_icon", "double_left_icon",
    "slider_handle_icon", "tray_icon", "youtube_icon",
]


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


def _opaque_pixels(icon):
    img = icon.pixmap(32, 32).toImage()
    return sum(
        1 for x in range(img.width()) for y in range(img.height())
        if img.pixelColor(x, y).alpha() > 0
    )


@pytest.mark.parametrize("name", ICONS)
def test_icon_draws_pixels_and_honours_color(app, name):
    fn = getattr(vectors, name)
    default = fn()
    assert not default.isNull()
    assert _opaque_pixels(default) > 0
    custom = fn(QColor(255, 0, 0))
    img = custom.pixmap(32, 32).toImage()
    reds = [
        img.pixelColor(x, y) for x in range(32) for y in range(32)
        if img.pixelColor(x, y).alpha() == 255
    ]
    assert reds and any(c.red() == 255 and c.green() == 0 for c in reds)


def test_default_color_is_apple_blue(app):
    img = vectors.stop_icon().pixmap(32, 32).toImage()
    c = img.pixelColor(16, 16)
    assert (c.red(), c.green(), c.blue()) == (0, 122, 255)


def test_apply_shadow_sets_effect(app):
    btn = QPushButton()
    vectors.apply_shadow(btn)
    eff = btn.graphicsEffect()
    assert isinstance(eff, QGraphicsDropShadowEffect)
    assert eff.blurRadius() == 8
