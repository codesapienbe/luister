# Luister Build Makefile
# Cross-platform build targets for Luister music player

# Use virtual environment if available
VENV := .venv
ifeq ($(OS),Windows_NT)
    PYTHON := $(VENV)/Scripts/python.exe
    PIP := $(VENV)/Scripts/pip.exe
else
    PYTHON := $(VENV)/bin/python
    PIP := $(VENV)/bin/pip
endif

# Fallback if venv doesn't exist
ifeq (,$(wildcard $(PYTHON)))
    PYTHON := python3
    PIP := pip3
endif

PROJECT_NAME := luister
VERSION := 0.1.0

.PHONY: all clean install dev build build-mac build-windows build-linux \
        dmg appimage deb installer run test lint help \
        android-setup android-debug android-release android-deploy android-clean

# Default target
all: help

help:
	@echo "Luister Build System"
	@echo ""
	@echo "Development:"
	@echo "  make install    - Install package in development mode"
	@echo "  make dev        - Install with development dependencies"
	@echo "  make run        - Run the application"
	@echo "  make test       - Run tests"
	@echo "  make lint       - Run linters"
	@echo ""
	@echo "Building:"
	@echo "  make build      - Build standalone executable for current platform"
	@echo "  make build-mac  - Build macOS app bundle"
	@echo "  make build-win  - Build Windows executable"
	@echo "  make build-linux - Build Linux executable"
	@echo ""
	@echo "Packaging:"
	@echo "  make dmg        - Create macOS DMG (requires macOS)"
	@echo "  make appimage   - Create Linux AppImage (requires Linux)"
	@echo "  make deb        - Create Debian package (requires Linux)"
	@echo "  make installer  - Create Windows installer (requires Windows + NSIS)"
	@echo ""
	@echo "Android:"
	@echo "  make android-setup   - Install Android build dependencies"
	@echo "  make android-debug   - Build debug APK"
	@echo "  make android-release - Build release APK"
	@echo "  make android-deploy  - Deploy to connected device"
	@echo "  make android-clean   - Clean Android build artifacts"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean      - Remove build artifacts"
	@echo "  make icons      - Generate icon files from SVG"

# Development targets
install:
	$(PIP) install -e .

dev:
	$(PIP) install -e ".[dev]"

run:
	$(PYTHON) -m luister

test:
	$(PYTHON) -m pytest tests/ -v

lint:
	$(PYTHON) -m flake8 src/
	$(PYTHON) -m black --check src/

# Build targets
build:
	$(PYTHON) packaging/build.py --clean

build-mac: build
	@echo "macOS build complete"

build-win: build
	@echo "Windows build complete"

build-linux: build
	@echo "Linux build complete"

# Packaging targets
dmg: build
	$(PYTHON) packaging/build.py --dmg

appimage: build
	$(PYTHON) packaging/build.py --appimage

deb: build
	$(PYTHON) packaging/build.py --deb

installer: build
	$(PYTHON) packaging/build.py --installer

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
	$(PYTHON) -m build

upload: dist
	$(PYTHON) -m twine upload dist/*

# Android build targets
android-setup:
	@echo "Setting up Android development environment..."
	./scripts/setup-android-dev.sh

android-debug:
	@echo "Building Android debug APK..."
	cd mobile && buildozer android debug
	@echo ""
	@echo "APK location: mobile/bin/"
	@ls -la mobile/bin/*.apk 2>/dev/null || echo "No APK found"

android-release:
	@echo "Building Android release APK..."
	cd mobile && buildozer android release
	@echo ""
	@echo "APK location: mobile/bin/"
	@ls -la mobile/bin/*.apk 2>/dev/null || echo "No APK found"

android-deploy:
	@echo "Deploying to connected Android device..."
	cd mobile && buildozer android deploy run logcat

android-logcat:
	@echo "Showing Android logcat (Ctrl+C to stop)..."
	adb logcat | grep -i python

android-clean:
	@echo "Cleaning Android build artifacts..."
	rm -rf mobile/.buildozer
	rm -rf mobile/bin
	@echo "Android build artifacts cleaned"
