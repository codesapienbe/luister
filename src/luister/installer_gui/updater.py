"""
GUI updater for Instyper: pulls latest changes from the existing installation
and reinstalls the package into the local .venv (or creates it if missing).

This is intentionally a focused workflow: do not clone repositories nor run
prerequisite checks; assume the target path already contains the project.
"""
from __future__ import annotations

import shutil
import threading
import subprocess
import venv
import os
import tempfile
import json
from pathlib import Path
from datetime import datetime
from typing import Any

# Try to import shared symbols from package initializer; fall back if not present
try:
    from . import QtWidgets, QtCore, QtGui, write_log, LOG_FILENAME, appdirs
except Exception:
    QtWidgets: Any = None  # type: ignore
    QtCore: Any = None  # type: ignore
    QtGui: Any = None  # type: ignore
    write_log: Any = None  # type: ignore
    LOG_FILENAME = "application.log"
    appdirs: Any = None

try:
    from git import Repo  # type: ignore
except Exception:
    Repo = None  # type: ignore


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


class UpdaterWorker(QtCore.QObject):
    _Signal = getattr(QtCore, 'pyqtSignal', None) or getattr(QtCore, 'Signal', None)
    if _Signal is None:
        class _DummySignal:
            def __init__(self, *a, **k):
                pass
            def connect(self, *a, **k):
                pass
            def emit(self, *a, **k):
                pass
        _Signal = _DummySignal

    progress = _Signal(str)
    finished = _Signal(bool, str)

    def __init__(self, install_dir: str):
        super().__init__()
        self.install_dir = Path(install_dir).expanduser().resolve()
        self.log_path = (self.install_dir / LOG_FILENAME) if self.install_dir.exists() else None

    def _venv_python(self, venv_dir: Path) -> Path:
        if os.name == 'nt':
            return venv_dir / 'Scripts' / 'python.exe'
        return venv_dir / 'bin' / 'python'

    def _create_launcher(self, launcher_path: Path, venv_python: Path) -> None:
        launcher_code = f"""#!/usr/bin/env python3
import subprocess
import sys
venv_python = r'{venv_python}'
try:
    subprocess.run([venv_python, '-m', 'uv', 'run', 'luister'], check=True)
except Exception as e:
    print('Failed to start Luister:', e)
    sys.exit(1)
"""
        try:
            launcher_path.write_text(launcher_code, encoding='utf-8')
            try:
                launcher_path.chmod(0o755)
            except Exception:
                pass
        except Exception:
            pass

    def run(self) -> None:
        try:
            self.progress.emit('2:Starting updater')
            if write_log is not None and self.log_path is not None:
                write_log(self.log_path, 'INFO', 'updater', 'starting', install_dir=str(self.install_dir))

            # Ensure install_dir exists
            self.progress.emit('10:Checking installation directory')
            if not self.install_dir.exists():
                msg = f'Install directory not found: {self.install_dir}'
                self.progress.emit('stage:locate:fail')
                if write_log is not None and self.log_path is not None:
                    write_log(self.log_path, 'WARN', 'updater', 'not_found', path=str(self.install_dir))
                self.finished.emit(False, msg)
                return
            self.progress.emit('stage:locate:ok')

            # Stage: git pull
            self.progress.emit('20:Pulling latest changes')
            self.progress.emit('stage:pull:started')
            try:
                if Repo is not None:
                    repo = Repo(self.install_dir)
                    origin = repo.remotes.origin
                    origin.pull()
                else:
                    git_bin = shutil.which('git')
                    if not git_bin:
                        raise RuntimeError('git not found')
                    subprocess.check_call([git_bin, '-C', str(self.install_dir), 'pull'])
                if write_log is not None and self.log_path is not None:
                    write_log(self.log_path, 'INFO', 'updater', 'pulled')
                self.progress.emit('stage:pull:ok')
            except Exception as e:
                if write_log is not None and self.log_path is not None:
                    write_log(self.log_path, 'ERROR', 'updater', 'pull_failed', error=str(e))
                self.progress.emit('stage:pull:fail')
                self.finished.emit(False, f'Git pull failed: {e}')
                return

            # Stage: venv (create if missing)
            self.progress.emit('40:Ensuring virtual environment')
            venv_dir = self.install_dir / '.venv'
            try:
                if not venv_dir.exists():
                    venv.create(str(venv_dir), with_pip=True)
                self.progress.emit('stage:venv:ok')
            except Exception as e:
                if write_log is not None and self.log_path is not None:
                    write_log(self.log_path, 'ERROR', 'updater', 'venv_failed', error=str(e))
                self.progress.emit('stage:venv:fail')
                self.finished.emit(False, f'Venv creation failed: {e}')
                return

            venv_python = self._venv_python(venv_dir)

            # Stage: install dependencies and build
            self.progress.emit('60:Installing dependencies and building')
            self.progress.emit('stage:deps:started')
            try:
                subprocess.check_call([str(venv_python), '-m', 'pip', 'install', '--upgrade', 'pip'])
                subprocess.check_call([str(venv_python), '-m', 'pip', 'install', 'uv'])
                subprocess.check_call([str(venv_python), '-m', 'uv', 'sync'], cwd=str(self.install_dir))
                try:
                    subprocess.check_call([str(venv_python), '-m', 'uv', 'build'], cwd=str(self.install_dir))
                except subprocess.CalledProcessError:
                    subprocess.check_call([str(venv_python), '-m', 'pip', 'install', '.'], cwd=str(self.install_dir))
                self.progress.emit('stage:deps:ok')
            except Exception as e:
                if write_log is not None and self.log_path is not None:
                    write_log(self.log_path, 'ERROR', 'updater', 'deps_failed', error=str(e))
                self.progress.emit('stage:deps:fail')
                self.finished.emit(False, f'Dependency/install failed: {e}')
                return

            # Re-create launcher
            self.progress.emit('85:Creating launcher')
            try:
                launcher_path = self.install_dir / 'luister-launcher.py'
                self._create_launcher(launcher_path, venv_python)
            except Exception:
                pass

            # Stage finished
            self.progress.emit('100:Update completed')
            if write_log is not None and self.log_path is not None:
                write_log(self.log_path, 'INFO', 'updater', 'completed')
            self.progress.emit('stage:all:ok')
            self.finished.emit(True, str(self.install_dir))
        except Exception as e:
            if write_log is not None and self.log_path is not None:
                write_log(self.log_path, 'ERROR', 'updater', 'failed', error=str(e))
            self.finished.emit(False, str(e))


if QtWidgets is not None and QtCore is not None:

    class UpdaterWindow(QtWidgets.QDialog):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('Instyper Updater')
            self.resize(640, 420)

            layout = QtWidgets.QVBoxLayout(self)

            try:
                card = QtWidgets.QFrame()
                card.setFrameShape(QtWidgets.QFrame.StyledPanel)
                h = QtWidgets.QHBoxLayout(card)
                icon = QtWidgets.QLabel()
                icon.setFixedSize(80, 80)
                try:
                    from . import find_project_logo
                    logo = find_project_logo()
                    if logo and logo.exists() and QtGui is not None:
                        pix = QtGui.QPixmap(str(logo)).scaled(80, 80, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                        icon.setPixmap(pix)
                except Exception:
                    pass
                h.addWidget(icon)
                ttl = QtWidgets.QLabel('<b><span style="font-size:16pt">Update Instyper</span></b>')
                h.addWidget(ttl)
                layout.addWidget(card)
            except Exception:
                pass

            default_dir = appdirs.user_data_dir('Instyper', appauthor=False) if appdirs else str(Path.home())
            self.install_dir_input = QtWidgets.QLineEdit(default_dir)
            layout.addWidget(self.install_dir_input)

            btn_row = QtWidgets.QHBoxLayout()
            self.update_btn = QtWidgets.QPushButton('Update')
            self.update_btn.clicked.connect(self.start_update)
            btn_row.addStretch(1)
            btn_row.addWidget(self.update_btn)
            layout.addLayout(btn_row)

            self.progress_bar = QtWidgets.QProgressBar()
            self.progress_bar.setRange(0, 100)
            try:
                self.progress_bar.setFixedHeight(20)
            except Exception:
                pass
            layout.addWidget(self.progress_bar)

            self.progress_output = QtWidgets.QTextEdit()
            self.progress_output.setReadOnly(True)
            self.progress_output.setVisible(False)
            layout.addWidget(self.progress_output)

            self._log_viewer = QtWidgets.QTextEdit()
            self._log_viewer.setReadOnly(True)
            self._log_viewer.setVisible(False)
            toggle = QtWidgets.QToolButton()
            toggle.setText('See details')
            toggle.setCheckable(True)
            toggle.toggled.connect(lambda c: self._log_viewer.setVisible(c))
            layout.addWidget(toggle)
            layout.addWidget(self._log_viewer)

            self.thread = None
            self.worker = None

        def append_log(self, message: str) -> None:
            try:
                m = __import__('re').match(r"^(\d{1,3}):(.*)$", message)
                if m:
                    pct = int(m.group(1))
                    text = m.group(2).strip()
                    self.progress_bar.setValue(max(0, min(100, pct)))
                    try:
                        self.progress_output.append(f'[{pct}%] {text}')
                    except Exception:
                        pass
                    try:
                        self._log_viewer.moveCursor(QtGui.QTextCursor.End)
                        self._log_viewer.insertPlainText(f'[{pct}%] {text}\n')
                        self._log_viewer.moveCursor(QtGui.QTextCursor.End)
                    except Exception:
                        pass
                    return
                self.progress_output.append(message)
                try:
                    self._log_viewer.moveCursor(QtGui.QTextCursor.End)
                    self._log_viewer.insertPlainText(message + '\n')
                    self._log_viewer.moveCursor(QtGui.QTextCursor.End)
                except Exception:
                    pass
            except Exception:
                pass

        def start_update(self):
            install_dir = self.install_dir_input.text().strip()
            if not install_dir:
                QtWidgets.QMessageBox.warning(self, 'Missing directory', 'Please provide the installation directory to update.')
                return

            # disable inputs
            self.install_dir_input.setEnabled(False)
            self.update_btn.setEnabled(False)

            self.thread = QtCore.QThread()
            self.worker = UpdaterWorker(install_dir)
            self.worker.moveToThread(self.thread)
            self.worker.progress.connect(self.append_log)
            self.worker.finished.connect(self.on_finished)
            self.thread.started.connect(self.worker.run)
            self.thread.start()

        def on_finished(self, ok: bool, result: str) -> None:
            try:
                try:
                    if getattr(self, 'thread', None) is not None:
                        quit_fn = getattr(self.thread, 'quit', None)
                        if callable(quit_fn):
                            try:
                                quit_fn()
                            except Exception:
                                pass
                except Exception:
                    pass
                try:
                    self.install_dir_input.setEnabled(True)
                    self.update_btn.setEnabled(True)
                except Exception:
                    pass
                try:
                    self.progress_bar.setValue(100 if ok else self.progress_bar.value())
                except Exception:
                    pass
                try:
                    if ok:
                        QtWidgets.QMessageBox.information(self, 'Update complete', f'Updated: {result}')
                    else:
                        QtWidgets.QMessageBox.critical(self, 'Update failed', f'Update failed: {result}')
                except Exception:
                    pass
            except Exception:
                pass


def main():
    if QtWidgets is None or QtCore is None:
        print('GUI not available; install PySide6 or PyQt5 to run the updater.')
        return 2
    app = QtWidgets.QApplication([])
    w = UpdaterWindow()
    w.show()
    return app.exec_() 