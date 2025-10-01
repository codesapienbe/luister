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

import logging

import math
import random
from PyQt6.QtCore import QRect, Qt, QPointF, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QColor, QPainter, QPen, QPainterPath
from PyQt6.QtWidgets import QWidget


class _AnalyzerThread(QThread):
    """Background thread that performs audio analysis (prefers librosa).

    Emits (magnitudes, times) via the analysis_finished signal on completion. Both
    values may be None on failure.
    """
    analysis_finished = pyqtSignal(object, object)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path

    def run(self):
        import logging
        logger = logging.getLogger(__name__)
        try:
            # Prefer librosa analysis when available (best results)
            if librosa is not None:
                y, sr = librosa.load(self.file_path, mono=True, sr=None)
                # honour interruption request after load
                if self.isInterruptionRequested():
                    return
                hop_length = 1024
                stft = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop_length))
                bands = 16
                bands_data = np.array_split(stft, bands, axis=0)
                mag_per_band = np.stack([band.mean(axis=0) for band in bands_data], axis=0)
                mag_db = librosa.amplitude_to_db(mag_per_band, ref=np.max)
                mag_db = np.clip((mag_db + 80) / 80, 0, 1)
                magnitudes = mag_db.T
                times = librosa.frames_to_time(np.arange(magnitudes.shape[0]), sr=sr, hop_length=hop_length)
                self.analysis_finished.emit(magnitudes, times)
                return

            # Fallback: soundfile + numpy FFT
            import soundfile as sf  # type: ignore
            data, sr = sf.read(self.file_path)
            if getattr(data, 'ndim', 1) > 1:
                data = np.mean(data, axis=1)
            hop_length = 1024
            n_fft = 2048
            frames = []
            hann = np.hanning(n_fft)
            for start in range(0, max(1, len(data) - n_fft), hop_length):
                # allow cooperative interruption
                if self.isInterruptionRequested():
                    return
                frame = data[start:start + n_fft]
                if len(frame) < n_fft:
                    frame = np.pad(frame, (0, n_fft - len(frame)))
                frame = frame * hann
                spec = np.abs(np.fft.rfft(frame, n=n_fft))
                frames.append(spec)
            if not frames:
                raise RuntimeError("no frames extracted for analysis")
            stft = np.array(frames).T
            bands = 16
            bands_data = np.array_split(stft, bands, axis=0)
            mag_per_band = np.stack([band.mean(axis=0) for band in bands_data], axis=0)
            mag_db = 20 * np.log10(np.maximum(mag_per_band, 1e-10))
            mag_db = np.clip((mag_db + 80) / 80, 0, 1)
            magnitudes = mag_db.T
            times = np.arange(magnitudes.shape[0]) * (hop_length / float(sr))
            self.analysis_finished.emit(magnitudes, times)
            return
        except Exception as exc:
            logger.exception("Visualizer analysis failed for %s: %s", self.file_path, exc)

        # Last-resort placeholder so widget is not blank
        try:
            fps = 30
            duration_sec = 5
            num_frames = int(duration_sec * fps)
            bands = 16
            rng = np.random.RandomState(seed=42)
            magnitudes = rng.rand(num_frames, bands) * 0.35
            times = np.linspace(0, duration_sec, num_frames)
            self.analysis_finished.emit(magnitudes, times)
        except Exception as exc:
            logger.exception("Visualizer placeholder generation failed: %s", exc)
            self.analysis_finished.emit(None, None)


class VisualizerWidget(QWidget):
    closed = pyqtSignal()
    analysis_started = pyqtSignal()
    analysis_ready = pyqtSignal(bool)
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
        # per-item rotation bookkeeping
        self._frame_counter = 0
        self._rot_speeds: dict[tuple, float] = {}
        self._rotation_timer = QTimer(self)
        self._rotation_timer.timeout.connect(self._increment_rotation)
        # do NOT start the rotation timer automatically; only resume when analysis is ready
        # self._rotation_timer.start(30)  # ~33 FPS
        # random color palette cache
        self._color_cache = [self._random_color() for _ in range(256)]
        # analysis timeout (ms) and timer to cancel long-running analysis
        self._analysis_timeout_ms = 10000
        self._analysis_timeout_timer = QTimer(self)
        self._analysis_timeout_timer.setSingleShot(True)
        self._analysis_timeout_timer.timeout.connect(self._on_analysis_timeout)
        self._analyzer_thread: Optional[_AnalyzerThread] = None

    def set_audio(self, file_path: str):
        """Start background analysis for file_path and enable visualization when ready.

        Analysis is performed in a background thread to avoid blocking the UI. The
        visualizer's animation is paused until the analysis thread emits results.
        """
        logger = logging.getLogger(__name__)

        # Cancel any running analyzer thread (best effort)
        try:
            if getattr(self, '_analyzer_thread', None) is not None:
                try:
                    if self._analyzer_thread.isRunning():
                        # request interruption and give it a short grace period
                        self._analyzer_thread.requestInterruption()
                        self._analyzer_thread.wait(50)
                except Exception:
                    pass
        except Exception:
            pass

        # Pause animation until new data available
        self.pause_animation()
        self._magnitudes = None
        self._times = None
        self._current_index = 0

        # Notify UI that analysis has started and arm the timeout
        try:
            self.analysis_started.emit()
        except Exception:
            pass

        # Start background analyzer thread which prefers librosa when available
        self._analyzer_thread = _AnalyzerThread(file_path)
        self._analyzer_thread.analysis_finished.connect(self._on_analysis_done)
        self._analyzer_thread.start()
        # start timeout watchdog
        try:
            self._analysis_timeout_timer.start(self._analysis_timeout_ms)
        except Exception:
            pass

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

        # style-based rendering with per-item rotations
        if self._style_index == 0:
            # vertical bars with ghosting effect
            bar_width = w / bands if bands else w
            for i, magnitude in enumerate(mags):
                for dup in range(self._duplication_count):
                    offset = (dup + 1) * w * 0.01
                    height = int((magnitude ** self._sensitivity_exponent) * h * 0.6 * (0.8 ** dup))
                    alpha = int(255 * (0.6 ** dup))
                    color = self._color_cache[(i+dup) % len(self._color_cache)]
                    color.setAlpha(alpha)
                    rect_x = int(bar_width * i + offset)
                    rect_y = h - height
                    rect_w = int(bar_width * 0.6)
                    rect_h = height
                    self._apply_item_rotation(painter, (0,i,dup), rect_x+rect_w/2, rect_y+rect_h/2)
                    painter.setBrush(color)
                    painter.drawRect(rect_x, rect_y, rect_w, rect_h)
                    painter.restore()
                    # horizontally mirrored duplicate
                    mirror_x = w - (bar_width * i + offset) - int(bar_width * 0.6)
                    self._apply_item_rotation(painter, (0,i,dup,'mirror'), mirror_x+rect_w/2, rect_y+rect_h/2)
                    painter.setBrush(color)
                    painter.drawRect(int(mirror_x), rect_y, rect_w, rect_h)
                    painter.restore()
                    # vertically flipped duplicate (drawn from top)
                    top_y = 0
                    self._apply_item_rotation(painter, (0,i,dup,'flip'), rect_x+rect_w/2, top_y+rect_h/2)
                    painter.setBrush(color)
                    painter.drawRect(rect_x, top_y, rect_w, rect_h)
                    painter.restore()
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
                col = self._random_color(50 // dup)
                # rotate path around center
                self._apply_item_rotation(painter, (1,dup), w/2, h/2)
                painter.fillPath(path, col)
                painter.restore()
                # horizontal mirror of the filled area
                painter.save()
                painter.translate(w, 0)
                painter.scale(-1, 1)
                painter.fillPath(path, col)
                painter.restore()
                # vertical mirror of the filled area
                painter.save()
                painter.translate(0, h)
                painter.scale(1, -1)
                painter.fillPath(path, col)
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
                        ang_key = (2,i,angle)
                        dynamic_angle = math.radians(self._get_angle(ang_key))
                        end_point = QPointF(
                            c.x() + line_length * math.cos(rad + dynamic_angle),
                            c.y() + line_length * math.sin(rad + dynamic_angle)
                        )
                        pen = QPen(self._random_color())
                        painter.setPen(pen)
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
                self._apply_item_rotation(painter, (3,dup), w/2, y_base)
                painter.setPen(QPen(self._random_color()))
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
                        col = self._random_color(alpha // 2)
                        self._apply_item_rotation(painter, (4,i,dup), c.x(), c.y())
                        painter.setBrush(col)
                        painter.drawEllipse(c, radius, radius)
                        painter.restore()
        painter.end()

    def _increment_rotation(self):
        self._frame_counter += 1
        self.update()

    def _get_angle(self, key: tuple) -> float:
        """Return current rotation angle for a given visual element key."""
        if key not in self._rot_speeds:
            # random speed between -3 and 3 deg per frame, excluding very slow
            speed = 0.0
            while abs(speed) < 0.2:
                speed = random.uniform(-3.0, 3.0)
            self._rot_speeds[key] = speed
        return (self._rot_speeds[key] * self._frame_counter) % 360

    def _apply_item_rotation(self, painter: QPainter, key: tuple, cx: float, cy: float):
        angle = self._get_angle(key)
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(angle)
        painter.translate(-cx, -cy)

    def _random_color(self, alpha: int = 255) -> QColor:
        """Return a bright random color."""
        hue = random.randint(0, 359)
        return QColor.fromHsv(hue, 255, 255, alpha)

    def pause_animation(self):
        """Stop internal rotation timer for idle state."""
        if self._rotation_timer.isActive():
            self._rotation_timer.stop()

    def resume_animation(self):
        """Restart rotation timer when playback resumes."""
        if not self._rotation_timer.isActive():
            self._rotation_timer.start(30) 

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event) 

    def _on_analysis_done(self, magnitudes, times):
        """Slot invoked from analyzer thread when analysis finishes."""
        try:
            # stop timeout watchdog
            try:
                if self._analysis_timeout_timer.isActive():
                    self._analysis_timeout_timer.stop()
            except Exception:
                pass

            if magnitudes is None or times is None:
                # keep magnitudes None to indicate not ready
                self._magnitudes = None
                self._times = None
                try:
                    self.analysis_ready.emit(False)
                except Exception:
                    pass
                return
            self._magnitudes = magnitudes
            self._times = times
            # Start animation and ask for an immediate repaint
            self.resume_animation()
            self.update()
            try:
                self.analysis_ready.emit(True)
            except Exception:
                pass
        except Exception:
            pass

    def _on_analysis_timeout(self):
        """Called when analysis exceeds allowed duration; attempt to cancel thread."""
        try:
            if getattr(self, '_analyzer_thread', None) is None:
                return
            thr = self._analyzer_thread
            # Cooperative interruption request
            try:
                thr.requestInterruption()
            except Exception:
                pass
            # wait briefly
            try:
                thr.wait(200)
            except Exception:
                pass
            # if still running, force-terminate as last resort
            if thr.isRunning():
                try:
                    thr.terminate()
                except Exception:
                    pass
            # inform UI that analysis failed due to timeout
            try:
                self.analysis_ready.emit(False)
            except Exception:
                pass
        except Exception:
            pass 