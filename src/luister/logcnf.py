"""Centralised logging configuration for Luister.

Creates ~/.luisters/logs/app.log and writes JSON lines that follow
OpenTelemetry Log Data Model. Falls back to basic logging if the
opentelemetry SDK is not present.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from types import FrameType
from typing import Any, Mapping

_LOG_DIR = Path.home() / ".luisters" / "logs"
_LOG_FILE = _LOG_DIR / "app.log"

# List of Python log levels to OTEL severity numbers as per spec
_OTEL_LEVELS = {
    "CRITICAL": 9,
    "ERROR": 17,
    "WARNING": 13,
    "INFO": 9,
    "DEBUG": 5,
}

class OTELJSONFormatter(logging.Formatter):
    """Formatter that outputs logs as JSON lines compatible with OTEL."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        base: Mapping[str, Any] = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "severity_text": record.levelname,
            "severity_number": _OTEL_LEVELS.get(record.levelname, 9),
            "body": super().format(record),
            "attributes": {
                "module": record.module,
                "func_name": record.funcName,
                "file_name": record.pathname,
                "line_no": record.lineno,
            },
        }
        return json.dumps(base, ensure_ascii=False)


def _ensure_log_dir() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging(level: int = logging.INFO) -> None:
    """Initialise logging for the whole application."""

    _ensure_log_dir()

    root = logging.getLogger()
    if root.handlers:  # Already configured
        return

    root.setLevel(level)

    # File handler with OTEL JSON format
    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    formatter = OTELJSONFormatter("%(message)s")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Console handler in simple format for convenience
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root.addHandler(console_handler)

    root.debug("Logging initialised. Logs at %s", _LOG_FILE)


# ---------------- Utility decorator ----------------- #

def log_call(level: int = logging.DEBUG):  # noqa: D401
    """Decorator that logs function entry and exit with arguments."""

    def decorator(func):
        import functools

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logging.log(level, "→ %s args=%s kwargs=%s", func.__qualname__, args[1:], kwargs)
            import inspect
            params = inspect.signature(func).parameters
            # if function expects only 'self', drop extra Qt signal args
            if len(params) == 1:
                result = func(args[0])
            else:
                result = func(*args, **kwargs)
            logging.log(level, "← %s returned %s", func.__qualname__, result)
            return result

        return wrapper

    return decorator 