"""End-to-end tests for luister.installer_cli.updater."""

import json
import runpy
import sys
import subprocess
import tempfile
from pathlib import Path

import pytest

from luister.installer_cli import updater as up


def logs(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines()]


@pytest.fixture
def env(tmp_path, monkeypatch):
    calls = []

    def cc(cmd, **kw):
        calls.append((list(cmd), kw))

    def vc(path, with_pip=False):
        (Path(path) / "bin").mkdir(parents=True)

    pulled = []

    class FakeRepo:
        def __init__(self, p):
            self.remotes = type("R", (), {"origin": type("O", (), {"pull": lambda s: pulled.append(p)})()})()

    monkeypatch.setattr(subprocess, "check_call", cc)
    monkeypatch.setattr(up.venv, "create", vc)
    monkeypatch.setattr(up, "Repo", FakeRepo)
    d = tmp_path / "inst"
    d.mkdir()
    return type("E", (), {"calls": calls, "pulled": pulled, "dir": d, "tmp": tmp_path})


def test_update_success(env, capsys):
    assert up.main(["--dir", str(env.dir), "-y"]) == 0
    assert env.pulled == [env.dir.resolve()]
    assert (env.dir / ".venv" / "bin").exists()
    launcher = env.dir / "luister-launcher.py"
    assert "uv" in launcher.read_text() and launcher.stat().st_mode & 0o111
    cmds = [c[0][1:] for c in env.calls]
    assert ["-m", "uv", "sync"] in cmds and ["-m", "uv", "build"] in cmds
    assert logs(env.dir / "application.log")[-1]["message"] == "completed"
    assert "Updated" in capsys.readouterr().out


def test_prompt_cancel_accept_and_input_error(env, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda p: "n")
    assert up.main(["--dir", str(env.dir)]) == 0
    assert "Cancelled" in capsys.readouterr().out
    assert not env.pulled
    monkeypatch.setattr("builtins.input", lambda p: "Y")
    assert up.main(["--dir", str(env.dir)]) == 0
    assert env.pulled

    def eof(p):
        raise EOFError

    env.pulled.clear()
    monkeypatch.setattr("builtins.input", eof)
    assert up.main(["--dir", str(env.dir)]) == 0


def test_missing_dir(env, capsys):
    assert up.main(["--dir", str(env.tmp / "none"), "-y"]) == 2
    assert "not found" in capsys.readouterr().out


def test_pull_via_git_binary(env, monkeypatch):
    monkeypatch.setattr(up, "Repo", None)
    monkeypatch.setattr(up.shutil, "which", lambda n: "/bin/git")
    assert up.main(["--dir", str(env.dir), "-y"]) == 0
    assert env.calls[0][0] == ["/bin/git", "-C", str(env.dir.resolve()), "pull"]


def test_pull_no_git(env, monkeypatch, capsys):
    monkeypatch.setattr(up, "Repo", None)
    monkeypatch.setattr(up.shutil, "which", lambda n: None)
    assert up.main(["--dir", str(env.dir), "-y"]) == 2
    assert "git not found" in capsys.readouterr().out


def test_pull_failure(env, monkeypatch, capsys):
    def bad(p):
        raise RuntimeError("conflict")

    monkeypatch.setattr(up, "Repo", bad)
    assert up.main(["--dir", str(env.dir), "-y"]) == 2
    assert "Git pull failed" in capsys.readouterr().out


def test_venv_failure_and_existing_venv(env, monkeypatch, capsys):
    def bad(*a, **k):
        raise OSError("no venv")

    monkeypatch.setattr(up.venv, "create", bad)
    assert up.main(["--dir", str(env.dir), "-y"]) == 2
    assert "Venv creation failed" in capsys.readouterr().out
    (env.dir / ".venv").mkdir()
    assert up.main(["--dir", str(env.dir), "-y"]) == 0


def test_build_fallback_and_install_failure(env, monkeypatch, capsys):
    def cc(cmd, **kw):
        env.calls.append(list(cmd))
        if cmd[3:] == ["build"]:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "check_call", cc)
    assert up.main(["--dir", str(env.dir), "-y"]) == 0
    assert env.calls[-1][-2:] == ["install", "."]

    def cc2(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "check_call", cc2)
    assert up.main(["--dir", str(env.dir), "-y"]) == 2
    assert "Install/build failed" in capsys.readouterr().out


def test_launcher_errors_ignored(env, monkeypatch):
    def bad_chmod(self, m):
        raise OSError

    monkeypatch.setattr(Path, "chmod", bad_chmod)
    assert up.main(["--dir", str(env.dir), "-y"]) == 0
    assert (env.dir / "luister-launcher.py").exists()

    def bad_write(self, *a, **k):
        raise OSError

    monkeypatch.setattr(Path, "write_text", bad_write)
    up._create_launcher(env.dir / "other.py", Path("p"))
    assert not (env.dir / "other.py").exists()


def test_create_launcher_exception_in_main_ignored(env, monkeypatch):
    def bad(*a):
        raise RuntimeError

    monkeypatch.setattr(up, "_create_launcher", bad)
    assert up.main(["--dir", str(env.dir), "-y"]) == 0


def test_unexpected_error_returns_2(env, monkeypatch, capsys):
    def bad(d):
        raise RuntimeError("weird")

    monkeypatch.setattr(up, "_venv_python", bad)
    assert up.main(["--dir", str(env.dir), "-y"]) == 2
    assert "Update failed: weird" in capsys.readouterr().out


def test_windows_venv_python(monkeypatch):
    v = Path("v")
    monkeypatch.setattr(up.os, "name", "nt")
    assert up._venv_python(v).parts[-2:] == ("Scripts", "python.exe")


def test_resolve_and_log_fallbacks(tmp_path, monkeypatch):
    assert up.resolve_install_dir(str(tmp_path)) == tmp_path.resolve()
    default = up.resolve_install_dir(None)
    assert default == Path(up.appdirs.user_data_dir("Instyper", appauthor=False)).resolve()
    monkeypatch.setattr(up, "appdirs", None)
    assert up.resolve_install_dir(None) == (Path.home() / ".luister").resolve()
    assert up.main(["--dir", str(tmp_path / "none"), "-y"]) == 2
    assert (Path.home() / up.LOG_FILENAME).exists()

    class Bad:
        def user_data_dir(self, *a, **k):
            raise RuntimeError

    monkeypatch.setattr(up, "appdirs", Bad())
    assert up.resolve_install_dir(None) == (Path.home() / ".luister").resolve()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    assert up.main(["--dir", str(tmp_path / "none"), "-y"]) == 2
    assert (tmp_path / up.LOG_FILENAME).exists()


def test_write_log_failure_swallowed(tmp_path):
    f = tmp_path / "f"
    f.write_text("x")
    up.write_log(f / "a" / "log", "INFO", "c", "m")


def test_run_as_main(env, monkeypatch):
    import git

    monkeypatch.setattr(git.Repo, "__init__", lambda s, p: (_ for _ in ()).throw(RuntimeError("stop")))
    monkeypatch.setattr("sys.argv", ["x", "--dir", str(env.dir), "-y"])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(up.__file__, run_name="__main__")
    assert e.value.code == 2


def test_import_fallbacks_without_optional_deps(monkeypatch):
    for name in ("appdirs", "git"):
        monkeypatch.setitem(sys.modules, name, None)
    ns = runpy.run_path(up.__file__, run_name="not_main")
    assert ns["appdirs"] is None and ns["Repo"] is None
