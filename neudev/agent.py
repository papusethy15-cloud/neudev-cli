"""Agent reasoning loop for NeuDev - the brain of the system."""

from concurrent.futures import ThreadPoolExecutor
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path

from neudev.config import NeuDevConfig
from neudev.llm import OllamaClient, LLMError
from neudev.model_routing import AgentTeam
from neudev.tools import create_tool_registry
from neudev.tools.base import ToolError
from neudev.context import WorkspaceContext
from neudev.session import SessionManager
from neudev.permissions import PermissionManager


SYSTEM_PROMPT = """You are NeuDev, an advanced AI coding agent. You help users build, modify, and understand code projects.

## Your Capabilities
You have access to powerful tools for file system operations:
- **read_file**: Read file contents with optional line ranges
- **read_files_batch**: Read multiple files in one call
- **write_file**: Create new files or overwrite existing ones
- **edit_file**: Edit files using find/replace
- **smart_edit_file**: Edit files with normalized matching fallbacks
- **python_ast_edit**: Replace Python symbols by AST location
- **js_ts_symbol_edit**: Replace JavaScript/TypeScript symbols by structural lookup
- **delete_file**: Delete files
- **search_files**: Search for files by name/pattern
- **grep_search**: Search file contents for text/patterns
- **symbol_search**: Search symbol definitions and references across the repo
- **list_directory**: List directory contents as a tree
- **run_command**: Execute shell commands
- **diagnostics**: Run syntax/tests/lint/typecheck with smart fallbacks
- **changed_files_diagnostics**: Run targeted diagnostics only for changed files
- **git_diff_review**: Review local git changes
- **file_outline**: View code structure (classes, functions)

## How to Work
1. **Understand First**: Read the user's request carefully. Ask clarifying questions if needed.
2. **Analyze**: Use list_directory, read_file, file_outline, and grep_search to understand the existing codebase.
3. **Plan**: Before making changes, explain what you will do and why.
4. **Execute**: Use the appropriate tools to make changes. Create files, edit code, run commands.
5. **Verify**: After changes, verify they work (e.g., run tests, check syntax).
6. **Report**: Summarize what you did and suggest next steps or improvements.

## Rules
- Always read existing files before editing them
- Explain what you're doing and why
- Use the correct tool for each task
- Follow the saved project memory so new changes stay consistent with the existing design and programming patterns
- If the user explicitly changes the framework, design direction, or coding style, adopt it for this task and let project memory refresh silently
- Use `symbol_search` when the task mentions a function, class, or method and you need fast repo navigation
- Prefer `python_ast_edit` or `js_ts_symbol_edit` for symbol-level refactors over brittle text replacement
- Prefer `changed_files_diagnostics` for quick verification after edits and `git_diff_review` before summarizing larger changes
- When the workspace has frontend/backend, mobile/backend, or multiple components, identify the affected components and inspect the boundary files before editing
- If a task requires multiple steps, execute them in order
- When creating test files, mention they are test files
- Suggest improvements after creating or modifying code
- Be precise with file paths - use the workspace directory as the base
- Prefer workspace-relative paths like `README.md` or `neudev/agent.py`
- Do not invent absolute paths when a relative path will work
- When editing files, provide the EXACT text to find and replace
- User-facing replies must be in {response_language} unless the user explicitly asks for another language
- If visible thinking is requested, keep it concise and in {response_language}
- Do not expose internal scratchpad text, chain-of-thought, or tool-planning narration in the final answer
- When you need tools, call them directly instead of narrating your internal process to the user

## Tool Calling
- Use native tool calling when the model supports it
- If native tool calling is unavailable, output ONLY tool call blocks in this format:
  <tool_call>
  <function=read_file>
  <parameter=path>README.md</parameter>
  </tool_call>
- After a tool result arrives, continue the analysis and request the next tool if needed

## Workspace Context
{workspace_context}

## Important
- Platform: {platform_name}
- The workspace directory is: {workspace_path}
- Preferred response language: {response_language}
- Use forward slashes in paths when possible
- Be helpful, precise, and professional
"""


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


@dataclass
class OrchestrationContext:
    team: AgentTeam
    brief: str = ""
    review_checklist: str = ""
    todo_items: list[str] = field(default_factory=list)
    convention_notes: list[str] = field(default_factory=list)


class Agent:
    """ReAct-style agent that reasons and acts using tools."""

    def __init__(self, config: NeuDevConfig, workspace: str):
        self.config = config
        self.workspace = str(Path(workspace).resolve())
        self.llm = OllamaClient(config)
        self.tool_registry = create_tool_registry()
        self.tool_registry.bind_workspace(self.workspace)
        self.context = WorkspaceContext(self.workspace)
        self.session = SessionManager(self.workspace)
        self.permissions = PermissionManager()
        self.conversation: list[dict] = []
        self.last_agent_team: AgentTeam | None = None
        self.last_review_notes: str = ""
        self.last_plan_items: list[str] = []
        self.last_plan_conventions: list[str] = []
        self.last_plan_progress: list[dict[str, str]] = []
        self._init_system_prompt()

    def _build_system_prompt(self) -> str:
        """Render the current system prompt text."""
        workspace_context = self.context.get_system_context()
        return SYSTEM_PROMPT.format(
            workspace_context=workspace_context,
            workspace_path=self.workspace,
            platform_name=platform.system(),
            response_language=self.config.response_language,
        )

    def _init_system_prompt(self) -> None:
        """Initialize the system prompt with workspace context."""
        self.conversation = [{"role": "system", "content": self._build_system_prompt()}]

    def refresh_context(self) -> None:
        """Refresh the workspace context in the system prompt."""
        system_content = self._build_system_prompt()
        if self.conversation and self.conversation[0].get("role") == "system":
            self.conversation[0]["content"] = system_content
        else:
            self.conversation.insert(0, {"role": "system", "content": system_content})

    def process_message(
        self,
        user_message: str,
        on_status=None,
        on_text=None,
        on_thinking=None,
        on_phase=None,
        on_workspace_change=None,
        on_plan=None,
        on_plan_update=None,
    ) -> str:
        """Process a user message through the agent loop.

        Args:
            user_message: The user's input
            on_status: Callback for status updates (tool name, args)
            on_text: Callback for streaming text chunks
            on_thinking: Callback for thinking/reasoning content

        Returns:
            Final response text
        """
        self.session.messages_count += 1
        workspace_changes = self.sync_workspace_state()
        memory_changed = self.context.apply_user_memory_directives(user_message)
        if memory_changed:
            self.refresh_context()
        turn_action_start = len(self.session.actions)
        working_conversation = list(self.conversation)
        if workspace_changes and on_workspace_change:
            on_workspace_change(workspace_changes)
        if workspace_changes:
            working_conversation.append({
                "role": "system",
                "content": self._format_workspace_change_message(workspace_changes),
            })
        working_conversation.append({"role": "user", "content": user_message})
        self.last_agent_team = None
        self.last_review_notes = ""
        self.last_plan_items = []
        self.last_plan_conventions = []
        self.last_plan_progress = []

        tool_defs = self.tool_registry.get_tool_definitions()
        final_response = ""
        use_thinking = self.config.show_thinking
        warned_about_tool_fallback = False
        orchestration = self._prepare_orchestration(
            working_conversation,
            tool_defs,
            on_phase=on_phase,
        )
        if orchestration:
            self.last_plan_items = list(orchestration.todo_items)
            self.last_plan_conventions = list(orchestration.convention_notes)
            self.last_plan_progress = self._initialize_plan_progress(orchestration.todo_items)
            if on_plan and (orchestration.todo_items or orchestration.convention_notes):
                on_plan(orchestration.todo_items, orchestration.convention_notes)
            self._emit_plan_update(on_plan_update)
        preferred_models = list(orchestration.team.executor_candidates) if orchestration else None
        route_reason = orchestration.team.route_reason if orchestration else None

        if orchestration and on_phase:
            on_phase("executor", orchestration.team.executor)

        for iteration in range(self.config.max_iterations):
            try:
                runtime_messages = self._build_runtime_messages(working_conversation, orchestration)
                result = self.llm.chat_with_tools(
                    messages=runtime_messages,
                    tools=tool_defs,
                    think=use_thinking,
                    preferred_models=preferred_models,
                    route_reason=route_reason,
                )
            except LLMError as e:
                error_msg = f"LLM Error: {e}"
                working_conversation.append({"role": "assistant", "content": error_msg})
                self._persist_turn_state(working_conversation)
                return error_msg

            if (
                not result.get("native_tools_supported", True)
                and not result["tool_calls"]
                and not warned_about_tool_fallback
            ):
                warning = (
                    "\n\n⚠️ **Note:** This model did not use tools in this reply. "
                    "Switch to a stronger tool-calling model with `/models` if analysis stalls."
                )
                result["content"] = (result["content"] or "") + warning
                warned_about_tool_fallback = True

            # If there's thinking content, send it to the callback
            if result.get("thinking") and on_thinking and self._should_surface_thinking(result["thinking"]):
                on_thinking(result["thinking"])

            # Only surface the final user-facing reply, not intermediate tool-planning text.
            if result["content"] and not result["tool_calls"]:
                final_response = result["content"]
                if on_text:
                    on_text(result["content"])

            # If no tool calls, we're done
            if result["done"] or not result["tool_calls"]:
                if final_response:
                    working_conversation.append({"role": "assistant", "content": final_response})
                break

            # Process tool calls
            # Add assistant message with tool calls to conversation
            assistant_msg = {"role": "assistant", "content": ""}
            if result["tool_calls"]:
                assistant_msg["tool_calls"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        }
                    }
                    for tc in result["tool_calls"]
                ]
            working_conversation.append(assistant_msg)

            for tool_call in result["tool_calls"]:
                tool_name = tool_call["name"]
                tool_args = tool_call["arguments"]

                if on_status:
                    on_status(tool_name, tool_args)

                # Execute the tool
                tool_result = self._execute_tool(tool_name, tool_args)
                if self._advance_plan_progress_from_tool(tool_name, tool_result):
                    self._emit_plan_update(on_plan_update)

                # Add tool result to conversation
                working_conversation.append({
                    "role": "tool",
                    "tool_name": tool_name,
                    "content": tool_result,
                })

        else:
            # Hit max iterations
            final_response += "\n\n⚠️ Reached maximum iterations. The task may be incomplete."
            working_conversation.append({"role": "assistant", "content": final_response})

        review_notes = self._run_reviewer(
            user_message=user_message,
            final_response=final_response,
            orchestration=orchestration,
            turn_action_start=turn_action_start,
            on_phase=on_phase,
        )
        if self._advance_plan_progress_for_stage("verify"):
            self._emit_plan_update(on_plan_update)
        if review_notes:
            self.last_review_notes = review_notes
            final_response += f"\n\n### Review Notes\n{review_notes}"
            if working_conversation and working_conversation[-1].get("role") == "assistant":
                working_conversation[-1]["content"] = final_response

        # Check for improvement suggestions after modifications
        suggestions = self._check_for_suggestions()
        if suggestions:
            final_response += suggestions
            if working_conversation and working_conversation[-1].get("role") == "assistant":
                working_conversation[-1]["content"] = final_response

        self._persist_turn_state(working_conversation)
        return final_response

    def _execute_tool(self, name: str, args: dict) -> str:
        """Execute a tool with permission checking and session tracking."""
        return self._execute_tool_internal(name, args, allow_fallback=True)

    def _execute_tool_internal(
        self,
        name: str,
        args: dict,
        *,
        allow_fallback: bool,
        skip_permission: bool = False,
        skip_backup: bool = False,
    ) -> str:
        """Execute a tool, optionally allowing related-tool fallback."""
        tool = self.tool_registry.get(name)
        if tool is None:
            return f"Error: Unknown tool '{name}'"

        resolved_path = None
        raw_path = args.get("path")
        if raw_path:
            try:
                resolved_path = str(tool.resolve_path(raw_path))
            except ToolError:
                resolved_path = None
        raw_paths = args.get("paths") or []

        # Permission check for destructive tools
        if tool.requires_permission and not skip_permission:
            message = tool.permission_message(args)
            if not self.permissions.request_permission(name, message):
                return f"Action denied by user: {name}"

        # Backup file before modification
        if not skip_backup and name in ("write_file", "edit_file", "smart_edit_file", "python_ast_edit", "js_ts_symbol_edit", "delete_file"):
            if resolved_path:
                self.session.backup_file(resolved_path)
            elif raw_path:
                self.session.backup_file(raw_path)

        # Execute
        try:
            result = tool.execute(**args)
        except ToolError as e:
            if allow_fallback:
                fallback_result = self._attempt_tool_fallback(
                    name,
                    args,
                    error=e,
                    backup_taken=not skip_backup and name in ("write_file", "edit_file", "smart_edit_file", "python_ast_edit", "js_ts_symbol_edit", "delete_file"),
                )
                if fallback_result is not None:
                    return fallback_result
            return f"Tool Error ({name}): {e}"
        except Exception as e:
            return f"Unexpected Error ({name}): {type(e).__name__}: {e}"

        # Track the action
        action_map = {
            "read_file": "read",
            "read_files_batch": "read",
            "write_file": "created",
            "edit_file": "modified",
            "smart_edit_file": "modified",
            "python_ast_edit": "modified",
            "js_ts_symbol_edit": "modified",
            "delete_file": "deleted",
            "run_command": "command",
            "diagnostics": "command",
            "changed_files_diagnostics": "command",
            "git_diff_review": "read",
            "symbol_search": "read",
        }
        action_type = action_map.get(name, "other")
        target = resolved_path or args.get("command") or args.get("directory") or ",".join(raw_paths) or name
        self.session.record_action(action_type, str(target))

        # Track file access
        if resolved_path:
            self.context.track_file_access(resolved_path)
        for path in raw_paths:
            self.context.track_file_access(path)

        # Track test files
        if name in ("write_file", "smart_edit_file", "python_ast_edit", "js_ts_symbol_edit") and resolved_path:
            if "test_" in resolved_path or "_test." in resolved_path:
                self.session.track_test_file(resolved_path)

        return result

    def _attempt_tool_fallback(self, name: str, args: dict, error: Exception, backup_taken: bool) -> str | None:
        """Try a related tool automatically after a primary tool fails."""
        message = str(error).lower()
        path = args.get("path")

        if name == "read_file" and path:
            if "not a file" in message or "directory" in message:
                result = self._execute_tool_internal(
                    "list_directory",
                    {"path": path, "max_depth": 2},
                    allow_fallback=False,
                )
                return (
                    f"Automatic fallback: `read_file` received a directory, so `list_directory` was used instead.\n\n"
                    f"{result}"
                )
            if "file not found" in message:
                pattern = Path(path).name or path
                parent = str(Path(path).parent).replace("\\", "/")
                directory = parent if parent not in ("", ".") else "."
                result = self._execute_tool_internal(
                    "search_files",
                    {"pattern": f"*{pattern}*", "directory": directory, "file_type": "any"},
                    allow_fallback=False,
                )
                return (
                    f"Automatic fallback: `read_file` could not find the path, so `search_files` looked for related names.\n\n"
                    f"{result}"
                )

        if name == "list_directory" and path and ("not a directory" in message or "not a file" in message):
            result = self._execute_tool_internal(
                "read_file",
                {"path": path, "start_line": 1, "end_line": 200},
                allow_fallback=False,
            )
            return (
                f"Automatic fallback: `list_directory` received a file path, so `read_file` was used instead.\n\n"
                f"{result}"
            )

        if name == "edit_file" and "target content not found" in message:
            result = self._execute_tool_internal(
                "smart_edit_file",
                args,
                allow_fallback=False,
                skip_permission=True,
                skip_backup=backup_taken,
            )
            return (
                "Automatic fallback: exact `edit_file` matching failed, so `smart_edit_file` retried with normalized matching.\n\n"
                f"{result}"
            )

        return None

    def _check_for_suggestions(self) -> str:
        """Check for improvement suggestions after actions."""
        recent_actions = self.session.actions[-5:]  # Last 5 actions
        has_modifications = any(a.action in ("created", "modified") for a in recent_actions)

        if not has_modifications:
            return ""

        suggestions = self.session.get_improvement_suggestions()
        if not suggestions:
            return ""

        text = "\n\n💡 **Suggestions:**\n"
        for s in suggestions:
            text += f"  • {s}\n"
        return text

    def clear_history(self) -> None:
        """Clear conversation history (keep system prompt)."""
        self._init_system_prompt()
        self.last_agent_team = None
        self.last_review_notes = ""
        self.last_plan_items = []
        self.last_plan_conventions = []
        self.last_plan_progress = []
        self.context.mark_workspace_state()

    def sync_workspace_state(self) -> dict[str, list[str]] | None:
        """Detect external editor changes and refresh context without clearing history."""
        changes = self.context.poll_external_changes()
        if any(changes.values()):
            self.refresh_context()
            return changes
        return None

    def _persist_turn_state(self, working_conversation: list[dict]) -> None:
        """Save conversation state and commit the current workspace snapshot."""
        self.conversation = working_conversation
        self.refresh_context()
        self.context.mark_workspace_state()

    @staticmethod
    def _format_workspace_change_message(changes: dict[str, list[str]], limit: int = 10) -> str:
        """Format external changes as hidden runtime guidance."""
        lines = [
            "External workspace edits were detected before this turn.",
            "Prioritize these files when the user refers to recent editor changes, new errors, or regressions.",
            "Use changed_files_diagnostics, git_diff_review, symbol_search, and focused file reads before widening the search.",
        ]
        for label in ("modified", "created", "deleted"):
            items = changes.get(label) or []
            if not items:
                continue
            shown = items[:limit]
            suffix = " ..." if len(items) > limit else ""
            lines.append(f"{label.title()}: {', '.join(shown)}{suffix}")
        return "\n".join(lines)

    def _should_surface_thinking(self, text: str) -> bool:
        """Keep raw reasoning hidden when it drifts far from the configured language."""
        if self.config.response_language.strip().lower() != "english":
            return True

        cjk_count = len(CJK_RE.findall(text))
        latin_count = len(re.findall(r"[A-Za-z]", text))
        return not (cjk_count >= 12 and cjk_count > latin_count)

    def _prepare_orchestration(self, messages: list[dict], tool_defs: list[dict], on_phase=None) -> OrchestrationContext | None:
        """Create a planner/executor/reviewer team for auto mode."""
        agent_mode = self._agent_mode()
        if agent_mode == "single":
            return None

        try:
            team = self.llm.select_agent_team(messages, tool_defs)
        except LLMError:
            return None

        self.last_agent_team = team

        if agent_mode == "parallel":
            return self._run_parallel_preflight(messages, tool_defs, team, on_phase=on_phase)

        if on_phase:
            on_phase("planner", team.planner)

        brief = self._run_planner(messages, tool_defs, team)
        parsed = self._parse_planner_brief(brief)
        convention_notes = parsed["conventions"] or self.context.analyze().get("conventions", [])
        return OrchestrationContext(
            team=team,
            brief=brief,
            todo_items=parsed["todo"],
            convention_notes=convention_notes,
        )

    def _build_runtime_messages(
        self,
        conversation: list[dict],
        orchestration: OrchestrationContext | None,
    ) -> list[dict]:
        """Inject the planner brief as hidden guidance for the executor."""
        if orchestration is None:
            return conversation

        injected_messages = []
        if orchestration.brief:
            injected_messages.append({
                "role": "system",
                "content": (
                    f"Internal execution brief from planner model {orchestration.team.planner}.\n"
                    "Use it as guidance only. Do not expose it to the user.\n\n"
                    f"{orchestration.brief}"
                ),
            })
        if orchestration.review_checklist:
            injected_messages.append({
                "role": "system",
                "content": (
                    f"Internal pre-review checklist from reviewer model {orchestration.team.reviewer}.\n"
                    "Use it to reduce mistakes. Do not expose it to the user.\n\n"
                    f"{orchestration.review_checklist}"
                ),
            })

        if not injected_messages:
            return conversation

        if conversation and conversation[0].get("role") == "system":
            return [conversation[0], *injected_messages, *conversation[1:]]
        return [*injected_messages, *conversation]

    def _run_planner(self, messages: list[dict], tool_defs: list[dict], team: AgentTeam) -> str:
        """Ask the planner model for a concise execution brief."""
        tool_names = ", ".join(tool["function"]["name"] for tool in tool_defs if tool.get("function"))
        planner_messages = [
            {
                "role": "system",
                "content": (
                    "You are the planning specialist for NeuDev.\n"
                    f"Write an INTERNAL execution brief in {self.config.response_language}.\n"
                    "Keep it concise. Include goal, affected components, likely files, tool priority, risks, and verification.\n"
                    "For backend/frontend or multi-component projects, mention both sides and any boundary files or contracts.\n"
                    "Use this exact plain-text structure with section labels followed by bullet items:\n"
                    "TODO:\nFILES:\nCONVENTIONS:\nRISKS:\nVERIFY:\n"
                    "Under TODO, list the concrete task checklist the agent should complete for the user.\n"
                    "Under CONVENTIONS, list the existing project patterns or coding structure that must be preserved.\n"
                    "Do not address the user directly. Do not use markdown headings."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Workspace context:\n{self.context.get_system_context()}\n\n"
                    f"Available tools: {tool_names}\n\n"
                    f"Conversation snapshot:\n{self._conversation_snapshot(messages)}"
                ),
            },
        ]
        try:
            response = self.llm.chat_with_fallback(
                planner_messages,
                think=False,
                preferred_models=self._role_candidate_models(team, "planner"),
                route_reason=f"planner selection; {team.route_reason}",
            )
        except LLMError:
            return ""

        return response.get("message", {}).get("content", "").strip()

    def _run_parallel_preflight(
        self,
        messages: list[dict],
        tool_defs: list[dict],
        team: AgentTeam,
        on_phase=None,
    ) -> OrchestrationContext:
        """Run planner and pre-review specialist concurrently before execution."""
        if on_phase:
            on_phase("planner", team.planner)
            on_phase("reviewer-pre", team.reviewer)

        with ThreadPoolExecutor(max_workers=2) as pool:
            planner_future = pool.submit(self._run_planner, messages, tool_defs, team)
            review_future = pool.submit(self._run_preflight_reviewer, messages, tool_defs, team)
            brief = planner_future.result()
            review_checklist = review_future.result()
        parsed = self._parse_planner_brief(brief)
        convention_notes = parsed["conventions"] or self.context.analyze().get("conventions", [])

        return OrchestrationContext(
            team=team,
            brief=brief,
            review_checklist=review_checklist,
            todo_items=parsed["todo"],
            convention_notes=convention_notes,
        )

    def _run_preflight_reviewer(self, messages: list[dict], tool_defs: list[dict], team: AgentTeam) -> str:
        """Ask the reviewer model for an internal checklist before execution."""
        tool_names = ", ".join(tool["function"]["name"] for tool in tool_defs if tool.get("function"))
        reviewer_messages = [
            {
                "role": "system",
                "content": (
                    "You are the preflight reviewer specialist for NeuDev.\n"
                    f"Write an INTERNAL checklist in {self.config.response_language}.\n"
                    "Focus on likely mistakes, risky file edits, missing validation, tool misuse, and missed cross-component impact.\n"
                    "Keep it concise with up to 3 bullets."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Workspace context:\n{self.context.get_system_context()}\n\n"
                    f"Available tools: {tool_names}\n\n"
                    f"Conversation snapshot:\n{self._conversation_snapshot(messages)}"
                ),
            },
        ]

        try:
            response = self.llm.chat_with_fallback(
                reviewer_messages,
                think=False,
                preferred_models=self._role_candidate_models(team, "reviewer"),
                route_reason=f"reviewer-pre selection; {team.route_reason}",
            )
        except LLMError:
            return ""

        return response.get("message", {}).get("content", "").strip()

    def _run_reviewer(
        self,
        user_message: str,
        final_response: str,
        orchestration: OrchestrationContext | None,
        turn_action_start: int,
        on_phase=None,
    ) -> str:
        """Ask the reviewer model to sanity-check the executor result."""
        if orchestration is None or not final_response:
            return ""

        turn_actions = self.session.actions[turn_action_start:]
        if not turn_actions:
            return ""

        if on_phase:
            on_phase("reviewer", orchestration.team.reviewer)

        review_messages = [
            {
                "role": "system",
                "content": (
                    "You are the reviewer specialist for NeuDev.\n"
                    f"Respond in {self.config.response_language}.\n"
                    "Review the executor output for correctness, missing validation, risky assumptions, and missed backend/frontend impact.\n"
                    "If everything is acceptable, reply with exactly: Approved.\n"
                    "Otherwise reply with up to 3 short bullet points."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User request:\n{user_message}\n\n"
                    f"Planner brief:\n{orchestration.brief or 'None'}\n\n"
                    f"Turn actions:\n{self._format_actions(turn_actions)}\n\n"
                    f"Executor response:\n{final_response}"
                ),
            },
        ]

        try:
            response = self.llm.chat_with_fallback(
                review_messages,
                think=False,
                preferred_models=self._role_candidate_models(orchestration.team, "reviewer"),
                route_reason=f"reviewer selection; {orchestration.team.route_reason}",
            )
        except LLMError:
            return ""

        review_text = response.get("message", {}).get("content", "").strip()
        if not review_text or review_text.lower() == "approved." or review_text.lower() == "approved":
            return ""
        return review_text

    @staticmethod
    def _parse_planner_brief(brief: str) -> dict[str, list[str]]:
        """Extract structured TODO and convention notes from the planner brief."""
        sections = {
            "todo": [],
            "files": [],
            "conventions": [],
            "risks": [],
            "verify": [],
        }
        current: str | None = None

        for raw_line in brief.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue

            header = stripped.strip("* ").rstrip(":").lower()
            if header in sections:
                current = header
                continue

            item = Agent._normalize_plan_item(stripped)
            if current and item:
                sections[current].append(item)

        if not sections["todo"] and brief.strip():
            fallback_items = []
            for line in brief.splitlines():
                item = Agent._normalize_plan_item(line.strip())
                if item:
                    fallback_items.append(item)
                if len(fallback_items) >= 5:
                    break
            sections["todo"] = fallback_items

        return sections

    @staticmethod
    def _normalize_plan_item(line: str) -> str:
        """Normalize planner bullets into plain checklist items."""
        if not line:
            return ""
        normalized = re.sub(r"^[-*•]\s*", "", line).strip()
        normalized = re.sub(r"^\d+\.\s*", "", normalized).strip()
        return normalized

    def _initialize_plan_progress(self, todo_items: list[str]) -> list[dict[str, str]]:
        """Create live progress state from planner todo items."""
        progress = [{"text": item, "status": "pending"} for item in todo_items if item.strip()]
        if progress:
            progress[0]["status"] = "in_progress"
        return progress

    def _emit_plan_update(self, callback) -> None:
        """Send the latest plan progress to the UI."""
        if callback and (self.last_plan_progress or self.last_plan_conventions):
            callback(
                [dict(item) for item in self.last_plan_progress],
                list(self.last_plan_conventions),
            )

    def _advance_plan_progress_from_tool(self, tool_name: str, tool_result: str) -> bool:
        """Advance the todo list after a successful tool action."""
        if not self.last_plan_progress or self._tool_result_failed(tool_result):
            return False
        stage = self._tool_stage(tool_name)
        return self._complete_plan_item(stage)

    def _advance_plan_progress_for_stage(self, stage: str) -> bool:
        """Advance the todo list for a specific phase such as verification."""
        if not self.last_plan_progress:
            return False
        return self._complete_plan_item(stage)

    def _complete_plan_item(self, stage: str) -> bool:
        """Mark the best matching todo item complete and move the pointer forward."""
        index = self._select_plan_item_index(stage)
        if index is None:
            return False

        self.last_plan_progress[index]["status"] = "completed"
        for item in self.last_plan_progress:
            if item["status"] == "in_progress":
                item["status"] = "pending"

        next_index = next(
            (i for i, item in enumerate(self.last_plan_progress) if item["status"] == "pending"),
            None,
        )
        if next_index is not None:
            self.last_plan_progress[next_index]["status"] = "in_progress"
        return True

    def _select_plan_item_index(self, stage: str) -> int | None:
        """Choose the most relevant incomplete todo item for the current stage."""
        if not self.last_plan_progress:
            return None

        in_progress_index = next(
            (i for i, item in enumerate(self.last_plan_progress) if item["status"] == "in_progress"),
            None,
        )
        if in_progress_index is not None and self._plan_item_stage(self.last_plan_progress[in_progress_index]["text"]) == stage:
            return in_progress_index

        for i, item in enumerate(self.last_plan_progress):
            if item["status"] == "completed":
                continue
            if self._plan_item_stage(item["text"]) == stage:
                return i

        return in_progress_index

    @staticmethod
    def _tool_result_failed(tool_result: str) -> bool:
        """Return True when the tool result indicates a failure."""
        lowered = tool_result.lower()
        return lowered.startswith("tool error") or lowered.startswith("unexpected error") or lowered.startswith("action denied")

    @staticmethod
    def _tool_stage(tool_name: str) -> str:
        """Map a tool name to a planning stage."""
        if tool_name in {
            "read_file", "read_files_batch", "search_files", "grep_search",
            "symbol_search", "list_directory", "file_outline", "git_diff_review",
        }:
            return "inspect"
        if tool_name in {
            "write_file", "edit_file", "smart_edit_file", "python_ast_edit",
            "js_ts_symbol_edit", "delete_file",
        }:
            return "change"
        if tool_name in {"run_command", "diagnostics", "changed_files_diagnostics"}:
            return "verify"
        return "other"

    @staticmethod
    def _plan_item_stage(text: str) -> str:
        """Infer the stage of a todo line from its wording."""
        lowered = text.lower()
        inspect_keywords = ("read", "inspect", "analy", "understand", "review", "find", "locate", "explore", "map")
        change_keywords = ("update", "implement", "edit", "change", "modify", "refactor", "fix", "add", "create", "remove", "delete", "wire")
        verify_keywords = ("verify", "test", "lint", "check", "validate", "diagnostic", "run")

        if any(keyword in lowered for keyword in inspect_keywords):
            return "inspect"
        if any(keyword in lowered for keyword in change_keywords):
            return "change"
        if any(keyword in lowered for keyword in verify_keywords):
            return "verify"
        return "other"

    @staticmethod
    def _conversation_snapshot(messages: list[dict], limit: int = 4) -> str:
        """Summarize the tail of the conversation for planner context."""
        tail = messages[-limit:]
        lines = []
        for item in tail:
            role = item.get("role", "unknown")
            content = str(item.get("content", "")).strip()
            if len(content) > 500:
                content = content[:500].rstrip() + "..."
            lines.append(f"[{role}] {content}")
        return "\n\n".join(lines)

    @staticmethod
    def _format_actions(actions) -> str:
        """Format session actions for reviewer context."""
        if not actions:
            return "No actions."
        return "\n".join(f"- {action.action}: {action.target}" for action in actions)

    def _agent_mode(self) -> str:
        """Return the normalized orchestration mode."""
        return getattr(self.config, "agent_mode", "parallel" if self.config.multi_agent else "single")

    @staticmethod
    def _role_candidate_models(team: AgentTeam, role: str) -> list[str]:
        """Build a fallback list for a specialist role."""
        ordered = []
        if role == "planner":
            ordered.extend([team.planner, team.reviewer])
        else:
            ordered.extend([team.reviewer, team.planner])
        ordered.extend(team.executor_candidates)

        unique: list[str] = []
        for model_name in ordered:
            if model_name and model_name not in unique:
                unique.append(model_name)
        return unique
