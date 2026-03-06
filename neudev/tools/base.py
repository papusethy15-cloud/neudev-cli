"""Base tool class and tool registry for NeuDev."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional


class ToolError(Exception):
    """Base error for tool execution failures."""
    pass


class BaseTool(ABC):
    """Abstract base class for all NeuDev tools."""

    def __init__(self) -> None:
        self.workspace: Optional[Path] = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what the tool does."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON Schema for tool parameters."""
        ...

    @property
    def requires_permission(self) -> bool:
        """Whether this tool requires user permission before execution."""
        return False

    def permission_message(self, args: dict) -> str:
        """Human-readable description of what will happen (for permission prompt)."""
        return f"Execute {self.name}"

    def bind_workspace(self, workspace: str | Path) -> None:
        """Bind the tool to a workspace root for relative path resolution."""
        self.workspace = Path(workspace).expanduser().resolve()

    def resolve_path(self, path: str, must_exist: bool = False) -> Path:
        """Resolve a path relative to the workspace and keep it inside the workspace."""
        raw = Path(path).expanduser()
        base = self.workspace or Path.cwd()
        direct = raw if raw.is_absolute() else base / raw
        alias = self._workspace_alias(raw)
        candidates: list[Path] = []

        if alias is not None:
            candidates.append(alias)
        candidates.append(direct)

        seen: set[str] = set()
        resolved_candidates: list[Path] = []
        for candidate in candidates:
            resolved = candidate.resolve()
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            resolved_candidates.append(resolved)

        if must_exist:
            for candidate in resolved_candidates:
                if candidate.exists() and self._is_in_workspace(candidate):
                    return candidate

        for candidate in resolved_candidates:
            if self._is_in_workspace(candidate):
                return candidate

        raise ToolError(
            f"Path must stay inside the workspace: {path}\n"
            f"Workspace: {self.workspace or Path.cwd()}"
        )

    def resolve_directory(self, path: Optional[str] = None, must_exist: bool = False) -> Path:
        """Resolve a directory path relative to the workspace."""
        target = path or "."
        return self.resolve_path(target, must_exist=must_exist)

    def _workspace_alias(self, raw: Path) -> Optional[Path]:
        """Map absolute or prefixed paths back into the active workspace."""
        if self.workspace is None or self.workspace.name not in raw.parts:
            return None

        parts = list(raw.parts)
        idx = parts.index(self.workspace.name)
        suffix = parts[idx + 1 :]
        return self.workspace.joinpath(*suffix) if suffix else self.workspace

    def _is_in_workspace(self, path: Path) -> bool:
        """Return True when the path stays within the workspace root."""
        if self.workspace is None:
            return True
        try:
            path.relative_to(self.workspace)
            return True
        except ValueError:
            return False

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Execute the tool and return result as string."""
        ...

    def to_ollama_tool(self) -> dict:
        """Convert to Ollama tool definition format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry that manages all available tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def bind_workspace(self, workspace: str | Path) -> None:
        """Bind all registered tools to the same workspace root."""
        for tool in self._tools.values():
            tool.bind_workspace(workspace)

    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all(self) -> list[BaseTool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_tool_definitions(self) -> list[dict]:
        """Get all tool definitions in Ollama format."""
        return [tool.to_ollama_tool() for tool in self._tools.values()]

    def execute(self, name: str, **kwargs) -> str:
        """Execute a tool by name."""
        tool = self.get(name)
        if tool is None:
            raise ToolError(f"Unknown tool: '{name}'. Available: {', '.join(self._tools.keys())}")
        try:
            return tool.execute(**kwargs)
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"Tool '{name}' failed: {type(e).__name__}: {e}")

    def list_tools(self) -> list[dict]:
        """List all tools with metadata."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "requires_permission": t.requires_permission,
            }
            for t in self._tools.values()
        ]
