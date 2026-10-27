"""InstallerWorker: the install pipeline with every external boundary mocked."""

import os
import subprocess
import tempfile
import zipfile
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from tests.test_installer_gui_common import gui, gui_app  # noqa: F401

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="red"/></svg>'


class FakeRepo:
    clones = []
    pulled = []
    pull_error = None
    clone_error = None

    def __init__(self, path):
        if not (Path(path) / ".git").exists():
            raise RuntimeError("InvalidGitRepositoryError")
        self.path = path
        origin = SimpleNamespace(pull=self._pull)
        self.remotes = SimpleNamespace(origin=origin)

    @classmethod
    def _pull(cls):
        if cls.pull_error:
            raise cls.pull_error
        cls.pulled.append(True)

    @classmethod
    def clone_from(cls, url, dest):
        if cls.clone_error:
            raise cls.clone_error
        cls.clones.append((url, dest))
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "README.md").write_text("hi")


@pytest.fixture
def env(gui, gui_app, monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    FakeRepo.clones, FakeRepo.pulled = [], []
    FakeRepo.pull_error = FakeRepo.clone_error = None
    e = SimpleNamespace(
        calls=[],
        which={"python": "/bin/python", "git": "/bin/git"},
        fail=None,
        shortcuts=[],
        logo=None,
        install=tmp_path / "inst" / "luister",
        scratch=scratch,
    )
    monkeypatch.setattr(gui.shutil, "which", lambda n: e.which.get(n))

    def check_call(cmd, **kw):
        e.calls.append((list(cmd), kw))
        if cmd[:1] == ["git"] and "pull" in cmd and not (e.install.resolve() / ".git").exists():
            raise subprocess.CalledProcessError(128, cmd)
        if e.fail and e.fail(list(cmd)):
            raise subprocess.CalledProcessError(1, cmd)
        return 0

    monkeypatch.setattr(gui.subprocess, "check_call", check_call)
    monkeypatch.setattr(gui.venv, "create", lambda d, with_pip=True: Path(d).mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(gui, "Repo", FakeRepo)
    monkeypatch.setattr(gui, "make_shortcut", lambda **kw: e.shortcuts.append(kw))
    monkeypatch.setattr(gui, "find_project_logo", lambda: e.logo)
    return e


def run_worker(gui, env, url="https://example.com/org/repo"):
    w = gui.InstallerWorker(url, str(env.install))
    msgs, fin = [], []
    w.progress.connect(msgs.append)
    w.finished.connect(lambda ok, m: fin.append((ok, m)))
    w.run()
    return w, msgs, fin


def cmds(env):
    return [c for c, _ in env.calls]


def log_messages(env):
    import json

    out = []
    # a failed pull moves the whole install dir (and its log) to "<dir>-backup"
    for d in (env.install.with_name(env.install.name + "-backup"), env.install):
        log = d / "application.log"
        if log.exists():
            out += [json.loads(x)["message"] for x in log.read_text().splitlines()]
    return out


# ---------------------------------------------------------------- happy path

def test_fresh_install_with_git_and_gitpython(gui, env):
    w, msgs, fin = run_worker(gui, env)
    assert fin == [(True, str(env.install.resolve()))]
    assert FakeRepo.clones and FakeRepo.clones[0][0] == "https://example.com/org/repo"
    assert "stage:clone:ok" in msgs and "stage:venv:ok" in msgs and "stage:deps:ok" in msgs
    assert msgs[-2:] == ["100:Installation completed successfully", "stage:all:ok"]
    py = str(env.install.resolve() / ".venv" / "bin" / "python")
    pip_cmds = [c for c in cmds(env) if c[0] == py]
    assert [c[1:] for c in pip_cmds] == [
        ["-m", "pip", "install", "--upgrade", "pip"],
        ["-m", "pip", "install", "uv"],
        ["-m", "uv", "sync"],
        ["-m", "uv", "build"],
    ]
    launcher = env.install.resolve() / "luister-launcher.py"
    assert py in launcher.read_text()
    assert os.access(launcher, os.X_OK)
    assert env.shortcuts and env.shortcuts[0]["name"] == "Luister"
    assert env.shortcuts[0]["icon"] is None
    assert "completed" in log_messages(env)


def test_prereq_problem_is_reported_but_install_continues(gui, env):
    env.which = {}
    w, msgs, fin = run_worker(gui, env)
    assert msgs[0] == "0:Prerequisite problem: python-not-found"
    assert len(fin) == 1  # pipeline is still attempted
    assert "prereq_failed" in log_messages(env)


@pytest.mark.parametrize(
    "which, pip_fails, expected",
    [
        ({}, False, (False, "python-not-found")),
        ({"python3": "/bin/python3"}, True, (False, "pip-not-found")),
        ({"python": "/bin/python"}, False, (True, "git-not-found-will-use-http")),
        ({"python": "/bin/python", "git": "/bin/git"}, False, (True, "ok")),
    ],
)
def test_check_prereqs(gui, env, which, pip_fails, expected):
    env.which = which
    env.fail = (lambda c: pip_fails)
    assert gui.InstallerWorker("https://x/y", str(env.install))._check_prereqs() == expected


# ---------------------------------------------------------------- clone / update

def test_fresh_install_clones_without_backing_up(gui, env):
    # The worker's own log file lands in install_dir before the clone step, which makes a
    # brand-new install look like an "existing repository" (pull -> fail -> backup -> clone).
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is True
    assert "20:Updating existing repository (git pull)" not in msgs
    assert not env.install.with_name("luister-backup").exists()


def test_fresh_dir_is_cloned_when_logging_is_unavailable(gui, env, monkeypatch):
    monkeypatch.setattr(gui, "write_log", lambda *a, **k: None)
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is True
    assert "20:Updating existing repository (git pull)" not in msgs
    assert FakeRepo.clones and "25:Repository cloned" in msgs


def test_existing_repo_is_pulled_via_gitpython(gui, env):
    env.install.mkdir(parents=True)
    (env.install / ".git").mkdir()
    (env.install / ".venv").mkdir()
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is True
    assert FakeRepo.pulled and not FakeRepo.clones
    assert "20:Updating existing repository (git pull)" in msgs
    assert "stage:clone:ok" in msgs


def test_existing_repo_is_pulled_via_git_cli_without_gitpython(gui, env, monkeypatch):
    monkeypatch.setattr(gui, "Repo", None)
    env.install.mkdir(parents=True)
    (env.install / ".git").mkdir()
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is True
    assert ["git", "-C", str(env.install.resolve()), "pull"] in cmds(env)


def test_failed_pull_backs_up_and_reclones(gui, env):
    FakeRepo.pull_error = RuntimeError("not a repo")
    env.install.mkdir(parents=True)
    (env.install / ".git").mkdir()
    (env.install / "old.txt").write_text("old")
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is True
    backup = env.install.with_name("luister-backup")
    assert (backup / "old.txt").exists()
    assert "25:Repository cloned" in msgs
    assert FakeRepo.clones


def test_clone_uses_git_cli_when_gitpython_missing(gui, env, monkeypatch):
    monkeypatch.setattr(gui, "Repo", None)
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is True
    assert ["/bin/git", "clone", "https://example.com/org/repo", str(env.install.resolve())] in cmds(env)


def test_clone_failure_reports_failure(gui, env):
    FakeRepo.clone_error = RuntimeError("network down")
    w, msgs, fin = run_worker(gui, env)
    assert fin == [(False, "network down")]
    assert "failed" in log_messages(env)


# ---------------------------------------------------------------- HTTP archive fallback

def _fake_download(env, behaviours):
    """behaviours: per-URL 'ok' | 'ok-flat' | 'empty' | 'error'. Writes a zip like GitHub does."""
    urls = []

    def retrieve(url, path):
        urls.append(url)
        b = behaviours[len(urls) - 1]
        if b == "error":
            raise OSError("404")
        with zipfile.ZipFile(path, "w") as zf:
            if b == "ok":
                zf.writestr("repo-main/README.md", "hi")
                zf.writestr("repo-main/pkg/mod.py", "x=1")
            elif b == "empty":
                zf.writestr("loose.txt", "no folder")
    return urls, retrieve


def test_http_archive_fallback_main_branch(gui, env, monkeypatch):
    env.which = {"python": "/bin/python"}
    urls, retrieve = _fake_download(env, ["ok"])
    monkeypatch.setattr(gui.urllib.request, "urlretrieve", retrieve)
    w, msgs, fin = run_worker(gui, env, url="https://github.com/org/repo.git")
    assert fin[0][0] is True
    assert urls == ["https://github.com/org/repo/archive/refs/heads/main.zip"]
    assert (env.install / "README.md").exists() and (env.install / "pkg" / "mod.py").exists()
    assert "git_not_found" in log_messages(env)
    assert not list(env.scratch.glob("luister-download-*"))


def test_http_archive_falls_back_to_master(gui, env, monkeypatch):
    env.which = {"python": "/bin/python"}
    urls, retrieve = _fake_download(env, ["error", "ok"])
    monkeypatch.setattr(gui.urllib.request, "urlretrieve", retrieve)
    w, msgs, fin = run_worker(gui, env, url="https://github.com/org/repo/")
    assert fin[0][0] is True
    assert urls[1].endswith("/master.zip")
    assert "archive_download_failed" in log_messages(env)


@pytest.mark.parametrize("behaviours", [["error", "error"], ["empty", "empty"]])
def test_http_archive_all_attempts_fail(gui, env, monkeypatch, behaviours):
    env.which = {"python": "/bin/python"}
    urls, retrieve = _fake_download(env, behaviours)
    monkeypatch.setattr(gui.urllib.request, "urlretrieve", retrieve)
    w, msgs, fin = run_worker(gui, env)
    assert fin == [(False, "All archive download attempts failed")]


def test_http_archive_cleanup_failure_is_ignored(gui, env, monkeypatch):
    env.which = {"python": "/bin/python"}
    urls, retrieve = _fake_download(env, ["ok"])
    monkeypatch.setattr(gui.urllib.request, "urlretrieve", retrieve)

    def boom(path, *a, **k):
        raise OSError("busy")

    monkeypatch.setattr(gui.shutil, "rmtree", boom)
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is True


def test_http_archive_mixed_top_level_items(gui, env, monkeypatch):
    # entries are moved whether they are files or directories; a loose file next to the folder is ignored
    env.which = {"python": "/bin/python"}

    def retrieve(url, path):
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("top/a.txt", "a")
            zf.writestr("top/dir/b.txt", "b")

    monkeypatch.setattr(gui.urllib.request, "urlretrieve", retrieve)
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is True
    assert (env.install / "a.txt").read_text() == "a" and (env.install / "dir" / "b.txt").exists()


# ---------------------------------------------------------------- dependency stage

def test_uv_build_failure_falls_back_to_pip_install(gui, env):
    env.fail = lambda c: c[-1] == "build"
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is True
    assert any(c[-3:] == ["-m", "pip", "install", "."][-3:] and c[-1] == "." for c in cmds(env))
    assert "stage:deps:ok" in msgs


def test_dependency_failure_fails_install(gui, env):
    env.fail = lambda c: c[-1] == "sync"
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is False and "non-zero exit status" in fin[0][1]
    assert "stage:all:ok" not in msgs


def test_fallback_pip_install_failure(gui, env):
    env.fail = lambda c: c[-1] in ("build", ".")
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is False


# ---------------------------------------------------------------- icons & shortcuts

def test_svg_logo_is_rasterised_and_used_for_shortcut(gui, env, tmp_path):
    svg = tmp_path / "logo.svg"
    svg.write_text(SVG)
    env.logo = svg
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is True
    assert (env.install / "logo.png").exists()
    assert env.shortcuts[0]["icon"] == str(env.install.resolve() / "logo.png")


def test_svg_rasterisation_error_copies_original(gui, env, tmp_path, monkeypatch):
    svg = tmp_path / "logo.svg"
    svg.write_text(SVG)
    env.logo = svg

    def boom(path):
        raise RuntimeError("renderer")

    monkeypatch.setattr(gui, "QSvgRenderer", boom)
    w, msgs, fin = run_worker(gui, env)
    assert (env.install / "logo.svg").exists()
    assert env.shortcuts[0]["icon"].endswith("logo.svg")


def test_png_logo_copied_without_svg_renderer(gui, env, tmp_path, monkeypatch):
    png = tmp_path / "logo.png"
    png.write_bytes(b"png")
    env.logo = png
    monkeypatch.setattr(gui, "QSvgRenderer", None)
    w, msgs, fin = run_worker(gui, env)
    assert (env.install / "logo.png").read_bytes() == b"png"


def test_svg_without_renderer_is_copied_as_is(gui, env, tmp_path, monkeypatch):
    svg = tmp_path / "logo.svg"
    svg.write_text(SVG)
    env.logo = svg
    monkeypatch.setattr(gui, "QSvgRenderer", None)
    w, msgs, fin = run_worker(gui, env)
    assert (env.install / "logo.svg").exists()


def test_windows_converts_logo_to_ico(gui, env, tmp_path, monkeypatch):
    from PIL import Image

    png = tmp_path / "logo.png"
    Image.new("RGBA", (64, 64), "red").save(png)
    env.logo = png
    monkeypatch.setattr(gui.platform, "system", lambda: "Windows")
    w, msgs, fin = run_worker(gui, env)
    assert (env.install / "logo.ico").exists()
    assert env.shortcuts[0]["icon"].endswith("logo.ico")


def test_windows_ico_conversion_failure_copies_raster(gui, env, tmp_path, monkeypatch):
    png = tmp_path / "logo.png"
    png.write_bytes(b"not really a png")
    env.logo = png
    monkeypatch.setattr(gui.platform, "system", lambda: "Windows")
    w, msgs, fin = run_worker(gui, env)
    assert (env.install / "logo.png").exists()
    assert env.shortcuts[0]["icon"].endswith("logo.png")


def test_icon_copy_failure_results_in_no_icon(gui, env, tmp_path, monkeypatch):
    png = tmp_path / "logo.png"
    png.write_bytes(b"png")
    env.logo = png

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(gui.shutil, "copy", boom)
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is True and env.shortcuts[0]["icon"] is None


def test_shortcut_failure_is_non_fatal(gui, env, monkeypatch):
    def boom(**kw):
        raise RuntimeError("no desktop")

    monkeypatch.setattr(gui, "make_shortcut", boom)
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is True
    assert "stage:launch:fail" in msgs and "shortcut_failed" in log_messages(env)


def test_missing_pyshortcuts_is_non_fatal(gui, env, monkeypatch):
    monkeypatch.setattr(gui, "make_shortcut", None)
    w, msgs, fin = run_worker(gui, env)
    assert fin[0][0] is True and "shortcuts_unavailable" in log_messages(env)


# ---------------------------------------------------------------- helpers

def test_venv_python_path_per_os(gui, env, monkeypatch):
    w = gui.InstallerWorker("https://x/y", str(env.install))
    assert w._venv_python(Path("v")) == Path("v/bin/python")
    monkeypatch.setattr(os, "name", "nt")
    assert w._venv_python(PureWindowsPath("v")) == PureWindowsPath("v/Scripts/python.exe")


def test_launcher_chmod_failure_is_ignored(gui, env, monkeypatch, tmp_path):
    def boom(self, mode):
        raise OSError("fat32")

    monkeypatch.setattr(Path, "chmod", boom)
    w = gui.InstallerWorker("https://x/y", str(env.install))
    target = tmp_path / "launch.py"
    w._create_launcher(target, Path("/v/bin/python"))
    assert "/v/bin/python" in target.read_text()


def test_worker_find_project_logo(gui, env, monkeypatch):
    w = gui.InstallerWorker("https://x/y", str(env.install))
    monkeypatch.setattr(Path, "exists", lambda self: True)
    assert w._find_project_logo().name == "logo.png"
    monkeypatch.setattr(Path, "exists", lambda self: False)
    assert w._find_project_logo() is None
