#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  kill -TERM "${TS_PID:-}" 2>/dev/null || true
  wait "${TS_PID:-}" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

/usr/local/bin/containerboot &
TS_PID=$!

for _ in $(seq 1 15); do
  [[ -S /var/run/tailscale/tailscaled.sock ]] && break
  sleep 1
done

exec "$@"