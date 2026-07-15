from PyQt6.QtWidgets import QWidget, QVBoxLayout, QProgressBar, QListWidget, QListWidgetItem, QMessageBox, QDialog, QComboBox, QDialogButtonBox, QFormLayout
from PyQt6.QtCore import pyqtSignal
import threading
import logging
from pathlib import Path
from typing import Any, cast, Dict
import json

# Whisper (and its torch dependency) are only imported lazily, in a background
# thread, the first time the user actually requests lyrics - importing them
# eagerly would make every app startup pay a heavy, unnecessary CPU/import cost.
MODEL_ROOT = Path.home() / ".luister" / "models"


def _load_whisper():
    """Import whisper on first use. Returns the module, or None if unavailable."""
    try:
        import whisper
        MODEL_ROOT.mkdir(parents=True, exist_ok=True)
        return whisper
    except ImportError:
        return None


# threshold for ignoring transcription when no speech detected
NO_SPEECH_THRESHOLD = 0.5

class LyricsWidget(QWidget):
    """Widget to transcribe and display timed lyrics using Whisper offline model."""

    segments_ready = pyqtSignal(object)
    closed = pyqtSignal()
    # Emitted (from the background prep thread) once the language has been
    # detected and it's safe to show the options dialog on the GUI thread.
    _prep_ready = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Progress bar to indicate transcription in progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate mode
        self.progress_bar.hide()
        # List widget to display lyric lines
        self.list_widget = QListWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.list_widget)
        self._whisper = None
        self._model = None
        self.segments: list[tuple[float, float, str]] = []
        # Transcription state
        self._transcribing = False
        self._current_audio_file: str | None = None
        # Connect signal to populate segments when ready
        self.segments_ready.connect(self._on_segments_ready)
        self._prep_ready.connect(self._on_prep_ready)

    def load_lyrics(self, file_path: str):
        """Detect language, show dropdown to select language, then transcribe audio and extract segments."""
        # check for cached transcription file
        audio_path = Path(file_path)
        cache_path = audio_path.with_suffix(audio_path.suffix + ".json")
        # Return cached segments early
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    segments = json.load(f)
            except Exception:
                segments = []
            self.segments_ready.emit(segments)
            return

        # Avoid double transcription: if currently transcribing same file, return
        if self._transcribing and self._current_audio_file == str(audio_path):
            return

        self._transcribing = True
        self._current_audio_file = str(audio_path)

        # Loading whisper/torch and running language detection is CPU-heavy and can
        # take many seconds - do all of it off the GUI thread so the rest of the
        # app (playback controls, etc.) stays responsive while it runs.
        def prepare():
            whisper = self._whisper or _load_whisper()
            if whisper is None:
                self._prep_ready.emit({
                    "error": "Error: whisper library not installed.",
                    "file_path": file_path,
                    "cache_path": cache_path,
                })
                return
            self._whisper = whisper

            model = self._model
            if model is None:
                try:
                    try:
                        model = whisper.load_model("tiny", download_root=str(MODEL_ROOT))  # type: ignore
                    except TypeError:
                        model = whisper.load_model("tiny")  # type: ignore
                    self._model = model
                except Exception:
                    logging.exception("Failed to load whisper 'tiny' model")
                    self._prep_ready.emit({
                        "error": "Error: failed to load whisper model.",
                        "file_path": file_path,
                        "cache_path": cache_path,
                    })
                    return

            # detect language
            language = "en"
            probs: Dict[str, Any] = {language: 1.0}
            try:
                audio = whisper.load_audio(file_path)  # type: ignore
                audio = whisper.pad_or_trim(audio)  # type: ignore
                mel = whisper.log_mel_spectrogram(audio).to(model.device)  # type: ignore
                detect = model.detect_language(mel)  # type: ignore
                probs_raw = detect[1]
                probs = cast(Dict[str, Any], probs_raw)
                language = max(probs.items(), key=lambda kv: kv[1])[0]
            except Exception:
                pass

            self._prep_ready.emit({
                "probs": probs,
                "language": language,
                "file_path": file_path,
                "cache_path": cache_path,
            })

        threading.Thread(target=prepare, daemon=True).start()

    def _on_prep_ready(self, prep: dict):
        """GUI-thread slot: show the transcription options dialog once prep work is done."""
        file_path = prep["file_path"]
        cache_path = prep["cache_path"]

        if "error" in prep:
            self._transcribing = False
            self._current_audio_file = None
            self.list_widget.addItem(prep["error"])
            self.segments_ready.emit([])
            return

        probs = prep["probs"]
        language = prep["language"]

        # show dialog for language and model size selection
        lang_codes = sorted(probs.keys(), key=lambda k: -probs.get(k, 0))
        default_idx = lang_codes.index(language) if language in lang_codes else 0
        dlg = QDialog(self)
        dlg.setWindowTitle("Transcription Options")
        form_layout = QFormLayout(dlg)
        lang_combo = QComboBox(dlg)
        lang_combo.addItems(lang_codes)
        lang_combo.setCurrentIndex(default_idx)
        form_layout.addRow("Language:", lang_combo)
        model_sizes = ["tiny", "small", "base", "medium", "large"]
        model_combo = QComboBox(dlg)
        model_combo.addItems(model_sizes)
        model_combo.setCurrentText("base")
        form_layout.addRow("Model Size:", model_combo)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=dlg)
        form_layout.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            # User cancelled transcription options — notify listeners with empty segments
            # so any pending playback (set by the caller) can proceed.
            self._transcribing = False
            self._current_audio_file = None
            self.segments_ready.emit([])
            return
        language = lang_combo.currentText()
        model_size = model_combo.currentText()
        whisper = self._whisper

        # transcription in background using selected language
        def run_transcribe():
            try:
                model = self._model
                # load user-selected model size for transcription
                if model_size != "tiny":
                    try:
                        model = whisper.load_model(model_size, download_root=str(MODEL_ROOT))  # type: ignore
                    except TypeError:
                        model = whisper.load_model(model_size)  # type: ignore
                # perform transcription with selected language
                raw = cast(Dict[str, Any], model.transcribe(file_path, language=language))  # type: ignore
                # skip segments if no speech probability exceeds threshold
                if raw.get("no_speech_prob", 0.0) > NO_SPEECH_THRESHOLD:
                    segments = []
                else:
                    segments = raw.get("segments", [])
                # write cache file
                try:
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(segments, f)
                except Exception:
                    pass
            except Exception:
                segments = []
            finally:
                self._transcribing = False
                self._current_audio_file = None
            self.segments_ready.emit(segments)

        threading.Thread(target=run_transcribe, daemon=True).start()

    def _on_segments_ready(self, segments: list):
        """Populate the list widget with timed lyric segments."""
        # hide progress once segments are ready
        self.progress_bar.hide()
        # build (start, end, text) tuples
        self.segments = [
            (s.get("start", 0.0), s.get("end", 0.0), s.get("text", ""))
            for s in segments
        ]
        self.list_widget.clear()
        for _, _, text in self.segments:
            self.list_widget.addItem(text)

    def update_position(self, ms: int):
        """Highlight and scroll to the current lyric line based on playback position."""
        sec = ms / 1000.0
        idx = next((i for i, (start, end, _) in enumerate(self.segments) if start <= sec <= end), None)
        if idx is not None and 0 <= idx < self.list_widget.count():
            self.list_widget.setCurrentRow(idx)
            self.list_widget.scrollToItem(self.list_widget.currentItem())

    def show_progress(self):
        """Show the progress bar while transcription is running."""
        self.progress_bar.show()

    def hide_progress(self):
        """Hide the progress bar after transcription completes."""
        self.progress_bar.hide()

    def closeEvent(self, event):
        try:
            self.closed.emit()
        except Exception:
            pass
        # Prevent destruction; minimize/hide instead so widget can be reopened quickly
        try:
            event.ignore()
        except Exception:
            pass
        try:
            self.hide()
        except Exception:
            pass
