"""Shared fixtures/helpers for the tests/test_installer_gui_*.py files (no tests here).

pyproject sets ``qt_api = pyqt6`` for pytest-qt, while the installer binds to
PySide6 in this environment, so these tests never use the ``qtbot``/``qapp``
fixtures and drive their own PySide6 QApplication instead.
"""

import importlib.util
import platform
import sys
import time
import types
from pathlib import Path

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

import luister.installer_gui  # noqa: F401  (import before any tests block optional modules)

SRC = Path(__file__).resolve().parents[1] / "src" / "luister" / "installer_gui" / "__init__.py"


@pytest.fixture(scope="session")
def gui_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def pump(app=None, ms=0):
    """Process Qt events for roughly ``ms`` milliseconds."""
    app = app or QtWidgets.QApplication.instance()
    end = time.monotonic() + ms / 1000.0
    app.processEvents()
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def wait_until(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QtWidgets.QApplication.instance().processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return bool(cond())


@pytest.fixture
def gui(gui_app):
    import luister.installer_gui as mod

    return mod


def load_fresh(monkeypatch, block=(), fakes=None, system=None):
    """Execute the installer module source from scratch under tweaked imports."""
    for name in block:
        monkeypatch.setitem(sys.modules, name, None)
    for name, mod in (fakes or {}).items():
        monkeypatch.setitem(sys.modules, name, mod)
    if system:
        monkeypatch.setattr(platform, "system", lambda: system)
    spec = importlib.util.spec_from_file_location("luister_installer_gui_fresh", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_pyqt5(qtcore=QtCore, qtgui=QtGui, svg=True):
    """Return a sys.modules mapping that makes ``import PyQt5`` resolve to PySide6 objects."""
    pkg = types.ModuleType("PyQt5")
    pkg.__path__ = []
    pkg.QtWidgets = QtWidgets
    pkg.QtCore = qtcore
    pkg.QtGui = qtgui
    mods = {"PyQt5": pkg}
    if svg:
        from PySide6 import QtSvg

        s = types.ModuleType("PyQt5.QtSvg")
        s.QSvgRenderer = QtSvg.QSvgRenderer
        mods["PyQt5.QtSvg"] = s
    return mods


def proxy_without(module, *names):
    p = types.ModuleType(module.__name__ + "_proxy")
    p.__dict__.update({k: v for k, v in vars(module).items() if k not in names})
    return p


class Boxes:
    def __init__(self):
        self.calls = []
        self.answer = QtWidgets.QMessageBox.Yes

    def kinds(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def boxes(monkeypatch):
    b = Boxes()
    for kind in ("warning", "information", "critical"):
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            kind,
            staticmethod(lambda parent, title, text, *a, _k=kind: b.calls.append((_k, title, text))),
        )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        staticmethod(lambda parent, title, text, *a: (b.calls.append(("question", title, text)), b.answer)[1]),
    )
    return b


class DialogDriver:
    """Replaces QDialog.exec_ so modal dialogs never block; ``script`` plays the user."""

    def __init__(self):
        self.script = None
        self.seen = []

    def click(self, dlg, text):
        for btn in dlg.findChildren(QtWidgets.QPushButton):
            if btn.text() == text:
                btn.click()
                return btn
        raise AssertionError(f"no button {text!r} in {dlg.windowTitle()!r}")


@pytest.fixture
def dialogs(monkeypatch):
    d = DialogDriver()

    def fake_exec(self):
        d.seen.append(self.windowTitle())
        if d.script:
            d.script(self)
        return 0

    monkeypatch.setattr(QtWidgets.QDialog, "exec_", fake_exec)
    return d


class SyncThread:
    """threading.Thread stand-in that runs the target inline (deterministic)."""

    def __init__(self, target=None, daemon=None, **kw):
        self.target = target

    def start(self):
        self.target()


@pytest.fixture
def deferred(monkeypatch, gui):
    """Capture QTimer.singleShot callables; run them on the test (GUI) thread."""
    calls = []
    monkeypatch.setattr(
        QtCore.QTimer, "singleShot", staticmethod(lambda ms, fn=None, *a: calls.append(fn))
    )

    def run():
        while calls:
            fn = calls.pop(0)
            if callable(fn):
                fn()

    run.calls = calls
    return run


@pytest.fixture
def window(gui, gui_app, monkeypatch, tmp_path):
    monkeypatch.setattr(gui, "find_project_logo", lambda: None)
    w = gui.InstallerWindow()
    w.show()
    yield w
    w.close()
    th = w.__dict__.get("thread")
    if th is not None:
        th.quit()
        th.wait(5000)
    w.deleteLater()
    pump()
