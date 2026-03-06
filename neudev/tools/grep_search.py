"""Grep search tool for NeuDev - search file contents."""

import fnmatch
import os
import re
from pathlib import Path

from neudev.tools.base import BaseTool, ToolError


DEFAULT_EXCLUDES = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".env", ".idea", ".vscode", "dist", "build",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".mp3", ".mp4", ".wav", ".avi", ".mkv",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".exe", ".dll", ".so", ".dylib",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".pyc", ".pyo", ".class", ".o",
}


class GrepSearchTool(BaseTool):
    """Search file contents for a pattern."""

    @property
    def name(self) -> str:
        return "grep_search"

    @property
    def description(self) -> str:
        return (
            "Search file contents for a text pattern or regex. Returns matching "
            "lines with file paths and line numbers. Like ripgrep/grep. Use this "
            "to find where functions, variables, or strings are used in the codebase."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The text pattern or regex to search for.",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to search within. Defaults to the workspace root.",
                },
                "is_regex": {
                    "type": "boolean",
                    "description": "Treat query as regex pattern. Default false.",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Case-insensitive search. Default false.",
                },
                "includes": {
                    "type": "string",
                    "description": "Glob pattern for files to include (e.g., '*.py').",
                },
            },
            "required": ["query"],
        }

    def execute(
        self,
        query: str,
        directory: str = ".",
        is_regex: bool = False,
        case_insensitive: bool = False,
        includes: str = None,
        **kwargs,
    ) -> str:
        dirpath = self.resolve_directory(directory, must_exist=True)

        if not dirpath.exists():
            raise ToolError(f"Directory not found: {dirpath}")

        matches, files_searched = self._search_contents(
            dirpath,
            query,
            is_regex=is_regex,
            case_insensitive=case_insensitive,
            includes=includes,
        )
        if matches:
            header = f"Found {len(matches)} match(es) for '{query}' ({files_searched} files searched):"
            if len(matches) >= 50:
                header += " (showing first 50)"
            return header + "\n" + "\n".join(matches)

        if not case_insensitive:
            retry_matches, retry_files = self._search_contents(
                dirpath,
                query,
                is_regex=is_regex,
                case_insensitive=True,
                includes=includes,
            )
            if retry_matches:
                return (
                    f"No exact case-sensitive matches for '{query}' in {dirpath}.\n"
                    "Automatic fallback: case-insensitive matches:\n"
                    + "\n".join(retry_matches)
                )
            files_searched = retry_files

        filename_matches = self._search_filenames(dirpath, query, includes=includes)
        if filename_matches:
            return (
                f"No content matches found for '{query}' in {dirpath} ({files_searched} files searched).\n"
                "Automatic fallback: related filename matches:\n"
                + "\n".join(filename_matches)
            )

        return f"No matches found for '{query}' in {dirpath} ({files_searched} files searched)"

    def _search_contents(
        self,
        dirpath: Path,
        query: str,
        is_regex: bool,
        case_insensitive: bool,
        includes: str | None,
    ) -> tuple[list[str], int]:
        flags = re.IGNORECASE if case_insensitive else 0
        try:
            pattern = re.compile(query if is_regex else re.escape(query), flags)
        except re.error as e:
            raise ToolError(f"Invalid regex pattern: {e}")

        matches = []
        max_results = 50
        files_searched = 0

        for root, dirs, files in os.walk(dirpath):
            dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES]

            for filename in files:
                ext = Path(filename).suffix.lower()
                if ext in BINARY_EXTENSIONS:
                    continue
                if includes and not fnmatch.fnmatch(filename, includes):
                    continue

                filepath = self.resolve_path(str(Path(root) / filename), must_exist=True)
                files_searched += 1
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, 1):
                            if pattern.search(line):
                                rel = filepath.relative_to(dirpath)
                                content = line.rstrip()
                                if len(content) > 200:
                                    content = content[:200] + "..."
                                matches.append(f"  {rel}:{line_num}: {content}")
                                if len(matches) >= max_results:
                                    break
                except (OSError, UnicodeDecodeError):
                    continue

                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break

        return matches, files_searched

    def _search_filenames(self, dirpath: Path, query: str, includes: str | None) -> list[str]:
        lowered_query = query.lower().strip()
        if not lowered_query:
            return []

        matches = []
        for root, dirs, files in os.walk(dirpath):
            dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES]
            for filename in files:
                if includes and not fnmatch.fnmatch(filename, includes):
                    continue
                if lowered_query not in filename.lower():
                    continue
                rel = (Path(root) / filename).relative_to(dirpath)
                matches.append(f"  {rel}")
                if len(matches) >= 20:
                    return matches
        return matches
