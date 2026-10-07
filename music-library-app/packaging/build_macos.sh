#!/usr/bin/env bash
# Baut "MusicLib Organizer.app" und das DMG. Läuft nur auf macOS.
#   ./packaging/build_macos.sh          → dist/MusicLib-Organizer-<version>.dmg
set -euo pipefail
cd "$(dirname "$0")/.."

NAME="MusicLib Organizer"
VERSION=$(python3 -c 'import re;print(re.search(r"__version__ = \"([^\"]+)\"", open("src/musiclib/__init__.py").read())[1])')
ARCH=$(uname -m)
BUILD=packaging/build
rm -rf "$BUILD" dist build
mkdir -p "$BUILD"

# Icon: alle Größen aus dem 1024-px-PNG, dann .icns mit Apples iconutil
ICONSET="$BUILD/icon.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s packaging/icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) packaging/icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUILD/icon.icns"

pyinstaller --noconfirm --clean packaging/musiclib.spec
APP="dist/$NAME.app"

# Ad-hoc-Signatur (ohne Apple-Developer-Konto); Pflicht auf Apple Silicon
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

# Kurztest: Fenster aufbauen und schließen
"$APP/Contents/MacOS/$NAME" --selftest

# DMG mit Verknüpfung zum Programme-Ordner (Drag & Drop)
STAGE="$BUILD/dmg"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Programme"
DMG="dist/MusicLib-Organizer-$VERSION-$ARCH.dmg"
hdiutil create -volname "$NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
echo "Fertig: $DMG"
