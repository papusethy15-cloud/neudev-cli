# Hybrid Runtime Plan

## Goal

Add a new `hybrid` runtime mode where:

- the CLI runs on the user's local machine
- the local machine workspace is the real coding workspace
- file tools, command tools, tests, permissions, and undo stay local
- Lightning hosts only the model backend and GPU inference
- the local CLI talks to Lightning through an authenticated API

This is different from the current `remote` mode, where the entire agent runtime and workspace live on Lightning.

## Why This Is Needed

The current project supports two runtime shapes:

- `local`: local workspace, local tools, local Ollama
- `remote`: remote workspace, remote tools, remote Ollama

The desired product shape is:

- `hybrid`: local workspace, local tools, remote model backend

This solves the main product requirement:

- users can install the CLI on their own machine
- users can work directly on their own repo
- heavy inference still runs on the Lightning GPU machine

## Current Code Constraints

The following parts already exist and should be reused:

- `neudev/agent.py`
  - local agent loop
  - local tool execution
  - planner / executor / reviewer orchestration
- `neudev/cli.py`
  - local and remote runtime startup flow
  - slash command UI
- `neudev/config.py`
  - runtime config persistence
- `neudev/server.py`
  - hosted API server
  - API key auth
  - Lightning deployment shape
- `neudev/remote_api.py`
  - authenticated client to hosted API
- `neudev/llm.py`
  - current Ollama-backed LLM interface used by `Agent`
- `neudev/model_routing.py`
  - auto routing and specialist role selection

The most important architectural constraint is:

- `Agent` currently assumes its `llm` object behaves like `OllamaClient`

That means the hybrid implementation should avoid changing the agent loop heavily. The clean path is to add a new LLM client class that matches the existing `OllamaClient` interface closely.

## Target Architecture

### Local Side

The local CLI in `hybrid` mode should:

- create a normal local `Agent`
- bind the agent to the local workspace
- keep the local tool registry unchanged
- keep local permission prompts unchanged
- keep local session history and undo unchanged
- replace only the model backend with a hosted inference client

### Lightning Side

Lightning should host:

- the Ollama daemon
- pulled models
- a thin inference API layer
- API key authentication
- model listing and optional model switching endpoints

Lightning should not host:

- the user's workspace
- local file editing tools
- local shell command execution

## Runtime Behavior

### `local`

- local agent
- local tools
- local Ollama

### `remote`

- hosted agent
- hosted tools
- hosted workspace
- hosted Ollama

### `hybrid`

- local agent
- local tools
- local workspace
- remote Lightning inference API
- remote Ollama on Lightning

## Phase Plan

## Phase 1: Config And Runtime Wiring

Add a new runtime mode:

- extend `VALID_RUNTIME_MODES` to include `hybrid`
- add any hybrid-specific config keys needed

Recommended config additions:

- `hybrid_api_base_url`
  - optional alias of `api_base_url`, if you want clean separation
- `hybrid_api_key`
  - optional alias of `api_key`
- `hybrid_stream_transport`
  - optional, only if inference streaming is added early

CLI changes:

- add `neu run --runtime hybrid`
- use the current local workspace as the active workspace
- prompt for API base URL and API key if missing
- display a clear status block:
  - local workspace
  - hosted inference endpoint
  - model mode
  - orchestration mode

Acceptance criteria:

- `neu run --runtime hybrid --workspace C:\path\to\repo` starts against the local repo
- no remote workspace path is shown in the banner

## Phase 2: Thin Hosted Inference API

Add Lightning server endpoints dedicated to model inference only.

Recommended endpoints:

- `GET /health`
  - already exists, reuse it
- `GET /v1/inference/models`
  - list installed models available on Lightning
- `POST /v1/inference/chat`
  - run one model call with messages, tools, and routing hints
- `POST /v1/inference/chat_fallback`
  - optional shortcut if you want the server to own fallback behavior

Recommended response shape for `/v1/inference/chat`:

- `content`
- `thinking`
- `tool_calls`
- `done`
- `native_tools_supported`
- `model`
- `route_reason`

This should intentionally mirror the shape already produced by `OllamaClient.chat_with_tools()`.

Acceptance criteria:

- a local test client can call Lightning and receive the same schema that the agent already expects

## Phase 3: Hosted LLM Client For Hybrid Mode

Create a new client, for example:

- `neudev/hosted_llm.py`

This client should present the same practical interface as `OllamaClient`:

- `list_models()`
- `switch_model()`
- `preview_auto_model()`
- `chat_with_tools()`
- `chat_with_fallback()`
- `select_agent_team()`
- `get_display_model()`

Implementation notes:

- `list_models()` should call Lightning, then apply the same role labeling logic locally
- `preview_auto_model()` should reuse `model_routing.py` locally after fetching the hosted model catalog
- `switch_model()` should support `auto`
- `chat_with_tools()` should call the hosted inference endpoint
- `chat_with_fallback()` can remain local logic if the client can request a specific model from Lightning per call
- `select_agent_team()` should stay local if possible

This keeps routing logic near the local agent and avoids moving project context orchestration back to the server.

Acceptance criteria:

- `Agent` can use the hosted client without changes to the tool loop

## Phase 4: Agent Injection Without Breaking Local Mode

Refactor agent construction so the LLM backend can be injected cleanly.

Preferred approach:

- keep `Agent(config, workspace)` behavior unchanged for local mode
- add optional `llm_client` injection:
  - `Agent(config, workspace, llm_client=None)`
- if `llm_client` is provided, use it instead of constructing `OllamaClient(config)`

Why this matters:

- hybrid mode should reuse the existing local agent without monkeypatching internals after creation

Acceptance criteria:

- local mode still works exactly as before
- hybrid mode can inject a hosted LLM client

## Phase 5: CLI Hybrid UX

Add hybrid-specific UX to the local CLI.

Startup behavior:

- banner should say `hybrid`
- workspace should show the local repo path
- status block should show:
  - local tools active
  - hosted inference connected
  - current routed model or fixed model

Slash command expectations:

- `/config`
  - show local workspace
  - show hosted inference URL
  - show hosted model mode
- `/models`
  - list Lightning-hosted models
  - allow `auto`
- `/history`
  - remain local
- `/remove`
  - remain local
- `/clear`
  - remain local
- `/sessions`
  - probably not needed for hybrid in the first version

Acceptance criteria:

- the user can point the CLI at `C:\WorkSpace\seo-audit-tool`
- the CLI edits local files while using Lightning-hosted models

## Phase 6: Security And Privacy Controls

Hybrid mode changes what data leaves the local machine.

Data sent to Lightning:

- user prompt
- selected local file contents
- tool definitions
- planner/reviewer execution context

Data that must stay local:

- actual file writes
- shell commands
- test execution
- environment secrets from local `.env` files unless explicitly read and sent

Required controls:

- keep API key auth
- never expose raw Ollama publicly
- keep file operations local
- add request size limits for hosted inference
- consider redaction rules for known secret patterns before inference calls

Recommended follow-up:

- add a privacy notice in hybrid mode startup
- add a future `--allow-send-secrets` opt-in only if ever needed

## Phase 7: Streaming Improvements

Hybrid mode can launch with plain request/response inference first.

Then add streaming later:

- inference SSE from Lightning to local CLI
- local CLI merges remote text/thinking with local tool status

Important UI rule:

- local tool events must remain authoritative because tools run locally
- hosted text/thinking should not imply remote file execution

Acceptance criteria:

- streaming does not confuse local-vs-remote responsibility

## Phase 8: Testing

Add focused tests by layer.

### Unit tests

- config supports `hybrid`
- hosted LLM client handles:
  - auth
  - list models
  - `auto`
  - fallback routing
  - errors
- agent injection path works

### Integration tests

- hybrid runtime starts with a local fixture workspace
- local file edits happen on the local fixture repo
- model calls hit the fake hosted inference API
- local permission prompts still gate destructive tools

### Regression tests

- local runtime still passes
- remote runtime still passes
- current hosted Lightning server mode still passes

## Recommended File Changes

Likely file additions:

- `neudev/hosted_llm.py`
- `tests/test_hosted_llm.py`
- `docs/hybrid-runtime-plan.md`
- `docs/hybrid-runtime-checklist.md`

Likely file modifications:

- `neudev/config.py`
- `neudev/cli.py`
- `neudev/agent.py`
- `neudev/server.py`
- `README.md`

## Suggested Implementation Order

1. Add `hybrid` to config and CLI flags
2. Add thin hosted inference endpoints to `server.py`
3. Create `HostedLLMClient`
4. Allow `Agent` LLM injection
5. Wire `hybrid` CLI startup to local agent plus hosted LLM client
6. Add `/models auto` support explicitly in remote and hybrid UI
7. Add tests
8. Update README and deployment docs

## Non-Goals For The First Hybrid Release

- syncing the full local workspace to Lightning
- remote file execution in hybrid mode
- remote shell commands in hybrid mode
- collaborative multi-user hosted workspaces
- long-term session persistence for hybrid inference history on Lightning

## Main Risks

### Risk 1: Prompt Payload Size

Large local files can make hosted inference requests heavy.

Mitigation:

- keep read operations selective
- avoid dumping whole repos into prompts
- add request size guards

### Risk 2: Local/Remote Responsibility Confusion

Users may think files are edited remotely when they are local.

Mitigation:

- show clear runtime and workspace labels
- show `hosted inference` rather than `remote workspace`

### Risk 3: Compatibility With Existing Agent Code

`Agent` expects an Ollama-like client.

Mitigation:

- make the hosted client match the same public interface
- avoid rewriting the tool loop

### Risk 4: Security Leakage

Local file contents are sent to Lightning for inference.

Mitigation:

- keep explicit auth
- document it clearly
- add future redaction safeguards

## Definition Of Done

Hybrid runtime is complete when:

- `neu run --runtime hybrid` works against a local repo
- the active workspace is local
- file edits and commands occur locally
- model inference occurs on Lightning
- `/models` can select hosted models and `auto`
- local permissions and undo still work
- local and remote runtimes remain unchanged
- tests cover the new path

## Recommended Immediate Next Step

Start with the smallest architecture-preserving slice:

1. add `hybrid` config and CLI mode
2. add LLM client injection to `Agent`
3. build a minimal hosted inference endpoint
4. prove one local repo edit in hybrid mode

That path minimizes rework and keeps the current remote mode intact.
