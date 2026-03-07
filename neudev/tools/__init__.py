"""Tool registry for NeuDev."""

from neudev.tools.base import BaseTool, ToolRegistry
from neudev.tools.read_file import ReadFileTool
from neudev.tools.read_files_batch import ReadFilesBatchTool
from neudev.tools.write_file import WriteFileTool
from neudev.tools.edit_file import EditFileTool
from neudev.tools.smart_edit_file import SmartEditFileTool
from neudev.tools.find_replace import FindReplaceTool
from neudev.tools.python_ast_edit import PythonAstEditTool
from neudev.tools.js_ts_symbol_edit import JsTsSymbolEditTool
from neudev.tools.delete_file import DeleteFileTool
from neudev.tools.search_files import SearchFilesTool
from neudev.tools.grep_search import GrepSearchTool
from neudev.tools.symbol_search import SymbolSearchTool
from neudev.tools.list_dir import ListDirectoryTool
from neudev.tools.run_command import RunCommandTool
from neudev.tools.diagnostics import DiagnosticsTool
from neudev.tools.changed_files_diagnostics import ChangedFilesDiagnosticsTool
from neudev.tools.git_diff_review import GitDiffReviewTool
from neudev.tools.file_outline import FileOutlineTool
from neudev.tools.web_search import WebSearchTool
from neudev.tools.url_fetch import UrlFetchTool
from neudev.tools.patch_file import PatchFileTool
from neudev.tools.dependency_install import DependencyInstallTool
from neudev.tools.project_init import ProjectInitTool


def create_tool_registry() -> ToolRegistry:
    """Create and populate the tool registry with all available tools."""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(ReadFilesBatchTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    registry.register(SmartEditFileTool())
    registry.register(FindReplaceTool())  # NEW: Multi-location find & replace
    registry.register(PythonAstEditTool())
    registry.register(JsTsSymbolEditTool())
    registry.register(DeleteFileTool())
    registry.register(SearchFilesTool())
    registry.register(GrepSearchTool())
    registry.register(SymbolSearchTool())
    registry.register(ListDirectoryTool())
    registry.register(RunCommandTool())
    registry.register(DiagnosticsTool())
    registry.register(ChangedFilesDiagnosticsTool())
    registry.register(GitDiffReviewTool())
    registry.register(FileOutlineTool())
    registry.register(WebSearchTool())
    registry.register(UrlFetchTool())
    registry.register(PatchFileTool())
    registry.register(DependencyInstallTool())
    registry.register(ProjectInitTool())
    return registry


__all__ = [
    "BaseTool",
    "ToolRegistry",
    "create_tool_registry",
    "ReadFileTool",
    "ReadFilesBatchTool",
    "WriteFileTool",
    "EditFileTool",
    "SmartEditFileTool",
    "PythonAstEditTool",
    "JsTsSymbolEditTool",
    "DeleteFileTool",
    "SearchFilesTool",
    "GrepSearchTool",
    "SymbolSearchTool",
    "ListDirectoryTool",
    "RunCommandTool",
    "DiagnosticsTool",
    "ChangedFilesDiagnosticsTool",
    "GitDiffReviewTool",
    "FileOutlineTool",
    "WebSearchTool",
    "UrlFetchTool",
    "PatchFileTool",
    "DependencyInstallTool",
    "ProjectInitTool",
]
