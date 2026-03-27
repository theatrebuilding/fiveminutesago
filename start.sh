#!/usr/bin/env bash
set -euo pipefail

expose_optional_host_sound() {
  local host_sound_dir="/host-dev/snd"

  [[ -e "$host_sound_dir" ]] || return 0

  if [[ -L /dev/snd ]]; then
    return 0
  fi

  if [[ -e /dev/snd && ! -L /dev/snd ]]; then
    return 0
  fi

  ln -s "$host_sound_dir" /dev/snd
}

render_serve_config() {
  local template_path="${TS_SERVE_TEMPLATE:-/config/control-app-funnel.template.json}"
  local output_path="${TS_SERVE_CONFIG:-}"
  local cert_domain=""

  [[ -n "$output_path" ]] || return 0
  [[ -f "$template_path" ]] || return 0

  for _ in $(seq 1 120); do
    cert_domain="$(
      tailscale status --json 2>/dev/null | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)

print(data.get("Self", {}).get("DNSName", "").rstrip("."))
'
    )"

    if [[ -n "$cert_domain" ]]; then
      mkdir -p "$(dirname "$output_path")"
      sed "s|\${TS_CERT_DOMAIN}|$cert_domain|g" "$template_path" > "${output_path}.tmp"
      mv "${output_path}.tmp" "$output_path"
      echo "Rendered Tailscale serve config for ${cert_domain}."
      return 0
    fi

    sleep 1
  done

  echo "Warning: could not determine Tailscale certificate domain; skipping serve config render." >&2
}

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

expose_optional_host_sound
render_serve_config &

exec "$@"
