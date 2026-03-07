"""Configuration management for NeuDev."""

import json
from dataclasses import dataclass, asdict
from pathlib import Path


CONFIG_DIR = Path.home() / ".neudev"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.txt"
VALID_AGENT_MODES = {"single", "team", "parallel"}
VALID_RUNTIME_MODES = {"local", "remote", "hybrid"}
VALID_STREAM_TRANSPORTS = {"auto", "sse", "websocket"}
VALID_COMMAND_POLICIES = {"auto", "permissive", "restricted", "disabled"}


@dataclass
class NeuDevConfig:
    """NeuDev configuration."""

    # LLM settings
    model: str = "auto"
    temperature: float = 0.7
    max_tokens: int = 4096
    ollama_host: str = "http://localhost:11434"

    # Agent settings
    max_iterations: int = 20
    command_timeout: int = 30

    # Session settings
    auto_permission: bool = False
    multi_agent: bool = True
    agent_mode: str = ""
    runtime_mode: str = "local"
    api_base_url: str = ""
    api_key: str = ""
    remote_workspace: str = ""
    websocket_base_url: str = ""
    stream_transport: str = "auto"
    command_policy: str = "auto"
    hybrid_max_payload_bytes: int = 262144
    hybrid_redact_secrets: bool = True

    # Display settings
    show_thinking: bool = False
    response_language: str = "English"

    def __post_init__(self) -> None:
        """Normalize derived config fields for backward compatibility."""
        mode = (self.agent_mode or "").strip().lower()
        if mode not in VALID_AGENT_MODES:
            mode = "parallel" if self.multi_agent else "single"
        self.agent_mode = mode
        self.multi_agent = mode != "single"
        runtime_mode = (self.runtime_mode or "local").strip().lower()
        if runtime_mode not in VALID_RUNTIME_MODES:
            runtime_mode = "local"
        self.runtime_mode = runtime_mode
        stream_transport = (self.stream_transport or "auto").strip().lower()
        if stream_transport not in VALID_STREAM_TRANSPORTS:
            stream_transport = "auto"
        self.stream_transport = stream_transport
        command_policy = (self.command_policy or "auto").strip().lower()
        if command_policy not in VALID_COMMAND_POLICIES:
            command_policy = "auto"
        self.command_policy = command_policy
        try:
            hybrid_max_payload_bytes = int(self.hybrid_max_payload_bytes)
        except (TypeError, ValueError):
            hybrid_max_payload_bytes = 262144
        if hybrid_max_payload_bytes <= 0:
            hybrid_max_payload_bytes = 262144
        self.hybrid_max_payload_bytes = hybrid_max_payload_bytes
        self.hybrid_redact_secrets = bool(self.hybrid_redact_secrets)

    @classmethod
    def load(cls) -> "NeuDevConfig":
        """Load config from file or create default."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "agent_mode" not in data and "multi_agent" in data:
                    data["agent_mode"] = "parallel" if data.get("multi_agent") else "single"
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        """Save config to file."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    def clone(self) -> "NeuDevConfig":
        """Return an in-memory copy without touching disk."""
        return NeuDevConfig(**asdict(self))

    def apply_runtime_updates(self, *, persist: bool, **kwargs) -> None:
        """Apply config updates, optionally persisting them to disk."""
        if "agent_mode" in kwargs:
            mode = str(kwargs["agent_mode"]).strip().lower()
            if mode not in VALID_AGENT_MODES:
                raise ValueError(
                    f"Invalid agent_mode '{kwargs['agent_mode']}'. "
                    f"Expected one of: {', '.join(sorted(VALID_AGENT_MODES))}"
                )
            kwargs["agent_mode"] = mode
            kwargs["multi_agent"] = mode != "single"
        elif "multi_agent" in kwargs:
            kwargs["agent_mode"] = "parallel" if kwargs["multi_agent"] else "single"

        if "runtime_mode" in kwargs:
            mode = str(kwargs["runtime_mode"]).strip().lower()
            if mode not in VALID_RUNTIME_MODES:
                raise ValueError(
                    f"Invalid runtime_mode '{kwargs['runtime_mode']}'. "
                    f"Expected one of: {', '.join(sorted(VALID_RUNTIME_MODES))}"
                )
            kwargs["runtime_mode"] = mode

        if "stream_transport" in kwargs:
            transport = str(kwargs["stream_transport"]).strip().lower()
            if transport not in VALID_STREAM_TRANSPORTS:
                raise ValueError(
                    f"Invalid stream_transport '{kwargs['stream_transport']}'. "
                    f"Expected one of: {', '.join(sorted(VALID_STREAM_TRANSPORTS))}"
                )
            kwargs["stream_transport"] = transport

        if "command_policy" in kwargs:
            command_policy = str(kwargs["command_policy"]).strip().lower()
            if command_policy not in VALID_COMMAND_POLICIES:
                raise ValueError(
                    f"Invalid command_policy '{kwargs['command_policy']}'. "
                    f"Expected one of: {', '.join(sorted(VALID_COMMAND_POLICIES))}"
                )
            kwargs["command_policy"] = command_policy

        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.__post_init__()
        if persist:
            self.save()

    def update(self, **kwargs) -> None:
        """Update config values and persist them."""
        self.apply_runtime_updates(persist=True, **kwargs)
