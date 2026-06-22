#!/usr/bin/env bash
# Expose mac-sysdash over HTTPS on your tailnet via Tailscale Serve.
#
# This gives a clean https://<host>.<tailnet>.ts.net URL (no port) and, because
# it is a secure context, lets the browser show desktop/phone notifications
# (the bell in the header). Requires HTTPS to be enabled for your tailnet
# (Tailscale admin console → DNS → HTTPS Certificates).
set -euo pipefail

PORT="${SYSDASH_PORT:-8765}"

if ! command -v tailscale >/dev/null 2>&1; then
  echo "error: tailscale CLI not found." >&2
  exit 1
fi

echo "Exposing http://127.0.0.1:$PORT over Tailscale HTTPS …"
# CLI syntax differs across versions; try the newer form, then fall back.
tailscale serve --bg "$PORT" 2>/dev/null \
  || tailscale serve --bg "http://127.0.0.1:$PORT"

echo
tailscale serve status || true
echo
echo "Open the https://…ts.net URL shown above."
echo "To stop sharing:  tailscale serve reset"
