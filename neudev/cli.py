"""Interactive CLI for local and hosted NeuDev runtimes."""

from __future__ import annotations

import argparse
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style as PTStyle
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from neudev import __app_name__, __version__
from neudev.agent import Agent
from neudev.config import CONFIG_DIR, CONFIG_FILE, HISTORY_FILE, VALID_COMMAND_POLICIES, NeuDevConfig
from neudev.hosted_llm import HostedLLMClient
from neudev.llm import ConnectionError as OllamaConnectionError
from neudev.llm import LLMError, ModelNotFoundError
from neudev.permissions import (
    PERMISSION_CHOICE_ALL,
    PERMISSION_CHOICE_DENY,
    PERMISSION_CHOICE_ONCE,
    PERMISSION_CHOICE_TOOL,
    PermissionManager,
    normalize_permission_choice,
    prompt_permission_choice,
)
from neudev.remote_api import RemoteAPIError, RemoteNeuDevClient, RemoteSessionClient
from neudev.server import serve_api
from neudev.tools.run_command import RunCommandTool


THEME = Theme(
    {
        "info": "bold cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "tool": "bold magenta",
        "dim": "dim white",
        "accent": "bold bright_blue",
        "highlight": "bold bright_yellow",
        "muted": "grey62",
    }
)

console = Console(theme=THEME)
LIGHTNING_ENV_KEYS = (
    "LIGHTNING_CLUSTER_ID",
    "LIGHTNING_CLOUD_PROJECT_ID",
    "LIGHTNING_CLOUD_SPACE_ID",
    "LIGHTNING_CLOUD_APP_ID",
)
TOOL_ACTIVITY_META = {
    "read_file": ("READ", "info"),
    "read_files_batch": ("READ", "info"),
    "search_files": ("SEARCH", "accent"),
    "grep_search": ("SEARCH", "accent"),
    "symbol_search": ("SEARCH", "accent"),
    "list_directory": ("SCAN", "info"),
    "file_outline": ("SCAN", "info"),
    "git_diff_review": ("REVIEW", "accent"),
    "write_file": ("WRITE", "warning"),
    "edit_file": ("EDIT", "warning"),
    "smart_edit_file": ("EDIT", "warning"),
    "python_ast_edit": ("PATCH", "warning"),
    "js_ts_symbol_edit": ("PATCH", "warning"),
    "delete_file": ("DELETE", "error"),
    "run_command": ("RUN", "tool"),
    "changed_files_diagnostics": ("VERIFY", "success"),
}
SLASH_COMMANDS = [
    "/help",
    "/models",
    "/sessions",
    "/clear",
    "/remove",
    "/history",
    "/close",
    "/exit",
    "/quit",
    "/version",
    "/config",
    "/thinking",
    "/language",
    "/agents",
    "/approve",
    "/deny",
    "/queue",
    "/stop",
    "/explain",
    "/refactor",
    "/test",
    "/commit",
    "/summarize",
]


def print_banner(config: NeuDevConfig, workspace: str, *, runtime_label: str) -> None:
    """Print a startup banner."""
    ws_name = Path(workspace).name or workspace
    now = datetime.now().strftime("%I:%M %p")

    title = Text()
    title.append("  ⚡ ", style="bold bright_yellow")
    title.append("N", style="bold bright_cyan")
    title.append("eu", style="bold white")
    title.append("D", style="bold bright_cyan")
    title.append("ev", style="bold white")

    info = Text()
    info.append("\n")
    info.append("  🧭 Runtime   ", style="muted")
    info.append(f"{runtime_label}\n", style="bold bright_yellow")
    info.append("  🤖 Model     ", style="muted")
    info.append(f"{config.model}\n", style="bold bright_cyan")
    info.append("  📂 Workspace  ", style="muted")
    info.append(f"{ws_name}\n", style="bold bright_green")
    info.append("  🕐 Started    ", style="muted")
    info.append(f"{now}\n", style="dim")
    info.append("\n")
    info.append("  💡 ", style="")
    info.append("Type ", style="dim")
    info.append("/help", style="bold bright_yellow")
    info.append(" for commands", style="dim")

    console.print()
    console.print(
        Panel(
            info,
            title=title,
            subtitle=Text("AI Coding Agent", style="dim italic"),
            border_style="bright_blue",
            padding=(0, 2),
            expand=False,
            width=min(console.width, 62),
        )
    )
    console.print()


def print_status_block(items: list[tuple[str, str, str]]) -> None:
    """Print a compact status block."""
    for icon, label, style in items:
        console.print(f"  {icon}  {label}", style=style)
    console.print()


def _truncate_cli_value(value: str, limit: int = 88) -> str:
    """Normalize CLI text to one line and cap the visible width."""
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def is_lightning_workspace(workspace: str | None) -> bool:
    """Return True when the workspace looks like a Lightning Studio mount."""
    if any(os.environ.get(key) for key in LIGHTNING_ENV_KEYS):
        return True
    if not workspace:
        return False
    normalized = str(workspace).replace("\\", "/").lower()
    return "/teamspace/studios/" in normalized


def resolve_local_command_policy(
    config: NeuDevConfig,
    runtime_mode: str,
    workspace: str | None,
) -> tuple[str, str]:
    """Resolve the effective local run_command policy and explain why."""
    configured = (config.command_policy or "auto").strip().lower()
    if configured != "auto":
        return configured, "explicit"
    if runtime_mode == "hybrid":
        return "restricted", "hybrid default"
    if is_lightning_workspace(workspace):
        return "restricted", "Lightning workspace default"
    return "permissive", "local default"


def format_command_policy_display(config: NeuDevConfig, effective_policy: str, reason: str) -> str:
    """Format the configured and effective policy for UI display."""
    configured = (config.command_policy or "auto").strip().lower()
    if configured == "auto":
        return f"auto -> {effective_policy} ({reason})"
    if configured == effective_policy:
        return effective_policy
    return f"{effective_policy} ({reason})"


def apply_agent_command_policy(agent: Agent, config: NeuDevConfig, runtime_mode: str) -> tuple[str, str]:
    """Apply the effective run_command policy for local or hybrid execution."""
    effective_policy, reason = resolve_local_command_policy(config, runtime_mode, agent.workspace)
    run_command = agent.tool_registry.get("run_command")
    if isinstance(run_command, RunCommandTool):
        extra_commands = [
            item.strip()
            for item in os.environ.get("NEUDEV_LOCAL_RUN_COMMAND_ALLOWLIST", "").split(",")
            if item.strip()
        ]
        run_command.set_execution_mode(effective_policy, extra_allowed_commands=extra_commands)
    display = format_command_policy_display(config, effective_policy, reason)
    setattr(agent, "_command_policy_mode", effective_policy)
    setattr(agent, "_command_policy_reason", reason)
    setattr(agent, "_command_policy_display", display)
    return effective_policy, display


def render_turn_header(request: str, *, title: str, metadata: list[tuple[str, str]]) -> None:
    """Render a compact execution header for the upcoming turn."""
    lines = [f"[muted]{label:<16}[/muted] [white]{value}[/white]" for label, value in metadata if value]
    lines.extend(
        [
            "",
            "[bold white]Request[/bold white]",
            f"[white]{_truncate_cli_value(request, limit=max(96, min(console.width * 2, 200)))}[/white]",
        ]
    )
    console.print(
        Panel(
            "\n".join(lines),
            border_style="bright_blue",
            title=f"[bold bright_cyan]{title}[/bold bright_cyan]",
            padding=(0, 1),
            expand=False,
            width=min(console.width, 96),
        )
    )
    console.print()


@dataclass
class ExecutionTraceState:
    """Capture a user-facing summary of what happened during a turn."""

    started_monotonic: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    phases: list[tuple[str, str]] = field(default_factory=list)
    tool_counts: dict[str, int] = field(default_factory=dict)
    touched_targets: list[str] = field(default_factory=list)
    changed_targets: list[str] = field(default_factory=list)
    workspace_delta_counts: dict[str, int] = field(
        default_factory=lambda: {"modified": 0, "created": 0, "deleted": 0}
    )
    plan_total: int = 0
    plan_completed: int = 0
    active_plan_item: str = ""
    current_phase: str = "understand"
    current_model: str = ""
    current_detail: str = "Preparing execution trace."
    current_target: str = ""
    current_tool: str = ""
    latest_thinking: str = ""
    latest_response: str = ""
    waiting_for_model: bool = False
    plan_panel_rendered: bool = False
    last_plan_signature: tuple = field(default_factory=tuple)
    last_plan_active_item: str = ""
    last_plan_completed: int = 0

    def elapsed_seconds(self) -> float:
        """Return the turn duration."""
        return round(time.monotonic() - self.started_monotonic, 1)


def _phase_label(phase: str) -> str:
    """Normalize phase labels for UI display."""
    return {
        "understand": "UNDERSTAND",
        "planner": "PLAN",
        "reviewer-pre": "PRECHECK",
        "executor": "EXECUTE",
        "reviewer": "REVIEW",
        "verify": "VERIFY",
    }.get(str(phase or "").strip().lower(), str(phase or "step").upper())


def _tool_activity_verb(activity_label: str) -> str:
    """Return a readable verb for a compact tool activity label."""
    return {
        "READ": "Inspecting",
        "SEARCH": "Searching",
        "SCAN": "Scanning",
        "REVIEW": "Reviewing",
        "WRITE": "Writing",
        "EDIT": "Editing",
        "PATCH": "Patching",
        "DELETE": "Deleting",
        "RUN": "Running",
        "VERIFY": "Verifying",
        "TOOL": "Using",
    }.get(activity_label, "Using")


def _append_unique(items: list[str], value: str, *, limit: int = 6) -> None:
    """Keep a short unique list in insertion order."""
    cleaned = str(value or "").strip()
    if not cleaned or cleaned in items:
        return
    items.append(cleaned)
    if len(items) > limit:
        del items[limit:]


def _record_trace_phase(trace: ExecutionTraceState | None, phase: str, model_name: str) -> int:
    """Store a phase transition and return its display step number."""
    if trace is None:
        return 1
    with trace.lock:
        trace.phases.append((str(phase or "").strip().lower(), model_name or ""))
        trace.current_phase = str(phase or "").strip().lower() or trace.current_phase
        trace.current_model = model_name or trace.current_model
        trace.waiting_for_model = False
        return len(trace.phases)


def _record_trace_plan(trace: ExecutionTraceState | None, plan_update: dict | None) -> None:
    """Store the latest plan progress snapshot."""
    if trace is None or not plan_update:
        return
    with trace.lock:
        plan_items = plan_update.get("plan") or []
        trace.plan_total = len(plan_items)
        trace.plan_completed = sum(1 for item in plan_items if item.get("status") == "completed")
        active = next((item.get("text", "") for item in plan_items if item.get("status") == "in_progress"), "")
        trace.active_plan_item = str(active or "").strip()


def _record_trace_workspace_change(trace: ExecutionTraceState | None, changes: dict | None) -> None:
    """Store detected workspace deltas for the turn summary."""
    if trace is None or not changes:
        return
    with trace.lock:
        for label in ("modified", "created", "deleted"):
            trace.workspace_delta_counts[label] += len(changes.get(label) or [])


def _record_trace_tool_event(trace: ExecutionTraceState | None, tool_name: str, payload: dict | None) -> None:
    """Track tool usage and touched files for the turn summary."""
    if trace is None:
        return
    payload = payload or {}
    event_type = str(payload.get("event", "start"))
    target = (
        payload.get("target")
        or payload.get("path")
        or payload.get("command")
        or payload.get("directory")
        or ""
    )
    target_text = str(target or "").strip()
    activity_label, _ = _tool_activity_style(tool_name)

    with trace.lock:
        if event_type == "start":
            trace.tool_counts[tool_name] = trace.tool_counts.get(tool_name, 0) + 1
            _append_unique(trace.touched_targets, target_text)
            trace.current_tool = tool_name
            trace.current_target = target_text
            trace.current_detail = f"{_tool_activity_verb(activity_label)} {target_text or tool_name}"
            trace.waiting_for_model = False
            return

        if event_type == "progress":
            mode = str(payload.get("mode", "background_wait"))
            trace.current_tool = tool_name
            trace.current_target = target_text
            trace.current_detail = (
                f"Waiting for command shutdown: {target_text or tool_name}"
                if mode == "stop_requested"
                else f"Command still running: {target_text or tool_name}"
            )
            trace.waiting_for_model = False
            return

        if event_type != "result":
            return

        _append_unique(trace.touched_targets, target_text)
        if payload.get("action") in {"write", "delete"} or payload.get("lines_added") or payload.get("lines_deleted"):
            _append_unique(trace.changed_targets, target_text)
        trace.current_tool = tool_name
        trace.current_target = target_text
        trace.current_detail = (
            f"Completed {tool_name}: {target_text or tool_name}"
            if payload.get("success", True)
            else f"{tool_name} reported an issue: {target_text or tool_name}"
        )
        trace.waiting_for_model = False


def _record_trace_progress(trace: ExecutionTraceState | None, payload: dict | None) -> None:
    """Store model-wait and step-detail updates for the live panel."""
    if trace is None or not payload:
        return
    event_type = str(payload.get("event", "")).strip().lower()
    phase = str(payload.get("phase", "")).strip().lower()
    model = str(payload.get("model", "")).strip()
    detail = str(payload.get("detail", "")).strip()
    with trace.lock:
        if phase:
            trace.current_phase = phase
        if model:
            trace.current_model = model
        if event_type == "model_wait":
            trace.waiting_for_model = True
            trace.current_detail = detail or "Waiting for model response."
        elif detail:
            trace.waiting_for_model = False
            trace.current_detail = detail


def _record_trace_thinking(trace: ExecutionTraceState | None, text: str) -> None:
    """Store the latest reasoning snippet for the live panel."""
    if trace is None or not text:
        return
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    snippet = " ".join(lines[:2]) if lines else str(text).strip()
    with trace.lock:
        trace.latest_thinking = _truncate_cli_value(snippet, limit=110)
        if trace.waiting_for_model:
            trace.current_detail = "Model returned reasoning for the next step."


def _record_trace_response(trace: ExecutionTraceState | None, text: str) -> None:
    """Store the latest response snippet for the live panel."""
    if trace is None or not text:
        return
    snippet = " ".join(str(text).split())
    with trace.lock:
        trace.latest_response = _truncate_cli_value(snippet, limit=110)
        trace.current_detail = "Drafting the user-facing response."
        trace.waiting_for_model = False


def build_live_status_lines(trace: ExecutionTraceState) -> list[str]:
    """Build a compact real-time status view for the active turn."""
    with trace.lock:
        elapsed = trace.elapsed_seconds()
        phase_label = _phase_label(trace.current_phase)

        # Phase icon mapping with descriptive status
        phase_icons = {
            "UNDERSTAND": "🔍", "PLAN": "📋", "PRECHECK": "🔎",
            "EXECUTE": "⚡", "REVIEW": "📝", "VERIFY": "✅",
        }
        icon = phase_icons.get(phase_label, "🔧")

        # Descriptive phase status messages
        phase_status = {
            "UNDERSTAND": "Analyzing your request",
            "PLAN": "Creating execution plan",
            "PRECHECK": "Validating approach",
            "EXECUTE": "Executing tasks",
            "REVIEW": "Reviewing changes",
            "VERIFY": "Verifying results",
        }
        status_text = phase_status.get(phase_label, "Processing")

        total_tool_calls = sum(trace.tool_counts.values()) if trace.tool_counts else 0

        # Step count and model display
        model_text = trace.current_model or "pending selection"
        headline = f"{icon} {phase_label}"
        step_info = f"Step {total_tool_calls + 1}"
        if trace.plan_total:
            step_info += f"/{trace.plan_total}"
        headline = f"{icon} {phase_label} | {step_info} | Model: {model_text}"

        lines = [f"[bold white]{headline}[/bold white]"]

        # Status description
        lines.append(f"  [dim]{status_text}...[/dim]")

        # Current tool activity with clear icons and action description
        if trace.current_target:
            tool_icon = "🔧"
            action_text = "Working on"
            if trace.current_phase in ("understand", "planner"):
                tool_icon = "📖"
                action_text = "Reading"
            elif trace.current_phase == "executor":
                tool_icon = "⚡"
                action_text = "Executing"
            elif trace.current_phase == "reviewer":
                tool_icon = "🔎"
                action_text = "Reviewing"
            elif trace.current_phase == "verify":
                tool_icon = "✅"
                action_text = "Verifying"
            target = _truncate_cli_value(trace.current_target, limit=60)
            lines.append(f"  {tool_icon} [white]{action_text}: {target}[/white]")
        elif trace.current_detail and trace.current_detail != "Preparing execution trace.":
            lines.append(f"  [dim]{trace.current_detail}[/dim]")

        # Timing and tool count
        timing_parts = [f"⏱️  {elapsed:.1f}s elapsed"]
        if total_tool_calls > 0:
            timing_parts.append(f"{total_tool_calls} tool(s) completed")
        lines.append(f"  [dim]{' | '.join(timing_parts)}[/dim]")

        # Plan progress bar
        if trace.plan_total:
            filled = int((trace.plan_completed / trace.plan_total) * 10)
            bar = "█" * filled + "░" * (10 - filled)
            plan_line = f"  📊 Plan: {bar} {trace.plan_completed}/{trace.plan_total} done"
            if trace.active_plan_item:
                plan_line += f" | [dim]{_truncate_cli_value(trace.active_plan_item, limit=42)}[/dim]"
            lines.append(plan_line)

        # Tool execution log (last few tools)
        if trace.tool_counts:
            tool_parts = []
            for name, count in sorted(trace.tool_counts.items()):
                tool_parts.append(f"{name}×{count}")
            lines.append(f"  🧰 [dim]{', '.join(tool_parts[:6])}[/dim]")

        # Thinking / waiting status with more descriptive text
        if trace.latest_thinking:
            lines.append(f"  💭 [dim italic]{trace.latest_thinking}[/dim italic]")
        elif trace.waiting_for_model:
            model_status = "Waiting for model to decide next step"
            if phase_label == "PLAN":
                model_status = "Model is creating the execution plan"
            elif phase_label == "EXECUTE":
                model_status = "Model is determining the best tool to use"
            elif phase_label == "REVIEW":
                model_status = "Model is reviewing the changes"
            lines.append(f"  💭 [dim italic]{model_status}...[/dim italic]")

        # Draft response preview
        if trace.latest_response and not trace.waiting_for_model:
            lines.append(f"  📝 [dim]{trace.latest_response}[/dim]")

        return lines


def build_live_status_panel(trace: ExecutionTraceState) -> Panel:
    """Build the live status panel renderable."""
    phase_label = _phase_label(trace.current_phase)
    phase_icons = {
        "UNDERSTAND": "🔍", "PLAN": "📋", "PRECHECK": "🔎",
        "EXECUTE": "⚡", "REVIEW": "📝", "VERIFY": "✅",
    }
    icon = phase_icons.get(phase_label, "🔧")
    return Panel(
        "\n".join(build_live_status_lines(trace)),
        border_style="cyan",
        title=f"[bold cyan]{icon} {phase_label}[/bold cyan]",
        padding=(0, 1),
        expand=False,
        width=min(console.width, 96),
    )


def should_use_live_trace_panel() -> bool:
    """Use Rich Live only when this process safely owns the active terminal."""
    return bool(console.is_terminal and threading.current_thread() is threading.main_thread())


def _run_live_trace_panel(trace: ExecutionTraceState, runner) -> None:
    """Refresh the transient live status panel while a turn is active."""
    stop_event = threading.Event()

    def refresh_loop(live: Live) -> None:
        while not stop_event.is_set():
            live.update(build_live_status_panel(trace), refresh=True)
            stop_event.wait(0.2)

    with Live(build_live_status_panel(trace), console=console, refresh_per_second=8, transient=True) as live:
        worker = threading.Thread(target=refresh_loop, args=(live,), daemon=True)
        worker.start()
        try:
            runner()
            live.update(build_live_status_panel(trace), refresh=True)
        finally:
            stop_event.set()
            worker.join(timeout=1)


def build_trace_summary_lines(trace: ExecutionTraceState) -> list[str]:
    """Build compact summary lines for a completed turn."""
    lines = [f"[bold white]⏱️  Elapsed[/bold white] {trace.elapsed_seconds():.1f}s"]

    if trace.phases:
        labels = []
        phase_icons = {
            "understand": "🔍", "planner": "📋", "reviewer-pre": "🔎",
            "executor": "⚡", "reviewer": "📝", "verify": "✅",
        }
        for phase, _model in trace.phases:
            label = {
                "understand": "UNDERSTAND",
                "planner": "PLAN",
                "reviewer-pre": "PRECHECK",
                "executor": "EXECUTE",
                "reviewer": "REVIEW",
                "verify": "VERIFY",
            }.get(phase, phase.upper())
            icon = phase_icons.get(phase, "•")
            if not labels or labels[-1] != f"{icon} {label}":
                labels.append(f"{icon} {label}")
        lines.append(f"[bold white]🔄 Flow[/bold white] {' → '.join(labels)}")

    if trace.plan_total:
        filled = int((trace.plan_completed / trace.plan_total) * 10)
        bar = "█" * filled + "░" * (10 - filled)
        plan_line = f"[bold white]📊 Plan[/bold white] {bar} {trace.plan_completed}/{trace.plan_total} completed"
        if trace.active_plan_item:
            plan_line += f" | [dim]{_truncate_cli_value(trace.active_plan_item, limit=56)}[/dim]"
        lines.append(plan_line)

    if trace.tool_counts:
        tool_parts = [f"{name} ×{count}" for name, count in sorted(trace.tool_counts.items())]
        lines.append(f"[bold white]🧰 Tools[/bold white] {', '.join(tool_parts[:5])}")

    # Enhanced change summary with diff preview
    if any(trace.workspace_delta_counts.values()):
        delta_icons = {"created": "✨", "modified": "📝", "deleted": "🗑️"}
        delta_parts = [
            f"{delta_icons.get(label, '•')} {count} {label}"
            for label, count in trace.workspace_delta_counts.items()
            if count
        ]

        # Calculate total changes
        total_changes = sum(trace.workspace_delta_counts.values())
        change_summary = f"[bold white]📂 Changes[/bold white] {', '.join(delta_parts)}"

        # Add change count badge
        if total_changes > 0:
            change_summary += f" [dim]({total_changes} file{'s' if total_changes > 1 else ''} changed)[/dim]"

        lines.append(change_summary)

        # Add diff preview for changed files
        if trace.changed_targets:
            preview_files = trace.changed_targets[:3]  # Show first 3 changed files
            for file_path in preview_files:
                rel_path = _make_workspace_relative(file_path, "")
                # Determine change type based on workspace delta counts
                # We can't know exact type per file, so use heuristics
                created_count = trace.workspace_delta_counts.get("created", 0)
                deleted_count = trace.workspace_delta_counts.get("deleted", 0)
                
                # Simple heuristic: if mostly creations, assume new; if mostly deletions, assume deleted
                if created_count > 0 and deleted_count == 0:
                    change_type = "[success]+new[/success]"
                elif deleted_count > 0 and created_count == 0:
                    change_type = "[error]-deleted[/error]"
                else:
                    change_type = "[warning]~modified[/warning]"
                lines.append(f"    {change_type} [dim]{_truncate_cli_value(rel_path, limit=60)}[/dim]")

    targets = trace.changed_targets or trace.touched_targets
    if targets:
        lines.append(f"[bold white]📍 Touched[/bold white] {', '.join(_truncate_cli_value(item, limit=32) for item in targets[:4])}")

    # Model routing explanation
    if trace.current_model:
        lines.append(f"[bold white]🧭 Model[/bold white] {trace.current_model}")

    return lines


def render_trace_summary(trace: ExecutionTraceState) -> None:
    """Render a compact summary of the completed turn."""
    lines = build_trace_summary_lines(trace)
    if not lines:
        return
    console.print(
        Panel(
            "\n".join(lines),
            border_style="bright_blue",
            title="[bold bright_cyan]Trace Summary[/bold bright_cyan]",
            padding=(0, 1),
            expand=False,
            width=min(console.width, 92),
        )
    )
    console.print()


def build_prompt_session() -> PromptSession:
    """Build the interactive prompt session."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    completer = WordCompleter(SLASH_COMMANDS, sentence=True)
    pt_style = PTStyle.from_dict({"prompt": "#00cc66 bold"})
    try:
        return PromptSession(
            history=FileHistory(str(HISTORY_FILE)),
            completer=completer,
            style=pt_style,
        )
    except Exception:
        return PromptSession(completer=completer, style=pt_style)


def _format_permission_panel_body(message: str, *, hosted: bool = False, countdown: int | None = None) -> str:
    """Render a readable approval card for the main prompt loop."""
    stop_hint = (
        "cancel the blocked hosted turn"
        if hosted
        else "stop task & deny"
    )

    countdown_display = ""
    if countdown is not None and countdown > 0:
        countdown_display = f" [yellow]({countdown}s timeout)[/yellow]"

    lines = [
        f"[bold white]{message}[/bold white]",
        "",
        "[bold bright_yellow]Choose an option:[/bold bright_yellow]",
        "",
        "  [success][1][/success] ✅ Allow once            [dim](y, /approve)[/dim]",
        "  [success][2][/success] 🔄 Allow this tool       [dim](a, /approve tool)[/dim]",
        "  [success][3][/success] 🟢 Allow all for session  [dim](all, /approve all)[/dim]",
        "  [error][4][/error] ❌ Deny                  [dim](n, /deny)[/dim]",
        f"  [warning][5][/warning] 🛑 {stop_hint:24s}  [dim](/stop)[/dim]",
        "",
        f"[dim italic]Enter choice (1-5) or use the shortcut commands above.{countdown_display}[/dim italic]",
    ]
    return "\n".join(lines)


@dataclass
class PendingLocalApproval:
    """A permission request that must be answered from the main CLI prompt."""

    tool_name: str
    message: str
    event: threading.Event = field(default_factory=threading.Event)
    decision: str | None = None


class InteractivePermissionManager(PermissionManager):
    """Permission manager that defers local approvals to the main prompt loop."""

    def __init__(self) -> None:
        super().__init__()
        self._pending_lock = threading.Lock()
        self._pending_request: PendingLocalApproval | None = None

    def request_permission(self, tool_name: str, message: str) -> bool:
        if self.auto_approve:
            console.print(f"  [dim]Auto-approved: {tool_name}[/dim]")
            return True
        if self._session_approvals.get(tool_name):
            console.print(f"  [dim]Previously approved: {tool_name}[/dim]")
            return True
        if self._consume_once_approval(tool_name):
            return True

        request = PendingLocalApproval(tool_name=tool_name, message=message)
        with self._pending_lock:
            if self._pending_request is not None:
                raise RuntimeError("Another permission request is already pending.")
            self._pending_request = request

        # Show permission panel with countdown
        console.print()
        permission_timeout = 60  # 60 second timeout
        start_time = time.monotonic()

        # Use Live panel for countdown updates
        from rich.live import Live

        def get_permission_panel():
            elapsed = int(time.monotonic() - start_time)
            remaining = max(0, permission_timeout - elapsed)
            return Panel(
                _format_permission_panel_body(message, countdown=remaining if remaining > 0 else None),
                title=f"[yellow]⚠️  Permission Required: {tool_name}[/yellow]",
                border_style="yellow",
                padding=(1, 2),
                expand=False,
                width=min(console.width, 86),
            )

        with Live(get_permission_panel(), console=console, refresh_per_second=1, transient=False) as live:
            # Wait for response with timeout
            while not request.event.is_set():
                elapsed = time.monotonic() - start_time
                if elapsed >= permission_timeout:
                    # Auto-deny on timeout
                    request.decision = PERMISSION_CHOICE_DENY
                    request.event.set()
                    live.update(
                        Panel(
                            f"[red]⏱️  Timeout - permission request denied after {permission_timeout}s[/red]",
                            title="[red]⚠️  Permission Timeout[/red]",
                            border_style="red",
                        )
                    )
                    break
                request.event.wait(timeout=0.5)
                live.update(get_permission_panel())

        decision = request.decision or PERMISSION_CHOICE_DENY
        with self._pending_lock:
            if self._pending_request is request:
                self._pending_request = None

        if decision == PERMISSION_CHOICE_TOOL:
            self._session_approvals[tool_name] = True
            return True
        if decision == PERMISSION_CHOICE_ALL:
            self.auto_approve = True
            return True
        return decision == PERMISSION_CHOICE_ONCE

    def pending_request(self) -> PendingLocalApproval | None:
        """Return the active local approval request, if any."""
        with self._pending_lock:
            return self._pending_request

    def resolve_pending(self, decision: str) -> bool:
        """Resolve the current pending request with a normalized decision."""
        if decision not in {
            PERMISSION_CHOICE_DENY,
            PERMISSION_CHOICE_ONCE,
            PERMISSION_CHOICE_TOOL,
            PERMISSION_CHOICE_ALL,
        }:
            return False
        with self._pending_lock:
            request = self._pending_request
            if request is None:
                return False
            request.decision = decision
            request.event.set()
            return True

    def cancel_pending(self) -> bool:
        """Deny the current pending request so a blocked worker can continue."""
        return self.resolve_pending(PERMISSION_CHOICE_DENY)


@dataclass
class PendingRemoteApproval:
    """A hosted approval request that is resolved from the main CLI prompt."""

    approval_id: str
    tool_name: str
    message: str
    event: threading.Event = field(default_factory=threading.Event)
    decision: str | None = None


class InteractiveRemoteApprovalManager:
    """Defer hosted approvals to the main prompt while the worker thread waits."""

    def __init__(self) -> None:
        self._pending_lock = threading.Lock()
        self._pending_request: PendingRemoteApproval | None = None

    def request_approval(self, approval_id: str, tool_name: str, message: str) -> str:
        request = PendingRemoteApproval(approval_id=approval_id, tool_name=tool_name, message=message)
        with self._pending_lock:
            if self._pending_request is not None:
                raise RuntimeError("Another hosted approval is already pending.")
            self._pending_request = request

        console.print()
        console.print(
            Panel(
                _format_permission_panel_body(message, hosted=True),
                title="[bold bright_yellow]Hosted Permission Required[/bold bright_yellow]",
                border_style="bright_yellow",
                padding=(1, 2),
                expand=False,
                width=min(console.width, 86),
            )
        )
        console.print()

        request.event.wait()
        decision = request.decision or PERMISSION_CHOICE_DENY
        with self._pending_lock:
            if self._pending_request is request:
                self._pending_request = None
        return decision

    def pending_request(self) -> PendingRemoteApproval | None:
        """Return the current hosted approval request, if any."""
        with self._pending_lock:
            return self._pending_request

    def resolve_pending(self, decision: str) -> bool:
        """Resolve the pending hosted approval with a normalized decision."""
        if decision not in {
            PERMISSION_CHOICE_DENY,
            PERMISSION_CHOICE_ONCE,
            PERMISSION_CHOICE_TOOL,
            PERMISSION_CHOICE_ALL,
        }:
            return False
        with self._pending_lock:
            request = self._pending_request
            if request is None:
                return False
            request.decision = decision
            request.event.set()
            return True

    def cancel_pending(self) -> bool:
        """Deny the pending hosted approval so the worker can continue."""
        return self.resolve_pending(PERMISSION_CHOICE_DENY)


def handle_help() -> None:
    """Render slash command help."""
    console.print()
    table = Table(
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        title="[bold bright_cyan]⌨️  Commands[/bold bright_cyan]",
        padding=(0, 2),
        expand=False,
        width=min(console.width, 58),
    )
    table.add_column("Command", style="bold bright_yellow", width=12)
    table.add_column("Description", style="white")
    table.add_row("/help", "Show this help message")
    table.add_row("/models", "List or switch models")
    table.add_row("/sessions", "List resumable remote sessions (remote only)")
    table.add_row("/clear", "Clear conversation history")
    table.add_row("/remove", "Undo last file change")
    table.add_row("/history", "Show session action log")
    table.add_row("/config", "Show current settings")
    table.add_row("/agents", "Set orchestration mode")
    table.add_row("/language", "Set reply language")
    table.add_row("/thinking", "Toggle local thinking display")
    table.add_row("/approve", "Approve a pending tool permission")
    table.add_row("/deny", "Deny a pending tool permission")
    table.add_row("/queue", "Show queue, add follow-ups, or clear pending tasks")
    table.add_row("/stop", "Request cancellation for the active task or hosted turn")
    table.add_row("/version", "Show version info")
    table.add_row("/close", "Close the current remote session")
    table.add_row("/exit", "Disconnect from the current session")
    table.add_row("/explain", "Explain selected code or file")
    table.add_row("/refactor", "Refactor selected code")
    table.add_row("/test", "Generate tests for selected code")
    table.add_row("/commit", "Review and commit changes")
    table.add_row("/summarize", "Summarize conversation history")
    console.print(table)
    console.print()


def handle_explain(agent, arg: str | None) -> None:
    """Handle /explain command - explain selected code or file."""
    if not arg:
        console.print("\n  [warning]⚠️  Usage: /explain <file_or_code>[/warning]\n")
        console.print("  [dim]Example: /explain neudev/agent.py[/dim]\n")
        return

    console.print(f"\n  [info]🔍 Explaining: {arg}[/info]\n")
    console.print("  [dim]NeuDev will analyze the selected code and provide a detailed explanation.[/dim]\n")
    console.print("  [dim]This is a shortcut for: \"Please explain in detail how this code works: {arg}\"[/dim]\n")


def handle_refactor(agent, arg: str | None) -> None:
    """Handle /refactor command - refactor selected code."""
    if not arg:
        console.print("\n  [warning]⚠️  Usage: /refactor <file_or_code> [goal][/warning]\n")
        console.print("  [dim]Example: /refactor neudev/agent.py --improve readability[/dim]\n")
        return

    goal = arg.split(" --", 1)[-1] if " --" in arg else "improve code quality"
    target = arg.split(" --")[0].strip()

    console.print(f"\n  [info]🔧 Refactoring: {target}[/info]\n")
    console.print(f"  [dim]Goal: {goal}[/dim]\n")
    console.print("  [dim]This is a shortcut for: \"Refactor this code to {goal}: {target}\"[/dim]\n")


def handle_test(agent, arg: str | None) -> None:
    """Handle /test command - generate tests for selected code."""
    if not arg:
        console.print("\n  [warning]⚠️  Usage: /test <file_or_code> [test_type][/warning]\n")
        console.print("  [dim]Example: /test neudev/agent.py --unit[/dim]\n")
        return

    test_type = arg.split(" --", 1)[-1] if " --" in arg else "unit"
    target = arg.split(" --")[0].strip()

    console.print(f"\n  [info]🧪 Generating {test_type} tests for: {target}[/info]\n")
    console.print("  [dim]This is a shortcut for: \"Generate comprehensive {test_type} tests for: {target}\"[/dim]\n")


def handle_commit(agent, arg: str | None) -> None:
    """Handle /commit command - review and commit changes."""
    console.print("\n  [info]📝 Reviewing changes for commit...[/info]\n")

    # Try to get git diff
    try:
        from neudev.tools.git_diff_review import GitDiffReviewTool
        from neudev.tools.base import ToolError

        tool = GitDiffReviewTool()
        tool.bind_workspace(agent.workspace)

        diff_result = tool.execute()
        if diff_result and "no changes" not in diff_result.lower():
            console.print(Panel(
                diff_result[:2000] + ("..." if len(diff_result) > 2000 else ""),
                title="[bold]Git Diff[/bold]",
                border_style="bright_blue",
            ))
            console.print("\n  [dim]This is a shortcut for: \"Review my changes and prepare a commit message\"[/dim]\n")
        else:
            console.print("  [dim]📭 No local git changes to review.[/dim]\n")
    except (ImportError, ToolError) as e:
        console.print(f"  [dim]📭 Git diff not available: {e}[/dim]\n")
        console.print("  [dim]This is a shortcut for: \"Review my changes and prepare a commit message\"[/dim]\n")


def handle_summarize(agent, arg: str | None) -> None:
    """Handle /summarize command - summarize conversation history."""
    console.print("\n  [info]📋 Summarizing conversation...[/info]\n")

    # Get recent conversation
    recent_messages = agent.conversation[-10:] if len(agent.conversation) > 10 else agent.conversation

    summary_parts = []
    user_messages = sum(1 for m in recent_messages if m.get("role") == "user")
    assistant_messages = sum(1 for m in recent_messages if m.get("role") == "assistant")

    summary_parts.append(f"**Recent Conversation Summary**:")
    summary_parts.append(f"- {user_messages} user messages")
    summary_parts.append(f"- {assistant_messages} assistant responses")

    # Count tool usage
    tool_count = sum(1 for m in recent_messages if m.get("role") == "tool")
    if tool_count:
        summary_parts.append(f"- {tool_count} tool calls")

    # Get action summary
    if agent.session.actions:
        recent_actions = agent.session.actions[-5:]
        action_types = set(a.action for a in recent_actions)
        if action_types:
            summary_parts.append(f"- Actions: {', '.join(action_types)}")

    console.print("\n".join(summary_parts))
    console.print("\n  [dim]This is a shortcut for: \"Summarize what we've discussed so far\"[/dim]\n")


def build_plan_panel_content(
    plan_update: dict | None,
    *,
    trace: ExecutionTraceState | None = None,
) -> tuple[str, list[str]] | None:
    """Build either the initial execution plan or a compact progress update."""
    if not plan_update:
        return None
    plan_items = plan_update.get("plan") or []
    conventions = plan_update.get("conventions") or []
    completed = sum(1 for item in plan_items if item.get("status") == "completed")
    active_item = next((item.get("text", "") for item in plan_items if item.get("status") == "in_progress"), "")
    signature = (
        tuple((item.get("text", ""), item.get("status", "pending")) for item in plan_items),
        tuple(str(item) for item in conventions),
    )

    previous_statuses: dict[str, str] = {}
    previous_completed = 0
    previous_active_item = ""
    initial_render = True
    if trace is not None:
        with trace.lock:
            previous_completed = trace.last_plan_completed
            previous_active_item = trace.last_plan_active_item
            if trace.last_plan_signature == signature:
                return None
            previous_statuses = {
                text: status for text, status in trace.last_plan_signature[0]
            } if trace.last_plan_signature else {}
            initial_render = not trace.plan_panel_rendered
            trace.plan_total = len(plan_items)
            trace.plan_completed = completed
            trace.active_plan_item = str(active_item or "").strip()
            trace.plan_panel_rendered = True
            trace.last_plan_signature = signature
            trace.last_plan_active_item = str(active_item or "").strip()
            trace.last_plan_completed = completed

    if not plan_items and not conventions:
        return None

    if not initial_render:
        lines = []
        newly_completed = [
            item.get("text", "")
            for item in plan_items
            if item.get("status") == "completed" and previous_statuses.get(item.get("text", "")) != "completed"
        ]
        for item in newly_completed[:2]:
            lines.append(f"[success]Completed[/success] {item}")
        if active_item and active_item != previous_active_item:
            lines.append(f"[info]In Progress[/info] {active_item}")
        remaining = max(len(plan_items) - completed, 0)
        lines.append(f"[dim]Progress[/dim] {completed}/{len(plan_items)} completed | {remaining} remaining")
        if not lines:
            return None
        return "[bold bright_yellow]Plan Progress[/bold bright_yellow]", lines

    lines = []
    if plan_items:
        lines.append("[bold bright_yellow]Execution Plan[/bold bright_yellow]")
        icon_map = {"pending": "☐", "in_progress": "◐", "completed": "☑"}
        priority = {"in_progress": 0, "pending": 1, "completed": 2}
        ordered_plan = sorted(
            enumerate(plan_items),
            key=lambda item: (priority.get(item[1].get("status", "pending"), 9), item[0]),
        )
        for _, item in ordered_plan[:4]:
            lines.append(f"{icon_map.get(item.get('status', 'pending'), '•')} {item.get('text', '')}")
        if len(plan_items) > 4:
            lines.append(f"[dim]... {len(plan_items) - 4} more items[/dim]")
    if conventions:
        if lines:
            lines.append("")
        lines.append("[bold bright_cyan]Repository Conventions[/bold bright_cyan]")
        lines.extend(f"- {item}" for item in conventions[:2])
        if len(conventions) > 2:
            lines.append(f"[dim]... {len(conventions) - 2} more conventions[/dim]")
    if not lines:
        return None
    return "[bold bright_yellow]Plan Update[/bold bright_yellow]", lines


def render_plan_panel(plan_update: dict | None, *, trace: ExecutionTraceState | None = None) -> None:
    """Render remote or local plan progress."""
    built = build_plan_panel_content(plan_update, trace=trace)
    if not built:
        return
    title, lines = built
    console.print(
        Panel(
            "\n".join(lines),
            border_style="bright_yellow",
            title=title,
            padding=(0, 1),
            expand=False,
            width=min(console.width, 72),
        )
    )
    console.print()


def render_workspace_change(changes: dict | None, *, trace: ExecutionTraceState | None = None) -> None:
    """Render detected workspace changes."""
    if not changes:
        return
    _record_trace_workspace_change(trace, changes)
    parts = []
    preview = []
    for label in ("modified", "created", "deleted"):
        items = changes.get(label) or []
        if items:
            parts.append(f"{len(items)} {label}")
            preview.extend(items[:3])
    if not parts:
        return
    lines = [f"[warning]Detected workspace changes:[/warning] {', '.join(parts)}"]
    if preview:
        lines.append(f"[dim]{', '.join(preview[:6])}[/dim]")
    console.print(
        Panel(
            "\n".join(lines),
            border_style="bright_yellow",
            title="[bold bright_yellow]Workspace Delta[/bold bright_yellow]",
            padding=(0, 1),
            expand=False,
            width=min(console.width, 84),
        )
    )
    console.print()


def render_thinking(thinking: str) -> None:
    """Render visible thinking text."""
    if not thinking:
        return
    thinking_lines = [line.rstrip() for line in thinking.strip().splitlines() if line.strip()]
    if len(thinking_lines) > 6:
        thinking_lines = thinking_lines[:6] + ["..."]
    body = "\n".join(thinking_lines)[:500]
    console.print(
        Panel(
            f"[dim italic]{body}[/dim italic]",
            border_style="grey50",
            title="[grey62]Reasoning Snapshot[/grey62]",
            padding=(0, 1),
            expand=True,
        )
    )
    console.print()


def render_phase_event(phase: str, model_name: str, *, trace: ExecutionTraceState | None = None) -> None:
    """Render the current execution phase in a consistent format."""
    normalized_phase = str(phase or "").strip().lower()
    labels = {
        "understand": "UNDERSTAND",
        "planner": "PLAN",
        "reviewer-pre": "PRECHECK",
        "executor": "EXECUTE",
        "reviewer": "REVIEW",
        "verify": "VERIFY",
    }
    descriptions = {
        "understand": "Inspecting the request, workspace context, and execution route.",
        "planner": "Building a focused execution checklist before edits.",
        "reviewer-pre": "Checking likely risks and missing validations before execution.",
        "executor": "Running the main implementation loop and calling tools as needed.",
        "reviewer": "Reviewing the completed work for gaps or regressions.",
        "verify": "Running final checks before returning the answer.",
    }
    step_number = _record_trace_phase(trace, normalized_phase, model_name)
    label = labels.get(normalized_phase, str(phase or "step").upper())
    model = model_name or "default model"
    detail = descriptions.get(normalized_phase, "Advancing the current task.")
    console.print(
        f"  [accent]{step_number:02d}. {label:<10}[/accent] [white]{detail}[/white]"
    )
    console.print(f"      [dim]model: {model}[/dim]")


def _tool_activity_style(tool_name: str) -> tuple[str, str]:
    """Return a compact label and color for a tool event."""
    return TOOL_ACTIVITY_META.get(tool_name, ("TOOL", "tool"))


def _make_workspace_relative(path: str, workspace: str = "") -> str:
    """Convert absolute path to workspace-relative path for display."""
    if not path:
        return path

    # If already relative, return as-is
    if not os.path.isabs(path):
        return path

    # Try to make relative to workspace
    if workspace:
        try:
            rel = os.path.relpath(path, workspace)
            # Only use relative path if it's shorter and doesn't start with ..
            if not rel.startswith("..") and len(rel) < len(path):
                return rel
        except (ValueError, OSError):
            pass

    # Try to make relative to home directory
    home = os.path.expanduser("~")
    if path.startswith(home):
        rel = path.replace(home, "~", 1)
        if len(rel) < len(path):
            return rel

    return path


def render_tool_event(
    tool_name: str,
    payload: dict | None,
    *,
    trace: ExecutionTraceState | None = None,
) -> None:
    """Render compact live tool activity."""
    payload = payload or {}
    _record_trace_tool_event(trace, tool_name, payload)
    event_type = str(payload.get("event", "start"))
    activity_label, activity_style = _tool_activity_style(tool_name)

    # Get target and convert to workspace-relative path
    target = (
        payload.get("target")
        or payload.get("path")
        or payload.get("command")
        or payload.get("directory")
        or ""
    )

    # Convert file paths to workspace-relative for better readability
    file_tools = {"read_file", "write_file", "edit_file", "smart_edit_file", "delete_file",
                  "python_ast_edit", "js_ts_symbol_edit", "file_outline"}
    if tool_name in file_tools and target:
        workspace = trace.custom_fields.get("workspace", "") if trace else ""
        target = _make_workspace_relative(str(target), workspace)

    target_text = _truncate_cli_value(str(target).strip() or tool_name, limit=92)

    if event_type == "progress":
        elapsed = payload.get("elapsed", 0)
        started_at = payload.get("started_at", "")
        mode = str(payload.get("mode", "background_wait"))
        state = "STOP" if mode == "stop_requested" else "WAIT"
        detail = "stop requested" if mode == "stop_requested" else f"running {elapsed}s"
        suffix = f"{detail} | started {started_at}".strip(" |")
        console.print(
            f"    [{activity_style}]{activity_label:<7}[/{activity_style}] "
            f"[warning]{state}[/warning] [white]{_tool_activity_verb(activity_label)} {target_text}[/white] "
            f"[dim]{suffix}[/dim]"
        )
        return

    if event_type == "result":
        success = payload.get("success", True)
        state = "DONE" if success else "FAIL"
        state_style = "success" if success else "error"
        parts = []
        lines_added = int(payload.get("lines_added", 0) or 0)
        lines_deleted = int(payload.get("lines_deleted", 0) or 0)
        if lines_added or lines_deleted:
            parts.append(f"+{lines_added}/-{lines_deleted} lines")
        elif payload.get("result_preview"):
            parts.append(_truncate_cli_value(str(payload.get("result_preview")), limit=72))
        parts.append(f"{payload.get('elapsed', 0)}s")
        console.print(
            f"    [{activity_style}]{activity_label:<7}[/{activity_style}] "
            f"[{state_style}]{state}[/{state_style}] [white]{target_text}[/white] "
            f"[dim]{' | '.join(part for part in parts if part)}[/dim]"
        )
        return

    started_at = payload.get("started_at", "")
    suffix = f"started {started_at}".strip()
    console.print(
        f"    [{activity_style}]{activity_label:<7}[/{activity_style}] "
        f"[info]START[/info] [white]{_tool_activity_verb(activity_label)} {target_text}[/white] [dim]{suffix}[/dim]"
    )


def render_agent_routing(
    config: NeuDevConfig,
    *,
    agent_team: dict | None = None,
    last_used_model: str | None = None,
    last_route_reason: str = "",
) -> None:
    """Render routing and specialist information."""
    if agent_team:
        console.print(
            "  [dim]"
            f"mode {config.agent_mode} · "
            f"🧭 Team: planner {agent_team['planner']} · "
            f"executor {agent_team['executor']} · "
            f"reviewer {agent_team['reviewer']}"
            "[/dim]"
        )
        console.print()
        return
    if last_used_model:
        note = f"  [dim]🤖 Active model: {last_used_model}"
        if last_route_reason:
            note += f" · {last_route_reason}"
        note += "[/dim]"
        console.print(note)
        console.print()


def render_response_panel(response: str) -> None:
    """Render the final agent response panel."""
    if not response:
        console.print("  [dim]No response from the agent.[/dim]\n")
        return
    try:
        body = Markdown(response)
    except Exception:
        body = response
    console.print(
        Panel(
            body,
            border_style="bright_blue",
            title="[bold bright_cyan]Agent Response[/bold bright_cyan]",
            padding=(1, 2),
            expand=True,
        )
    )
    console.print()


def print_history_table(actions: list[dict]) -> None:
    """Render session history actions."""
    if not actions:
        console.print("\n  [dim]📭 No actions recorded yet.[/dim]\n")
        return
    console.print()
    table = Table(
        title="[bold bright_cyan]📋 Session History[/bold bright_cyan]",
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        padding=(0, 1),
        expand=False,
    )
    table.add_column("#", style="dim", width=4, justify="center")
    table.add_column("Action", style="bold", width=12)
    table.add_column("Target")
    icon_map = {
        "created": ("✨", "green"),
        "modified": ("✏️", "yellow"),
        "deleted": ("🗑️", "red"),
        "command": ("⚡", "magenta"),
        "read": ("📖", "cyan"),
    }
    for index, item in enumerate(actions, 1):
        icon, color = icon_map.get(item.get("action"), ("•", "white"))
        table.add_row(str(index), f"{icon} {item.get('action', 'other')}", item.get("target", ""), style=color)
    console.print(table)
    console.print()


def print_remote_sessions_table(sessions: list[dict]) -> None:
    """Render hosted sessions that can be resumed."""
    if not sessions:
        console.print("\n  [dim]📭 No hosted sessions available.[/dim]\n")
        return
    console.print()
    table = Table(
        title="[bold bright_cyan]🌐 Hosted Sessions[/bold bright_cyan]",
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        padding=(0, 1),
        expand=False,
        width=min(console.width, 96),
    )
    table.add_column("Session ID", style="bold white")
    table.add_column("Workspace", style="bright_cyan")
    table.add_column("Messages", justify="right", style="dim")
    table.add_column("Model", style="dim")
    table.add_column("Pending", justify="center")
    table.add_column("Updated", style="dim")
    for item in sessions:
        table.add_row(
            item.get("session_id", ""),
            item.get("workspace", ""),
            str(item.get("messages_count", 0)),
            item.get("model", ""),
            "⚠️" if item.get("pending_approval") else "",
            item.get("updated_at", ""),
        )
    console.print(table)
    console.print()


def render_remote_error(payload: dict[str, str]) -> None:
    """Render a hosted runtime error payload."""
    console.print(
        Panel(
            f"[bold red]❌ Hosted Agent Error[/bold red]\n\n[white]{payload.get('error', 'Unknown error')}[/white]",
            border_style="red",
            title="[bold red]⚠️  Remote request failed[/bold red]",
            padding=(1, 2),
            expand=False,
        )
    )
    console.print()


def ask_remote_permission(tool_name: str, message: str) -> str:
    """Prompt for remote tool permission."""
    return prompt_permission_choice(tool_name, message, title_prefix="Remote Permission Required")


def prompt_for_hosted_settings(config: NeuDevConfig, *, runtime_mode: str) -> tuple[str, str]:
    """Ensure hosted API settings are available for remote or hybrid modes."""
    runtime_label = "Remote" if runtime_mode == "remote" else "Hosted inference"
    api_base_url = os.environ.get("NEUDEV_API_BASE_URL") or config.api_base_url
    if not api_base_url:
        api_base_url = Prompt.ask(f"{runtime_label} API base URL", default="http://127.0.0.1:8765")
        config.update(api_base_url=api_base_url, runtime_mode=runtime_mode)

    api_key = os.environ.get("NEUDEV_API_KEY") or config.api_key
    if not api_key:
        api_key = Prompt.ask(f"{runtime_label} API key", password=True)
        config.update(api_key=api_key, runtime_mode=runtime_mode)

    return api_base_url, api_key


def run_login_setup(args: argparse.Namespace | None = None) -> None:
    """Persist hosted API settings for remote or hybrid CLI usage."""
    config = NeuDevConfig.load()
    runtime_mode = getattr(args, "runtime", None) or config.runtime_mode or "remote"
    if runtime_mode not in {"remote", "hybrid"}:
        runtime_mode = "remote"

    default_api_base_url = (getattr(args, "api_base_url", None) or config.api_base_url or "http://127.0.0.1:8765").strip()
    api_base_url = default_api_base_url.rstrip("/")
    if not api_base_url:
        api_base_url = Prompt.ask("Hosted API base URL", default="http://127.0.0.1:8765").strip().rstrip("/")

    api_key = (getattr(args, "api_key", None) or config.api_key or "").strip()
    if not api_key:
        api_key = Prompt.ask("Hosted API key", password=True).strip()
    if not api_key:
        console.print("\n  [error]❌ API key cannot be empty.[/error]\n")
        return

    websocket_base_url = getattr(args, "ws_base_url", None)
    if websocket_base_url is None:
        websocket_base_url = config.websocket_base_url
    websocket_base_url = str(websocket_base_url or "").strip().rstrip("/")

    updates = {
        "runtime_mode": runtime_mode,
        "api_base_url": api_base_url,
        "api_key": api_key,
    }
    if websocket_base_url:
        updates["websocket_base_url"] = websocket_base_url
    config.update(**updates)

    console.print()
    table = Table(
        title="[bold bright_cyan]🔐 Hosted Login Saved[/bold bright_cyan]",
        show_header=False,
        border_style="bright_blue",
        padding=(0, 1),
        expand=False,
        width=min(console.width, 78),
    )
    table.add_column("Key", style="muted")
    table.add_column("Value", style="bold white")
    table.add_row("Config File", str(CONFIG_DIR / "config.json"))
    table.add_row("Runtime", runtime_mode)
    table.add_row("API Base URL", api_base_url)
    table.add_row("API Key", "saved")
    if websocket_base_url:
        table.add_row("WebSocket URL", websocket_base_url)
    console.print(table)
    console.print("  [dim]Environment variables still override saved values: NEUDEV_API_BASE_URL, NEUDEV_API_KEY, NEUDEV_WS_BASE_URL.[/dim]")
    console.print()


def run_auth_status() -> None:
    """Show stored hosted authentication settings."""
    config = NeuDevConfig.load()
    console.print()
    table = Table(
        title="[bold bright_cyan]🔐 Hosted Auth Status[/bold bright_cyan]",
        show_header=False,
        border_style="bright_blue",
        padding=(0, 1),
        expand=False,
        width=min(console.width, 78),
    )
    table.add_column("Key", style="muted")
    table.add_column("Value", style="bold white")
    table.add_row("Config File", str(CONFIG_FILE))
    table.add_row("Runtime", config.runtime_mode)
    table.add_row("API Base URL", config.api_base_url or "not set")
    table.add_row("API Key", "saved" if config.api_key else "not set")
    table.add_row("WebSocket URL", config.websocket_base_url or "not set")
    console.print(table)
    console.print("  [dim]Environment variables override saved values when present.[/dim]")
    console.print()


def run_logout(args: argparse.Namespace | None = None) -> None:
    """Clear saved hosted credentials."""
    config = NeuDevConfig.load()
    clear_all = bool(getattr(args, "all", False))
    updates = {"api_key": ""}
    if clear_all:
        updates["api_base_url"] = ""
        updates["websocket_base_url"] = ""
    config.update(**updates)

    console.print()
    if clear_all:
        console.print("  [success]✅ Cleared the saved API key, API base URL, and WebSocket URL.[/success]")
    else:
        console.print("  [success]✅ Cleared the saved API key.[/success]")
    console.print(f"  [dim]Config file: {CONFIG_FILE}[/dim]")
    console.print()


def run_uninstall(args: argparse.Namespace | None = None) -> None:
    """Show uninstall commands and optionally purge local config."""
    args = args or argparse.Namespace(purge_config=False, yes=False)
    if getattr(args, "purge_config", False):
        removed = []
        for path in (CONFIG_FILE, HISTORY_FILE):
            if path.exists():
                path.unlink()
                removed.append(str(path))
        if CONFIG_DIR.exists():
            try:
                next(CONFIG_DIR.iterdir())
            except StopIteration:
                CONFIG_DIR.rmdir()
        console.print()
        if removed:
            console.print("  [success]✅ Removed local NeuDev config files.[/success]")
            for path in removed:
                console.print(f"  [dim]{path}[/dim]")
        else:
            console.print("  [dim]No local NeuDev config files were present.[/dim]")
        console.print()

    console.print(
        Panel(
            "[bold bright_yellow]Remove the CLI package with the installer you used:[/bold bright_yellow]\n\n"
            "[white]npm uninstall -g neudev-cli[/white]\n"
            "[white]python -m pip uninstall neudev[/white]\n"
            "[white]py -m pip uninstall neudev[/white]\n\n"
            "[dim]If you also want to clear saved credentials and command history, run:[/dim]\n"
            "[white]neu uninstall --purge-config[/white]",
            border_style="bright_blue",
            title="[bold bright_cyan]🧹 Uninstall NeuDev[/bold bright_cyan]",
            padding=(1, 2),
            expand=False,
        )
    )
    console.print()


def handle_local_models(agent: Agent, selection: str | None = None) -> None:
    """List or switch local models."""
    try:
        models = agent.llm.list_models()
    except LLMError as exc:
        console.print(f"\n  [error]❌ Error listing models: {exc}[/error]\n")
        return
    if not models:
        console.print("\n  [warning]⚠️  No models found. Download one with `ollama pull qwen3:latest`.[/warning]\n")
        return

    console.print()
    table = Table(
        title="[bold bright_cyan]🤖 Available Models[/bold bright_cyan]",
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        padding=(0, 1),
        expand=False,
        width=min(console.width, 68),
    )
    table.add_column("#", style="dim", width=3, justify="center")
    table.add_column("Model", style="bold white")
    table.add_column("Size", style="dim", justify="right")
    table.add_column("Role", style="dim")
    table.add_column("Active", justify="center")

    preview_model, preview_reason = agent.llm.preview_auto_model()
    auto_active = "✅" if agent.llm.model == "auto" else "  "
    table.add_row(
        "0",
        "auto",
        "-",
        f"Task-routed -> {preview_model or 'No model available'}",
        auto_active,
        style="bold bright_green" if auto_active.strip() else "",
    )

    for index, model in enumerate(models, 1):
        size_mb = model["size"] / (1024 * 1024)
        size_str = f"{size_mb:.0f} MB" if size_mb < 1024 else f"{size_mb / 1024:.1f} GB"
        active = "✅" if model.get("active") else "  "
        table.add_row(
            str(index),
            model["name"],
            size_str,
            model.get("role", ""),
            active,
            style="bold bright_green" if active.strip() else "",
        )
    console.print(table)
    console.print(f"  [dim]Auto routing: {preview_reason}[/dim]")
    console.print()

    choice = (selection or "").strip()
    if not choice:
        choice = Prompt.ask("Enter `0` for auto, a model number, or a model name", default="")
    if not choice:
        return
    if choice.lower() == "auto" or choice == "0":
        selected_name = "auto"
    elif choice.isdigit() and 0 < int(choice) <= len(models):
        selected_name = models[int(choice) - 1]["name"]
    else:
        selected_name = choice

    try:
        agent.llm.switch_model(selected_name)
        agent.refresh_context()
        console.print(f"\n  [success]✅ Model mode: {agent.llm.get_display_model()}[/success]\n")
    except LLMError as exc:
        console.print(f"\n  [error]❌ Failed to switch: {exc}[/error]\n")


def handle_remote_models(session: RemoteSessionClient, config: NeuDevConfig, selection: str | None = None) -> None:
    """List or switch hosted models."""
    try:
        payload = session.list_models()
    except RemoteAPIError as exc:
        console.print(f"\n  [error]❌ Error listing remote models: {exc}[/error]\n")
        return

    models = payload.get("models", [])
    if not models:
        console.print("\n  [warning]⚠️  No remote models are available.[/warning]\n")
        return

    console.print()
    table = Table(
        title="[bold bright_cyan]🌐 Remote Models[/bold bright_cyan]",
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        padding=(0, 1),
        expand=False,
        width=min(console.width, 68),
    )
    table.add_column("#", style="dim", width=3, justify="center")
    table.add_column("Model", style="bold white")
    table.add_column("Size", style="dim", justify="right")
    table.add_column("Role", style="dim")
    table.add_column("Active", justify="center")
    auto_active = "✅" if config.model == "auto" else "  "
    auto_preview = payload.get("auto_preview_model") or "No model available"
    table.add_row(
        "0",
        "auto",
        "-",
        f"Task-routed -> {auto_preview}",
        auto_active,
        style="bold bright_green" if auto_active.strip() else "",
    )
    for index, model in enumerate(models, 1):
        size_mb = model["size"] / (1024 * 1024)
        size_str = f"{size_mb:.0f} MB" if size_mb < 1024 else f"{size_mb / 1024:.1f} GB"
        active = "✅" if model.get("active") else "  "
        table.add_row(
            str(index),
            model["name"],
            size_str,
            model.get("role", ""),
            active,
            style="bold bright_green" if active.strip() else "",
        )
    console.print(table)
    console.print(f"  [dim]Current remote model: {payload.get('display_model', config.model)}[/dim]")
    if payload.get("auto_preview_reason"):
        console.print(f"  [dim]Auto routing: {payload.get('auto_preview_reason')}[/dim]")
    console.print()

    choice = (selection or "").strip()
    if not choice:
        choice = Prompt.ask("Enter `0` for auto, a model number, or a model name", default="")
    if not choice:
        return
    if choice.lower() == "auto" or choice == "0":
        selected_name = "auto"
    elif choice.isdigit() and 0 < int(choice) <= len(models):
        selected_name = models[int(choice) - 1]["name"]
    else:
        selected_name = choice

    try:
        result = session.switch_model(selected_name)
        config.update(model=selected_name)
        console.print(f"\n  [success]✅ Remote model: {result.get('display_model', selected_name)}[/success]\n")
    except RemoteAPIError as exc:
        console.print(f"\n  [error]❌ Failed to switch remote model: {exc}[/error]\n")


def handle_hybrid_models(agent: Agent, config: NeuDevConfig, selection: str | None = None) -> None:
    """List or switch hosted models used by the hybrid runtime."""
    try:
        models = agent.llm.list_models()
    except LLMError as exc:
        console.print(f"\n  [error]❌ Error listing hosted models: {exc}[/error]\n")
        return
    if not models:
        console.print("\n  [warning]⚠️  No hosted models are available.[/warning]\n")
        return

    console.print()
    table = Table(
        title="[bold bright_cyan]🌩️ Hybrid Hosted Models[/bold bright_cyan]",
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        padding=(0, 1),
        expand=False,
        width=min(console.width, 72),
    )
    table.add_column("#", style="dim", width=3, justify="center")
    table.add_column("Model", style="bold white")
    table.add_column("Size", style="dim", justify="right")
    table.add_column("Role", style="dim")
    table.add_column("Active", justify="center")

    preview_model, preview_reason = agent.llm.preview_auto_model()
    auto_active = "✅" if agent.llm.model == "auto" else "  "
    table.add_row(
        "0",
        "auto",
        "-",
        f"Task-routed -> {preview_model or 'No model available'}",
        auto_active,
        style="bold bright_green" if auto_active.strip() else "",
    )

    for index, model in enumerate(models, 1):
        size_mb = model["size"] / (1024 * 1024)
        size_str = f"{size_mb:.0f} MB" if size_mb < 1024 else f"{size_mb / 1024:.1f} GB"
        active = "✅" if model.get("active") else "  "
        table.add_row(
            str(index),
            model["name"],
            size_str,
            model.get("role", ""),
            active,
            style="bold bright_green" if active.strip() else "",
        )
    console.print(table)
    console.print(f"  [dim]Hosted inference endpoint: {config.api_base_url or '(unset)'}[/dim]")
    console.print(f"  [dim]Auto routing: {preview_reason}[/dim]")
    console.print()

    choice = (selection or "").strip()
    if not choice:
        choice = Prompt.ask("Enter `0` for auto, a model number, or a model name", default="")
    if not choice:
        return
    if choice.lower() == "auto" or choice == "0":
        selected_name = "auto"
    elif choice.isdigit() and 0 < int(choice) <= len(models):
        selected_name = models[int(choice) - 1]["name"]
    else:
        selected_name = choice

    try:
        agent.llm.switch_model(selected_name)
        agent.refresh_context()
        console.print(f"\n  [success]✅ Hybrid model mode: {agent.llm.get_display_model()}[/success]\n")
    except LLMError as exc:
        console.print(f"\n  [error]❌ Failed to switch hosted model: {exc}[/error]\n")


def handle_local_config(agent: Agent) -> None:
    """Render local config."""
    config = agent.config
    workspace_info = agent.context.analyze()
    command_policy = getattr(agent, "_command_policy_display", "unknown")
    console.print()
    table = Table(
        title="[bold bright_cyan]⚙️  Local Configuration[/bold bright_cyan]",
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        padding=(0, 2),
        expand=False,
        width=min(console.width, 64),
    )
    table.add_column("Setting", style="bold white")
    table.add_column("Value", style="bright_cyan")
    table.add_row("Runtime", "local")
    table.add_row("Model", agent.llm.get_display_model())
    table.add_row("Ollama Host", config.ollama_host)
    table.add_row("Agent Mode", config.agent_mode)
    table.add_row("Reply Language", config.response_language)
    table.add_row("Auto Permission", "ON" if agent.permissions.auto_approve else "OFF")
    table.add_row("Command Policy", command_policy)
    table.add_row("Workspace Type", workspace_info.get("project_type", "unknown"))
    table.add_row("Tech Stack", ", ".join(workspace_info.get("technologies", [])[:4]) or "unknown")
    table.add_row("Show Thinking", "ON" if config.show_thinking else "OFF")
    console.print(table)
    console.print()


def handle_remote_config(session: RemoteSessionClient, config: NeuDevConfig) -> None:
    """Render remote session config."""
    try:
        remote = session.get_config()
    except RemoteAPIError as exc:
        console.print(f"\n  [error]❌ Failed to fetch remote config: {exc}[/error]\n")
        return

    console.print()
    table = Table(
        title="[bold bright_cyan]⚙️  Remote Session Configuration[/bold bright_cyan]",
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        padding=(0, 2),
        expand=False,
        width=min(console.width, 72),
    )
    table.add_column("Setting", style="bold white")
    table.add_column("Value", style="bright_cyan")
    table.add_row("Runtime", "remote")
    table.add_row("API Base URL", config.api_base_url or "(unset)")
    table.add_row("Remote Workspace", remote.get("workspace", session.workspace))
    table.add_row("Model", remote.get("model", config.model))
    table.add_row("Agent Mode", remote.get("agent_mode", config.agent_mode))
    table.add_row("Reply Language", remote.get("response_language", config.response_language))
    table.add_row("Auto Permission", "ON" if remote.get("auto_permission") else "OFF")
    table.add_row("Hosted Command Policy", remote.get("command_policy", "unknown"))
    table.add_row("Show Thinking", "ON" if remote.get("show_thinking") else "OFF")
    table.add_row("Stream Transport", config.stream_transport)
    table.add_row("WebSocket URL", config.websocket_base_url or "(auto)")
    table.add_row("Project Type", remote.get("project_type", "unknown"))
    table.add_row("Tech Stack", ", ".join(remote.get("technologies", [])[:4]) or "unknown")
    console.print(table)
    console.print()


def handle_hybrid_config(agent: Agent, config: NeuDevConfig) -> None:
    """Render hybrid runtime config."""
    workspace_info = agent.context.analyze()
    command_policy = getattr(agent, "_command_policy_display", "unknown")
    console.print()
    table = Table(
        title="[bold bright_cyan]⚙️  Hybrid Configuration[/bold bright_cyan]",
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        padding=(0, 2),
        expand=False,
        width=min(console.width, 78),
    )
    table.add_column("Setting", style="bold white")
    table.add_column("Value", style="bright_cyan")
    table.add_row("Runtime", "hybrid")
    table.add_row("Local Workspace", agent.workspace)
    table.add_row("Hosted Inference API", config.api_base_url or "(unset)")
    table.add_row("Model", agent.llm.get_display_model())
    table.add_row("Agent Mode", config.agent_mode)
    table.add_row("Reply Language", config.response_language)
    table.add_row("Auto Permission", "ON" if agent.permissions.auto_approve else "OFF")
    table.add_row("Command Policy", command_policy)
    table.add_row("Secret Redaction", "ON" if config.hybrid_redact_secrets else "OFF")
    table.add_row("Payload Limit", f"{config.hybrid_max_payload_bytes} bytes")
    table.add_row("Workspace Type", workspace_info.get("project_type", "unknown"))
    table.add_row("Tech Stack", ", ".join(workspace_info.get("technologies", [])[:4]) or "unknown")
    table.add_row("Show Thinking", "ON" if config.show_thinking else "OFF")
    console.print(table)
    console.print()


def handle_remote_sessions(client: RemoteNeuDevClient) -> None:
    """List resumable hosted sessions."""
    try:
        payload = client.list_sessions()
    except RemoteAPIError as exc:
        console.print(f"\n  [error]❌ Failed to fetch hosted sessions: {exc}[/error]\n")
        return
    print_remote_sessions_table(payload.get("sessions", []))


def handle_remote_language(session: RemoteSessionClient, config: NeuDevConfig, selection: str | None = None) -> None:
    """Set remote reply language."""
    language = (selection or "").strip() or Prompt.ask(
        "Enter reply language (for example: English, Hindi)",
        default=config.response_language,
    )
    if not language:
        return
    try:
        session.update_config(response_language=language)
        config.update(response_language=language)
        console.print(f"\n  [success]✅ Remote reply language set to: {language}[/success]\n")
    except (RemoteAPIError, ValueError) as exc:
        console.print(f"\n  [error]❌ Failed to set remote language: {exc}[/error]\n")


def handle_local_language(agent: Agent, selection: str | None = None) -> None:
    """Set local reply language."""
    language = (selection or "").strip() or Prompt.ask(
        "Enter reply language (for example: English, Hindi)",
        default=agent.config.response_language,
    )
    if not language:
        return
    agent.config.update(response_language=language)
    agent.refresh_context()
    console.print(f"\n  [success]✅ Reply language set to: {language}[/success]\n")


def handle_remote_agents(session: RemoteSessionClient, config: NeuDevConfig, selection: str | None = None) -> None:
    """Set remote agent mode."""
    mode = (selection or "").strip().lower() or Prompt.ask(
        "Choose agent mode (`single`, `team`, `parallel`)",
        default=config.agent_mode,
    )
    if not mode:
        return
    try:
        session.update_config(agent_mode=mode)
        config.update(agent_mode=mode)
        console.print(f"\n  [success]✅ Remote agent mode: {mode}[/success]\n")
    except (RemoteAPIError, ValueError) as exc:
        console.print(f"\n  [error]❌ Failed to set remote agent mode: {exc}[/error]\n")


def handle_local_agents(agent: Agent, selection: str | None = None) -> None:
    """Set local agent mode."""
    mode = (selection or "").strip().lower() or Prompt.ask(
        "Choose agent mode (`single`, `team`, `parallel`)",
        default=agent.config.agent_mode,
    )
    if not mode:
        return
    try:
        agent.config.update(agent_mode=mode)
        console.print(f"\n  [success]✅ Agent mode: {agent.config.agent_mode}[/success]\n")
    except ValueError as exc:
        console.print(f"\n  [error]❌ {exc}[/error]\n")


def handle_thinking(config: NeuDevConfig) -> None:
    """Toggle local thinking display."""
    config.update(show_thinking=not config.show_thinking)
    state = "ON" if config.show_thinking else "OFF"
    console.print(f"\n  [success]🧠 Thinking display: {state}[/success]\n")


def handle_remote_thinking(session: RemoteSessionClient, config: NeuDevConfig) -> None:
    """Toggle hosted thinking display."""
    next_value = not config.show_thinking
    try:
        session.update_config(show_thinking=next_value)
        config.update(show_thinking=next_value)
        state = "ON" if next_value else "OFF"
        console.print(f"\n  [success]🧠 Remote thinking display: {state}[/success]\n")
    except RemoteAPIError as exc:
        console.print(f"\n  [error]❌ Failed to toggle remote thinking display: {exc}[/error]\n")


def process_local_user_input(agent: Agent, user_input: str, *, stop_event=None) -> str | None:
    """Process a local user message."""
    runtime_label = "hybrid" if agent.config.runtime_mode == "hybrid" else "local"
    command_policy_display = getattr(agent, "_command_policy_display", "unknown")
    trace = ExecutionTraceState()
    console.print()
    render_turn_header(
        user_input,
        title="Execution Trace",
        metadata=[
            ("Runtime", runtime_label),
            ("Workspace", _truncate_cli_value(agent.workspace, limit=72)),
            ("Model", agent.llm.get_display_model()),
            ("Orchestration", agent.config.agent_mode),
            ("Command Policy", command_policy_display),
        ],
    )
    console.print(
        "  [dim]NeuDev will show each phase, tool action, and verification step below in real time. "
        "Use /stop to request cancellation. While work is active, use `/queue add <message>` for intentional follow-ups.[/dim]"
    )
    console.print()
    thinking_parts: list[str] = []
    response = ""

    def handle_thinking(text: str) -> None:
        thinking_parts.append(text)
        _record_trace_thinking(trace, text)

    def handle_text(text: str) -> None:
        _record_trace_response(trace, text)

    def run_turn() -> None:
        nonlocal response
        render_phase_event("understand", "request + workspace context", trace=trace)
        response = agent.process_message(
            user_input,
            on_status=lambda tool_name, payload: render_tool_event(tool_name, payload, trace=trace),
            on_thinking=handle_thinking,
            on_text=handle_text,
            on_phase=lambda phase, model_name: render_phase_event(phase, model_name, trace=trace),
            on_workspace_change=lambda changes: render_workspace_change(changes, trace=trace),
            on_plan_update=lambda plan, conventions: render_plan_panel(
                {"plan": [dict(item) for item in plan], "conventions": list(conventions)},
                trace=trace,
            ),
            on_progress=lambda payload: _record_trace_progress(trace, payload),
            stop_event=stop_event,
        )

    try:
        if should_use_live_trace_panel():
            _run_live_trace_panel(trace, run_turn)
        else:
            run_turn()
    except LLMError as exc:
        console.print(
            Panel(
                f"[bold red]❌ Error[/bold red]\n\n[white]{exc}[/white]",
                border_style="red",
                title="[bold red]⚠️  Something went wrong[/bold red]",
                padding=(1, 2),
                expand=False,
            )
        )
        console.print()
        return None
    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]❌ Unexpected Error[/bold red]\n\n[white]{type(exc).__name__}: {exc}[/white]",
                border_style="red",
                title="[bold red]⚠️  Something went wrong[/bold red]",
                padding=(1, 2),
                expand=False,
            )
        )
        console.print()
        return None

    render_thinking("".join(thinking_parts).strip())
    render_trace_summary(trace)
    render_agent_routing(
        agent.config,
        agent_team={
            "planner": agent.last_agent_team.planner,
            "executor": agent.last_agent_team.executor,
            "reviewer": agent.last_agent_team.reviewer,
        }
        if agent.last_agent_team
        else None,
        last_used_model=agent.llm.last_used_model,
        last_route_reason=agent.llm.last_route_reason,
    )
    render_response_panel(response)
    return response


def _summarize_queue_item(text: str, limit: int = 72) -> str:
    """Render queued user input on one compact line."""
    return _truncate_cli_value(str(text), limit=limit)


def _render_queue_panel(
    active: str | None,
    pending: list[str],
    *,
    title: str,
    empty_message: str,
) -> None:
    """Render an active-task and pending-task queue panel."""
    if not active and not pending:
        console.print(f"\n  [dim]{empty_message}[/dim]\n")
        return

    lines: list[str] = []
    if active:
        lines.append("[bold bright_yellow]Active[/bold bright_yellow]")
        lines.append(f"1. {_summarize_queue_item(active)}")
    if pending:
        if lines:
            lines.append("")
        lines.append("[bold bright_cyan]Pending[/bold bright_cyan]")
        for index, item in enumerate(pending[:4], 1):
            lines.append(f"{index}. {_summarize_queue_item(item)}")
        if len(pending) > 4:
            lines.append(f"[dim]... {len(pending) - 4} more queued tasks[/dim]")

    console.print(
        Panel(
            "\n".join(lines),
            border_style="bright_blue",
            title=title,
            padding=(0, 1),
            expand=False,
            width=min(console.width, 78),
        )
    )
    console.print()


class QueuedLocalTaskRunner:
    """Run local or hybrid agent turns sequentially while keeping the prompt active."""

    def __init__(self, agent: Agent, *, processor=None) -> None:
        self.agent = agent
        self._processor = processor or process_local_user_input
        self._pending: deque[str] = deque()
        self._condition = threading.Condition()
        self._shutdown = False
        self._current_message: str | None = None
        self._current_stop_event: threading.Event | None = None
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="neudev-local-task-runner",
            daemon=True,
        )
        self._worker.start()

    def submit(self, user_input: str) -> int:
        """Queue a user task and return its pending position, or 0 if it starts immediately."""
        message = user_input.strip()
        if not message:
            return 0
        with self._condition:
            was_busy = self._current_message is not None or bool(self._pending)
            self._pending.append(message)
            position = len(self._pending)
            self._condition.notify()
            return position if was_busy else 0

    def is_busy(self) -> bool:
        """Return True when a task is currently running."""
        with self._condition:
            return self._current_message is not None

    def pending_count(self) -> int:
        """Return the number of queued tasks that have not started yet."""
        with self._condition:
            return len(self._pending)

    def clear_pending(self) -> int:
        """Drop queued follow-up tasks that have not started yet."""
        with self._condition:
            cleared = len(self._pending)
            self._pending.clear()
            self._condition.notify_all()
            return cleared

    def snapshot(self) -> tuple[str | None, list[str]]:
        """Return the active task and queued follow-up tasks."""
        with self._condition:
            return self._current_message, list(self._pending)

    def request_stop(self) -> bool:
        """Ask the active task to stop at the next safe checkpoint."""
        with self._condition:
            stop_event = self._current_stop_event
        if stop_event is None:
            return False
        stop_event.set()
        return True

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        """Block until the active task and queue are empty."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while self._current_message is not None or self._pending:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def shutdown(
        self,
        *,
        cancel_pending: bool = False,
        stop_current: bool = False,
        join_timeout: float = 1.0,
    ) -> None:
        """Stop the worker thread and optionally clear queued or active work."""
        with self._condition:
            self._shutdown = True
            if cancel_pending:
                self._pending.clear()
            stop_event = self._current_stop_event
            self._condition.notify_all()
        if stop_current and stop_event is not None:
            stop_event.set()
        self._worker.join(timeout=join_timeout)

    def _worker_loop(self) -> None:
        """Consume queued tasks one at a time."""
        while True:
            should_exit = False
            with self._condition:
                while not self._pending and not self._shutdown:
                    self._condition.wait()
                if self._shutdown and not self._pending:
                    return
                if not self._pending:
                    continue
                message = self._pending.popleft()
                stop_event = threading.Event()
                self._current_message = message
                self._current_stop_event = stop_event

            try:
                self._processor(self.agent, message, stop_event=stop_event)
            finally:
                with self._condition:
                    self._current_message = None
                    self._current_stop_event = None
                    remaining = len(self._pending)
                    should_exit = self._shutdown and not self._pending
                    self._condition.notify_all()
                if remaining:
                    console.print(f"\n  [dim]🕒 Pending queue: {remaining} task(s) remaining.[/dim]\n")
            if should_exit:
                return


def render_local_queue(runner: QueuedLocalTaskRunner) -> None:
    """Show the active local task and queued follow-up prompts."""
    active, pending = runner.snapshot()
    _render_queue_panel(
        active,
        pending,
        title="[bold bright_blue]Task Queue[/bold bright_blue]",
        empty_message="No active or pending local tasks.",
    )


def handle_local_stop(
    runner: QueuedLocalTaskRunner,
    permission_manager: InteractivePermissionManager | None = None,
) -> None:
    """Request cancellation of the current local or hybrid task."""
    stop_requested = runner.request_stop()
    pending_cleared = permission_manager.cancel_pending() if permission_manager is not None else False
    if stop_requested:
        message = "Stop requested. NeuDev will halt after the current model/tool step returns."
        if pending_cleared:
            message += " The pending permission was denied so the task can exit."
        console.print(
            f"\n  [warning]⏹ {message}[/warning]\n"
        )
    elif pending_cleared:
        console.print("\n  [warning]⏹ Pending permission denied.[/warning]\n")
    else:
        console.print("\n  [dim]📭 No active local task to stop.[/dim]\n")


def handle_local_permission_input(
    permission_manager: InteractivePermissionManager,
    user_input: str,
) -> bool:
    """Resolve an in-flight local permission request from the main prompt."""
    pending = permission_manager.pending_request()
    if pending is None:
        return False

    raw = user_input.strip()
    warning = (
        "\n  [warning]⚠️  A permission request is waiting. Use `y`, `a`, `all`, `n`, "
        "`/approve [once|tool|all]`, `/deny`, or `/stop`.[/warning]\n"
    )
    decision: str | None

    if raw.lower().startswith("/approve"):
        parts = raw.split(maxsplit=1)
        scope_text = parts[1].strip() if len(parts) > 1 else "once"
        decision = normalize_permission_choice(scope_text)
        if decision is None:
            console.print(
                "\n  [warning]⚠️  Invalid approval scope. Use `/approve`, `/approve tool`, `/approve all`, or `/deny`.[/warning]\n"
            )
            return True
    elif raw.lower().startswith("/deny"):
        decision = PERMISSION_CHOICE_DENY
    else:
        decision = normalize_permission_choice(raw)
        if decision is None:
            console.print(warning)
            return True

    if not permission_manager.resolve_pending(decision):
        console.print("\n  [dim]📭 No pending permission request.[/dim]\n")
        return True

    if decision == PERMISSION_CHOICE_DENY:
        console.print(f"\n  [warning]✗ Denied `{pending.tool_name}`.[/warning]\n")
    elif decision == PERMISSION_CHOICE_TOOL:
        console.print(f"\n  [success]✓ Approved `{pending.tool_name}` for this session.[/success]\n")
    elif decision == PERMISSION_CHOICE_ALL:
        console.print("\n  [success]✓ Approved all destructive actions for this session.[/success]\n")
    else:
        console.print(f"\n  [success]✓ Approved `{pending.tool_name}` once.[/success]\n")
    return True


def handle_remote_permission_input(
    permission_manager: InteractiveRemoteApprovalManager,
    user_input: str,
) -> bool:
    """Resolve an in-flight hosted permission request from the main prompt."""
    pending = permission_manager.pending_request()
    if pending is None:
        return False

    raw = user_input.strip()
    warning = (
        "\n  [warning]A hosted permission request is waiting. Use `y`, `a`, `all`, `n`, "
        "`/approve [once|tool|all]`, `/deny`, or `/stop`.[/warning]\n"
    )
    decision: str | None

    if raw.lower().startswith("/approve"):
        parts = raw.split(maxsplit=1)
        scope_text = parts[1].strip() if len(parts) > 1 else "once"
        decision = normalize_permission_choice(scope_text)
        if decision is None:
            console.print(
                "\n  [warning]Invalid approval scope. Use `/approve`, `/approve tool`, `/approve all`, or `/deny`.[/warning]\n"
            )
            return True
    elif raw.lower().startswith("/deny"):
        decision = PERMISSION_CHOICE_DENY
    else:
        decision = normalize_permission_choice(raw)
        if decision is None:
            console.print(warning)
            return True

    if not permission_manager.resolve_pending(decision):
        console.print("\n  [dim]No pending hosted permission request.[/dim]\n")
        return True

    if decision == PERMISSION_CHOICE_DENY:
        console.print(f"\n  [warning]Denied hosted action `{pending.tool_name}`.[/warning]\n")
    elif decision == PERMISSION_CHOICE_TOOL:
        console.print(f"\n  [success]Approved hosted action `{pending.tool_name}` for this session.[/success]\n")
    elif decision == PERMISSION_CHOICE_ALL:
        console.print("\n  [success]Approved all hosted destructive actions for this session.[/success]\n")
    else:
        console.print(f"\n  [success]Approved hosted action `{pending.tool_name}` once.[/success]\n")
    return True


def _render_busy_command_warning(command: str) -> None:
    """Explain why a slash command is blocked while work is in progress."""
    console.print(
        f"\n  [warning]⚠️  {command} is locked while a task is running. Use `/queue`, `/queue add <message>`, `/queue clear`, `/stop`, or wait for completion.[/warning]\n"
    )


def _render_busy_text_warning(user_input: str, *, hosted: bool = False) -> None:
    """Warn when plain text arrives while work is already running."""
    scope = "hosted turn" if hosted else "task"
    preview = _truncate_cli_value(user_input, limit=72)
    console.print(
        "\n"
        f"  [warning]⚠️  Ignored plain-text input while a {scope} is running: `{preview}`.\n"
        "  Use `/queue add <message>` to queue an intentional follow-up, `/queue clear` to drop pending work, or `/stop` to cancel.[/warning]\n"
    )


def _handle_queue_command(runner, arg: str, *, hosted: bool, render_queue) -> None:
    """Handle `/queue`, `/queue add`, and `/queue clear`."""
    action = (arg or "").strip()
    label = "hosted task" if hosted else "task"
    title_label = "Hosted turn" if hosted else "Task"
    if not action:
        render_queue(runner)
        return

    parts = action.split(maxsplit=1)
    subcommand = parts[0].lower()
    remainder = parts[1].strip() if len(parts) > 1 else ""

    if subcommand == "add":
        if not remainder:
            console.print(
                "\n  [warning]⚠️  Missing message. Use `/queue add <message>` to queue an explicit follow-up.[/warning]\n"
            )
            return
        position = runner.submit(remainder)
        if position:
            console.print(
                f"\n  [success]🕒 Queued {label} #{position}: {_summarize_queue_item(remainder)}[/success]\n"
            )
        else:
            console.print(f"\n  [success]▶ {title_label} submitted immediately from `/queue add`.[/success]\n")
        return

    if subcommand == "clear":
        cleared = runner.clear_pending()
        if cleared:
            console.print(f"\n  [success]🧹 Cleared {cleared} pending {label}(s).[/success]\n")
        else:
            console.print(f"\n  [dim]📭 No pending {label}s to clear.[/dim]\n")
        return

    console.print(
        "\n  [warning]⚠️  Unknown `/queue` action. Use `/queue`, `/queue add <message>`, or `/queue clear`.[/warning]\n"
    )


def handle_local_queue_command(runner: "QueuedLocalTaskRunner", arg: str) -> None:
    """Handle queue inspection and management for local or hybrid runs."""
    _handle_queue_command(runner, arg, hosted=False, render_queue=render_local_queue)


def handle_remote_queue_command(runner: "QueuedRemoteTaskRunner", arg: str) -> None:
    """Handle queue inspection and management for hosted runs."""
    _handle_queue_command(runner, arg, hosted=True, render_queue=render_remote_queue)


def run_local_agent_loop(agent: Agent, config: NeuDevConfig, *, runtime_mode: str) -> None:
    """Run the interactive loop for local and hybrid runtimes."""
    prompt_session = build_prompt_session()
    runner = QueuedLocalTaskRunner(agent)
    permission_manager = agent.permissions if isinstance(agent.permissions, InteractivePermissionManager) else None
    safe_busy_commands = {"/help", "/queue", "/stop", "/version", "/exit", "/quit"}

    try:
        while True:
            try:
                with patch_stdout(raw=True):
                    user_input = prompt_session.prompt([("class:prompt", "neudev ❯ ")]).strip()
            except (KeyboardInterrupt, EOFError):
                if permission_manager is not None:
                    permission_manager.cancel_pending()
                if runner.is_busy() or runner.pending_count():
                    console.print("\n  [warning]⏹ Stopping the active task and clearing pending work...[/warning]\n")
                    runner.shutdown(cancel_pending=True, stop_current=True)
                console.print("\n  [dim]👋 Goodbye![/dim]\n")
                break
            if not user_input:
                continue

            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""
            has_active_work = runner.is_busy() or runner.pending_count() > 0

            if cmd in ("/exit", "/quit"):
                if permission_manager is not None:
                    permission_manager.cancel_pending()
                if has_active_work:
                    console.print("\n  [warning]⏹ Stopping the active task and clearing pending work...[/warning]\n")
                    runner.shutdown(cancel_pending=True, stop_current=True)
                handle_local_exit(agent)
                break
            if cmd == "/help":
                handle_help()
            elif cmd == "/queue":
                handle_local_queue_command(runner, arg)
            elif cmd == "/stop":
                handle_local_stop(runner, permission_manager)
            elif cmd == "/version":
                console.print(f"\n  [bold bright_cyan]⚡ {__app_name__}[/bold bright_cyan] [dim]v{__version__}[/dim]\n")
            elif permission_manager is not None and permission_manager.pending_request() is not None:
                if handle_local_permission_input(permission_manager, user_input):
                    continue
            elif cmd in {"/approve", "/deny"}:
                console.print("\n  [dim]📭 No pending permission request.[/dim]\n")
            elif has_active_work and user_input.startswith("/") and cmd not in safe_busy_commands:
                _render_busy_command_warning(cmd)
            elif has_active_work:
                _render_busy_text_warning(user_input)
            elif cmd == "/models":
                if runtime_mode == "hybrid":
                    handle_hybrid_models(agent, config, arg or None)
                else:
                    handle_local_models(agent, arg or None)
            elif cmd == "/sessions" and runtime_mode == "hybrid":
                console.print("\n  [dim]📭 Hybrid runtime keeps history locally, so hosted sessions are not used.[/dim]\n")
            elif cmd == "/clear":
                agent.clear_history()
                console.print("\n  [success]✅ Conversation history cleared.[/success]\n")
            elif cmd == "/remove":
                result = agent.session.undo_last_change()
                if result:
                    agent.refresh_context()
                    agent.context.mark_workspace_state()
                    console.print(f"\n  [success]✅ {result}[/success]\n")
                else:
                    console.print("\n  [dim]📭 Nothing to undo.[/dim]\n")
            elif cmd == "/history":
                print_history_table(
                    [
                        {
                            "action": item.action,
                            "target": item.target,
                            "timestamp": item.timestamp,
                            "details": item.details,
                        }
                        for item in agent.session.actions
                    ]
                )
            elif cmd == "/config":
                if runtime_mode == "hybrid":
                    handle_hybrid_config(agent, config)
                else:
                    handle_local_config(agent)
            elif cmd == "/agents":
                handle_local_agents(agent, arg or None)
            elif cmd == "/language":
                handle_local_language(agent, arg or None)
            elif cmd == "/thinking":
                handle_thinking(config)
                agent.config.show_thinking = config.show_thinking
            elif cmd == "/explain":
                handle_explain(agent, arg)
            elif cmd == "/refactor":
                handle_refactor(agent, arg)
            elif cmd == "/test":
                handle_test(agent, arg)
            elif cmd == "/commit":
                handle_commit(agent, arg)
            elif cmd == "/summarize":
                handle_summarize(agent, arg)
            elif cmd == "/close" and runtime_mode == "hybrid":
                console.print("\n  [dim]📭 Hybrid runtime has no hosted workspace session to close. Use /exit instead.[/dim]\n")
            elif user_input.startswith("/"):
                console.print(f"\n  [warning]⚠️  Unknown command: {user_input}[/warning]\n")
            else:
                queue_position = runner.submit(user_input)
                if queue_position:
                    console.print(
                        f"\n  [dim]🕒 Queued pending task #{queue_position}. It will run after the current task.[/dim]\n"
                    )
    finally:
        if permission_manager is not None:
            permission_manager.cancel_pending()
        runner.shutdown(cancel_pending=False, stop_current=False)


def _consume_remote_stream(
    session: RemoteSessionClient,
    config: NeuDevConfig,
    stream,
    *,
    approval_manager: InteractiveRemoteApprovalManager | None = None,
    trace: ExecutionTraceState | None = None,
) -> dict[str, object] | None:
    """Render streamed remote events and return the final payload."""
    final_payload = None

    for event in stream:
        event_name = event.get("event", "")
        payload = event.get("data", {}) or {}

        if event_name == "workspace_change":
            render_workspace_change(payload, trace=trace)
        elif event_name == "phase":
            render_phase_event(payload.get("phase", ""), payload.get("model", ""), trace=trace)
        elif event_name == "status":
            render_tool_event(payload.get("tool", ""), payload.get("args", {}), trace=trace)
        elif event_name == "plan_update":
            render_plan_panel(payload, trace=trace)
        elif event_name == "progress":
            _record_trace_progress(trace, payload)
        elif event_name == "thinking":
            _record_trace_thinking(trace, payload.get("chunk", ""))
        elif event_name == "text":
            _record_trace_response(trace, payload.get("chunk", ""))
        elif event_name == "approval_required":
            if approval_manager is None:
                console.print()
                decision = ask_remote_permission(payload.get("tool_name", "tool"), payload.get("message", ""))
            else:
                decision = approval_manager.request_approval(
                    payload["approval_id"],
                    payload.get("tool_name", "tool"),
                    payload.get("message", ""),
                )
            approved = decision != PERMISSION_CHOICE_DENY
            if decision == PERMISSION_CHOICE_ALL:
                config.apply_runtime_updates(persist=False, auto_permission=True)
            return _consume_remote_stream(
                session,
                config,
                session.stream_approval(
                    payload["approval_id"],
                    approved,
                    scope=decision if approved else None,
                    transport=config.stream_transport,
                ),
                approval_manager=approval_manager,
                trace=trace,
            )
        elif event_name == "error":
            render_remote_error(payload)
            return None
        elif event_name == "result":
            final_payload = payload

    return final_payload


def process_remote_user_input(
    session: RemoteSessionClient,
    config: NeuDevConfig,
    user_input: str,
    *,
    approval_manager: InteractiveRemoteApprovalManager | None = None,
) -> None:
    """Process a remote user message."""
    remote_snapshot = session.config_snapshot or {}
    trace = ExecutionTraceState()
    console.print()
    render_turn_header(
        user_input,
        title="Hosted Execution Trace",
        metadata=[
            ("Runtime", "remote"),
            ("Session", session.session_id),
            ("Workspace", _truncate_cli_value(remote_snapshot.get("workspace", session.workspace), limit=72)),
            ("Model", remote_snapshot.get("model", config.model)),
            ("Orchestration", remote_snapshot.get("agent_mode", config.agent_mode)),
            ("Streaming", config.stream_transport),
            ("Hosted Policy", remote_snapshot.get("command_policy", "unknown")),
        ],
    )
    console.print(
        "  [dim]Hosted plan, tool, and verification events appear below in real time. "
        "Use /stop to interrupt the active turn. While work is active, use `/queue add <message>` for intentional follow-ups.[/dim]"
    )
    console.print()
    payload: dict[str, object] | None = None

    def run_turn() -> None:
        nonlocal payload
        render_phase_event("understand", "request + hosted session context", trace=trace)
        payload = _consume_remote_stream(
            session,
            config,
            session.stream_message(user_input, transport=config.stream_transport),
            approval_manager=approval_manager,
            trace=trace,
        )

    try:
        if should_use_live_trace_panel():
            _run_live_trace_panel(trace, run_turn)
        else:
            run_turn()
    except RemoteAPIError as exc:
        console.print(
            Panel(
                f"[bold red]❌ Remote API Error[/bold red]\n\n[white]{exc}[/white]",
                border_style="red",
                title="[bold red]⚠️  Remote request failed[/bold red]",
                padding=(1, 2),
                expand=False,
            )
        )
        console.print()
        return

    if not payload:
        return
    if payload.get("status") == "denied":
        console.print(f"  [warning]⚠️  {payload.get('message', 'Permission denied.')}[/warning]\n")
        return
    if payload.get("status") == "error":
        render_remote_error(payload)
        return

    render_thinking(payload.get("thinking", ""))
    render_trace_summary(trace)
    render_agent_routing(
        config,
        agent_team=payload.get("agent_team"),
        last_used_model=payload.get("last_used_model"),
        last_route_reason=payload.get("last_route_reason", ""),
    )
    render_response_panel(payload.get("response") or payload.get("streamed_response", ""))


class QueuedRemoteTaskRunner:
    """Run remote turns sequentially while keeping the hosted prompt interactive."""

    def __init__(
        self,
        session: RemoteSessionClient,
        config: NeuDevConfig,
        approval_manager: InteractiveRemoteApprovalManager,
        *,
        processor=None,
    ) -> None:
        self.session = session
        self.config = config
        self.approval_manager = approval_manager
        self._processor = processor or process_remote_user_input
        self._pending: deque[str] = deque()
        self._condition = threading.Condition()
        self._shutdown = False
        self._current_message: str | None = None
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="neudev-remote-task-runner",
            daemon=True,
        )
        self._worker.start()

    def submit(self, user_input: str) -> int:
        """Queue a hosted turn and return its queue position, or 0 if it starts now."""
        message = user_input.strip()
        if not message:
            return 0
        with self._condition:
            was_busy = self._current_message is not None or bool(self._pending)
            self._pending.append(message)
            position = len(self._pending)
            self._condition.notify()
            return position if was_busy else 0

    def is_busy(self) -> bool:
        """Return True when a hosted turn is currently running or waiting for approval."""
        with self._condition:
            return self._current_message is not None

    def pending_count(self) -> int:
        """Return the number of queued hosted turns waiting to run."""
        with self._condition:
            return len(self._pending)

    def clear_pending(self) -> int:
        """Drop queued hosted turns that have not started yet."""
        with self._condition:
            cleared = len(self._pending)
            self._pending.clear()
            self._condition.notify_all()
            return cleared

    def snapshot(self) -> tuple[str | None, list[str]]:
        """Return the active hosted turn and queued follow-up turns."""
        with self._condition:
            return self._current_message, list(self._pending)

    def request_stop(self) -> dict[str, object]:
        """Cancel the blocked approval or request stop for the active hosted turn."""
        pending_approval = self.approval_manager.pending_request()
        if pending_approval is not None:
            self.approval_manager.cancel_pending()
            return {
                "status": "approval_denied",
                "message": f"Denied pending hosted approval for {pending_approval.tool_name}.",
                "approval_id": pending_approval.approval_id,
            }

        with self._condition:
            if self._current_message is None:
                return {"status": "idle", "message": "No active hosted turn."}
        try:
            return self.session.request_stop()
        except RemoteAPIError as exc:
            return {"status": "error", "message": str(exc)}

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        """Block until the hosted turn and queue are empty."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while self._current_message is not None or self._pending:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def shutdown(
        self,
        *,
        cancel_pending: bool = False,
        stop_current: bool = False,
        join_timeout: float = 2.0,
    ) -> None:
        """Stop the worker and optionally clear queued or active hosted work."""
        with self._condition:
            self._shutdown = True
            if cancel_pending:
                self._pending.clear()
            self._condition.notify_all()
        if cancel_pending:
            self.approval_manager.cancel_pending()
        if stop_current:
            self.request_stop()
        self._worker.join(timeout=join_timeout)

    def _worker_loop(self) -> None:
        """Consume hosted turns one at a time."""
        while True:
            should_exit = False
            with self._condition:
                while not self._pending and not self._shutdown:
                    self._condition.wait()
                if self._shutdown and not self._pending:
                    return
                if not self._pending:
                    continue
                message = self._pending.popleft()
                self._current_message = message

            try:
                self._processor(
                    self.session,
                    self.config,
                    message,
                    approval_manager=self.approval_manager,
                )
            finally:
                with self._condition:
                    self._current_message = None
                    remaining = len(self._pending)
                    should_exit = self._shutdown and not self._pending
                    self._condition.notify_all()
                if remaining:
                    console.print(f"\n  [dim]Hosted queue: {remaining} task(s) remaining.[/dim]\n")
            if should_exit:
                return


def render_remote_queue(runner: QueuedRemoteTaskRunner) -> None:
    """Show the active hosted turn and queued follow-up requests."""
    active, pending = runner.snapshot()
    _render_queue_panel(
        active,
        pending,
        title="[bold bright_blue]Hosted Queue[/bold bright_blue]",
        empty_message="No active or pending hosted tasks.",
    )


def handle_remote_stop(runner: QueuedRemoteTaskRunner) -> None:
    """Request cancellation for the active hosted turn."""
    result = runner.request_stop()
    status = str(result.get("status", "error"))
    if status == "stop_requested":
        console.print("\n  [warning]Stop requested. The hosted turn will halt after the current model or tool step returns.[/warning]\n")
    elif status == "already_requested":
        console.print("\n  [warning]Stop was already requested for the active hosted turn.[/warning]\n")
    elif status == "approval_denied":
        console.print("\n  [warning]Pending hosted permission denied. The blocked turn will now finish cleanly.[/warning]\n")
    elif status == "awaiting_approval":
        console.print("\n  [warning]A hosted approval is still pending. Use `/approve`, `/deny`, or `/stop` again after it clears.[/warning]\n")
    elif status == "idle":
        console.print("\n  [dim]No active hosted turn to stop.[/dim]\n")
    else:
        console.print(f"\n  [error]Failed to stop hosted turn: {result.get('message', 'Unknown error')}[/error]\n")


def handle_local_exit(agent: Agent) -> None:
    """Finish a local session."""
    console.print()
    console.print(Rule("[bold bright_cyan]Session Ending[/bold bright_cyan]", style="bright_blue"))
    console.print()
    agent.session.get_summary()
    console.print("  [bold bright_green]👋 Thanks for using NeuDev![/bold bright_green]\n")


def handle_remote_exit(session: RemoteSessionClient, *, close: bool = False) -> None:
    """Finish or disconnect from a remote session."""
    console.print()
    console.print(Rule("[bold bright_cyan]Remote Session Ending[/bold bright_cyan]", style="bright_blue"))
    console.print()
    try:
        summary = session.get_summary()
    except RemoteAPIError as exc:
        console.print(f"  [error]❌ Failed to fetch remote summary: {exc}[/error]\n")
        return
    table = Table(
        title="[bold bright_cyan]📋 Remote Session Summary[/bold bright_cyan]",
        show_header=False,
        border_style="bright_blue",
        padding=(0, 2),
        expand=False,
        width=min(console.width, 60),
    )
    table.add_column("Label", style="bold cyan")
    table.add_column("Value", style="white")
    table.add_row("Session ID", session.session_id)
    table.add_row("Workspace", summary.get("workspace", ""))
    table.add_row("Messages", str(summary.get("messages_count", 0)))
    counts = summary.get("action_counts", {})
    table.add_row("Actions", ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none")
    console.print(table)
    console.print()
    if close:
        try:
            session.close()
        except RemoteAPIError as exc:
            console.print(f"  [error]❌ Failed to close hosted session: {exc}[/error]\n")
            return
        console.print("  [bold bright_green]👋 Remote NeuDev session closed.[/bold bright_green]\n")
        return

    console.print(
        "  [dim]Session preserved on the hosted server. Resume with "
        f"`neu run --runtime remote --session-id {session.session_id}`.[/dim]\n"
    )


def run_local_cli(config: NeuDevConfig, workspace: str | None = None) -> None:
    """Run the local interactive CLI."""
    workspace = workspace or os.getcwd()
    print_banner(config, workspace, runtime_label="local")
    try:
        with console.status("[bold bright_cyan]⏳ Initializing NeuDev...[/bold bright_cyan]", spinner="dots"):
            agent = Agent(config, workspace)
            permissions = InteractivePermissionManager()
            permissions.auto_approve = config.auto_permission
            agent.permissions = permissions
            agent.config.apply_runtime_updates(persist=False, runtime_mode="local")
            _, command_policy_display = apply_agent_command_policy(agent, config, "local")
    except OllamaConnectionError as exc:
        console.print(
            Panel(
                f"[bold red]Cannot connect to Ollama[/bold red]\n\n[white]{exc}[/white]\n\n"
                f"[dim]Make sure Ollama is running:[/dim]\n  [bold bright_green]ollama serve[/bold bright_green]",
                border_style="red",
                title="[bold red]❌ Connection Failed[/bold red]",
                padding=(1, 2),
                expand=False,
            )
        )
        return
    except (ModelNotFoundError, LLMError) as exc:
        console.print(f"\n  [error]❌ Failed to initialize local NeuDev: {exc}[/error]\n")
        return

    print_status_block(
        [
            ("✅", "Local agent ready", "success"),
            ("✅", f"Model: {agent.llm.get_display_model()}", "success"),
            ("✅", f"Orchestration: {config.agent_mode}", "success"),
            ("✅", f"Command Policy: {command_policy_display}", "success"),
            ("✅", f"Tools: {len(agent.tool_registry.get_all())} loaded", "success"),
        ]
    )
    console.print(Rule(style="bright_blue"))
    console.print()

    run_local_agent_loop(agent, config, runtime_mode="local")


def run_hybrid_cli(config: NeuDevConfig, workspace: str | None = None) -> None:
    """Run the hybrid CLI with local tools and hosted inference."""
    api_base_url, api_key = prompt_for_hosted_settings(config, runtime_mode="hybrid")
    config.api_base_url = api_base_url
    config.api_key = api_key
    workspace = workspace or os.getcwd()
    print_banner(config, workspace, runtime_label="hybrid")
    try:
        with console.status("[bold bright_cyan]🌩️ Connecting local agent to hosted inference...[/bold bright_cyan]", spinner="dots"):
            llm_client = HostedLLMClient(config, api_base_url, api_key)
            agent = Agent(config, workspace, llm_client=llm_client)
            permissions = InteractivePermissionManager()
            permissions.auto_approve = config.auto_permission
            agent.permissions = permissions
            config.update(runtime_mode="hybrid")
            _, command_policy_display = apply_agent_command_policy(agent, config, "hybrid")
    except (ModelNotFoundError, LLMError) as exc:
        console.print(f"\n  [error]❌ Failed to initialize hybrid NeuDev: {exc}[/error]\n")
        return

    print_status_block(
        [
            ("✅", f"Local workspace: {agent.workspace}", "success"),
            ("✅", f"Hosted inference: {api_base_url}", "success"),
            ("✅", f"Model: {agent.llm.get_display_model()}", "success"),
            ("✅", f"Orchestration: {config.agent_mode}", "success"),
            ("✅", f"Command Policy: {command_policy_display}", "success"),
            ("✅", f"Tools: {len(agent.tool_registry.get_all())} local", "success"),
        ]
    )
    redaction_state = "ON" if config.hybrid_redact_secrets else "OFF"
    console.print(
        f"  [dim]Privacy: local tools stay local. Secret redaction {redaction_state}. "
        f"Payload cap {config.hybrid_max_payload_bytes} bytes.[/dim]"
    )
    console.print()
    console.print(Rule(style="bright_blue"))
    console.print()

    run_local_agent_loop(agent, config, runtime_mode="hybrid")


def run_remote_cli(config: NeuDevConfig, workspace: str | None = None, session_id: str | None = None) -> None:
    """Run the remote interactive CLI."""
    api_base_url, api_key = prompt_for_hosted_settings(config, runtime_mode="remote")
    config.api_base_url = api_base_url
    config.api_key = api_key
    remote_workspace = workspace or config.remote_workspace or "."
    print_banner(config, remote_workspace, runtime_label="remote")

    websocket_base_url = os.environ.get("NEUDEV_WS_BASE_URL") or config.websocket_base_url or ""
    client = RemoteNeuDevClient(api_base_url, api_key, websocket_url=websocket_base_url)
    try:
        with console.status("[bold bright_cyan]🌐 Connecting to hosted NeuDev...[/bold bright_cyan]", spinner="dots"):
            client.health()
            status_label = "Hosted API connected"
            if session_id:
                session = RemoteSessionClient.resume(client, session_id)
                status_label = "Hosted session resumed"
            else:
                session = RemoteSessionClient.create(
                    client,
                    workspace=remote_workspace,
                    model=config.model,
                    language=config.response_language,
                    agent_mode=config.agent_mode,
                    auto_permission=config.auto_permission,
                )
            remote_config = session.get_config()
    except RemoteAPIError as exc:
        console.print(f"\n  [error]❌ Failed to initialize remote NeuDev: {exc}[/error]\n")
        return

    if not websocket_base_url and client.websocket_url:
        websocket_base_url = client.websocket_url
    config.update(
        runtime_mode="remote",
        remote_workspace=remote_config.get("workspace", remote_workspace),
        websocket_base_url=websocket_base_url,
    )
    stream_label = "websocket" if config.stream_transport == "websocket" else (
        "auto (websocket)" if client.websocket_url and config.stream_transport == "auto" else config.stream_transport
    )
    print_status_block(
        [
            ("✅", status_label, "success"),
            ("✅", f"Session ID: {session.session_id}", "success"),
            ("✅", f"Remote workspace: {remote_config.get('workspace', remote_workspace)}", "success"),
            ("✅", f"Model: {remote_config.get('model', config.model)}", "success"),
            ("✅", f"Orchestration: {remote_config.get('agent_mode', config.agent_mode)}", "success"),
            ("✅", f"Hosted Policy: {remote_config.get('command_policy', 'unknown')}", "success"),
            ("✅", f"Streaming: {stream_label}", "success"),
        ]
    )
    console.print(Rule(style="bright_blue"))
    console.print()

    prompt_session = build_prompt_session()
    approval_manager = InteractiveRemoteApprovalManager()
    runner = QueuedRemoteTaskRunner(session, config, approval_manager)
    safe_busy_commands = {"/help", "/queue", "/stop", "/version", "/exit", "/quit"}

    try:
        while True:
            try:
                with patch_stdout(raw=True):
                    user_input = prompt_session.prompt([("class:prompt", "neudev ❯ ")]).strip()
            except (KeyboardInterrupt, EOFError):
                approval_manager.cancel_pending()
                if runner.is_busy() or runner.pending_count():
                    console.print("\n  [warning]Stopping the active hosted turn and clearing pending work...[/warning]\n")
                    runner.shutdown(cancel_pending=True, stop_current=True)
                handle_remote_exit(session)
                break
            if not user_input:
                continue

            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""
            has_active_work = runner.is_busy() or runner.pending_count() > 0

            if cmd in ("/exit", "/quit"):
                approval_manager.cancel_pending()
                if has_active_work:
                    console.print("\n  [warning]Stopping the active hosted turn and clearing pending work...[/warning]\n")
                    runner.shutdown(cancel_pending=True, stop_current=True)
                handle_remote_exit(session)
                break
            if cmd == "/help":
                handle_help()
            elif cmd == "/queue":
                handle_remote_queue_command(runner, arg)
            elif cmd == "/stop":
                handle_remote_stop(runner)
            elif cmd == "/version":
                console.print(f"\n  [bold bright_cyan]⚡ {__app_name__}[/bold bright_cyan] [dim]v{__version__}[/dim]\n")
            elif approval_manager.pending_request() is not None:
                if handle_remote_permission_input(approval_manager, user_input):
                    continue
            elif cmd in {"/approve", "/deny"}:
                console.print("\n  [dim]No pending hosted permission request.[/dim]\n")
            elif has_active_work and user_input.startswith("/") and cmd not in safe_busy_commands:
                _render_busy_command_warning(cmd)
            elif has_active_work:
                _render_busy_text_warning(user_input, hosted=True)
            elif cmd == "/models":
                handle_remote_models(session, config, arg or None)
            elif cmd == "/sessions":
                handle_remote_sessions(client)
            elif cmd == "/clear":
                try:
                    session.clear_history()
                    console.print("\n  [success]✅ Remote conversation history cleared.[/success]\n")
                except RemoteAPIError as exc:
                    console.print(f"\n  [error]❌ Failed to clear remote history: {exc}[/error]\n")
            elif cmd == "/remove":
                try:
                    result = session.undo_last_change()
                    message = result.get("result") or "Nothing to undo."
                    console.print(f"\n  [success]✅ {message}[/success]\n")
                except RemoteAPIError as exc:
                    console.print(f"\n  [error]❌ Failed to undo remote change: {exc}[/error]\n")
            elif cmd == "/history":
                try:
                    print_history_table(session.get_history().get("actions", []))
                except RemoteAPIError as exc:
                    console.print(f"\n  [error]❌ Failed to fetch remote history: {exc}[/error]\n")
            elif cmd == "/close":
                handle_remote_exit(session, close=True)
                break
            elif cmd == "/config":
                handle_remote_config(session, config)
            elif cmd == "/agents":
                handle_remote_agents(session, config, arg or None)
            elif cmd == "/language":
                handle_remote_language(session, config, arg or None)
            elif cmd == "/thinking":
                handle_remote_thinking(session, config)
            elif user_input.startswith("/"):
                console.print(f"\n  [warning]⚠️  Unknown command: {user_input}[/warning]\n")
            else:
                queue_position = runner.submit(user_input)
                if queue_position:
                    console.print(
                        f"\n  [dim]Queued hosted task #{queue_position}. It will run after the current turn.[/dim]\n"
                    )
    finally:
        approval_manager.cancel_pending()
        runner.shutdown(cancel_pending=False, stop_current=False)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="neu",
        description=f"{__app_name__} - Advanced AI Coding Agent powered by Ollama",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Start the interactive AI agent")
    run_parser.add_argument("--workspace", "-w", type=str, default=None, help="Workspace directory or remote workspace path")
    run_parser.add_argument("--model", "-m", type=str, default=None, help="Model to use")
    run_parser.add_argument("--language", "-l", type=str, default=None, help="Preferred reply language")
    run_parser.add_argument("--agents", choices=["single", "team", "parallel"], default=None, help="Agent orchestration mode")
    run_parser.add_argument("--runtime", choices=["local", "remote", "hybrid"], default=None, help="Run fully local, fully hosted, or hybrid with local tools plus hosted inference")
    run_parser.add_argument("--api-base-url", default=None, help="Hosted NeuDev API base URL for remote or hybrid mode")
    run_parser.add_argument("--api-key", default=None, help="Hosted NeuDev API key for remote or hybrid mode")
    run_parser.add_argument("--ws-base-url", default=None, help="Hosted NeuDev WebSocket URL for remote streaming")
    run_parser.add_argument("--transport", choices=["auto", "sse", "websocket"], default=None, help="Remote streaming transport")
    run_parser.add_argument("--session-id", default=None, help="Resume an existing hosted session by ID")
    run_parser.add_argument("--auto-permission", action="store_true", help="Auto-approve destructive tools")
    run_parser.add_argument(
        "--command-policy",
        choices=sorted(VALID_COMMAND_POLICIES),
        default=None,
        help="Local and hybrid run_command policy: auto, permissive, restricted, or disabled",
    )

    serve_parser = subparsers.add_parser("serve", help="Run the hosted NeuDev API server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Bind host. Default 0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8765, help="Bind port. Default 8765")
    serve_parser.add_argument("--workspace", "-w", default=os.getcwd(), help="Workspace root served by the API")
    serve_parser.add_argument("--api-key", default="", help="Bearer API key required by clients")
    serve_parser.add_argument("--ollama-host", default=None, help="Hosted Ollama API base URL")
    serve_parser.add_argument("--model", default=None, help="Default hosted model")
    serve_parser.add_argument("--language", default=None, help="Default hosted reply language")
    serve_parser.add_argument("--agents", choices=["single", "team", "parallel"], default=None, help="Hosted agent mode")
    serve_parser.add_argument("--auto-permission", action="store_true", help="Auto-approve destructive tools on the hosted runtime")
    serve_parser.add_argument("--session-store", default=None, help="Directory for persisted hosted session snapshots")
    serve_parser.add_argument("--ws-port", type=int, default=None, help="Optional WebSocket port for remote streaming")
    serve_parser.add_argument("--disable-websocket", action="store_true", help="Disable the WebSocket stream server")

    login_parser = subparsers.add_parser("login", help="Persist hosted API settings for remote or hybrid usage")
    login_parser.add_argument("--runtime", choices=["remote", "hybrid"], default="remote", help="Default runtime to store with the hosted credentials")
    login_parser.add_argument("--api-base-url", default=None, help="Hosted NeuDev API base URL to save in local config")
    login_parser.add_argument("--api-key", default=None, help="Hosted NeuDev API key to save in local config")
    login_parser.add_argument("--ws-base-url", default=None, help="Optional hosted WebSocket URL to save in local config")

    auth_parser = subparsers.add_parser("auth", help="Manage hosted API credentials and saved connection settings")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command")
    auth_login_parser = auth_subparsers.add_parser("login", help="Save hosted API settings in local config")
    auth_login_parser.add_argument("--runtime", choices=["remote", "hybrid"], default="remote", help="Default runtime to store with the hosted credentials")
    auth_login_parser.add_argument("--api-base-url", default=None, help="Hosted NeuDev API base URL to save in local config")
    auth_login_parser.add_argument("--api-key", default=None, help="Hosted NeuDev API key to save in local config")
    auth_login_parser.add_argument("--ws-base-url", default=None, help="Optional hosted WebSocket URL to save in local config")
    auth_subparsers.add_parser("status", help="Show saved hosted auth settings")
    auth_logout_parser = auth_subparsers.add_parser("logout", help="Clear the saved hosted API key")
    auth_logout_parser.add_argument("--all", action="store_true", help="Also clear the saved hosted API and WebSocket URLs")

    uninstall_parser = subparsers.add_parser("uninstall", help="Show uninstall commands and optionally remove local NeuDev config")
    uninstall_parser.add_argument("--purge-config", action="store_true", help="Remove ~/.neudev config and history files")

    subparsers.add_parser("version", help="Show version")
    return parser


def apply_run_overrides(config: NeuDevConfig, args: argparse.Namespace) -> NeuDevConfig:
    """Persist run-command config overrides."""
    updates = {}
    if getattr(args, "model", None):
        updates["model"] = args.model
    if getattr(args, "language", None):
        updates["response_language"] = args.language
    if getattr(args, "agents", None):
        updates["agent_mode"] = args.agents
    if getattr(args, "runtime", None):
        updates["runtime_mode"] = args.runtime
    if getattr(args, "api_base_url", None):
        updates["api_base_url"] = args.api_base_url
    if getattr(args, "api_key", None):
        updates["api_key"] = args.api_key
    if getattr(args, "ws_base_url", None):
        updates["websocket_base_url"] = args.ws_base_url
    if getattr(args, "transport", None):
        updates["stream_transport"] = args.transport
    if getattr(args, "workspace", None) and getattr(args, "runtime", None) == "remote":
        updates["remote_workspace"] = args.workspace
    if getattr(args, "auto_permission", False):
        updates["auto_permission"] = True
    if getattr(args, "command_policy", None):
        updates["command_policy"] = args.command_policy
    if updates:
        config.update(**updates)
    return config


def main() -> None:
    """Entry point for the `neu` CLI."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "version":
        print(f"{__app_name__} v{__version__}")
        return

    if args.command == "login":
        run_login_setup(args)
        return

    if args.command == "auth":
        if args.auth_command in (None, "status"):
            run_auth_status()
        elif args.auth_command == "login":
            run_login_setup(args)
        elif args.auth_command == "logout":
            run_logout(args)
        else:
            parser.error(f"Unknown auth subcommand: {args.auth_command}")
        return

    if args.command == "uninstall":
        run_uninstall(args)
        return

    if args.command == "serve":
        serve_api(
            host=args.host,
            port=args.port,
            workspace=args.workspace,
            api_key=args.api_key,
            ollama_host=args.ollama_host,
            model=args.model,
            language=args.language,
            agent_mode=args.agents,
            auto_permission=args.auto_permission,
            session_store=args.session_store,
            websocket_port=args.ws_port,
            disable_websocket=args.disable_websocket,
        )
        return

    if args.command == "run" or args.command is None:
        config = apply_run_overrides(NeuDevConfig.load(), args)
        workspace = getattr(args, "workspace", None)
        if config.runtime_mode == "remote":
            run_remote_cli(config, workspace=workspace, session_id=getattr(args, "session_id", None))
        elif config.runtime_mode == "hybrid":
            run_hybrid_cli(config, workspace=workspace)
        else:
            run_local_cli(config, workspace=workspace)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
