"""Agent reasoning loop for NeuDev - the brain of the system."""

from concurrent.futures import ThreadPoolExecutor
import difflib
import platform
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

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
- **write_file**: Create new files or overwrite existing ones (use overwrite=true to replace)
- **edit_file**: Edit files using exact find/replace
- **smart_edit_file**: Edit files with normalized/fuzzy matching fallbacks
- **find_replace**: Find and replace text across multiple files (supports regex)
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
- **web_search**: Search the web for documentation, error solutions, API references
- **url_fetch**: Fetch and extract text content from a URL
- **patch_file**: Apply unified diff patches to files
- **dependency_install**: Install project dependencies (auto-detects pip, npm, cargo, etc.)
- **project_init**: Scaffold new project structures (Python, Node.js, React)

## How to Work
1. **Understand First**: Read the user's request carefully. Ask clarifying questions if needed.
2. **Analyze**: Use list_directory, read_file, file_outline, and grep_search to understand the existing codebase.
3. **Plan**: Before making changes, explain what you will do and why.
4. **Execute**: Use the appropriate tools to make changes. Create files, edit code, run commands.
5. **Verify**: After changes, verify they work (e.g., run tests, check syntax).
6. **Report**: Summarize what you did and suggest next steps or improvements.

## Tool Selection Strategy
Choose tools based on your task type for optimal results:

**For debugging tasks** (errors, bugs, issues):
1. grep_search → Find error messages in code
2. read_file → Examine relevant files
3. diagnostics → Run tests/lint to confirm issue
4. edit_file or smart_edit_file → Fix the problem
5. run_command → Verify the fix works

**For coding tasks** (new features, implementations):
1. list_directory → Understand project structure
2. read_file or file_outline → Review existing code
3. write_file → Create new files (use overwrite=true to replace existing)
4. run_command → Test your changes
5. diagnostics → Ensure code quality

**For website creation tasks** (HTML/CSS/JS websites, landing pages, web apps):
1. project_init → Use template='html' with name parameter to scaffold standard website structure (FASTEST)
   - Example: project_init(template='html', name='Travel GO', directory='.')
2. write_file → Create individual HTML, CSS, or JS files with complete content
   - For single-page websites: write index.html, css/style.css, js/script.js
   - Always write COMPLETE file content, not placeholders
3. dependency_install → Install any npm packages if needed
4. run_command → Test with `python -m http.server` or open in browser
⚠️ IMPORTANT: Do NOT use web_search or url_fetch to create website files - these are for research only!
⚠️ IMPORTANT: Do NOT call project_init multiple times - call once with correct template and name

**For refactoring tasks** (restructuring, renaming):
1. symbol_search → Find all usages across the repo
2. read_files_batch → Review all affected files
3. find_replace → Rename across multiple files (best for simple text replacement)
4. patch_file → Apply structured changes (best for multi-region edits)
5. python_ast_edit or js_ts_symbol_edit → Symbol-level refactors
6. diagnostics → Verify nothing broke

**For research tasks** (documentation, API lookup):
1. web_search → Find external information and solutions
2. url_fetch → Read documentation from URLs
3. read_file → Check existing implementations
4. grep_search → Search for related patterns in codebase
⚠️ IMPORTANT: web_search and url_fetch are for RESEARCH ONLY - they do NOT create files!

**For dependency management**:
1. dependency_install → Install all dependencies or add new packages (auto-detects manager)
2. run_command → Verify installation with package-specific commands

**For new projects**:
1. project_init → Scaffold standard project structure (Python, Node.js, React, HTML)
   - HTML websites: project_init(template='html', name='Project Name')
   - Python projects: project_init(template='python', name='project-name')
   - Node.js projects: project_init(template='node', name='project-name')
   - React projects: project_init(template='react', name='Project Name')
2. dependency_install → Install the created project's dependencies

**For bulk text replacement**:
1. grep_search → First, find where the text appears
2. find_replace → Replace across multiple files at once (supports regex)
3. read_files_batch → Verify the changes
4. diagnostics → Ensure nothing broke

## Rules
- Always read existing files before editing them
- Explain what you're doing and why
- Use the correct tool for each task
- Follow the saved project memory so new changes stay consistent with the existing design and programming patterns
- If the user explicitly changes the framework, design direction, or coding style, adopt it for this task and let project memory refresh silently
- Use `symbol_search` when the task mentions a function, class, or method and you need fast repo navigation
- Prefer `python_ast_edit` or `js_ts_symbol_edit` for symbol-level refactors over brittle text replacement
- Prefer `patch_file` for multi-region edits instead of multiple edit_file calls
- Prefer `smart_edit_file` when exact text matching fails
- Use `web_search` and `url_fetch` when you need external information not in the workspace
- Prefer `changed_files_diagnostics` for quick verification after edits and `git_diff_review` before summarizing larger changes
- When the workspace has frontend/backend, mobile/backend, or multiple components, identify the affected components and inspect the boundary files before editing
- Determine the active stack and component from workspace context before editing; inspect the nearest package/config/entry files first
- Do not create files in a different language or framework than the active component unless the user explicitly requests a migration or new service
- For React/Next/Vite or other frontend work, inspect package.json, tsconfig, app entry/router, and nearby components before scaffolding missing files
- Use `python_ast_edit` only for existing Python code and `js_ts_symbol_edit` for JavaScript/TypeScript symbol changes
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
- NEVER output tool request syntax like `<tool_request>` or `{{"name": ...}}` in your final response - only use native tool calls
- Your final response should be natural language summarizing what was accomplished, not tool calls

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
FILE_MUTATION_TOOLS = {
    "write_file",
    "edit_file",
    "smart_edit_file",
    "python_ast_edit",
    "js_ts_symbol_edit",
    "delete_file",
}
READ_ONLY_TOOLS = {
    "read_file",
    "read_files_batch",
    "search_files",
    "grep_search",
    "symbol_search",
    "list_directory",
    "git_diff_review",
    "file_outline",
}


@dataclass
class OrchestrationContext:
    team: AgentTeam
    brief: str = ""
    review_checklist: str = ""
    todo_items: list[str] = field(default_factory=list)
    convention_notes: list[str] = field(default_factory=list)


class Agent:
    """ReAct-style agent that reasons and acts using tools."""

    def __init__(self, config: NeuDevConfig, workspace: str, llm_client: Any | None = None):
        self.config = config
        self.workspace = str(Path(workspace).resolve())
        self.llm = llm_client if llm_client is not None else OllamaClient(config)
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
        
        # Self-correction: track consecutive tool failures
        self._consecutive_failures: dict[str, int] = {}
        self._failure_suggestions: list[str] = []
        
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

    def _prune_conversation(self, messages: list[dict], max_messages: int = None) -> list[dict]:
        """
        Prune conversation to prevent context overflow on long sessions.
        
        Keeps system prompt + last N messages. Summarizes old context implicitly
        by removing it (the model retains understanding from recent messages).
        
        Args:
            messages: Full conversation history
            max_messages: Maximum messages to keep (default: config.max_context_messages)
            
        Returns:
            Pruned conversation list
        """
        if max_messages is None:
            max_messages = self.config.max_context_messages
            
        if len(messages) <= max_messages:
            return messages
        
        # Keep system prompt(s) - there should typically be only one
        system_messages = [m for m in messages if m.get("role") == "system"]
        
        # Keep the most recent non-system messages
        non_system = [m for m in messages if m.get("role") != "system"]
        recent = non_system[-max_messages:] if len(non_system) > max_messages else non_system
        
        # Combine: system messages first, then recent conversation
        return system_messages + recent

    def _track_tool_failure(self, tool_name: str, error: str) -> None:
        """
        Track consecutive failures for a tool to enable self-correction.
        
        Args:
            tool_name: Name of the failed tool
            error: Error message from the failure
        """
        self._consecutive_failures[tool_name] = (
            self._consecutive_failures.get(tool_name, 0) + 1
        )
        
        # Generate suggestion after 2 consecutive failures
        if self._consecutive_failures[tool_name] >= 2:
            suggestion = self._get_alternative_tool_suggestion(tool_name, error)
            if suggestion and suggestion not in self._failure_suggestions:
                self._failure_suggestions.append(suggestion)

    def _reset_tool_failure(self, tool_name: str) -> None:
        """
        Reset failure count on successful tool execution.
        
        Args:
            tool_name: Name of the successful tool
        """
        self._consecutive_failures.pop(tool_name, None)
        # Clear related suggestions
        self._failure_suggestions = []

    def _get_alternative_tool_suggestion(self, tool_name: str, error: str) -> str | None:
        """
        Suggest alternative tools after repeated failures.
        
        Args:
            tool_name: Name of the failing tool
            error: Error message
            
        Returns:
            Suggestion string or None
        """
        alternatives = {
            "edit_file": (
                "The exact text matching failed. Try smart_edit_file for fuzzy matching, "
                "or use write_file to rewrite the entire file, or patch_file for structured changes."
            ),
            "grep_search": (
                "Text search didn't find results. Try symbol_search for code symbols, "
                "or search_files to locate files by name pattern."
            ),
            "run_command": (
                "Command execution failed. Try checking if the command exists with 'which <cmd>' "
                "or 'command -v <cmd>' first, or verify the working directory is correct."
            ),
            "read_file": (
                "File not found. Try search_files to locate the correct file path first, "
                "or list_directory to see available files in the directory."
            ),
            "python_ast_edit": (
                "AST-based edit failed. The symbol may not exist or has a different name. "
                "Try symbol_search first to verify the exact symbol name and location."
            ),
            "js_ts_symbol_edit": (
                "Symbol edit failed. Try symbol_search to verify the symbol exists, "
                "or use edit_file with exact text matching instead."
            ),
        }
        
        base_suggestion = alternatives.get(tool_name)
        if not base_suggestion:
            return None
        
        # Add error-specific context
        error_context = ""
        if "not found" in error.lower() or "does not exist" in error.lower():
            error_context = " The target was not found - verify it exists first."
        elif "permission" in error.lower() or "denied" in error.lower():
            error_context = " Permission was denied - ensure you have the required access."
        elif "timeout" in error.lower():
            error_context = " Operation timed out - try a smaller change or increase timeout."
        
        return base_suggestion + error_context

    def _get_failure_suggestions(self) -> list[str]:
        """Get accumulated failure suggestions for inclusion in prompts."""
        return self._failure_suggestions.copy()

    def _clear_failure_history(self) -> None:
        """Clear all failure tracking (called after successful turn completion)."""
        self._consecutive_failures.clear()
        self._failure_suggestions.clear()

    def process_message(
        self,
        user_message: str,
        on_status=None,
        on_text=None,
        on_thinking=None,
        on_progress=None,
        on_phase=None,
        on_workspace_change=None,
        on_plan=None,
        on_plan_update=None,
        stop_event=None,
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
        
        # Prune conversation to prevent context overflow on long sessions
        working_conversation = self._prune_conversation(working_conversation)
        
        if workspace_changes and on_workspace_change:
            on_workspace_change(workspace_changes)
        if workspace_changes:
            working_conversation.append({
                "role": "system",
                "content": self._format_workspace_change_message(workspace_changes),
            })
        working_conversation.append({"role": "user", "content": user_message})
        
        # Add failure suggestions to context if any
        failure_suggestions = self._get_failure_suggestions()
        if failure_suggestions:
            suggestion_text = "\n\n## Recent Tool Failures and Suggestions\n" + "\n".join(
                f"- {s}" for s in failure_suggestions
            )
            working_conversation.append({
                "role": "system",
                "content": suggestion_text,
            })
        self.last_agent_team = None
        self.last_review_notes = ""
        self.last_plan_items = []
        self.last_plan_conventions = []
        self.last_plan_progress = []

        tool_defs = self.tool_registry.get_tool_definitions()
        final_response = ""
        use_thinking = self.config.show_thinking
        orchestration = self._prepare_orchestration(
            working_conversation,
            tool_defs,
            on_progress=on_progress,
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

        final_response, warned_about_tool_fallback, stopped = self._run_executor_loop(
            working_conversation,
            orchestration,
            tool_defs,
            preferred_models=preferred_models,
            route_reason=route_reason,
            use_thinking=use_thinking,
            on_status=on_status,
            on_text=on_text,
            on_thinking=on_thinking,
            on_progress=on_progress,
            on_plan_update=on_plan_update,
            stop_event=stop_event,
            warned_about_tool_fallback=False,
            max_iterations=self.config.max_iterations,
        )

        if not stopped:
            final_response = self._run_completion_guard(
                working_conversation,
                orchestration,
                tool_defs,
                user_message=user_message,
                final_response=final_response,
                turn_action_start=turn_action_start,
                preferred_models=preferred_models,
                route_reason=route_reason,
                use_thinking=use_thinking,
                on_status=on_status,
                on_text=on_text,
                on_thinking=on_thinking,
                on_progress=on_progress,
                on_plan_update=on_plan_update,
                stop_event=stop_event,
                warned_about_tool_fallback=warned_about_tool_fallback,
            )

        if stopped or self._is_stop_requested(stop_event):
            if not final_response:
                final_response = "Stopped by user before completion."
            self._persist_turn_state(working_conversation)
            return final_response

        review_notes = self._run_reviewer(
            user_message=user_message,
            final_response=final_response,
            orchestration=orchestration,
            turn_action_start=turn_action_start,
            on_progress=on_progress,
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

        self.context.memory.record_turn(
            user_message=user_message,
            action_targets=self._collect_turn_action_targets(self.session.actions[turn_action_start:]),
            review_notes=self.last_review_notes,
            response=final_response,
        )
        self._persist_turn_state(working_conversation)
        
        # Clear failure history after successful turn completion
        self._clear_failure_history()
        
        return final_response

    def _execute_tool(self, name: str, args: dict, event_callback=None, stop_event=None) -> str:
        """Execute a tool with permission checking and session tracking."""
        return self._execute_tool_internal(
            name,
            args,
            allow_fallback=True,
            event_callback=event_callback,
            stop_event=stop_event,
        )

    def _execute_tool_internal(
        self,
        name: str,
        args: dict,
        *,
        allow_fallback: bool,
        skip_permission: bool = False,
        skip_backup: bool = False,
        event_callback=None,
        stop_event=None,
    ) -> str:
        """Execute a tool, optionally allowing related-tool fallback."""
        tool = self.tool_registry.get(name)
        if tool is None:
            return f"Error: Unknown tool '{name}'"

        started_wall = datetime.now().strftime("%I:%M:%S %p")
        started_mono = time.monotonic()
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
                denied = f"Action denied by user: {name}"
                if event_callback:
                    event_callback(
                        name,
                        self._build_tool_result_event(
                            name,
                            args,
                            denied,
                            resolved_path=resolved_path,
                            backup=None,
                            elapsed=time.monotonic() - started_mono,
                            started_at=started_wall,
                            success=False,
                        ),
                    )
                return denied

        # Backup file before modification
        if self._is_stop_requested(stop_event):
            stopped_result = f"Stopped by user before executing tool: {name}"
            if event_callback:
                event_callback(
                    name,
                    self._build_tool_result_event(
                        name,
                        args,
                        stopped_result,
                        resolved_path=resolved_path,
                        backup=None,
                        elapsed=time.monotonic() - started_mono,
                        started_at=started_wall,
                        success=False,
                    ),
                )
            return stopped_result

        backup = None
        if not skip_backup and name in FILE_MUTATION_TOOLS:
            if resolved_path:
                backup = self.session.backup_file(resolved_path)
            elif raw_path:
                backup = self.session.backup_file(raw_path)

        if event_callback:
            event_callback(name, self._build_tool_start_event(name, args, resolved_path, started_wall))

        # Execute
        execute_args = dict(args)
        if name == "run_command":
            if event_callback:
                execute_args["progress_callback"] = lambda payload: event_callback(name, payload)
            execute_args["stop_event"] = stop_event
        try:
            result = tool.execute(**execute_args)
        except ToolError as e:
            if allow_fallback:
                fallback_result = self._attempt_tool_fallback(
                    name,
                    args,
                    error=e,
                    backup_taken=not skip_backup and name in FILE_MUTATION_TOOLS,
                    event_callback=event_callback,
                    stop_event=stop_event,
                )
                if fallback_result is not None:
                    return fallback_result
            error_result = f"Tool Error ({name}): {e}"
            # Track failure for self-correction
            self._track_tool_failure(name, str(e))
            if event_callback:
                event_callback(
                    name,
                    self._build_tool_result_event(
                        name,
                        args,
                        error_result,
                        resolved_path=resolved_path,
                        backup=backup,
                        elapsed=time.monotonic() - started_mono,
                        started_at=started_wall,
                        success=False,
                    ),
                )
            return error_result
        except Exception as e:
            error_result = f"Unexpected Error ({name}): {type(e).__name__}: {e}"
            # Track failure for self-correction
            self._track_tool_failure(name, str(e))
            if event_callback:
                event_callback(
                    name,
                    self._build_tool_result_event(
                        name,
                        args,
                        error_result,
                        resolved_path=resolved_path,
                        backup=backup,
                        elapsed=time.monotonic() - started_mono,
                        started_at=started_wall,
                        success=False,
                    ),
                )
            return error_result

        # Track success - reset failure count
        self._reset_tool_failure(name)
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
        event_payload = self._build_tool_result_event(
            name,
            args,
            result,
            resolved_path=resolved_path,
            backup=backup,
            elapsed=time.monotonic() - started_mono,
            started_at=started_wall,
            success=not self._tool_result_failed(result),
        )
        self.session.record_action(action_type, str(target), details=event_payload.get("summary", ""))

        # Track file access
        if resolved_path:
            self.context.track_file_access(resolved_path)
        for path in raw_paths:
            self.context.track_file_access(path)

        # Track test files
        if name in ("write_file", "smart_edit_file", "python_ast_edit", "js_ts_symbol_edit") and resolved_path:
            if "test_" in resolved_path or "_test." in resolved_path:
                self.session.track_test_file(resolved_path)

        if event_callback:
            event_callback(name, event_payload)
        return result

    def _attempt_tool_fallback(
        self,
        name: str,
        args: dict,
        error: Exception,
        backup_taken: bool,
        event_callback=None,
        stop_event=None,
    ) -> str | None:
        """Try a related tool automatically after a primary tool fails."""
        message = str(error).lower()
        path = args.get("path")

        if name == "read_file" and path:
            if "not a file" in message or "directory" in message:
                result = self._execute_tool_internal(
                    "list_directory",
                    {"path": path, "max_depth": 2},
                    allow_fallback=False,
                    event_callback=event_callback,
                    stop_event=stop_event,
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
                    event_callback=event_callback,
                    stop_event=stop_event,
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
                event_callback=event_callback,
                stop_event=stop_event,
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
                event_callback=event_callback,
                stop_event=stop_event,
            )
            return (
                "Automatic fallback: exact `edit_file` matching failed, so `smart_edit_file` retried with normalized matching.\n\n"
                f"{result}"
            )

        return None

    def _run_executor_loop(
        self,
        working_conversation: list[dict],
        orchestration: OrchestrationContext | None,
        tool_defs: list[dict],
        *,
        preferred_models: list[str] | None,
        route_reason: str | None,
        use_thinking: bool,
        on_status=None,
        on_text=None,
        on_thinking=None,
        on_progress=None,
        on_plan_update=None,
        stop_event=None,
        warned_about_tool_fallback: bool,
        max_iterations: int,
    ) -> tuple[str, bool, bool]:
        """Run the main LLM/tool loop and return the response, warning state, and stop flag."""
        final_response = ""
        stopped = False

        for _ in range(max_iterations):
            if self._is_stop_requested(stop_event):
                stopped = True
                break

            try:
                if on_progress:
                    on_progress(
                        {
                            "event": "model_wait",
                            "phase": "executor",
                            "model": preferred_models[0] if preferred_models else getattr(self.llm, "model", ""),
                            "detail": "Waiting for the executor model to decide the next step.",
                        }
                    )
                runtime_messages = self._build_runtime_messages(working_conversation, orchestration)
                result = self.llm.chat_with_tools(
                    messages=runtime_messages,
                    tools=tool_defs,
                    think=use_thinking,
                    preferred_models=preferred_models,
                    route_reason=route_reason,
                )
            except LLMError as exc:
                error_msg = f"LLM Error: {exc}"
                working_conversation.append({"role": "assistant", "content": error_msg})
                return error_msg, warned_about_tool_fallback, True

            if (
                not result.get("native_tools_supported", True)
                and not result.get("tool_calls")
                and not warned_about_tool_fallback
            ):
                warning = (
                    "\n\n⚠️ **Note:** This model did not use tools in this reply. "
                    "Switch to a stronger tool-calling model with `/models` if analysis stalls."
                )
                result["content"] = (result.get("content") or "") + warning
                warned_about_tool_fallback = True

            if result.get("thinking") and on_thinking and self._should_surface_thinking(result["thinking"]):
                on_thinking(result["thinking"])

            if result.get("content") and not result.get("tool_calls"):
                final_response = result["content"]
                if on_text:
                    on_text(result["content"])

            if result.get("done") or not result.get("tool_calls"):
                if final_response:
                    working_conversation.append({"role": "assistant", "content": final_response})
                break

            assistant_msg = {"role": "assistant", "content": ""}
            tool_calls = result.get("tool_calls") or []
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": tool_call["name"],
                            "arguments": tool_call["arguments"],
                        },
                    }
                    for tool_call in tool_calls
                ]
            working_conversation.append(assistant_msg)

            for tool_call in tool_calls:
                if self._is_stop_requested(stop_event):
                    stopped = True
                    break

                tool_name = tool_call["name"]
                tool_args = tool_call["arguments"]
                tool_result = self._execute_tool(
                    tool_name,
                    tool_args,
                    event_callback=on_status,
                    stop_event=stop_event,
                )
                if self._advance_plan_progress_from_tool(tool_name, tool_result):
                    self._emit_plan_update(on_plan_update)
                working_conversation.append(
                    {
                        "role": "tool",
                        "tool_name": tool_name,
                        "content": tool_result,
                    }
                )
                if self._is_stop_requested(stop_event):
                    stopped = True
                    break

            if stopped:
                break
        else:
            final_response += "\n\n⚠️ Reached maximum iterations. The task may be incomplete."
            working_conversation.append({"role": "assistant", "content": final_response})

        if stopped and not final_response:
            final_response = "Stopped by user before completion."
        return final_response, warned_about_tool_fallback, stopped

    def _run_completion_guard(
        self,
        working_conversation: list[dict],
        orchestration: OrchestrationContext | None,
        tool_defs: list[dict],
        *,
        user_message: str,
        final_response: str,
        turn_action_start: int,
        preferred_models: list[str] | None,
        route_reason: str | None,
        use_thinking: bool,
        on_status=None,
        on_text=None,
        on_thinking=None,
        on_progress=None,
        on_plan_update=None,
        stop_event=None,
        warned_about_tool_fallback: bool,
    ) -> str:
        """Run a bounded verification/remediation pass before the final review."""
        if self._is_stop_requested(stop_event):
            return final_response

        turn_actions = self.session.actions[turn_action_start:]
        had_turn_actions = bool(turn_actions)
        mutated_workspace = any(action.action in {"created", "modified", "deleted"} for action in turn_actions)
        diagnostics_result = ""
        requires_initial_repo_checks = (
            not had_turn_actions
            and self._should_require_initial_repo_checks(user_message)
            and not self._looks_like_clarification_response(final_response)
        )

        if mutated_workspace and self._should_run_completion_diagnostics(turn_actions):
            diagnostics_result = self._execute_tool(
                "changed_files_diagnostics",
                {},
                event_callback=on_status,
                stop_event=stop_event,
            )
            working_conversation.append(
                {
                    "role": "tool",
                    "tool_name": "changed_files_diagnostics",
                    "content": diagnostics_result,
                }
            )
            if self._advance_plan_progress_from_tool("changed_files_diagnostics", diagnostics_result):
                self._emit_plan_update(on_plan_update)

        incomplete_items = [
            item["text"]
            for item in self.last_plan_progress
            if item.get("status") in {"pending", "in_progress"}
        ]
        diagnostics_failed = bool(diagnostics_result) and self._tool_result_failed(diagnostics_result)
        needs_retry = requires_initial_repo_checks or diagnostics_failed or (had_turn_actions and bool(incomplete_items))
        if not needs_retry:
            return final_response

        if self._is_stop_requested(stop_event):
            return final_response

        guard_lines = [
            "Internal completion guard: do not summarize yet.",
        ]
        if requires_initial_repo_checks:
            guard_lines.append(
                "No repository inspection tools were used yet. Inspect the relevant files, configs, or tests before the final answer."
            )
            guard_lines.append(
                "Use focused inspection tools first, confirm the actual state of the workspace, then continue with changes or verification."
            )
        if diagnostics_failed:
            guard_lines.append(
                "Changed-file diagnostics reported an error. Fix the underlying issue before the final answer."
            )
            guard_lines.append(diagnostics_result[:1500])
        if incomplete_items:
            guard_lines.append("Remaining todo items:")
            guard_lines.extend(f"- {item}" for item in incomplete_items[:6])
        if final_response:
            guard_lines.append("Previous draft response:")
            guard_lines.append(final_response[:1500])

        working_conversation.append({"role": "system", "content": "\n".join(guard_lines)})
        retry_response, _, stopped = self._run_executor_loop(
            working_conversation,
            orchestration,
            tool_defs,
            preferred_models=preferred_models,
            route_reason=route_reason,
            use_thinking=use_thinking,
            on_status=on_status,
            on_text=on_text,
            on_thinking=on_thinking,
            on_progress=on_progress,
            on_plan_update=on_plan_update,
            stop_event=stop_event,
            warned_about_tool_fallback=warned_about_tool_fallback,
            max_iterations=min(4, max(1, self.config.max_iterations)),
        )
        if stopped and not retry_response:
            return final_response or "Stopped by user before completion."
        return retry_response or final_response

    @staticmethod
    def _should_run_completion_diagnostics(turn_actions) -> bool:
        """Limit automatic diagnostics to code and build/config file edits."""
        code_suffixes = {
            ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp",
            ".html", ".java", ".js", ".json", ".jsx", ".mjs", ".php",
            ".ps1", ".py", ".rb", ".rs", ".scss", ".sh", ".sql", ".toml",
            ".ts", ".tsx", ".vue", ".yaml", ".yml",
        }
        special_files = {
            "dockerfile",
            "makefile",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
            "tsconfig.json",
        }
        for action in turn_actions:
            if getattr(action, "action", "") not in {"created", "modified", "deleted"}:
                continue
            target = Path(str(getattr(action, "target", "") or ""))
            if target.suffix.lower() in code_suffixes:
                return True
            if target.name.lower() in special_files:
                return True
        return False

    @staticmethod
    def _should_require_initial_repo_checks(user_message: str) -> bool:
        """Require repo inspection before finalizing repo-specific implementation or analysis requests."""
        lowered = f" {str(user_message or '').lower()} "
        implementation_keywords = (
            " fix ", " build ", " create ", " implement ", " update ", " edit ",
            " change ", " modify ", " refactor ", " debug ", " generate ",
            " wire ", " scaffold ", " add ", " remove ",
        )
        inspection_keywords = (
            " analyze ", " inspect ", " understand ", " review ", " check ",
            " verify ", " summarize ", " explain ", " audit ", " investigate ",
        )
        repo_scope_keywords = (
            " project ", " repo ", " repository ", " codebase ", " workspace ",
            " file ", " files ", " folder ", " module ", " component ", " cli ",
            " agent ", " readme ", " package.json ", " pyproject.toml ",
        )
        if any(keyword in lowered for keyword in implementation_keywords):
            return True
        return any(keyword in lowered for keyword in inspection_keywords) and any(
            keyword in lowered for keyword in repo_scope_keywords
        )

    @staticmethod
    def _looks_like_clarification_response(final_response: str) -> bool:
        """Allow direct clarification questions without forcing repo inspection first."""
        text = " ".join(str(final_response or "").split()).lower()
        if not text:
            return False
        clarification_markers = (
            "could you clarify",
            "can you clarify",
            "please provide",
            "please share",
            "which ",
            "what ",
            "where ",
            "do you want",
        )
        return text.endswith("?") or any(marker in text for marker in clarification_markers)

    def _collect_turn_action_targets(self, turn_actions, limit: int = 6) -> list[str]:
        """Collect a compact set of repo-relative action targets for turn memory."""
        targets = []
        seen = set()
        workspace_root = Path(self.workspace)
        for action in turn_actions:
            raw_target = str(getattr(action, "target", "") or "").strip()
            if not raw_target:
                continue
            normalized = raw_target
            candidate = Path(raw_target)
            try:
                if candidate.is_absolute():
                    normalized = candidate.resolve().relative_to(workspace_root).as_posix()
            except (OSError, ValueError):
                normalized = raw_target.replace("\\", "/")
            if normalized in seen:
                continue
            seen.add(normalized)
            targets.append(normalized)
            if len(targets) >= limit:
                break
        return targets

    @staticmethod
    def _is_stop_requested(stop_event) -> bool:
        """Return True when a caller requested cancellation."""
        return bool(stop_event is not None and stop_event.is_set())

    def _build_tool_start_event(
        self,
        name: str,
        args: dict,
        resolved_path: str | None,
        started_at: str,
    ) -> dict:
        """Build a compact tool-start event for the CLI."""
        return {
            "event": "start",
            "tool": name,
            "target": self._tool_target(name, args, resolved_path),
            "started_at": started_at,
            "path": args.get("path", ""),
            "command": args.get("command", ""),
            "directory": args.get("directory", ""),
        }

    def _build_tool_result_event(
        self,
        name: str,
        args: dict,
        result: str,
        *,
        resolved_path: str | None,
        backup,
        elapsed: float,
        started_at: str,
        success: bool,
    ) -> dict:
        """Build a compact tool-result event for the CLI and session history."""
        target = self._tool_target(name, args, resolved_path)
        lines_added = 0
        lines_deleted = 0
        if name in FILE_MUTATION_TOOLS:
            lines_added, lines_deleted = self._line_change_counts(resolved_path, backup)

        preview = self._result_preview(result)
        parts = [target] if target else []
        if name in FILE_MUTATION_TOOLS and (lines_added or lines_deleted):
            parts.append(f"+{lines_added}/-{lines_deleted} lines")
        elif preview and name not in FILE_MUTATION_TOOLS:
            parts.append(preview)
        parts.append(f"{elapsed:.1f}s")

        if name == "run_command":
            action = "command"
        elif name in READ_ONLY_TOOLS:
            action = "read"
        elif name == "delete_file":
            action = "delete"
        else:
            action = "write"

        return {
            "event": "result",
            "tool": name,
            "target": target,
            "started_at": started_at,
            "elapsed": round(elapsed, 1),
            "success": success,
            "action": action,
            "lines_added": lines_added,
            "lines_deleted": lines_deleted,
            "result_preview": preview,
            "summary": " | ".join(part for part in parts if part),
            "path": args.get("path", ""),
            "command": args.get("command", ""),
            "directory": args.get("directory", ""),
        }

    @staticmethod
    def _tool_target(name: str, args: dict, resolved_path: str | None) -> str:
        """Choose the most useful target label for a tool event."""
        if name == "run_command":
            return str(args.get("command", "")).strip()
        if resolved_path:
            return str(resolved_path)
        if args.get("path"):
            return str(args.get("path"))
        if args.get("paths"):
            return ", ".join(str(item) for item in (args.get("paths") or [])[:3])
        return str(args.get("directory") or args.get("pattern") or "")

    def _line_change_counts(self, resolved_path: str | None, backup) -> tuple[int, int]:
        """Return added/deleted line counts for a changed text file."""
        before = getattr(backup, "original_content", None)
        after = None
        if resolved_path:
            candidate = Path(resolved_path)
            if candidate.exists():
                try:
                    after = candidate.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    after = None
        return self._count_line_diff(before, after)

    @staticmethod
    def _count_line_diff(before: str | None, after: str | None) -> tuple[int, int]:
        """Count approximate added/deleted lines between two text snapshots."""
        before_lines = [] if before is None else before.splitlines()
        after_lines = [] if after is None else after.splitlines()
        matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines)
        added = 0
        deleted = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in {"replace", "delete"}:
                deleted += i2 - i1
            if tag in {"replace", "insert"}:
                added += j2 - j1
        return added, deleted

    @staticmethod
    def _result_preview(result: str, limit: int = 100) -> str:
        """Extract a compact first-line preview from a tool result."""
        first_line = (result or "").strip().splitlines()[0] if result else ""
        if len(first_line) > limit:
            return first_line[:limit].rstrip() + "..."
        return first_line

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

    def _prepare_orchestration(self, messages: list[dict], tool_defs: list[dict], on_progress=None, on_phase=None) -> OrchestrationContext | None:
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
            return self._run_parallel_preflight(messages, tool_defs, team, on_progress=on_progress, on_phase=on_phase)

        if on_phase:
            on_phase("planner", team.planner)

        brief = self._run_planner(messages, tool_defs, team, on_progress=on_progress)
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

    def _run_planner(self, messages: list[dict], tool_defs: list[dict], team: AgentTeam, on_progress=None) -> str:
        """Ask the planner model for a concise execution brief."""
        tool_names = ", ".join(tool["function"]["name"] for tool in tool_defs if tool.get("function"))
        
        # Extract the actual user request from the conversation
        user_request = self._extract_user_request(messages)
        
        planner_messages = [
            {
                "role": "system",
                "content": (
                    "You are the planning specialist for NeuDev.\n"
                    f"Write an INTERNAL execution brief in {self.config.response_language}.\n"
                    "Keep it concise. Include goal, affected components, likely files, tool priority, risks, and verification.\n"
                    "For backend/frontend or multi-component projects, mention both sides and any boundary files or contracts.\n"
                    "Respect the detected stack and component boundaries. Do not suggest unrelated languages, frameworks, or scaffolding.\n"
                    "Use this exact plain-text structure with section labels followed by bullet items:\n"
                    "TODO:\nFILES:\nCONVENTIONS:\nRISKS:\nVERIFY:\n"
                    "Under TODO, list the concrete task checklist the agent should complete for the user.\n"
                    "Under FILES, list the first files or entrypoints the executor should inspect.\n"
                    "Under CONVENTIONS, list the existing project patterns or coding structure that must be preserved.\n"
                    "Do not address the user directly. Do not use markdown headings.\n\n"
                    "## CRITICAL RULES TO PREVENT HALLUCINATION:\n"
                    "1. ONLY create TODO items based on the EXPLICIT user request shown in the conversation snapshot.\n"
                    "2. DO NOT invent tasks, files, or directories that the user did not mention.\n"
                    "3. If the user request is simple (greeting, question), keep TODO empty or minimal.\n"
                    "4. DO NOT assume files/directories exist - verify with tools first.\n"
                    "5. For new project creation, use project_init tool, don't manually create files.\n"
                    "6. If workspace is empty and user wants new content, scaffold first, then implement.\n"
                    "7. NEVER reference files/directories from previous unrelated conversations.\n"
                    "8. Base your plan SOLELY on the current user request, not historical context.\n"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Workspace context:\n{self.context.get_system_context()}\n\n"
                    f"Available tools: {tool_names}\n\n"
                    f"Conversation snapshot:\n{self._conversation_snapshot(messages)}\n\n"
                    f"EXPLICIT USER REQUEST: {user_request}\n\n"
                    "IMPORTANT: Create TODO items ONLY for the explicit user request above. "
                    "Do not add tasks from previous conversations or assume file existence."
                ),
            },
        ]
        try:
            if on_progress:
                on_progress(
                    {
                        "event": "model_wait",
                        "phase": "planner",
                        "model": team.planner,
                        "detail": "Planner is building the execution checklist.",
                    }
                )
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
        on_progress=None,
        on_phase=None,
    ) -> OrchestrationContext:
        """Run planner and pre-review specialist concurrently before execution."""
        if on_phase:
            on_phase("planner", team.planner)
            on_phase("reviewer-pre", team.reviewer)

        with ThreadPoolExecutor(max_workers=2) as pool:
            planner_future = pool.submit(self._run_planner, messages, tool_defs, team, on_progress)
            review_future = pool.submit(self._run_preflight_reviewer, messages, tool_defs, team, on_progress)
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

    def _run_preflight_reviewer(self, messages: list[dict], tool_defs: list[dict], team: AgentTeam, on_progress=None) -> str:
        """Ask the reviewer model for an internal checklist before execution."""
        tool_names = ", ".join(tool["function"]["name"] for tool in tool_defs if tool.get("function"))
        user_request = self._extract_user_request(messages)
        
        reviewer_messages = [
            {
                "role": "system",
                "content": (
                    "You are the preflight reviewer specialist for NeuDev.\n"
                    f"Write an INTERNAL checklist in {self.config.response_language}.\n"
                    "Focus on likely mistakes, risky file edits, stack-mismatched changes, missing validation, tool misuse, and missed cross-component impact.\n"
                    "Keep it concise with up to 3 bullets.\n\n"
                    "## CRITICAL ANTI-HALLUCINATION CHECK:\n"
                    "1. Verify the planner's TODO items match the EXPLICIT user request.\n"
                    "2. Flag any TODO items that reference files/directories not mentioned by the user.\n"
                    "3. Ensure the plan doesn't assume file existence without verification.\n"
                    "4. For simple requests (greetings, questions), flag if planner created unnecessary tasks.\n"
                    "5. If workspace is empty, flag if planner assumes files exist.\n"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Workspace context:\n{self.context.get_system_context()}\n\n"
                    f"Available tools: {tool_names}\n\n"
                    f"Conversation snapshot:\n{self._conversation_snapshot(messages)}\n\n"
                    f"EXPLICIT USER REQUEST: {user_request}\n\n"
                    "IMPORTANT: Your checklist should catch any planner hallucination or tasks not grounded in the user request."
                ),
            },
        ]

        try:
            if on_progress:
                on_progress(
                    {
                        "event": "model_wait",
                        "phase": "reviewer-pre",
                        "model": team.reviewer,
                        "detail": "Pre-review is checking likely risks before execution.",
                    }
                )
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
        on_progress=None,
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
                    "Review the executor output for correctness, stack fit, missing validation, risky assumptions, and missed backend/frontend impact.\n"
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
            if on_progress:
                on_progress(
                    {
                        "event": "model_wait",
                        "phase": "reviewer",
                        "model": orchestration.team.reviewer,
                        "detail": "Reviewer is checking the completed work for gaps.",
                    }
                )
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
    def _extract_user_request(messages: list[dict]) -> str:
        """Extract the most recent user request from the conversation for grounded planning."""
        # Find the last user message (non-system, non-assistant)
        for msg in reversed(messages):
            role = msg.get("role", "")
            content = str(msg.get("content", "")).strip()
            if role == "user" and content:
                # Truncate very long requests but keep them grounded
                if len(content) > 500:
                    return content[:500].rstrip() + "..."
                return content
        return "No explicit request - user may be greeting or asking a question."

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
