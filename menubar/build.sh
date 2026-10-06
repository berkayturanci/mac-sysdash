#!/usr/bin/env bash
# Build the sysdash menu bar app (needs the Xcode Command Line Tools for swiftc).
#   ./menubar/build.sh                 -> menubar/build/SysdashBar.app
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
APP="$OUT/SysdashBar.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
swiftc -O -swift-version 5 -parse-as-library "$HERE/SysdashBar.swift" -o "$APP/Contents/MacOS/SysdashBar"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>sysdash</string>
  <key>CFBundleDisplayName</key><string>sysdash</string>
  <key>CFBundleIdentifier</key><string>io.github.berkayturanci.sysdash-bar</string>
  <key>CFBundleExecutable</key><string>SysdashBar</string>
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
  rm -rf "$HOME/Applications/SysdashBar.app"
  cp -R "$APP" "$HOME/Applications/"
  open "$HOME/Applications/SysdashBar.app"
  echo "installed ~/Applications/SysdashBar.app"
fi
