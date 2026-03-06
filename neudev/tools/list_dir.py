"""List directory tool for NeuDev."""

from pathlib import Path

from neudev.tools.base import BaseTool, ToolError


DEFAULT_EXCLUDES = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".env", ".idea", ".vscode",
}


class ListDirectoryTool(BaseTool):
    """List contents of a directory."""

    @property
    def name(self) -> str:
        return "list_directory"

    @property
    def description(self) -> str:
        return (
            "List the contents of a directory showing files and subdirectories "
            "with their sizes. Provides a tree-like view of the project structure. "
            "Use this to understand the project layout."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory to list. Defaults to the workspace root.",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum depth to list. Default 3.",
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "Show hidden files (starting with '.'). Default false.",
                },
            },
        }

    def execute(self, path: str = ".", max_depth: int = 3, show_hidden: bool = False, **kwargs) -> str:
        dirpath = self.resolve_directory(path, must_exist=True)

        if not dirpath.exists():
            raise ToolError(f"Directory not found: {dirpath}")
        if not dirpath.is_dir():
            raise ToolError(f"Not a directory: {dirpath}")

        lines = [f"📂 {dirpath}"]
        self._build_tree(dirpath, dirpath, lines, "", max_depth, 0, show_hidden)

        if len(lines) == 1:
            lines.append("  (empty directory)")

        return "\n".join(lines)

    def _build_tree(
        self,
        root: Path,
        current: Path,
        lines: list,
        prefix: str,
        max_depth: int,
        depth: int,
        show_hidden: bool,
    ) -> None:
        if depth >= max_depth:
            return

        try:
            entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            lines.append(f"{prefix}  ⚠️ Permission denied")
            return

        # Filter
        filtered = []
        for entry in entries:
            if entry.name in DEFAULT_EXCLUDES:
                continue
            if not show_hidden and entry.name.startswith("."):
                continue
            filtered.append(entry)

        for i, entry in enumerate(filtered):
            is_last = i == len(filtered) - 1
            connector = "└── " if is_last else "├── "
            child_prefix = prefix + ("    " if is_last else "│   ")

            if entry.is_dir():
                child_count = sum(1 for _ in entry.iterdir()) if entry.is_dir() else 0
                lines.append(f"{prefix}{connector}📂 {entry.name}/ ({child_count} items)")
                self._build_tree(root, entry, lines, child_prefix, max_depth, depth + 1, show_hidden)
            else:
                size = entry.stat().st_size
                size_str = self._format_size(size)
                lines.append(f"{prefix}{connector}📄 {entry.name} ({size_str})")

            if len(lines) > 200:
                lines.append(f"{prefix}  ... (truncated)")
                return

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"
