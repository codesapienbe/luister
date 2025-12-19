"""Theme configuration for Luister.

Apple-inspired Crystal Glass design with beautiful glassmorphic effects.
"""
from __future__ import annotations

from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt


class Theme:
    """Namespace for theme helpers."""

    @staticmethod
    def light() -> QPalette:
        pal = QPalette()
        # Apple-inspired light palette
        pal.setColor(QPalette.ColorRole.Window, QColor("#F5F5F7"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#1D1D1F"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#F5F5F7"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#1D1D1F"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#FFFFFF"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#1D1D1F"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#007AFF"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
        pal.setColor(QPalette.ColorRole.Mid, QColor("#86868B"))
        pal.setColor(QPalette.ColorRole.Dark, QColor("#6E6E73"))
        pal.setColor(QPalette.ColorRole.Light, QColor("#FFFFFF"))
        return pal

    @staticmethod
    def dark() -> QPalette:
        pal = QPalette()
        # Apple-inspired dark palette
        pal.setColor(QPalette.ColorRole.Window, QColor("#1C1C1E"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#F5F5F7"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#2C2C2E"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#3A3A3C"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#F5F5F7"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#3A3A3C"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#F5F5F7"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#0A84FF"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
        pal.setColor(QPalette.ColorRole.Mid, QColor("#636366"))
        pal.setColor(QPalette.ColorRole.Dark, QColor("#48484A"))
        pal.setColor(QPalette.ColorRole.Light, QColor("#636366"))
        return pal

    @staticmethod
    def apply(app, theme: str) -> None:  # type: ignore
        """Apply a theme ('light' or 'dark') to QApplication."""

        if app.style().objectName() != "fusion":
            app.setStyle("Fusion")

        palette = Theme.light() if theme == "light" else Theme.dark()
        app.setPalette(palette)

        # Crystal Glass stylesheet - Apple-inspired glassmorphism
        if theme == "light":
            # Light mode colors
            bg_primary = "#FFFFFF"
            bg_secondary = "#F5F5F7"
            glass_bg = "rgba(255, 255, 255, 0.78)"
            glass_border = "rgba(255, 255, 255, 0.5)"
            glass_shadow = "rgba(0, 0, 0, 0.04)"
            text_primary = "#1D1D1F"
            text_secondary = "#86868B"
            accent = "#007AFF"
            accent_hover = "#0066CC"
            accent_pressed = "#004999"
            btn_bg = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,255,255,0.95), stop:1 rgba(245,245,247,0.9))"
            btn_hover = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,255,255,1), stop:1 rgba(240,240,242,0.95))"
            btn_pressed = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(230,230,232,0.95), stop:1 rgba(220,220,222,0.9))"
            btn_border = "rgba(0, 0, 0, 0.12)"
            btn_border_hover = "rgba(0, 122, 255, 0.5)"
            input_bg = "rgba(255, 255, 255, 0.9)"
            groove_bg = "rgba(0, 0, 0, 0.08)"
            active_indicator = "#34C759"  # Green for active state
        else:
            # Dark mode colors
            bg_primary = "#1C1C1E"
            bg_secondary = "#2C2C2E"
            glass_bg = "rgba(44, 44, 46, 0.78)"
            glass_border = "rgba(255, 255, 255, 0.08)"
            glass_shadow = "rgba(0, 0, 0, 0.3)"
            text_primary = "#F5F5F7"
            text_secondary = "#98989D"
            accent = "#0A84FF"
            accent_hover = "#409CFF"
            accent_pressed = "#0066CC"
            btn_bg = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(72,72,74,0.9), stop:1 rgba(58,58,60,0.85))"
            btn_hover = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(82,82,84,0.95), stop:1 rgba(68,68,70,0.9))"
            btn_pressed = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(58,58,60,0.95), stop:1 rgba(44,44,46,0.9))"
            btn_border = "rgba(255, 255, 255, 0.1)"
            btn_border_hover = "rgba(10, 132, 255, 0.6)"
            input_bg = "rgba(58, 58, 60, 0.8)"
            groove_bg = "rgba(255, 255, 255, 0.1)"
            active_indicator = "#30D158"  # Green for active state (dark)

        app.setStyleSheet(f"""
            /* ============ BASE STYLING ============ */
            QMainWindow {{
                background-color: {bg_primary};
            }}

            QWidget {{
                background-color: transparent;
                color: {text_primary};
                font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", sans-serif;
                font-size: 13px;
            }}

            /* ============ GLASSMORPHIC PANELS ============ */
            QFrame, QGroupBox {{
                background-color: {glass_bg};
                border: 1px solid {glass_border};
                border-radius: 12px;
            }}

            /* ============ COMPACT CIRCULAR BUTTONS ============ */
            QPushButton {{
                background: {btn_bg};
                color: {text_primary};
                border: 1px solid {btn_border};
                border-radius: 6px;
                padding: 4px 8px;
                font-weight: 500;
                font-size: 12px;
            }}

            QPushButton:hover {{
                background: {btn_hover};
                border: 1px solid {btn_border_hover};
            }}

            QPushButton:pressed {{
                background: {btn_pressed};
            }}

            QPushButton:disabled {{
                color: {text_secondary};
                opacity: 0.5;
            }}

            /* Checked state for toggle buttons */
            QPushButton:checked {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {accent}, stop:1 {accent_pressed});
                color: white;
                border: none;
            }}

            /* === ULTRA-MINIMAL 2-BUTTON CONTROLS (equal size 52px) === */
            /* Open button - circular with dropdown menu, light bg for icon visibility */
            QPushButton#open_btn {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(255,255,255,0.95), stop:1 rgba(240,240,242,0.9));
                border: 1px solid {btn_border};
                border-radius: 26px;
                padding: 0px;
            }}

            QPushButton#open_btn:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(255,255,255,1), stop:1 rgba(245,245,247,0.95));
                border: 2px solid {accent};
            }}

            QPushButton#open_btn:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(220,220,222,0.95), stop:1 rgba(210,210,212,0.9));
            }}

            QPushButton#open_btn::menu-indicator {{
                width: 0px;
                height: 0px;
            }}

            /* Play button - accent colored, white icon for contrast */
            QPushButton#play_btn {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {accent}, stop:1 {accent_pressed});
                border: none;
                border-radius: 26px;
                padding: 0px;
            }}

            QPushButton#play_btn:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {accent_hover}, stop:1 {accent});
                border: 2px solid rgba(255, 255, 255, 0.4);
            }}

            QPushButton#play_btn:pressed {{
                background: {accent_pressed};
            }}

            QPushButton#play_btn:disabled {{
                background: rgba(128, 128, 128, 0.3);
            }}

            /* ============ TEXT INPUTS ============ */
            QTextEdit, QPlainTextEdit {{
                background-color: {input_bg};
                color: {text_primary};
                border: 1px solid {glass_border};
                border-radius: 10px;
                padding: 10px;
                selection-background-color: {accent};
                selection-color: white;
                font-size: 13px;
            }}

            QTextEdit:focus, QPlainTextEdit:focus {{
                border: 2px solid {accent};
            }}

            QLineEdit {{
                background-color: {input_bg};
                color: {text_primary};
                border: 1px solid {glass_border};
                border-radius: 8px;
                padding: 8px 12px;
                selection-background-color: {accent};
                font-size: 13px;
            }}

            QLineEdit:focus {{
                border: 2px solid {accent};
            }}

            /* ============ LIST WIDGETS ============ */
            QListWidget {{
                background-color: {glass_bg};
                color: {text_primary};
                border: 1px solid {glass_border};
                border-radius: 12px;
                padding: 6px;
                outline: none;
                font-size: 13px;
            }}

            QListWidget::item {{
                padding: 10px 14px;
                border-radius: 8px;
                margin: 2px 4px;
            }}

            QListWidget::item:hover {{
                background-color: rgba(128, 128, 128, 0.1);
            }}

            QListWidget::item:selected {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {accent}, stop:1 {accent_pressed});
                color: white;
                border-radius: 8px;
            }}

            /* ============ SLIDERS (with nav zones) ============ */
            QSlider {{
                height: 32px;
            }}

            QSlider#time_slider {{
                height: 40px;
            }}

            QSlider::groove:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(128, 128, 128, 0.15),
                    stop:0.15 {groove_bg},
                    stop:0.85 {groove_bg},
                    stop:1 rgba(128, 128, 128, 0.15));
                height: 6px;
                border-radius: 3px;
            }}

            QSlider#time_slider::groove:horizontal {{
                height: 8px;
                border-radius: 4px;
            }}

            QSlider::sub-page:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {accent}, stop:1 {accent_hover});
                border-radius: 3px;
            }}

            QSlider#time_slider::sub-page:horizontal {{
                border-radius: 4px;
            }}

            QSlider::handle:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FFFFFF, stop:1 #E8E8E8);
                width: 20px;
                height: 20px;
                margin: -7px 0;
                border-radius: 10px;
                border: 1px solid rgba(0, 0, 0, 0.15);
            }}

            QSlider#time_slider::handle:horizontal {{
                width: 24px;
                height: 24px;
                margin: -8px 0;
                border-radius: 12px;
            }}

            QSlider::handle:horizontal:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FFFFFF, stop:1 #F0F0F0);
                border: 2px solid {accent};
            }}

            /* ============ PROGRESS BAR (download indicator) ============ */
            QProgressBar {{
                background-color: {groove_bg};
                border: none;
                border-radius: 12px;
                min-height: 24px;
                text-align: center;
                font-size: 11px;
                color: {text_secondary};
            }}

            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {accent}, stop:1 {accent_hover});
                border-radius: 12px;
            }}

            QProgressBar#yt_progress {{
                min-height: 24px;
                border-radius: 12px;
            }}

            /* ============ SCROLL BARS ============ */
            QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 4px 2px;
                border-radius: 5px;
            }}

            QScrollBar::handle:vertical {{
                background: rgba(128, 128, 128, 0.4);
                border-radius: 5px;
                min-height: 40px;
            }}

            QScrollBar::handle:vertical:hover {{
                background: rgba(128, 128, 128, 0.6);
            }}

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
                height: 0;
            }}

            QScrollBar:horizontal {{
                background: transparent;
                height: 10px;
                margin: 2px 4px;
                border-radius: 5px;
            }}

            QScrollBar::handle:horizontal {{
                background: rgba(128, 128, 128, 0.4);
                border-radius: 5px;
                min-width: 40px;
            }}

            QScrollBar::handle:horizontal:hover {{
                background: rgba(128, 128, 128, 0.6);
            }}

            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: transparent;
                width: 0;
            }}

            /* ============ DOCK WIDGETS ============ */
            QDockWidget {{
                background-color: {glass_bg};
                border: 1px solid {glass_border};
                border-radius: 14px;
                font-weight: 600;
            }}

            QDockWidget::title {{
                background: transparent;
                padding: 10px 14px;
                font-weight: 600;
                font-size: 14px;
                color: {text_primary};
            }}

            /* ============ MENUS ============ */
            QMenu {{
                background-color: {bg_secondary};
                border: 1px solid {glass_border};
                border-radius: 12px;
                padding: 8px;
            }}

            QMenu::item {{
                padding: 10px 20px 10px 14px;
                border-radius: 8px;
                margin: 2px 4px;
                font-size: 13px;
            }}

            QMenu::item:selected {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {accent}, stop:1 {accent_pressed});
                color: white;
            }}

            QMenu::separator {{
                height: 1px;
                background: {glass_border};
                margin: 6px 12px;
            }}

            /* ============ LCD DISPLAY ============ */
            QLCDNumber {{
                background-color: transparent;
                color: {text_primary};
                border: none;
            }}

            /* ============ TOOLTIPS ============ */
            QToolTip {{
                background-color: {bg_secondary};
                color: {text_primary};
                border: 1px solid {glass_border};
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 12px;
            }}

            /* ============ TAB WIDGET ============ */
            QTabWidget::pane {{
                background-color: {glass_bg};
                border: 1px solid {glass_border};
                border-radius: 12px;
            }}

            QTabBar::tab {{
                background: transparent;
                color: {text_secondary};
                padding: 10px 18px;
                margin: 2px;
                border-radius: 8px;
                font-weight: 500;
            }}

            QTabBar::tab:selected {{
                background: {btn_bg};
                color: {text_primary};
                border: 1px solid {glass_border};
            }}

            QTabBar::tab:hover:!selected {{
                background: rgba(128, 128, 128, 0.1);
            }}

            /* ============ COMBO BOX ============ */
            QComboBox {{
                background: {btn_bg};
                color: {text_primary};
                border: 1px solid {btn_border};
                border-radius: 8px;
                padding: 8px 12px;
                min-height: 24px;
            }}

            QComboBox:hover {{
                border: 1.5px solid {btn_border_hover};
            }}

            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}

            QComboBox::down-arrow {{
                width: 12px;
                height: 12px;
            }}

            QComboBox QAbstractItemView {{
                background-color: {bg_secondary};
                border: 1px solid {glass_border};
                border-radius: 8px;
                selection-background-color: {accent};
                selection-color: white;
            }}

            /* ============ SPIN BOX ============ */
            QSpinBox, QDoubleSpinBox {{
                background: {input_bg};
                color: {text_primary};
                border: 1px solid {glass_border};
                border-radius: 8px;
                padding: 6px 10px;
            }}

            QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 2px solid {accent};
            }}
        """)
