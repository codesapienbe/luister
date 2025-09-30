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
)
from PyQt6.QtCore import QUrl, QEvent, Qt, QSize, QBuffer, QIODevice, QTimer, QThread, pyqtSignal, QPropertyAnimation
from PyQt6.QtGui import QIcon, QAction, QActionGroup, QPalette, QTransform, QPixmap
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
    double_left_icon,
    double_right_icon,
    slider_handle_icon,
    tray_icon,
    youtube_icon,
)
from luister.visualizer import VisualizerWidget
from luister.lyrics import LyricsWidget  # type: ignore
import logging
from typing import Optional
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

        _mk_btn("back_btn", 20, 144, 41, 41)
        _mk_btn("play_btn", 63, 144, 41, 41)
        _mk_btn("pause_btn", 106, 144, 41, 41)
        _mk_btn("stop_btn", 149, 144, 41, 41)
        _mk_btn("next_btn", 193, 144, 41, 41)
        _mk_btn("download_btn", 257, 144, 46, 38)
        # YouTube quick-add button
        yt_btn = _mk_btn("youtube_btn", 310, 144, 41, 41)
        _mk_btn("shuffle_btn", 340, 150, 121, 25)
        _mk_btn("loop_btn", 470, 150, 61, 25)
        eq_btn = QPushButton("EQ", central); eq_btn.setObjectName("eq_btn"); eq_btn.setGeometry(470, 70, 51, 25)

        # Sliders
        time_slider = QSlider(Qt.Orientation.Horizontal, central)
        time_slider.setObjectName("time_slider")
        time_slider.setGeometry(20, 109, 561, 21)

        volume_slider = QSlider(Qt.Orientation.Horizontal, central)
        volume_slider.setObjectName("volume_slider")
        volume_slider.setGeometry(200, 80, 131, 16)

        # Displays
        time_lcd = QTextEdit(central)
        time_lcd.setObjectName("time_lcd")
        time_lcd.setGeometry(20, 10, 161, 81)
        time_lcd.setReadOnly(True)

        title_lcd = QTextEdit(central)
        title_lcd.setObjectName("title_lcd")
        title_lcd.setGeometry(210, 10, 371, 21)
        title_lcd.setReadOnly(True)

        kbps_lcd = QLCDNumber(central)
        kbps_lcd.setObjectName("lcdNumber_3")
        kbps_lcd.setGeometry(200, 50, 31, 23)

        khz_lcd = QLCDNumber(central)
        khz_lcd.setObjectName("lcdNumber_4")
        khz_lcd.setGeometry(280, 50, 31, 23)

        # YouTube download progress bar
        self.yt_progress = QProgressBar(central)
        self.yt_progress.setObjectName("yt_progress")
        self.yt_progress.setGeometry(20, 190, 561, 12)
        self.yt_progress.setRange(0, 0)  # indeterminate
        self.yt_progress.hide()

        # End of manual UI build
        # Enforce single-app width with all components docked and visible
        # Central area remains similar size; overall window widened to accommodate docks
        self.resize(1120, 420)  # expanded width/height to fit docks without overlap

        # initial LCD text (replicates old HTML)
        time_lcd.setPlainText('▶    00:00')
        time_lcd.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_path = base_path.parent / 'img' / 'icon.png'
        self.setWindowIcon(QIcon(str(icon_path)))

        # Clear hard-coded styles from Designer so palette/stylesheet can work
        self._clear_inline_styles()

        # visualizer window created lazily
        self.visualizer: Optional[VisualizerWidget] = None
        # lyrics window created lazily
        self.lyrics: Optional[LyricsWidget] = None

        # Define widgets
        #Buttons
        self.back_btn = self.findChild(QPushButton, "back_btn")
        self.play_btn = self.findChild(QPushButton, "play_btn")
        self.pause_btn = self.findChild(QPushButton, "pause_btn")
        self.stop_btn = self.findChild(QPushButton, "stop_btn")
        self.next_btn = self.findChild(QPushButton, "next_btn")
        self.download_btn = self.findChild(QPushButton, "download_btn")
        self.youtube_btn = self.findChild(QPushButton, "youtube_btn")
        if self.youtube_btn is not None:
            self.youtube_btn.setToolTip('Add YouTube URL (paste)')
        self.eq_btn = self.findChild(QPushButton, "eq_btn")
        self.shuffle_btn = self.findChild(QPushButton, 'shuffle_btn')
        self.loop_btn = self.findChild(QPushButton, 'loop_btn')
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
        #set icons
        sp = QStyle.StandardPixmap  # type: ignore[attr-defined]
        self.back_btn.setIcon(double_left_icon())
        self.play_btn.setIcon(play_icon())
        self.pause_btn.setIcon(pause_icon())
        self.stop_btn.setIcon(stop_icon())
        self.next_btn.setIcon(double_right_icon())
        self.download_btn.setIcon(folder_icon())
        self.youtube_btn.setIcon(youtube_icon())
        self.eq_btn.setIcon(eq_icon())

        # Normalize button appearance and spacing
        btns = [
            self.back_btn,
            self.play_btn,
            self.pause_btn,
            self.stop_btn,
            self.next_btn,
            self.download_btn,
            self.youtube_btn,
            self.eq_btn,
            self.shuffle_btn,
            self.loop_btn,
        ]
        # adjust width to fit larger icon set and avoid overlap
        for b in btns:
            try:
                b.setText("")
                b.setIconSize(QSize(28, 28))
                b.setFixedHeight(42)
                apply_shadow(b)
            except Exception:
                pass

        # make widths uniform based on play_btn but ensure enough room
        try:
            base_w = max(48, self.play_btn.size().width())
        except Exception:
            base_w = 48
        for b in (self.play_btn, self.pause_btn, self.stop_btn, self.next_btn, self.back_btn, self.download_btn, self.youtube_btn, self.eq_btn):
            try:
                b.setFixedSize(base_w, 42)
            except Exception:
                pass
        # shuffle & loop slightly wider
        try:
            self.shuffle_btn.setFixedSize(base_w + 40, 42)
            self.loop_btn.setFixedSize(base_w + 20, 42)
        except Exception:
            pass

        # reposition controls with larger spacing
        gap = 12
        x = 20
        y = 144
        for b in (self.back_btn, self.play_btn, self.pause_btn, self.stop_btn, self.next_btn, self.download_btn, self.youtube_btn, self.shuffle_btn, self.loop_btn):
            try:
                b.move(x, y)
                x += b.width() + gap
            except Exception:
                pass


        # assign icons to shuffle/loop
        self.shuffle_btn.setIcon(shuffle_icon())
        self.loop_btn.setIcon(loop_icon())

        #click Buttons
        self.back_btn.clicked.connect(self.back)
        self.play_btn.clicked.connect(self.play_stop_toggle)
        self.pause_btn.clicked.connect(self.pause)
        self.stop_btn.clicked.connect(self.stop)
        self.next_btn.clicked.connect(self.next)
        self.download_btn.clicked.connect(self.download)
        if self.youtube_btn is not None:
            self.youtube_btn.clicked.connect(self._on_youtube_click)
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
        except Exception as e:
            from PyQt6.QtWidgets import QLabel
            self.visualizer_widget = QLabel(f"Visualizer failed to initialize: {e}")
        self.visualizer_dock = QDockWidget("Visualizer", self)
        self.visualizer_dock.setWidget(self.visualizer_widget)
        self.visualizer_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.visualizer_dock.visibilityChanged.connect(lambda visible: self.set_visualizer_visible(visible))
        # dock to left and don't allow floating to avoid overlap
        self.visualizer_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
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
                self.ui.setMinimumWidth(260)
                self.ui.setMinimumHeight(240)
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
                    # add playlist right of visualizer by default
                    self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.playlist_dock)
                # ensure minimum size so it remains visible
                try:
                    self.playlist_dock.setMinimumWidth(280)
                    self.playlist_dock.setMinimumHeight(240)
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
        # Create a tray icon that toggles the app visibility on click
        self.tray_icon = QSystemTrayIcon(tray_icon(), self)  # type: ignore
        self.tray_icon.activated.connect(self._on_tray_activated)  # type: ignore
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

        # tray icon rotating animation
        self._tray_base_icon = tray_icon()
        # Ensure the application/window taskbar uses the same icon as the system tray
        try:
            app = QApplication.instance()
            # Only call setWindowIcon when we have a QApplication instance (type-checker friendly)
            if isinstance(app, QApplication):
                app.setWindowIcon(self._tray_base_icon)
        except Exception:
            # benign if setting app icon fails on some platforms
            pass
        self._tray_rotation_angle = 0
        self._tray_timer = QTimer(self)
        self._tray_timer.timeout.connect(self._rotate_tray_icon)
        # timer will start when playback begins

    def set_Enabled_button(self):
        if not self.playlist_urls:
            self.back_btn.setEnabled(False)
            self.play_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.shuffle_btn.setEnabled(False)
            self.loop_btn.setEnabled(False)
        else:
            self.back_btn.setEnabled(True)
            self.play_btn.setEnabled(True)
            self.pause_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
            self.next_btn.setEnabled(True)
            self.shuffle_btn.setEnabled(True)
            self.loop_btn.setEnabled(True)

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

    # play/stop toggle via single button
    @log_call()
    def play_stop_toggle(self):
        if self.Player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.Player.stop()
        else:
            self.Player.play()
        self.update_play_stop_icon()

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
                if not self.ui.isVisible():
                    self.ui.show()
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
            self.yt_progress.show()
            self._yt_thread = YTDownloadThread(url, output_dir)
            self._yt_thread.finished.connect(self._on_ytdl_finished)
            self._yt_thread.start()
        except Exception as e:
            self.title_lcd.setPlainText(f"Error starting YouTube download: {e}")

    def _on_ytdl_finished(self, files: list):  # noqa: D401
        if not files:
            self.yt_progress.hide()
            self.title_lcd.setPlainText('YouTube download failed')
            return
        # Add downloaded files and play first
        self._add_files(files, replace=True)
        self.current_index = len(self.playlist_urls) - len(files)
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

        # Control tray icon rotation
        if playing:
            if not self._tray_timer.isActive():
                self._tray_timer.start(100)  # 10 FPS
        else:
            if self._tray_timer.isActive():
                self._tray_timer.stop()
                # restore static icon
                self.tray_icon.setIcon(self._tray_base_icon)  # type: ignore[arg-type]

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
        #if mode plyilist = sequential
        if self.loop_plaing is False:
            self.Player.setLoops(QMediaPlayer.Loops.Infinite)
            self.loop_btn.setStyleSheet(""" background-color : rgb(53, 159, 159);
                                            border-top: 4px double rgb(253, 253, 253);
                                            border-right: 4px double #DFDBDD;
                                            border-bottom: 4px double #BCB8BA;
                                            border-left: 4px double #EFEAEC;""")
            self.loop_plaing = True
        #if already play in loop
        else:
            self.Player.setLoops(1)
            self.loop_btn.setStyleSheet("""background-color: rgb(221, 221, 221);
                                            border-top: 4px double rgb(253, 253, 253);
                                            border-right: 4px double #DFDBDD;
                                            border-bottom: 4px double #BCB8BA;
                                            border-left: 4px double #EFEAEC;""")
            self.loop_plaing = False

    #show error in TextInput
    def handle_errors(self):
        self.play_btn.setEnabled(False)
        if isinstance(self.ui, PlaylistUI):
            self.title_lcd.setPlainText('Error' + str(self.Player.errorString()))

    # ------- Playlist docking/toggle ---------

    def _ensure_playlist(self):
        # Main playlist UI
        try:
            self.ui = PlaylistUI(main_window=self)
            self.ui.filesDropped.connect(self._add_files)
            self.ui.list_songs.itemDoubleClicked.connect(self.clicked_song)  # type: ignore[arg-type]
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
            # if lyrics view is visible and no cached segments yet, wait
            if self.lyrics_dock is not None and self.lyrics_dock.isVisible():
                widget = self.lyrics_dock.widget()
                if isinstance(widget, LyricsWidget):
                    widget.show_progress()  # type: ignore
                    # set pending playback and start loading lyrics
                    self._pending_play_when_lyrics_loaded = True
                    widget.load_lyrics(current_url.toLocalFile())  # type: ignore
                    return
            else:
                self.Player.play()
                self.update_play_stop_icon()
            # feed audio to visualizer
            if self.visualizer_dock is not None and self.visualizer_dock.isVisible():
                widget = self.visualizer_dock.widget()
                if isinstance(widget, VisualizerWidget):
                    widget.set_audio(current_url.toLocalFile())
            if self.lyrics_dock is not None and self.lyrics_dock.isVisible():
                widget = self.lyrics_dock.widget()
                if isinstance(widget, LyricsWidget):
                    widget.load_lyrics(current_url.toLocalFile())
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
            if hasattr(self, 'ui'):
                self.ui.list_songs.clear()
            self.current_index = -1

        start_index = len(self.playlist_urls) + 1
        for idx, fp in enumerate(file_paths, start=start_index):
            url = QUrl.fromLocalFile(fp)
            self.playlist_urls.append(url)
            if hasattr(self, 'ui'):
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

            # Reflow control buttons horizontally with spacing
            gap = 12
            x = 20
            y = 144
            btns = (
                getattr(self, 'back_btn', None),
                getattr(self, 'play_btn', None),
                getattr(self, 'pause_btn', None),
                getattr(self, 'stop_btn', None),
                getattr(self, 'next_btn', None),
                getattr(self, 'download_btn', None),
                getattr(self, 'youtube_btn', None),
                getattr(self, 'shuffle_btn', None),
                getattr(self, 'loop_btn', None),
            )
            for b in btns:
                try:
                    if b is None:
                        continue
                    b.move(x, y)
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

    def update_play_stop_icon(self):
        sp = QStyle.StandardPixmap  # type: ignore[attr-defined]
        if self.Player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            icon = self.style().standardIcon(sp.SP_MediaStop)  # type: ignore
        else:
            icon = self.style().standardIcon(sp.SP_MediaPlay)  # type: ignore
        self.play_btn.setIcon(icon)

    def _clear_inline_styles(self):
        from PyQt6.QtWidgets import QWidget
        stack = [self]
        while stack:
            w = stack.pop()
            if isinstance(w, QWidget) and w.styleSheet():  # type: ignore[arg-type]
                w.setStyleSheet("")
            stack.extend(list(w.findChildren(QWidget)))  # type: ignore[arg-type]

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
        if hasattr(self, 'visualizer_action') and self.visualizer_action is not None:
            self.visualizer_action.setChecked(self.visualizer_dock.isVisible())

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
        if hasattr(self, 'lyrics_action') and self.lyrics_action is not None:
            self.lyrics_action.setChecked(self.lyrics_dock.isVisible())
        # No view menu/actions required when all widgets are always visible

    def _apply_dock_styles(self):
        dock_style = '''
        QDockWidget {
            background: rgba(255,255,255,0.15);
            border-radius: 16px;
            border: 1.5px solid rgba(0,0,0,0.08);
        }
        QDockWidget::title {
            background: rgba(255,255,255,0.25);
            border-top-left-radius: 16px;
            border-top-right-radius: 16px;
            padding: 6px 12px;
            color: palette(window-text);
        }
        QDockWidget::title:hover {
            background: rgba(255,255,255,0.40);
            color: #21808D;
        }
        QDockWidget::title:active {
            background: rgba(33,128,141,0.25);
            color: #FCFCF9;
        }
        '''
        if self.visualizer_dock is not None:
            self.visualizer_dock.setStyleSheet(dock_style)
        if self.lyrics_dock is not None:
            self.lyrics_dock.setStyleSheet(dock_style)

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

    # ---- tray icon rotation helper ----
    def _rotate_tray_icon(self):
        try:
            size = 32
            orig_pix = self._tray_base_icon.pixmap(size, size)
            transform = QTransform()
            transform.rotate(self._tray_rotation_angle)
            rotated_pix = orig_pix.transformed(transform, Qt.TransformationMode.SmoothTransformation)
            self.tray_icon.setIcon(QIcon(rotated_pix))  # type: ignore[arg-type]
            self._tray_rotation_angle = (self._tray_rotation_angle + 10) % 360
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
    """Background thread that uses yt-dlp to fetch audio files from YouTube."""

    finished = pyqtSignal(list)  # list of downloaded file paths

    def __init__(self, url: str, output_dir: Path):
        super().__init__()
        self._url = url
        self._output_dir = output_dir

    def run(self):  # noqa: D401
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            before = set(self._output_dir.glob("*.mp3")) | set(self._output_dir.glob("*.m4a")) | set(self._output_dir.glob("*.webm"))
            # Build yt-dlp command
            cmd = [
                "yt-dlp",
                "-x",  # extract audio
                "--audio-format", "mp3",
                "--prefer-ffmpeg",
                "--embed-thumbnail",
                "--no-colors",
                "--output",
                str(self._output_dir / "%(title)s.%(ext)s"),
                self._url,
            ]

            try:
                # Capture stdout/stderr for diagnostics if yt-dlp fails
                proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
            except FileNotFoundError:
                logging.error("yt-dlp not found; please install yt-dlp and ensure it is on PATH")
                self.finished.emit([])
                return
            except Exception as exc:
                logging.exception("Unexpected error running yt-dlp: %s", exc)
                self.finished.emit([])
                return

            if proc.returncode != 0:
                logging.error("yt-dlp failed with return code %s; stdout=%s stderr=%s", proc.returncode, proc.stdout, proc.stderr)
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