"""Read multiple files in one call for NeuDev."""

from __future__ import annotations

from pathlib import Path

from neudev.tools.base import BaseTool, ToolError


class ReadFilesBatchTool(BaseTool):
    """Read multiple files with a shared line window."""

    @property
    def name(self) -> str:
        return "read_files_batch"

    @property
    def description(self) -> str:
        return (
            "Read multiple files in one tool call. Returns each file with line numbers. "
            "Useful when comparing related modules, tests, or configs during coding."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to read.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional start line number (1-indexed).",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Optional end line number (1-indexed, inclusive).",
                },
            },
            "required": ["paths"],
        }

    def execute(
        self,
        paths: list[str],
        start_line: int = None,
        end_line: int = None,
        **kwargs,
    ) -> str:
        if not paths:
            raise ToolError("At least one path is required.")

        results = []
        for raw_path in paths[:10]:
            filepath = self.resolve_path(raw_path, must_exist=True)
            if not filepath.is_file():
                raise ToolError(f"Not a file: {filepath}")
            try:
                lines = filepath.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                raise ToolError(f"Cannot read binary file: {filepath}")

            total_lines = len(lines)
            s = max(1, start_line or 1)
            e = min(total_lines, end_line or total_lines)
            selected = lines[s - 1 : e]
            numbered = "\n".join(f"{i:4d} | {line}" for i, line in enumerate(selected, start=s))
            header = f"File: {filepath} ({total_lines} lines)"
            if start_line or end_line:
                header += f" [showing lines {s}-{e}]"
            results.append(header + "\n" + numbered)

        return "\n\n".join(results)
