#!/usr/bin/env python3
"""Prove the pinned yt-dlp can still pull audio from YouTube.

Checking that the import works is not enough: the failure mode that matters is
metadata resolving fine while the media transfer 403s. So this actually
downloads a short public video and asserts a file lands on disk.

Exit codes: 0 success, 1 broken, 75 (EX_TEMPFAIL) network/unavailable so CI can
tell "yt-dlp is broken" apart from "GitHub could not reach YouTube".
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# "Me at the zoo" - the oldest video on YouTube, 19 seconds long and
# unlikely to vanish.
TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def main() -> int:
    try:
        import yt_dlp
    except ImportError:
        print("FAIL: yt-dlp is not installed", file=sys.stderr)
        return 1

    print(f"yt-dlp version: {yt_dlp.version.__version__}")

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        opts = {
            "format": "bestaudio/best",
            "outtmpl": str(out / "probe.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }
            ],
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(TEST_URL, download=False)
                if not info or not info.get("title"):
                    print("FAIL: metadata extraction returned nothing",
                          file=sys.stderr)
                    return 1
                print(f"metadata OK: {info['title']}")

                ydl.download([TEST_URL])
        except Exception as exc:  # noqa: BLE001 - we classify below
            message = str(exc)
            print(f"download failed: {message}", file=sys.stderr)
            transient = any(
                marker in message.lower()
                for marker in ("timed out", "temporary failure",
                               "connection reset",
                               "network is unreachable",
                               "sign in to confirm")
            )
            return 75 if transient else 1

        produced = [
            p for p in out.iterdir()
            if p.is_file() and p.stat().st_size > 0
        ]
        if not produced:
            print("FAIL: no output file was produced", file=sys.stderr)
            return 1

        for path in produced:
            print(f"downloaded OK: {path.name} ({path.stat().st_size} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
