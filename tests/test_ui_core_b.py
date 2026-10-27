"""E2E-style tests for the second half of luister.UI, YTDownloadThread, main()."""

import json
import signal
import struct
import sys
import types
import wave
from pathlib import Path
from unittest import mock

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, QUrl, Qt
from PyQt6.QtGui import QMouseEvent, QPalette, QColor
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDockWidget, QLabel, QPushButton, QSystemTrayIcon

import luister
from luister.views import PlaylistUI


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    yield existing or QApplication([])


@pytest.fixture
def ui(app, tmp_path, monkeypatch):
    monkeypatch.setattr(luister.Path, "home", staticmethod(lambda: tmp_path))
    window = luister.UI()
    yield window
    window._gui_state_frozen = True
    window.Player.stop()


@pytest.fixture
def wavs(tmp_path):
    paths = []
    for name in ("a.wav", "b.wav", "c.wav"):
        p = tmp_path / name
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(struct.pack("<h", 0) * 800)
        paths.append(str(p))
    return paths


@pytest.fixture
def loaded(ui, wavs):
    ui._ensure_playlist()
    ui._add_files(wavs, play_on_load=False)
    return ui


# --- volume / mute -------------------------------------------------------


def test_mute_toggle_and_glyphs(ui):
    ui.volume_slider.setValue(80)
    ui.toggle_mute()
    assert ui.volume_slider.value() == 0 and ui._muted
    assert ui.mute_btn.isChecked()
    ui.toggle_mute()
    assert ui.volume_slider.value() == 80 and not ui._muted
    for v in (20, 50, 90):
        ui._sync_mute_button(v)
    ui.nudge_volume(-1000)
    assert ui.volume_slider.value() == 0
    ui.nudge_volume(5)
    assert ui.volume_slider.value() == 5


def test_sync_mute_button_without_button(ui):
    del ui.mute_btn
    ui._sync_mute_button(10)


def test_persist_volume_writes_and_swallows_errors(ui, tmp_path):
    ui._config_path = tmp_path / "cfg.json"
    ui._persist_volume(42)
    assert json.loads(ui._config_path.read_text())["volume"] == 42
    ui._config_path = tmp_path / "missing" / "cfg.json"
    ui._persist_volume(10)


# --- player state / display ---------------------------------------------


def test_audiostate_and_formatting(ui):
    ui.audiostate_changed(QMediaPlayer.PlaybackState.PlayingState)
    ui.audiostate_changed(QMediaPlayer.PlaybackState.PausedState)
    assert ui._format_ms(3_661_000) == "1:01:01"
    assert ui._format_ms(-5) == "00:00"
    assert ui._format_ms(65_000) == "01:05"


def test_position_and_duration(loaded):
    loaded.duration_changed(120_000)
    assert loaded.total_label.text() == "02:00"
    loaded.position_changed(5000)
    assert loaded.elapsed_label.text() == "00:05"
    assert loaded.time_slider.value() == 5000
    loaded._user_seeking = True
    loaded.position_changed(9000)
    assert loaded.time_slider.value() == 5000
    loaded.set_position(1000)


def test_position_changed_with_broken_playlist_ui(ui):
    ui._ensure_playlist()
    ui.ui.time_song_text = mock.Mock()
    ui.ui.time_song_text.setPlainText.side_effect = RuntimeError
    ui.position_changed(1000)


def test_display_and_status(ui):
    ui._set_track_title("Song")
    ui._set_status("hello", transient_ms=1)
    assert "hello" in ui.time_lcd.toPlainText()
    QTest.qWait(30)
    assert ui.time_lcd.toPlainText() == "Song"
    ui._set_track_title("")
    assert ui.time_lcd.toPlainText() == "No track loaded"
    ui.time_lcd = mock.Mock()
    ui.time_lcd.setPlainText.side_effect = RuntimeError
    ui._refresh_display()


def test_media_status_invalid_and_other(ui):
    ui.media_status_changed(QMediaPlayer.MediaStatus.InvalidMedia)
    assert "Cannot play" in ui.time_lcd.toPlainText()
    ui.media_status_changed(QMediaPlayer.MediaStatus.LoadedMedia)


def test_end_of_media_last_track_stops(loaded):
    loaded.current_index = 2
    loaded.loop_plaing = False
    loaded.media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)
    assert "End of playlist" in loaded.time_lcd.toPlainText()


def test_end_of_media_advances(loaded):
    loaded.current_index = 0
    with mock.patch.object(loaded, "next") as nxt:
        loaded.media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)
    nxt.assert_called_once()


def test_shuffle_keeps_current_track(loaded):
    loaded.shuffle()
    loaded.current_index = 1
    cur = loaded.playlist_urls[1]
    loaded.shuffle()
    assert loaded.playlist_urls[loaded.current_index] == cur
    assert loaded.ui.list_songs.count() == 3


def test_shuffle_empty_and_no_current(ui, wavs):
    ui.shuffle()
    ui.playlist_urls = [QUrl.fromLocalFile(p) for p in wavs]
    ui.current_index = -1
    ui.shuffle()
    assert ui.current_index == -1


def test_loop_toggle(ui):
    ui.loop_btn = QPushButton()
    ui.loop_btn.setCheckable(True)
    ui.loop()
    assert ui.loop_plaing and ui.loop_btn.isChecked()
    ui.loop_action = mock.Mock()
    ui.loop()
    assert not ui.loop_plaing
    ui.loop_action.setChecked.assert_called_with(False)
    ui.loop_btn = None
    ui.loop()


def test_errors(loaded):
    loaded.handle_errors()
    loaded.current_index = 0
    with mock.patch.object(luister.QTimer, "singleShot") as ss:
        loaded._on_player_error(None, "boom")
        ss.assert_any_call(1200, loaded.next)
    loaded.current_index = 2
    loaded._on_player_error(None, "")


# --- playlist ------------------------------------------------------------


def test_ensure_playlist_failure_falls_back_to_label(ui):
    del ui.ui
    class Boom(PlaylistUI):
        def __init__(self, *a, **k):
            raise RuntimeError("x")

    with mock.patch.object(luister, "PlaylistUI", Boom):
        ui._ensure_playlist()
    assert isinstance(ui.ui, QLabel)
    ui._update_playlist_selection()
    ui.ui = None
    ui._update_playlist_selection()


def test_double_click_plays_row(loaded):
    item = loaded.ui.list_songs.item(1)
    loaded.ui.list_songs.itemDoubleClicked.emit(item)
    assert loaded.current_index == 1
    assert "2. b.wav" in loaded.time_lcd.toPlainText()
    assert Path(loaded.Player.source().toLocalFile()).name == "b.wav"


def test_clicked_song_non_playlist_and_error(loaded):
    loaded.clicked_song(loaded.ui.list_songs.item(0))
    with mock.patch.object(loaded, "play_current", side_effect=RuntimeError):
        loaded.clicked_song(loaded.ui.list_songs.item(0))
    loaded.ui = QLabel("x")
    loaded.clicked_song(None)


def test_play_current_pending_placeholder(loaded):
    loaded.playlist_urls[0] = QUrl("pending://x")
    loaded.current_index = 0
    loaded.play_current()
    assert "Still downloading" in loaded.time_lcd.toPlainText()


def test_play_current_out_of_range_noop(ui):
    ui.current_index = -1
    ui.play_current()


def test_add_files_autoplay_replace_and_drop(ui, wavs):
    ui._ensure_playlist()
    ui.handle_dropped_urls([])
    ui.handle_dropped_urls([QUrl.fromLocalFile(wavs[0])])
    assert ui.current_index == 0 and len(ui.playlist_urls) == 1
    ui._add_files(wavs[1:], replace=True, play_on_load=False)
    assert len(ui.playlist_urls) == 2
    assert "1. b.wav" in ui.time_lcd.toPlainText()


def test_add_files_replace_without_playlist_ui(ui, wavs):
    ui.ui = QLabel("x")
    ui._add_files(wavs, replace=True, play_on_load=False)
    assert len(ui.playlist_urls) == 3


def test_remove_requested(loaded):
    loaded.current_index = 1
    loaded._on_remove_requested(0)
    assert loaded.current_index == 0
    loaded._on_remove_requested(0)  # remove current
    assert loaded.current_index == 0 and len(loaded.playlist_urls) == 1
    loaded._on_remove_requested(0)
    assert loaded.current_index == -1
    loaded._on_remove_requested(5)
    loaded.playlist_urls = [QUrl("file:///a"), QUrl("file:///b")]
    loaded.current_index = 0
    loaded._on_remove_requested(1)
    assert loaded.current_index == 0
    loaded.ui = QLabel("x")
    loaded._on_remove_requested(0)


def test_lyrics_requested(loaded):
    loaded._ensure_lyrics()
    with mock.patch.object(luister.LyricsWidget, "load_lyrics") as ll:
        loaded._on_lyrics_requested(0)
    ll.assert_called_once()
    loaded._on_lyrics_requested(99)
    loaded.lyrics_dock = None
    loaded._on_lyrics_requested(0)


def test_lyrics_requested_dock_with_foreign_widget(loaded):
    loaded.lyrics_dock = QDockWidget("x", loaded)
    loaded.lyrics_dock.setWidget(QLabel("y"))
    loaded.lyrics_dock.show()
    loaded._on_lyrics_requested(0)


def test_toggle_playlist(loaded):
    loaded.show()
    loaded.playlist_dock.show()
    loaded.toggle_playlist()
    assert not loaded.playlist_dock.isVisible()
    loaded.toggle_playlist()
    assert loaded.playlist_dock.isVisible()


def test_toggle_playlist_fallback_paths(loaded):
    loaded.show()
    loaded.playlist_dock = None
    loaded.toggle_playlist()
    loaded.toggle_playlist()
    loaded.ui = None
    with mock.patch.object(loaded, "_ensure_playlist"):
        loaded.toggle_playlist()
    loaded.playlist_dock = mock.Mock()
    loaded.playlist_dock.isVisible.side_effect = RuntimeError
    loaded.toggle_playlist()


# --- theme / events ------------------------------------------------------


def test_dark_palette_and_system_theme(ui):
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
    assert ui._is_dark_palette(pal)
    pal.setColor(QPalette.ColorRole.Window, QColor(255, 255, 255))
    assert not ui._is_dark_palette(pal)
    ui._apply_system_theme()
    assert ui._current_theme in ("dark", "light")


def test_system_theme_dark_and_fallbacks(ui, app):
    hints = mock.Mock()
    hints.colorScheme.return_value = Qt.ColorScheme.Dark
    with mock.patch.object(QApplication, "styleHints", return_value=hints):
        ui._apply_system_theme()
    assert ui._current_theme == "dark"
    with mock.patch.object(QApplication, "styleHints", side_effect=RuntimeError):
        with mock.patch.object(ui, "_apply_dock_styles", side_effect=RuntimeError):
            ui._apply_system_theme()


def test_audio_device_changed(ui):
    ui._audio_device_changed(ui.audio_output.device())
    bad = mock.Mock()
    ui.audio_output = mock.Mock()
    ui.audio_output.setDevice.side_effect = RuntimeError
    ui.audio_output.volume.return_value = 0.5
    with mock.patch.object(luister, "QAudioOutput") as qa:
        qa.return_value = QAudioOutput()
        ui._audio_device_changed(bad)
    qa.assert_called_once_with(bad)


def test_event_filter_minimize_restore(ui):
    ui.show()
    ui.playlist_dock.show()
    ui._ensure_lyrics()
    ev = QEvent(QEvent.Type.WindowStateChange)
    with mock.patch.object(ui, "isMinimized", return_value=True):
        ui.eventFilter(ui, ev)
    assert "playlist_dock" in ui._panels_hidden_by_minimize
    ui.playlist_dock.hide()
    with mock.patch.object(ui, "isMinimized", return_value=False):
        ui.eventFilter(ui, ev)
    assert ui.playlist_dock.isVisible()
    assert ui._panels_hidden_by_minimize == []
    ui._panels_hidden_by_minimize = ["nonexistent_dock"]
    with mock.patch.object(ui, "isMinimized", return_value=False):
        ui.eventFilter(ui, ev)


def test_double_click_lcd_toggles_visualizer(ui):
    ui.show()
    before = ui.visualizer_widget.isVisible()
    ev = QMouseEvent(
        QEvent.Type.MouseButtonDblClick, QPointF(2, 2), QPointF(2, 2),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert ui.eventFilter(ui.time_lcd, ev) is True
    assert ui.visualizer_widget.isVisible() != before


def test_palette_change_tracks_theme(ui):
    ui._track_system_theme = True
    with mock.patch.object(ui, "_apply_system_theme") as ap:
        ui.eventFilter(ui, QEvent(QEvent.Type.ApplicationPaletteChange))
    ap.assert_called_once()
    ui._track_system_theme = False
    ui.eventFilter(ui, QEvent(QEvent.Type.ApplicationPaletteChange))


def test_menu_toggles(ui):
    ui._ensure_lyrics()
    ui._menu_toggle_visualizer(False)
    assert not ui.visualizer_widget.isVisible()
    ui._menu_toggle_lyrics(True)


# --- icons / styles / icon loading --------------------------------------


def test_play_pause_icon(ui):
    ui.update_play_pause_icon()
    with mock.patch.object(
        ui.Player, "playbackState",
        return_value=QMediaPlayer.PlaybackState.PlayingState,
    ):
        ui.update_play_stop_icon()


def test_clear_inline_styles(ui):
    ui.play_btn.setStyleSheet("color: red;")
    ui._clear_inline_styles()
    assert ui.play_btn.styleSheet() == ""


def test_load_app_icon_variants(ui, tmp_path, monkeypatch):
    assert not ui._load_app_icon().isNull()
    exe_dir = tmp_path / "bundle" / "MacOS"
    exe_dir.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "luister"))
    monkeypatch.setattr(sys, "platform", "darwin")
    ui._load_app_icon()
    monkeypatch.setattr(sys, "platform", "linux")
    ui._load_app_icon()
    with mock.patch.object(Path, "exists", return_value=False):
        assert ui._load_app_icon() is not None


def test_dock_hide_on_close(ui):
    dock = QDockWidget("d", ui)
    ui._make_dock_hide_on_close(dock)
    dock.show()
    ev = mock.Mock()
    dock.closeEvent(ev)
    ev.ignore.assert_called_once()
    assert not dock.isVisible()
    bad = mock.Mock()
    bad.ignore.side_effect = RuntimeError
    bad_dock = mock.Mock()
    bad_dock.hide.side_effect = RuntimeError
    ui._make_dock_hide_on_close(bad_dock)
    bad_dock.closeEvent(bad)

    class Frozen:
        __slots__ = ()
    ui._make_dock_hide_on_close(Frozen())


# --- lyrics / visualizer / docks -----------------------------------------


def test_ensure_visualizer_noop(ui):
    ui._ensure_visualizer()


def test_ensure_lyrics_creates_once_and_toggles(ui):
    ui.show()
    ui._ensure_lyrics()
    dock = ui.lyrics_dock
    ui._ensure_lyrics()
    assert ui.lyrics_dock is dock
    ui.toggle_lyrics()
    assert dock.isVisible()
    ui.lyrics_widget.closed.emit()
    QTest.qWait(400)
    assert not dock.isVisible()
    ui.toggle_lyrics()
    ui._on_lyrics_visibility_changed(False)


def test_ensure_lyrics_init_failure(ui):
    ui.lyrics_dock = None
    with mock.patch.object(luister, "LyricsWidget", side_effect=RuntimeError("no")):
        ui._ensure_lyrics()
    assert isinstance(ui.lyrics_widget, QLabel)
    assert ui.lyrics_dock is not None


def test_ensure_lyrics_signal_connect_failures(ui):
    ui.lyrics_dock = None
    fake = mock.MagicMock(spec=luister.LyricsWidget)
    fake.closed.connect.side_effect = RuntimeError
    ui.Player = mock.Mock()
    ui.Player.positionChanged.connect.side_effect = RuntimeError
    with mock.patch.object(luister, "LyricsWidget", return_value=fake), \
            mock.patch.object(ui, "addDockWidget"), \
            mock.patch.object(luister, "QDockWidget"):
        ui._ensure_lyrics()
    ui.lyrics_dock = None


def test_lyrics_visibility_changed_runtime_error(ui):
    with mock.patch.object(ui, "set_lyrics_visible", side_effect=RuntimeError):
        ui._on_lyrics_visibility_changed(True)


def test_set_lyrics_visible_guards(ui):
    ui.lyrics_dock = None
    ui.set_lyrics_visible(True)
    ui._ensure_lyrics()
    ui._lyrics_visibility_guard = True
    ui.set_lyrics_visible(True)
    ui._lyrics_visibility_guard = False
    ui.lyrics_action = mock.Mock()
    ui.set_lyrics_visible(False)
    ui.lyrics_action.setChecked.assert_called_with(False)


def test_set_visualizer_visible_without_widget(ui):
    ui.visualizer_widget = None
    ui.visualizer_action = None
    ui.set_visualizer_visible(True)
    ui.toggle_visualizer()


def test_visualizer_toggle_updates_action(ui):
    ui.show()
    ui.visualizer_action = mock.Mock()
    ui.set_visualizer_visible(False)
    ui.visualizer_action.setChecked.assert_called_with(False)


def test_apply_dock_styles(ui):
    ui.visualizer_dock = None
    ui._ensure_lyrics()
    ui._ensure_dock_styles()


def test_fade_dock_in_out_and_none(ui):
    ui._fade_dock(None)
    dock = QDockWidget("d", ui)
    ui._fade_dock(dock, fade_in=True)
    assert dock.isVisible()
    ui._fade_dock(dock, fade_in=False)
    QTest.qWait(500)
    assert not dock.isVisible()
    QTest.qWait(400)


def test_stack_helpers(ui):
    ui.show()
    ui._stack_playlist_below()
    ui.visualizer_dock = None
    ui._stack_visualizer()
    ui.visualizer_dock = QDockWidget("v", ui)
    ui._stack_visualizer()
    ui.visualizer_dock.setFloating(True)
    ui._stack_visualizer()
    ui._stack_lyrics()
    ui._ensure_lyrics()
    ui._stack_lyrics()
    ui.lyrics_dock.setFloating(True)
    ui._stack_lyrics()


def test_stack_helpers_errors(ui):
    ui.playlist_dock = mock.Mock()
    ui.playlist_dock.show.side_effect = RuntimeError
    ui._stack_playlist_below()
    ui.visualizer_dock = mock.Mock()
    ui.visualizer_dock.isFloating.side_effect = RuntimeError
    ui._stack_visualizer()
    ui.lyrics_dock = mock.Mock()
    ui.lyrics_dock.isFloating.side_effect = RuntimeError
    ui._stack_lyrics()
    ui.lyrics_dock = None
    ui._stack_lyrics()


# --- shutdown ------------------------------------------------------------


def test_graceful_shutdown_persists_state(loaded, tmp_path):
    loaded.current_index = 1
    with mock.patch.object(QApplication, "quit") as q:
        loaded.graceful_shutdown()
    q.assert_called()
    playing = tmp_path / ".luister" / "states" / "playing.txt"
    assert playing.read_text().endswith("b.wav")
    assert (tmp_path / ".luister" / "states" / "playlistdir.txt").exists()


def test_graceful_shutdown_errors(ui):
    with mock.patch.object(ui, "_persist_gui_state", side_effect=RuntimeError), \
            mock.patch.object(luister, "get_manager", side_effect=RuntimeError), \
            mock.patch.object(QApplication, "instance", return_value=None):
        ui.graceful_shutdown()


def test_force_shutdown(ui):
    with mock.patch.object(QApplication, "exit") as ex:
        ui.force_shutdown()
    ex.assert_called_once_with(1)
    with mock.patch.object(luister, "get_manager", side_effect=RuntimeError), \
            mock.patch.object(QApplication, "instance", return_value=None):
        ui.force_shutdown()


def test_close_event(ui):
    with mock.patch.object(ui, "graceful_shutdown") as gs:
        ui.close()
    gs.assert_called_once()


def test_close_event_failure_accepts(ui):
    ev = mock.Mock()
    with mock.patch.object(ui, "graceful_shutdown", side_effect=RuntimeError):
        ui.closeEvent(ev)
    ev.accept.assert_called_once()
    ev.accept.side_effect = RuntimeError
    with mock.patch.object(ui, "graceful_shutdown", side_effect=RuntimeError):
        ui.closeEvent(ev)


# --- GUI state persistence ----------------------------------------------


def test_gui_state_roundtrip(ui, tmp_path):
    ui.show()
    ui._gui_state_frozen = False
    ui._gui_state_ready = True
    ui.set_visualizer_visible(False)
    text = ui._gui_state_path().read_text()
    assert "visualizer=0" in text and "schema=" in text
    state = ui._load_gui_state()
    assert state["visualizer"] == "0"
    assert "schema" not in state


def test_load_gui_state_variants(ui):
    assert ui._load_gui_state()["lyrics"] == "0"
    path = ui._gui_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("lyrics=1\nvisualizer=0\ngarbage\n")
    state = ui._load_gui_state()
    assert state["lyrics"] == "0" and state["visualizer"] == "0"
    path.write_bytes(b"\xff\xfe\x00")
    assert ui._load_gui_state()["visualizer"] == "1"


def test_save_gui_state_guards(ui):
    ui._gui_state_ready = False
    ui._save_gui_state()
    assert not ui._gui_state_path().exists()
    ui._gui_state_ready = True
    ui._gui_state_frozen = True
    ui._save_gui_state()
    assert not ui._gui_state_path().exists()
    del ui._gui_state_ready
    ui._save_gui_state()
    ui._gui_state_ready = True
    ui._gui_state_frozen = False
    with mock.patch.object(Path, "mkdir", side_effect=OSError):
        ui._save_gui_state()
    ui._dock_visibility_changed(True)
    with mock.patch.object(ui, "_save_gui_state", side_effect=RuntimeError):
        ui._dock_visibility_changed()


# --- tray ----------------------------------------------------------------

DBL = QSystemTrayIcon.ActivationReason.DoubleClick


def test_tray_double_click_hides_then_shows(ui):
    ui.show()
    ui._ensure_lyrics()
    ui.lyrics_dock.show()
    ui._on_tray_activated(DBL)
    assert not ui.isVisible()
    ui._on_tray_activated(DBL)
    assert ui.isVisible()
    ui._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)


def test_tray_without_playlist_dock(ui):
    ui.show()
    ui.playlist_dock = None
    ui._on_tray_activated(DBL)
    ui._on_tray_activated(DBL)
    ui._show_from_tray()


def test_tray_errors_are_swallowed(ui):
    ui.show()
    with mock.patch.object(ui, "hide", side_effect=RuntimeError):
        ui.playlist_dock = mock.Mock()
        ui.playlist_dock.hide.side_effect = RuntimeError
        ui.lyrics_dock = mock.Mock()
        ui.lyrics_dock.hide.side_effect = RuntimeError
        ui._on_tray_activated(DBL)
    ui.hide()
    with mock.patch.object(ui, "show", side_effect=RuntimeError):
        ui._on_tray_activated(DBL)
        ui._show_from_tray()
    with mock.patch.object(ui, "showNormal", side_effect=RuntimeError), \
            mock.patch.object(ui, "raise_", side_effect=RuntimeError):
        ui.playlist_dock = mock.Mock()
        ui.playlist_dock.show.side_effect = RuntimeError
        ui._on_tray_activated(DBL)
        ui._show_from_tray()
    ui.hide()
    with mock.patch.object(ui, "isVisible", side_effect=RuntimeError):
        ui._on_tray_activated(DBL)


def test_tray_toplevel_without_docks(ui):
    del ui.playlist_dock
    ui.show()
    ui._on_tray_activated(DBL)
    ui._on_tray_activated(DBL)


def test_persist_states_swallow_errors(ui):
    with mock.patch.object(Path, "mkdir", side_effect=OSError):
        ui._persist_playing_state("x")
        ui._persist_playlist_dir("x")


# --- YTDownloadThread ----------------------------------------------------


class FakeYDL:
    """Scriptable stand-in for yt_dlp.YoutubeDL."""

    info = {"title": "Vid", "id": "abc", "duration": 3,
            "webpage_url": "https://youtu.be/abc"}
    extract_error = None
    download_behaviour = None  # callable(ydl, urls)
    instances: list = []

    def __init__(self, opts):
        self.opts = opts
        FakeYDL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        if FakeYDL.extract_error:
            raise FakeYDL.extract_error
        return FakeYDL.info

    def download(self, urls):
        if FakeYDL.download_behaviour:
            FakeYDL.download_behaviour(self, urls)


@pytest.fixture
def fake_ydl(monkeypatch):
    FakeYDL.info = {"title": "Vid", "id": "abc", "duration": 3,
                    "webpage_url": "https://youtu.be/abc"}
    FakeYDL.extract_error = None
    FakeYDL.download_behaviour = None
    FakeYDL.instances = []
    mod = types.ModuleType("yt_dlp")
    mod.YoutubeDL = FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", mod)
    monkeypatch.setattr(luister.YTDownloadThread, "_find_ffmpeg",
                        lambda self: "/fake/bin/ffmpeg")
    return FakeYDL


def _thread(tmp_path):
    t = luister.YTDownloadThread("https://youtu.be/abc", tmp_path / "out")
    got = {"meta": [], "done": [], "err": [], "batch": [], "prog": []}
    t.metadata_ready.connect(got["meta"].append)
    t.item_complete.connect(lambda i, p: got["done"].append((i, p)))
    t.item_error.connect(lambda i, m: got["err"].append((i, m)))
    t.batch_finished.connect(got["batch"].append)
    t.item_progress.connect(lambda i, p: got["prog"].append((i, p)))
    return t, got


def test_progress_hook_paths(app, tmp_path):
    t, got = _thread(tmp_path)
    t._progress_hook({"status": "downloading", "total_bytes": 200,
                      "downloaded_bytes": 100})
    t._progress_hook({"status": "downloading", "total_bytes": 200,
                      "downloaded_bytes": 100})
    t._progress_hook({"status": "downloading"})
    t._progress_hook({"status": "finished", "filename": "f.webm"})
    t._progress_hook({"status": "finished"})
    assert got["prog"][0] == (0, 50) and got["prog"][-1] == (0, 100)
    assert t._final_path == "f.webm"
    t.cancel()
    with pytest.raises(RuntimeError):
        t._progress_hook({"status": "downloading"})


def test_postprocessor_hook(app, tmp_path):
    t, _ = _thread(tmp_path)
    t._postprocessor_hook({"status": "started"})
    assert t._final_path is None
    t._postprocessor_hook({"status": "finished", "info_dict": {}})
    assert t._final_path is None
    t._postprocessor_hook({"status": "finished",
                           "info_dict": {"_filename": "x.mp3"}})
    assert t._final_path == "x.mp3"


def test_find_ffmpeg_branches(app, tmp_path, monkeypatch):
    t, _ = _thread(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    for plat in ("darwin", "linux"):
        monkeypatch.setattr(sys, "platform", plat)
        exe = tmp_path / plat / "MacOS"
        exe.mkdir(parents=True)
        monkeypatch.setattr(sys, "executable", str(exe / "luister"))
        (exe / "ffmpeg").write_text("x")
        assert t._find_ffmpeg() == str(exe / "ffmpeg")
        (exe / "ffmpeg").unlink()
        with mock.patch("shutil.which", return_value="/p/ffmpeg"):
            assert t._find_ffmpeg() == "/p/ffmpeg"
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    with mock.patch("shutil.which", return_value=None):
        with mock.patch.object(Path, "exists", return_value=True):
            assert t._find_ffmpeg() == "/opt/homebrew/bin/ffmpeg"
        with mock.patch.object(Path, "exists", return_value=False):
            assert t._find_ffmpeg() is None


def test_base_opts(app, tmp_path):
    t, _ = _thread(tmp_path)
    assert "ffmpeg_location" not in t._base_opts(None)
    assert t._base_opts("/a/b/ffmpeg")["ffmpeg_location"] == "/a/b"


def test_run_single_video_success(app, tmp_path, fake_ydl):
    out = tmp_path / "out"

    def behave(ydl, urls):
        out.mkdir(parents=True, exist_ok=True)
        (out / "Vid.mp3").write_text("x")
        ydl.opts["progress_hooks"][0]({"status": "finished",
                                       "filename": str(out / "Vid.webm")})
    fake_ydl.download_behaviour = behave
    t, got = _thread(tmp_path)
    t.run()
    assert got["meta"][0][0]["title"] == "Vid"
    assert got["done"] == [(0, str(out / "Vid.mp3"))]
    assert got["batch"] == [[str(out / "Vid.mp3")]]


def test_run_playlist_hook_path_and_fallback_client(app, tmp_path, fake_ydl):
    out = tmp_path / "out"
    fake_ydl.info = {"entries": [
        None,
        {"title": "A", "id": "1", "url": "https://youtu.be/1"},
        {"title": "!!!", "id": "2"},
    ]}
    calls = []

    def behave(ydl, urls):
        calls.append(urls[0])
        if len(calls) == 1:
            raise RuntimeError("HTTP Error 403: Forbidden")
        out.mkdir(parents=True, exist_ok=True)
        real = out / f"f{len(calls)}.mp3"
        real.write_text("x")
        ydl.opts["postprocessor_hooks"][0](
            {"status": "finished", "info_dict": {"filepath": str(real)}})
    fake_ydl.download_behaviour = behave
    t, got = _thread(tmp_path)
    t.run()
    assert len(got["done"]) == 2
    assert calls[-1].endswith("watch?v=2")
    assert any("player_client" in str(i.opts.get("extractor_args"))
               for i in fake_ydl.instances)


def test_run_all_clients_fail_403(app, tmp_path, fake_ydl):
    def behave(ydl, urls):
        raise RuntimeError("HTTP Error 403: Forbidden")
    fake_ydl.download_behaviour = behave
    t, got = _thread(tmp_path)
    t.run()
    assert "403" in got["err"][0][1]
    assert got["batch"] == [[]]


def test_run_no_output_file(app, tmp_path, fake_ydl):
    t, got = _thread(tmp_path)
    t.run()
    assert "no output file" in got["err"][0][1]


def test_download_one_no_clients_returns_none(app, tmp_path, fake_ydl):
    t, _ = _thread(tmp_path)
    t.PLAYER_CLIENTS = ()
    assert t._download_one({"title": "x", "id": "1"}, 0, None) is None


def test_run_item_with_no_file_reports_error(app, tmp_path, fake_ydl):
    t, got = _thread(tmp_path)
    t._output_dir.mkdir(parents=True)
    with mock.patch.object(t, "_download_one", return_value=None):
        t.run()
    assert got["err"] == [(0, "No output file created")]


def test_run_cancelled_midway(app, tmp_path, fake_ydl):
    t, got = _thread(tmp_path)

    def cancel_during(ydl, urls):
        t.cancel()
        raise RuntimeError("cancelled")
    fake_ydl.download_behaviour = cancel_during
    t.run()
    assert got["err"] == [] and got["batch"] == [[]]


def test_run_cancelled_before_item_and_client(app, tmp_path, fake_ydl):
    t, got = _thread(tmp_path)
    t.cancel()
    t.run()
    assert got["batch"] == [[]]
    assert t._download_one({"title": "x", "id": "1"}, 0, None) is None
    with mock.patch.object(t, "_download_one", return_value=None):
        t._cancelled = False
        t.run()


def test_run_cancel_returns_none_in_loop(app, tmp_path, fake_ydl):
    t, got = _thread(tmp_path)

    def side(item, idx, ff):
        t._cancelled = True
        return None
    with mock.patch.object(t, "_download_one", side_effect=side):
        t.run()
    assert got["err"] == []


def test_run_metadata_failures(app, tmp_path, fake_ydl):
    fake_ydl.extract_error = RuntimeError("nope")
    t, got = _thread(tmp_path)
    t.run()
    assert got["batch"] == [[]]
    fake_ydl.extract_error = None
    fake_ydl.info = None
    t, got = _thread(tmp_path)
    t.run()
    assert got["batch"] == [[]]


def test_run_without_ffmpeg_and_empty_playlist(app, tmp_path, fake_ydl, monkeypatch):
    monkeypatch.setattr(luister.YTDownloadThread, "_find_ffmpeg",
                        lambda self: None)
    fake_ydl.info = {"entries": []}
    t, got = _thread(tmp_path)
    t.run()
    assert got["meta"] == [] and got["batch"] == [[]]


def test_run_missing_yt_dlp(app, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yt_dlp", None)
    t, got = _thread(tmp_path)
    t.run()
    assert got["batch"] == [[]]


def test_run_unexpected_error(app, tmp_path, fake_ydl):
    t, got = _thread(tmp_path)
    with mock.patch.object(Path, "mkdir", side_effect=OSError("ro")):
        t.run()
    assert got["batch"] == [[]]


def test_thread_start_end_to_end(app, tmp_path, fake_ydl):
    t, got = _thread(tmp_path)
    t.start()
    assert t.wait(5000)
    QTest.qWait(50)
    assert got["batch"]


# --- main() --------------------------------------------------------------


def test_main_runs_event_loop_and_registers_signals(app, tmp_path, monkeypatch):
    monkeypatch.setattr(luister.Path, "home", staticmethod(lambda: tmp_path))
    fake_app = mock.Mock()
    window = mock.Mock()
    handlers = {}
    monkeypatch.setattr(luister, "QApplication", mock.Mock(return_value=fake_app))
    monkeypatch.setattr(luister, "UI", mock.Mock(return_value=window))
    monkeypatch.setattr(signal, "signal",
                        lambda sig, h: handlers.__setitem__(sig, h))
    luister.main()
    fake_app.exec.assert_called_once()
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    window.graceful_shutdown.assert_called_once()
    window.graceful_shutdown.side_effect = RuntimeError
    handlers[signal.SIGINT](signal.SIGINT, None)


def test_main_signal_registration_failures_and_keyboard_interrupt(app, monkeypatch):
    fake_app = mock.Mock()
    fake_app.exec.side_effect = KeyboardInterrupt
    window = mock.Mock()
    monkeypatch.setattr(luister, "QApplication", mock.Mock(return_value=fake_app))
    monkeypatch.setattr(luister, "UI", mock.Mock(return_value=window))
    monkeypatch.setattr(signal, "signal", mock.Mock(side_effect=ValueError))
    luister.main()
    window.graceful_shutdown.assert_called_once()
    window.graceful_shutdown.side_effect = RuntimeError
    luister.main()


def test_dunder_main_invokes_main(app, tmp_path, monkeypatch):
    monkeypatch.setattr(luister.Path, "home", staticmethod(lambda: tmp_path))
    fake_app = mock.Mock()
    fake_app.instance.return_value = app
    monkeypatch.setattr(signal, "signal", lambda *a: None)
    monkeypatch.setattr("PyQt6.QtWidgets.QApplication",
                        mock.Mock(return_value=fake_app))
    source = Path(luister.__file__).read_text(encoding="utf-8")
    code = compile(source, luister.__file__, "exec")
    scope = {"__name__": "__main__", "__package__": "luister",
             "__file__": luister.__file__}
    exec(code, scope)
    fake_app.exec.assert_called_once()
