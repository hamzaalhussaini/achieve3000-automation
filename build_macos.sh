#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

python3 -m pip install -r requirements.txt pyinstaller

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

# Place Playwright browsers in Contents/Resources to comply with Apple bundle structure
cp -R "$ROOT_DIR/playwright-browsers" "$APP_RESOURCES_DIR/playwright-browsers"

echo "Created macOS app bundle: dist/Achieve3000Launcher.app"
