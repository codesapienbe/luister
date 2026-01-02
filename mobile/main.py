"""
Luister Mobile - Apple-inspired Crystal Glass Design
Full-featured music player matching desktop functionality with premium UI
"""
# pyright: reportOptionalMemberAccess=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportOptionalContextManager=false
# pyright: reportCallIssue=false
# pyright: reportIndexIssue=false
# Kivy uses dynamic properties that static type checkers don't understand

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.widget import Widget
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.progressbar import ProgressBar
from kivy.uix.behaviors import ButtonBehavior
from kivy.metrics import dp, sp
from kivy.clock import Clock
from kivy.core.audio import SoundLoader
from kivy.properties import (
    StringProperty, NumericProperty, BooleanProperty,
    ListProperty, ColorProperty, ObjectProperty
)
from kivy.graphics import (
    Color, Rectangle, RoundedRectangle, Line, Ellipse,
    PushMatrix, PopMatrix, Rotate, Scale, Translate
)
from kivy.graphics.texture import Texture
from kivy.utils import platform, get_color_from_hex
from kivy.core.window import Window
from kivy.animation import Animation

import os
import json
import random
import threading
import math
from pathlib import Path
from typing import Optional, List, Dict, Any

# Try to import numpy for FFT analysis
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# Try to import plyer for file picker
try:
    from plyer import filechooser
    HAS_FILECHOOSER = True
except ImportError:
    HAS_FILECHOOSER = False


# ============================================================================
# ANDROID NATIVE AUDIO PLAYER (uses MediaPlayer for better format support)
# ============================================================================
class AndroidMediaPlayer:
    """Wrapper for Android's native MediaPlayer - supports m4a, mp3, ogg, etc."""

    def __init__(self, path: str):
        from jnius import autoclass
        self.MediaPlayer = autoclass('android.media.MediaPlayer')
        self._player = self.MediaPlayer()
        self._player.setDataSource(path)
        self._player.prepare()
        self._length = self._player.getDuration() / 1000.0  # Convert ms to seconds
        self._volume = 1.0

    @property
    def length(self) -> float:
        return self._length

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = max(0.0, min(1.0, value))
        self._player.setVolume(self._volume, self._volume)

    def play(self):
        self._player.start()

    def stop(self):
        if self._player.isPlaying():
            self._player.pause()

    def seek(self, position: float):
        """Seek to position in seconds"""
        self._player.seekTo(int(position * 1000))

    def get_pos(self) -> float:
        """Get current position in seconds"""
        return self._player.getCurrentPosition() / 1000.0

    def unload(self):
        try:
            self._player.stop()
            self._player.release()
        except Exception:
            pass


def load_audio(path: str, logger=None):
    """Load audio file - uses Android MediaPlayer on Android, SoundLoader elsewhere"""
    if platform == 'android':
        try:
            if logger:
                logger(f'Using Android MediaPlayer')
            player = AndroidMediaPlayer(path)
            if logger:
                logger(f'MediaPlayer ready: {player.length:.1f}s')
            return player
        except Exception as e:
            if logger:
                logger(f'MediaPlayer error: {e}')
            # Don't fallback - Android MediaPlayer is preferred
            return None
    # Use Kivy SoundLoader on non-Android platforms
    return SoundLoader.load(path)


# ============================================================================
# APPLE-INSPIRED CRYSTAL GLASS THEME COLORS
# ============================================================================
class Theme:
    """Apple-inspired Crystal Glass color palette"""

    # Background colors (dark mode - matches desktop)
    BG_PRIMARY = get_color_from_hex('#1C1C1E')      # Main background
    BG_SECONDARY = get_color_from_hex('#2C2C2E')    # Card/panel background
    BG_TERTIARY = get_color_from_hex('#3A3A3C')     # Elevated surfaces

    # Glass effect colors
    GLASS_BG = (0.17, 0.17, 0.18, 0.85)             # Semi-transparent panels
    GLASS_BORDER = (1, 1, 1, 0.08)                   # Subtle borders
    GLASS_HIGHLIGHT = (1, 1, 1, 0.05)               # Top highlight

    # Text colors
    TEXT_PRIMARY = get_color_from_hex('#F5F5F7')    # Main text
    TEXT_SECONDARY = get_color_from_hex('#98989D')  # Secondary text
    TEXT_TERTIARY = get_color_from_hex('#636366')   # Dimmed text

    # Accent colors (Apple Blue)
    ACCENT = get_color_from_hex('#0A84FF')          # Primary accent
    ACCENT_HOVER = get_color_from_hex('#409CFF')    # Lighter accent
    ACCENT_PRESSED = get_color_from_hex('#0066CC')  # Darker accent

    # Semantic colors
    SUCCESS = get_color_from_hex('#30D158')         # Green
    WARNING = get_color_from_hex('#FF9F0A')         # Orange
    ERROR = get_color_from_hex('#FF453A')           # Red

    # Visualizer gradient (teal-cyan)
    VIZ_START = get_color_from_hex('#2C8A8E')       # Teal
    VIZ_END = get_color_from_hex('#4DAFB1')         # Cyan

    # Button colors
    BTN_LIGHT_BG = (1, 1, 1, 0.95)                  # Light button background
    BTN_DARK_BG = (0.28, 0.28, 0.29, 0.9)          # Dark button background
    BTN_BORDER = (1, 1, 1, 0.1)                     # Button border

    # Slider colors
    SLIDER_TRACK = (1, 1, 1, 0.1)                   # Slider track
    SLIDER_FILL_START = get_color_from_hex('#007AFF')
    SLIDER_FILL_END = get_color_from_hex('#0066CC')
    SLIDER_HANDLE = (1, 1, 1, 0.95)                 # White handle


# Standard button sizes for consistency across all screens
BUTTON_SIZE = dp(52)        # Standard icon button size
BUTTON_SIZE_LARGE = dp(64)  # Main play/pause button
BUTTON_SIZE_SMALL = dp(44)  # Compact buttons (volume icon, etc.)


# ============================================================================
# ANIMATED SPLASH SCREEN
# ============================================================================
class SplashScreen(Screen):
    """Animated splash screen with logo only"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Main layout
        layout = FloatLayout()

        # Background
        with layout.canvas.before:
            Color(*Theme.BG_PRIMARY)
            self._bg = Rectangle(pos=layout.pos, size=layout.size)
        layout.bind(pos=self._update_bg, size=self._update_bg)

        # Logo container (centered)
        self.logo_widget = Widget(
            size_hint=(None, None),
            size=(dp(120), dp(120)),
            pos_hint={'center_x': 0.5, 'center_y': 0.55},
            opacity=0
        )

        # Draw logo (stylized 'L' in a circle)
        with self.logo_widget.canvas:
            # Outer glow
            Color(*Theme.ACCENT[:3], 0.15)
            Ellipse(pos=(-dp(10), -dp(10)), size=(dp(140), dp(140)))

            # Main circle with gradient effect
            Color(*Theme.ACCENT)
            Ellipse(pos=(0, 0), size=(dp(120), dp(120)))

            # Inner highlight
            Color(1, 1, 1, 0.2)
            Ellipse(pos=(dp(10), dp(40)), size=(dp(80), dp(60)))

            # Letter 'L' stylized
            Color(1, 1, 1, 0.95)
            # Vertical bar
            RoundedRectangle(
                pos=(dp(38), dp(25)),
                size=(dp(14), dp(70)),
                radius=[dp(4)]
            )
            # Horizontal bar
            RoundedRectangle(
                pos=(dp(38), dp(25)),
                size=(dp(50), dp(14)),
                radius=[dp(4)]
            )

        layout.add_widget(self.logo_widget)

        # App name
        self.app_name = Label(
            text='Luister',
            font_size=sp(36),
            color=Theme.TEXT_PRIMARY,
            bold=True,
            pos_hint={'center_x': 0.5, 'center_y': 0.38},
            opacity=0
        )
        layout.add_widget(self.app_name)

        self.add_widget(layout)

    def _update_bg(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def on_enter(self):
        """Start animations when screen is shown"""
        # Reset state
        self.logo_widget.opacity = 0
        self.app_name.opacity = 0

        # Logo animation: fade in with pulse
        logo_anim = Animation(opacity=1, duration=0.5, t='out_cubic')
        logo_anim.start(self.logo_widget)

        # Gentle pulse animation for logo
        def pulse_logo(dt):
            if self.logo_widget.opacity > 0:
                pulse = Animation(opacity=0.9, duration=0.6) + Animation(opacity=1, duration=0.6)
                pulse.repeat = True
                pulse.start(self.logo_widget)
        Clock.schedule_once(pulse_logo, 0.6)

        # App name fade in (delayed)
        Clock.schedule_once(lambda dt: Animation(opacity=1, duration=0.4).start(self.app_name), 0.3)

        # Transition to main screen after delay
        Clock.schedule_once(self._go_to_main, 1.8)

    def _go_to_main(self, dt):
        # Fade out
        fade_out = Animation(opacity=0, duration=0.25)
        fade_out.start(self.logo_widget)
        fade_out.start(self.app_name)

        # Switch screen
        def switch(dt):
            app = App.get_running_app()
            if app and app.root:
                app.root.transition.duration = 0.4
                app.root.current = 'main'
        Clock.schedule_once(switch, 0.3)


# ============================================================================
# CONFIGURATION MANAGEMENT
# ============================================================================
class Config:
    """Configuration management for persistence"""

    def __init__(self):
        self._config_dir = self._get_config_dir()
        self._config_file = self._config_dir / "config.json"
        self._downloads_dir = self._config_dir / "downloads"
        self._config: Dict[str, Any] = {}
        self._load()

    def _get_config_dir(self) -> Path:
        if platform == 'android':
            from android.storage import app_storage_path
            return Path(app_storage_path()) / ".luister"
        else:
            return Path.home() / ".luister"

    def _load(self):
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._downloads_dir.mkdir(parents=True, exist_ok=True)
        try:
            if self._config_file.exists():
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
        except Exception:
            self._config = {}

    def save(self):
        try:
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2)
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any):
        self._config[key] = value
        self.save()

    @property
    def downloads_dir(self) -> Path:
        return self._downloads_dir

    @property
    def last_playlist(self) -> List[str]:
        return self.get('last_playlist', [])

    @last_playlist.setter
    def last_playlist(self, value: List[str]):
        self.set('last_playlist', value)

    @property
    def last_index(self) -> int:
        return self.get('last_index', 0)

    @last_index.setter
    def last_index(self, value: int):
        self.set('last_index', value)

    @property
    def volume(self) -> float:
        return self.get('volume', 0.7)

    @volume.setter
    def volume(self, value: float):
        self.set('volume', value)


# ============================================================================
# CUSTOM STYLED WIDGETS
# ============================================================================
class GlassPanel(Widget):
    """Glassmorphic panel with blur effect simulation"""

    corner_radius = NumericProperty(dp(16))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._update_canvas, size=self._update_canvas)
        Clock.schedule_once(lambda dt: self._update_canvas())

    def _update_canvas(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            # Main glass background
            Color(*Theme.GLASS_BG)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self.corner_radius])
            # Top highlight for glass effect
            Color(*Theme.GLASS_HIGHLIGHT)
            RoundedRectangle(
                pos=(self.x, self.y + self.height - dp(2)),
                size=(self.width, dp(2)),
                radius=[self.corner_radius, self.corner_radius, 0, 0]
            )
            # Border
            Color(*Theme.GLASS_BORDER)
            Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self.corner_radius),
                width=1
            )


class IconButton(ButtonBehavior, Widget):
    """Custom circular button with icon drawing and press feedback"""

    icon = StringProperty('play')  # play, pause, prev, next, shuffle, loop, folder, youtube
    is_accent = BooleanProperty(False)  # Use accent color background
    is_active = BooleanProperty(False)  # Toggle state
    icon_color = ColorProperty([1, 1, 1, 0.95])
    press_opacity = NumericProperty(1.0)  # Opacity for press feedback

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._pressed = False
        self._press_anim = None
        self.bind(pos=self._draw, size=self._draw, icon=self._draw,
                  is_accent=self._draw, is_active=self._draw, press_opacity=self._draw)
        Clock.schedule_once(lambda dt: self._draw())

    def on_press(self):
        self._pressed = True
        # Cancel any running animation
        if self._press_anim:
            self._press_anim.cancel(self)
        # Dim on press
        self._press_anim = Animation(press_opacity=0.6, duration=0.08, t='out_quad')
        self._press_anim.start(self)

    def on_release(self):
        self._pressed = False
        # Cancel any running animation
        if self._press_anim:
            self._press_anim.cancel(self)
        # Bounce back to full brightness
        self._press_anim = Animation(press_opacity=1.0, duration=0.15, t='out_quad')
        self._press_anim.start(self)

    def _draw(self, *args):
        self.canvas.clear()
        with self.canvas:
            # Calculate dimensions (no scaling - positions stay fixed)
            size = min(self.width, self.height)
            cx, cy = self.center_x, self.center_y
            radius = size / 2

            # Draw shadow
            Color(0, 0, 0, 0.15 * self.press_opacity)
            Ellipse(pos=(cx - radius + dp(1), cy - radius - dp(1)), size=(size, size))

            # Draw button background with press feedback
            if self.is_accent or self.is_active:
                r, g, b = Theme.ACCENT[:3]
                Color(r * self.press_opacity, g * self.press_opacity, b * self.press_opacity, 1)
            else:
                r, g, b, a = Theme.BTN_DARK_BG
                Color(r * self.press_opacity, g * self.press_opacity, b * self.press_opacity, a)

            Ellipse(pos=(cx - radius, cy - radius), size=(size, size))

            # Draw border
            if not self.is_accent and not self.is_active:
                Color(1, 1, 1, 0.1 * self.press_opacity)
                Line(circle=(cx, cy, radius), width=1)

            # Draw icon with press feedback
            if self.is_accent or self.is_active:
                Color(1, 1, 1, 0.95 * self.press_opacity)
            else:
                r, g, b, a = Theme.TEXT_PRIMARY
                Color(r, g, b, a * self.press_opacity)

            icon_size = size * 0.4
            self._draw_icon(cx, cy, icon_size)

    def _draw_icon(self, cx, cy, size):
        """Draw the icon based on type"""
        if self.icon == 'play':
            # Triangle pointing right
            points = [
                cx - size * 0.35, cy + size * 0.5,
                cx - size * 0.35, cy - size * 0.5,
                cx + size * 0.5, cy
            ]
            Line(points=points, width=dp(2), close=True)
            # Fill
            from kivy.graphics import Triangle
            Triangle(points=points)

        elif self.icon == 'pause':
            # Two vertical bars
            bar_width = size * 0.25
            bar_height = size * 0.8
            gap = size * 0.15
            RoundedRectangle(
                pos=(cx - gap - bar_width, cy - bar_height/2),
                size=(bar_width, bar_height),
                radius=[dp(2)]
            )
            RoundedRectangle(
                pos=(cx + gap, cy - bar_height/2),
                size=(bar_width, bar_height),
                radius=[dp(2)]
            )

        elif self.icon == 'prev':
            # Double left arrows
            arrow_size = size * 0.5
            # First arrow
            Line(points=[
                cx + arrow_size * 0.1, cy - arrow_size,
                cx - arrow_size * 0.5, cy,
                cx + arrow_size * 0.1, cy + arrow_size
            ], width=dp(2))
            # Second arrow
            Line(points=[
                cx + arrow_size * 0.6, cy - arrow_size,
                cx, cy,
                cx + arrow_size * 0.6, cy + arrow_size
            ], width=dp(2))

        elif self.icon == 'next':
            # Double right arrows
            arrow_size = size * 0.5
            # First arrow
            Line(points=[
                cx - arrow_size * 0.1, cy - arrow_size,
                cx + arrow_size * 0.5, cy,
                cx - arrow_size * 0.1, cy + arrow_size
            ], width=dp(2))
            # Second arrow
            Line(points=[
                cx - arrow_size * 0.6, cy - arrow_size,
                cx, cy,
                cx - arrow_size * 0.6, cy + arrow_size
            ], width=dp(2))

        elif self.icon == 'shuffle':
            # Crossed arrows
            s = size * 0.5
            Line(points=[cx - s, cy - s * 0.5, cx + s, cy + s * 0.5], width=dp(2))
            Line(points=[cx - s, cy + s * 0.5, cx + s, cy - s * 0.5], width=dp(2))
            # Arrow heads
            Line(points=[cx + s - dp(4), cy + s * 0.5 - dp(4), cx + s, cy + s * 0.5], width=dp(2))
            Line(points=[cx + s - dp(4), cy - s * 0.5 + dp(4), cx + s, cy - s * 0.5], width=dp(2))

        elif self.icon == 'loop':
            # Circular arrow
            s = size * 0.45
            # Draw arc using line segments
            segments = 12
            points = []
            for i in range(segments):
                angle = (i / segments) * 1.7 * math.pi - math.pi * 0.5
                px = cx + s * math.cos(angle)
                py = cy + s * math.sin(angle)
                points.extend([px, py])
            Line(points=points, width=dp(2))
            # Arrow head
            end_angle = 1.2 * math.pi
            ex = cx + s * math.cos(end_angle)
            ey = cy + s * math.sin(end_angle)
            Line(points=[ex - dp(4), ey + dp(4), ex, ey, ex + dp(4), ey + dp(4)], width=dp(2))

        elif self.icon == 'folder':
            # Folder shape
            s = size * 0.5
            # Folder body
            Line(rounded_rectangle=(cx - s, cy - s * 0.6, s * 2, s * 1.2, dp(3)), width=dp(2))
            # Folder tab
            Line(points=[
                cx - s, cy + s * 0.4,
                cx - s * 0.3, cy + s * 0.4,
                cx - s * 0.1, cy + s * 0.6,
                cx + s * 0.3, cy + s * 0.6
            ], width=dp(2))

        elif self.icon == 'youtube':
            # Play button in rectangle
            s = size * 0.5
            Line(rounded_rectangle=(cx - s, cy - s * 0.7, s * 2, s * 1.4, dp(4)), width=dp(2))
            # Triangle
            ts = s * 0.4
            from kivy.graphics import Triangle
            Triangle(points=[
                cx - ts * 0.3, cy + ts,
                cx - ts * 0.3, cy - ts,
                cx + ts * 0.6, cy
            ])

        elif self.icon == 'list':
            # Playlist icon (three lines)
            s = size * 0.5
            for i in range(3):
                y_offset = (i - 1) * s * 0.6
                Line(points=[cx - s, cy + y_offset, cx + s, cy + y_offset], width=dp(2))

        elif self.icon == 'scan':
            # Magnifying glass / refresh icon
            s = size * 0.4
            # Circle
            segments = 16
            points = []
            for i in range(segments):
                angle = (i / segments) * 2 * math.pi
                px = cx - s * 0.2 + s * 0.8 * math.cos(angle)
                py = cy + s * 0.2 + s * 0.8 * math.sin(angle)
                points.extend([px, py])
            points.extend([points[0], points[1]])
            Line(points=points, width=dp(2))
            # Handle
            Line(points=[cx + s * 0.4, cy - s * 0.4, cx + s * 0.8, cy - s * 0.8], width=dp(2.5))

        elif self.icon == 'clear':
            # Trash / X icon
            s = size * 0.5
            # X shape
            Line(points=[cx - s, cy - s, cx + s, cy + s], width=dp(2.5))
            Line(points=[cx - s, cy + s, cx + s, cy - s], width=dp(2.5))

        elif self.icon == 'volume':
            # Speaker icon
            s = size * 0.4
            # Speaker body
            RoundedRectangle(
                pos=(cx - s * 0.8, cy - s * 0.4),
                size=(s * 0.6, s * 0.8),
                radius=[dp(2)]
            )
            # Speaker cone
            from kivy.graphics import Triangle
            Triangle(points=[
                cx - s * 0.2, cy - s * 0.4,
                cx - s * 0.2, cy + s * 0.4,
                cx + s * 0.5, cy + s * 0.8,
            ])
            Triangle(points=[
                cx - s * 0.2, cy - s * 0.4,
                cx + s * 0.5, cy - s * 0.8,
                cx + s * 0.5, cy + s * 0.8,
            ])
            # Sound waves
            Line(points=[cx + s * 0.7, cy - s * 0.3, cx + s * 0.9, cy, cx + s * 0.7, cy + s * 0.3], width=dp(1.5))

        elif self.icon == 'back':
            # Back arrow (single)
            s = size * 0.5
            Line(points=[
                cx + s * 0.3, cy - s,
                cx - s * 0.3, cy,
                cx + s * 0.3, cy + s
            ], width=dp(2.5))


class GestureButton(IconButton):
    """Play button with gesture support: tap=play/pause, swipe=next/prev, hold=stop"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._touch_start = None
        self._touch_start_time = 0
        self._hold_triggered = False
        self._hold_event = None

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._touch_start = touch.pos
            self._touch_start_time = Clock.get_time()
            self._hold_triggered = False
            # Trigger press animation
            self.on_press()
            # Schedule long press detection
            self._hold_event = Clock.schedule_once(self._on_long_press, 0.5)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._touch_start:
            dx = touch.pos[0] - self._touch_start[0]
            # Cancel hold if moved significantly
            if abs(dx) > dp(20) and self._hold_event:
                self._hold_event.cancel()
                self._hold_event = None
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self._touch_start and self.collide_point(*touch.pos):
            # Cancel hold event
            if self._hold_event:
                self._hold_event.cancel()
                self._hold_event = None

            # Trigger release animation
            self.on_release()

            if self._hold_triggered:
                self._touch_start = None
                return True

            dx = touch.pos[0] - self._touch_start[0]
            duration = Clock.get_time() - self._touch_start_time

            app = App.get_running_app()
            if app:
                if abs(dx) > dp(30):
                    # Swipe gesture
                    if dx > 0:
                        app.next_track()
                    else:
                        app.prev_track()
                elif duration < 0.3:
                    # Quick tap - toggle play
                    app.toggle_play()

            self._touch_start = None
            return True
        return super().on_touch_up(touch)

    def _on_long_press(self, dt):
        """Handle long press - stop playback"""
        self._hold_triggered = True
        app = App.get_running_app()
        if app:
            app.stop_playback()
        # Visual feedback
        self._draw()


class StyledSlider(BoxLayout):
    """Custom styled slider matching desktop design"""

    value = NumericProperty(0)
    min_value = NumericProperty(0)
    max_value = NumericProperty(100)
    show_handle = BooleanProperty(True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._touch_active = False
        self.bind(pos=self._draw, size=self._draw, value=self._draw)
        Clock.schedule_once(lambda dt: self._draw())

    def _draw(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            # Track background
            track_height = dp(6)
            track_y = self.center_y - track_height / 2

            Color(*Theme.SLIDER_TRACK)
            RoundedRectangle(
                pos=(self.x + dp(10), track_y),
                size=(self.width - dp(20), track_height),
                radius=[track_height / 2]
            )

            # Filled portion
            fill_width = (self.value - self.min_value) / max(1, self.max_value - self.min_value) * (self.width - dp(20))
            Color(*Theme.ACCENT)
            RoundedRectangle(
                pos=(self.x + dp(10), track_y),
                size=(max(0, fill_width), track_height),
                radius=[track_height / 2]
            )

            # Handle
            if self.show_handle:
                handle_x = self.x + dp(10) + fill_width
                handle_size = dp(20)

                # Handle shadow
                Color(0, 0, 0, 0.2)
                Ellipse(
                    pos=(handle_x - handle_size/2 + dp(1), self.center_y - handle_size/2 - dp(1)),
                    size=(handle_size, handle_size)
                )

                # Handle
                Color(*Theme.SLIDER_HANDLE)
                Ellipse(
                    pos=(handle_x - handle_size/2, self.center_y - handle_size/2),
                    size=(handle_size, handle_size)
                )

                # Handle border
                Color(*Theme.BTN_BORDER)
                Line(circle=(handle_x, self.center_y, handle_size/2), width=1)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._touch_active = True
            self._update_value(touch.pos[0])
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._touch_active:
            self._update_value(touch.pos[0])
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self._touch_active:
            self._touch_active = False
            self._update_value(touch.pos[0])
            return True
        return super().on_touch_up(touch)

    def _update_value(self, touch_x):
        relative_x = (touch_x - self.x - dp(10)) / max(1, self.width - dp(20))
        relative_x = max(0, min(1, relative_x))
        self.value = self.min_value + relative_x * (self.max_value - self.min_value)


class NavigableSlider(StyledSlider):
    """Slider with navigation zones: left 15% = prev, right 15% = next, center = seek"""

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos) and self._touch_active:
            self._touch_active = False

            # Calculate zone
            relative_x = (touch.pos[0] - self.x) / max(1, self.width)

            app = App.get_running_app()
            if app:
                if relative_x < 0.15:
                    app.prev_track()
                elif relative_x > 0.85:
                    app.next_track()
                else:
                    # Normal seek
                    self._update_value(touch.pos[0])
                    app.seek(self.value / 100)
            return True
        return super().on_touch_up(touch)


# ============================================================================
# VISUALIZER
# ============================================================================
class VisualizerWidget(Widget):
    """Real spectrum visualizer with Apple-style gradient bars"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bars = 32
        self.magnitudes = [0.0] * self.bars
        self.target_magnitudes = [0.0] * self.bars
        self._audio_data: Optional[np.ndarray] = None
        self._sample_rate: int = 44100
        self._current_frame: int = 0
        self._is_playing: bool = False
        self._has_audio: bool = False

        self.bind(size=self._draw_bars, pos=self._draw_bars)
        Clock.schedule_interval(self._update_animation, 1/60)

    def set_audio(self, file_path: str):
        if not HAS_NUMPY:
            return

        def load_audio():
            try:
                try:
                    import soundfile as sf
                    data, sr = sf.read(file_path)
                    if len(data.shape) > 1:
                        data = data.mean(axis=1)
                    self._audio_data = data.astype(np.float32)
                    self._sample_rate = sr
                    self._current_frame = 0
                    self._has_audio = True
                except ImportError:
                    self._has_audio = False
            except Exception:
                self._has_audio = False

        threading.Thread(target=load_audio, daemon=True).start()

    def update_position(self, position_ms: float):
        if not self._has_audio or self._audio_data is None:
            return
        frame = int((position_ms / 1000.0) * self._sample_rate)
        self._current_frame = min(frame, len(self._audio_data) - 1)

    def set_playing(self, playing: bool):
        self._is_playing = playing

    def _update_animation(self, dt):
        if self._has_audio and self._is_playing and self._audio_data is not None:
            self._calculate_fft()
        elif not self._is_playing:
            for i in range(self.bars):
                self.magnitudes[i] *= 0.92
        else:
            # Demo animation
            for i in range(self.bars):
                target = random.random() * 0.4 + 0.1
                self.target_magnitudes[i] = target

        for i in range(self.bars):
            diff = self.target_magnitudes[i] - self.magnitudes[i]
            self.magnitudes[i] += diff * 0.25

        self._draw_bars()

    def _calculate_fft(self):
        if self._audio_data is None or not HAS_NUMPY:
            return

        window_size = 2048
        start = max(0, self._current_frame - window_size // 2)
        end = min(len(self._audio_data), start + window_size)

        if end - start < window_size // 2:
            return

        samples = self._audio_data[start:end]
        window = np.hanning(len(samples))
        windowed = samples * window
        fft = np.fft.rfft(windowed)
        magnitudes = np.abs(fft)

        fft_size = len(magnitudes)
        for i in range(self.bars):
            start_idx = int(fft_size * (2 ** (i / self.bars * 4) - 1) / 15)
            end_idx = int(fft_size * (2 ** ((i + 1) / self.bars * 4) - 1) / 15)
            start_idx = max(0, min(start_idx, fft_size - 1))
            end_idx = max(start_idx + 1, min(end_idx, fft_size))
            band_mag = np.mean(magnitudes[start_idx:end_idx])
            normalized = min(1.0, band_mag / 800.0)
            self.target_magnitudes[i] = normalized

    def _draw_bars(self, *args):
        self.canvas.clear()
        with self.canvas:
            # Background
            Color(*Theme.BG_SECONDARY)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(12)])

            # Draw bars
            bar_width = (self.width - dp(24)) / self.bars
            padding = dp(12)

            for i, mag in enumerate(self.magnitudes):
                # Gradient color based on magnitude
                t = mag  # 0 to 1
                r = Theme.VIZ_START[0] * (1-t) + Theme.VIZ_END[0] * t
                g = Theme.VIZ_START[1] * (1-t) + Theme.VIZ_END[1] * t
                b = Theme.VIZ_START[2] * (1-t) + Theme.VIZ_END[2] * t
                Color(r, g, b, 0.9)

                bar_height = max(dp(4), mag * (self.height - dp(24)) * 0.95)
                x = self.x + padding + i * bar_width + dp(1)
                y = self.y + padding
                w = bar_width - dp(2)

                RoundedRectangle(
                    pos=(x, y),
                    size=(w, bar_height),
                    radius=[dp(2), dp(2), 0, 0]
                )


# ============================================================================
# PLAYER CONTROLS
# ============================================================================
class PlayerControls(BoxLayout):
    """Touch-friendly player control buttons with icons"""

    is_playing = BooleanProperty(False)
    is_shuffled = BooleanProperty(False)
    is_looping = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'horizontal'
        self.spacing = dp(8)
        self.padding = [dp(8), dp(8)]

        # Left spacer for centering
        self.add_widget(Widget(size_hint=(1, 1)))

        # Shuffle button
        self.shuffle_btn = IconButton(
            icon='shuffle',
            size_hint=(None, None),
            size=(BUTTON_SIZE, BUTTON_SIZE)
        )
        self.shuffle_btn.bind(on_release=self.on_shuffle)
        self.add_widget(self.shuffle_btn)

        # Previous button
        self.prev_btn = IconButton(
            icon='prev',
            size_hint=(None, None),
            size=(BUTTON_SIZE, BUTTON_SIZE)
        )
        self.prev_btn.bind(on_release=self.on_prev)
        self.add_widget(self.prev_btn)

        # Play/Pause button (larger, accent colored, with gestures)
        self.play_btn = GestureButton(
            icon='play',
            is_accent=True,
            size_hint=(None, None),
            size=(BUTTON_SIZE_LARGE, BUTTON_SIZE_LARGE)
        )
        self.add_widget(self.play_btn)

        # Next button
        self.next_btn = IconButton(
            icon='next',
            size_hint=(None, None),
            size=(BUTTON_SIZE, BUTTON_SIZE)
        )
        self.next_btn.bind(on_release=self.on_next)
        self.add_widget(self.next_btn)

        # Loop button
        self.loop_btn = IconButton(
            icon='loop',
            size_hint=(None, None),
            size=(BUTTON_SIZE, BUTTON_SIZE)
        )
        self.loop_btn.bind(on_release=self.on_loop)
        self.add_widget(self.loop_btn)

        # Right spacer for centering
        self.add_widget(Widget(size_hint=(1, 1)))

    def on_prev(self, instance):
        app = App.get_running_app()
        if app:
            app.prev_track()

    def on_next(self, instance):
        app = App.get_running_app()
        if app:
            app.next_track()

    def on_shuffle(self, instance):
        app = App.get_running_app()
        if app:
            app.shuffle_playlist()
            self.is_shuffled = not self.is_shuffled
            self.shuffle_btn.is_active = self.is_shuffled

    def on_loop(self, instance):
        app = App.get_running_app()
        if app:
            app.toggle_loop()
            self.is_looping = not self.is_looping
            self.loop_btn.is_active = self.is_looping

    def update_play_button(self, is_playing):
        self.is_playing = is_playing
        self.play_btn.icon = 'pause' if is_playing else 'play'
        self.play_btn._draw()


# ============================================================================
# PLAYLIST WIDGETS
# ============================================================================
class PlaylistItem(BoxLayout):
    """Individual playlist item with glass styling - tap to play, long-press for lyrics"""

    index = NumericProperty(0)
    title = StringProperty('')
    file_path = StringProperty('')
    is_current = BooleanProperty(False)

    def __init__(self, index: int, title: str, file_path: str = '', **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'horizontal'
        self.size_hint_y = None
        self.height = dp(56)
        self.padding = [dp(16), dp(8)]
        self.index = index
        self.title = title
        self.file_path = file_path

        # Long press detection
        self._touch_start = None
        self._long_press_event = None
        self._long_press_triggered = False

        self.bind(pos=self._draw_bg, size=self._draw_bg, is_current=self._draw_bg)

        # Index label
        self.index_label = Label(
            text=str(index + 1),
            size_hint=(None, 1),
            width=dp(32),
            font_size=sp(14),
            color=Theme.TEXT_SECONDARY
        )
        self.add_widget(self.index_label)

        # Title label
        self.label = Label(
            text=title,
            halign='left',
            valign='middle',
            font_size=sp(15),
            color=Theme.TEXT_PRIMARY,
            size_hint=(1, 1),
            shorten=True,
            shorten_from='right'
        )
        self.label.bind(size=self.label.setter('text_size'))
        self.add_widget(self.label)

    def _draw_bg(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            if self.is_current:
                # Highlighted background for current playing track
                Color(*Theme.ACCENT[:3], 0.35)
                RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
                # Left accent bar indicator
                Color(*Theme.ACCENT)
                RoundedRectangle(
                    pos=(self.x, self.y + dp(8)),
                    size=(dp(4), self.height - dp(16)),
                    radius=[dp(2)]
                )
            else:
                Color(*Theme.BG_SECONDARY[:3], 0.3)
                RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._touch_start = touch.pos
            self._long_press_triggered = False
            # Schedule long press detection (0.6 seconds)
            self._long_press_event = Clock.schedule_once(self._on_long_press, 0.6)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._touch_start and self._long_press_event:
            # Cancel long press if moved too much
            dx = abs(touch.pos[0] - self._touch_start[0])
            dy = abs(touch.pos[1] - self._touch_start[1])
            if dx > dp(15) or dy > dp(15):
                self._long_press_event.cancel()
                self._long_press_event = None
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self._touch_start and self.collide_point(*touch.pos):
            # Cancel pending long press
            if self._long_press_event:
                self._long_press_event.cancel()
                self._long_press_event = None

            # If long press was triggered, don't do tap action
            if self._long_press_triggered:
                self._touch_start = None
                return True

            # Regular tap - play the track
            app = App.get_running_app()
            if app:
                app.play_index(self.index)
                app.root.current = 'main'

            self._touch_start = None
            return True
        return super().on_touch_up(touch)

    def _on_long_press(self, dt):
        """Handle long press - show lyrics"""
        self._long_press_triggered = True
        self._long_press_event = None
        app = App.get_running_app()
        if app:
            app.show_lyrics_popup(self.title, self.file_path)

    def update_highlight(self, is_current: bool):
        self.is_current = is_current
        if is_current:
            self.label.color = Theme.TEXT_PRIMARY
            self.index_label.color = Theme.ACCENT
        else:
            self.label.color = Theme.TEXT_PRIMARY
            self.index_label.color = Theme.TEXT_SECONDARY


# ============================================================================
# SCREENS
# ============================================================================
class MainScreen(Screen):
    """Main player screen with visualizer and controls"""

    track_title = StringProperty('No track loaded')
    current_time = StringProperty('0:00')
    total_time = StringProperty('0:00')
    progress = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Main layout with dark background
        main_box = BoxLayout(orientation='vertical')

        # Add background
        with main_box.canvas.before:
            Color(*Theme.BG_PRIMARY)
            self._bg_rect = Rectangle(pos=main_box.pos, size=main_box.size)
        main_box.bind(pos=self._update_bg, size=self._update_bg)

        layout = BoxLayout(
            orientation='vertical',
            padding=[dp(16), dp(24), dp(16), dp(16)],
            spacing=dp(12)
        )

        # Track title with glass panel
        title_box = BoxLayout(size_hint=(1, 0.06))
        self.title_label = Label(
            text=self.track_title,
            font_size=sp(18),
            color=Theme.TEXT_PRIMARY,
            halign='center',
            valign='middle',
            shorten=True,
            shorten_from='center'
        )
        self.title_label.bind(width=lambda *x: setattr(self.title_label, 'text_size', (self.title_label.width, None)))
        title_box.add_widget(self.title_label)
        layout.add_widget(title_box)

        # Lyrics display area (above visualizer)
        lyrics_container = BoxLayout(orientation='vertical', size_hint=(1, 0.12), spacing=dp(2))

        # Current lyrics line (main, larger)
        self.lyrics_current = Label(
            text='',
            font_size=sp(16),
            color=Theme.ACCENT,
            halign='center',
            valign='bottom',
            bold=True,
            size_hint=(1, 0.6)
        )
        self.lyrics_current.bind(width=lambda *x: setattr(self.lyrics_current, 'text_size', (self.lyrics_current.width, None)))
        lyrics_container.add_widget(self.lyrics_current)

        # Next lyrics line (dimmer, smaller)
        self.lyrics_next = Label(
            text='',
            font_size=sp(13),
            color=Theme.TEXT_TERTIARY,
            halign='center',
            valign='top',
            size_hint=(1, 0.4)
        )
        self.lyrics_next.bind(width=lambda *x: setattr(self.lyrics_next, 'text_size', (self.lyrics_next.width, None)))
        lyrics_container.add_widget(self.lyrics_next)

        layout.add_widget(lyrics_container)

        # Visualizer
        self.visualizer = VisualizerWidget(size_hint=(1, 0.28))
        layout.add_widget(self.visualizer)

        # Time display
        time_layout = BoxLayout(size_hint=(1, 0.05), spacing=dp(8), padding=[dp(8), 0])
        self.time_current = Label(
            text='0:00',
            size_hint=(0.2, 1),
            font_size=sp(14),
            color=Theme.TEXT_SECONDARY,
            halign='left'
        )
        self.time_current.bind(size=self.time_current.setter('text_size'))

        self.time_total = Label(
            text='0:00',
            size_hint=(0.2, 1),
            font_size=sp(14),
            color=Theme.TEXT_SECONDARY,
            halign='right'
        )
        self.time_total.bind(size=self.time_total.setter('text_size'))

        time_layout.add_widget(self.time_current)
        time_layout.add_widget(Widget(size_hint=(0.6, 1)))
        time_layout.add_widget(self.time_total)
        layout.add_widget(time_layout)

        # Progress slider with navigation zones
        self.progress_slider = NavigableSlider(
            value=0,
            min_value=0,
            max_value=100,
            size_hint=(1, 0.07)
        )
        layout.add_widget(self.progress_slider)

        # Volume control
        volume_layout = BoxLayout(size_hint=(1, 0.06), spacing=dp(12), padding=[dp(8), 0])

        # Volume icon (using IconButton but non-interactive)
        vol_icon = IconButton(
            icon='volume',
            size_hint=(None, None),
            size=(BUTTON_SIZE_SMALL, BUTTON_SIZE_SMALL)
        )
        vol_icon.disabled = True  # Just for display
        volume_layout.add_widget(vol_icon)

        self.volume_slider = StyledSlider(
            value=70,
            min_value=0,
            max_value=100,
            size_hint=(1, 1)
        )
        self.volume_slider.bind(value=self.on_volume)
        volume_layout.add_widget(self.volume_slider)
        layout.add_widget(volume_layout)

        # Player controls
        self.controls = PlayerControls(size_hint=(1, None), height=BUTTON_SIZE_LARGE + dp(16))
        layout.add_widget(self.controls)

        # Bottom action buttons (centered with consistent sizing)
        bottom_layout = BoxLayout(size_hint=(1, None), height=BUTTON_SIZE + dp(16), spacing=dp(24), padding=[dp(16), dp(8)])

        # Left spacer for centering
        bottom_layout.add_widget(Widget(size_hint=(1, 1)))

        self.playlist_btn = IconButton(
            icon='list',
            size_hint=(None, None),
            size=(BUTTON_SIZE, BUTTON_SIZE)
        )
        self.playlist_btn.bind(on_release=self.open_playlist)
        bottom_layout.add_widget(self.playlist_btn)

        self.open_btn = IconButton(
            icon='folder',
            size_hint=(None, None),
            size=(BUTTON_SIZE, BUTTON_SIZE)
        )
        self.open_btn.bind(on_release=self.open_folder)
        bottom_layout.add_widget(self.open_btn)

        self.youtube_btn = IconButton(
            icon='youtube',
            size_hint=(None, None),
            size=(BUTTON_SIZE, BUTTON_SIZE)
        )
        self.youtube_btn.bind(on_release=self.open_youtube)
        bottom_layout.add_widget(self.youtube_btn)

        # Right spacer for centering
        bottom_layout.add_widget(Widget(size_hint=(1, 1)))

        layout.add_widget(bottom_layout)
        main_box.add_widget(layout)

        # Debug footer (one-liner status bar)
        self.debug_label = Label(
            text='Ready',
            size_hint=(1, None),
            height=dp(24),
            font_size=sp(11),
            color=Theme.TEXT_TERTIARY,
            halign='center',
            valign='middle',
            shorten=True,
            shorten_from='left'
        )
        self.debug_label.bind(width=lambda *x: setattr(self.debug_label, 'text_size', (self.debug_label.width, None)))
        main_box.add_widget(self.debug_label)

        self.add_widget(main_box)

    def _update_bg(self, *args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def on_volume(self, instance, value):
        app = App.get_running_app()
        if app:
            app.set_volume(value / 100)

    def open_playlist(self, instance):
        app = App.get_running_app()
        if app:
            app.root.transition = SlideTransition(direction='left')
            app.root.current = 'playlist'

    def open_folder(self, instance):
        app = App.get_running_app()
        if app:
            app.open_folder()

    def open_youtube(self, instance):
        app = App.get_running_app()
        if app:
            app.show_youtube_dialog()

    def update_track_info(self, title: str, duration: float):
        self.title_label.text = title
        mins, secs = divmod(int(duration), 60)
        self.time_total.text = f'{mins}:{secs:02d}'
        # Clear lyrics when track changes
        self.lyrics_current.text = ''
        self.lyrics_next.text = ''

    def update_position(self, position: float, duration: float):
        if duration > 0:
            self.progress_slider.value = (position / duration) * 100
            mins, secs = divmod(int(position), 60)
            self.time_current.text = f'{mins}:{secs:02d}'

    def update_lyrics(self, current_line: str, next_line: str = ''):
        """Update the lyrics display with current and next lines"""
        self.lyrics_current.text = current_line
        self.lyrics_next.text = next_line


class PlaylistScreen(Screen):
    """Playlist management screen with glass styling"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        main_box = BoxLayout(orientation='vertical')

        with main_box.canvas.before:
            Color(*Theme.BG_PRIMARY)
            self._bg_rect = Rectangle(pos=main_box.pos, size=main_box.size)
        main_box.bind(pos=self._update_bg, size=self._update_bg)

        layout = BoxLayout(
            orientation='vertical',
            padding=[dp(16), dp(24), dp(16), dp(16)],
            spacing=dp(12)
        )

        # Header
        header = BoxLayout(size_hint=(1, None), height=BUTTON_SIZE + dp(8), spacing=dp(12))

        back_btn = IconButton(
            icon='back',
            size_hint=(None, None),
            size=(BUTTON_SIZE, BUTTON_SIZE)
        )
        back_btn.bind(on_release=self.go_back)
        header.add_widget(back_btn)

        header.add_widget(Label(
            text='Playlist',
            size_hint=(1, 1),
            font_size=sp(20),
            color=Theme.TEXT_PRIMARY,
            bold=True
        ))

        self.count_label = Label(
            text='0 tracks',
            size_hint=(None, 1),
            width=dp(80),
            font_size=sp(14),
            color=Theme.TEXT_SECONDARY
        )
        header.add_widget(self.count_label)
        layout.add_widget(header)

        # Playlist items with glass background
        scroll_container = BoxLayout(size_hint=(1, 0.8))
        with scroll_container.canvas.before:
            Color(*Theme.GLASS_BG)
            self._scroll_bg = RoundedRectangle(
                pos=scroll_container.pos,
                size=scroll_container.size,
                radius=[dp(16)]
            )
        scroll_container.bind(
            pos=lambda *a: setattr(self._scroll_bg, 'pos', scroll_container.pos),
            size=lambda *a: setattr(self._scroll_bg, 'size', scroll_container.size)
        )

        self.scroll = ScrollView(size_hint=(1, 1))
        self.playlist_grid = GridLayout(
            cols=1,
            spacing=dp(4),
            size_hint_y=None,
            padding=[dp(8), dp(8)]
        )
        self.playlist_grid.bind(minimum_height=self.playlist_grid.setter('height'))
        self.scroll.add_widget(self.playlist_grid)
        scroll_container.add_widget(self.scroll)
        layout.add_widget(scroll_container)

        # Bottom actions
        actions = BoxLayout(size_hint=(1, None), height=BUTTON_SIZE + dp(16), spacing=dp(24))

        # Left spacer for centering
        actions.add_widget(Widget(size_hint=(1, 1)))

        add_btn = IconButton(icon='folder', size_hint=(None, None), size=(BUTTON_SIZE, BUTTON_SIZE))
        add_btn.bind(on_release=self.add_files)
        actions.add_widget(add_btn)

        scan_btn = IconButton(icon='scan', size_hint=(None, None), size=(BUTTON_SIZE, BUTTON_SIZE))
        scan_btn.bind(on_release=self.scan_music)
        actions.add_widget(scan_btn)

        clear_btn = IconButton(icon='clear', size_hint=(None, None), size=(BUTTON_SIZE, BUTTON_SIZE))
        clear_btn.bind(on_release=self.clear_playlist)
        actions.add_widget(clear_btn)

        # Right spacer for centering
        actions.add_widget(Widget(size_hint=(1, 1)))

        layout.add_widget(actions)
        main_box.add_widget(layout)
        self.add_widget(main_box)

    def _update_bg(self, *args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def go_back(self, instance):
        app = App.get_running_app()
        if app:
            app.root.transition = SlideTransition(direction='right')
            app.root.current = 'main'

    def add_files(self, instance):
        app = App.get_running_app()
        if app:
            app.open_folder()

    def scan_music(self, instance):
        app = App.get_running_app()
        if app:
            app.scan_music_directories()

    def clear_playlist(self, instance):
        app = App.get_running_app()
        if app:
            app.clear_playlist()

    def refresh_playlist(self, playlist: List[str], current_index: int):
        self.playlist_grid.clear_widgets()

        for idx, path in enumerate(playlist):
            title = Path(path).stem
            item = PlaylistItem(index=idx, title=title, file_path=path)
            item.update_highlight(idx == current_index)
            self.playlist_grid.add_widget(item)

        self.count_label.text = f'{len(playlist)} tracks'

        # Auto-scroll to current playing item
        if current_index >= 0 and current_index < len(playlist):
            Clock.schedule_once(lambda dt: self._scroll_to_current(current_index, len(playlist)), 0.1)

    def _scroll_to_current(self, current_index: int, total_items: int):
        """Scroll the playlist to show the currently playing item"""
        if total_items <= 0:
            return

        # Calculate relative position (0 = top, 1 = bottom in scroll_y)
        # Item height is dp(56) + dp(4) spacing
        item_height = dp(56) + dp(4)
        total_height = total_items * item_height
        scroll_height = self.scroll.height

        # Only scroll if content is taller than viewport
        if total_height <= scroll_height:
            return

        # Calculate position of current item from top
        item_top = current_index * item_height

        # Center the item in the viewport
        target_scroll_pos = item_top - (scroll_height / 2) + (item_height / 2)

        # Clamp to valid range
        max_scroll = total_height - scroll_height
        target_scroll_pos = max(0, min(target_scroll_pos, max_scroll))

        # Convert to scroll_y (1 = top, 0 = bottom)
        scroll_y = 1 - (target_scroll_pos / max_scroll) if max_scroll > 0 else 1

        # Animate scroll
        Animation(scroll_y=scroll_y, duration=0.3, t='out_cubic').start(self.scroll)


# ============================================================================
# YOUTUBE DOWNLOAD POPUP
# ============================================================================
class YouTubeDownloadPopup(Popup):
    """Popup for YouTube URL input with glass styling"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = ''
        self.separator_height = 0
        self.size_hint = (0.9, 0.45)
        self.auto_dismiss = False
        self.background = ''
        self.background_color = (0, 0, 0, 0)

        # Main container with glass effect
        container = BoxLayout(orientation='vertical')

        with container.canvas.before:
            Color(*Theme.GLASS_BG)
            self._bg = RoundedRectangle(pos=container.pos, size=container.size, radius=[dp(20)])
            Color(*Theme.GLASS_BORDER)
            Line(rounded_rectangle=(0, 0, 100, 100, dp(20)), width=1)
        container.bind(
            pos=lambda *a: setattr(self._bg, 'pos', container.pos),
            size=lambda *a: setattr(self._bg, 'size', container.size)
        )

        layout = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(16))

        # Title
        layout.add_widget(Label(
            text='Download from YouTube',
            font_size=sp(18),
            color=Theme.TEXT_PRIMARY,
            bold=True,
            size_hint=(1, 0.15)
        ))

        # URL input
        self.url_input = TextInput(
            hint_text='Paste YouTube URL here...',
            multiline=False,
            size_hint=(1, 0.2),
            font_size=sp(15),
            background_color=Theme.BG_TERTIARY,
            foreground_color=Theme.TEXT_PRIMARY,
            hint_text_color=Theme.TEXT_TERTIARY,
            cursor_color=Theme.ACCENT,
            padding=[dp(16), dp(12)]
        )
        layout.add_widget(self.url_input)

        # Progress section
        progress_box = BoxLayout(orientation='vertical', size_hint=(1, 0.25), spacing=dp(8))

        self.progress_bar = ProgressBar(max=100, value=0, size_hint=(1, 0.5))
        progress_box.add_widget(self.progress_bar)

        self.status_label = Label(
            text='Enter a YouTube URL',
            size_hint=(1, 0.5),
            font_size=sp(13),
            color=Theme.TEXT_SECONDARY
        )
        progress_box.add_widget(self.status_label)
        layout.add_widget(progress_box)

        # Buttons
        btn_layout = BoxLayout(size_hint=(1, None), height=BUTTON_SIZE + dp(8), spacing=dp(16))

        # Left spacer
        btn_layout.add_widget(Widget(size_hint=(1, 1)))

        self.cancel_btn = IconButton(icon='back', size_hint=(None, None), size=(BUTTON_SIZE, BUTTON_SIZE))
        self.cancel_btn.bind(on_release=lambda x: self.dismiss())
        btn_layout.add_widget(self.cancel_btn)

        self.download_btn = IconButton(icon='youtube', is_accent=True, size_hint=(None, None), size=(BUTTON_SIZE, BUTTON_SIZE))
        self.download_btn.bind(on_release=self.start_download)
        btn_layout.add_widget(self.download_btn)

        # Right spacer
        btn_layout.add_widget(Widget(size_hint=(1, 1)))

        layout.add_widget(btn_layout)
        container.add_widget(layout)
        self.content = container

    def start_download(self, instance):
        url = self.url_input.text.strip()
        if not url:
            self.status_label.text = 'Please enter a URL'
            return

        app = App.get_running_app()
        if app:
            self.download_btn.disabled = True
            self.status_label.text = 'Starting download...'
            app.download_youtube(url, self)

    def update_progress(self, progress: int, status: str):
        self.progress_bar.value = progress
        self.status_label.text = status

    def download_complete(self, success: bool, message: str):
        self.download_btn.disabled = False
        self.status_label.text = message
        if success:
            Clock.schedule_once(lambda dt: self.dismiss(), 1.5)


# ============================================================================
# LYRICS POPUP
# ============================================================================
class LyricsPopup(Popup):
    """Popup for fetching and displaying lyrics with glass styling"""

    def __init__(self, song_title: str, file_path: str, **kwargs):
        super().__init__(**kwargs)
        self.song_title = song_title
        self.file_path = file_path
        self.title = ''
        self.separator_height = 0
        self.size_hint = (0.95, 0.85)
        self.auto_dismiss = True
        self.background = ''
        self.background_color = (0, 0, 0, 0)

        # Main container with glass effect
        container = BoxLayout(orientation='vertical')

        with container.canvas.before:
            Color(*Theme.GLASS_BG)
            self._bg = RoundedRectangle(pos=container.pos, size=container.size, radius=[dp(20)])
        container.bind(
            pos=lambda *a: setattr(self._bg, 'pos', container.pos),
            size=lambda *a: setattr(self._bg, 'size', container.size)
        )

        layout = BoxLayout(orientation='vertical', padding=dp(16), spacing=dp(12))

        # Header with title and close button
        header = BoxLayout(size_hint=(1, None), height=dp(44), spacing=dp(8))

        back_btn = IconButton(icon='back', size_hint=(None, None), size=(BUTTON_SIZE_SMALL, BUTTON_SIZE_SMALL))
        back_btn.bind(on_release=lambda x: self.dismiss())
        header.add_widget(back_btn)

        header.add_widget(Label(
            text=song_title[:40] + ('...' if len(song_title) > 40 else ''),
            font_size=sp(16),
            color=Theme.TEXT_PRIMARY,
            bold=True,
            size_hint=(1, 1),
            halign='left',
            valign='middle'
        ))
        layout.add_widget(header)

        # Status label
        self.status_label = Label(
            text='Tap "Fetch" to download lyrics',
            size_hint=(1, None),
            height=dp(24),
            font_size=sp(13),
            color=Theme.TEXT_SECONDARY
        )
        layout.add_widget(self.status_label)

        # Scrollable lyrics content
        scroll_container = BoxLayout(size_hint=(1, 1))
        with scroll_container.canvas.before:
            Color(*Theme.BG_SECONDARY[:3], 0.5)
            self._scroll_bg = RoundedRectangle(
                pos=scroll_container.pos,
                size=scroll_container.size,
                radius=[dp(12)]
            )
        scroll_container.bind(
            pos=lambda *a: setattr(self._scroll_bg, 'pos', scroll_container.pos),
            size=lambda *a: setattr(self._scroll_bg, 'size', scroll_container.size)
        )

        scroll = ScrollView(size_hint=(1, 1))
        self.lyrics_label = Label(
            text='',
            font_size=sp(14),
            color=Theme.TEXT_PRIMARY,
            halign='left',
            valign='top',
            size_hint_y=None,
            padding=[dp(12), dp(12)]
        )
        self.lyrics_label.bind(texture_size=lambda inst, val: setattr(inst, 'height', val[1] + dp(24)))
        self.lyrics_label.bind(width=lambda inst, val: setattr(inst, 'text_size', (val - dp(24), None)))
        scroll.add_widget(self.lyrics_label)
        scroll_container.add_widget(scroll)
        layout.add_widget(scroll_container)

        # Action buttons
        btn_layout = BoxLayout(size_hint=(1, None), height=BUTTON_SIZE + dp(8), spacing=dp(16))
        btn_layout.add_widget(Widget(size_hint=(1, 1)))

        # Fetch button
        self.fetch_btn = IconButton(icon='scan', is_accent=True, size_hint=(None, None), size=(BUTTON_SIZE, BUTTON_SIZE))
        self.fetch_btn.bind(on_release=self.fetch_lyrics)
        btn_layout.add_widget(self.fetch_btn)

        # Save button (save synced lyrics)
        self.save_btn = IconButton(icon='folder', size_hint=(None, None), size=(BUTTON_SIZE, BUTTON_SIZE))
        self.save_btn.bind(on_release=self.save_lyrics)
        self.save_btn.disabled = True
        btn_layout.add_widget(self.save_btn)

        btn_layout.add_widget(Widget(size_hint=(1, 1)))
        layout.add_widget(btn_layout)

        container.add_widget(layout)
        self.content = container

        # Check if lyrics already exist
        self._check_existing_lyrics()

    def _check_existing_lyrics(self):
        """Check if lyrics file already exists"""
        app = App.get_running_app()
        if app:
            lyrics = app.get_lyrics_for_track(self.file_path)
            if lyrics:
                self.lyrics_label.text = lyrics
                self.status_label.text = 'Lyrics loaded from file'
                self.save_btn.disabled = False

    def fetch_lyrics(self, instance):
        """Fetch lyrics from online API"""
        self.fetch_btn.disabled = True
        self.status_label.text = 'Searching for lyrics...'

        app = App.get_running_app()
        if app:
            app.fetch_lyrics(self.song_title, self)

    def update_lyrics(self, lyrics: str, status: str):
        """Update the lyrics display"""
        self.lyrics_label.text = lyrics
        self.status_label.text = status
        self.fetch_btn.disabled = False
        if lyrics:
            self.save_btn.disabled = False

    def save_lyrics(self, instance):
        """Save lyrics to file"""
        if not self.lyrics_label.text:
            return

        app = App.get_running_app()
        if app:
            success = app.save_lyrics_for_track(self.file_path, self.lyrics_label.text)
            if success:
                self.status_label.text = 'Lyrics saved!'
            else:
                self.status_label.text = 'Failed to save lyrics'


# ============================================================================
# MAIN APPLICATION
# ============================================================================
class LuisterApp(App):
    """Main Kivy application with full music player functionality"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config_manager = Config()
        self.sound: Optional[Any] = None
        self.playlist: List[str] = []
        self.current_index: int = -1
        self.is_playing: bool = False
        self.is_looping: bool = False
        self._update_event = None
        self._download_thread: Optional[threading.Thread] = None

        # Lyrics management
        self._lyrics_dir = self.config_manager._config_dir / "lyrics"
        self._current_lyrics: List[tuple] = []  # List of (timestamp_seconds, text)
        self._current_lyrics_index: int = -1

    def log(self, msg: str):
        """Update debug footer with a message (thread-safe)"""
        def update(dt):
            if hasattr(self, 'main_screen') and hasattr(self.main_screen, 'debug_label'):
                self.main_screen.debug_label.text = str(msg)[:100]
        Clock.schedule_once(update, 0)

    def build(self):
        self.title = 'Luister'
        Window.clearcolor = Theme.BG_PRIMARY

        from kivy.uix.screenmanager import FadeTransition
        sm = ScreenManager(transition=FadeTransition(duration=0.5))

        # Add splash screen first (initial screen)
        self.splash_screen = SplashScreen(name='splash')
        sm.add_widget(self.splash_screen)

        self.main_screen = MainScreen(name='main')
        self.playlist_screen = PlaylistScreen(name='playlist')

        sm.add_widget(self.main_screen)
        sm.add_widget(self.playlist_screen)

        return sm

    def on_start(self):
        self._update_event = Clock.schedule_interval(self._update_position, 0.1)

        volume = self.config_manager.volume
        self.main_screen.volume_slider.value = volume * 100

        last_playlist = self.config_manager.last_playlist
        if last_playlist:
            valid_files = [p for p in last_playlist if os.path.exists(p)]
            if valid_files:
                self.playlist = valid_files
                self.current_index = min(self.config_manager.last_index, len(valid_files) - 1)
                self.playlist_screen.refresh_playlist(self.playlist, self.current_index)
                self.main_screen.update_track_info(
                    f'{len(self.playlist)} tracks loaded',
                    0
                )

        if not self.playlist:
            self.scan_music_directories()

    def on_stop(self):
        if self._update_event:
            self._update_event.cancel()
        if self.sound:
            self.sound.stop()

        self.config_manager.last_playlist = self.playlist
        self.config_manager.last_index = self.current_index
        self.config_manager.save()

    def scan_music_directories(self):
        music_dirs = []

        if platform == 'android':
            music_dirs = [
                '/storage/emulated/0/Music',
                '/storage/emulated/0/Download',
                '/storage/emulated/0/Downloads',
            ]
        else:
            music_dirs = [
                str(Path.home() / 'Music'),
                str(Path.home() / 'Downloads'),
            ]

        music_dirs.append(str(self.config_manager.downloads_dir))

        audio_exts = {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.webm', '.opus'}
        found_files: List[str] = []

        for music_dir in music_dirs:
            if os.path.exists(music_dir):
                try:
                    for f in os.listdir(music_dir):
                        if Path(f).suffix.lower() in audio_exts:
                            full_path = os.path.join(music_dir, f)
                            if os.path.isfile(full_path) and full_path not in found_files:
                                found_files.append(full_path)
                except PermissionError:
                    pass

        if found_files:
            found_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            self.playlist = found_files[:100]
            self.current_index = 0 if self.playlist else -1
            self.playlist_screen.refresh_playlist(self.playlist, self.current_index)
            self.main_screen.update_track_info(
                f'{len(self.playlist)} tracks found',
                0
            )

    def open_folder(self):
        if not HAS_FILECHOOSER:
            self.main_screen.title_label.text = 'File picker not available'
            return

        try:
            filechooser.open_file(
                on_selection=self._on_files_selected,
                multiple=True,
                filters=[('Audio Files', '*.mp3', '*.wav', '*.ogg', '*.m4a', '*.flac', '*.opus', '*.webm', '*.aac')]
            )
        except Exception as e:
            self.main_screen.title_label.text = f'Error: {str(e)[:30]}'

    def _on_files_selected(self, selection):
        if selection:
            audio_exts = {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.webm', '.opus'}
            valid_files = [f for f in selection if Path(f).suffix.lower() in audio_exts]

            if valid_files:
                self.playlist = valid_files
                self.current_index = 0
                self.playlist_screen.refresh_playlist(self.playlist, self.current_index)
                self.play_index(0)

                self.config_manager.last_playlist = self.playlist
                self.config_manager.save()

    def _update_position(self, dt):
        if self.sound and self.is_playing:
            try:
                # Handle both AndroidMediaPlayer (get_pos) and Kivy Sound (.pos)
                if hasattr(self.sound, 'get_pos'):
                    pos = self.sound.get_pos() or 0
                else:
                    pos = self.sound.pos or 0
                length = self.sound.length or 1
                self.main_screen.update_position(pos, length)
                self.main_screen.visualizer.update_position(pos * 1000)

                # Update synced lyrics display
                self.update_lyrics_display(pos)

                if pos >= length - 0.5:
                    self.next_track()
            except Exception:
                pass

    def load_track(self, path: str) -> bool:
        self.log(f'Loading: {Path(path).name}')

        if self.sound:
            self.sound.stop()
            self.sound.unload()
            self.sound = None

        try:
            self.sound = load_audio(path, logger=self.log)
            if self.sound:
                title = Path(path).stem
                duration = self.sound.length or 0
                self.log(f'Loaded: {title} ({duration:.1f}s)')
                self.main_screen.update_track_info(title, duration)
                self.sound.volume = self.config_manager.volume
                self.main_screen.visualizer.set_audio(path)
                # Load synced lyrics if available
                self.load_lyrics_for_current_track()
                return True
            else:
                self.log(f'Audio load failed: {Path(path).suffix}')
        except Exception as e:
            self.log(f'Load error: {e}')
        return False

    def toggle_play(self):
        if not self.sound and self.playlist:
            self.play_index(0 if self.current_index < 0 else self.current_index)
            return

        if self.sound:
            if self.is_playing:
                self.sound.stop()
                self.is_playing = False
                self.main_screen.visualizer.set_playing(False)
            else:
                self.sound.play()
                self.is_playing = True
                self.main_screen.visualizer.set_playing(True)

            self.main_screen.controls.update_play_button(self.is_playing)

    def stop_playback(self):
        """Stop playback and reset to beginning"""
        if self.sound:
            self.sound.stop()
            self.sound.seek(0)
            self.is_playing = False
            self.main_screen.visualizer.set_playing(False)
            self.main_screen.controls.update_play_button(False)
            self.main_screen.update_position(0, self.sound.length or 1)

    def play_index(self, index: int):
        if 0 <= index < len(self.playlist):
            self.current_index = index
            if self.load_track(self.playlist[index]):
                self.sound.play()
                self.is_playing = True
                self.main_screen.controls.update_play_button(True)
                self.main_screen.visualizer.set_playing(True)

                self.playlist_screen.refresh_playlist(self.playlist, self.current_index)

                self.config_manager.last_index = self.current_index
                self.config_manager.save()

    def next_track(self):
        if self.playlist:
            if self.is_looping:
                self.play_index(self.current_index)
            else:
                next_idx = (self.current_index + 1) % len(self.playlist)
                self.play_index(next_idx)

    def prev_track(self):
        if self.playlist:
            prev_idx = (self.current_index - 1) % len(self.playlist)
            self.play_index(prev_idx)

    def seek(self, percent: float):
        if self.sound and self.sound.length:
            try:
                self.sound.seek(percent * self.sound.length)
            except Exception:
                pass

    def set_volume(self, level: float):
        if self.sound:
            self.sound.volume = level
        self.config_manager.volume = level

    def shuffle_playlist(self):
        if len(self.playlist) > 1:
            current_track = self.playlist[self.current_index] if self.current_index >= 0 else None
            random.shuffle(self.playlist)

            if current_track:
                try:
                    self.current_index = self.playlist.index(current_track)
                except ValueError:
                    self.current_index = 0

            self.playlist_screen.refresh_playlist(self.playlist, self.current_index)

    def toggle_loop(self):
        self.is_looping = not self.is_looping

    def clear_playlist(self):
        if self.sound:
            self.sound.stop()
            self.sound.unload()
            self.sound = None
        self.playlist = []
        self.current_index = -1
        self.is_playing = False
        self.main_screen.controls.update_play_button(False)
        self.main_screen.visualizer.set_playing(False)
        self.playlist_screen.refresh_playlist([], -1)
        self.main_screen.update_track_info('No track loaded', 0)

    def show_youtube_dialog(self):
        popup = YouTubeDownloadPopup()
        popup.open()

    def download_youtube(self, url: str, popup: YouTubeDownloadPopup):
        app = self

        def download_task():
            app.log('Importing yt-dlp...')
            try:
                import yt_dlp
            except ImportError as e:
                app.log(f'Import error: {e}')
                Clock.schedule_once(
                    lambda dt: popup.download_complete(False, 'yt-dlp not installed'), 0
                )
                return

            try:
                app.log('Starting download...')
                output_dir = self.config_manager.downloads_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                app.log(f'Output: {output_dir}')

                def progress_hook(d):
                    if d.get('status') == 'downloading':
                        total = d.get('total_bytes') or d.get('total_bytes_estimate')
                        downloaded = d.get('downloaded_bytes', 0)
                        if total and total > 0:
                            pct = int((downloaded / total) * 100)
                            app.log(f'Downloading: {pct}%')
                            Clock.schedule_once(
                                lambda dt, p=pct: popup.update_progress(p, f'Downloading... {p}%'), 0
                            )
                    elif d.get('status') == 'finished':
                        app.log('Download finished, processing...')
                        Clock.schedule_once(
                            lambda dt: popup.update_progress(100, 'Processing...'), 0
                        )

                # Custom logger to route yt-dlp messages to debug footer
                class DebugLogger:
                    def debug(self, msg): app.log(f'[D] {msg}')
                    def info(self, msg): app.log(f'[I] {msg}')
                    def warning(self, msg): app.log(f'[W] {msg}')
                    def error(self, msg): app.log(f'[E] {msg}')

                # Audio formats supported by Kivy (no FFmpeg needed)
                audio_extensions = ('*.m4a', '*.mp3', '*.ogg', '*.opus', '*.webm', '*.wav', '*.aac')

                ydl_opts = {
                    # Prefer m4a (AAC) which Kivy can play, fallback to best audio
                    'format': 'bestaudio[ext=m4a]/bestaudio/best',
                    'outtmpl': str(output_dir / '%(title)s.%(ext)s'),
                    'progress_hooks': [progress_hook],
                    # No postprocessors - avoid FFmpeg dependency
                    'quiet': True,
                    'no_warnings': True,
                    'logger': DebugLogger(),
                    'noprogress': True,
                    # Bypass bot detection
                    'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
                        'Accept-Language': 'en-US,en;q=0.9',
                    },
                    # Network options
                    'socket_timeout': 30,
                    'retries': 3,
                    'fragment_retries': 3,
                    'no_check_certificates': True,
                }

                # Get all audio files before download
                before_files: set = set()
                for ext in audio_extensions:
                    before_files.update(output_dir.glob(ext))
                app.log('Calling yt-dlp (no FFmpeg)...')

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

                # Get all audio files after download
                after_files: set = set()
                for ext in audio_extensions:
                    after_files.update(output_dir.glob(ext))
                new_files = list(after_files - before_files)
                app.log(f'Found {len(new_files)} new file(s)')

                if new_files:
                    for f in new_files:
                        if str(f) not in self.playlist:
                            self.playlist.insert(0, str(f))

                    def update_ui():
                        self.playlist_screen.refresh_playlist(self.playlist, self.current_index)
                        popup.download_complete(True, f'Downloaded {len(new_files)} file(s)')
                        app.log(f'Done: {new_files[0].name if new_files else ""}')

                        if len(new_files) > 0 and not self.is_playing:
                            self.play_index(0)

                    Clock.schedule_once(lambda dt: update_ui(), 0)
                else:
                    app.log('No audio files found after download')
                    Clock.schedule_once(
                        lambda dt: popup.download_complete(False, 'No files downloaded'), 0
                    )

            except Exception as e:
                error_msg = str(e)
                app.log(f'Error: {error_msg}')
                Clock.schedule_once(
                    lambda dt: popup.download_complete(False, f'Error: {error_msg[:50]}'), 0
                )

        self._download_thread = threading.Thread(target=download_task, daemon=True)
        self._download_thread.start()

    # =========================================================================
    # LYRICS MANAGEMENT
    # =========================================================================
    def show_lyrics_popup(self, song_title: str, file_path: str):
        """Show lyrics popup for a song"""
        popup = LyricsPopup(song_title=song_title, file_path=file_path)
        popup.open()

    def get_lyrics_path(self, audio_path: str) -> Path:
        """Get the lyrics file path for an audio file"""
        self._lyrics_dir.mkdir(parents=True, exist_ok=True)
        # Use audio filename as base for lyrics file
        audio_name = Path(audio_path).stem
        # Sanitize filename
        safe_name = "".join(c for c in audio_name if c.isalnum() or c in (' ', '-', '_')).strip()
        return self._lyrics_dir / f"{safe_name}.lrc"

    def get_lyrics_for_track(self, audio_path: str) -> Optional[str]:
        """Get saved lyrics for a track, returns None if not found"""
        lyrics_path = self.get_lyrics_path(audio_path)
        try:
            if lyrics_path.exists():
                return lyrics_path.read_text(encoding='utf-8')
        except Exception as e:
            self.log(f'Error reading lyrics: {e}')
        return None

    def save_lyrics_for_track(self, audio_path: str, lyrics: str) -> bool:
        """Save lyrics to file"""
        lyrics_path = self.get_lyrics_path(audio_path)
        try:
            lyrics_path.write_text(lyrics, encoding='utf-8')
            self.log(f'Lyrics saved: {lyrics_path.name}')
            return True
        except Exception as e:
            self.log(f'Error saving lyrics: {e}')
            return False

    def parse_lrc_lyrics(self, lrc_text: str) -> List[tuple]:
        """Parse LRC format lyrics into list of (timestamp_seconds, text)"""
        import re
        lyrics = []
        # Match [mm:ss.xx] or [mm:ss] format
        pattern = r'\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)$'

        for line in lrc_text.split('\n'):
            line = line.strip()
            if not line:
                continue

            match = re.match(pattern, line)
            if match:
                mins = int(match.group(1))
                secs = int(match.group(2))
                ms = int(match.group(3) or 0)
                # Normalize milliseconds (could be 2 or 3 digits)
                if len(match.group(3) or '') == 2:
                    ms *= 10
                text = match.group(4).strip()

                timestamp = mins * 60 + secs + ms / 1000.0
                if text:  # Only add non-empty lines
                    lyrics.append((timestamp, text))

        # Sort by timestamp
        lyrics.sort(key=lambda x: x[0])
        return lyrics

    def load_lyrics_for_current_track(self):
        """Load synced lyrics for the currently playing track"""
        self._current_lyrics = []
        self._current_lyrics_index = -1

        if self.current_index < 0 or self.current_index >= len(self.playlist):
            return

        audio_path = self.playlist[self.current_index]
        lyrics_text = self.get_lyrics_for_track(audio_path)

        if lyrics_text:
            self._current_lyrics = self.parse_lrc_lyrics(lyrics_text)
            if self._current_lyrics:
                self.log(f'Loaded {len(self._current_lyrics)} synced lines')
            else:
                # Plain text lyrics (no timestamps) - show as single block
                self.main_screen.update_lyrics(lyrics_text[:200], '')

    def update_lyrics_display(self, position: float):
        """Update lyrics display based on current playback position"""
        if not self._current_lyrics:
            return

        # Find the current lyrics line based on position
        current_idx = -1
        for i, (timestamp, _) in enumerate(self._current_lyrics):
            if timestamp <= position:
                current_idx = i
            else:
                break

        # Only update if changed
        if current_idx != self._current_lyrics_index:
            self._current_lyrics_index = current_idx

            if current_idx >= 0:
                current_text = self._current_lyrics[current_idx][1]
                next_text = ''
                if current_idx + 1 < len(self._current_lyrics):
                    next_text = self._current_lyrics[current_idx + 1][1]
                self.main_screen.update_lyrics(current_text, next_text)
            else:
                # Before first lyrics line
                if self._current_lyrics:
                    self.main_screen.update_lyrics('', self._current_lyrics[0][1])

    def fetch_lyrics(self, song_title: str, popup: 'LyricsPopup'):
        """Fetch lyrics from online API (runs in background thread)"""
        app = self

        def fetch_task():
            app.log(f'Fetching lyrics for: {song_title}')
            try:
                import requests

                # Clean up song title for search
                # Remove common patterns like "(Official Video)", "[Lyrics]", etc.
                import re
                clean_title = re.sub(r'\[.*?\]|\(.*?\)', '', song_title).strip()
                clean_title = re.sub(r'\s+', ' ', clean_title)

                # Try to split into artist and title if there's a separator
                artist = ''
                title = clean_title
                for sep in [' - ', ' – ', ' — ', ' _ ']:
                    if sep in clean_title:
                        parts = clean_title.split(sep, 1)
                        artist = parts[0].strip()
                        title = parts[1].strip()
                        break

                app.log(f'Searching: {artist or "?"} - {title}')

                # Try lyrics.ovh API (free, no key needed)
                lyrics_text = None

                if artist:
                    try:
                        url = f"https://api.lyrics.ovh/v1/{requests.utils.quote(artist)}/{requests.utils.quote(title)}"
                        response = requests.get(url, timeout=10)
                        if response.status_code == 200:
                            data = response.json()
                            lyrics_text = data.get('lyrics', '')
                    except Exception as e:
                        app.log(f'lyrics.ovh error: {e}')

                # If no artist or first API failed, try lrclib.net (has synced lyrics!)
                if not lyrics_text:
                    try:
                        # lrclib provides synced lyrics
                        search_url = f"https://lrclib.net/api/search?q={requests.utils.quote(clean_title)}"
                        response = requests.get(search_url, timeout=10, headers={'User-Agent': 'Luister/1.0'})
                        if response.status_code == 200:
                            results = response.json()
                            if results:
                                # Get synced lyrics if available, else plain
                                best = results[0]
                                lyrics_text = best.get('syncedLyrics') or best.get('plainLyrics', '')
                                app.log(f'Found on lrclib: {best.get("trackName", "")}')
                    except Exception as e:
                        app.log(f'lrclib error: {e}')

                if lyrics_text:
                    Clock.schedule_once(
                        lambda dt: popup.update_lyrics(lyrics_text, 'Lyrics found!'), 0
                    )
                else:
                    Clock.schedule_once(
                        lambda dt: popup.update_lyrics('', 'No lyrics found'), 0
                    )

            except Exception as e:
                app.log(f'Fetch error: {e}')
                Clock.schedule_once(
                    lambda dt: popup.update_lyrics('', f'Error: {str(e)[:50]}'), 0
                )

        threading.Thread(target=fetch_task, daemon=True).start()


def main():
    LuisterApp().run()


if __name__ == '__main__':
    main()
