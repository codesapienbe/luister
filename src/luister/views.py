from PyQt6.QtWidgets import (
    QMainWindow,
    QApplication,
    QPushButton,
    QListWidget,
    QTextEdit,
)
from PyQt6.uic import loadUi  # type: ignore
from pathlib import Path
import sys
from PyQt6.QtCore import Qt, QMimeData, pyqtSignal
from PyQt6.QtGui import QDropEvent

class SongListWidget(QListWidget):
    """QListWidget that accepts audio files via drag-and-drop."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._apply_palette_colors()
        # update colors when palette changes
        QApplication.instance().installEventFilter(self)  # type: ignore

    def _apply_palette_colors(self):
        # Use Qt palette-sensitive CSS values
        self.setStyleSheet("QListWidget { background-color: palette(base); color: palette(text); selection-background-color: palette(highlight); selection-color: palette(highlighted-text); }")

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

        # Load the ui file
        base_path = Path(__file__).resolve().parent
        ui_path = base_path / 'playlist.ui'
        loadUi(str(ui_path), self)

        # remove designer inline styles so palette stylesheet applies
        self._clear_inline_styles()

        # Define widgets
        # Buttons
        self.pl_back_btn = self.findChild(QPushButton, "pl_back_btn")
        self.pl_play_btn = self.findChild(QPushButton, "pl_play_btn")
        self.pl_pause_btn = self.findChild(QPushButton, "pl_pause_btn")
        self.pl_stop_btn = self.findChild(QPushButton, "pl_stop_btn")
        self.pl_next_btn = self.findChild(QPushButton, "pl_next_btn")
        self.pl_download_btn = self.findChild(QPushButton, "pl_download_btn")

        # Hide all control buttons to simplify UI
        for w in (
            self.pl_back_btn,
            self.pl_play_btn,
            self.pl_pause_btn,
            self.pl_stop_btn,
            self.pl_next_btn,
            self.pl_download_btn,
        ):
            if w is not None:
                w.hide()

        # Replace placeholder list widget with drag-drop capable one
        placeholder = self.findChild(QListWidget, 'list_songs')
        self.list_songs = SongListWidget(self)
        self.list_songs.setObjectName('list_songs')
        # Insert into UI layout at the same position
        if placeholder is not None:
            parent_layout = placeholder.parent().layout() if placeholder.parent() else None  # type: ignore[attr-defined]
            if parent_layout is not None:
                idx = parent_layout.indexOf(placeholder)
                parent_layout.removeWidget(placeholder)
                placeholder.deleteLater()
                parent_layout.insertWidget(idx, self.list_songs)
            else:
                # Fallback: no layout, just mimic geometry
                self.list_songs.setGeometry(placeholder.geometry())
                placeholder.setParent(None)
                placeholder.deleteLater()

        # Text display no longer needed
        self.time_song_text = self.findChild(QTextEdit, 'time_song_text')
        if self.time_song_text is not None:
            self.time_song_text.hide()

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