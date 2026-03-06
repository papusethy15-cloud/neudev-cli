"""AST-aware Python edit tool for NeuDev."""

from __future__ import annotations

import ast
import textwrap

from neudev.tools.base import BaseTool, ToolError


class PythonAstEditTool(BaseTool):
    """Replace Python symbols by AST location instead of raw text matching."""

    @property
    def name(self) -> str:
        return "python_ast_edit"

    @property
    def description(self) -> str:
        return (
            "Edit a Python file by replacing a function, class, or method using AST "
            "symbol lookup. Use this for safer symbol-level edits when text matching "
            "is too brittle."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the Python file.",
                },
                "symbol": {
                    "type": "string",
                    "description": "Symbol to replace. Examples: 'demo', 'Worker.run'.",
                },
                "replacement_code": {
                    "type": "string",
                    "description": "Replacement function/class block. For methods, provide an unindented def block.",
                },
            },
            "required": ["path", "symbol", "replacement_code"],
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        return f"AST edit Python symbol: {args.get('symbol', 'unknown')} in {args.get('path', 'unknown')}"

    def execute(self, path: str, symbol: str, replacement_code: str, **kwargs) -> str:
        filepath = self.resolve_path(path, must_exist=True)
        if filepath.suffix.lower() != ".py":
            raise ToolError(f"python_ast_edit only supports Python files: {filepath}")

        try:
            source = filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ToolError(f"Cannot edit binary file: {filepath}")

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise ToolError(f"Cannot parse Python file {filepath}: {e}")

        symbol_parts = [part.strip() for part in symbol.split(".") if part.strip()]
        if not symbol_parts:
            raise ToolError("Symbol name is required.")

        target_node = self._find_symbol(tree, symbol_parts)
        if target_node is None or not hasattr(target_node, "end_lineno"):
            available = ", ".join(self._list_symbols(tree)[:20])
            raise ToolError(
                f"Symbol '{symbol}' not found in {filepath}.\n"
                f"Available symbols: {available or 'none'}"
            )

        replacement_text = replacement_code.replace("\r\n", "\n")
        normalized_lines = self._validate_and_prepare_replacement(
            target_node,
            symbol_parts,
            replacement_text,
        )

        newline = "\r\n" if "\r\n" in source else "\n"
        lines = source.splitlines()
        start = target_node.lineno - 1
        end = target_node.end_lineno
        lines[start:end] = normalized_lines

        new_source = newline.join(lines)
        if source.endswith(("\n", "\r\n")) and not new_source.endswith(newline):
            new_source += newline

        try:
            ast.parse(new_source)
        except SyntaxError as e:
            raise ToolError(f"Replacement created invalid Python syntax: {e}")

        filepath.write_text(new_source, encoding="utf-8")
        return f"AST edited {filepath}: replaced symbol '{symbol}'"

    def _find_symbol(self, tree: ast.AST, parts: list[str]):
        if len(parts) == 1:
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == parts[0]:
                    return node
            return None

        class_name, member_name = parts[0], parts[1]
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == member_name:
                        return member
        return None

    def _validate_and_prepare_replacement(
        self,
        target_node,
        symbol_parts: list[str],
        replacement_text: str,
    ) -> list[str]:
        normalized_text = textwrap.dedent(replacement_text).strip()
        snippet = normalized_text
        if not snippet:
            raise ToolError("Replacement code cannot be empty.")

        try:
            replacement_tree = ast.parse(snippet)
        except SyntaxError as e:
            raise ToolError(f"Replacement code is not valid Python: {e}")

        expected = ast.ClassDef if isinstance(target_node, ast.ClassDef) else (ast.FunctionDef, ast.AsyncFunctionDef)
        if not replacement_tree.body or not isinstance(replacement_tree.body[0], expected):
            raise ToolError(
                "Replacement code does not match the target symbol type."
            )

        if len(symbol_parts) == 1:
            return normalized_text.split("\n")

        indent = " " * getattr(target_node, "col_offset", 0)
        normalized = []
        for line in normalized_text.split("\n"):
            if line.strip():
                normalized.append(indent + line)
            else:
                normalized.append("")
        return normalized

    @staticmethod
    def _list_symbols(tree: ast.AST) -> list[str]:
        symbols = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append(node.name)
                if isinstance(node, ast.ClassDef):
                    for member in node.body:
                        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            symbols.append(f"{node.name}.{member.name}")
        return symbols
