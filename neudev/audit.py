"""Audit logging and rate limiting for NeuDev security."""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class AuditEventType(Enum):
    """Types of audit events."""

    TOOL_EXECUTE = "tool_execute"
    TOOL_SUCCESS = "tool_success"
    TOOL_FAILURE = "tool_failure"
    TOOL_DENIED = "tool_denied"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    COMMAND_EXECUTE = "command_execute"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    RATE_LIMIT_HIT = "rate_limit_hit"
    SECURITY_BLOCK = "security_block"


@dataclass
class AuditEvent:
    """Represents an audit log event."""

    event_type: AuditEventType
    timestamp: str
    session_id: Optional[str]
    tool_name: Optional[str]
    target: Optional[str]
    details: dict[str, Any]
    success: bool
    user_id: Optional[str] = None
    ip_address: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "target": self.target,
            "details": self.details,
            "success": self.success,
            "user_id": self.user_id,
            "ip_address": self.ip_address,
        }


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    # Maximum calls per tool per minute
    max_per_minute: int = 60
    # Maximum calls per tool per hour
    max_per_hour: int = 1000
    # Maximum destructive operations per minute
    max_destructive_per_minute: int = 10
    # Cooldown period after hitting limit (seconds)
    cooldown_seconds: int = 60


# Tools considered destructive
DESTRUCTIVE_TOOLS = {
    "write_file",
    "edit_file",
    "smart_edit_file",
    "python_ast_edit",
    "js_ts_symbol_edit",
    "delete_file",
    "run_command",
    "diagnostics",
    "changed_files_diagnostics",
}


class RateLimiter:
    """Rate limiter for tool execution."""

    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()
        self._lock = threading.Lock()
        # Tool call timestamps: {tool_name: [timestamps]}
        self._tool_calls: dict[str, list[float]] = defaultdict(list)
        # Destructive operation timestamps
        self._destructive_calls: list[float] = []
        # Rate limit hit tracking: {tool_name: cooldown_end_time}
        self._cooldowns: dict[str, float] = {}

    def check_rate_limit(self, tool_name: str, is_destructive: bool = False) -> tuple[bool, str]:
        """
        Check if a tool call is within rate limits.

        Returns:
            Tuple of (allowed, reason_message)
        """
        now = time.time()

        with self._lock:
            # Check if in cooldown
            if tool_name in self._cooldowns:
                if now < self._cooldowns[tool_name]:
                    remaining = int(self._cooldowns[tool_name] - now)
                    return False, f"Rate limit hit. Cooldown: {remaining}s remaining"
                else:
                    # Cooldown expired, clear it
                    del self._cooldowns[tool_name]

            # Clean old entries (older than 1 hour)
            cutoff = now - 3600
            self._tool_calls[tool_name] = [t for t in self._tool_calls[tool_name] if t > cutoff]

            # Check per-minute limit
            minute_ago = now - 60
            recent_calls = [t for t in self._tool_calls[tool_name] if t > minute_ago]
            if len(recent_calls) >= self.config.max_per_minute:
                self._cooldowns[tool_name] = now + self.config.cooldown_seconds
                return False, f"Rate limit exceeded: {self.config.max_per_minute} calls/minute"

            # Check per-hour limit
            hour_ago = now - 3600
            hour_calls = [t for t in self._tool_calls[tool_name] if t > hour_ago]
            if len(hour_calls) >= self.config.max_per_hour:
                self._cooldowns[tool_name] = now + self.config.cooldown_seconds * 2
                return False, f"Rate limit exceeded: {self.config.max_per_hour} calls/hour"

            # Check destructive operation limits
            if is_destructive:
                self._destructive_calls = [t for t in self._destructive_calls if t > minute_ago]
                if len(self._destructive_calls) >= self.config.max_destructive_per_minute:
                    self._cooldowns[tool_name] = now + self.config.cooldown_seconds
                    return (
                        False,
                        f"Destructive operation limit exceeded: {self.config.max_destructive_per_minute}/minute",
                    )

            return True, "OK"

    def record_call(self, tool_name: str, is_destructive: bool = False) -> None:
        """Record a tool call for rate limiting."""
        now = time.time()
        with self._lock:
            self._tool_calls[tool_name].append(now)
            if is_destructive:
                self._destructive_calls.append(now)

    def get_usage_stats(self, tool_name: Optional[str] = None) -> dict[str, Any]:
        """Get rate limit usage statistics."""
        now = time.time()
        minute_ago = now - 60
        hour_ago = now - 3600

        with self._lock:
            if tool_name:
                calls = self._tool_calls.get(tool_name, [])
                minute_count = len([t for t in calls if t > minute_ago])
                hour_count = len([t for t in calls if t > hour_ago])
                cooldown_remaining = max(0, self._cooldowns.get(tool_name, 0) - now)

                return {
                    "tool": tool_name,
                    "calls_last_minute": minute_count,
                    "calls_last_hour": hour_count,
                    "limit_per_minute": self.config.max_per_minute,
                    "limit_per_hour": self.config.max_per_hour,
                    "cooldown_remaining_seconds": cooldown_remaining,
                    "is_rate_limited": cooldown_remaining > 0,
                }

            # Stats for all tools
            stats = {}
            for name in self._tool_calls:
                stats[name] = self.get_usage_stats(name)
            return stats


class AuditLogger:
    """Audit logger for security and compliance."""

    def __init__(
        self,
        log_dir: Optional[str | Path] = None,
        enabled: bool = True,
        log_level: str = "INFO",
    ):
        self.enabled = enabled
        self.log_dir = Path(log_dir) if log_dir else Path.home() / ".neudev" / "audit_logs"
        if enabled:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._current_session: Optional[str] = None
        self._current_user: Optional[str] = None

    def set_session(self, session_id: str, user_id: Optional[str] = None) -> None:
        """Set the current session context."""
        self._current_session = session_id
        self._current_user = user_id

    def log(
        self,
        event_type: AuditEventType,
        tool_name: Optional[str] = None,
        target: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        success: bool = True,
    ) -> None:
        """Log an audit event."""
        if not self.enabled:
            return

        event = AuditEvent(
            event_type=event_type,
            timestamp=datetime.utcnow().isoformat() + "Z",
            session_id=self._current_session,
            tool_name=tool_name,
            target=target,
            details=details or {},
            success=success,
            user_id=self._current_user,
        )

        with self._lock:
            self._write_event(event)

    def _write_event(self, event: AuditEvent) -> None:
        """Write event to log file."""
        log_file = self.log_dir / f"audit_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"

        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except (OSError, IOError) as e:
            # Don't fail if logging fails, but note it
            print(f"Warning: Failed to write audit log: {e}")

    def log_tool_execute(
        self,
        tool_name: str,
        target: Optional[str] = None,
        args: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log tool execution start."""
        self.log(
            AuditEventType.TOOL_EXECUTE,
            tool_name=tool_name,
            target=target,
            details={"args": args} if args else {},
            success=True,
        )

    def log_tool_success(
        self,
        tool_name: str,
        target: Optional[str] = None,
        result_summary: Optional[str] = None,
    ) -> None:
        """Log successful tool execution."""
        event_type = AuditEventType.TOOL_SUCCESS
        if tool_name in {"read_file", "read_files_batch", "list_directory"}:
            event_type = AuditEventType.FILE_READ
        elif tool_name in {"write_file", "edit_file", "smart_edit_file"}:
            event_type = AuditEventType.FILE_WRITE
        elif tool_name == "delete_file":
            event_type = AuditEventType.FILE_DELETE
        elif tool_name == "run_command":
            event_type = AuditEventType.COMMAND_EXECUTE

        self.log(
            event_type,
            tool_name=tool_name,
            target=target,
            details={"result_summary": result_summary} if result_summary else {},
            success=True,
        )

    def log_tool_failure(
        self,
        tool_name: str,
        target: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Log failed tool execution."""
        self.log(
            AuditEventType.TOOL_FAILURE,
            tool_name=tool_name,
            target=target,
            details={"error": error} if error else {},
            success=False,
        )

    def log_security_block(
        self,
        tool_name: str,
        reason: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log security-blocked operation."""
        self.log(
            AuditEventType.SECURITY_BLOCK,
            tool_name=tool_name,
            details={"reason": reason, **(details or {})},
            success=False,
        )

    def log_rate_limit_hit(
        self,
        tool_name: str,
        reason: str,
    ) -> None:
        """Log rate limit hit."""
        self.log(
            AuditEventType.RATE_LIMIT_HIT,
            tool_name=tool_name,
            details={"reason": reason},
            success=False,
        )

    def get_recent_events(
        self,
        limit: int = 100,
        event_type: Optional[AuditEventType] = None,
        tool_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Get recent audit events."""
        events = []
        log_file = self.log_dir / f"audit_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"

        if not log_file.exists():
            return []

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        event = json.loads(line.strip())
                        if event_type and event.get("event_type") != event_type.value:
                            continue
                        if tool_name and event.get("tool_name") != tool_name:
                            continue
                        events.append(event)
                    except json.JSONDecodeError:
                        continue

                    if len(events) >= limit:
                        break
        except (OSError, IOError):
            return []

        return list(reversed(events))


class SecurityMiddleware:
    """Middleware combining rate limiting and audit logging."""

    def __init__(
        self,
        audit_logger: Optional[AuditLogger] = None,
        rate_limiter: Optional[RateLimiter] = None,
        session_id: Optional[str] = None,
    ):
        self.audit_logger = audit_logger or AuditLogger()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.session_id = session_id

    def before_tool_execute(
        self,
        tool_name: str,
        target: Optional[str] = None,
        args: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        """
        Check before tool execution.

        Returns:
            Tuple of (allowed, reason)
        """
        is_destructive = tool_name in DESTRUCTIVE_TOOLS

        # Check rate limit
        allowed, reason = self.rate_limiter.check_rate_limit(tool_name, is_destructive)
        if not allowed:
            self.audit_logger.log_rate_limit_hit(tool_name, reason)
            return False, reason

        # Record the call
        self.rate_limiter.record_call(tool_name, is_destructive)

        # Log execution
        self.audit_logger.log_tool_execute(tool_name, target, args)

        return True, "OK"

    def after_tool_success(
        self,
        tool_name: str,
        target: Optional[str] = None,
        result_summary: Optional[str] = None,
    ) -> None:
        """Log successful tool execution."""
        self.audit_logger.log_tool_success(tool_name, target, result_summary)

    def after_tool_failure(
        self,
        tool_name: str,
        target: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Log failed tool execution."""
        self.audit_logger.log_tool_failure(tool_name, target, error)


# Global instances for easy access
_default_audit_logger: Optional[AuditLogger] = None
_default_rate_limiter: Optional[RateLimiter] = None


def get_audit_logger() -> AuditLogger:
    """Get or create the default audit logger."""
    global _default_audit_logger
    if _default_audit_logger is None:
        _default_audit_logger = AuditLogger()
    return _default_audit_logger


def get_rate_limiter() -> RateLimiter:
    """Get or create the default rate limiter."""
    global _default_rate_limiter
    if _default_rate_limiter is None:
        _default_rate_limiter = RateLimiter()
    return _default_rate_limiter


def create_security_middleware(session_id: Optional[str] = None) -> SecurityMiddleware:
    """Create security middleware with default components."""
    return SecurityMiddleware(
        audit_logger=get_audit_logger(),
        rate_limiter=get_rate_limiter(),
        session_id=session_id,
    )
