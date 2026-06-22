#!/usr/bin/env bash
# Install mac-sysdash as a per-user launchd agent.
set -euo pipefail

APP_DIR="$HOME/.local/share/sysdash"
LOG_DIR="$HOME/.local/log"
LABEL="com.berkay.sysdash"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT="${SYSDASH_PORT:-8765}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$APP_DIR" "$LOG_DIR" "$HOME/Library/LaunchAgents"

# --- find a python that already has psutil ---
find_python() {
  for c in \
    "$(command -v python3 || true)" \
    "/opt/homebrew/opt/glances/libexec/bin/python3" \
    "/usr/local/opt/glances/libexec/bin/python3" \
    "/opt/homebrew/bin/python3"; do
    [ -n "$c" ] && [ -x "$c" ] || continue
    if "$c" -c "import psutil" >/dev/null 2>&1; then echo "$c"; return 0; fi
  done
  return 1
}

PYTHON="$(find_python || true)"

# --- otherwise bootstrap a self-contained venv with psutil ---
if [ -z "$PYTHON" ]; then
  VENV="$APP_DIR/venv"
  if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import psutil" >/dev/null 2>&1; then
    PYTHON="$VENV/bin/python"
  else
    BASE="$(command -v python3 || true)"
    if [ -z "$BASE" ]; then
      echo "error: python3 not found. Install the Xcode Command Line Tools" >&2
      echo "       (xcode-select --install) or Homebrew python, then re-run." >&2
      exit 1
    fi
    echo "no psutil found — creating a virtualenv at $VENV …"
    "$BASE" -m venv "$VENV"
    "$VENV/bin/python" -m pip install --quiet --upgrade pip
    "$VENV/bin/python" -m pip install --quiet psutil
    PYTHON="$VENV/bin/python"
  fi
fi
echo "using python: $PYTHON"

# --- copy app files ---
cp "$SRC_DIR/server.py" "$APP_DIR/server.py"
cp "$SRC_DIR/index.html" "$APP_DIR/index.html"
echo "installed app to: $APP_DIR"

# --- generate launchd plist ---
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$LABEL</string>
	<key>ProgramArguments</key>
	<array>
		<string>$PYTHON</string>
		<string>$APP_DIR/server.py</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>StandardOutPath</key>
	<string>$LOG_DIR/sysdash.log</string>
	<key>StandardErrorPath</key>
	<string>$LOG_DIR/sysdash.log</string>
	<key>EnvironmentVariables</key>
	<dict>
		<key>SYSDASH_PORT</key>
		<string>$PORT</string>
		<key>PATH</key>
		<string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin</string>
	</dict>
</dict>
</plist>
PLISTEOF
echo "wrote launchd plist: $PLIST"

# --- (re)load ---
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"

echo
echo "mac-sysdash is running:"
echo "  http://localhost:$PORT"
if command -v tailscale >/dev/null 2>&1; then
  IP="$(tailscale ip -4 2>/dev/null | head -1 || true)"
  [ -n "$IP" ] && echo "  http://$IP:$PORT   (over Tailscale)"
fi
