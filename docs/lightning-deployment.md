# Lightning Deployment

This repository now includes a repeatable hosted deployment path for Lightning Studio.

## Files

- `Dockerfile`
- `scripts/lightning_entrypoint.sh`
- `.env.lightning.example`
- `scripts/lightning_bootstrap.sh`

## Recommended hosted policy

- Keep `NEUDEV_HOSTED_RUN_COMMAND_MODE=restricted`
- Expose only the NeuDev API ports, not Ollama itself
- Keep `NEUDEV_BOOTSTRAP=0` for normal container restarts after the environment is already prepared

## Environment variables

Copy `.env.lightning.example` and set at least:

- `NEUDEV_API_KEY`
- `NEUDEV_WORKSPACE`
- `NEUDEV_SESSION_STORE`
- `NEUDEV_OLLAMA_HOST`

`.env.lightning.example` is intended for direct Lightning shell startup. If you use Docker, override the workspace and session-store paths for the container filesystem.

Optional controls:

- `NEUDEV_HOSTED_RUN_COMMAND_MODE=restricted|permissive|disabled`
- `NEUDEV_HOSTED_RUN_COMMAND_ALLOWLIST=comma,separated,extra,commands`
- `NEUDEV_AUTO_PERMISSION=1`
- `NEUDEV_DISABLE_WEBSOCKET=1`
- `NEUDEV_BOOTSTRAP=1`

## Container build

```bash
docker build -t neudev-lightning .
```

## Container run

```bash
docker run --rm -it \
  --env-file .env.lightning.example \
  -e NEUDEV_WORKSPACE=/workspace/neu-dev \
  -e NEUDEV_SESSION_STORE=/workspace/.neudev/hosted_sessions \
  -e NEUDEV_OLLAMA_HOST=http://host.docker.internal:11434 \
  -p 8765:8765 \
  -p 8766:8766 \
  neudev-lightning
```

## Direct Studio startup

If you are not using Docker, the same entrypoint behavior can be reproduced with:

```bash
export NEUDEV_API_KEY=YOUR_API_KEY
export NEUDEV_WORKSPACE="$PWD"
export NEUDEV_SESSION_STORE="$HOME/.neudev/hosted_sessions"
export NEUDEV_OLLAMA_HOST="http://127.0.0.1:11434"
export NEUDEV_HOSTED_RUN_COMMAND_MODE=restricted
export NEUDEV_BOOTSTRAP=1
bash scripts/lightning_entrypoint.sh
```

The entrypoint now launches `python -m neudev.cli` from the repo root, which avoids failures caused by stale global `neu` installs in another Python environment.

## Local user install

Users connecting to Lightning can install the local CLI with either:

```bash
npm install -g .
```

or:

```bash
python -m pip install "git+https://github.com/papusethy15-cloud/neudev-cli.git"
```

Then save hosted auth once:

```bash
neu auth login --runtime remote --api-base-url https://YOUR-HOSTED-ENDPOINT --api-key YOUR_API_KEY
neu run --runtime remote
```

If you publish the npm launcher package publicly, users can replace `npm install -g .` with:

```bash
npm install -g neudev-cli
```

## Hybrid safety controls

Hybrid inference now enforces two client-side safeguards before local context is sent to Lightning:

- sensitive-looking keys and bearer tokens are redacted when `hybrid_redact_secrets` is enabled
- oversized inference payloads are rejected locally when they exceed `hybrid_max_payload_bytes`

Default values come from `neudev/config.py`:

- `hybrid_redact_secrets = true`
- `hybrid_max_payload_bytes = 262144`
