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
        # Crystal glass inspired light palette: cool neutrals with soft cyan highlights
        pal.setColor(QPalette.ColorRole.Window, QColor("#F6F8FA"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#0F2933"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#F2F6F8"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#0F2933"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#F8FBFC"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#0F2933"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#5AC8FA"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
        return pal

    @staticmethod
    def dark() -> QPalette:
        pal = QPalette()
        # Crystal glass inspired dark palette: translucent dark surfaces with cool cyan accent
        pal.setColor(QPalette.ColorRole.Window, QColor("#111417"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#E8F6F9"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#0F1214"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#151819"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#E8F6F9"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#121416"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#E8F6F9"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#39BEE6"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#0F2933"))
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
        # Tuned glass variables for a Crystal Glass look
        if theme == "light":
            glass_bg = "#1AFFFFFF"  # subtle translucent white (~10%)
            hover_bg = "#26FFFFFF"  # ~15%
            pressed_bg = "#33FFFFFF"  # ~20%
            border_rgba = "rgba(255,255,255,0.22)"
            groove_bg = "rgba(15,41,51,0.06)"
            input_bg = "#28FFFFFF"  # ~16%
        else:
            glass_bg = "#22000000"  # translucent black (~13%) on dark
            hover_bg = "#26FFFFFF"  # use light overlay for hover to mimic glossy effect
            pressed_bg = "#33FFFFFF"
            border_rgba = "rgba(255,255,255,0.08)"
            groove_bg = "rgba(255,255,255,0.04)"
            input_bg = "#22FFFFFF"  # subtle overlay for inputs

        app.setStyleSheet(
            f"""
            /* ----- Base glass container ----- */
            QMainWindow, QDialog {{
                background-color: {glass_bg};
                /* subtle vertical sheen to mimic polished glass */
                background-image: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,255,255,0.16), stop:0.5 rgba(255,255,255,0.06), stop:1 rgba(255,255,255,0.03));
                color: palette(window-text);
                border: 1px solid {border_rgba};
                border-radius: 16px;
                padding: 6px;
            }}

            /* Ensure child widgets use the application's base palette to avoid nested rounded borders */
            QWidget {{
                background-color: palette(base);
                color: palette(window-text);
                border: none;
                border-radius: 8px;
            }}

            /* Panels that intentionally want the glass look */
            QFrame[frameShape="Panel"] {{
                background-color: {glass_bg};
                border-radius: 12px;
                border: 1px solid rgba(255,255,255,0.08);
            }}

            /* Buttons: softer rounded capsules with inner highlight */
            QPushButton {{
                background-color: rgba(255,255,255,0.02);
                color: palette(button-text);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{ background-color: {hover_bg}; }}
            QPushButton:pressed {{ background-color: {pressed_bg}; }}
            QPushButton:disabled {{ color: palette(mid); }}

            /* Text inputs & lists: frosted glass surfaces with subtle inner shadow feel */
            QTextEdit, QListWidget, QLineEdit {{
                background-color: {input_bg};
                color: palette(text);
                border: 1px solid rgba(0,0,0,0.06);
                border-radius: 10px;
                selection-background-color: palette(highlight);
                selection-color: palette(highlighted-text);
            }}

            /* Sliders: thin groove with highlight handle */
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