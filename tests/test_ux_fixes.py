"""Regression tests for the UX/playback fixes.

Each test here pins down a bug that was actually present in the app, so a
future refactor cannot quietly reintroduce it.
"""

import os

import pytest
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

import luister
from luister.views import PlaylistUI


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    existing = QApplication.instance()
    yield existing or QApplication([])


@pytest.fixture
def ui(app, tmp_path, monkeypatch):
    # Keep every test off the real ~/.luister directory.
    monkeypatch.setattr(luister.Path, "home", staticmethod(lambda: tmp_path))
    window = luister.UI()
    yield window
    window._gui_state_frozen = True


# --- URL validation -------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/abc123",
        "https://www.youtube-nocookie.com/embed/abc123",
    ],
)
def test_accepts_valid_youtube_urls(url):
    assert luister._is_supported_media_url(url)


@pytest.mark.parametrize(
    "url",
    ["", "not a url", "https://vimeo.com/12345", "ftp://youtube.com/x", "youtube.com"],
)
def test_rejects_non_youtube_urls(url):
    assert not luister._is_supported_media_url(url)


# --- Download thread ------------------------------------------------------


def test_download_thread_does_not_shadow_qthread_finished():
    """QThread.finished must stay the built-in no-argument signal."""
    assert luister.YTDownloadThread.finished is QThread.finished
    assert hasattr(luister.YTDownloadThread, "batch_finished")


def test_download_thread_has_client_fallbacks():
    """A single 403-ing client must not fail the whole download."""
    assert len(luister.YTDownloadThread.PLAYER_CLIENTS) > 1


# --- Volume ---------------------------------------------------------------


def test_volume_slider_range_is_full_0_to_100(ui):
    assert ui.volume_slider.minimum() == 0
    assert ui.volume_slider.maximum() == 100


def test_volume_reaches_full_scale(ui):
    ui.volume_slider.setValue(100)
    assert ui.audio_output.volume() == pytest.approx(1.0)


def test_volume_is_monotonic_and_perceptual(ui):
    """Volume must rise with the slider, and not be a flat linear ramp."""
    readings = []
    for value in (0, 25, 50, 75, 100):
        ui.volume_slider.setValue(value)
        readings.append(ui.audio_output.volume())

    assert readings == sorted(readings)
    assert readings[0] == pytest.approx(0.0)
    # Logarithmic scaling puts the midpoint well below the linear 0.5.
    assert readings[2] < 0.4


def test_initial_volume_is_pushed_to_the_audio_output(ui):
    """The slider position and the actual output must agree at startup."""
    assert ui.audio_output.volume() == pytest.approx(
        luister.QAudio.convertVolume(
            ui.volume_slider.value() / 100.0,
            luister.QAudio.VolumeScale.LogarithmicVolumeScale,
            luister.QAudio.VolumeScale.LinearVolumeScale,
        )
    )


def test_mute_round_trips(ui):
    ui.volume_slider.setValue(70)
    ui.toggle_mute()
    assert ui.volume_slider.value() == 0
    assert ui.audio_output.volume() == pytest.approx(0.0)
    ui.toggle_mute()
    assert ui.volume_slider.value() == 70


def test_volume_persists_across_restart(ui, tmp_path, monkeypatch):
    ui.volume_slider.setValue(37)
    ui._gui_state_frozen = True

    monkeypatch.setattr(luister.Path, "home", staticmethod(lambda: tmp_path))
    second = luister.UI()
    try:
        assert second.volume_slider.value() == 37
    finally:
        second._gui_state_frozen = True


# --- Lyrics default -------------------------------------------------------


def test_lyrics_hidden_by_default(ui):
    assert not ui.lyrics_dock.isVisible()


def test_lyrics_choice_persists(ui, tmp_path, monkeypatch):
    ui.set_lyrics_visible(True)
    assert ui.lyrics_dock.isVisible()
    ui._persist_gui_state()
    ui._gui_state_frozen = True

    monkeypatch.setattr(luister.Path, "home", staticmethod(lambda: tmp_path))
    second = luister.UI()
    try:
        assert second.lyrics_dock.isVisible()
    finally:
        second._gui_state_frozen = True


def test_stale_pre_migration_state_does_not_force_lyrics_open(ui, tmp_path, monkeypatch):
    """Old state files recorded lyrics=1 because the app forced it open."""
    state = tmp_path / ".luister" / "states" / "gui.txt"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("visualizer=1\nlyrics=1\n", encoding="utf-8")

    monkeypatch.setattr(luister.Path, "home", staticmethod(lambda: tmp_path))
    second = luister.UI()
    try:
        assert not second.lyrics_dock.isVisible()
    finally:
        second._gui_state_frozen = True


# --- Responsive layout ----------------------------------------------------


def test_widgets_use_a_layout_not_absolute_geometry(ui):
    assert ui.centralWidget().layout() is not None


def test_no_widget_overlap_when_window_is_small(ui, app):
    ui.resize(ui.minimumWidth(), ui.minimumHeight())
    app.processEvents()

    rects = {
        "lcd": ui.time_lcd.geometry(),
        "slider": ui.time_slider.geometry(),
        "play": ui.play_btn.geometry(),
        "visualizer": ui.visualizer_widget.geometry(),
    }
    names = list(rects)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert not rects[a].intersects(rects[b]), f"{a} overlaps {b}"


def test_contents_grow_with_the_window(ui, app):
    ui.resize(500, 400)
    app.processEvents()
    small = ui.time_slider.width()

    ui.resize(1200, 800)
    app.processEvents()
    assert ui.time_slider.width() > small


def test_window_can_shrink_to_a_laptop_friendly_size(ui):
    """Dock minimums used to force the window to stay ~1000px wide."""
    assert ui.minimumWidth() <= 600
    assert ui.minimumHeight() <= 500


# --- Playlist indexing ----------------------------------------------------


def test_row_lookup_survives_a_status_prefix(app):
    playlist = PlaylistUI()
    playlist.list_songs.addItem("1. first.mp3")
    playlist.list_songs.addItem("2. second.mp3")
    playlist.set_item_download_status(1, "downloading")

    item = playlist.list_songs.item(1)
    assert item.text().startswith("⬇")
    # The old code parsed the leading digit out of the display text.
    assert playlist.list_songs.row(item) == 1


# --- Display --------------------------------------------------------------


def test_track_title_survives_position_updates(ui):
    ui._set_track_title("1. song.mp3")
    ui.position_changed(45_000)
    assert "song.mp3" in ui.time_lcd.toPlainText()
    assert ui.elapsed_label.text() == "00:45"


@pytest.mark.parametrize(
    "ms,expected",
    [(0, "00:00"), (5_000, "00:05"), (65_000, "01:05"), (3_725_000, "1:02:05")],
)
def test_duration_formatting(ms, expected):
    assert luister.UI._format_ms(ms) == expected


def test_seek_slider_is_not_yanked_while_dragging(ui):
    ui.duration_changed(100_000)
    ui._on_seek_start()
    ui.time_slider.setValue(80_000)
    ui.position_changed(10_000)
    assert ui.time_slider.value() == 80_000
    ui._on_seek_end()
