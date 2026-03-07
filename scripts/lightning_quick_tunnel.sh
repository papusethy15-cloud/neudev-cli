#!/usr/bin/env bash
set -euo pipefail

NEUDEV_HTTP_PORT="${NEUDEV_HTTP_PORT:-8765}"
NEUDEV_TUNNEL_TARGET="${NEUDEV_TUNNEL_TARGET:-http://127.0.0.1:${NEUDEV_HTTP_PORT}}"
CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-$HOME/bin/cloudflared}"

install_cloudflared() {
  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to download cloudflared." >&2
    exit 1
  fi

  mkdir -p "$(dirname "$CLOUDFLARED_BIN")"
  echo "Downloading cloudflared to $CLOUDFLARED_BIN ..."
  curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o "$CLOUDFLARED_BIN"
  chmod +x "$CLOUDFLARED_BIN"
}

if [[ ! -x "$CLOUDFLARED_BIN" ]]; then
  install_cloudflared
fi

echo "Starting Cloudflare quick tunnel for $NEUDEV_TUNNEL_TARGET"
echo "Keep this process running while local NeuDev clients connect."
exec "$CLOUDFLARED_BIN" tunnel --url "$NEUDEV_TUNNEL_TARGET"
