import sys
import os
import json
import argparse
import subprocess
import venv
import shutil
from pathlib import Path
from datetime import datetime
import urllib.request
import zipfile
import tempfile

try:
    # optional dependencies; present in pyproject
    import appdirs  # type: ignore
    from git import Repo, GitCommandError  # type: ignore
    from pyshortcuts import make_shortcut  # type: ignore
except Exception:
    appdirs = None  # type: ignore
    Repo = None  # type: ignore
    GitCommandError = Exception  # type: ignore
    make_shortcut = None  # type: ignore

LOG_FILENAME = "application.log"
DEFAULT_REPO = ""  # default repository not set; pass --repo to specify a remote


def now_iso():
    return datetime.utcnow().isoformat() + "Z"


def write_log(log_path: Path, level: str, component: str, message: str, **meta) -> None:
    entry = {
        "timestamp": now_iso(),
        "level": level,
        "component": component,
        "message": message,
    }
    entry.update(meta)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # best-effort
        pass


class Installer:
    def __init__(self, repo_url: str, install_dir: Path):
        self.repo_url = repo_url
        self.install_dir = install_dir.expanduser().resolve()
        self.log_path = self.install_dir / LOG_FILENAME

    def run(self):
        try:
            self.log_info("starting", repo_url=self.repo_url, install_dir=str(self.install_dir))

            # Clone or update
            if self.install_dir.exists() and any(self.install_dir.iterdir()):
                self.log_info("updating_repo", path=str(self.install_dir))
                try:
                    if Repo is not None:
                        repo = Repo(self.install_dir)
                        repo.remotes.origin.pull()
                    else:
                        subprocess.check_call(["git", "-C", str(self.install_dir), "pull"])                
                except Exception:
                    backup = self.install_dir.with_name(self.install_dir.name + "-backup")
                    shutil.move(str(self.install_dir), str(backup))
                    self._clone()
            else:
                self._clone()

            # venv
            venv_dir = self.install_dir / ".venv"
            self.log_info("creating_venv", venv=str(venv_dir))
            if not venv_dir.exists():
                venv.create(str(venv_dir), with_pip=True)

            venv_python = self._venv_python(venv_dir)

            # pip/uv
            self.log_info("installing_uv")
            subprocess.check_call([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])            
            subprocess.check_call([str(venv_python), "-m", "pip", "install", "uv"])            

            # uv sync
            self.log_info("running_uv_sync")
            subprocess.check_call([str(venv_python), "-m", "uv", "sync"], cwd=str(self.install_dir))

            # uv build or python -m pip install
            self.log_info("installing_package")
            try:
                subprocess.check_call([str(venv_python), "-m", "uv", "build"], cwd=str(self.install_dir))
            except subprocess.CalledProcessError:
                subprocess.check_call([str(venv_python), "-m", "pip", "install", "."], cwd=str(self.install_dir))

            # launcher
            launcher_path = self.install_dir / "luister-launcher.py"
            self._create_launcher(launcher_path, venv_python)

            # shortcuts
            self.log_info("creating_shortcuts")
            if callable(make_shortcut):
                try:
                    make_shortcut(name="Luister", script=str(launcher_path), icon=None, desktop=True, startmenu=True)
                except Exception as e:
                    self.log_warn("shortcut_failed", error=str(e))
            else:
                self.log_warn("shortcuts_unavailable")

            self.log_info("completed")
            return True
        except Exception as e:
            self.log_error("failed", error=str(e))
            return False

    def _clone(self):
        self.log_info("cloning", repo=self.repo_url)
        self.install_dir.parent.mkdir(parents=True, exist_ok=True)
        tmpdir = None
        try:
            git_bin = shutil.which('git')
            if git_bin and Repo is not None:
                Repo.clone_from(self.repo_url, str(self.install_dir))
                return
            if git_bin:
                subprocess.check_call([git_bin, 'clone', self.repo_url, str(self.install_dir)])
                return
            # git not available: attempt to download repository archive
            self.log_warn('git_not_found', reason='git-binary-missing')
            url_base = self.repo_url.rstrip('/')
            if url_base.endswith('.git'):
                url_base = url_base[:-4]
            candidates = [f"{url_base}/archive/refs/heads/main.zip", f"{url_base}/archive/refs/heads/master.zip"]
            tmpdir = tempfile.mkdtemp(prefix='luister-download-')
            for zip_url in candidates:
                try:
                    self.log_info('downloading_archive', url=zip_url)
                    zip_path = Path(tmpdir) / 'repo.zip'
                    urllib.request.urlretrieve(zip_url, str(zip_path))
                    with zipfile.ZipFile(str(zip_path), 'r') as zf:
                        zf.extractall(tmpdir)
                    entries = [p for p in Path(tmpdir).iterdir() if p.is_dir()]
                    if not entries:
                        continue
                    top = entries[0]
                    self.install_dir.mkdir(parents=True, exist_ok=True)
                    for item in top.iterdir():
                        dest = self.install_dir / item.name
                        shutil.move(str(item), str(dest))
                    self.log_info('archive_extracted', source=zip_url)
                    return
                except Exception as e:
                    self.log_warn('archive_download_failed', url=zip_url, error=str(e))
                    continue
            raise RuntimeError('All archive download attempts failed')
        finally:
            if tmpdir:
                try:
                    shutil.rmtree(tmpdir)
                except Exception:
                    pass

    def _venv_python(self, venv_dir: Path) -> Path:
        if os.name == "nt":
            return venv_dir / "Scripts" / "python.exe"
        return venv_dir / "bin" / "python"

    def _create_launcher(self, launcher_path: Path, venv_python: Path) -> None:
        launcher_code = f"""#!/usr/bin/env python3
import subprocess
import sys
venv_python = r'{venv_python}'
try:
    subprocess.run([venv_python, '-m', 'uv', 'run', 'luister'], check=True)
except Exception as e:
    print('Failed to start Luister:', e)
    sys.exit(1)
"""
        launcher_path.write_text(launcher_code, encoding="utf-8")
        try:
            launcher_path.chmod(0o755)
        except Exception:
            pass

    def log_info(self, message: str, **meta):
        print(message)
        write_log(self.log_path, "INFO", "installer", message, **meta)

    def log_warn(self, message: str, **meta):
        print("WARN:", message)
        write_log(self.log_path, "WARN", "installer", message, **meta)

    def log_error(self, message: str, **meta):
        print("ERROR:", message)
        write_log(self.log_path, "ERROR", "installer", message, **meta)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Luister headless installer")
    p.add_argument("--repo", default=DEFAULT_REPO, help="Git repository URL to clone (optional)")
    p.add_argument("--dir", help="Install directory (default: OS app data dir)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.dir:
        install_dir = Path(args.dir)
    else:
        if appdirs:
            default = appdirs.user_data_dir("Instyper", appauthor=False)
            install_dir = Path(default)
        else:
            install_dir = Path.home() / ".luister"

    installer = Installer(args.repo, install_dir)
    ok = installer.run()
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main() 