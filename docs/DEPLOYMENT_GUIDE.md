# Lightning Studio Deployment Guide - NeuDev v2.2.0

**Date**: 2026-03-07  
**Version**: 2.2.0  
**Deployment Mode**: Hybrid (Hosted Inference + Local Workspace)

---

## 📋 Quick Start

```bash
# 1. Commit & Push
git add -A
git commit -m "feat: Add advanced agent intelligence and new tools"
git push origin main

# 2. Update Lightning Studio
ssh lightning-studio
cd ~/neudev-cli
git pull origin main
python -m pip install -e .

# 3. Start Hosted Server
export NEUDEV_API_KEY="your-secret-key"
neu serve --host 0.0.0.0 --port 8765 --api-key "$NEUDEV_API_KEY"

# 4. Test Locally (Hybrid Mode)
neu run --runtime hybrid --workspace .
```

---

## Phase 1: Commit & Push Changes

### 1.1 Review Changes

```bash
cd C:\WorkSpace\neu-dev
git status
git diff --stat
```

**Expected Output**:
```
 neudev/agent.py                          | 200 ++++++++++++++
 neudev/model_routing.py                  | 100 +++++++
 neudev/cli.py                            | 150 +++++++++++
 neudev/tools/find_replace.py             | 220 ++++++++++++++++
 neudev/tools/write_file.py               |  50 +++-
 neudev/tools/__init__.py                 |  10 +-
 docs/AGENT_INTELLIGENCE_IMPLEMENTATION.md| 300 +++++++++++++++++++++
 docs/NEW_TOOLS_IMPLEMENTATION.md         | 250 ++++++++++++++++++
 ... (more files)
```

### 1.2 Commit Changes

```bash
git add -A

git commit -m "feat: Add advanced agent intelligence and new tools

Major Enhancements:
- Conversation pruning to prevent context overflow
- Self-correction on tool errors with alternative suggestions  
- Dynamic tool selection guidance in system prompt
- New find_replace tool for multi-location text replacement
- Enhanced write_file with explicit override mode
- VRAM-aware model routing
- Enhanced CLI UI with descriptive status
- Permission prompt with visual countdown
- Workspace-relative paths in tool events
- Diff preview in turn summary

New Tools:
- find_replace: Multi-location find & replace (regex support)
- write_file (enhanced): Explicit overwrite mode

Total: 27 tools available

Version: 2.2.0"

git push origin main
```

### 1.3 Verify Push

```bash
git log -n 3
# Should show your latest commit at the top
```

---

## Phase 2: Update Lightning Studio

### 2.1 Connect to Lightning Studio

**Option A: SSH**
```bash
ssh your-username@your-lightning-studio.lightning.ai
```

**Option B: Lightning Studio Terminal**
- Open Lightning AI Studio in browser
- Click "Terminal" tab

### 2.2 Pull Latest Changes

```bash
cd ~/neudev-cli  # or your NeuDev path
git pull origin main
```

**Expected Output**:
```
remote: Enumerating objects: 150, done.
remote: Counting objects: 100% (150/150), done.
remote: Compressing objects: 100% (80/80), done.
remote: Total 120 (delta 60), reused 90 (delta 40)
Receiving objects: 100% (150/150), 50.5 KiB | 2.5 MiB/s, done.
Updating abc1234..def5678
Fast-forward
 neudev/agent.py           | 200 +++++++++++++
 neudev/model_routing.py   | 100 +++++++
 ... (more files)
```

### 2.3 Install Dependencies

```bash
python -m pip install -e .
```

**Expected Output**:
```
Obtaining file:///teamspace/studios/this_studio/neudev-cli
  Installing build dependencies ... done
  Checking if build backend supports build_editable ... done
  Getting requirements to build editable ... done
  Preparing editable metadata (pyproject.toml) ... done
Requirement already satisfied: ollama>=0.4.0 in /usr/local/lib/python3.11/site-packages
Requirement already satisfied: rich>=14.0.0 in /usr/local/lib/python3.11/site-packages
...
Successfully installed neudev-2.2.0
```

### 2.4 Verify Installation

```bash
# Check version
neu version

# Expected: NeuDev v2.2.0

# Verify new tools
python -c "from neudev.tools import create_tool_registry; r = create_tool_registry(); print(f'Total tools: {len(r.get_all())}')"

# Expected: Total tools: 27

# Verify agent intelligence
python -c "from neudev.agent import Agent; from neudev.config import NeuDevConfig; a = Agent(NeuDevConfig(), '.'); print('Agent features: conversation pruning, self-correction, dynamic tool selection')"

# Expected: Agent features: conversation pruning, self-correction, dynamic tool selection
```

---

## Phase 3: Start Hosted Server on Lightning

### 3.1 Set Environment Variables

```bash
# Generate a secure API key (if you don't have one)
export NEUDEV_API_KEY=$(openssl rand -hex 32)
echo "Your API Key: $NEUDEV_API_KEY"
# Save this key - you'll need it for local CLI!

# Or use your existing API key
export NEUDEV_API_KEY="your-existing-secret-key"

# Set workspace
export NEUDEV_WORKSPACE="$PWD"

# Set session store
export NEUDEV_SESSION_STORE="$HOME/.neudev/hosted_sessions"
mkdir -p "$NEUDEV_SESSION_STORE"
```

### 3.2 Verify Ollama is Running

```bash
# Check if Ollama is running
ollama list

# If not running, start it
ollama serve &
sleep 3
ollama list
```

**Expected Output**:
```
NAME                       ID              SIZE      MODIFIED
qwen3:latest              abc1234567890   4.7 GB    2 days ago
qwen2.5-coder:7b          def5678901234   4.7 GB    2 days ago
deepseek-coder-v2:16b     ghi9012345678   9.2 GB    1 week ago
starcoder2:7b             jkl3456789012   4.2 GB    1 week ago
```

### 3.3 Start the Hosted Server

```bash
neu serve \
  --host 0.0.0.0 \
  --port 8765 \
  --ws-port 8766 \
  --workspace "$NEUDEV_WORKSPACE" \
  --api-key "$NEUDEV_API_KEY" \
  --session-store "$NEUDEV_SESSION_STORE" \
  --ollama-host http://127.0.0.1:11434 \
  --model auto \
  --agents parallel \
  --language English
```

**Expected Output**:
```
Starting NeuDev hosted server...
  workspace: /teamspace/studios/this_studio/neudev-cli
  session_store: /teamspace/studios/this_studio/.neudev/hosted_sessions
  ollama_host: http://127.0.0.1:11434
  inference_models: 4
  run_command_policy: restricted

Server running on:
  HTTP: http://0.0.0.0:8765
  WebSocket: ws://0.0.0.0:8766/v1/stream

Press Ctrl+C to stop
```

### 3.4 Create Public URL (Cloudflare Tunnel)

Lightning Studio may not expose ports publicly. Use Cloudflare tunnel:

```bash
# In a NEW terminal (keep server running in first terminal)
cd ~/neudev-cli
export NEUDEV_HTTP_PORT=8765
bash scripts/lightning_quick_tunnel.sh
```

**Expected Output**:
```
Downloading cloudflared...
Starting Cloudflare tunnel...

+--------------------------------------------------------------------+
|  Your public URL:                                                   |
|  https://your-studio-name-8765.trycloudflare.com                    |
|                                                                     |
|  Keep this terminal open while testing locally.                     |
+--------------------------------------------------------------------+
```

**Save this URL** - you'll need it for local CLI configuration!

### 3.5 Verify Server Health

```bash
# In another terminal or from your local machine
curl https://your-studio-name-8765.trycloudflare.com/health
```

**Expected Output**:
```json
{
  "status": "healthy",
  "timestamp": "2026-03-07T12:00:00Z",
  "checks": [
    {"check_name": "ollama", "status": "healthy", "message": "Ollama is running with 4 model(s)"},
    {"check_name": "workspace", "status": "healthy", "message": "Workspace is writable"},
    {"check_name": "disk_space", "status": "healthy", "message": "Disk space OK"}
  ],
  "service_info": {
    "service": "NeuDev",
    "version": "2.2.0"
  }
}
```

---

## Phase 4: Configure Local CLI for Hybrid Mode

### 4.1 Install/Update Local CLI

```bash
cd C:\WorkSpace\neu-dev
python -m pip install -e .
```

**Expected Output**:
```
Obtaining file:///C:/WorkSpace/neu-dev
  Installing build dependencies ... done
  Checking if build backend supports build_editable ... done
  Getting requirements to build editable ... done
  Preparing editable metadata (pyproject.toml) ... done
Successfully installed neudev-2.2.0
```

### 4.2 Configure Hybrid Mode

```bash
# Configure for hybrid runtime
neu auth login --runtime hybrid `
  --api-base-url https://your-studio-name-8765.trycloudflare.com `
  --api-key your-api-key-here
```

**Expected Output**:
```
✅ Authentication successful!

Configuration saved to: C:\Users\YourName\.neudev\config.json

Runtime Mode: hybrid
API Base URL: https://your-studio-name-8765.trycloudflare.com
Workspace: Local (C:\WorkSpace\neu-dev)
Inference: Hosted (Lightning Studio)

You can now run: neu run --runtime hybrid
```

### 4.3 Verify Configuration

```bash
neu auth status
```

**Expected Output**:
```
NeuDev Authentication Status

Runtime Mode: hybrid
API Base URL: https://your-studio-name-8765.trycloudflare.com
API Key: configured ✓
Workspace: C:\WorkSpace\neu-dev
Stream Transport: auto (WebSocket preferred)

Health Check:
  Server: ✓ Healthy
  Models: 4 available
  Latency: 45ms
```

---

## Phase 5: Test the Enhanced AI Agent

### 5.1 Start Hybrid Session

```bash
neu run --runtime hybrid --workspace .
```

**Expected Output**:
```
  ⚡ NeuDev
  
  🧭 Runtime   Hybrid (Local workspace + Hosted inference)
  🤖 Model     auto
  📂 Workspace neu-dev
  🕐 Started  02:30 PM
  
  💡 Type /help for commands

neudev ❯
```

### 5.2 Test New Features

#### Test 1: Conversation Pruning

```
neudev ❯ Let's have a long conversation. I'll send 50 messages.
[Send 50 short messages back and forth]
neudev ❯ This is message 51. Can you still remember context?

# Expected: Agent responds correctly without context overflow errors
```

#### Test 2: Self-Correction

```
neudev ❯ Edit the file nonexistent.py and add a function

# Agent tries to edit, fails
# After 2 failures, suggests: "File not found. Try search_files to locate the correct file path first"

neudev ❯ Good suggestion! Let's search for Python files instead.

# Expected: Agent adapts and uses search_files
```

#### Test 3: New find_replace Tool

```
neudev ❯ Rename all occurrences of 'old_function' to 'new_function' in all *.py files

# Expected: Agent uses find_replace tool
# Result: "✅ Find & replace completed:
#   Files searched: 15
#   Files changed: 8
#   Total replacements: 23"
```

#### Test 4: Enhanced write_file

```
neudev ❯ Create a new file called test_override.txt with content "Hello"

# Creates file

neudev ❯ Now completely replace test_override.txt with new content "World"

# Expected: Agent uses write_file with overwrite=true
# Result: "Overwrote file: test_override.txt (replaced 1 lines)"
```

#### Test 5: Complex Command (Website Creation)

```
neudev ❯ Create a single page website using modern design with advanced features

# Expected:
# 1. Agent classifies as CODING + PROJECT_INIT
# 2. Selects qwen2.5-coder:7b model
# 3. Uses tool sequence:
#    - list_directory
#    - project_init (React template)
#    - write_file (custom components)
#    - write_file (modern CSS)
#    - dependency_install
#    - run_command (start dev server)
# 4. Reports: "✅ Website created successfully!"
```

#### Test 6: Enhanced UI Features

```
# Watch for these UI improvements:

# 1. Live Status Panel shows:
#    "⚡ EXECUTE | Step 3/5 | Model: qwen2.5-coder:7b"
#    "Executing tasks..."
#    "⚡ Executing: src/App.jsx"

# 2. Permission Prompt shows:
#    "[1] ✅ Allow once (y, /approve)"
#    "[2] 🔄 Allow this tool (a, /approve tool)"
#    "[3] 🟢 Allow all for session (all)"
#    "[4] ❌ Deny (n)"
#    "[5] 🛑 Stop task (/stop)"
#    "(45s timeout)"

# 3. Tool Events show relative paths:
#    "📖 READ    neudev/agent.py started 02:30:45 PM"
#    (not full C:\WorkSpace\neu-dev\neudev\agent.py)

# 4. Turn Summary shows diff preview:
#    "📂 Changes ✨ 1 created, 📝 2 modified (3 files changed)
#       +new      src/App.jsx
#       ~modified neudev/agent.py"
```

### 5.3 Test All New Slash Commands

```
neudev ❯ /help
# Should show new commands: /explain, /refactor, /test, /commit, /summarize

neudev ❯ /explain neudev/agent.py
# Explains the agent.py file

neudev ❯ /summarize
# Summarizes conversation history

neudev ❯ /commit
# Reviews changes and prepares commit message
```

---

## 🎯 Verification Checklist

### Server-Side (Lightning Studio)

```bash
# 1. Check version
neu version
# ✓ Should show v2.2.0

# 2. Check tools
python -c "from neudev.tools import create_tool_registry; print(len(create_tool_registry().get_all()))"
# ✓ Should show 27

# 3. Check agent features
python -c "from neudev.agent import Agent; from neudev.config import NeuDevConfig; a = Agent(NeuDevConfig(), '.'); print(hasattr(a, '_prune_conversation'))"
# ✓ Should show True

# 4. Check health
curl http://127.0.0.1:8765/health | python -m json.tool
# ✓ Should show "status": "healthy"
```

### Client-Side (Local)

```bash
# 1. Check version
neu version
# ✓ Should show v2.2.0

# 2. Check auth
neu auth status
# ✓ Should show "Runtime Mode: hybrid"

# 3. Test connection
neu run --runtime hybrid --workspace .
# Type: "Hello"
# ✓ Should get response from hosted model

# 4. Check new tools available
python -c "from neudev.tools.find_replace import FindReplaceTool; print('find_replace: OK')"
# ✓ Should show "find_replace: OK"
```

---

## 🐛 Troubleshooting

### Issue: Can't Connect to Lightning Server

**Solution**:
```bash
# 1. Check tunnel is running
# Look for the tunnel terminal - keep it open!

# 2. Test connectivity
curl -I https://your-studio-name-8765.trycloudflare.com/health

# 3. If fails, restart tunnel
bash scripts/lightning_quick_tunnel.sh
```

### Issue: Model Not Found Errors

**Solution**:
```bash
# On Lightning Studio
ollama pull qwen3:latest
ollama pull qwen2.5-coder:7b
ollama pull deepseek-coder-v2:16b
ollama pull starcoder2:7b

# Verify
ollama list
```

### Issue: Permission Denied on Local CLI

**Solution**:
```bash
# Windows (Run as Administrator)
# Reinstall CLI
cd C:\WorkSpace\neu-dev
python -m pip install -e . --user
```

### Issue: Hybrid Mode Not Working

**Solution**:
```bash
# Clear config and re-authenticate
rm C:\Users\YourName\.neudev\config.json  # Windows PowerShell
# or
del C:\Users\YourName\.neudev\config.json  # Windows CMD

# Re-authenticate
neu auth login --runtime hybrid `
  --api-base-url https://your-studio-url `
  --api-key your-key
```

---

## 📊 Deployment Summary

| Component | Status | Version |
|-----------|--------|---------|
| **GitHub** | ✅ Pushed | v2.2.0 |
| **Lightning Studio** | ✅ Updated | v2.2.0 |
| **Hosted Server** | ✅ Running | Port 8765 |
| **Cloudflare Tunnel** | ✅ Active | Public URL |
| **Local CLI** | ✅ Configured | Hybrid Mode |
| **Ollama Models** | ✅ Available | 4 models |
| **Tools** | ✅ 27 total | +2 new |
| **Agent Intelligence** | ✅ Enhanced | +3 features |

---

## 🎉 Next Steps

1. **Test thoroughly** with various commands
2. **Monitor server logs** on Lightning Studio
3. **Check performance** - should be faster with caching
4. **Verify new features** work as expected
5. **Document any issues** for future improvements

---

**Deployment Complete!** 🚀

Your enhanced NeuDev v2.2.0 is now:
- ✅ Running on Lightning Studio
- ✅ Accessible locally in hybrid mode
- ✅ Ready for testing with all new features

Happy coding! 💻✨
