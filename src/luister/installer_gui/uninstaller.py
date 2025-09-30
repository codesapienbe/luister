import shutil
import threading
import subprocess
from pathlib import Path
import os
import tempfile
import json
from typing import Any

# Import shared symbols from package-level initializer; fall back if not present
try:
    from . import QtWidgets, QtCore, QtGui, write_log, LOG_FILENAME, appdirs
except Exception:
    QtWidgets: Any = None  # type: ignore
    QtCore: Any = None  # type: ignore
    QtGui: Any = None  # type: ignore
    write_log: Any = None  # type: ignore
    LOG_FILENAME = 'application.log'
    appdirs: Any = None


if QtWidgets is not None and QtCore is not None:

    class UninstallerWorker(QtCore.QObject):
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

        def __init__(self, install_dir: str, remove_user_data: bool):
            super().__init__()
            self.install_dir = Path(install_dir).expanduser().resolve()
            self.remove_user_data = bool(remove_user_data)
            # log into install_dir/application.log if possible
            self.log_path = (self.install_dir / LOG_FILENAME) if self.install_dir.exists() else None

        def run(self):
            try:
                self.progress.emit('2:Starting uninstallation')
                if write_log is not None and self.log_path is not None:
                    write_log(self.log_path, 'INFO', 'uninstaller', 'starting', install_dir=str(self.install_dir))

                # Stage: locate
                self.progress.emit('10:Locating installation')
                if not self.install_dir.exists():
                    msg = f'Install directory not found: {self.install_dir}'
                    self.progress.emit(f'stage:locate:fail')
                    if write_log is not None and self.log_path is not None:
                        write_log(self.log_path, 'WARN', 'uninstaller', 'not_found', path=str(self.install_dir))
                    self.finished.emit(False, msg)
                    return
                self.progress.emit('stage:locate:ok')

                # Stage: remove application directory
                self.progress.emit('30:Removing application directory')
                self.progress.emit('stage:remove_app:started')
                try:
                    shutil.rmtree(str(self.install_dir))
                    if write_log is not None and self.log_path is not None:
                        write_log(self.log_path, 'INFO', 'uninstaller', 'removed_app_dir', path=str(self.install_dir))
                    self.progress.emit('stage:remove_app:ok')
                except Exception as e:
                    # Attempt remediation for permission issues: try to make files writable then retry
                    try:
                        import stat as _stat
                        for p in self.install_dir.rglob('*'):
                            try:
                                if p.exists():
                                    # add owner write bit
                                    p.chmod(p.stat().st_mode | _stat.S_IWRITE)
                            except Exception:
                                # ignore per-file errors
                                pass
                        # retry removal after chmod-ing
                        shutil.rmtree(str(self.install_dir))
                        if write_log is not None and self.log_path is not None:
                            write_log(self.log_path, 'INFO', 'uninstaller', 'removed_app_dir_after_chmod', path=str(self.install_dir))
                        self.progress.emit('stage:remove_app:ok')
                    except Exception as e2:
                        # Still failed; attempt to detect blocking processes that have open handles
                        blockers: list[dict] = []
                        try:
                            import psutil  # type: ignore
                            for proc in psutil.process_iter(['pid', 'name', 'open_files', 'cmdline']):
                                try:
                                    pid = getattr(proc, 'pid', None)
                                    name = getattr(proc, 'name', lambda: '')()
                                    cmdline = ' '.join(proc.info.get('cmdline') or []) if proc.info.get('cmdline') else ''
                                    try:
                                        for of in proc.open_files() or []:
                                            try:
                                                if str(self.install_dir) in (of.path or ''):
                                                    blockers.append({'pid': pid, 'name': name, 'cmd': cmdline})
                                                    break
                                            except Exception:
                                                continue
                                    except Exception:
                                        continue
                                except Exception:
                                    continue
                        except Exception:
                            blockers = []

                        if write_log is not None and self.log_path is not None:
                            try:
                                write_log(self.log_path, 'ERROR', 'uninstaller', 'remove_app_failed', error=str(e2), blockers=blockers)
                            except Exception:
                                pass

                        self.progress.emit('stage:remove_app:fail')
                        if blockers:
                            blk_desc = ','.join(f"{b.get('pid')}:{b.get('name')}" for b in blockers)
                            self.finished.emit(False, f'Failed removing application: {e2} - blocking processes: {blk_desc}')
                        else:
                            self.finished.emit(False, f'Failed removing application: {e2}')
                        return

                # Stage: remove user data
                if self.remove_user_data:
                    self.progress.emit('60:Removing user data')
                    self.progress.emit('stage:remove_user:started')
                    try:
                        if appdirs:
                            user_data = Path(appdirs.user_data_dir('Instyper', appauthor=False))
                        else:
                            user_data = Path.home() / '.luister'
                        if user_data.exists():
                            # remove safely
                            shutil.rmtree(str(user_data))
                            if write_log is not None and self.log_path is not None:
                                write_log(self.log_path, 'INFO', 'uninstaller', 'removed_user_data', path=str(user_data))
                        self.progress.emit('stage:remove_user:ok')
                    except Exception as e:
                        if write_log is not None and self.log_path is not None:
                            write_log(self.log_path, 'WARN', 'uninstaller', 'remove_user_failed', error=str(e))
                        self.progress.emit('stage:remove_user:fail')
                        # continue; user may clean manually

                # Stage: finished
                self.progress.emit('100:Uninstallation completed')
                if write_log is not None and self.log_path is not None:
                    write_log(self.log_path, 'INFO', 'uninstaller', 'completed')
                self.progress.emit('stage:all:ok')
                self.finished.emit(True, str(self.install_dir))
            except Exception as e:
                if write_log is not None and self.log_path is not None:
                    write_log(self.log_path, 'ERROR', 'uninstaller', 'failed', error=str(e))
                self.finished.emit(False, str(e))


    class UninstallerWindow(QtWidgets.QDialog):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('Luister Uninstaller')
            self.resize(640, 420)

            layout = QtWidgets.QVBoxLayout(self)

            # Welcome card
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
                ttl = QtWidgets.QLabel('<b><span style="font-size:16pt">Uninstall Luister</span></b>')
                h.addWidget(ttl)
                layout.addWidget(card)
            except Exception:
                pass

            # Install dir input
            default_dir = appdirs.user_data_dir('Luister', appauthor=False) if appdirs else str(Path.home())
            self.install_dir_input = QtWidgets.QLineEdit(default_dir)
            layout.addWidget(self.install_dir_input)

            # Remove user data checkbox
            self.remove_user_cb = QtWidgets.QCheckBox('Also remove user data (~/ .luister)')
            layout.addWidget(self.remove_user_cb)

            # Buttons
            btn_row = QtWidgets.QHBoxLayout()
            self.start_btn = QtWidgets.QPushButton('Uninstall')
            self.start_btn.clicked.connect(self.start_uninstall)
            btn_row.addStretch(1)
            btn_row.addWidget(self.start_btn)
            layout.addLayout(btn_row)

            # Progress and logs
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
            # track retry attempts to avoid infinite loops
            self._uninstall_retry_attempts = 0

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

        def _detect_running_instances(self, install_dir: Path) -> list[dict]:
            """Return a list of running process info dicts that likely belong to Instyper.

            Each dict contains keys: pid, name, exe, cmd.
            """
            instances: list[dict] = []
            # don't include ourselves in the results
            current_pid = os.getpid()
            # tokens that likely identify this uninstaller process; exclude them
            exclude_tokens = ['uninstaller', 'installer_gui', 'luister.installer_gui.uninstaller']
            try:
                import psutil  # type: ignore
            except Exception:
                psutil = None  # type: ignore

            try:
                if psutil is not None:
                    for p in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                        try:
                            info = p.info
                            pid = info.get('pid')
                            # skip current process
                            if pid is not None and pid == current_pid:
                                continue
                            name = (info.get('name') or '')
                            exe = (info.get('exe') or '')
                            cmd = ' '.join(info.get('cmdline') or [])
                            # avoid listing this exact uninstaller module/process
                            try:
                                this_file = str(Path(__file__).resolve())
                            except Exception:
                                this_file = ''
                            cmd_l = (cmd or '').lower()
                            name_l = (name or '').lower()
                            # skip if command line refers to this file or contains known exclude tokens
                            if this_file and (this_file in (exe or '') or this_file in (cmd or '')):
                                continue
                            if any(t in cmd_l for t in exclude_tokens) or any(t in name_l for t in exclude_tokens):
                                continue
                            if (str(install_dir) in (exe or '') or str(install_dir) in (cmd or '')
                                    or 'luister' in name_l or 'luister' in cmd_l):
                                instances.append({'pid': pid, 'name': name, 'exe': exe, 'cmd': cmd})
                        except Exception:
                            # best-effort; skip problematic process
                            continue
                else:
                    # Fallback: use platform tools
                    if os.name == 'nt':
                        out = subprocess.check_output(['tasklist', '/fo', 'csv', '/nh'], text=True, errors='ignore')
                        for line in out.splitlines():
                            try:
                                # CSV: "Image Name","PID",...
                                parts = [p.strip().strip('"') for p in line.split(',')]
                                if len(parts) < 2:
                                    continue
                                name = parts[0]
                                pid = int(parts[1]) if parts[1].isdigit() else None
                                # skip current process
                                if pid is not None and pid == current_pid:
                                    continue
                                # exclude known uninstaller identifiers
                                name_l = (name or '').lower()
                                if any(t in name_l for t in exclude_tokens):
                                    continue
                                if 'luister' in name_l:
                                    instances.append({'pid': pid, 'name': name, 'exe': '', 'cmd': ''})
                            except Exception:
                                continue
                    else:
                        out = subprocess.check_output(['ps', '-eo', 'pid=,args='], text=True, errors='ignore')
                        for line in out.splitlines():
                            try:
                                parts = line.strip().split(None, 1)
                                if not parts:
                                    continue
                                pid = int(parts[0])
                                # skip current process
                                if pid == current_pid:
                                    continue
                                cmd = parts[1] if len(parts) > 1 else ''
                                cmd_l = (cmd or '').lower()
                                # exclude if commandline suggests the uninstaller itself
                                if any(t in cmd_l for t in exclude_tokens):
                                    continue
                                if str(install_dir) in cmd or 'luister' in cmd_l:
                                    instances.append({'pid': pid, 'name': cmd.split()[0] if cmd else '', 'exe': '', 'cmd': cmd})
                            except Exception:
                                continue
            except Exception:
                # If detection fails, return empty list (don't block uninstall)
                return []

            return instances

        def _show_running_processes_dialog(self, install_dir: Path, instances: list[dict]) -> bool:
            """Show a dialog listing detected processes and allow the user to kill selected ones.

            Returns True if the user wants to proceed with uninstall, False to cancel.
            """
            if not instances:
                return True

            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle('Running Instyper Processes Detected')
            dlg.setMinimumWidth(520)
            v = QtWidgets.QVBoxLayout(dlg)

            intro = QtWidgets.QLabel(f"Found {len(instances)} running process(es) that may belong to Instyper. Select processes to terminate before continuing.")
            intro.setWordWrap(True)
            v.addWidget(intro)

            listw = QtWidgets.QListWidget()
            for inst in instances:
                pid = inst.get('pid')
                name = inst.get('name') or ''
                cmd = inst.get('cmd') or inst.get('exe') or ''
                display = f"{pid} — {name} — {cmd}"
                item = QtWidgets.QListWidgetItem(display)
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Unchecked)
                listw.addItem(item)
            v.addWidget(listw)

            btn_row = QtWidgets.QHBoxLayout()
            kill_btn = QtWidgets.QPushButton('Kill Selected')
            cont_btn = QtWidgets.QPushButton('Continue Anyway')
            cancel_btn = QtWidgets.QPushButton('Cancel')
            btn_row.addStretch(1)
            btn_row.addWidget(kill_btn)
            btn_row.addWidget(cont_btn)
            btn_row.addWidget(cancel_btn)
            v.addLayout(btn_row)

            result: dict[str, str | None] = {'action': None}

            def on_cancel():
                result['action'] = 'cancel'
                dlg.reject()

            def on_continue():
                result['action'] = 'continue'
                dlg.accept()

            def on_kill():
                to_kill: list[int] = []
                for i in range(listw.count()):
                    it = listw.item(i)
                    if it.checkState() == QtCore.Qt.Checked:
                        try:
                            pid = int(it.text().split('—')[0].strip())
                            to_kill.append(pid)
                        except Exception:
                            continue
                if not to_kill:
                    QtWidgets.QMessageBox.information(self, 'No selection', 'No processes selected to kill.')
                    return

                failed: list[tuple] = []
                for pid in to_kill:
                    try:
                        if os.name == 'nt':
                            subprocess.check_call(['taskkill', '/PID', str(pid), '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        else:
                            os.kill(pid, 15)
                        # log successful kill
                        try:
                            ld = Path(install_dir) / LOG_FILENAME if isinstance(install_dir, Path) else Path.home() / LOG_FILENAME
                            write_log(ld, 'INFO', 'uninstaller', 'killed_process', pid=pid)
                        except Exception:
                            pass
                    except Exception as e:
                        failed.append((pid, str(e)))
                        try:
                            ld = Path(install_dir) / LOG_FILENAME if isinstance(install_dir, Path) else Path.home() / LOG_FILENAME
                            write_log(ld, 'WARN', 'uninstaller', 'kill_failed', pid=pid, error=str(e))
                        except Exception:
                            pass

                if failed:
                    msgs = '; '.join(f'{p}:{e}' for p, e in failed)
                    QtWidgets.QMessageBox.warning(self, 'Kill result', f'Failed to kill: {msgs}')
                else:
                    QtWidgets.QMessageBox.information(self, 'Kill result', 'Selected processes terminated.')

                # Refresh list by removing killed PIDs
                for i in range(listw.count() - 1, -1, -1):
                    it = listw.item(i)
                    try:
                        pid = int(it.text().split('—')[0].strip())
                        if pid in to_kill:
                            listw.takeItem(i)
                    except Exception:
                        continue

                if listw.count() == 0:
                    result['action'] = 'continue'
                    dlg.accept()

            kill_btn.clicked.connect(on_kill)
            cont_btn.clicked.connect(on_continue)
            cancel_btn.clicked.connect(on_cancel)

            dlg.exec_()
            return result.get('action') != 'cancel'

        def start_uninstall(self, skip_confirmation: bool = False):
            install_dir = self.install_dir_input.text().strip()
            if not install_dir:
                QtWidgets.QMessageBox.warning(self, 'Missing directory', 'Please provide the installation directory to remove.')
                return

            # Detect running instances and offer to kill them before confirming
            try:
                detected = self._detect_running_instances(Path(install_dir))
                if detected:
                    proceed = self._show_running_processes_dialog(Path(install_dir), detected)
                    if not proceed:
                        return
            except Exception:
                # detection failure should not block uninstall; continue to confirmation
                pass

            # Confirm destructive action (skip_confirmation is used for automatic retries after killing blockers)
            if not skip_confirmation:
                ok = QtWidgets.QMessageBox.question(self, 'Confirm Uninstall', f'Remove installation at {install_dir}? This cannot be undone.', QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if ok != QtWidgets.QMessageBox.Yes:
                    return

            remove_user = self.remove_user_cb.isChecked()

            # disable inputs
            self.install_dir_input.setEnabled(False)
            self.start_btn.setEnabled(False)

            # start worker
            self.thread = QtCore.QThread()
            self.worker = UninstallerWorker(install_dir, remove_user)
            self.worker.moveToThread(self.thread)
            self.worker.progress.connect(self.append_log)
            self.worker.finished.connect(self.on_finished)
            self.thread.started.connect(self.worker.run)
            self.thread.start()

        def _parse_blockers_from_message(self, msg: str) -> list[dict]:
            # Expect format: '...blocking processes: pid:name,pid2:name2'
            try:
                lower = msg.lower()
                key = 'blocking processes:'
                if key in lower:
                    tail = msg[lower.find(key) + len(key):].strip()
                    # split by comma
                    parts = [p.strip() for p in tail.split(',') if p.strip()]
                    out: list[dict] = []
                    for part in parts:
                        try:
                            pid_s, name = part.split(':', 1)
                            pid = int(pid_s)
                            out.append({'pid': pid, 'name': name})
                        except Exception:
                            continue
                    return out
            except Exception:
                pass
            return []

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
                    self.start_btn.setEnabled(True)
                except Exception:
                    pass
                try:
                    self.progress_bar.setValue(100 if ok else self.progress_bar.value())
                except Exception:
                    pass
                try:
                    if ok:
                        QtWidgets.QMessageBox.information(self, 'Uninstall complete', f'Uninstalled: {result}')
                    else:
                        # If failure mentions blocking processes, offer user to kill and retry
                        if isinstance(result, str) and 'blocking processes' in result.lower() and self._uninstall_retry_attempts < 2:
                            blockers = self._parse_blockers_from_message(result)
                            if blockers:
                                # Build instances list to reuse the existing dialog
                                instances = [{'pid': b.get('pid'), 'name': b.get('name'), 'exe': '', 'cmd': ''} for b in blockers]
                                proceed = self._show_running_processes_dialog(Path(self.install_dir_input.text().strip()), instances)
                                if proceed:
                                    # increment retry counter and retry uninstall once
                                    self._uninstall_retry_attempts += 1
                                    QtCore.QTimer.singleShot(400, lambda: self.start_uninstall(skip_confirmation=True))
                                    return
                        QtWidgets.QMessageBox.critical(self, 'Uninstall failed', f'Uninstall failed: {result}')
                except Exception:
                    pass
            except Exception:
                pass


def main():
    if QtWidgets is None or QtCore is None:
        print('GUI not available; install PySide6 or PyQt5 to run the uninstaller.')
        return 2
    app = QtWidgets.QApplication([])
    w = UninstallerWindow()
    w.show()
    return app.exec_() 