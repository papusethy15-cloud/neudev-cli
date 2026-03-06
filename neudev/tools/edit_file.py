"""Edit file tool for NeuDev."""

from neudev.tools.base import BaseTool, ToolError


class EditFileTool(BaseTool):
    """Edit an existing file using find and replace."""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Edit an existing file by replacing specific content. Provide the exact "
            "text to find and the replacement text. The tool validates that the target "
            "content exists before making changes and shows a diff of what changed. "
            "Use read_file first to understand the current content."
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
                    "description": "The exact text to find and replace. Must match exactly.",
                },
                "replacement_content": {
                    "type": "string",
                    "description": "The new text to replace the target with.",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "If true, replace all occurrences. Default false (replace first only).",
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
        return f"Edit file: {path}\n  Replace: {preview}"

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
            with open(filepath, "r", encoding="utf-8") as f:
                original = f.read()
        except UnicodeDecodeError:
            raise ToolError(f"Cannot edit binary file: {filepath}")

        if target_content not in original:
            raise ToolError(
                f"Target content not found in {filepath}.\n"
                f"Looking for:\n{target_content[:200]}\n\n"
                f"Make sure the text matches exactly (including whitespace)."
            )

        count = original.count(target_content)
        if replace_all:
            new_content = original.replace(target_content, replacement_content)
            replaced = count
        else:
            new_content = original.replace(target_content, replacement_content, 1)
            replaced = 1

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)

        # Generate simple diff
        diff_lines = []
        for line in target_content.splitlines():
            diff_lines.append(f"- {line}")
        for line in replacement_content.splitlines():
            diff_lines.append(f"+ {line}")

        diff = "\n".join(diff_lines)
        return (
            f"Edited {filepath} ({replaced} replacement{'s' if replaced > 1 else ''}):\n"
            f"```diff\n{diff}\n```"
        )
