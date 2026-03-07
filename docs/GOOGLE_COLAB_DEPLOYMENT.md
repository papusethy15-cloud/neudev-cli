# Google Colab Deployment Guide - NeuDev v2.2.0

**Date**: 2026-03-07  
**Platform**: Google Colab (Free/Pro)  
**Mode**: Hosted Server + Local Hybrid CLI

---

## 🚀 Quick Start

### Step 1: Clone & Setup (Run in Colab Cell)

```python
# Clone NeuDev
!git clone https://github.com/papusethy15-cloud/neudev-cli.git /content/neudev-cli
%cd /content/neudev-cli

# Install dependencies
!pip install -e . -q

# Install ngrok for public URL
!pip install pyngrok -q
!wget -q https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
!tar -xzf ngrok-v3-stable-linux-amd64.tgz
!mv ngrok /usr/local/bin/
!chmod +x /usr/local/bin/ngrok

# Set ngrok auth token (get from https://dashboard.ngrok.com)
!ngrok config add-authtoken YOUR_NGROK_TOKEN_HERE
```

### Step 2: Start Ollama (Run in Colab Cell)

```python
# Install Ollama
!curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama in background
import subprocess
import time

# Start ollama serve
ollama_process = subprocess.Popen(
    ["ollama", "serve"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

# Wait for Ollama to start
time.sleep(5)

# Pull models
!ollama pull qwen3:latest
!ollama pull qwen2.5-coder:7b
!ollama pull deepseek-coder-v2:16b
!ollama pull starcoder2:7b

print("✅ Ollama is running with 4 models")
```

### Step 3: Start NeuDev Server (Run in Colab Cell)

```python
# Set environment variables
import os
os.environ['NEUDEV_API_KEY'] = 'colab-secret-key-12345'
os.environ['NEUDEV_WORKSPACE'] = '/content/neudev-cli'
os.environ['NEUDEV_SESSION_STORE'] = '/root/.neudev/hosted_sessions'
os.environ['NEUDEV_OLLAMA_HOST'] = 'http://127.0.0.1:11434'
os.environ['NEUDEV_HTTP_PORT'] = '8765'

# Start server in background
import subprocess
import time

server_cmd = [
    'python', '-m', 'neudev.cli', 'serve',
    '--host', '0.0.0.0',
    '--port', os.environ['NEUDEV_HTTP_PORT'],
    '--workspace', os.environ['NEUDEV_WORKSPACE'],
    '--api-key', os.environ['NEUDEV_API_KEY'],
    '--session-store', os.environ['NEUDEV_SESSION_STORE'],
    '--ollama-host', os.environ['NEUDEV_OLLAMA_HOST'],
    '--model', 'auto',
    '--agents', 'parallel',
    '--language', 'English'
]

# Start server
server_process = subprocess.Popen(
    server_cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

print(f"Server PID: {server_process.pid}")
print("Waiting for server to start...")

# Wait for server
time.sleep(10)

# Check health
import urllib.request
try:
    response = urllib.request.urlopen(f'http://127.0.0.1:{os.environ["NEUDEV_HTTP_PORT"]}/health')
    print("✅ Server is running!")
except Exception as e:
    print(f"❌ Server failed: {e}")
```

### Step 4: Create Public URL (Run in Colab Cell)

```python
from pyngrok import ngrok

# Create tunnel
public_url = ngrok.connect(8765)
print(f"🎉 NeuDev Server is running!")
print(f"")
print(f"Public URL: {public_url}")
print(f"API Key: {os.environ['NEUDEV_API_KEY']}")
print(f"")
print(f"Configure your local CLI:")
print(f"  neu auth login --runtime hybrid \\")
print(f"    --api-base-url {public_url} \\")
print(f"    --api-key {os.environ['NEUDEV_API_KEY']}")
```

---

## 📋 Complete Setup Script

Copy this entire block into a single Colab cell:

```python
# ============================================
# NeuDev v2.2.0 - Complete Google Colab Setup
# ============================================

print("🚀 Starting NeuDev setup on Google Colab...")
print("")

# 1. Clone repository
print("📦 Step 1: Cloning repository...")
!git clone https://github.com/papusethy15-cloud/neudev-cli.git /content/neudev-cli
%cd /content/neudev-cli

# 2. Install Python dependencies
print("📦 Step 2: Installing Python dependencies...")
!pip install -e . -q

# 3. Install Ollama
print("📦 Step 3: Installing Ollama...")
!curl -fsSL https://ollama.com/install.sh | sh

# 4. Install ngrok
print("📦 Step 4: Installing ngrok...")
!pip install pyngrok -q
!wget -q https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz -O /tmp/ngrok.tgz
!tar -xzf /tmp/ngrok.tgz
!mv ngrok /usr/local/bin/
!chmod +x /usr/local/bin/ngrok

# Set your ngrok token here
NGROK_TOKEN = "YOUR_NGROK_TOKEN_HERE"  # Get from https://dashboard.ngrok.com
!ngrok config add-authtoken $NGROK_TOKEN

print("")
print("✅ Setup complete! Continue with next cell to start services.")
```

---

## 🏃 Running Services

### Cell 1: Start Ollama

```python
import subprocess
import time

print("🚀 Starting Ollama...")

# Start ollama
ollama = subprocess.Popen(
    ["ollama", "serve"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

# Wait for startup
time.sleep(5)

# Pull models
print("📥 Pulling models...")
!ollama pull qwen3:latest
!ollama pull qwen2.5-coder:7b
!ollama pull deepseek-coder-v2:16b
!ollama pull starcoder2:7b

print("✅ Ollama is running with 4 models")
!ollama list
```

### Cell 2: Start NeuDev Server

```python
import os
import subprocess
import time
import urllib.request

# Configuration
API_KEY = 'colab-secret-key-12345'
PORT = 8765
WORKSPACE = '/content/neudev-cli'
SESSION_STORE = '/root/.neudev/hosted_sessions'
OLLAMA_HOST = 'http://127.0.0.1:11434'

print("🚀 Starting NeuDev server...")

# Start server
server_cmd = [
    'python', '-m', 'neudev.cli', 'serve',
    '--host', '0.0.0.0',
    '--port', str(PORT),
    '--workspace', WORKSPACE,
    '--api-key', API_KEY,
    '--session-store', SESSION_STORE,
    '--ollama-host', OLLAMA_HOST,
    '--model', 'auto',
    '--agents', 'parallel',
    '--language', 'English'
]

server = subprocess.Popen(
    server_cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

print(f"Server PID: {server.pid}")

# Wait for startup
print("Waiting for server to start...")
for i in range(30):
    try:
        response = urllib.request.urlopen(f'http://127.0.0.1:{PORT}/health')
        print("✅ Server is ready!")
        break
    except:
        if i == 29:
            print("❌ Server failed to start")
        time.sleep(1)
```

### Cell 3: Create Public URL

```python
from pyngrok import ngrok

print("🌐 Creating public URL...")

# Connect tunnel
public_url = ngrok.connect(8765)

print("")
print("=" * 60)
print("  🎉 NeuDev Server is Running!")
print("=" * 60)
print("")
print(f"Public URL: {public_url}")
print(f"API Key: colab-secret-key-12345")
print("")
print("Configure your local CLI:")
print(f"  neu auth login --runtime hybrid \\")
print(f"    --api-base-url {public_url} \\")
print(f"    --api-key colab-secret-key-12345")
print("")
print("Then test:")
print("  neu run --runtime hybrid --workspace .")
print("")
print("=" * 60)
```

---

## 💻 Local CLI Configuration

On your **local machine** (Windows/Mac/Linux):

```bash
# Install NeuDev CLI
cd /path/to/neu-dev
pip install -e .

# Configure for hybrid mode
neu auth login --runtime hybrid \
  --api-base-url https://YOUR-NGROK-URL.ngrok.io \
  --api-key colab-secret-key-12345

# Verify
neu auth status

# Test
neu run --runtime hybrid --workspace .
```

---

## 🧪 Test Commands

Once connected, test these commands:

```
neudev ❯ Create a single page website using modern design

neudev ❯ Rename all 'test' to 'check' in *.py files

neudev ❯ Fix the ImportError in neudev/agent.py

neudev ❯ /help
```

---

## ⚠️ Important Notes

### Colab Limitations

1. **Session Timeout**: Free Colab sessions last 12 hours max
2. **RAM**: ~12GB available
3. **CPU**: 2 vCPUs
4. **GPU**: Optional (T4/K80 on free tier)

### Keeping Server Alive

```python
# Add this cell to keep Colab from disconnecting
import time
while True:
    time.sleep(3600)  # Keep alive
```

### Ngrok Limitations

- Free tier: Random URL each session
- Paid tier: Custom domains available

---

## 🔧 Troubleshooting

### Issue: Server won't start

```python
# Check logs
!cat /proc/$(pgrep -f "neudev.cli serve")/fd/1 2>/dev/null || echo "No logs"

# Check if port is in use
!netstat -tlnp | grep 8765

# Kill existing server
!pkill -f "neudev.cli serve"
```

### Issue: Ollama not responding

```python
# Restart Ollama
!pkill ollama
!ollama serve &
time.sleep(5)
!ollama list
```

### Issue: Ngrok connection fails

```python
# Check ngrok auth
!ngrok config check

# Re-add auth token
!ngrok config add-authtoken YOUR_TOKEN
```

---

## 📊 Performance

| Metric | Colab Free | Colab Pro |
|--------|------------|-----------|
| RAM | 12GB | 25GB |
| CPU | 2 vCPU | 2+ vCPU |
| GPU | T4 (optional) | Better GPUs |
| Session | 12 hours | 24 hours |
| Models | 4 (7-16GB) | More models |

---

## 🎯 Quick Reference

### Start Everything (Copy-Paste)

```python
# Clone
!git clone https://github.com/papusethy15-cloud/neudev-cli.git /content/neudev-cli && cd /content/neudev-cli && pip install -e . -q

# Ollama
!curl -fsSL https://ollama.com/install.sh | sh
!ollama serve &
import time; time.sleep(5)
!ollama pull qwen3:latest && !ollama pull qwen2.5-coder:7b

# NeuDev Server
import os, subprocess, urllib.request
os.environ['NEUDEV_API_KEY'] = 'test123'
subprocess.Popen(['python', '-m', 'neudev.cli', 'serve', '--host', '0.0.0.0', '--port', '8765', '--api-key', 'test123'])
time.sleep(10)

# Public URL
from pyngrok import ngrok
print(f"URL: {ngrok.connect(8765)}")
print("API Key: test123")
```

---

**Deployment Complete!** 🎉

Your NeuDev v2.2.0 is now running on Google Colab with:
- ✅ Ollama with 4 models
- ✅ NeuDev server with all intelligence features
- ✅ Public URL via ngrok
- ✅ Ready for local hybrid CLI testing

Happy coding! 💻✨
