#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

python3 -m pip install -r requirements.txt pyinstaller pillow

# Ensure ICNS icon is ready
if [ ! -f "achieve3000.icns" ]; then
    python3 -c "
import os
from PIL import Image
if os.path.exists('achieve3000.png'):
    Image.open('achieve3000.png').save('achieve3000.icns', format='ICNS')
elif os.path.exists('achieve3000.ico'):
    Image.open('achieve3000.ico').save('achieve3000.icns', format='ICNS')
" || true
fi

export PLAYWRIGHT_BROWSERS_PATH="$ROOT_DIR/playwright-browsers"
python3 -m playwright install chromium

rm -rf build dist

# Build automation worker binary
python3 -m PyInstaller --noconfirm --clean --onefile \
  --name achieve3000_automation achieve3000_automation.py

# Build launcher app bundle using spec file
python3 -m PyInstaller --noconfirm --clean Achieve3000Launcher.spec

APP_MACOS_DIR="dist/Achieve3000Launcher.app/Contents/MacOS"
APP_RESOURCES_DIR="dist/Achieve3000Launcher.app/Contents/Resources"

mkdir -p "$APP_RESOURCES_DIR"
cp "dist/achieve3000_automation" "$APP_MACOS_DIR/achieve3000_automation"
chmod +x "$APP_MACOS_DIR/achieve3000_automation"

# Place Playwright browsers in Contents/Resources
cp -R "$ROOT_DIR/playwright-browsers" "$APP_RESOURCES_DIR/playwright-browsers"

# Copy branding assets and mac launcher into the bundle
if [ -f "achieve3000.png" ]; then
    cp "achieve3000.png" "$APP_RESOURCES_DIR/achieve3000.png"
    cp "achieve3000.png" "$APP_MACOS_DIR/achieve3000.png"
fi
if [ -f "achieve3000.icns" ]; then
    cp "achieve3000.icns" "$APP_RESOURCES_DIR/achieve3000.icns"
fi
if [ -f "mac_launcher.py" ]; then
    cp "mac_launcher.py" "$APP_MACOS_DIR/mac_launcher.py"
fi

echo "Created macOS app bundle: dist/Achieve3000Launcher.app"
