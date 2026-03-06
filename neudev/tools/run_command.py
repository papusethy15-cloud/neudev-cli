"""Run shell command tool for NeuDev."""

from pathlib import Path
import subprocess

from neudev.tools.base import BaseTool, ToolError


# Commands that are blocked for safety
BLOCKED_COMMANDS = {
    "rm -rf /", "rmdir /s /q c:\\", "del /f /s /q c:\\",
    "format", "mkfs",
}


class RunCommandTool(BaseTool):
    """Execute a shell command."""

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

        work_dir = self.resolve_directory(cwd, must_exist=True)
        if not work_dir.exists():
            raise ToolError(f"Working directory not found: {work_dir}")

        try:
            result = self._run_subprocess(command, work_dir, timeout)
            if result.returncode != 0:
                fallback_command = self._get_fallback_command(command, work_dir, result)
                if fallback_command:
                    fallback_result = self._run_subprocess(fallback_command, work_dir, timeout)
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
    def _run_subprocess(command: str, work_dir: Path, timeout: int):
        return subprocess.run(
            command,
            shell=True,
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
