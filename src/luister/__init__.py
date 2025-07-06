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
)
from PyQt6.QtCore import QUrl, QEvent, Qt, QSize, QBuffer, QIODevice, QTimer
from PyQt6.QtGui import QIcon, QAction, QActionGroup, QPalette, QTransform, QPixmap
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
import sys
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
    playlist_icon,
    folder_icon,
    shuffle_icon,
    loop_icon,
    apply_shadow,
    double_left_icon,
    double_right_icon,
    slider_handle_icon,
    tray_icon,
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
        _mk_btn("shuffle_btn", 340, 150, 121, 25)
        _mk_btn("loop_btn", 470, 150, 61, 25)
        eq_btn = QPushButton("EQ", central); eq_btn.setObjectName("eq_btn"); eq_btn.setGeometry(470, 70, 51, 25)
        pl_btn = QPushButton("PL", central); pl_btn.setObjectName("pl_btn"); pl_btn.setGeometry(530, 70, 51, 25)

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

        # End of manual UI build
        self.resize(620, 230)  # match original designer size

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
        self.eq_btn = self.findChild(QPushButton, "eq_btn")
        self.shuffle_btn = self.findChild(QPushButton, 'shuffle_btn')
        self.loop_btn = self.findChild(QPushButton, 'loop_btn')
        self.pl_btn = self.findChild(QPushButton, 'pl_btn')
        # Theme menu
        menubar = self.menuBar()  # type: ignore[reportOptionalMemberAccess]

        # View menu with visualizer toggle
        view_menu = menubar.addMenu("&View")  # type: ignore
        self.visualizer_action = view_menu.addAction("Visualizer")  # type: ignore
        self.visualizer_action.setCheckable(True)  # type: ignore[attr-defined]
        self.visualizer_action.toggled.connect(lambda checked: self.toggle_visualizer() if checked else self.toggle_visualizer())  # type: ignore
        self.lyrics_action = view_menu.addAction("Lyrics")  # type: ignore
        self.lyrics_action.setCheckable(True)  # type: ignore
        self.lyrics_action.toggled.connect(self.toggle_lyrics)  # type: ignore

        theme_menu = menubar.addMenu("&Theme")  # type: ignore
        quit_action = menubar.addAction("Quit")  # type: ignore
        quit_action.triggered.connect(self.quit_app)  # type: ignore

        self.action_group = QActionGroup(self)
        self.action_group.setExclusive(True)

        self.light_action = QAction("Light", self)
        self.light_action.setCheckable(True)
        self.dark_action = QAction("Dark", self)
        self.dark_action.setCheckable(True)

        self.action_group.addAction(self.light_action)
        self.action_group.addAction(self.dark_action)

        theme_menu.addAction(self.light_action)  # type: ignore
        theme_menu.addAction(self.dark_action)  # type: ignore

        self.light_action.triggered.connect(lambda: self.set_theme("light"))
        self.dark_action.triggered.connect(lambda: self.set_theme("dark"))
        #set icons
        sp = QStyle.StandardPixmap  # type: ignore[attr-defined]
        self.back_btn.setIcon(double_left_icon())
        self.play_btn.setIcon(play_icon())
        self.pause_btn.setIcon(pause_icon())
        self.stop_btn.setIcon(stop_icon())
        self.next_btn.setIcon(double_right_icon())
        self.download_btn.setIcon(folder_icon())
        self.eq_btn.setIcon(eq_icon())
        self.pl_btn.setIcon(playlist_icon())

        for btn in (
            self.back_btn,
            self.play_btn,
            self.pause_btn,
            self.stop_btn,
            self.next_btn,
            self.eq_btn,
            self.pl_btn,
            self.download_btn,
            self.shuffle_btn,
            self.loop_btn,
        ):
            btn.setText("")
            btn.setIconSize(QSize(24, 24))
            apply_shadow(btn)

        # uniform button sizes
        uniform_size = self.play_btn.size()
        self.shuffle_btn.setFixedSize(uniform_size)
        self.loop_btn.setFixedSize(uniform_size)

        # reposition shuffle & loop to sit right of next_btn with 20px gap
        gap = 100
        new_x = self.next_btn.x() + uniform_size.width() + gap
        self.shuffle_btn.move(new_x, self.next_btn.y())
        self.loop_btn.move(new_x + uniform_size.width() + 10, self.next_btn.y())

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
        self.shuffle_btn.clicked.connect(self.shuffle)
        self.loop_btn.clicked.connect(self.loop)
        self.pl_btn.clicked.connect(self.toggle_playlist)

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
        self._ensure_playlist()
        # restore last playlist from config
        last_paths = self._config.get("last_playlist", [])
        if last_paths:
            # clear existing playlist
            self.playlist_urls.clear()
            self.ui.list_songs.clear()
            for p in last_paths:
                url = QUrl.fromLocalFile(p)
                self.playlist_urls.append(url)
            # repopulate UI list
            for i, url in enumerate(self.playlist_urls, 1):
                self.ui.list_songs.addItem(f"{i}. {url.fileName()}")
            self.set_Enabled_button()
            # restore last index
            last_idx = self._config.get("last_index", 0)
            if 0 <= last_idx < len(self.playlist_urls):
                self.current_index = last_idx
                item = self.ui.list_songs.item(self.current_index)
                if item:
                    self.ui.list_songs.setCurrentItem(item)
                    self.ui.list_songs.scrollToItem(item)

        self.ui.show()
        self._stack_playlist_below()

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
            if self.lyrics is not None:
                try:
                    self.lyrics.segments_ready.connect(self._on_lyrics_ready)  # type: ignore
                except Exception:
                    pass
        self._ensure_lyrics = patched_ensure_lyrics

        # -- System Tray Icon Setup --
        # Create a tray icon that toggles the app visibility on click
        self.tray_icon = QSystemTrayIcon(tray_icon(), self)  # type: ignore
        self.tray_icon.activated.connect(self._on_tray_activated)  # type: ignore
        self.tray_icon.show()

        # tray icon rotating animation
        self._tray_base_icon = tray_icon()
        self._tray_rotation_angle = 0
        self._tray_timer = QTimer(self)
        self._tray_timer.timeout.connect(self._rotate_tray_icon)
        self._tray_timer.start(100)  # 10 FPS

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

    #download list of music
    @log_call()
    def download(self):
        try:
            # Ask user for a directory first; if cancelled, fall back to files
            dir_path = QFileDialog.getExistingDirectory(self, 'Select music directory')

            selected_files = []
            if dir_path:
                # Collect common audio files inside directory (non-recursive)
                audio_exts = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac'}
                for p in Path(dir_path).iterdir():
                    if p.suffix.lower() in audio_exts and p.is_file():
                        selected_files.append(str(p))
            else:
                # Fall back to picking individual files
                files, _ = QFileDialog.getOpenFileNames(self, 'Select songs')
                selected_files.extend(files)

            if selected_files:
                # ensure playlist exists and is visible
                self._ensure_playlist()
                if not self.ui.isVisible():
                    self.ui.show()
                self._add_files(selected_files)
            else:
                self.title_lcd.setPlainText('No audio files found in selected directory')
        except Exception as e:
            self.title_lcd.setPlainText(f'Error: {e}')

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
        if self.Player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            pass

    #update slider position
    def position_changed(self, position):
        self.time_slider.setValue(position)
        duration_list = convert_duration_to_show(position)
        time = duration_list[0] + ':' + duration_list[1]
        self.time_lcd.setHtml(get_html(time))
        try:
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
        # rebuild list view if open
        if hasattr(self, 'ui'):
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
        self.title_lcd.setPlainText('Error' + str(self.Player.errorString()))

    # ------- Playlist docking/toggle ---------

    def _ensure_playlist(self):
        if not hasattr(self, "ui"):
            self.ui = PlaylistUI(self)
            self.ui.filesDropped.connect(self._add_files)
            self.ui.list_songs.itemDoubleClicked.connect(self.clicked_song)  # type: ignore[arg-type]
        # populate once
        self.ui.list_songs.clear()
        for i, url in enumerate(self.playlist_urls, 1):
            self.ui.list_songs.addItem(f"{i}. {url.fileName()}")

    @log_call()
    def toggle_playlist(self):
        self._ensure_playlist()
        if self.ui.isVisible():
            self.ui.hide()
        else:
            self.ui.show()
            self._stack_playlist_below()

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
            self.Player.setSource(current_url)
            # if lyrics view is visible and no cached segments yet, wait
            if self.lyrics and self.lyrics.isVisible():
                # show progress
                self.lyrics.show_progress()  # type: ignore
                # set pending playback and start loading lyrics
                self._pending_play_when_lyrics_loaded = True
                self.lyrics.load_lyrics(current_url.toLocalFile())  # type: ignore
                return
            else:
                self.Player.play()
                self.update_play_stop_icon()
            # feed audio to visualizer
            if self.visualizer and self.visualizer.isVisible():
                self.visualizer.set_audio(current_url.toLocalFile())
            if self.lyrics and self.lyrics.isVisible():
                self.lyrics.load_lyrics(current_url.toLocalFile())
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
            if hasattr(self, 'ui'):
                self.ui.time_song_text.setPlainText('00:00')
                # select & center current song in playlist view
                item = self.ui.list_songs.item(self.current_index)
                if item is not None:
                    self.ui.list_songs.setCurrentItem(item)
                    self.ui.list_songs.scrollToItem(item)

    @log_call()
    def handle_dropped_urls(self, urls):
        """Called from PlaylistUI when files are dragged into the list widget."""
        paths = [url.toLocalFile() for url in urls]
        if paths:
            self._add_files(paths)

    @log_call()
    def _add_files(self, file_paths):
        """Add a list of local file paths to playlist and UI."""
        i = len(self.playlist_urls) + 1
        for fp in file_paths:
            url = QUrl.fromLocalFile(fp)
            self.playlist_urls.append(url)
            if hasattr(self, 'ui'):
                self.ui.list_songs.addItem(f"{i}. {Path(fp).name}")
            i += 1
        self.set_Enabled_button()
        if self.current_index == -1 and self.playlist_urls:
            self.current_index = 0
            self.play_current()

    def set_theme(self, name: str):
        if getattr(self, "_current_theme", None) == name:
            return
        Theme.apply(QApplication.instance(), name)
        # update check state
        self.light_action.setChecked(name == "light")
        self.dark_action.setChecked(name == "dark")
        self._current_theme = name

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
        self.set_theme(name)

    def eventFilter(self, obj, event):  # noqa: D401
        from PyQt6.QtCore import QEvent
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            if hasattr(self, 'ui') and self.ui.isVisible():
                self._stack_playlist_below()
            if self.visualizer and self.visualizer.isVisible():
                self._stack_visualizer()
            if self.lyrics and self.lyrics.isVisible():
                self._stack_lyrics()
            # hide dependent windows when main window is minimized
            if event.type() == QEvent.Type.WindowStateChange and obj is self:
                if self.isMinimized():
                    if hasattr(self, 'ui'):
                        self.ui.hide()
                    if self.visualizer:
                        self.visualizer.hide()
                    if self.lyrics:
                        self.lyrics.hide()
        if event.type() == QEvent.Type.MouseButtonDblClick and obj is self.time_lcd:
            self.toggle_visualizer()
            return True
        if event.type() == QEvent.Type.MouseButtonDblClick and obj is self.title_lcd:
            self.toggle_lyrics()
            return True
        if event.type() == QEvent.Type.ApplicationPaletteChange:
            self._apply_system_theme()
        return super().eventFilter(obj, event)

    # icon update helper
    def update_play_stop_icon(self):
        sp = QStyle.StandardPixmap  # type: ignore[attr-defined]
        if self.Player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            icon = self.style().standardIcon(sp.SP_MediaStop)  # type: ignore
        else:
            icon = self.style().standardIcon(sp.SP_MediaPlay)  # type: ignore
        self.play_btn.setIcon(icon)

    # ---- style cleanup ----

    def _clear_inline_styles(self):
        from PyQt6.QtWidgets import QWidget
        stack = [self]
        while stack:
            w = stack.pop()
            if isinstance(w, QWidget) and w.styleSheet():  # type: ignore[arg-type]
                w.setStyleSheet("")
            stack.extend(list(w.findChildren(QWidget)))  # type: ignore[arg-type]

    # ---- audio device handling ----

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

    # ------- Visualizer -------

    def _ensure_visualizer(self):
        if self.visualizer is None:
            self.visualizer = VisualizerWidget()
            self.visualizer.setWindowTitle("Visualizer")
            self.visualizer.resize(150, 400)
            # wire player position
            self.Player.positionChanged.connect(self.visualizer.update_position)

            get_manager().register(self.visualizer)
    def _ensure_lyrics(self):
        if self.lyrics is None:
            self.lyrics = LyricsWidget()  # type: ignore
            self.lyrics.setWindowTitle("Lyrics")  # type: ignore
            self.lyrics.resize(300, 400)  # type: ignore
            # wire player position updates for lyrics sync
            self.Player.positionChanged.connect(self.lyrics.update_position)  # type: ignore
            get_manager().register(self.lyrics)

    def toggle_visualizer(self):
        self._ensure_visualizer()
        if self.visualizer is None:
            return
        if self.visualizer.isVisible():
            self.visualizer.hide()
        else:
            self.visualizer.show()
            # if no magnitude data yet and a track is loaded, feed it
            if self.current_index >= 0 and self.current_index < len(self.playlist_urls):
                self.visualizer.set_audio(self.playlist_urls[self.current_index].toLocalFile())
            self._stack_visualizer()
    def toggle_lyrics(self):
        self._ensure_lyrics()
        if self.lyrics is None:
            return
        if self.lyrics.isVisible():
            self.lyrics.hide()
        else:
            # load lyrics for current track
            if self.current_index >= 0 and self.current_index < len(self.playlist_urls):
                self.lyrics.load_lyrics(self.playlist_urls[self.current_index].toLocalFile())
            self.lyrics.show()
            self._stack_lyrics()

    # ---- positioning helper ----

    def _stack_playlist_below(self):
        if not hasattr(self, 'ui'):
            return
        geo = self.geometry()
        self.ui.setGeometry(geo.left(), geo.bottom() + 5, geo.width(), 400)

    def _stack_visualizer(self):
        if self.visualizer is None:
            return
        main_geo = self.geometry()
        playlist_height = self.ui.height() if hasattr(self, 'ui') and self.ui.isVisible() else 0
        total_height = main_geo.height() + playlist_height + 5
        vis_width = main_geo.width()
        left_x = main_geo.left() - vis_width - 5
        self.visualizer.setGeometry(left_x, main_geo.top(), vis_width, total_height)
    def _stack_lyrics(self):
        if self.lyrics is None:
            return
        main_geo = self.geometry()
        playlist_height = self.ui.height() if hasattr(self, 'ui') and self.ui.isVisible() else 0
        total_height = main_geo.height() + playlist_height + 5
        right_x = main_geo.right() + 5
        self.lyrics.setGeometry(right_x, main_geo.top(), main_geo.width(), total_height)

    @log_call()
    def quit_app(self):
        # save playlist state to config
        try:
            self._config["last_playlist"] = [url.toLocalFile() for url in self.playlist_urls]
            self._config["last_index"] = self.current_index
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f)
        except Exception:
            pass
        mgr = get_manager()
        mgr.shutdown()
        app = QApplication.instance()
        if app is not None:
            app.quit()  # type: ignore[attr-defined]

    def _on_lyrics_ready(self, segments):
        """Slot called when lyrics segments are loaded; resume playback if pending."""
        if getattr(self, '_pending_play_when_lyrics_loaded', False):
            self._pending_play_when_lyrics_loaded = False
            # hide progress bar
            if self.lyrics:
                self.lyrics.hide_progress()  # type: ignore
            self.Player.play()
            self.update_play_stop_icon()

    def closeEvent(self, event):  # override close to hide windows instead of exit
        event.ignore()
        # hide main and all child windows
        self.hide()
        if hasattr(self, 'ui'):
            self.ui.hide()
        if self.visualizer and self.visualizer.isVisible():
            self.visualizer.hide()
        if self.lyrics and self.lyrics.isVisible():
            self.lyrics.hide()
        # keep tray icon active

    def _on_tray_activated(self, reason):
        """Toggle app windows on tray icon click."""
        try:
            if reason == QSystemTrayIcon.ActivationReason.Trigger:  # type: ignore[attr-defined]
                # toggle main and child windows
                if self.isVisible():
                    self.hide()
                    if hasattr(self, 'ui'):
                        self.ui.hide()
                    if self.visualizer:
                        self.visualizer.hide()
                    if self.lyrics:
                        self.lyrics.hide()
                else:
                    self.show()
                    if hasattr(self, 'ui'):
                        self.ui.show()
                    if self.visualizer:
                        self.visualizer.show()
                    if self.lyrics:
                        self.lyrics.show()
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

def main():
    app = QApplication(sys.argv)
    UIWindow = UI()
    app.exec()


if __name__ == "__main__":
    main()