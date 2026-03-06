"""Base tool class and tool registry for NeuDev."""

from abc import ABC, abstractmethod
from typing import Any, Optional


class ToolError(Exception):
    """Base error for tool execution failures."""
    pass


class BaseTool(ABC):
    """Abstract base class for all NeuDev tools."""

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
