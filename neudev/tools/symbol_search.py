"""Symbol-level search tool for NeuDev."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from neudev.tools.base import BaseTool
from neudev.tools.js_ts_symbols import JS_TS_EXTENSIONS, iter_js_ts_symbols


SUPPORTED_EXTENSIONS = {".py", *JS_TS_EXTENSIONS}


class SymbolSearchTool(BaseTool):
    """Search for symbol definitions and references across the workspace."""

    @property
    def name(self) -> str:
        return "symbol_search"

    @property
    def description(self) -> str:
        return (
            "Search for symbol definitions and references across Python, JavaScript, and TypeScript files. "
            "Useful for fast repo navigation before edits or reviews."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Symbol name to search for. Examples: 'greet', 'Worker.run'.",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to search from. Defaults to the workspace root.",
                },
                "definitions_only": {
                    "type": "boolean",
                    "description": "Only return symbol definitions, not references.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of definition and reference rows to return per section. Default 20.",
                },
            },
            "required": ["symbol"],
        }

    def execute(
        self,
        symbol: str,
        directory: str = ".",
        definitions_only: bool = False,
        max_results: int = 20,
        **kwargs,
    ) -> str:
        dirpath = self.resolve_directory(directory, must_exist=True)
        limit = max(1, int(max_results))
        definition_rows: list[str] = []
        reference_rows: list[str] = []
        definition_lines: dict[str, set[int]] = {}

        for filepath in sorted(dirpath.rglob("*")):
            if not filepath.is_file() or filepath.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            try:
                source = filepath.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue

            relative = self._relative_path(filepath)
            if filepath.suffix.lower() == ".py":
                definitions = self._python_definitions(source, symbol)
            else:
                definitions = self._js_ts_definitions(source, symbol)

            if definitions:
                definition_lines.setdefault(relative, set()).update(item["line"] for item in definitions)
                for item in definitions:
                    if len(definition_rows) >= limit:
                        break
                    definition_rows.append(
                        f"- {relative}:{item['line']} {item['kind']} {item['name']}"
                    )

            if definitions_only or len(reference_rows) >= limit:
                continue

            skip_lines = definition_lines.get(relative, set())
            for row in self._reference_rows(source, relative, symbol, skip_lines, limit - len(reference_rows)):
                reference_rows.append(row)
                if len(reference_rows) >= limit:
                    break

        lines = [f"Symbol search: {symbol}", ""]
        lines.append("Definitions:")
        lines.extend(definition_rows or ["- No definitions found."])

        if not definitions_only:
            lines.extend(["", "References:"])
            lines.extend(reference_rows or ["- No references found."])

        return "\n".join(lines)

    def _python_definitions(self, source: str, symbol: str) -> list[dict]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        parts = [part.strip() for part in symbol.split(".") if part.strip()]
        results = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                if self._matches_symbol(parts, node.name, None):
                    results.append({"line": node.lineno, "kind": "class", "name": node.name})
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and self._matches_symbol(parts, member.name, node.name):
                        results.append({
                            "line": member.lineno,
                            "kind": "method",
                            "name": f"{node.name}.{member.name}",
                        })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and self._matches_symbol(parts, node.name, None):
                results.append({"line": node.lineno, "kind": "function", "name": node.name})
        return results

    def _js_ts_definitions(self, source: str, symbol: str) -> list[dict]:
        parts = [part.strip() for part in symbol.split(".") if part.strip()]
        results = []
        for item in iter_js_ts_symbols(source):
            container = item["full_name"].split(".")[0] if "." in item["full_name"] else None
            if self._matches_symbol(parts, item["name"], container):
                results.append({
                    "line": item["start_line"],
                    "kind": item["kind"],
                    "name": item["full_name"],
                })
        return results

    def _reference_rows(
        self,
        source: str,
        relative: str,
        symbol: str,
        skip_lines: set[int],
        remaining: int,
    ) -> list[str]:
        token = symbol.split(".")[-1].strip()
        if not token:
            return []

        pattern = re.compile(rf"(?<![A-Za-z0-9_$]){re.escape(token)}(?![A-Za-z0-9_$])")
        rows = []
        for line_number, line in enumerate(source.splitlines(), 1):
            if line_number in skip_lines or not pattern.search(line):
                continue
            snippet = line.strip()
            if len(snippet) > 160:
                snippet = snippet[:160].rstrip() + "..."
            rows.append(f"- {relative}:{line_number} {snippet}")
            if len(rows) >= remaining:
                break
        return rows

    @staticmethod
    def _matches_symbol(parts: list[str], name: str, container: str | None) -> bool:
        if not parts:
            return False
        if len(parts) == 1:
            return name == parts[0]
        return container == parts[0] and name == parts[1]

    def _relative_path(self, filepath: Path) -> str:
        base = self.workspace or Path.cwd()
        return str(filepath.relative_to(base)).replace("\\", "/")
