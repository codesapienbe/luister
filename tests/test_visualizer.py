"""Tests for luister.visualizer (analysis thread and spectrum widget)."""

import importlib
import sys

import numpy as np
import pytest
import soundfile as sf
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from luister import visualizer
from luister.visualizer import VisualizerWidget, _AnalyzerThread


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


def _wav(path, seconds=0.5, channels=1, sr=22050):
    t = np.arange(int(sr * seconds)) / sr
    sig = 0.5 * np.sin(2 * np.pi * 440 * t) + 0.2 * np.sin(2 * np.pi * 3000 * t)
    if channels == 2:
        sig = np.stack([sig, sig * 0.5], axis=1)
    sf.write(str(path), sig, sr)
    return str(path)


def _run(file_path, interrupted=False):
    th = _AnalyzerThread(file_path)
    got = []
    th.analysis_finished.connect(lambda m, t: got.append((m, t)))
    if interrupted:
        th.isInterruptionRequested = lambda: True
    th.run()
    return got


# --- import fallback --------------------------------------------------------


def test_module_without_librosa_sets_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "librosa", None)
    mod = importlib.reload(visualizer)
    try:
        assert mod.librosa is None
    finally:
        monkeypatch.undo()
        importlib.reload(visualizer)
    assert visualizer.librosa is not None


# --- analysis thread --------------------------------------------------------


def test_analyzer_librosa_path(tmp_path):
    ((mags, times),) = _run(_wav(tmp_path / "a.wav"))
    assert mags.shape[1] == 32 and mags.shape[0] == len(times)
    assert mags.min() >= 0 and mags.max() <= 1


def test_analyzer_librosa_interrupted(tmp_path):
    assert _run(_wav(tmp_path / "a.wav"), interrupted=True) == []


def test_analyzer_fallback_stereo(tmp_path, monkeypatch):
    monkeypatch.setattr(visualizer, "librosa", None)
    ((mags, times),) = _run(_wav(tmp_path / "s.wav", 0.5, channels=2))
    assert mags.shape[1] == 32 and len(times) == mags.shape[0]
    assert mags.max() <= 1


def test_analyzer_fallback_short_file_is_padded(tmp_path, monkeypatch):
    monkeypatch.setattr(visualizer, "librosa", None)
    ((mags, _),) = _run(_wav(tmp_path / "short.wav", 0.02))
    assert mags.shape == (1, 32)


def test_analyzer_fallback_interrupted(tmp_path, monkeypatch):
    monkeypatch.setattr(visualizer, "librosa", None)
    assert _run(_wav(tmp_path / "a.wav"), interrupted=True) == []


@pytest.mark.parametrize("use_librosa", [True, False])
def test_analyzer_missing_file_emits_none(tmp_path, monkeypatch, use_librosa):
    if not use_librosa:
        monkeypatch.setattr(visualizer, "librosa", None)
    assert _run(str(tmp_path / "missing.wav")) == [(None, None)]


def test_analyzer_runs_in_real_thread(app, qtbot, tmp_path):
    th = _AnalyzerThread(_wav(tmp_path / "t.wav", 0.2))
    with qtbot.waitSignal(th.analysis_finished, timeout=20000) as blocker:
        th.start()
    th.wait()
    assert blocker.args[0].shape[1] == 32


# --- widget -----------------------------------------------------------------


@pytest.fixture
def vis(app, qtbot):
    w = VisualizerWidget()
    qtbot.addWidget(w)
    w.resize(300, 150)
    w.show()
    yield w
    w.pause_animation()
    w._analysis_timeout_timer.stop()


def _pixels(w):
    img = w.grab().toImage()
    return {img.pixelColor(x, y).name() for x in range(0, img.width(), 3) for y in range(0, img.height(), 3)}


def test_set_audio_end_to_end_then_play(vis, qtbot, tmp_path):
    started, ready = [], []
    vis.analysis_started.connect(lambda: started.append(1))
    vis.analysis_ready.connect(ready.append)
    with qtbot.waitSignal(vis.analysis_ready, timeout=20000):
        vis.set_audio(_wav(tmp_path / "x.wav", 0.5))
    vis._analyzer_thread.wait()
    assert started == [1] and ready == [True]
    assert not vis._analysis_timeout_timer.isActive()
    assert vis._animation_timer.isActive()

    vis.update_position(100)
    assert vis._current_index == np.searchsorted(vis._times, 0.1)
    vis.update_position(10**9)
    assert vis._current_index == len(vis._times) - 1
    vis.update_position(-5)
    assert vis._current_index == 0

    for _ in range(3):
        vis._on_animation_tick()
    assert vis._smoothed_mags.max() > 0
    assert "#ffffff" in _pixels(vis) or len(_pixels(vis)) > 2

    vis.pause_animation()
    assert not vis._animation_timer.isActive()
    vis.pause_animation()
    vis.resume_animation()
    vis.resume_animation()
    assert vis._animation_timer.isActive()


def test_set_audio_cancels_running_thread(vis):
    class Running:
        interrupted = False
        waited = None

        def isRunning(self):
            return True

        def requestInterruption(self):
            self.interrupted = True

        def wait(self, ms):
            self.waited = ms

    old = Running()
    vis._analyzer_thread = old
    vis.set_audio("/nonexistent/file.wav")
    assert old.interrupted and old.waited == 100
    vis._analyzer_thread.wait()
    assert vis._status_text == "Analyzing..."


def test_update_position_without_data_is_noop(vis):
    vis.update_position(500)
    assert vis._current_index == 0


def test_paint_states(vis):
    base = _pixels(vis)
    assert base  # "Loading..." default text on dark background
    vis._status_text = "Analysis failed"
    vis.repaint()
    vis._magnitudes = np.zeros((2, 32))
    vis._smoothed_mags = None
    assert "#0a0a0a" in _pixels(vis)


@pytest.mark.parametrize("style", [0, 1, 2])
def test_paint_each_style_with_peaks(vis, style):
    vis._magnitudes = np.ones((2, 8))
    vis._smoothed_mags = np.linspace(0.1, 1.0, 8)
    vis._peaks = np.ones(8)
    vis._style = style
    colors = _pixels(vis)
    assert len(colors) > 3


def test_draw_bars_without_peaks(vis):
    vis._magnitudes = np.ones((2, 8))
    vis._smoothed_mags = np.full(8, 0.5)
    vis._peaks = None
    vis._style = 1
    assert len(_pixels(vis)) > 3


def test_double_click_cycles_style(vis):
    assert vis._style == 0
    for expected in (1, 2, 0):
        QTest.mouseDClick(vis, Qt.MouseButton.LeftButton)
        assert vis._style == expected


def test_animation_tick_without_data_is_noop(vis):
    vis._on_animation_tick()
    assert vis._smoothed_mags is None


def test_animation_tick_peak_hold_and_fall(vis):
    vis._magnitudes = np.array([[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]])
    vis._on_animation_tick()  # new peaks
    assert vis._peaks[0] > 0
    vis._current_index = 1
    vis._smoothed_mag_before = vis._smoothed_mags.copy()
    for _ in range(vis._peak_hold_frames):
        vis._on_animation_tick()
    held = vis._peaks[0]
    vis._on_animation_tick()  # hold counter expired: peak falls
    assert vis._peaks[0] < held


def test_animation_tick_resizes_on_band_change(vis):
    vis._magnitudes = np.ones((1, 5))
    vis._smoothed_mags = np.zeros(3)
    vis._on_animation_tick()
    assert len(vis._smoothed_mags) == 5 and len(vis._peaks) == 5


def test_analysis_done_failure(vis):
    ready = []
    vis.analysis_ready.connect(ready.append)
    vis._on_analysis_done(None, None)
    assert vis._status_text == "Analysis failed" and ready == [False]
    vis._on_analysis_done(np.zeros((1, 4)), None)
    assert ready == [False, False]


def test_analysis_done_one_dimensional_magnitudes(vis):
    vis._on_analysis_done(np.zeros(4), np.zeros(4))
    assert len(vis._peaks) == 32


def test_analysis_timeout_with_stuck_thread(vis):
    class Stuck:
        calls = []

        def isRunning(self):
            return True

        def requestInterruption(self):
            self.calls.append("int")

        def wait(self, ms):
            self.calls.append(("wait", ms))

        def terminate(self):
            self.calls.append("terminate")

    ready = []
    vis.analysis_ready.connect(ready.append)
    vis._analyzer_thread = Stuck()
    vis._on_analysis_timeout()
    assert Stuck.calls == ["int", ("wait", 200), "terminate"]
    assert vis._status_text == "Analysis timeout" and ready == [False]


def test_analysis_timeout_without_thread(vis):
    vis._analyzer_thread = None
    vis._on_analysis_timeout()
    assert vis._status_text == "Analysis timeout"


def test_analysis_timeout_thread_stops(vis):
    class Quick:
        state = [True, False]

        def isRunning(self):
            return self.state.pop(0)

        def requestInterruption(self):
            pass

        def wait(self, ms):
            pass

    vis._analyzer_thread = Quick()
    vis._on_analysis_timeout()
    assert vis._status_text == "Analysis timeout"


class _BoomSignal:
    def emit(self, *a):
        raise RuntimeError("no receiver")


def test_signal_emit_failures_are_swallowed(vis, monkeypatch):
    for name in ("analysis_started", "analysis_ready", "closed"):
        monkeypatch.setattr(VisualizerWidget, name, _BoomSignal())
    vis._on_analysis_done(None, None)
    vis._on_analysis_done(np.zeros((1, 4)), np.zeros(1))
    vis._analyzer_thread = None
    vis._on_analysis_timeout()
    vis.set_audio("/nonexistent.wav")
    vis._analyzer_thread.wait()
    vis.close()
    assert not vis.isVisible()


def test_close_hides_and_emits(vis):
    closed = []
    vis.closed.connect(lambda: closed.append(1))
    vis.close()
    assert closed == [1] and not vis.isVisible()
