"""Tests for theme, utils, logcnf and manager."""

import json
import logging

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from luister import logcnf, utils
from luister.manager import _Manager, get_manager
from luister.theme import Theme


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


# --- theme ----------------------------------------------------------------


@pytest.mark.parametrize("name", ["light", "dark"])
def test_theme_apply_sets_palette_and_stylesheet(app, name):
    Theme.apply(app, name)
    pal = Theme.light() if name == "light" else Theme.dark()
    assert app.palette().window().color() == pal.window().color()
    assert "QMainWindow" in app.styleSheet()
    Theme.apply(app, name)  # re-apply is harmless


def test_light_and_dark_palettes_differ():
    assert Theme.light().window().color() != Theme.dark().window().color()


# --- utils ----------------------------------------------------------------


def test_convert_duration_to_show():
    # 90 s is 1 min 30 s, not "1.50" decimal minutes
    assert utils.convert_duration_to_show(90000) == ["1", "30"]


def test_get_html_embeds_time():
    html = utils.get_html("3:45")
    assert "3:45" in html and html.strip().startswith("<!DOCTYPE")


# --- manager --------------------------------------------------------------


def test_manager_register_and_shutdown(app):
    mgr = get_manager()
    assert mgr is get_manager()
    mgr.register(None)
    assert mgr._widgets == []

    good = QWidget()
    good.show()
    gone = QWidget()
    mgr.register(good)
    mgr.register(gone)
    del gone

    class Bad:
        def close(self):
            raise RuntimeError("boom")

    bad = Bad()
    mgr.register(bad)
    mgr.shutdown()
    assert not good.isVisible()
    assert mgr._widgets == []


# --- logcnf ---------------------------------------------------------------


def test_otel_formatter_outputs_json():
    rec = logging.LogRecord("x", logging.WARNING, __file__, 7, "hello %s", ("w",), None)
    out = json.loads(logcnf.OTELJSONFormatter("%(message)s").format(rec))
    assert out["body"] == "hello w"
    assert out["severity_number"] == 13
    assert out["attributes"]["line_no"] == 7
    rec.levelname = "CUSTOM"
    out = json.loads(logcnf.OTELJSONFormatter("%(message)s").format(rec))
    assert out["severity_number"] == 9


def test_otel_severity_numbers_follow_spec():
    # OTEL: DEBUG=5, INFO=9, WARN=13, ERROR=17, FATAL=21
    assert logcnf._OTEL_LEVELS["CRITICAL"] == 21


def test_setup_logging_creates_file_and_is_idempotent(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(logcnf, "_LOG_DIR", log_dir)
    monkeypatch.setattr(logcnf, "_LOG_FILE", log_dir / "app.log")
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    root.handlers = []
    try:
        logcnf.setup_logging(logging.DEBUG)
        assert len(root.handlers) == 2
        logging.getLogger("t").info("written")
        for h in root.handlers:
            h.flush()
        assert "written" in (log_dir / "app.log").read_text()
        logcnf.setup_logging()
        assert len(root.handlers) == 2
    finally:
        for h in root.handlers:
            h.close()
        root.handlers = saved
        root.setLevel(level)


def test_log_call_decorator(caplog):
    class K:
        @logcnf.log_call(logging.INFO)
        def only_self(self):
            return 1

        @logcnf.log_call()
        def with_args(self, a, b=2):
            return a + b

    k = K()
    with caplog.at_level(logging.DEBUG):
        assert k.only_self(True) == 1  # extra signal arg dropped
        assert k.with_args(1, b=3) == 4
    assert "K.with_args" in caplog.text
    assert K.only_self.__name__ == "only_self"
