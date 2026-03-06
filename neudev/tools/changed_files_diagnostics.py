"""Changed-file diagnostics tool for NeuDev."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from neudev.tools.base import BaseTool, ToolError


VALID_CHECKS = {"syntax", "tests", "lint", "typecheck"}
PYTHON_EXTENSIONS = {".py"}
NODE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}


@dataclass
class CheckOutcome:
    name: str
    status: str
    files: list[str]
    command: str = ""
    details: str = ""


class ChangedFilesDiagnosticsTool(BaseTool):
    """Run targeted verification only for changed files in a git repo."""

    @property
    def name(self) -> str:
        return "changed_files_diagnostics"

    @property
    def description(self) -> str:
        return (
            "Run targeted syntax, tests, lint, and type checks only for changed files in a git repository. "
            "Useful for quick verification after edits."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Git repository directory. Defaults to the workspace root.",
                },
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": sorted(VALID_CHECKS),
                    },
                    "description": "Subset of checks to run. Defaults to smart per-language checks.",
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
        return (
            f"Run changed-file diagnostics in {args.get('directory', '.')} "
            f"with checks: {', '.join(checks)}"
        )

    def execute(self, directory: str = ".", checks: list[str] = None, timeout: int = 60, **kwargs) -> str:
        repo_dir = self.resolve_directory(directory, must_exist=True)
        if not repo_dir.is_dir():
            raise ToolError(f"Not a directory: {repo_dir}")
        if not self._is_git_repo(repo_dir):
            raise ToolError(f"Not a git repository: {repo_dir}")

        changed_files = self._collect_changed_files(repo_dir)
        if not changed_files:
            return f"Changed file diagnostics: {repo_dir}\nNo changed files."

        requested_checks = self._normalize_checks(checks)
        groups = self._group_files(changed_files)
        if not requested_checks:
            requested_checks = self._default_checks(repo_dir, groups)

        outcomes: list[CheckOutcome] = []
        for profile, files in groups.items():
            for check in requested_checks:
                outcome = self._run_profile_check(profile, check, repo_dir, files, timeout)
                if outcome is not None:
                    outcomes.append(outcome)

        passed = sum(1 for item in outcomes if item.status == "PASS")
        failed = sum(1 for item in outcomes if item.status == "FAIL")
        skipped = sum(1 for item in outcomes if item.status == "SKIP")

        lines = [
            f"Changed file diagnostics: {repo_dir}",
            f"Changed files ({len(changed_files)}):",
            *[f"- {path}" for path in changed_files],
            "",
            f"Summary: {passed} passed, {failed} failed, {skipped} skipped",
            "",
        ]

        for outcome in outcomes:
            lines.append(f"[{outcome.status}] {outcome.name}")
            lines.append(f"Files: {', '.join(outcome.files)}")
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

    def _default_checks(self, repo_dir: Path, groups: dict[str, list[str]]) -> list[str]:
        checks: list[str] = []
        if groups.get("python"):
            checks.extend(["syntax", "lint"])
            if self._python_test_targets(repo_dir, groups["python"]):
                checks.append("tests")
            if self._has_type_config(repo_dir):
                checks.append("typecheck")
        if groups.get("node"):
            package_scripts = self._read_package_scripts(repo_dir)
            if "lint" in package_scripts and "lint" not in checks:
                checks.append("lint")
            if any(name in package_scripts for name in ("typecheck", "check-types")) and "typecheck" not in checks:
                checks.append("typecheck")
            if "test" in package_scripts and "tests" not in checks:
                checks.append("tests")
        return checks or ["syntax"]

    def _group_files(self, changed_files: list[str]) -> dict[str, list[str]]:
        groups = {"python": [], "node": []}
        for path in changed_files:
            suffix = Path(path).suffix.lower()
            if suffix in PYTHON_EXTENSIONS:
                groups["python"].append(path)
            elif suffix in NODE_EXTENSIONS:
                groups["node"].append(path)
        return {name: files for name, files in groups.items() if files}

    def _run_profile_check(
        self,
        profile: str,
        check: str,
        repo_dir: Path,
        files: list[str],
        timeout: int,
    ) -> CheckOutcome | None:
        if profile == "python":
            candidates, scoped_files = self._python_candidates(repo_dir, check, files)
        else:
            candidates, scoped_files = self._node_candidates(repo_dir, check, files)

        outcome_name = f"{check} [{profile}]"
        if not scoped_files:
            return CheckOutcome(outcome_name, "SKIP", files, details="No related files were eligible for this check.")
        if not candidates:
            return CheckOutcome(outcome_name, "SKIP", scoped_files, details="No suitable command found.")

        attempted_not_installed = False
        for command in candidates:
            try:
                result = subprocess.run(
                    command,
                    cwd=str(repo_dir),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                return CheckOutcome(
                    outcome_name,
                    "FAIL",
                    scoped_files,
                    " ".join(command),
                    f"Timed out after {timeout}s.",
                )
            except FileNotFoundError:
                attempted_not_installed = True
                continue

            combined = (result.stdout or "") + "\n" + (result.stderr or "")
            if result.returncode == 0:
                return CheckOutcome(
                    outcome_name,
                    "PASS",
                    scoped_files,
                    " ".join(command),
                    self._trim_output(combined),
                )
            if self._looks_like_missing_module(combined):
                attempted_not_installed = True
                continue
            return CheckOutcome(
                outcome_name,
                "FAIL",
                scoped_files,
                " ".join(command),
                self._trim_output(combined),
            )

        if attempted_not_installed:
            return CheckOutcome(outcome_name, "SKIP", scoped_files, details="Required diagnostic command is not installed.")
        return CheckOutcome(outcome_name, "SKIP", scoped_files, details="No diagnostic command produced a result.")

    def _python_candidates(self, repo_dir: Path, check: str, files: list[str]) -> tuple[list[list[str]], list[str]]:
        if check == "syntax":
            return ([["python", "-m", "py_compile", *files]], files)
        if check == "lint":
            return (
                [
                    ["python", "-m", "ruff", "check", *files],
                    ["python", "-m", "flake8", *files],
                ],
                files,
            )
        if check == "typecheck":
            return ([["python", "-m", "mypy", *files]], files)
        if check == "tests":
            targets = self._python_test_targets(repo_dir, files)
            if not targets:
                return ([], [])
            commands = [["python", "-m", "pytest", "-q", *targets]]
            modules = [self._path_to_module(Path(path)) for path in targets]
            modules = [module for module in modules if module]
            if modules:
                commands.append(["python", "-m", "unittest", *modules])
            return (commands, targets)
        return ([], files)

    def _node_candidates(self, repo_dir: Path, check: str, files: list[str]) -> tuple[list[list[str]], list[str]]:
        package_scripts = self._read_package_scripts(repo_dir)
        runner = self._package_runner(repo_dir)
        if check == "syntax":
            return ([], [])
        if check == "lint" and "lint" in package_scripts:
            return ([self._node_script_command(runner, "lint", files)], files)
        if check == "typecheck":
            for script in ("typecheck", "check-types"):
                if script in package_scripts:
                    return ([self._node_script_command(runner, script, files)], files)
        if check == "tests" and "test" in package_scripts:
            test_files = [path for path in files if any(token in path for token in (".test.", ".spec.", "_test.", ".cy."))]
            if test_files:
                return ([self._node_script_command(runner, "test", test_files)], test_files)
        return ([], files)

    @staticmethod
    def _node_script_command(runner: list[str], script: str, files: list[str]) -> list[str]:
        if runner == ["yarn"]:
            return [*runner, script, *files]
        return [*runner, script, "--", *files]

    def _collect_changed_files(self, repo_dir: Path) -> list[str]:
        result = self._run_git(repo_dir, ["status", "--porcelain", "--untracked-files=all"])
        if result.returncode != 0:
            raise ToolError(self._trim_output(result.stderr or result.stdout))

        changed = []
        seen: set[str] = set()
        for raw_line in (result.stdout or "").splitlines():
            line = raw_line.rstrip()
            if len(line) < 4:
                continue
            path_text = line[3:].strip()
            if " -> " in path_text:
                path_text = path_text.split(" -> ", 1)[1].strip()

            path = path_text.replace("\\", "/")
            candidate = (repo_dir / path).resolve()
            if not candidate.exists() or not candidate.is_file():
                continue
            if not candidate.is_relative_to(repo_dir):
                continue
            normalized = str(candidate.relative_to(repo_dir)).replace("\\", "/")
            if normalized not in seen:
                seen.add(normalized)
                changed.append(normalized)
        return changed

    def _python_test_targets(self, repo_dir: Path, files: list[str]) -> list[str]:
        targets: list[str] = []
        seen: set[str] = set()
        for relative in files:
            path = Path(relative)
            if self._is_test_file(path):
                normalized = relative.replace("\\", "/")
                if normalized not in seen:
                    seen.add(normalized)
                    targets.append(normalized)
                continue

            stem = path.stem
            candidates = [
                Path("tests") / f"test_{stem}.py",
                Path("tests") / f"{stem}_test.py",
                path.with_name(f"test_{path.name}"),
                path.with_name(f"{stem}_test.py"),
            ]
            if path.parts and path.parts[0] == "src":
                candidates.extend([
                    Path("tests") / f"{stem}_test.py",
                    Path("tests") / f"test_{stem}.py",
                ])

            for candidate in candidates:
                full_path = (repo_dir / candidate).resolve()
                if full_path.exists() and full_path.is_file() and full_path.is_relative_to(repo_dir):
                    normalized = str(full_path.relative_to(repo_dir)).replace("\\", "/")
                    if normalized not in seen:
                        seen.add(normalized)
                        targets.append(normalized)
        return targets

    @staticmethod
    def _is_test_file(path: Path) -> bool:
        return path.name.startswith("test_") or path.stem.endswith("_test")

    @staticmethod
    def _path_to_module(path: Path) -> str | None:
        parts = list(path.with_suffix("").parts)
        if not parts:
            return None
        if not all(part.replace("_", "").isalnum() for part in parts):
            return None
        return ".".join(parts)

    @staticmethod
    def _read_package_scripts(repo_dir: Path) -> dict:
        package_json = repo_dir / "package.json"
        if not package_json.exists():
            return {}
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        scripts = data.get("scripts")
        return scripts if isinstance(scripts, dict) else {}

    @staticmethod
    def _package_runner(repo_dir: Path) -> list[str]:
        if (repo_dir / "pnpm-lock.yaml").exists():
            return ["pnpm", "run"]
        if (repo_dir / "yarn.lock").exists():
            return ["yarn"]
        return ["npm", "run"]

    @staticmethod
    def _has_type_config(repo_dir: Path) -> bool:
        return any(
            (repo_dir / name).exists()
            for name in ("mypy.ini", "pyrightconfig.json", ".pyrightconfig.json")
        )

    @staticmethod
    def _run_git(repo_dir: Path, args: list[str]):
        return subprocess.run(
            ["git", *args],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def _is_git_repo(self, repo_dir: Path) -> bool:
        result = self._run_git(repo_dir, ["rev-parse", "--is-inside-work-tree"])
        return result.returncode == 0 and (result.stdout or "").strip() == "true"

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
