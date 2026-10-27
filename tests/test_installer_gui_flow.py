"""End-to-end install flow, prerequisite dialogs, completion page, log sending and main()."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from tests.test_installer_gui_common import (  # noqa: F401
    SyncThread,
    boxes,
    deferred,
    dialogs,
    gui,
    gui_app,
    pump,
    wait_until,
)
from tests.test_installer_gui_window import Boom, click, make_png, mkwin, write_state  # noqa: F401
from tests.test_installer_gui_worker import FakeRepo, env  # noqa: F401


@pytest.fixture
def sync_threads(monkeypatch, gui):
    monkeypatch.setattr(gui, "threading", SimpleNamespace(Thread=SyncThread))


def open_wizard(w):
    click(w.get_started)
    assert wait_until(lambda: getattr(w, "_config_created", False))


def fill_and_install(w, repo, target):
    w.repo_input.setText(repo)
    w.install_dir_input.setText(str(target))
    click(w.start_button)


# ---------------------------------------------------------------- full wizard install

def test_full_install_through_wizard(mkwin, gui, env, dialogs, boxes, monkeypatch):
    w = mkwin()
    open_wizard(w)
    popen = []
    monkeypatch.setattr(gui.subprocess, "Popen", lambda cmd: popen.append(cmd))

    def completion(dlg):
        dialogs.click(dlg, "See details")
        dialogs.click(dlg, "Open install folder")
        dialogs.click(dlg, "Close")

    dialogs.script = completion
    fill_and_install(w, "https://example.com/org/repo", env.install)
    assert not w.start_button.isEnabled() and not w.repo_input.isEnabled()
    assert wait_until(lambda: "Installation Complete" in dialogs.seen)
    assert w.progress_bar.value() == 100
    assert w.start_button.isEnabled() and w.repo_input.isEnabled()
    assert w._toggle_logs_btn.isChecked() and w._log_viewer.isVisible()
    assert [w._stage_labels[k][0].text() for k in ("clone", "venv", "deps", "launch")] == ["✅"] * 4
    assert "Installation finished successfully." in w.progress_output.toPlainText()
    assert popen and popen[0][-1] == str(env.install.resolve())
    assert (env.install / "luister-launcher.py").exists()
    assert env.shortcuts
    w._tail_log_file()
    assert "installing_uv" in w._log_viewer.toPlainText() or "starting" in w._log_viewer.toPlainText()
    w.thread.wait(5000)


def test_failed_install_shows_failure_page(mkwin, gui, env, dialogs, monkeypatch):
    w = mkwin()
    open_wizard(w)
    env.fail = lambda c: c[-1] == "sync"
    dialogs.script = lambda dlg: dialogs.click(dlg, "Close")
    fill_and_install(w, "https://example.com/org/repo", env.install)
    assert wait_until(lambda: "Installation Failed" in dialogs.seen)
    assert w.progress_bar.value() < 100
    assert w.start_button.isEnabled()
    assert "Installation failed:" in w.progress_output.toPlainText()
    w.thread.wait(5000)


# ---------------------------------------------------------------- start_install validation

def test_start_install_validation_messages(mkwin, boxes, tmp_path):
    w = mkwin()
    w.repo_input.setText("")
    w.start_install()
    w.repo_input.setText("ftp://nope")
    w.start_install()
    w.repo_input.setText("git@github.com:o/r.git")
    w.install_dir_input.setText("   ")
    w.start_install()
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    w.install_dir_input.setText(str(blocker / "sub" / "dir"))
    w.start_install()
    assert [c[1] for c in boxes.calls] == ["Missing repository", "Invalid repository",
                                          "Missing install directory", "Directory error"]
    assert w.start_button.isEnabled()


def test_start_install_cancelled_at_prerequisites(mkwin, monkeypatch, tmp_path):
    w = mkwin()
    monkeypatch.setattr(w, "check_and_prompt_prereqs", lambda: False)
    w.repo_input.setText("https://x/y")
    w.install_dir_input.setText(str(tmp_path / "inst"))
    w.start_install()
    assert w.worker is None and w.progress_bar.value() == 0


def test_start_install_without_usable_log_file(mkwin, gui, monkeypatch, tmp_path):
    w = mkwin()
    monkeypatch.setattr(w, "check_and_prompt_prereqs", lambda: True)
    started = []

    class IdleWorker(QtCore.QObject):
        progress = QtCore.Signal(str)
        finished = QtCore.Signal(bool, str)

        def __init__(self, repo, install_dir):
            super().__init__()
            started.append((repo, install_dir))

        def run(self):
            pass

    monkeypatch.setattr(gui, "InstallerWorker", IdleWorker)
    monkeypatch.setattr(QtCore.QThread, "start", lambda self, *a: started.append("thread"))
    target = tmp_path / "plainfile"
    target.write_text("x")  # install dir is a file, so the log file cannot be prepared
    w.repo_input.setText("https://x/y")
    w.install_dir_input.setText(str(target))
    w.start_install()
    assert w._log_tail_path is None
    assert started[-1] == "thread"


# ---------------------------------------------------------------- on_finished / completion page

def test_on_finished_tolerates_broken_widgets(mkwin, gui, dialogs, monkeypatch):
    w = mkwin()
    w.thread = Boom()
    w.repo_input = Boom()
    w.progress_bar = Boom()
    monkeypatch.setattr(w, "append_log", Boom())
    w.on_finished(False, "bad")  # nothing may escape


def test_on_finished_tolerates_thread_lookup_failure(mkwin, gui, dialogs, monkeypatch):
    w = mkwin()
    monkeypatch.setattr(gui.InstallerWindow, "thread", property(lambda self: (_ for _ in ()).throw(RuntimeError("x"))))
    w.on_finished(True, "ok")


@pytest.mark.parametrize("system, binary", [("Windows", "explorer"), ("Darwin", "open"), ("Linux", "xdg-open")])
def test_completion_page_open_folder_per_platform(mkwin, gui, dialogs, monkeypatch, tmp_path, system, binary):
    w = mkwin()
    popen = []
    monkeypatch.setattr(gui.platform, "system", lambda: system)
    monkeypatch.setattr(gui.subprocess, "Popen", lambda cmd: popen.append(cmd))
    dialogs.script = lambda d: dialogs.click(d, "Open install folder")
    w._show_completion_page(True, str(tmp_path))
    assert popen == [[binary, str(tmp_path)]]


def test_completion_page_failure_opens_configured_dir(mkwin, gui, dialogs, monkeypatch, tmp_path):
    w = mkwin()
    popen = []
    monkeypatch.setattr(gui.subprocess, "Popen", lambda cmd: popen.append(cmd))
    w.install_dir_input.setText(str(tmp_path))
    dialogs.script = lambda d: dialogs.click(d, "Open install folder")
    w._show_completion_page(False, "boom")
    assert dialogs.seen == ["Installation Failed"] and popen[0][-1] == str(tmp_path)


def test_completion_page_action_errors_are_ignored(mkwin, gui, dialogs, monkeypatch):
    w = mkwin()

    def explode(cmd):
        raise OSError("no opener")

    monkeypatch.setattr(gui.subprocess, "Popen", explode)
    w._toggle_logs_btn = Boom()

    def script(d):
        dialogs.click(d, "Open install folder")
        dialogs.click(d, "See details")

    dialogs.script = script
    w._show_completion_page(True, "/x")


def test_completion_page_construction_error_is_ignored(mkwin, monkeypatch):
    w = mkwin()
    monkeypatch.setattr(QtWidgets, "QDialog", Boom())
    w._show_completion_page(True, "/x")


# ---------------------------------------------------------------- log tailing

def test_tail_log_file(mkwin, tmp_path):
    w = mkwin()
    w._log_tail_path = None
    w._tail_log_file()
    w._log_tail_path = tmp_path / "missing.log"
    w._tail_log_file()
    log = tmp_path / "t.log"
    log.write_text("line one\n")
    w._log_tail_path = log
    w._log_tail_pos = 0
    w._tail_log_file()
    w._tail_log_file()  # nothing new
    with log.open("a") as fh:
        fh.write("line two\n")
    w._tail_log_file()
    assert w._log_viewer.toPlainText() == "line one\nline two\n"
    w._log_viewer = Boom()
    with log.open("a") as fh:
        fh.write("three\n")
    w._tail_log_file()  # swallowed


# ---------------------------------------------------------------- prerequisites dialog

@pytest.fixture
def probes(gui, monkeypatch):
    s = SimpleNamespace(which={"python": "/bin/python", "git": "/bin/git"}, pip_ok=True)
    monkeypatch.setattr(gui.shutil, "which", lambda n: s.which.get(n))

    def check_call(cmd, **kw):
        if not s.pip_ok:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(gui.subprocess, "check_call", check_call)
    return s


def scripted(dialogs, steps, seen=None):
    it = iter(steps)

    def script(dlg):
        step = next(it)
        if seen is not None:
            seen.append(dlg)
        if callable(step):
            step(dlg)
        elif step:
            dialogs.click(dlg, step)

    dialogs.script = script


def test_prereqs_all_present_needs_no_dialog(mkwin, probes, dialogs):
    assert mkwin().check_and_prompt_prereqs() is True
    assert dialogs.seen == []


def test_prereqs_optional_git_missing_can_continue(mkwin, probes, dialogs):
    probes.which.pop("git")
    scripted(dialogs, ["Continue"])
    assert mkwin().check_and_prompt_prereqs() is True
    assert dialogs.seen == ["Prerequisites"]


def test_prereqs_required_missing_blocks_continue_and_can_cancel(mkwin, probes, dialogs):
    probes.which.clear()
    states = []
    scripted(dialogs, [lambda d: (states.append(d.findChildren(QtWidgets.QPushButton)), dialogs.click(d, "Cancel"))])
    assert mkwin().check_and_prompt_prereqs() is False
    cont = [b for b in states[0] if b.text() == "Continue"][0]
    assert not cont.isEnabled()


def test_prereqs_pip_missing_is_required(mkwin, probes, dialogs):
    probes.pip_ok = False
    labels = []
    scripted(dialogs, [lambda d: (labels.extend(l.text() for l in d.findChildren(QtWidgets.QLabel)), dialogs.click(d, "Cancel"))])
    assert mkwin().check_and_prompt_prereqs() is False
    assert "pip" in labels and "Git (optional)" not in labels


def test_prereqs_retry_and_closed_dialog_loop_until_continue(mkwin, probes, dialogs):
    probes.which.pop("git")
    scripted(dialogs, ["Retry", None, "Continue"])
    assert mkwin().check_and_prompt_prereqs() is True
    assert len(dialogs.seen) == 3


def test_prereqs_install_buttons_delegate(mkwin, probes, dialogs, monkeypatch):
    probes.which.clear()
    w = mkwin()
    got = []
    monkeypatch.setattr(w, "_install_prereq", lambda pkg, dlg: got.append(pkg))

    def script(d):
        btns = [b for b in d.findChildren(QtWidgets.QPushButton) if b.text() == "Install"]
        for b in btns:
            b.click()
        dialogs.click(d, "Cancel")

    scripted(dialogs, [script])
    w.check_and_prompt_prereqs()
    assert got == ["Python", "Git (optional)"]


def test_prereqs_background_recheck_enables_continue(mkwin, probes, dialogs, deferred):
    probes.which.clear()
    w = mkwin()
    results = []

    def script(d):
        timer = d.findChildren(QtCore.QTimer)[0]
        cont = [b for b in d.findChildren(QtWidgets.QPushButton) if b.text() == "Continue"][0]
        assert timer.interval() == 10000
        timer.timeout.emit()  # still no python
        deferred()
        results.append(cont.isEnabled())
        probes.which["python"] = "/bin/python"
        probes.pip_ok = False
        timer.timeout.emit()  # python but pip broken
        deferred()
        results.append(cont.isEnabled())
        probes.pip_ok = True
        timer.timeout.emit()
        deferred()
        results.append(cont.isEnabled())
        dialogs.click(d, "Continue")

    scripted(dialogs, [script])
    assert w.check_and_prompt_prereqs() is True
    assert results == [False, False, True]


def test_prereqs_recheck_errors_are_swallowed(mkwin, probes, dialogs, gui, monkeypatch):
    probes.which.pop("git")
    w = mkwin()

    def script(d):
        monkeypatch.setattr(gui.shutil, "which", Boom())
        d.findChildren(QtCore.QTimer)[0].timeout.emit()
        dialogs.click(d, "Continue")

    scripted(dialogs, [script])
    assert w.check_and_prompt_prereqs() is True


def test_prereqs_timer_creation_failure(mkwin, probes, dialogs, monkeypatch):
    probes.which.pop("git")
    w = mkwin()

    def no_timer(*a, **k):
        raise RuntimeError("no timer")

    monkeypatch.setattr(QtCore, "QTimer", no_timer)
    scripted(dialogs, ["Continue"])
    assert w.check_and_prompt_prereqs() is True


def test_prereqs_timer_stop_failure(mkwin, probes, dialogs, monkeypatch):
    probes.which.pop("git")
    w = mkwin()

    class T:
        def __init__(self, *a):
            self.timeout = SimpleNamespace(connect=lambda f: None)

        def setInterval(self, ms):
            pass

        def start(self):
            pass

        def stop(self):
            raise RuntimeError("stop")

    monkeypatch.setattr(QtCore, "QTimer", T)
    scripted(dialogs, ["Continue"])
    assert w.check_and_prompt_prereqs() is True


# ---------------------------------------------------------------- installing prerequisites

def prereq_which(**present):
    return lambda name: present.get(name)


def capture_command(w, monkeypatch):
    got = []
    monkeypatch.setattr(w, "_run_command_in_thread", lambda cmd, pkg, dlg: got.append((cmd, pkg, dlg)))
    return got


def test_install_prereq_declined(mkwin, gui, boxes, monkeypatch):
    w = mkwin()
    got = capture_command(w, monkeypatch)
    boxes.answer = QtWidgets.QMessageBox.No
    w._install_prereq("Python", None)
    assert got == [] and boxes.kinds() == ["question"]


@pytest.mark.parametrize(
    "pkg, expected",
    [
        ("Python", ["winget", "install", "--id", "Python.Python.3", "-e", "--silent"]),
        ("Git (optional)", ["winget", "install", "--id", "Git.Git", "-e", "--silent"]),
        ("Other", ["winget", "install", "Other"]),
    ],
)
def test_install_prereq_windows(mkwin, gui, boxes, monkeypatch, pkg, expected):
    w = mkwin()
    got = capture_command(w, monkeypatch)
    monkeypatch.setattr(gui.platform, "system", lambda: "Windows")
    w._install_prereq(pkg, "dlg")
    assert got == [(expected, pkg, "dlg")]


@pytest.mark.parametrize("pkg, tail", [("Python", "python"), ("Git (optional)", "git"), ("Other", "Other")])
def test_install_prereq_macos_with_homebrew(mkwin, gui, boxes, monkeypatch, pkg, tail):
    w = mkwin()
    got = capture_command(w, monkeypatch)
    monkeypatch.setattr(gui.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(gui.shutil, "which", prereq_which(brew="/opt/brew"))
    w._install_prereq(pkg, None)
    assert got[0][0] == ["/opt/brew", "install", tail]


def test_install_prereq_macos_without_homebrew(mkwin, gui, boxes, monkeypatch):
    w = mkwin()
    got = capture_command(w, monkeypatch)
    monkeypatch.setattr(gui.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(gui.shutil, "which", prereq_which())
    w._install_prereq("Python", None)
    assert got == [] and boxes.calls[-1][1] == "Homebrew missing"


LINUX = {
    "apt-get": ("sudo apt-get update && sudo apt-get install -y", {
        "Python": "python3 python3-venv python3-pip", "pip": "python3-pip", "Git (optional)": "git", "Other": "Other"}),
    "dnf": ("sudo dnf install -y", {
        "Python": "python3 python3-virtualenv python3-pip", "pip": "python3-pip", "Git (optional)": "git", "Other": "Other"}),
    "pacman": ("sudo pacman -Sy --noconfirm", {
        "Python": "python", "pip": "python-pip", "Git (optional)": "git", "Other": "Other"}),
    "zypper": ("sudo zypper refresh && sudo zypper install -y", {
        "Python": "python3 python3-pip", "pip": "python3-pip", "Git (optional)": "git", "Other": "Other"}),
    "apk": ("sudo apk add", {
        "Python": "python3 py3-pip", "pip": "py3-pip", "Git (optional)": "git", "Other": "Other"}),
}


@pytest.mark.parametrize("mgr", list(LINUX))
@pytest.mark.parametrize("pkg", ["Python", "pip", "Git (optional)", "Other"])
def test_install_prereq_linux_package_managers(mkwin, gui, boxes, monkeypatch, mgr, pkg):
    w = mkwin()
    got = capture_command(w, monkeypatch)
    monkeypatch.setattr(gui.platform, "system", lambda: "Linux")
    monkeypatch.setattr(gui.shutil, "which", prereq_which(**{mgr: "/bin/" + mgr}))  # no python -> pip uses the manager
    w._install_prereq(pkg, None)
    prefix, pkgs = LINUX[mgr]
    assert got[0][0] == ["bash", "-lc", f"{prefix} {pkgs[pkg]}"]


def test_install_prereq_linux_without_package_manager(mkwin, gui, boxes, monkeypatch):
    w = mkwin()
    got = capture_command(w, monkeypatch)
    monkeypatch.setattr(gui.platform, "system", lambda: "Linux")
    monkeypatch.setattr(gui.shutil, "which", prereq_which())
    w._install_prereq("Python", None)
    assert got == [] and boxes.calls[-1][1] == "Package manager not found"


def test_install_prereq_pip_uses_ensurepip_sequence(mkwin, gui, boxes, monkeypatch):
    w = mkwin()
    seq = []
    monkeypatch.setattr(w, "_install_pip_sequence", lambda py, dlg: seq.append((py, dlg)))
    monkeypatch.setattr(gui.shutil, "which", prereq_which(python3="/bin/python3"))
    w._install_prereq("pip", "dlg")
    assert seq == [("/bin/python3", "dlg")]


# ---------------------------------------------------------------- background command runners

def test_run_command_in_thread_success(mkwin, gui, monkeypatch, sync_threads, deferred, tmp_path):
    w = mkwin()
    w._log_tail_path = tmp_path / "x.log"
    monkeypatch.setattr(gui.subprocess, "run", lambda cmd, **k: SimpleNamespace(stdout="done"))
    accepted = []
    dlg = SimpleNamespace(accept=lambda: accepted.append(1))
    w._run_command_in_thread(["tool", "arg"], "Pkg", dlg)
    deferred()
    assert accepted == [1]
    assert "Installed Pkg successfully" in w._log_viewer.toPlainText()
    assert "install_command_success" in (tmp_path / "x.log").read_text()


def test_run_command_in_thread_success_without_dialog_or_log(mkwin, gui, monkeypatch, sync_threads, deferred):
    w = mkwin()
    w._log_tail_path = None
    monkeypatch.setattr(gui.subprocess, "run", lambda cmd, **k: SimpleNamespace(stdout=""))
    w._run_command_in_thread(["tool"], "Pkg", None)
    deferred()
    assert "Installed Pkg successfully" in w._log_viewer.toPlainText()


@pytest.mark.parametrize("with_log", [True, False])
def test_run_command_in_thread_failure(mkwin, gui, monkeypatch, sync_threads, deferred, tmp_path, with_log):
    w = mkwin()
    w._log_tail_path = tmp_path / "x.log" if with_log else None

    def run(cmd, **k):
        raise subprocess.CalledProcessError(1, cmd, stderr="denied")

    monkeypatch.setattr(gui.subprocess, "run", run)
    w._run_command_in_thread(["tool"], "Pkg", None)
    deferred()
    assert "Failed to install Pkg: denied" in w._log_viewer.toPlainText()
    if with_log:
        assert "install_command_failed" in (tmp_path / "x.log").read_text()


def pip_runs(monkeypatch, gui, results):
    """results: list of CompletedProcess-likes or exceptions for successive subprocess.run calls."""
    it = iter(results)

    def run(cmd, **k):
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(gui.subprocess, "run", run)


def cp(rc=0, out="", err=""):
    return SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def test_pip_sequence_success(mkwin, gui, monkeypatch, sync_threads, deferred, tmp_path):
    w = mkwin()
    w._log_tail_path = tmp_path / "pip.log"
    pip_runs(monkeypatch, gui, [cp(0, "ensured", "warn"), cp(0, "upgraded", "note")])
    accepted = []
    w._install_pip_sequence("/bin/python", SimpleNamespace(accept=lambda: accepted.append(1)))
    deferred()
    assert accepted == [1]
    assert "Installed/updated pip successfully" in w._log_viewer.toPlainText()
    text = (tmp_path / "pip.log").read_text()
    assert "ensurepip_stdout" in text and "pip_upgrade_stderr" in text and "pip_upgrade_done" in text


def test_pip_sequence_success_without_dialog(mkwin, gui, monkeypatch, sync_threads, deferred, tmp_path):
    w = mkwin()
    w._log_tail_path = tmp_path / "pip.log"
    pip_runs(monkeypatch, gui, [cp(), cp()])
    w._install_pip_sequence("/bin/python", None)
    deferred()
    assert "Installed/updated pip successfully" in w._log_viewer.toPlainText()


def test_pip_sequence_ensurepip_error_then_upgrade_failure(mkwin, gui, monkeypatch, sync_threads, deferred, tmp_path):
    w = mkwin()
    w._log_tail_path = tmp_path / "pip.log"
    pip_runs(monkeypatch, gui, [OSError("no ensurepip"), cp(1, "", "no network")])
    w._install_pip_sequence("/bin/python", None)
    deferred()
    assert "Failed to install/upgrade pip: no network" in w._log_viewer.toPlainText()
    assert "ensurepip_failed" in (tmp_path / "pip.log").read_text()


def test_pip_sequence_upgrade_exception(mkwin, gui, monkeypatch, sync_threads, deferred, tmp_path):
    w = mkwin()
    w._log_tail_path = tmp_path / "pip.log"
    pip_runs(monkeypatch, gui, [cp(), RuntimeError("exploded")])
    w._install_pip_sequence("/bin/python", None)
    deferred()
    assert "Failed to install/upgrade pip: exploded" in w._log_viewer.toPlainText()


@pytest.mark.parametrize("have_appdirs", [True, False])
def test_pip_sequence_default_log_location(mkwin, gui, monkeypatch, sync_threads, deferred, have_appdirs):
    w = mkwin()
    w._log_tail_path = None
    if not have_appdirs:
        monkeypatch.setattr(gui, "appdirs", None)
    pip_runs(monkeypatch, gui, [cp(), cp()])
    w._install_pip_sequence("/bin/python", None)
    deferred()
    base = Path(gui.appdirs.user_data_dir("Luister", appauthor=False)) if have_appdirs else Path.home()
    assert (base / gui.LOG_FILENAME).exists()


def test_pip_sequence_log_location_fallbacks(mkwin, gui, monkeypatch, sync_threads, deferred):
    w = mkwin()
    w._log_tail_path = None
    monkeypatch.setattr(gui, "appdirs", Boom())
    pip_runs(monkeypatch, gui, [cp(), cp()])
    w._install_pip_sequence("/bin/python", None)
    assert (Path.home() / gui.LOG_FILENAME).exists()

    class BadStr:
        def __str__(self):
            raise RuntimeError("str")

    w._log_tail_path = BadStr()
    pip_runs(monkeypatch, gui, [cp(), cp()])
    w._install_pip_sequence("/bin/python", None)


def test_pip_sequence_progress_dialog_lifecycle(mkwin, gui, monkeypatch, sync_threads, deferred, tmp_path):
    w = mkwin()
    w._log_tail_path = tmp_path / "pip.log"
    pip_runs(monkeypatch, gui, [cp(), cp()])
    w._install_pip_sequence("/bin/python", None)
    dlg = w.findChildren(QtWidgets.QProgressDialog)[0]
    assert dlg.windowTitle() == "Installing pip"
    deferred()
    assert not dlg.isVisible()


def test_pip_sequence_without_progress_dialog_or_close(mkwin, gui, monkeypatch, sync_threads, deferred, tmp_path):
    w = mkwin()
    w._log_tail_path = tmp_path / "pip.log"
    monkeypatch.setattr(QtWidgets, "QProgressDialog", Boom())
    pip_runs(monkeypatch, gui, [cp(), cp()])
    w._install_pip_sequence("/bin/python", None)
    deferred()
    monkeypatch.undo()


def test_pip_sequence_close_scheduling_failure(mkwin, gui, monkeypatch, sync_threads, tmp_path):
    w = mkwin()
    w._log_tail_path = tmp_path / "pip.log"
    pip_runs(monkeypatch, gui, [cp(), cp()])

    def single_shot(ms, fn=None):
        if fn is not None and fn.__defaults__:
            raise RuntimeError("no loop")

    monkeypatch.setattr(QtCore.QTimer, "singleShot", staticmethod(single_shot))
    w._install_pip_sequence("/bin/python", None)


# ---------------------------------------------------------------- send logs

def test_send_logs_requires_a_log_file(mkwin, boxes, tmp_path):
    w = mkwin()
    w._send_logs_report()
    w._log_tail_path = 12345  # not path-like
    w._send_logs_report()
    w._log_tail_path = tmp_path / "gone.log"
    w._send_logs_report()
    assert [c[2] for c in boxes.calls] == ["No log file configured for sending."] * 2 + ["No log file found to send."]


@pytest.fixture
def fast_sleep(monkeypatch):
    monkeypatch.setattr(QtCore.QThread, "msleep", staticmethod(lambda ms: None))


def test_send_logs_simulated_upload(mkwin, gui, boxes, sync_threads, deferred, fast_sleep, tmp_path):
    w = mkwin()
    log = tmp_path / "send.log"
    log.write_text("some log\n")
    w._log_tail_path = log
    w._send_logs_report()
    dlg = w.findChildren(QtWidgets.QProgressDialog)[0]
    assert dlg.windowTitle() == "Send Logs"
    deferred()
    assert not dlg.isVisible()
    text = w._log_viewer.toPlainText()
    assert "Sending logs... (20%)" in text and "(simulated)" in text
    assert boxes.calls[-1][1] == "Logs Sent"
    assert "send_logs_done" in log.read_text()


def test_send_logs_without_progress_dialog(mkwin, gui, boxes, sync_threads, deferred, fast_sleep, tmp_path, monkeypatch):
    w = mkwin()
    log = tmp_path / "send.log"
    log.write_text("x")
    w._log_tail_path = log
    monkeypatch.setattr(QtWidgets, "QProgressDialog", Boom())
    w._send_logs_report()
    deferred()
    assert boxes.calls[-1][1] == "Logs Sent"


def test_send_logs_read_failure(mkwin, gui, boxes, sync_threads, deferred, fast_sleep, tmp_path, monkeypatch):
    w = mkwin()
    log = tmp_path / "send.log"
    log.write_text("x")
    w._log_tail_path = log

    def boom(self, *a, **k):
        raise OSError("unreadable")

    monkeypatch.setattr(Path, "read_text", boom)
    w._send_logs_report()
    deferred()
    assert boxes.calls[-1][:2] == ("critical", "Send Failed")
    assert "send_logs_failed" in log.read_bytes().decode()


def test_send_logs_close_scheduling_failure(mkwin, gui, boxes, sync_threads, fast_sleep, tmp_path, monkeypatch):
    w = mkwin()
    log = tmp_path / "send.log"
    log.write_text("x")
    w._log_tail_path = log

    def single_shot(ms, fn=None):
        if fn is not None and fn.__defaults__ and fn.__defaults__[0].__class__.__name__ == "QProgressDialog" and len(fn.__defaults__) == 1:
            raise RuntimeError("no loop")

    monkeypatch.setattr(QtCore.QTimer, "singleShot", staticmethod(single_shot))
    w._send_logs_report()


# ---------------------------------------------------------------- main()

@pytest.fixture
def fake_app(gui, gui_app, monkeypatch):
    real = QtWidgets.QApplication.instance()
    icons = []
    fake = SimpleNamespace(setWindowIcon=lambda ic: (icons.append(ic), real.setWindowIcon(ic)), exec_=lambda: 7)
    monkeypatch.setattr(QtWidgets, "QApplication", lambda argv: fake)
    made = []
    base = gui.InstallerWindow

    class Recorded(base):
        def __init__(self):
            super().__init__()
            made.append(self)

    monkeypatch.setattr(gui, "InstallerWindow", Recorded)
    fake.icons, fake.windows = icons, made
    yield fake
    for w in made:
        w.close()
        w.deleteLater()
    pump(real)


def test_main_without_logo(gui, fake_app, monkeypatch):
    monkeypatch.setattr(gui, "find_project_logo", lambda: None)
    assert gui.main() == 7
    assert fake_app.icons == [] and fake_app.windows[0].isVisible()


def test_main_with_svg_logo_rasterises_icon(gui, fake_app, monkeypatch, tmp_path):
    svg = tmp_path / "logo.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8"/></svg>')
    monkeypatch.setattr(gui, "find_project_logo", lambda: svg)
    assert gui.main() == 7
    assert len(fake_app.icons) == 1 and not fake_app.icons[0].isNull()


def test_main_svg_render_failure_uses_file_icon(gui, fake_app, monkeypatch, tmp_path):
    svg = tmp_path / "logo.svg"
    svg.write_text("<svg/>")
    monkeypatch.setattr(gui, "find_project_logo", lambda: svg)
    monkeypatch.setattr(gui, "QSvgRenderer", Boom())
    assert gui.main() == 7
    assert len(fake_app.icons) == 1


def test_main_svg_render_and_icon_failure(gui, fake_app, monkeypatch, tmp_path):
    svg = tmp_path / "logo.svg"
    svg.write_text("<svg/>")
    monkeypatch.setattr(gui, "find_project_logo", lambda: svg)
    monkeypatch.setattr(gui, "QSvgRenderer", Boom())
    monkeypatch.setattr(fake_app, "setWindowIcon", Boom())
    assert gui.main() == 7


def test_main_png_logo_sets_app_and_window_icon(gui, fake_app, monkeypatch, tmp_path):
    png = make_png(tmp_path / "logo.png")
    monkeypatch.setattr(gui, "find_project_logo", lambda: png)
    assert gui.main() == 7
    assert len(fake_app.icons) == 1
    assert not fake_app.windows[0].windowIcon().isNull()


def test_main_png_icon_failure_is_ignored(gui, fake_app, monkeypatch, tmp_path):
    png = make_png(tmp_path / "logo.png")
    monkeypatch.setattr(gui, "find_project_logo", lambda: png)
    monkeypatch.setattr(fake_app, "setWindowIcon", Boom())
    assert gui.main() == 7
    assert fake_app.windows[0].isVisible()


def test_main_window_icon_failure_is_ignored(gui, fake_app, monkeypatch, tmp_path):
    png = make_png(tmp_path / "logo.png")
    monkeypatch.setattr(gui, "find_project_logo", lambda: png)
    monkeypatch.setattr(gui.InstallerWindow, "setWindowIcon", Boom())
    assert gui.main() == 7


def test_main_logo_lookup_failure_is_ignored(gui, fake_app, monkeypatch):
    def boom():
        raise RuntimeError("fs")

    monkeypatch.setattr(gui, "find_project_logo", boom)
    assert gui.main() == 7


def _ctypes_for_windows(appid_error=None):
    calls = []

    def appid(x):
        calls.append(x)
        if appid_error:
            raise appid_error

    return SimpleNamespace(windll=SimpleNamespace(shell32=SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=appid)), calls=calls)


def test_main_on_windows_sets_appid_and_taskbar_icon(gui, fake_app, monkeypatch, tmp_path):
    png = make_png(tmp_path / "logo.png")
    monkeypatch.setattr(gui, "find_project_logo", lambda: png)
    fake = _ctypes_for_windows()
    monkeypatch.setattr(gui, "ctypes", fake)
    monkeypatch.setattr(gui.platform, "system", lambda: "Windows")
    taskbar = []
    monkeypatch.setattr(gui.InstallerWindow, "_set_windows_taskbar_icon", lambda self, hwnd, path: taskbar.append((hwnd, path)))
    assert gui.main() == 7
    assert fake.calls == ["net.luister.app"]
    assert taskbar and taskbar[0][1] == str(png)


def test_main_on_windows_tolerates_win32_failures(gui, fake_app, monkeypatch, tmp_path):
    png = make_png(tmp_path / "logo.png")
    monkeypatch.setattr(gui, "find_project_logo", lambda: png)
    monkeypatch.setattr(gui, "ctypes", _ctypes_for_windows(appid_error=OSError("denied")))
    monkeypatch.setattr(gui.platform, "system", lambda: "Windows")
    monkeypatch.setattr(gui.InstallerWindow, "_set_windows_taskbar_icon", Boom())
    assert gui.main() == 7


def test_main_on_windows_winid_failure(gui, fake_app, monkeypatch, tmp_path):
    png = make_png(tmp_path / "logo.png")
    monkeypatch.setattr(gui, "find_project_logo", lambda: png)
    monkeypatch.setattr(gui, "ctypes", _ctypes_for_windows())
    monkeypatch.setattr(gui.platform, "system", lambda: "Windows")
    monkeypatch.setattr(gui.InstallerWindow, "winId", Boom())
    assert gui.main() == 7
