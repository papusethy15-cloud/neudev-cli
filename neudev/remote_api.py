"""HTTP and streaming client for talking to a hosted NeuDev server."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterator

from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.sync.client import connect as websocket_connect


class RemoteAPIError(Exception):
    """Raised when the hosted NeuDev API returns an error."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


class RemoteNeuDevClient:
    """Thin HTTP client used by the local CLI in remote mode."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 300, websocket_url: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.websocket_url = (websocket_url or "").rstrip("/")

    def configure_streaming(self, health_payload: dict[str, Any]) -> None:
        if self.websocket_url:
            return
        websocket_port = health_payload.get("websocket_port")
        websocket_path = health_payload.get("websocket_path") or "/v1/stream"
        if not websocket_port:
            return
        parsed = urllib.parse.urlparse(self.base_url)
        if not parsed.hostname:
            return
        scheme = "wss" if parsed.scheme == "https" else "ws"
        self.websocket_url = f"{scheme}://{parsed.hostname}:{int(websocket_port)}{websocket_path}"

    def health(self) -> dict[str, Any]:
        payload = self._request("GET", "/health", authenticated=False)
        self.configure_streaming(payload)
        return payload

    def create_session(
        self,
        *,
        workspace: str | None = None,
        model: str | None = None,
        language: str | None = None,
        agent_mode: str | None = None,
        auto_permission: bool | None = None,
    ) -> dict[str, Any]:
        payload = {
            "workspace": workspace,
            "model": model,
            "language": language,
            "agent_mode": agent_mode,
            "auto_permission": auto_permission,
        }
        return self._request("POST", "/v1/sessions", payload)

    def list_sessions(self) -> dict[str, Any]:
        return self._request("GET", "/v1/sessions")

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/sessions/{session_id}")

    def close_session(self, session_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/sessions/{session_id}/close", {})

    def send_message(self, session_id: str, message: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/sessions/{session_id}/messages", {"message": message})

    def stream_message(self, session_id: str, message: str, transport: str = "auto") -> Iterator[dict[str, Any]]:
        effective_transport = self._pick_transport(transport)
        if effective_transport == "websocket":
            try:
                yield from self._websocket_stream(
                    {
                        "action": "stream_message",
                        "api_key": self.api_key,
                        "session_id": session_id,
                        "message": message,
                    }
                )
                return
            except RemoteAPIError as exc:
                if transport == "websocket":
                    raise
                if exc.status_code not in (404, 426, 503):
                    raise
        yield from self._request_stream("POST", f"/v1/sessions/{session_id}/messages/stream", {"message": message})

    def respond_to_approval(self, session_id: str, approval_id: str, approved: bool) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/sessions/{session_id}/approvals/{approval_id}",
            {"approved": approved},
        )

    def stream_approval(
        self,
        session_id: str,
        approval_id: str,
        approved: bool,
        transport: str = "auto",
    ) -> Iterator[dict[str, Any]]:
        effective_transport = self._pick_transport(transport)
        if effective_transport == "websocket":
            try:
                yield from self._websocket_stream(
                    {
                        "action": "stream_approval",
                        "api_key": self.api_key,
                        "session_id": session_id,
                        "approval_id": approval_id,
                        "approved": approved,
                    }
                )
                return
            except RemoteAPIError as exc:
                if transport == "websocket":
                    raise
                if exc.status_code not in (404, 426, 503):
                    raise
        yield from self._request_stream(
            "POST",
            f"/v1/sessions/{session_id}/approvals/{approval_id}/stream",
            {"approved": approved},
        )

    def clear_history(self, session_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/sessions/{session_id}/clear", {})

    def get_history(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/sessions/{session_id}/history")

    def undo_last_change(self, session_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/sessions/{session_id}/undo", {})

    def get_config(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/sessions/{session_id}/config")

    def update_config(self, session_id: str, **kwargs) -> dict[str, Any]:
        return self._request("POST", f"/v1/sessions/{session_id}/config", kwargs)

    def list_models(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/sessions/{session_id}/models")

    def switch_model(self, session_id: str, selection: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/sessions/{session_id}/models", {"selection": selection})

    def get_summary(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/sessions/{session_id}/summary")

    def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        *,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        if not self.base_url:
            raise RemoteAPIError("Remote API base URL is not configured.", status_code=400)

        headers = {"Content-Type": "application/json"}
        if authenticated:
            if not self.api_key:
                raise RemoteAPIError("Remote API key is not configured.", status_code=400)
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc)
        except urllib.error.URLError as exc:
            raise RemoteAPIError(f"Cannot connect to remote NeuDev API: {exc}", status_code=503)

        if not payload:
            return {}
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RemoteAPIError(f"Invalid JSON response from remote API: {exc}", status_code=502)

    def _request_stream(self, method: str, path: str, data: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        if not self.base_url:
            raise RemoteAPIError("Remote API base URL is not configured.", status_code=400)
        if not self.api_key:
            raise RemoteAPIError("Remote API key is not configured.", status_code=400)

        headers = {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = json.dumps(data or {}).encode("utf-8")
        request = urllib.request.Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                event_name = "message"
                data_lines: list[str] = []
                for raw_line in response:
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                    if not line:
                        if data_lines:
                            item = {"event": event_name, "data": self._parse_stream_payload("\n".join(data_lines))}
                            yield item
                            if item["event"] == "done":
                                break
                            event_name = "message"
                            data_lines = []
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip() or "message"
                    elif line.startswith("data:"):
                        data_lines.append(line.split(":", 1)[1].lstrip())
                if data_lines:
                    yield {"event": event_name, "data": self._parse_stream_payload("\n".join(data_lines))}
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc)
        except urllib.error.URLError as exc:
            raise RemoteAPIError(f"Cannot connect to remote NeuDev API: {exc}", status_code=503)

    def _websocket_stream(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        if not self.websocket_url:
            raise RemoteAPIError("Remote WebSocket stream is not configured.", status_code=503)
        try:
            with websocket_connect(self.websocket_url, open_timeout=self.timeout) as websocket:
                websocket.send(json.dumps(payload))
                for message in websocket:
                    try:
                        event = json.loads(message)
                    except json.JSONDecodeError as exc:
                        raise RemoteAPIError(f"Invalid WebSocket payload from remote API: {exc}", status_code=502)
                    yield event
                    if event.get("event") == "done":
                        break
        except InvalidHandshake as exc:
            raise RemoteAPIError(f"Cannot open remote WebSocket stream: {exc}", status_code=426)
        except OSError as exc:
            raise RemoteAPIError(f"Cannot connect to remote WebSocket stream: {exc}", status_code=503)
        except ConnectionClosed:
            return

    @staticmethod
    def _parse_stream_payload(payload: str) -> dict[str, Any]:
        if not payload:
            return {}
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RemoteAPIError(f"Invalid event stream payload from remote API: {exc}", status_code=502)

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError) -> RemoteAPIError:
        try:
            payload = exc.read().decode("utf-8", errors="replace")
            message = payload
            try:
                error_data = json.loads(payload)
                message = error_data.get("error") or error_data.get("message") or payload
            except json.JSONDecodeError:
                pass
            return RemoteAPIError(str(message), status_code=exc.code)
        finally:
            exc.close()

    def _pick_transport(self, transport: str) -> str:
        selected = (transport or "auto").strip().lower()
        if selected == "websocket":
            return "websocket"
        if selected == "sse":
            return "sse"
        return "websocket" if self.websocket_url else "sse"


class RemoteSessionClient:
    """Session-scoped wrapper around the hosted NeuDev API."""

    def __init__(
        self,
        client: RemoteNeuDevClient,
        session_id: str,
        *,
        workspace: str,
        config_snapshot: dict[str, Any] | None = None,
    ):
        self.client = client
        self.session_id = session_id
        self.workspace = workspace
        self.config_snapshot = config_snapshot or {}

    @classmethod
    def create(
        cls,
        client: RemoteNeuDevClient,
        *,
        workspace: str | None = None,
        model: str | None = None,
        language: str | None = None,
        agent_mode: str | None = None,
        auto_permission: bool | None = None,
    ) -> "RemoteSessionClient":
        created = client.create_session(
            workspace=workspace,
            model=model,
            language=language,
            agent_mode=agent_mode,
            auto_permission=auto_permission,
        )
        return cls(
            client,
            created["session_id"],
            workspace=created.get("workspace", workspace or "."),
            config_snapshot=created.get("config"),
        )

    @classmethod
    def resume(cls, client: RemoteNeuDevClient, session_id: str) -> "RemoteSessionClient":
        snapshot = client.get_session(session_id)
        return cls(
            client,
            session_id,
            workspace=snapshot.get("workspace", "."),
            config_snapshot=snapshot.get("config"),
        )

    def send_message(self, message: str) -> dict[str, Any]:
        return self.client.send_message(self.session_id, message)

    def stream_message(self, message: str, transport: str = "auto") -> Iterator[dict[str, Any]]:
        return self.client.stream_message(self.session_id, message, transport=transport)

    def respond_to_approval(self, approval_id: str, approved: bool) -> dict[str, Any]:
        return self.client.respond_to_approval(self.session_id, approval_id, approved)

    def stream_approval(self, approval_id: str, approved: bool, transport: str = "auto") -> Iterator[dict[str, Any]]:
        return self.client.stream_approval(self.session_id, approval_id, approved, transport=transport)

    def clear_history(self) -> dict[str, Any]:
        return self.client.clear_history(self.session_id)

    def get_history(self) -> dict[str, Any]:
        return self.client.get_history(self.session_id)

    def undo_last_change(self) -> dict[str, Any]:
        return self.client.undo_last_change(self.session_id)

    def get_config(self) -> dict[str, Any]:
        self.config_snapshot = self.client.get_config(self.session_id)
        return self.config_snapshot

    def update_config(self, **kwargs) -> dict[str, Any]:
        self.config_snapshot = self.client.update_config(self.session_id, **kwargs)
        return self.config_snapshot

    def list_models(self) -> dict[str, Any]:
        return self.client.list_models(self.session_id)

    def switch_model(self, selection: str) -> dict[str, Any]:
        return self.client.switch_model(self.session_id, selection)

    def get_summary(self) -> dict[str, Any]:
        return self.client.get_summary(self.session_id)

    def close(self) -> dict[str, Any]:
        return self.client.close_session(self.session_id)
