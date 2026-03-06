"""Configuration management for NeuDev."""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path.home() / ".neudev"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.txt"


@dataclass
class NeuDevConfig:
    """NeuDev configuration."""

    # LLM settings
    model: str = "qwen3.5:0.8b"
    temperature: float = 0.7
    max_tokens: int = 4096
    ollama_host: str = "http://localhost:11434"

    # Agent settings
    max_iterations: int = 20
    command_timeout: int = 30

    # Session settings
    auto_permission: bool = False

    # Display settings
    show_thinking: bool = False

    @classmethod
    def load(cls) -> "NeuDevConfig":
        """Load config from file or create default."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        """Save config to file."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    def update(self, **kwargs) -> None:
        """Update config values."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.save()
