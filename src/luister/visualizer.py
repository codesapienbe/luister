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

import math
import random
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPainterPath
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
        # visual styles
        self._style_index = 0
        self._num_styles = 5
        # sensitivity settings to suppress low-level noise
        self._sensitivity_threshold = 0.2
        self._sensitivity_exponent = 0.5

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

    def mouseDoubleClickEvent(self, event):
        """Cycle visual style on double click."""
        self._style_index = (self._style_index + 1) % self._num_styles  # type: ignore
        self.update()

    def paintEvent(self, event):
        if self._magnitudes is None:
            return
        # get raw magnitude data and apply sensitivity mapping
        raw_mags = self._magnitudes  # type: ignore
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        # map raw magnitudes to [0,1] after threshold and exponent
        idx = self._current_index
        raw = raw_mags[idx]
        # linear threshold
        proc = np.clip((raw - self._sensitivity_threshold) / (1.0 - self._sensitivity_threshold), 0.0, 1.0)
        # non-linear curve
        mags = proc ** self._sensitivity_exponent
        bands = len(mags)
        # style-based rendering
        if self._style_index == 0:
            # vertical bars
            bar_width = w / bands if bands else w
            for i, mag in enumerate(mags):
                bar_h = mag * h
                rect = QRect(int(i * bar_width), int(h - bar_h), int(bar_width * 0.8), int(bar_h))
                color = QColor(self._bar_color)
                color.setAlphaF(max(0.2, mag))
                painter.fillRect(rect, color)
        elif self._style_index == 1:
            # area under spectrum curve
            path = QPainterPath()
            # start at bottom-left
            path.moveTo(0, h)
            # draw curve across top of bars
            for i, mag in enumerate(mags):
                x = (i / (bands - 1)) * w if bands > 1 else w / 2
                y = h - mag * h
                path.lineTo(x, y)
            # close path at bottom-right
            path.lineTo(w, h)
            path.closeSubpath()
            color = QColor(self._bar_color)
            color.setAlphaF(0.6)
            painter.fillPath(path, color)
        elif self._style_index == 2:
            # radial lines
            center_x, center_y = w / 2, h / 2
            radius = min(w, h) * 0.3
            pen = QPen(self._bar_color)
            pen.setWidth(2)
            painter.setPen(pen)
            for i, mag in enumerate(mags):
                angle = (i / bands) * 2 * math.pi
                x1 = center_x + math.cos(angle) * radius
                y1 = center_y + math.sin(angle) * radius
                x2 = center_x + math.cos(angle) * (radius + mag * radius)
                y2 = center_y + math.sin(angle) * (radius + mag * radius)
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))
        elif self._style_index == 3:
            # line spectrum
            pen = QPen(self._bar_color)
            pen.setWidth(2)
            painter.setPen(pen)
            points = []
            for i, mag in enumerate(mags):
                x = int((i / (bands - 1)) * w) if bands > 1 else w / 2
                y = int(h - mag * h)
                points.append((x, y))
            for p1, p2 in zip(points, points[1:]):
                painter.drawLine(p1[0], p1[1], p2[0], p2[1])
        elif self._style_index == 4:
            # circles
            bar_width = w / bands if bands else w
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._bar_color))
            for i, mag in enumerate(mags):
                cx = (i + 0.5) * bar_width
                cy = h / 2
                radius = mag * min(bar_width, h) * 0.5
                painter.drawEllipse(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))
        painter.end() 