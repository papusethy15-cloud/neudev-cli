"""AST-based JavaScript/TypeScript symbol parser using tree-sitter."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# Optional tree-sitter imports
try:
    import tree_sitter
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    tree_sitter = None

try:
    import tree_sitter_typescript
    TS_PARSER_AVAILABLE = True
except ImportError:
    TS_PARSER_AVAILABLE = False
    tree_sitter_typescript = None


logger = logging.getLogger(__name__)


class SymbolKind(Enum):
    """JavaScript/TypeScript symbol kinds."""

    CLASS = "class"
    INTERFACE = "interface"
    FUNCTION = "function"
    METHOD = "method"
    PROPERTY = "property"
    VARIABLE = "variable"
    CONSTANT = "constant"
    TYPE_ALIAS = "type_alias"
    ENUM = "enum"
    ENUM_MEMBER = "enum_member"
    IMPORT = "import"
    EXPORT = "export"
    MODULE = "module"


@dataclass
class Symbol:
    """Represents a code symbol."""

    name: str
    full_name: str
    kind: SymbolKind
    start_line: int
    end_line: int
    start_column: int
    end_column: int
    start_byte: int
    end_byte: int
    is_exported: bool = False
    is_async: bool = False
    parameters: list[str] | None = None
    type_annotation: str | None = None
    children: list["Symbol"] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "full_name": self.full_name,
            "kind": self.kind.value,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_column": self.start_column,
            "end_column": self.end_column,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "is_exported": self.is_exported,
            "is_async": self.is_async,
            "parameters": self.parameters,
            "type_annotation": self.type_annotation,
            "children": [c.to_dict() for c in self.children] if self.children else None,
        }


class JSTSParser:
    """JavaScript/TypeScript AST parser using tree-sitter."""

    def __init__(self):
        self._parser: Optional[tree_sitter.Parser] = None
        self._language: Optional[tree_sitter.Language] = None
        self._available = TREE_SITTER_AVAILABLE and TS_PARSER_AVAILABLE

        if self._available:
            try:
                self._language = tree_sitter.Language(tree_sitter_typescript.language_typescript())
                self._parser = tree_sitter.Parser(self._language)
            except Exception as e:
                logger.warning(f"Failed to initialize tree-sitter parser: {e}")
                self._available = False

    @property
    def is_available(self) -> bool:
        """Check if tree-sitter parsing is available."""
        return self._available

    def parse(self, source: str, file_path: Optional[str] = None) -> list[Symbol]:
        """
        Parse JavaScript/TypeScript source code and extract symbols.

        Args:
            source: Source code text
            file_path: Optional file path for language detection

        Returns:
            List of extracted symbols
        """
        if not self._available or self._parser is None:
            # Fallback to regex-based parsing
            return self._fallback_parse(source)

        try:
            # Parse the source
            tree = self._parser.parse(bytes(source, "utf8"))

            # Extract symbols from the tree
            symbols = self._extract_symbols(tree.root_node, source)
            return symbols

        except Exception as e:
            logger.warning(f"Tree-sitter parsing failed, using fallback: {e}")
            return self._fallback_parse(source)

    def _extract_symbols(
        self,
        node: tree_sitter.TreeNode,
        source: str,
        parent_name: str = "",
        parent_prefix: str = "",
    ) -> list[Symbol]:
        """Extract symbols from a tree-sitter node."""
        symbols: list[Symbol] = []

        # Get node type and check if it's a symbol
        symbol = self._node_to_symbol(node, source, parent_name, parent_prefix)

        if symbol:
            symbols.append(symbol)
            # Update parent prefix for nested symbols
            new_prefix = f"{parent_prefix}{symbol.name}." if parent_prefix else f"{symbol.name}."

        # Process child nodes
        for child in node.children:
            # Skip certain non-symbol nodes
            if child.type in {"comment", "string", "number", "regex", "template_string"}:
                continue

            # Recursively extract symbols from children
            child_symbols = self._extract_symbols(
                child,
                source,
                parent_name=symbol.name if symbol else parent_name,
                parent_prefix=new_prefix if symbol else parent_prefix,
            )
            symbols.extend(child_symbols)

        return symbols

    def _node_to_symbol(
        self,
        node: tree_sitter.TreeNode,
        source: str,
        parent_name: str,
        parent_prefix: str,
    ) -> Optional[Symbol]:
        """Convert a tree-sitter node to a Symbol if it represents one."""
        node_type = node.type
        start_point = node.start_point
        end_point = node.end_point

        # Get the node text
        node_text = source[node.start_byte : node.end_byte]

        # Check for different symbol types
        if node_type == "class_declaration":
            name = self._get_identifier_name(node, source)
            if not name:
                return None

            is_exported = self._is_exported(node)
            parameters = self._get_type_parameters(node, source)

            return Symbol(
                name=name,
                full_name=f"{parent_prefix}{name}" if parent_prefix else name,
                kind=SymbolKind.CLASS,
                start_line=start_point[0] + 1,
                end_line=end_point[0] + 1,
                start_column=start_point[1],
                end_column=end_point[1],
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                is_exported=is_exported,
                type_annotation=parameters,
            )

        elif node_type == "interface_declaration":
            name = self._get_identifier_name(node, source)
            if not name:
                return None

            return Symbol(
                name=name,
                full_name=f"{parent_prefix}{name}" if parent_prefix else name,
                kind=SymbolKind.INTERFACE,
                start_line=start_point[0] + 1,
                end_line=end_point[0] + 1,
                start_column=start_point[1],
                end_column=end_point[1],
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                is_exported=self._is_exported(node),
            )

        elif node_type == "function_declaration":
            name = self._get_identifier_name(node, source)
            if not name:
                return None

            params = self._get_parameters(node, source)
            is_async = self._is_async(node)

            return Symbol(
                name=name,
                full_name=f"{parent_prefix}{name}" if parent_prefix else name,
                kind=SymbolKind.FUNCTION,
                start_line=start_point[0] + 1,
                end_line=end_point[0] + 1,
                start_column=start_point[1],
                end_column=end_point[1],
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                is_exported=self._is_exported(node),
                is_async=is_async,
                parameters=params,
            )

        elif node_type == "method_definition":
            name = self._get_identifier_name(node, source)
            if not name:
                return None

            params = self._get_parameters(node, source)
            is_async = self._is_async(node)

            full_name = f"{parent_prefix}{name}" if parent_prefix else name

            return Symbol(
                name=name,
                full_name=full_name,
                kind=SymbolKind.METHOD,
                start_line=start_point[0] + 1,
                end_line=end_point[0] + 1,
                start_column=start_point[1],
                end_column=end_point[1],
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                is_async=is_async,
                parameters=params,
            )

        elif node_type == "variable_declarator":
            name = self._get_identifier_name(node, source)
            if not name:
                return None

            # Check if it's a function assignment
            is_function = self._is_function_assignment(node, source)
            kind = SymbolKind.FUNCTION if is_function else SymbolKind.VARIABLE

            params = self._get_parameters(node, source) if is_function else None
            is_async = self._is_async(node) if is_function else False

            return Symbol(
                name=name,
                full_name=f"{parent_prefix}{name}" if parent_prefix else name,
                kind=kind,
                start_line=start_point[0] + 1,
                end_line=end_point[0] + 1,
                start_column=start_point[1],
                end_column=end_point[1],
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                is_async=is_async,
                parameters=params,
            )

        elif node_type == "type_alias_declaration":
            name = self._get_identifier_name(node, source)
            if not name:
                return None

            return Symbol(
                name=name,
                full_name=f"{parent_prefix}{name}" if parent_prefix else name,
                kind=SymbolKind.TYPE_ALIAS,
                start_line=start_point[0] + 1,
                end_line=end_point[0] + 1,
                start_column=start_point[1],
                end_column=end_point[1],
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                is_exported=self._is_exported(node),
            )

        elif node_type == "enum_declaration":
            name = self._get_identifier_name(node, source)
            if not name:
                return None

            return Symbol(
                name=name,
                full_name=f"{parent_prefix}{name}" if parent_prefix else name,
                kind=SymbolKind.ENUM,
                start_line=start_point[0] + 1,
                end_line=end_point[0] + 1,
                start_column=start_point[1],
                end_column=end_point[1],
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                is_exported=self._is_exported(node),
            )

        return None

    def _get_identifier_name(self, node: tree_sitter.TreeNode, source: str) -> Optional[str]:
        """Get the identifier name from a node."""
        # Look for identifier child node
        for child in node.children:
            if child.type == "identifier":
                return source[child.start_byte : child.end_byte]
            if child.type == "type_identifier":
                return source[child.start_byte : child.end_byte]
            if child.type == "property_identifier":
                return source[child.start_byte : child.end_byte]
        return None

    def _is_exported(self, node: tree_sitter.TreeNode) -> bool:
        """Check if a node is exported."""
        # Check for export modifier
        for child in node.children:
            if child.type == "export":
                return True
            if child.type == "modifiers":
                for modifier in child.children:
                    if modifier.type == "export":
                        return True
        return False

    def _is_async(self, node: tree_sitter.TreeNode) -> bool:
        """Check if a node is async."""
        for child in node.children:
            if child.type == "async":
                return True
            if child.type == "modifiers":
                for modifier in child.children:
                    if modifier.type == "async":
                        return True
        return False

    def _get_parameters(
        self,
        node: tree_sitter.TreeNode,
        source: str,
    ) -> Optional[list[str]]:
        """Get parameter names from a function/method."""
        # Look for formal_parameters node
        for child in node.children:
            if child.type == "formal_parameters":
                params = []
                for param in child.children:
                    if param.type == "identifier":
                        params.append(source[param.start_byte : param.end_byte])
                    elif param.type == "required_parameter":
                        name = self._get_identifier_name(param, source)
                        if name:
                            params.append(name)
                return params if params else None
        return None

    def _get_type_parameters(
        self,
        node: tree_sitter.TreeNode,
        source: str,
    ) -> Optional[str]:
        """Get type parameters from a class/interface."""
        for child in node.children:
            if child.type == "type_parameters":
                return source[child.start_byte : child.end_byte]
        return None

    def _is_function_assignment(
        self,
        node: tree_sitter.TreeNode,
        source: str,
    ) -> bool:
        """Check if a variable is assigned a function."""
        for child in node.children:
            if child.type in {
                "arrow_function",
                "function_expression",
                "async_function_expression",
            }:
                return True
        return False

    def _fallback_parse(self, source: str) -> list[Symbol]:
        """Fallback to regex-based parsing when tree-sitter is unavailable."""
        # Import the fallback parser
        from neudev.tools.js_ts_symbols import iter_js_ts_symbols

        symbols: list[Symbol] = []
        fallback_symbols = iter_js_ts_symbols(source)

        for fb_symbol in fallback_symbols:
            kind_map = {
                "class": SymbolKind.CLASS,
                "function": SymbolKind.FUNCTION,
                "const function": SymbolKind.FUNCTION,
                "method": SymbolKind.METHOD,
            }

            kind = kind_map.get(fb_symbol["kind"], SymbolKind.VARIABLE)

            symbols.append(
                Symbol(
                    name=fb_symbol["name"],
                    full_name=fb_symbol["full_name"],
                    kind=kind,
                    start_line=fb_symbol["start_line"],
                    end_line=fb_symbol["end_line"],
                    start_column=0,
                    end_column=0,
                    start_byte=0,
                    end_byte=0,
                )
            )

        return symbols


def parse_js_ts_file(file_path: str | Path) -> list[Symbol]:
    """Parse a JavaScript/TypeScript file and extract symbols."""
    path = Path(file_path)
    if not path.exists():
        return []

    source = path.read_text(encoding="utf-8")
    parser = JSTSParser()
    return parser.parse(source, str(path))


def find_symbol_in_source(source: str, symbol_name: str) -> Optional[Symbol]:
    """Find a specific symbol in source code."""
    parser = JSTSParser()
    symbols = parser.parse(source)

    # Try exact match
    for symbol in symbols:
        if symbol.name == symbol_name or symbol.full_name == symbol_name:
            return symbol

    # Try partial match
    for symbol in symbols:
        if symbol_name in symbol.name or symbol_name in symbol.full_name:
            return symbol

    return None


def get_symbol_at_position(source: str, line: int, column: int) -> Optional[Symbol]:
    """Get the symbol at a specific position in source code."""
    parser = JSTSParser()
    symbols = parser.parse(source)

    for symbol in symbols:
        if symbol.start_line <= line <= symbol.end_line:
            if symbol.start_column <= column <= symbol.end_column:
                return symbol
            # Check children if available
            if symbol.children:
                for child in symbol.children:
                    if child.start_line <= line <= child.end_line:
                        if child.start_column <= column <= child.end_column:
                            return child

    return None
