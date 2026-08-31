from PyQt6.QtWidgets import (
    QMainWindow,
    QApplication,
    QWidget,
    QPushButton,
    QSlider,
    QFileDialog,
    QTextEdit,
    QSystemTrayIcon,
    QInputDialog,
    QDockWidget,
    QGraphicsOpacityEffect,
    QMenu,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
)
from PyQt6.QtCore import QUrl, QEvent, Qt, QSize, QBuffer, QIODevice, QTimer, QThread, pyqtSignal, QPropertyAnimation
from PyQt6.QtGui import QIcon, QPalette, QKeySequence, QShortcut
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices, QAudio
import sys
import re
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
    double_left_icon,
    double_right_icon,
)
from luister.visualizer import VisualizerWidget
from luister.lyrics import LyricsWidget  # type: ignore
import logging
from typing import Optional, Dict
from luister.manager import get_manager
import json

setup_logging()

# Hosts yt-dlp can pull audio from. Kept deliberately broad: the previous
# pattern rejected perfectly valid links such as music.youtube.com and
# youtube-nocookie.com, which read to the user as "the app is broken".
_SUPPORTED_URL_RE = re.compile(
    r"^https?://"
    r"(?:[\w-]+\.)*"
    r"(?:youtube\.com|youtu\.be|youtube-nocookie\.com)"
    r"/.+",
    re.IGNORECASE,
)


# Bumped when the meaning of a persisted GUI-state key changes, so stale
# files are not misread as a deliberate user preference.
_GUI_STATE_SCHEMA = "2"


def _is_supported_media_url(url: str) -> bool:
    """True if the URL looks like something the YouTube extractor can handle."""
    return bool(_SUPPORTED_URL_RE.match((url or "").strip()))


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
        # Everything below is driven by real Qt layouts. The previous version
        # positioned every widget with absolute setGeometry() calls plus a
        # resizeEvent() that recomputed hardcoded pixel offsets, which meant the
        # UI overlapped itself at anything but the one window size it was tuned
        # for.
        central = QWidget(self)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Now-playing / status panel
        time_lcd = QTextEdit(central)
        time_lcd.setObjectName("time_lcd")
        time_lcd.setReadOnly(True)
        time_lcd.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        time_lcd.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        time_lcd.setMinimumHeight(48)
        time_lcd.setMaximumHeight(80)
        # A read-only status panel should not take the focus ring, nor swallow
        # the arrow keys that drive seeking and volume.
        time_lcd.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        time_lcd.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        root.addWidget(time_lcd)

        # Seek row: elapsed | slider | total
        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)

        self.elapsed_label = QLabel("00:00", central)
        self.elapsed_label.setObjectName("elapsed_label")
        self.elapsed_label.setMinimumWidth(48)
        self.elapsed_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        seek_row.addWidget(self.elapsed_label)

        time_slider = QSlider(Qt.Orientation.Horizontal, central)
        time_slider.setObjectName("time_slider")
        time_slider.setMinimumWidth(120)
        time_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        seek_row.addWidget(time_slider, 1)

        self.total_label = QLabel("00:00", central)
        self.total_label.setObjectName("total_label")
        self.total_label.setMinimumWidth(48)
        self.total_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        seek_row.addWidget(self.total_label)

        root.addLayout(seek_row)

        # Transport row: open | prev | play | next .... mute | volume
        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)

        def _mk_btn(name: str) -> QPushButton:
            btn = QPushButton(central)
            btn.setObjectName(name)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            return btn

        for _name in ("open_btn", "back_btn", "play_btn", "next_btn"):
            controls_row.addWidget(_mk_btn(_name))

        controls_row.addStretch(1)

        self.mute_btn = _mk_btn("mute_btn")
        controls_row.addWidget(self.mute_btn)

        volume_slider = QSlider(Qt.Orientation.Horizontal, central)
        volume_slider.setObjectName("volume_slider")
        volume_slider.setMinimumWidth(60)
        volume_slider.setMaximumWidth(180)
        volume_slider.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        controls_row.addWidget(volume_slider)

        controls_row.setContentsMargins(0, 0, 0, 0)
        root.addLayout(controls_row)

        # Visualizer takes all remaining vertical space
        self.visualizer_widget = VisualizerWidget(central)
        self.visualizer_widget.setObjectName("visualizer_widget")
        self.visualizer_widget.setMinimumHeight(80)
        self.visualizer_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self.visualizer_widget, 1)

        # The transport row cannot compress below the width of its buttons, so
        # give the central area a floor. QMainWindow then folds this together
        # with the dock minimums to derive the real window minimum, instead of
        # letting the docks squeeze the controls until they overlap.
        central.setMinimumWidth(340)
        central.setMinimumHeight(260)

        # A sensible default size instead of showMaximized().
        self.resize(920, 640)

        # initial status text
        time_lcd.setPlainText('Luister - no track loaded')
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

        # Define widgets
        self.open_btn = self.findChild(QPushButton, "open_btn")
        self.back_btn = self.findChild(QPushButton, "back_btn")
        self.play_btn = self.findChild(QPushButton, "play_btn")
        self.next_btn = self.findChild(QPushButton, "next_btn")

        # Backwards compatibility - removed buttons set to None
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

        from PyQt6.QtGui import QColor
        white = QColor(255, 255, 255)

        btn_size = 40
        icon_size = 20

        for _btn in (self.open_btn, self.back_btn, self.play_btn, self.next_btn):
            if _btn is None:
                continue
            _btn.setText("")
            _btn.setFixedSize(btn_size, btn_size)
            _btn.setIconSize(QSize(icon_size, icon_size))

        # Open button with dropdown menu
        self.open_btn.setIcon(folder_icon())
        self.open_btn.setToolTip("Open music (folder or YouTube)")
        self._open_menu = QMenu(self.open_btn)
        self._open_folder_action = self._open_menu.addAction("Open Files...")
        self._open_youtube_action = self._open_menu.addAction("YouTube URL...")
        self._open_folder_action.triggered.connect(self.download)
        self._open_youtube_action.triggered.connect(self._on_youtube_click)
        self.open_btn.setMenu(self._open_menu)

        # Explicit, discoverable transport controls. The previous build hid
        # prev/next behind a swipe gesture on the play button and behind
        # invisible 15% hit-zones at each end of the seek bar - which meant
        # clicking near the start of the seek bar silently skipped tracks
        # instead of seeking.
        self.back_btn.setIcon(double_left_icon(white))
        self.back_btn.setToolTip("Previous track (\u2190)")
        self.back_btn.clicked.connect(self.back)

        self.play_btn.setIcon(play_icon(white))
        self.play_btn.setToolTip("Play / Pause (Space)")
        self.play_btn.clicked.connect(self.play_pause_toggle)

        self.next_btn.setIcon(double_right_icon(white))
        self.next_btn.setToolTip("Next track (\u2192)")
        self.next_btn.clicked.connect(self.next)

        # Mute toggle
        self.mute_btn.setFixedSize(btn_size, btn_size)
        self.mute_btn.setText("\U0001F509")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setToolTip("Mute / Unmute (M)")
        self.mute_btn.clicked.connect(self.toggle_mute)

        #sliders
        self.time_slider = self.findChild(QSlider, 'time_slider')
        self.volume_slider = self.findChild(QSlider, 'volume_slider')

        # QSlider's default range is 0-99, not 0-100, so the old `value / 100`
        # conversion could never reach full volume. Set the range explicitly.
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setSingleStep(5)
        self.volume_slider.setPageStep(10)
        self.time_slider.setRange(0, 0)

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
        # Connect *before* seeding the initial value, so the stored volume is
        # actually pushed into the audio output at startup. Previously
        # setValue() ran before this connection existed, so the slider showed
        # 20% while the output sat at its 100% default.
        self.volume_slider.valueChanged.connect(self.set_volume)

        # Seek handling: track drag state so position updates coming from the
        # player don't fight the handle while the user is dragging it.
        self._user_seeking = False
        self.time_slider.sliderPressed.connect(self._on_seek_start)
        self.time_slider.sliderReleased.connect(self._on_seek_end)
        self.time_slider.sliderMoved.connect(self._on_seek_preview)

        #LCD display (single panel for time and status)
        self.time_lcd = self.findChild(QTextEdit, 'time_lcd')
        self.title_lcd = None  # Removed - using time_lcd for all display

        # double-click on time_lcd toggles visualizer
        if self.time_lcd is not None:
            self.time_lcd.setCursorWidth(0)
            self.time_lcd.setToolTip("Double-click to show/hide visualizer")
            self.time_lcd.installEventFilter(self)

        # create media player and audio output (required by Qt6)
        self.audio_output = QAudioOutput()
        self.Player = QMediaPlayer()
        self.Player.setAudioOutput(self.audio_output)

        # Seed the volume now that the audio output exists. This has to happen
        # after QAudioOutput is constructed but after the slider's
        # valueChanged connection too, so the value actually reaches the sink.
        self._muted = False
        self._volume_before_mute = 50
        try:
            saved_volume = int(self._config.get("volume", 50))
        except (TypeError, ValueError):
            saved_volume = 50
        saved_volume = max(0, min(100, saved_volume))
        self.volume_slider.setValue(saved_volume)
        # setValue() is a no-op if the value already equals the default, so
        # apply once explicitly to guarantee the output is in sync.
        self.set_volume(saved_volume)


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
        # handle_errors() existed but was never connected to anything, so
        # playback failures were completely silent.
        try:
            self.Player.errorOccurred.connect(self._on_player_error)
        except Exception:
            logging.debug("Could not connect errorOccurred")

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

        # Visualizer setup (widget already created in central widget)
        self.visualizer_dock = None  # No dock - embedded in main window
        try:
            self.Player.positionChanged.connect(self.visualizer_widget.update_position)
        except Exception:
            pass
        get_manager().register(self.visualizer_widget)
        # Wire visualizer analysis status to UI
        if isinstance(self.visualizer_widget, VisualizerWidget):
            saved_title: Dict[str, Optional[str]] = {"val": None}

            def _on_vis_analysis_started():
                self._set_status('Analysing audio for visualizer...')

            def _on_vis_analysis_ready(ok: bool):
                self._set_status(
                    'Visualizer ready' if ok else 'Visualizer analysis failed',
                    transient_ms=2500,
                )

            self.visualizer_widget.analysis_started.connect(_on_vis_analysis_started)
            self.visualizer_widget.analysis_ready.connect(_on_vis_analysis_ready)

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
            self.lyrics_widget = QLabel(f"Lyrics failed to initialize: {e}")
        self.lyrics_dock = QDockWidget("Lyrics", self)
        self.lyrics_dock.setWidget(self.lyrics_widget)
        self.lyrics_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.lyrics_dock.visibilityChanged.connect(self._on_lyrics_visibility_changed)
        # dock to right and prevent floating
        self.lyrics_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        try:
            self._make_dock_hide_on_close(self.lyrics_dock)
        except Exception:
            pass
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.lyrics_dock)
        self._apply_dock_styles()
        # --- Playlist dock -------------------------------------------------
        if not hasattr(self, 'ui') or self.ui is None:
            self._ensure_playlist()

        # Modest minimums only. The old values (playlist dock 600px wide, 350
        # tall) forced the whole main window to stay huge, so the app could not
        # be resized down on a laptop screen at all.
        try:
            if isinstance(self.ui, PlaylistUI):
                self.ui.setMinimumWidth(200)
                self.ui.setMinimumHeight(120)
        except Exception:
            pass

        try:
            if isinstance(self.ui, PlaylistUI):
                if not hasattr(self, 'playlist_dock') or self.playlist_dock is None:
                    self.playlist_dock = QDockWidget("Playlist", self)
                    self.playlist_dock.setObjectName("playlist_dock")
                    self.playlist_dock.setWidget(self.ui)
                    self.playlist_dock.setAllowedAreas(
                        Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
                    )
                    self.playlist_dock.setFeatures(
                        QDockWidget.DockWidgetFeature.DockWidgetMovable
                        | QDockWidget.DockWidgetFeature.DockWidgetClosable
                    )
                    try:
                        self._make_dock_hide_on_close(self.playlist_dock)
                    except Exception:
                        pass
                    self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.playlist_dock)
                    try:
                        self.playlist_dock.visibilityChanged.connect(
                            self._dock_visibility_changed
                        )
                    except Exception:
                        pass

                try:
                    self.playlist_dock.setMinimumWidth(220)
                    self.playlist_dock.setMinimumHeight(140)
                except Exception:
                    pass

                # Stack lyrics above the song list
                try:
                    if self.lyrics_dock is not None:
                        self.splitDockWidget(
                            self.lyrics_dock, self.playlist_dock, Qt.Orientation.Vertical
                        )
                        self.resizeDocks(
                            [self.lyrics_dock, self.playlist_dock],
                            [200, 400],
                            Qt.Orientation.Vertical,
                        )
                except Exception:
                    pass
                # Give the docks a sensible share of the width instead of
                # letting their minimum sizes dictate the window size.
                try:
                    self.resizeDocks([self.playlist_dock], [320], Qt.Orientation.Horizontal)
                except Exception:
                    pass
        except Exception:
            pass

        # --- Apply persisted panel visibility -------------------------------
        # This runs *after* every dock exists. The previous build applied the
        # saved state here and then unconditionally called show() on the lyrics
        # and playlist docks a few lines later, which silently overrode
        # whatever the user had chosen.
        state = self._load_gui_state()

        try:
            if self.visualizer_widget is not None:
                self.visualizer_widget.setVisible(state.get('visualizer', '1') == '1')
        except Exception:
            pass

        try:
            if self.lyrics_dock is not None:
                self.lyrics_dock.setVisible(state.get('lyrics', '0') == '1')
        except Exception:
            pass

        try:
            if getattr(self, 'playlist_dock', None) is not None:
                self.playlist_dock.setVisible(state.get('playlist', '1') == '1')
        except Exception:
            pass

        # From here on, visibility changes are the user's and worth saving.
        self._gui_state_ready = True

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

        # Playback options. shuffle() and loop() already existed but had no
        # button, menu entry or shortcut anywhere, so they were unreachable.
        tray_menu.addAction("Shuffle playlist").triggered.connect(self.shuffle)
        self.loop_action = tray_menu.addAction("Loop playlist")
        self.loop_action.setCheckable(True)
        self.loop_action.setChecked(self.loop_plaing)
        self.loop_action.triggered.connect(self.loop)

        tray_menu.addSeparator()

        # Panel visibility, mirroring the Ctrl+P / Ctrl+L / Ctrl+B shortcuts.
        self.playlist_action = tray_menu.addAction("Playlist")
        self.playlist_action.setCheckable(True)
        self.playlist_action.setChecked(
            getattr(self, 'playlist_dock', None) is not None
            and self.playlist_dock.isVisible()
        )
        self.playlist_action.triggered.connect(lambda _c: self.toggle_playlist())

        self.lyrics_action = tray_menu.addAction("Lyrics")
        self.lyrics_action.setCheckable(True)
        self.lyrics_action.setChecked(
            self.lyrics_dock is not None and self.lyrics_dock.isVisible()
        )
        self.lyrics_action.triggered.connect(self._menu_toggle_lyrics)

        self.visualizer_action = tray_menu.addAction("Visualizer")
        self.visualizer_action.setCheckable(True)
        self.visualizer_action.setChecked(
            getattr(self, 'visualizer_widget', None) is not None
            and self.visualizer_widget.isVisible()
        )
        self.visualizer_action.triggered.connect(self._menu_toggle_visualizer)

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

        # Keyboard shortcuts (the app previously had none at all)
        self._install_shortcuts()

    def _install_shortcuts(self):
        """Standard media keyboard shortcuts."""
        bindings = [
            ("Space", self.play_pause_toggle),
            ("Right", self.next),
            ("Left", self.back),
            ("Up", lambda: self.nudge_volume(5)),
            ("Down", lambda: self.nudge_volume(-5)),
            ("M", self.toggle_mute),
            ("Ctrl+O", self.download),
            ("Ctrl+U", self._on_youtube_click),
            ("Ctrl+L", self.toggle_lyrics),
            ("Ctrl+P", self.toggle_playlist),
            ("Ctrl+B", self.toggle_visualizer),
            ("Ctrl+H", self.shuffle),
            ("Ctrl+R", self.loop),
            ("Shift+Right", lambda: self.seek_relative(5000)),
            ("Shift+Left", lambda: self.seek_relative(-5000)),
        ]
        self._shortcuts = []
        for key, handler in bindings:
            try:
                sc = QShortcut(QKeySequence(key), self)
                sc.activated.connect(handler)
                self._shortcuts.append(sc)
            except Exception:
                logging.debug("Could not bind shortcut %s", key)

    def seek_relative(self, delta_ms: int):
        """Jump forward/backward within the current track."""
        try:
            duration = self.Player.duration()
            target = max(0, self.Player.position() + delta_ms)
            if duration:
                target = min(target, duration)
            self.Player.setPosition(target)
        except Exception:
            logging.debug("Relative seek failed")

    def wheelEvent(self, event):
        """Mouse wheel over the window adjusts volume."""
        try:
            delta = event.angleDelta().y()
            if delta:
                self.nudge_volume(5 if delta > 0 else -5)
                event.accept()
                return
        except Exception:
            pass
        super().wheelEvent(event)

    def set_Enabled_button(self):
        """Enable/disable playback buttons based on playlist state."""
        has_songs = bool(self.playlist_urls)
        # Minimal button set - just play button needs enabling
        if self.play_btn:
            self.play_btn.setEnabled(has_songs)

    # --- seek handling -------------------------------------------------

    def _on_seek_start(self):
        self._user_seeking = True

    def _on_seek_preview(self, position):
        """Live-update the elapsed readout while dragging, without seeking yet."""
        self.elapsed_label.setText(self._format_ms(position))

    def _on_seek_end(self):
        self._user_seeking = False
        self.Player.setPosition(self.time_slider.value())

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
                self._set_status('No audio files selected', transient_ms=3000)
        except Exception as e:
            self._set_status(f'Error: {e}', transient_ms=5000)

    @log_call()
    def _on_youtube_click(self):
        """Prompt for a YouTube URL and use the existing download flow."""
        try:
            url, ok = QInputDialog.getText(self, "Add from YouTube", "Paste YouTube URL:")
            if not ok or not url or not url.strip():
                return
            url = url.strip()
            if not _is_supported_media_url(url):
                self._set_status("Invalid YouTube URL")
                return

            output_dir = Path.home() / ".luister" / "downloads"
            self._set_status("Fetching metadata...")

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
            self._yt_thread.batch_finished.connect(self._on_ytdl_finished)
            self._yt_thread.start()
        except Exception as e:
            self._set_status(f"Error starting YouTube download: {e}", transient_ms=6000)

    def _on_ytdl_metadata(self, items: list):  # noqa: D401
        """Handle metadata ready - add all items to playlist immediately."""
        self._yt_items_metadata = items
        count = len(items)
        self._set_status(f"Found {count} item(s), starting downloads...")

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

        self._set_status(f"Downloading ({item_idx + 1}/{total_items}): {pct}%")

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
            self._set_status(f"Downloaded {file_count} file(s)", transient_ms=4000)
        else:
            # Check if we had metadata - if so, all downloads failed
            if hasattr(self, '_yt_items_metadata') and self._yt_items_metadata:
                self._set_status("Downloads failed", transient_ms=6000)
            else:
                self._set_status("No items to download", transient_ms=4000)

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
        """Apply a 0-100 slider position to the audio output.

        QAudioOutput.setVolume() takes a *linear amplitude*, but human loudness
        perception is logarithmic - feeding it the raw fraction makes the
        bottom two thirds of the slider sound almost identical, which is why
        the control felt like it did nothing. QAudio.convertVolume() does the
        proper logarithmic-to-linear conversion.
        """
        value = max(0, min(100, int(value)))

        try:
            linear = QAudio.convertVolume(
                value / 100.0,
                QAudio.VolumeScale.LogarithmicVolumeScale,
                QAudio.VolumeScale.LinearVolumeScale,
            )
        except Exception:
            linear = value / 100.0

        try:
            self.audio_output.setVolume(linear)
        except Exception:
            logging.exception("Failed to set output volume")

        if value > 0:
            self._muted = False
            self._volume_before_mute = value

        self._sync_mute_button(value)

        self.volume_slider.setToolTip(f"Volume: {value}%")
        self._persist_volume(value)

    def _sync_mute_button(self, value: int):
        """Keep the mute button's glyph and checked state in step with volume."""
        btn = getattr(self, "mute_btn", None)
        if btn is None:
            return
        if value == 0:
            glyph = "\U0001F507"
        elif value < 34:
            glyph = "\U0001F508"
        elif value < 67:
            glyph = "\U0001F509"
        else:
            glyph = "\U0001F50A"
        btn.setText(glyph)
        was_blocked = btn.blockSignals(True)
        btn.setChecked(value == 0)
        btn.blockSignals(was_blocked)

    def toggle_mute(self):
        """Mute to 0 and restore the previous level on unmute."""
        if self.volume_slider.value() > 0:
            self._volume_before_mute = self.volume_slider.value()
            self._muted = True
            self.volume_slider.setValue(0)
        else:
            self._muted = False
            restore = self._volume_before_mute or 50
            self.volume_slider.setValue(restore)

    def _persist_volume(self, value: int):
        """Remember the volume across restarts."""
        try:
            self._config["volume"] = int(value)
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f)
        except Exception:
            logging.debug("Could not persist volume")

    def nudge_volume(self, delta: int):
        """Keyboard/scroll volume adjustment."""
        self.volume_slider.setValue(
            max(0, min(100, self.volume_slider.value() + delta))
        )

    def audiostate_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState

        # Control visualizer animation if it exists
        if hasattr(self, 'visualizer_widget') and isinstance(self.visualizer_widget, VisualizerWidget):
            if playing:
                self.visualizer_widget.resume_animation()
            else:
                self.visualizer_widget.pause_animation()

    @staticmethod
    def _format_ms(ms: int) -> str:
        """Render milliseconds as mm:ss (or h:mm:ss for long tracks)."""
        total = max(0, int(ms)) // 1000
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _refresh_display(self):
        """Repaint the now-playing panel from the current title + status.

        The old code wrote the raw elapsed time straight into time_lcd on every
        positionChanged tick, so the track title vanished a fraction of a
        second after playback started. Title and transient status now live in
        separate fields and the elapsed time has its own label.
        """
        title = getattr(self, "_track_title", "") or "No track loaded"
        status = getattr(self, "_status_message", "")
        text = title if not status else f"{title}\n{status}"
        try:
            self.time_lcd.setPlainText(text)
            self.time_lcd.setAlignment(Qt.AlignmentFlag.AlignCenter)
        except Exception:
            pass

    def _set_status(self, message: str, transient_ms: int = 0):
        """Show a status line under the track title."""
        self._status_message = message or ""
        self._refresh_display()
        if transient_ms > 0:
            QTimer.singleShot(transient_ms, self._clear_status)

    def _clear_status(self):
        self._status_message = ""
        self._refresh_display()

    def _set_track_title(self, title: str):
        self._track_title = title or ""
        self._refresh_display()

    #update slider position
    def position_changed(self, position):
        # Never move the handle out from under a user who is dragging it.
        if not getattr(self, "_user_seeking", False):
            blocked = self.time_slider.blockSignals(True)
            self.time_slider.setValue(position)
            self.time_slider.blockSignals(blocked)

        self.elapsed_label.setText(self._format_ms(position))
        try:
            if isinstance(self.ui, PlaylistUI):
                self.ui.time_song_text.setPlainText(self._format_ms(position))
        except Exception:
            logging.debug('Error updating playlist time display')

    #set slider range
    def duration_changed(self, duration):
        self.time_slider.setRange(0, max(0, duration))
        self.total_label.setText(self._format_ms(duration))

    #set position played song
    def set_position(self, position):
        self.Player.setPosition(position)

    def media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._set_status("Cannot play this file", transient_ms=4000)
            return

        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return

        at_last_track = self.current_index >= len(self.playlist_urls) - 1
        if at_last_track and not self.loop_plaing:
            # Reaching the end used to leave the UI stuck showing the final
            # position with the play icon still in "playing" state.
            self.Player.stop()
            self.Player.setPosition(0)
            self.update_play_pause_icon()
            self._set_status("End of playlist", transient_ms=3000)
            return

        self.next()

    @log_call()
    def shuffle(self):
        """Shuffle the playlist without interrupting what is playing.

        The previous version reshuffled and then jumped to index 0, so
        shuffling always cut off the current song.
        """
        if not self.playlist_urls:
            return

        current = (
            self.playlist_urls[self.current_index]
            if 0 <= self.current_index < len(self.playlist_urls)
            else None
        )

        random.shuffle(self.playlist_urls)

        if current is not None:
            self.current_index = self.playlist_urls.index(current)

        if isinstance(self.ui, PlaylistUI):
            self.ui.list_songs.clear()
            for i, url in enumerate(self.playlist_urls, 1):
                self.ui.list_songs.addItem(f"{i}. {url.fileName()}")

        self._update_playlist_selection()
        self._set_status("Playlist shuffled", transient_ms=2000)

    @log_call()
    def loop(self):
        """Toggle looping of the *playlist*.

        The old implementation set QMediaPlayer.Loops.Infinite, which repeats
        the single track forever, while next()/back() read the same flag as
        "wrap around the playlist". The two meanings contradicted each other;
        playlist looping is the one the rest of the code expects.
        """
        self.loop_plaing = not self.loop_plaing
        self.Player.setLoops(1)
        if self.loop_btn is not None:
            self.loop_btn.setChecked(self.loop_plaing)
        loop_act = getattr(self, 'loop_action', None)
        if loop_act is not None:
            loop_act.setChecked(self.loop_plaing)
        self._set_status(
            "Loop playlist: on" if self.loop_plaing else "Loop playlist: off",
            transient_ms=2000,
        )

    #show error in TextInput
    def handle_errors(self):
        self._set_status('Error: ' + str(self.Player.errorString()), transient_ms=6000)

    def _on_player_error(self, error, error_string=""):
        """Surface playback errors instead of failing silently."""
        message = error_string or self.Player.errorString() or str(error)
        logging.warning("Playback error: %s", message)
        self._set_status(f"Playback error: {message}", transient_ms=6000)

        # A single unplayable file should not wedge the whole playlist.
        if self.playlist_urls and self.current_index < len(self.playlist_urls) - 1:
            QTimer.singleShot(1200, self.next)

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
            removing_current = index == self.current_index
            del self.playlist_urls[index]

            # Keep current_index pointing at the same *track*, not the same
            # slot. The old condition also decremented when index > current,
            # which silently shifted playback to the wrong song.
            if index < self.current_index:
                self.current_index -= 1
            elif removing_current:
                if not self.playlist_urls:
                    self.current_index = -1
                    self.Player.stop()
                    self._set_track_title("")
                else:
                    self.current_index = min(index, len(self.playlist_urls) - 1)
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
        """Play the clicked row.

        Uses the widget's real row index. The old version parsed the leading
        number out of the item's display text, which broke as soon as a
        download-status prefix was prepended ("\u2b07\ufe0f 3. song.mp3") or a
        filename itself started with digits.
        """
        try:
            if not isinstance(self.ui, PlaylistUI):
                return
            index = self.ui.list_songs.row(item)
            if 0 <= index < len(self.playlist_urls):
                self.current_index = index
                self.play_current()
        except Exception:
            logging.exception("Could not play clicked song")

    @log_call()
    def play_current(self):
        """Start playback of the current index."""
        if 0 <= self.current_index < len(self.playlist_urls):
            current_url = self.playlist_urls[self.current_index]

            # Entries queued from a YouTube download are placeholders until
            # the file actually lands on disk. Trying to play one produced an
            # opaque media error, so report the real reason instead.
            if current_url.scheme() == 'pending':
                self._set_status("Still downloading - track not ready yet",
                                 transient_ms=3000)
                return

            # persist playing state for future features
            self._persist_playing_state(current_url.toLocalFile())

            self.Player.setSource(current_url)
            self.Player.play()
            self.update_play_stop_icon()

            # feed audio to visualizer (always, so it's ready when shown)
            if hasattr(self, 'visualizer_widget') and isinstance(self.visualizer_widget, VisualizerWidget):
                self.visualizer_widget.set_audio(current_url.toLocalFile())

            # Lyrics are loaded via context menu only, not auto-loaded

            # update title display
            self._set_track_title(f"{self.current_index + 1}. {current_url.fileName()}")
            self._clear_status()
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
            else:
                # Show what is queued up rather than leaving the panel reading
                # "no track loaded" while the playlist is clearly populated.
                self._set_track_title(
                    f"1. {self.playlist_urls[0].fileName()}"
                )

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
        etype = event.type()

        # Docks are managed by QMainWindow now, so Move/Resize needs no manual
        # repositioning. Only window-state and palette changes matter here.
        if etype == QEvent.Type.WindowStateChange and obj is self:
            if self.isMinimized():
                self._panels_hidden_by_minimize = []
                for name in ('playlist_dock', 'lyrics_dock'):
                    dock = getattr(self, name, None)
                    if dock is not None and dock.isVisible():
                        self._panels_hidden_by_minimize.append(name)
            elif getattr(self, '_panels_hidden_by_minimize', None):
                for name in self._panels_hidden_by_minimize:
                    dock = getattr(self, name, None)
                    if dock is not None:
                        dock.show()
                self._panels_hidden_by_minimize = []

        if etype == QEvent.Type.MouseButtonDblClick and obj is self.time_lcd:
            self.toggle_visualizer()
            return True

        if etype == QEvent.Type.ApplicationPaletteChange:
            if getattr(self, '_track_system_theme', False):
                self._apply_system_theme()

        return super().eventFilter(obj, event)

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
        """Ensure visualizer widget exists (created at init in central widget)."""
        # Visualizer is now embedded in main window, created during __init__
        pass

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
            self.lyrics_dock.visibilityChanged.connect(self._on_lyrics_visibility_changed)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.lyrics_dock)
        except Exception as e:
            logging.exception("Lyrics init failed: %s", e)
            self.lyrics_widget = QLabel(f"Lyrics failed to initialize: {e}")
            self.lyrics_dock = QDockWidget("Lyrics", self)
            self.lyrics_dock.setWidget(self.lyrics_widget)

    def set_visualizer_visible(self, visible: bool):
        # Visualizer is embedded in the main window, not a dock
        if getattr(self, 'visualizer_widget', None) is not None:
            self.visualizer_widget.setVisible(visible)
        vis_act = getattr(self, 'visualizer_action', None)
        if vis_act is not None:
            vis_act.setChecked(visible)
        self._save_gui_state()

    def _on_lyrics_visibility_changed(self, visible: bool):
        """Dock-driven visibility slot, guarded against teardown races."""
        try:
            self.set_lyrics_visible(visible)
        except RuntimeError:
            pass

    def set_lyrics_visible(self, visible: bool):
        """Show/hide the lyrics dock.

        Guarded against re-entry: this is also wired to the dock's own
        visibilityChanged signal, and _fade_dock() calls show()/hide(), so
        without the guard every toggle re-triggered itself and spawned a
        cascade of overlapping animations.
        """
        if self.lyrics_dock is None:
            return
        if getattr(self, '_lyrics_visibility_guard', False):
            return

        self._lyrics_visibility_guard = True
        try:
            if visible != self.lyrics_dock.isVisible():
                # Lyrics are loaded via the "Download Lyrics" context menu
                # action only, never automatically when the dock is shown.
                self._fade_dock(self.lyrics_dock, fade_in=visible)

            lyr_act = getattr(self, 'lyrics_action', None)
            if lyr_act is not None:
                lyr_act.setChecked(visible)
        finally:
            self._lyrics_visibility_guard = False

        self._save_gui_state()

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
        # Visualizer is embedded in main window
        is_visible = hasattr(self, 'visualizer_widget') and self.visualizer_widget is not None and self.visualizer_widget.isVisible()
        self.set_visualizer_visible(not is_visible)
    def toggle_lyrics(self):
        self.set_lyrics_visible(not (self.lyrics_dock is not None and self.lyrics_dock.isVisible()))

    # --- Ensure menu state is updated if user closes component window directly ---
    # (Assumes VisualizerWidget and LyricsWidget can emit a signal or call back on close)
    # If not, we can subclass and override closeEvent to call back here.

    # --- Improved stacking for UX ---
    def _stack_playlist_below(self):
        """Make sure the playlist dock is visible.

        This used to call addDockWidget() again on every invocation, which
        re-docked the widget and destroyed the lyrics/playlist split the user
        had arranged. Qt already owns the dock layout - just reveal it.
        """
        try:
            dock = getattr(self, 'playlist_dock', None)
            if dock is not None:
                dock.show()
                dock.raise_()
        except Exception:
            logging.exception("Error revealing playlist dock")

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
            # Snapshot the layout while the widgets are still shown, then stop
            # accepting further saves for the rest of teardown.
            self._persist_gui_state()
            self._gui_state_frozen = True
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
        """Legacy name kept for callers; delegates to the single saver."""
        self._save_gui_state()

    def _gui_state_path(self) -> Path:
        return Path.home() / ".luister" / "states" / "gui.txt"

    def _load_gui_state(self):
        """Read persisted panel visibility.

        Defaults: visualizer on, lyrics OFF. Lyrics transcription is an
        opt-in, expensive feature, so the panel should not occupy screen
        space until the user asks for it.
        """
        state = {"visualizer": "1", "lyrics": "0", "playlist": "1"}
        try:
            gui_file = self._gui_state_path()
            if not gui_file.exists():
                return state

            stored = {}
            for line in gui_file.read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    stored[k.strip()] = v.strip()

            # Files written before the lyrics-default change carry no schema
            # marker. Those recorded "lyrics=1" only because the old build
            # force-showed the panel on every launch, not because the user
            # chose it - so discard that one value and let the new default win.
            if stored.get("schema") != _GUI_STATE_SCHEMA:
                stored.pop("lyrics", None)

            state.update({k: v for k, v in stored.items() if k != "schema"})
        except Exception:
            pass
        return state

    def _dock_visibility_changed(self, _visible=None):
        """visibilityChanged slot that survives interpreter teardown.

        Qt emits visibilityChanged while the C++ side of the window is being
        destroyed; touching `self` at that point raises RuntimeError from sip.
        """
        try:
            self._save_gui_state()
        except RuntimeError:
            pass

    def _save_gui_state(self):
        """Persist panel visibility so the user's choice survives a restart.

        Previously only a loader existed - nothing ever wrote the file, so
        toggling a panel was forgotten the moment the app closed.
        """
        try:
            ready = self._gui_state_ready
        except (AttributeError, RuntimeError):
            return
        if not ready:
            # Don't write during construction, when widgets are mid-setup.
            return
        if getattr(self, "_gui_state_frozen", False):
            # Teardown hides every dock on the way out. Without this guard the
            # resulting visibilityChanged storm overwrote the saved layout with
            # "everything hidden" on every exit.
            return
        try:
            lyrics_dock = getattr(self, "lyrics_dock", None)
            playlist_dock = getattr(self, "playlist_dock", None)
            visualizer = getattr(self, "visualizer_widget", None)
            state = {
                "visualizer": "1" if (visualizer is not None and visualizer.isVisible()) else "0",
                "lyrics": "1" if (lyrics_dock is not None and lyrics_dock.isVisible()) else "0",
                "playlist": "1" if (playlist_dock is not None and playlist_dock.isVisible()) else "0",
            }
            gui_file = self._gui_state_path()
            gui_file.parent.mkdir(parents=True, exist_ok=True)
            state["schema"] = _GUI_STATE_SCHEMA
            gui_file.write_text(
                "\n".join(f"{k}={v}" for k, v in state.items()) + "\n",
                encoding="utf-8",
            )
        except Exception:
            logging.debug("Could not persist GUI state")

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
                    # Visualizer is embedded in main window, hides with it
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
                    # Lyrics deliberately not force-shown here: restoring from
                    # the tray must not re-open a panel the user closed.
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
        # Lyrics deliberately not force-shown here (see _on_tray_activated).

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
    """Background thread that uses yt-dlp to fetch audio files from YouTube.

    Workflow:
    1. Extract metadata for all items first (playlist or single video)
    2. Emit metadata_ready so the UI can show the tracks immediately
    3. Download each item, emitting per-item progress
    4. Emit item_complete / item_error per item
    5. Emit batch_finished when all items are done

    YouTube periodically breaks a given extractor client, which surfaces as
    "HTTP Error 403: Forbidden" on the media download while metadata still
    resolves fine. We therefore retry each item across several player clients
    rather than failing on the first 403.
    """

    # Emitted with list of dicts: [{'title': str, 'duration': int, 'url': str}, ...]
    metadata_ready = pyqtSignal(list)
    # Emitted with (item_index, percent) for per-item progress
    item_progress = pyqtSignal(int, int)
    # Emitted with (item_index, file_path) when item download completes
    item_complete = pyqtSignal(int, str)
    # Emitted with (item_index, error_msg) when item download fails
    item_error = pyqtSignal(int, str)
    # Emitted with the list of downloaded file paths once the batch is done.
    # NOTE: deliberately *not* called `finished` - that name is already taken by
    # QThread's own no-argument finished() signal and shadowing it breaks the
    # thread's internal lifecycle notifications.
    batch_finished = pyqtSignal(list)
    progress = pyqtSignal(int)

    # Player clients to try in order. The first that yields a downloadable
    # stream wins; each subsequent one is a fallback for 403/nsig breakage.
    PLAYER_CLIENTS = ('default', 'ios', 'android_vr', 'web_safari', 'tv')

    def __init__(self, url: str, output_dir: Path):
        super().__init__()
        self._url = url
        self._output_dir = output_dir
        self._last_progress = -1
        self._current_item_index = 0
        self._downloaded_files: list[str] = []
        self._final_path: Optional[str] = None
        self._cancelled = False

    def cancel(self):
        """Ask the running download to stop at the next safe point."""
        self._cancelled = True

    def _progress_hook(self, d: dict):
        """yt-dlp progress hook callback."""
        if self._cancelled:
            # yt-dlp treats an exception from a hook as an aborted download.
            raise RuntimeError("cancelled")
        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            if total and total > 0:
                pct = int((downloaded / total) * 100)
                if pct != self._last_progress:
                    self._last_progress = pct
                    self.item_progress.emit(self._current_item_index, pct)
                    self.progress.emit(pct)
        elif d.get('status') == 'finished':
            # Pre-postprocessing path; may be replaced by the PP hook below.
            fn = d.get('filename')
            if fn:
                self._final_path = fn
            self.item_progress.emit(self._current_item_index, 100)
            self.progress.emit(100)

    def _postprocessor_hook(self, d: dict):
        """Capture the real output path after ffmpeg conversion."""
        if d.get('status') != 'finished':
            return
        info = d.get('info_dict') or {}
        path = info.get('filepath') or info.get('_filename')
        if path:
            self._final_path = path

    def _find_ffmpeg(self) -> str | None:
        """Find ffmpeg binary path."""
        # For PyInstaller bundles, check the app's directory first
        if getattr(sys, 'frozen', False):
            app_dir = Path(sys.executable).parent
            if sys.platform == 'darwin':
                bundle_paths = [
                    app_dir / 'ffmpeg',
                    app_dir.parent / 'Frameworks' / 'ffmpeg',
                    app_dir.parent / 'Resources' / 'ffmpeg',
                ]
            else:
                bundle_paths = [app_dir / 'ffmpeg', app_dir / 'ffmpeg.exe']

            for bp in bundle_paths:
                if bp.exists():
                    return str(bp)

        # Fall back to PATH, then to the usual install locations
        from shutil import which
        found = which('ffmpeg')
        if found:
            return found
        for path in ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg']:
            if Path(path).exists():
                return path
        return None

    def _base_opts(self, ffmpeg_path: str | None) -> dict:
        opts: dict = {
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'noplaylist': False,
            'retries': 3,
            'fragment_retries': 3,
            'ignoreerrors': False,
        }
        if ffmpeg_path:
            opts['ffmpeg_location'] = str(Path(ffmpeg_path).parent)
        return opts

    def _download_one(self, item: dict, idx: int, ffmpeg_path: str | None) -> str | None:
        """Download a single item, trying each player client until one works.

        Returns the output file path, or None if every client failed.
        """
        import yt_dlp

        safe_title = "".join(c for c in item['title'] if c.isalnum() or c in ' ._-').strip()[:100]
        if not safe_title:
            safe_title = f"video_{item.get('id', idx)}"

        download_url = item.get('url') or f"https://www.youtube.com/watch?v={item['id']}"
        last_error: Optional[Exception] = None

        for client in self.PLAYER_CLIENTS:
            if self._cancelled:
                return None

            self._final_path = None
            self._last_progress = -1

            ydl_opts = self._base_opts(ffmpeg_path)
            ydl_opts.update({
                'format': 'bestaudio/best',
                'outtmpl': str(self._output_dir / f'{safe_title}.%(ext)s'),
                'progress_hooks': [self._progress_hook],
                'postprocessor_hooks': [self._postprocessor_hook],
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
            if client != 'default':
                ydl_opts['extractor_args'] = {'youtube': {'player_client': [client]}}

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([download_url])

                # Prefer the path reported by the hooks; fall back to the
                # expected output name (covers the "already downloaded" case
                # where yt-dlp skips the transfer and no hook fires).
                path = self._final_path
                if not path or not Path(path).exists():
                    candidate = self._output_dir / f'{safe_title}.mp3'
                    path = str(candidate) if candidate.exists() else None

                if path and Path(path).exists():
                    if client != 'default':
                        logging.info("Item %d downloaded using fallback client '%s'", idx, client)
                    return path

                last_error = RuntimeError("no output file produced")
            except Exception as exc:
                last_error = exc
                if self._cancelled:
                    return None
                logging.warning(
                    "Client '%s' failed for item %d (%s); trying next client",
                    client, idx, str(exc)[:200],
                )

        if last_error is not None:
            raise last_error
        return None

    def run(self):  # noqa: D401
        try:
            import yt_dlp
        except ImportError:
            logging.error("yt_dlp module not found; please install yt-dlp")
            self.batch_finished.emit([])
            return

        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)

            # Step 1: Extract metadata without downloading
            extract_opts = {
                'quiet': True,
                'no_warnings': True,
                'noprogress': True,
                'extract_flat': 'in_playlist',
            }

            items_to_download = []
            try:
                with yt_dlp.YoutubeDL(extract_opts) as ydl:
                    info = ydl.extract_info(self._url, download=False)

                    if info is None:
                        self.batch_finished.emit([])
                        return

                    if 'entries' in info:
                        for entry in info.get('entries', []):
                            if entry:
                                items_to_download.append({
                                    'title': entry.get('title', 'Unknown'),
                                    'duration': entry.get('duration', 0),
                                    'url': entry.get('url') or entry.get('webpage_url', ''),
                                    'id': entry.get('id', ''),
                                })
                    else:
                        items_to_download.append({
                            'title': info.get('title', 'Unknown'),
                            'duration': info.get('duration', 0),
                            'url': info.get('webpage_url', self._url),
                            'id': info.get('id', ''),
                        })

                if items_to_download:
                    self.metadata_ready.emit(items_to_download)
                    logging.info("Found %d items to download", len(items_to_download))

            except Exception as exc:
                logging.exception("Failed to extract metadata: %s", exc)
                self.batch_finished.emit([])
                return

            # Step 2: Download each item individually
            ffmpeg_path = self._find_ffmpeg()
            if ffmpeg_path:
                logging.info("Using ffmpeg from: %s", str(Path(ffmpeg_path).parent))
            else:
                logging.warning("ffmpeg not found - audio conversion may fail")

            for idx, item in enumerate(items_to_download):
                if self._cancelled:
                    break
                self._current_item_index = idx

                try:
                    file_path = self._download_one(item, idx, ffmpeg_path)
                    if file_path:
                        self._downloaded_files.append(file_path)
                        self.item_complete.emit(idx, file_path)
                        logging.info("Downloaded item %d: %s", idx, file_path)
                    elif not self._cancelled:
                        self.item_error.emit(idx, "No output file created")
                        logging.warning("No output file for item %d", idx)
                except Exception as exc:
                    message = str(exc)
                    if 'HTTP Error 403' in message:
                        message = (
                            "YouTube refused the download (403) on every client. "
                            "Updating yt-dlp usually fixes this."
                        )
                    self.item_error.emit(idx, message[:200])
                    logging.exception("Failed to download item %d: %s", idx, exc)

            self.batch_finished.emit(self._downloaded_files)
            logging.info("Download complete: %d files", len(self._downloaded_files))

        except Exception:
            logging.exception("YTDownloadThread encountered an unexpected error")
            self.batch_finished.emit([])

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