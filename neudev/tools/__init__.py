"""Tool registry for NeuDev."""

from neudev.tools.base import BaseTool, ToolRegistry
from neudev.tools.read_file import ReadFileTool
from neudev.tools.write_file import WriteFileTool
from neudev.tools.edit_file import EditFileTool
from neudev.tools.delete_file import DeleteFileTool
from neudev.tools.search_files import SearchFilesTool
from neudev.tools.grep_search import GrepSearchTool
from neudev.tools.list_dir import ListDirectoryTool
from neudev.tools.run_command import RunCommandTool
from neudev.tools.file_outline import FileOutlineTool


def create_tool_registry() -> ToolRegistry:
    """Create and populate the tool registry with all available tools."""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    registry.register(DeleteFileTool())
    registry.register(SearchFilesTool())
    registry.register(GrepSearchTool())
    registry.register(ListDirectoryTool())
    registry.register(RunCommandTool())
    registry.register(FileOutlineTool())
    return registry


__all__ = [
    "BaseTool",
    "ToolRegistry",
    "create_tool_registry",
    "ReadFileTool",
    "WriteFileTool",
    "EditFileTool",
    "DeleteFileTool",
    "SearchFilesTool",
    "GrepSearchTool",
    "ListDirectoryTool",
    "RunCommandTool",
    "FileOutlineTool",
]
