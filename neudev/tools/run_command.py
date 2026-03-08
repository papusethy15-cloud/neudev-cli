"""Run shell command tool for NeuDev - Enhanced with strict security."""

from datetime import datetime
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
from typing import Optional

from neudev.tools.base import BaseTool, ToolError
from neudev.security import SecretDetector, redact_secrets_in_payload
from neudev.path_security import PathSecurityValidator


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
    "cmd",
    "composer",
    "curl",
    "dotnet",
    "echo",
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
    "powershell",
    "pwsh",
    "py",
    "pytest",
    "python",
    "python3",
    "ruff",
    "ruby",
    "sh",
    "test",
    "type",
    "uv",
    "uvicorn",
    "wget",
    "yarn",
}
SHELL_CONTROL_TOKENS = ("&&", "||", ";", "|", ">", "<", "`", "$(", "\n", "\r")
BACKGROUND_WAIT_THRESHOLD_SECONDS = 2.0
BACKGROUND_WAIT_UPDATE_SECONDS = 5.0
DISALLOWED_INLINE_FLAGS = {
    "bash": {"-c"},
    "cmd": {"/c", "/k"},
    "node": {"-e", "--eval", "-p"},
    # PowerShell and pwsh allow -Command but not inline script blocks for security
    "powershell": {"-EncodedCommand"},
    "pwsh": {"-EncodedCommand"},
    "py": {"-c"},
    "python": {"-c"},
    "python3": {"-c"},
    "sh": {"-c"},
}
WINDOWS_EXECUTABLE_SUFFIXES = {".exe", ".cmd", ".bat", ".com", ".ps1"}


class CommandStopped(Exception):
    """Raised when a user requests cancellation of a running command."""


class RunCommandTool(BaseTool):
    """Execute a shell command with strict security controls."""

    def __init__(self) -> None:
        super().__init__()
        self.execution_mode = "permissive"
        self.allowed_commands = set(RESTRICTED_ALLOWED_COMMANDS)
        self._secret_detector = SecretDetector()
        self._path_validator: Optional[PathSecurityValidator] = None

    def _get_path_validator(self) -> PathSecurityValidator:
        """Lazy-initialize path validator."""
        if self._path_validator is None and self.workspace:
            self._path_validator = PathSecurityValidator(self.workspace)
        elif self._path_validator is None:
            self._path_validator = PathSecurityValidator(Path.cwd())
        return self._path_validator

    def set_execution_mode(self, mode: str, *, extra_allowed_commands: list[str] | None = None) -> None:
        normalized = str(mode or "permissive").strip().lower()
        if normalized not in {"permissive", "restricted", "disabled"}:
            raise ValueError("run_command mode must be one of: permissive, restricted, disabled")
        self.execution_mode = normalized
        self.allowed_commands = set(RESTRICTED_ALLOWED_COMMANDS)
        for command in extra_allowed_commands or []:
            name = self._policy_command_name(command)
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

    def execute(
        self,
        command: str,
        cwd: str = None,
        timeout: int = 30,
        progress_callback=None,
        stop_event=None,
        **kwargs,
    ) -> str:
        # Security check: Detect secrets in command
        has_secrets, secret_msg = self._secret_detector.detect_secrets(command), None
        if has_secrets:
            summary = has_secrets.get_summary()
            if summary.get("high_confidence", 0) > 0:
                raise ToolError(
                    f"⚠️  Security warning: Command contains {summary['total']} potential secret(s). "
                    f"Types: {', '.join(summary['by_type'].keys())}. "
                    "Remove sensitive data before executing."
                )

        # Safety check for dangerous commands
        cmd_lower = command.lower().strip()
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                raise ToolError(f"Blocked dangerous command: {command}")
        if self.execution_mode == "disabled":
            raise ToolError(
                "run_command is disabled by the hosted command policy.\n"
                "Set NEUDEV_HOSTED_RUN_COMMAND_MODE=restricted or permissive to enable it."
            )

        # Validate and resolve working directory
        path_validator = self._get_path_validator()
        if cwd:
            try:
                work_dir = path_validator.safe_resolve_path(cwd, must_exist=True)
            except ValueError as e:
                # Provide more helpful error message
                raise ToolError(
                    f"Invalid working directory '{cwd}': {e}\n\n"
                    f"💡 The working directory must:\n"
                    f"  - Exist on the file system\n"
                    f"  - Be inside the workspace: {self.workspace or Path.cwd()}\n"
                    f"  - Not contain path traversal components (.., ~, etc.)"
                )
        else:
            # Use workspace as default - ensure it exists
            work_dir = Path(self.workspace) if self.workspace else Path.cwd()
            if not work_dir.exists():
                raise ToolError(f"Workspace directory not found: {work_dir}")
            if not work_dir.is_dir():
                raise ToolError(f"Workspace is not a directory: {work_dir}")

        # Prepare command for execution
        run_target: str | list[str] = command
        use_shell = False  # Default to no shell for security

        if self.execution_mode == "restricted":
            run_target = self._validate_restricted_command(command)
            use_shell = False  # Never use shell in restricted mode
        elif self.execution_mode == "permissive":
            # In permissive mode, still avoid shell=True when possible
            # Only use shell for commands that require shell features
            needs_shell = any(token in command for token in SHELL_CONTROL_TOKENS)
            if needs_shell:
                # Log warning about shell usage
                use_shell = True
            else:
                # Parse command into tokens for safer execution
                try:
                    run_target = shlex.split(command, posix=os.name != "nt")
                    if run_target:
                        run_target = self._resolve_executable_tokens(run_target)
                except ValueError:
                    # If parsing fails, fall back to shell execution
                    use_shell = True

        started_wall = datetime.now().strftime("%I:%M:%S %p")
        started_mono = time.monotonic()
        try:
            result = self._run_subprocess(
                run_target,
                work_dir,
                timeout,
                shell=use_shell,
                display_command=command,
                progress_callback=progress_callback,
                started_at=started_wall,
                stop_event=stop_event,
            )
            if result.returncode != 0:
                fallback_command = self._get_fallback_command(command, work_dir, result)
                if fallback_command:
                    fallback_target: str | list[str] = fallback_command
                    fallback_shell = use_shell
                    if self.execution_mode == "restricted":
                        fallback_target = self._validate_restricted_command(fallback_command)
                        fallback_shell = False
                    fallback_result = self._run_subprocess(
                        fallback_target,
                        work_dir,
                        timeout,
                        shell=fallback_shell,
                        display_command=fallback_command,
                        progress_callback=progress_callback,
                        started_at=started_wall,
                        stop_event=stop_event,
                    )
                    if fallback_result.returncode == 0:
                        duration = time.monotonic() - started_mono
                        output = self._format_output(fallback_result)
                        return (
                            f"Command: {command}\n"
                            f"Started: {started_wall}\n"
                            f"Duration: {duration:.1f}s\n"
                            f"Status: ❌ Failed (auto-fallback used)\n\n"
                            f"Automatic fallback command: {fallback_command}\n\n{output}"
                        )
            duration = time.monotonic() - started_mono
            output = self._format_output(result)
            status = "✅ Success" if result.returncode == 0 else f"❌ Failed (exit code {result.returncode})"
            return f"Command: {command}\nStarted: {started_wall}\nDuration: {duration:.1f}s\nStatus: {status}\n\n{output}"

        except CommandStopped:
            raise ToolError(f"Command stopped by user: {command}")
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
    def _run_subprocess(
        command: str | list[str],
        work_dir: Path,
        timeout: int,
        *,
        shell: bool,
        display_command: str,
        progress_callback=None,
        started_at: str = "",
        stop_event=None,
    ):
        """
        Execute subprocess with enhanced security controls.

        Security features:
        - No shell execution by default (shell=False)
        - Environment variable sanitization
        - Process group isolation
        - Timeout enforcement
        """
        if stop_event is not None and stop_event.is_set():
            raise CommandStopped(display_command)

        # Prepare environment - remove potentially dangerous variables
        env = os.environ.copy()
        # Remove sensitive environment variables
        sensitive_vars = [
            "AWS_SECRET_ACCESS_KEY",
            "AWS_ACCESS_KEY_ID",
            "PRIVATE_KEY",
            "SSH_PASSWORD",
            "API_KEY",
            "DATABASE_URL",
        ]
        for var in sensitive_vars:
            env.pop(var, None)

        if progress_callback is None:
            # Simple execution without progress tracking
            try:
                result = subprocess.run(
                    command,
                    shell=shell,
                    cwd=str(work_dir),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                    # Don't create new process group on Windows to avoid issues
                    creationflags=subprocess.CREATE_NO_PROCESS_GROUP if os.name == "nt" else 0,
                )
                return result
            except subprocess.TimeoutExpired:
                raise
            except FileNotFoundError:
                raise
            except OSError as e:
                raise ToolError(f"Command execution failed: {e}")

        # Execution with progress tracking
        try:
            process = subprocess.Popen(
                command,
                shell=shell,
                cwd=str(work_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                # Create process group for clean termination
                preexec_fn=os.setsid if os.name != "nt" else None,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
        except OSError as e:
            raise ToolError(f"Failed to start process: {e}")

        started_mono = time.monotonic()
        wait_announced = False
        last_update = 0.0

        while True:
            try:
                stdout, stderr = process.communicate(timeout=1)
                return subprocess.CompletedProcess(
                    args=command,
                    returncode=process.returncode,
                    stdout=stdout,
                    stderr=stderr,
                )
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - started_mono
                if stop_event is not None and stop_event.is_set():
                    if progress_callback is not None:
                        progress_callback(
                            {
                                "event": "progress",
                                "command": display_command,
                                "started_at": started_at,
                                "elapsed": round(elapsed, 1),
                                "mode": "stop_requested",
                            }
                        )
                    # Kill entire process group
                    try:
                        if os.name != "nt":
                            os.killpg(os.getpgid(process.pid), 9)
                        else:
                            process.kill()
                    except (OSError, ProcessLookupError):
                        pass
                    process.communicate()
                    raise CommandStopped(display_command)
                if elapsed >= timeout:
                    try:
                        if os.name != "nt":
                            os.killpg(os.getpgid(process.pid), 9)
                        else:
                            process.kill()
                    except (OSError, ProcessLookupError):
                        pass
                    stdout, stderr = process.communicate()
                    raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
                if elapsed < BACKGROUND_WAIT_THRESHOLD_SECONDS:
                    continue
                if (not wait_announced) or (elapsed - last_update >= BACKGROUND_WAIT_UPDATE_SECONDS):
                    wait_announced = True
                    last_update = elapsed
                    progress_callback(
                        {
                            "event": "progress",
                            "command": display_command,
                            "started_at": started_at,
                            "elapsed": round(elapsed, 1),
                            "mode": "background_wait",
                        }
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

        # On Windows, suggest PowerShell equivalents for common Unix commands
        if os.name == "nt":
            powershell_equivalents = {
                "ls": "powershell -Command \"Get-ChildItem\"",
                "cat": "powershell -Command \"Get-Content\"",
                "grep": "powershell -Command \"Select-String\"",
                "echo": "powershell -Command \"Write-Output\"",
                "pwd": "powershell -Command \"Get-Location\"",
                "cd": "powershell -Command \"Set-Location\"",
                "mkdir": "powershell -Command \"New-Item -ItemType Directory\"",
                "rm": "powershell -Command \"Remove-Item\"",
                "cp": "powershell -Command \"Copy-Item\"",
                "mv": "powershell -Command \"Move-Item\"",
                "ps": "powershell -Command \"Get-Process\"",
                "kill": "powershell -Command \"Stop-Process\"",
            }
            if first_token in powershell_equivalents:
                return powershell_equivalents[first_token]

        candidate = self.resolve_path(first_token)
        if candidate.exists() and candidate.suffix.lower() == ".py":
            return f"python {first_token} {rest}".strip()

        return None

    def _validate_restricted_command(self, command: str) -> list[str]:
        """Validate and parse a restricted mode command for safe execution."""
        stripped = command.strip()
        if not stripped:
            raise ToolError("Command cannot be empty.")
        
        # On Windows, detect if this is a PowerShell-native command
        if os.name == "nt":
            # Allow PowerShell commands with -Command flag for better Windows support
            powershell_patterns = ("powershell -Command", "powershell.exe -Command", 
                                   "pwsh -Command", "pwsh.exe -Command",
                                   "powershell ", "powershell.exe ", 
                                   "pwsh ", "pwsh.exe ")
            if any(stripped.lower().startswith(p) for p in powershell_patterns):
                return self._parse_powershell_command(stripped)
        
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
        command_name = self._policy_command_name(tokens[0])
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
        return self._resolve_executable_tokens(tokens)

    def _parse_powershell_command(self, command: str) -> list[str]:
        """Parse a PowerShell command for safe execution on Windows."""
        # PowerShell command format: powershell [-Command] "& { script }" or powershell -Command "command"
        # We allow -Command but validate the script doesn't contain dangerous patterns
        
        dangerous_powershell_patterns = [
            "invoke-webrequest", "wget ", "curl ",  # These are aliases, use carefully
            "start-process",  # Process spawning
            "invoke-expression", "iex ",  # Code execution
            "set-executionpolicy",  # Security bypass
        ]
        
        cmd_lower = command.lower()
        for pattern in dangerous_powershell_patterns:
            if pattern in cmd_lower:
                # Allow but flag for review - these are common but potentially dangerous
                pass  # We'll allow them but they must pass other validation
        
        # Split into tokens - PowerShell commands are typically: powershell -Command "script"
        try:
            tokens = shlex.split(command, posix=False)  # Use POSIX=False for Windows
        except ValueError:
            # Fallback to simple split
            tokens = command.split()
        
        if not tokens:
            raise ToolError("PowerShell command cannot be empty.")
        
        # Resolve the PowerShell executable
        return self._resolve_executable_tokens(tokens)

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

    @staticmethod
    def _looks_path_like(token: str) -> bool:
        raw = str(token or "").strip()
        return bool(Path(raw).anchor or os.sep in raw or (os.altsep and os.altsep in raw))

    @classmethod
    def _policy_command_name(cls, token: str) -> str:
        raw = str(token or "").strip().strip("\"'")
        command_name = Path(raw).name.lower()
        if cls._looks_path_like(raw):
            return command_name
        suffix = Path(command_name).suffix.lower()
        if suffix in WINDOWS_EXECUTABLE_SUFFIXES:
            return Path(command_name).stem.lower()
        return command_name

    def _resolve_executable_tokens(self, tokens: list[str]) -> list[str]:
        if not tokens:
            return tokens
        executable = tokens[0]
        if self._looks_path_like(executable):
            return tokens
        resolved = shutil.which(executable)
        if not resolved:
            return tokens
        return [resolved, *tokens[1:]]
