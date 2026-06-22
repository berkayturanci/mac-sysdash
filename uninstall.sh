#!/usr/bin/env bash
# Remove the mac-sysdash launchd agent and installed app files.
set -euo pipefail

LABEL="com.berkay.sysdash"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
APP_DIR="$HOME/.local/share/sysdash"

launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
rm -rf "$APP_DIR"
pkill -f "sysdash/server.py" 2>/dev/null || true

echo "mac-sysdash removed (logs in ~/.local/log/sysdash.log were left in place)."
