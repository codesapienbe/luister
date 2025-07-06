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
from PyQt6.QtCore import QRect, Qt, QPointF
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
        self._duplication_count = 3  # Number of element copies
        self._spread_factor = 0.15   # Coordinate spread percentage

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
            # vertical bars with ghosting effect
            bar_width = w / bands if bands else w
            for i, magnitude in enumerate(mags):
                for dup in range(self._duplication_count):
                    offset = (dup + 1) * w * 0.01
                    height = int((magnitude ** self._sensitivity_exponent) * h * 0.6 * (0.8 ** dup))
                    alpha = int(255 * (0.6 ** dup))
                    painter.setBrush(QColor(255, 163 + dup*30, 25, alpha))
                    painter.drawRect(
                        int(bar_width * i + offset),
                        h - height,
                        int(bar_width * 0.6),
                        height
                    )
                    # horizontally mirrored duplicate
                    mirror_x = w - (bar_width * i + offset) - int(bar_width * 0.6)
                    painter.drawRect(
                        int(mirror_x),
                        h - height,
                        int(bar_width * 0.6),
                        height
                    )
                    # vertically flipped duplicate (drawn from top)
                    painter.drawRect(
                        int(bar_width * i + offset),
                        0,
                        int(bar_width * 0.6),
                        height
                    )
        elif self._style_index == 1:
            # filled area with multiple reflection layers
            for dup in range(1, self._duplication_count + 1):
                path = QPainterPath()
                path.moveTo(0, h)
                y_offset = dup * 10
                scale_factor = 1 - (dup * 0.1)
                
                for i, magnitude in enumerate(mags):
                    x = int(i * (w / bands))
                    y = int(h - (magnitude * h * scale_factor) - y_offset)
                    path.lineTo(x, y)
                
                path.lineTo(w, h)
                painter.fillPath(path, QColor(25, 255, 163, 50 // dup))
                # horizontal mirror of the filled area
                painter.save()
                painter.translate(w, 0)
                painter.scale(-1, 1)
                painter.fillPath(path, QColor(25, 255, 163, 50 // dup))
                painter.restore()
                # vertical mirror of the filled area
                painter.save()
                painter.translate(0, h)
                painter.scale(1, -1)
                painter.fillPath(path, QColor(25, 255, 163, 50 // dup))
                painter.restore()
        elif self._style_index == 2:
            # radial lines with positional offsets and rotational duplication
            center_base = QPointF(self.rect().center())
            shifts = [
                (i - self._duplication_count // 2) * w * self._spread_factor
                for i in range(self._duplication_count)
            ]
            centers = [QPointF(center_base.x() + dx, center_base.y()) for dx in shifts]
            for c in centers:
                for i, magnitude in enumerate(mags):
                    line_length = magnitude * min(w, h) * 0.4
                    for angle in range(0, 360, 360 // (self._duplication_count + 2)):
                        rad = math.radians(angle + i * 5)
                        end_point = QPointF(
                            c.x() + line_length * math.cos(rad),
                            c.y() + line_length * math.sin(rad)
                        )
                        painter.drawLine(c, end_point)
        elif self._style_index == 3:
            # line spectrum with parallel echoes
            for dup in range(self._duplication_count):
                y_base = h * (0.2 + 0.1 * dup)
                path = QPainterPath()
                path.moveTo(0, y_base)
                for i, magnitude in enumerate(mags):
                    x = int(i * (w / bands))
                    y = y_base - magnitude * h * 0.4
                    path.lineTo(x, y)
                    if dup > 0:
                        path.addEllipse(x, y, 3 + dup*2, 3 + dup*2)
                painter.drawPath(path)
                # horizontal mirror of the spectrum path
                painter.save()
                painter.translate(w, 0)
                painter.scale(-1, 1)
                painter.drawPath(path)
                painter.restore()
                # vertical mirror of the spectrum path
                painter.save()
                painter.translate(0, h)
                painter.scale(1, -1)
                painter.drawPath(path)
                painter.restore()
        elif self._style_index == 4:
            # circles with concentric rings at multiple positions
            center_base = QPointF(self.rect().center())
            max_radius = min(w, h) * 0.4
            shifts = [
                (i - self._duplication_count // 2) * w * self._spread_factor
                for i in range(self._duplication_count)
            ]
            centers = [QPointF(center_base.x() + dx, center_base.y()) for dx in shifts]
            for c in centers:
                for i, magnitude in enumerate(mags):
                    for dup in range(self._duplication_count):
                        radius = (
                            max_radius
                            * (i / bands)
                            * (1 + 0.1 * dup)
                            * magnitude
                        )
                        alpha = int(255 * (0.7 ** dup))
                        painter.setBrush(QColor(255, 25, 163, alpha // 2))
                        painter.drawEllipse(c, radius, radius)
        painter.end() 