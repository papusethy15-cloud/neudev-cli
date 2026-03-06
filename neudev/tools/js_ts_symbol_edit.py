"""Structured JavaScript/TypeScript symbol edit tool for NeuDev."""

from __future__ import annotations

import textwrap

from neudev.tools.base import BaseTool, ToolError
from neudev.tools.js_ts_symbols import JS_TS_EXTENSIONS, find_js_ts_symbol, list_js_ts_symbol_names


class JsTsSymbolEditTool(BaseTool):
    """Replace common JS/TS functions, classes, and methods by symbol lookup."""

    @property
    def name(self) -> str:
        return "js_ts_symbol_edit"

    @property
    def description(self) -> str:
        return (
            "Edit a JavaScript or TypeScript file by replacing a function, class, or class method "
            "using symbol lookup and structural brace matching."
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
            },
            "required": ["path", "symbol", "replacement_code"],
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        return f"Structured JS/TS edit: {args.get('symbol', 'unknown')} in {args.get('path', 'unknown')}"

    def execute(self, path: str, symbol: str, replacement_code: str, **kwargs) -> str:
        filepath = self.resolve_path(path, must_exist=True)
        if filepath.suffix.lower() not in JS_TS_EXTENSIONS:
            raise ToolError(f"js_ts_symbol_edit only supports JS/TS files: {filepath}")

        try:
            source = filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ToolError(f"Cannot edit binary file: {filepath}")

        target = find_js_ts_symbol(source, symbol)
        if target is None:
            available = ", ".join(list_js_ts_symbol_names(source)[:20])
            raise ToolError(
                f"Symbol '{symbol}' not found in {filepath}.\n"
                f"Available symbols: {available or 'none'}"
            )

        replacement_lines = self._prepare_replacement(replacement_code, target["indent"], target["kind"])

        newline = "\r\n" if "\r\n" in source else "\n"
        lines = source.splitlines()
        start = target["start_index"]
        end = target["end_index"] + 1
        lines[start:end] = replacement_lines

        new_source = newline.join(lines)
        if source.endswith(("\n", "\r\n")) and not new_source.endswith(newline):
            new_source += newline

        filepath.write_text(new_source, encoding="utf-8")
        return f"Structured edited {filepath}: replaced symbol '{symbol}'"

    @staticmethod
    def _prepare_replacement(replacement_code: str, indent: str, kind: str) -> list[str]:
        normalized = textwrap.dedent(replacement_code).strip()
        if not normalized:
            raise ToolError("Replacement code cannot be empty.")

        if kind == "method":
            return [f"{indent}{line}" if line.strip() else "" for line in normalized.split("\n")]
        return normalized.split("\n")
