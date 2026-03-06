"""Shared JavaScript/TypeScript symbol helpers for NeuDev tools."""

from __future__ import annotations

import re


JS_TS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}

CLASS_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)\b"
)
FUNCTION_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\b"
)
CONST_FUNCTION_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s+)?(?:function\b|\([^;=]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"
)
METHOD_RE = re.compile(
    r"^(?P<indent>\s*)(?:public\s+|private\s+|protected\s+|static\s+|readonly\s+|"
    r"abstract\s+|override\s+|async\s+|get\s+|set\s+)*(?P<name>[A-Za-z_$][\w$]*)"
    r"\s*\([^;]*\)\s*(?::\s*[^={]+)?\s*\{"
)


def iter_js_ts_symbols(source: str) -> list[dict]:
    """Return common JS/TS symbol declarations with their line spans."""
    lines = source.splitlines()
    symbols: list[dict] = []
    index = 0

    while index < len(lines):
        line = lines[index]

        class_match = CLASS_RE.match(line)
        if class_match:
            name = class_match.group("name")
            end_index = _find_declaration_end(lines, index)
            symbols.append({
                "name": name,
                "full_name": name,
                "kind": "class",
                "start_index": index,
                "end_index": end_index,
                "start_line": index + 1,
                "end_line": end_index + 1,
                "indent": _leading_whitespace(line),
            })
            symbols.extend(_iter_class_methods(lines, index, end_index, name))
            index = max(index + 1, end_index + 1)
            continue

        function_match = FUNCTION_RE.match(line)
        if function_match:
            name = function_match.group("name")
            end_index = _find_declaration_end(lines, index)
            symbols.append({
                "name": name,
                "full_name": name,
                "kind": "function",
                "start_index": index,
                "end_index": end_index,
                "start_line": index + 1,
                "end_line": end_index + 1,
                "indent": _leading_whitespace(line),
            })
            index = max(index + 1, end_index + 1)
            continue

        const_match = CONST_FUNCTION_RE.match(line)
        if const_match:
            name = const_match.group("name")
            end_index = _find_declaration_end(lines, index)
            symbols.append({
                "name": name,
                "full_name": name,
                "kind": "const function",
                "start_index": index,
                "end_index": end_index,
                "start_line": index + 1,
                "end_line": end_index + 1,
                "indent": _leading_whitespace(line),
            })
            index = max(index + 1, end_index + 1)
            continue

        index += 1

    return symbols


def find_js_ts_symbol(source: str, symbol: str) -> dict | None:
    """Find a symbol entry by full name or short name."""
    parts = [part.strip() for part in symbol.split(".") if part.strip()]
    for entry in iter_js_ts_symbols(source):
        if entry["full_name"] == symbol:
            return entry
        if len(parts) == 1 and entry["name"] == parts[0]:
            return entry
    return None


def list_js_ts_symbol_names(source: str) -> list[str]:
    """List discovered symbol names for error messages and prompts."""
    return [entry["full_name"] for entry in iter_js_ts_symbols(source)]


def _iter_class_methods(lines: list[str], class_start: int, class_end: int, class_name: str) -> list[dict]:
    methods: list[dict] = []
    index = class_start + 1
    while index < class_end:
        line = lines[index]
        method_match = METHOD_RE.match(line)
        if method_match:
            name = method_match.group("name")
            end_index = _find_declaration_end(lines, index)
            methods.append({
                "name": name,
                "full_name": f"{class_name}.{name}",
                "kind": "method",
                "start_index": index,
                "end_index": end_index,
                "start_line": index + 1,
                "end_line": end_index + 1,
                "indent": method_match.group("indent"),
            })
            index = max(index + 1, end_index + 1)
            continue
        index += 1
    return methods


def _find_declaration_end(lines: list[str], start_index: int) -> int:
    seen_open = False
    depth = 0

    for index in range(start_index, len(lines)):
        for char in _strip_inline_comment(lines[index]):
            if char == "{":
                seen_open = True
                depth += 1
            elif char == "}":
                if seen_open and depth > 0:
                    depth -= 1
            elif char == ";" and not seen_open:
                return index

        if seen_open and depth == 0:
            return index

    return start_index


def _strip_inline_comment(line: str) -> str:
    return re.sub(r"//.*", "", line)


def _leading_whitespace(line: str) -> str:
    stripped = line.lstrip()
    return line[: len(line) - len(stripped)]
