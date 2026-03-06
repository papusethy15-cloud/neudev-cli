"""Smart edit file tool for NeuDev."""

from __future__ import annotations

from neudev.tools.base import BaseTool, ToolError


class SmartEditFileTool(BaseTool):
    """Edit a file with normalized matching fallbacks."""

    @property
    def name(self) -> str:
        return "smart_edit_file"

    @property
    def description(self) -> str:
        return (
            "Edit an existing file using resilient matching. Tries exact replacement first, "
            "then falls back to normalized newline and whitespace-aware block matching. "
            "Useful when exact find/replace is brittle."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit.",
                },
                "target_content": {
                    "type": "string",
                    "description": "The text block to replace.",
                },
                "replacement_content": {
                    "type": "string",
                    "description": "The new text to insert.",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace every matching block. Default false.",
                },
            },
            "required": ["path", "target_content", "replacement_content"],
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        path = args.get("path", "unknown")
        target = args.get("target_content", "")
        preview = target[:80] + "..." if len(target) > 80 else target
        return f"Smart edit file: {path}\n  Replace: {preview}"

    def execute(
        self,
        path: str,
        target_content: str,
        replacement_content: str,
        replace_all: bool = False,
        **kwargs,
    ) -> str:
        filepath = self.resolve_path(path, must_exist=True)

        if not filepath.exists():
            raise ToolError(f"File not found: {filepath}")
        if not filepath.is_file():
            raise ToolError(f"Not a file: {filepath}")

        try:
            original = filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ToolError(f"Cannot edit binary file: {filepath}")

        new_content, replaced, strategy = self._apply_edit(
            original,
            target_content,
            replacement_content,
            replace_all=replace_all,
        )
        if replaced == 0:
            raise ToolError(
                f"Smart edit could not find a matching block in {filepath}.\n"
                f"Looking for:\n{target_content[:200]}\n\n"
                "Try reading the file again and use a smaller or more exact snippet."
            )

        filepath.write_text(new_content, encoding="utf-8")

        diff_lines = []
        for line in target_content.splitlines():
            diff_lines.append(f"- {line}")
        for line in replacement_content.splitlines():
            diff_lines.append(f"+ {line}")

        diff = "\n".join(diff_lines)
        return (
            f"Edited {filepath} ({replaced} replacement{'s' if replaced > 1 else ''}, "
            f"strategy: {strategy}):\n"
            f"```diff\n{diff}\n```"
        )

    def _apply_edit(
        self,
        original: str,
        target: str,
        replacement: str,
        replace_all: bool,
    ) -> tuple[str, int, str]:
        if target in original:
            count = original.count(target)
            if replace_all:
                return original.replace(target, replacement), count, "exact"
            return original.replace(target, replacement, 1), 1, "exact"

        newline = "\r\n" if "\r\n" in original else "\n"
        original_norm = original.replace("\r\n", "\n")
        target_norm = target.replace("\r\n", "\n")
        replacement_norm = replacement.replace("\r\n", "\n")
        if target_norm in original_norm:
            count = original_norm.count(target_norm)
            if replace_all:
                new_norm = original_norm.replace(target_norm, replacement_norm)
                replaced = count
            else:
                new_norm = original_norm.replace(target_norm, replacement_norm, 1)
                replaced = 1
            return new_norm.replace("\n", newline), replaced, "normalized-newlines"

        replaced_text, replaced = self._replace_line_blocks(
            original,
            target_norm.split("\n"),
            replacement_norm.split("\n"),
            newline=newline,
            replace_all=replace_all,
        )
        if replaced:
            return replaced_text, replaced, "whitespace-aware-block"

        return original, 0, "none"

    def _replace_line_blocks(
        self,
        source: str,
        target_lines: list[str],
        replacement_lines: list[str],
        newline: str,
        replace_all: bool,
    ) -> tuple[str, int]:
        source_lines = source.splitlines()
        if not target_lines:
            return source, 0

        matches: list[int] = []
        block_len = len(target_lines)
        normalized_target = [self._normalize_line(line) for line in target_lines]
        for idx in range(0, len(source_lines) - block_len + 1):
            window = source_lines[idx : idx + block_len]
            normalized_window = [self._normalize_line(line) for line in window]
            if normalized_window == normalized_target:
                matches.append(idx)
                if not replace_all:
                    break

        if not matches:
            return source, 0

        result_lines = list(source_lines)
        offset = 0
        for match_idx in matches:
            start = match_idx + offset
            end = start + block_len
            result_lines[start:end] = list(replacement_lines)
            offset += len(replacement_lines) - block_len

        trailing_newline = source.endswith(("\n", "\r\n"))
        joined = newline.join(result_lines)
        if trailing_newline and not joined.endswith(newline):
            joined += newline
        return joined, len(matches)

    @staticmethod
    def _normalize_line(line: str) -> str:
        return " ".join(line.strip().split())
