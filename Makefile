# Luister Build Makefile
# Cross-platform build targets for Luister music player

# Use uv for package management (preferred)
UV := $(shell command -v uv 2>/dev/null)

# Virtual environment paths
VENV := .venv
ifeq ($(OS),Windows_NT)
    PYTHON := $(VENV)/Scripts/python.exe
else
    PYTHON := $(VENV)/bin/python
endif

# Use uv run if available, otherwise fall back to venv python
ifdef UV
    RUN := uv run
    PYTHON_CMD := uv run python
else
    RUN := $(PYTHON)
    PYTHON_CMD := $(PYTHON)
endif

PROJECT_NAME := luister
VERSION := 0.1.0
PLATFORM ?= auto

.PHONY: all clean install dev coverage bundle bundle-macos bundle-windows bundle-linux \
        dmg appimage deb installer run test lint help \
        android android-setup android-debug android-release android-deploy android-install android-run android-logcat android-uninstall android-clean \
        ios ios-setup ios-build ios-xcode ios-clean

# Default target
all: help

help:
	@echo "Luister Build System (using uv)"
	@echo ""
	@echo "Development:"
	@echo "  make install    - Install/sync dependencies with uv"
	@echo "  make dev        - Install with development dependencies"
	@echo "  make run        - Run the desktop application (uv run luister)"
	@echo "  make test       - Run tests"
	@echo "  make lint       - Run linters"
	@echo ""
	@echo "Desktop Building:"
	@echo "  make bundle      - Build executable for PLATFORM=auto|macos|windows|linux"
	@echo "  make bundle-macos - Build macOS executable"
	@echo "  make bundle-windows - Build Windows executable"
	@echo "  make bundle-linux - Build Linux executable"
	@echo ""
	@echo "Desktop Packaging:"
	@echo "  make dmg        - Create macOS DMG (requires macOS)"
	@echo "  make appimage   - Create Linux AppImage (requires Linux)"
	@echo "  make deb        - Create Debian package (requires Linux)"
	@echo "  make installer  - Create Windows installer (requires Windows + NSIS)"
	@echo ""
	@echo "Android (Kivy/Buildozer):"
	@echo "  make android         - Build debug APK and install (TARGET=usb|wifi, or DEVICE_ID=<serial>)"
	@echo "  make bundle PLATFORM=android - Same as android-debug"
	@echo "  make android-setup   - Install Android build dependencies"
	@echo "  make android-debug   - Build debug APK only"
	@echo "  make android-release - Build release APK"
	@echo "  make android-deploy  - Build + install on TARGET=usb|wifi device (default usb)"
	@echo "  make android-install - Install the last built APK without rebuilding"
	@echo "  make android-run     - Build, install, launch, and follow logs"
	@echo "  make android-logcat  - Launch app and follow its logs"
	@echo "  make android-uninstall - Remove the app from the device"
	@echo "  make android-clean   - Clean Android build artifacts"
	@echo ""
	@echo "iOS (Kivy-iOS, macOS only):"
	@echo "  make ios-setup  - Install iOS build dependencies"
	@echo "  make ios-build  - Build iOS toolchain and create Xcode project"
	@echo "  make ios-xcode  - Open project in Xcode"
	@echo "  make ios-clean  - Clean iOS build artifacts"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean      - Remove build artifacts"
	@echo "  make icons      - Generate icon files from SVG"

# Development targets
install:
	uv sync

dev:
ifdef UV
	uv pip install -e ".[dev]"
else
	$(PYTHON) -m pip install -e ".[dev]"
endif

run:
	uv run luister

test:
	$(PYTHON_CMD) -m pytest tests/ -v

# Full suite with line coverage for src/luister and mobile/ (headless Qt/Kivy).
coverage:
	QT_QPA_PLATFORM=offscreen $(PYTHON_CMD) -m pytest tests/ --cov --cov-report=term-missing

lint:
	$(PYTHON_CMD) -m flake8 src/
	$(PYTHON_CMD) -m black --check src/

# Build targets
# PLATFORM=android builds the debug APK instead (see android-* targets).
bundle:
ifeq ($(PLATFORM),android)
	$(MAKE) android-debug
else
	uv run python packaging/build.py --clean --platform $(PLATFORM)
endif

bundle-macos:
	$(MAKE) bundle PLATFORM=macos

bundle-windows:
	$(MAKE) bundle PLATFORM=windows

bundle-linux:
	$(MAKE) bundle PLATFORM=linux

# Packaging targets
dmg:
	uv run python packaging/build.py --clean --platform macos --dmg

appimage:
	uv run python packaging/build.py --clean --platform linux --appimage

deb:
	uv run python packaging/build.py --clean --platform linux --deb

installer:
	uv run python packaging/build.py --clean --platform windows --installer

# Icon generation (requires ImageMagick or Pillow)
icons:
	@echo "Generating icons..."
	@mkdir -p packaging/icons
	@if [ -f packaging/logo.svg ]; then \
		echo "Converting SVG to PNG..."; \
		convert packaging/logo.svg -resize 256x256 packaging/icons/luister.png; \
		convert packaging/logo.svg -resize 512x512 packaging/icons/luister-512.png; \
		echo "Creating ICO for Windows..."; \
		convert packaging/logo.svg -define icon:auto-resize=256,128,64,48,32,16 packaging/icons/luister.ico; \
		echo "Creating ICNS for macOS..."; \
		mkdir -p packaging/icons/luister.iconset; \
		convert packaging/logo.svg -resize 16x16 packaging/icons/luister.iconset/icon_16x16.png; \
		convert packaging/logo.svg -resize 32x32 packaging/icons/luister.iconset/icon_16x16@2x.png; \
		convert packaging/logo.svg -resize 32x32 packaging/icons/luister.iconset/icon_32x32.png; \
		convert packaging/logo.svg -resize 64x64 packaging/icons/luister.iconset/icon_32x32@2x.png; \
		convert packaging/logo.svg -resize 128x128 packaging/icons/luister.iconset/icon_128x128.png; \
		convert packaging/logo.svg -resize 256x256 packaging/icons/luister.iconset/icon_128x128@2x.png; \
		convert packaging/logo.svg -resize 256x256 packaging/icons/luister.iconset/icon_256x256.png; \
		convert packaging/logo.svg -resize 512x512 packaging/icons/luister.iconset/icon_256x256@2x.png; \
		convert packaging/logo.svg -resize 512x512 packaging/icons/luister.iconset/icon_512x512.png; \
		convert packaging/logo.svg -resize 1024x1024 packaging/icons/luister.iconset/icon_512x512@2x.png; \
		iconutil -c icns packaging/icons/luister.iconset -o packaging/icons/luister.icns 2>/dev/null || echo "iconutil not available (macOS only)"; \
		rm -rf packaging/icons/luister.iconset; \
	else \
		echo "No packaging/logo.svg found. Please add a logo."; \
	fi

# Cleanup
clean:
	rm -rf build/
	rm -rf dist/Luister*
	rm -rf dist/luister/
	rm -rf *.egg-info/
	rm -rf src/*.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true

# Wheel and source distribution
dist: clean
	$(PYTHON_CMD) -m build

upload: dist
	$(PYTHON_CMD) -m twine upload dist/*

# =============================================================================
# ANDROID BUILD TARGETS (Kivy/Buildozer)
# =============================================================================

# Where `make deploy` installs: usb | wifi. DEVICE_ID=<serial> bypasses the lookup.
TARGET ?= usb
ANDROID_PKG := be.codesapien.luister
ANDROID_APK_DIR := mobile/bin

# Buildozer/Gradle need JDK 17 (or 21); the machine default may be newer and breaks
# the build. Pick one from sdkman, then macOS java_home; otherwise leave JAVA_HOME alone.
JAVA17 := $(firstword $(shell ls -d $(HOME)/.sdkman/candidates/java/17* 2>/dev/null) $(shell /usr/libexec/java_home -v 17 2>/dev/null))
ifneq ($(JAVA17),)
export JAVA_HOME := $(JAVA17)
export PATH := $(JAVA17)/bin:$(PATH)
endif

# Run buildozer with the project venv's interpreter directly: `uv run buildozer` can
# resolve to a pipx-installed buildozer whose python has no pip, and re-syncs the project.
# The newest macOS SDK declares pipe2/dup3 (macOS 27+) and -Werror breaks the host-python build.
BUILDOZER := cd mobile && ac_cv_func_pipe2=no ac_cv_func_dup3=no VIRTUAL_ENV="$(abspath $(VENV))" PATH="$(abspath $(VENV))/bin:$$PATH" $(abspath $(PYTHON)) -m buildozer

# Resolve the adb serial for TARGET into $$serial (shell snippet, used by android-* targets).
#   usb  -> the one device whose `adb devices -l` line has a usb: field
#   wifi -> the one device connected over TCP (ip:port serial, or mDNS adb-*._adb-tls-connect)
define ADB_PICK_DEVICE
command -v adb >/dev/null || { echo "❌ adb not on PATH — add \$$ANDROID_HOME/platform-tools to it."; exit 2; }; \
serial="$(DEVICE_ID)"; \
if [ -z "$$serial" ]; then \
  case "$(TARGET)" in \
    usb)  list="$$(adb devices -l | awk '$$2 == "device" && / usb:/ { print $$1 }')";; \
    wifi) list="$$(adb devices -l | awk '$$2 == "device" && !/ usb:/ && ($$1 ~ /^[0-9.]+:[0-9]+$$/ || $$1 ~ /_adb-tls-connect/) { print $$1 }')";; \
    *) echo "❌ TARGET=$(TARGET) is not supported. Use TARGET=usb|wifi, or DEVICE_ID=<serial>."; exit 2;; \
  esac; \
  count="$$(printf '%s' "$$list" | grep -c . || true)"; \
  if [ "$$count" -eq 0 ]; then \
    echo "❌ no $(TARGET) device in 'adb devices -l'. Attached:"; \
    adb devices -l | tail -n +2 | sed '/^$$/d; s/^/  /'; \
    [ "$(TARGET)" = "wifi" ] && echo "   (pair/connect first: adb pair <ip:port>; adb connect <ip:port>)"; \
    exit 1; \
  fi; \
  if [ "$$count" -gt 1 ]; then \
    echo "❌ $$count $(TARGET) devices attached — pick one with DEVICE_ID=<serial>:"; printf '  %s\n' $$list; exit 1; \
  fi; \
  serial="$$list"; \
elif [ "$$(adb -s "$$serial" get-state 2>/dev/null)" != "device" ]; then \
  echo "❌ $$serial is not an attached adb device. 'adb devices -l' lists them."; exit 2; \
fi
endef

android-setup:
	@echo "Setting up Android development environment..."
ifdef UV
	uv add buildozer cython
else
	$(PYTHON) -m pip install buildozer cython
endif
	@echo "JAVA_HOME: $$JAVA_HOME"

# Quick dev cycle: pick the device first (fails fast), build, install.
#   make android                  -> debug APK to the USB device
#   make android TARGET=wifi      -> ... to the wireless-debugging device
android: android-deploy

android-debug:
	@echo "Building Android debug APK..."
	$(BUILDOZER) android debug
	@ls -la $(ANDROID_APK_DIR)/*.apk 2>/dev/null || echo "No APK found"

android-release:
	@echo "Building Android release APK (unsigned unless signing is configured)..."
	$(BUILDOZER) android release
	@ls -la $(ANDROID_APK_DIR)/*.apk 2>/dev/null || echo "No APK found"

# Device is resolved BEFORE the build so a missing phone fails in a second, not after
# a long build. Installs the newest debug APK; does not launch (see android-run).
android-deploy:
	@set -e; \
	$(ADB_PICK_DEVICE); \
	echo "▶ deploy → $$serial ($(TARGET))"; \
	$(MAKE) --no-print-directory android-debug; \
	apk="$$(ls -t $(ANDROID_APK_DIR)/*-debug.apk 2>/dev/null | head -1)"; \
	[ -n "$$apk" ] || { echo "❌ no debug APK in $(ANDROID_APK_DIR)"; exit 1; }; \
	adb -s "$$serial" install -r "$$apk"; \
	echo "✓ $$apk installed on $$serial (not launched)."

# Install the already-built APK without rebuilding.
android-install:
	@set -e; \
	$(ADB_PICK_DEVICE); \
	apk="$$(ls -t $(ANDROID_APK_DIR)/*-debug.apk 2>/dev/null | head -1)"; \
	[ -n "$$apk" ] || { echo "❌ no debug APK — run 'make android-debug' first."; exit 1; }; \
	adb -s "$$serial" install -r "$$apk"; \
	echo "✓ $$apk installed on $$serial."

# Build, install, launch and follow the app's logs.
android-run: android-deploy android-logcat
	@true

android-logcat:
	@set -e; \
	$(ADB_PICK_DEVICE); \
	adb -s "$$serial" shell monkey -p $(ANDROID_PKG) -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true; \
	echo "Showing logcat for $(ANDROID_PKG) on $$serial (Ctrl+C to stop)..."; \
	adb -s "$$serial" logcat -c; \
	adb -s "$$serial" logcat -v time python:V SDL:V SDLActivity:V AndroidRuntime:E '*:S'

android-uninstall:
	@set -e; \
	$(ADB_PICK_DEVICE); \
	adb -s "$$serial" uninstall $(ANDROID_PKG)

android-clean:
	@echo "Cleaning Android build artifacts..."
	rm -rf mobile/.buildozer
	rm -rf mobile/bin
	@echo "Android build artifacts cleaned"

# =============================================================================
# iOS BUILD TARGETS (Kivy-iOS, macOS only)
# =============================================================================

IOS_DIR := ios-build
IOS_PROJECT := $(IOS_DIR)/luister-ios

ios-setup:
	@echo "Setting up iOS development environment..."
	@if [ "$$(uname)" != "Darwin" ]; then \
		echo "Error: iOS builds require macOS"; \
		exit 1; \
	fi
	@echo "Installing kivy-ios toolchain..."
ifdef UV
	uv add kivy-ios
else
	$(PYTHON) -m pip install kivy-ios
endif
	@echo ""
	@echo "iOS setup complete. Next steps:"
	@echo "  1. Ensure Xcode is installed: xcode-select --install"
	@echo "  2. Run: make ios-build"

ios-build:
	@echo "Building iOS toolchain and creating Xcode project..."
	@if [ "$$(uname)" != "Darwin" ]; then \
		echo "Error: iOS builds require macOS"; \
		exit 1; \
	fi
	@mkdir -p $(IOS_DIR)
	@echo "Note: iOS build uses urllib instead of requests (no recipe available)"
ifdef UV
	cd $(IOS_DIR) && uv run toolchain build python3 kivy numpy
	cd $(IOS_DIR) && uv run toolchain create Luister ../mobile
else
	cd $(IOS_DIR) && $(PYTHON) -m toolchain build python3 kivy numpy
	cd $(IOS_DIR) && $(PYTHON) -m toolchain create Luister ../mobile
endif
	@echo ""
	@echo "iOS project created at: $(IOS_PROJECT)"
	@echo "Run 'make ios-xcode' to open in Xcode"

ios-xcode:
	@echo "Opening Xcode project..."
	@if [ -d "$(IOS_PROJECT)/luister.xcodeproj" ]; then \
		open $(IOS_PROJECT)/luister.xcodeproj; \
	else \
		echo "Error: Xcode project not found. Run 'make ios-build' first."; \
		exit 1; \
	fi

ios-clean:
	@echo "Cleaning iOS build artifacts..."
	rm -rf $(IOS_DIR)
	@echo "iOS build artifacts cleaned"
