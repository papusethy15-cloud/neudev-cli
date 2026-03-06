"""Search files by name/pattern tool for NeuDev."""

import fnmatch
import os
from pathlib import Path
from datetime import datetime

from neudev.tools.base import BaseTool, ToolError


# Default directories/patterns to exclude from search
DEFAULT_EXCLUDES = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".env", ".idea", ".vscode", "dist", "build", ".tox",
    "*.pyc", "*.pyo", "*.egg-info",
}


class SearchFilesTool(BaseTool):
    """Search for files by name or glob pattern."""

    @property
    def name(self) -> str:
        return "search_files"

    @property
    def description(self) -> str:
        return (
            "Search for files and directories by name or glob pattern within a "
            "directory. Returns matching file paths with sizes and modification "
            "times. Useful for finding specific files in a project."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory to search within. Defaults to the workspace root.",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match (e.g., '*.py', 'test_*', '*.js').",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum directory depth to search. Default 10.",
                },
                "file_type": {
                    "type": "string",
                    "enum": ["file", "directory", "any"],
                    "description": "Filter by type. Default 'file'.",
                },
            },
            "required": ["pattern"],
        }

    def execute(
        self,
        pattern: str,
        directory: str = ".",
        max_depth: int = 10,
        file_type: str = "file",
        **kwargs,
    ) -> str:
        dirpath = self.resolve_directory(directory, must_exist=True)

        if not dirpath.exists():
            raise ToolError(f"Directory not found: {dirpath}")
        if not dirpath.is_dir():
            raise ToolError(f"Not a directory: {dirpath}")

        matches = []
        max_results = 50

        for root, dirs, files in os.walk(dirpath):
            # Calculate depth
            depth = len(Path(root).relative_to(dirpath).parts)
            if depth > max_depth:
                dirs.clear()
                continue

            # Exclude common directories
            dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES]

            items = []
            if file_type in ("file", "any"):
                items.extend((f, "file") for f in files)
            if file_type in ("directory", "any"):
                items.extend((d, "dir") for d in dirs)

            for name, kind in items:
                if fnmatch.fnmatch(name, pattern):
                    full_path = Path(root) / name
                    try:
                        stat = full_path.stat()
                        size = stat.st_size if kind == "file" else 0
                        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                    except OSError:
                        size = 0
                        modified = "unknown"

                    rel_path = full_path.relative_to(dirpath)
                    matches.append(f"  {kind:4s}  {size:>8d}B  {modified}  {rel_path}")

                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break

        if not matches:
            fuzzy_matches = self._find_fuzzy_matches(dirpath, pattern, max_depth, file_type, max_results)
            if fuzzy_matches:
                return (
                    f"No exact glob matches for '{pattern}' in {dirpath}.\n"
                    f"Automatic fallback: fuzzy name matches:\n" + "\n".join(fuzzy_matches)
                )
            return f"No matches found for '{pattern}' in {dirpath}"

        header = f"Found {len(matches)} match(es) for '{pattern}' in {dirpath}:"
        if len(matches) >= max_results:
            header += f" (showing first {max_results})"

        return header + "\n" + "\n".join(matches)

    def _find_fuzzy_matches(
        self,
        dirpath: Path,
        pattern: str,
        max_depth: int,
        file_type: str,
        max_results: int,
    ) -> list[str]:
        query = pattern.replace("*", "").replace("?", "").strip().lower()
        if not query:
            return []

        matches = []
        for root, dirs, files in os.walk(dirpath):
            depth = len(Path(root).relative_to(dirpath).parts)
            if depth > max_depth:
                dirs.clear()
                continue

            dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES]

            items = []
            if file_type in ("file", "any"):
                items.extend((f, "file") for f in files)
            if file_type in ("directory", "any"):
                items.extend((d, "dir") for d in dirs)

            for name, kind in items:
                lowered = name.lower()
                stem = Path(name).stem.lower()
                if query not in lowered and query not in stem:
                    continue
                rel_path = (Path(root) / name).relative_to(dirpath)
                matches.append(f"  {kind:4s}  fuzzy match  {rel_path}")
                if len(matches) >= max_results:
                    return matches

        return matches
