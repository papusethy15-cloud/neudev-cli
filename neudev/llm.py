"""Ollama LLM client wrapper for NeuDev - uses REST API directly for Python 3.14 compat."""

import json
import socket
import time
import urllib.request
import urllib.error
from typing import Generator, Optional

from neudev.config import NeuDevConfig
from neudev.model_routing import (
    AgentTeam,
    LEGACY_DEFAULT_MODEL,
    build_agent_team,
    get_model_role_label,
    is_chat_capable_model,
    preview_best_model,
    rank_models,
    should_enable_thinking,
)
from neudev.tool_call_parser import extract_text_tool_calls


class LLMError(Exception):
    """Base LLM error."""
    pass


class ConnectionError(LLMError):
    """Cannot connect to Ollama."""
    pass


class ModelNotFoundError(LLMError):
    """Model not available."""
    pass


class ToolsNotSupportedError(LLMError):
    """Model does not support tool/function calling."""
    pass


class OllamaClient:
    """REST API wrapper for Ollama chat + tool calling."""

    def __init__(self, config: NeuDevConfig):
        self.config = config
        self.model = config.model
        self.base_url = config.ollama_host.rstrip("/")
        self.last_used_model: str | None = None
        self.last_route_reason: str = ""
        self._test_connection()

    def _test_connection(self) -> None:
        """Test connection to Ollama."""
        try:
            self._api_get("/api/tags")
        except Exception as e:
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.base_url}.\n"
                f"Is Ollama running? Start it with: ollama serve\n"
                f"Error: {e}"
            )

    def _api_get(self, endpoint: str) -> dict:
        """Make a GET request to Ollama API."""
        url = f"{self.base_url}{endpoint}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise ConnectionError(f"Cannot connect to Ollama: {e}")
        except json.JSONDecodeError:
            raise LLMError("Invalid response from Ollama")

    def _api_post(self, endpoint: str, data: dict, stream: bool = False):
        """Make a POST request to Ollama API."""
        url = f"{self.base_url}{endpoint}"
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            resp = urllib.request.urlopen(req, timeout=300)
            if stream:
                return resp  # Return for streaming
            body = resp.read().decode("utf-8")
            return json.loads(body)

        except urllib.error.HTTPError as e:
            # Read the error body from Ollama for the real error message
            try:
                error_body = e.read().decode("utf-8")
                try:
                    error_json = json.loads(error_body)
                    error_msg = error_json.get("error", error_body)
                except json.JSONDecodeError:
                    error_msg = error_body
            except Exception:
                error_msg = str(e)

            # Check for actual model-not-found (HTTP 404)
            if e.code == 404:
                raise ModelNotFoundError(
                    f"Model '{data.get('model', 'unknown')}' not found on Ollama.\n"
                    f"Download it with: ollama pull {data.get('model', 'unknown')}\n"
                    f"Or run /models to switch to an available model."
                )

            # Check for "does not support tools" (HTTP 400)
            if e.code == 400 and "does not support tools" in str(error_msg).lower():
                raise ToolsNotSupportedError(
                    f"Model '{data.get('model', 'unknown')}' does not support tool calling.\n"
                    f"Falling back to plain chat mode (no file/command tools).\n"
                    f"Use /models to switch to a tool-capable model."
                )

            raise LLMError(f"Ollama API error ({e.code}): {error_msg}")

        except socket.timeout:
            raise LLMError(
                "Request timed out. The model is taking too long to respond.\n"
                "This can happen with complex prompts or tool calls.\n"
                "Try again or use a smaller prompt."
            )
        except urllib.error.URLError as e:
            if isinstance(e.reason, socket.timeout):
                raise LLMError(
                    "Request timed out. The model is taking too long to respond.\n"
                    "Try again with a simpler request."
                )
            raise ConnectionError(f"Cannot connect to Ollama: {e}")
        except json.JSONDecodeError:
            raise LLMError("Invalid response from Ollama")

    def list_models(self) -> list[dict]:
        """List all downloaded Ollama models."""
        try:
            models = self._fetch_installed_models()
            active_name = self.last_used_model if self.model == "auto" else self._match_model_name(
                self.model,
                [m["name"] for m in models],
                raise_on_missing=False,
            )
            for model in models:
                model["active"] = model["name"] == active_name
                model["role"] = get_model_role_label(model["name"])
            return models
        except Exception as e:
            raise LLMError(f"Failed to list models: {e}")

    def switch_model(self, model_name: str) -> bool:
        """Switch to a different model."""
        requested = model_name.strip()
        if requested.lower() == "auto":
            self.model = "auto"
            self.last_route_reason = "automatic task-based routing"
            preview, _ = self.preview_auto_model()
            self.last_used_model = preview
            self.config.update(model="auto")
            return True

        models = self._fetch_installed_models()
        available = [m["name"] for m in models]

        matched = self._match_model_name(requested, available)

        if matched is None:
            raise ModelNotFoundError(
                f"Model '{requested}' not found.\n"
                f"Available models: {', '.join(available)}\n"
                f"Download with: ollama pull {requested}"
            )

        self._ensure_chat_capable_model(matched)
        self.model = matched
        self.last_used_model = matched
        self.last_route_reason = "manual selection"
        self.config.update(model=matched)
        return True

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
        think: bool = False,
        model_name: Optional[str] = None,
    ):
        """Send a chat request to Ollama.

        Args:
            messages: Conversation history [{role, content}, ...]
            tools: Tool definitions for function calling
            stream: Whether to stream the response
            think: Whether to enable thinking mode

        Returns:
            If stream=False: Complete response dict
            If stream=True: Generator yielding response chunks
        """
        data = {
            "model": model_name or self.model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }
        if tools:
            data["tools"] = tools
        if think:
            data["think"] = True

        max_retries = 3
        for attempt in range(max_retries):
            try:
                if stream:
                    return self._stream_chat(data)
                else:
                    response = self._api_post("/api/chat", data)
                    return response
            except (ModelNotFoundError, ConnectionError, ToolsNotSupportedError):
                # Don't retry these — they are definitive errors
                raise
            except LLMError:
                # Retry LLM errors (timeouts, API errors, etc.)
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(
                    f"Failed to communicate with Ollama after {max_retries} attempts.\n"
                    f"Error: {e}\n"
                    f"Check if Ollama is running: ollama serve"
                )

    def _stream_chat(self, data: dict) -> Generator[dict, None, None]:
        """Stream chat responses."""
        try:
            resp = self._api_post("/api/chat", data, stream=True)
            buffer = b""
            for chunk in iter(lambda: resp.read(4096), b""):
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line.decode("utf-8"))
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            raise LLMError(f"Stream interrupted: {e}")

    def chat_with_fallback(
        self,
        messages: list[dict],
        think: bool = False,
        preferred_models: Optional[list[str]] = None,
        route_reason: Optional[str] = None,
    ) -> dict:
        """Send a plain chat request with runtime model fallback."""
        candidate_models, route_reason = self._resolve_candidate_models(
            messages,
            tools=None,
            preferred_models=preferred_models,
            route_reason=route_reason,
        )
        response, selected_model, think_enabled, _, fallback_used = self._chat_across_candidates(
            messages,
            candidate_models,
            tools=None,
            think=think,
        )

        resolved_reason = self._resolve_route_reason(route_reason, fallback_used)
        self.last_used_model = selected_model
        self.last_route_reason = resolved_reason

        result = dict(response)
        result["model"] = selected_model
        result["route_reason"] = resolved_reason
        result["thinking_enabled"] = think_enabled
        result["fallback_used"] = fallback_used
        return result

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        think: bool = False,
        preferred_models: Optional[list[str]] = None,
        route_reason: Optional[str] = None,
    ) -> dict:
        """Chat and parse tool calls from response.

        Returns dict with:
            - content: str (text response if any)
            - thinking: str (thinking/reasoning if any)
            - tool_calls: list[dict] (tool calls if any)
            - done: bool (whether agent is done - no more tool calls)
        """
        candidate_models, route_reason = self._resolve_candidate_models(
            messages,
            tools,
            preferred_models=preferred_models,
            route_reason=route_reason,
        )
        response, selected_model, think_enabled, native_tools_supported, fallback_used = self._chat_across_candidates(
            messages,
            candidate_models,
            tools=tools,
            think=think,
        )
        resolved_reason = self._resolve_route_reason(route_reason, fallback_used)
        self.last_used_model = selected_model
        self.last_route_reason = resolved_reason

        result = {
            "content": "",
            "thinking": "",
            "tool_calls": [],
            "done": True,
            "native_tools_supported": native_tools_supported,
            "tool_call_mode": "native",
            "model": selected_model,
            "route_reason": resolved_reason,
            "thinking_enabled": think_enabled,
            "fallback_used": fallback_used,
        }

        message = response.get("message", {})
        result["content"] = message.get("content", "")
        result["thinking"] = message.get("thinking", "")

        # Parse tool calls
        tool_calls = message.get("tool_calls", [])
        if tool_calls:
            result["done"] = False
            for tc in tool_calls:
                func = tc.get("function", {})
                result["tool_calls"].append({
                    "name": func.get("name", ""),
                    "arguments": func.get("arguments", {}),
                })
        elif tools:
            tool_names = [tool["function"]["name"] for tool in tools if tool.get("function")]
            extracted_calls = []

            content_calls, cleaned_content = extract_text_tool_calls(result["content"], tool_names)
            if content_calls:
                extracted_calls.extend(content_calls)
                result["content"] = cleaned_content

            thinking_calls, cleaned_thinking = extract_text_tool_calls(result["thinking"], tool_names)
            if thinking_calls:
                extracted_calls.extend(thinking_calls)
                result["thinking"] = cleaned_thinking

            if extracted_calls:
                result["tool_calls"] = extracted_calls
                result["done"] = False
                result["tool_call_mode"] = "text"

        return result

    def preview_auto_model(self, messages: Optional[list[dict]] = None, tools: Optional[list[dict]] = None) -> tuple[str | None, str]:
        """Preview the model auto-routing would currently choose."""
        available = self._fetch_installed_models()
        return preview_best_model(available, messages or [], bool(tools))

    def select_agent_team(self, messages: list[dict], tools: Optional[list[dict]] = None) -> AgentTeam:
        """Select planner/executor/reviewer roles for orchestration."""
        available = self._fetch_installed_models()
        if not available:
            raise ModelNotFoundError("No Ollama models are installed.")

        available_names = [m["name"] for m in available]
        if self.model != "auto":
            matched = self._match_model_name(self.model, available_names, raise_on_missing=False)
            if matched is None and self.model == LEGACY_DEFAULT_MODEL:
                return build_agent_team(available, messages, bool(tools))
            if matched is None:
                raise ModelNotFoundError(
                    f"Model '{self.model}' not found.\n"
                    f"Available models: {', '.join(available_names)}"
                )
            self._ensure_chat_capable_model(matched)
            return AgentTeam(
                planner=matched,
                executor=matched,
                reviewer=matched,
                executor_candidates=(matched,),
                route_reason="manual selection",
            )

        try:
            return build_agent_team(available, messages, bool(tools))
        except ValueError as e:
            raise LLMError(str(e))

    def get_display_model(self) -> str:
        """Describe the configured model mode for UI display."""
        if self.model != "auto":
            return self.model

        preview, _ = self.preview_auto_model()
        target = self.last_used_model or preview
        return f"auto -> {target}" if target else "auto"

    def _fetch_installed_models(self) -> list[dict]:
        response = self._api_get("/api/tags")
        models = []
        for m in response.get("models", []):
            name = m.get("name", "unknown")
            models.append({
                "name": name,
                "size": m.get("size", 0),
                "modified": m.get("modified_at", ""),
                "active": False,
            })
        return models

    def _resolve_candidate_models(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        preferred_models: Optional[list[str]] = None,
        route_reason: Optional[str] = None,
    ) -> tuple[list[str], str]:
        available = self._fetch_installed_models()
        if not available:
            raise ModelNotFoundError("No Ollama models are installed.")

        available_names = [m["name"] for m in available]

        if preferred_models:
            matched = []
            for name in preferred_models:
                resolved = self._match_model_name(name, available_names, raise_on_missing=False)
                if resolved and is_chat_capable_model(resolved) and resolved not in matched:
                    matched.append(resolved)
            if matched:
                fallbacks = self._rank_fallback_models(available, messages, bool(tools), exclude=matched)
                return matched + fallbacks, route_reason or "role-directed selection"

        if self.model != "auto":
            matched = self._match_model_name(self.model, available_names, raise_on_missing=False)
            if matched is not None:
                self._ensure_chat_capable_model(matched)
                fallbacks = self._rank_fallback_models(available, messages, bool(tools), exclude=[matched])
                return [matched] + fallbacks, "manual selection"
            if self.model == LEGACY_DEFAULT_MODEL:
                ranked, route_reason = rank_models(available, messages, bool(tools))
                if not ranked:
                    raise LLMError("No chat-capable Ollama models are installed.")
                return [m["name"] for m in ranked], f"auto fallback from legacy default; {route_reason}"
            raise ModelNotFoundError(
                f"Model '{self.model}' not found.\n"
                f"Available models: {', '.join(available_names)}"
            )

        ranked, route_reason = rank_models(available, messages, bool(tools))
        if not ranked:
            raise LLMError("No chat-capable Ollama models are installed.")
        return [m["name"] for m in ranked], route_reason

    @staticmethod
    def _ensure_chat_capable_model(model_name: str) -> None:
        if is_chat_capable_model(model_name):
            return
        raise LLMError(
            f"Model '{model_name}' is embeddings-only and cannot be used as the interactive chat agent.\n"
            "Use /models auto or switch to a chat-capable coding model."
        )

    def _chat_across_candidates(
        self,
        messages: list[dict],
        candidate_models: list[str],
        *,
        tools: Optional[list[dict]],
        think: bool,
    ) -> tuple[dict, str, bool, bool, bool]:
        """Try candidate models in order until one succeeds."""
        if not candidate_models:
            raise LLMError("No compatible model could be selected for this request.")

        failures: list[str] = []
        toolless_candidates: list[str] = []

        for index, model_name in enumerate(candidate_models):
            think_for_model = should_enable_thinking(model_name, think)
            try:
                response = self.chat(
                    messages,
                    tools=tools,
                    stream=False,
                    think=think_for_model,
                    model_name=model_name,
                )
                return response, model_name, think_for_model, True, index > 0
            except ToolsNotSupportedError as e:
                failures.append(f"{model_name}: {e}")
                if tools:
                    toolless_candidates.append(model_name)
                continue
            except ConnectionError:
                raise
            except (ModelNotFoundError, LLMError) as e:
                failures.append(f"{model_name}: {e}")
                continue

        if tools:
            for model_name in toolless_candidates:
                think_for_model = should_enable_thinking(model_name, think)
                try:
                    response = self.chat(
                        messages,
                        tools=None,
                        stream=False,
                        think=think_for_model,
                        model_name=model_name,
                    )
                    fallback_used = model_name != candidate_models[0] or len(candidate_models) > 1
                    return response, model_name, think_for_model, False, fallback_used
                except ConnectionError:
                    raise
                except (ModelNotFoundError, LLMError, ToolsNotSupportedError) as e:
                    failures.append(f"{model_name} (plain chat): {e}")
                    continue

        raise LLMError(self._format_candidate_failure_message(failures))

    @staticmethod
    def _format_candidate_failure_message(failures: list[str]) -> str:
        """Summarize the candidate failures after runtime fallback is exhausted."""
        if not failures:
            return "No compatible model could be selected for this request."
        shown = failures[:3]
        suffix = "" if len(failures) <= 3 else f" (+{len(failures) - 3} more)"
        return f"All fallback models failed. Tried: {' | '.join(shown)}{suffix}"

    def _rank_fallback_models(
        self,
        available: list[dict],
        messages: list[dict],
        has_tools: bool,
        *,
        exclude: list[str],
    ) -> list[str]:
        """Return ranked fallback models excluding already-preferred entries."""
        ranked, _ = rank_models(available, messages, has_tools)
        excluded = set(exclude)
        return [model["name"] for model in ranked if model["name"] not in excluded]

    @staticmethod
    def _resolve_route_reason(route_reason: str, fallback_used: bool) -> str:
        if fallback_used:
            return f"{route_reason}; runtime model fallback"
        return route_reason

    @staticmethod
    def _match_model_name(model_name: str, available: list[str], raise_on_missing: bool = True) -> str | None:
        for name in available:
            if name == model_name or name.startswith(model_name):
                return name
        if raise_on_missing:
            raise ModelNotFoundError(f"Model '{model_name}' not found.")
        return None
