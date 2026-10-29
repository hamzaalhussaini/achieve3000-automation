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

# Set custom volume icon on the DMG root so the disk doesn't show generic/Python icon
if [ -f "achieve3000.icns" ]; then
    cp "achieve3000.icns" "$DMG_ROOT/.VolumeIcon.icns"
    SetFile -c icnC "$DMG_ROOT/.VolumeIcon.icns" 2>/dev/null || true
    SetFile -a C "$DMG_ROOT" 2>/dev/null || true
fi

APP_PATH="$DMG_ROOT/Achieve3000Launcher.app"

# Create a helper that removes only the quarantine attribute from the installed
# app. Do not ad-hoc sign the bundle: PyInstaller/Playwright payloads are not
# validly sealed by that signature and macOS can then report the app as damaged.
cat << 'EOF' > "$DMG_ROOT/Fix Damaged App.command"
#!/bin/bash
set -u
echo "--------------------------------------------------------"
echo " Fixing macOS Gatekeeper Quarantine for Achieve3000... "
echo "--------------------------------------------------------"

APP_PATH=""
for candidate in \
    "$HOME/Applications/Achieve3000Launcher.app" \
    "/Applications/Achieve3000Launcher.app"; do
    if [ -d "$candidate" ]; then APP_PATH="$candidate"; break; fi
done

if [ -z "$APP_PATH" ]; then
    echo "App not found. Drag Achieve3000Launcher.app to Applications first."
    read -r -p "Press Return to close..."
    exit 1
fi

if ! /usr/bin/xattr -dr com.apple.quarantine "$APP_PATH"; then
    echo "Could not remove quarantine from: $APP_PATH"
    echo "Move the app to your personal Applications folder and run this helper again."
    read -r -p "Press Return to close..."
    exit 1
fi

echo "Removed the downloaded-app quarantine flag. Opening the installed app..."
if ! /usr/bin/open "$APP_PATH"; then
    echo "macOS still blocked launch. Control-click the app in Applications and choose Open."
    read -r -p "Press Return to close..."
    exit 1
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
