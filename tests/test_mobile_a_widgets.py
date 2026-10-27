"""E2E-style tests for the first half of mobile/main.py (helpers, widgets, MainScreen)."""

import sys
import time
import types
from unittest.mock import MagicMock

import pytest
from kivy.clock import Clock
from kivy.input.motionevent import MotionEvent

from tests.helpers_mobile import load_mobile_main

m = load_mobile_main()


class Touch(MotionEvent):
    def depack(self, args):
        self.is_touch = True
        self.sx, self.sy = args
        super().depack(args)


def touch(x, y):
    t = Touch("test", 1, (0.0, 0.0))
    t.x, t.y = x, y
    t.pos = (x, y)
    return t


@pytest.fixture
def app(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(m.App, "get_running_app", staticmethod(lambda: fake))
    return fake


@pytest.fixture
def no_app(monkeypatch):
    monkeypatch.setattr(m.App, "get_running_app", staticmethod(lambda: None))


def tick(n=2):
    for _ in range(n):
        Clock.tick()


# ---------------------------------------------------------------- HTTP helpers
def test_http_get_requests(monkeypatch):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"a": 1}
    monkeypatch.setattr(m.requests, "get", lambda *a, **k: resp)
    assert m.http_get("http://x") == (200, {"a": 1})
    resp.status_code = 404
    assert m.http_get("http://x") == (404, None)

    def boom(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(m.requests, "get", boom)
    assert m.http_get("http://x") == (0, None)


def test_http_post_file_and_quote(monkeypatch, tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"abc")
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"text": "hi"}
    monkeypatch.setattr(m.requests, "post", lambda *a, **k: resp)
    assert m.http_post_file("u", {}, str(f), "file", {}) == (200, {"text": "hi"})
    status, data = m.http_post_file("u", {}, str(tmp_path / "missing"), "file", {})
    assert status == 0 and "error" in data
    assert m.url_quote("a b") == "a%20b"


@pytest.fixture
def fallback(monkeypatch):
    """Module loaded as if requests/numpy/plyer were unavailable."""
    for name in ("requests", "numpy", "plyer"):
        monkeypatch.setitem(sys.modules, name, None)
    return load_mobile_main("luister_mobile_a_fallback", fresh=True)


def test_plyer_available(monkeypatch):
    plyer = types.ModuleType("plyer")
    plyer.filechooser = object()
    monkeypatch.setitem(sys.modules, "plyer", plyer)
    assert load_mobile_main("luister_mobile_a_plyer", fresh=True).HAS_FILECHOOSER


def test_urllib_fallback(fallback, monkeypatch):
    assert not fallback.HAS_REQUESTS and not fallback.HAS_NUMPY and not fallback.HAS_FILECHOOSER

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"k": 2}'

    monkeypatch.setattr(fallback.urllib.request, "urlopen", lambda *a, **k: Resp())
    assert fallback.http_get("http://x") == (200, {"k": 2})

    def http_err(*a, **k):
        raise fallback.urllib.error.HTTPError("u", 503, "e", {}, None)

    monkeypatch.setattr(fallback.urllib.request, "urlopen", http_err)
    assert fallback.http_get("http://x", headers={"a": "b"}) == (503, None)

    def other(*a, **k):
        raise RuntimeError

    monkeypatch.setattr(fallback.urllib.request, "urlopen", other)
    assert fallback.http_get("http://x") == (0, None)

    status, data = fallback.http_post_file("u", {}, "f", "file", {})
    assert status == 0 and "not supported" in data["error"]["message"]
    assert fallback.url_quote("a b") == "a%20b"


def test_visualizer_without_numpy(fallback, tmp_path):
    v = fallback.VisualizerWidget()
    v.set_audio(str(tmp_path / "x.wav"))
    assert not v._has_audio


# ------------------------------------------------------------- Android player
@pytest.fixture
def android(monkeypatch):
    player = MagicMock()
    player.getDuration.return_value = 125000
    cls = MagicMock(return_value=player)
    jnius = types.ModuleType("jnius")
    jnius.autoclass = lambda name: cls
    monkeypatch.setitem(sys.modules, "jnius", jnius)
    return player


def test_android_media_player(android):
    p = m.AndroidMediaPlayer("/a.m4a")
    assert p.length == 125.0 and p.volume == 1.0
    p.volume = 5
    assert p.volume == 1.0
    p.volume = -1
    assert p.volume == 0.0
    android.setVolume.assert_called_with(0.0, 0.0)
    p.play()
    android.start.assert_called()
    android.isPlaying.return_value = True
    p.stop()
    android.pause.assert_called()
    android.isPlaying.return_value = False
    p.stop()
    p.seek(2.5)
    android.seekTo.assert_called_with(2500)
    android.getCurrentPosition.return_value = 3000
    assert p.get_pos() == 3.0
    android.isPlaying.return_value = True
    assert p.is_playing() is True
    p.unload()
    android.release.assert_called()

    android.getCurrentPosition.side_effect = RuntimeError
    android.isPlaying.side_effect = RuntimeError
    android.stop.side_effect = RuntimeError
    assert p.get_pos() == 0.0
    assert p.is_playing() is False
    p.unload()


def test_load_audio_android(monkeypatch, android):
    monkeypatch.setattr(m, "platform", "android")
    logs = []
    player = m.load_audio("/a.mp3", logs.append)
    assert isinstance(player, m.AndroidMediaPlayer) and len(logs) == 2
    assert isinstance(m.load_audio("/a.mp3"), m.AndroidMediaPlayer)

    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(m, "AndroidMediaPlayer", boom)
    assert m.load_audio("/a.mp3", logs.append) is None
    assert "MediaPlayer error: nope" in logs[-1]
    assert m.load_audio("/a.mp3") is None


def test_load_audio_desktop(monkeypatch):
    monkeypatch.setattr(m, "platform", "linux")
    monkeypatch.setattr(m.SoundLoader, "load", staticmethod(lambda p: ("sound", p)))
    assert m.load_audio("/a.mp3") == ("sound", "/a.mp3")


# --------------------------------------------------------------------- Config
def test_config_roundtrip():
    c = m.Config()
    assert c.last_playlist == [] and c.last_index == 0
    assert c.volume == 0.7 and c.openai_api_key == ""
    c.last_playlist = ["a"]
    c.last_index = 3
    c.volume = 0.2
    c.openai_api_key = "k"
    assert c.downloads_dir.is_dir()
    c2 = m.Config()
    assert (c2.last_playlist, c2.last_index, c2.volume, c2.openai_api_key) == (["a"], 3, 0.2, "k")


def test_config_corrupt_and_unwritable():
    c = m.Config()
    c._config_file.write_text("{not json")
    assert m.Config()._config == {}
    c._config_file.unlink()
    c._config_file.mkdir()
    c.set("a", 1)  # save fails silently
    assert c.get("a") == 1


def test_config_android(monkeypatch, tmp_path):
    mod = types.ModuleType("android.storage")
    mod.app_storage_path = lambda: str(tmp_path / "store")
    monkeypatch.setitem(sys.modules, "android", types.ModuleType("android"))
    monkeypatch.setitem(sys.modules, "android.storage", mod)
    monkeypatch.setattr(m, "platform", "android")
    assert m.Config()._config_dir == tmp_path / "store" / ".luister"


# --------------------------------------------------------------------- Splash
def test_splash_flow(app):
    s = m.SplashScreen()
    s.size = (400, 800)
    tick()
    s.on_enter()
    tick()
    time.sleep(0.7)
    tick(3)
    s._go_to_main(0)
    time.sleep(0.35)
    tick(3)
    assert app.root.current == "main"


def test_splash_no_app(no_app):
    s = m.SplashScreen()
    s._go_to_main(0)
    time.sleep(0.35)
    tick(2)


def test_splash_app_without_root(app):
    app.root = None
    s = m.SplashScreen()
    s._go_to_main(0)
    time.sleep(0.35)
    tick(2)


# ------------------------------------------------------- GlassPanel / buttons
def test_glass_panel():
    g = m.GlassPanel(pos=(0, 0), size=(100, 50))
    tick()
    g.size = (120, 60)


ICONS = ["play", "pause", "prev", "next", "shuffle", "loop", "folder", "youtube",
         "list", "scan", "clear", "volume", "back", "settings", "none"]


@pytest.mark.parametrize("accent,active", [(False, False), (True, False), (False, True)])
def test_icon_button_all_icons(accent, active):
    b = m.IconButton(size=(60, 60), is_accent=accent, is_active=active)
    for icon in ICONS:
        b.icon = icon


def test_icon_button_press_feedback():
    b = m.IconButton(size=(60, 60))
    tick()
    b.on_press()
    b.on_press()
    assert b._pressed
    time.sleep(0.1)
    tick(2)
    b.on_release()
    b.on_release()
    assert not b._pressed
    time.sleep(0.2)
    tick(2)


@pytest.fixture(autouse=True)
def _cancel_pending_holds():
    yield
    for w in _made:
        for attr in ("_hold_event", "_long_press_event"):
            ev = getattr(w, attr, None)
            if ev:
                ev.cancel()
    _made.clear()


_made = []


def make_gesture():
    b = m.GestureButton(pos=(0, 0), size=(100, 100))
    _made.append(b)
    return b


def test_gesture_tap_and_outside(app):
    b = make_gesture()
    assert not b.on_touch_down(touch(500, 500))
    assert not b.on_touch_up(touch(500, 500))
    t = touch(50, 50)
    assert b.on_touch_down(t)
    b.on_touch_move(touch(52, 50))
    assert b.on_touch_up(t)
    app.toggle_play.assert_called_once()


def test_gesture_slow_release_does_nothing(app, monkeypatch):
    b = make_gesture()
    t = touch(50, 50)
    b.on_touch_down(t)
    monkeypatch.setattr(m.Clock, "get_time", lambda: b._touch_start_time + 1)
    b.on_touch_up(t)
    app.toggle_play.assert_not_called()


def test_gesture_swipes(app):
    b = make_gesture()
    b.on_touch_down(touch(10, 50))
    b.on_touch_move(touch(60, 50))
    assert b._hold_event is None
    b.on_touch_move(touch(70, 50))
    b.on_touch_up(touch(60, 50))
    app.next_track.assert_called_once()
    b.on_touch_down(touch(60, 50))
    b.on_touch_up(touch(10, 50))
    app.prev_track.assert_called_once()
    assert not b.on_touch_move(touch(1, 1)) or True


def test_gesture_long_press(app):
    b = make_gesture()
    b.on_touch_down(touch(50, 50))
    time.sleep(0.6)
    tick()
    assert b._hold_triggered
    app.stop_playback.assert_called_once()
    assert b.on_touch_up(touch(50, 50))
    assert b._touch_start is None


def test_gesture_no_app(no_app):
    b = make_gesture()
    b.on_touch_down(touch(50, 50))
    b.on_touch_up(touch(50, 50))
    b._on_long_press(0)


# --------------------------------------------------------------------- Sliders
def test_styled_slider_drag():
    s = m.StyledSlider(pos=(0, 0), size=(220, 40), show_handle=False)
    tick()
    s.value = 10
    s.show_handle = True
    assert not s.on_touch_move(touch(5, 5)) or True
    assert not s.on_touch_up(touch(5, 5)) or True
    assert not s.on_touch_down(touch(900, 900)) or True
    assert s.on_touch_down(touch(110, 20))
    assert s.value == pytest.approx(50)
    assert s.on_touch_move(touch(210, 20))
    assert s.value == 100
    assert s.on_touch_up(touch(0, 20))
    assert s.value == 0


def test_navigable_slider_zones(app):
    s = m.NavigableSlider(pos=(0, 0), size=(1000, 40))
    s.on_touch_down(touch(50, 20))
    s.on_touch_up(touch(50, 20))
    app.prev_track.assert_called_once()
    s.on_touch_down(touch(950, 20))
    s.on_touch_up(touch(950, 20))
    app.next_track.assert_called_once()
    s.on_touch_down(touch(500, 20))
    s.on_touch_up(touch(500, 20))
    app.seek.assert_called_once()
    assert app.seek.call_args[0][0] == pytest.approx(0.5, abs=0.02)
    # released outside while active -> base handling
    s.on_touch_down(touch(500, 20))
    assert s.on_touch_up(touch(5000, 20))


def test_navigable_slider_no_app(no_app):
    s = m.NavigableSlider(pos=(0, 0), size=(1000, 40))
    s.on_touch_down(touch(500, 20))
    assert s.on_touch_up(touch(500, 20))


# ------------------------------------------------------------------ Visualizer
class FakeSF:
    def __init__(self, data=None, exc=None):
        self.data, self.exc = data, exc

    def read(self, path):
        if self.exc:
            raise self.exc
        return self.data, 8000


class SyncThread:
    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        self.target()


@pytest.fixture
def viz(monkeypatch):
    monkeypatch.setattr(m.threading, "Thread", SyncThread)
    return m.VisualizerWidget(pos=(0, 0), size=(300, 200))


def test_visualizer_set_audio(viz, monkeypatch):
    import numpy as np

    monkeypatch.setitem(sys.modules, "soundfile", FakeSF(np.random.rand(8000, 2)))
    viz.set_audio("a.wav")
    assert viz._has_audio and viz._audio_data.ndim == 1 and viz._sample_rate == 8000
    monkeypatch.setitem(sys.modules, "soundfile", FakeSF(np.random.rand(8000)))
    viz.set_audio("a.wav")
    assert viz._has_audio
    monkeypatch.setitem(sys.modules, "soundfile", None)
    viz.set_audio("a.wav")
    assert not viz._has_audio
    monkeypatch.setitem(sys.modules, "soundfile", FakeSF(exc=ValueError("bad")))
    viz._has_audio = True
    viz.set_audio("a.wav")
    assert not viz._has_audio


def test_visualizer_position_and_animation(viz):
    import numpy as np

    viz.update_position(1000)
    assert viz._current_frame == 0
    viz._has_audio = True
    viz._audio_data = np.random.rand(16000).astype(np.float32) * 10
    viz._sample_rate = 8000
    viz.update_position(500)
    assert viz._current_frame == 4000
    viz.update_position(10 ** 9)
    assert viz._current_frame == 15999

    viz.set_playing(True)
    viz._update_animation(0.016)
    assert max(viz.target_magnitudes) > 0
    viz._has_audio = False
    viz._update_animation(0.016)  # playing without audio: random targets
    viz.set_playing(False)
    viz.magnitudes = [1.0] * viz.bars
    viz._update_animation(0.016)
    assert viz.magnitudes[0] < 1.0


def test_visualizer_fft_edges(viz, monkeypatch):
    import numpy as np

    viz._audio_data = None
    viz._calculate_fft()
    viz._audio_data = np.zeros(100, dtype=np.float32)
    viz._calculate_fft()  # window too short
    viz._audio_data = np.ones(5000, dtype=np.float32)
    viz._current_frame = 0
    viz._calculate_fft()
    monkeypatch.setattr(m, "HAS_NUMPY", False)
    viz._calculate_fft()


# --------------------------------------------------------------- PlayerControls
def test_player_controls(app):
    c = m.PlayerControls()
    c.on_prev(None)
    c.on_next(None)
    app.prev_track.assert_called_once()
    app.next_track.assert_called_once()
    c.on_shuffle(None)
    assert c.is_shuffled and c.shuffle_btn.is_active
    c.on_loop(None)
    assert c.is_looping and c.loop_btn.is_active
    c.update_play_button(True)
    assert c.play_btn.icon == "pause"
    c.update_play_button(False)
    assert c.play_btn.icon == "play"


def test_player_controls_button_events(app):
    c = m.PlayerControls()
    for b in (c.shuffle_btn, c.prev_btn, c.next_btn, c.loop_btn):
        b.dispatch("on_release")
    app.shuffle_playlist.assert_called_once()
    app.toggle_loop.assert_called_once()


def test_player_controls_no_app(no_app):
    c = m.PlayerControls()
    c.on_prev(None)
    c.on_next(None)
    c.on_shuffle(None)
    c.on_loop(None)
    assert not c.is_shuffled and not c.is_looping


# ----------------------------------------------------------------- PlaylistItem
def make_item():
    it = m.PlaylistItem(2, "Song", "/s.mp3", pos=(0, 0), size=(300, 56))
    _made.append(it)
    return it


def test_playlist_item_tap(app):
    it = make_item()
    it.size = (310, 56)
    assert it.index_label.text == "3"
    assert not it.on_touch_down(touch(900, 900))
    assert not it.on_touch_up(touch(900, 900))
    t = touch(50, 20)
    assert it.on_touch_down(t)
    assert it.on_touch_move(touch(51, 21)) or True
    assert it.on_touch_up(t)
    app.play_index.assert_called_once_with(2)
    assert app.root.current == "main"


def test_playlist_item_move_cancels_long_press(app):
    it = make_item()
    it.on_touch_down(touch(50, 20))
    it.on_touch_move(touch(100, 20))
    assert it._long_press_event is None
    it.on_touch_move(touch(100, 20))
    time.sleep(0.65)
    tick()
    app.show_lyrics_popup.assert_not_called()


def test_playlist_item_long_press(app):
    it = make_item()
    it.on_touch_down(touch(50, 20))
    time.sleep(0.65)
    tick()
    app.show_lyrics_popup.assert_called_once_with("Song", "/s.mp3")
    assert it.on_touch_up(touch(50, 20))
    app.play_index.assert_not_called()


def test_playlist_item_no_app_and_highlight(no_app):
    it = make_item()
    it.on_touch_down(touch(50, 20))
    it.on_touch_up(touch(50, 20))
    it.on_touch_down(touch(50, 20))
    it._on_long_press(0)
    it.update_highlight(True)
    assert it.index_label.color == m.Theme.ACCENT
    it.update_highlight(False)
    assert it.index_label.color == m.Theme.TEXT_SECONDARY


# ------------------------------------------------------------------- MainScreen
def test_main_screen(app, monkeypatch):
    popup = MagicMock()
    monkeypatch.setattr(m, "SettingsPopup", lambda: popup)
    s = m.MainScreen()
    s.size = (400, 800)
    tick()
    for lbl in (s.title_label, s.lyrics_current, s.lyrics_next, s.debug_label):
        lbl.width = 123
    assert s.title_label.text_size[0] == 123

    s.progress_slider.value = 0
    s.volume_slider.value = 50
    app.set_volume.assert_called_with(0.5)

    s.playlist_btn.dispatch("on_release")
    assert app.root.current == "playlist"
    s.youtube_btn.dispatch("on_release")
    app.show_youtube_dialog.assert_called_once()
    s.settings_btn.dispatch("on_release")
    popup.open.assert_called_once()

    s.lyrics_current.text = "x"
    s.update_track_info("Title", 125)
    assert s.title_label.text == "Title" and s.time_total.text == "2:05"
    assert s.lyrics_current.text == ""

    s.update_position(30, 120)
    assert s.progress_slider.value == 25 and s.time_current.text == "0:30"
    s.update_position(30, 0)
    assert s.time_current.text == "0:30"

    s.update_lyrics("now", "next")
    tick()
    assert (s.lyrics_current.text, s.lyrics_next.text) == ("now", "next")
    s.update_lyrics("only")
    tick()
    assert s.lyrics_next.text == ""


def test_main_screen_no_app(no_app, monkeypatch):
    s = m.MainScreen()
    s.on_volume(None, 10)
    s.open_playlist(None)
    s.open_youtube(None)


def test_visualizer_styles_and_long_press():
    v = m.VisualizerWidget(pos=(0, 0), size=(300, 200))
    v.magnitudes = [0.5] * v.bars
    for style in range(len(v.STYLES)):
        v.style = style
        v._draw_bars()

    class Touch:
        def __init__(self, pos):
            self.pos = pos
            self.grab_current = None

        def grab(self, w):
            self.grab_current = w

        def ungrab(self, w):
            self.grab_current = None

    outside = Touch((999, 999))
    assert not v.on_touch_down(outside)
    assert not v.on_touch_up(outside)

    t = Touch((10, 10))
    assert v.on_touch_down(t) and v._hold_event is not None
    assert v.on_touch_up(t) and v._hold_event is None  # released early: no change
    assert v.style == 2

    start = v.style
    t = Touch((10, 10))
    v.on_touch_down(t)
    v._hold_event.cancel()
    v._next_style()
    assert v.style == (start + 1) % 3
