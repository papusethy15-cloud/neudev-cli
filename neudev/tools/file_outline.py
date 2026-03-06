"""File outline tool for NeuDev - extract code structure."""

import ast
import re
from pathlib import Path

from neudev.tools.base import BaseTool, ToolError


class FileOutlineTool(BaseTool):
    """View the code structure/outline of a file."""

    @property
    def name(self) -> str:
        return "file_outline"

    @property
    def description(self) -> str:
        return (
            "View the structure/outline of a code file: classes, functions, methods "
            "with their line numbers. Useful for understanding a file's organization "
            "before reading specific sections. Supports Python files with AST parsing "
            "and basic regex parsing for JavaScript/TypeScript."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the code file to outline.",
                },
            },
            "required": ["path"],
        }

    def execute(self, path: str, **kwargs) -> str:
        filepath = Path(path).resolve()

        if not filepath.exists():
            raise ToolError(f"File not found: {filepath}")
        if not filepath.is_file():
            raise ToolError(f"Not a file: {filepath}")

        ext = filepath.suffix.lower()

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            raise ToolError(f"Cannot read binary file: {filepath}")

        total_lines = content.count("\n") + 1

        if ext == ".py":
            outline = self._parse_python(content)
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            outline = self._parse_javascript(content)
        elif ext in (".java", ".cs", ".cpp", ".c", ".h", ".hpp"):
            outline = self._parse_clike(content)
        else:
            outline = self._parse_generic(content)

        if not outline:
            return f"File: {filepath} ({total_lines} lines)\n  No classes or functions found."

        header = f"File: {filepath} ({total_lines} lines)\n"
        return header + "\n".join(outline)

    def _parse_python(self, source: str) -> list[str]:
        """Parse Python file using AST."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return self._parse_generic(source)

        items = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                items.append((node.lineno, f"  class {node.name} (line {node.lineno})"))
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                        args = self._get_py_args(item)
                        prefix = "async " if isinstance(item, ast.AsyncFunctionDef) else ""
                        items.append(
                            (item.lineno, f"    {prefix}def {item.name}({args}) (line {item.lineno})")
                        )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Top-level functions only (not methods)
                if not any(
                    isinstance(parent, ast.ClassDef)
                    for parent in ast.walk(tree)
                    if hasattr(parent, "body") and node in getattr(parent, "body", [])
                ):
                    args = self._get_py_args(node)
                    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                    items.append((node.lineno, f"  {prefix}def {node.name}({args}) (line {node.lineno})"))

        items.sort(key=lambda x: x[0])
        return [item[1] for item in items]

    @staticmethod
    def _get_py_args(node) -> str:
        """Get function argument string."""
        args = []
        for arg in node.args.args:
            args.append(arg.arg)
        if len(args) > 4:
            return ", ".join(args[:3]) + ", ..."
        return ", ".join(args)

    def _parse_javascript(self, source: str) -> list[str]:
        """Parse JS/TS using regex."""
        items = []
        lines = source.splitlines()

        patterns = [
            (r"^\s*(?:export\s+)?class\s+(\w+)", "class"),
            (r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
            (r"^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(", "const fn"),
            (r"^\s*(?:async\s+)?(\w+)\s*\([^)]*\)\s*\{", "method"),
        ]

        for i, line in enumerate(lines, 1):
            for pattern, kind in patterns:
                match = re.match(pattern, line)
                if match:
                    name = match.group(1)
                    items.append(f"  {kind} {name} (line {i})")
                    break

        return items

    def _parse_clike(self, source: str) -> list[str]:
        """Parse C-like languages using regex."""
        items = []
        lines = source.splitlines()

        for i, line in enumerate(lines, 1):
            # Class/struct
            match = re.match(r"^\s*(?:public|private|protected)?\s*(?:class|struct|interface)\s+(\w+)", line)
            if match:
                items.append(f"  class {match.group(1)} (line {i})")
                continue

            # Function/method (simplified)
            match = re.match(r"^\s*(?:public|private|protected|static|virtual|override|\w+)\s+\w+\s+(\w+)\s*\(", line)
            if match:
                items.append(f"  function {match.group(1)} (line {i})")

        return items

    def _parse_generic(self, source: str) -> list[str]:
        """Fallback: find function-like and class-like patterns."""
        items = []
        lines = source.splitlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if any(stripped.startswith(kw) for kw in ("def ", "class ", "function ", "func ")):
                items.append(f"  {stripped[:60]}{'...' if len(stripped) > 60 else ''} (line {i})")

        return items
