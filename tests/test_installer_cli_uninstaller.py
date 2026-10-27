"""End-to-end tests for luister.installer_cli.uninstaller."""

import json
import runpy
import sys
import tempfile
from pathlib import Path

import pytest

from luister.installer_cli import uninstaller as un


def logs(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines()]


def make_install(tmp_path):
    d = tmp_path / "inst"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "f").write_text("x")
    return d


def test_remove_with_yes(tmp_path, capsys):
    d = make_install(tmp_path)
    assert un.main(["--dir", str(d), "-y"]) == 0
    assert not d.exists()
    assert "Uninstalled" in capsys.readouterr().out


def test_cancel_and_confirm(tmp_path, monkeypatch, capsys):
    d = make_install(tmp_path)
    monkeypatch.setattr("builtins.input", lambda p: "n")
    assert un.main(["--dir", str(d)]) == 0
    assert d.exists() and "Cancelled" in capsys.readouterr().out
    assert logs(d / "application.log")[-1]["message"] == "cancelled_by_user"
    monkeypatch.setattr("builtins.input", lambda p: " YES ")
    assert un.main(["--dir", str(d)]) == 0
    assert not d.exists()


def test_confirm_input_error_cancels(tmp_path, monkeypatch):
    d = make_install(tmp_path)

    def eof(p):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert un.main(["--dir", str(d)]) == 0
    assert d.exists()


def test_missing_dir_returns_2_and_logs_to_fallback(tmp_path, capsys):
    assert un.main(["--dir", str(tmp_path / "nope"), "-y"]) == 2
    assert "not found" in capsys.readouterr().out
    log = Path(un.appdirs.user_data_dir("Instyper", appauthor=False)) / un.LOG_FILENAME
    assert logs(log)[-1]["message"] == "install_dir_not_found"


def test_remove_user_data(tmp_path, monkeypatch):
    d = make_install(tmp_path)
    ud = tmp_path / "ud"
    ud.mkdir()
    monkeypatch.setattr(un, "resolve_user_data_dir", lambda: ud)
    assert un.main(["--dir", str(d), "-y", "--remove-user-data"]) == 0
    assert not ud.exists()


def test_remove_user_data_absent_and_failure(tmp_path, monkeypatch):
    d = make_install(tmp_path)
    monkeypatch.setattr(un, "resolve_user_data_dir", lambda: tmp_path / "none")
    assert un.main(["--dir", str(d), "-y", "--remove-user-data"]) == 0

    d = make_install(tmp_path)
    ud = tmp_path / "ud"
    ud.write_text("x")
    monkeypatch.setattr(un, "resolve_user_data_dir", lambda: ud)
    real = un.remove_path

    def rp(p):
        if p == ud:
            raise OSError("denied")
        real(p)

    monkeypatch.setattr(un, "remove_path", rp)
    assert un.main(["--dir", str(d), "-y", "--remove-user-data"]) == 0
    assert ud.exists()


def test_removal_failure_returns_2(tmp_path, monkeypatch, capsys):
    d = make_install(tmp_path)

    def bad(p):
        raise OSError("denied")

    monkeypatch.setattr(un, "remove_path", bad)
    assert un.main(["--dir", str(d), "-y"]) == 2
    assert "Uninstall failed" in capsys.readouterr().out


def test_remove_path_file(tmp_path):
    f = tmp_path / "f"
    f.write_text("x")
    un.remove_path(f)
    assert not f.exists()
    un.remove_path(f)


def test_resolve_dirs(tmp_path, monkeypatch):
    assert un.resolve_install_dir(str(tmp_path)) == tmp_path.resolve()
    monkeypatch.setattr(un, "appdirs", None)
    assert un.resolve_install_dir(None) == (Path.home() / ".luister").resolve()
    assert un.resolve_user_data_dir() == (Path.home() / ".instyper").resolve()

    class Bad:
        def user_data_dir(self, *a, **k):
            raise RuntimeError

    monkeypatch.setattr(un, "appdirs", Bad())
    assert un.resolve_install_dir(None) == (Path.home() / ".luister").resolve()
    assert un.resolve_user_data_dir() == (Path.home() / ".instyper").resolve()


def test_log_path_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setattr(un, "appdirs", None)
    assert un.main(["--dir", str(tmp_path / "none"), "-y"]) == 2
    assert (Path.home() / un.LOG_FILENAME).exists()

    class Bad:
        def user_data_dir(self, *a, **k):
            raise RuntimeError

    monkeypatch.setattr(un, "appdirs", Bad())
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    assert un.main(["--dir", str(tmp_path / "none"), "-y"]) == 2
    assert (tmp_path / un.LOG_FILENAME).exists()


def test_default_dir_consistent_with_installer(tmp_path):
    from luister.installer_cli import Installer, main as imain  # noqa: F401
    import luister.installer_cli as inst

    # installer installs into appdirs "Instyper"; uninstaller must target the same default
    assert un.resolve_install_dir(None) == Path(inst.appdirs.user_data_dir("Instyper", appauthor=False)).resolve()


def test_write_log_failure_swallowed(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    un.write_log(blocker / "a" / "log", "INFO", "c", "m")


def test_run_as_main(tmp_path, monkeypatch):
    d = make_install(tmp_path)
    monkeypatch.setattr("sys.argv", ["x", "--dir", str(d), "-y"])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(un.__file__, run_name="__main__")
    assert e.value.code == 0
    assert not d.exists()


def test_import_fallback_without_appdirs(monkeypatch):
    monkeypatch.setitem(sys.modules, "appdirs", None)
    ns = runpy.run_path(un.__file__, run_name="not_main")
    assert ns["appdirs"] is None
