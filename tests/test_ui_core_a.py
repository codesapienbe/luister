"""E2E-style tests for the module header and the first half of luister.UI."""

import json
import os
import struct
import wave

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QKeyEvent, QWheelEvent
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtTest import QTest
from PyQt6.QtMultimedia import QAudio
from PyQt6.QtWidgets import QApplication, QDockWidget, QFileDialog, QInputDialog, QLabel

import luister
from luister.views import PlaylistUI


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    yield QApplication.instance() or QApplication([])


def make_wav(path, ms=300):
    rate = 8000
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * (rate * ms // 1000))
    return str(path)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(luister.Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


@pytest.fixture
def make_ui(app, home):
    created = []

    def factory():
        w = luister.UI()
        created.append(w)
        w.visualizer_widget.set_audio = lambda *_a, **_k: None
        return w

    yield factory
    for w in created:
        w._gui_state_ready = False
        w._gui_state_frozen = True
        if hasattr(w.Player, "stop"):
            w.Player.stop()


@pytest.fixture
def ui(make_ui):
    return make_ui()


@pytest.fixture
def tracks(tmp_path):
    d = tmp_path / "music"
    d.mkdir()
    return [make_wav(d / f"t{i}.wav") for i in range(3)]


def load(ui, tracks, play=True):
    ui._add_files(tracks, replace=True, play_on_load=play)


# --- url ---------------------------------------------------------------


def test_url_helper():
    assert luister._is_supported_media_url(" https://youtu.be/abc ")
    assert not luister._is_supported_media_url(None)
    assert not luister._is_supported_media_url("https://vimeo.com/x")


# --- startup -----------------------------------------------------------


def test_startup_defaults(ui):
    assert ui.time_lcd.toPlainText().startswith("Luister")
    assert not ui.play_btn.isEnabled()
    assert ui.volume_slider.value() == 50


def test_startup_loads_downloads_dir(app, home):
    d = home / ".luister" / "downloads"
    d.mkdir(parents=True)
    make_wav(d / "a.wav")
    (d / "note.txt").write_text("x")
    w = luister.UI()
    try:
        assert len(w.playlist_urls) == 1
    finally:
        w._gui_state_frozen = True


def test_startup_restores_config(app, home, tracks):
    cfg = home / ".luister"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text(
        json.dumps({"volume": 80, "last_playlist": tracks, "last_index": 1})
    )
    w = luister.UI()
    try:
        assert w.volume_slider.value() == 80
        assert w.current_index == 1
        assert w.ui.list_songs.currentRow() == 1
        assert w.play_btn.isEnabled()
    finally:
        w._gui_state_frozen = True


def test_startup_restore_without_dock_and_bad_index(app, home, tracks, monkeypatch):
    cfg = home / ".luister"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text(
        json.dumps({"volume": "bogus", "last_playlist": tracks, "last_index": 9})
    )
    w = luister.UI()
    try:
        assert w.volume_slider.value() == 50
        assert w.current_index == -1
    finally:
        w._gui_state_frozen = True


def test_startup_restore_ui_show_fallbacks(app, home, tracks, monkeypatch):
    cfg = home / ".luister"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text(
        json.dumps({"last_playlist": tracks, "last_index": 0})
    )

    calls = []

    def boom(self):
        calls.append(1)
        raise RuntimeError("x")

    monkeypatch.setattr(luister.UI, "_stack_playlist_below", boom)
    w = luister.UI()
    try:
        assert len(calls) >= 2
    finally:
        w._gui_state_frozen = True


# --- startup fault injection -----------------------------------------------


def _boom(*_a, **_k):
    raise RuntimeError("boom")


class SigProxy:
    """Wraps a bound signal; connect() fails for the named slots."""

    def __init__(self, real, fail_names=None):
        self._real = real
        self._fail = fail_names

    def connect(self, slot, *a):
        if self._fail is None or getattr(slot, "__name__", "") in self._fail:
            raise RuntimeError("cannot connect")
        return self._real.connect(slot, *a)

    def __getattr__(self, name):
        return getattr(self._real, name)


class FaultyPlayer(QMediaPlayer):
    @property
    def errorOccurred(self):
        return SigProxy(QMediaPlayer.errorOccurred.__get__(self, type(self)))

    @property
    def positionChanged(self):
        return SigProxy(
            QMediaPlayer.positionChanged.__get__(self, type(self)),
            {"update_position"},
        )


def build(app_):
    w = luister.UI()
    w._gui_state_frozen = True
    return w


@pytest.fixture
def raw_ui(app, home):
    built = []

    def factory():
        w = luister.UI()
        built.append(w)
        return w

    yield factory
    for w in built:
        w._gui_state_ready = False
        w._gui_state_frozen = True


def test_startup_survives_player_signal_failures(raw_ui, monkeypatch):
    monkeypatch.setattr(luister, "QMediaPlayer", FaultyPlayer)
    w = raw_ui()
    assert w.play_btn is not None


def test_startup_survives_window_icon_and_theme_failures(raw_ui, monkeypatch):
    monkeypatch.setattr(luister.UI, "setWindowIcon", _boom)
    real_exists = luister.Path.exists
    monkeypatch.setattr(
        luister.Path, "exists",
        lambda self: self.name == "icon.png" or real_exists(self),
    )
    real = luister.UI._apply_system_theme
    state = {"n": 0}

    def flaky(self):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("theme")
        return real(self)

    monkeypatch.setattr(luister.UI, "_apply_system_theme", flaky)
    w = raw_ui()
    assert state["n"] >= 2 and w.isVisible()


def test_startup_dock_helper_failures(raw_ui, monkeypatch):
    monkeypatch.setattr(luister.UI, "_make_dock_hide_on_close", _boom)
    monkeypatch.setattr(luister.UI, "resizeDocks", _boom)
    monkeypatch.setattr(luister.PlaylistUI, "setMinimumWidth", _boom)
    w = raw_ui()
    assert w.playlist_dock is not None


def test_startup_gui_state_failure(raw_ui, monkeypatch):
    class Bad:
        def get(self, *_a):
            raise RuntimeError

    monkeypatch.setattr(luister.UI, "_load_gui_state", lambda self: Bad())
    assert raw_ui().ui is not None


def test_startup_ensure_playlist_first_call_noop(raw_ui, monkeypatch):
    real = luister.UI._ensure_playlist
    n = {"n": 0}

    def lazy(self):
        n["n"] += 1
        if n["n"] > 1:
            real(self)

    monkeypatch.setattr(luister.UI, "_ensure_playlist", lazy)
    # self.ui is missing during the first dock setup; construction still works
    # only if the later code tolerates it.
    try:
        raw_ui()
    except AttributeError:
        pass
    assert n["n"] >= 2


class FaultyDock(QDockWidget):
    @property
    def visibilityChanged(self):
        return SigProxy(
            QDockWidget.visibilityChanged.__get__(self, type(self)),
            {"_dock_visibility_changed"},
        )

    def setMinimumWidth(self, _w):
        raise RuntimeError("no")


def _dock_factory(monkeypatch, playlist_dock):
    real = QDockWidget

    def factory(title, parent=None):
        if title == "Playlist":
            return playlist_dock(title, parent) if playlist_dock else None
        return real(title, parent)

    factory.DockWidgetFeature = real.DockWidgetFeature
    monkeypatch.setattr(luister, "QDockWidget", factory)


def test_startup_playlist_dock_faults(raw_ui, monkeypatch):
    _dock_factory(monkeypatch, FaultyDock)
    assert raw_ui().playlist_dock is not None


def test_startup_playlist_dock_creation_fails(app, home, tracks, monkeypatch):
    (home / ".luister").mkdir(parents=True)
    (home / ".luister" / "config.json").write_text(
        json.dumps({"last_playlist": tracks, "last_index": 0})
    )
    _dock_factory(monkeypatch, None)
    w = luister.UI()
    try:
        assert w.playlist_dock is None
        assert w.current_index == 0
    finally:
        w._gui_state_frozen = True


def test_startup_playlist_dock_none_and_stack_fails(app, home, tracks, monkeypatch):
    (home / ".luister").mkdir(parents=True)
    (home / ".luister" / "config.json").write_text(
        json.dumps({"last_playlist": tracks, "last_index": 0})
    )
    _dock_factory(monkeypatch, None)
    monkeypatch.setattr(luister.UI, "_stack_playlist_below", _boom)
    w = luister.UI()
    try:
        assert w.current_index == 0
    finally:
        w._gui_state_frozen = True


def test_startup_add_dock_failure(raw_ui, monkeypatch):
    real = luister.UI.addDockWidget

    def add(self, area, dock):
        if dock.windowTitle() == "Playlist":
            raise RuntimeError
        return real(self, area, dock)

    monkeypatch.setattr(luister.UI, "addDockWidget", add)
    assert raw_ui() is not None


class BadClosedLyrics(luister.LyricsWidget):
    @property
    def closed(self):
        return SigProxy(luister.LyricsWidget.closed.__get__(self, type(self)))


def test_startup_lyrics_closed_connect_failure(raw_ui, monkeypatch):
    monkeypatch.setattr(luister, "LyricsWidget", BadClosedLyrics)
    assert isinstance(raw_ui().lyrics_widget, BadClosedLyrics)


def test_startup_lyrics_init_failure(raw_ui, monkeypatch):
    def broken():
        raise RuntimeError("no lyrics")

    monkeypatch.setattr(luister, "LyricsWidget", broken)
    w = raw_ui()
    assert isinstance(w.lyrics_widget, QLabel)
    assert "no lyrics" in w.lyrics_widget.text()


def test_startup_shortcut_failure(raw_ui, monkeypatch):
    monkeypatch.setattr(luister, "QShortcut", _boom)
    assert raw_ui()._shortcuts == []


def test_visualizer_analysis_status(ui):
    ui.visualizer_widget.analysis_started.emit()
    assert "Analysing" in ui.time_lcd.toPlainText()
    ui.visualizer_widget.analysis_ready.emit(True)
    assert "Visualizer ready" in ui.time_lcd.toPlainText()
    ui.visualizer_widget.analysis_ready.emit(False)
    assert "failed" in ui.time_lcd.toPlainText()


def test_media_devices_without_default_signal(raw_ui, monkeypatch):
    class Sig:
        def __init__(self):
            self.cb = None

        def connect(self, cb):
            self.cb = cb

    class Devices:
        audioOutputsChanged = Sig()

        def defaultAudioOutput(self):
            return "dev"

    monkeypatch.setattr(luister, "QMediaDevices", Devices)
    seen = []
    monkeypatch.setattr(luister.UI, "_audio_device_changed", lambda self, d: seen.append(d))
    raw_ui()
    Devices.audioOutputsChanged.cb()
    assert seen == ["dev"]


def test_media_devices_with_default_signal(raw_ui, monkeypatch):
    class Sig:
        def connect(self, cb):
            self.cb = cb

    sig = Sig()

    class Devices:
        defaultAudioOutputChanged = sig

    monkeypatch.setattr(luister, "QMediaDevices", Devices)
    raw_ui()
    assert sig.cb is not None


# --- runtime behaviour -----------------------------------------------------


class FakePlayer:
    PS = QMediaPlayer.PlaybackState

    def __init__(self):
        self.state = self.PS.StoppedState
        self.pos = 0
        self.dur = 0
        self.source = None
        self.calls = []

    def playbackState(self):
        return self.state

    def play(self):
        self.calls.append("play")
        self.state = self.PS.PlayingState

    def pause(self):
        self.calls.append("pause")
        self.state = self.PS.PausedState

    def stop(self):
        self.calls.append("stop")
        self.state = self.PS.StoppedState

    def setSource(self, url):
        self.source = url

    def setPosition(self, p):
        self.pos = p

    def position(self):
        return self.pos

    def duration(self):
        return self.dur

    def setLoops(self, n):
        pass

    def errorString(self):
        return ""


@pytest.fixture
def fp(ui):
    ui.Player = FakePlayer()
    return ui.Player


def test_shortcuts_drive_playback(ui, fp, tracks):
    load(ui, tracks)
    assert fp.state == FakePlayer.PS.PlayingState
    QTest.keyClick(ui, Qt.Key.Key_Space)
    for sc in ui._shortcuts:
        if sc.key().toString() in ("Space",):
            sc.activated.emit()
    assert fp.calls.count("pause") >= 1


def test_shortcut_handlers(ui, fp, tracks):
    load(ui, tracks)
    keys = {sc.key().toString(): sc for sc in ui._shortcuts}
    keys["Right"].activated.emit()
    assert ui.current_index == 1
    keys["Left"].activated.emit()
    assert ui.current_index == 0
    v = ui.volume_slider.value()
    keys["Up"].activated.emit()
    assert ui.volume_slider.value() == v + 5
    keys["Down"].activated.emit()
    assert ui.volume_slider.value() == v
    fp.dur = 60000
    fp.pos = 10000
    keys["Shift+Right"].activated.emit()
    assert fp.pos == 15000
    keys["Shift+Left"].activated.emit()
    assert fp.pos == 10000


def test_seek_relative_clamps(ui, fp):
    fp.dur = 1000
    fp.pos = 900
    ui.seek_relative(5000)
    assert fp.pos == 1000
    ui.seek_relative(-5000)
    assert fp.pos == 0
    fp.dur = 0
    ui.seek_relative(7)
    assert fp.pos == 7


def test_seek_relative_failure_is_swallowed(ui):
    ui.Player = object()
    ui.seek_relative(10)


def test_wheel_event(ui):
    def ev(cls, dy):
        return cls(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy),
                   Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                   Qt.ScrollPhase.NoScrollPhase, False)

    ui.volume_slider.setValue(50)
    ui.wheelEvent(ev(QWheelEvent, 120))
    assert ui.volume_slider.value() == 55
    ui.wheelEvent(ev(QWheelEvent, -120))
    assert ui.volume_slider.value() == 50
    ui.wheelEvent(ev(QWheelEvent, 0))
    assert ui.volume_slider.value() == 50

    class Bad(QWheelEvent):
        def angleDelta(self):
            raise RuntimeError

    ui.wheelEvent(ev(Bad, 120))
    assert ui.volume_slider.value() == 50


def test_play_button_enabled_by_playlist(ui, fp, tracks):
    assert not ui.play_btn.isEnabled()
    load(ui, tracks)
    assert ui.play_btn.isEnabled()
    ui.play_btn = None
    ui.set_Enabled_button()


def test_seek_slider_interaction(ui, fp):
    ui.duration_changed(60000)
    ui._on_seek_start()
    assert ui._user_seeking
    ui._on_seek_preview(61000)
    assert ui.elapsed_label.text() == "01:01"
    ui.time_slider.setValue(30000)
    ui._on_seek_end()
    assert not ui._user_seeking and fp.pos == 30000


def test_back_and_next_navigation(ui, fp, tracks):
    ui.back()
    ui.next()
    assert ui.current_index == -1
    load(ui, tracks)
    ui.back()
    assert ui.current_index == 0
    QTest.mouseClick(ui.next_btn, Qt.MouseButton.LeftButton)
    QTest.mouseClick(ui.next_btn, Qt.MouseButton.LeftButton)
    assert ui.current_index == 2
    ui.next()
    assert ui.current_index == 2
    ui.loop_plaing = True
    ui.next()
    assert ui.current_index == 0
    ui.back()
    assert ui.current_index == 2
    ui.loop_plaing = False
    QTest.mouseClick(ui.back_btn, Qt.MouseButton.LeftButton)
    assert ui.current_index == 1


def test_play_pause_toggle_states(ui, fp, tracks):
    ui.play_pause_toggle()
    assert fp.calls == ["play"]
    fp.calls.clear()
    fp.state = FakePlayer.PS.StoppedState
    load(ui, tracks)
    fp.calls.clear()
    QTest.mouseClick(ui.play_btn, Qt.MouseButton.LeftButton)
    assert fp.calls == ["pause"]
    ui.play_stop_toggle()
    assert fp.calls == ["pause", "play"]
    fp.state = FakePlayer.PS.StoppedState
    ui.play_pause_toggle()
    assert fp.source == ui.playlist_urls[0]


def test_play_pause_stop_helpers(ui, fp):
    ui.play()
    assert fp.state == FakePlayer.PS.PlayingState
    ui.pause()
    assert fp.state == FakePlayer.PS.PausedState
    ui.pause()
    assert fp.state == FakePlayer.PS.PlayingState
    ui.stop()
    assert fp.state == FakePlayer.PS.StoppedState
    ui.stop()


def test_open_files_dialog(ui, fp, tracks, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: (tracks, ""))
    ui.open_btn.menu().actions()[0].trigger()
    assert len(ui.playlist_urls) == 3
    assert ui.playlist_dock.isVisible()


def test_open_files_variants(ui, fp, tracks, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: ([], ""))
    ui.download()
    assert "No audio files selected" in ui.time_lcd.toPlainText()

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: (tracks, ""))
    monkeypatch.setattr(ui, "_persist_playlist_dir", _boom)
    ui.playlist_dock = None
    ui.ui.hide()
    ui.download()
    assert ui.ui.isVisible()
    assert len(ui.playlist_urls) == 3

    class BadDock:
        def show(self):
            raise RuntimeError

    ui.playlist_dock = BadDock()
    ui.download()
    assert len(ui.playlist_urls) == 3

    def raising(*a, **k):
        raise RuntimeError("dialog")

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", raising)
    ui.download()
    assert "Error: dialog" in ui.time_lcd.toPlainText()


class FakeSig:
    def __init__(self):
        self.slots = []

    def connect(self, s):
        self.slots.append(s)

    def emit(self, *a):
        for s in self.slots:
            s(*a)


class FakeThread:
    instances = []

    def __init__(self, url, out):
        self.url, self.out = url, out
        self.metadata_ready = FakeSig()
        self.item_progress = FakeSig()
        self.item_complete = FakeSig()
        self.item_error = FakeSig()
        self.batch_finished = FakeSig()
        self.started = False
        FakeThread.instances.append(self)

    def start(self):
        self.started = True


@pytest.fixture
def yt(ui, fp, monkeypatch):
    FakeThread.instances.clear()
    monkeypatch.setattr(luister, "YTDownloadThread", FakeThread)
    return ui


def test_youtube_prompt_rejections(yt, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
    yt._on_youtube_click()
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("  ", True))
    yt._on_youtube_click()
    assert not FakeThread.instances
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("http://x.com/a", True))
    yt._on_youtube_click()
    assert "Invalid YouTube URL" in yt.time_lcd.toPlainText()
    assert not FakeThread.instances


def test_youtube_prompt_thread_failure(yt, monkeypatch):
    monkeypatch.setattr(
        QInputDialog, "getText",
        lambda *a, **k: ("https://youtu.be/abc", True),
    )
    monkeypatch.setattr(luister, "YTDownloadThread", _boom)
    yt._on_youtube_click()
    assert "Error starting YouTube download" in yt.time_lcd.toPlainText()


def test_youtube_full_flow(yt, tracks, monkeypatch):
    load(yt, tracks[:1])
    monkeypatch.setattr(
        QInputDialog, "getText",
        lambda *a, **k: ("https://youtu.be/abc", True),
    )
    yt.open_btn.menu().actions()[1].trigger()
    th = FakeThread.instances[-1]
    assert th.started and yt._yt_base_index == 1

    th.metadata_ready.emit([{"title": "One"}, {"title": "Two"}, {}])
    assert len(yt.playlist_urls) == 4
    assert yt.ui.list_songs.count() == 4

    th.item_progress.emit(0, 50)
    assert "Downloading (1/3): 50%" in yt.time_lcd.toPlainText()
    yt._yt_items_metadata = []
    th.item_progress.emit(0, 50)
    yt._yt_items_metadata = [{"title": "x"}]
    th.item_progress.emit(5, 10)
    yt._yt_items_metadata = [{"title": "One"}, {"title": "Two"}, {}]

    th.item_complete.emit(1, tracks[1])
    assert not yt._yt_playback_started
    th.item_complete.emit(0, tracks[2])
    assert yt._yt_playback_started and yt.current_index == 1
    assert yt.playlist_urls[1].toLocalFile() == tracks[2]
    th.item_complete.emit(40, tracks[2])

    th.item_error.emit(2, "bad")
    th.batch_finished.emit([tracks[1], tracks[2]])
    assert "Downloaded 2 file(s)" in yt.time_lcd.toPlainText()
    assert len(yt.playlist_urls) == 3
    assert yt.ui.list_songs.count() == 3


def test_youtube_finish_variants(yt, tracks):
    yt._yt_items_metadata = [{"title": "x"}]
    yt._on_ytdl_finished([])
    assert "Downloads failed" in yt.time_lcd.toPlainText()
    yt._yt_items_metadata = []
    yt._on_ytdl_finished([])
    assert "No items to download" in yt.time_lcd.toPlainText()
    del yt._yt_items_metadata
    yt._on_ytdl_finished([])
    assert "No items" in yt.time_lcd.toPlainText()


def test_youtube_handlers_with_non_playlist_ui(yt, tracks):
    yt.ui = QLabel("x")
    yt._yt_base_index = 0
    yt._yt_playback_started = False
    yt._on_ytdl_metadata([{"title": "a"}])
    yt._on_ytdl_item_progress(0, 10)
    yt._on_ytdl_item_complete(0, tracks[0])
    yt._on_ytdl_item_error(0, "e")
    yt._on_ytdl_finished([tracks[0]])
    assert yt.playlist_urls[0].toLocalFile() == tracks[0]


def test_youtube_item_complete_list_shorter_than_urls(yt, tracks):
    yt._yt_base_index = 0
    yt._yt_playback_started = True
    yt.playlist_urls = [QUrl("pending://0")]
    yt._on_ytdl_item_complete(0, tracks[0])
    assert yt.playlist_urls[0].isLocalFile()


# --- volume ----------------------------------------------------------------


def test_volume_glyphs_and_mute_button(ui):
    for v, glyph in [(0, "\U0001F507"), (20, "\U0001F508"),
                     (50, "\U0001F509"), (90, "\U0001F50A")]:
        ui.volume_slider.setValue(v)
        assert ui.mute_btn.text() == glyph
    ui.volume_slider.setValue(0)
    assert ui.mute_btn.isChecked()


def test_set_volume_fallbacks(ui, monkeypatch):
    class FakeQAudio:
        VolumeScale = QAudio.VolumeScale
        convertVolume = staticmethod(_boom)

    monkeypatch.setattr(luister, "QAudio", FakeQAudio)
    ui.set_volume(40)
    assert ui.audio_output.volume() == pytest.approx(0.4, abs=0.01)

    class BadOut:
        setVolume = staticmethod(_boom)

    ui.audio_output = BadOut()
    ui.set_volume(30)
    assert ui.volume_slider.toolTip() == "Volume: 30%"


def test_sync_mute_button_without_button(ui):
    ui.mute_btn = None
    ui.set_volume(10)
    assert ui.volume_slider.toolTip() == "Volume: 10%"


def test_startup_fails_loudly_when_transport_button_missing(app, home, monkeypatch):
    real = luister.UI.findChild

    def find(self, cls, name=""):
        return None if name == "next_btn" else real(self, cls, name)

    monkeypatch.setattr(luister.UI, "findChild", find)
    with pytest.raises(AttributeError):
        luister.UI()
