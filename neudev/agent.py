"""Agent reasoning loop for NeuDev - the brain of the system."""

import json
from pathlib import Path
from typing import Optional

from neudev.config import NeuDevConfig
from neudev.llm import OllamaClient, LLMError, ToolsNotSupportedError
from neudev.tools import ToolRegistry, create_tool_registry
from neudev.tools.base import ToolError
from neudev.context import WorkspaceContext
from neudev.session import SessionManager
from neudev.permissions import PermissionManager


SYSTEM_PROMPT = """You are NeuDev, an advanced AI coding agent. You help users build, modify, and understand code projects.

## Your Capabilities
You have access to powerful tools for file system operations:
- **read_file**: Read file contents with optional line ranges
- **write_file**: Create new files or overwrite existing ones
- **edit_file**: Edit files using find/replace
- **delete_file**: Delete files
- **search_files**: Search for files by name/pattern
- **grep_search**: Search file contents for text/patterns
- **list_directory**: List directory contents as a tree
- **run_command**: Execute shell commands
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
- If a task requires multiple steps, execute them in order
- When creating test files, mention they are test files
- Suggest improvements after creating or modifying code
- Be precise with file paths - use the workspace directory as the base
- When editing files, provide the EXACT text to find and replace

## Workspace Context
{workspace_context}

## Important
- You are running on Windows
- The workspace directory is: {workspace_path}
- Use forward slashes or escaped backslashes in paths
- Be helpful, precise, and professional
"""


class Agent:
    """ReAct-style agent that reasons and acts using tools."""

    def __init__(self, config: NeuDevConfig, workspace: str):
        self.config = config
        self.workspace = str(Path(workspace).resolve())
        self.llm = OllamaClient(config)
        self.tool_registry = create_tool_registry()
        self.context = WorkspaceContext(self.workspace)
        self.session = SessionManager(self.workspace)
        self.permissions = PermissionManager()
        self.conversation: list[dict] = []
        self._init_system_prompt()

    def _init_system_prompt(self) -> None:
        """Initialize the system prompt with workspace context."""
        workspace_context = self.context.get_system_context()
        system_content = SYSTEM_PROMPT.format(
            workspace_context=workspace_context,
            workspace_path=self.workspace,
        )
        self.conversation = [{"role": "system", "content": system_content}]

    def refresh_context(self) -> None:
        """Refresh the workspace context in the system prompt."""
        self._init_system_prompt()

    def process_message(self, user_message: str, on_status=None, on_text=None, on_thinking=None) -> str:
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
        self.conversation.append({"role": "user", "content": user_message})

        tool_defs = self.tool_registry.get_tool_definitions()
        final_response = ""
        use_thinking = self.config.show_thinking

        for iteration in range(self.config.max_iterations):
            try:
                result = self.llm.chat_with_tools(
                    messages=self.conversation,
                    tools=tool_defs,
                    think=use_thinking,
                )
            except ToolsNotSupportedError:
                # Model doesn't support tools — retry without them
                try:
                    result = self.llm.chat_with_tools(
                        messages=self.conversation,
                        tools=None,
                        think=use_thinking,
                    )
                    # Append a warning note so the user knows
                    warning = (
                        "\n\n⚠️ **Note:** This model does not support tool calling. "
                        "File and command tools are unavailable. "
                        "Use `/models` to switch to a tool-capable model."
                    )
                    if result["content"]:
                        result["content"] += warning
                    else:
                        result["content"] = warning
                    result["done"] = True
                    result["tool_calls"] = []
                except LLMError as e2:
                    error_msg = f"LLM Error: {e2}"
                    self.conversation.append({"role": "assistant", "content": error_msg})
                    return error_msg
            except LLMError as e:
                error_msg = f"LLM Error: {e}"
                self.conversation.append({"role": "assistant", "content": error_msg})
                return error_msg

            # If there's thinking content, send it to the callback
            if result.get("thinking") and on_thinking:
                on_thinking(result["thinking"])

            # If there's text content, accumulate it
            if result["content"]:
                final_response += result["content"]
                if on_text:
                    on_text(result["content"])

            # If no tool calls, we're done
            if result["done"] or not result["tool_calls"]:
                if final_response:
                    self.conversation.append({"role": "assistant", "content": final_response})
                break

            # Process tool calls
            # Add assistant message with tool calls to conversation
            assistant_msg = {"role": "assistant", "content": result["content"] or ""}
            if result["tool_calls"]:
                assistant_msg["tool_calls"] = [
                    {
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        }
                    }
                    for tc in result["tool_calls"]
                ]
            self.conversation.append(assistant_msg)

            for tool_call in result["tool_calls"]:
                tool_name = tool_call["name"]
                tool_args = tool_call["arguments"]

                if on_status:
                    on_status(tool_name, tool_args)

                # Execute the tool
                tool_result = self._execute_tool(tool_name, tool_args)

                # Add tool result to conversation
                self.conversation.append({
                    "role": "tool",
                    "content": tool_result,
                })

        else:
            # Hit max iterations
            final_response += "\n\n⚠️ Reached maximum iterations. The task may be incomplete."
            self.conversation.append({"role": "assistant", "content": final_response})

        # Check for improvement suggestions after modifications
        suggestions = self._check_for_suggestions()
        if suggestions:
            final_response += suggestions

        return final_response

    def _execute_tool(self, name: str, args: dict) -> str:
        """Execute a tool with permission checking and session tracking."""
        tool = self.tool_registry.get(name)
        if tool is None:
            return f"Error: Unknown tool '{name}'"

        # Permission check for destructive tools
        if tool.requires_permission:
            message = tool.permission_message(args)
            if not self.permissions.request_permission(name, message):
                return f"Action denied by user: {name}"

        # Backup file before modification
        if name in ("write_file", "edit_file", "delete_file"):
            path = args.get("path", "")
            if path:
                self.session.backup_file(path)

        # Execute
        try:
            result = tool.execute(**args)
        except ToolError as e:
            return f"Tool Error ({name}): {e}"
        except Exception as e:
            return f"Unexpected Error ({name}): {type(e).__name__}: {e}"

        # Track the action
        action_map = {
            "read_file": "read",
            "write_file": "created",
            "edit_file": "modified",
            "delete_file": "deleted",
            "run_command": "command",
        }
        action_type = action_map.get(name, "other")
        target = args.get("path", args.get("command", args.get("directory", name)))
        self.session.record_action(action_type, str(target))

        # Track file access
        if "path" in args:
            self.context.track_file_access(args["path"])

        # Track test files
        if name == "write_file" and ("test_" in str(args.get("path", "")) or "_test." in str(args.get("path", ""))):
            self.session.track_test_file(args["path"])

        return result

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
