from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel
from PyQt6.QtCore import QUrl, Qt, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

import logging
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


class VideoWidget(QWidget):
    """Minimal video player widget.

    - Wraps Qt's QVideoWidget when available, falls back to a placeholder QLabel when not.
    - Exposes `set_source(path_or_url: str)` to set the media and `play()`/`pause()`.
    - Emits `closed` when the user requests the widget to be closed.
    """

    closed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None, player: Optional[QMediaPlayer] = None):
        super().__init__(parent)
        self.setObjectName("video_widget")

        # Try to import QVideoWidget; fallback handled below
        try:
            from PyQt6.QtMultimediaWidgets import QVideoWidget
        except Exception:
            QVideoWidget = None
            logger.warning("QVideoWidget not available; video playback will show placeholder")

        self._video_view = None
        if QVideoWidget is not None:
            try:
                self._video_view = QVideoWidget(self)
            except Exception:
                self._video_view = None
                logger.exception("Failed to instantiate QVideoWidget")

        # Player: use provided instance so app can share audio/video pipeline, otherwise create one
        if player is not None:
            self.player = player
            self._owned_player = False
        else:
            # Create a paired player + audio output for video playback
            self.player = QMediaPlayer(self)
            audio_out = QAudioOutput(self)
            self.player.setAudioOutput(audio_out)
            self._owned_player = True

        # Attach video output if available
        try:
            if self._video_view is not None:
                self.player.setVideoOutput(self._video_view)
        except Exception:
            logger.exception("Could not attach video output to player")

        # Build UI
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        if self._video_view is not None:
            layout.addWidget(self._video_view)
        else:
            self._placeholder = QLabel("Video not supported on this platform", self)
            self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self._placeholder)

        # Controls row
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        self.play_pause_btn = QPushButton(self)
        self.play_pause_btn.setText("Play")
        self.play_pause_btn.clicked.connect(self._toggle_play)
        ctrl_row.addWidget(self.play_pause_btn)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderMoved.connect(self._on_seek)
        ctrl_row.addWidget(self.seek_slider, 1)

        self.close_btn = QPushButton(self)
        self.close_btn.setText("×")
        self.close_btn.setFixedWidth(32)
        self.close_btn.clicked.connect(self._on_close)
        ctrl_row.addWidget(self.close_btn)

        layout.addLayout(ctrl_row)

        # Connect player signals to UI
        try:
            self.player.positionChanged.connect(self._on_position_changed)
            self.player.durationChanged.connect(self._on_duration_changed)
            self.player.playbackStateChanged.connect(self._on_state_changed)
        except Exception:
            logger.exception("Failed to connect QMediaPlayer signals")

    # -- Public API -------------------------------------------------
    def set_source(self, source: str) -> None:
        """Set the media source. Accepts local file paths or HTTP/HTTPS URLs.

        This method does not start playback automatically.
        """
        try:
            if not source:
                return
            if Path(source).exists():
                url = QUrl.fromLocalFile(str(Path(source)))
            else:
                url = QUrl(source)
            self.player.setSource(url)
            logger.info("VideoWidget set source: %s", source)
        except Exception as exc:
            logger.exception("Failed to set video source: %s", exc)

    def play(self) -> None:
        try:
            self.player.play()
        except Exception:
            logger.exception("Failed to start playback")

    def pause(self) -> None:
        try:
            self.player.pause()
        except Exception:
            logger.exception("Failed to pause playback")

    def stop(self) -> None:
        try:
            self.player.stop()
        except Exception:
            logger.exception("Failed to stop playback")

    # -- Internal helpers ------------------------------------------
    def _toggle_play(self):
        try:
            state = self.player.playbackState()
            from PyQt6.QtMultimedia import QMediaPlayer as _MP
            if state == _MP.PlaybackState.PlayingState:
                self.pause()
            else:
                self.play()
        except Exception:
            logger.exception("Error toggling play state")

    def _on_seek(self, val: int) -> None:
        try:
            self.player.setPosition(val)
        except Exception:
            logger.exception("Seek failed")

    def _on_position_changed(self, pos: int) -> None:
        try:
            self.seek_slider.setValue(pos)
        except Exception:
            pass

    def _on_duration_changed(self, dur: int) -> None:
        try:
            self.seek_slider.setRange(0, dur)
        except Exception:
            pass

    def _on_state_changed(self, state) -> None:
        try:
            from PyQt6.QtMultimedia import QMediaPlayer as _MP
            if state == _MP.PlaybackState.PlayingState:
                self.play_pause_btn.setText("Pause")
            else:
                self.play_pause_btn.setText("Play")
        except Exception:
            pass

    def _on_close(self) -> None:
        # notify listeners; caller may hide/destroy or persist state
        self.closed.emit()

    def closeEvent(self, event):
        try:
            self.stop()
        except Exception:
            pass
        super().closeEvent(event) 