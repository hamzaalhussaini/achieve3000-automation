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

hdiutil create \
  -volname "Achieve3000" \
  -srcfolder "$DMG_ROOT" \
  -ov \
  -format UDZO \
  "$DMG_OUTPUT"

echo "Created drag-to-Applications DMG: $DMG_OUTPUT"
