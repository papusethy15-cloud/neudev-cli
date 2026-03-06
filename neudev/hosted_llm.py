"""Hosted inference client for hybrid NeuDev runtime."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from neudev.config import NeuDevConfig
from neudev.llm import ConnectionError, LLMError, ModelNotFoundError, OllamaClient, ToolsNotSupportedError
from neudev.remote_api import RemoteAPIError, RemoteNeuDevClient


PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----",
    re.DOTALL,
)
ENV_SECRET_RE = re.compile(
    r"(?im)^([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET_KEY|PASSWORD|PASSWD|CLIENT_SECRET)[A-Z0-9_]*\s*=\s*)(.+)$"
)
AUTH_HEADER_RE = re.compile(r"(?im)(authorization\s*:\s*bearer\s+)([^\s\"']+)")
INLINE_SECRET_RE = re.compile(
    r"(?im)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret[_-]?key|client[_-]?secret|password|passwd)\b"
    r"\s*[:=]\s*)([^\s,\"']+)"
)


class HostedLLMClient(OllamaClient):
    """Ollama-compatible client that proxies inference through the hosted API."""

    def __init__(self, config: NeuDevConfig, base_url: str, api_key: str, timeout: int = 300):
        self.remote_client = RemoteNeuDevClient(base_url, api_key, timeout=timeout)
        self.last_redaction_count = 0
        self.last_payload_bytes = 0
        super().__init__(config)
        self.base_url = self.remote_client.base_url

    def _test_connection(self) -> None:
        """Verify the hosted API is reachable and authenticated."""
        try:
            self.remote_client.health()
            self._fetch_installed_models()
        except RemoteAPIError as exc:
            if exc.status_code in (401, 403):
                raise LLMError("Hosted inference API rejected the provided API key.")
            if exc.status_code >= 500:
                raise ConnectionError(f"Cannot connect to hosted inference API at {self.remote_client.base_url}: {exc}")
            raise LLMError(f"Hosted inference API error: {exc}")

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
        think: bool = False,
        model_name: Optional[str] = None,
    ):
        """Send a chat request to the hosted inference API."""
        prepared = self._prepare_inference_payload(
            messages=messages,
            model_name=model_name,
            tools=tools,
            think=think,
        )
        if stream:
            return self._stream_chat(
                messages=prepared["messages"],
                tools=prepared["tools"],
                think=prepared["think"],
                model_name=prepared["model"],
            )

        try:
            payload = self.remote_client.chat_inference(
                messages=prepared["messages"],
                model=prepared["model"],
                tools=prepared["tools"],
                think=prepared["think"],
            )
        except RemoteAPIError as exc:
            message = str(exc)
            lowered = message.lower()
            if exc.status_code == 404:
                raise ModelNotFoundError(
                    f"Model '{model_name or self.model}' not found on the hosted inference server.\n"
                    "Use /models to switch to an available hosted model."
                )
            if exc.status_code == 400 and "does not support tools" in lowered:
                raise ToolsNotSupportedError(message)
            if exc.status_code in (401, 403):
                raise LLMError("Hosted inference API rejected the provided API key.")
            if exc.status_code >= 500:
                raise ConnectionError(f"Cannot connect to hosted inference API: {message}")
            raise LLMError(f"Hosted inference API error ({exc.status_code}): {message}")

        response = payload.get("response")
        if not isinstance(response, dict):
            raise LLMError("Hosted inference API returned an invalid chat payload.")
        return response

    def _stream_chat(
        self,
        *,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        think: bool = False,
        model_name: Optional[str] = None,
    ):
        """Stream raw hosted inference chunks."""
        try:
            yield from self.remote_client.stream_inference_chat(
                messages=messages,
                model=model_name or self.model,
                tools=tools,
                think=think,
            )
        except RemoteAPIError as exc:
            message = str(exc)
            lowered = message.lower()
            if exc.status_code == 404:
                raise ModelNotFoundError(
                    f"Model '{model_name or self.model}' not found on the hosted inference server.\n"
                    "Use /models to switch to an available hosted model."
                )
            if exc.status_code == 400 and "does not support tools" in lowered:
                raise ToolsNotSupportedError(message)
            if exc.status_code in (401, 403):
                raise LLMError("Hosted inference API rejected the provided API key.")
            if exc.status_code >= 500:
                raise ConnectionError(f"Cannot connect to hosted inference API: {message}")
            raise LLMError(f"Hosted inference API error ({exc.status_code}): {message}")

    def _fetch_installed_models(self) -> list[dict]:
        """Fetch models from the hosted inference API."""
        try:
            payload = self.remote_client.list_inference_models()
        except RemoteAPIError as exc:
            if exc.status_code in (401, 403):
                raise LLMError("Hosted inference API rejected the provided API key.")
            if exc.status_code >= 500:
                raise ConnectionError(f"Cannot connect to hosted inference API: {exc}")
            raise LLMError(f"Hosted inference API error ({exc.status_code}): {exc}")

        models = []
        for item in payload.get("models", []):
            models.append(
                {
                    "name": item.get("name", "unknown"),
                    "size": item.get("size", 0),
                    "modified": item.get("modified", item.get("modified_at", "")),
                    "active": False,
                }
            )
        return models

    def _prepare_inference_payload(
        self,
        *,
        messages: list[dict[str, Any]],
        model_name: Optional[str],
        tools: Optional[list[dict[str, Any]]],
        think: bool,
    ) -> dict[str, Any]:
        redaction_count = 0
        prepared_messages: list[dict[str, Any]] = messages
        if self.config.hybrid_redact_secrets:
            prepared_messages, redaction_count = self._sanitize_value(messages)

        payload = {
            "messages": prepared_messages,
            "model": model_name or self.model,
            "tools": tools,
            "think": think,
        }
        payload_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        self.last_redaction_count = redaction_count
        self.last_payload_bytes = payload_bytes
        if payload_bytes > self.config.hybrid_max_payload_bytes:
            raise LLMError(
                "Hybrid inference payload is too large for the configured safety limit.\n"
                f"Payload bytes: {payload_bytes}\n"
                f"Configured limit: {self.config.hybrid_max_payload_bytes}\n"
                "Read smaller file ranges, reduce copied logs, or split the task into smaller turns."
            )
        return payload

    def _sanitize_value(self, value: Any) -> tuple[Any, int]:
        if isinstance(value, str):
            return self._redact_text(value)
        if isinstance(value, list):
            total = 0
            sanitized = []
            for item in value:
                next_value, count = self._sanitize_value(item)
                sanitized.append(next_value)
                total += count
            return sanitized, total
        if isinstance(value, dict):
            total = 0
            sanitized = {}
            for key, item in value.items():
                next_value, count = self._sanitize_value(item)
                sanitized[key] = next_value
                total += count
            return sanitized, total
        return value, 0

    @staticmethod
    def _redact_text(text: str) -> tuple[str, int]:
        redacted = text
        count = 0

        redacted, hits = PRIVATE_KEY_RE.subn("[REDACTED PRIVATE KEY]", redacted)
        count += hits
        redacted, hits = AUTH_HEADER_RE.subn(r"\1[REDACTED]", redacted)
        count += hits
        redacted, hits = ENV_SECRET_RE.subn(r"\1[REDACTED]", redacted)
        count += hits
        redacted, hits = INLINE_SECRET_RE.subn(r"\1[REDACTED]", redacted)
        count += hits

        return redacted, count
