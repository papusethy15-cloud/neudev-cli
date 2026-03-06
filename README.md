# ⚡ NeuDev

NeuDev is a terminal-first AI coding agent built on top of Ollama.

The project now supports three runtime shapes:

- `local`: the CLI, agent, tools, and Ollama all run on the same machine
- `remote`: the user installs only the CLI locally, while the full agent runtime runs on a hosted server such as Lightning Studio
- `hybrid`: the CLI, agent, tools, and workspace stay local, while Lightning hosts only model inference

The current codebase already includes:

- A ReAct-style executor loop
- Automatic model routing for planning, coding, debugging, and repo analysis
- Multi-agent orchestration (`single`, `team`, `parallel`)
- Workspace analysis and project-memory persistence
- Smart repo tools for code search, editing, diagnostics, and diff review
- A rich interactive CLI for daily coding work

This README is meant to answer four questions clearly:

1. What this project does
2. How the codebase is organized
3. How to run it locally
4. How to host the agent on Lightning and use it from local machines

## 🚀 Current Capability Summary

NeuDev is already beyond a basic file-edit bot. The most important implemented capabilities are:

- **17 built-in tools** for reading, writing, searching, symbol lookup, diagnostics, and git review
- **Auto model routing** so `auto` can choose a better model for planning vs coding tasks
- **Planner / executor / reviewer orchestration**
- **Parallel preflight mode** where planning and pre-review run together
- **Live remote event streaming** over SSE with optional WebSocket transport
- **Persistent hosted sessions** that can survive Lightning restarts and be resumed by session ID
- **Workspace-safe path resolution** so tools stay inside the active repo
- **Project memory** so style and stack preferences can persist across sessions
- **External editor change detection** so recent manual edits are pulled back into context
- **Targeted changed-file diagnostics** for faster verification after edits
- **Text tool-call fallback parsing** for weaker models that cannot reliably use native tools

## 🧱 Project Structure

The core repository layout is:

| Path | Purpose |
|------|---------|
| `neudev/agent.py` | Main reasoning loop, tool execution, orchestration, planner/reviewer flow |
| `neudev/cli.py` | Interactive CLI, slash commands, startup flow, user-facing terminal UI |
| `neudev/llm.py` | Ollama REST client used by the hosted or local runtime |
| `neudev/hosted_llm.py` | Hosted inference client used by the hybrid runtime |
| `neudev/model_routing.py` | Capability presets and automatic planner/executor/reviewer model selection |
| `neudev/remote_api.py` | Thin HTTP/SSE/WebSocket client used by the local CLI in remote or hybrid mode |
| `neudev/server.py` | Hosted NeuDev API server with persisted sessions plus SSE and optional WebSocket streaming |
| `neudev/context.py` | Workspace scanning, component detection, convention inference, external change tracking |
| `neudev/project_memory.py` | Persistent memory for learned stack and style preferences |
| `neudev/session.py` | Session history, file backups, undo support, improvement suggestions |
| `neudev/permissions.py` | Permission prompts for destructive tools |
| `neudev/tools/` | Tool implementations |
| `tests/` | Unit tests for agent flow, model routing, workspace handling, and advanced tools |
| `scripts/lightning_bootstrap.sh` | Linux bootstrap helper for Lightning or similar GPU machines |

## 🔧 Built-in Tools

| Tool | Permission | Purpose |
|------|:----------:|---------|
| `read_file` | No | Read a file with optional line ranges |
| `read_files_batch` | No | Read multiple files in one call |
| `write_file` | Yes | Create or overwrite files |
| `edit_file` | Yes | Exact find/replace editing |
| `smart_edit_file` | Yes | Whitespace-tolerant fallback editing |
| `python_ast_edit` | Yes | Replace Python symbols structurally |
| `js_ts_symbol_edit` | Yes | Replace JS/TS symbols structurally |
| `delete_file` | Yes | Delete files |
| `search_files` | No | Search paths by name or glob |
| `symbol_search` | No | Find symbol definitions and references |
| `grep_search` | No | Search file contents |
| `list_directory` | No | Show directory trees |
| `run_command` | Yes | Run shell commands inside the workspace |
| `diagnostics` | Yes | Run syntax/tests/lint/typecheck with fallback commands |
| `changed_files_diagnostics` | Yes | Run targeted checks only for changed files |
| `git_diff_review` | No | Summarize local git changes for review |
| `file_outline` | No | Show code structure for supported files |

## 🧠 Model Strategy

NeuDev now recognizes official Ollama model families such as:

- `qwen3`
- `qwen2.5-coder`
- `deepseek-coder-v2`
- `deepseek-coder`
- `starcoder2`
- `codellama`
- `nomic-embed-text`

Recommended model roles:

| Role | Recommended Ollama model | Why |
|------|--------------------------|-----|
| Planner / reviewer | `qwen3:latest` | Best fit for repo analysis, orchestration, and tool-heavy reasoning |
| Main executor | `qwen2.5-coder:7b` | Best fit for direct coding and implementation tasks |
| Heavy refactor fallback | `deepseek-coder-v2:16b` | Useful for larger cross-file refactors on stronger GPUs |
| Small optional fallback | `starcoder2:7b` | Useful when resources are limited or quick edits are enough |

Notes:

- If you only install one model, NeuDev can still run, but multi-role routing becomes less useful.
- The repo keeps backward compatibility for older `qwen3.5` names in code, but the recommended Ollama downloads should use current official model families such as `qwen3`.
- On smaller local machines, install a smaller `qwen3` tag instead of `qwen3:latest` if needed.

## 📦 Ollama Model Downloads

Minimum recommended pulls:

```bash
ollama pull qwen3:latest
ollama pull qwen2.5-coder:7b
```

Recommended full set for local + Lightning:

```bash
ollama pull qwen3:latest
ollama pull qwen2.5-coder:7b
ollama pull deepseek-coder-v2:16b
ollama pull starcoder2:7b
```

Useful Ollama commands:

```bash
ollama serve
ollama list
ollama ps
```

Official references:

- Ollama CLI reference: https://docs.ollama.com/cli
- Ollama Linux install: https://docs.ollama.com/linux
- Qwen 3 library page: https://ollama.com/library/qwen3
- Qwen 2.5 Coder library page: https://ollama.com/library/qwen2.5-coder
- DeepSeek Coder V2 library page: https://ollama.com/library/deepseek-coder-v2
- StarCoder2 library page: https://ollama.com/library/starcoder2

## 💻 Local Install and Development

### 1. Install the CLI on a local machine

Node.js global install from the local repo:

```bash
npm install -g .
neu version
```

After you publish to npm, the same flow becomes:

```bash
npm install -g neudev-cli
neu version
```

The npm package installs a thin `neu` launcher and bootstraps the Python runtime underneath. If the Python package already exists locally, the npm install path reinstalls or upgrades it.

Python install from this repository:

Windows PowerShell or `cmd`:

```bash
git clone https://github.com/papusethy15-cloud/neudev-cli.git
cd neudev-cli
python -m pip install --upgrade pip
python -m pip install -e .
neu version
```

Linux, macOS, or WSL:

```bash
git clone https://github.com/papusethy15-cloud/neudev-cli.git
cd neudev-cli
python3 -m pip install --upgrade pip
python3 -m pip install -e .
neu version
```

If you want the Python install straight from git without cloning first:

```bash
python -m pip install "git+https://github.com/papusethy15-cloud/neudev-cli.git"
```

### 2. One-time hosted auth setup on a user machine

If the user will connect to Lightning in `remote` or `hybrid` mode, store the hosted endpoint and API key once:

```bash
neu auth login --runtime remote --api-base-url https://YOUR-HOSTED-ENDPOINT --api-key YOUR_API_KEY
```

That command saves the values in `~/.neudev/config.json`, so the user does not need to pass `--api-key` on every run.

Short alias:

```bash
neu login --runtime remote --api-base-url https://YOUR-HOSTED-ENDPOINT --api-key YOUR_API_KEY
```

You can still override saved settings per session with environment variables:

```bash
set NEUDEV_API_BASE_URL=https://YOUR-HOSTED-ENDPOINT
set NEUDEV_API_KEY=YOUR_API_KEY
```

Linux, macOS, or WSL:

```bash
export NEUDEV_API_BASE_URL="https://YOUR-HOSTED-ENDPOINT"
export NEUDEV_API_KEY="YOUR_API_KEY"
```

### 3. Run the full local agent in local mode

```bash
ollama serve
ollama pull qwen3:latest
ollama pull qwen2.5-coder:7b
neu run --runtime local --workspace . --model auto --agents parallel --language English
```

### 4. Run the thin client against Lightning

Remote hosted runtime:

```bash
neu run --runtime remote
```

Hybrid runtime with local workspace and hosted inference:

```bash
neu run --runtime hybrid --workspace /path/to/local/repo
```

The local machine does not need Ollama or downloaded models for `remote` or `hybrid`.

## 🧪 Verification

Primary verification commands:

```bash
python -m unittest discover -s tests -q
python -m pytest -q
```

At the current state of this repository, both passed during validation.

Packaging checks:

```bash
npm pack --dry-run
```

## 💬 CLI Usage

Local runtime:

```bash
neu run --runtime local --workspace /path/to/project
neu run --runtime local --model auto
neu run --runtime local --model qwen2.5-coder:7b
```

Remote client runtime:

```bash
neu auth login --runtime remote --api-base-url https://YOUR-HOSTED-ENDPOINT --api-key YOUR_API_KEY
neu auth status
neu run --runtime remote --api-base-url https://YOUR-HOSTED-ENDPOINT --api-key YOUR_API_KEY
neu run --runtime remote --transport auto
neu run --runtime remote --session-id YOUR_SESSION_ID
neu run --runtime remote --workspace .
neu run --runtime hybrid --workspace /path/to/local/repo --api-base-url https://YOUR-HOSTED-ENDPOINT --api-key YOUR_API_KEY
```

Hosted server on Lightning:

```bash
neu serve --host 0.0.0.0 --port 8765 --ws-port 8766 --workspace /teamspace/studios/this_studio/neudev-cli --api-key YOUR_API_KEY
```

Version:

```bash
neu version
```

Auth and cleanup:

```bash
neu auth login --runtime remote --api-base-url https://YOUR-HOSTED-ENDPOINT --api-key YOUR_API_KEY
neu auth status
neu auth logout
neu auth logout --all
neu uninstall
neu uninstall --purge-config
```

Install and release notes:

```bash
npm install -g .
python -m pip install .
```

Slash commands:

| Command | Action |
|---------|--------|
| `/help` | Show command help |
| `/models` | List or switch models |
| `/sessions` | List resumable hosted sessions |
| `/clear` | Clear conversation history |
| `/remove` | Undo the last file change |
| `/history` | Show session actions |
| `/config` | Show current config |
| `/agents` | Change orchestration mode |
| `/language` | Change response language |
| `/version` | Show version |
| `/close` | Close the current hosted session |
| `/exit` | Disconnect and preserve the hosted session |

## ⚙️ Configuration

NeuDev stores config in `~/.neudev/config.json`.

The fastest way to create that config for hosted usage is:

```bash
neu auth login --runtime remote --api-base-url https://YOUR-HOSTED-ENDPOINT --api-key YOUR_API_KEY
```

Example:

```json
{
  "runtime_mode": "remote",
  "api_base_url": "https://YOUR-HOSTED-ENDPOINT",
  "api_key": "YOUR_API_KEY",
  "remote_workspace": ".",
  "websocket_base_url": "wss://YOUR-HOSTED-WS-ENDPOINT/v1/stream",
  "stream_transport": "auto",
  "model": "auto",
  "temperature": 0.7,
  "max_tokens": 4096,
  "ollama_host": "http://localhost:11434",
  "max_iterations": 20,
  "command_timeout": 30,
  "agent_mode": "parallel",
  "multi_agent": true,
  "auto_permission": false,
  "response_language": "English"
}
```

Runtime modes:

- `local`: run the agent and tools on the same machine as the CLI
- `remote`: use the local CLI as a thin client against a hosted NeuDev server
- `hybrid`: keep the workspace and tools local while Lightning provides model inference only

Remote streaming transports:

- `auto`: prefer WebSocket when the hosted server advertises it, otherwise use SSE
- `sse`: use server-sent events over the main HTTP port
- `websocket`: force the secondary WebSocket stream endpoint

Agent modes:

- `single`: executor only
- `team`: planner -> executor -> reviewer
- `parallel`: planner + pre-review in parallel, then executor + reviewer

Project memory is stored under `~/.codex/memories/neudev/`.

Environment variables override saved config values:

- `NEUDEV_API_BASE_URL`
- `NEUDEV_API_KEY`
- `NEUDEV_WS_BASE_URL`

Useful local account commands:

- `neu auth status`
- `neu auth logout`
- `neu auth logout --all`
- `neu uninstall --purge-config`

## ☁️ Lightning Deployment

The intended production architecture now supports two hosted shapes:

### Full remote runtime

1. Users install `neu` locally
2. Users enter your hosted API base URL and API key
3. The local CLI sends requests to your hosted NeuDev server
4. The hosted NeuDev server runs the full `Agent`
5. Ollama and all pulled models stay on the Lightning machine
6. File tools, git actions, diagnostics, and shell commands run on Lightning, not on the user laptop
7. Live tool/phase/status output streams back to the local CLI over SSE or WebSocket
8. Hosted session snapshots persist on Lightning and can be resumed with `--session-id`

### Hybrid runtime

1. Users install `neu` locally
2. Users enter your hosted API base URL and API key
3. The local CLI runs the `Agent` against the user's local repo
4. Local tools, permissions, undo, git actions, and diagnostics stay on the user machine
5. Lightning exposes only hosted inference endpoints backed by Ollama and the pulled models
6. The local CLI sends model requests to Lightning but never moves the workspace there

Lightning-oriented references:

- Lightning Studio docs: https://lightning.ai/docs/studios
- Lightning guide on installing dependencies and downloading data in Studio: https://lightning.ai/docs/studios/guide/get-started-with-code
- Lightning public port guide: https://lightning.ai/docs/overview/ai-studio/deploy-on-public-ports

### Fastest Lightning Studio deploy path

This repository now includes deployment assets for Lightning:

- `Dockerfile`
- `.env.lightning.example`
- `scripts/lightning_entrypoint.sh`
- `docs/lightning-deployment.md`

Recommended update cycle on the Lightning machine:

```bash
git clone https://github.com/papusethy15-cloud/neudev-cli.git
cd neudev-cli
cp .env.lightning.example .env.lightning
```

Edit `.env.lightning` and set at least:

- `NEUDEV_API_KEY`
- `NEUDEV_WORKSPACE`
- `NEUDEV_SESSION_STORE`
- `NEUDEV_OLLAMA_HOST`

Then either run the container path:

```bash
docker build -t neudev-lightning .
docker run --rm -it --env-file .env.lightning -p 8765:8765 -p 8766:8766 neudev-lightning
```

Or run directly inside Lightning Studio:

```bash
set -a
source .env.lightning
set +a
bash scripts/lightning_entrypoint.sh
```

After you push new commits from local development, update Lightning with:

```bash
cd /path/to/neudev-cli
git pull origin main
bash scripts/lightning_entrypoint.sh
```

### Release and publish

If you want users to install with `npm install -g neudev-cli`, you must publish the npm launcher package first.

Release checklist:

```bash
python -m unittest discover -s tests -q
python -m pytest -q
npm pack --dry-run
```

Python package build:

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
```

npm publish:

```bash
npm publish --access public
```

Full release notes are in `docs/release.md`.

### Recommended Lightning bootstrap flow

Clone the repo on the Lightning machine:

```bash
git clone https://github.com/papusethy15-cloud/neudev-cli.git
cd neudev-cli
```

Install Ollama first using the official Linux instructions if it is not already available on the image:

- https://docs.ollama.com/linux

Then run the included bootstrap script:

```bash
bash scripts/lightning_bootstrap.sh
```

That script will:

- install NeuDev into the active Python environment
- start `ollama serve` if it is not already running
- pull the recommended models
- run the unit test suite

After bootstrap, start the hosted NeuDev API:

```bash
export NEUDEV_API_KEY="YOUR_API_KEY"
neu serve \
  --host 0.0.0.0 \
  --port 8765 \
  --ws-port 8766 \
  --workspace "$PWD" \
  --api-key "$NEUDEV_API_KEY" \
  --session-store "$HOME/.neudev/hosted_sessions" \
  --ollama-host http://127.0.0.1:11434 \
  --model auto \
  --agents parallel
```

Then from a local user machine:

```bash
neu run \
  --runtime remote \
  --api-base-url https://YOUR-LIGHTNING-ENDPOINT \
  --api-key YOUR_API_KEY \
  --transport auto
```

Hybrid local-workspace mode from a user machine:

```bash
neu run \
  --runtime hybrid \
  --workspace /path/to/local/repo \
  --api-base-url https://YOUR-LIGHTNING-ENDPOINT \
  --api-key YOUR_API_KEY
```

Important deployment note:

- Do not expose Ollama directly to the internet.
- Expose only the hosted NeuDev API server.
- Keep Ollama bound to `127.0.0.1` or a private interface on Lightning.
- If you expose WebSocket streaming, publish the WebSocket port through Lightning as well or keep the client on SSE.

### Hosted session behavior

- Remote sessions are persisted under the hosted session store on the Lightning machine.
- The local CLI now preserves hosted sessions on `/exit`; use `/close` only when you want to delete a session.
- Users can reconnect with `neu run --runtime remote --session-id YOUR_SESSION_ID`.
- The local client auto-detects the hosted WebSocket endpoint from `/health` and falls back to SSE when WebSocket is unavailable.

### Environment variables for Lightning bootstrap

The bootstrap script supports:

- `PYTHON_BIN`
- `OLLAMA_HOST`
- `NEUDEV_OLLAMA_MODELS`
- `OLLAMA_LOG_FILE`

## 📋 Requirements

### Python package requirements

Runtime dependencies from `requirements.txt`:

- `ollama>=0.4.0`
- `rich>=14.0.0`
- `prompt_toolkit>=3.0.0`
- `websockets>=15.0.1`

### System/runtime requirements

- Python 3.10+
- Git
- Ollama installed and running
- At least one chat-capable Ollama model
- Enough disk space for model weights
- Enough VRAM or RAM for the selected models on the target machine

## 🔍 Implementation Assessment

After reviewing the current codebase, the project is already strong in these areas:

- Tool coverage is much richer than a basic coding CLI
- The agent loop is now aware of planning, review, and verification phases
- Workspace context and project memory are meaningful differentiators
- The test suite covers routing, orchestration, workspace handling, and several smart tools

The highest-value next implementations are:

1. **Lightning-native deployment assets**
   Add a Dockerfile, Lightning app/studio provisioning config, and a repeatable remote startup command instead of relying on manual machine setup.

2. **Stronger JS/TS parsing**
   `js_ts_symbols.py` is regex-based. For larger TypeScript projects, this should move to a real parser or AST-backed approach.

3. **Safer command execution**
   `run_command` still uses `shell=True` with a small blocklist. For remote/shared environments this should move toward stricter sandboxing or command policy layers.

4. **Richer CI**
   Add lint/type/test automation in CI so local changes are validated before pushing to Lightning.

5. **Model catalog expansion**
   Add explicit routing profiles for newer official Ollama coding models beyond the currently tuned families.

6. **Deployment observability**
   Add structured logs and health checks so Lightning failures are easier to diagnose after pull/update cycles.

## 🛣️ Suggested Workflow

Recommended day-to-day workflow:

1. Develop and verify locally with `neu run --runtime local`
2. Run `python -m unittest discover -s tests -q`
3. Commit and push to git
4. Pull on Lightning
5. Run `bash scripts/lightning_bootstrap.sh`
6. Start the hosted API with `neu serve`
7. Use `neu run --runtime remote` when you want the full hosted agent
8. Use `neu run --runtime hybrid` when you want local coding with Lightning-hosted models

## 📄 License

MIT
