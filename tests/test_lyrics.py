"""Tests for luister.lyrics with a fake whisper module (no real models)."""

import json
import sys
import types

import pytest
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox, QDialog, QDialogButtonBox

from luister import lyrics
from luister.lyrics import LyricsWidget

SEGMENTS = [
    {"start": 0.0, "end": 2.0, "text": "first"},
    {"start": 2.5, "end": 4.0, "text": "second"},
    {"start": 5.0, "end": 6.0, "text": "third"},
]


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


class FakeMel:
    def to(self, device):
        return self


class FakeModel:
    device = "cpu"

    def __init__(self, name, result, probs, detect_error=False):
        self.name, self.result, self.probs = name, result, probs
        self.detect_error = detect_error
        self.transcribed = []

    def detect_language(self, mel):
        if self.detect_error:
            raise RuntimeError("detect failed")
        return None, self.probs

    def transcribe(self, path, language=None):
        self.transcribed.append((path, language, self.name))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make_whisper(result=None, probs=None, detect_error=False, kwarg_loader=True,
                 load_error=None):
    mod = types.ModuleType("whisper")
    mod.loaded = []
    result = {"segments": SEGMENTS} if result is None else result
    probs = probs or {"en": 0.2, "nl": 0.7}

    def build(name):
        mod.loaded.append(name)
        if load_error:
            raise load_error
        return FakeModel(name, result, probs, detect_error)

    if kwarg_loader:
        mod.load_model = lambda name, download_root=None: build(name)
    else:
        mod.load_model = lambda name: build(name)
    mod.load_audio = lambda p: [0.0]
    mod.pad_or_trim = lambda a: a
    mod.log_mel_spectrogram = lambda a: FakeMel()
    return mod


@pytest.fixture
def lw(app, qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(lyrics, "MODEL_ROOT", tmp_path / "models")
    w = LyricsWidget()
    qtbot.addWidget(w)
    w.show()
    return w


@pytest.fixture
def audio(tmp_path):
    p = tmp_path / "song.mp3"
    p.write_bytes(b"x")
    return str(p)


def answer_dialog(action, model=None, lang=None):
    """Drive the modal options dialog like a user: pick values, then OK/Cancel/Esc."""

    def handler():
        dlg = QApplication.activeModalWidget()
        if not isinstance(dlg, QDialog):
            QTimer.singleShot(10, handler)
            return
        combos = dlg.findChildren(QComboBox)
        if lang is not None:
            combos[0].setCurrentText(lang)
        if model is not None:
            combos[1].setCurrentText(model)
        if action == "ok":
            box = dlg.findChild(QDialogButtonBox)
            QTest.mouseClick(box.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
        elif action == "cancel":
            box = dlg.findChild(QDialogButtonBox)
            QTest.mouseClick(box.button(QDialogButtonBox.StandardButton.Cancel), Qt.MouseButton.LeftButton)
        else:
            QTest.keyClick(dlg, Qt.Key.Key_Escape)

    QTimer.singleShot(10, handler)


def texts(w):
    return [w.list_widget.item(i).text() for i in range(w.list_widget.count())]


# --- _load_whisper ------------------------------------------------------------


def test_load_whisper_returns_module_and_creates_cache_dir(tmp_path, monkeypatch):
    fake = make_whisper()
    monkeypatch.setitem(sys.modules, "whisper", fake)
    monkeypatch.setattr(lyrics, "MODEL_ROOT", tmp_path / "m" / "n")
    assert lyrics._load_whisper() is fake
    assert (tmp_path / "m" / "n").is_dir()


def test_load_whisper_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "whisper", None)
    assert lyrics._load_whisper() is None


# --- cache --------------------------------------------------------------------


def test_cached_transcription_is_used(lw, audio, qtbot):
    with open(audio + ".json", "w", encoding="utf-8") as f:
        json.dump(SEGMENTS, f)
    with qtbot.waitSignal(lw.segments_ready):
        lw.load_lyrics(audio)
    assert texts(lw) == ["first", "second", "third"]
    assert lw.segments[1] == (2.5, 4.0, "second")


def test_corrupt_cache_yields_empty(lw, audio, qtbot):
    with open(audio + ".json", "w", encoding="utf-8") as f:
        f.write("{not json")
    with qtbot.waitSignal(lw.segments_ready) as b:
        lw.load_lyrics(audio)
    assert b.args == [[]] and lw.segments == []


def test_same_file_already_transcribing_is_ignored(lw, audio, monkeypatch):
    monkeypatch.setitem(sys.modules, "whisper", None)
    lw._transcribing = True
    lw._current_audio_file = audio
    seen = []
    lw.segments_ready.connect(seen.append)
    lw.load_lyrics(audio)
    QTest.qWait(100)
    assert seen == [] and lw.list_widget.count() == 0


# --- prepare / error paths ------------------------------------------------------


def test_whisper_not_installed_shows_error(lw, audio, qtbot, monkeypatch):
    monkeypatch.setitem(sys.modules, "whisper", None)
    with qtbot.waitSignal(lw.segments_ready):
        lw.load_lyrics(audio)
    assert lw.list_widget.count() == 0  # cleared again by empty segments
    assert lw._transcribing is False and lw._current_audio_file is None


def test_whisper_error_message_is_listed(lw, audio, tmp_path):
    lw._on_prep_ready({"error": "Error: boom", "file_path": audio, "cache_path": tmp_path / "c.json"})
    assert lw._transcribing is False
    # the error must stay visible to the user
    assert texts(lw) == ["Error: boom"]


def test_model_load_failure(lw, audio, qtbot, monkeypatch):
    monkeypatch.setitem(sys.modules, "whisper", make_whisper(load_error=RuntimeError("no model")))
    with qtbot.waitSignal(lw.segments_ready):
        lw.load_lyrics(audio)
    assert lw._model is None and lw._transcribing is False


def test_old_whisper_without_download_root_kwarg(lw, audio, qtbot, monkeypatch):
    mod = make_whisper(kwarg_loader=False)
    monkeypatch.setitem(sys.modules, "whisper", mod)
    answer_dialog("ok", model="tiny")
    with qtbot.waitSignal(lw.segments_ready, timeout=10000) as b:
        lw.load_lyrics(audio)
    assert b.args[0] == SEGMENTS
    assert mod.loaded == ["tiny"]


def test_old_whisper_big_model_without_kwarg(lw, audio, qtbot, monkeypatch):
    mod = make_whisper(kwarg_loader=False)
    monkeypatch.setitem(sys.modules, "whisper", mod)
    answer_dialog("ok", model="small")
    with qtbot.waitSignal(lw.segments_ready, timeout=10000):
        lw.load_lyrics(audio)
    assert mod.loaded == ["tiny", "small"]


# --- full flows ------------------------------------------------------------------


def test_full_transcription_writes_cache(lw, audio, qtbot, monkeypatch):
    mod = make_whisper()
    monkeypatch.setitem(sys.modules, "whisper", mod)
    answer_dialog("ok")  # defaults: detected language 'nl', model 'base'
    with qtbot.waitSignal(lw.segments_ready, timeout=10000):
        lw.load_lyrics(audio)
    assert texts(lw) == ["first", "second", "third"]
    assert mod.loaded == ["tiny", "base"]
    assert json.load(open(audio + ".json")) == SEGMENTS
    assert lw._transcribing is False


def test_user_picked_language_and_tiny_model_reuse_loaded_model(lw, audio, qtbot, monkeypatch):
    mod = make_whisper()
    monkeypatch.setitem(sys.modules, "whisper", mod)
    answer_dialog("ok", model="tiny", lang="en")
    with qtbot.waitSignal(lw.segments_ready, timeout=10000):
        lw.load_lyrics(audio)
    assert mod.loaded == ["tiny"]
    assert lw._model.transcribed == [(audio, "en", "tiny")]
    # second request reuses cached whisper + model objects
    other = audio.replace("song", "other")
    open(other, "wb").write(b"y")
    answer_dialog("ok", model="tiny")
    with qtbot.waitSignal(lw.segments_ready, timeout=10000):
        lw.load_lyrics(other)
    assert mod.loaded == ["tiny"]


def test_language_detection_failure_defaults_to_english(lw, audio, qtbot, monkeypatch):
    monkeypatch.setitem(sys.modules, "whisper", make_whisper(detect_error=True))
    answer_dialog("ok", model="tiny")
    with qtbot.waitSignal(lw.segments_ready, timeout=10000):
        lw.load_lyrics(audio)
    assert lw._model.transcribed[0][1] == "en"


@pytest.mark.parametrize("how", ["cancel", "escape"])
def test_cancelling_dialog_emits_empty_segments(lw, audio, qtbot, monkeypatch, how):
    monkeypatch.setitem(sys.modules, "whisper", make_whisper())
    answer_dialog(how)
    with qtbot.waitSignal(lw.segments_ready, timeout=10000) as b:
        lw.load_lyrics(audio)
    assert b.args == [[]]
    assert lw._transcribing is False and lw._current_audio_file is None


def test_no_speech_probability_discards_segments(lw, audio, qtbot, monkeypatch):
    res = {"segments": SEGMENTS, "no_speech_prob": 0.9}
    monkeypatch.setitem(sys.modules, "whisper", make_whisper(result=res))
    answer_dialog("ok", model="tiny")
    with qtbot.waitSignal(lw.segments_ready, timeout=10000) as b:
        lw.load_lyrics(audio)
    assert b.args == [[]]


def test_transcribe_exception_yields_empty(lw, audio, qtbot, monkeypatch):
    monkeypatch.setitem(sys.modules, "whisper", make_whisper(result=RuntimeError("bad audio")))
    answer_dialog("ok", model="tiny")
    with qtbot.waitSignal(lw.segments_ready, timeout=10000) as b:
        lw.load_lyrics(audio)
    assert b.args == [[]] and lw._transcribing is False


def test_unwritable_cache_is_ignored_and_unknown_language_defaults(lw, audio, qtbot, tmp_path):
    lw._whisper = make_whisper()
    lw._model = FakeModel("tiny", {"segments": SEGMENTS}, {})
    prep = {
        "probs": {"en": 0.9, "nl": 0.1},
        "language": "zz",
        "file_path": audio,
        "cache_path": tmp_path / "no_such_dir" / "x.json",
    }
    answer_dialog("ok", model="tiny")
    with qtbot.waitSignal(lw.segments_ready, timeout=10000) as b:
        lw._on_prep_ready(prep)
    assert b.args[0] == SEGMENTS
    assert lw._model.transcribed[0][1] == "en"  # index 0 = highest probability


# --- display -----------------------------------------------------------------------


def test_segments_ready_resets_state_and_hides_progress(lw):
    lw.show_progress()
    assert lw.progress_bar.isVisible()
    lw.segments_ready.emit(SEGMENTS + [{}])
    assert not lw.progress_bar.isVisible()
    assert lw.segments[-1] == (0.0, 0.0, "")
    assert lw._active_index == -1
    lw.hide_progress()
    assert not lw.progress_bar.isVisible()


def test_update_position_highlights_active_line(lw):
    lw.update_position(1000)  # no segments: no-op
    assert lw.list_widget.currentRow() == -1
    lw.segments_ready.emit(SEGMENTS)
    lw.update_position(-500)  # before first segment
    assert lw._active_index == -1
    lw.update_position(1000)
    assert lw.list_widget.currentRow() == 0
    lw.list_widget.setCurrentRow(2)
    lw.update_position(1500)  # same line: widget untouched
    assert lw.list_widget.currentRow() == 2
    lw.update_position(3000)
    assert lw.list_widget.currentRow() == 1
    lw.update_position(4500)  # gap between segments: keep current
    assert lw.list_widget.currentRow() == 1
    lw.update_position(5500)
    assert lw.list_widget.currentRow() == 2


def test_update_position_index_beyond_list_items(lw):
    lw.segments_ready.emit(SEGMENTS)
    lw.list_widget.takeItem(2)
    lw.update_position(5500)
    assert lw._active_index == -1


def test_update_position_missing_item(lw, monkeypatch):
    lw.segments_ready.emit(SEGMENTS)
    monkeypatch.setattr(lw.list_widget, "item", lambda i: None)
    lw.update_position(1000)
    assert lw._active_index == 0


def test_close_hides_and_emits(lw):
    closed = []
    lw.closed.connect(lambda: closed.append(1))
    lw.close()
    assert closed == [1] and not lw.isVisible()


def test_close_tolerates_failures(lw, monkeypatch):
    class Boom:
        def emit(self, *a):
            raise RuntimeError

    class BadEvent:
        def ignore(self):
            raise RuntimeError

    monkeypatch.setattr(LyricsWidget, "closed", Boom())
    monkeypatch.setattr(LyricsWidget, "hide", lambda self: (_ for _ in ()).throw(RuntimeError()))
    lw.closeEvent(BadEvent())
