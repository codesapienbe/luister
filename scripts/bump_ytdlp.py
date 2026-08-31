#!/usr/bin/env python3
"""Pin pyproject.toml to the newest published yt-dlp release.

YouTube regularly changes its player in ways that break older yt-dlp builds -
the usual symptom is that metadata still resolves but the media download fails
with "HTTP Error 403: Forbidden". Keeping the floor pin close to upstream is
the practical mitigation, so CI runs this on a schedule.

Prints a `key=value` block on stdout for consumption via $GITHUB_OUTPUT.
Exits non-zero only on a real error; "already current" is a success.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
PIN_RE = re.compile(r'(?P<prefix>"yt-dlp>=)(?P<version>[^"]+)(?P<suffix>")')


def latest_version() -> str:
    request = urllib.request.Request(
        PYPI_URL, headers={"Accept": "application/json", "User-Agent": "luister-ci"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["info"]["version"]


def version_key(version: str) -> tuple[int, ...]:
    """yt-dlp uses date-based versions such as 2026.8.19."""
    parts = []
    for chunk in version.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def emit(**values: str) -> None:
    lines = [f"{k}={v}" for k, v in values.items()]
    print("\n".join(lines))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def main() -> int:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")

    match = PIN_RE.search(content)
    if match is None:
        print("ERROR: no yt-dlp pin found in pyproject.toml", file=sys.stderr)
        return 1

    current = match.group("version")

    try:
        latest = latest_version()
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not query PyPI: {exc}", file=sys.stderr)
        return 1

    if version_key(latest) <= version_key(current):
        emit(updated="false", current=current, latest=latest)
        return 0

    updated = PIN_RE.sub(
        lambda m: f"{m.group('prefix')}{latest}{m.group('suffix')}", content, count=1
    )
    pyproject.write_text(updated, encoding="utf-8")
    emit(updated="true", current=current, latest=latest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
