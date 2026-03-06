"""Diagnostics tool for NeuDev."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from neudev.tools.base import BaseTool, ToolError


VALID_CHECKS = {"syntax", "tests", "lint", "typecheck"}


@dataclass
class CheckOutcome:
    name: str
    status: str
    command: str = ""
    details: str = ""


class DiagnosticsTool(BaseTool):
    """Run grouped project diagnostics with internal command fallbacks."""

    @property
    def name(self) -> str:
        return "diagnostics"

    @property
    def description(self) -> str:
        return (
            "Run smart project diagnostics such as syntax checks, tests, lint, and typecheck. "
            "Automatically falls back between common commands for Python and package-script projects."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Project directory to diagnose. Defaults to workspace root.",
                },
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": sorted(VALID_CHECKS),
                    },
                    "description": "Subset of checks to run. Defaults to auto-detected checks.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Per-check timeout in seconds. Default 60.",
                },
            },
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        checks = args.get("checks") or ["auto"]
        return f"Run diagnostics in {args.get('directory', '.')} with checks: {', '.join(checks)}"

    def execute(self, directory: str = ".", checks: list[str] = None, timeout: int = 60, **kwargs) -> str:
        dirpath = self.resolve_directory(directory, must_exist=True)
        if not dirpath.is_dir():
            raise ToolError(f"Not a directory: {dirpath}")

        requested_checks = self._normalize_checks(checks)
        profile = self._detect_profile(dirpath)
        if not requested_checks:
            requested_checks = self._default_checks(dirpath, profile)

        outcomes = []
        for check in requested_checks:
            outcomes.append(self._run_check(check, dirpath, profile, timeout))

        passed = sum(1 for item in outcomes if item.status == "PASS")
        failed = sum(1 for item in outcomes if item.status == "FAIL")
        skipped = sum(1 for item in outcomes if item.status == "SKIP")

        lines = [
            f"Diagnostics: {dirpath}",
            f"Profile: {profile}",
            f"Summary: {passed} passed, {failed} failed, {skipped} skipped",
            "",
        ]
        for outcome in outcomes:
            lines.append(f"[{outcome.status}] {outcome.name}")
            if outcome.command:
                lines.append(f"Command: {outcome.command}")
            if outcome.details:
                lines.append(outcome.details)
            lines.append("")
        return "\n".join(lines).rstrip()

    def _normalize_checks(self, checks: list[str] | None) -> list[str]:
        if not checks:
            return []
        normalized = []
        for check in checks:
            name = str(check).strip().lower()
            if name not in VALID_CHECKS:
                raise ToolError(
                    f"Invalid diagnostics check '{check}'. Expected one of: {', '.join(sorted(VALID_CHECKS))}"
                )
            if name not in normalized:
                normalized.append(name)
        return normalized

    def _detect_profile(self, dirpath: Path) -> str:
        if (dirpath / "package.json").exists() and not (
            (dirpath / "setup.py").exists()
            or (dirpath / "pyproject.toml").exists()
            or (dirpath / "requirements.txt").exists()
        ):
            return "node"
        return "python"

    def _default_checks(self, dirpath: Path, profile: str) -> list[str]:
        checks = ["syntax"]
        if profile == "python":
            if self._has_tests(dirpath):
                checks.append("tests")
            checks.append("lint")
            if self._has_type_config(dirpath):
                checks.append("typecheck")
            return checks

        checks = []
        package_scripts = self._read_package_scripts(dirpath)
        for check, script_names in {
            "tests": ("test",),
            "lint": ("lint",),
            "typecheck": ("typecheck", "check-types"),
        }.items():
            if any(name in package_scripts for name in script_names):
                checks.append(check)
        return checks or ["tests"]

    def _run_check(self, check: str, dirpath: Path, profile: str, timeout: int) -> CheckOutcome:
        candidates = self._candidate_commands(check, dirpath, profile)
        if not candidates:
            return CheckOutcome(check, "SKIP", details="No suitable command found.")

        attempted_not_installed = False
        for command in candidates:
            try:
                result = subprocess.run(
                    command,
                    cwd=str(dirpath),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                return CheckOutcome(check, "FAIL", " ".join(command), f"Timed out after {timeout}s.")
            except FileNotFoundError:
                attempted_not_installed = True
                continue

            combined = (result.stdout or "") + "\n" + (result.stderr or "")
            if result.returncode == 0:
                return CheckOutcome(check, "PASS", " ".join(command), self._trim_output(combined))
            if self._looks_like_missing_module(combined):
                attempted_not_installed = True
                continue
            return CheckOutcome(check, "FAIL", " ".join(command), self._trim_output(combined))

        if attempted_not_installed:
            return CheckOutcome(check, "SKIP", details="Required diagnostic command is not installed.")
        return CheckOutcome(check, "SKIP", details="No diagnostic command produced a result.")

    def _candidate_commands(self, check: str, dirpath: Path, profile: str) -> list[list[str]]:
        if profile == "python":
            return self._python_candidates(check, dirpath)
        return self._node_candidates(check, dirpath)

    def _python_candidates(self, check: str, dirpath: Path) -> list[list[str]]:
        if check == "syntax":
            return [["python", "-m", "compileall", "-q", "."]]
        if check == "tests":
            candidates = [["python", "-m", "pytest", "-q"]]
            if (dirpath / "tests").exists():
                candidates.append(["python", "-m", "unittest", "discover", "-s", "tests"])
            candidates.append(["python", "-m", "unittest", "discover"])
            return candidates
        if check == "lint":
            return [
                ["python", "-m", "ruff", "check", "."],
                ["python", "-m", "flake8", "."],
            ]
        if check == "typecheck":
            return [["python", "-m", "mypy", "."]]
        return []

    def _node_candidates(self, check: str, dirpath: Path) -> list[list[str]]:
        package_scripts = self._read_package_scripts(dirpath)
        package_runner = self._package_runner(dirpath)
        script_lookup = {
            "tests": ["test"],
            "lint": ["lint"],
            "typecheck": ["typecheck", "check-types"],
        }
        script_names = script_lookup.get(check, [])
        for script in script_names:
            if script in package_scripts:
                return [[*package_runner, script]]
        return []

    @staticmethod
    def _package_runner(dirpath: Path) -> list[str]:
        if (dirpath / "pnpm-lock.yaml").exists():
            return ["pnpm", "run"]
        if (dirpath / "yarn.lock").exists():
            return ["yarn"]
        return ["npm", "run"]

    @staticmethod
    def _read_package_scripts(dirpath: Path) -> dict:
        package_json = dirpath / "package.json"
        if not package_json.exists():
            return {}
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        scripts = data.get("scripts")
        return scripts if isinstance(scripts, dict) else {}

    @staticmethod
    def _has_tests(dirpath: Path) -> bool:
        if (dirpath / "tests").exists():
            return True
        return any(path.name.startswith("test_") or path.name.endswith("_test.py") for path in dirpath.rglob("*.py"))

    @staticmethod
    def _has_type_config(dirpath: Path) -> bool:
        return any(
            (dirpath / name).exists()
            for name in ("mypy.ini", "pyrightconfig.json", ".pyrightconfig.json")
        )

    @staticmethod
    def _looks_like_missing_module(output: str) -> bool:
        lowered = output.lower()
        markers = (
            "no module named",
            "is not recognized as an internal or external command",
            "command not found",
        )
        return any(marker in lowered for marker in markers)

    @staticmethod
    def _trim_output(output: str, limit: int = 2000) -> str:
        text = output.strip() or "(no output)"
        if len(text) > limit:
            return text[:limit] + "\n... (output truncated)"
        return text
