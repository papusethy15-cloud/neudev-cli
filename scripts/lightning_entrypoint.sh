#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
NEUDEV_HOST="${NEUDEV_HOST:-0.0.0.0}"
NEUDEV_HTTP_PORT="${NEUDEV_HTTP_PORT:-8765}"
NEUDEV_WS_PORT="${NEUDEV_WS_PORT:-8766}"
NEUDEV_WORKSPACE="${NEUDEV_WORKSPACE:-$ROOT_DIR}"
NEUDEV_SESSION_STORE="${NEUDEV_SESSION_STORE:-$HOME/.neudev/hosted_sessions}"
NEUDEV_MODEL="${NEUDEV_MODEL:-auto}"
NEUDEV_AGENT_MODE="${NEUDEV_AGENT_MODE:-parallel}"
NEUDEV_LANGUAGE="${NEUDEV_LANGUAGE:-English}"
NEUDEV_AUTO_PERMISSION="${NEUDEV_AUTO_PERMISSION:-0}"
NEUDEV_DISABLE_WEBSOCKET="${NEUDEV_DISABLE_WEBSOCKET:-0}"
NEUDEV_BOOTSTRAP="${NEUDEV_BOOTSTRAP:-0}"
NEUDEV_OLLAMA_HOST="${NEUDEV_OLLAMA_HOST:-${OLLAMA_HOST:-http://127.0.0.1:11434}}"
NEUDEV_HOSTED_RUN_COMMAND_MODE="${NEUDEV_HOSTED_RUN_COMMAND_MODE:-restricted}"

if [[ -z "${NEUDEV_API_KEY:-}" ]]; then
  echo "NEUDEV_API_KEY must be set before starting the hosted server." >&2
  exit 1
fi

if [[ "$NEUDEV_BOOTSTRAP" == "1" ]]; then
  bash "$ROOT_DIR/scripts/lightning_bootstrap.sh"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python runtime '$PYTHON_BIN' was not found." >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c "import rich, prompt_toolkit, websockets" >/dev/null 2>&1; then
  echo "Missing Python dependencies for NeuDev." >&2
  echo "Run '$PYTHON_BIN -m pip install -e .' from $ROOT_DIR or set NEUDEV_BOOTSTRAP=1." >&2
  exit 1
fi

cd "$ROOT_DIR"

mkdir -p "$NEUDEV_SESSION_STORE"

set -- "$PYTHON_BIN" -m neudev.cli serve \
  --host "$NEUDEV_HOST" \
  --port "$NEUDEV_HTTP_PORT" \
  --workspace "$NEUDEV_WORKSPACE" \
  --api-key "$NEUDEV_API_KEY" \
  --session-store "$NEUDEV_SESSION_STORE" \
  --ollama-host "$NEUDEV_OLLAMA_HOST" \
  --model "$NEUDEV_MODEL" \
  --agents "$NEUDEV_AGENT_MODE" \
  --language "$NEUDEV_LANGUAGE"

if [[ "$NEUDEV_DISABLE_WEBSOCKET" == "1" ]]; then
  set -- "$@" --disable-websocket
else
  set -- "$@" --ws-port "$NEUDEV_WS_PORT"
fi

if [[ "$NEUDEV_AUTO_PERMISSION" == "1" ]]; then
  set -- "$@" --auto-permission
fi

echo "Starting NeuDev hosted server..."
echo "  workspace: $NEUDEV_WORKSPACE"
echo "  session_store: $NEUDEV_SESSION_STORE"
echo "  ollama_host: $NEUDEV_OLLAMA_HOST"
echo "  run_command_policy: $NEUDEV_HOSTED_RUN_COMMAND_MODE"

exec env NEUDEV_HOSTED_RUN_COMMAND_MODE="$NEUDEV_HOSTED_RUN_COMMAND_MODE" "$@"
