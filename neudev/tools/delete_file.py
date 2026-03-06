"""Delete file tool for NeuDev."""

from neudev.tools.base import BaseTool, ToolError


class DeleteFileTool(BaseTool):
    """Delete a file."""

    @property
    def name(self) -> str:
        return "delete_file"

    @property
    def description(self) -> str:
        return (
            "Delete a file from the filesystem. Use with caution. "
            "Requires user permission before execution."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to delete.",
                },
            },
            "required": ["path"],
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        return f"Delete file: {args.get('path', 'unknown')}"

    def execute(self, path: str, **kwargs) -> str:
        filepath = self.resolve_path(path, must_exist=True)

        if not filepath.exists():
            raise ToolError(f"File not found: {filepath}")
        if not filepath.is_file():
            raise ToolError(f"Not a file (is a directory?): {filepath}")

        filepath.unlink()
        return f"Deleted file: {filepath}"
