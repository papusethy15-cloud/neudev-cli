"""Enhanced CLI UI with advanced visualization for NeuDev."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.text import Text

console = Console()


@dataclass
class TodoItem:
    """Represents a todo item in the agent's plan."""
    text: str
    status: str  # pending, in_progress, completed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class ToolActivity:
    """Represents a tool execution activity."""
    tool_name: str
    target: str
    status: str  # running, success, error
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration: float = 0.0


@dataclass
class EnhancedTraceState:
    """Enhanced state tracking for live UI updates."""
    current_phase: str = "UNDERSTAND"
    current_model: str = ""
    current_tool: Optional[str] = None
    current_target: str = ""
    current_detail: str = ""
    waiting_for_model: bool = False
    start_time: datetime = field(default_factory=datetime.now)
    tool_activities: list[ToolActivity] = field(default_factory=list)
    todo_items: list[TodoItem] = field(default_factory=list)
    latest_thinking: str = ""
    latest_response: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)
    
    # Counters
    total_tools_called: int = 0
    successful_tools: int = 0
    failed_tools: int = 0
    
    # Compatibility with old ExecutionTraceState
    phases: list = field(default_factory=list)
    tool_counts: dict = field(default_factory=dict)
    plan_completed: int = 0
    plan_total: int = 0
    active_plan_item: str = ""
    custom_fields: dict = field(default_factory=dict)
    
    def elapsed_seconds(self) -> float:
        """Get elapsed time since start."""
        return (datetime.now() - self.start_time).total_seconds()


# Phase configuration with icons and colors
PHASE_CONFIG = {
    "UNDERSTAND": {"icon": "🔍", "color": "cyan", "label": "Understanding"},
    "PLAN": {"icon": "📋", "color": "yellow", "label": "Planning"},
    "PRECHECK": {"icon": "🔎", "color": "blue", "label": "Pre-check"},
    "EXECUTE": {"icon": "⚡", "color": "green", "label": "Executing"},
    "REVIEW": {"icon": "📝", "color": "magenta", "label": "Reviewing"},
    "VERIFY": {"icon": "✅", "color": "green", "label": "Verifying"},
}

# Tool type icons and colors
TOOL_CONFIG = {
    "read_file": {"icon": "📖", "color": "cyan", "label": "READ"},
    "write_file": {"icon": "✏️", "color": "yellow", "label": "WRITE"},
    "edit_file": {"icon": "🔧", "color": "yellow", "label": "EDIT"},
    "smart_edit_file": {"icon": "🔧", "color": "yellow", "label": "SMART EDIT"},
    "list_directory": {"icon": "📂", "color": "cyan", "label": "SCAN"},
    "grep_search": {"icon": "🔍", "color": "blue", "label": "SEARCH"},
    "symbol_search": {"icon": "🔍", "color": "blue", "label": "SYMBOL"},
    "run_command": {"icon": "⚙️", "color": "magenta", "label": "RUN"},
    "project_init": {"icon": "🏗️", "color": "green", "label": "SCAFFOLD"},
    "diagnostics": {"icon": "🏥", "color": "green", "label": "DIAGNOSE"},
    "changed_files_diagnostics": {"icon": "🏥", "color": "green", "label": "CHECK"},
    "web_search": {"icon": "🌐", "color": "blue", "label": "WEB SEARCH"},
    "delete_file": {"icon": "🗑️", "color": "red", "label": "DELETE"},
}


def get_todo_status_icon(status: str) -> str:
    """Get icon for todo item status."""
    icons = {
        "pending": "⚪",
        "in_progress": "🔄",
        "completed": "✅",
    }
    return icons.get(status, "⚪")


def get_todo_status_style(status: str) -> str:
    """Get style for todo item status."""
    styles = {
        "pending": "dim",
        "in_progress": "bold yellow",
        "completed": "green",
    }
    return styles.get(status, "dim")


def build_enhanced_todo_panel(trace: EnhancedTraceState) -> Panel:
    """Build enhanced todo list panel."""
    if not trace.todo_items:
        return Panel(
            "[dim]No todo items - executing single task[/dim]",
            title="[bold]📋 Task List[/bold]",
            border_style="dim",
            padding=(0, 1),
        )
    
    table = Table.grid(padding=(0, 1))
    table.add_column("Status", width=3)
    table.add_column("Task", ratio=1)
    
    for item in trace.todo_items:
        icon = get_todo_status_icon(item.status)
        style = get_todo_status_style(item.status)
        table.add_row(
            f"[{style}]{icon}[/{style}]",
            f"[{style}]{item.text}[/{style}]",
        )
    
    completed = sum(1 for item in trace.todo_items if item.status == "completed")
    total = len(trace.todo_items)
    progress_pct = int((completed / total) * 100) if total > 0 else 0
    
    return Panel(
        table,
        title=f"[bold]📋 Task List[/bold] [green]{completed}/{total}[/green] ({progress_pct}%)",
        border_style="green" if completed == total else "yellow",
        padding=(0, 1),
    )


def build_enhanced_tool_activity_panel(trace: EnhancedTraceState) -> Panel:
    """Build enhanced tool activity panel."""
    if not trace.tool_activities:
        return Panel(
            "[dim]No tool activity yet[/dim]",
            title="[bold]🛠️ Tool Activity[/bold]",
            border_style="dim",
            padding=(0, 1),
        )
    
    # Show last 8 activities
    recent = trace.tool_activities[-8:]
    
    table = Table.grid(padding=(0, 1))
    table.add_column("Icon", width=3)
    table.add_column("Tool", width=15)
    table.add_column("Target", ratio=1)
    table.add_column("Time", width=10, justify="right")
    
    for activity in recent:
        config = TOOL_CONFIG.get(activity.tool_name, {"icon": "🔧", "color": "white", "label": activity.tool_name.upper()})
        
        if activity.status == "running":
            status_icon = "🔄"
            time_text = f"[yellow]{activity.duration:.1f}s[/yellow]"
        elif activity.status == "success":
            status_icon = "✅"
            time_text = f"[green]{activity.duration:.1f}s[/green]"
        else:  # error
            status_icon = "❌"
            time_text = f"[red]{activity.duration:.1f}s[/red]"
        
        target = activity.target[:40] + "..." if len(activity.target) > 40 else activity.target
        table.add_row(
            f"{status_icon}",
            f"[{config['color']}]{config['label']}[/{config['color']}]",
            f"[white]{target}[/white]",
            time_text,
        )
    
    stats = f"[green]✓ {trace.successful_tools}[/green]  [red]✗ {trace.failed_tools}[/red]"
    
    return Panel(
        table,
        title=f"[bold]🛠️ Tool Activity[/bold]  {stats}",
        border_style="green" if trace.failed_tools == 0 else "yellow",
        padding=(0, 1),
    )


def build_enhanced_thinking_panel(trace: EnhancedTraceState) -> Panel:
    """Build enhanced thinking/reasoning panel."""
    if not trace.latest_thinking:
        if trace.waiting_for_model:
            return Panel(
                "[dim italic]Waiting for model to think about next step...[/dim italic]",
                title="[bold]💭 Model Thinking[/bold]",
                border_style="blue",
                padding=(0, 1),
            )
        return Panel(
            "[dim]No reasoning to display[/dim]",
            title="[bold]💭 Model Thinking[/bold]",
            border_style="dim",
            padding=(0, 1),
        )
    
    # Format thinking text with better readability
    thinking_text = trace.latest_thinking
    if len(thinking_text) > 500:
        thinking_text = thinking_text[:500] + "..."
    
    return Panel(
        f"[dim italic]{thinking_text}[/dim italic]",
        title="[bold]💭 Model Thinking[/bold]",
        border_style="blue",
        padding=(0, 1),
    )


def build_enhanced_status_panel(trace: EnhancedTraceState) -> Panel:
    """Build enhanced main status panel."""
    with trace.lock:
        elapsed = trace.elapsed_seconds()
        config = PHASE_CONFIG.get(trace.current_phase, {"icon": "🔧", "color": "white", "label": trace.current_phase})
        
        # Build header
        header = Text()
        header.append(f"{config['icon']} ", style="bold")
        header.append(f"{config['label']} ", style=f"bold {config['color']}")
        header.append(f"| Model: [cyan]{trace.current_model or 'auto'}[/cyan]", style="dim")
        
        # Build content lines
        lines = [header]
        
        # Current activity
        if trace.current_target:
            tool_config = TOOL_CONFIG.get(trace.current_tool or "", {"icon": "🔧", "color": "white"})
            activity_text = Text()
            activity_text.append(f"{tool_config['icon']} ", style="bold")
            activity_text.append(f"[bold white]{trace.current_target}[/bold white]")
            lines.append(activity_text)
        elif trace.current_detail:
            lines.append(Text(f"[dim]{trace.current_detail}[/dim]"))
        
        # Progress info
        progress_parts = [f"[dim]⏱️ {elapsed:.1f}s elapsed[/dim]"]
        if trace.total_tools_called > 0:
            progress_parts.append(f"[dim]🛠️ {trace.total_tools_called} tools called[/dim]")
        lines.append(Text(" | ".join(progress_parts)))
        
        # Model waiting status
        if trace.waiting_for_model:
            lines.append(Text("[dim italic]💭 Model is thinking about next step...[/dim italic]"))
        
        content = Text("\n").join(lines)
        
        return Panel(
            content,
            title=f"[bold {config['color']}]⚡ NeuDev Agent[/bold {config['color']}]",
            border_style=config['color'],
            padding=(0, 1),
            width=min(console.width, 100),
        )


def build_enhanced_full_dashboard(trace: EnhancedTraceState) -> list:
    """Build complete enhanced dashboard with all panels."""
    panels = []
    
    # Main status panel (always shown)
    panels.append(build_enhanced_status_panel(trace))
    
    # Todo list (shown when available)
    if trace.todo_items:
        panels.append(build_enhanced_todo_panel(trace))
    
    # Tool activity (shown when tools have been called)
    if trace.tool_activities:
        panels.append(build_enhanced_tool_activity_panel(trace))
    
    # Thinking panel (shown when model is thinking)
    if trace.latest_thinking or trace.waiting_for_model:
        panels.append(build_enhanced_thinking_panel(trace))
    
    return panels


def run_enhanced_live_dashboard(trace: EnhancedTraceState, runner) -> None:
    """Run enhanced live dashboard during agent execution."""
    stop_event = threading.Event()
    last_update_time = 0
    last_dashboard_hash = ""

    def refresh_loop(live: Live) -> None:
        nonlocal last_update_time, last_dashboard_hash
        while not stop_event.is_set():
            # Throttle updates to 4 FPS to prevent terminal blinking
            current_time = time.time()
            if current_time - last_update_time < 0.25:  # 250ms minimum between updates
                stop_event.wait(0.05)
                continue
            
            dashboard = build_enhanced_full_dashboard(trace)
            # Only update if content changed (prevents flickering)
            dashboard_str = str(dashboard)
            if dashboard_str != last_dashboard_hash:
                from rich.console import Group
                live.update(Group(*dashboard), refresh=True)
                last_dashboard_hash = dashboard_str
                last_update_time = current_time
            stop_event.wait(0.05)

    dashboard = build_enhanced_full_dashboard(trace)
    from rich.console import Group
    # Use redirect_stdout=False to prevent conflicts with other output
    with Live(
        Group(*dashboard),
        console=console,
        refresh_per_second=4,  # Reduced from 7 to 4 FPS
        transient=True,
        redirect_stdout=False,
        redirect_stderr=False,
    ) as live:
        worker = threading.Thread(target=refresh_loop, args=(live,), daemon=True)
        worker.start()
        try:
            runner()
        finally:
            stop_event.set()
            worker.join(timeout=1)


def update_trace_from_plan_update(trace: EnhancedTraceState, plan_items: list, conventions: list) -> None:
    """Update trace state from plan update callback."""
    with trace.lock:
        trace.todo_items = []
        for item in plan_items:
            if isinstance(item, dict):
                trace.todo_items.append(TodoItem(
                    text=item.get("text", str(item)),
                    status=item.get("status", "pending"),
                ))
            else:
                trace.todo_items.append(TodoItem(text=str(item), status="pending"))


def update_trace_from_tool_start(trace: EnhancedTraceState, tool_name: str, target: str) -> None:
    """Update trace state when tool starts."""
    with trace.lock:
        activity = ToolActivity(
            tool_name=tool_name,
            target=target,
            status="running",
            started_at=datetime.now(),
        )
        trace.tool_activities.append(activity)
        trace.current_tool = tool_name
        trace.current_target = target
        trace.waiting_for_model = False


def update_trace_from_tool_done(trace: EnhancedTraceState, tool_name: str, success: bool, duration: float) -> None:
    """Update trace state when tool completes."""
    with trace.lock:
        # Find and update the running activity for this tool
        for activity in reversed(trace.tool_activities):
            if activity.tool_name == tool_name and activity.status == "running":
                activity.status = "success" if success else "error"
                activity.completed_at = datetime.now()
                activity.duration = duration
                break
        
        trace.total_tools_called += 1
        if success:
            trace.successful_tools += 1
        else:
            trace.failed_tools += 1
        
        # Update todo progress if tool succeeded
        if success and trace.todo_items:
            for item in reversed(trace.todo_items):
                if item.status == "in_progress":
                    item.status = "completed"
                    item.completed_at = datetime.now()
                    break
            
            # Mark next pending item as in_progress
            for item in trace.todo_items:
                if item.status == "pending":
                    item.status = "in_progress"
                    item.started_at = datetime.now()
                    break


def update_trace_from_thinking(trace: EnhancedTraceState, text: str) -> None:
    """Update trace state with model thinking."""
    with trace.lock:
        lines = [line.strip() for line in str(text).splitlines() if line.strip()]
        snippet = " ".join(lines[:3]) if lines else str(text).strip()
        # Truncate for display
        if len(snippet) > 200:
            snippet = snippet[:200] + "..."
        trace.latest_thinking = snippet
