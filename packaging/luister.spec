# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Luister - Cross-platform music player

This spec file builds standalone executables for Windows, macOS, and Linux.
Run with: pyinstaller packaging/luister.spec
"""

import sys
import os
from pathlib import Path

# Determine platform
IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')

# Project paths
SPEC_DIR = Path(SPECPATH)
PROJECT_ROOT = SPEC_DIR.parent
SRC_DIR = PROJECT_ROOT / 'src'
PACKAGING_DIR = PROJECT_ROOT / 'packaging'

# App metadata
APP_NAME = 'Luister'
APP_VERSION = '0.1.0'
APP_BUNDLE_ID = 'io.github.luister'

# Icon paths (platform-specific)
if IS_WINDOWS:
    ICON_PATH = str(PACKAGING_DIR / 'icons' / 'luister.ico')
elif IS_MACOS:
    ICON_PATH = str(PACKAGING_DIR / 'icons' / 'luister.icns')
else:
    ICON_PATH = str(PACKAGING_DIR / 'icons' / 'luister.png')

# Check if icon exists, use None if not
if not Path(ICON_PATH).exists():
    ICON_PATH = None

# Hidden imports that PyInstaller might miss
hidden_imports = [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.QtMultimedia',
    'PyQt6.sip',
    'librosa',
    'soundfile',
    'numpy',
    'tinytag',
    'whisper',
    'pydub',
    'yt_dlp',
    'appdirs',
    'PIL',
    'PIL.Image',
]

# Data files to include
datas = [
    # Include any UI files or assets
    (str(SRC_DIR / 'luister'), 'luister'),
]

# Add whisper assets if available
try:
    import whisper
    whisper_path = Path(whisper.__file__).parent
    if (whisper_path / 'assets').exists():
        datas.append((str(whisper_path / 'assets'), 'whisper/assets'))
except ImportError:
    pass

# Binaries to include (platform-specific)
binaries = []

# Bundle ffmpeg/ffprobe for yt-dlp audio extraction
import shutil
if IS_MACOS:
    # Check common Homebrew locations for ffmpeg
    for ffmpeg_dir in ['/opt/homebrew/bin', '/usr/local/bin']:
        ffmpeg_path = Path(ffmpeg_dir) / 'ffmpeg'
        ffprobe_path = Path(ffmpeg_dir) / 'ffprobe'
        if ffmpeg_path.exists() and ffprobe_path.exists():
            binaries.append((str(ffmpeg_path), '.'))
            binaries.append((str(ffprobe_path), '.'))
            print(f"Bundling ffmpeg from {ffmpeg_dir}")
            break
elif IS_WINDOWS:
    # Check for ffmpeg in PATH or common locations
    ffmpeg_exe = shutil.which('ffmpeg')
    ffprobe_exe = shutil.which('ffprobe')
    if ffmpeg_exe and ffprobe_exe:
        binaries.append((ffmpeg_exe, '.'))
        binaries.append((ffprobe_exe, '.'))
elif IS_LINUX:
    ffmpeg_exe = shutil.which('ffmpeg')
    ffprobe_exe = shutil.which('ffprobe')
    if ffmpeg_exe and ffprobe_exe:
        binaries.append((ffmpeg_exe, '.'))
        binaries.append((ffprobe_exe, '.'))

# Collect all submodules
collect_submodules = [
    'luister',
    'PyQt6',
    'librosa',
    'numpy',
    'whisper',
]

# Analysis
a = Analysis(
    [str(SRC_DIR / 'luister' / '__init__.py')],
    pathex=[str(SRC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy.spatial.cKDTree',
    ],
    noarchive=False,
)

# Remove duplicate/unnecessary files
def remove_from_list(lst, pattern):
    return [x for x in lst if pattern not in str(x[0]).lower()]

# Remove test files
a.datas = remove_from_list(a.datas, 'test')
a.datas = remove_from_list(a.datas, '__pycache__')

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

if IS_MACOS:
    # macOS: Create an app bundle
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=True,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=ICON_PATH,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )

    app = BUNDLE(
        coll,
        name=f'{APP_NAME}.app',
        icon=ICON_PATH,
        bundle_identifier=APP_BUNDLE_ID,
        info_plist={
            'CFBundleName': APP_NAME,
            'CFBundleDisplayName': APP_NAME,
            'CFBundleIdentifier': APP_BUNDLE_ID,
            'CFBundleVersion': APP_VERSION,
            'CFBundleShortVersionString': APP_VERSION,
            'CFBundleExecutable': APP_NAME,
            'CFBundlePackageType': 'APPL',
            'LSMinimumSystemVersion': '10.15',
            'NSHighResolutionCapable': True,
            'NSMicrophoneUsageDescription': 'Luister needs microphone access for audio visualization.',
            'LSApplicationCategoryType': 'public.app-category.music',
            'CFBundleDocumentTypes': [
                {
                    'CFBundleTypeName': 'Audio File',
                    'CFBundleTypeRole': 'Viewer',
                    'LSHandlerRank': 'Alternate',
                    'LSItemContentTypes': [
                        'public.mp3',
                        'public.mpeg-4-audio',
                        'com.apple.m4a-audio',
                        'public.aiff-audio',
                        'com.microsoft.waveform-audio',
                        'org.xiph.flac',
                        'org.xiph.ogg-vorbis',
                    ],
                }
            ],
        },
    )

elif IS_WINDOWS:
    # Windows: Create a single executable with console disabled
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=ICON_PATH,
        version_file=str(PACKAGING_DIR / 'windows' / 'version_info.txt') if (PACKAGING_DIR / 'windows' / 'version_info.txt').exists() else None,
    )

else:
    # Linux: Create executable with collected files
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME.lower(),
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=ICON_PATH,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name=APP_NAME.lower(),
    )
