"""Read file tool for NeuDev."""

import os
from pathlib import Path

from neudev.tools.base import BaseTool, ToolError


class ReadFileTool(BaseTool):
    """Read the contents of a file with optional line range."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a file. Can read the entire file or a specific "
            "line range. Returns the file contents with line numbers. Use this to "
            "understand existing code before making changes."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to read.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional start line number (1-indexed). Omit to read from beginning.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Optional end line number (1-indexed, inclusive). Omit to read to end.",
                },
            },
            "required": ["path"],
        }

    def execute(self, path: str, start_line: int = None, end_line: int = None, **kwargs) -> str:
        filepath = Path(path).resolve()

        if not filepath.exists():
            raise ToolError(f"File not found: {filepath}")
        if not filepath.is_file():
            raise ToolError(f"Not a file: {filepath}")

        # Check if binary
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            raise ToolError(f"Cannot read binary file: {filepath}")

        total_lines = len(lines)

        # Apply line range
        s = max(1, start_line or 1)
        e = min(total_lines, end_line or total_lines)

        if s > total_lines:
            raise ToolError(f"Start line {s} exceeds total lines ({total_lines}).")

        selected = lines[s - 1 : e]

        # Format with line numbers
        numbered = []
        for i, line in enumerate(selected, start=s):
            numbered.append(f"{i:4d} | {line.rstrip()}")

        header = f"File: {filepath} ({total_lines} lines)"
        if start_line or end_line:
            header += f" [showing lines {s}-{e}]"

        return header + "\n" + "\n".join(numbered)
