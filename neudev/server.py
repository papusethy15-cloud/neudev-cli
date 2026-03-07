"""Hosted NeuDev API server for Lightning or other remote runtimes."""

from __future__ import annotations

import argparse
import json
import os
import queue
import socket
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterator

from neudev import __app_name__
from neudev.agent import Agent
from neudev.config import CONFIG_DIR, NeuDevConfig
from neudev.llm import LLMError, OllamaClient
from neudev.permissions import (
    PERMISSION_CHOICE_ALL,
    PERMISSION_CHOICE_ONCE,
    PERMISSION_CHOICE_TOOL,
    PermissionManager,
)
from neudev.session import ActionRecord, FileBackup
from neudev.tools.run_command import RunCommandTool

try:
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.server import ServerConnection, serve as websocket_serve
except ImportError:  # pragma: no cover - optional dependency at runtime
    ConnectionClosed = None
    ServerConnection = Any
    websocket_serve = None


DEFAULT_SESSION_STORE = CONFIG_DIR / "hosted_sessions"
DEFAULT_WEBSOCKET_PATH = "/v1/stream"


class RemoteApprovalRequired(Exception):
    """Raised when a hosted session needs user approval for a tool."""

    def __init__(self, tool_name: str, message: str):
        super().__init__(message)
        self.tool_name = tool_name
        self.message = message


class HostedPermissionManager(PermissionManager):
    """Permission manager that defers approval to the remote client."""

    def request_permission(self, tool_name: str, message: str) -> bool:
        if self.auto_approve or self._session_approvals.get(tool_name) or self._consume_once_approval(tool_name):
            return True
        raise RemoteApprovalRequired(tool_name, message)


@dataclass
class HostedSession:
    session_id: str
    agent: Agent
    workspace: str
    created_at: str
    updated_at: str
    pending_user_message: str | None = None
    pending_tool_name: str | None = None
    pending_prompt: str | None = None
    pending_approval_id: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    control_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    current_message: str | None = None
    current_stop_event: threading.Event | None = field(default=None, repr=False)
    stop_requested: bool = False

    @property
    def config(self) -> NeuDevConfig:
        return self.agent.config


class HostedSessionService:
    """Disk-backed remote session manager."""

    def __init__(
        self,
        base_config: NeuDevConfig,
        default_workspace: str,
        api_key: str,
        storage_dir: str | None = None,
    ):
        self.base_config = base_config
        self.default_workspace = str(Path(default_workspace).resolve())
        self.allowed_root = Path(self.default_workspace).resolve()
        self.api_key = api_key.strip()
        self.storage_dir = Path(storage_dir).expanduser().resolve() if storage_dir else DEFAULT_SESSION_STORE.resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.sessions: dict[str, HostedSession] = {}
        self._inference_client: OllamaClient | None = None
        self._inference_lock = threading.Lock()
        self._load_sessions()

    def authenticate(self, auth_header: str | None) -> bool:
        if not self.api_key:
            return True
        if not auth_header or not auth_header.startswith("Bearer "):
            return False
        token = auth_header.split(" ", 1)[1].strip()
        return token == self.api_key

    def create_session(
        self,
        *,
        workspace: str | None = None,
        model: str | None = None,
        language: str | None = None,
        agent_mode: str | None = None,
        auto_permission: bool | None = None,
    ) -> dict[str, Any]:
        resolved_workspace = self._resolve_workspace(workspace)
        config = self.base_config.clone()
        config.apply_runtime_updates(
            persist=False,
            model=model or config.model,
            response_language=language or config.response_language,
            agent_mode=agent_mode or config.agent_mode,
            auto_permission=config.auto_permission if auto_permission is None else bool(auto_permission),
        )
        session = self._build_session(config=config, workspace=resolved_workspace, session_id=uuid.uuid4().hex)
        self.sessions[session.session_id] = session
        with session.lock:
            self._save_session(session)
        return self._session_snapshot(session)

    def list_sessions(self) -> dict[str, Any]:
        sessions = sorted(self.sessions.values(), key=lambda item: item.updated_at, reverse=True)
        return {"status": "ok", "sessions": [self._session_listing(item) for item in sessions]}

    def get_session(self, session_id: str) -> dict[str, Any]:
        session = self._get_session(session_id)
        return self._session_snapshot(session)

    def close_session(self, session_id: str) -> dict[str, Any]:
        session = self._get_session(session_id)
        summary = self.get_summary(session_id)
        self.sessions.pop(session.session_id, None)
        self._delete_session_file(session.session_id)
        return {"status": "closed", "summary": summary}

    def get_history(self, session_id: str) -> dict[str, Any]:
        session = self._get_session(session_id)
        return {
            "session_id": session.session_id,
            "actions": [
                {
                    "action": item.action,
                    "target": item.target,
                    "timestamp": item.timestamp,
                    "details": item.details,
                }
                for item in session.agent.session.actions
            ],
        }

    def clear_history(self, session_id: str) -> dict[str, Any]:
        session = self._get_session(session_id)
        with session.lock:
            session.agent.clear_history()
            self._save_session(session)
        return {"status": "ok", "message": "Conversation history cleared."}

    def undo_last_change(self, session_id: str) -> dict[str, Any]:
        session = self._get_session(session_id)
        with session.lock:
            result = session.agent.session.undo_last_change()
            if result:
                session.agent.refresh_context()
                session.agent.context.mark_workspace_state()
            self._save_session(session)
        return {"status": "ok", "result": result}

    def get_config(self, session_id: str) -> dict[str, Any]:
        session = self._get_session(session_id)
        return self._config_snapshot(session)

    def update_config(self, session_id: str, **kwargs) -> dict[str, Any]:
        session = self._get_session(session_id)
        with session.lock:
            session.config.apply_runtime_updates(persist=False, **kwargs)
            session.agent.refresh_context()
            self._save_session(session)
        return self._config_snapshot(session)

    def list_models(self, session_id: str) -> dict[str, Any]:
        session = self._get_session(session_id)
        with session.lock:
            models = session.agent.llm.list_models()
            display_model = session.agent.llm.get_display_model()
            preview_model, preview_reason = session.agent.llm.preview_auto_model()
        return {
            "session_id": session.session_id,
            "display_model": display_model,
            "auto_preview_model": preview_model,
            "auto_preview_reason": preview_reason,
            "models": models,
        }

    def switch_model(self, session_id: str, selection: str) -> dict[str, Any]:
        session = self._get_session(session_id)
        with session.lock:
            session.agent.llm.switch_model(selection)
            session.agent.refresh_context()
            preview_model, preview_reason = session.agent.llm.preview_auto_model()
            display_model = session.agent.llm.get_display_model()
            self._save_session(session)
        return {
            "status": "ok",
            "display_model": display_model,
            "selected_model": session.agent.llm.last_used_model or session.agent.llm.model,
            "auto_preview_model": preview_model,
            "auto_preview_reason": preview_reason,
        }

    def list_inference_models(self) -> dict[str, Any]:
        with self._inference_lock:
            client = self._get_inference_client()
            models = client.list_models()
            preview_model, preview_reason = client.preview_auto_model()
            display_model = client.get_display_model()
        return {
            "status": "ok",
            "display_model": display_model,
            "auto_preview_model": preview_model,
            "auto_preview_reason": preview_reason,
            "models": models,
        }

    def chat_inference(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        think: bool = False,
    ) -> dict[str, Any]:
        with self._inference_lock:
            client = self._get_inference_client()
            response = client.chat(
                messages=messages,
                tools=tools,
                stream=False,
                think=think,
                model_name=model or client.model,
            )
        return {
            "status": "ok",
            "response": response,
        }

    def stream_inference_chat(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        think: bool = False,
    ) -> Iterator[dict[str, Any]]:
        def stream() -> Iterator[dict[str, Any]]:
            try:
                with self._inference_lock:
                    client = self._get_inference_client()
                    response_stream = client.chat(
                        messages=messages,
                        tools=tools,
                        stream=True,
                        think=think,
                        model_name=model or client.model,
                    )
                    for chunk in response_stream:
                        yield {"event": "chunk", "data": chunk}
                yield {"event": "done", "data": {"status": "ok"}}
            except Exception as exc:
                yield {"event": "error", "data": {"status": "error", "error": str(exc)}}
                yield {"event": "done", "data": {"status": "error"}}

        return stream()

    def process_message(self, session_id: str, message: str) -> dict[str, Any]:
        session = self._get_session(session_id)
        return self._execute_message(session, message)

    def stream_message(self, session_id: str, message: str) -> Iterator[dict[str, Any]]:
        session = self._get_session(session_id)
        return self._stream_operation(lambda emit: self._execute_message(session, message, emit))

    def request_stop(self, session_id: str) -> dict[str, Any]:
        session = self._get_session(session_id)
        with session.control_lock:
            if session.pending_approval_id and session.current_stop_event is None:
                return {
                    "status": "awaiting_approval",
                    "message": "The hosted turn is waiting for approval. Deny or approve the pending request first.",
                    "approval_id": session.pending_approval_id,
                    "tool_name": session.pending_tool_name,
                }
            stop_event = session.current_stop_event
            current_message = session.current_message
            if stop_event is None:
                return {"status": "idle", "message": "No active hosted turn."}
            if session.stop_requested:
                return {
                    "status": "already_requested",
                    "message": "Stop was already requested for the active hosted turn.",
                    "current_message": current_message,
                }
            session.stop_requested = True
            stop_event.set()
        return {
            "status": "stop_requested",
            "message": "Stop requested for the active hosted turn.",
            "current_message": current_message,
        }

    def respond_to_approval(
        self,
        session_id: str,
        approval_id: str,
        approved: bool,
        scope: str | None = None,
    ) -> dict[str, Any]:
        session = self._get_session(session_id)
        approval_scope = str(scope or PERMISSION_CHOICE_ONCE).strip().lower()
        if approval_scope not in {PERMISSION_CHOICE_ONCE, PERMISSION_CHOICE_TOOL, PERMISSION_CHOICE_ALL}:
            raise ValueError(
                f"Invalid approval scope '{scope}'. Expected one of: "
                f"{PERMISSION_CHOICE_ONCE}, {PERMISSION_CHOICE_TOOL}, {PERMISSION_CHOICE_ALL}."
            )
        with session.lock:
            if approval_id != session.pending_approval_id:
                raise KeyError(f"Unknown approval id '{approval_id}'.")
            pending_message = session.pending_user_message
            tool_name = session.pending_tool_name
            session.pending_approval_id = None
            session.pending_prompt = None
            session.pending_tool_name = None
            session.pending_user_message = None

            if not approved:
                self._save_session(session)
                return {"status": "denied", "message": f"Permission denied for {tool_name or 'tool'}."}

            if approval_scope == PERMISSION_CHOICE_ALL:
                session.agent.permissions.auto_approve = True
                session.config.apply_runtime_updates(persist=False, auto_permission=True)
            elif approval_scope == PERMISSION_CHOICE_TOOL and tool_name:
                session.agent.permissions._session_approvals[tool_name] = True
            elif approval_scope == PERMISSION_CHOICE_ONCE and pending_message and tool_name:
                session.agent.permissions.grant_once(tool_name)
            self._save_session(session)

        if not pending_message:
            return {"status": "ok", "message": "Approval stored."}
        return self._execute_message(session, pending_message)

    def stream_approval(
        self,
        session_id: str,
        approval_id: str,
        approved: bool,
        scope: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        return self._stream_operation(
            lambda emit: self._respond_to_approval_stream(session_id, approval_id, approved, scope, emit)
        )

    def get_summary(self, session_id: str) -> dict[str, Any]:
        session = self._get_session(session_id)
        actions = session.agent.session.actions
        counts: dict[str, int] = {}
        for item in actions:
            counts[item.action] = counts.get(item.action, 0) + 1
        return {
            "session_id": session.session_id,
            "workspace": session.workspace,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "messages_count": session.agent.session.messages_count,
            "action_counts": counts,
            "test_files": list(session.agent.session.test_files),
        }

    def _respond_to_approval_stream(
        self,
        session_id: str,
        approval_id: str,
        approved: bool,
        scope: str | None,
        emit: Callable[[str, dict[str, Any]], None],
    ) -> dict[str, Any]:
        result = self.respond_to_approval(session_id, approval_id, approved, scope=scope)
        if result.get("status") == "denied":
            emit("denied", result)
        return result

    def _execute_message(
        self,
        session: HostedSession,
        message: str,
        emit: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        phases: list[dict[str, str]] = []
        workspace_changes: list[dict[str, list[str]]] = []
        plan_updates: list[dict[str, Any]] = []
        thinking_chunks: list[str] = []
        response_chunks: list[str] = []
        status_events: list[dict[str, Any]] = []
        progress_events: list[dict[str, Any]] = []
        stop_event = threading.Event()

        def record_workspace_change(changes: dict[str, list[str]]) -> None:
            payload = {key: list(value) for key, value in changes.items()}
            workspace_changes.append(payload)
            if emit:
                emit("workspace_change", payload)

        def record_plan_update(plan: list[dict[str, str]], conventions: list[str]) -> None:
            payload = {
                "plan": [dict(item) for item in plan],
                "conventions": list(conventions),
            }
            plan_updates.append(payload)
            if emit:
                emit("plan_update", payload)

        def record_status(tool_name: str, args: dict[str, Any]) -> None:
            payload = {"tool": tool_name, "args": dict(args)}
            status_events.append(payload)
            if emit:
                emit("status", payload)

        def record_progress(payload: dict[str, Any]) -> None:
            snapshot = dict(payload)
            progress_events.append(snapshot)
            if emit:
                emit("progress", snapshot)

        def record_thinking(text: str) -> None:
            thinking_chunks.append(text)
            if emit:
                emit("thinking", {"chunk": text})

        def record_phase(phase: str, model_name: str) -> None:
            payload = {"phase": phase, "model": model_name}
            phases.append(payload)
            if emit:
                emit("phase", payload)

        def record_text(text: str) -> None:
            response_chunks.append(text)
            if emit:
                emit("text", {"chunk": text})

        with session.control_lock:
            session.current_message = message
            session.current_stop_event = stop_event
            session.stop_requested = False

        try:
            with session.lock:
                try:
                    response = session.agent.process_message(
                        message,
                        on_status=record_status,
                        on_text=record_text,
                        on_thinking=record_thinking,
                        on_progress=record_progress,
                        on_phase=record_phase,
                        on_workspace_change=record_workspace_change,
                        on_plan_update=record_plan_update,
                        stop_event=stop_event,
                    )
                except RemoteApprovalRequired as exc:
                    approval_id = uuid.uuid4().hex
                    session.pending_user_message = message
                    session.pending_tool_name = exc.tool_name
                    session.pending_prompt = exc.message
                    session.pending_approval_id = approval_id
                    self._save_session(session)
                    payload = {
                        "status": "approval_required",
                        "session_id": session.session_id,
                        "approval_id": approval_id,
                        "tool_name": exc.tool_name,
                        "message": exc.message,
                    }
                    if emit:
                        emit("approval_required", payload)
                    return payload
                except LLMError as exc:
                    payload = {
                        "status": "error",
                        "session_id": session.session_id,
                        "error": str(exc),
                    }
                    self._save_session(session)
                    if emit:
                        emit("error", payload)
                    return payload

                payload = {
                    "status": "ok",
                    "session_id": session.session_id,
                    "response": response,
                    "thinking": "".join(thinking_chunks).strip(),
                    "phases": phases,
                    "workspace_changes": workspace_changes[-1] if workspace_changes else None,
                    "plan_update": plan_updates[-1] if plan_updates else None,
                    "status_events": status_events,
                    "progress_events": progress_events,
                    "agent_team": self._team_snapshot(session),
                    "review_notes": session.agent.last_review_notes,
                    "display_model": session.agent.llm.get_display_model(),
                    "last_used_model": session.agent.llm.last_used_model,
                    "last_route_reason": session.agent.llm.last_route_reason,
                    "streamed_response": "".join(response_chunks).strip(),
                }
                self._save_session(session)

            return payload
        finally:
            with session.control_lock:
                if session.current_stop_event is stop_event:
                    session.current_message = None
                    session.current_stop_event = None
                    session.stop_requested = False

    def _stream_operation(self, operation: Callable[[Callable[[str, dict[str, Any]], None]], dict[str, Any]]) -> Iterator[dict[str, Any]]:
        event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def emit(event_name: str, payload: dict[str, Any]) -> None:
            event_queue.put({"event": event_name, "data": payload})

        def runner() -> None:
            final_status = "ok"
            try:
                result = operation(emit)
                final_status = result.get("status", "ok")
                event_queue.put({"event": "result", "data": result})
            except Exception as exc:  # pragma: no cover - defensive guard
                final_status = "error"
                event_queue.put(
                    {
                        "event": "error",
                        "data": {"status": "error", "error": f"{type(exc).__name__}: {exc}"},
                    }
                )
            finally:
                event_queue.put({"event": "done", "data": {"status": final_status}})
                event_queue.put(None)

        threading.Thread(target=runner, daemon=True).start()

        while True:
            item = event_queue.get()
            if item is None:
                break
            yield item

    def _build_session(
        self,
        *,
        config: NeuDevConfig,
        workspace: str,
        session_id: str,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> HostedSession:
        agent = Agent(config, workspace)
        permissions = HostedPermissionManager()
        permissions.auto_approve = config.auto_permission
        agent.permissions = permissions
        run_command = agent.tool_registry.get("run_command")
        if isinstance(run_command, RunCommandTool):
            extra_commands = [
                item.strip()
                for item in os.environ.get("NEUDEV_HOSTED_RUN_COMMAND_ALLOWLIST", "").split(",")
                if item.strip()
            ]
            run_command.set_execution_mode(
                os.environ.get("NEUDEV_HOSTED_RUN_COMMAND_MODE", "restricted"),
                extra_allowed_commands=extra_commands,
            )
        now = datetime.now(UTC).isoformat()
        return HostedSession(
            session_id=session_id,
            agent=agent,
            workspace=workspace,
            created_at=created_at or now,
            updated_at=updated_at or now,
        )

    def _get_inference_client(self) -> OllamaClient:
        if self._inference_client is None:
            self._inference_client = OllamaClient(self.base_config.clone())
        return self._inference_client

    def _session_snapshot(self, session: HostedSession) -> dict[str, Any]:
        return {
            "status": "ok",
            "session_id": session.session_id,
            "workspace": session.workspace,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "pending_approval": self._pending_snapshot(session),
            "config": self._config_snapshot(session),
        }

    def _session_listing(self, session: HostedSession) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "workspace": session.workspace,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "messages_count": session.agent.session.messages_count,
            "pending_approval": bool(session.pending_approval_id),
            "pending_tool_name": session.pending_tool_name,
            "model": session.agent.llm.get_display_model(),
            "agent_mode": session.config.agent_mode,
        }

    def _config_snapshot(self, session: HostedSession) -> dict[str, Any]:
        workspace_info = session.agent.context.analyze()
        run_command = session.agent.tool_registry.get("run_command")
        return {
            "session_id": session.session_id,
            "workspace": session.workspace,
            "runtime_mode": "remote",
            "model": session.agent.llm.get_display_model(),
            "response_language": session.config.response_language,
            "agent_mode": session.config.agent_mode,
            "show_thinking": session.config.show_thinking,
            "auto_permission": session.config.auto_permission,
            "command_policy": getattr(run_command, "execution_mode", "unknown"),
            "project_type": workspace_info.get("project_type", "unknown"),
            "technologies": workspace_info.get("technologies", []),
            "memory_enabled": session.agent.context.memory.has_saved_memory(),
        }

    @staticmethod
    def _team_snapshot(session: HostedSession) -> dict[str, str] | None:
        if session.agent.last_agent_team is None:
            return None
        return {
            "planner": session.agent.last_agent_team.planner,
            "executor": session.agent.last_agent_team.executor,
            "reviewer": session.agent.last_agent_team.reviewer,
        }

    @staticmethod
    def _pending_snapshot(session: HostedSession) -> dict[str, Any] | None:
        if not session.pending_approval_id:
            return None
        return {
            "approval_id": session.pending_approval_id,
            "tool_name": session.pending_tool_name,
            "message": session.pending_prompt,
        }

    def _resolve_workspace(self, requested: str | None) -> str:
        if not requested:
            return str(self.allowed_root)

        candidate = Path(requested).expanduser()
        if not candidate.is_absolute():
            candidate = self.allowed_root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.allowed_root)
        except ValueError as exc:
            raise ValueError(f"Workspace must stay inside the allowed root: {self.allowed_root}") from exc
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"Workspace not found: {resolved}")
        return str(resolved)

    def _get_session(self, session_id: str) -> HostedSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise KeyError(f"Unknown session '{session_id}'.")
        return session

    def _load_sessions(self) -> None:
        for snapshot_path in sorted(self.storage_dir.glob("*.json")):
            try:
                data = json.loads(snapshot_path.read_text(encoding="utf-8"))
                session = self._restore_session(data)
            except Exception:
                continue
            self.sessions[session.session_id] = session

    def _restore_session(self, data: dict[str, Any]) -> HostedSession:
        session_id = str(data["session_id"])
        workspace = self._resolve_workspace(data.get("workspace"))
        config_payload = data.get("config") or {}
        config_data = asdict(self.base_config)
        config_data.update({key: value for key, value in config_payload.items() if key in config_data})
        config = NeuDevConfig(**config_data)
        session = self._build_session(
            config=config,
            workspace=workspace,
            session_id=session_id,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
        permissions = session.agent.permissions
        permissions._session_approvals = dict(data.get("session_approvals") or {})
        session.agent.conversation = [dict(item) for item in data.get("conversation") or session.agent.conversation]
        session.agent.refresh_context()
        session.agent.session.actions = [ActionRecord(**item) for item in data.get("actions", [])]
        session.agent.session.file_backups = [FileBackup(**item) for item in data.get("file_backups", [])]
        session.agent.session.test_files = list(data.get("test_files", []))
        session.agent.session.messages_count = int(data.get("messages_count", 0))
        session.agent.last_review_notes = str(data.get("last_review_notes", ""))
        session.agent.last_plan_items = [str(item) for item in data.get("last_plan_items", [])]
        session.agent.last_plan_conventions = [str(item) for item in data.get("last_plan_conventions", [])]
        session.agent.last_plan_progress = [dict(item) for item in data.get("last_plan_progress", [])]
        session.pending_user_message = data.get("pending_user_message")
        session.pending_tool_name = data.get("pending_tool_name")
        session.pending_prompt = data.get("pending_prompt")
        session.pending_approval_id = data.get("pending_approval_id")
        session.agent.context.mark_workspace_state()
        return session

    def _save_session(self, session: HostedSession) -> None:
        session.updated_at = datetime.now(UTC).isoformat()
        payload = self._serialize_session(session)
        target = self._session_file(session.session_id)
        temp_path = target.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(target)

    def _serialize_session(self, session: HostedSession) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "workspace": session.workspace,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "config": asdict(session.config),
            "conversation": session.agent.conversation,
            "actions": [asdict(item) for item in session.agent.session.actions],
            "file_backups": [asdict(item) for item in session.agent.session.file_backups],
            "test_files": list(session.agent.session.test_files),
            "messages_count": session.agent.session.messages_count,
            "session_approvals": dict(session.agent.permissions._session_approvals),
            "last_review_notes": session.agent.last_review_notes,
            "last_plan_items": list(session.agent.last_plan_items),
            "last_plan_conventions": list(session.agent.last_plan_conventions),
            "last_plan_progress": [dict(item) for item in session.agent.last_plan_progress],
            "pending_user_message": session.pending_user_message,
            "pending_tool_name": session.pending_tool_name,
            "pending_prompt": session.pending_prompt,
            "pending_approval_id": session.pending_approval_id,
        }

    def _delete_session_file(self, session_id: str) -> None:
        target = self._session_file(session_id)
        if target.exists():
            target.unlink()

    def _session_file(self, session_id: str) -> Path:
        return self.storage_dir / f"{session_id}.json"


class NeuDevHTTPRequestHandler(BaseHTTPRequestHandler):
    """Simple JSON + SSE API handler."""

    server: "NeuDevHTTPServer"

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _dispatch(self, method: str) -> None:
        try:
            path_only = self.path.split("?", 1)[0]
            if path_only == "/health" and method == "GET":
                transports = ["sse"]
                if self.server.websocket_port is not None:
                    transports.append("websocket")
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "service": __app_name__,
                        "stream_transports": transports,
                        "websocket_port": self.server.websocket_port,
                        "websocket_path": DEFAULT_WEBSOCKET_PATH if self.server.websocket_port is not None else None,
                    },
                )
                return

            if not self.server.service.authenticate(self.headers.get("Authorization")):
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
                return

            payload = self._read_json_body() if method == "POST" else {}
            path_parts = [part for part in path_only.split("/") if part]

            if path_parts == ["v1", "inference", "models"] and method == "GET":
                self._send_json(HTTPStatus.OK, self.server.service.list_inference_models())
                return
            if path_parts == ["v1", "inference", "chat"] and method == "POST":
                self._send_json(
                    HTTPStatus.OK,
                    self.server.service.chat_inference(
                        messages=payload.get("messages") or [],
                        model=payload.get("model"),
                        tools=payload.get("tools"),
                        think=bool(payload.get("think")),
                    ),
                )
                return
            if path_parts == ["v1", "inference", "chat", "stream"] and method == "POST":
                self._send_sse(
                    HTTPStatus.OK,
                    self.server.service.stream_inference_chat(
                        messages=payload.get("messages") or [],
                        model=payload.get("model"),
                        tools=payload.get("tools"),
                        think=bool(payload.get("think")),
                    ),
                )
                return

            if path_parts == ["v1", "sessions"] and method == "GET":
                self._send_json(HTTPStatus.OK, self.server.service.list_sessions())
                return
            if path_parts == ["v1", "sessions"] and method == "POST":
                result = self.server.service.create_session(
                    workspace=payload.get("workspace"),
                    model=payload.get("model"),
                    language=payload.get("language"),
                    agent_mode=payload.get("agent_mode"),
                    auto_permission=payload.get("auto_permission"),
                )
                self._send_json(HTTPStatus.OK, result)
                return

            if len(path_parts) >= 3 and path_parts[0] == "v1" and path_parts[1] == "sessions":
                session_id = path_parts[2]

                if len(path_parts) == 3 and method == "GET":
                    self._send_json(HTTPStatus.OK, self.server.service.get_session(session_id))
                    return
                if len(path_parts) == 4 and path_parts[3] == "history" and method == "GET":
                    self._send_json(HTTPStatus.OK, self.server.service.get_history(session_id))
                    return
                if len(path_parts) == 4 and path_parts[3] == "config":
                    if method == "GET":
                        self._send_json(HTTPStatus.OK, self.server.service.get_config(session_id))
                    else:
                        self._send_json(HTTPStatus.OK, self.server.service.update_config(session_id, **payload))
                    return
                if len(path_parts) == 4 and path_parts[3] == "models":
                    if method == "GET":
                        self._send_json(HTTPStatus.OK, self.server.service.list_models(session_id))
                    else:
                        self._send_json(
                            HTTPStatus.OK,
                            self.server.service.switch_model(session_id, payload.get("selection", "")),
                        )
                    return
                if len(path_parts) == 4 and path_parts[3] == "messages" and method == "POST":
                    self._send_json(
                        HTTPStatus.OK,
                        self.server.service.process_message(session_id, payload.get("message", "")),
                    )
                    return
                if len(path_parts) == 5 and path_parts[3] == "messages" and path_parts[4] == "stream" and method == "POST":
                    self._send_sse(HTTPStatus.OK, self.server.service.stream_message(session_id, payload.get("message", "")))
                    return
                if len(path_parts) == 4 and path_parts[3] == "undo" and method == "POST":
                    self._send_json(HTTPStatus.OK, self.server.service.undo_last_change(session_id))
                    return
                if len(path_parts) == 4 and path_parts[3] == "clear" and method == "POST":
                    self._send_json(HTTPStatus.OK, self.server.service.clear_history(session_id))
                    return
                if len(path_parts) == 4 and path_parts[3] == "summary" and method == "GET":
                    self._send_json(HTTPStatus.OK, self.server.service.get_summary(session_id))
                    return
                if len(path_parts) == 4 and path_parts[3] == "stop" and method == "POST":
                    self._send_json(HTTPStatus.OK, self.server.service.request_stop(session_id))
                    return
                if len(path_parts) == 4 and path_parts[3] == "close" and method == "POST":
                    self._send_json(HTTPStatus.OK, self.server.service.close_session(session_id))
                    return
                if len(path_parts) == 5 and path_parts[3] == "approvals" and method == "POST":
                    self._send_json(
                        HTTPStatus.OK,
                        self.server.service.respond_to_approval(
                            session_id,
                            path_parts[4],
                            bool(payload.get("approved")),
                            payload.get("scope"),
                        ),
                    )
                    return
                if (
                    len(path_parts) == 6
                    and path_parts[3] == "approvals"
                    and path_parts[5] == "stream"
                    and method == "POST"
                ):
                    self._send_sse(
                        HTTPStatus.OK,
                        self.server.service.stream_approval(
                            session_id,
                            path_parts[4],
                            bool(payload.get("approved")),
                            payload.get("scope"),
                        ),
                    )
                    return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown endpoint: {self.path}"})
        except KeyError as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except LLMError as exc:
            self._send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(exc).__name__}: {exc}"})

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        if not body.strip():
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON body: {exc}") from exc

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_sse(self, status: HTTPStatus, stream: Iterator[dict[str, Any]]) -> None:
        self.send_response(int(status))
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            for item in stream:
                event_name = item.get("event", "message")
                payload = json.dumps(item.get("data", {}), ensure_ascii=False)
                raw = f"event: {event_name}\ndata: {payload}\n\n".encode("utf-8")
                self.wfile.write(raw)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


class NeuDevHTTPServer(ThreadingHTTPServer):
    """HTTP server that carries a HostedSessionService instance."""

    daemon_threads = True

    def __init__(self, server_address, service: HostedSessionService, *, websocket_port: int | None = None):
        super().__init__(server_address, NeuDevHTTPRequestHandler)
        self.service = service
        self.websocket_port = websocket_port


class NeuDevWebSocketServer:
    """Synchronous WebSocket server for streaming hosted events."""

    def __init__(self, host: str, port: int, service: HostedSessionService):
        if websocket_serve is None:
            raise RuntimeError("websockets is not installed")
        self.service = service
        sock = socket.create_server((host, port), reuse_port=False)
        self.server_port = sock.getsockname()[1]
        self._server = websocket_serve(self._handle_connection, sock=sock)

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()

    def _handle_connection(self, websocket: ServerConnection) -> None:
        try:
            raw = websocket.recv()
            payload = json.loads(raw)
            token = str(payload.get("api_key", "")).strip()
            if not self.service.authenticate(f"Bearer {token}"):
                websocket.send(json.dumps({"event": "error", "data": {"status": "error", "error": "Unauthorized"}}))
                return

            action = str(payload.get("action", "")).strip().lower()
            if action == "stream_message":
                stream = self.service.stream_message(str(payload.get("session_id", "")), str(payload.get("message", "")))
            elif action == "stream_approval":
                stream = self.service.stream_approval(
                    str(payload.get("session_id", "")),
                    str(payload.get("approval_id", "")),
                    bool(payload.get("approved")),
                    str(payload.get("scope", "")) or None,
                )
            else:
                websocket.send(
                    json.dumps(
                        {
                            "event": "error",
                            "data": {"status": "error", "error": f"Unknown websocket action: {action or '(empty)'}"},
                        }
                    )
                )
                return

            for item in stream:
                websocket.send(json.dumps(item))
        except OSError:
            return
        except Exception as exc:
            if ConnectionClosed is not None and isinstance(exc, ConnectionClosed):
                return
            try:
                websocket.send(
                    json.dumps({"event": "error", "data": {"status": "error", "error": f"{type(exc).__name__}: {exc}"}})
                )
            except Exception:
                return


def create_server(
    host: str,
    port: int,
    service: HostedSessionService,
    *,
    websocket_port: int | None = None,
) -> NeuDevHTTPServer:
    return NeuDevHTTPServer((host, port), service, websocket_port=websocket_port)


def create_websocket_server(host: str, port: int, service: HostedSessionService) -> NeuDevWebSocketServer:
    return NeuDevWebSocketServer(host, port, service)


def serve_api(
    *,
    host: str,
    port: int,
    workspace: str,
    api_key: str,
    ollama_host: str | None = None,
    model: str | None = None,
    language: str | None = None,
    agent_mode: str | None = None,
    auto_permission: bool = False,
    session_store: str | None = None,
    websocket_port: int | None = None,
    disable_websocket: bool = False,
) -> None:
    config = NeuDevConfig.load().clone()
    updates: dict[str, Any] = {"runtime_mode": "local", "auto_permission": auto_permission}
    if ollama_host:
        updates["ollama_host"] = ollama_host
    if model:
        updates["model"] = model
    if language:
        updates["response_language"] = language
    if agent_mode:
        updates["agent_mode"] = agent_mode
    config.apply_runtime_updates(persist=False, **updates)

    effective_api_key = api_key or os.environ.get("NEUDEV_API_KEY", "")
    if not effective_api_key:
        raise SystemExit("API key is required. Pass --api-key or set NEUDEV_API_KEY.")

    service = HostedSessionService(config, workspace, effective_api_key, storage_dir=session_store)
    websocket_server = None
    websocket_thread = None

    if not disable_websocket and websocket_serve is not None:
        effective_ws_port = websocket_port if websocket_port is not None else port + 1
        websocket_server = create_websocket_server(host, effective_ws_port, service)
        websocket_thread = threading.Thread(target=websocket_server.serve_forever, daemon=True)
        websocket_thread.start()

    server = create_server(
        host,
        port,
        service,
        websocket_port=websocket_server.server_port if websocket_server is not None else None,
    )
    print(f"{__app_name__} server listening on http://{host}:{server.server_port}")
    print(f"Workspace root: {Path(workspace).resolve()}")
    print(f"Session store: {service.storage_dir}")
    print(f"Hosted run_command policy: {os.environ.get('NEUDEV_HOSTED_RUN_COMMAND_MODE', 'restricted')}")
    if websocket_server is not None:
        print(f"WebSocket stream listening on ws://{host}:{websocket_server.server_port}{DEFAULT_WEBSOCKET_PATH}")

    try:
        server.serve_forever()
    finally:
        if websocket_server is not None:
            websocket_server.shutdown()
        if websocket_thread is not None:
            websocket_thread.join(timeout=2)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m neudev.server", description="Run the hosted NeuDev API server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host. Default 0.0.0.0")
    parser.add_argument("--port", type=int, default=8765, help="Bind port. Default 8765")
    parser.add_argument("--workspace", "-w", default=os.getcwd(), help="Workspace root served by the API")
    parser.add_argument("--api-key", default="", help="Bearer API key required by clients")
    parser.add_argument("--ollama-host", default=None, help="Ollama API base URL for the hosted runtime")
    parser.add_argument("--model", default=None, help="Default hosted model")
    parser.add_argument("--language", default=None, help="Default hosted reply language")
    parser.add_argument("--agents", choices=["single", "team", "parallel"], default=None, help="Hosted agent mode")
    parser.add_argument("--auto-permission", action="store_true", help="Auto-approve destructive tools on the hosted runtime")
    parser.add_argument("--session-store", default=None, help="Directory for persisted hosted session snapshots")
    parser.add_argument("--ws-port", type=int, default=None, help="Optional WebSocket port for remote streaming")
    parser.add_argument("--disable-websocket", action="store_true", help="Disable the WebSocket stream server")
    args = parser.parse_args()

    serve_api(
        host=args.host,
        port=args.port,
        workspace=args.workspace,
        api_key=args.api_key,
        ollama_host=args.ollama_host,
        model=args.model,
        language=args.language,
        agent_mode=args.agents,
        auto_permission=args.auto_permission,
        session_store=args.session_store,
        websocket_port=args.ws_port,
        disable_websocket=args.disable_websocket,
    )


if __name__ == "__main__":
    main()
