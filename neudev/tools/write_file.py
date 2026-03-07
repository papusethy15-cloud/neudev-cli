"""Write file tool for NeuDev."""

from neudev.tools.base import BaseTool, ToolError


class WriteFileTool(BaseTool):
    """Create or overwrite a file."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Create a new file or overwrite an existing file with the given content. "
            "Parent directories are created automatically. Use this to create new "
            "source files, config files, etc. Set overwrite=true to replace existing files."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to create or overwrite.",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file.",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": (
                        "If true, overwrite existing file without error. "
                        "If false (default), fails if file exists. "
                        "Use true when you want to completely replace a file's content."
                    ),
                    "default": False,
                },
                "create_dirs": {
                    "type": "boolean",
                    "description": "Create parent directories if they don't exist (default: True).",
                    "default": True,
                },
            },
            "required": ["path", "content"],
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        path = args.get("path", "unknown")
        overwrite = args.get("overwrite", False)
        try:
            exists = self.resolve_path(path).exists()
        except ToolError:
            exists = False
        if exists and overwrite:
            return f"Overwrite existing file: {path}"
        elif exists:
            return f"File already exists: {path} (set overwrite=true to replace)"
        else:
            return f"Create new file: {path}"

    def execute(self, path: str, content: str, overwrite: bool = False, create_dirs: bool = True, **kwargs) -> str:
        filepath = self.resolve_path(path)

        existed = filepath.exists()

        if existed and not overwrite:
            raise ToolError(
                f"File already exists: {filepath}\n"
                f"Set overwrite=true to replace it, or use edit_file to modify specific parts."
            )

        # Create parent directories if requested
        if create_dirs:
            filepath.parent.mkdir(parents=True, exist_ok=True)
        elif not filepath.parent.exists():
            raise ToolError(f"Parent directory does not exist: {filepath.parent}")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        
        if existed and overwrite:
            action = "Overwrote"
            detail = f" (replaced {line_count} lines)"
        elif existed:
            action = "Modified"
            detail = f" ({line_count} lines)"
        else:
            action = "Created"
            detail = f" ({line_count} lines)"
        
        return f"{action} file: {filepath}{detail}"
