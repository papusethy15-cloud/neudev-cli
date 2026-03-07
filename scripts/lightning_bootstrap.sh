#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
NEUDEV_OLLAMA_MODELS="${NEUDEV_OLLAMA_MODELS:-qwen3:latest qwen2.5-coder:7b deepseek-coder-v2:16b starcoder2:7b}"
NEUDEV_INSTALL_OLLAMA="${NEUDEV_INSTALL_OLLAMA:-1}"
OLLAMA_LOG_FILE="${OLLAMA_LOG_FILE:-$HOME/.neudev-ollama.log}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python executable not found: $PYTHON_BIN" >&2
  exit 1
fi

if ! command -v ollama >/dev/null 2>&1; then
  if [[ "$NEUDEV_INSTALL_OLLAMA" == "1" ]]; then
    if ! command -v curl >/dev/null 2>&1; then
      echo "Ollama is not installed in PATH and curl is required to install it automatically." >&2
      exit 1
    fi
    echo "Ollama was not found in PATH. Installing it with the official Linux installer..."
    curl -fsSL https://ollama.com/install.sh | sh
  fi
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed in PATH." >&2
  echo "Install Ollama first: https://docs.ollama.com/linux" >&2
  echo "Or rerun with NEUDEV_INSTALL_OLLAMA=1." >&2
  exit 1
fi

echo "Installing NeuDev into the current Python environment..."
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -e "$ROOT_DIR"

echo "Ensuring the Ollama server is reachable at $OLLAMA_HOST ..."
if ! OLLAMA_HOST="$OLLAMA_HOST" ollama list >/dev/null 2>&1; then
  nohup ollama serve >"$OLLAMA_LOG_FILE" 2>&1 &

  for _ in $(seq 1 30); do
    if OLLAMA_HOST="$OLLAMA_HOST" ollama list >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi

if ! OLLAMA_HOST="$OLLAMA_HOST" ollama list >/dev/null 2>&1; then
  echo "Ollama did not become ready. Check $OLLAMA_LOG_FILE" >&2
  exit 1
fi

echo "Pulling Ollama models..."
for model in $NEUDEV_OLLAMA_MODELS; do
  echo "  - $model"
  OLLAMA_HOST="$OLLAMA_HOST" ollama pull "$model"
done

echo "Running the NeuDev test suite..."
(cd "$ROOT_DIR" && "$PYTHON_BIN" -m unittest discover -s tests -q)

echo
echo "Bootstrap complete."
echo "Suggested hosted start command:"
echo "  export NEUDEV_API_KEY=YOUR_API_KEY"
echo "  neu serve --host 0.0.0.0 --port 8765 --ws-port 8766 --workspace $ROOT_DIR --api-key \$NEUDEV_API_KEY --session-store \$HOME/.neudev/hosted_sessions --ollama-host $OLLAMA_HOST --model auto --agents parallel"
