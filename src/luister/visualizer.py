"""Real-time audio visualizer for Luister.

Winamp-style spectrum analyzer with reactive bars.
Uses numpy and librosa to analyze the current audio file.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
try:
    import librosa  # type: ignore[import]
except ImportError:
    librosa = None

import logging

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QColor, QPainter, QLinearGradient
from PyQt6.QtWidgets import QWidget


class _AnalyzerThread(QThread):
    """Background thread that performs audio analysis."""
    analysis_finished = pyqtSignal(object, object)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path

    def run(self):
        logger = logging.getLogger(__name__)
        try:
            if librosa is not None:
                y, sr = librosa.load(self.file_path, mono=True, sr=22050)
                if self.isInterruptionRequested():
                    return
                hop_length = 512
                stft = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop_length))
                # Use 32 frequency bands for Winamp-like display
                bands = 32
                freq_bins = stft.shape[0]
                # Logarithmic frequency binning (more bins for lower frequencies)
                bin_edges = np.logspace(0, np.log10(freq_bins), bands + 1).astype(int)
                bin_edges = np.clip(bin_edges, 0, freq_bins)

                mag_per_band = []
                for i in range(bands):
                    start, end = bin_edges[i], bin_edges[i + 1]
                    if end <= start:
                        end = start + 1
                    band_mean = stft[start:end, :].mean(axis=0)
                    mag_per_band.append(band_mean)

                mag_per_band = np.array(mag_per_band)
                # Convert to dB and normalize
                mag_db = librosa.amplitude_to_db(mag_per_band, ref=np.max)
                # Normalize to 0-1 range (typical dynamic range is -80 to 0 dB)
                mag_normalized = np.clip((mag_db + 60) / 60, 0, 1)
                magnitudes = mag_normalized.T
                times = librosa.frames_to_time(np.arange(magnitudes.shape[0]), sr=sr, hop_length=hop_length)
                self.analysis_finished.emit(magnitudes, times)
                return

            # Fallback: soundfile + numpy FFT
            import soundfile as sf  # type: ignore
            data, sr = sf.read(self.file_path)
            if getattr(data, 'ndim', 1) > 1:
                data = np.mean(data, axis=1)
            hop_length = 512
            n_fft = 2048
            frames = []
            hann = np.hanning(n_fft)
            for start in range(0, max(1, len(data) - n_fft), hop_length):
                if self.isInterruptionRequested():
                    return
                frame = data[start:start + n_fft]
                if len(frame) < n_fft:
                    frame = np.pad(frame, (0, n_fft - len(frame)))
                frame = frame * hann
                spec = np.abs(np.fft.rfft(frame, n=n_fft))
                frames.append(spec)
            if not frames:
                raise RuntimeError("no frames extracted")
            stft = np.array(frames).T
            bands = 32
            freq_bins = stft.shape[0]
            bin_edges = np.logspace(0, np.log10(freq_bins), bands + 1).astype(int)
            bin_edges = np.clip(bin_edges, 0, freq_bins)

            mag_per_band = []
            for i in range(bands):
                start_bin, end_bin = bin_edges[i], bin_edges[i + 1]
                if end_bin <= start_bin:
                    end_bin = start_bin + 1
                band_mean = stft[start_bin:end_bin, :].mean(axis=0)
                mag_per_band.append(band_mean)

            mag_per_band = np.array(mag_per_band)
            mag_db = 20 * np.log10(np.maximum(mag_per_band, 1e-10))
            mag_normalized = np.clip((mag_db + 60) / 60, 0, 1)
            magnitudes = mag_normalized.T
            times = np.arange(magnitudes.shape[0]) * (hop_length / float(sr))
            self.analysis_finished.emit(magnitudes, times)
        except Exception as exc:
            logger.exception("Visualizer analysis failed: %s", exc)
            self.analysis_finished.emit(None, None)


class VisualizerWidget(QWidget):
    """Winamp-style spectrum analyzer visualizer."""
    closed = pyqtSignal()
    analysis_started = pyqtSignal()
    analysis_ready = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setMinimumWidth(200)

        # Audio data
        self._magnitudes: Optional[np.ndarray] = None
        self._times: Optional[np.ndarray] = None
        self._current_index: int = 0

        # Peak hold values (fall slowly)
        self._peaks: Optional[np.ndarray] = None
        self._peak_hold_frames = 15  # Hold peak for this many frames
        self._peak_hold_counters: Optional[np.ndarray] = None
        self._peak_fall_speed = 0.02  # How fast peaks fall

        # Smoothing for bars (prevents jitter)
        self._smoothed_mags: Optional[np.ndarray] = None
        self._smooth_factor = 0.3  # 0 = no smoothing, 1 = full smoothing

        # Animation timer
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._on_animation_tick)

        # Analysis thread
        self._analyzer_thread: Optional[_AnalyzerThread] = None
        self._analysis_timeout_timer = QTimer(self)
        self._analysis_timeout_timer.setSingleShot(True)
        self._analysis_timeout_timer.timeout.connect(self._on_analysis_timeout)

        # Visual style (0=bars, 1=mirrored bars, 2=waveform)
        self._style = 0
        self._num_styles = 3

        self.setAutoFillBackground(False)

    def set_audio(self, file_path: str):
        """Start background analysis for the audio file."""
        # Cancel any running analysis
        if self._analyzer_thread is not None and self._analyzer_thread.isRunning():
            self._analyzer_thread.requestInterruption()
            self._analyzer_thread.wait(100)

        self.pause_animation()
        self._magnitudes = None
        self._times = None
        self._peaks = None
        self._smoothed_mags = None
        self._current_index = 0

        try:
            self.analysis_started.emit()
        except Exception:
            pass

        self._analyzer_thread = _AnalyzerThread(file_path)
        self._analyzer_thread.analysis_finished.connect(self._on_analysis_done)
        self._analyzer_thread.start()
        self._analysis_timeout_timer.start(15000)  # 15s timeout

    def update_position(self, ms: int):
        """Called with current playback position in milliseconds."""
        if self._times is None:
            return
        sec = ms / 1000.0
        idx = np.searchsorted(self._times, sec)
        self._current_index = max(0, min(idx, len(self._times) - 1))

    def mouseDoubleClickEvent(self, event):
        """Cycle visual style on double click."""
        self._style = (self._style + 1) % self._num_styles
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        # Dark background
        painter.fillRect(0, 0, w, h, QColor("#0a0a0a"))

        if self._magnitudes is None:
            painter.setPen(QColor("#444444"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Loading...")
            painter.end()
            return

        if self._smoothed_mags is None:
            painter.end()
            return

        mags = self._smoothed_mags
        bands = len(mags)

        if self._style == 0:
            # Classic Winamp bars
            self._draw_bars(painter, mags, w, h, mirrored=False)
        elif self._style == 1:
            # Mirrored bars (top and bottom)
            self._draw_bars(painter, mags, w, h, mirrored=True)
        elif self._style == 2:
            # Oscilloscope-style waveform
            self._draw_waveform(painter, mags, w, h)

        painter.end()

    def _draw_bars(self, painter: QPainter, mags: np.ndarray, w: int, h: int, mirrored: bool = False):
        """Draw Winamp-style spectrum bars."""
        bands = len(mags)
        bar_width = max(4, (w - bands * 2) // bands)
        gap = 2
        total_width = bands * (bar_width + gap)
        start_x = (w - total_width) // 2

        draw_height = h if not mirrored else h // 2

        for i, mag in enumerate(mags):
            x = start_x + i * (bar_width + gap)
            bar_height = int(mag * draw_height * 0.9)

            if bar_height < 2:
                bar_height = 2

            # Create gradient for bar (green at bottom, yellow middle, red at top)
            if mirrored:
                y = draw_height - bar_height
                gradient = QLinearGradient(x, draw_height, x, y)
            else:
                y = h - bar_height
                gradient = QLinearGradient(x, h, x, y)

            gradient.setColorAt(0.0, QColor("#00ff00"))  # Green at bottom
            gradient.setColorAt(0.5, QColor("#ffff00"))  # Yellow in middle
            gradient.setColorAt(0.8, QColor("#ff8800"))  # Orange
            gradient.setColorAt(1.0, QColor("#ff0000"))  # Red at top

            painter.fillRect(x, y, bar_width, bar_height, gradient)

            # Draw peak indicator
            if self._peaks is not None and i < len(self._peaks):
                peak_height = int(self._peaks[i] * draw_height * 0.9)
                if peak_height > bar_height:
                    peak_y = draw_height - peak_height if mirrored else h - peak_height
                    painter.fillRect(x, peak_y, bar_width, 3, QColor("#ffffff"))

            # Draw mirrored bars (top half)
            if mirrored:
                mirror_y = draw_height
                gradient_mirror = QLinearGradient(x, mirror_y, x, mirror_y + bar_height)
                gradient_mirror.setColorAt(0.0, QColor("#00ff00"))
                gradient_mirror.setColorAt(0.5, QColor("#ffff00"))
                gradient_mirror.setColorAt(0.8, QColor("#ff8800"))
                gradient_mirror.setColorAt(1.0, QColor("#ff0000"))
                painter.fillRect(x, mirror_y, bar_width, bar_height, gradient_mirror)

    def _draw_waveform(self, painter: QPainter, mags: np.ndarray, w: int, h: int):
        """Draw oscilloscope-style waveform."""
        bands = len(mags)
        center_y = h // 2

        painter.setPen(QColor("#00ff00"))

        prev_x, prev_y = 0, center_y
        for i, mag in enumerate(mags):
            x = int(i * w / bands)
            # Oscillate above and below center based on band index
            direction = 1 if i % 2 == 0 else -1
            y = center_y + int(direction * mag * h * 0.4)
            painter.drawLine(prev_x, prev_y, x, y)
            prev_x, prev_y = x, y

    def _on_animation_tick(self):
        """Update smoothed values and peaks on each animation frame."""
        if self._magnitudes is None:
            return

        # Get current raw magnitudes
        raw_mags = self._magnitudes[self._current_index]
        bands = len(raw_mags)

        # Initialize smoothed mags if needed
        if self._smoothed_mags is None or len(self._smoothed_mags) != bands:
            self._smoothed_mags = np.zeros(bands)
            self._peaks = np.zeros(bands)
            self._peak_hold_counters = np.zeros(bands)

        # Apply smoothing (exponential moving average)
        self._smoothed_mags = self._smooth_factor * self._smoothed_mags + (1 - self._smooth_factor) * raw_mags

        # Update peaks
        for i in range(bands):
            if self._smoothed_mags[i] >= self._peaks[i]:
                # New peak
                self._peaks[i] = self._smoothed_mags[i]
                self._peak_hold_counters[i] = self._peak_hold_frames
            else:
                # Peak hold or fall
                if self._peak_hold_counters[i] > 0:
                    self._peak_hold_counters[i] -= 1
                else:
                    self._peaks[i] = max(0, self._peaks[i] - self._peak_fall_speed)

        self.update()

    def _on_analysis_done(self, magnitudes, times):
        """Called when audio analysis completes."""
        self._analysis_timeout_timer.stop()

        if magnitudes is None or times is None:
            try:
                self.analysis_ready.emit(False)
            except Exception:
                pass
            return

        self._magnitudes = magnitudes
        self._times = times
        bands = magnitudes.shape[1] if magnitudes.ndim > 1 else 32
        self._peaks = np.zeros(bands)
        self._peak_hold_counters = np.zeros(bands)
        self._smoothed_mags = np.zeros(bands)

        self.resume_animation()
        self.update()

        try:
            self.analysis_ready.emit(True)
        except Exception:
            pass

    def _on_analysis_timeout(self):
        """Handle analysis timeout."""
        if self._analyzer_thread is not None and self._analyzer_thread.isRunning():
            self._analyzer_thread.requestInterruption()
            self._analyzer_thread.wait(200)
            if self._analyzer_thread.isRunning():
                self._analyzer_thread.terminate()
        try:
            self.analysis_ready.emit(False)
        except Exception:
            pass

    def pause_animation(self):
        """Stop animation timer."""
        if self._animation_timer.isActive():
            self._animation_timer.stop()

    def resume_animation(self):
        """Start animation timer."""
        if not self._animation_timer.isActive():
            self._animation_timer.start(33)  # ~30 FPS

    def closeEvent(self, event):
        try:
            self.closed.emit()
        except Exception:
            pass
        event.ignore()
        self.hide()
