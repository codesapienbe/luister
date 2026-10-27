"""InstallerWindow: welcome wizard, log/progress display, persisted UI state, theming, settings, speaker lock."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from tests.test_installer_gui_common import (  # noqa: F401
    boxes,
    dialogs,
    gui,
    gui_app,
    pump,
    wait_until,
)


class BoomError(RuntimeError, AttributeError):
    pass


class Boom:
    """Any attribute access or call raises: used to drive defensive ``except`` branches."""

    def __getattr__(self, name):
        raise BoomError(f"boom:{name}")

    def __call__(self, *a, **k):
        raise RuntimeError("boom-call")


class EqBoom:
    def __eq__(self, other):
        raise RuntimeError("eq")

    __hash__ = None


@pytest.fixture
def mkwin(gui, gui_app, monkeypatch):
    made = []

    def make(logo=None, state=None):
        monkeypatch.setattr(gui, "find_project_logo", lambda: logo)
        if state is not None:
            write_state(gui, state)
        w = gui.InstallerWindow()
        w.show()
        made.append(w)
        return w

    yield make
    for w in made:
        w.close()
        th = w.__dict__.get("thread")
        if th is not None and hasattr(th, "quit"):
            th.quit()
            th.wait(5000)
        w.deleteLater()
    pump()


def write_state(gui, state):
    p = Path(gui.appdirs.user_config_dir("Luister", appauthor=False))
    p.mkdir(parents=True, exist_ok=True)
    (p / "installer_ui.json").write_text(json.dumps(state) if not isinstance(state, str) else state)
    return p / "installer_ui.json"


def make_png(path, size=16):
    img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
    img.fill(QtGui.QColor(10, 200, 10))
    assert img.save(str(path))
    return path


def click(btn):
    QTest.mouseClick(btn, QtCore.Qt.LeftButton)


# ---------------------------------------------------------------- wizard

def test_wizard_get_started_reveals_installation_form(mkwin):
    w = mkwin()
    assert not w.repo_input.isVisible() and not w.start_button.isVisible()
    assert w.windowTitle() == "Luister Installer"
    click(w.get_started)
    assert wait_until(lambda: getattr(w, "_config_created", False))
    pump(w and None, 50)
    assert not w._welcome_card.isVisible()
    assert w.repo_input.isVisible() and w.install_dir_input.isVisible()
    assert w.start_button.isVisible() and w.progress_bar.isVisible() and w._toggle_logs_btn.isVisible()
    assert list(w._stage_labels) == ["clone", "venv", "deps", "launch"]
    assert w.repo_input.text() == "https://github.com/codesapienbe/luister"
    # a second call is a no-op
    before = len(w._stage_labels)
    w._create_installation_config()
    assert len(w._stage_labels) == before


def test_welcome_card_shows_logo(mkwin, tmp_path):
    w = mkwin(logo=make_png(tmp_path / "logo.png"))
    label = w._welcome_card.findChildren(QtWidgets.QLabel)[0]
    assert not label.pixmap().isNull()


def test_logo_loading_failure_is_tolerated(mkwin, gui, monkeypatch):
    class Logo:
        def exists(self):
            raise RuntimeError("fs")

    w = mkwin(logo=Logo())
    assert w._welcome_card is not None


def test_get_started_without_animation_still_hides_card(mkwin, monkeypatch):
    w = mkwin()
    monkeypatch.setattr(QtCore, "QPropertyAnimation", Boom())
    click(w.get_started)
    assert not w._welcome_card.isVisible()


def test_config_creation_failure_is_reported_in_log(mkwin, monkeypatch):
    w = mkwin()
    monkeypatch.setattr(QtWidgets, "QFrame", Boom())
    w._create_installation_config()
    assert "Failed to create installation UI components" in w.progress_output.toPlainText()
    monkeypatch.setattr(w, "append_log", Boom())
    w._create_installation_config()  # even logging failing must not raise


def test_config_creation_reveal_error_is_logged(mkwin, monkeypatch):
    w = mkwin()
    monkeypatch.setattr(w, "repo_input", Boom())
    w._create_installation_config()
    assert "stage:internal:error" in w.progress_output.toPlainText()
    assert w._config_created is True


def test_config_creation_reveal_error_with_failing_log(mkwin, monkeypatch):
    w = mkwin()
    monkeypatch.setattr(w, "repo_input", Boom())
    monkeypatch.setattr(w, "append_log", Boom())
    w._create_installation_config()
    assert w._config_created is True


def test_config_creation_retries_when_inputs_missing(mkwin, monkeypatch):
    w = mkwin()
    del w.repo_input
    delayed = []
    monkeypatch.setattr(QtCore.QTimer, "singleShot", staticmethod(lambda ms, fn=None: delayed.append((ms, fn))))
    w._create_installation_config()
    assert delayed and delayed[0][0] == 120
    assert getattr(w, "_config_created", False) is False


def test_set_focus_failure_is_ignored(mkwin, monkeypatch):
    w = mkwin()
    monkeypatch.setattr(w.repo_input, "setFocus", Boom())
    w._create_installation_config()
    assert w._config_created is True


def _fail_stylesheet_containing(monkeypatch, marker):
    orig = QtWidgets.QWidget.setStyleSheet

    def patched(self, sheet):
        if marker in sheet:
            raise RuntimeError("style")
        return orig(self, sheet)

    monkeypatch.setattr(QtWidgets.QWidget, "setStyleSheet", patched)


@pytest.mark.parametrize("marker", ["stop:0 rgba(250,250,255,255)", "QPushButton { background: qlineargradient"])
def test_construction_survives_stylesheet_failures(mkwin, monkeypatch, marker):
    _fail_stylesheet_containing(monkeypatch, marker)
    w = mkwin()
    assert w.start_button is not None and w.get_started is not None


def test_construction_survives_shadow_effect_failure(mkwin, monkeypatch):
    monkeypatch.setattr(QtWidgets, "QGraphicsDropShadowEffect", Boom())
    w = mkwin()
    assert w.title_label is not None


def test_construction_without_welcome_card(mkwin, monkeypatch):
    monkeypatch.setattr(QtWidgets, "QFrame", Boom())
    w = mkwin()
    assert not hasattr(w, "_welcome_card")
    assert w.start_button is not None


def test_construction_without_toolbar(mkwin, monkeypatch):
    real = QtWidgets.QPushButton

    def factory(*a, **k):
        if a and a[0] == "Settings":
            raise RuntimeError("no settings")
        return real(*a, **k)

    monkeypatch.setattr(QtWidgets, "QPushButton", factory)
    w = mkwin()
    assert w._settings_btn is None


def test_construction_survives_progress_bar_height_failure(mkwin, monkeypatch):
    orig = QtWidgets.QWidget.setFixedHeight

    def patched(self, h):
        if h == 20:
            raise RuntimeError("height")
        return orig(self, h)

    monkeypatch.setattr(QtWidgets.QWidget, "setFixedHeight", patched)
    assert mkwin().progress_bar is not None


def test_toolbar_buttons(mkwin, gui, boxes, dialogs):
    w = mkwin(state={"theme": "light"})
    click(w._send_logs_btn)  # no log configured -> warning, no crash
    assert boxes.calls[-1][1] == "No Logs"
    dialogs.script = lambda d: dialogs.click(d, "Save Settings")
    click(w._settings_btn)
    assert "Installer Settings" in dialogs.seen


def test_send_logs_button_swallows_errors(mkwin, monkeypatch):
    w = mkwin()
    monkeypatch.setattr(w, "_send_logs_report", Boom())
    click(w._send_logs_btn)


# ---------------------------------------------------------------- log display / stages

def test_append_log_progress_messages(mkwin):
    w = mkwin()
    w.append_log("45:Installing things ")
    assert w.progress_bar.value() == 45
    assert "[45%] Installing things" in w._log_viewer.toPlainText()
    assert "[45%] Installing things" in w.progress_output.toPlainText()
    w.append_log("250:clamped")
    assert w.progress_bar.value() == 100


def test_append_log_generic_message(mkwin):
    w = mkwin()
    w.append_log("hello there")
    assert "hello there" in w._log_viewer.toPlainText()
    assert "hello there" in w.progress_output.toPlainText()


def test_append_log_without_log_viewer(mkwin):
    w = mkwin()
    w._log_viewer = None
    w.append_log("12:x")
    w.append_log("plain")
    assert w.progress_bar.value() == 12


def test_append_log_widget_failures_do_not_raise(mkwin):
    w = mkwin()
    w.progress_output = Boom()
    w._log_viewer = Boom()
    w.append_log("12:x")
    w.append_log("plain")
    w.append_log("stage:clone:ok")


def test_append_log_progress_bar_failure_falls_back_to_generic(mkwin):
    w = mkwin()
    w.progress_bar = Boom()
    w.append_log("33:boom")
    assert "33:boom" in w.progress_output.toPlainText()


def test_append_log_stage_message_updates_badge(mkwin):
    w = mkwin()
    click(w.get_started)
    assert wait_until(lambda: getattr(w, "_config_created", False))
    w.append_log("stage:clone:started")
    assert w._stage_labels["clone"][0].text() == "⏳"
    w.append_log("stage:clone:ok")
    assert w._stage_labels["clone"][0].text() == "✅"
    w.append_log("stage:short")  # malformed, ignored
    pump(None, 600)  # let badge animations run to completion


def test_stage_message_handler_error_is_swallowed(mkwin, monkeypatch):
    w = mkwin()
    monkeypatch.setattr(w, "_set_stage_state", Boom())
    w.append_log("stage:clone:ok")


def test_set_stage_state_all_states(mkwin):
    w = mkwin()
    badge = QtWidgets.QLabel("1")
    w._stage_labels = {"a": (badge, 7), "b": badge}
    w._set_stage_state("a", "started")
    assert badge.text() == "⏳"
    w._set_stage_state("a", "fail")
    assert badge.text() == "❌"
    w._set_stage_state("a", "ok")
    assert badge.text() == "✅"
    w._set_stage_state("a", "reset")
    assert badge.text() == "7"
    w._set_stage_state("b", "reset")  # non-tuple entry keeps its text
    assert badge.text() == "7"
    w._set_stage_state("missing", "ok")
    pump(None, 50)


def test_set_stage_state_error_paths(mkwin, monkeypatch):
    w = mkwin()
    w._stage_labels = {"x": (Boom(), 1)}
    w._set_stage_state("x", "ok")
    badge = QtWidgets.QLabel("1")
    w._stage_labels = {"y": (badge, 1)}
    monkeypatch.setattr(w, "_animate_badge", Boom())
    w._set_stage_state("y", "ok")
    assert badge.text() == "✅"


def test_animate_badge_runs_and_reuses_effect(mkwin):
    w = mkwin()
    badge = QtWidgets.QLabel("1")
    badge.show()
    w._animate_badge(badge)
    first = badge._opacity_effect
    w._animate_badge(badge)
    assert badge._opacity_effect is first
    pump(None, 600)


def test_animate_badge_failure_modes(mkwin, monkeypatch):
    w = mkwin()
    badge = QtWidgets.QLabel("1")
    monkeypatch.setattr(QtWidgets, "QGraphicsOpacityEffect", Boom())
    w._animate_badge(badge)  # no effect available, pulse still works
    assert not hasattr(badge, "_opacity_effect")
    monkeypatch.setattr(QtCore, "QPropertyAnimation", Boom())
    w._animate_badge(badge)  # pulse fails silently

    class Hostile:
        @property
        def _opacity_effect(self):
            raise RuntimeError("x")

    w._animate_badge(Hostile())


# ---------------------------------------------------------------- persisted state

def test_state_roundtrip(mkwin, gui):
    w = mkwin(state={"logs_visible": True, "log_height": 120, "theme": "dark",
                     "speaker_lock_enabled": True, "speaker_lock_threshold": 0.9})
    assert w._toggle_logs_btn.isChecked() and w._log_viewer.isVisible()
    assert w._log_viewer.height() == 120
    assert w._theme == "dark"
    assert w._speaker_lock_enabled is True and w._speaker_lock_threshold == 0.9
    w._save_ui_state()
    saved = json.loads(w._config_path().read_text())
    assert saved["theme"] == "dark" and saved["speaker_lock_threshold"] == 0.9 and saved["logs_visible"] is True


def test_state_ignores_tiny_log_height(mkwin):
    w = mkwin(state={"log_height": 10, "theme": "light"})
    assert w._log_viewer.height() >= 40 and w._theme == "light"


@pytest.mark.parametrize("detected, expected", [(True, "dark"), (False, "light"), (None, "light")])
def test_auto_theme_uses_system_detection(mkwin, gui, monkeypatch, detected, expected):
    monkeypatch.setattr(gui, "detect_system_dark_mode", lambda: detected)
    w = mkwin(state={"theme": "auto"})
    assert w._theme == expected


def test_corrupt_state_file_is_ignored(mkwin):
    w = mkwin(state="{not json")
    assert not hasattr(w, "_theme")


def test_state_application_error_is_ignored(mkwin, gui, monkeypatch):
    monkeypatch.setattr(gui.InstallerWindow, "_apply_theme", Boom())
    w = mkwin(state={"theme": "dark"})
    assert w is not None


def test_config_path_without_appdirs(mkwin, gui, monkeypatch):
    monkeypatch.setattr(gui, "appdirs", None)
    w = mkwin()
    assert w._config_path() == Path.home() / ".luister" / "installer_ui.json"
    assert w.install_dir_input.text() == str(Path.home())


def test_config_path_falls_back_when_appdirs_breaks(mkwin, gui, monkeypatch):
    w = mkwin()
    monkeypatch.setattr(gui, "appdirs", Boom())
    assert w._config_path() == Path.home() / ".luister_installer_ui.json"


def test_save_state_write_failure_is_ignored(mkwin, monkeypatch):
    w = mkwin(state={"theme": "light"})

    def boom(self, *a, **k):
        raise OSError("ro")

    monkeypatch.setattr(Path, "write_text", boom)
    w._save_ui_state()


def test_logs_toggle_persists_state(mkwin):
    w = mkwin(state={"theme": "light"})
    w._toggle_logs_btn.setChecked(True)
    assert w._toggle_logs_btn.text() == "Hide logs" and w._log_viewer.isVisible()
    assert json.loads(w._config_path().read_text())["logs_visible"] is True
    w._toggle_logs_btn.setChecked(False)
    assert w._toggle_logs_btn.text() == "Show logs"


def test_logs_toggle_survives_save_failure(mkwin, monkeypatch):
    w = mkwin()
    monkeypatch.setattr(w, "_save_ui_state", Boom())
    w._toggle_logs_btn.setChecked(True)
    assert w._log_viewer.isVisible()


def test_close_event_saves_state(mkwin):
    w = mkwin(state={"theme": "dark"})
    cfg = w._config_path()
    cfg.unlink()
    w.close()
    assert json.loads(cfg.read_text())["theme"] == "dark"


def test_close_event_tolerates_failures(mkwin, monkeypatch):
    w = mkwin()
    monkeypatch.setattr(w, "_save_ui_state", Boom())
    ev = SimpleNamespace(accepted=False, accept=lambda: setattr(ev, "accepted", True))
    w.closeEvent(ev)  # super().closeEvent rejects the fake event -> accept() fallback
    assert ev.accepted


# ---------------------------------------------------------------- theming

def test_apply_theme_dark_and_light(mkwin):
    w = mkwin()
    click(w.get_started)
    assert wait_until(lambda: getattr(w, "_config_created", False))
    w._theme_btn = QtWidgets.QPushButton()
    w._apply_theme("dark")
    assert "rgba(20,24,28" in w.centralWidget().styleSheet()
    assert w._theme_btn.text() == "☀️"
    assert "#E6EEF8" in w.title_label.styleSheet()
    assert "#0b1b2b" not in w._stage_labels["clone"][0].styleSheet()
    w._apply_theme("light")
    assert w._theme_btn.text() == "🌙"
    assert "#2b2b2b" in w.title_label.styleSheet() and "#0b1b2b" in w._stage_labels["clone"][0].styleSheet()


def test_apply_theme_component_failures(mkwin):
    w = mkwin()
    w.centralWidget = lambda: Boom()
    w._welcome_card = Boom()
    w.title_label = Boom()
    w.get_started = Boom()
    w._stage_labels = {"a": (Boom(), 1), "b": Boom()}
    w._apply_theme("dark")
    w._stage_labels = None  # iterating fails
    w._apply_theme("light")
    assert w._theme == "light"


def test_apply_theme_total_failure_is_swallowed(mkwin):
    mkwin()._apply_theme(EqBoom())


# ---------------------------------------------------------------- settings dialog & speaker lock

def pick(dlg, text):
    for r in dlg.findChildren(QtWidgets.QRadioButton):
        if r.text() == text:
            r.setChecked(True)
            return
    raise AssertionError(text)


def test_settings_switch_to_dark_and_set_speaker_options(mkwin, dialogs):
    w = mkwin(state={"theme": "light"})

    def script(dlg):
        pick(dlg, "Dark")
        dlg.findChildren(QtWidgets.QCheckBox)[0].setChecked(True)
        dlg.findChildren(QtWidgets.QSlider)[0].setValue(90)
        dialogs.click(dlg, "Save Settings")

    dialogs.script = script
    w._open_settings_dialog()
    assert w._theme == "dark"
    saved = json.loads(w._config_path().read_text())
    assert saved["theme"] == "dark" and saved["speaker_lock_enabled"] is True
    assert saved["speaker_lock_threshold"] == 0.9


@pytest.mark.parametrize("current, choose, expected", [("dark", "Light", "light"), ("auto", "Auto (System)", "auto"),
                                                       ("light", "Auto (System)", "auto")])
def test_settings_theme_choices(mkwin, dialogs, current, choose, expected):
    w = mkwin(state={"theme": current})
    w._theme = current
    dialogs.script = lambda d: (pick(d, choose), dialogs.click(d, "Save Settings"))
    w._open_settings_dialog()
    assert w._theme == expected


def test_settings_without_theme_selection_keeps_theme(mkwin, dialogs):
    w = mkwin(state={"theme": "light"})

    def script(dlg):
        for r in dlg.findChildren(QtWidgets.QRadioButton):
            r.setAutoExclusive(False)
            r.setChecked(False)

    dialogs.script = script
    w._open_settings_dialog()
    assert w._theme == "light"


def test_settings_speaker_persistence_failure_is_ignored(mkwin, dialogs, monkeypatch):
    w = mkwin(state={"theme": "light"})
    dialogs.script = lambda d: setattr(w, "_speaker_enable_cb", Boom())
    w._open_settings_dialog()


def test_settings_load_sample_button_enrolls(mkwin, gui, dialogs, boxes, monkeypatch, tmp_path):
    w = mkwin(state={"theme": "light"})
    w._open_settings_dialog()
    wav = tmp_path / "me.wav"
    wav.write_bytes(b"RIFF")
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(wav), "")))
    seen = []
    monkeypatch.setattr(gui, "speaker_fingerprint", SimpleNamespace(enroll_speaker=lambda p: (seen.append(p), "spk-1")[1]))
    w._load_sample_btn.click()
    assert w._speaker_status_lbl.text() == "Enrolled as speaker ID: spk-1"
    assert seen and not Path(seen[0]).exists()
    assert boxes.calls[-1][1] == "Enrollment successful"


def test_settings_load_sample_cancelled(mkwin, dialogs, boxes, monkeypatch):
    w = mkwin(state={"theme": "light"})
    w._open_settings_dialog()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    w._load_sample_btn.click()
    assert boxes.calls == []


def test_settings_load_sample_dialog_error(mkwin, dialogs, boxes, monkeypatch):
    w = mkwin(state={"theme": "light"})
    w._open_settings_dialog()

    def boom(*a, **k):
        raise RuntimeError("no dialog")

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", staticmethod(boom))
    w._load_sample_btn.click()
    assert boxes.calls[-1][1] == "Enrollment failed"


def test_settings_sample_hook_failure_is_ignored(mkwin, dialogs):
    w = mkwin(state={"theme": "light"})
    dialogs.script = lambda d: setattr(w, "_load_sample_btn", Boom())
    w._open_settings_dialog()


def test_settings_without_loaded_state_uses_default_theme(mkwin, dialogs):
    # Fresh installs have no saved UI state; the settings dialog must still open.
    w = mkwin()
    dialogs.script = lambda d: dialogs.click(d, "Save Settings")
    w._open_settings_dialog()
    assert w._theme == "light"


def test_settings_survive_without_prior_state_file_in_save(mkwin, dialogs):
    w = mkwin()
    w._theme = "light"
    dialogs.script = lambda d: dialogs.click(d, "Save Settings")
    w._open_settings_dialog()
    assert w._config_path().exists()


def test_enroll_requires_speaker_module(mkwin, gui, boxes, monkeypatch, tmp_path):
    w = mkwin()
    monkeypatch.setattr(gui, "speaker_fingerprint", None)
    w._enroll_from_wav(tmp_path / "x.wav")
    assert boxes.calls[-1][1] == "Speaker lock not available"


def test_enroll_unreadable_wav(mkwin, gui, boxes, monkeypatch, tmp_path):
    w = mkwin()
    monkeypatch.setattr(gui, "speaker_fingerprint", SimpleNamespace(enroll_speaker=lambda p: "id"))
    w._enroll_from_wav(tmp_path / "missing.wav")
    assert boxes.calls[-1][1] == "Error reading WAV"


def test_read_wav_file(mkwin, boxes, tmp_path):
    w = mkwin()
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"abc")
    assert w._read_wav_file(wav) == b"abc"
    assert w._read_wav_file(tmp_path / "nope.wav") is None


def test_enroll_rejected_sample(mkwin, gui, boxes, monkeypatch, tmp_path):
    w = mkwin(state={"theme": "light"})
    w._speaker_status_lbl = QtWidgets.QLabel()
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"abc")
    monkeypatch.setattr(gui, "speaker_fingerprint", SimpleNamespace(enroll_speaker=lambda p: None))
    w._enroll_from_wav(wav)
    assert w._speaker_status_lbl.text() == "Enrollment failed"
    assert boxes.calls[-1][1] == "Enrollment failed"


def test_enroll_engine_error_and_cleanup_failure(mkwin, gui, boxes, monkeypatch, tmp_path):
    w = mkwin()
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"abc")

    def explode(p):
        raise RuntimeError("model missing")

    monkeypatch.setattr(gui, "speaker_fingerprint", SimpleNamespace(enroll_speaker=explode))

    def no_unlink(self, *a, **k):
        raise OSError("locked")

    monkeypatch.setattr(Path, "unlink", no_unlink)
    w._enroll_from_wav(wav)
    assert "model missing" in boxes.calls[-1][2]


# ---------------------------------------------------------------- Windows taskbar icon

def _win_ctypes(hicon=1, appid_error=None, send_error=None):
    sent = []

    def send(*a):
        if send_error:
            raise send_error
        sent.append(a)

    def appid(x):
        if appid_error:
            raise appid_error

    windll = SimpleNamespace(
        shell32=SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=appid),
        user32=SimpleNamespace(LoadImageW=lambda *a: hicon, SendMessageW=send),
    )
    return SimpleNamespace(windll=windll, sent=sent)


def test_taskbar_icon_sets_small_and_big_icons(mkwin, gui, monkeypatch):
    w = mkwin()
    fake = _win_ctypes()
    monkeypatch.setattr(gui, "ctypes", fake)
    w._set_windows_taskbar_icon(1234, "icon.ico")
    assert [(a[0], a[2]) for a in fake.sent] == [(1234, 0), (1234, 1)]


def test_taskbar_icon_edge_cases(mkwin, gui, monkeypatch):
    w = mkwin()
    monkeypatch.setattr(gui, "ctypes", None)
    w._set_windows_taskbar_icon(1, "i.ico")

    fake = _win_ctypes(hicon=0, appid_error=OSError())  # appid failure ignored, no icon -> return
    monkeypatch.setattr(gui, "ctypes", fake)
    w._set_windows_taskbar_icon(1, "i.ico")
    assert fake.sent == []

    fake = _win_ctypes()
    monkeypatch.setattr(gui, "ctypes", fake)
    w._set_windows_taskbar_icon("not-a-handle", "i.ico")
    assert fake.sent == []

    fake = _win_ctypes(send_error=OSError("denied"))
    monkeypatch.setattr(gui, "ctypes", fake)
    w._set_windows_taskbar_icon(1, "i.ico")

    monkeypatch.setattr(gui, "ctypes", SimpleNamespace())  # no windll at all
    w._set_windows_taskbar_icon(1, "i.ico")
