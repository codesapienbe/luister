"""Shared test setup: headless Qt/Kivy and a sandboxed HOME for every test."""

import os

# Must be set before PyQt6 / Kivy are imported anywhere.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
os.environ.setdefault("KIVY_NO_FILELOG", "1")
os.environ.setdefault("KIVY_NO_CONFIG", "1")

import pytest


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path_factory, monkeypatch):
    """Keep tests off the real home directory (~/.luister, logs, configs)."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    return home
