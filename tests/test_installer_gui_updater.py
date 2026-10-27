"""End-to-end style tests for luister.installer_gui.updater (hermetic)."""

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

import luister.installer_gui as pkg
from luister.installer_gui import updater as upd
from PySide6 import QtCore, QtGui, QtWidgets

QMessageBox = QtWidgets.QMessageBox


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


class _Bot:
    """Minimal pytest-qt replacement (pytest-qt is bound to PyQt6, windows use PySide6)."""

    def __init__(self):
        self.widgets = []

    def addWidget(self, w):
        self.widgets.append(w)

    def waitUntil(self, cond, timeout=5000):
        import time
        end = time.time() + timeout / 1000
        while time.time() < end:
            QtWidgets.QApplication.processEvents()
            if cond():
                return
            QtCore.QThread.msleep(10)
        raise AssertionError("condition not met")


@pytest.fixture
def qtbot(qapp):
    bot = _Bot()
    yield bot
    for w in bot.widgets:
        w.close()
        w.deleteLater()


@pytest.fixture
def boxes(monkeypatch):
    calls = []
    for name in ("information", "critical", "warning"):
        monkeypatch.setattr(
            QMessageBox, name,
            staticmethod(lambda *a, _n=name, **k: calls.append((_n, a[1:])))
        )
    return calls


class Boom:
    """Widget stand-in whose every call raises."""

    def __getattr__(self, name):
        def f(*a, **k):
            raise RuntimeError("boom")
        return f


def collect(worker):
    prog, fin = [], []
    worker.progress.connect(prog.append)
    worker.finished.connect(lambda ok, msg: fin.append((ok, msg)))
    return prog, fin


@pytest.fixture
def install(tmp_path):
    d = tmp_path / "inst"
    d.mkdir()
    return d


@pytest.fixture
def happy(monkeypatch):
    """Mock git/venv/subprocess boundaries; returns the recorded subprocess calls."""
    calls = []

    class Origin:
        def pull(self):
            calls.append("pull")

    class Repo:
        def __init__(self, path):
            self.remotes = types.SimpleNamespace(origin=Origin())

    monkeypatch.setattr(upd, "Repo", Repo)
    monkeypatch.setattr(upd.venv, "create", lambda *a, **k: calls.append(("venv", a)))
    monkeypatch.setattr(upd.subprocess, "check_call", lambda cmd, **k: calls.append(cmd))
    return calls


# ---------------------------------------------------------------- helpers

def test_now_iso():
    assert upd.now_iso().endswith("Z")


def test_venv_python_paths(install, monkeypatch):
    w = upd.UpdaterWorker(str(install))
    assert w._venv_python(install / ".venv") == install / ".venv" / "bin" / "python"
    monkeypatch.setattr(upd, "os", types.SimpleNamespace(name="nt"))
    assert w._venv_python(install / ".venv") == install / ".venv" / "Scripts" / "python.exe"


def test_worker_log_path_none_when_missing(tmp_path):
    assert upd.UpdaterWorker(str(tmp_path / "nope")).log_path is None


def test_create_launcher_writes_executable(install):
    w = upd.UpdaterWorker(str(install))
    p = install / "l.py"
    w._create_launcher(p, Path("/x/python"))
    assert "/x/python" in p.read_text()
    assert p.stat().st_mode & 0o111


def test_create_launcher_swallow_errors(install, monkeypatch):
    w = upd.UpdaterWorker(str(install))
    p = install / "l.py"

    def bad_chmod(self, mode):
        raise OSError("no")

    monkeypatch.setattr(Path, "chmod", bad_chmod)
    w._create_launcher(p, Path("/x/python"))
    assert p.exists()

    def bad_write(self, *a, **k):
        raise OSError("ro")

    monkeypatch.setattr(Path, "write_text", bad_write)
    w._create_launcher(install / "other.py", Path("/x/python"))
    assert not (install / "other.py").exists()


# ---------------------------------------------------------------- worker run

def test_run_success_creates_venv_and_launcher(install, happy):
    w = upd.UpdaterWorker(str(install))
    prog, fin = collect(w)
    w.run()
    assert fin == [(True, str(install.resolve()))]
    assert "stage:all:ok" in prog
    assert "pull" in happy
    assert any(c[0] == "venv" for c in happy if isinstance(c, tuple))
    assert (install / "luister-launcher.py").exists()
    assert (install / pkg.LOG_FILENAME).exists()
    assert any(c[-3:] == ["-m", "uv", "build"] for c in happy if isinstance(c, list))


def test_run_existing_venv_not_recreated(install, happy):
    (install / ".venv").mkdir()
    w = upd.UpdaterWorker(str(install))
    _, fin = collect(w)
    w.run()
    assert fin[0][0] is True
    assert not any(isinstance(c, tuple) for c in happy)


def test_run_build_fallback_to_pip_install(install, happy, monkeypatch):
    def cc(cmd, **k):
        happy.append(cmd)
        if cmd[-2:] == ["uv", "build"]:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(upd.subprocess, "check_call", cc)
    w = upd.UpdaterWorker(str(install))
    _, fin = collect(w)
    w.run()
    assert fin[0][0] is True
    assert happy[-1][-3:] == ["pip", "install", "."]


def test_run_missing_dir(tmp_path):
    w = upd.UpdaterWorker(str(tmp_path / "gone"))
    prog, fin = collect(w)
    w.run()
    assert fin[0][0] is False and "not found" in fin[0][1]
    assert "stage:locate:fail" in prog


def test_run_pull_failure_via_repo(install, happy, monkeypatch):
    class Repo:
        def __init__(self, p):
            raise RuntimeError("not a repo")

    monkeypatch.setattr(upd, "Repo", Repo)
    w = upd.UpdaterWorker(str(install))
    prog, fin = collect(w)
    w.run()
    assert fin == [(False, "Git pull failed: not a repo")]
    assert "stage:pull:fail" in prog


def test_run_git_cli_fallback(install, happy, monkeypatch):
    monkeypatch.setattr(upd, "Repo", None)
    monkeypatch.setattr(upd.shutil, "which", lambda n: "/usr/bin/git")
    w = upd.UpdaterWorker(str(install))
    _, fin = collect(w)
    w.run()
    assert fin[0][0] is True
    assert ["/usr/bin/git", "-C", str(install.resolve()), "pull"] in happy


def test_run_git_missing(install, happy, monkeypatch):
    monkeypatch.setattr(upd, "Repo", None)
    monkeypatch.setattr(upd.shutil, "which", lambda n: None)
    w = upd.UpdaterWorker(str(install))
    _, fin = collect(w)
    w.run()
    assert fin == [(False, "Git pull failed: git not found")]


def test_run_venv_failure(install, happy, monkeypatch):
    def bad(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(upd.venv, "create", bad)
    w = upd.UpdaterWorker(str(install))
    prog, fin = collect(w)
    w.run()
    assert fin == [(False, "Venv creation failed: disk full")]
    assert "stage:venv:fail" in prog


def test_run_deps_failure(install, happy, monkeypatch):
    def cc(cmd, **k):
        raise subprocess.CalledProcessError(2, cmd)

    monkeypatch.setattr(upd.subprocess, "check_call", cc)
    w = upd.UpdaterWorker(str(install))
    prog, fin = collect(w)
    w.run()
    assert fin[0][0] is False and fin[0][1].startswith("Dependency/install failed")
    assert "stage:deps:fail" in prog


def test_run_launcher_error_ignored(install, happy, monkeypatch):
    def bad(self, *a):
        raise RuntimeError("x")

    monkeypatch.setattr(upd.UpdaterWorker, "_create_launcher", bad)
    w = upd.UpdaterWorker(str(install))
    _, fin = collect(w)
    w.run()
    assert fin[0][0] is True


def test_run_unexpected_exception(install, happy, monkeypatch):
    w = upd.UpdaterWorker(str(install))
    _, fin = collect(w)
    # an emit failure on the very first progress call hits the outer handler
    real_emit = w.progress.emit
    n = {"c": 0}

    class P:
        def emit(self, m):
            n["c"] += 1
            if n["c"] == 1:
                raise RuntimeError("emit broke")
            real_emit(m)

    monkeypatch.setattr(w, "progress", P(), raising=False)
    w.run()
    assert fin == [(False, "emit broke")]


def test_run_without_logging(install, happy, monkeypatch):
    monkeypatch.setattr(upd, "write_log", None)
    w = upd.UpdaterWorker(str(install))
    _, fin = collect(w)
    w.run()
    assert fin[0][0] is True
    assert not (install / pkg.LOG_FILENAME).exists()


def test_run_dir_vanishes_before_run(install, monkeypatch):
    # the real write_log would mkdir the directory back, so record instead
    logged = []
    monkeypatch.setattr(upd, "write_log", lambda *a, **k: logged.append(a[3]))
    w = upd.UpdaterWorker(str(install))
    install.rmdir()
    _, fin = collect(w)
    w.run()
    assert fin[0][0] is False and "not found" in fin[0][1]
    assert "not_found" in logged


def test_run_failure_paths_without_logging(install, happy, monkeypatch, tmp_path):
    monkeypatch.setattr(upd, "write_log", None)
    # not found
    w = upd.UpdaterWorker(str(tmp_path / "gone"))
    w.run()
    # outer exception
    w = upd.UpdaterWorker(str(install))
    _, fin = collect(w)

    class P:
        def emit(self, m):
            raise RuntimeError("e")

    monkeypatch.setattr(w, "progress", P(), raising=False)
    w.run()
    assert fin[0][0] is False


# ---------------------------------------------------------------- window

@pytest.fixture
def win(qtbot, monkeypatch, tmp_path, boxes):
    png = tmp_path / "logo.png"
    img = QtGui.QImage(10, 10, QtGui.QImage.Format_RGB32)
    img.fill(0xFF0000)
    img.save(str(png))
    monkeypatch.setattr(pkg, "find_project_logo", lambda: png)
    w = upd.UpdaterWindow()
    qtbot.addWidget(w)
    return w


def test_window_defaults_and_toggle(win):
    win.show()
    assert win.windowTitle() == "Instyper Updater"
    assert win.install_dir_input.text()
    toggle = win.findChild(QtWidgets.QToolButton)
    toggle.click()
    assert win._log_viewer.isVisible()
    toggle.click()
    assert not win._log_viewer.isVisible()


def test_window_without_logo_and_appdirs(qtbot, monkeypatch, boxes):
    monkeypatch.setattr(pkg, "find_project_logo", lambda: None)
    monkeypatch.setattr(upd, "appdirs", None)
    w = upd.UpdaterWindow()
    qtbot.addWidget(w)
    assert w.install_dir_input.text() == str(Path.home())


def test_window_logo_lookup_error_and_card_error(qtbot, monkeypatch, boxes):
    def bad():
        raise RuntimeError("x")

    monkeypatch.setattr(pkg, "find_project_logo", bad)
    w = upd.UpdaterWindow()
    qtbot.addWidget(w)

    monkeypatch.setattr(QtWidgets, "QFrame", Boom)
    w2 = upd.UpdaterWindow()
    qtbot.addWidget(w2)


def test_window_progress_bar_height_error(qtbot, monkeypatch, boxes):
    class Bar(QtWidgets.QProgressBar):
        def setFixedHeight(self, h):
            raise RuntimeError("x")

    monkeypatch.setattr(QtWidgets, "QProgressBar", Bar)
    w = upd.UpdaterWindow()
    qtbot.addWidget(w)


def test_append_log_percent_and_plain(win):
    win.append_log("42: Working ")
    assert win.progress_bar.value() == 42
    assert "[42%] Working" in win.progress_output.toPlainText()
    win.append_log("250:Over")
    assert win.progress_bar.value() == 100
    win.append_log("stage:pull:ok")
    assert "stage:pull:ok" in win.progress_output.toPlainText()
    assert "stage:pull:ok" in win._log_viewer.toPlainText()


def test_append_log_error_tolerance(win):
    win._log_viewer = Boom()
    win.append_log("10:x")
    win.append_log("plain")
    win.progress_output = Boom()
    win.append_log("20:y")
    win.progress_bar = Boom()
    win.append_log("30:z")


def test_start_update_requires_dir(win, boxes):
    win.install_dir_input.setText("   ")
    QtTest = pytest.importorskip("PySide6.QtTest")
    QtTest.QTest.mouseClick(win.update_btn, QtCore.Qt.LeftButton)
    assert boxes[0][0] == "warning"
    assert win.thread is None


def test_full_update_success_via_thread(win, qtbot, boxes, install, happy):
    from PySide6.QtTest import QTest
    win.install_dir_input.setText(str(install))
    QTest.mouseClick(win.update_btn, QtCore.Qt.LeftButton)
    assert not win.update_btn.isEnabled()
    qtbot.waitUntil(lambda: any(b[0] == "information" for b in boxes), timeout=10000)
    assert win.progress_bar.value() == 100
    assert win.update_btn.isEnabled() and win.install_dir_input.isEnabled()
    assert "Update completed" in win.progress_output.toPlainText()
    qtbot.waitUntil(lambda: win.thread.isFinished(), timeout=5000)


def test_full_update_failure_via_thread(win, qtbot, boxes, tmp_path):
    from PySide6.QtTest import QTest
    win.install_dir_input.setText(str(tmp_path / "missing"))
    QTest.mouseClick(win.update_btn, QtCore.Qt.LeftButton)
    qtbot.waitUntil(lambda: any(b[0] == "critical" for b in boxes), timeout=10000)
    assert win.progress_bar.value() == 10
    qtbot.waitUntil(lambda: win.thread.isFinished(), timeout=5000)


def test_on_finished_error_tolerance(win, qtbot, boxes, monkeypatch):
    win.thread = types.SimpleNamespace(quit=lambda: 1 / 0)
    win.on_finished(True, "ok")
    win.thread = types.SimpleNamespace(quit=None)
    win.on_finished(True, "ok")
    win.thread = None

    class Broken(upd.UpdaterWindow):
        thread = property(lambda self: 1 / 0, lambda self, v: None)

    broken = Broken()
    qtbot.addWidget(broken)
    broken.on_finished(True, "ok")
    win.install_dir_input = Boom()
    win.on_finished(True, "ok")
    win.progress_bar = Boom()
    win.on_finished(False, "bad")

    def bad(*a, **k):
        raise RuntimeError("dlg")

    monkeypatch.setattr(QMessageBox, "information", staticmethod(bad))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(bad))
    win.on_finished(True, "ok")
    win.on_finished(False, "bad")


# ---------------------------------------------------------------- main

def test_main_runs_app(monkeypatch):
    shown = []

    class App:
        def __init__(self, argv):
            pass

        def exec_(self):
            return 7

    class W:
        def show(self):
            shown.append(1)

    monkeypatch.setattr(QtWidgets, "QApplication", App)
    monkeypatch.setattr(upd, "UpdaterWindow", W)
    assert upd.main() == 7
    assert shown


def test_main_without_gui(monkeypatch, capsys):
    monkeypatch.setattr(upd, "QtWidgets", None)
    assert upd.main() == 2
    assert "GUI not available" in capsys.readouterr().out


# ------------------------------------------- import-fallback module variants

def _load_copy(name="luister.installer_gui._updater_copy"):
    path = Path(upd.__file__)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
    return mod


def test_import_fallback_without_package_symbols_and_git(monkeypatch):
    for attr in ("QtWidgets", "QtCore", "QtGui", "write_log", "appdirs"):
        monkeypatch.delattr(pkg, attr)
    monkeypatch.setitem(sys.modules, "git", None)
    # QtCore is None in the fallback, so class creation fails after the fallback ran
    with pytest.raises(AttributeError):
        _load_copy()


def test_dummy_signal_fallback(monkeypatch):
    class FakeCore(types.SimpleNamespace):
        pass

    fake_core = FakeCore(QObject=object)
    monkeypatch.setattr(pkg, "QtCore", fake_core)
    monkeypatch.setattr(pkg, "QtWidgets", types.SimpleNamespace(QDialog=object))
    mod = _load_copy()
    sig = mod.UpdaterWorker._Signal(str)
    sig.connect(lambda: None)
    sig.emit("x")
