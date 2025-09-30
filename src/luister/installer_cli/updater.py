"""
Command-line updater for Instyper.

Performs a simple update workflow on an existing installation directory:
- run `git pull` in the directory (using GitPython if available, otherwise the git binary)
- ensure a local `.venv` exists (create if missing)
- install uv and run `uv sync` and `uv build` (with pip install fallback)
- recreate a small launcher script

This tool intentionally does NOT clone or re-check system prerequisites; it assumes
an existing project tree is already present at the provided path.

Exit codes:
 - 0: success
 - 2: failure
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import venv
import tempfile
import os
from datetime import datetime
from pathlib import Path
from typing import Any
import argparse

try:
    import appdirs  # type: ignore
except Exception:
    appdirs = None  # type: ignore

try:
    from git import Repo  # type: ignore
except Exception:
    Repo = None  # type: ignore

LOG_FILENAME = "application.log"


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def write_log(log_path: Path, level: str, component: str, message: str, **meta: Any) -> None:
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Instyper command-line updater")
    p.add_argument("--dir", help="Path to existing installation directory (defaults to OS app data dir)")
    p.add_argument("--yes", "-y", action="store_true", help="Skip interactive prompts")
    return p.parse_args(argv)


def resolve_install_dir(provided: str | None) -> Path:
    if provided:
        return Path(provided).expanduser().resolve()
    try:
        if appdirs:
            return Path(appdirs.user_data_dir("Instyper", appauthor=False)).expanduser().resolve()
    except Exception:
        pass
    return (Path.home() / ".luister").expanduser().resolve()


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _create_launcher(launcher_path: Path, venv_python: Path) -> None:
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
    try:
        launcher_path.write_text(launcher_code, encoding="utf-8")
        try:
            launcher_path.chmod(0o755)
        except Exception:
            pass
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    install_dir = resolve_install_dir(args.dir)

    # choose log path: prefer install dir if present
    log_path = (install_dir / LOG_FILENAME) if install_dir.exists() else None
    if log_path is None:
        try:
            if appdirs:
                log_path = Path(appdirs.user_data_dir("Instyper", appauthor=False)) / LOG_FILENAME
            else:
                log_path = Path.home() / LOG_FILENAME
        except Exception:
            log_path = Path(tempfile.gettempdir()) / LOG_FILENAME

    write_log(Path(log_path), "INFO", "updater", "start", install_dir=str(install_dir))

    if not args.yes:
        try:
            resp = input(f"Update installation at {install_dir}? (y/N): ").strip().lower()
            if resp not in ("y", "yes"):
                write_log(Path(log_path), "INFO", "updater", "cancelled_by_user")
                print("Cancelled")
                return 0
        except Exception:
            pass

    try:
        if not install_dir.exists():
            write_log(Path(log_path), "WARN", "updater", "install_dir_not_found", path=str(install_dir))
            print(f"Install directory not found: {install_dir}")
            return 2

        # Git pull
        write_log(Path(log_path), "INFO", "updater", "pull_start", path=str(install_dir))
        try:
            if Repo is not None:
                repo = Repo(install_dir)
                origin = repo.remotes.origin
                origin.pull()
            else:
                git_bin = shutil.which("git")
                if not git_bin:
                    raise RuntimeError("git not found")
                subprocess.check_call([git_bin, "-C", str(install_dir), "pull"])            
            write_log(Path(log_path), "INFO", "updater", "pull_ok")
        except Exception as e:
            write_log(Path(log_path), "ERROR", "updater", "pull_failed", error=str(e))
            print(f"Git pull failed: {e}")
            return 2

        # Ensure venv exists
        venv_dir = install_dir / ".venv"
        write_log(Path(log_path), "INFO", "updater", "ensure_venv", venv=str(venv_dir))
        try:
            if not venv_dir.exists():
                venv.create(str(venv_dir), with_pip=True)
        except Exception as e:
            write_log(Path(log_path), "ERROR", "updater", "venv_failed", error=str(e))
            print(f"Venv creation failed: {e}")
            return 2

        venv_python = _venv_python(venv_dir)

        # Install dependencies and build
        write_log(Path(log_path), "INFO", "updater", "install_deps_start")
        try:
            subprocess.check_call([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])            
            subprocess.check_call([str(venv_python), "-m", "pip", "install", "uv"])            
            subprocess.check_call([str(venv_python), "-m", "uv", "sync"], cwd=str(install_dir))
            try:
                subprocess.check_call([str(venv_python), "-m", "uv", "build"], cwd=str(install_dir))
            except subprocess.CalledProcessError:
                subprocess.check_call([str(venv_python), "-m", "pip", "install", "."], cwd=str(install_dir))
            write_log(Path(log_path), "INFO", "updater", "install_deps_ok")
        except Exception as e:
            write_log(Path(log_path), "ERROR", "updater", "install_deps_failed", error=str(e))
            print(f"Install/build failed: {e}")
            return 2

        # Recreate launcher
        try:
            launcher_path = install_dir / "luister-launcher.py"
            _create_launcher(launcher_path, venv_python)
        except Exception:
            pass

        write_log(Path(log_path), "INFO", "updater", "completed")
        print(f"Updated: {install_dir}")
        return 0
    except Exception as e:
        write_log(Path(log_path), "ERROR", "updater", "failed", error=str(e))
        print(f"Update failed: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main()) 