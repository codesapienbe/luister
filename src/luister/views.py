import sys
from PyQt6.QtWidgets import (
    QMainWindow,
    QApplication,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QListWidget,
    QTextEdit,
    QMenu,
)
from PyQt6.QtCore import Qt, QMimeData, pyqtSignal
from PyQt6.QtGui import QDropEvent, QAction

class SongListWidget(QListWidget):
    """QListWidget that accepts audio files via drag-and-drop."""

    # Signal emitted when user requests lyrics download for a specific item index
    lyricsRequested = pyqtSignal(int)
    # Signal emitted when user requests to remove an item
    removeRequested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._apply_palette_colors()
        # update colors when palette changes
        QApplication.instance().installEventFilter(self)  # type: ignore

    def _apply_palette_colors(self):
        # Use Qt palette-sensitive CSS values
        self.setStyleSheet("QListWidget { background-color: palette(base); color: palette(text); selection-background-color: palette(highlight); selection-color: palette(highlighted-text); }")

    def _show_context_menu(self, pos):
        """Show context menu for playlist items."""
        item = self.itemAt(pos)
        if item is None:
            return

        # Get the index from the item text (format: "1. filename.mp3")
        try:
            index = int(item.text().split('.')[0]) - 1
        except (ValueError, IndexError):
            return

        menu = QMenu(self)

        # Download Lyrics action
        lyrics_action = QAction("Download Lyrics", self)
        lyrics_action.triggered.connect(lambda: self.lyricsRequested.emit(index))
        menu.addAction(lyrics_action)

        menu.addSeparator()

        # Remove from playlist action
        remove_action = QAction("Remove from Playlist", self)
        remove_action.triggered.connect(lambda: self.removeRequested.emit(index))
        menu.addAction(remove_action)

        menu.exec(self.mapToGlobal(pos))

    def eventFilter(self, obj, event):  # type: ignore[override]
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.ApplicationPaletteChange:
            self._apply_palette_colors()
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime and mime.hasUrls():  # type: ignore[attr-defined]
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        mime = event.mimeData()
        if mime and mime.hasUrls():  # type: ignore[attr-defined]
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent):
        mime = event.mimeData()
        if mime and mime.hasUrls():  # type: ignore[attr-defined]
            urls = mime.urls()  # type: ignore[attr-defined]
            win = self.window()
            if hasattr(win, 'handle_dropped_urls'):
                win.handle_dropped_urls(urls)  # type: ignore[reportAttributeAccessIssue]
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

class PlaylistUI(QMainWindow):
    filesDropped = pyqtSignal(list)  # list of file paths

    def __init__(self, main_window=None):
        super().__init__(parent=main_window)
        self.main_window = main_window

        # --- Build UI programmatically (Designer-free) ---
        self.setWindowTitle("Playlist")
        self.setObjectName("winamp_playlist")

        central = QWidget(self)
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Drag-and-drop capable song list
        self.list_songs = SongListWidget(self)
        self.list_songs.setObjectName("list_songs")
        layout.addWidget(self.list_songs, stretch=1)

        # Optional time display area (mirrors old UI element)
        self.time_song_text = QTextEdit(self)
        self.time_song_text.setObjectName("time_song_text")
        self.time_song_text.setFixedHeight(24)
        self.time_song_text.setEnabled(False)
        layout.addWidget(self.time_song_text)

        # Placeholder transport buttons kept for API compatibility (hidden)
        self.pl_back_btn = QPushButton("⏪", self)
        self.pl_play_btn = QPushButton("▶️", self)
        self.pl_pause_btn = QPushButton("⏸️", self)
        self.pl_stop_btn = QPushButton("⏹", self)
        self.pl_next_btn = QPushButton("⏩", self)
        self.pl_download_btn = QPushButton("⏏️", self)
        for _btn in (self.pl_back_btn, self.pl_play_btn, self.pl_pause_btn, self.pl_stop_btn, self.pl_next_btn, self.pl_download_btn):
            _btn.hide()

        # Ensure stylesheet cleans any inline defaults
        self._clear_inline_styles()

        self.show()

    def handle_dropped_urls(self, urls):
        paths = [url.toLocalFile() for url in urls]
        if paths:
            self.filesDropped.emit(paths)

    # ---- style cleanup ----

    def _clear_inline_styles(self):
        from PyQt6.QtWidgets import QWidget
        stack = [self]
        while stack:
            w = stack.pop()
            if isinstance(w, QWidget) and w.styleSheet():  # type: ignore[arg-type]
                w.setStyleSheet("")
            stack.extend(list(w.findChildren(QWidget)))  # type: ignore[arg-type]

    # --- UX: hide instead of destroy ---

    def closeEvent(self, event):  # noqa: D401
        """When user clicks ✕, just hide the window so it can be reopened."""
        event.ignore()
        self.hide()

    # Qt Designer may auto-connect item signals expecting this slot; forward to main window
    def clicked_song(self, item):  # noqa: D401
        if self.main_window is not None and hasattr(self.main_window, 'clicked_song'):
            self.main_window.clicked_song(item)

if __name__=='__main__':
    app = QApplication(sys.argv)
    UIWindow = PlaylistUI()
    app.exec()