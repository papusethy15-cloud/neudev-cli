#!/bin/bash
# Google Colab NeuDev Server Startup
# Runs server in background so you can continue using the notebook

set -e

echo "=========================================="
echo "  ⚡ NeuDev Server for Google Colab"
echo "=========================================="
echo ""

# Set environment variables
export NEUDEV_API_KEY="${NEUDEV_API_KEY:-colab-default-key-12345}"
export NEUDEV_WORKSPACE="${NEUDEV_WORKSPACE:-/content/neudev-cli}"
export NEUDEV_SESSION_STORE="${NEUDEV_SESSION_STORE:-/root/.neudev/hosted_sessions}"
export NEUDEV_OLLAMA_HOST="${NEUDEV_OLLAMA_HOST:-http://127.0.0.1:11434}"
export NEUDEV_HTTP_PORT="${NEUDEV_HTTP_PORT:-8765}"
export NEUDEV_DISABLE_WEBSOCKET="${NEUDEV_DISABLE_WEBSOCKET:-1}"

# Create session store directory
mkdir -p "$NEUDEV_SESSION_STORE"

echo "Configuration:"
echo "  API Key: $NEUDEV_API_KEY"
echo "  Workspace: $NEUDEV_WORKSPACE"
echo "  Session Store: $NEUDEV_SESSION_STORE"
echo "  Ollama Host: $NEUDEV_OLLAMA_HOST"
echo "  HTTP Port: $NEUDEV_HTTP_PORT"
echo ""

# Check if Ollama is running
echo "Checking Ollama..."
if curl -s "$NEUDEV_OLLAMA_HOST/api/tags" > /dev/null 2>&1; then
    echo "✅ Ollama is running"
    ollama list
else
    echo "❌ Ollama is not running. Please start Ollama first."
    exit 1
fi
echo ""

# Kill any existing NeuDev server
pkill -f "python -m neudev.cli serve" 2>/dev/null || true
sleep 2

# Start server in background
echo "Starting NeuDev server in background..."
nohup python -m neudev.cli serve \
  --host 0.0.0.0 \
  --port "$NEUDEV_HTTP_PORT" \
  --workspace "$NEUDEV_WORKSPACE" \
  --api-key "$NEUDEV_API_KEY" \
  --session-store "$NEUDEV_SESSION_STORE" \
  --ollama-host "$NEUDEV_OLLAMA_HOST" \
  --model auto \
  --agents parallel \
  --language English \
  > /tmp/neudev_server.log 2>&1 &

SERVER_PID=$!
echo "Server PID: $SERVER_PID"
echo ""

# Wait for server to start
echo "Waiting for server to start..."
for i in {1..30}; do
    if curl -s "http://127.0.0.1:$NEUDEV_HTTP_PORT/health" > /dev/null 2>&1; then
        echo "✅ Server is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ Server failed to start. Check logs:"
        cat /tmp/neudev_server.log
        exit 1
    fi
    sleep 1
done

# Get public URL using ngrok (if available)
echo ""
echo "=========================================="
echo "  🌐 Public Access"
echo "=========================================="
echo ""

if command -v ngrok &> /dev/null; then
    echo "Starting ngrok tunnel..."
    ngrok http $NEUDEV_HTTP_PORT --log=stdout > /tmp/ngrok.log 2>&1 &
    NGROK_PID=$!
    echo "Ngrok PID: $NGROK_PID"
    
    sleep 5
    
    # Get ngrok URL
    NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels | python3 -c "import sys, json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null || echo "Check ngrok dashboard")
    
    echo ""
    echo "🎉 NeuDev Server is running!"
    echo ""
    echo "Public URL: $NGROK_URL"
    echo ""
    echo "Local URL: http://127.0.0.1:$NEUDEV_HTTP_PORT"
    echo ""
    echo "API Key: $NEUDEV_API_KEY"
    echo ""
    echo "=========================================="
    echo "  Local Testing"
    echo "=========================================="
    echo ""
    echo "Configure your local CLI:"
    echo "  neu auth login --runtime hybrid \\"
    echo "    --api-base-url $NGROK_URL \\"
    echo "    --api-key $NEUDEV_API_KEY"
    echo ""
    echo "Then run:"
    echo "  neu run --runtime hybrid --workspace ."
    echo ""
else
    echo "ngrok not found. Installing..."
    
    # Install ngrok
    cd /tmp
    wget -q https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
    tar -xzf ngrok-v3-stable-linux-amd64.tgz
    mv ngrok /usr/local/bin/
    chmod +x /usr/local/bin/ngrok
    
    echo ""
    echo "ngrok installed. Please set your auth token:"
    echo "  ngrok config add-authtoken YOUR_TOKEN"
    echo ""
    echo "Then restart the server."
fi

# Show server logs command
echo ""
echo "=========================================="
echo "  📋 Useful Commands"
echo "=========================================="
echo ""
echo "View server logs:"
echo "  tail -f /tmp/neudev_server.log"
echo ""
echo "Check server health:"
echo "  curl http://127.0.0.1:$NEUDEV_HTTP_PORT/health"
echo ""
echo "Stop server:"
echo "  kill $SERVER_PID"
echo ""
echo "Restart server:"
echo "  bash /content/neudev-cli/scripts/colab_start_server.sh"
echo ""
echo "=========================================="
