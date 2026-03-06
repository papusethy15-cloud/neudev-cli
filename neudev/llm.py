"""Ollama LLM client wrapper for NeuDev - uses REST API directly for Python 3.14 compat."""

import json
import socket
import time
import urllib.request
import urllib.error
from typing import Generator, Optional

from neudev.config import NeuDevConfig


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
            response = self._api_get("/api/tags")
            models = []
            for m in response.get("models", []):
                name = m.get("name", "unknown")
                models.append({
                    "name": name,
                    "size": m.get("size", 0),
                    "modified": m.get("modified_at", ""),
                    "active": name == self.model,
                })
            return models
        except Exception as e:
            raise LLMError(f"Failed to list models: {e}")

    def switch_model(self, model_name: str) -> bool:
        """Switch to a different model."""
        models = self.list_models()
        available = [m["name"] for m in models]

        matched = None
        for name in available:
            if name == model_name or name.startswith(model_name):
                matched = name
                break

        if matched is None:
            raise ModelNotFoundError(
                f"Model '{model_name}' not found.\n"
                f"Available models: {', '.join(available)}\n"
                f"Download with: ollama pull {model_name}"
            )

        self.model = matched
        self.config.update(model=matched)
        return True

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
        think: bool = False,
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
            "model": self.model,
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

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        think: bool = False,
    ) -> dict:
        """Chat and parse tool calls from response.

        Returns dict with:
            - content: str (text response if any)
            - thinking: str (thinking/reasoning if any)
            - tool_calls: list[dict] (tool calls if any)
            - done: bool (whether agent is done - no more tool calls)
        """
        try:
            response = self.chat(messages, tools=tools, stream=False, think=think)
        except ToolsNotSupportedError:
            # Retry without tools — model can still chat, just no function calling
            response = self.chat(messages, tools=None, stream=False, think=think)

        result = {
            "content": "",
            "thinking": "",
            "tool_calls": [],
            "done": True,
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

        return result
