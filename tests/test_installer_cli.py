"""End-to-end tests for luister.installer_cli (installer)."""

import json
import runpy
import sys
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest

import luister.installer_cli as inst

MODULE_FILE = inst.__file__


@pytest.fixture
def env(tmp_path, monkeypatch):
    calls = []

    def fake_check_call(cmd, **kw):
        calls.append((list(cmd), kw))
        return 0

    def fake_venv_create(path, with_pip=False):
        (Path(path) / "bin").mkdir(parents=True)
        (Path(path) / "bin" / "python").write_text("")

    def fake_clone_from(url, to):
        Path(to).mkdir(parents=True, exist_ok=True)
        if any(Path(to).iterdir()):
            raise RuntimeError("destination path already exists and is not an empty directory")
        (Path(to) / "README").write_text(url)

    shortcuts = []
    monkeypatch.setattr(subprocess, "check_call", fake_check_call)
    monkeypatch.setattr(inst.venv, "create", fake_venv_create)
    monkeypatch.setattr(inst.shutil, "which", lambda n: "/usr/bin/git")
    monkeypatch.setattr(inst, "make_shortcut", lambda **kw: shortcuts.append(kw))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()

    class FakeRepo:
        clone_from = staticmethod(fake_clone_from)
        pulled = []

        def __init__(self, path):
            if getattr(FakeRepo, "fail_pull", False):
                raise RuntimeError("bad repo")
            self.remotes = type("R", (), {"origin": type("O", (), {"pull": lambda s: FakeRepo.pulled.append(1)})()})()

    monkeypatch.setattr(inst, "Repo", FakeRepo)
    return type("E", (), {"calls": calls, "shortcuts": shortcuts, "Repo": FakeRepo, "tmp": tmp_path})


def logs(d):
    return [json.loads(x) for x in (Path(d) / "application.log").read_text().splitlines()]


def test_fresh_install_with_gitpython(env, capsys):
    d = env.tmp / "inst"
    with pytest.raises(SystemExit) as e:
        inst.main(["--repo", "https://x/y.git", "--dir", str(d)])
    assert e.value.code == 0
    assert (d / "README").read_text() == "https://x/y.git"
    assert not (env.tmp / "inst-backup").exists()
    assert (d / ".venv" / "bin" / "python").exists()
    launcher = d / "luister-launcher.py"
    assert str(d.resolve() / ".venv" / "bin" / "python") in launcher.read_text()
    assert launcher.stat().st_mode & 0o111
    cmds = [c[0][1:] for c in env.calls]
    assert ["-m", "pip", "install", "uv"] in cmds
    assert ["-m", "uv", "sync"] in cmds and ["-m", "uv", "build"] in cmds
    assert env.shortcuts[0]["name"] == "Luister"
    assert logs(d)[-1]["message"] == "completed"
    assert "completed" in capsys.readouterr().out


def test_clone_via_git_binary_and_build_fallback(env, monkeypatch):
    monkeypatch.setattr(inst, "Repo", None)

    def cc(cmd, **kw):
        env.calls.append((list(cmd), kw))
        if cmd[1:3] == ["-m", "uv"] and cmd[3] == "build":
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "check_call", cc)
    d = env.tmp / "inst"
    assert inst.Installer("u", d).run() is True
    assert env.calls[-1][0][-2:] == ["install", "."]
    inst.Installer("u", env.tmp / "other")._clone()
    assert env.calls[-1][0][:2] == ["/usr/bin/git", "clone"]


def test_update_existing_dir_pull_ok(env):
    d = env.tmp / "inst"
    d.mkdir()
    (d / "f").write_text("x")
    assert inst.Installer("u", d).run() is True
    assert env.Repo.pulled


def test_update_existing_dir_without_gitpython(env, monkeypatch):
    monkeypatch.setattr(inst, "Repo", None)
    d = env.tmp / "inst"
    d.mkdir()
    (d / "f").write_text("x")
    assert inst.Installer("u", d).run() is True
    assert env.calls[0][0] == ["git", "-C", str(d.resolve()), "pull"]


def test_pull_failure_backs_up_and_reclones(env):
    env.Repo.fail_pull = True
    try:
        d = env.tmp / "inst"
        d.mkdir()
        (d / "old").write_text("x")
        assert inst.Installer("u", d).run() is True
    finally:
        env.Repo.fail_pull = False
    assert (env.tmp / "inst-backup" / "old").exists()
    assert (d / "README").exists() and not (d / "old").exists()


def test_existing_venv_reused_and_shortcut_problems(env, monkeypatch, capsys):
    d = env.tmp / "inst"
    (d / ".venv").mkdir(parents=True)
    monkeypatch.setattr(inst, "Repo", None)
    monkeypatch.setattr(subprocess, "check_call", lambda *a, **k: 0)
    monkeypatch.setattr(inst, "make_shortcut", lambda **k: 1 / 0)
    assert inst.Installer("u", d).run() is True
    assert "shortcut_failed" in [r["message"] for r in logs(d)]
    monkeypatch.setattr(inst, "make_shortcut", None)
    assert inst.Installer("u", d).run() is True
    assert "shortcuts_unavailable" in [r["message"] for r in logs(d)]


def test_launcher_chmod_failure_ignored(env, monkeypatch):
    def bad(self, mode):
        raise OSError("no")

    monkeypatch.setattr(Path, "chmod", bad)
    d = env.tmp / "inst"
    assert inst.Installer("u", d).run() is True
    assert (d / "luister-launcher.py").exists()


def test_failure_exit_code_2(env, monkeypatch, capsys):
    def boom(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "check_call", boom)
    d = env.tmp / "inst"
    with pytest.raises(SystemExit) as e:
        inst.main(["--dir", str(d)])
    assert e.value.code == 2
    assert logs(d)[-1]["level"] == "ERROR"
    assert "ERROR:" in capsys.readouterr().out


def _make_zip(path, with_dir=True):
    with zipfile.ZipFile(path, "w") as z:
        if with_dir:
            z.writestr("proj-main/pyproject.toml", "x")
        else:
            z.writestr("loose.txt", "x")


def test_archive_download_fallback(env, monkeypatch):
    monkeypatch.setattr(inst.shutil, "which", lambda n: None)
    urls = []

    def retrieve(url, dest):
        urls.append(url)
        if url.endswith("main.zip"):
            raise OSError("404")
        _make_zip(dest)

    monkeypatch.setattr(inst.urllib.request, "urlretrieve", retrieve)
    d = env.tmp / "inst"
    inst.Installer("https://h/o/r.git/", d)._clone()
    assert urls == ["https://h/o/r/archive/refs/heads/main.zip", "https://h/o/r/archive/refs/heads/master.zip"]
    assert (d / "pyproject.toml").exists()
    assert not list((env.tmp / "tmp").glob("luister-download-*"))


def test_archive_empty_zip_and_all_fail(env, monkeypatch):
    monkeypatch.setattr(inst.shutil, "which", lambda n: None)
    monkeypatch.setattr(inst.urllib.request, "urlretrieve", lambda u, p: _make_zip(p, with_dir=False))
    real_rmtree = inst.shutil.rmtree

    def bad_rmtree(p, *a, **k):
        raise OSError("busy")

    monkeypatch.setattr(inst.shutil, "rmtree", bad_rmtree)
    d = env.tmp / "inst"
    with pytest.raises(RuntimeError, match="All archive download attempts failed"):
        inst.Installer("https://h/o/r", d)._clone()
    monkeypatch.setattr(inst.shutil, "rmtree", real_rmtree)


def test_windows_venv_python(env, monkeypatch):
    i = inst.Installer("u", env.tmp / "i")
    v = Path("v")
    monkeypatch.setattr(inst.os, "name", "nt")
    assert i._venv_python(v).parts[-2:] == ("Scripts", "python.exe")


def test_default_dir_with_and_without_appdirs(env, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(inst.Installer, "run", lambda self: seen.append(self.install_dir) or True)
    fake = type("A", (), {"user_data_dir": staticmethod(lambda n, appauthor=False: str(tmp_path / n))})
    monkeypatch.setattr(inst, "appdirs", fake)
    with pytest.raises(SystemExit):
        inst.main([])
    monkeypatch.setattr(inst, "appdirs", None)
    with pytest.raises(SystemExit):
        inst.main([])
    assert seen[0] == (tmp_path / "Instyper").resolve()
    assert seen[1] == (Path.home() / ".luister").resolve()


def test_write_log_failure_is_swallowed(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    inst.write_log(blocker / "sub" / "log", "INFO", "c", "m")


def test_run_as_main(env, monkeypatch):
    import git

    monkeypatch.setattr(git.Repo, "clone_from", staticmethod(lambda u, to: Path(to).mkdir(parents=True)))
    import pyshortcuts

    monkeypatch.setattr(pyshortcuts, "make_shortcut", lambda **k: None)
    d = env.tmp / "m"
    monkeypatch.setattr("sys.argv", ["x", "--dir", str(d)])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(MODULE_FILE, run_name="__main__")
    assert e.value.code == 0
    assert (d / "luister-launcher.py").exists()


def test_import_fallbacks_without_optional_deps(monkeypatch):
    for name in ("appdirs", "git", "pyshortcuts"):
        monkeypatch.setitem(sys.modules, name, None)
    ns = runpy.run_path(MODULE_FILE, run_name="not_main")
    assert ns["appdirs"] is None and ns["Repo"] is None and ns["make_shortcut"] is None
    assert ns["GitCommandError"] is Exception


def test_fresh_clone_when_log_cannot_be_written(env, monkeypatch):
    monkeypatch.setattr(inst, "write_log", lambda *a, **k: None)
    d = env.tmp / "inst"
    assert inst.Installer("u", d).run() is True
    assert (d / "README").read_text() == "u"
