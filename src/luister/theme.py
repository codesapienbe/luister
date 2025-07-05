"""Theme configuration for Luister.

Provides light and dark QPalette instances and helper to apply them.
"""
from __future__ import annotations

from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt


class Theme:
    """Namespace for theme helpers."""

    @staticmethod
    def light() -> QPalette:
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.black)
        pal.setColor(QPalette.ColorRole.Base, QColor("#f0f0f0"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#e0e0e0"))
        pal.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.black)
        pal.setColor(QPalette.ColorRole.Button, QColor("#e0e0e0"))
        pal.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.black)
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#2196f3"))
        pal.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
        return pal

    @staticmethod
    def dark() -> QPalette:
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#121212"))
        pal.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        pal.setColor(QPalette.ColorRole.Base, QColor("#1e1e1e"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#2a2a2a"))
        pal.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        pal.setColor(QPalette.ColorRole.Button, QColor("#2a2a2a"))
        pal.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#64b5f6"))
        pal.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
        return pal

    @staticmethod
    def apply(app, theme: str) -> None:  # type: ignore
        """Apply a theme ('light' or 'dark') to QApplication.

        Qt widgets honour QPalette reliably when using the *Fusion* style.
        Native platform styles (macOS, Windows, etc.) often ignore custom
        palette roles for widgets like buttons, text edits, etc.  We therefore
        switch the application style to "Fusion" the first time this helper is
        called, then apply the palette.
        """

        # Switch to Fusion style once so palettes are respected cross-platform
        if app.style().objectName() != "fusion":
            app.setStyle("Fusion")          # ensure widgets honour QPalette

        palette = Theme.light() if theme == "light" else Theme.dark()
        app.setPalette(palette)

        # Apply a palette-aware application stylesheet so child widgets inherit
        # correct colours even if .ui files contained hard-coded styles.
        app.setStyleSheet(
            """
            /* Basic text and window */
            QWidget { background-color: palette(window); color: palette(window-text); }

            /* Buttons */
            QPushButton { background-color: palette(button); color: palette(button-text); }
            QPushButton:disabled { color: palette(mid); }

            /* Inputs */
            QTextEdit, QListWidget, QLineEdit {
                background-color: palette(base);
                color: palette(text);
                selection-background-color: palette(highlight);
                selection-color: palette(highlighted-text);
            }

            /* Sliders */
            QSlider::groove:horizontal { background: palette(mid); }
            QSlider::handle:horizontal { background: palette(button); }
            """
        ) 