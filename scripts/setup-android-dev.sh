#!/bin/bash
# Luister Android Development Setup Script
# Sets up the build environment for Android APK generation using Buildozer

set -e

echo "=== Luister Android Development Setup ==="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Python version
check_python() {
    if command -v python3 &> /dev/null; then
        python_version=$(python3 --version 2>&1 | cut -d' ' -f2)
        major=$(echo "$python_version" | cut -d'.' -f1)
        minor=$(echo "$python_version" | cut -d'.' -f2)

        if [[ "$major" -eq 3 ]] && [[ "$minor" -ge 9 ]]; then
            echo -e "${GREEN}[OK]${NC} Python $python_version found"
        else
            echo -e "${YELLOW}[WARN]${NC} Python 3.9+ recommended, found $python_version"
        fi
    else
        echo -e "${RED}[ERROR]${NC} Python 3 not found. Please install Python 3.9+"
        exit 1
    fi
}

# Check Java version
check_java() {
    if command -v java &> /dev/null; then
        java_version=$(java -version 2>&1 | head -1 | cut -d'"' -f2)
        echo -e "${GREEN}[OK]${NC} Java $java_version found"
    else
        echo -e "${YELLOW}[WARN]${NC} Java not found. Will attempt to install."
    fi
}

# Install macOS dependencies
install_macos_deps() {
    echo ""
    echo "Installing macOS dependencies..."

    # Check for Homebrew
    if ! command -v brew &> /dev/null; then
        echo -e "${YELLOW}[INFO]${NC} Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi

    echo "Installing build tools..."
    brew install autoconf automake libtool pkg-config || true
    brew install coreutils || true

    # Install Java if not present
    if ! command -v java &> /dev/null; then
        echo "Installing OpenJDK 17..."
        brew install openjdk@17
        # Add to PATH hint
        echo -e "${YELLOW}[INFO]${NC} Add to your shell profile:"
        echo "  export PATH=\"\$(brew --prefix openjdk@17)/bin:\$PATH\""
    fi

    echo -e "${GREEN}[OK]${NC} macOS dependencies installed"
}

# Install Linux dependencies
install_linux_deps() {
    echo ""
    echo "Installing Linux dependencies..."

    if command -v apt-get &> /dev/null; then
        sudo apt-get update
        sudo apt-get install -y \
            build-essential \
            git \
            zip \
            unzip \
            openjdk-17-jdk \
            autoconf \
            libtool \
            pkg-config \
            zlib1g-dev \
            libncurses5-dev \
            libncursesw5-dev \
            cmake \
            libffi-dev \
            libssl-dev \
            automake \
            python3-pip \
            python3-venv \
            ccache
        echo -e "${GREEN}[OK]${NC} Linux dependencies installed (apt)"
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y \
            @development-tools \
            git \
            zip \
            unzip \
            java-17-openjdk-devel \
            autoconf \
            libtool \
            pkgconfig \
            zlib-devel \
            ncurses-devel \
            cmake \
            libffi-devel \
            openssl-devel \
            automake \
            python3-pip \
            ccache
        echo -e "${GREEN}[OK]${NC} Linux dependencies installed (dnf)"
    elif command -v pacman &> /dev/null; then
        sudo pacman -Sy --noconfirm \
            base-devel \
            git \
            zip \
            unzip \
            jdk17-openjdk \
            autoconf \
            libtool \
            pkgconf \
            zlib \
            ncurses \
            cmake \
            libffi \
            openssl \
            automake \
            python-pip \
            ccache
        echo -e "${GREEN}[OK]${NC} Linux dependencies installed (pacman)"
    else
        echo -e "${RED}[ERROR]${NC} Unsupported Linux distribution. Install dependencies manually."
        exit 1
    fi
}

# Install Python dependencies
install_python_deps() {
    echo ""
    echo "Installing Python build dependencies..."

    pip3 install --upgrade pip
    pip3 install --upgrade buildozer cython virtualenv

    echo -e "${GREEN}[OK]${NC} Python dependencies installed"
}

# Set up Android SDK/NDK environment hints
setup_android_env() {
    echo ""
    echo "=== Android SDK/NDK Configuration ==="
    echo ""
    echo "Buildozer will automatically download Android SDK and NDK on first build."
    echo "This can take 15-30 minutes and requires ~5GB of disk space."
    echo ""

    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS - check if Android Studio is installed
        if [[ -d "/Applications/Android Studio.app" ]]; then
            ANDROID_HOME="$HOME/Library/Android/sdk"
            echo -e "${GREEN}[OK]${NC} Android Studio detected"
            echo "  ANDROID_HOME=$ANDROID_HOME"
        else
            echo -e "${YELLOW}[INFO]${NC} Android Studio not found. Buildozer will download SDK."
        fi

        echo ""
        echo "Optional: To use existing Android SDK, add to ~/.zshrc or ~/.bashrc:"
        echo "  export ANDROID_HOME=\$HOME/Library/Android/sdk"
        echo "  export ANDROID_NDK_HOME=\$HOME/.buildozer/android/platform/android-ndk-*"
    else
        # Linux
        if [[ -d "$HOME/Android/Sdk" ]]; then
            ANDROID_HOME="$HOME/Android/Sdk"
            echo -e "${GREEN}[OK]${NC} Android SDK detected at $ANDROID_HOME"
        else
            echo -e "${YELLOW}[INFO]${NC} Android SDK not found. Buildozer will download SDK."
        fi

        echo ""
        echo "Optional: To use existing Android SDK, add to ~/.bashrc:"
        echo "  export ANDROID_HOME=\$HOME/Android/Sdk"
        echo "  export ANDROID_NDK_HOME=\$HOME/.buildozer/android/platform/android-ndk-*"
    fi
}

# Initialize mobile project
init_mobile_project() {
    echo ""
    echo "Checking mobile project structure..."

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
    MOBILE_DIR="$PROJECT_ROOT/mobile"

    if [[ ! -d "$MOBILE_DIR" ]]; then
        echo "Creating mobile directory..."
        mkdir -p "$MOBILE_DIR"
    fi

    if [[ ! -f "$MOBILE_DIR/buildozer.spec" ]]; then
        echo -e "${YELLOW}[INFO]${NC} buildozer.spec not found. It should be created by the project."
    else
        echo -e "${GREEN}[OK]${NC} buildozer.spec found"
    fi

    if [[ ! -f "$MOBILE_DIR/main.py" ]]; then
        echo -e "${YELLOW}[INFO]${NC} main.py not found. It should be created by the project."
    else
        echo -e "${GREEN}[OK]${NC} main.py found"
    fi
}

# Print build instructions
print_instructions() {
    echo ""
    echo "=== Setup Complete ==="
    echo ""
    echo "To build the Android APK:"
    echo ""
    echo "  cd mobile"
    echo "  buildozer android debug     # Debug build"
    echo "  buildozer android release   # Release build (requires signing)"
    echo ""
    echo "Or use Makefile targets:"
    echo ""
    echo "  make android-debug          # Build debug APK"
    echo "  make android-release        # Build release APK"
    echo "  make android-deploy         # Deploy to connected device"
    echo ""
    echo "First build will download Android SDK/NDK (~5GB, 15-30 min)."
    echo "Subsequent builds will be much faster."
    echo ""
    echo "To test on device:"
    echo "  1. Enable USB debugging on your Android device"
    echo "  2. Connect device via USB"
    echo "  3. Run: make android-deploy"
    echo ""
    echo "To test on emulator:"
    echo "  1. Install Android Studio"
    echo "  2. Create an AVD (Android Virtual Device)"
    echo "  3. Start the emulator"
    echo "  4. Run: make android-deploy"
}

# Main execution
main() {
    check_python
    check_java

    if [[ "$OSTYPE" == "darwin"* ]]; then
        install_macos_deps
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        install_linux_deps
    else
        echo -e "${YELLOW}[WARN]${NC} Unsupported OS: $OSTYPE"
        echo "Attempting to install Python dependencies only..."
    fi

    install_python_deps
    setup_android_env
    init_mobile_project
    print_instructions
}

main "$@"
