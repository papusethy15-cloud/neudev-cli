"""Observability module for NeuDev - structured logging, metrics, and tracing."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generator, Optional

# Optional imports for enhanced observability
try:
    import structlog
    STRUCTLOG_AVAILABLE = True
except ImportError:
    STRUCTLOG_AVAILABLE = False
    structlog = None

try:
    from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    Counter = Gauge = Histogram = CollectorRegistry = None

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.trace import Span, Status, StatusCode
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    trace = Span = Status = StatusCode = None


class LogLevel(Enum):
    """Log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogContext:
    """Context for structured logging."""

    session_id: Optional[str] = None
    user_id: Optional[str] = None
    request_id: Optional[str] = None
    tool_name: Optional[str] = None
    model_name: Optional[str] = None
    workspace: Optional[str] = None
    custom_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "model_name": self.model_name,
            "workspace": self.workspace,
            **self.custom_fields,
        }


class NeuDevLogger:
    """Structured logger for NeuDev."""

    def __init__(
        self,
        name: str = "neudev",
        level: LogLevel = LogLevel.INFO,
        log_format: str = "json",
        output_file: Optional[str | Path] = None,
    ):
        self.name = name
        self.level = level
        self.log_format = log_format
        self.output_file = Path(output_file) if output_file else None
        self._context = threading.local()
        self._lock = threading.Lock()

        # Set up logging
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Configure logging handlers and formatters."""
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(getattr(logging, self.level.value))

        # Clear existing handlers
        self.logger.handlers = []

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, self.level.value))

        if self.log_format == "json":
            if STRUCTLOG_AVAILABLE:
                # Use structlog for JSON formatting
                structlog.configure(
                    processors=[
                        structlog.stdlib.filter_by_level,
                        structlog.stdlib.add_logger_name,
                        structlog.stdlib.add_log_level,
                        structlog.processors.TimeStamper(fmt="iso"),
                        structlog.processors.JSONRenderer(),
                    ],
                    context_class=dict,
                    logger_factory=structlog.stdlib.LoggerFactory(),
                    wrapper_class=structlog.stdlib.BoundLogger,
                    cache_logger_on_first_use=True,
                )
                self.logger = structlog.get_logger(self.name)
            else:
                # Fallback to simple JSON formatting
                console_handler.setFormatter(logging.Formatter(
                    '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'
                ))
        else:
            # Human-readable format
            console_handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            ))

        self.logger.addHandler(console_handler)

        # File handler if output_file is specified
        if self.output_file:
            self.output_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(self.output_file, encoding="utf-8")
            file_handler.setLevel(getattr(logging, self.level.value))
            if self.log_format == "json":
                file_handler.setFormatter(logging.Formatter(
                    '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'
                ))
            else:
                file_handler.setFormatter(logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                ))
            self.logger.addHandler(file_handler)

    def _get_context(self) -> LogContext:
        """Get current thread's log context."""
        if not hasattr(self._context, "log_context"):
            self._context.log_context = LogContext()
        return self._context.log_context

    def set_context(self, **kwargs) -> None:
        """Set log context for current thread."""
        context = self._get_context()
        for key, value in kwargs.items():
            if hasattr(context, key):
                setattr(context, key, value)
            else:
                context.custom_fields[key] = value

    def clear_context(self) -> None:
        """Clear log context."""
        self._context.log_context = LogContext()

    def _log(
        self,
        level: LogLevel,
        message: str,
        **kwargs,
    ) -> None:
        """Log a message with context."""
        context = self._get_context()
        extra = context.to_dict()
        extra.update(kwargs)

        if STRUCTLOG_AVAILABLE and isinstance(self.logger, structlog.stdlib.BoundLogger):
            # Use structlog
            log_method = getattr(self.logger, level.value.lower())
            log_method(message, **extra)
        else:
            # Use standard logging
            log_method = getattr(self.logger, level.value.lower())
            extra_str = " ".join(f"{k}={v}" for k, v in extra.items() if v is not None)
            log_method(f"{message} {extra_str}".strip())

    def debug(self, message: str, **kwargs) -> None:
        """Log debug message."""
        self._log(LogLevel.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        """Log info message."""
        self._log(LogLevel.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        """Log warning message."""
        self._log(LogLevel.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        """Log error message."""
        self._log(LogLevel.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs) -> None:
        """Log critical message."""
        self._log(LogLevel.CRITICAL, message, **kwargs)

    def exception(self, message: str, exc: Optional[Exception] = None, **kwargs) -> None:
        """Log exception with traceback."""
        if exc is None:
            self.logger.exception(message, **kwargs)
        else:
            self.error(f"{message} - {type(exc).__name__}: {exc}", **kwargs)


class NeuDevMetrics:
    """Metrics collector using Prometheus."""

    def __init__(self, registry: Optional[CollectorRegistry] = None):
        self.registry = registry or CollectorRegistry()
        self._initialized = False

        if PROMETHEUS_AVAILABLE:
            self._init_metrics()

    def _init_metrics(self) -> None:
        """Initialize Prometheus metrics."""
        # Counter metrics
        self.tool_calls_total = Counter(
            "neudev_tool_calls_total",
            "Total number of tool calls",
            ["tool_name", "success"],
            registry=self.registry,
        )

        self.model_requests_total = Counter(
            "neudev_model_requests_total",
            "Total number of model requests",
            ["model_name", "status"],
            registry=self.registry,
        )

        self.sessions_total = Counter(
            "neudev_sessions_total",
            "Total number of sessions",
            ["runtime_mode"],
            registry=self.registry,
        )

        self.errors_total = Counter(
            "neudev_errors_total",
            "Total number of errors",
            ["error_type", "component"],
            registry=self.registry,
        )

        # Gauge metrics
        self.active_sessions = Gauge(
            "neudev_active_sessions",
            "Number of active sessions",
            registry=self.registry,
        )

        self.context_tokens = Gauge(
            "neudev_context_tokens",
            "Current context token count",
            registry=self.registry,
        )

        # Histogram metrics
        self.tool_duration = Histogram(
            "neudev_tool_duration_seconds",
            "Tool execution duration in seconds",
            ["tool_name"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
            registry=self.registry,
        )

        self.model_latency = Histogram(
            "neudev_model_latency_seconds",
            "Model response latency in seconds",
            ["model_name"],
            buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
            registry=self.registry,
        )

        self.request_size = Histogram(
            "neudev_request_size_bytes",
            "Request size in bytes",
            ["request_type"],
            buckets=(100, 500, 1000, 5000, 10000, 50000, 100000),
            registry=self.registry,
        )

        self._initialized = True

    def record_tool_call(self, tool_name: str, success: bool, duration: float) -> None:
        """Record a tool call."""
        if not self._initialized:
            return
        self.tool_calls_total.labels(tool_name=tool_name, success=str(success)).inc()
        self.tool_duration.labels(tool_name=tool_name).observe(duration)

    def record_model_request(
        self,
        model_name: str,
        status: str,
        latency: float,
        tokens: Optional[int] = None,
    ) -> None:
        """Record a model request."""
        if not self._initialized:
            return
        self.model_requests_total.labels(model_name=model_name, status=status).inc()
        self.model_latency.labels(model_name=model_name).observe(latency)
        if tokens:
            self.context_tokens.set(tokens)

    def record_error(self, error_type: str, component: str) -> None:
        """Record an error."""
        if not self._initialized:
            return
        self.errors_total.labels(error_type=error_type, component=component).inc()

    def record_session_start(self, runtime_mode: str) -> None:
        """Record session start."""
        if not self._initialized:
            return
        self.sessions_total.labels(runtime_mode=runtime_mode).inc()
        self.active_sessions.inc()

    def record_session_end(self) -> None:
        """Record session end."""
        if not self._initialized:
            return
        self.active_sessions.dec()

    def get_metrics(self) -> str:
        """Get metrics in Prometheus format."""
        if not self._initialized or not PROMETHEUS_AVAILABLE:
            return ""
        return generate_latest(self.registry).decode("utf-8")

    def get_metrics_json(self) -> dict[str, Any]:
        """Get metrics as JSON."""
        if not self._initialized or not PROMETHEUS_AVAILABLE:
            return {}

        metrics = {}
        for line in self.get_metrics().split("\n"):
            if line and not line.startswith("#"):
                parts = line.split(" ")
                if len(parts) >= 2:
                    metric_name = parts[0]
                    metric_value = parts[1]
                    metrics[metric_name] = float(metric_value)

        return metrics


class NeuDevTracer:
    """Distributed tracing using OpenTelemetry."""

    def __init__(self, service_name: str = "neudev", export_to_console: bool = False):
        self.service_name = service_name
        self._tracer = None
        self._initialized = False

        if OTEL_AVAILABLE:
            try:
                provider = TracerProvider()
                if export_to_console:
                    processor = BatchSpanProcessor(ConsoleSpanExporter())
                    provider.add_span_processor(processor)
                trace.set_tracer_provider(provider)
                self._tracer = trace.get_tracer(service_name)
                self._initialized = True
            except Exception as e:
                print(f"Warning: Failed to initialize OpenTelemetry: {e}")

    @contextmanager
    def trace(
        self,
        name: str,
        kind: Any = None,  # type: trace.SpanKind (deferred to avoid import error)
        attributes: Optional[dict[str, Any]] = None,
    ) -> Generator[Optional[Any], None, None]:  # type: Generator[Optional[Span], None, None]
        """Create a trace span."""
        if not self._initialized or self._tracer is None:
            yield None
            return

        # Import here to avoid evaluation at class definition time
        if OTEL_AVAILABLE and trace:
            from opentelemetry.trace import SpanKind, Status, StatusCode
            
            # Use default if kind not provided
            if kind is None:
                kind = SpanKind.INTERNAL
                
            with self._tracer.start_as_current_span(name, kind=kind) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                try:
                    yield span
                    span.set_status(Status(StatusCode.OK))
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    raise
        else:
            yield None

    @contextmanager
    def trace_tool_execution(
        self,
        tool_name: str,
        session_id: Optional[str] = None,
    ) -> Generator[Optional[Any], None, None]:  # type: Generator[Optional[Span], None, None]
        """Trace tool execution."""
        attributes = {
            "tool.name": tool_name,
            "tool.type": "function",
        }
        if session_id:
            attributes["session.id"] = session_id

        with self.trace(f"tool.{tool_name}", attributes=attributes) as span:
            yield span

    @contextmanager
    def trace_model_request(
        self,
        model_name: str,
        session_id: Optional[str] = None,
    ) -> Generator[Optional[Any], None, None]:  # type: Generator[Optional[Span], None, None]
        """Trace model request."""
        attributes = {
            "model.name": model_name,
        }
        if session_id:
            attributes["session.id"] = session_id

        with self.trace(f"model.{model_name}", attributes=attributes) as span:
            yield span

    @contextmanager
    def trace_agent_turn(
        self,
        session_id: str,
        message_length: int,
    ) -> Generator[Optional[Any], None, None]:  # type: Generator[Optional[Span], None, None]
        """Trace an agent turn."""
        attributes = {
            "session.id": session_id,
            "message.length": message_length,
        }

        with self.trace("agent.turn", attributes=attributes) as span:
            yield span


# Global instances
_default_logger: Optional[NeuDevLogger] = None
_default_metrics: Optional[NeuDevMetrics] = None
_default_tracer: Optional[NeuDevTracer] = None


def get_logger(name: str = "neudev") -> NeuDevLogger:
    """Get or create the default logger."""
    global _default_logger
    if _default_logger is None:
        log_file = os.environ.get("NEUDEV_LOG_FILE")
        log_level = os.environ.get("NEUDEV_LOG_LEVEL", "INFO")
        log_format = os.environ.get("NEUDEV_LOG_FORMAT", "json")

        _default_logger = NeuDevLogger(
            name=name,
            level=LogLevel[log_level.upper()],
            log_format=log_format,
            output_file=log_file,
        )
    return _default_logger


def get_metrics() -> NeuDevMetrics:
    """Get or create the default metrics collector."""
    global _default_metrics
    if _default_metrics is None:
        _default_metrics = NeuDevMetrics()
    return _default_metrics


def get_tracer(service_name: str = "neudev") -> NeuDevTracer:
    """Get or create the default tracer."""
    global _default_tracer
    if _default_tracer is None:
        export_enabled = os.environ.get("NEUDEV_ENABLE_TRACING", "false").lower() == "true"
        _default_tracer = NeuDevTracer(
            service_name=service_name,
            export_to_console=export_enabled,
        )
    return _default_tracer


@contextmanager
def observe_tool(tool_name: str, session_id: Optional[str] = None):
    """Context manager to observe tool execution with logging, metrics, and tracing."""
    logger = get_logger()
    metrics = get_metrics()
    tracer = get_tracer()

    start_time = time.time()
    logger.info(f"Tool execution started: {tool_name}", tool_name=tool_name, session_id=session_id)

    try:
        with tracer.trace_tool_execution(tool_name, session_id):
            yield
        success = True
    except Exception as e:
        success = False
        logger.exception(f"Tool execution failed: {tool_name}", tool_name=tool_name, exc=e)
        metrics.record_error(type(e).__name__, "tool")
        raise
    finally:
        duration = time.time() - start_time
        metrics.record_tool_call(tool_name, success, duration)
        logger.info(
            f"Tool execution completed: {tool_name}",
            tool_name=tool_name,
            success=success,
            duration=f"{duration:.3f}s",
        )


@contextmanager
def observe_model_request(model_name: str, session_id: Optional[str] = None):
    """Context manager to observe model requests."""
    logger = get_logger()
    metrics = get_metrics()
    tracer = get_tracer()

    start_time = time.time()
    logger.info(f"Model request started: {model_name}", model_name=model_name, session_id=session_id)

    try:
        with tracer.trace_model_request(model_name, session_id):
            yield
        status = "success"
    except Exception as e:
        status = "error"
        logger.exception(f"Model request failed: {model_name}", model_name=model_name, exc=e)
        metrics.record_error(type(e).__name__, "model")
        raise
    finally:
        latency = time.time() - start_time
        metrics.record_model_request(model_name, status, latency)
        logger.info(
            f"Model request completed: {model_name}",
            model_name=model_name,
            status=status,
            latency=f"{latency:.3f}s",
        )
