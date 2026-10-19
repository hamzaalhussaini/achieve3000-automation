#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

APP_SOURCE="dist/Achieve3000Launcher.app"
DMG_ROOT="dmg-root"
DMG_OUTPUT="Achieve3000-macOS.dmg"

rm -rf "$DMG_ROOT" "$DMG_OUTPUT"
mkdir -p "$DMG_ROOT"

# Copy the app bundle preserving macOS metadata
ditto "$APP_SOURCE" "$DMG_ROOT/Achieve3000Launcher.app"
ln -s /Applications "$DMG_ROOT/Applications"

APP_PATH="$DMG_ROOT/Achieve3000Launcher.app"

# Strip quarantine / extended attributes from build environment
xattr -cr "$APP_PATH" || true

# Apply local ad-hoc code signature structure (helps Gatekeeper accept "Open Anyway")
echo "Applying ad-hoc code signature..."
codesign --force --verbose --sign - "$APP_PATH/Contents/MacOS/achieve3000_automation" || true
codesign --force --verbose --sign - "$APP_PATH/Contents/MacOS/Achieve3000Launcher" || true
codesign --force --verbose --sign - "$APP_PATH" || true

# Create a 1-click helper script to unquarantine the app for users encountering "App is damaged"
cat << 'EOF' > "$DMG_ROOT/Fix Damaged App.command"
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "--------------------------------------------------------"
echo " Fixing macOS Gatekeeper Quarantine for Achieve3000... "
echo "--------------------------------------------------------"

if [ -d "/Applications/Achieve3000Launcher.app" ]; then
    xattr -cr "/Applications/Achieve3000Launcher.app"
    echo "[SUCCESS] Removed macOS quarantine flag."
    echo "Opening Achieve3000 Launcher..."
    open "/Applications/Achieve3000Launcher.app"
else
    echo "[!] Please drag Achieve3000Launcher into your Applications folder first,"
    echo "    then double-click this helper again."
fi
echo "You can close this window."
EOF
chmod +x "$DMG_ROOT/Fix Damaged App.command"

# Package into drag-and-drop DMG
hdiutil create \
  -volname "Achieve3000" \
  -srcfolder "$DMG_ROOT" \
  -ov \
  -format UDZO \
  "$DMG_OUTPUT"

echo "Created drag-to-Applications DMG: $DMG_OUTPUT"
