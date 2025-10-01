import sys
import os
import json
import threading
import subprocess
import venv
import shutil
from pathlib import Path
import urllib.request
import zipfile
import tempfile

from datetime import datetime
import re
from typing import Any
import platform
import webbrowser
import subprocess
import os
try:
    import winreg  # type: ignore
except Exception:
    winreg = None
try:
    import ctypes
except Exception:
    ctypes = None

try:
    from PIL import Image  # type: ignore
except Exception:
    Image = None

# Try to locate an SVG renderer from available Qt bindings
try:
    from PyQt5.QtSvg import QSvgRenderer  # type: ignore
except Exception:
    try:
        from PySide6.QtSvg import QSvgRenderer  # type: ignore
    except Exception:
        QSvgRenderer = None


def find_project_logo() -> Path | None:
    # Prefer SVG, then PNG. Check common locations (packaging, repo root, package assets, cwd)
    suffixes = ['logo.svg', 'logo.png']
    candidates = []
    cwd = Path.cwd()
    # packaging folder
    candidates.extend([cwd / 'packaging' / s for s in suffixes])
    # repo root
    candidates.extend([cwd / s for s in suffixes])
    # package tree upward
    p = Path(__file__).resolve()
    for _ in range(8):
        for s in suffixes:
            candidates.append(p.parent / s)
            candidates.append(p.parent / 'assets' / s)
        p = p.parent
    # dedupe while preserving order
    seen = set()
    for c in candidates:
        if str(c) in seen:
            continue
        seen.add(str(c))
        if c.exists():
            return c
    return None


def detect_system_dark_mode() -> bool | None:
    """Detect whether the system is in dark mode.

    Returns True for dark, False for light, None if unknown.
    """
    try:
        system = platform.system()
        if system == 'Windows' and winreg is not None:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                # 0 = dark, 1 = light
                try:
                    val, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
                    winreg.CloseKey(key)
                    return False if val == 1 else True
                except FileNotFoundError:
                    winreg.CloseKey(key)
                    return None
            except Exception:
                return None

        if system == 'Darwin':
            # macOS: 'Dark' returned when in dark mode
            try:
                p = subprocess.run(['defaults', 'read', '-g', 'AppleInterfaceStyle'], capture_output=True, text=True, timeout=1)
                out = p.stdout.strip() or p.stderr.strip()
                return out.lower().startswith('dark')
            except Exception:
                return None

        # Linux: try gsettings (GNOME), then GTK settings
        # GNOME: check gtk-theme or color-scheme
        try:
            p = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.interface', 'color-scheme'], capture_output=True, text=True, timeout=1)
            out = p.stdout.strip()
            if out:
                if 'prefer-dark' in out or 'dark' in out:
                    return True
                if 'prefer-light' in out or 'light' in out:
                    return False
        except Exception:
            pass

        try:
            p = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.interface', 'gtk-theme'], capture_output=True, text=True, timeout=1)
            out = p.stdout.strip().strip("'")
            if out and 'dark' in out.lower():
                return True
            if out:
                return False
        except Exception:
            pass

        # Fallback: check GTK config file for theme name
        try:
            cfg = Path.home() / '.config' / 'gtk-3.0' / 'settings.ini'
            if cfg.exists():
                text = cfg.read_text(encoding='utf-8', errors='ignore')
                for line in text.splitlines():
                    if line.lower().startswith('gtk-theme-name'):
                        _, val = line.split('=', 1)
                        if 'dark' in val.lower():
                            return True
                        return False
        except Exception:
            pass

        return None
    except Exception:
        return None

# Prefer PySide6 on Windows (better wheel coverage), PyQt5 on other platforms.
# Try fallbacks so the GUI works across environments.

def _try_import_pyside6():
    try:
        from PySide6 import QtWidgets as _QtWidgets, QtCore as _QtCore, QtGui as _QtGui  # type: ignore
        return _QtWidgets, _QtCore, _QtGui
    except Exception:
        return None, None, None


def _try_import_pyqt5():
    try:
        from PyQt5 import QtWidgets as _QtWidgets, QtCore as _QtCore, QtGui as _QtGui  # type: ignore
        return _QtWidgets, _QtCore, _QtGui
    except Exception:
        return None, None, None

if platform.system() == "Windows":
    QtWidgets, QtCore, QtGui = _try_import_pyside6()
    if QtWidgets is None:
        QtWidgets, QtCore, QtGui = _try_import_pyqt5()
else:
    QtWidgets, QtCore, QtGui = _try_import_pyqt5()
    if QtWidgets is None:
        QtWidgets, QtCore, QtGui = _try_import_pyside6()

if QtWidgets is None:
    QtWidgets = None  # type: Any
    QtCore = None  # type: Any
    QtGui = None  # type: Any
else:
    # ensure QTextCursor exists for tailing implementation
    try:
        QTextCursor = QtGui.QTextCursor
    except Exception:
        class QTextCursor:  # type: ignore
            End = 0
            def __init__(self, *a, **k):
                pass

try:
    from git import Repo, GitCommandError  # type: ignore
except Exception:
    Repo = None  # type: Any
    GitCommandError = Exception

try:
    import appdirs  # type: ignore
except Exception:
    appdirs = None  # type: Any

try:
    from pyshortcuts import make_shortcut  # type: ignore
except Exception:
    make_shortcut = None  # type: Any
try:
    from luister import speaker_fingerprint  # placeholder: Luister may provide speaker helpers later
except Exception:
    speaker_fingerprint = None  # type: Any


LOG_FILENAME = "application.log"
DEFAULT_REPO = "https://github.com/codesapienbe/luister"  # no default repository; pass --repo when invoking installer


# If PyQt5 is not available at development time, avoid defining Qt-based classes
# to keep static analyzers happy. Define GUI classes only when runtime imports are present.
if QtWidgets is not None and QtCore is not None:

    def write_log(log_path: Path, level: str, component: str, message: str, **meta) -> None:
        if QtCore is not None:
            timestamp = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        else:
            timestamp = datetime.utcnow().isoformat() + "Z"
        entry = {
            "timestamp": timestamp,
            "level": level,
            "component": component,
            "message": message,
        }
        entry.update(meta)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            # best-effort logging; avoid crashing installer
            pass


    class InstallerWorker(QtCore.QObject):
        # Cross-binding Signal alias: PyQt uses pyqtSignal, PySide uses Signal
        _Signal = getattr(QtCore, 'pyqtSignal', None) or getattr(QtCore, 'Signal', None)
        if _Signal is None:
            # fallback dummy signal to keep edit-time analyzers happy
            class _DummySignal:
                def __init__(self, *args, **kwargs):
                    pass
                def connect(self, *args, **kwargs):
                    pass
                def emit(self, *args, **kwargs):
                    pass
            _Signal = _DummySignal

        progress = _Signal(str)
        finished = _Signal(bool, str)

        def __init__(self, repo_url: str, install_dir: str):
            super().__init__()
            self.repo_url = repo_url
            self.install_dir = Path(install_dir).expanduser().resolve()
            self.log_path = self.install_dir / LOG_FILENAME

        def run(self):
            # Check prerequisites (python/pip present in system path; git optional)
            ok, msg = self._check_prereqs()
            if not ok:
                self.progress.emit(f"0:Prerequisite problem: {msg}")
                write_log(self.log_path, "WARN", "installer", "prereq_failed", detail=msg)
                # continue to attempt install; git fallback will use HTTP archive
            
            try:
                # Provide coarse-grained percentage updates to the UI.
                self.progress.emit("2:Starting installation")
                write_log(self.log_path, "INFO", "installer", "starting", repo_url=self.repo_url, install_dir=str(self.install_dir))

                # Clone or update repository
                self.progress.emit("10:Preparing repository")
                self.progress.emit("stage:clone:started")
                if self.install_dir.exists() and any(self.install_dir.iterdir()):
                    self.progress.emit("20:Updating existing repository (git pull)")
                    write_log(self.log_path, "INFO", "installer", "pulling", path=str(self.install_dir))
                    try:
                        if Repo is not None:
                            repo = Repo(self.install_dir)
                            origin = repo.remotes.origin
                            origin.pull()
                        else:
                            subprocess.check_call(["git", "-C", str(self.install_dir), "pull"])
                        self.progress.emit("stage:clone:ok")
                    except Exception:
                        backup = self.install_dir.with_name(self.install_dir.name + "-backup")
                        shutil.move(str(self.install_dir), str(backup))
                        self._clone_repo()
                        self.progress.emit("25:Repository cloned")
                        self.progress.emit("stage:clone:ok")
                else:
                    self._clone_repo()
                    self.progress.emit("25:Repository cloned")
                    self.progress.emit("stage:clone:ok")

                # Create venv
                venv_dir = self.install_dir / ".venv"
                self.progress.emit("30:Creating virtual environment")
                self.progress.emit("stage:venv:started")
                write_log(self.log_path, "INFO", "installer", "creating_venv", venv=str(venv_dir))
                if not venv_dir.exists():
                    venv.create(str(venv_dir), with_pip=True)
                self.progress.emit("stage:venv:ok")

                venv_python = self._venv_python(venv_dir)

                # Upgrade pip and install uv
                self.progress.emit("45:Installing UV and dependencies into venv")
                self.progress.emit("stage:deps:started")
                write_log(self.log_path, "INFO", "installer", "installing_uv", python=str(venv_python))
                subprocess.check_call([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
                subprocess.check_call([str(venv_python), "-m", "pip", "install", "uv"])

                # Run uv sync
                self.progress.emit("60:Running 'uv sync'")
                write_log(self.log_path, "INFO", "installer", "running_uv_sync")
                subprocess.check_call([str(venv_python), "-m", "uv", "sync"], cwd=str(self.install_dir))

                # Try building or installing the package
                self.progress.emit("75:Installing Luister into the venv (uv build -> python -m pip install fallback)")
                write_log(self.log_path, "INFO", "installer", "installing_package")
                try:
                    subprocess.check_call([str(venv_python), "-m", "uv", "build"], cwd=str(self.install_dir))
                    self.progress.emit("stage:deps:ok")
                except subprocess.CalledProcessError:
                    subprocess.check_call([str(venv_python), "-m", "pip", "install", "."], cwd=str(self.install_dir))
                    self.progress.emit("stage:deps:ok")

                # Create launcher script
                launcher_path = self.install_dir / "luister-launcher.py"
                self._create_launcher(launcher_path, venv_python)

                # Copy icon from project if available into install dir and use for shortcuts
                icon_src = find_project_logo()
                icon_dst = None
                if icon_src and icon_src.exists():
                    try:
                        # If source is SVG and we have an SVG renderer, rasterize to PNG first
                        if icon_src.suffix.lower() == '.svg' and QSvgRenderer is not None and QtGui is not None:
                            try:
                                tmp_png = self.install_dir / (icon_src.stem + '.png')
                                svg_renderer = QSvgRenderer(str(icon_src))
                                # render at 256px square
                                img = QtGui.QImage(256, 256, QtGui.QImage.Format_ARGB32)
                                img.fill(QtGui.QColor(0,0,0,0))
                                painter = QtGui.QPainter(img)
                                svg_renderer.render(painter)
                                painter.end()
                                img.save(str(tmp_png))
                                raster_src = tmp_png
                            except Exception:
                                raster_src = icon_src
                        else:
                            raster_src = icon_src

                        # On Windows prefer .ico for shortcuts
                        if platform.system() == 'Windows' and Image is not None:
                            ico_path = self.install_dir / (icon_src.stem + '.ico')
                            try:
                                # Use Pillow to convert raster_src to ICO
                                im = Image.open(str(raster_src))
                                im.save(str(ico_path), format='ICO', sizes=[(256, 256)])
                                icon_dst = ico_path
                            except Exception:
                                # fallback to copy raster PNG/SVG
                                icon_dst = self.install_dir / raster_src.name
                                shutil.copy(str(raster_src), str(icon_dst))
                        else:
                            icon_dst = self.install_dir / raster_src.name
                            shutil.copy(str(raster_src), str(icon_dst))
                    except Exception:
                        icon_dst = None

                # Create shortcuts (desktop + start menu) using pyshortcuts if available
                self.progress.emit("95:Creating shortcuts on Desktop and Start Menu")
                self.progress.emit("stage:launch:started")
                write_log(self.log_path, "INFO", "installer", "creating_shortcuts")
                if callable(make_shortcut):
                    try:
                        icon_path = str(icon_dst) if icon_dst is not None else None
                        # pyshortcuts expects a path to .ico on Windows for best results
                        make_shortcut(name="Luister", script=str(launcher_path), icon=icon_path, desktop=True, startmenu=True)
                        self.progress.emit("stage:launch:ok")
                    except Exception as e:
                        write_log(self.log_path, "WARN", "installer", "shortcut_failed", error=str(e))
                        self.progress.emit("stage:launch:fail")
                else:
                    write_log(self.log_path, "WARN", "installer", "shortcuts_unavailable")

                self.progress.emit("100:Installation completed successfully")
                write_log(self.log_path, "INFO", "installer", "completed")
                # Emit stage completion for UI
                self.progress.emit("stage:all:ok")
                self.finished.emit(True, str(self.install_dir))
            except Exception as e:
                write_log(self.log_path, "ERROR", "installer", "failed", error=str(e))
                self.finished.emit(False, str(e))

        def _download_and_extract_zip(self, repo_url: str) -> None:
            # Attempt to download a GitHub repository archive (try main, then master)
            url_base = repo_url.rstrip('/')
            if url_base.endswith('.git'):
                url_base = url_base[:-4]
            candidates = [f"{url_base}/archive/refs/heads/main.zip", f"{url_base}/archive/refs/heads/master.zip"]
            tmpdir = tempfile.mkdtemp(prefix='luister-download-')
            try:
                for zip_url in candidates:
                    try:
                        self.progress.emit(f"Downloading repository archive: {zip_url}")
                        write_log(self.log_path, "INFO", "installer", "downloading_archive", url=zip_url)
                        zip_path = Path(tmpdir) / 'repo.zip'
                        urllib.request.urlretrieve(zip_url, str(zip_path))
                        self.progress.emit("Extracting archive")
                        with zipfile.ZipFile(str(zip_path), 'r') as zf:
                            zf.extractall(tmpdir)
                        # Move extracted contents (strip one top-level folder)
                        entries = [p for p in Path(tmpdir).iterdir() if p.is_dir()]
                        if not entries:
                            raise RuntimeError('Archive had no contents')
                        top = entries[0]
                        self.install_dir.mkdir(parents=True, exist_ok=True)
                        for item in top.iterdir():
                            dest = self.install_dir / item.name
                            if item.is_dir():
                                shutil.move(str(item), str(dest))
                            else:
                                shutil.move(str(item), str(dest))
                        write_log(self.log_path, "INFO", "installer", "archive_extracted", source=zip_url)
                        return
                    except Exception as e:
                        write_log(self.log_path, "WARN", "installer", "archive_download_failed", url=zip_url, error=str(e))
                        continue
                raise RuntimeError('All archive download attempts failed')
            finally:
                try:
                    shutil.rmtree(tmpdir)
                except Exception:
                    pass

        def _clone_repo(self):
            self.progress.emit(f"Cloning {self.repo_url} to {self.install_dir}")
            self.install_dir.parent.mkdir(parents=True, exist_ok=True)
            # Prefer local git binary if available and GitPython present
            git_bin = shutil.which('git')
            try:
                if git_bin and Repo is not None:
                    Repo.clone_from(self.repo_url, str(self.install_dir))
                    return
                if git_bin:
                    subprocess.check_call([git_bin, 'clone', self.repo_url, str(self.install_dir)])
                    return
                # git not available, fallback to HTTP archive download (works for GitHub)
                write_log(self.log_path, "WARN", "installer", "git_not_found", reason='git-binary-missing')
                self._download_and_extract_zip(self.repo_url)
            except Exception as e:
                # If everything fails, raise to be handled by caller
                raise

        def _check_prereqs(self) -> tuple[bool, str]:
            """Check system prerequisites: python and pip must be available in PATH; git is optional.
            Returns (ok, message)."""
            # Check python
            python_bin = shutil.which('python') or shutil.which('python3')
            if not python_bin:
                return False, 'python-not-found'
            # Check pip
            pip_ok = False
            try:
                subprocess.check_call([python_bin, '-m', 'pip', '--version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                pip_ok = True
            except Exception:
                pip_ok = False
            if not pip_ok:
                return False, 'pip-not-found'
            # git is optional; note its presence
            git_bin = shutil.which('git')
            if not git_bin:
                return True, 'git-not-found-will-use-http'
            return True, 'ok'

        def _venv_python(self, venv_dir: Path) -> Path:
            if os.name == "nt":
                return venv_dir / "Scripts" / "python.exe"
            return venv_dir / "bin" / "python"

        def _create_launcher(self, launcher_path: Path, venv_python: Path) -> None:
            launcher_code = f"""#!/usr/bin/env python3
import subprocess
import sys
import os
venv_python = r'{venv_python}'
try:
    subprocess.run([venv_python, '-m', 'uv', 'run', 'luister'], check=True)
except Exception as e:
    print('Failed to start Luister:', e)
    sys.exit(1)
"""
            launcher_path.write_text(launcher_code, encoding="utf-8")
            try:
                launcher_path.chmod(0o755)
            except Exception:
                pass

        def _find_project_logo(self) -> Path | None:
            # Attempt to find a logo file by walking upward from this file
            p = Path(__file__).resolve()
            for _ in range(6):
                candidate = p.parent / 'logo.png'
                if candidate.exists():
                    return candidate
                p = p.parent
            return None


    class InstallerWindow(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Luister Installer")
            self.resize(700, 420)

            central = QtWidgets.QWidget()
            self.setCentralWidget(central)
            layout = QtWidgets.QVBoxLayout(central)
            # expose main layout for dynamic configuration
            self._main_layout = layout
            # Crystal Glass: subtle translucent gradient background
            try:
                central.setStyleSheet(
                    "background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(250,250,255,255), stop:1 rgba(235,240,255,255));"
                )
            except Exception:
                pass

            # Welcome card: friendly installer intro and stages
            try:
                welcome_card = QtWidgets.QFrame()
                welcome_card.setFrameShape(QtWidgets.QFrame.StyledPanel)
                welcome_card.setObjectName('welcomeCard')
                welcome_layout = QtWidgets.QHBoxLayout(welcome_card)

                icon_label = QtWidgets.QLabel()
                icon_label.setFixedSize(96, 96)
                # attempt to load a logo for the welcome card
                try:
                    logo_path = find_project_logo()
                    if logo_path and logo_path.exists() and QtGui is not None:
                        pix = QtGui.QPixmap(str(logo_path)).scaled(96, 96, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                        icon_label.setPixmap(pix)
                except Exception:
                    pass
                welcome_layout.addWidget(icon_label)
                # Keep reference for theme updates
                self._welcome_card = welcome_card
                # Apply frosted glass card style and a soft shadow
                try:
                    welcome_card.setStyleSheet(
                        "background: rgba(255,255,255,0.72); border: 1px solid rgba(255,255,255,0.5); border-radius: 12px;"
                    )
                    shadow = QtWidgets.QGraphicsDropShadowEffect(welcome_card)
                    shadow.setBlurRadius(24)
                    shadow.setOffset(0, 6)
                    shadow.setColor(QtGui.QColor(0, 0, 0, 80))
                    welcome_card.setGraphicsEffect(shadow)
                except Exception:
                    pass

                text_layout = QtWidgets.QVBoxLayout()
                self.title_label = QtWidgets.QLabel('<b><span style="font-size:20pt">Welcome to Luister</span></b>')
                self.subtitle = QtWidgets.QLabel('This installer will set up Luister on your computer. Click Get Started to see the installation steps and options.')
                self.subtitle.setWordWrap(True)
                self.title_label.setStyleSheet('color: #2b2b2b;')
                self.subtitle.setStyleSheet('font-size:11pt; color: #444444;')
                text_layout.addWidget(self.title_label)
                text_layout.addWidget(self.subtitle)

                # Get Started button collapses the welcome panel to reveal the inputs below
                btn_row = QtWidgets.QHBoxLayout()
                btn_row.addStretch(1)
                get_started = QtWidgets.QPushButton('Get Started')
                def _hide_welcome():
                    # Animate collapse using QPropertyAnimation on maximumHeight
                    try:
                        anim = QtCore.QPropertyAnimation(welcome_card, b"maximumHeight")
                        anim.setDuration(400)
                        anim.setStartValue(welcome_card.sizeHint().height())
                        anim.setEndValue(0)
                        anim.setEasingCurve(QtCore.QEasingCurve.InOutQuad)
                        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
                        # ensure eventually hidden
                        QtCore.QTimer.singleShot(420, lambda: (welcome_card.setVisible(False), self._create_installation_config()))
                    except Exception:
                        welcome_card.setVisible(False)
                get_started.clicked.connect(_hide_welcome)
                # Glassy button style
                try:
                    get_started.setStyleSheet("""QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(255,255,255,0.85), stop:1 rgba(240,245,255,0.9)); border: 1px solid rgba(255,255,255,0.6); border-radius: 8px; padding:8px 16px; } QPushButton:hover { background: rgba(255,255,255,0.95);} """)
                except Exception:
                    pass
                # keep reference for theme toggling
                self.get_started = get_started
                btn_row.addWidget(get_started)
                text_layout.addLayout(btn_row)

                welcome_layout.addLayout(text_layout)
                layout.addWidget(welcome_card)
            except Exception:
                # best-effort: if UI pieces fail, proceed without welcome card
                pass

            # Stage UI will be created after user clicks Get Started
            self._stage_labels = {}
            # small toolbar row for settings next to inputs
            try:
                self._toolbar_row = QtWidgets.QHBoxLayout()
                self._settings_btn = QtWidgets.QPushButton('Settings')
                self._settings_btn.setFixedSize(80, 28)
                def _open_settings():
                    self._open_settings_dialog()
                self._settings_btn.clicked.connect(_open_settings)
                self._toolbar_row.addWidget(self._settings_btn)
                # Send logs button
                self._send_logs_btn = QtWidgets.QPushButton('Send logs')
                self._send_logs_btn.setFixedSize(100, 28)
                def _on_send_logs():
                    try:
                        self._send_logs_report()
                    except Exception:
                        pass
                self._send_logs_btn.clicked.connect(_on_send_logs)
                self._toolbar_row.addWidget(self._send_logs_btn)
                self._toolbar_row.addStretch(1)
                layout.addLayout(self._toolbar_row)
            except Exception:
                self._settings_btn = None

            self.repo_input = QtWidgets.QLineEdit(self)
            self.repo_input.setPlaceholderText(f"Repository URL (e.g. {DEFAULT_REPO})")
            self.repo_input.setText(DEFAULT_REPO)
            self.repo_input.setVisible(False)
            layout.addWidget(self.repo_input)

            default_dir = appdirs.user_data_dir("Luister", appauthor=False) if appdirs else os.path.expanduser("~")
            self.install_dir_input = QtWidgets.QLineEdit(default_dir)
            self.install_dir_input.setVisible(False)
            layout.addWidget(self.install_dir_input)

            self.start_button = QtWidgets.QPushButton("Install")
            self.start_button.clicked.connect(self.start_install)
            self.start_button.setVisible(False)
            layout.addWidget(self.start_button)

            # Progress bar (0-100)
            self.progress_bar = QtWidgets.QProgressBar()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            # Make progress bar more visible by increasing height
            try:
                self.progress_bar.setFixedHeight(20)
            except Exception:
                pass
            self.progress_bar.setVisible(False)
            layout.addWidget(self.progress_bar)

            self.progress_output = QtWidgets.QTextEdit()
            self.progress_output.setReadOnly(True)
            self.progress_output.setVisible(False)
            layout.addWidget(self.progress_output, 1)

            self.worker = None

            # Sticky log viewer (collapsed by default)
            self._log_viewer = QtWidgets.QTextEdit()
            self._log_viewer.setReadOnly(True)
            self._log_viewer.setFixedHeight(200)
            self._log_viewer.setVisible(False)
            # Toggle button to show/hide logs
            self._toggle_logs_btn = QtWidgets.QToolButton()
            # Hidden by default; allow user to reveal a single unified 'details' view
            self._toggle_logs_btn.setText('See details')
            self._toggle_logs_btn.setCheckable(True)
            def _toggle_logs(checked: bool):
                self._log_viewer.setVisible(checked)
                self._toggle_logs_btn.setText('Hide logs' if checked else 'Show logs')
                # persist visibility and height
                try:
                    self._save_ui_state()
                except Exception:
                    pass
            self._toggle_logs_btn.toggled.connect(_toggle_logs)
            self._toggle_logs_btn.setVisible(False)
            self._log_viewer.setVisible(False)
            layout.addWidget(self._toggle_logs_btn)
            layout.addWidget(self._log_viewer)

            # Timer for tailing the log file
            self._log_tail_timer = QtCore.QTimer()
            self._log_tail_timer.setInterval(500)
            self._log_tail_timer.timeout.connect(self._tail_log_file)
            self._log_tail_path = None
            self._log_tail_pos = 0

            # Load persisted UI state (visibility and log height)
            try:
                state = self._load_ui_state()
                if state is not None:
                    vis = state.get('logs_visible', False)
                    h = state.get('log_height', None)
                    theme = state.get('theme', 'light')
                    self._toggle_logs_btn.setChecked(vis)
                    self._log_viewer.setVisible(vis)
                    if isinstance(h, int) and h > 40:
                        self._log_viewer.setFixedHeight(h)
                    # Apply theme (handle 'auto')
                    if theme == 'auto':
                        # Basic system preference detection (Windows dark mode via registry not implemented here)
                        # Fallback to light
                        theme_to_apply = 'light'
                    else:
                        theme_to_apply = theme
                    self._apply_theme(theme_to_apply)
            except Exception:
                pass

        def append_log(self, message: str) -> None:
            # Expect messages optionally prefixed with '<percent>:<text>' from the worker
            m = re.match(r"^(\d{1,3}):(.*)$", message)
            if m:
                try:
                    pct = int(m.group(1))
                    text = m.group(2).strip()
                    self.progress_bar.setValue(max(0, min(100, pct)))
                    # Keep the compact progress_output for backward compatibility (hidden by default)
                    try:
                        self.progress_output.append(f"[{pct}%] {text}")
                    except Exception:
                        pass
                    # Mirror into the unified collapsible log viewer
                    try:
                        if getattr(self, '_log_viewer', None) is not None:
                            self._log_viewer.moveCursor(QTextCursor.End)
                            self._log_viewer.insertPlainText(f"[{pct}%] {text}\n")
                            self._log_viewer.moveCursor(QTextCursor.End)
                    except Exception:
                        pass
                    return
                except Exception:
                    pass

            # Generic messages: write to hidden progress output and to unified log viewer
            try:
                self.progress_output.append(message)
            except Exception:
                pass
            try:
                if getattr(self, '_log_viewer', None) is not None:
                    self._log_viewer.moveCursor(QTextCursor.End)
                    self._log_viewer.insertPlainText(message + "\n")
                    self._log_viewer.moveCursor(QTextCursor.End)
            except Exception:
                pass

            # react to stage messages emitted by worker: format 'stage:<name>:<state>'
            try:
                if message.startswith('stage:'):
                    parts = message.split(':')
                    if len(parts) >= 3:
                        _, name, state = parts[:3]
                        self._set_stage_state(name, state)
            except Exception:
                pass

        def _set_stage_state(self, name: str, state: str) -> None:
            # state: started, ok, fail
            item = self._stage_labels.get(name)
            if not item:
                return
            try:
                badge = item[0] if isinstance(item, tuple) else item
                if state == 'started':
                    badge.setText('⏳')
                    badge.setStyleSheet('background:#FFD54F; color:#000; border-radius:24px; font-weight:bold; font-size:12pt;')
                elif state == 'ok':
                    badge.setText('✅')
                    badge.setStyleSheet('background:#A5D6A7; color:#000; border-radius:24px; font-weight:bold; font-size:12pt;')
                elif state == 'fail':
                    badge.setText('❌')
                    badge.setStyleSheet('background:#EF9A9A; color:#000; border-radius:24px; font-weight:bold; font-size:12pt;')
                else:
                    # reset to number
                    if isinstance(item, tuple) and len(item) > 1:
                        badge.setText(str(item[1]))
                    badge.setStyleSheet('background:#E0E0E0; color:#000; border-radius:24px; font-weight:bold; font-size:14pt;')
                # small animation (fade + pulse) to draw attention to state change
                try:
                    self._animate_badge(badge)
                except Exception:
                    pass
            except Exception:
                pass

        def _animate_badge(self, badge: Any) -> None:
            """Apply a short fade-in + pulse (size) animation to the badge label."""
            try:
                # Opacity effect
                effect = getattr(badge, '_opacity_effect', None)
                if effect is None:
                    try:
                        effect = QtWidgets.QGraphicsOpacityEffect(badge)
                        badge.setGraphicsEffect(effect)
                        badge._opacity_effect = effect
                    except Exception:
                        effect = None

                # Fade animation
                if effect is not None:
                    fade = QtCore.QPropertyAnimation(effect, b"opacity")
                    fade.setDuration(350)
                    fade.setStartValue(0.2)
                    fade.setEndValue(1.0)
                    fade.setEasingCurve(QtCore.QEasingCurve.OutCubic)
                    fade.start(QtCore.QAbstractAnimation.DeleteWhenStopped)

                # Pulse size animation using maximumWidth/Height
                try:
                    start_w = badge.width() or 48
                    start_h = badge.height() or 48
                    big_w = int(start_w * 1.35)
                    big_h = int(start_h * 1.35)

                    anim_up_w = QtCore.QPropertyAnimation(badge, b"maximumWidth")
                    anim_up_w.setDuration(180)
                    anim_up_w.setStartValue(start_w)
                    anim_up_w.setEndValue(big_w)
                    anim_up_w.setEasingCurve(QtCore.QEasingCurve.OutQuad)

                    anim_up_h = QtCore.QPropertyAnimation(badge, b"maximumHeight")
                    anim_up_h.setDuration(180)
                    anim_up_h.setStartValue(start_h)
                    anim_up_h.setEndValue(big_h)
                    anim_up_h.setEasingCurve(QtCore.QEasingCurve.OutQuad)

                    anim_down_w = QtCore.QPropertyAnimation(badge, b"maximumWidth")
                    anim_down_w.setDuration(220)
                    anim_down_w.setStartValue(big_w)
                    anim_down_w.setEndValue(start_w)
                    anim_down_w.setEasingCurve(QtCore.QEasingCurve.InOutQuad)

                    anim_down_h = QtCore.QPropertyAnimation(badge, b"maximumHeight")
                    anim_down_h.setDuration(220)
                    anim_down_h.setStartValue(big_h)
                    anim_down_h.setEndValue(start_h)
                    anim_down_h.setEasingCurve(QtCore.QEasingCurve.InOutQuad)

                    group = QtCore.QParallelAnimationGroup()
                    seq = QtCore.QSequentialAnimationGroup()
                    up_group = QtCore.QParallelAnimationGroup()
                    up_group.addAnimation(anim_up_w)
                    up_group.addAnimation(anim_up_h)
                    down_group = QtCore.QParallelAnimationGroup()
                    down_group.addAnimation(anim_down_w)
                    down_group.addAnimation(anim_down_h)
                    seq.addAnimation(up_group)
                    seq.addAnimation(down_group)
                    group.addAnimation(seq)
                    group.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
                except Exception:
                    pass
            except Exception:
                pass

        def _install_prereq(self, pkg_name: str, parent_dialog: Any) -> None:
            """Attempt to install a prerequisite using the platform package manager in a background thread."""
            ok = QtWidgets.QMessageBox.question(self, 'Install prerequisite', f'Do you want the installer to attempt installing {pkg_name}?', QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if ok != QtWidgets.QMessageBox.Yes:
                return

            key = pkg_name.lower()
            system = platform.system()

            # Special-case: install pip using python -m ensurepip / python -m pip
            if 'pip' in key:
                python_bin = shutil.which('python') or shutil.which('python3')
                if python_bin:
                    # Run ensurepip then upgrade pip in a background thread
                    self._install_pip_sequence(python_bin, parent_dialog)
                    return
                # else: fall through to package manager approach below

            # Build command depending on platform and package
            if system == 'Windows':
                if 'python' in key:
                    cmd = ['winget', 'install', '--id', 'Python.Python.3', '-e', '--silent']
                elif 'git' in key:
                    cmd = ['winget', 'install', '--id', 'Git.Git', '-e', '--silent']
                else:
                    cmd = ['winget', 'install', pkg_name]
            elif system == 'Darwin':
                brew = shutil.which('brew')
                if not brew:
                    QtWidgets.QMessageBox.information(self, 'Homebrew missing', 'Homebrew is not installed. Please install Homebrew first: https://brew.sh/')
                    return
                if 'python' in key:
                    cmd = [brew, 'install', 'python']
                elif 'git' in key:
                    cmd = [brew, 'install', 'git']
                else:
                    cmd = [brew, 'install', pkg_name]
            else:
                # Detect package manager on Linux
                if shutil.which('apt-get'):
                    mgr = 'apt'
                elif shutil.which('dnf'):
                    mgr = 'dnf'
                elif shutil.which('pacman'):
                    mgr = 'pacman'
                elif shutil.which('zypper'):
                    mgr = 'zypper'
                elif shutil.which('apk'):
                    mgr = 'apk'
                else:
                    mgr = None

                if mgr == 'apt':
                    if 'python' in key:
                        cmd = ['bash', '-lc', 'sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip']
                    elif 'pip' in key:
                        cmd = ['bash', '-lc', 'sudo apt-get update && sudo apt-get install -y python3-pip']
                    elif 'git' in key:
                        cmd = ['bash', '-lc', 'sudo apt-get update && sudo apt-get install -y git']
                    else:
                        cmd = ['bash', '-lc', f"sudo apt-get update && sudo apt-get install -y {pkg_name}"]
                elif mgr == 'dnf':
                    if 'python' in key:
                        cmd = ['bash', '-lc', 'sudo dnf install -y python3 python3-virtualenv python3-pip']
                    elif 'pip' in key:
                        cmd = ['bash', '-lc', 'sudo dnf install -y python3-pip']
                    elif 'git' in key:
                        cmd = ['bash', '-lc', 'sudo dnf install -y git']
                    else:
                        cmd = ['bash', '-lc', f"sudo dnf install -y {pkg_name}"]
                elif mgr == 'pacman':
                    if 'python' in key:
                        cmd = ['bash', '-lc', 'sudo pacman -Sy --noconfirm python']
                    elif 'pip' in key:
                        cmd = ['bash', '-lc', 'sudo pacman -Sy --noconfirm python-pip']
                    elif 'git' in key:
                        cmd = ['bash', '-lc', 'sudo pacman -Sy --noconfirm git']
                    else:
                        cmd = ['bash', '-lc', f"sudo pacman -Sy --noconfirm {pkg_name}"]
                elif mgr == 'zypper':
                    if 'python' in key:
                        cmd = ['bash', '-lc', 'sudo zypper refresh && sudo zypper install -y python3 python3-pip']
                    elif 'pip' in key:
                        cmd = ['bash', '-lc', 'sudo zypper refresh && sudo zypper install -y python3-pip']
                    elif 'git' in key:
                        cmd = ['bash', '-lc', 'sudo zypper refresh && sudo zypper install -y git']
                    else:
                        cmd = ['bash', '-lc', f"sudo zypper refresh && sudo zypper install -y {pkg_name}"]
                elif mgr == 'apk':
                    if 'python' in key:
                        cmd = ['bash', '-lc', 'sudo apk add python3 py3-pip']
                    elif 'pip' in key:
                        cmd = ['bash', '-lc', 'sudo apk add py3-pip']
                    elif 'git' in key:
                        cmd = ['bash', '-lc', 'sudo apk add git']
                    else:
                        cmd = ['bash', '-lc', f"sudo apk add {pkg_name}"]
                else:
                    QtWidgets.QMessageBox.information(self, 'Package manager not found', 'Could not detect a supported package manager. Please install the prerequisite manually.')
                    return

            # Run installation command in background
            self._run_command_in_thread(cmd, pkg_name, parent_dialog)

        def _run_command_in_thread(self, cmd, pkg_name: str, parent_dialog: Any) -> None:
            def worker():
                try:
                    # log start
                    if self._log_tail_path:
                        write_log(self._log_tail_path, 'INFO', 'installer', 'install_command_start', package=pkg_name, cmd=' '.join(cmd))
                    # run command
                    proc = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    out = proc.stdout
                    if self._log_tail_path:
                        write_log(self._log_tail_path, 'INFO', 'installer', 'install_command_success', package=pkg_name, output=out)
                    # schedule UI updates on main thread
                    QtCore.QTimer.singleShot(0, lambda: parent_dialog.accept() if parent_dialog else None)
                    QtCore.QTimer.singleShot(0, lambda: self.append_log(f'Installed {pkg_name} successfully'))
                except subprocess.CalledProcessError as e:
                    err = e.stderr if hasattr(e, 'stderr') else str(e)
                    if self._log_tail_path:
                        write_log(self._log_tail_path, 'ERROR', 'installer', 'install_command_failed', package=pkg_name, error=err)
                    QtCore.QTimer.singleShot(0, lambda: self.append_log(f'Failed to install {pkg_name}: {err}'))

            t = threading.Thread(target=worker, daemon=True)
            t.start()

        def _install_pip_sequence(self, python_bin: str, parent_dialog: Any) -> None:
            """Run python -m ensurepip --upgrade and python -m pip install --upgrade pip in a worker thread.

            Shows a small progress dialog while running and appends output into the sticky log viewer.
            """
            # create a non-modal progress dialog so the user sees activity
            progress_dialog = None
            try:
                progress_dialog = QtWidgets.QProgressDialog('Installing/Upgrading pip...', None, 0, 0, self)
                progress_dialog.setWindowTitle('Installing pip')
                progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
                progress_dialog.setCancelButton(None)
                progress_dialog.setMinimumDuration(0)
                progress_dialog.show()
            except Exception:
                progress_dialog = None

            def worker():
                # Prefer the installer log tail path. Avoid using current working directory as a fallback;
                # use the application data directory (or home) to store installer logs instead.
                try:
                    if getattr(self, '_log_tail_path', None):
                        log_path = self._log_tail_path
                    else:
                        if appdirs:
                            log_path = Path(appdirs.user_data_dir('Luister', appauthor=False)) / LOG_FILENAME
                        else:
                            log_path = Path.home() / LOG_FILENAME
                except Exception:
                    log_path = Path.home() / LOG_FILENAME

                # Ensure we have a Path instance (not None) before calling write_log
                try:
                    # Coerce via str() to avoid passing None/Path|None to Path()
                    log_path = Path(str(log_path))
                except Exception:
                    log_path = Path.home() / LOG_FILENAME

                try:
                    write_log(log_path, 'INFO', 'installer', 'ensurepip_start', python=python_bin)
                    # ensurepip may be no-op if pip already present
                    proc = subprocess.run([python_bin, '-m', 'ensurepip', '--upgrade'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if proc.stdout:
                        write_log(log_path, 'DEBUG', 'installer', 'ensurepip_stdout', output=proc.stdout[:4000])
                    if proc.stderr:
                        write_log(log_path, 'WARN', 'installer', 'ensurepip_stderr', error=proc.stderr[:4000])
                    write_log(log_path, 'INFO', 'installer', 'ensurepip_done')
                except Exception as e:
                    write_log(log_path, 'WARN', 'installer', 'ensurepip_failed', error=str(e))
                try:
                    write_log(log_path, 'INFO', 'installer', 'pip_upgrade_start', python=python_bin)
                    proc = subprocess.run([python_bin, '-m', 'pip', 'install', '--upgrade', 'pip'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if proc.stdout:
                        write_log(log_path, 'INFO', 'installer', 'pip_upgrade_stdout', output=proc.stdout[:4000])
                    if proc.stderr:
                        write_log(log_path, 'WARN', 'installer', 'pip_upgrade_stderr', error=proc.stderr[:4000])
                    if proc.returncode == 0:
                        write_log(log_path, 'INFO', 'installer', 'pip_upgrade_done')
                        QtCore.QTimer.singleShot(0, lambda: self.append_log('Installed/updated pip successfully'))
                        QtCore.QTimer.singleShot(0, lambda: parent_dialog.accept() if parent_dialog else None)
                    else:
                        err = proc.stderr or proc.stdout
                        write_log(log_path, 'ERROR', 'installer', 'pip_upgrade_failed', error=err[:4000])
                        QtCore.QTimer.singleShot(0, lambda: self.append_log(f'Failed to install/upgrade pip: {err}'))
                except Exception as e:
                    write_log(log_path, 'ERROR', 'installer', 'pip_upgrade_failed', error=str(e))
                    QtCore.QTimer.singleShot(0, lambda: self.append_log(f'Failed to install/upgrade pip: {e}'))
                finally:
                    if progress_dialog is not None:
                        try:
                            QtCore.QTimer.singleShot(0, lambda pd=progress_dialog: getattr(pd, 'close', lambda: None)())
                        except Exception:
                            pass

            t = threading.Thread(target=worker, daemon=True)
            t.start()

        def start_install(self):
            repo = self.repo_input.text().strip()
            install_dir = self.install_dir_input.text().strip()

            # Basic validations
            if not repo:
                QtWidgets.QMessageBox.warning(self, "Missing repository", "Please enter the repository URL to clone.")
                return
            if not (repo.startswith("http://") or repo.startswith("https://") or repo.startswith("git@")):
                QtWidgets.QMessageBox.warning(self, "Invalid repository", "Repository URL looks invalid. Use https://... or git@...:...git")
                return
            if not install_dir:
                QtWidgets.QMessageBox.warning(self, "Missing install directory", "Please select an installation directory.")
                return
            try:
                target = Path(install_dir).expanduser()
                target.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Directory error", f"Cannot write to target directory: {e}")
                return

            # Pre-install prerequisites dialog: check and prompt
            proceed = self.check_and_prompt_prereqs()
            if not proceed:
                return

            # Prepare log tailing
            try:
                log_path = Path(install_dir) / LOG_FILENAME
                log_path.parent.mkdir(parents=True, exist_ok=True)
                # ensure file exists
                log_path.write_text('', encoding='utf-8') if not log_path.exists() else None
                self._log_tail_path = log_path
                self._log_tail_pos = 0
                self._log_viewer.clear()
                # start tail timer
                self._log_tail_timer.start()
            except Exception:
                self._log_tail_path = None

            # Disable inputs while installing
            self.repo_input.setEnabled(False)
            self.install_dir_input.setEnabled(False)
            self.start_button.setEnabled(False)
            self.progress_bar.setValue(1)

            self.append_log(f"Starting install: {repo} -> {install_dir}")

            self.thread = QtCore.QThread()
            self.worker = InstallerWorker(repo, install_dir)
            self.worker.moveToThread(self.thread)
            self.worker.progress.connect(self.append_log)
            self.worker.finished.connect(self.on_finished)
            self.thread.started.connect(self.worker.run)
            self.thread.start()

        def on_finished(self, ok: bool, result: str) -> None:
            """Slot called when the InstallerWorker finishes."""
            try:
                # stop thread safely
                try:
                    if getattr(self, 'thread', None) is not None:
                        try:
                            self.thread.quit()
                        except Exception:
                            pass
                except Exception:
                    pass

                # Update UI
                try:
                    self.repo_input.setEnabled(True)
                    self.install_dir_input.setEnabled(True)
                    self.start_button.setEnabled(True)
                except Exception:
                    pass

                # Final progress
                try:
                    self.progress_bar.setValue(100 if ok else self.progress_bar.value())
                except Exception:
                    pass

                # Log and notify
                try:
                    # Append concise status and show a completion summary dialog with actions
                    self.append_log('Installation finished successfully.' if ok else f'Installation failed: {result}')
                    self._show_completion_page(ok, result)
                except Exception:
                    pass
            except Exception:
                pass

        def _show_completion_page(self, ok: bool, result: str) -> None:
            """Show a simple Installation Complete/Failed dialog with a brief summary and actions."""
            try:
                dlg = QtWidgets.QDialog(self)
                dlg.setWindowTitle('Installation Complete' if ok else 'Installation Failed')
                dlg.setMinimumWidth(420)
                v = QtWidgets.QVBoxLayout(dlg)

                status_lbl = QtWidgets.QLabel(f"<b>{'Success' if ok else 'Failure'}</b>")
                v.addWidget(status_lbl)

                info = QtWidgets.QLabel(f"Installation path: {result}")
                info.setWordWrap(True)
                v.addWidget(info)

                # Offer actions: open folder, reveal logs/details, close
                btn_row = QtWidgets.QHBoxLayout()
                open_btn = QtWidgets.QPushButton('Open install folder')
                def _open_folder():
                    try:
                        p = Path(result) if ok else Path(self.install_dir_input.text() or Path.home())
                        if platform.system() == 'Windows':
                            subprocess.Popen(['explorer', str(p)])
                        elif platform.system() == 'Darwin':
                            subprocess.Popen(['open', str(p)])
                        else:
                            subprocess.Popen(['xdg-open', str(p)])
                    except Exception:
                        pass
                open_btn.clicked.connect(_open_folder)

                details_btn = QtWidgets.QPushButton('See details')
                def _show_details():
                    try:
                        # Reveal the unified log viewer and ensure the toggle reflects state
                        if getattr(self, '_toggle_logs_btn', None) is not None:
                            self._toggle_logs_btn.setChecked(True)
                        if getattr(self, '_log_viewer', None) is not None:
                            self._log_viewer.setVisible(True)
                    except Exception:
                        pass
                details_btn.clicked.connect(_show_details)

                close_btn = QtWidgets.QPushButton('Close')
                close_btn.clicked.connect(dlg.accept)

                btn_row.addStretch(1)
                btn_row.addWidget(open_btn)
                btn_row.addWidget(details_btn)
                btn_row.addWidget(close_btn)
                v.addLayout(btn_row)

                dlg.exec_()
            except Exception:
                pass

        def check_and_prompt_prereqs(self) -> bool:
            """Check for python/pip/git and prompt the user with downloadable links if something is missing.
            Returns True if the user chooses to proceed, False to cancel."""
            # Loop: allow Retry after installs; Continue only enabled when required prereqs are met.
            while True:
                # Recompute missing lists each loop
                missing_required = []
                missing_optional = []
                python_bin = shutil.which('python') or shutil.which('python3')
                if not python_bin:
                    missing_required.append(('Python', ''))
                else:
                    try:
                        subprocess.check_call([python_bin, '-m', 'pip', '--version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        missing_required.append(('pip', ''))
                git_bin = shutil.which('git')
                if not git_bin:
                    missing_optional.append(('Git (optional)', ''))

                if not missing_required and not missing_optional:
                    return True

                dlg = QtWidgets.QDialog(self)
                dlg.setWindowTitle('Prerequisites')
                v = QtWidgets.QVBoxLayout(dlg)

                intro = QtWidgets.QLabel(dlg)
                intro.setWordWrap(True)
                intro.setText('The installer checked your system and found the following prerequisites. Use the Install buttons to let the installer try to install them, or Retry after installing. Continue is only available once required prerequisites are satisfied.')
                v.addWidget(intro)

                if missing_required:
                    v.addWidget(QtWidgets.QLabel('<b>Required</b>'))
                    for name, _ in missing_required:
                        row = QtWidgets.QHBoxLayout()
                        row.addWidget(QtWidgets.QLabel(name))
                        btn = QtWidgets.QPushButton('Install')
                        btn.clicked.connect(lambda _, pkg=name: self._install_prereq(pkg, dlg))
                        row.addWidget(btn)
                        v.addLayout(row)

                if missing_optional:
                    v.addWidget(QtWidgets.QLabel('<b>Optional</b> (installer can proceed without these)'))
                    for name, _ in missing_optional:
                        row = QtWidgets.QHBoxLayout()
                        row.addWidget(QtWidgets.QLabel(name))
                        btn = QtWidgets.QPushButton('Install')
                        btn.clicked.connect(lambda _, pkg=name: self._install_prereq(pkg, dlg))
                        row.addWidget(btn)
                        v.addLayout(row)

                # Action buttons: Continue (disabled if required missing), Retry, Cancel
                actions = QtWidgets.QHBoxLayout()
                continue_btn = QtWidgets.QPushButton('Continue')
                retry_btn = QtWidgets.QPushButton('Retry')
                cancel_btn = QtWidgets.QPushButton('Cancel')
                continue_btn.setEnabled(not missing_required)
                actions.addStretch(1)
                actions.addWidget(continue_btn)
                actions.addWidget(retry_btn)
                actions.addWidget(cancel_btn)
                v.addLayout(actions)

                result: dict = {'action': None}

                def on_continue():
                    result['action'] = 'continue'
                    dlg.accept()

                def on_retry():
                    result['action'] = 'retry'
                    dlg.accept()

                def on_cancel():
                    result['action'] = 'cancel'
                    dlg.reject()

                continue_btn.clicked.connect(on_continue)
                retry_btn.clicked.connect(on_retry)
                cancel_btn.clicked.connect(on_cancel)

                # Start a background timer to re-check prerequisites every 10 seconds
                try:
                    def _recheck():
                        try:
                            python_bin = shutil.which('python') or shutil.which('python3')
                            pip_ok = False
                            if python_bin:
                                try:
                                    subprocess.check_call([python_bin, '-m', 'pip', '--version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                    pip_ok = True
                                except Exception:
                                    pip_ok = False
                            # enable Continue only when required prerequisites are met
                            QtCore.QTimer.singleShot(0, lambda: continue_btn.setEnabled(bool(python_bin and pip_ok)))
                        except Exception:
                            pass

                    _prereq_timer = QtCore.QTimer(dlg)
                    _prereq_timer.setInterval(10000)
                    _prereq_timer.timeout.connect(_recheck)
                    _prereq_timer.start()
                except Exception:
                    _prereq_timer = None

                dlg.exec_()

                # stop timer when dialog closes
                try:
                    if '_prereq_timer' in locals() and _prereq_timer is not None:
                        _prereq_timer.stop()
                except Exception:
                    pass

                if result['action'] == 'continue':
                    return True
                if result['action'] == 'cancel':
                    return False
                # if 'retry' or dialog closed by install success, loop and re-check 

        def _tail_log_file(self) -> None:
            """Read new log lines from the current log file and display them in the sticky viewer."""
            try:
                if not self._log_tail_path:
                    return
                p = Path(self._log_tail_path)
                if not p.exists():
                    return
                with p.open('r', encoding='utf-8', errors='replace') as fh:
                    fh.seek(self._log_tail_pos)
                    new = fh.read()
                    if new:
                        self._log_viewer.moveCursor(QTextCursor.End)
                        self._log_viewer.insertPlainText(new)
                        self._log_viewer.moveCursor(QTextCursor.End)
                    self._log_tail_pos = fh.tell()
            except Exception:
                pass

        def _config_path(self) -> Path:
            # Use appdirs if available, otherwise use home directory
            try:
                if appdirs:
                    cfg_dir = Path(appdirs.user_config_dir('Luister', appauthor=False))
                else:
                    cfg_dir = Path.home() / '.luister'
                cfg_dir.mkdir(parents=True, exist_ok=True)
                return cfg_dir / 'installer_ui.json'
            except Exception:
                return Path.home() / '.luister_installer_ui.json'

        def _load_ui_state(self) -> dict | None:
            p = self._config_path()
            try:
                if p.exists():
                    state = json.loads(p.read_text(encoding='utf-8'))
                    # Apply system dark mode detection to theme
                    if state.get('theme') == 'auto':
                        system_dark_mode = detect_system_dark_mode()
                        if system_dark_mode is not None:
                            state['theme'] = 'dark' if system_dark_mode else 'light'
                    # Load speaker lock settings
                    self._speaker_lock_enabled = state.get('speaker_lock_enabled', False)
                    self._speaker_lock_threshold = state.get('speaker_lock_threshold', 0.78)
                    return state
            except Exception:
                return None
            return None

        def _save_ui_state(self) -> None:
            p = self._config_path()
            try:
                state = {
                    'logs_visible': bool(self._log_viewer.isVisible()),
                    'log_height': int(self._log_viewer.height()),
                    'theme': getattr(self, '_theme', 'light'), # Persist theme
                    'speaker_lock_enabled': self._speaker_lock_enabled, # Persist speaker lock settings
                    'speaker_lock_threshold': self._speaker_lock_threshold, # Persist speaker lock settings
                }
                p.write_text(json.dumps(state), encoding='utf-8')
            except Exception:
                pass

        def closeEvent(self, event):
            try:
                self._save_ui_state()
            except Exception:
                pass
            try:
                super().closeEvent(event)
            except Exception:
                event.accept()

        def _create_installation_config(self):
            """Creates the installation stages UI and adds it to the main layout."""
            # avoid creating twice
            if getattr(self, '_config_created', False):
                return
            try:
                self._stages = [
                    ("clone", "Clone repository", "Clone the project from Git or download archive if Git is unavailable."),
                    ("venv", "Create virtual environment", "Create a local .venv inside the application folder."),
                    ("deps", "Install dependencies", "Run uv sync and build (or python -m pip install) to install the app into the venv."),
                    ("launch", "Create launcher & shortcuts", "Create a small launcher and Desktop/StartMenu shortcuts to start Luister."),
                ]
                stages_frame = QtWidgets.QFrame()
                stages_layout = QtWidgets.QHBoxLayout(stages_frame)
                self._stage_labels = {}
                for idx, (key, title, tip) in enumerate(self._stages, start=1):
                    col = QtWidgets.QVBoxLayout()
                    # numbered badge
                    badge = QtWidgets.QLabel(str(idx))
                    badge.setAlignment(QtCore.Qt.AlignCenter)
                    # Slightly smaller badges to fit the wizard better
                    badge.setFixedSize(40, 40)
                    # Glass gradient badge (reduced radius and font-size)
                    badge.setStyleSheet('background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(255,255,255,0.9), stop:1 rgba(220,230,255,0.8)); color:#0b1b2b; border-radius:20px; font-weight:bold; font-size:11pt; border: 1px solid rgba(255,255,255,0.6);')
                    title_lbl = QtWidgets.QLabel(title)
                    title_lbl.setAlignment(QtCore.Qt.AlignCenter)
                    title_lbl.setToolTip(tip)
                    title_lbl.setStyleSheet('font-size:11pt; color:#273346;')
                    col.addWidget(badge)
                    col.addWidget(title_lbl)
                    stages_layout.addLayout(col)
                    # store tuple (badge_label, index)
                    self._stage_labels[key] = (badge, idx)
                self._main_layout.addWidget(stages_frame)
                # Reveal installation controls now that user started
                try:
                    # If inputs not yet created, retry shortly (happens if timing differs)
                    if not hasattr(self, 'repo_input'):
                        QtCore.QTimer.singleShot(120, self._create_installation_config)
                        return
                    self.repo_input.setVisible(True)
                    self.install_dir_input.setVisible(True)
                    self.start_button.setVisible(True)
                    self.progress_bar.setVisible(True)
                    self.progress_output.setVisible(True)
                    self._toggle_logs_btn.setVisible(True)
                    # focus repo input
                    try:
                        self.repo_input.setFocus()
                    except Exception:
                        pass
                except Exception as e:
                    # surface error to user log pane
                    try:
                        self.append_log(f"stage:internal:error:{e}")
                    except Exception:
                        pass
                # mark created so we don't duplicate
                self._config_created = True
            except Exception:
                # ensure not to crash the UI
                try:
                    self.append_log('Failed to create installation UI components')
                except Exception:
                    pass

        def _apply_theme(self, theme: str) -> None:
            """Apply light/dark theme to key widgets."""
            try:
                self._theme = theme
                if theme == 'dark':
                    bg = 'qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(20,24,28,255), stop:1 rgba(36,40,48,255))'
                    card_bg = 'rgba(255,255,255,0.06)'
                    card_border = 'rgba(255,255,255,0.06)'
                    title_color = '#E6EEF8'
                    subtitle_color = '#AAB6C2'
                    badge_bg = 'qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(80,90,110,0.6), stop:1 rgba(60,70,90,0.5))'
                    badge_text = '#EAF2FF'
                    btn_style = "QPushButton { background: rgba(255,255,255,0.04); color:#EAF2FF; border:1px solid rgba(255,255,255,0.06); border-radius:8px; padding:6px 12px;}"
                else:
                    bg = 'qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(250,250,255,255), stop:1 rgba(235,240,255,255))'
                    card_bg = 'rgba(255,255,255,0.72)'
                    card_border = 'rgba(255,255,255,0.5)'
                    title_color = '#2b2b2b'
                    subtitle_color = '#444444'
                    badge_bg = 'qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(255,255,255,0.9), stop:1 rgba(220,230,255,0.8))'
                    badge_text = '#0b1b2b'
                    btn_style = "QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(255,255,255,0.85), stop:1 rgba(240,245,255,0.9)); border: 1px solid rgba(255,255,255,0.6); border-radius: 8px; padding:8px 16px; }"

                # apply central background
                try:
                    cw = self.centralWidget()
                    if cw is not None:
                        cw.setStyleSheet(f'background: {bg};')
                except Exception:
                    pass

                # welcome card
                try:
                    if hasattr(self, '_welcome_card'):
                        self._welcome_card.setStyleSheet(f'background: {card_bg}; border: 1px solid {card_border}; border-radius: 12px;')
                except Exception:
                    pass

                # title/subtitle
                try:
                    if hasattr(self, 'title_label'):
                        self.title_label.setStyleSheet(f'color: {title_color}; font-size:20pt;')
                    if hasattr(self, 'subtitle'):
                        self.subtitle.setStyleSheet(f'font-size:11pt; color: {subtitle_color};')
                except Exception:
                    pass

                # buttons
                try:
                    if getattr(self, 'get_started', None) is not None:
                        self.get_started.setStyleSheet(btn_style)
                    btn = getattr(self, '_theme_btn', None)
                    if btn is not None:
                        # simple invert icon
                        btn.setText('☀️' if theme == 'dark' else '🌙')
                except Exception:
                    pass

                # badges default
                try:
                    for key, item in self._stage_labels.items():
                        badge = item[0] if isinstance(item, tuple) else item
                        try:
                            badge.setStyleSheet(f'background: {badge_bg}; color: {badge_text}; border-radius:28px; font-weight:bold; font-size:14pt; border: 1px solid rgba(255,255,255,0.6);')
                        except Exception:
                            pass
                except Exception:
                    pass

            except Exception:
                pass

        def _open_settings_dialog(self):
            """Opens a settings dialog to allow the user to choose the theme."""
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("Installer Settings")
            dlg.setMinimumWidth(300)
            layout = QtWidgets.QVBoxLayout(dlg)

            # Theme selection
            theme_group = QtWidgets.QGroupBox("Theme")
            theme_layout = QtWidgets.QVBoxLayout(theme_group)

            light_radio = QtWidgets.QRadioButton("Light")
            dark_radio = QtWidgets.QRadioButton("Dark")
            auto_radio = QtWidgets.QRadioButton("Auto (System)")

            if self._theme == 'dark':
                dark_radio.setChecked(True)
            elif self._theme == 'light':
                light_radio.setChecked(True)
            else:
                auto_radio.setChecked(True)

            theme_layout.addWidget(light_radio)
            theme_layout.addWidget(dark_radio)
            theme_layout.addWidget(auto_radio)
            theme_layout.addStretch(1)
            layout.addWidget(theme_group)

            # Speaker lock (lightweight enrollment)
            speaker_group = QtWidgets.QGroupBox("Speaker lock (optional)")
            sp_layout = QtWidgets.QVBoxLayout(speaker_group)
            self._speaker_enable_cb = QtWidgets.QCheckBox('Enable speaker-only mode (allow only enrolled speaker)')
            sp_layout.addWidget(self._speaker_enable_cb)
            row = QtWidgets.QHBoxLayout()
            self._load_sample_btn = QtWidgets.QPushButton('Load sample (WAV)')
            self._load_sample_btn.setToolTip('Load a short WAV file (5-15s) to enroll the primary speaker')
            row.addWidget(self._load_sample_btn)
            self._speaker_status_lbl = QtWidgets.QLabel('No enrollment')
            row.addWidget(self._speaker_status_lbl)
            sp_layout.addLayout(row)

            # threshold slider
            thr_row = QtWidgets.QHBoxLayout()
            thr_row.addWidget(QtWidgets.QLabel('Match threshold'))
            self._speaker_thresh_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self._speaker_thresh_slider.setRange(50, 95)
            self._speaker_thresh_slider.setValue(78)
            thr_row.addWidget(self._speaker_thresh_slider)
            self._speaker_thresh_val = QtWidgets.QLabel('0.78')
            thr_row.addWidget(self._speaker_thresh_val)
            sp_layout.addLayout(thr_row)

            layout.addWidget(speaker_group)

            # Action buttons
            buttons = QtWidgets.QHBoxLayout()
            save_btn = QtWidgets.QPushButton("Save Settings")
            save_btn.clicked.connect(dlg.accept)
            buttons.addStretch(1)
            buttons.addWidget(save_btn)
            layout.addLayout(buttons)

            dlg.exec_()

            selected_theme = None
            if light_radio.isChecked():
                selected_theme = 'light'
            elif dark_radio.isChecked():
                selected_theme = 'dark'
            elif auto_radio.isChecked():
                selected_theme = 'auto'

            if selected_theme and selected_theme != self._theme:
                self._theme = selected_theme
                self._apply_theme(self._theme)
                self._save_ui_state()

            # Speaker settings: persist checkbox and threshold
            try:
                enabled = bool(getattr(self, '_speaker_enable_cb', None) and self._speaker_enable_cb.isChecked())
                slider = getattr(self, '_speaker_thresh_slider', None)
                thresh_val = int(slider.value()) if slider is not None else 78
                # store as float between 0 and 1
                self._speaker_lock_enabled = enabled
                self._speaker_lock_threshold = float(thresh_val) / 100.0
                self._save_ui_state()
            except Exception:
                pass

            # Hook up actions for sample loading after dialog close (connect earlier UI elements)
            try:
                def _on_load_sample():
                    try:
                        dlg_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Select enrollment WAV', str(Path.home()), 'WAV files (*.wav)')
                        if dlg_path:
                            self._enroll_from_wav(Path(dlg_path))
                    except Exception as e:
                        QtWidgets.QMessageBox.warning(self, 'Enrollment failed', f'Could not enroll sample: {e}')
                if getattr(self, '_load_sample_btn', None) is not None:
                    self._load_sample_btn.clicked.connect(_on_load_sample)
            except Exception:
                pass

        def _read_wav_file(self, file_path: Path) -> bytes | None:
            """Reads a WAV file and returns its raw bytes."""
            try:
                with open(file_path, 'rb') as f:
                    return f.read()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, 'Error reading WAV', f'Could not read WAV file {file_path}: {e}')
                return None

        def _enroll_from_wav(self, wav_path: Path) -> None:
            """Enrolls a speaker from a WAV file using the speaker_fingerprint module."""
            if speaker_fingerprint is None:
                QtWidgets.QMessageBox.warning(self, 'Speaker lock not available', 'Speaker lock functionality is not available in this installation.')
                return

            wav_data = self._read_wav_file(wav_path)
            if wav_data is None:
                return

            tmp_wav_path = None
            try:
                # Use a temporary file for enrollment
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_wav:
                    tmp_wav.write(wav_data)
                    tmp_wav_path = Path(tmp_wav.name)

                    # Enroll the speaker
                    speaker_id = speaker_fingerprint.enroll_speaker(str(tmp_wav_path))
                    if speaker_id:
                        self._speaker_status_lbl.setText(f'Enrolled as speaker ID: {speaker_id}')
                        self._speaker_status_lbl.setStyleSheet('color: green; font-weight: bold;')
                        QtWidgets.QMessageBox.information(self, 'Enrollment successful', f'Speaker enrolled successfully with ID: {speaker_id}')
                    else:
                        self._speaker_status_lbl.setText('Enrollment failed')
                        self._speaker_status_lbl.setStyleSheet('color: red; font-weight: bold;')
                        QtWidgets.QMessageBox.warning(self, 'Enrollment failed', 'Failed to enroll speaker from WAV file.')
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, 'Enrollment failed', f'An unexpected error occurred during enrollment: {e}')
            finally:
                # Clean up the temporary file if created
                try:
                    if tmp_wav_path is not None and tmp_wav_path.exists():
                        tmp_wav_path.unlink()
                except Exception:
                    pass

        def _set_windows_taskbar_icon(self, hwnd: int, icon_path: str) -> None:
            """Sets the taskbar and window icon for the given HWND using Win32 APIs.

            This attempts to load an .ico file from disk with LoadImageW and posts
            WM_SETICON messages for both large and small icons so the taskbar/ALT+TAB
            pick up the correct artwork.
            """
            if ctypes is None:
                return
            try:
                # Constants
                WM_SETICON = 0x0080
                ICON_SMALL = 0
                ICON_BIG = 1
                LR_LOADFROMFILE = 0x00000010
                IMAGE_ICON = 1

                # Ensure appid present
                try:
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('net.luister.app')
                except Exception:
                    pass

                # Load the icon from file (Unicode API)
                hicon = ctypes.windll.user32.LoadImageW(0, str(icon_path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
                if not hicon:
                    return

                # Ensure hwnd is integer
                try:
                    win = int(hwnd)
                except Exception:
                    return

                # Post messages to set small and big icons
                try:
                    ctypes.windll.user32.SendMessageW(win, WM_SETICON, ICON_SMALL, hicon)
                    ctypes.windll.user32.SendMessageW(win, WM_SETICON, ICON_BIG, hicon)
                except Exception:
                    # best-effort; ignore failures
                    pass
            except Exception:
                # swallow errors to avoid crashing the GUI
                pass

        def _send_logs_report(self) -> None:
            """Simulate sending logs to the dev team (background task with UI progress)."""
            # Resolve log path
            p = getattr(self, '_log_tail_path', None)
            if p is None:
                QtWidgets.QMessageBox.warning(self, "No Logs", "No log file configured for sending.")
                return
            try:
                log_path = Path(p)
            except Exception:
                QtWidgets.QMessageBox.warning(self, "No Logs", "No log file configured for sending.")
                return

            if not log_path.exists():
                QtWidgets.QMessageBox.warning(self, "No Logs", "No log file found to send.")
                return

            # Progress dialog
            try:
                dlg = QtWidgets.QProgressDialog('Sending logs to dev team...', None, 0, 100, self)
                dlg.setWindowTitle('Send Logs')
                dlg.setWindowModality(QtCore.Qt.WindowModal)
                dlg.setCancelButtonText('Cancel')
                dlg.setAutoClose(False)
                dlg.show()
            except Exception:
                dlg = None

            def worker():
                try:
                    # Read log (cap to avoid huge sends)
                    content = log_path.read_text(encoding='utf-8', errors='replace')
                    total = len(content)
                    write_log(log_path, 'INFO', 'installer', 'send_logs_start', recipient='yilmaz@codesapien.net', size=total)
                    # Simulate chunked upload
                    steps = 5
                    for i in range(steps):
                        v = int((i+1)/steps*100)
                        if dlg is not None:
                            QtCore.QTimer.singleShot(0, (lambda val=v, d=dlg: d.setValue(val) if d is not None else None))
                        QtCore.QThread.msleep(400)
                        QtCore.QTimer.singleShot(0, (lambda msg=f'Sending logs... ({v}%)', inst=self: inst.append_log(msg)))
                    # Simulate success
                    write_log(log_path, 'INFO', 'installer', 'send_logs_done', recipient='yilmaz@codesapien.net')
                    QtCore.QTimer.singleShot(0, lambda: self.append_log('Logs successfully sent to yilmaz@codesapien.net (simulated)'))
                    QtCore.QTimer.singleShot(0, lambda: QtWidgets.QMessageBox.information(self, 'Logs Sent', 'Logs simulated as sent to yilmaz@codesapien.net'))
                except Exception as e:
                    write_log(log_path, 'ERROR', 'installer', 'send_logs_failed', error=str(e))
                    QtCore.QTimer.singleShot(0, lambda: QtWidgets.QMessageBox.critical(self, 'Send Failed', f'Failed to send logs: {e}'))
                finally:
                    if dlg is not None:
                        try:
                            QtCore.QTimer.singleShot(0, lambda d=dlg: d.close())
                        except Exception:
                            pass

            t = threading.Thread(target=worker, daemon=True)
            t.start()


def main():
    if QtWidgets is None or QtCore is None:
        print("GUI Qt bindings not available. Please install PySide6 (Windows) or PyQt5 (Linux/macOS) to run the GUI installer.")
        sys.exit(2)

    # On Windows, set AppUserModelID early to help taskbar grouping
    if platform.system() == 'Windows' and ctypes is not None:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('net.luister.app')
        except Exception:
            pass

    app = QtWidgets.QApplication(sys.argv)

    icon_path = None
    try:
        src = find_project_logo()
        if src and src.exists() and QtGui is not None:
            # Prefer SVG rasterization when possible
            if src.suffix.lower() == '.svg' and QSvgRenderer is not None:
                try:
                    svg = QSvgRenderer(str(src))
                    img = QtGui.QImage(256, 256, QtGui.QImage.Format_ARGB32)
                    img.fill(QtGui.QColor(0, 0, 0, 0))
                    painter = QtGui.QPainter(img)
                    svg.render(painter)
                    painter.end()
                    pix = QtGui.QPixmap.fromImage(img)
                    app.setWindowIcon(QtGui.QIcon(pix))
                except Exception:
                    try:
                        app.setWindowIcon(QtGui.QIcon(str(src)))
                    except Exception:
                        icon_path = None
            else:
                try:
                    app.setWindowIcon(QtGui.QIcon(str(src)))
                    icon_path = str(src)
                except Exception:
                    icon_path = None
    except Exception:
        icon_path = None

    w = InstallerWindow()
    # also set window icon for the main window if we have a file path
    if icon_path and QtGui is not None:
        try:
            w.setWindowIcon(QtGui.QIcon(icon_path))
        except Exception:
            pass

    w.show()

    # On Windows, attempt to set the taskbar/window icons at Win32 level (best-effort)
    if platform.system() == 'Windows' and ctypes is not None and icon_path:
        try:
            hwnd = int(w.winId())
            try:
                w._set_windows_taskbar_icon(hwnd, icon_path)
            except Exception:
                pass
        except Exception:
            pass

    return app.exec_() 