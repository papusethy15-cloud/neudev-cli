"""Permission system for NeuDev - prompts user before destructive actions."""

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm


console = Console()


class PermissionManager:
    """Manages permission prompts for destructive tool actions."""

    def __init__(self):
        self.auto_approve = False
        self._session_approvals: dict[str, bool] = {}

    def request_permission(self, tool_name: str, message: str) -> bool:
        """Ask user permission before executing a destructive tool.

        Returns True if approved, False if denied.
        """
        if self.auto_approve:
            console.print(f"  [dim]Auto-approved: {tool_name}[/dim]")
            return True

        # Check if we already have a blanket approval for this tool
        if self._session_approvals.get(tool_name):
            console.print(f"  [dim]Previously approved: {tool_name}[/dim]")
            return True

        console.print()
        console.print(
            Panel(
                f"[bold]{message}[/bold]",
                title=f"[yellow]⚠️  Permission Required: {tool_name}[/yellow]",
                border_style="yellow",
                padding=(0, 1),
            )
        )

        try:
            choice = console.input(
                "[yellow]Allow?[/yellow] [dim]([bold]y[/bold]es / [bold]n[/bold]o / "
                "[bold]a[/bold]lways for this tool / always [bold]all[/bold])[/dim]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("[red]  Denied.[/red]")
            return False

        if choice in ("y", "yes"):
            return True
        elif choice in ("a", "always"):
            self._session_approvals[tool_name] = True
            console.print(f"  [green]✓ Will auto-approve '{tool_name}' for this session.[/green]")
            return True
        elif choice in ("all",):
            self.auto_approve = True
            console.print("  [green]✓ Will auto-approve all actions for this session.[/green]")
            return True
        else:
            console.print("  [red]✗ Denied.[/red]")
            return False

    def reset(self) -> None:
        """Reset all approvals."""
        self.auto_approve = False
        self._session_approvals.clear()
