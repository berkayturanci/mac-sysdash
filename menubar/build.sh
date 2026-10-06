#!/usr/bin/env bash
# Build the Mac System Dashboard menu bar app (needs the Xcode Command Line Tools for swiftc).
#   ./menubar/build.sh                 -> "menubar/build/Mac System Dashboard.app"
#   ./menubar/build.sh --install       -> also copies it to ~/Applications and opens it
#   ./menubar/build.sh <out-dir>       -> builds into <out-dir> (used by the Homebrew formula)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL=0
OUT="$HERE/build"
for a in "$@"; do
  case "$a" in
    --install) INSTALL=1 ;;
    *) OUT="$a" ;;
  esac
done
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$HERE/../server.py")"
NAME="Mac System Dashboard"
APP="$OUT/$NAME.app"

rm -rf "$APP" "$OUT/SysdashBar.app"   # the bundle was SysdashBar.app before 1.38
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -swift-version 5 -parse-as-library "$HERE/SysdashBar.swift" -o "$APP/Contents/MacOS/SysdashBar"

# App icon (Dock, Finder, Spotlight) from the dashboard's own PNG — sips and
# iconutil ship with macOS, so no extra tooling.
ICONSET="$(mktemp -d)/AppIcon.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z "$s" "$s" "$HERE/../icon-512.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  [ "$s" -lt 512 ] && sips -z $((s * 2)) $((s * 2)) "$HERE/../icon-512.png" \
    --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$(dirname "$ICONSET")"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleIdentifier</key><string>io.github.berkayturanci.sysdash-bar</string>
  <key>CFBundleExecutable</key><string>SysdashBar</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION:-0}</string>
  <key>CFBundleVersion</key><string>${VERSION:-0}</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <!-- sysdash://open and sysdash://settings, linked from the web dashboard. -->
  <key>CFBundleURLTypes</key><array><dict>
    <key>CFBundleURLName</key><string>io.github.berkayturanci.sysdash-bar</string>
    <key>CFBundleURLSchemes</key><array><string>sysdash</string></array>
  </dict></array>
  <!-- The hub is plain http on localhost or a tailnet IP. -->
  <key>NSAppTransportSecurity</key><dict>
    <key>NSAllowsLocalNetworking</key><true/>
    <key>NSAllowsArbitraryLoads</key><true/>
  </dict>
</dict></plist>
PLIST
codesign --force --sign - "$APP" >/dev/null 2>&1 || true
echo "built $APP"

if [ "$INSTALL" = 1 ]; then
  mkdir -p "$HOME/Applications"
  pkill -x SysdashBar 2>/dev/null || true
  rm -rf "$HOME/Applications/$NAME.app" "$HOME/Applications/SysdashBar.app"
  cp -R "$APP" "$HOME/Applications/"
  open "$HOME/Applications/$NAME.app"
  echo "installed ~/Applications/$NAME.app"
fi
