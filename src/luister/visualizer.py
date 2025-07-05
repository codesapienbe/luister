"""Real-time audio visualizer for Luister.

Uses numpy and librosa to analyze the current audio file into magnitude bands,
then draws a bar visualization that advances with playback time.

If librosa is unavailable, the widget shows nothing but does not break the app.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
try:
    import librosa  # type: ignore[import]
except ImportError:
    librosa = None

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

class VisualizerWidget(QWidget):
    """Simple bar visualizer driven by the current audio playback."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        self._magnitudes: Optional[np.ndarray] = None
        self._times: Optional[np.ndarray] = None
        self._current_index: int = 0
        self._bar_color = QColor("#4caf50")
        self.setAutoFillBackground(False)

    def set_audio(self, file_path: str):
        """Load file_path with librosa and pre-compute magnitude per band."""
        if librosa is None:
            self._magnitudes = None
            self._times = None
            return
        try:
            y, sr = librosa.load(file_path, mono=True, sr=None)
            hop_length = 1024
            stft = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop_length))
            bands = 16
            # split frequency bins into bands and average each band
            bands_data = np.array_split(stft, bands, axis=0)
            mag_per_band = np.stack([band.mean(axis=0) for band in bands_data], axis=0)
            mag_db = librosa.amplitude_to_db(mag_per_band, ref=np.max)
            mag_db = np.clip((mag_db + 80) / 80, 0, 1)
            magnitudes = mag_db.T
            self._magnitudes = magnitudes
            self._times = librosa.frames_to_time(
                np.arange(magnitudes.shape[0]), sr=sr, hop_length=hop_length)
        except Exception:
            self._magnitudes = None
            self._times = None

    def update_position(self, ms: int):
        """Called with current playback position in milliseconds."""
        if self._times is None:
            return
        sec = ms / 1000.0
        idx = np.searchsorted(self._times, sec)
        self._current_index = max(0, min(idx, len(self._times) - 1))  # type: ignore[arg-type]
        self.update()

    def paintEvent(self, event):
        if self._magnitudes is None:
            return
        # Narrow Optional for type checker
        magnitudes: np.ndarray = self._magnitudes  # type: ignore
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        mags = magnitudes[self._current_index]
        bar_count = mags.shape[0]
        bar_width = w / bar_count if bar_count else w
        for i, mag in enumerate(mags):
            bar_h = mag * h
            rect = QRect(
                int(i * bar_width), int(h - bar_h), int(bar_width * 0.8), int(bar_h)
            )
            color = QColor(self._bar_color)
            color.setAlphaF(max(0.2, mag))
            painter.fillRect(rect, color)
        painter.end() 