"""Run shell command tool for NeuDev."""

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
            # Use shell=True on Windows for proper command execution
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=None,
            )

            output_parts = []
            if result.stdout:
                output_parts.append(f"STDOUT:\n{result.stdout.strip()}")
            if result.stderr:
                output_parts.append(f"STDERR:\n{result.stderr.strip()}")

            output = "\n\n".join(output_parts) if output_parts else "(no output)"

            status = "✅ Success" if result.returncode == 0 else f"❌ Failed (exit code {result.returncode})"

            # Truncate very long output
            if len(output) > 5000:
                output = output[:5000] + "\n... (output truncated)"

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
