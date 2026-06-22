#!/usr/bin/env bash
# Remove the mac-sysdash launchd agent. The app runs in place from this repo, so
# the repository itself is left untouched — delete it manually if you want.
set -euo pipefail

LABEL="com.berkay.sysdash"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
pkill -f "sysdash/server.py" 2>/dev/null || true

echo "mac-sysdash agent removed. The repo and logs were left in place."
echo "Tip: if you exposed it over HTTPS, run 'tailscale serve reset' to stop that too."
