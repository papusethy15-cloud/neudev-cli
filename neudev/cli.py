"""RovoDev-style interactive CLI for NeuDev."""

import argparse
import os
import sys
import time
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.columns import Columns
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich.rule import Rule
from rich.align import Align

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style as PTStyle

from neudev import __version__, __app_name__
from neudev.config import NeuDevConfig, HISTORY_FILE, CONFIG_DIR
from neudev.agent import Agent
from neudev.llm import LLMError, ConnectionError as OllamaConnectionError, ModelNotFoundError


# Rich theme — vibrant, modern palette
THEME = Theme({
    "info": "bold cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "tool": "bold magenta",
    "dim": "dim white",
    "accent": "bold bright_blue",
    "highlight": "bold bright_yellow",
    "muted": "grey62",
})

console = Console(theme=THEME)

# Slash commands
SLASH_COMMANDS = [
    "/help", "/models", "/clear", "/remove", "/history", "/exit", "/quit",
    "/version", "/config", "/thinking",
]


def print_banner(config: NeuDevConfig, workspace: str) -> None:
    """Print a beautiful startup banner."""
    ws_name = Path(workspace).name or workspace
    now = datetime.now().strftime("%I:%M %p")

    # Build the main title
    title = Text()
    title.append("  ⚡ ", style="bold bright_yellow")
    title.append("N", style="bold bright_cyan")
    title.append("eu", style="bold white")
    title.append("D", style="bold bright_cyan")
    title.append("ev", style="bold white")
    title.append("  ", style="")

    # Subtitle
    subtitle = Text("AI Coding Agent", style="dim italic")

    # Info grid
    info = Text()
    info.append("\n")
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
    info.append(" for commands • ", style="dim")
    info.append("/models", style="bold bright_yellow")
    info.append(" to switch model", style="dim")

    console.print()
    console.print(
        Panel(
            info,
            title=title,
            subtitle=subtitle,
            border_style="bright_blue",
            padding=(0, 2),
            expand=False,
            width=min(console.width, 60),
        )
    )
    console.print()


def print_status_block(items: list[tuple[str, str, str]]) -> None:
    """Print a grouped status block. items = [(icon, label, status_style)]"""
    for icon, label, style in items:
        console.print(f"  {icon}  {label}", style=style)
    console.print()


def handle_help() -> None:
    """Display help information in a friendly layout."""
    console.print()

    # Commands table
    table = Table(
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        title="[bold bright_cyan]⌨️  Commands[/bold bright_cyan]",
        title_style="bold",
        padding=(0, 2),
        expand=False,
        width=min(console.width, 55),
    )
    table.add_column("Command", style="bold bright_yellow", width=12)
    table.add_column("Description", style="white")

    table.add_row("/help", "Show this help message")
    table.add_row("/models", "List & switch Ollama models")
    table.add_row("/clear", "Clear conversation history")
    table.add_row("/remove", "Undo the last file change")
    table.add_row("/history", "Show session action log")
    table.add_row("/config", "Show current settings")
    table.add_row("/thinking", "Toggle thinking display ON/OFF")
    table.add_row("/version", "Show version info")
    table.add_row("/exit", "End session with summary")

    console.print(table)

    # Tips
    console.print()
    tips = Text()
    tips.append("  💡 ", style="")
    tips.append("Just type naturally to chat with the AI agent.\n", style="dim")
    tips.append("  💡 ", style="")
    tips.append("Press ", style="dim")
    tips.append("↑/↓", style="bold")
    tips.append(" to browse command history.", style="dim")
    console.print(tips)
    console.print()


def handle_models(agent: Agent) -> None:
    """List and switch models."""
    try:
        models = agent.llm.list_models()
    except LLMError as e:
        console.print(f"\n  [error]❌ Error listing models: {e}[/error]\n")
        return

    if not models:
        console.print("\n  [warning]⚠️  No models found. Download one with:[/warning]")
        console.print("     [bold]ollama pull qwen3.5:0.8b[/bold]\n")
        return

    console.print()
    table = Table(
        title="[bold bright_cyan]🤖 Available Models[/bold bright_cyan]",
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        padding=(0, 1),
        expand=False,
        width=min(console.width, 60),
    )
    table.add_column("#", style="dim", width=3, justify="center")
    table.add_column("Model", style="bold white")
    table.add_column("Size", style="dim", justify="right")
    table.add_column("Active", justify="center")

    for i, m in enumerate(models, 1):
        size_mb = m["size"] / (1024 * 1024)
        size_str = f"{size_mb:.0f} MB" if size_mb < 1024 else f"{size_mb/1024:.1f} GB"
        active = "✅" if m["active"] else "  "
        row_style = "bold bright_green" if m["active"] else ""
        table.add_row(str(i), m["name"], size_str, active, style=row_style)

    console.print(table)
    console.print()

    # Ask to switch
    try:
        choice = console.input(
            "  [dim]Enter model number to switch (or press Enter to keep current):[/dim] "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return

    if choice and choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(models):
            model_name = models[idx]["name"]
            try:
                agent.llm.switch_model(model_name)
                agent.refresh_context()
                console.print(f"\n  [success]✅ Switched to: {model_name}[/success]\n")
            except LLMError as e:
                console.print(f"\n  [error]❌ Failed to switch: {e}[/error]\n")
        else:
            console.print("  [warning]⚠️  Invalid selection.[/warning]\n")


def handle_history(agent: Agent) -> None:
    """Show session action history."""
    actions = agent.session.actions
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

    for i, a in enumerate(actions, 1):
        icon, color = icon_map.get(a.action, ("•", ""))
        table.add_row(str(i), f"{icon} {a.action}", a.target, style=color)

    console.print(table)
    console.print()


def handle_remove(agent: Agent) -> None:
    """Undo last file change."""
    result = agent.session.undo_last_change()
    if result:
        console.print(f"\n  [success]✅ {result}[/success]\n")
    else:
        console.print("\n  [dim]📭 Nothing to undo.[/dim]\n")


def handle_config(config: NeuDevConfig) -> None:
    """Show current config in a clean layout."""
    console.print()
    table = Table(
        title="[bold bright_cyan]⚙️  Configuration[/bold bright_cyan]",
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        padding=(0, 2),
        expand=False,
        width=min(console.width, 50),
    )
    table.add_column("Setting", style="bold white")
    table.add_column("Value", style="bright_cyan")

    table.add_row("Model", config.model)
    table.add_row("Temperature", str(config.temperature))
    table.add_row("Max Tokens", str(config.max_tokens))
    table.add_row("Ollama Host", config.ollama_host)
    table.add_row("Max Iterations", str(config.max_iterations))
    table.add_row("Cmd Timeout", f"{config.command_timeout}s")
    table.add_row("Show Thinking", "ON \U0001f7e2" if config.show_thinking else "OFF \u26ab")

    console.print(table)
    console.print()


def handle_thinking(config: NeuDevConfig) -> None:
    """Toggle thinking display ON/OFF."""
    new_state = not config.show_thinking
    config.update(show_thinking=new_state)
    state_str = "ON" if new_state else "OFF"
    icon = "🧠" if new_state else "💤"
    style = "success" if new_state else "warning"
    console.print(f"\n  [{style}]{icon} Thinking display: {state_str}[/{style}]")
    if new_state:
        console.print("  [dim]Model reasoning will be shown before responses.[/dim]")
    else:
        console.print("  [dim]Model reasoning will be hidden.[/dim]")
    console.print()


def handle_exit(agent: Agent) -> None:
    """Handle session exit with summary and cleanup."""
    console.print()
    console.print(Rule("[bold bright_cyan]Session Ending[/bold bright_cyan]", style="bright_blue"))
    console.print()

    # Offer test file cleanup
    if agent.session.test_files:
        console.print(
            f"  [warning]⚠️  Found {len(agent.session.test_files)} test file(s) "
            f"created this session.[/warning]"
        )
        try:
            cleanup = console.input("  [dim]Delete test files? (y/n):[/dim] ").strip().lower()
            if cleanup in ("y", "yes"):
                deleted = agent.session.cleanup_test_files()
                for d in deleted:
                    console.print(f"    [dim]🗑️  Deleted: {d}[/dim]")
                console.print()
        except (EOFError, KeyboardInterrupt):
            pass

    # Show session summary
    agent.session.get_summary()

    # Show improvement suggestions
    suggestions = agent.session.get_improvement_suggestions()
    if suggestions:
        suggestion_text = "\n".join(f"  💡 {s}" for s in suggestions)
        console.print(
            Panel(
                suggestion_text,
                title="[bold bright_cyan]💡 Suggestions[/bold bright_cyan]",
                border_style="bright_cyan",
                padding=(0, 1),
                expand=False,
            )
        )
        console.print()

    console.print("  [bold bright_green]👋 Thanks for using NeuDev! Happy coding![/bold bright_green]\n")


def process_user_input(agent: Agent, user_input: str) -> None:
    """Process user input and display agent response."""
    # Status callback for tool execution display
    def on_status(tool_name: str, args: dict):
        target = args.get("path", args.get("command", args.get("directory", "")))
        if target:
            target = Path(target).name if len(str(target)) > 40 else target
        console.print(f"    [tool]🔧 {tool_name}[/tool]  [dim]{target}[/dim]")

    # Text callback
    text_parts = []
    def on_text(text: str):
        text_parts.append(text)

    # Thinking callback
    thinking_parts = []
    def on_thinking(text: str):
        thinking_parts.append(text)

    console.print()

    # Show thinking indicator
    with console.status(
        "[bold bright_cyan]🧠 Thinking...[/bold bright_cyan]",
        spinner="dots",
        spinner_style="bright_cyan",
    ):
        try:
            response = agent.process_message(
                user_input,
                on_status=on_status,
                on_text=on_text,
                on_thinking=on_thinking,
            )
        except LLMError as e:
            error_msg = str(e)
            console.print()
            console.print(
                Panel(
                    f"[bold red]❌ Error[/bold red]\n\n[white]{error_msg}[/white]\n\n"
                    f"[dim]💡 Tips:[/dim]\n"
                    f"[dim]  • Check if Ollama is running: [bold]ollama serve[/bold][/dim]\n"
                    f"[dim]  • Try a simpler request[/dim]\n"
                    f"[dim]  • Use [bold]/models[/bold] to switch to a different model[/dim]",
                    border_style="red",
                    title="[bold red]⚠️  Something went wrong[/bold red]",
                    padding=(1, 2),
                    expand=False,
                    width=min(console.width, 65),
                )
            )
            console.print()
            return
        except Exception as e:
            console.print()
            console.print(
                Panel(
                    f"[bold red]❌ Unexpected Error[/bold red]\n\n"
                    f"[white]{type(e).__name__}: {e}[/white]\n\n"
                    f"[dim]Please try again or type [bold]/help[/bold] for assistance.[/dim]",
                    border_style="red",
                    title="[bold red]⚠️  Something went wrong[/bold red]",
                    padding=(1, 2),
                    expand=False,
                    width=min(console.width, 65),
                )
            )
            console.print()
            return

    # Display thinking content (if any)
    if thinking_parts:
        thinking_text = "".join(thinking_parts).strip()
        if thinking_text:
            console.print()
            console.print(
                Panel(
                    f"[dim italic]{thinking_text}[/dim italic]",
                    border_style="grey50",
                    title="[grey62]💭 Thinking[/grey62]",
                    padding=(1, 2),
                    expand=True,
                )
            )

    # Display the response
    if response:
        console.print()
        try:
            md = Markdown(response)
            console.print(
                Panel(
                    md,
                    border_style="bright_blue",
                    title="[bold bright_cyan]🤖 NeuDev[/bold bright_cyan]",
                    padding=(1, 2),
                    expand=True,
                )
            )
        except Exception:
            # Fallback to plain text
            console.print(
                Panel(
                    response,
                    border_style="bright_blue",
                    title="[bold bright_cyan]🤖 NeuDev[/bold bright_cyan]",
                    padding=(1, 2),
                    expand=True,
                )
            )
    else:
        console.print("  [dim]🤖 No response from agent.[/dim]")

    console.print()


def run_cli(workspace: str = None) -> None:
    """Run the interactive CLI loop."""
    workspace = workspace or os.getcwd()
    config = NeuDevConfig.load()

    # Ensure config dir exists for history
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Print banner
    print_banner(config, workspace)

    # Initialize agent
    try:
        with console.status(
            "[bold bright_cyan]⏳ Initializing NeuDev...[/bold bright_cyan]",
            spinner="dots",
            spinner_style="bright_cyan",
        ):
            agent = Agent(config, workspace)

        print_status_block([
            ("✅", "Connected to Ollama", "success"),
            ("✅", f"Model: {config.model}", "success"),
            ("✅", f"Tools: {len(agent.tool_registry.get_all())} loaded", "success"),
        ])
        console.print(Rule(style="bright_blue"))
        console.print()

    except OllamaConnectionError as e:
        console.print(
            Panel(
                f"[bold red]Cannot connect to Ollama[/bold red]\n\n"
                f"[white]{e}[/white]\n\n"
                f"[dim]Make sure Ollama is running:[/dim]\n"
                f"  [bold bright_green]ollama serve[/bold bright_green]",
                border_style="red",
                title="[bold red]❌ Connection Failed[/bold red]",
                padding=(1, 2),
                expand=False,
            )
        )
        return
    except ModelNotFoundError as e:
        console.print(
            Panel(
                f"[bold red]Model not available[/bold red]\n\n"
                f"[white]{e}[/white]\n\n"
                f"[dim]Download a model:[/dim]\n"
                f"  [bold bright_green]ollama pull qwen3.5:0.8b[/bold bright_green]",
                border_style="red",
                title="[bold red]❌ Model Not Found[/bold red]",
                padding=(1, 2),
                expand=False,
            )
        )
        return
    except LLMError as e:
        console.print(f"\n  [error]❌ Failed to initialize: {e}[/error]\n")
        return

    # Setup prompt — green prompt with arrow
    completer = WordCompleter(SLASH_COMMANDS, sentence=True)
    pt_style = PTStyle.from_dict({
        "prompt": "#00cc66 bold",
    })

    try:
        session = PromptSession(
            history=FileHistory(str(HISTORY_FILE)),
            completer=completer,
            style=pt_style,
        )
    except Exception:
        session = PromptSession(completer=completer, style=pt_style)

    # Main loop
    while True:
        try:
            user_input = session.prompt(
                [("class:prompt", "neudev ❯ ")],
            ).strip()
        except KeyboardInterrupt:
            console.print(
                "\n  [dim]Press Ctrl+C again to force quit, or type [bold]/exit[/bold] for session summary.[/dim]"
            )
            try:
                user_input = session.prompt([("class:prompt", "neudev ❯ ")]).strip()
            except (KeyboardInterrupt, EOFError):
                console.print("\n  [dim]👋 Goodbye![/dim]\n")
                break
            if not user_input:
                continue
        except EOFError:
            break

        if not user_input:
            continue

        # Handle slash commands
        cmd = user_input.lower()

        if cmd in ("/exit", "/quit"):
            handle_exit(agent)
            break
        elif cmd == "/help":
            handle_help()
        elif cmd == "/models":
            handle_models(agent)
        elif cmd == "/clear":
            agent.clear_history()
            console.print("\n  [success]✅ Conversation history cleared.[/success]\n")
        elif cmd == "/remove":
            handle_remove(agent)
        elif cmd == "/history":
            handle_history(agent)
        elif cmd == "/config":
            handle_config(agent.config)
        elif cmd == "/thinking":
            handle_thinking(agent.config)
        elif cmd == "/version":
            console.print(f"\n  [bold bright_cyan]⚡ {__app_name__}[/bold bright_cyan] [dim]v{__version__}[/dim]\n")
        elif user_input.startswith("/"):
            console.print(f"\n  [warning]⚠️  Unknown command: {user_input}[/warning]")
            console.print("  [dim]Type [bold]/help[/bold] for available commands.[/dim]\n")
        else:
            # Process as agent message
            process_user_input(agent, user_input)


def main():
    """Entry point for `neu` CLI command."""
    parser = argparse.ArgumentParser(
        prog="neu",
        description=f"{__app_name__} - Advanced AI Coding Agent powered by Ollama",
    )
    subparsers = parser.add_subparsers(dest="command")

    # `neu run` command
    run_parser = subparsers.add_parser("run", help="Start the interactive AI agent")
    run_parser.add_argument(
        "--workspace", "-w",
        type=str,
        default=None,
        help="Workspace directory (default: current directory)",
    )
    run_parser.add_argument(
        "--model", "-m",
        type=str,
        default=None,
        help="Ollama model to use (default: from config)",
    )

    # `neu version` command
    subparsers.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command == "version":
        print(f"{__app_name__} v{__version__}")
        return

    if args.command == "run" or args.command is None:
        # Update config if model specified
        if hasattr(args, "model") and args.model:
            config = NeuDevConfig.load()
            config.update(model=args.model)

        workspace = getattr(args, "workspace", None)
        run_cli(workspace=workspace)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
