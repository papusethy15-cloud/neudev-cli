"""Fallback parsing for text-based tool calls emitted by non-native tool models."""

from __future__ import annotations

import json
import re
from typing import Iterable


TOOL_BLOCK_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.IGNORECASE | re.DOTALL)
FUNCTION_RE = re.compile(r"<function\s*=\s*([a-zA-Z0-9_]+)>", re.IGNORECASE)
PARAM_RE = re.compile(
    r"<parameter\s*=\s*([a-zA-Z0-9_]+)>(.*?)</parameter>",
    re.IGNORECASE | re.DOTALL,
)
JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def extract_text_tool_calls(text: str, available_tools: Iterable[str]) -> tuple[list[dict], str]:
    """Extract structured tool calls from text content and return the cleaned text."""
    if not text:
        return [], text

    allowed = set(available_tools)
    tool_calls: list[dict] = []
    cleaned = text

    xml_calls = _extract_xml_tool_calls(text, allowed)
    if xml_calls:
        tool_calls.extend(xml_calls)
        cleaned = TOOL_BLOCK_RE.sub("", cleaned)

    if not tool_calls:
        json_calls, json_cleaned = _extract_json_tool_calls(cleaned, allowed)
        if json_calls:
            tool_calls.extend(json_calls)
            cleaned = json_cleaned

    cleaned = _normalize_whitespace(cleaned)
    return tool_calls, cleaned


def _extract_xml_tool_calls(text: str, allowed: set[str]) -> list[dict]:
    tool_calls: list[dict] = []

    for block in TOOL_BLOCK_RE.findall(text):
        function_match = FUNCTION_RE.search(block)
        if not function_match:
            continue

        name = function_match.group(1).strip()
        if name not in allowed:
            continue

        arguments = {}
        for arg_name, raw_value in PARAM_RE.findall(block):
            arguments[arg_name.strip()] = _coerce_value(raw_value)

        tool_calls.append({"name": name, "arguments": arguments})

    return tool_calls


def _extract_json_tool_calls(text: str, allowed: set[str]) -> tuple[list[dict], str]:
    tool_calls: list[dict] = []
    cleaned = text

    for block in JSON_BLOCK_RE.findall(text):
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue

        parsed = _normalize_json_payload(payload, allowed)
        if not parsed:
            continue

        tool_calls.extend(parsed)
        cleaned = cleaned.replace(f"```json\n{block}```", "")
        cleaned = cleaned.replace(f"```json\r\n{block}```", "")

    return tool_calls, cleaned


def _normalize_json_payload(payload: object, allowed: set[str]) -> list[dict]:
    if isinstance(payload, dict):
        if "tool_calls" in payload and isinstance(payload["tool_calls"], list):
            result: list[dict] = []
            for item in payload["tool_calls"]:
                result.extend(_normalize_json_payload(item, allowed))
            return result

        name = payload.get("name") or payload.get("tool") or payload.get("function")
        arguments = payload.get("arguments") or payload.get("args") or {}
        if isinstance(name, str) and isinstance(arguments, dict) and name in allowed:
            return [{"name": name, "arguments": arguments}]
        return []

    if isinstance(payload, list):
        result: list[dict] = []
        for item in payload:
            result.extend(_normalize_json_payload(item, allowed))
        return result

    return []


def _coerce_value(value: str) -> object:
    stripped = value.strip()
    if not stripped:
        return ""

    if stripped.lower() == "true":
        return True
    if stripped.lower() == "false":
        return False
    if re.fullmatch(r"-?\d+", stripped):
        return int(stripped)
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
    return stripped


def _normalize_whitespace(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)
