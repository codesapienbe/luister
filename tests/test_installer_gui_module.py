"""Module-level behaviour of luister.installer_gui: import fallbacks, logo lookup, dark-mode detection."""

import json
import pathlib
import platform
import subprocess
import sys
import types
from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtGui

from tests.test_installer_gui_common import (  # noqa: F401
    fake_pyqt5,
    gui,
    gui_app,
    load_fresh,
    proxy_without,
)


# ---------------------------------------------------------------- import fallbacks

def test_default_import_binds_to_available_qt(gui):
    assert gui.QtWidgets is not None
    assert gui.QTextCursor is QtGui.QTextCursor
    assert hasattr(gui, "InstallerWindow")


def test_optional_dependencies_missing(monkeypatch, gui_app):
    mod = load_fresh(
        monkeypatch,
        block=["PIL", "ctypes", "git", "appdirs", "pyshortcuts", "luister.speaker_fingerprint", "PySide6.QtSvg"],
    )
    assert mod.Image is None
    assert mod.ctypes is None
    assert mod.Repo is None
    assert mod.GitCommandError is Exception
    assert mod.appdirs is None
    assert mod.make_shortcut is None
    assert mod.speaker_fingerprint is None
    assert mod.QSvgRenderer is None


def test_optional_dependencies_present(monkeypatch, gui_app):
    fp = types.ModuleType("luister.speaker_fingerprint")
    winreg = types.ModuleType("winreg")
    mod = load_fresh(monkeypatch, fakes={"luister.speaker_fingerprint": fp, "winreg": winreg, **fake_pyqt5()})
    assert mod.speaker_fingerprint is fp
    assert mod.winreg is winreg
    assert mod.QSvgRenderer is not None
    assert mod.QtWidgets is not None


def test_non_windows_prefers_pyqt5_stub_then_pyside(monkeypatch, gui_app):
    mod = load_fresh(monkeypatch, fakes=fake_pyqt5(), system="Linux")
    assert mod.QtCore is QtCore


def test_windows_prefers_pyside6(monkeypatch, gui_app):
    mod = load_fresh(monkeypatch, system="Windows")
    assert mod.QtCore is QtCore


def test_windows_falls_back_to_pyqt5(monkeypatch, gui_app):
    mod = load_fresh(monkeypatch, block=["PySide6.QtWidgets"], fakes=fake_pyqt5(), system="Windows")
    assert mod.QtWidgets is not None


def test_windows_without_any_binding_and_main_exits(monkeypatch, capsys):
    mod = load_fresh(monkeypatch, block=["PySide6", "PyQt5", "PySide6.QtSvg"], system="Windows")
    assert mod.QtWidgets is None and mod.QtCore is None and mod.QtGui is None
    assert not hasattr(mod, "InstallerWindow")
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2
    assert "bindings not available" in capsys.readouterr().out


def test_no_binding_on_linux(monkeypatch):
    mod = load_fresh(monkeypatch, block=["PySide6", "PyQt5"], system="Linux")
    assert mod.QtWidgets is None


def test_qtextcursor_fallback_and_dummy_signal(monkeypatch, gui_app):
    qtgui = proxy_without(QtGui, "QTextCursor")
    qtcore = proxy_without(QtCore, "Signal", "pyqtSignal")
    mod = load_fresh(monkeypatch, fakes=fake_pyqt5(qtcore=qtcore, qtgui=qtgui), system="Linux")
    cursor = mod.QTextCursor()
    assert mod.QTextCursor.End == 0 and cursor is not None
    dummy = mod.InstallerWorker._Signal(str)
    assert dummy.connect(print) is None
    assert dummy.emit("x") is None


# ---------------------------------------------------------------- write_log

def test_write_log_appends_json_lines(gui, tmp_path):
    log = tmp_path / "sub" / "app.log"
    gui.write_log(log, "INFO", "comp", "msg", extra=1)
    gui.write_log(log, "WARN", "comp", "again")
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r["message"] for r in rows] == ["msg", "again"]
    assert rows[0]["extra"] == 1 and rows[0]["level"] == "INFO" and rows[0]["timestamp"]


def test_write_log_without_qtcore_uses_utc_clock(gui, tmp_path, monkeypatch):
    monkeypatch.setattr(gui, "QtCore", None)
    log = tmp_path / "plain.log"
    gui.write_log(log, "INFO", "c", "m")
    assert json.loads(log.read_text())["timestamp"].endswith("Z")


def test_write_log_swallows_errors(gui, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    gui.write_log(blocker / "x" / "app.log", "INFO", "c", "m")  # must not raise


# ---------------------------------------------------------------- find_project_logo

def test_logo_found_in_cwd(gui, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logo.png").write_bytes(b"x")
    assert gui.find_project_logo() == tmp_path / "logo.png"


def test_logo_prefers_packaging_svg(gui, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "packaging").mkdir()
    (tmp_path / "packaging" / "logo.svg").write_text("<svg/>")
    (tmp_path / "logo.png").write_bytes(b"x")
    assert gui.find_project_logo() == tmp_path / "packaging" / "logo.svg"


def test_logo_dedupes_cwd_equal_to_package_dir(gui, monkeypatch):
    monkeypatch.chdir(pathlib.Path(gui.__file__).parent)
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: False)
    assert gui.find_project_logo() is None


def test_logo_none_when_nothing_exists(gui, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: False)
    assert gui.find_project_logo() is None


# ---------------------------------------------------------------- detect_system_dark_mode

def _run_result(stdout="", stderr=""):
    return lambda *a, **k: SimpleNamespace(stdout=stdout, stderr=stderr)


def _winreg(value=None, open_exc=None, query_exc=None):
    closed = []

    def open_key(*a):
        if open_exc:
            raise open_exc
        return "key"

    def query(key, name):
        if query_exc:
            raise query_exc
        return value, 4

    return SimpleNamespace(HKEY_CURRENT_USER=0, OpenKey=open_key, QueryValueEx=query, CloseKey=closed.append, closed=closed)


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"value": 1}, False),
        ({"value": 0}, True),
        ({"query_exc": FileNotFoundError()}, None),
        ({"open_exc": OSError()}, None),
    ],
)
def test_dark_mode_windows(gui, monkeypatch, kwargs, expected):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(gui, "winreg", _winreg(**kwargs))
    assert gui.detect_system_dark_mode() is expected


def test_dark_mode_windows_without_winreg_falls_through(gui, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(gui, "winreg", None)
    monkeypatch.setattr(subprocess, "run", _run_result("'prefer-dark'"))
    assert gui.detect_system_dark_mode() is True


@pytest.mark.parametrize(
    "run, expected",
    [
        (_run_result("Dark\n"), True),
        (_run_result("", "The domain/default pair does not exist"), False),
    ],
)
def test_dark_mode_macos(gui, monkeypatch, run, expected):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(subprocess, "run", run)
    assert gui.detect_system_dark_mode() is expected


def test_dark_mode_macos_defaults_missing(gui, monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("defaults")

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(subprocess, "run", boom)
    assert gui.detect_system_dark_mode() is None


def _linux(monkeypatch, outputs):
    """outputs: list of stdout strings or Exceptions for successive gsettings calls."""
    it = iter(outputs)

    def run(*a, **k):
        v = next(it)
        if isinstance(v, Exception):
            raise v
        return SimpleNamespace(stdout=v, stderr="")

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(subprocess, "run", run)


@pytest.mark.parametrize(
    "outputs, expected",
    [
        (["'prefer-dark'\n"], True),
        (["'prefer-light'\n"], False),
        (["'default'\n", "'Adwaita-dark'\n"], True),
        (["'default'\n", "'Adwaita'\n"], False),
        ([OSError(), "'Yaru-Dark'"], True),
        ([OSError(), OSError()], None),
        (["", ""], None),
    ],
)
def test_dark_mode_linux_gsettings(gui, monkeypatch, outputs, expected):
    _linux(monkeypatch, outputs)
    assert gui.detect_system_dark_mode() is expected


@pytest.mark.parametrize(
    "ini, expected",
    [
        ("[Settings]\ngtk-theme-name=Adwaita-dark\n", True),
        ("[Settings]\ngtk-theme-name=Adwaita\n", False),
        ("[Settings]\ngtk-application-prefer-dark-theme=1\n", None),
    ],
)
def test_dark_mode_linux_gtk_ini(gui, monkeypatch, ini, expected):
    _linux(monkeypatch, ["", ""])
    cfg = pathlib.Path.home() / ".config" / "gtk-3.0"
    cfg.mkdir(parents=True)
    (cfg / "settings.ini").write_text(ini)
    assert gui.detect_system_dark_mode() is expected


def test_dark_mode_linux_ini_unreadable(gui, monkeypatch):
    _linux(monkeypatch, ["", ""])
    cfg = pathlib.Path.home() / ".config" / "gtk-3.0"
    cfg.mkdir(parents=True)
    (cfg / "settings.ini").write_text("gtk-theme-name=x\n")

    def boom(self, **k):
        raise OSError("denied")

    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    assert gui.detect_system_dark_mode() is None


def test_dark_mode_unexpected_error_returns_none(gui, monkeypatch):
    def boom():
        raise RuntimeError("no platform")

    monkeypatch.setattr(platform, "system", boom)
    assert gui.detect_system_dark_mode() is None
