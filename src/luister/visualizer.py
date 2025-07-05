"""Real-time audio visualizer for Luister.

Uses librosa to analyse the audio file into magnitude bands, then draws a bar
visualisation that advances with playback time.

If *librosa* is unavailable, the widget shows nothing but does not break the
app.
"""

from __future__ import annotations

import math
from typing import Optional, TYPE_CHECKING, Any

from PyQt6.QtCore import QTimer, Qt, QRect
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

try:
    import librosa  # type: ignore
    import numpy as np  # type: ignore
except ImportError:  # optional dependency not installed
    librosa = None  # type: ignore
    np = None  # type: ignore


class VisualizerWidget(QWidget):
    """Simple bar visualizer driven by pre-computed magnitude data."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        self._magnitudes: Optional[Any] = None  # ndarray when numpy present
        self._times: Optional[Any] = None  # frame timestamps sec
        self._current_index: int = 0
        # timer not strictly needed; driven by external update_position
        self._bar_color = QColor("#4caf50")
        self.setAutoFillBackground(False)

    # ---------------- Public API ---------------- #

    def set_audio(self, file_path: str):
        """Load *file_path* with librosa and pre-compute magnitude per band."""
        if librosa is None:
            self._magnitudes = None
            self._times = None
            return
        try:
            y, sr = librosa.load(file_path, mono=True, sr=None)
            hop_length = 1024
            stft = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop_length))  # type: ignore[attr-defined]
            # average magnitude in 16 frequency bins per frame
            bands = 16
            mag_per_band = stft.reshape(bands, -1, stft.shape[1]).mean(axis=1)  # type: ignore[attr-defined]
            # Use log scale
            mag_db = librosa.amplitude_to_db(mag_per_band, ref=np.max)  # type: ignore[attr-defined]
            mag_db = np.clip((mag_db + 80) / 80, 0, 1)  # type: ignore[attr-defined]
            self._magnitudes = mag_db.T  # shape (frames, bands)
            self._times = librosa.frames_to_time(np.arange(self._magnitudes.shape[0]), sr=sr, hop_length=hop_length)  # type: ignore[attr-defined]
        except Exception:
            self._magnitudes = None
            self._times = None

    def update_position(self, ms: int):
        """Called with current playback position in milliseconds."""
        if self._times is None:
            return
        sec = ms / 1000.0
        idx = np.searchsorted(self._times, sec)  # type: ignore[attr-defined]
        self._current_index = max(0, min(idx, len(self._times) - 1))
        self.update()  # trigger repaint

    # ---------------- Paint ---------------- #

    def paintEvent(self, event):  # noqa: D401
        if self._magnitudes is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        bands = self._magnitudes.shape[1]
        bar_width = w / bands
        mags = self._magnitudes[self._current_index]
        for i, mag in enumerate(mags):
            bar_h = mag * h
            rect = QRect(int(i * bar_width), int(h - bar_h), int(bar_width * 0.8), int(bar_h))
            color = QColor(self._bar_color)
            color.setAlphaF(max(0.2, mag))
            painter.fillRect(rect, color)
        painter.end() 