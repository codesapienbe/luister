"""
Command-line uninstaller for Luister.

This module is intentionally lightweight and self-contained to avoid import-time
side-effects when invoked as a console script. It performs structured JSON logging
to an application log file and removes the installation directory and (optionally)
user data.

Exit codes:
 - 0: success
 - 2: failure
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import appdirs  # type: ignore
except Exception:
    appdirs = None  # type: ignore

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
        # best-effort logging; do not raise
        pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Luister command-line uninstaller")
    p.add_argument("--dir", help="Installation directory to remove. If omitted, defaults to OS app data dir.")
    p.add_argument("--remove-user-data", action="store_true", help="Also remove per-user data (user config/cache).")
    p.add_argument("--yes", "-y", action="store_true", help="Skip interactive confirmation")
    return p.parse_args(argv)


def resolve_install_dir(provided: str | None) -> Path:
    if provided:
        return Path(provided).expanduser().resolve()
    try:
        if appdirs:
            return Path(appdirs.user_data_dir("Luister", appauthor=False)).expanduser().resolve()
    except Exception:
        pass
    return (Path.home() / ".luister").expanduser().resolve()


def resolve_user_data_dir() -> Path:
    try:
        if appdirs:
            return Path(appdirs.user_data_dir("Instyper", appauthor=False)).expanduser().resolve()
    except Exception:
        pass
    return (Path.home() / ".instyper").expanduser().resolve()


def confirm_removal(target: Path) -> bool:
    try:
        resp = input(f"Remove installation at {target} ? This cannot be undone. (y/N): ").strip().lower()
        return resp in ("y", "yes")
    except Exception:
        return False


def remove_path(path: Path) -> None:
    # Use shutil.rmtree for directories, unlink for files
    if path.is_dir():
        shutil.rmtree(str(path))
    elif path.exists():
        path.unlink()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    install_dir = resolve_install_dir(args.dir)

    # prefer log located inside the installation directory if present, otherwise fall back
    log_path = (install_dir / LOG_FILENAME) if install_dir.exists() else None
    if log_path is None:
        try:
            if appdirs:
                log_path = Path(appdirs.user_data_dir("Instyper", appauthor=False)) / LOG_FILENAME
            else:
                log_path = Path.home() / LOG_FILENAME
        except Exception:
            log_path = Path(tempfile.gettempdir()) / LOG_FILENAME

    write_log(Path(log_path), "INFO", "uninstaller", "start", install_dir=str(install_dir), remove_user_data=bool(args.remove_user_data))

    if not args.yes:
        ok = confirm_removal(install_dir)
        if not ok:
            write_log(Path(log_path), "INFO", "uninstaller", "cancelled_by_user")
            print("Cancelled")
            return 0

    try:
        if not install_dir.exists():
            write_log(Path(log_path), "WARN", "uninstaller", "install_dir_not_found", path=str(install_dir))
            print(f"Install directory not found: {install_dir}")
            return 2

        write_log(Path(log_path), "INFO", "uninstaller", "removing_install_dir", path=str(install_dir))
        remove_path(install_dir)
        write_log(Path(log_path), "INFO", "uninstaller", "removed_install_dir", path=str(install_dir))

        if args.remove_user_data:
            try:
                user_data = resolve_user_data_dir()
                if user_data.exists():
                    write_log(Path(log_path), "INFO", "uninstaller", "removing_user_data", path=str(user_data))
                    remove_path(user_data)
                    write_log(Path(log_path), "INFO", "uninstaller", "removed_user_data", path=str(user_data))
            except Exception as e:
                write_log(Path(log_path), "WARN", "uninstaller", "remove_user_failed", error=str(e))

        write_log(Path(log_path), "INFO", "uninstaller", "completed")
        print(f"Uninstalled: {install_dir}")
        return 0
    except Exception as e:
        write_log(Path(log_path), "ERROR", "uninstaller", "failed", error=str(e))
        print(f"Uninstall failed: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
