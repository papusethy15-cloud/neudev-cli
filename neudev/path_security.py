"""Enhanced path security with symlink and traversal protection."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class PathRiskLevel(Enum):
    """Risk level for path operations."""

    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


@dataclass
class PathSecurityResult:
    """Result of path security validation."""

    is_safe: bool
    risk_level: PathRiskLevel
    resolved_path: Optional[Path]
    message: str
    is_symlink: bool = False
    symlink_target: Optional[Path] = None
    outside_workspace: bool = False


class PathSecurityValidator:
    """Validates file paths for security issues."""

    # Dangerous path components
    DANGEROUS_COMPONENTS = {
        "..",  # Parent directory traversal
        "~",  # Home directory
        "$",  # Environment variable
        "%",  # Windows environment variable
        "`",  # Command substitution
        "!",  # History expansion
    }

    # Dangerous symlinks that should always be blocked
    BLOCKED_SYMLINK_TARGETS = {
        "/etc",
        "/etc/passwd",
        "/etc/shadow",
        "/etc/hosts",
        "/etc/resolv.conf",
        "/proc",
        "/sys",
        "/dev",
        "/var/log",
        "/root",
        "/boot",
        "C:\\Windows",
        "C:\\Windows\\System32",
        "C:\\Program Files",
        "C:\\Program Files (x86)",
    }

    # Maximum symlink depth to prevent symlink loops
    MAX_SYMLINK_DEPTH = 10

    # Maximum path length
    MAX_PATH_LENGTH = 260 if os.name == "nt" else 4096

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()

    def validate_path(
        self,
        path: str | Path,
        must_exist: bool = False,
        allow_symlinks: bool = True,
    ) -> PathSecurityResult:
        """
        Validate a path for security issues.

        Args:
            path: Path to validate
            must_exist: Whether the path must exist
            allow_symlinks: Whether to allow symlinks

        Returns:
            PathSecurityResult with validation details
        """
        path_str = str(path)

        # Check path length
        if len(path_str) > self.MAX_PATH_LENGTH:
            return PathSecurityResult(
                is_safe=False,
                risk_level=PathRiskLevel.BLOCKED,
                resolved_path=None,
                message=f"Path exceeds maximum length ({len(path_str)} > {self.MAX_PATH_LENGTH})",
            )

        # Check for dangerous components
        dangerous = self._check_dangerous_components(path_str)
        if dangerous:
            return PathSecurityResult(
                is_safe=False,
                risk_level=PathRiskLevel.BLOCKED,
                resolved_path=None,
                message=f"Path contains dangerous components: {dangerous}",
            )

        # Resolve the path
        try:
            path_obj = Path(path_str)
            if not path_obj.is_absolute():
                path_obj = self.workspace / path_obj

            # Check if path is inside workspace before resolving symlinks
            try:
                # Use resolve() to get canonical path
                resolved = path_obj.resolve(strict=must_exist)
            except (OSError, RuntimeError) as e:
                return PathSecurityResult(
                    is_safe=False,
                    risk_level=PathRiskLevel.HIGH,
                    resolved_path=None,
                    message=f"Path resolution failed: {e}",
                )

            # Check if resolved path is inside workspace
            outside_workspace = self._is_outside_workspace(resolved)

            # Check for symlinks
            is_symlink = path_obj.is_symlink()
            symlink_target = None
            if is_symlink:
                try:
                    symlink_target = path_obj.readlink()
                except (OSError, NotImplementedError):
                    pass

            # Validate symlinks
            if is_symlink and not allow_symlinks:
                return PathSecurityResult(
                    is_safe=False,
                    risk_level=PathRiskLevel.HIGH,
                    resolved_path=resolved,
                    message="Symlinks are not allowed",
                    is_symlink=True,
                    symlink_target=symlink_target,
                    outside_workspace=outside_workspace,
                )

            # Check if symlink target is blocked
            if is_symlink and symlink_target:
                blocked = self._is_blocked_symlink_target(resolved, symlink_target)
                if blocked:
                    return PathSecurityResult(
                        is_safe=False,
                        risk_level=PathRiskLevel.BLOCKED,
                        resolved_path=resolved,
                        message=f"Symlink target is blocked: {symlink_target}",
                        is_symlink=True,
                        symlink_target=symlink_target,
                        outside_workspace=outside_workspace,
                    )

            # Determine risk level
            risk_level = self._assess_risk_level(resolved, is_symlink, outside_workspace)

            return PathSecurityResult(
                is_safe=risk_level != PathRiskLevel.BLOCKED,
                risk_level=risk_level,
                resolved_path=resolved,
                message=self._get_risk_message(risk_level, outside_workspace, is_symlink),
                is_symlink=is_symlink,
                symlink_target=symlink_target,
                outside_workspace=outside_workspace,
            )

        except Exception as e:
            return PathSecurityResult(
                is_safe=False,
                risk_level=PathRiskLevel.HIGH,
                resolved_path=None,
                message=f"Path validation error: {type(e).__name__}: {e}",
            )

    def _check_dangerous_components(self, path_str: str) -> list[str]:
        """Check for dangerous path components."""
        found = []
        path_lower = path_str.lower()

        for component in self.DANGEROUS_COMPONENTS:
            if component in path_str:
                # Allow ~ at the start for home directory expansion
                if component == "~" and path_str.startswith("~"):
                    continue
                found.append(component)

        # Check for null bytes
        if "\x00" in path_str:
            found.append("<null-byte>")

        # Check for shell command patterns
        if "$(" in path_str or "`" in path_str:
            found.append("command-substitution")

        return found

    def _is_outside_workspace(self, path: Path) -> bool:
        """Check if path is outside the workspace."""
        try:
            path.relative_to(self.workspace)
            return False
        except ValueError:
            return True

    def _is_blocked_symlink_target(
        self,
        resolved: Path,
        symlink_target: Path,
    ) -> bool:
        """Check if symlink target is in blocked list."""
        resolved_str = str(resolved).lower()
        target_str = str(symlink_target).lower()

        for blocked in self.BLOCKED_SYMLINK_TARGETS:
            blocked_lower = blocked.lower()
            if resolved_str.startswith(blocked_lower) or target_str.startswith(blocked_lower):
                return True

        return False

    def _assess_risk_level(
        self,
        path: Path,
        is_symlink: bool,
        outside_workspace: bool,
    ) -> PathRiskLevel:
        """Assess the risk level of a path."""
        # Always block paths outside workspace
        if outside_workspace:
            return PathRiskLevel.BLOCKED

        # High risk: symlinks to sensitive locations
        if is_symlink:
            path_str = str(path).lower()
            if any(sensitive in path_str for sensitive in [".env", ".git", "password", "secret", "key"]):
                return PathRiskLevel.HIGH

        # Check file permissions if path exists
        if path.exists():
            try:
                file_stat = path.stat()
                # Check if world-writable
                if file_stat.st_mode & stat.S_IWOTH:
                    return PathRiskLevel.MEDIUM
                # Check if setuid/setgid
                if file_stat.st_mode & (stat.S_ISUID | stat.S_ISGID):
                    return PathRiskLevel.MEDIUM
            except OSError:
                pass

        # Low risk: normal files inside workspace
        return PathRiskLevel.LOW

    def _get_risk_message(
        self,
        risk_level: PathRiskLevel,
        outside_workspace: bool,
        is_symlink: bool,
    ) -> str:
        """Get human-readable risk message."""
        if outside_workspace:
            return "Path is outside the workspace directory"

        messages = {
            PathRiskLevel.SAFE: "Path is safe to access",
            PathRiskLevel.LOW: "Path has low risk",
            PathRiskLevel.MEDIUM: "Path has medium risk (check permissions)",
            PathRiskLevel.HIGH: "Path has high risk (review before accessing)",
            PathRiskLevel.BLOCKED: "Path is blocked for security reasons",
        }

        msg = messages.get(risk_level, "Unknown risk level")

        if is_symlink:
            msg += " (symlink detected)"

        return msg

    def safe_resolve_path(
        self,
        path: str | Path,
        must_exist: bool = False,
    ) -> Path:
        """
        Safely resolve a path, raising an error if unsafe.

        Args:
            path: Path to resolve
            must_exist: Whether path must exist

        Returns:
            Resolved Path

        Raises:
            ValueError: If path is unsafe
        """
        result = self.validate_path(path, must_exist=must_exist)

        if not result.is_safe:
            raise ValueError(f"Path security violation: {result.message}")

        if result.resolved_path is None:
            raise ValueError(f"Could not resolve path: {path}")

        return result.resolved_path


def create_safe_path_resolver(workspace: str | Path) -> callable:
    """
    Create a safe path resolver function for a workspace.

    Args:
        workspace: Workspace root path

    Returns:
        Function that safely resolves paths
    """
    validator = PathSecurityValidator(workspace)

    def resolver(path: str, must_exist: bool = False) -> str:
        """Resolve a path safely."""
        resolved = validator.safe_resolve_path(path, must_exist=must_exist)
        return str(resolved)

    return resolver
