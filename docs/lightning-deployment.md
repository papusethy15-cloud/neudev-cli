# Lightning Deployment

This is the repeatable Lightning Studio path that matches the working deployment flow already validated against this repo.

## Recommended shape

Use direct Studio startup first.

- It keeps Ollama on the host where GPU access already exists.
- It avoids Docker-to-host networking problems around `127.0.0.1:11434`.
- It matches the public quick-tunnel flow that local `neu` clients already used successfully.

Use Docker only when you specifically need container isolation.

## Files

- `Dockerfile`
- `.env.lightning.example`
- `scripts/lightning_bootstrap.sh`
- `scripts/lightning_entrypoint.sh`
- `scripts/lightning_quick_tunnel.sh`

## Environment variables

Copy the example file and edit it:

```bash
cp .env.lightning.example .env.lightning
```

Set at least:

- `NEUDEV_API_KEY`
- `NEUDEV_WORKSPACE`
- `NEUDEV_SESSION_STORE`
- `NEUDEV_OLLAMA_HOST`

Useful optional controls:

- `NEUDEV_BOOTSTRAP=1` for first boot on a fresh Studio
- `NEUDEV_OLLAMA_MODELS=qwen3:latest qwen2.5-coder:7b deepseek-coder-v2:16b starcoder2:7b`
- `NEUDEV_INSTALL_OLLAMA=1`
- `NEUDEV_HOSTED_RUN_COMMAND_MODE=restricted|permissive|disabled`
- `NEUDEV_HOSTED_RUN_COMMAND_ALLOWLIST=comma,separated,extra,commands`
- `NEUDEV_AUTO_PERMISSION=1`
- `NEUDEV_DISABLE_WEBSOCKET=1`

`.env.lightning.example` is written for direct Studio startup. If you use Docker, override the workspace and session-store paths for the container filesystem.

## Direct Studio startup

Clone the repo:

```bash
git clone https://github.com/papusethy15-cloud/neudev-cli.git
cd neudev-cli
cp .env.lightning.example .env.lightning
```

Load the env file and bootstrap the machine:

```bash
set -a
source .env.lightning
set +a
export NEUDEV_BOOTSTRAP=1
bash scripts/lightning_entrypoint.sh
```

What bootstrap now does:

- installs NeuDev into the active Python environment
- installs Ollama automatically on Linux when missing and `NEUDEV_INSTALL_OLLAMA=1`
- starts `ollama serve` if the API is not already reachable
- pulls every model in `NEUDEV_OLLAMA_MODELS`
- runs the NeuDev unit test suite

Normal restarts after the first successful bootstrap:

```bash
set -a
source .env.lightning
set +a
export NEUDEV_BOOTSTRAP=0
bash scripts/lightning_entrypoint.sh
```

The entrypoint now fails early if `NEUDEV_OLLAMA_HOST` is unreachable, and it prints how many Ollama models are currently installed before it starts the hosted API.

## Health checks

From a second Lightning terminal:

```bash
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:11434/api/tags
```

Expected:

- `/health` returns `status: ok`
- `/api/tags` returns a model list, not `models: []`

## Public access with Cloudflare quick tunnels

If Lightning Studio does not expose public ports in the UI, use the included quick-tunnel helper from another terminal:

```bash
cd ~/neudev-cli
export NEUDEV_HTTP_PORT=8765
bash scripts/lightning_quick_tunnel.sh
```

The script downloads `cloudflared` to `~/bin/cloudflared` when needed and starts:

```bash
cloudflared tunnel --url http://127.0.0.1:$NEUDEV_HTTP_PORT
```

It will print a public URL like:

```text
https://example-name.trycloudflare.com
```

Important:

- keep the tunnel terminal open
- quick-tunnel URLs are temporary and change when the tunnel restarts
- if the URL changes, users must update `neu auth login` locally

## Local client connection

Windows PowerShell:

```powershell
$LIGHTNING_URL = "https://YOUR-TUNNEL.trycloudflare.com"
$API_KEY = "YOUR_REAL_SECRET_KEY"

Invoke-RestMethod "$LIGHTNING_URL/health" | ConvertTo-Json -Depth 5
neu auth login --runtime remote --api-base-url "$LIGHTNING_URL" --api-key "$API_KEY"
neu run --runtime remote --transport sse
```

Hybrid mode from a local machine:

```powershell
$LIGHTNING_URL = "https://YOUR-TUNNEL.trycloudflare.com"
$API_KEY = "YOUR_REAL_SECRET_KEY"

neu auth login --runtime hybrid --api-base-url "$LIGHTNING_URL" --api-key "$API_KEY"
neu run --runtime hybrid --transport sse --workspace "C:\path\to\your\repo"
```

Use `sse` first unless you have also exposed the WebSocket endpoint reliably.

## Docker path

Build:

```bash
docker build -t neudev-lightning .
```

Run:

```bash
docker run --rm -it \
  --env-file .env.lightning \
  --add-host=host.docker.internal:host-gateway \
  -e NEUDEV_WORKSPACE=/workspace/neu-dev \
  -e NEUDEV_SESSION_STORE=/workspace/.neudev/hosted_sessions \
  -e NEUDEV_OLLAMA_HOST=http://host.docker.internal:11434 \
  -p 8765:8765 \
  -p 8766:8766 \
  neudev-lightning
```

Docker is optional. Direct Studio startup is the simpler Lightning path.

## Recommended hosted policy

- Keep `NEUDEV_HOSTED_RUN_COMMAND_MODE=restricted`
- Expose only NeuDev, not Ollama itself
- Use `NEUDEV_BOOTSTRAP=0` for normal restarts
- Rotate the API key before real user traffic

## Hybrid safety controls

Hybrid inference enforces two client-side safeguards before local context is sent to Lightning:

- sensitive-looking keys and bearer tokens are redacted when `hybrid_redact_secrets` is enabled
- oversized inference payloads are rejected locally when they exceed `hybrid_max_payload_bytes`

Default values come from `neudev/config.py`:

- `hybrid_redact_secrets = true`
- `hybrid_max_payload_bytes = 262144`
