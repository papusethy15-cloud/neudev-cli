"""Run shell command tool for NeuDev."""

import os
from pathlib import Path
import shlex
import subprocess

from neudev.tools.base import BaseTool, ToolError


# Commands that are blocked for safety
BLOCKED_COMMANDS = {
    "rm -rf /", "rmdir /s /q c:\\", "del /f /s /q c:\\",
    "format", "mkfs",
}
RESTRICTED_ALLOWED_COMMANDS = {
    "bash",
    "black",
    "bundle",
    "cargo",
    "composer",
    "dotnet",
    "flake8",
    "git",
    "go",
    "gradle",
    "java",
    "javac",
    "mvn",
    "mypy",
    "node",
    "npm",
    "npx",
    "php",
    "pip",
    "pnpm",
    "py",
    "pytest",
    "python",
    "python3",
    "ruff",
    "ruby",
    "sh",
    "uv",
    "uvicorn",
    "yarn",
}
SHELL_CONTROL_TOKENS = ("&&", "||", ";", "|", ">", "<", "`", "$(", "\n", "\r")
DISALLOWED_INLINE_FLAGS = {
    "bash": {"-c"},
    "cmd": {"/c", "/k"},
    "node": {"-e", "--eval", "-p"},
    "powershell": {"-c", "-command", "-encodedcommand"},
    "pwsh": {"-c", "-command", "-encodedcommand"},
    "py": {"-c"},
    "python": {"-c"},
    "python3": {"-c"},
    "sh": {"-c"},
}


class RunCommandTool(BaseTool):
    """Execute a shell command."""

    def __init__(self) -> None:
        super().__init__()
        self.execution_mode = "permissive"
        self.allowed_commands = set(RESTRICTED_ALLOWED_COMMANDS)

    def set_execution_mode(self, mode: str, *, extra_allowed_commands: list[str] | None = None) -> None:
        normalized = str(mode or "permissive").strip().lower()
        if normalized not in {"permissive", "restricted", "disabled"}:
            raise ValueError("run_command mode must be one of: permissive, restricted, disabled")
        self.execution_mode = normalized
        self.allowed_commands = set(RESTRICTED_ALLOWED_COMMANDS)
        for command in extra_allowed_commands or []:
            name = command.strip().lower()
            if name:
                self.allowed_commands.add(name)

    @property
    def name(self) -> str:
        return "run_command"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return its output. Use this to run "
            "build commands, install dependencies, run tests, or any other "
            "shell operation. Commands run in the workspace directory."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the command. Defaults to workspace.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds. Default 30.",
                },
            },
            "required": ["command"],
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        cmd = args.get("command", "unknown")
        cwd = args.get("cwd", ".")
        return f"Run command: {cmd}\n  Directory: {cwd}"

    def execute(self, command: str, cwd: str = None, timeout: int = 30, **kwargs) -> str:
        # Safety check
        cmd_lower = command.lower().strip()
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                raise ToolError(f"Blocked dangerous command: {command}")
        if self.execution_mode == "disabled":
            raise ToolError(
                "run_command is disabled by the hosted command policy.\n"
                "Set NEUDEV_HOSTED_RUN_COMMAND_MODE=restricted or permissive to enable it."
            )

        work_dir = self.resolve_directory(cwd, must_exist=True)
        if not work_dir.exists():
            raise ToolError(f"Working directory not found: {work_dir}")

        run_target: str | list[str] = command
        use_shell = True
        if self.execution_mode == "restricted":
            run_target = self._validate_restricted_command(command)
            use_shell = False

        try:
            result = self._run_subprocess(run_target, work_dir, timeout, shell=use_shell)
            if result.returncode != 0:
                fallback_command = self._get_fallback_command(command, work_dir, result)
                if fallback_command:
                    fallback_target: str | list[str] = fallback_command
                    fallback_shell = use_shell
                    if self.execution_mode == "restricted":
                        fallback_target = self._validate_restricted_command(fallback_command)
                        fallback_shell = False
                    fallback_result = self._run_subprocess(fallback_target, work_dir, timeout, shell=fallback_shell)
                    if fallback_result.returncode == 0:
                        output = self._format_output(fallback_result)
                        return (
                            f"Command: {command}\n"
                            f"Status: ❌ Failed (auto-fallback used)\n\n"
                            f"Automatic fallback command: {fallback_command}\n\n{output}"
                        )
            output = self._format_output(result)
            status = "✅ Success" if result.returncode == 0 else f"❌ Failed (exit code {result.returncode})"
            return f"Command: {command}\nStatus: {status}\n\n{output}"

        except subprocess.TimeoutExpired:
            raise ToolError(
                f"Command timed out after {timeout}s: {command}\n"
                f"Try increasing the timeout or breaking the command into smaller steps."
            )
        except FileNotFoundError:
            raise ToolError(
                f"Command not found: {command}\n"
                f"Make sure the command is installed and in PATH."
            )
        except Exception as e:
            raise ToolError(f"Command execution failed: {type(e).__name__}: {e}")

    @staticmethod
    def _run_subprocess(command: str | list[str], work_dir: Path, timeout: int, *, shell: bool):
        return subprocess.run(
            command,
            shell=shell,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=None,
        )

    @staticmethod
    def _format_output(result) -> str:
        output_parts = []
        if result.stdout:
            output_parts.append(f"STDOUT:\n{result.stdout.strip()}")
        if result.stderr:
            output_parts.append(f"STDERR:\n{result.stderr.strip()}")

        output = "\n\n".join(output_parts) if output_parts else "(no output)"
        if len(output) > 5000:
            output = output[:5000] + "\n... (output truncated)"
        return output

    def _get_fallback_command(self, command: str, work_dir: Path, result) -> str | None:
        stderr = (result.stderr or "").lower()
        stdout = (result.stdout or "").lower()
        combined = stderr + "\n" + stdout
        not_found_markers = (
            "is not recognized as an internal or external command",
            "command not found",
            "no such file or directory",
        )
        if not any(marker in combined for marker in not_found_markers):
            return None

        stripped = command.strip()
        first_token = stripped.split()[0] if stripped.split() else ""
        rest = stripped[len(first_token) :].strip()

        module_fallbacks = {
            "pytest": "python -m pytest",
            "pip": "python -m pip",
            "ruff": "python -m ruff",
            "black": "python -m black",
            "mypy": "python -m mypy",
            "uvicorn": "python -m uvicorn",
        }
        if first_token in module_fallbacks:
            return f"{module_fallbacks[first_token]} {rest}".strip()

        candidate = self.resolve_path(first_token)
        if candidate.exists() and candidate.suffix.lower() == ".py":
            return f"python {first_token} {rest}".strip()

        return None

    def _validate_restricted_command(self, command: str) -> list[str]:
        stripped = command.strip()
        if not stripped:
            raise ToolError("Command cannot be empty.")
        if any(token in stripped for token in SHELL_CONTROL_TOKENS):
            raise ToolError(
                "Hosted command policy blocks shell operators such as pipes, redirects, chaining, and inline scripts."
            )

        try:
            tokens = shlex.split(stripped, posix=os.name != "nt")
        except ValueError as exc:
            raise ToolError(f"Command could not be parsed safely: {exc}") from exc
        if not tokens:
            raise ToolError("Command cannot be empty.")

        tokens = self._normalize_script_tokens(tokens)
        command_name = Path(tokens[0]).name.lower()
        if command_name not in self.allowed_commands:
            raise ToolError(
                f"Hosted command policy blocks '{tokens[0]}'.\n"
                f"Allowed command prefixes: {', '.join(sorted(self.allowed_commands))}"
            )

        disallowed_flags = DISALLOWED_INLINE_FLAGS.get(command_name, set())
        if any(token.lower() in disallowed_flags for token in tokens[1:]):
            raise ToolError(
                f"Hosted command policy blocks inline execution flags for '{tokens[0]}'. "
                "Use checked-in scripts or module commands instead."
            )
        return tokens

    def _normalize_script_tokens(self, tokens: list[str]) -> list[str]:
        first_token = tokens[0]
        try:
            candidate = self.resolve_path(first_token, must_exist=True)
        except ToolError:
            return tokens
        if not candidate.exists() or not candidate.is_file():
            return tokens
        suffix = candidate.suffix.lower()
        if suffix == ".py":
            return ["python", first_token, *tokens[1:]]
        if suffix == ".sh":
            return ["bash", first_token, *tokens[1:]]
        return tokens
