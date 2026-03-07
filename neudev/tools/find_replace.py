"""Find and replace tool for NeuDev — search and replace across multiple files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from neudev.tools.base import BaseTool, ToolError


class FindReplaceTool(BaseTool):
    """Find and replace text across one or more files."""

    @property
    def name(self) -> str:
        return "find_replace"

    @property
    def description(self) -> str:
        return (
            "Find and replace text across one or more files. Better than edit_file for "
            "simple text replacements that span multiple locations or files. "
            "Supports regex patterns and provides a preview of all changes before applying."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "find": {
                    "type": "string",
                    "description": (
                        "Text or regex pattern to find. For regex, set use_regex=True. "
                        "Example: 'old_function_name' or r'\\bold_function\\b' for regex."
                    ),
                },
                "replace": {
                    "type": "string",
                    "description": (
                        "Replacement text. For regex, use \\1, \\2 for capture groups. "
                        "Example: 'new_function_name' or r'new_\\1' for regex."
                    ),
                },
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of file paths to search and replace in. "
                        "Use ['*.py'] for all Python files, ['.'] for all files in workspace."
                    ),
                },
                "use_regex": {
                    "type": "boolean",
                    "description": "Treat 'find' as a regex pattern (default: False).",
                    "default": False,
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Case-sensitive search (default: False).",
                    "default": False,
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "Preview changes without applying them (default: False). "
                        "Use this to see what would be changed before committing."
                    ),
                    "default": False,
                },
            },
            "required": ["find", "replace", "paths"],
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        find_str = args.get("find", "pattern")
        replace_str = args.get("replace", "replacement")
        paths = args.get("paths", [])
        return (
            f"Find and replace across {len(paths)} path(s):\n"
            f"  Find: {find_str}\n"
            f"  Replace: {replace_str}\n"
            f"  Paths: {', '.join(paths[:5])}{'...' if len(paths) > 5 else ''}"
        )

    def execute(
        self,
        find: str,
        replace: str,
        paths: list[str],
        use_regex: bool = False,
        case_sensitive: bool = False,
        dry_run: bool = False,
        **kwargs,
    ) -> str:
        if not find:
            raise ToolError("'find' parameter is required.")
        if not paths:
            raise ToolError("'paths' parameter is required.")

        # Compile regex if needed
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(find, flags) if use_regex else None
        except re.error as e:
            raise ToolError(f"Invalid regex pattern: {e}")

        # Find all matching files
        files_to_process = self._expand_paths(paths)
        if not files_to_process:
            raise ToolError(f"No files found matching paths: {paths}")

        # Process each file
        total_matches = 0
        total_files_changed = 0
        changes_preview = []

        for file_path in files_to_process:
            try:
                matches, new_content = self._process_file(
                    file_path, find, replace, pattern, use_regex, case_sensitive
                )

                if matches > 0:
                    total_matches += matches
                    total_files_changed += 1

                    # Add to preview
                    if len(changes_preview) < 10:  # Limit preview to first 10 files
                        changes_preview.append({
                            "file": str(file_path),
                            "matches": matches,
                            "preview": new_content[:200] if not dry_run else "",
                        })

                    # Write changes if not dry run
                    if not dry_run and matches > 0:
                        file_path.write_text(new_content, encoding="utf-8")

            except (OSError, UnicodeDecodeError) as e:
                # Skip files that can't be read/written
                continue

        # Build result message
        if total_matches == 0:
            return f"No matches found for '{find}' in {len(files_to_process)} file(s)."

        result_lines = [
            f"✅ Find & replace completed:",
            f"  Find: {find}",
            f"  Replace: {replace}",
            f"  Files searched: {len(files_to_process)}",
            f"  Files changed: {total_files_changed}",
            f"  Total replacements: {total_matches}",
        ]

        if dry_run:
            result_lines.insert(1, f"  [DRY RUN - No changes applied]")

        # Add preview
        if changes_preview:
            result_lines.append("")
            result_lines.append("Changes:")
            for change in changes_preview:
                result_lines.append(f"  {change['file']}: {change['matches']} replacement(s)")

        return "\n".join(result_lines)

    def _expand_paths(self, paths: list[str]) -> list[Path]:
        """Expand path patterns to actual file paths."""
        expanded = []

        for path_pattern in paths:
            # Handle glob patterns
            if "*" in path_pattern or "?" in path_pattern:
                try:
                    resolved = self.resolve_directory(".")
                    matches = list(resolved.glob(path_pattern))
                    expanded.extend(
                        m for m in matches if m.is_file() and self._is_text_file(m)
                    )
                except (OSError, ToolError):
                    continue
            else:
                # Single file or directory
                try:
                    resolved = self.resolve_path(path_pattern, must_exist=True)
                    if resolved.is_file():
                        if self._is_text_file(resolved):
                            expanded.append(resolved)
                    elif resolved.is_dir():
                        # Recursively find all text files in directory
                        expanded.extend(
                            f for f in resolved.rglob("*")
                            if f.is_file() and self._is_text_file(f)
                        )
                except (OSError, ToolError):
                    continue

        return expanded

    def _is_text_file(self, path: Path) -> bool:
        """Check if a file is likely a text file."""
        text_extensions = {
            ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss",
            ".json", ".yaml", ".yml", ".xml", ".md", ".rst", ".txt",
            ".sh", ".bash", ".zsh", ".fish",
            ".java", ".cpp", ".c", ".h", ".hpp", ".cs", ".go", ".rs",
            ".rb", ".php", ".swift", ".kt", ".scala", ".r", ".sql",
        }
        return path.suffix.lower() in text_extensions

    def _process_file(
        self,
        file_path: Path,
        find: str,
        replace: str,
        pattern: Optional[re.Pattern],
        use_regex: bool,
        case_sensitive: bool,
    ) -> tuple[int, str]:
        """
        Process a single file and return (match_count, new_content).
        """
        content = file_path.read_text(encoding="utf-8")

        if use_regex:
            # Regex replacement
            new_content, count = pattern.subn(replace, content)
        else:
            # Simple string replacement
            if case_sensitive:
                count = content.count(find)
                new_content = content.replace(find, replace)
            else:
                # Case-insensitive replacement
                pattern = re.compile(re.escape(find), re.IGNORECASE)
                new_content, count = pattern.subn(replace, content)

        return count, new_content
