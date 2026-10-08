#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

APP_SOURCE="dist/Achieve3000Launcher.app"
DMG_ROOT="dmg-root"
DMG_OUTPUT="Achieve3000-macOS.dmg"

rm -rf "$DMG_ROOT" "$DMG_OUTPUT"
mkdir -p "$DMG_ROOT"

# Build the familiar drag-to-Applications layout.  ditto preserves the
# bundle's macOS metadata and symlinks more reliably than a plain cp.
ditto "$APP_SOURCE" "$DMG_ROOT/Achieve3000Launcher.app"
ln -s /Applications "$DMG_ROOT/Applications"

# Apply local ad-hoc signatures after all bundled files are present.  The
# Playwright browser bundle contains a .links directory that is data, not
# code, so recursive --deep signing rejects it as an unsuitable component.
# Sign the two actual Mach-O executables, then seal the app bundle itself.
# This needs no Apple Developer account; Gatekeeper can still be approved via
# Privacy & Security -> Open Anyway.
APP_PATH="$DMG_ROOT/Achieve3000Launcher.app"
codesign --force --verbose --sign - "$APP_PATH/Contents/MacOS/Achieve3000Launcher"
codesign --force --verbose --sign - "$APP_PATH/Contents/MacOS/achieve3000_automation"
codesign --force --verbose --sign - "$APP_PATH"
codesign --verify --verbose=2 "$APP_PATH"

hdiutil create \
  -volname "Achieve3000" \
  -srcfolder "$DMG_ROOT" \
  -ov \
  -format UDZO \
  "$DMG_OUTPUT"

echo "Created drag-to-Applications DMG: $DMG_OUTPUT"
