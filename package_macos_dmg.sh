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

# Apply a local ad-hoc signature after all bundled files are present.  This
# does not require an Apple Developer account and lets the user approve the
# app through Privacy & Security -> Open Anyway when Gatekeeper prompts.
codesign --deep --force --verbose --sign - "$DMG_ROOT/Achieve3000Launcher.app"
codesign --verify --deep --strict --verbose=2 "$DMG_ROOT/Achieve3000Launcher.app"

hdiutil create \
  -volname "Achieve3000" \
  -srcfolder "$DMG_ROOT" \
  -ov \
  -format UDZO \
  "$DMG_OUTPUT"

echo "Created drag-to-Applications DMG: $DMG_OUTPUT"
