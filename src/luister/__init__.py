from PyQt6.QtWidgets import (
    QMainWindow,
    QApplication,
    QWidget,
    QPushButton,
    QStyle,
    QSlider,
    QFileDialog,
    QTextEdit,
    QVBoxLayout,
    QLCDNumber,
    QSystemTrayIcon,
    QInputDialog,
    QProgressBar,
    QDockWidget,
    QGraphicsOpacityEffect,
    QMenu,
)
from PyQt6.QtCore import QUrl, QEvent, Qt, QSize, QBuffer, QIODevice, QTimer, QThread, pyqtSignal, QPropertyAnimation
from PyQt6.QtGui import QIcon, QAction, QActionGroup, QPalette, QPixmap
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
import sys
import subprocess
import re
import os
import tempfile
from pathlib import Path
from luister.utils import get_html, convert_duration_to_show
from luister.views import PlaylistUI
import random
from luister.logcnf import setup_logging, log_call
from luister.theme import Theme
from luister.vectors import (
    play_icon,
    pause_icon,
    stop_icon,
    eq_icon,
    folder_icon,
    shuffle_icon,
    loop_icon,
    apply_shadow,
    slider_handle_icon,
    tray_icon,
)
from luister.visualizer import VisualizerWidget
from luister.lyrics import LyricsWidget  # type: ignore
import logging
from typing import Optional, Dict
from luister.manager import get_manager
import json

try:
    from tinytag import TinyTag  # type: ignore
except ImportError:
    TinyTag = None  # type: ignore

setup_logging()

class UI(QMainWindow):
    def __init__(self):
        super(UI, self).__init__()

        # load user config for playlist persistence
        self._config_path = Path.home() / ".luister" / "config.json"
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        except Exception:
            self._config = {}

        # Resolve resources relative to package directory
        base_path = Path(__file__).resolve().parent

        # --- Build main window UI programmatically (Designer-free) ---
        central = QWidget(self)
        self.setCentralWidget(central)

        # Buttons
        def _mk_btn(name: str, x: int, y: int, w: int, h: int) -> QPushButton:
            btn = QPushButton(central)
            btn.setObjectName(name)
            btn.setGeometry(x, y, w, h)
            return btn

        # Create buttons (simplified - fewer buttons, more gestures)
        # Main controls: Open (merged folder+youtube), Play (with swipe for prev/next), Stop
        _mk_btn("open_btn", 0, 0, 44, 44)  # Combined open button with menu
        _mk_btn("play_btn", 0, 0, 56, 56)  # Larger play button - supports swipe gestures
        _mk_btn("stop_btn", 0, 0, 36, 36)
        _mk_btn("shuffle_btn", 0, 0, 36, 36)
        _mk_btn("loop_btn", 0, 0, 36, 36)
        eq_btn = QPushButton("", central); eq_btn.setObjectName("eq_btn"); eq_btn.setGeometry(0, 0, 36, 36)

        # Compact panel width
        panel_width = 480

        # Sliders - full width of panel
        time_slider = QSlider(Qt.Orientation.Horizontal, central)
        time_slider.setObjectName("time_slider")
        time_slider.setGeometry(16, 100, panel_width - 32, 24)

        volume_slider = QSlider(Qt.Orientation.Horizontal, central)
        volume_slider.setObjectName("volume_slider")
        volume_slider.setGeometry(180, 68, 120, 20)

        # Displays - compact layout
        time_lcd = QTextEdit(central)
        time_lcd.setObjectName("time_lcd")
        time_lcd.setGeometry(16, 10, 150, 50)
        time_lcd.setReadOnly(True)

        title_lcd = QTextEdit(central)
        title_lcd.setObjectName("title_lcd")
        title_lcd.setGeometry(180, 10, panel_width - 196, 50)
        title_lcd.setReadOnly(True)

        kbps_lcd = QLCDNumber(central)
        kbps_lcd.setObjectName("lcdNumber_3")
        kbps_lcd.setGeometry(180, 42, 40, 20)

        khz_lcd = QLCDNumber(central)
        khz_lcd.setObjectName("lcdNumber_4")
        khz_lcd.setGeometry(230, 42, 40, 20)

        # YouTube download progress bar
        self.yt_progress = QProgressBar(central)
        self.yt_progress.setObjectName("yt_progress")
        self.yt_progress.setGeometry(16, 195, panel_width - 32, 8)
        self.yt_progress.setRange(0, 0)  # indeterminate
        self.yt_progress.hide()

        # Window size: compact main panel + wide playlist dock
        self.resize(1200, 380)  # wider for larger playlist

        # initial LCD text (replicates old HTML)
        time_lcd.setPlainText('▶    00:00')
        time_lcd.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_path = base_path.parent / 'img' / 'icon.png'
        if icon_path.exists():
            try:
                self.setWindowIcon(QIcon(str(icon_path)))
            except Exception:
                pass

        # Clear hard-coded styles from Designer so palette/stylesheet can work
        self._clear_inline_styles()

        # visualizer window created lazily
        self.visualizer: Optional[VisualizerWidget] = None
        # lyrics window created lazily
        self.lyrics: Optional[LyricsWidget] = None

        # Define widgets (simplified button set)
        # Buttons
        self.open_btn = self.findChild(QPushButton, "open_btn")
        self.play_btn = self.findChild(QPushButton, "play_btn")
        self.stop_btn = self.findChild(QPushButton, "stop_btn")
        self.eq_btn = self.findChild(QPushButton, "eq_btn")
        self.shuffle_btn = self.findChild(QPushButton, 'shuffle_btn')
        self.loop_btn = self.findChild(QPushButton, 'loop_btn')

        # Backwards compatibility - some methods reference these
        self.back_btn = None
        self.next_btn = None
        self.pause_btn = None
        self.download_btn = None
        self.youtube_btn = None
        # No menubar required: use OS theme dynamically and keep all widgets docked and visible.
        # Ensure theme QAction attributes exist so menu-sync calls are safe even without a menubar
        # These actions are checkable placeholders only; the app does not expose a menubar in normal use
        self.system_action = QAction("System", self)
        self.system_action.setCheckable(True)
        self.light_action = QAction("Light", self)
        self.light_action.setCheckable(True)
        self.dark_action = QAction("Dark", self)
        self.dark_action.setCheckable(True)
        # Apply system theme dynamically at startup
        try:
            self._track_system_theme = True
            self._apply_system_theme()
        except Exception:
            pass
        # Set icons for simplified button set
        self.open_btn.setIcon(folder_icon())
        self.play_btn.setIcon(play_icon())
        self.stop_btn.setIcon(stop_icon())
        self.eq_btn.setIcon(eq_icon())
        self.shuffle_btn.setIcon(shuffle_icon())
        self.loop_btn.setIcon(loop_icon())

        # === Modern minimal controls - fewer buttons, more gestures ===
        # Sizes
        open_size = 44
        play_size = 56  # Play button is largest - it's the main control
        small_size = 36
        icon_open = 22
        icon_play = 28
        icon_small = 20

        # Setup Open button with dropdown menu
        self.open_btn.setText("")
        self.open_btn.setFixedSize(open_size, open_size)
        self.open_btn.setIconSize(QSize(icon_open, icon_open))
        self.open_btn.setToolTip("Open music (folder or YouTube)")

        # Create open menu
        self._open_menu = QMenu(self.open_btn)
        self._open_folder_action = self._open_menu.addAction("Open Folder...")
        self._open_youtube_action = self._open_menu.addAction("YouTube URL...")
        self._open_folder_action.triggered.connect(self.download)
        self._open_youtube_action.triggered.connect(self._on_youtube_click)
        self.open_btn.setMenu(self._open_menu)

        # Play button - larger, supports swipe gestures for prev/next
        self.play_btn.setText("")
        self.play_btn.setFixedSize(play_size, play_size)
        self.play_btn.setIconSize(QSize(icon_play, icon_play))
        self.play_btn.setToolTip("Play/Pause (swipe left/right for prev/next)")

        # Install gesture handler on play button
        self._setup_play_button_gestures()

        # Other buttons - uniform small size
        for btn in [self.stop_btn, self.shuffle_btn, self.loop_btn, self.eq_btn]:
            if btn:
                btn.setText("")
                btn.setFixedSize(small_size, small_size)
                btn.setIconSize(QSize(icon_small, icon_small))

        # Position controls in a clean centered row
        y_controls = 140
        gap = 12

        # Calculate total width and center
        total_width = open_size + play_size + small_size * 4 + gap * 5
        start_x = 16

        x = start_x

        # Open button
        self.open_btn.move(x, y_controls + (play_size - open_size) // 2)
        x += open_size + gap

        # Play button (central, largest)
        self.play_btn.move(x, y_controls)
        x += play_size + gap

        # Stop button
        self.stop_btn.move(x, y_controls + (play_size - small_size) // 2)
        x += small_size + gap

        # EQ button
        self.eq_btn.move(x, y_controls + (play_size - small_size) // 2)
        x += small_size + gap

        # Shuffle button
        self.shuffle_btn.move(x, y_controls + (play_size - small_size) // 2)
        x += small_size + gap

        # Loop button
        self.loop_btn.move(x, y_controls + (play_size - small_size) // 2)


        # Loop button is a toggle state
        self.loop_btn.setCheckable(True)

        # Click Buttons - simplified set
        # Note: play_btn click is handled by gesture handler (tap = play/pause)
        self.stop_btn.clicked.connect(self.stop)
        self.shuffle_btn.clicked.connect(self.shuffle)
        self.loop_btn.clicked.connect(self.loop)
        # playlist toggle removed: playlist is always shown as a dock

        #sliders
        self.time_slider = self.findChild(QSlider, 'time_slider')
        self.volume_slider = self.findChild(QSlider, 'volume_slider')

        #set default volume
        self.volume_slider.setValue(20)

        # apply custom vector handle to sliders
        def _apply_slider_style(slider):
            pix = slider_handle_icon().pixmap(QSize(16, 16))
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)  # type: ignore[attr-defined]
            pix.save(buf, 'PNG')
            # use Qt to base64-encode
            b64 = buf.data().toBase64().data().decode()  # type: ignore
            css = f"""
QSlider::groove:horizontal {{
    background: palette(mid);
    height: 6px;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    border-image: url(data:image/png;base64,{b64});
    width: 16px;
    margin: -5px 0;
}}
"""
            slider.setStyleSheet(css)

        if self.time_slider:
            _apply_slider_style(self.time_slider)
        if self.volume_slider:
            _apply_slider_style(self.volume_slider)

        #sliders value change
        self.time_slider.sliderMoved.connect(self.set_position)
        self.volume_slider.valueChanged.connect(self.set_volume)

        #LCD and metadata displays
        self.time_lcd = self.findChild(QTextEdit, 'time_lcd')
        self.kbps_lcd = self.findChild(QLCDNumber, 'lcdNumber_3')
        self.khz_lcd = self.findChild(QLCDNumber, 'lcdNumber_4')
        self.title_lcd = self.findChild(QTextEdit, 'title_lcd')

        # double-click on time_lcd toggles visualizer
        if self.time_lcd is not None:
            self.time_lcd.setCursorWidth(0)
            self.time_lcd.setToolTip("Double-click to show/hide visualizer")
            self.time_lcd.installEventFilter(self)
        # double-click on title_lcd toggles lyrics view
        if self.title_lcd is not None:
            self.title_lcd.setCursorWidth(0)
            self.title_lcd.setToolTip("Double-click to show/hide lyrics")
            self.title_lcd.installEventFilter(self)

        # create media player and audio output (required by Qt6)
        self.audio_output = QAudioOutput()
        self.Player = QMediaPlayer()
        self.Player.setAudioOutput(self.audio_output)

        # monitor system audio device changes via an instance of QMediaDevices
        self._media_devices = QMediaDevices()
        if hasattr(self._media_devices, "defaultAudioOutputChanged"):
            self._media_devices.defaultAudioOutputChanged.connect(self._audio_device_changed)  # type: ignore[attr-defined]
        else:
            # older Qt versions emit audioOutputsChanged when the list changes
            self._media_devices.audioOutputsChanged.connect(  # type: ignore[attr-defined]
                lambda *_: self._audio_device_changed(self._media_devices.defaultAudioOutput())
            )

        # in-memory playlist management
        self.playlist_urls: list[QUrl] = []
        self.current_index: int = -1

        # player signals
        self.Player.playbackStateChanged.connect(self.audiostate_changed)
        self.Player.positionChanged.connect(self.position_changed)
        self.Player.durationChanged.connect(self.duration_changed)
        self.Player.mediaStatusChanged.connect(self.media_status_changed)

        #set value for loop plaing
        self.loop_plaing = False

        self.set_Enabled_button()
        #show The App
        self.show()

        # --- create & show playlist under main window ---
        # Try to load last playlist dir from global state
        last_dir = None
        try:
            state_dir = Path.home() / ".luister" / "states"
            playlist_file = state_dir / "playlistdir.txt"
            if playlist_file.exists():
                last_dir = playlist_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass

        if last_dir and Path(last_dir).is_dir():
            audio_exts = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac'}
            files = [str(p) for p in Path(last_dir).iterdir() if p.suffix.lower() in audio_exts and p.is_file()]
            if files:
                self._add_files(files, replace=True, play_on_load=False)
        else:
            self._ensure_playlist()

        # Visualizer dock
        try:
            self.visualizer_widget = VisualizerWidget()
            self.visualizer_widget.setWindowTitle("Visualizer")
            # generous default size to remain visible when docked
            self.visualizer_widget.resize(420, 420)
            # Ensure visualizer minimum matches lyrics/playlist for readable UI
            try:
                self.visualizer_widget.setMinimumWidth(320)
                self.visualizer_widget.setMinimumHeight(420)
            except Exception:
                pass
            try:
                self.Player.positionChanged.connect(self.visualizer_widget.update_position)
            except Exception:
                pass
            get_manager().register(self.visualizer_widget)
            try:
                self.visualizer_widget.closed.connect(lambda: self.set_visualizer_visible(False))
            except Exception:
                pass
            # Wire visualizer analysis status to UI: show "Visualizer: loading" while analysis runs
            if isinstance(self.visualizer_widget, VisualizerWidget):
                    saved_title: Dict[str, Optional[str]] = {"val": None}

                    def _on_vis_analysis_started():
                        try:
                            # cache current title and show loading indicator
                            saved_title["val"] = self.title_lcd.toPlainText()
                            self.title_lcd.setPlainText('Visualizer: loading')
                        except Exception:
                            pass

                    def _on_vis_analysis_ready(ok: bool):
                        try:
                            if ok:
                                # restore previous title if available
                                prev = saved_title.get("val")
                                if prev is not None:
                                    self.title_lcd.setPlainText(prev)
                                else:
                                    self.title_lcd.setPlainText('Visualizer ready')
                            else:
                                self.title_lcd.setPlainText('Visualizer failed')
                        except Exception:
                            pass

                    self.visualizer_widget.analysis_started.connect(_on_vis_analysis_started)
                    self.visualizer_widget.analysis_ready.connect(_on_vis_analysis_ready)
        except Exception as e:
            from PyQt6.QtWidgets import QLabel
            self.visualizer_widget = QLabel(f"Visualizer failed to initialize: {e}")
        

        self.visualizer_dock = QDockWidget("Visualizer", self)
        self.visualizer_dock.setWidget(self.visualizer_widget)
        self.visualizer_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.visualizer_dock.visibilityChanged.connect(lambda visible: self.set_visualizer_visible(visible))
        # dock to left and don't allow floating to avoid overlap
        self.visualizer_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        try:
            self._make_dock_hide_on_close(self.visualizer_dock)
        except Exception:
            pass
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.visualizer_dock)
        
        # Lyrics dock
        try:
            self.lyrics_widget = LyricsWidget()  # type: ignore
            self.lyrics_widget.setWindowTitle("Lyrics")
            # ensure lyrics area is tall and wide enough
            self.lyrics_widget.resize(320, 420)
            try:
                self.Player.positionChanged.connect(self.lyrics_widget.update_position)
            except Exception:
                pass
            get_manager().register(self.lyrics_widget)
            try:
                self.lyrics_widget.closed.connect(lambda: self.set_lyrics_visible(False))
            except Exception:
                pass
        except Exception as e:
            from PyQt6.QtWidgets import QLabel
            self.lyrics_widget = QLabel(f"Lyrics failed to initialize: {e}")
        self.lyrics_dock = QDockWidget("Lyrics", self)
        self.lyrics_dock.setWidget(self.lyrics_widget)
        self.lyrics_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.lyrics_dock.visibilityChanged.connect(lambda visible: self.set_lyrics_visible(visible))
        # dock to right and prevent floating
        self.lyrics_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        try:
            self._make_dock_hide_on_close(self.lyrics_dock)
        except Exception:
            pass
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.lyrics_dock)
        self._apply_dock_styles()
        # Apply persisted GUI state (visualizer/lyrics visibility) so docks are visible at startup
        try:
            state = self._load_gui_state()
            if state.get('visualizer', '0') == '1':
                try:
                    if self.visualizer_dock is not None:
                        self.visualizer_dock.show()
                        self.visualizer_dock.raise_()
                except Exception:
                    pass
            else:
                try:
                    if self.visualizer_dock is not None:
                        self.visualizer_dock.hide()
                except Exception:
                    pass
            if state.get('lyrics', '0') == '1':
                try:
                    if self.lyrics_dock is not None:
                        self.lyrics_dock.show()
                        self.lyrics_dock.raise_()
                except Exception:
                    pass
            else:
                try:
                    if self.lyrics_dock is not None:
                        self.lyrics_dock.hide()
                except Exception:
                    pass
        except Exception:
            # if loading state fails, default to showing docks
            try:
                if self.visualizer_dock is not None:
                    self.visualizer_dock.show()
                    self.visualizer_dock.raise_()
            except Exception:
                pass
            try:
                if self.lyrics_dock is not None:
                    self.lyrics_dock.show()
                    self.lyrics_dock.raise_()
            except Exception:
                pass

        # --- ensure widgets are instantiated and visible at startup ---
        # Ensure playlist exists and is shown as a dock to avoid overlapping windows
        if not hasattr(self, 'ui') or self.ui is None:
            self._ensure_playlist()
        # ensure playlist widget minimum sizes so it is always readable
        try:
            if isinstance(self.ui, PlaylistUI):
                self.ui.setMinimumWidth(380)  # wider playlist
                self.ui.setMinimumHeight(280)
        except Exception:
            pass
        # Reparent playlist into a dock widget if not already
        try:
            if isinstance(self.ui, PlaylistUI):
                # create a dock for playlist and set fixed size policies
                if not hasattr(self, 'playlist_dock') or self.playlist_dock is None:
                    self.playlist_dock = QDockWidget("Playlist", self)
                    self.playlist_dock.setWidget(self.ui)
                    self.playlist_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
                    self.playlist_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
                    try:
                        self._make_dock_hide_on_close(self.playlist_dock)
                    except Exception:
                        pass
                    # add playlist right of visualizer by default
                    self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.playlist_dock)
                # ensure minimum size so it remains visible - wider for better readability
                try:
                    self.playlist_dock.setMinimumWidth(400)
                    self.playlist_dock.setMinimumHeight(280)
                except Exception:
                    pass
        except Exception:
            pass

        # Show all components and enforce docked layout (no floating/overlap)
        try:
            if hasattr(self, 'playlist_dock') and self.playlist_dock is not None:
                self.playlist_dock.show()
                self.playlist_dock.raise_()
        except Exception:
            pass
        try:
            if self.visualizer_dock is not None:
                self.visualizer_dock.show()
                self.visualizer_dock.raise_()
        except Exception:
            pass
        try:
            if self.lyrics_dock is not None:
                self.lyrics_dock.show()
                self.lyrics_dock.raise_()
        except Exception:
            pass

        # restore last playlist from config (legacy)
        last_paths = self._config.get("last_playlist", [])
        if last_paths and not self.playlist_urls:
            self.playlist_urls.clear()
            if isinstance(self.ui, PlaylistUI):
                self.ui.list_songs.clear()
            for p in last_paths:
                url = QUrl.fromLocalFile(p)
                self.playlist_urls.append(url)
            if isinstance(self.ui, PlaylistUI):
                for i, url in enumerate(self.playlist_urls, 1):
                    self.ui.list_songs.addItem(f"{i}. {url.fileName()}")
            self.set_Enabled_button()
            last_idx = self._config.get("last_index", 0)
            if 0 <= last_idx < len(self.playlist_urls):
                self.current_index = last_idx
                if isinstance(self.ui, PlaylistUI):
                    item = self.ui.list_songs.item(self.current_index)
                    if item:
                        self.ui.list_songs.setCurrentItem(item)
                        self.ui.list_songs.scrollToItem(item)

                    if isinstance(self.ui, PlaylistUI):
                        try:
                            if hasattr(self, 'playlist_dock') and self.playlist_dock is not None:
                                self.playlist_dock.show()
                                self._stack_playlist_below()
                            else:
                                self.ui.show()
                                self._stack_playlist_below()
                        except Exception:
                            try:
                                self.ui.show()
                                self._stack_playlist_below()
                            except Exception:
                                pass

        # track window move/resize to keep playlist docked
        self.installEventFilter(self)

        # Apply system theme initially
        self._apply_system_theme()

        # monitor system palette/theme changes
        QApplication.instance().installEventFilter(self)  # type: ignore

        # register self with component manager
        mgr = get_manager()
        mgr.register(self)

        # pending playback flag for lyrics sync
        self._pending_play_when_lyrics_loaded = False
        # connect handler once lyrics created
        orig_ensure_lyrics = self._ensure_lyrics
        def patched_ensure_lyrics():
            orig_ensure_lyrics()
            if self.lyrics_dock is not None:
                try:
                    widget = self.lyrics_dock.widget()
                    if isinstance(widget, LyricsWidget):
                        widget.segments_ready.connect(self._on_lyrics_ready)  # type: ignore
                except Exception:
                    pass
        self._ensure_lyrics = patched_ensure_lyrics

        # -- System Tray Icon Setup --
        # Create a tray icon using the app's custom icon
        app_icon = self._load_app_icon()
        self.tray_icon = QSystemTrayIcon(app_icon, self)  # type: ignore
        self.tray_icon.activated.connect(self._on_tray_activated)  # type: ignore

        # Create context menu for tray icon
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show")
        show_action.triggered.connect(self._show_from_tray)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.graceful_shutdown)
        self.tray_icon.setContextMenu(tray_menu)

        self.tray_icon.show()
        # Ensure closing child docks does not quit the app. Catch close events on docks and hide instead
        try:
            def _intercept_close(event):
                event.ignore()
                sender = event.sender() if hasattr(event, 'sender') else None
                try:
                    # hide the widget instead of closing
                    widget = event
                except Exception:
                    widget = None
                if widget is not None:
                    try:
                        widget.hide()
                    except Exception:
                        pass
            # We rely on Qt's closeEvent handling per-widget; docks use hide() behavior via closeEvent override where appropriate
        except Exception:
            pass

        # Store the app icon for tray and window
        self._tray_base_icon = app_icon
        # Ensure the application/window taskbar uses the same icon
        try:
            app = QApplication.instance()
            if isinstance(app, QApplication):
                app.setWindowIcon(app_icon)
            self.setWindowIcon(app_icon)
        except Exception:
            pass

    def set_Enabled_button(self):
        """Enable/disable playback buttons based on playlist state."""
        has_songs = bool(self.playlist_urls)
        # Simplified button set
        for btn in [self.play_btn, self.stop_btn, self.shuffle_btn, self.loop_btn]:
            if btn:
                btn.setEnabled(has_songs)

    def _setup_play_button_gestures(self):
        """Install gesture handling on play button for swipe navigation."""
        from PyQt6.QtCore import QPoint

        self._gesture_start_pos = None
        self._gesture_threshold = 30  # Minimum swipe distance in pixels

        # Store original event handlers
        original_press = self.play_btn.mousePressEvent
        original_release = self.play_btn.mouseReleaseEvent
        original_move = self.play_btn.mouseMoveEvent

        def on_press(event):
            self._gesture_start_pos = event.pos()
            self._gesture_is_swipe = False

        def on_move(event):
            if self._gesture_start_pos is not None:
                delta = event.pos() - self._gesture_start_pos
                if abs(delta.x()) > self._gesture_threshold:
                    self._gesture_is_swipe = True

        def on_release(event):
            if self._gesture_start_pos is not None:
                delta = event.pos() - self._gesture_start_pos

                if abs(delta.x()) > self._gesture_threshold:
                    # Swipe detected
                    if delta.x() > 0:
                        # Swipe right -> next
                        self.next()
                    else:
                        # Swipe left -> previous
                        self.back()
                elif not self._gesture_is_swipe:
                    # Tap -> play/pause toggle
                    self.play_pause_toggle()

            self._gesture_start_pos = None
            self._gesture_is_swipe = False

        self.play_btn.mousePressEvent = on_press
        self.play_btn.mouseMoveEvent = on_move
        self.play_btn.mouseReleaseEvent = on_release

    #to previous song
    @log_call()
    def back(self):
        if not self.playlist_urls:
            return
        if self.current_index > 0:
            self.current_index -= 1
        elif self.loop_plaing:
            self.current_index = len(self.playlist_urls) - 1
        else:
            return
        self.play_current()
        self._update_playlist_selection()

    # play/pause toggle via single button (tap on play button)
    @log_call()
    def play_pause_toggle(self):
        """Toggle between play and pause states."""
        if self.Player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.Player.pause()
        elif self.Player.playbackState() == QMediaPlayer.PlaybackState.PausedState:
            self.Player.play()
        else:
            # Stopped state - start playing current track
            if self.playlist_urls and self.current_index >= 0:
                self.play_current()
            else:
                self.Player.play()
        self.update_play_pause_icon()

    # Legacy method name for compatibility
    def play_stop_toggle(self):
        self.play_pause_toggle()

    # maintain separate play() for internal resume calls
    def play(self):
        self.Player.play()

    #pause music
    def pause(self):
        if self.Player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.Player.pause()
        else:
            self.play()

    #stop music
    def stop(self):
        if self.Player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.Player.stop()
        self.update_play_stop_icon()

    #next song
    @log_call()
    def next(self):
        if not self.playlist_urls:
            return
        if self.current_index < len(self.playlist_urls) - 1:
            self.current_index += 1
        elif self.loop_plaing:
            self.current_index = 0
        else:
            return
        self.play_current()
        self._update_playlist_selection()

    #download list of music
    @log_call()
    def download(self):

        try:
            # Open file selection dialog for audio files only. URL workflows are handled
            # by the dedicated YouTube button; this method now only selects songs.
            files, _ = QFileDialog.getOpenFileNames(
                self,
                'Select songs',
                '',
                'Audio Files (*.mp3 *.wav *.flac *.ogg *.m4a *.aac)'
            )
            if files:
                # Persist playlist directory for convenience
                try:
                    first_dir = str(Path(files[0]).parent)
                    self._persist_playlist_dir(first_dir)
                except Exception:
                    pass
                self._ensure_playlist()
                # Prefer showing the docked playlist if it exists to avoid creating
                # or raising a separate floating Playlist window.
                try:
                    if hasattr(self, 'playlist_dock') and self.playlist_dock is not None:
                        self.playlist_dock.show()
                        self.playlist_dock.raise_()
                        self._stack_playlist_below()
                    else:
                        # Fallback for older flows where ui may be a standalone PlaylistUI
                        if isinstance(self.ui, PlaylistUI) and not self.ui.isVisible():
                            self.ui.show()
                except Exception:
                    # Best-effort only; do not fail the add-files flow
                    pass
                self._add_files(files, replace=True)
            else:
                self.title_lcd.setPlainText('No audio files selected')
        except Exception as e:
            self.title_lcd.setPlainText(f'Error: {e}')

    @log_call()
    def _on_youtube_click(self):
        """Prompt for a YouTube URL and use the existing download flow."""
        try:
            url, ok = QInputDialog.getText(self, "Add from YouTube", "Paste YouTube URL:")
            if not ok or not url or not url.strip():
                return
            url = url.strip()
            yt_match = re.match(r"https?://(www\.)?(youtube\.com|youtu\.be)/.+", url)
            if not yt_match:
                self.title_lcd.setPlainText("Invalid YouTube URL")
                return
            # Reuse download flow but start YT thread immediately
            output_dir = Path.home() / ".luister" / "downloads"
            self.title_lcd.setPlainText("Downloading from YouTube…")
            self.yt_progress.setRange(0, 100)  # determinate progress bar
            self.yt_progress.setValue(0)
            self.yt_progress.show()
            self._yt_playback_started = False  # track if playback has been triggered
            self._yt_download_files = []  # will store files when finished
            self._yt_thread = YTDownloadThread(url, output_dir)
            self._yt_thread.progress.connect(self._on_ytdl_progress)
            self._yt_thread.finished.connect(self._on_ytdl_finished)
            self._yt_thread.start()
        except Exception as e:
            self.title_lcd.setPlainText(f"Error starting YouTube download: {e}")

    def _on_ytdl_progress(self, pct: int):  # noqa: D401
        """Handle download progress updates."""
        self.yt_progress.setValue(pct)
        self.title_lcd.setPlainText(f"Downloading from YouTube… {pct}%")

        # Start playback once we reach 10% (and file exists)
        if pct >= 10 and not self._yt_playback_started:
            output_dir = Path.home() / ".luister" / "downloads"
            # Check for partially downloaded files
            partial_files = list(output_dir.glob("*.mp3")) + list(output_dir.glob("*.mp3.part"))
            mp3_files = [f for f in partial_files if f.suffix == ".mp3"]
            if mp3_files:
                # Sort by modification time to get the most recently created file
                newest_file = max(mp3_files, key=lambda f: f.stat().st_mtime)
                self._yt_playback_started = True
                self._yt_download_files = [str(newest_file)]
                self._add_files([str(newest_file)], replace=True, play_on_load=False)
                self.current_index = len(self.playlist_urls) - 1
                # Start playback without lyrics loading (defer to 100%)
                current_url = self.playlist_urls[self.current_index]
                self.Player.setSource(current_url)
                self.Player.play()
                self.update_play_stop_icon()
                # Update title
                text = f"{self.current_index + 1}. {current_url.fileName()}"
                self.title_lcd.setPlainText(f"Playing (downloading {pct}%): {current_url.fileName()}")

    def _on_ytdl_finished(self, files: list):  # noqa: D401
        if not files:
            self.yt_progress.hide()
            self.title_lcd.setPlainText('YouTube download failed')
            return

        # Update progress bar to 100%
        self.yt_progress.setValue(100)

        # Load ALL audio files from the download directory
        output_dir = Path.home() / ".luister" / "downloads"
        audio_exts = {'.mp3', '.m4a', '.webm', '.wav', '.flac', '.ogg', '.aac'}
        all_files = sorted(
            [str(f) for f in output_dir.iterdir() if f.is_file() and f.suffix.lower() in audio_exts],
            key=lambda x: Path(x).stat().st_mtime,
            reverse=True  # newest first
        )

        if self._yt_playback_started:
            # Playback already started at 10%, reload full directory
            self.title_lcd.setPlainText(f"Download complete: {Path(files[0]).name}")
            self.yt_progress.hide()

            # Reload playlist with all files from directory
            self._add_files(all_files, replace=True, play_on_load=False)
            # Find and select the newly downloaded file
            for i, f in enumerate(all_files):
                if f == files[0]:
                    self.current_index = i
                    break

            # Load visualizer if visible
            if self.visualizer_dock is not None and self.visualizer_dock.isVisible():
                widget = self.visualizer_dock.widget()
                if isinstance(widget, VisualizerWidget):
                    current_url = self.playlist_urls[self.current_index]
                    widget.set_audio(current_url.toLocalFile())

            self._update_playlist_selection()
        else:
            # Normal flow - load all files from directory
            self._add_files(all_files, replace=True, play_on_load=False)
            # Find and play the newly downloaded file
            for i, f in enumerate(all_files):
                if f == files[0]:
                    self.current_index = i
                    break
            self.play_current()
            self.yt_progress.hide()
            self._update_playlist_selection()

    def set_volume(self, value):
        # Qt6 handles volume via QAudioOutput (0.0 - 1.0)
        volume_ratio = value / 100
        self.audio_output.setVolume(volume_ratio)
        # some platforms still honour QMediaPlayer.setVolume; harmless otherwise
        try:
            self.Player.setVolume(value)  # type: ignore[attr-defined]
        except Exception:
            pass

        # user feedback – show percentage as tooltip
        self.volume_slider.setToolTip(f"Volume: {value}%")

        # optional: update window title volume icon/emoji based on loudness
        if value == 0:
            vol_icon = "🔇"
        elif value < 30:
            vol_icon = "🔈"
        elif value < 70:
            vol_icon = "🔉"
        else:
            vol_icon = "🔊"
        self.setWindowTitle(f"Luister {vol_icon}")

    def audiostate_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState

        # Control visualizer animation if it exists
        if self.visualizer_dock is not None:
            widget = self.visualizer_dock.widget()
            if isinstance(widget, VisualizerWidget):
                if playing:
                    widget.resume_animation()
                else:
                    widget.pause_animation()

    #update slider position
    def position_changed(self, position):
        self.time_slider.setValue(position)
        duration_list = convert_duration_to_show(position)
        time = duration_list[0] + ':' + duration_list[1]
        self.time_lcd.setHtml(get_html(time))
        try:
            if isinstance(self.ui, PlaylistUI):
                self.ui.time_song_text.setPlainText('0' + time)
        except:
            print('Error Playlist')

    #set slider range
    def duration_changed(self, duration):
        self.time_slider.setRange(0, duration)
        #add duration to song title
        duration_list = convert_duration_to_show(duration)
        text = self.title_lcd.toPlainText() + ' (' + duration_list[0] + ':' + duration_list[1] + ')'
        self.title_lcd.setPlainText(text)

    #set position played song
    def set_position(self, position):
        self.Player.setPosition(position)

    #show title played of song in text input
    def media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.next()

    @log_call()
    def shuffle(self):
        if not self.playlist_urls:
            return
        random.shuffle(self.playlist_urls)
        if isinstance(self.ui, PlaylistUI):
            self.ui.list_songs.clear()
            for i, url in enumerate(self.playlist_urls, 1):
                self.ui.list_songs.addItem(f"{i}. {url.fileName()}")
        self.current_index = 0
        self.play_current()

    @log_call()
    def loop(self):
        """Toggle loop mode for current track."""
        if self.loop_plaing is False:
            self.Player.setLoops(QMediaPlayer.Loops.Infinite)
            self.loop_btn.setChecked(True)
            self.loop_plaing = True
        else:
            self.Player.setLoops(1)
            self.loop_btn.setChecked(False)
            self.loop_plaing = False

    #show error in TextInput
    def handle_errors(self):
        self.play_btn.setEnabled(False)
        if isinstance(self.ui, PlaylistUI):
            self.title_lcd.setPlainText('Error' + str(self.Player.errorString()))

    # ------- Playlist docking/toggle ---------

    def _ensure_playlist(self):
        # Main playlist UI - reuse existing PlaylistUI instance if present
        try:
            if not hasattr(self, 'ui') or not isinstance(self.ui, PlaylistUI):
                self.ui = PlaylistUI(main_window=self)
                self.ui.filesDropped.connect(self._add_files)
                self.ui.list_songs.itemDoubleClicked.connect(self.clicked_song)  # type: ignore[arg-type]
                self.ui.list_songs.lyricsRequested.connect(self._on_lyrics_requested)
                self.ui.list_songs.removeRequested.connect(self._on_remove_requested)
        except Exception as e:
            from PyQt6.QtWidgets import QLabel
            self.ui = QLabel(f"Playlist failed to initialize: {e}")
        # populate once
        if isinstance(self.ui, PlaylistUI):
            self.ui.list_songs.clear()
            for i, url in enumerate(self.playlist_urls, 1):
                self.ui.list_songs.addItem(f"{i}. {url.fileName()}")

        # highlight currently playing song
        self._update_playlist_selection()

    def _update_playlist_selection(self):
        """Ensure the playlist list widget selects & centres current_index."""
        if not hasattr(self, "ui") or self.ui is None:
            return
        if isinstance(self.ui, PlaylistUI):
            if 0 <= self.current_index < self.ui.list_songs.count():
                self.ui.list_songs.setCurrentRow(self.current_index)
                self.ui.list_songs.scrollToItem(self.ui.list_songs.currentItem())

    def _on_lyrics_requested(self, index: int):
        """Handle context menu request to download lyrics for a playlist item."""
        if 0 <= index < len(self.playlist_urls):
            file_path = self.playlist_urls[index].toLocalFile()
            # Ensure lyrics dock is visible
            if self.lyrics_dock is None or not self.lyrics_dock.isVisible():
                self.toggle_lyrics()
            # Load lyrics for the selected file
            if self.lyrics_dock is not None:
                widget = self.lyrics_dock.widget()
                if isinstance(widget, LyricsWidget):
                    widget.show_progress()
                    widget.load_lyrics(file_path)

    def _on_remove_requested(self, index: int):
        """Handle context menu request to remove an item from the playlist."""
        if 0 <= index < len(self.playlist_urls):
            # Remove from playlist_urls
            del self.playlist_urls[index]
            # Adjust current_index if needed
            if self.current_index >= index and self.current_index > 0:
                self.current_index -= 1
            # Refresh playlist display
            if isinstance(self.ui, PlaylistUI):
                self.ui.list_songs.clear()
                for i, url in enumerate(self.playlist_urls, 1):
                    self.ui.list_songs.addItem(f"{i}. {url.fileName()}")
            self._update_playlist_selection()

    @log_call()
    def toggle_playlist(self):
        self._ensure_playlist()
        # Toggle the dock widget instead of floating window
        try:
            if hasattr(self, 'playlist_dock') and self.playlist_dock is not None:
                if self.playlist_dock.isVisible():
                    self.playlist_dock.hide()
                else:
                    self.playlist_dock.show()
                    self.playlist_dock.raise_()
                    self._stack_playlist_below()
                return
        except Exception:
            pass
        # Fallback to previous behaviour
        try:
            if self.ui.isVisible():
                self.ui.hide()
            else:
                self.ui.show()
                self._stack_playlist_below()
        except Exception:
            pass

    @log_call()
    def clicked_song(self, item):  # type: ignore
        try:
            index = int(item.text().split('.')[0]) - 1
            self.current_index = index
            self.play_current()
        except Exception:
            pass

    def __del__(self):
        if hasattr(self, "playlist_urls"):
            del self.playlist_urls

    @log_call()
    def play_current(self):
        """Start playback of the current index."""
        if 0 <= self.current_index < len(self.playlist_urls):
            current_url = self.playlist_urls[self.current_index]

            # persist playing state for future features
            self._persist_playing_state(current_url.toLocalFile())

            self.Player.setSource(current_url)
            self.Player.play()
            self.update_play_stop_icon()

            # feed audio to visualizer
            if self.visualizer_dock is not None and self.visualizer_dock.isVisible():
                widget = self.visualizer_dock.widget()
                if isinstance(widget, VisualizerWidget):
                    widget.set_audio(current_url.toLocalFile())

            # Lyrics are loaded via context menu only, not auto-loaded

            # metadata extraction
            if TinyTag is not None:
                try:
                    tag = TinyTag.get(current_url.toLocalFile())
                    if self.kbps_lcd:
                        self.kbps_lcd.display(int(tag.bitrate or 0))
                    if self.khz_lcd:
                        self.khz_lcd.display(int((tag.samplerate or 0) / 1000))
                except Exception:
                    pass
            # update title display
            text = f"{self.current_index + 1}. {current_url.fileName()}"
            self.title_lcd.setPlainText(text)
            if isinstance(self.ui, PlaylistUI):
                self.ui.time_song_text.setPlainText('00:00')
                self._update_playlist_selection()

    @log_call()
    def handle_dropped_urls(self, urls):
        """Called from PlaylistUI when files are dragged into the list widget."""
        paths = [url.toLocalFile() for url in urls]
        if paths:
            self._add_files(paths)

    @log_call()
    def _add_files(self, file_paths, replace: bool = False, play_on_load: bool = True):
        """Add a list of local file paths to playlist.

        If replace=True the existing in-memory playlist and UI list are cleared first.
        If play_on_load is True, playback starts after loading (default True).
        """
        if replace:
            # clear previous state
            self.playlist_urls.clear()
            if isinstance(self.ui, PlaylistUI):
                self.ui.list_songs.clear()
            self.current_index = -1

        start_index = len(self.playlist_urls) + 1
        for idx, fp in enumerate(file_paths, start=start_index):
            url = QUrl.fromLocalFile(fp)
            self.playlist_urls.append(url)
            if isinstance(self.ui, PlaylistUI):
                self.ui.list_songs.addItem(f"{idx}. {Path(fp).name}")
        self.set_Enabled_button()
        if self.current_index == -1 and self.playlist_urls:
            self.current_index = 0
            if play_on_load:
                self.play_current()

    def set_theme(self, name: str):
        if getattr(self, "_current_theme", None) == name:
            return
        if name == "system":
            self._track_system_theme = True
            self._apply_system_theme()
        else:
            self._track_system_theme = False
            Theme.apply(QApplication.instance(), name)
            self._update_theme_menu(name)
            self._current_theme = name
            # Update dock styles for new theme
            try:
                self._apply_dock_styles()
            except Exception:
                pass

    def _update_theme_menu(self, name: str):
        self.system_action.setChecked(name == "system")
        self.light_action.setChecked(name == "light")
        self.dark_action.setChecked(name == "dark")

    # ---- system theme helpers ----

    def _is_dark_palette(self, pal):
        col = pal.color(QPalette.ColorRole.Window)
        r, g, b, _ = col.getRgb()
        # luminance formula
        return (0.299 * r + 0.587 * g + 0.114 * b) < 128

    def _apply_system_theme(self):
        try:
            scheme = QApplication.instance().styleHints().colorScheme()  # type: ignore[attr-defined]
            if scheme == Qt.ColorScheme.Dark:  # type: ignore[attr-defined]
                name = "dark"
            else:
                name = "light"
        except Exception:
            pal = QApplication.palette()
            name = "dark" if self._is_dark_palette(pal) else "light"
        Theme.apply(QApplication.instance(), name)
        self._update_theme_menu("system")
        self._current_theme = "system"
        # Update dock styles for new theme
        try:
            self._apply_dock_styles()
        except Exception:
            pass

    def _audio_device_changed(self, device):  # noqa: D401
        """Qt signal slot for system default-audio-output changes."""
        try:
            self.audio_output.setDevice(device)
        except Exception as exc:
            # recreate audio output if underlying device no longer valid
            logging.warning("Recreating QAudioOutput after device switch: %s", exc)
            vol = self.audio_output.volume()
            self.audio_output = QAudioOutput(device)
            self.audio_output.setVolume(vol)
            self.Player.setAudioOutput(self.audio_output)

    def eventFilter(self, obj, event):  # noqa: D401
        from PyQt6.QtCore import QEvent
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            if hasattr(self, 'ui') and self.ui.isVisible():
                self._stack_playlist_below()
            visualizer_dock = getattr(self, 'visualizer_dock', None)
            if visualizer_dock is not None and visualizer_dock.isVisible():
                self._stack_visualizer()
            lyrics_dock = getattr(self, 'lyrics_dock', None)
            if lyrics_dock is not None and lyrics_dock.isVisible():
                self._stack_lyrics()
            # hide dependent windows when main window is minimized
            if event.type() == QEvent.Type.WindowStateChange and obj is self:
                if self.isMinimized():
                    if hasattr(self, 'ui'):
                        self.ui.hide()
                    if visualizer_dock is not None:
                        visualizer_dock.hide()
                    if lyrics_dock is not None:
                        lyrics_dock.hide()
        if event.type() == QEvent.Type.MouseButtonDblClick and obj is self.time_lcd:
            self.toggle_visualizer()
            return True
        if event.type() == QEvent.Type.MouseButtonDblClick and obj is self.title_lcd:
            self.toggle_lyrics()
            return True
        if event.type() == QEvent.Type.ApplicationPaletteChange:
            if getattr(self, '_track_system_theme', False):
                self._apply_system_theme()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        """Adjust key widget geometry for responsive resizing without full-layout rewrite.

        This method repositions/resizes main controls based on the current window width
        so the UI remains usable when the user resizes the window.
        """
        try:
            w = self.width()
            # Time slider: maintain left margin and right margin relative to window
            left = 20
            ts_y = 109
            ts_h = 21
            ts_w = max(200, w - 160)
            if hasattr(self, 'time_slider') and self.time_slider is not None:
                try:
                    self.time_slider.setGeometry(left, ts_y, ts_w, ts_h)
                except Exception:
                    pass

            # Title display: expand/shrink with window
            title_x = 210
            title_h = 21
            title_w = max(120, w - 240)
            if hasattr(self, 'title_lcd') and self.title_lcd is not None:
                try:
                    self.title_lcd.setGeometry(title_x, 10, title_w, title_h)
                except Exception:
                    pass

            # Volume slider: anchored near right side of title area
            try:
                vol_w = 131
                vol_x = max(title_x + title_w - vol_w, w - vol_w - 20)
                if hasattr(self, 'volume_slider') and self.volume_slider is not None:
                    self.volume_slider.setGeometry(vol_x, 80, vol_w, 16)
            except Exception:
                pass

            # Reflow control buttons horizontally with spacing (simplified set)
            gap = 12
            x = 20
            y = 140
            play_size = 56  # Play button is largest

            # Simplified button set: open, play, stop, eq, shuffle, loop
            btns = (
                getattr(self, 'open_btn', None),
                getattr(self, 'play_btn', None),
                getattr(self, 'stop_btn', None),
                getattr(self, 'eq_btn', None),
                getattr(self, 'shuffle_btn', None),
                getattr(self, 'loop_btn', None),
            )
            for b in btns:
                try:
                    if b is None:
                        continue
                    # Vertically center smaller buttons relative to play button
                    btn_y = y + (play_size - b.height()) // 2 if b != self.play_btn else y
                    b.move(x, btn_y)
                    x += b.width() + gap
                except Exception:
                    pass
        except Exception:
            pass
        super().resizeEvent(event)

    # --- Unified component visibility toggling and menu sync ---
    def _menu_toggle_visualizer(self, checked):
        self.set_visualizer_visible(checked)
    def _menu_toggle_lyrics(self, checked):
        self.set_lyrics_visible(checked)

    def update_play_pause_icon(self):
        """Update play button icon based on playback state."""
        if self.Player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setIcon(pause_icon())
        else:
            self.play_btn.setIcon(play_icon())

    # Legacy method name for compatibility
    def update_play_stop_icon(self):
        self.update_play_pause_icon()

    def _clear_inline_styles(self):
        from PyQt6.QtWidgets import QWidget
        stack = [self]
        while stack:
            w = stack.pop()
            if isinstance(w, QWidget) and w.styleSheet():  # type: ignore[arg-type]
                w.setStyleSheet("")
            stack.extend(list(w.findChildren(QWidget)))  # type: ignore[arg-type]

    def _load_app_icon(self) -> QIcon:
        """Load the app icon from bundled resources or package directory."""
        # Try multiple locations for the icon
        icon_paths = []

        # For PyInstaller bundles
        if getattr(sys, 'frozen', False):
            app_dir = Path(sys.executable).parent
            if sys.platform == 'darwin':
                icon_paths.extend([
                    app_dir.parent / 'Resources' / 'luister.icns',
                    app_dir.parent / 'Resources' / 'luister.png',
                    app_dir / 'luister.icns',
                    app_dir / 'luister.png',
                ])
            else:
                icon_paths.extend([
                    app_dir / 'luister.ico',
                    app_dir / 'luister.png',
                ])

        # For development: check packaging/icons directory
        base_path = Path(__file__).resolve().parent
        icon_paths.extend([
            base_path.parent.parent / 'packaging' / 'icons' / 'luister.icns',
            base_path.parent.parent / 'packaging' / 'icons' / 'luister.png',
            base_path.parent.parent / 'packaging' / 'icons' / 'luister-512.png',
            base_path / 'icons' / 'luister.png',
        ])

        for icon_path in icon_paths:
            if icon_path.exists():
                return QIcon(str(icon_path))

        # Fallback to the vector tray icon
        return tray_icon()

    def _make_dock_hide_on_close(self, dock):
        """Ensure a QDockWidget hides instead of closing when its titlebar X is clicked.

        This assigns a small closeEvent override on the provided dock that ignores the
        close event and hides the dock. Kept lightweight and tolerant of failures.
        """
        try:
            def _dock_close(ev, d=dock):
                try:
                    ev.ignore()
                except Exception:
                    pass
                try:
                    d.hide()
                except Exception:
                    pass
            dock.closeEvent = _dock_close
        except Exception:
            pass

    def _ensure_visualizer(self):
        """Lazily create the visualizer widget and dock if missing."""
        if getattr(self, 'visualizer_dock', None) is not None:
            return
        try:
            self.visualizer_widget = VisualizerWidget()
            self.visualizer_widget.setWindowTitle("Visualizer")
            self.visualizer_widget.resize(150, 400)
            try:
                self.Player.positionChanged.connect(self.visualizer_widget.update_position)
            except Exception:
                # Player may not be fully initialised yet
                pass
            get_manager().register(self.visualizer_widget)
            try:
                self.visualizer_widget.closed.connect(lambda: self.set_visualizer_visible(False))
            except Exception:
                pass
            self.visualizer_dock = QDockWidget("Visualizer", self)
            self.visualizer_dock.setWidget(self.visualizer_widget)
            self.visualizer_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
            self.visualizer_dock.visibilityChanged.connect(lambda visible: self.set_visualizer_visible(visible))
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.visualizer_dock)
        except Exception as e:
            from PyQt6.QtWidgets import QLabel
            logging.exception("Visualizer init failed: %s", e)
            self.visualizer_widget = QLabel(f"Visualizer failed to initialize: {e}")
            self.visualizer_dock = QDockWidget("Visualizer", self)
            self.visualizer_dock.setWidget(self.visualizer_widget)

    def _ensure_lyrics(self):
        """Lazily create the lyrics widget and dock if missing."""
        if getattr(self, 'lyrics_dock', None) is not None:
            return
        try:
            self.lyrics_widget = LyricsWidget()  # type: ignore
            self.lyrics_widget.setWindowTitle("Lyrics")
            self.lyrics_widget.resize(300, 400)
            try:
                self.Player.positionChanged.connect(self.lyrics_widget.update_position)
            except Exception:
                pass
            get_manager().register(self.lyrics_widget)
            try:
                self.lyrics_widget.closed.connect(lambda: self.set_lyrics_visible(False))
            except Exception:
                pass
            self.lyrics_dock = QDockWidget("Lyrics", self)
            self.lyrics_dock.setWidget(self.lyrics_widget)
            self.lyrics_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
            self.lyrics_dock.visibilityChanged.connect(lambda visible: self.set_lyrics_visible(visible))
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.lyrics_dock)
        except Exception as e:
            from PyQt6.QtWidgets import QLabel
            logging.exception("Lyrics init failed: %s", e)
            self.lyrics_widget = QLabel(f"Lyrics failed to initialize: {e}")
            self.lyrics_dock = QDockWidget("Lyrics", self)
            self.lyrics_dock.setWidget(self.lyrics_widget)

    def set_visualizer_visible(self, visible: bool):
        self.visualizer_dock.setVisible(visible)
        vis_act = getattr(self, 'visualizer_action', None)
        if vis_act is not None:
            vis_act.setChecked(self.visualizer_dock.isVisible())

    def set_lyrics_visible(self, visible: bool):
        if visible:
            widget = self.lyrics_dock.widget()
            from luister.lyrics import LyricsWidget
            if isinstance(widget, LyricsWidget):
                if self.current_index >= 0 and self.current_index < len(self.playlist_urls):
                    current_file = self.playlist_urls[self.current_index].toLocalFile()
                    try:
                        already_transcribing = getattr(widget, '_transcribing', False)
                        current_target = getattr(widget, '_current_audio_file', None)
                    except Exception:
                        already_transcribing = False
                        current_target = None
                    # Avoid starting a duplicate transcription for the same file
                    if not (already_transcribing and current_target == current_file):
                        widget.load_lyrics(current_file)
            self._fade_dock(self.lyrics_dock, fade_in=True)
        else:
            self._fade_dock(self.lyrics_dock, fade_in=False)
        lyr_act = getattr(self, 'lyrics_action', None)
        if lyr_act is not None:
            lyr_act.setChecked(self.lyrics_dock.isVisible())
        # No view menu/actions required when all widgets are always visible

    def _apply_dock_styles(self):
        """Apply crystal glass styling to dock widgets (inherited from theme)."""
        # Clear any custom styles to inherit from the app theme
        for dock in [self.visualizer_dock, self.lyrics_dock, getattr(self, 'playlist_dock', None)]:
            if dock is not None:
                dock.setStyleSheet("")  # Use theme styles

    def _highlight_main_window(self):
        # Animate the main window background color to a highlight and back
        from PyQt6.QtGui import QColor
        from PyQt6.QtCore import QPropertyAnimation
        start_color = self.palette().color(self.backgroundRole())
        highlight_color = QColor(33, 128, 141, 40)  # Subtle teal highlight
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), highlight_color)
        self.setPalette(pal)
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(350)
        anim.setStartValue(1.0)
        anim.setEndValue(1.0)
        def restore_bg():
            pal = self.palette()
            pal.setColor(self.backgroundRole(), start_color)
            self.setPalette(pal)
        anim.finished.connect(restore_bg)
        anim.start()
        self._mainwin_anim = anim

    def _fade_dock(self, dock, fade_in=True):
        if dock is None:
            return
        effect = QGraphicsOpacityEffect(dock)
        dock.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", dock)
        anim.setDuration(250)
        if fade_in:
            anim.setStartValue(0)
            anim.setEndValue(1)
            dock.show()
            self._highlight_main_window()
        else:
            anim.setStartValue(1)
            anim.setEndValue(0)
            def hide_dock():
                dock.hide()
                dock.setGraphicsEffect(None)
            anim.finished.connect(hide_dock)
            self._highlight_main_window()
        anim.start()
        # Keep a reference to prevent garbage collection
        dock._fade_anim = anim

    # Call this after docks are created
    def _ensure_dock_styles(self):
        self._apply_dock_styles()

    def toggle_visualizer(self):
        self.set_visualizer_visible(not (self.visualizer_dock is not None and self.visualizer_dock.isVisible()))
    def toggle_lyrics(self):
        self.set_lyrics_visible(not (self.lyrics_dock is not None and self.lyrics_dock.isVisible()))

    # --- Ensure menu state is updated if user closes component window directly ---
    # (Assumes VisualizerWidget and LyricsWidget can emit a signal or call back on close)
    # If not, we can subclass and override closeEvent to call back here.

    # --- Improved stacking for UX ---
    def _stack_playlist_below(self):
        """Ensure playlist dock is directly adjacent to main window without overlap.
        For docked playlists we snap the dock into the right dock area; for floating (rare) we position it.
        """
        try:
            # If we have a dock wrapper, rely on Qt's docking layout and ensure visibility
            dock = getattr(self, 'playlist_dock', None)
            if dock is not None:
                # ensure dock is attached to right side
                try:
                    self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
                except Exception:
                    pass
                dock.show()
                dock.raise_()
                return
            # Fallback: position floating playlist widget without overlap
            if not hasattr(self, 'ui') or self.ui is None:
                return
            playlist = self.ui
            main_geo = self.geometry()
            gap = 8
            target_x = main_geo.x() + main_geo.width() + gap
            target_y = main_geo.y()
            playlist.move(target_x, target_y)
            playlist.show()
            playlist.raise_()
            # Keep on-screen
            screen = QApplication.primaryScreen()  # type: ignore[attr-defined]
            if screen is not None:
                avail = screen.availableGeometry()
                if playlist.x() + playlist.width() > avail.x() + avail.width():
                    playlist.move(max(avail.x() + gap, avail.x()), playlist.y())
                if playlist.y() + playlist.height() > avail.y() + avail.height():
                    playlist.move(playlist.x(), max(avail.y() + gap, avail.y()))
        except Exception:
            logging.exception("Error stacking playlist window")

    def _stack_visualizer(self):
        """Place the visualizer dock suitably to the left of the main window when floating.
        If docked, ensure it remains visible (no-op)."""
        try:
            dock = getattr(self, 'visualizer_dock', None)
            if dock is None:
                return
            # If the dock is floating, position it to the left of the main window
            if getattr(dock, 'isFloating', lambda: False)():
                main_geo = self.geometry()
                gap = 8
                target_x = main_geo.x() - dock.width() - gap
                target_y = main_geo.y()
                dock.move(target_x, target_y)
                dock.show()
                dock.raise_()
        except Exception:
            logging.exception("Error stacking visualizer dock")

    def _stack_lyrics(self):
        """Place the lyrics dock to the right of the main window when floating.
        If docked, ensure it remains visible (no-op)."""
        try:
            dock = getattr(self, 'lyrics_dock', None)
            if dock is None:
                return
            if getattr(dock, 'isFloating', lambda: False)():
                main_geo = self.geometry()
                gap = 8
                target_x = main_geo.x() + main_geo.width() + gap
                target_y = main_geo.y()
                dock.move(target_x, target_y)
                dock.show()
                dock.raise_()
        except Exception:
            logging.exception("Error stacking lyrics dock")

    @log_call()
    def graceful_shutdown(self):
        """Graceful shutdown: save state, close widgets, stop threads, quit app."""
        try:
            self._persist_gui_state()
            self._persist_playing_state(self.playlist_urls[self.current_index].toLocalFile() if self.playlist_urls and self.current_index >= 0 else "")
            self._persist_playlist_dir(str(Path.home() / ".luister" / "states"))
        except Exception as e:
            logging.error(f"Error saving state during shutdown: {e}")
        try:
            mgr = get_manager()
            mgr.shutdown()
        except Exception as e:
            logging.error(f"Error during manager shutdown: {e}")
        app = QApplication.instance()
        if app is not None:
            app.quit()  # type: ignore[attr-defined]

    @log_call()
    def force_shutdown(self):
        """Immediate shutdown: skip state save, force close all widgets and exit."""
        try:
            mgr = get_manager()
            mgr.shutdown()
        except Exception as e:
            logging.error(f"Error during forced manager shutdown: {e}")
        app = QApplication.instance()
        if app is not None:
            app.exit(1)  # type: ignore[attr-defined]

    def _on_lyrics_ready(self, segments):
        """Slot called when lyrics segments are loaded; resume playback if pending."""
        if getattr(self, '_pending_play_when_lyrics_loaded', False):
            self._pending_play_when_lyrics_loaded = False
            # hide progress bar
            if self.lyrics_dock is not None:
                widget = self.lyrics_dock.widget()
                from luister.lyrics import LyricsWidget
                if isinstance(widget, LyricsWidget):
                    widget.hide_progress()  # type: ignore
            self.Player.play()
            self.update_play_stop_icon()

    def closeEvent(self, event):
        """On window close (X) perform a graceful shutdown.

        This persists state, shuts down registered components, and quits the app.
        If graceful shutdown fails we log and accept the event to allow the close to proceed.
        """
        try:
            self.graceful_shutdown()
        except Exception as exc:
            logging.exception("Error during graceful shutdown triggered by closeEvent: %s", exc)
            try:
                event.accept()
            except Exception:
                pass

    def _persist_gui_state(self):
        try:
            state_dir = Path.home() / ".luister" / "states"
            state_dir.mkdir(parents=True, exist_ok=True)
            gui_file = state_dir / "gui.txt"
            visualizer = "1" if self.visualizer_dock is not None and self.visualizer_dock.isVisible() else "0"
            lyrics = "1" if self.lyrics_dock is not None and self.lyrics_dock.isVisible() else "0"
            with open(gui_file, "w", encoding="utf-8") as f:
                f.write(f"visualizer={visualizer}\nlyrics={lyrics}\n")
        except Exception:
            pass

    def _load_gui_state(self):
        state = {"visualizer": "0", "lyrics": "0"}
        try:
            state_dir = Path.home() / ".luister" / "states"
            gui_file = state_dir / "gui.txt"
            if gui_file.exists():
                for line in gui_file.read_text(encoding="utf-8").splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        state[k.strip()] = v.strip()
        except Exception:
            pass
        return state

    def _on_tray_activated(self, reason):
        """Toggle app windows on tray icon double-click: show/restore or hide to tray.

        Double-click the tray icon to restore the main window and all docks; double-click again
        will hide them to the tray. Single-click behavior is ignored here.
        """
        try:
            # Prefer DoubleClick activation for show/hide toggle
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick:  # type: ignore[attr-defined]
                # If visible and not minimized -> hide to tray
                if self.isVisible() and not self.isMinimized():
                    try:
                        self.hide()
                    except Exception:
                        pass
                    try:
                        if hasattr(self, 'playlist_dock') and self.playlist_dock is not None:
                            self.playlist_dock.hide()
                        elif hasattr(self, 'ui'):
                            self.ui.hide()
                    except Exception:
                        pass
                    try:
                        if self.visualizer_dock is not None:
                            self.visualizer_dock.hide()
                    except Exception:
                        pass
                    try:
                        if self.lyrics_dock is not None:
                            self.lyrics_dock.hide()
                    except Exception:
                        pass
                else:
                    # Show / restore app and docks
                    try:
                        self.show()
                        # ensure window is not minimized
                        try:
                            self.showNormal()
                        except Exception:
                            pass
                        try:
                            self.raise_()
                            self.activateWindow()
                        except Exception:
                            pass
                    except Exception:
                        pass
                    try:
                        if hasattr(self, 'playlist_dock') and self.playlist_dock is not None:
                            self.playlist_dock.show()
                        elif hasattr(self, 'ui'):
                            self.ui.show()
                    except Exception:
                        pass
                    try:
                        if self.visualizer_dock is not None:
                            self.visualizer_dock.show()
                    except Exception:
                        pass
                    try:
                        if self.lyrics_dock is not None:
                            self.lyrics_dock.show()
                    except Exception:
                        pass
        except Exception:
            pass

    def _show_from_tray(self):
        """Show the app from the tray menu."""
        try:
            self.show()
            self.showNormal()
            self.raise_()
            self.activateWindow()
        except Exception:
            pass
        try:
            if hasattr(self, 'playlist_dock') and self.playlist_dock is not None:
                self.playlist_dock.show()
        except Exception:
            pass
        try:
            if self.visualizer_dock is not None:
                self.visualizer_dock.show()
        except Exception:
            pass
        try:
            if self.lyrics_dock is not None:
                self.lyrics_dock.show()
        except Exception:
            pass

    # ---- playing state persistence ----

    def _persist_playing_state(self, file_path: str):
        try:
            state_dir = Path.home() / ".luister" / "states"
            state_dir.mkdir(parents=True, exist_ok=True)
            playing_file = state_dir / "playing.txt"
            with open(playing_file, "w", encoding="utf-8") as f:
                f.write(file_path)
        except Exception:
            pass

    def _persist_playlist_dir(self, dir_path: str):
        try:
            state_dir = Path.home() / ".luister" / "states"
            state_dir.mkdir(parents=True, exist_ok=True)
            playlist_file = state_dir / "playlistdir.txt"
            with open(playlist_file, "w", encoding="utf-8") as f:
                f.write(dir_path)
        except Exception:
            pass

# ---- YouTube downloader thread ----


class YTDownloadThread(QThread):
    """Background thread that uses yt-dlp Python library to fetch audio files from YouTube."""

    finished = pyqtSignal(list)  # list of downloaded file paths
    progress = pyqtSignal(int)  # download progress percentage (0-100)

    def __init__(self, url: str, output_dir: Path):
        super().__init__()
        self._url = url
        self._output_dir = output_dir
        self._last_progress = -1
        self._downloaded_file: str | None = None

    def _progress_hook(self, d: dict):
        """yt-dlp progress hook callback."""
        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            if total and total > 0:
                pct = int((downloaded / total) * 100)
                if pct != self._last_progress:
                    self._last_progress = pct
                    self.progress.emit(pct)
        elif d.get('status') == 'finished':
            self._downloaded_file = d.get('filename')
            self.progress.emit(100)

    def run(self):  # noqa: D401
        try:
            import yt_dlp
        except ImportError:
            logging.error("yt_dlp module not found; please install yt-dlp")
            self.finished.emit([])
            return

        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            before = set(self._output_dir.glob("*.mp3")) | set(self._output_dir.glob("*.m4a")) | set(self._output_dir.glob("*.webm"))

            # Find ffmpeg - first check bundled location, then system paths
            ffmpeg_path = None

            # For PyInstaller bundles, check the app's directory first
            if getattr(sys, 'frozen', False):
                # Running as bundled app
                if sys.platform == 'darwin':
                    # macOS: ffmpeg is in Contents/MacOS/ or Contents/Frameworks/
                    app_dir = Path(sys.executable).parent
                    bundle_paths = [
                        app_dir / 'ffmpeg',
                        app_dir.parent / 'Frameworks' / 'ffmpeg',
                        app_dir.parent / 'Resources' / 'ffmpeg',
                    ]
                else:
                    # Windows/Linux: ffmpeg is next to the executable
                    app_dir = Path(sys.executable).parent
                    bundle_paths = [app_dir / 'ffmpeg', app_dir / 'ffmpeg.exe']

                for bp in bundle_paths:
                    if bp.exists():
                        ffmpeg_path = str(bp)
                        break

            # Fall back to system locations
            if not ffmpeg_path:
                for path in ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg']:
                    if Path(path).exists():
                        ffmpeg_path = path
                        break

            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': str(self._output_dir / '%(title)s.%(ext)s'),
                'progress_hooks': [self._progress_hook],
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
            }

            # Add ffmpeg location if found
            if ffmpeg_path:
                ffmpeg_dir = str(Path(ffmpeg_path).parent)
                ydl_opts['ffmpeg_location'] = ffmpeg_dir
                logging.info("Using ffmpeg from: %s", ffmpeg_dir)
            else:
                logging.warning("ffmpeg not found - audio conversion may fail")

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([self._url])
            except Exception as exc:
                logging.exception("yt-dlp download failed: %s", exc)
                self.finished.emit([])
                return

            after = set(self._output_dir.glob("*.mp3")) | set(self._output_dir.glob("*.m4a")) | set(self._output_dir.glob("*.webm"))
            new_files = [str(p) for p in sorted(after - before)]
            logging.info("yt-dlp downloaded %d new files", len(new_files))
            self.finished.emit(new_files)
        except Exception:
            logging.exception("YTDownloadThread encountered an unexpected error")
            self.finished.emit([])

def main():
    import signal

    app = QApplication(sys.argv)
    UIWindow = UI()

    def _handle_termination(signum, frame):
        try:
            UIWindow.graceful_shutdown()
        except Exception:
            logging.exception("Error during graceful shutdown from signal %s", signum)

    # Register signal handlers for clean termination where supported
    try:
        signal.signal(signal.SIGINT, _handle_termination)
    except Exception:
        pass
    try:
        signal.signal(signal.SIGTERM, _handle_termination)
    except Exception:
        pass

    try:
        app.exec()
    except KeyboardInterrupt:
        try:
            UIWindow.graceful_shutdown()
        except Exception:
            logging.exception("Error during graceful shutdown after KeyboardInterrupt")


if __name__ == "__main__":
    main()