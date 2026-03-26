#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  kill -TERM "${APP_PID:-}" 2>/dev/null || true
  kill -TERM "${TS_PID:-}" 2>/dev/null || true
  wait "${APP_PID:-}" 2>/dev/null || true
  wait "${TS_PID:-}" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

/usr/local/bin/containerboot &
TS_PID=$!

# Optional small delay so the app doesn't race startup hard against tailscaled.
for _ in $(seq 1 15); do
  [[ -S /var/run/tailscale/tailscaled.sock ]] && break
  sleep 1
done

python3 /app/server.py &
APP_PID=$!

wait -n "$TS_PID" "$APP_PID"
exit $?