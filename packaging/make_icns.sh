#!/usr/bin/env bash
# Baut packaging/build/icon.icns aus musiclib/resources/icon.png (1024 px). Läuft nur auf macOS.
# Das PNG selbst entsteht aus packaging/icon.svg mit packaging/make_icon.py.
set -euo pipefail
cd "$(dirname "$0")/.."

ICONSET=packaging/build/icon.iconset
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s musiclib/resources/icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) musiclib/resources/icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o packaging/build/icon.icns
echo "packaging/build/icon.icns geschrieben"
