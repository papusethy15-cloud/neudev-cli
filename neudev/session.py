"""Session tracking and summary for NeuDev."""

import copy
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


console = Console()


@dataclass
class FileBackup:
    """Backup of a file's content before modification."""
    path: str
    original_content: Optional[str]  # None if file didn't exist
    timestamp: float = field(default_factory=time.time)


@dataclass
class ActionRecord:
    """Record of an action performed during the session."""
    action: str  # "created", "modified", "deleted", "command", "read"
    target: str  # file path or command
    timestamp: float = field(default_factory=time.time)
    details: str = ""


class SessionManager:
    """Tracks all actions in a session for summaries and undo."""

    def __init__(self, workspace: str):
        self.workspace = str(Path(workspace).resolve())
        self.start_time = time.time()
        self.actions: list[ActionRecord] = []
        self.file_backups: list[FileBackup] = []
        self.test_files: list[str] = []  # Test files created during session
        self.messages_count = 0

    def record_action(self, action: str, target: str, details: str = "") -> None:
        """Record an action."""
        self.actions.append(ActionRecord(action=action, target=target, details=details))

    def backup_file(self, path: str) -> None:
        """Backup a file's content before modification."""
        filepath = self._resolve_path(path)
        content = None
        if filepath.exists():
            try:
                content = filepath.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                content = None
        self.file_backups.append(FileBackup(path=str(filepath), original_content=content))

    def track_test_file(self, path: str) -> None:
        """Track a test file for cleanup."""
        self.test_files.append(str(self._resolve_path(path)))

    def undo_last_change(self) -> Optional[str]:
        """Undo the last file change. Returns description of what was undone."""
        if not self.file_backups:
            return None

        backup = self.file_backups.pop()
        filepath = Path(backup.path)

        try:
            if backup.original_content is None:
                # File didn't exist before — delete it
                if filepath.exists():
                    filepath.unlink()
                    self.record_action("undo-delete", backup.path, "File was created, now removed")
                    return f"Removed file: {backup.path} (was newly created)"
            else:
                # Restore original content
                filepath.write_text(backup.original_content, encoding="utf-8")
                self.record_action("undo-restore", backup.path, "Content restored to original")
                return f"Restored file: {backup.path} to its original content"
        except Exception as e:
            return f"Failed to undo: {e}"

    def cleanup_test_files(self) -> list[str]:
        """Delete tracked test files. Returns list of deleted paths."""
        deleted = []
        for path in self.test_files:
            filepath = Path(path)
            if filepath.exists():
                try:
                    filepath.unlink()
                    deleted.append(path)
                except OSError:
                    pass
        self.test_files.clear()
        return deleted

    def get_summary(self) -> None:
        """Print a rich session summary."""
        duration = time.time() - self.start_time
        minutes = int(duration // 60)
        seconds = int(duration % 60)

        # Count actions by type
        created = [a for a in self.actions if a.action == "created"]
        modified = [a for a in self.actions if a.action == "modified"]
        deleted = [a for a in self.actions if a.action in ("deleted", "undo-delete")]
        commands = [a for a in self.actions if a.action == "command"]
        reads = [a for a in self.actions if a.action == "read"]

        # Build summary table
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Label", style="bold cyan")
        table.add_column("Value")

        table.add_row("⏱️  Duration", f"{minutes}m {seconds}s")
        table.add_row("💬 Messages", str(self.messages_count))
        table.add_row("📄 Files Read", str(len(reads)))
        table.add_row("✨ Files Created", str(len(created)))
        table.add_row("✏️  Files Modified", str(len(modified)))
        table.add_row("🗑️  Files Deleted", str(len(deleted)))
        table.add_row("⚡ Commands Run", str(len(commands)))

        console.print()
        console.print(Panel(table, title="[bold green]📋 Session Summary[/bold green]", border_style="green"))

        # List changed files
        changed_files = created + modified
        if changed_files:
            console.print("\n[bold]Files Changed:[/bold]")
            for a in changed_files:
                icon = "✨" if a.action == "created" else "✏️"
                console.print(f"  {icon} {a.target}")

        if commands:
            console.print("\n[bold]Commands Executed:[/bold]")
            for a in commands:
                console.print(f"  ⚡ {a.target}")

        console.print()

    def get_improvement_suggestions(self) -> list[str]:
        """Generate improvement suggestions based on session activity."""
        suggestions = []

        created_files = [a.target for a in self.actions if a.action == "created"]

        # Check for common improvements
        py_files = [f for f in created_files if f.endswith(".py")]
        if py_files and not any("test_" in f or "_test.py" in f for f in created_files):
            suggestions.append("Consider adding unit tests for the new Python files.")

        if py_files and not any("requirements" in f for f in created_files):
            if not Path(self.workspace, "requirements.txt").exists():
                suggestions.append("Consider creating a requirements.txt for dependency management.")

        if created_files and not any("README" in f.upper() for f in created_files):
            if not Path(self.workspace, "README.md").exists():
                suggestions.append("Consider adding a README.md to document the project.")

        if not any(".gitignore" in f for f in created_files):
            if not Path(self.workspace, ".gitignore").exists():
                suggestions.append("Consider adding a .gitignore file.")

        return suggestions

    def _resolve_path(self, path: str) -> Path:
        """Resolve a session path relative to the workspace."""
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = Path(self.workspace) / candidate
        return candidate.resolve()
