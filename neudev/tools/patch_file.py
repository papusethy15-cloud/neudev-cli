"""Patch file tool for NeuDev — apply unified diffs to files."""

from __future__ import annotations

import re
from pathlib import Path

from neudev.tools.base import BaseTool, ToolError


class PatchFileTool(BaseTool):
    """Apply a unified diff patch to a file."""

    @property
    def name(self) -> str:
        return "patch_file"

    @property
    def description(self) -> str:
        return (
            "Apply a unified diff (patch) to a file. Better than edit_file for "
            "multi-region edits. Provide the patch in standard unified diff format "
            "(lines starting with +, -, or space). The patch is validated before applying."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to patch (relative to workspace).",
                },
                "patch": {
                    "type": "string",
                    "description": (
                        "The unified diff patch to apply. Each hunk should start with "
                        "@@ -start,count +start,count @@ and contain lines prefixed "
                        "with ' ' (context), '-' (remove), or '+' (add)."
                    ),
                },
            },
            "required": ["path", "patch"],
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        path = args.get("path", "unknown")
        return f"Apply patch to: {path}"

    def execute(self, path: str, patch: str, **kwargs) -> str:
        if not path:
            raise ToolError("File path is required.")
        if not patch or not patch.strip():
            raise ToolError("Patch content is required.")

        resolved = self.resolve_path(path, must_exist=True)
        if not resolved.exists():
            raise ToolError(f"File not found: {path}")
        if not resolved.is_file():
            raise ToolError(f"Not a file: {path}")

        try:
            original = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise ToolError(f"Cannot read file: {e}")

        hunks = self._parse_hunks(patch)
        if not hunks:
            raise ToolError(
                "No valid hunks found in the patch. Each hunk must start with "
                "'@@ -start,count +start,count @@'."
            )

        original_lines = original.splitlines(keepends=True)
        result_lines, applied_count, total_hunks = self._apply_hunks(original_lines, hunks)

        if applied_count == 0:
            raise ToolError(
                "Patch could not be applied — no hunks matched the file content. "
                "The context lines in the patch may not match the current file."
            )

        result_text = "".join(result_lines)
        try:
            resolved.write_text(result_text, encoding="utf-8")
        except OSError as e:
            raise ToolError(f"Cannot write file: {e}")

        added = sum(1 for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in patch.splitlines() if line.startswith("-") and not line.startswith("---"))
        return (
            f"Patch applied to {path}\n"
            f"Hunks: {applied_count}/{total_hunks} applied\n"
            f"Changes: +{added}/-{removed} lines"
        )

    @staticmethod
    def _parse_hunks(patch: str) -> list[dict]:
        """Parse unified diff into structured hunks."""
        hunk_header_re = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
        hunks: list[dict] = []
        current_hunk: dict | None = None

        for raw_line in patch.splitlines():
            header_match = hunk_header_re.match(raw_line)
            if header_match:
                if current_hunk:
                    hunks.append(current_hunk)
                current_hunk = {
                    "old_start": int(header_match.group(1)),
                    "old_count": int(header_match.group(2) or 1),
                    "new_start": int(header_match.group(3)),
                    "new_count": int(header_match.group(4) or 1),
                    "lines": [],
                }
                continue

            if current_hunk is not None:
                if raw_line.startswith(("+", "-", " ")):
                    current_hunk["lines"].append(raw_line)
                elif raw_line.startswith(("---", "+++")):
                    continue  # Skip file headers
                elif raw_line.strip() == "":
                    current_hunk["lines"].append(" ")  # Treat blank as context

        if current_hunk:
            hunks.append(current_hunk)
        return hunks

    @staticmethod
    def _apply_hunks(
        original_lines: list[str],
        hunks: list[dict],
    ) -> tuple[list[str], int, int]:
        """Apply parsed hunks to the original file lines."""
        result = list(original_lines)
        offset = 0
        applied = 0

        for hunk in hunks:
            old_start = hunk["old_start"] - 1 + offset
            hunk_lines = hunk["lines"]

            # Verify context lines match
            context_ok = True
            check_pos = old_start
            for line in hunk_lines:
                if line.startswith(" ") or line.startswith("-"):
                    expected = line[1:]
                    if check_pos >= len(result):
                        context_ok = False
                        break
                    actual = result[check_pos].rstrip("\n").rstrip("\r")
                    if actual != expected.rstrip("\n").rstrip("\r"):
                        context_ok = False
                        break
                    check_pos += 1
                elif line.startswith("+"):
                    pass  # Addition lines don't need context check

            if not context_ok:
                continue

            # Apply the hunk
            new_lines: list[str] = []
            remove_count = 0
            pos = old_start

            for line in hunk_lines:
                if line.startswith(" "):
                    new_lines.append(result[pos] if pos < len(result) else line[1:] + "\n")
                    pos += 1
                    remove_count += 1
                elif line.startswith("-"):
                    pos += 1
                    remove_count += 1
                elif line.startswith("+"):
                    content = line[1:]
                    if not content.endswith("\n"):
                        content += "\n"
                    new_lines.append(content)

            result[old_start: old_start + remove_count] = new_lines
            offset += len(new_lines) - remove_count
            applied += 1

        return result, applied, len(hunks)
