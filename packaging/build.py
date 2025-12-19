#!/usr/bin/env python3
"""
Cross-platform build script for Luister.

Usage:
    python packaging/build.py [--platform PLATFORM] [--clean] [--dmg] [--installer]

Options:
    --platform    Target platform: auto, windows, macos, linux (default: auto)
    --clean       Clean build directories before building
    --dmg         Create DMG on macOS
    --installer   Create installer (NSIS on Windows, deb on Linux)
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


# Project paths
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
DIST_DIR = PROJECT_ROOT / 'dist'
BUILD_DIR = PROJECT_ROOT / 'build'
VENV_DIR = PROJECT_ROOT / '.venv'


def get_python_executable():
    """Get the correct Python executable, preferring venv if available."""
    # Check if we're already in a virtual environment
    if sys.prefix != sys.base_prefix:
        return sys.executable

    # Check for .venv in project root
    if VENV_DIR.exists():
        if platform.system() == 'Windows':
            venv_python = VENV_DIR / 'Scripts' / 'python.exe'
        else:
            venv_python = VENV_DIR / 'bin' / 'python'

        if venv_python.exists():
            return str(venv_python)

    # Fall back to current Python
    return sys.executable


PYTHON_EXE = get_python_executable()


def detect_platform():
    """Detect current platform."""
    system = platform.system().lower()
    if system == 'darwin':
        return 'macos'
    elif system == 'windows':
        return 'windows'
    else:
        return 'linux'


def clean_build():
    """Remove build artifacts."""
    print("Cleaning build directories...")
    for d in [BUILD_DIR, DIST_DIR / 'Luister', DIST_DIR / 'Luister.app']:
        if d.exists():
            shutil.rmtree(d)
            print(f"  Removed {d}")


def run_command(cmd, cwd=None):
    """Run a command and print output."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=False)
    if result.returncode != 0:
        print(f"Command failed with code {result.returncode}")
        sys.exit(1)


def build_pyinstaller():
    """Build with PyInstaller."""
    print("\n=== Building with PyInstaller ===")
    print(f"Using Python: {PYTHON_EXE}")
    spec_file = SCRIPT_DIR / 'luister.spec'

    if not spec_file.exists():
        print(f"Error: Spec file not found: {spec_file}")
        sys.exit(1)

    cmd = [
        PYTHON_EXE, '-m', 'PyInstaller',
        '--clean',
        '--noconfirm',
        str(spec_file),
    ]
    run_command(cmd, cwd=PROJECT_ROOT)


def create_macos_dmg():
    """Create DMG for macOS."""
    print("\n=== Creating macOS DMG ===")

    app_path = DIST_DIR / 'Luister.app'
    if not app_path.exists():
        print(f"Error: App bundle not found: {app_path}")
        return False

    dmg_path = DIST_DIR / 'Luister.dmg'

    # Remove existing DMG
    if dmg_path.exists():
        dmg_path.unlink()

    # Create DMG using hdiutil
    cmd = [
        'hdiutil', 'create',
        '-volname', 'Luister',
        '-srcfolder', str(app_path),
        '-ov',
        '-format', 'UDZO',
        str(dmg_path),
    ]

    try:
        run_command(cmd)
        print(f"DMG created: {dmg_path}")
        return True
    except Exception as e:
        print(f"Error creating DMG: {e}")
        return False


def create_windows_installer():
    """Create Windows installer using NSIS."""
    print("\n=== Creating Windows Installer ===")

    nsis_script = SCRIPT_DIR / 'windows' / 'installer.nsi'
    if not nsis_script.exists():
        print(f"NSIS script not found: {nsis_script}")
        print("Skipping Windows installer creation.")
        return False

    # Check if NSIS is installed
    makensis = shutil.which('makensis')
    if not makensis:
        # Try common Windows paths
        for path in [
            r'C:\Program Files (x86)\NSIS\makensis.exe',
            r'C:\Program Files\NSIS\makensis.exe',
        ]:
            if Path(path).exists():
                makensis = path
                break

    if not makensis:
        print("NSIS not found. Please install NSIS to create Windows installer.")
        return False

    cmd = [makensis, str(nsis_script)]
    try:
        run_command(cmd)
        return True
    except Exception as e:
        print(f"Error creating Windows installer: {e}")
        return False


def create_linux_appimage():
    """Create Linux AppImage."""
    print("\n=== Creating Linux AppImage ===")

    app_dir = DIST_DIR / 'luister'
    if not app_dir.exists():
        print(f"Error: Build directory not found: {app_dir}")
        return False

    # Check for appimagetool
    appimagetool = shutil.which('appimagetool')
    if not appimagetool:
        print("appimagetool not found. Downloading...")
        # Download appimagetool
        import urllib.request
        tool_url = 'https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage'
        tool_path = SCRIPT_DIR / 'appimagetool'
        try:
            urllib.request.urlretrieve(tool_url, tool_path)
            tool_path.chmod(0o755)
            appimagetool = str(tool_path)
        except Exception as e:
            print(f"Failed to download appimagetool: {e}")
            return False

    # Create AppDir structure
    appdir = DIST_DIR / 'Luister.AppDir'
    if appdir.exists():
        shutil.rmtree(appdir)

    appdir.mkdir(parents=True)
    (appdir / 'usr' / 'bin').mkdir(parents=True)
    (appdir / 'usr' / 'share' / 'applications').mkdir(parents=True)
    (appdir / 'usr' / 'share' / 'icons' / 'hicolor' / '256x256' / 'apps').mkdir(parents=True)

    # Copy application
    shutil.copytree(app_dir, appdir / 'usr' / 'bin' / 'luister', dirs_exist_ok=True)

    # Create AppRun script
    apprun = appdir / 'AppRun'
    apprun.write_text('''#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
export PATH="${HERE}/usr/bin/luister:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/bin/luister:${LD_LIBRARY_PATH}"
exec "${HERE}/usr/bin/luister/luister" "$@"
''')
    apprun.chmod(0o755)

    # Create desktop file
    desktop = appdir / 'luister.desktop'
    desktop.write_text('''[Desktop Entry]
Type=Application
Name=Luister
Comment=Music player with visualization and lyrics
Exec=luister
Icon=luister
Categories=Audio;Music;Player;
MimeType=audio/mpeg;audio/mp3;audio/ogg;audio/flac;audio/wav;
Terminal=false
''')
    shutil.copy(desktop, appdir / 'usr' / 'share' / 'applications' / 'luister.desktop')

    # Copy icon
    icon_src = SCRIPT_DIR / 'icons' / 'luister.png'
    if icon_src.exists():
        shutil.copy(icon_src, appdir / 'luister.png')
        shutil.copy(icon_src, appdir / 'usr' / 'share' / 'icons' / 'hicolor' / '256x256' / 'apps' / 'luister.png')
    else:
        # Create placeholder icon
        (appdir / 'luister.png').touch()

    # Create AppImage
    output = DIST_DIR / 'Luister-x86_64.AppImage'
    cmd = [appimagetool, str(appdir), str(output)]

    try:
        # Set ARCH for appimagetool
        env = os.environ.copy()
        env['ARCH'] = 'x86_64'
        subprocess.run(cmd, env=env, check=True)
        print(f"AppImage created: {output}")
        return True
    except Exception as e:
        print(f"Error creating AppImage: {e}")
        return False


def create_linux_deb():
    """Create Debian package."""
    print("\n=== Creating Debian Package ===")

    app_dir = DIST_DIR / 'luister'
    if not app_dir.exists():
        print(f"Error: Build directory not found: {app_dir}")
        return False

    # Check for dpkg-deb
    dpkg_deb = shutil.which('dpkg-deb')
    if not dpkg_deb:
        print("dpkg-deb not found. Skipping .deb creation.")
        return False

    # Create package structure
    pkg_dir = DIST_DIR / 'luister_0.1.0_amd64'
    if pkg_dir.exists():
        shutil.rmtree(pkg_dir)

    (pkg_dir / 'DEBIAN').mkdir(parents=True)
    (pkg_dir / 'usr' / 'bin').mkdir(parents=True)
    (pkg_dir / 'usr' / 'share' / 'applications').mkdir(parents=True)
    (pkg_dir / 'usr' / 'share' / 'icons' / 'hicolor' / '256x256' / 'apps').mkdir(parents=True)
    (pkg_dir / 'opt' / 'luister').mkdir(parents=True)

    # Copy application
    shutil.copytree(app_dir, pkg_dir / 'opt' / 'luister' / 'bin', dirs_exist_ok=True)

    # Create symlink script
    (pkg_dir / 'usr' / 'bin' / 'luister').write_text('''#!/bin/bash
exec /opt/luister/bin/luister "$@"
''')
    (pkg_dir / 'usr' / 'bin' / 'luister').chmod(0o755)

    # Create control file
    (pkg_dir / 'DEBIAN' / 'control').write_text('''Package: luister
Version: 0.1.0
Section: sound
Priority: optional
Architecture: amd64
Depends: libgl1, libxcb1, libxkbcommon0, libfontconfig1
Maintainer: Yilmaz Mustafa <ymus@tuta.io>
Description: Music player with visualization and lyrics
 Luister is a feature-rich music player built with PyQt6,
 featuring audio visualization, lyrics transcription via Whisper,
 and YouTube downloading capabilities.
Homepage: https://github.com/ymus/luister
''')

    # Create desktop file
    (pkg_dir / 'usr' / 'share' / 'applications' / 'luister.desktop').write_text('''[Desktop Entry]
Type=Application
Name=Luister
Comment=Music player with visualization and lyrics
Exec=/opt/luister/bin/luister
Icon=luister
Categories=Audio;Music;Player;
MimeType=audio/mpeg;audio/mp3;audio/ogg;audio/flac;audio/wav;
Terminal=false
''')

    # Copy icon
    icon_src = SCRIPT_DIR / 'icons' / 'luister.png'
    if icon_src.exists():
        shutil.copy(icon_src, pkg_dir / 'usr' / 'share' / 'icons' / 'hicolor' / '256x256' / 'apps' / 'luister.png')

    # Build package
    output = DIST_DIR / 'luister_0.1.0_amd64.deb'
    cmd = [dpkg_deb, '--build', str(pkg_dir), str(output)]

    try:
        run_command(cmd)
        print(f"Debian package created: {output}")
        return True
    except Exception as e:
        print(f"Error creating Debian package: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Build Luister for desktop platforms')
    parser.add_argument('--platform', choices=['auto', 'windows', 'macos', 'linux'],
                        default='auto', help='Target platform')
    parser.add_argument('--clean', action='store_true', help='Clean before building')
    parser.add_argument('--dmg', action='store_true', help='Create DMG (macOS)')
    parser.add_argument('--installer', action='store_true', help='Create installer')
    parser.add_argument('--appimage', action='store_true', help='Create AppImage (Linux)')
    parser.add_argument('--deb', action='store_true', help='Create .deb package (Linux)')

    args = parser.parse_args()

    # Detect or use specified platform
    target_platform = args.platform if args.platform != 'auto' else detect_platform()
    print(f"Building for platform: {target_platform}")

    # Clean if requested
    if args.clean:
        clean_build()

    # Build with PyInstaller
    build_pyinstaller()

    # Platform-specific post-processing
    if target_platform == 'macos':
        if args.dmg:
            create_macos_dmg()

    elif target_platform == 'windows':
        if args.installer:
            create_windows_installer()

    elif target_platform == 'linux':
        if args.appimage:
            create_linux_appimage()
        if args.deb:
            create_linux_deb()

    print("\n=== Build Complete ===")
    print(f"Output directory: {DIST_DIR}")


if __name__ == '__main__':
    main()
