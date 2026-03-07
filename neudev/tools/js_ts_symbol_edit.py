"""Structured JavaScript/TypeScript symbol edit tool for NeuDev - AST-enhanced."""

from __future__ import annotations

import textwrap
from typing import Optional

from neudev.tools.base import BaseTool, ToolError
from neudev.tools.js_ts_symbols import JS_TS_EXTENSIONS, find_js_ts_symbol, list_js_ts_symbol_names
from neudev.ast_parser import JSTSParser, Symbol as ASTSymbol


class JsTsSymbolEditTool(BaseTool):
    """Replace common JS/TS functions, classes, and methods using AST or fallback parsing."""

    def __init__(self) -> None:
        super().__init__()
        self._ast_parser = JSTSParser()

    @property
    def name(self) -> str:
        return "js_ts_symbol_edit"

    @property
    def description(self) -> str:
        return (
            "Edit a JavaScript or TypeScript file by replacing a function, class, or class method "
            "using AST-based symbol lookup with fallback to structural brace matching. "
            "Prefer this tool for precise symbol-level edits that preserve formatting."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the JavaScript or TypeScript file.",
                },
                "symbol": {
                    "type": "string",
                    "description": "Symbol to replace. Examples: 'greetUser', 'Widget.run'.",
                },
                "replacement_code": {
                    "type": "string",
                    "description": "Replacement function, class, or method block.",
                },
                "use_ast": {
                    "type": "boolean",
                    "description": "Force AST-based parsing (default: auto-detect).",
                    "default": None,
                },
            },
            "required": ["path", "symbol", "replacement_code"],
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        return f"Structured JS/TS edit: {args.get('symbol', 'unknown')} in {args.get('path', 'unknown')}"

    def execute(
        self,
        path: str,
        symbol: str,
        replacement_code: str,
        use_ast: Optional[bool] = None,
        **kwargs,
    ) -> str:
        filepath = self.resolve_path(path, must_exist=True)
        if filepath.suffix.lower() not in JS_TS_EXTENSIONS:
            raise ToolError(f"js_ts_symbol_edit only supports JS/TS files: {filepath}")

        try:
            source = filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ToolError(f"Cannot edit binary file: {filepath}")

        # Try AST-based parsing first
        use_ast_parser = use_ast if use_ast is not None else self._ast_parser.is_available
        target: Optional[ASTSymbol | dict] = None

        if use_ast_parser:
            target = self._find_symbol_ast(source, symbol)

        # Fallback to regex-based parsing
        if target is None:
            target = find_js_ts_symbol(source, symbol)

        if target is None:
            available = ", ".join(list_js_ts_symbol_names(source)[:20])
            raise ToolError(
                f"Symbol '{symbol}' not found in {filepath}.\n"
                f"Available symbols: {available or 'none'}"
            )

        # Extract symbol properties
        if isinstance(target, ASTSymbol):
            symbol_name = target.name
            indent = self._detect_indent(source, target.start_line - 1)
            kind = target.kind.value
            start_index = target.start_line - 1
            end_index = target.end_line - 1
        else:
            symbol_name = target["name"]
            indent = target.get("indent", "")
            kind = target["kind"]
            start_index = target["start_index"]
            end_index = target["end_index"]

        replacement_lines = self._prepare_replacement(replacement_code, indent, kind)

        newline = "\r\n" if "\r\n" in source else "\n"
        lines = source.splitlines()
        start = start_index
        end = end_index + 1
        lines[start:end] = replacement_lines

        new_source = newline.join(lines)
        if source.endswith(("\n", "\r\n")) and not new_source.endswith(newline):
            new_source += newline

        filepath.write_text(new_source, encoding="utf-8")

        parse_method = "AST" if isinstance(target, ASTSymbol) else "regex fallback"
        return f"Structured edited {filepath}: replaced symbol '{symbol_name}' using {parse_method} parsing"

    def _find_symbol_ast(self, source: str, symbol: str) -> Optional[ASTSymbol]:
        """Find a symbol using AST parsing."""
        if not self._ast_parser.is_available:
            return None

        try:
            symbols = self._ast_parser.parse(source)

            # Try exact match on full_name
            for sym in symbols:
                if sym.full_name == symbol or sym.name == symbol:
                    return sym

            # Try partial match
            for sym in symbols:
                if symbol in sym.name or symbol in sym.full_name:
                    return sym

        except Exception:
            pass

        return None

    def _detect_indent(self, source: str, line_index: int) -> str:
        """Detect indentation for a specific line."""
        lines = source.splitlines()
        if 0 <= line_index < len(lines):
            line = lines[line_index]
            stripped = line.lstrip()
            if stripped:
                return line[: len(line) - len(stripped)]
        return ""

    @staticmethod
    def _prepare_replacement(replacement_code: str, indent: str, kind: str) -> list[str]:
        normalized = textwrap.dedent(replacement_code).strip()
        if not normalized:
            raise ToolError("Replacement code cannot be empty.")

        if kind == "method":
            return [f"{indent}{line}" if line.strip() else "" for line in normalized.split("\n")]
        return normalized.split("\n")
