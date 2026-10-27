"""End-to-end style tests for luister.installer_gui.uninstaller (hermetic)."""

import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

import luister.installer_gui as pkg
from luister.installer_gui import uninstaller as un
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest

QMessageBox = QtWidgets.QMessageBox
LEFT = QtCore.Qt.LeftButton


@pytest.fixture(scope="session")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


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
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: calls.append(("question", a[1:])) or QMessageBox.Yes),
    )
    return calls


class Boom:
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
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "f.txt").write_text("x")
    return d


@pytest.fixture
def user_data(tmp_path, monkeypatch):
    ud = tmp_path / "userdata"
    ud.mkdir()
    (ud / "settings.json").write_text("{}")
    monkeypatch.setattr(un, "appdirs", types.SimpleNamespace(user_data_dir=lambda *a, **k: str(ud)))
    return ud


@pytest.fixture
def quiet_log(monkeypatch):
    """Record log calls without recreating deleted directories on disk."""
    logged = []
    monkeypatch.setattr(un, "write_log", lambda p, lvl, comp, msg, **kw: logged.append((lvl, msg)))
    return logged


# ---------------------------------------------------------------- worker

def test_worker_success_removes_everything(install, user_data):
    w = un.UninstallerWorker(str(install), True)
    prog, fin = collect(w)
    w.run()
    assert fin == [(True, str(install.resolve()))]
    assert "stage:remove_user:ok" in prog and "stage:all:ok" in prog
    assert not user_data.exists()
    # correct behaviour: the install dir must be gone afterwards (logging must not resurrect it)
    assert not install.exists()


def test_worker_keeps_user_data_when_not_requested(install, user_data, quiet_log):
    w = un.UninstallerWorker(str(install), False)
    _, fin = collect(w)
    w.run()
    assert fin[0][0] is True
    assert user_data.exists()
    assert not install.exists()


def test_worker_user_data_missing_and_no_appdirs(install, monkeypatch, quiet_log):
    monkeypatch.setattr(un, "appdirs", None)
    (Path.home() / ".luister").mkdir()
    w = un.UninstallerWorker(str(install), True)
    prog, fin = collect(w)
    w.run()
    assert fin[0][0] is True
    assert not (Path.home() / ".luister").exists()
    # and again when it does not exist at all
    install.mkdir()
    w = un.UninstallerWorker(str(install), True)
    _, fin = collect(w)
    w.run()
    assert fin[0][0] is True


def test_worker_user_data_removal_failure_is_not_fatal(install, user_data):
    real = un.shutil.rmtree

    def rm(path, *a, **k):
        if str(path) == str(user_data):
            raise PermissionError("locked")
        return real(path, *a, **k)

    un.shutil.rmtree = rm
    try:
        w = un.UninstallerWorker(str(install), True)
        prog, fin = collect(w)
        w.run()
    finally:
        un.shutil.rmtree = real
    assert "stage:remove_user:fail" in prog
    assert fin[0][0] is True
    assert user_data.exists()


def test_worker_missing_dir(tmp_path):
    w = un.UninstallerWorker(str(tmp_path / "nope"), False)
    prog, fin = collect(w)
    w.run()
    assert fin[0][0] is False and "not found" in fin[0][1]
    assert "stage:locate:fail" in prog


def test_worker_dir_vanishes_logs_not_found(install, quiet_log):
    w = un.UninstallerWorker(str(install), False)
    un.shutil.rmtree(str(install))
    _, fin = collect(w)
    w.run()
    assert fin[0][0] is False
    assert ("WARN", "not_found") in quiet_log


def _flaky_rmtree(monkeypatch, failures):
    real = un.shutil.rmtree
    state = {"n": 0}

    def rm(path, *a, **k):
        state["n"] += 1
        if state["n"] <= failures:
            raise PermissionError("denied")
        return real(path, *a, **k)

    monkeypatch.setattr(un.shutil, "rmtree", rm)


def test_worker_retry_after_chmod_succeeds(install, monkeypatch, quiet_log):
    _flaky_rmtree(monkeypatch, 1)
    real_chmod = Path.chmod
    seen = {"n": 0}

    def chmod(self, mode, *a, **k):
        seen["n"] += 1
        if seen["n"] == 1:
            raise OSError("per-file failure ignored")
        return real_chmod(self, mode, *a, **k)

    monkeypatch.setattr(Path, "chmod", chmod)
    w = un.UninstallerWorker(str(install), False)
    prog, fin = collect(w)
    w.run()
    assert fin[0][0] is True
    assert ("INFO", "removed_app_dir_after_chmod") in quiet_log
    assert seen["n"] >= 2


def test_worker_retry_after_chmod_succeeds_without_log(install, monkeypatch):
    _flaky_rmtree(monkeypatch, 1)
    monkeypatch.setattr(un, "write_log", None)
    w = un.UninstallerWorker(str(install), False)
    _, fin = collect(w)
    w.run()
    assert fin[0][0] is True


class FakeFile:
    def __init__(self, path):
        self.path = path


class FakeProc:
    def __init__(self, pid=1, name="p", cmdline=None, files=(), info=True, name_raises=False, files_raises=False):
        self.pid = pid
        self._name = name
        self.info = {"cmdline": cmdline} if info else None
        self._files = files
        self._name_raises = name_raises
        self._files_raises = files_raises

    def name(self):
        if self._name_raises:
            raise RuntimeError("gone")
        return self._name

    def open_files(self):
        if self._files_raises:
            raise RuntimeError("denied")
        return self._files


def fake_psutil(monkeypatch, procs=None, raises=False):
    def process_iter(attrs):
        if raises:
            raise RuntimeError("psutil broke")
        return iter(procs)

    monkeypatch.setitem(sys.modules, "psutil", types.SimpleNamespace(process_iter=process_iter))


def test_worker_removal_fails_reports_blockers(install, monkeypatch, quiet_log):
    _flaky_rmtree(monkeypatch, 2)
    holder = str(install.resolve())
    procs = [
        FakeProc(10, "editor", ["vim", "x"], files=[FakeFile(holder + "/sub/f.txt")]),
        FakeProc(11, "other", [], files=[FakeFile("/elsewhere"), FakeFile(None)]),
        FakeProc(12, "bad-file", None, files=[object()]),
        FakeProc(13, "denied", None, files_raises=True),
        FakeProc(14, "nameless", None, info=False),
        FakeProc(15, "namefail", None, name_raises=True),
    ]
    fake_psutil(monkeypatch, procs)
    w = un.UninstallerWorker(str(install), False)
    prog, fin = collect(w)
    w.run()
    ok, msg = fin[0]
    assert ok is False
    assert "blocking processes: 10:editor" in msg
    assert "stage:remove_app:fail" in prog
    assert any(m == "remove_app_failed" for _, m in quiet_log)


@pytest.mark.parametrize("mode", ["missing", "raises"])
def test_worker_removal_fails_without_blocker_info(install, monkeypatch, mode):
    _flaky_rmtree(monkeypatch, 2)
    if mode == "missing":
        monkeypatch.setitem(sys.modules, "psutil", None)
    else:
        fake_psutil(monkeypatch, raises=True)

    def bad_log(*a, **k):
        if a[3] == "remove_app_failed":
            raise RuntimeError("log broke")

    monkeypatch.setattr(un, "write_log", bad_log)
    w = un.UninstallerWorker(str(install), False)
    _, fin = collect(w)
    w.run()
    assert fin[0][0] is False
    assert fin[0][1].startswith("Failed removing application: denied")
    assert "blocking processes" not in fin[0][1]


def test_worker_removal_fails_without_logging(install, monkeypatch):
    _flaky_rmtree(monkeypatch, 2)
    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(un, "write_log", None)
    w = un.UninstallerWorker(str(install), False)
    _, fin = collect(w)
    w.run()
    assert fin[0][0] is False


def test_worker_unexpected_exception(install, quiet_log):
    w = un.UninstallerWorker(str(install), False)
    _, fin = collect(w)

    class P:
        def emit(self, m):
            raise RuntimeError("emit broke")

    w.progress = P()
    w.run()
    assert fin == [(False, "emit broke")]
    assert ("ERROR", "failed") in quiet_log


def test_worker_unexpected_exception_without_logging(install, monkeypatch):
    monkeypatch.setattr(un, "write_log", None)
    w = un.UninstallerWorker(str(install), False)
    _, fin = collect(w)

    class P:
        def emit(self, m):
            raise RuntimeError("emit broke")

    w.progress = P()
    w.run()
    assert fin[0][0] is False


def test_worker_no_logging_happy_and_missing(install, tmp_path, monkeypatch, user_data):
    monkeypatch.setattr(un, "write_log", None)
    w = un.UninstallerWorker(str(install), True)
    _, fin = collect(w)
    w.run()
    assert fin[0][0] is True
    w = un.UninstallerWorker(str(tmp_path / "nope"), False)
    w.run()


def test_worker_user_data_failure_without_logging(install, monkeypatch):
    monkeypatch.setattr(un, "write_log", None)
    monkeypatch.setattr(un, "appdirs", types.SimpleNamespace(user_data_dir=lambda *a, **k: 1 / 0))
    w = un.UninstallerWorker(str(install), True)
    prog, fin = collect(w)
    w.run()
    assert "stage:remove_user:fail" in prog and fin[0][0] is True


# ---------------------------------------------------------------- window construction

@pytest.fixture
def win(qtbot, boxes, monkeypatch, tmp_path):
    from PySide6 import QtGui
    png = tmp_path / "logo.png"
    img = QtGui.QImage(10, 10, QtGui.QImage.Format_RGB32)
    img.fill(0xFF0000)
    img.save(str(png))
    monkeypatch.setattr(pkg, "find_project_logo", lambda: png)
    monkeypatch.setitem(sys.modules, "psutil", types.SimpleNamespace(process_iter=lambda a: iter([])))
    w = un.UninstallerWindow()
    qtbot.addWidget(w)
    return w


def test_window_defaults_and_details_toggle(win):
    win.show()
    assert win.windowTitle() == "Luister Uninstaller"
    assert win.install_dir_input.text()
    assert not win.remove_user_cb.isChecked()
    toggle = win.findChild(QtWidgets.QToolButton)
    QTest.mouseClick(toggle, LEFT)
    assert win._log_viewer.isVisible()
    QTest.mouseClick(toggle, LEFT)
    assert not win._log_viewer.isVisible()


def test_window_without_logo_and_appdirs(qtbot, boxes, monkeypatch):
    monkeypatch.setattr(pkg, "find_project_logo", lambda: None)
    monkeypatch.setattr(un, "appdirs", None)
    w = un.UninstallerWindow()
    qtbot.addWidget(w)
    assert w.install_dir_input.text() == str(Path.home())


def test_window_construction_error_tolerance(qtbot, boxes, monkeypatch):
    def bad():
        raise RuntimeError("x")

    monkeypatch.setattr(pkg, "find_project_logo", bad)
    qtbot.addWidget(un.UninstallerWindow())

    class Bar(QtWidgets.QProgressBar):
        def setFixedHeight(self, h):
            raise RuntimeError("x")

    monkeypatch.setattr(QtWidgets, "QProgressBar", Bar)
    qtbot.addWidget(un.UninstallerWindow())
    monkeypatch.setattr(QtWidgets, "QFrame", Boom)
    qtbot.addWidget(un.UninstallerWindow())


def test_append_log(win):
    win.append_log("42: Working ")
    assert win.progress_bar.value() == 42
    assert "[42%] Working" in win.progress_output.toPlainText()
    win.append_log("999:big")
    assert win.progress_bar.value() == 100
    win.append_log("stage:x:ok")
    assert "stage:x:ok" in win._log_viewer.toPlainText()


def test_append_log_error_tolerance(win):
    win._log_viewer = Boom()
    win.append_log("10:x")
    win.append_log("plain")
    win.progress_output = Boom()
    win.append_log("20:y")
    win.progress_bar = Boom()
    win.append_log("30:z")


# ---------------------------------------------------------------- process detection

def _procs(monkeypatch, entries):
    class P:
        def __init__(self, info):
            if info is None:
                raise_ = True
            self.info = info

    class Bad:
        @property
        def info(self):
            raise RuntimeError("vanished")

    items = [Bad() if e is None else P(e) for e in entries]
    monkeypatch.setitem(sys.modules, "psutil", types.SimpleNamespace(process_iter=lambda a: iter(items)))


def test_detect_with_psutil(win, monkeypatch, tmp_path):
    me = os.getpid()
    this_file = str(Path(un.__file__).resolve())
    inst = tmp_path / "inst"
    _procs(monkeypatch, [
        {"pid": me, "name": "self", "exe": "", "cmdline": ["luister"]},
        {"pid": 1, "name": "py", "exe": this_file, "cmdline": []},
        {"pid": 2, "name": "py", "exe": "", "cmdline": ["python", this_file]},
        {"pid": 3, "name": "py", "exe": "", "cmdline": ["python", "-m", "luister.installer_gui.uninstaller"]},
        {"pid": 4, "name": "installer_gui", "exe": "", "cmdline": None},
        {"pid": 5, "name": "unrelated", "exe": "", "cmdline": ["ls"]},
        {"pid": 6, "name": "x", "exe": str(inst / "bin"), "cmdline": []},
        {"pid": 7, "name": "Luister", "exe": None, "cmdline": ["a"]},
        {"pid": None, "name": None, "exe": None, "cmdline": ["luister", "run"]},
        None,
    ])
    found = win._detect_running_instances(inst)
    assert [i["pid"] for i in found] == [6, 7, None]
    assert found[1]["cmd"] == "a"


def test_detect_this_file_resolution_error(win, monkeypatch):
    _procs(monkeypatch, [{"pid": 9, "name": "luister", "exe": "", "cmdline": []}])
    real = Path.resolve

    def bad(self, *a, **k):
        raise OSError("x")

    monkeypatch.setattr(Path, "resolve", bad)
    try:
        found = win._detect_running_instances(Path("/nowhere"))
    finally:
        monkeypatch.setattr(Path, "resolve", real)
    assert len(found) == 1


def test_detect_psutil_iteration_failure(win, monkeypatch):
    def boom(a):
        raise RuntimeError("x")

    monkeypatch.setitem(sys.modules, "psutil", types.SimpleNamespace(process_iter=boom))
    assert win._detect_running_instances(Path("/x")) == []


def test_detect_ps_fallback(win, monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)
    me = os.getpid()
    out = "\n".join([
        "",
        f"{me} luister me",
        "abc notanumber",
        "5 python -m luister.installer_gui.uninstaller",
        "6 /usr/bin/luister --serve",
        "7 /opt/inst/app run",
        "8 ls -l",
        "9",
    ])
    monkeypatch.setattr(un.subprocess, "check_output", lambda *a, **k: out)
    found = win._detect_running_instances(Path("/opt/inst"))
    assert [(i["pid"], i["name"]) for i in found] == [(6, "/usr/bin/luister"), (7, "/opt/inst/app")]


def test_detect_ps_fallback_failure(win, monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)

    def bad(*a, **k):
        raise FileNotFoundError("ps")

    monkeypatch.setattr(un.subprocess, "check_output", bad)
    assert win._detect_running_instances(Path("/x")) == []


def test_detect_windows_tasklist_fallback(win, monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)
    me = os.getpid()

    class Out:
        def splitlines(self):
            return [
                "single",
                f'"luister.exe","{me}","Console"',
                '"uninstaller.exe","20","Console"',
                '"luister.exe","30","Console"',
                '"luister-gui.exe","abc","Console"',
                '"notepad.exe","40","Console"',
                None,
            ]

    monkeypatch.setattr(un, "os", types.SimpleNamespace(name="nt", getpid=os.getpid))
    monkeypatch.setattr(un.subprocess, "check_output", lambda *a, **k: Out())
    found = win._detect_running_instances(Path("C:/x"))
    assert [(i["pid"], i["name"]) for i in found] == [(30, "luister.exe"), (None, "luister-gui.exe")]


# ---------------------------------------------------------------- process dialog

@pytest.fixture
def dialog_script(monkeypatch):
    """Replace the modal exec_ with a scripted 'user' acting on the dialog's widgets."""
    holder = {"script": None, "dlg": None}

    def fake_exec(self):
        holder["dlg"] = self
        buttons = {b.text(): b for b in self.findChildren(QtWidgets.QPushButton)}
        lst = self.findChild(QtWidgets.QListWidget)
        holder["script"](self, buttons, lst)
        return 0

    monkeypatch.setattr(QtWidgets.QDialog, "exec_", fake_exec)
    return holder


def _click(btn):
    QTest.mouseClick(btn, LEFT)


def _check(lst, *rows):
    for r in rows:
        lst.item(r).setCheckState(QtCore.Qt.Checked)


INSTANCES = [
    {"pid": 111, "name": "a", "cmd": "cmd a", "exe": ""},
    {"pid": 222, "name": "b", "cmd": "", "exe": "/bin/b"},
]


def test_dialog_no_instances(win):
    assert win._show_running_processes_dialog(Path("/x"), []) is True


def test_dialog_cancel_and_continue(win, dialog_script):
    dialog_script["script"] = lambda d, b, l: (
        __import__("builtins").setattr(sys, "_ls", [l.item(i).text() for i in range(l.count())]),
        _click(b["Cancel"]),
    )
    assert win._show_running_processes_dialog(Path("/x"), INSTANCES) is False
    assert sys._ls == ["111 — a — cmd a", "222 — b — /bin/b"]
    del sys._ls
    dialog_script["script"] = lambda d, b, l: _click(b["Continue Anyway"])
    assert win._show_running_processes_dialog(Path("/x"), INSTANCES) is True


def test_dialog_dismissed_without_choice(win, dialog_script):
    dialog_script["script"] = lambda d, b, l: None
    assert win._show_running_processes_dialog(Path("/x"), INSTANCES) is True


def test_dialog_kill_without_selection(win, dialog_script, boxes):
    dialog_script["script"] = lambda d, b, l: _click(b["Kill Selected"])
    win._show_running_processes_dialog(Path("/x"), INSTANCES)
    assert boxes[-1][0] == "information" and boxes[-1][1][0] == "No selection"


def test_dialog_kill_all_selected_accepts(win, dialog_script, boxes, monkeypatch, tmp_path):
    killed = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))

    def script(d, b, l):
        _check(l, 0, 1)
        _click(b["Kill Selected"])
        assert l.count() == 0 and not d.isVisible()

    dialog_script["script"] = script
    assert win._show_running_processes_dialog(tmp_path, INSTANCES) is True
    assert killed == [(111, 15), (222, 15)]
    assert boxes[-1][1][0] == "Kill result"
    assert (tmp_path / pkg.LOG_FILENAME).exists()


def test_dialog_kill_partial_failure(win, dialog_script, boxes, monkeypatch, tmp_path):
    def kill(pid, sig):
        if pid == 222:
            raise PermissionError("no")

    monkeypatch.setattr(os, "kill", kill)
    state = {}

    def script(d, b, l):
        _check(l, 0, 1)
        _click(b["Kill Selected"])
        state["left"] = [l.item(i).text() for i in range(l.count())]
        _click(b["Cancel"])

    dialog_script["script"] = script
    assert win._show_running_processes_dialog(tmp_path, INSTANCES) is False
    assert boxes[-1][0] == "warning" and "222:no" in boxes[-1][1][1]
    assert len(state["left"]) == 1 and state["left"][0].startswith("222")


def test_dialog_kill_bad_pid_text_and_log_errors(win, dialog_script, boxes, monkeypatch):
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)

    def bad_log(*a, **k):
        raise RuntimeError("log")

    monkeypatch.setattr(un, "write_log", bad_log)
    insts = [{"pid": "abc", "name": "x"}, {"pid": 5, "name": "y"}]

    def script(d, b, l):
        _check(l, 0, 1)
        _click(b["Kill Selected"])
        _click(b["Cancel"])

    dialog_script["script"] = script
    # install_dir passed as a plain string exercises the home-directory log path
    win._show_running_processes_dialog("not-a-path", insts)
    assert boxes[-1][1][0] == "Kill result"


def test_dialog_kill_failure_log_errors(win, dialog_script, boxes, monkeypatch, tmp_path):
    def kill(pid, sig):
        raise ProcessLookupError("gone")

    monkeypatch.setattr(os, "kill", kill)

    def bad_log(*a, **k):
        raise RuntimeError("log")

    monkeypatch.setattr(un, "write_log", bad_log)

    def script(d, b, l):
        _check(l, 0)
        _click(b["Kill Selected"])
        _click(b["Cancel"])

    dialog_script["script"] = script
    win._show_running_processes_dialog(tmp_path, INSTANCES)
    assert boxes[-1][0] == "warning"


def test_dialog_kill_on_windows_uses_taskkill(win, dialog_script, boxes, monkeypatch, tmp_path):
    cmds = []

    def check_call(cmd, **k):
        cmds.append(cmd)
        if cmd[2] == "222":
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(un.subprocess, "check_call", check_call)
    monkeypatch.setattr(un, "os", types.SimpleNamespace(name="nt", getpid=os.getpid))

    def script(d, b, l):
        _check(l, 0, 1)
        _click(b["Kill Selected"])
        _click(b["Cancel"])

    dialog_script["script"] = script
    win._show_running_processes_dialog(tmp_path, INSTANCES)
    assert [c[:3] for c in cmds] == [["taskkill", "/PID", "111"], ["taskkill", "/PID", "222"]]


# ---------------------------------------------------------------- start_uninstall flows

def test_start_requires_directory(win, boxes):
    win.install_dir_input.setText(" ")
    _click(win.start_btn)
    assert boxes[0][0] == "warning"
    assert win.thread is None


def test_start_cancelled_from_process_dialog(win, boxes, monkeypatch, install):
    win.install_dir_input.setText(str(install))
    monkeypatch.setattr(win, "_detect_running_instances", lambda d: [{"pid": 1}])
    monkeypatch.setattr(win, "_show_running_processes_dialog", lambda d, i: False)
    _click(win.start_btn)
    assert win.thread is None and install.exists()
    assert not any(b[0] == "question" for b in boxes)


def test_start_detection_failure_then_user_declines(win, boxes, monkeypatch, install):
    win.install_dir_input.setText(str(install))

    def bad(d):
        raise RuntimeError("detect")

    monkeypatch.setattr(win, "_detect_running_instances", bad)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
    _click(win.start_btn)
    assert win.thread is None and install.exists()
    assert win.start_btn.isEnabled()


def test_full_uninstall_success_via_thread(win, qtbot, boxes, install, user_data, monkeypatch):
    monkeypatch.setattr(win, "_detect_running_instances", lambda d: [{"pid": 1}])
    monkeypatch.setattr(win, "_show_running_processes_dialog", lambda d, i: True)
    win.install_dir_input.setText(str(install))
    win.remove_user_cb.setChecked(True)
    _click(win.start_btn)
    assert not win.start_btn.isEnabled() and not win.install_dir_input.isEnabled()
    qtbot.waitUntil(lambda: any(b[0] == "information" for b in boxes), timeout=10000)
    assert not user_data.exists()
    assert win.progress_bar.value() == 100
    assert win.start_btn.isEnabled() and win.install_dir_input.isEnabled()
    assert "Uninstallation completed" in win.progress_output.toPlainText()
    qtbot.waitUntil(lambda: win.thread.isFinished(), timeout=5000)


def test_full_uninstall_failure_via_thread(win, qtbot, boxes, tmp_path):
    win.install_dir_input.setText(str(tmp_path / "missing"))
    _click(win.start_btn)
    qtbot.waitUntil(lambda: any(b[0] == "critical" for b in boxes), timeout=10000)
    assert win.progress_bar.value() == 10
    assert win.start_btn.isEnabled()
    qtbot.waitUntil(lambda: win.thread.isFinished(), timeout=5000)


def test_skip_confirmation_does_not_ask(win, qtbot, boxes, tmp_path):
    win.install_dir_input.setText(str(tmp_path / "missing"))
    win.start_uninstall(skip_confirmation=True)
    qtbot.waitUntil(lambda: any(b[0] == "critical" for b in boxes), timeout=10000)
    assert not any(b[0] == "question" for b in boxes)
    qtbot.waitUntil(lambda: win.thread.isFinished(), timeout=5000)


# ---------------------------------------------------------------- blockers / retry

def test_parse_blockers(win):
    assert win._parse_blockers_from_message("x - Blocking Processes: 12:foo, 13:bar:baz,bad,x:y") == [
        {"pid": 12, "name": "foo"}, {"pid": 13, "name": "bar:baz"},
    ]
    assert win._parse_blockers_from_message("nothing here") == []
    assert win._parse_blockers_from_message(None) == []


def test_on_finished_retry_after_killing_blockers(win, qtbot, boxes, monkeypatch, tmp_path):
    win.install_dir_input.setText(str(tmp_path))
    seen = {}
    monkeypatch.setattr(win, "_show_running_processes_dialog", lambda d, i: seen.update(i=i) or True)
    retried = []
    monkeypatch.setattr(win, "start_uninstall", lambda skip_confirmation=False: retried.append(skip_confirmation))
    win.on_finished(False, "Failed: x - blocking processes: 42:vim")
    assert seen["i"] == [{"pid": 42, "name": "vim", "exe": "", "cmd": ""}]
    assert win._uninstall_retry_attempts == 1
    assert not any(b[0] == "critical" for b in boxes)
    qtbot.waitUntil(lambda: retried == [True], timeout=3000)


def test_on_finished_blockers_declined_or_unparsable_or_exhausted(win, boxes, monkeypatch, tmp_path):
    win.install_dir_input.setText(str(tmp_path))
    monkeypatch.setattr(win, "_show_running_processes_dialog", lambda d, i: False)
    win.on_finished(False, "bad - blocking processes: 1:a")
    assert boxes[-1][0] == "critical"
    win.on_finished(False, "bad - blocking processes: garbage")
    assert boxes[-1][0] == "critical"
    monkeypatch.setattr(win, "_show_running_processes_dialog", lambda d, i: True)
    win._uninstall_retry_attempts = 2
    n = len(boxes)
    win.on_finished(False, "bad - blocking processes: 1:a")
    assert len(boxes) == n + 1 and boxes[-1][0] == "critical"
    assert win._uninstall_retry_attempts == 2


def test_on_finished_error_tolerance(win, qtbot, boxes, monkeypatch):
    win.thread = types.SimpleNamespace(quit=lambda: 1 / 0)
    win.on_finished(True, "ok")
    win.thread = types.SimpleNamespace(quit=None)
    win.on_finished(True, "ok")
    win.thread = None

    class Broken(un.UninstallerWindow):
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


# ---------------------------------------------------------------- main and import fallbacks

def test_main_runs_app(monkeypatch):
    shown = []

    class App:
        def __init__(self, argv):
            pass

        def exec_(self):
            return 5

    class W:
        def show(self):
            shown.append(1)

    monkeypatch.setattr(QtWidgets, "QApplication", App)
    monkeypatch.setattr(un, "UninstallerWindow", W)
    assert un.main() == 5 and shown


def _load_copy(name="luister.installer_gui._uninstaller_copy"):
    spec = importlib.util.spec_from_file_location(name, Path(un.__file__))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
    return mod


def test_import_fallback_and_main_without_gui(monkeypatch, capsys):
    for attr in ("QtWidgets", "QtCore", "QtGui", "write_log", "appdirs"):
        monkeypatch.delattr(pkg, attr)
    mod = _load_copy()
    assert mod.LOG_FILENAME == "application.log"
    assert mod.main() == 2
    assert "GUI not available" in capsys.readouterr().out


def test_dummy_signal_fallback(monkeypatch):
    monkeypatch.setattr(pkg, "QtCore", types.SimpleNamespace(QObject=object))
    monkeypatch.setattr(pkg, "QtWidgets", types.SimpleNamespace(QDialog=object))
    mod = _load_copy()
    sig = mod.UninstallerWorker._Signal(str)
    sig.connect(lambda: None)
    sig.emit("x")
