#!/usr/bin/env bash
# Remove the mac-sysdash launchd agent. The app runs in place from this repo, so
# the repository itself is left untouched — delete it manually if you want.
set -euo pipefail

LABEL="com.berkay.sysdash"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
pkill -f "sysdash/server.py" 2>/dev/null || true

# Menu bar app: its "Open at login" agent and the copy build.sh --install made.
pkill -x SysdashBar 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/io.github.berkayturanci.sysdash-bar.plist"
rm -rf "$HOME/Applications/SysdashBar.app"

echo "mac-sysdash agent and menu bar app removed. The repo and logs were left in place."
echo "Tip: if you exposed it over HTTPS, run 'tailscale serve reset' to stop that too."
