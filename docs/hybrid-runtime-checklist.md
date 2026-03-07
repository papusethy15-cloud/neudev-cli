# Hybrid Runtime Checklist

## Objective

Implement a `hybrid` runtime where the workspace and tools stay local while Lightning provides only model inference.

## Checklist

- [x] Add `hybrid` to `VALID_RUNTIME_MODES` in `neudev/config.py`
- [x] Add CLI flag support for `neu run --runtime hybrid`
- [x] Decide whether hybrid reuses `api_base_url` / `api_key` or adds separate config keys
- [x] Add `Agent(..., llm_client=...)` injection support in `neudev/agent.py`
- [x] Create `neudev/hosted_llm.py`
- [x] Implement hosted `list_models()` client call
- [x] Implement hosted `switch_model()` client path with explicit `auto` support
- [x] Implement hosted `chat_with_tools()` client path
- [x] Implement hosted `chat_with_fallback()` client path
- [x] Reuse local `model_routing.py` for auto routing in hybrid mode
- [x] Add thin hosted inference endpoints in `neudev/server.py`
- [x] Keep current full `remote` session endpoints unchanged
- [x] Add hybrid startup flow in `neudev/cli.py`
- [x] Show local workspace path in the hybrid banner
- [x] Show hosted inference endpoint in `/config`
- [x] Make `/models` in hybrid include `auto`
- [x] Make `/clear`, `/remove`, `/history` stay local in hybrid
- [x] Keep local permission prompts in hybrid
- [x] Add tests for hosted LLM client auth and error handling
- [x] Add tests for hybrid runtime local file edits
- [ ] Add tests for hybrid runtime local command execution
- [ ] Add regression tests for current `local` mode
- [x] Add regression tests for current `remote` mode
- [x] Update `README.md` with the new runtime shape
- [x] Add a Lightning deployment section specifically for hybrid inference hosting

## First Executable Milestone

The first useful milestone is complete when all of these are true:

- [x] `neu run --runtime hybrid --workspace <local repo>` starts
- [x] the local banner shows the local repo path
- [x] `/config` reports `hybrid`
- [x] one local file can be read and edited through the normal tool flow
- [x] the model response came from Lightning, not local Ollama

## Release Gate

Do not call hybrid ready until:

- [x] the CLI edits a local repo successfully
- [x] Lightning is only used for inference
- [x] `auto` model routing works
- [x] at least one end-to-end hybrid test passes
- [x] current `local` and `remote` tests still pass
