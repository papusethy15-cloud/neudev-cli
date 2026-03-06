"""Permission system for NeuDev - prompts user before destructive actions."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel


console = Console()

PERMISSION_CHOICE_DENY = "deny"
PERMISSION_CHOICE_ONCE = "once"
PERMISSION_CHOICE_TOOL = "tool"
PERMISSION_CHOICE_ALL = "all"

_PERMISSION_PROMPT = (
    "[yellow]Allow?[/yellow] [dim]([bold]y[/bold]es / [bold]n[/bold]o / "
    "[bold]a[/bold]lways for this tool / always [bold]all[/bold])[/dim]: "
)


def prompt_permission_choice(tool_name: str, message: str, *, title_prefix: str = "Permission Required") -> str:
    """Prompt for a permission decision and return the selected scope."""
    console.print()
    console.print(
        Panel(
            f"[bold]{message}[/bold]",
            title=f"[yellow]⚠️  {title_prefix}: {tool_name}[/yellow]",
            border_style="yellow",
            padding=(0, 1),
        )
    )

    while True:
        try:
            choice = console.input(_PERMISSION_PROMPT).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return PERMISSION_CHOICE_DENY

        if choice in ("y", "yes"):
            return PERMISSION_CHOICE_ONCE
        if choice in ("n", "no"):
            return PERMISSION_CHOICE_DENY
        if choice in ("a", "always"):
            return PERMISSION_CHOICE_TOOL
        if choice in ("all", "always all"):
            return PERMISSION_CHOICE_ALL

        console.print("  [yellow]Enter `y`, `n`, `a`, or `all`.[/yellow]")


class PermissionManager:
    """Manages permission prompts for destructive tool actions."""

    def __init__(self):
        self.auto_approve = False
        self._session_approvals: dict[str, bool] = {}
        self._one_time_approvals: dict[str, int] = {}

    def grant_once(self, tool_name: str) -> None:
        """Allow one upcoming execution of a tool without persisting approval."""
        self._one_time_approvals[tool_name] = self._one_time_approvals.get(tool_name, 0) + 1

    def _consume_once_approval(self, tool_name: str) -> bool:
        remaining = self._one_time_approvals.get(tool_name, 0)
        if remaining <= 0:
            return False
        if remaining == 1:
            self._one_time_approvals.pop(tool_name, None)
        else:
            self._one_time_approvals[tool_name] = remaining - 1
        return True

    def request_permission(self, tool_name: str, message: str) -> bool:
        """Ask user permission before executing a destructive tool.

        Returns True if approved, False if denied.
        """
        if self.auto_approve:
            console.print(f"  [dim]Auto-approved: {tool_name}[/dim]")
            return True

        if self._session_approvals.get(tool_name):
            console.print(f"  [dim]Previously approved: {tool_name}[/dim]")
            return True

        if self._consume_once_approval(tool_name):
            return True

        decision = prompt_permission_choice(tool_name, message)
        if decision == PERMISSION_CHOICE_ONCE:
            return True
        if decision == PERMISSION_CHOICE_TOOL:
            self._session_approvals[tool_name] = True
            console.print(f"  [green]✓ Will auto-approve '{tool_name}' for this session.[/green]")
            return True
        if decision == PERMISSION_CHOICE_ALL:
            self.auto_approve = True
            console.print("  [green]✓ Will auto-approve all actions for this session.[/green]")
            return True

        console.print("  [red]✗ Denied.[/red]")
        return False

    def reset(self) -> None:
        """Reset all approvals."""
        self.auto_approve = False
        self._session_approvals.clear()
        self._one_time_approvals.clear()
