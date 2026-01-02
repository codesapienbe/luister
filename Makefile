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

.PHONY: all clean install dev build build-mac build-windows build-linux \
        dmg appimage deb installer run test lint help \
        android android-setup android-debug android-release android-deploy android-run android-logcat android-clean \
        ios ios-setup ios-build ios-xcode ios-clean

# Default target
all: help

help:
	@echo "Luister Build System (using uv)"
	@echo ""
	@echo "Development:"
	@echo "  make install    - Install package in development mode"
	@echo "  make dev        - Install with development dependencies"
	@echo "  make run        - Run the desktop application"
	@echo "  make test       - Run tests"
	@echo "  make lint       - Run linters"
	@echo ""
	@echo "Desktop Building:"
	@echo "  make build      - Build standalone executable for current platform"
	@echo "  make build-mac  - Build macOS app bundle"
	@echo "  make build-win  - Build Windows executable"
	@echo "  make build-linux - Build Linux executable"
	@echo ""
	@echo "Desktop Packaging:"
	@echo "  make dmg        - Create macOS DMG (requires macOS)"
	@echo "  make appimage   - Create Linux AppImage (requires Linux)"
	@echo "  make deb        - Create Debian package (requires Linux)"
	@echo "  make installer  - Create Windows installer (requires Windows + NSIS)"
	@echo ""
	@echo "Android (Kivy/Buildozer):"
	@echo "  make android         - Build debug APK and deploy (quick dev cycle)"
	@echo "  make android-setup   - Install Android build dependencies"
	@echo "  make android-debug   - Build debug APK only"
	@echo "  make android-release - Build release APK"
	@echo "  make android-deploy  - Deploy to connected device"
	@echo "  make android-run     - Build, deploy, and show logs"
	@echo "  make android-logcat  - Show device logs"
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
ifdef UV
	uv pip install -e .
else
	$(PYTHON) -m pip install -e .
endif

dev:
ifdef UV
	uv pip install -e ".[dev]"
else
	$(PYTHON) -m pip install -e ".[dev]"
endif

run:
	$(PYTHON_CMD) -m luister

test:
	$(PYTHON_CMD) -m pytest tests/ -v

lint:
	$(PYTHON_CMD) -m flake8 src/
	$(PYTHON_CMD) -m black --check src/

# Build targets
build:
	$(PYTHON_CMD) packaging/build.py --clean

build-mac: build
	@echo "macOS build complete"

build-win: build
	@echo "Windows build complete"

build-linux: build
	@echo "Linux build complete"

# Packaging targets
dmg: build
	$(PYTHON_CMD) packaging/build.py --dmg

appimage: build
	$(PYTHON_CMD) packaging/build.py --appimage

deb: build
	$(PYTHON_CMD) packaging/build.py --deb

installer: build
	$(PYTHON_CMD) packaging/build.py --installer

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

# Buildozer command using uv
ifdef UV
    BUILDOZER := cd mobile && uv run buildozer
else
    BUILDOZER := cd mobile && $(PYTHON) -m buildozer
endif

android-setup:
	@echo "Setting up Android development environment..."
ifdef UV
	uv add buildozer cython
else
	$(PYTHON) -m pip install buildozer cython
endif
	@echo "JAVA_HOME: $$JAVA_HOME"

# Quick dev cycle: build + deploy
android: android-debug android-deploy
	@echo "Done! App deployed to device."

android-debug:
	@echo "Building Android debug APK..."
	$(BUILDOZER) android debug
	@ls -la mobile/bin/*.apk 2>/dev/null || echo "No APK found"

android-release:
	@echo "Building Android release APK..."
	$(BUILDOZER) android release
	@ls -la mobile/bin/*.apk 2>/dev/null || echo "No APK found"

android-deploy:
	$(BUILDOZER) android deploy run

android-run: android-debug
	$(BUILDOZER) android deploy run logcat

android-logcat:
	@echo "Showing Android logcat (Ctrl+C to stop)..."
	adb logcat | grep -iE "(python|kivy|luister)"

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
ifdef UV
	cd $(IOS_DIR) && uv run toolchain build python3 kivy numpy requests
	cd $(IOS_DIR) && uv run toolchain create Luister ../mobile
else
	cd $(IOS_DIR) && $(PYTHON) -m toolchain build python3 kivy numpy requests
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
