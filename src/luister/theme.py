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
        pal.setColor(QPalette.ColorRole.Window, QColor("#FCFCF9"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#13343B"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFD"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#F2F2F0"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#13343B"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#EFEDE7"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#13343B"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#21808D"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FCFCF9"))
        return pal

    @staticmethod
    def dark() -> QPalette:
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#1F2121"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#F5F5F5"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#262828"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#303131"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#F5F5F5"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#2A2C2C"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#F5F5F5"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#32B8C6"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#13343B"))
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

        # --- Glassmorphic style sheet -------------------------------------------------
        if theme == "light":
            glass_bg = "#26FFFFFF"  # ~15% white
            hover_bg = "#33FFFFFF"  # ~20%
            pressed_bg = "#4DFFFFFF"  # ~30%
            border_rgba = "rgba(255,255,255,0.25)"
            groove_bg = "rgba(0,0,0,0.15)"
            input_bg = "#40FFFFFF"  # ~25%
        else:
            glass_bg = "#33FFFFFF"  # ~20% white on dark
            hover_bg = "#26FFFFFF"  # slightly less opaque
            pressed_bg = "#4DFFFFFF"
            border_rgba = "rgba(255,255,255,0.15)"
            groove_bg = "rgba(255,255,255,0.10)"
            input_bg = "#26FFFFFF"  # for dark inputs

        app.setStyleSheet(
            f"""
            /* ----- Base glass container ----- */
            QWidget {{
                background-color: {glass_bg};
                color: palette(window-text);
                border: 1px solid {border_rgba};
                border-radius: 12px;
            }}

            /* Top-level windows */
            QMainWindow {{
                background-color: {glass_bg};
                border: 1px solid {border_rgba};
                border-radius: 16px;
            }}

            /* Buttons */
            QPushButton {{
                background-color: transparent;
                color: palette(button-text);
                border: 1px solid {border_rgba};
                border-radius: 8px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{ background-color: {hover_bg}; }}
            QPushButton:pressed {{ background-color: {pressed_bg}; }}
            QPushButton:disabled {{ color: palette(mid); }}

            /* Text inputs & lists */
            QTextEdit, QListWidget, QLineEdit {{
                background-color: {input_bg};
                color: palette(text);
                border: 1px solid {border_rgba};
                border-radius: 8px;
                selection-background-color: palette(highlight);
                selection-color: palette(highlighted-text);
            }}

            /* Sliders */
            QSlider::groove:horizontal {{
                background: {groove_bg};
                height: 4px;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: palette(highlight);
                width: 14px;
                border-radius: 7px;
            }}
            """
        ) 