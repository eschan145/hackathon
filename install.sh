#!/bin/bash
set -e

echo "🚀 Installing Hackathon Assistant on Linux"
echo ""

# Check if running on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo "❌ This script is for Linux only"
    exit 1
fi

# Check for Python 3
echo "📦 Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed"
    echo "Install with: sudo apt-get install python3 python3-pip python3-venv"
    exit 1
fi
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "✓ Python $PYTHON_VERSION found"

# Check for Node.js
echo "📦 Checking Node.js installation..."
if ! command -v node &> /dev/null; then
    echo "⚠️  Node.js is not installed"
    echo "Installing Node.js 20.x..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
else
    NODE_VERSION=$(node -v)
    echo "✓ Node.js $NODE_VERSION found"
fi

# Check for npm
echo "📦 Checking npm installation..."
if ! command -v npm &> /dev/null; then
    echo "❌ npm is not installed"
    exit 1
fi
NPM_VERSION=$(npm -v)
echo "✓ npm $NPM_VERSION found"

# Check for the vision engine's system tools (window management + OCR)
echo ""
echo "📦 Checking system tools (wmctrl, xdotool, tesseract-ocr)..."
MISSING_PKGS=""
for pkg_bin in "wmctrl:wmctrl" "xdotool:xdotool" "tesseract:tesseract-ocr"; do
    bin_name="${pkg_bin%%:*}"
    pkg_name="${pkg_bin##*:}"
    if ! command -v "$bin_name" &> /dev/null; then
        MISSING_PKGS="$MISSING_PKGS $pkg_name"
    fi
done
if [ -n "$MISSING_PKGS" ]; then
    echo "Installing:$MISSING_PKGS"
    sudo apt-get install -y $MISSING_PKGS
else
    echo "✓ wmctrl, xdotool, tesseract-ocr already installed"
fi

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "📁 Setting up Python environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Created Python virtual environment"
else
    echo "✓ Python virtual environment already exists"
fi

# Activate venv
source venv/bin/activate
echo "✓ Activated virtual environment"

echo ""
echo "📚 Installing Python dependencies..."
pip install --upgrade pip setuptools wheel > /dev/null 2>&1
pip install -r requirements.txt
echo "✓ Python dependencies installed"

echo ""
echo "📁 Setting up Node.js frontend..."
cd frontend
npm install
echo "✓ Node.js dependencies installed"

echo ""
echo "✅ Installation complete!"
echo ""
echo "To run the app, use:"
echo "  ./run.sh"
echo ""
