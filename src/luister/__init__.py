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
    folder_icon,
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

        # Create buttons (minimal - just 2 buttons, equal size)
        # Open: folder/youtube menu, Play: tap=play/pause, swipe=prev/next, hold=stop
        btn_size = 52
        _mk_btn("open_btn", 0, 0, btn_size, btn_size)
        _mk_btn("play_btn", 0, 0, btn_size, btn_size)

        # Compact panel width
        panel_width = 480

        # Sliders - positioned below larger time panel
        time_slider = QSlider(Qt.Orientation.Horizontal, central)
        time_slider.setObjectName("time_slider")
        time_slider.setGeometry(16, 120, panel_width - 32, 24)  # Below time_lcd (y=10+100+10)

        volume_slider = QSlider(Qt.Orientation.Horizontal, central)
        volume_slider.setObjectName("volume_slider")
        volume_slider.setGeometry(330, 120, 120, 20)  # Beside title area

        # Displays - time panel 2x larger
        time_lcd = QTextEdit(central)
        time_lcd.setObjectName("time_lcd")
        time_lcd.setGeometry(16, 10, 300, 100)  # 2x width and height
        time_lcd.setReadOnly(True)

        title_lcd = QTextEdit(central)
        title_lcd.setObjectName("title_lcd")
        title_lcd.setGeometry(330, 10, panel_width - 346, 100)  # Adjusted position and height
        title_lcd.setReadOnly(True)

        # Removed unused kbps_lcd and khz_lcd - not visible/useful in minimal UI
        # Note: Download progress bar moved to playlist component (PlaylistUI)

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

        # Define widgets (minimal - just 2 buttons)
        self.open_btn = self.findChild(QPushButton, "open_btn")
        self.play_btn = self.findChild(QPushButton, "play_btn")

        # Backwards compatibility - removed buttons set to None
        self.back_btn = None
        self.next_btn = None
        self.pause_btn = None
        self.stop_btn = None
        self.download_btn = None
        self.youtube_btn = None
        self.eq_btn = None
        self.shuffle_btn = None
        self.loop_btn = None

        # Always follow system theme (no manual theme switching)
        self._track_system_theme = True
        try:
            self._apply_system_theme()
        except Exception:
            pass
        # Set icons for minimal 2-button UI (white icons for contrast on colored bg)
        from PyQt6.QtGui import QColor
        white = QColor(255, 255, 255)
        self.open_btn.setIcon(folder_icon())
        self.play_btn.setIcon(play_icon(white))  # White icon on blue button

        # === Ultra-minimal controls - 2 equal-size buttons ===
        btn_size = 52
        icon_size = 26

        # Setup Open button with dropdown menu
        self.open_btn.setText("")
        self.open_btn.setFixedSize(btn_size, btn_size)
        self.open_btn.setIconSize(QSize(icon_size, icon_size))
        self.open_btn.setToolTip("Open music (folder or YouTube)")

        # Create open menu
        self._open_menu = QMenu(self.open_btn)
        self._open_folder_action = self._open_menu.addAction("Open Folder...")
        self._open_youtube_action = self._open_menu.addAction("YouTube URL...")
        self._open_folder_action.triggered.connect(self.download)
        self._open_youtube_action.triggered.connect(self._on_youtube_click)
        self.open_btn.setMenu(self._open_menu)

        # Play button - gesture-enabled (tap=play/pause, swipe=prev/next, hold=stop)
        self.play_btn.setText("")
        self.play_btn.setFixedSize(btn_size, btn_size)
        self.play_btn.setIconSize(QSize(icon_size, icon_size))
        self.play_btn.setToolTip("Tap: Play/Pause | Swipe: Prev/Next | Hold: Stop")

        # Install gesture handler on play button
        self._setup_play_button_gestures()

        # Position buttons side by side (below slider at y=120+24)
        y_controls = 155
        gap = 12
        x = 16

        self.open_btn.move(x, y_controls)
        x += btn_size + gap
        self.play_btn.move(x, y_controls)

        # Note: All button clicks handled via gesture handlers

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

        # Setup progress bar with prev/next navigation zones
        self._setup_progress_bar_navigation()

        #LCD and metadata displays
        self.time_lcd = self.findChild(QTextEdit, 'time_lcd')
        self.title_lcd = self.findChild(QTextEdit, 'title_lcd')
        # Removed unused LCD displays
        self.kbps_lcd = None
        self.khz_lcd = None

        # double-click on time_lcd toggles visualizer
        if self.time_lcd is not None:
            self.time_lcd.setCursorWidth(0)
            self.time_lcd.setToolTip("Double-click to show/hide visualizer")
            self.time_lcd.installEventFilter(self)
        # title_lcd - no toggle, just display
        if self.title_lcd is not None:
            self.title_lcd.setCursorWidth(0)

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
        # First, ensure playlist UI is created
        self._ensure_playlist()

        # Load songs from the default downloads directory
        downloads_dir = Path.home() / ".luister" / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)

        audio_exts = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.webm'}
        files = sorted(
            [str(p) for p in downloads_dir.iterdir() if p.suffix.lower() in audio_exts and p.is_file()],
            key=lambda x: Path(x).stat().st_mtime,
            reverse=True  # Newest first
        )
        if files:
            self._add_files(files, replace=True, play_on_load=False)

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
                # ensure minimum size so it remains visible - much wider for better readability
                try:
                    self.playlist_dock.setMinimumWidth(600)  # 2x wider
                    self.playlist_dock.setMinimumHeight(350)
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
        # Minimal button set - just play button needs enabling
        if self.play_btn:
            self.play_btn.setEnabled(has_songs)

    def _setup_play_button_gestures(self):
        """Install gesture handling on play button.

        Gestures:
        - Tap: Play/Pause toggle
        - Swipe left/right: Previous/Next track
        - Hold (500ms): Stop and go to beginning
        """
        self._gesture_start_pos = None
        self._gesture_threshold = 30  # Minimum swipe distance in pixels
        self._gesture_is_swipe = False
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_triggered = False

        def on_hold_timeout():
            """Called when hold duration is reached."""
            self._hold_triggered = True
            # Stop and go to beginning
            self.Player.stop()
            self.Player.setPosition(0)
            self.update_play_pause_icon()
            # Visual feedback - briefly show stop state
            self.title_lcd.setPlainText("⏹ Stopped")

        self._hold_timer.timeout.connect(on_hold_timeout)

        def on_press(event):
            self._gesture_start_pos = event.pos()
            self._gesture_is_swipe = False
            self._hold_triggered = False
            # Start hold timer (500ms for hold detection)
            self._hold_timer.start(500)

        def on_move(event):
            if self._gesture_start_pos is not None:
                delta = event.pos() - self._gesture_start_pos
                if abs(delta.x()) > self._gesture_threshold:
                    self._gesture_is_swipe = True
                    # Cancel hold if user starts swiping
                    self._hold_timer.stop()

        def on_release(event):
            # Stop hold timer
            self._hold_timer.stop()

            if self._hold_triggered:
                # Hold was triggered, don't do anything else
                self._gesture_start_pos = None
                return

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

    def _setup_progress_bar_navigation(self):
        """Setup progress bar with prev/next navigation zones.

        - Click on left 15% → previous track
        - Click on right 15% → next track
        - Click in middle → seek to position (normal slider behavior)
        """
        if not self.time_slider:
            return

        # Zone size as fraction of slider width
        self._nav_zone_size = 0.15  # 15% on each side
        self._slider_nav_action: Optional[str] = None

        original_mouse_press = self.time_slider.mousePressEvent
        original_mouse_release = self.time_slider.mouseReleaseEvent

        def on_slider_press(ev):
            slider_width = self.time_slider.width()
            click_x = ev.pos().x()
            zone_width = slider_width * self._nav_zone_size

            if click_x < zone_width:
                # Left zone - will trigger prev on release
                self._slider_nav_action = 'prev'
            elif click_x > slider_width - zone_width:
                # Right zone - will trigger next on release
                self._slider_nav_action = 'next'
            else:
                # Middle zone - normal seek behavior
                self._slider_nav_action = None
                original_mouse_press(ev)

        def on_slider_release(ev):
            if self._slider_nav_action:
                if self._slider_nav_action == 'prev':
                    self.back()
                elif self._slider_nav_action == 'next':
                    self.next()
                self._slider_nav_action = None
            else:
                original_mouse_release(ev)

        self.time_slider.mousePressEvent = on_slider_press  # type: ignore
        self.time_slider.mouseReleaseEvent = on_slider_release  # type: ignore

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

            output_dir = Path.home() / ".luister" / "downloads"
            self.title_lcd.setPlainText("Fetching metadata...")

            # Show progress in playlist component
            if isinstance(self.ui, PlaylistUI):
                self.ui.show_download_progress("Fetching metadata...")

            # Track base index for new items (append to existing playlist)
            self._yt_base_index = len(self.playlist_urls)
            self._yt_items_metadata: list = []  # Store metadata for reference
            self._yt_playback_started = False

            self._yt_thread = YTDownloadThread(url, output_dir)
            # Connect new signals
            self._yt_thread.metadata_ready.connect(self._on_ytdl_metadata)
            self._yt_thread.item_progress.connect(self._on_ytdl_item_progress)
            self._yt_thread.item_complete.connect(self._on_ytdl_item_complete)
            self._yt_thread.item_error.connect(self._on_ytdl_item_error)
            self._yt_thread.finished.connect(self._on_ytdl_finished)
            self._yt_thread.start()
        except Exception as e:
            self.title_lcd.setPlainText(f"Error starting YouTube download: {e}")

    def _on_ytdl_metadata(self, items: list):  # noqa: D401
        """Handle metadata ready - add all items to playlist immediately."""
        self._yt_items_metadata = items
        count = len(items)
        self.title_lcd.setPlainText(f"Found {count} item(s), starting downloads...")

        if isinstance(self.ui, PlaylistUI):
            self.ui.update_download_progress(0, f"Downloading {count} item(s)...")

        # Add all items to playlist with pending status
        for idx, item in enumerate(items):
            title = item.get('title', 'Unknown')
            # Add placeholder to playlist (will be replaced with actual file when complete)
            playlist_idx = len(self.playlist_urls) + 1
            # Create a placeholder URL (will be updated when download completes)
            placeholder_url = QUrl(f"pending://{idx}")
            self.playlist_urls.append(placeholder_url)

            if isinstance(self.ui, PlaylistUI):
                self.ui.list_songs.addItem(f"{playlist_idx}. {title}")
                # Mark as downloading (pending)
                self.ui.set_item_download_status(self._yt_base_index + idx, 'downloading')

        self.set_Enabled_button()
        self._update_playlist_selection()

    def _on_ytdl_item_progress(self, item_idx: int, pct: int):  # noqa: D401
        """Handle per-item download progress."""
        total_items = len(getattr(self, '_yt_items_metadata', []))
        overall_pct = int(((item_idx + pct / 100) / total_items) * 100) if total_items > 0 else pct

        item_title = 'Unknown'
        if hasattr(self, '_yt_items_metadata') and item_idx < len(self._yt_items_metadata):
            item_title = self._yt_items_metadata[item_idx].get('title', 'Unknown')

        if isinstance(self.ui, PlaylistUI):
            self.ui.update_download_progress(overall_pct, f"Downloading ({item_idx + 1}/{total_items}): {item_title[:30]}... {pct}%")

        self.title_lcd.setPlainText(f"Downloading ({item_idx + 1}/{total_items}): {pct}%")

    def _on_ytdl_item_complete(self, item_idx: int, file_path: str):  # noqa: D401
        """Handle individual item download complete."""
        playlist_idx = self._yt_base_index + item_idx

        # Update the placeholder URL with the actual file
        if 0 <= playlist_idx < len(self.playlist_urls):
            self.playlist_urls[playlist_idx] = QUrl.fromLocalFile(file_path)

            # Update playlist item text
            if isinstance(self.ui, PlaylistUI) and playlist_idx < self.ui.list_songs.count():
                item = self.ui.list_songs.item(playlist_idx)
                if item:
                    item.setText(f"{playlist_idx + 1}. {Path(file_path).name}")
                self.ui.set_item_download_status(playlist_idx, 'complete')

        # Start playback of first completed item if not already playing
        if not self._yt_playback_started and item_idx == 0:
            self._yt_playback_started = True
            self.current_index = playlist_idx
            self.play_current()

    def _on_ytdl_item_error(self, item_idx: int, error_msg: str):  # noqa: D401
        """Handle individual item download error."""
        playlist_idx = self._yt_base_index + item_idx

        if isinstance(self.ui, PlaylistUI):
            self.ui.set_item_download_status(playlist_idx, 'error')

        logging.warning("Download failed for item %d: %s", item_idx, error_msg)

    def _on_ytdl_finished(self, files: list):  # noqa: D401
        """Handle download batch completion."""
        # Hide playlist progress bar
        if isinstance(self.ui, PlaylistUI):
            self.ui.hide_download_progress()

        # Log completion
        file_count = len(files)
        logging.info("YouTube download batch complete: %d files", file_count)

        if file_count > 0:
            self.title_lcd.setPlainText(f"Downloaded {file_count} file(s)")
        else:
            # Check if we had metadata - if so, all downloads failed
            if hasattr(self, '_yt_items_metadata') and self._yt_items_metadata:
                self.title_lcd.setPlainText("Downloads failed")
            else:
                self.title_lcd.setPlainText("No items to download")

        # Clean up placeholder URLs (remove any that weren't successfully downloaded)
        # This handles cases where some items failed
        valid_urls = [url for url in self.playlist_urls if not url.toString().startswith('pending://')]
        if len(valid_urls) != len(self.playlist_urls):
            # Rebuild playlist with only valid URLs
            self.playlist_urls = valid_urls
            if isinstance(self.ui, PlaylistUI):
                self.ui.list_songs.clear()
                for idx, url in enumerate(self.playlist_urls):
                    self.ui.list_songs.addItem(f"{idx + 1}. {Path(url.toLocalFile()).name}")

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

            # feed audio to visualizer (always, so it's ready when shown)
            if self.visualizer_dock is not None:
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

            # Always highlight the currently playing song in playlist
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

        # Always update playlist selection to highlight current item
        self._update_playlist_selection()

    # ---- system theme helpers ----

    def _is_dark_palette(self, pal):
        col = pal.color(QPalette.ColorRole.Window)
        r, g, b, _ = col.getRgb()
        # luminance formula
        return (0.299 * r + 0.587 * g + 0.114 * b) < 128

    def _apply_system_theme(self):
        """Apply theme based on system dark/light mode."""
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
        self._current_theme = name
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
        # Lyrics toggle removed - lyrics always visible by default
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
            # Time slider: below time_lcd (y=120)
            left = 16
            ts_y = 120
            ts_h = 24
            ts_w = max(200, w - 160)
            if hasattr(self, 'time_slider') and self.time_slider is not None:
                try:
                    self.time_slider.setGeometry(left, ts_y, ts_w, ts_h)
                except Exception:
                    pass

            # Title display: beside time_lcd (which is 300px wide)
            title_x = 330
            title_h = 100
            title_w = max(120, w - 360)
            if hasattr(self, 'title_lcd') and self.title_lcd is not None:
                try:
                    self.title_lcd.setGeometry(title_x, 10, title_w, title_h)
                except Exception:
                    pass

            # Volume slider: below title area
            try:
                vol_w = 120
                vol_x = 330
                if hasattr(self, 'volume_slider') and self.volume_slider is not None:
                    self.volume_slider.setGeometry(vol_x, ts_y, vol_w, 20)
            except Exception:
                pass

            # Reflow control buttons (minimal 2-button set, equal size)
            gap = 12
            x = 16
            y = 155  # Below slider
            btn_size = 52

            # Position Open button
            if self.open_btn:
                self.open_btn.move(x, y)
                x += btn_size + gap

            # Position Play button
            if self.play_btn:
                self.play_btn.move(x, y)
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
        from PyQt6.QtGui import QColor
        white = QColor(255, 255, 255)
        if self.Player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setIcon(pause_icon(white))
        else:
            self.play_btn.setIcon(play_icon(white))

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
        # Default: lyrics visible, visualizer hidden
        state = {"visualizer": "0", "lyrics": "1"}
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
    """Background thread that uses yt-dlp Python library to fetch audio files from YouTube.

    Improved workflow:
    1. Extract metadata for all items first (playlist or single video)
    2. Emit metadata_ready signal with list of items
    3. Download each item, emitting per-item progress
    4. Emit item_complete for each finished item
    5. Emit finished when all done
    """

    # Emitted with list of dicts: [{'title': str, 'duration': int, 'url': str}, ...]
    metadata_ready = pyqtSignal(list)
    # Emitted with (item_index, percent) for per-item progress
    item_progress = pyqtSignal(int, int)
    # Emitted with (item_index, file_path) when item download completes
    item_complete = pyqtSignal(int, str)
    # Emitted with (item_index, error_msg) when item download fails
    item_error = pyqtSignal(int, str)
    # Legacy signals for compatibility
    finished = pyqtSignal(list)
    progress = pyqtSignal(int)

    def __init__(self, url: str, output_dir: Path):
        super().__init__()
        self._url = url
        self._output_dir = output_dir
        self._last_progress = -1
        self._current_item_index = 0
        self._downloaded_files: list[str] = []

    def _progress_hook(self, d: dict):
        """yt-dlp progress hook callback."""
        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            if total and total > 0:
                pct = int((downloaded / total) * 100)
                if pct != self._last_progress:
                    self._last_progress = pct
                    self.item_progress.emit(self._current_item_index, pct)
                    self.progress.emit(pct)  # Legacy compatibility
        elif d.get('status') == 'finished':
            self.item_progress.emit(self._current_item_index, 100)
            self.progress.emit(100)

    def _find_ffmpeg(self) -> str | None:
        """Find ffmpeg binary path."""
        # For PyInstaller bundles, check the app's directory first
        if getattr(sys, 'frozen', False):
            if sys.platform == 'darwin':
                app_dir = Path(sys.executable).parent
                bundle_paths = [
                    app_dir / 'ffmpeg',
                    app_dir.parent / 'Frameworks' / 'ffmpeg',
                    app_dir.parent / 'Resources' / 'ffmpeg',
                ]
            else:
                app_dir = Path(sys.executable).parent
                bundle_paths = [app_dir / 'ffmpeg', app_dir / 'ffmpeg.exe']

            for bp in bundle_paths:
                if bp.exists():
                    return str(bp)

        # Fall back to system locations
        for path in ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg']:
            if Path(path).exists():
                return path
        return None

    def run(self):  # noqa: D401
        try:
            import yt_dlp
        except ImportError:
            logging.error("yt_dlp module not found; please install yt-dlp")
            self.finished.emit([])
            return

        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)

            # Step 1: Extract metadata without downloading
            extract_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': 'in_playlist',  # Don't resolve individual entries yet
            }

            items_to_download = []
            try:
                with yt_dlp.YoutubeDL(extract_opts) as ydl:
                    info = ydl.extract_info(self._url, download=False)

                    if info is None:
                        self.finished.emit([])
                        return

                    # Handle playlist vs single video
                    if 'entries' in info:
                        # It's a playlist
                        for entry in info.get('entries', []):
                            if entry:
                                items_to_download.append({
                                    'title': entry.get('title', 'Unknown'),
                                    'duration': entry.get('duration', 0),
                                    'url': entry.get('url') or entry.get('webpage_url', ''),
                                    'id': entry.get('id', ''),
                                })
                    else:
                        # Single video
                        items_to_download.append({
                            'title': info.get('title', 'Unknown'),
                            'duration': info.get('duration', 0),
                            'url': info.get('webpage_url', self._url),
                            'id': info.get('id', ''),
                        })

                # Emit metadata so UI can add items to playlist
                if items_to_download:
                    self.metadata_ready.emit(items_to_download)
                    logging.info("Found %d items to download", len(items_to_download))

            except Exception as exc:
                logging.exception("Failed to extract metadata: %s", exc)
                self.finished.emit([])
                return

            # Step 2: Download each item individually
            ffmpeg_path = self._find_ffmpeg()
            if ffmpeg_path:
                logging.info("Using ffmpeg from: %s", str(Path(ffmpeg_path).parent))
            else:
                logging.warning("ffmpeg not found - audio conversion may fail")

            for idx, item in enumerate(items_to_download):
                self._current_item_index = idx
                self._last_progress = -1

                # Sanitize filename
                safe_title = "".join(c for c in item['title'] if c.isalnum() or c in ' ._-')[:100]
                if not safe_title:
                    safe_title = f"video_{item.get('id', idx)}"

                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': str(self._output_dir / f'{safe_title}.%(ext)s'),
                    'progress_hooks': [self._progress_hook],
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'quiet': True,
                    'no_warnings': True,
                }

                if ffmpeg_path:
                    ydl_opts['ffmpeg_location'] = str(Path(ffmpeg_path).parent)

                try:
                    before = set(self._output_dir.glob("*.mp3"))
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        # Download using the item's URL or ID
                        download_url = item.get('url') or f"https://www.youtube.com/watch?v={item['id']}"
                        ydl.download([download_url])

                    after = set(self._output_dir.glob("*.mp3"))
                    new_files = list(after - before)
                    if new_files:
                        file_path = str(new_files[0])
                        self._downloaded_files.append(file_path)
                        self.item_complete.emit(idx, file_path)
                        logging.info("Downloaded item %d: %s", idx, file_path)
                    else:
                        self.item_error.emit(idx, "No output file created")
                        logging.warning("No output file for item %d", idx)

                except Exception as exc:
                    error_msg = str(exc)[:100]
                    self.item_error.emit(idx, error_msg)
                    logging.exception("Failed to download item %d: %s", idx, exc)

            # Emit finished with all successfully downloaded files
            self.finished.emit(self._downloaded_files)
            logging.info("Download complete: %d files", len(self._downloaded_files))

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