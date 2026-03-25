#!/usr/bin/env bash
set -euo pipefail

TS_STATE_DIR="${TS_STATE_DIR:-/var/lib/tailscale}"
TS_SOCKET="${TS_SOCKET:-/var/run/tailscale/tailscaled.sock}"
TS_USERSPACE="${TS_USERSPACE:-false}"

mkdir -p "$TS_STATE_DIR" "$(dirname "$TS_SOCKET")"

tailscaled_args=(
  "--statedir=${TS_STATE_DIR}"
  "--socket=${TS_SOCKET}"
)

if [[ "${TS_USERSPACE}" == "true" ]]; then
  tailscaled_args+=("--tun=userspace-networking")
fi

if [[ -n "${TS_TAILSCALED_EXTRA_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  extra_tsdaemon=( ${TS_TAILSCALED_EXTRA_ARGS} )
  tailscaled_args+=("${extra_tsdaemon[@]}")
fi

/usr/local/bin/tailscaled "${tailscaled_args[@]}" &
TS_PID=$!

cleanup() {
  kill "${TS_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait for the local socket to exist.
for _ in $(seq 1 30); do
  [[ -S "${TS_SOCKET}" ]] && break
  sleep 1
done

# Try tailscale up until tailscaled is actually ready.
up_args=()

if [[ -n "${TS_AUTHKEY:-}" ]]; then
  up_args+=("--auth-key=${TS_AUTHKEY}")
fi

if [[ -n "${TS_HOSTNAME:-}" ]]; then
  up_args+=("--hostname=${TS_HOSTNAME}")
fi

if [[ -n "${TS_EXTRA_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  extra_up=( ${TS_EXTRA_ARGS} )
  up_args+=("${extra_up[@]}")
fi

for _ in $(seq 1 30); do
  if /usr/local/bin/tailscale --socket="${TS_SOCKET}" up "${up_args[@]}"; then
    break
  fi
  sleep 2
done

/usr/local/bin/tailscale --socket="${TS_SOCKET}" status

exec "$@"