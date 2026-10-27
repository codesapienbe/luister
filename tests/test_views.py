"""Tests for luister.views (playlist window and drag-and-drop list)."""

import runpy
import sys

import pytest
from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PyQt6.QtWidgets import QApplication, QMenu, QMainWindow

from luister.views import PlaylistUI, SongListWidget


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def pl(app):
    w = PlaylistUI()
    for name in ("one", "two", "three"):
        w.addItemWithTooltip(name)
    w.show()
    yield w
    w.close()


def _mime(urls=True):
    m = QMimeData()
    if urls:
        m.setUrls([QUrl.fromLocalFile("/a.mp3"), QUrl.fromLocalFile("/b.mp3")])
    else:
        m.setText("plain")
    return m


def _drop(widget, mime, kind):
    pos = QPointF(5, 5)
    act = Qt.DropAction.CopyAction
    if kind == "enter":
        ev = QDragEnterEvent(pos.toPoint(), act, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        widget.dragEnterEvent(ev)
    elif kind == "move":
        ev = QDragMoveEvent(pos.toPoint(), act, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        widget.dragMoveEvent(ev)
    else:
        ev = QDropEvent(pos, act, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        widget.dropEvent(ev)
    return ev


def test_drag_enter_and_move_accept_urls_only(pl):
    lw = pl.list_songs
    for kind in ("enter", "move"):
        assert _drop(lw, _mime(True), kind).isAccepted()
        assert not _drop(lw, _mime(False), kind).isAccepted()


def test_drop_urls_emits_files_dropped(pl):
    got = []
    pl.filesDropped.connect(got.append)
    ev = _drop(pl.list_songs, _mime(True), "drop")
    assert ev.isAccepted()
    assert got == [["/a.mp3", "/b.mp3"]]


def test_drop_non_urls_falls_back_and_window_without_handler(app):
    lw = SongListWidget()  # top-level: window() has no handle_dropped_urls
    ev = _drop(lw, _mime(True), "drop")
    assert ev.isAccepted()
    _drop(lw, _mime(False), "drop")


def test_handle_dropped_urls_empty_emits_nothing(pl):
    got = []
    pl.filesDropped.connect(got.append)
    pl.handle_dropped_urls([])
    assert got == []


def test_context_menu_actions(pl, monkeypatch):
    lyrics, removed = [], []
    pl.list_songs.lyricsRequested.connect(lyrics.append)
    pl.list_songs.removeRequested.connect(removed.append)
    texts = []

    def fake_exec(self, *a, **k):
        acts = [x for x in self.actions() if not x.isSeparator()]
        texts.extend(x.text() for x in acts)
        acts[self._pick].trigger()

    monkeypatch.setattr(QMenu, "exec", fake_exec)
    lw = pl.list_songs
    pos = lw.visualItemRect(lw.item(1)).center()
    monkeypatch.setattr(QMenu, "_pick", 0, raising=False)
    lw._show_context_menu(pos)
    monkeypatch.setattr(QMenu, "_pick", 1, raising=False)
    lw._show_context_menu(pos)
    assert lyrics == [1] and removed == [1]
    assert texts[:2] == ["Download Lyrics", "Remove from Playlist"]


def test_context_menu_on_empty_area_and_bad_row(pl, monkeypatch):
    called = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: called.append(1))
    lw = pl.list_songs
    lw._show_context_menu(QPoint(5, lw.viewport().height() - 2))
    assert called == []
    monkeypatch.setattr(lw, "itemAt", lambda p: lw.item(0))
    monkeypatch.setattr(lw, "row", lambda i: -1)
    lw._show_context_menu(QPoint(1, 1))
    assert called == []


def test_context_menu_via_signal(pl, monkeypatch):
    called = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: called.append(1))
    lw = pl.list_songs
    lw.customContextMenuRequested.emit(lw.visualItemRect(lw.item(0)).center())
    assert called == [1]


def test_palette_change_event_reapplies_style(pl):
    lw = pl.list_songs
    lw.setStyleSheet("")
    QApplication.sendEvent(lw, QEvent(QEvent.Type.ApplicationPaletteChange))
    assert lw.eventFilter(lw, QEvent(QEvent.Type.ApplicationPaletteChange)) is False
    assert "palette(base)" in lw.styleSheet()
    lw.setStyleSheet("")
    lw.eventFilter(lw, QEvent(QEvent.Type.None_))
    assert lw.styleSheet() == ""


def test_download_progress_lifecycle(pl):
    pl.show_download_progress("Fetching")
    assert pl._download_container.isVisible()
    assert pl._download_label.text() == "Fetching"
    pl.show_download_progress()
    assert pl._download_label.text() == "Downloading..."
    pl.update_download_progress(40)
    assert pl._download_progress.value() == 40
    assert pl._download_label.text() == "Downloading..."
    pl.update_download_progress(50, "half")
    assert pl._download_label.text() == "half"
    pl.hide_download_progress()
    assert not pl._download_container.isVisible()
    assert pl._download_label.text() == "" and pl._download_progress.value() == 0


def test_item_download_status_all_states(pl):
    lw = pl.list_songs
    pl.set_item_download_status(-1, "error")
    pl.set_item_download_status(99, "error")
    assert pl._download_status == {}
    for status, prefix in (("downloading", "⬇️ "), ("complete", "✓ "), ("error", "✗ ")):
        pl.set_item_download_status(0, status)
        assert lw.item(0).text() == prefix + "one"
    pl.set_item_download_status(0, "")
    assert lw.item(0).text() == "one"
    pl.set_item_download_status(1, "complete")
    pl.clear_download_status()
    assert pl._download_status == {}
    assert lw.item(1).text() == "two"


def test_item_download_status_item_missing(pl, monkeypatch):
    monkeypatch.setattr(pl.list_songs, "item", lambda i: None)
    pl.set_item_download_status(0, "error")
    assert pl._download_status == {}


def test_tooltip_and_elide(pl):
    assert pl.list_songs.item(0).toolTip() == "one"
    assert pl.list_songs.textElideMode() == Qt.TextElideMode.ElideRight


def test_clear_inline_styles(pl):
    assert pl.list_songs.styleSheet()
    pl._clear_inline_styles()
    assert pl.list_songs.styleSheet() == ""
    assert pl._download_label.styleSheet() == ""


def test_close_hides_instead_of_destroying(pl):
    pl.close()
    assert not pl.isVisible()
    pl.show()
    assert pl.isVisible()


def test_clicked_song_forwards_to_main_window(app):
    class Main(QMainWindow):
        seen = None

        def clicked_song(self, item):
            self.seen = item

    main = Main()
    p = PlaylistUI(main)
    p.clicked_song("x")
    assert main.seen == "x"
    PlaylistUI(QMainWindow()).clicked_song("y")  # no handler: no-op
    PlaylistUI().clicked_song("z")  # no main window: no-op


def test_module_main_block(app, monkeypatch):
    import PyQt6.QtWidgets as qtw

    class SingleApp(QApplication):
        def __new__(cls, *args):
            return app

    monkeypatch.setattr(QApplication, "exec", lambda *a: 0)
    monkeypatch.setattr(qtw, "QApplication", SingleApp)
    monkeypatch.setattr(sys, "argv", ["views"])
    runpy.run_module("luister.views", run_name="__main__")
