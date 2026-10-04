#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

python3 -m pip install -r requirements.txt pyinstaller

export PLAYWRIGHT_BROWSERS_PATH="$ROOT_DIR/playwright-browsers"
python3 -m playwright install chromium

rm -rf build dist

python3 -m PyInstaller --noconfirm --clean --onefile \
  --name achieve3000_automation achieve3000_automation.py
python3 -m PyInstaller --noconfirm --clean --onedir --windowed \
  --name Achieve3000Launcher launcher.py

APP_MACOS_DIR="dist/Achieve3000Launcher/Achieve3000Launcher.app/Contents/MacOS"
cp "dist/achieve3000_automation" "$APP_MACOS_DIR/achieve3000_automation"
cp -R "$ROOT_DIR/playwright-browsers" "$APP_MACOS_DIR/playwright-browsers"

echo "Created macOS app bundle: dist/Achieve3000Launcher/Achieve3000Launcher.app"
