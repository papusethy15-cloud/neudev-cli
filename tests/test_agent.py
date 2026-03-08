import threading
import unittest
from pathlib import Path
import shutil
from unittest.mock import patch

from neudev.agent import Agent
from neudev.config import NeuDevConfig
from neudev.model_routing import AgentTeam


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "workspace_basic"
FULLSTACK_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "workspace_fullstack"
REACT_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "workspace_react_app"


class FakeOllamaClient:
    def __init__(self, config):
        self.config = config
        self.responses = []
        self.chat_responses = []
        self.chat_with_tools_calls = []
        self.chat_with_fallback_calls = []
        self.chat_calls = []
        self.chat_handler = None
        self.team = None

    def chat_with_tools(self, messages, tools=None, think=False, preferred_models=None, route_reason=None):
        self.chat_with_tools_calls.append({
            "messages": messages,
            "tools": tools,
            "think": think,
            "preferred_models": preferred_models,
            "route_reason": route_reason,
        })
        if not self.responses:
            raise AssertionError("No fake responses configured")
        return self.responses.pop(0)

    def chat_with_fallback(self, messages, think=False, preferred_models=None, route_reason=None):
        self.chat_with_fallback_calls.append({
            "messages": messages,
            "think": think,
            "preferred_models": preferred_models,
            "route_reason": route_reason,
        })
        model_name = preferred_models[0] if preferred_models else None
        response = self.chat(
            messages,
            tools=None,
            stream=False,
            think=think,
            model_name=model_name,
        )
        enriched = dict(response)
        enriched["model"] = model_name
        enriched["route_reason"] = route_reason or ""
        enriched["thinking_enabled"] = think
        enriched["fallback_used"] = False
        return enriched

    def chat(self, messages, tools=None, stream=False, think=False, model_name=None):
        self.chat_calls.append({
            "messages": messages,
            "tools": tools,
            "stream": stream,
            "think": think,
            "model_name": model_name,
        })
        if self.chat_handler is not None:
            return self.chat_handler(
                messages,
                tools=tools,
                stream=stream,
                think=think,
                model_name=model_name,
            )
        if not self.chat_responses:
            raise AssertionError("No fake chat responses configured")
        return self.chat_responses.pop(0)

    def select_agent_team(self, messages, tools=None):
        if self.team is None:
            raise AssertionError("No fake team configured")
        return self.team


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.workspace = FIXTURE_ROOT
        self.readme_path = FIXTURE_ROOT / "README.md"
        self.example_path = FIXTURE_ROOT / "src" / "example.py"
        self.original_readme = self.readme_path.read_text(encoding="utf-8")
        self.original_example = self.example_path.read_text(encoding="utf-8")
        self.config = NeuDevConfig(
            show_thinking=True,
            response_language="English",
            multi_agent=False,
            agent_mode="single",
        )

    def tearDown(self):
        self.readme_path.write_text(self.original_readme, encoding="utf-8")
        self.example_path.write_text(self.original_example, encoding="utf-8")
        notes_path = self.workspace / "notes.txt"
        if notes_path.exists():
            notes_path.unlink()

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_tool_loop_hides_intermediate_planning_text(self):
        agent = Agent(self.config, str(self.workspace))
        agent.llm.responses = [
            {
                "content": "Let me inspect the project first.",
                "thinking": "",
                "tool_calls": [{"name": "read_file", "arguments": {"path": "README.md"}}],
                "done": False,
                "native_tools_supported": True,
            },
            {
                "content": "This is a Python project with a README.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        streamed = []
        response = agent.process_message("Analyze the project", on_text=streamed.append)

        self.assertEqual(response, "This is a Python project with a README.")
        self.assertEqual(streamed, ["This is a Python project with a README."])
        self.assertNotIn("Let me inspect", response)

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_system_prompt_includes_response_language(self):
        agent = Agent(self.config, str(self.workspace))
        system_prompt = agent.conversation[0]["content"]

        self.assertIn("User-facing replies must be in English", system_prompt)
        self.assertIn("Preferred response language: English", system_prompt)
        self.assertIn("Conventions:", system_prompt)
        self.assertIn("Indentation mostly uses 4 spaces.", system_prompt)

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_refresh_context_preserves_conversation_history(self):
        agent = Agent(self.config, str(self.workspace))
        agent.conversation.append({"role": "user", "content": "hello"})
        agent.conversation.append({"role": "assistant", "content": "world"})

        agent.refresh_context()

        self.assertEqual(agent.conversation[1]["content"], "hello")
        self.assertEqual(agent.conversation[2]["content"], "world")

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_non_english_thinking_is_not_displayed_when_language_is_english(self):
        agent = Agent(self.config, str(self.workspace))
        agent.llm.responses = [
            {
                "content": "Final answer in English.",
                "thinking": "\u8fd9\u662f\u4e00\u6bb5\u4e2d\u6587\u63a8\u7406\u5185\u5bb9\uff0c\u7528\u4e8e\u9a8c\u8bc1\u9690\u85cf\u903b\u8f91\u3002",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            }
        ]

        seen_thinking = []
        response = agent.process_message("Summarize", on_thinking=seen_thinking.append)

        self.assertEqual(response, "Final answer in English.")
        self.assertEqual(seen_thinking, [])

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_multi_agent_orchestration_uses_planner_executor_and_reviewer(self):
        config = NeuDevConfig(
            model="auto",
            response_language="English",
            multi_agent=True,
            agent_mode="team",
            show_thinking=False,
        )
        agent = Agent(config, str(self.workspace))
        agent.llm.team = AgentTeam(
            planner="qwen3:latest",
            executor="qwen2.5-coder:7b",
            reviewer="qwen3:latest",
            executor_candidates=("qwen2.5-coder:7b", "qwen3:latest"),
            route_reason="code generation and editing",
        )
        agent.llm.chat_responses = [
            {"message": {"content": "Inspect README, then implement and verify.", "thinking": "", "tool_calls": []}},
            {"message": {"content": "- Add verification for the new change.", "thinking": "", "tool_calls": []}},
        ]
        agent.llm.responses = [
            {
                "content": "I will inspect the workspace first.",
                "thinking": "",
                "tool_calls": [{"name": "read_file", "arguments": {"path": "README.md"}}],
                "done": False,
                "native_tools_supported": True,
            },
            {
                "content": "Implemented the change.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        phases = []
        response = agent.process_message(
            "Implement the feature",
            on_phase=lambda phase, model_name: phases.append((phase, model_name)),
        )

        self.assertEqual(
            phases,
            [
                ("planner", "qwen3:latest"),
                ("executor", "qwen2.5-coder:7b"),
                ("reviewer", "qwen3:latest"),
            ],
        )
        self.assertEqual(agent.last_agent_team.executor, "qwen2.5-coder:7b")
        self.assertEqual(
            agent.llm.chat_with_tools_calls[0]["preferred_models"],
            ["qwen2.5-coder:7b", "qwen3:latest"],
        )
        self.assertIn("Implemented the change.", response)
        self.assertIn("### Review Notes", response)

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_planner_emits_todo_list_and_convention_notes(self):
        config = NeuDevConfig(
            model="auto",
            response_language="English",
            agent_mode="team",
            show_thinking=False,
        )
        agent = Agent(config, str(self.workspace))
        agent.llm.team = AgentTeam(
            planner="qwen3:latest",
            executor="qwen2.5-coder:7b",
            reviewer="qwen3:latest",
            executor_candidates=("qwen2.5-coder:7b", "qwen3:latest"),
            route_reason="code generation and editing",
        )
        agent.llm.chat_responses = [
            {
                "message": {
                    "content": (
                        "TODO:\n"
                        "- Read backend entrypoint\n"
                        "- Update API handler\n"
                        "- Verify tests\n"
                        "FILES:\n"
                        "- src/sample_module.py\n"
                        "CONVENTIONS:\n"
                        "- Keep 4-space indentation\n"
                        "- Preserve type hints\n"
                        "RISKS:\n"
                        "- Avoid breaking callers\n"
                        "VERIFY:\n"
                        "- Run changed-file diagnostics\n"
                    ),
                    "thinking": "",
                    "tool_calls": [],
                }
            },
            {"message": {"content": "Approved.", "thinking": "", "tool_calls": []}},
        ]
        # Add extra responses for potential retry/completion guard calls
        agent.llm.responses = [
            {
                "content": "Done.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
            {
                "content": "Done.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        seen_plan = []
        response = agent.process_message(
            "Update the handler",
            on_plan=lambda todo, conventions: seen_plan.append((todo, conventions)),
        )

        self.assertIn("Done.", response)
        self.assertEqual(agent.last_plan_items[:3], ["Read backend entrypoint", "Update API handler", "Verify tests"])
        self.assertEqual(agent.last_plan_conventions[:2], ["Keep 4-space indentation", "Preserve type hints"])
        self.assertEqual(seen_plan[0][0][0], "Read backend entrypoint")
        self.assertEqual(seen_plan[0][1][0], "Keep 4-space indentation")

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_plan_progress_updates_as_tools_complete_steps(self):
        config = NeuDevConfig(
            model="auto",
            response_language="English",
            agent_mode="team",
            show_thinking=False,
        )
        agent = Agent(config, str(self.workspace))
        agent.permissions.auto_approve = True
        agent.llm.team = AgentTeam(
            planner="qwen3:latest",
            executor="qwen2.5-coder:7b",
            reviewer="qwen3:latest",
            executor_candidates=("qwen2.5-coder:7b", "qwen3:latest"),
            route_reason="code generation and editing",
        )
        agent.llm.chat_responses = [
            {
                "message": {
                    "content": (
                        "TODO:\n"
                        "- Inspect README\n"
                        "- Update demo function\n"
                        "- Verify result\n"
                        "CONVENTIONS:\n"
                        "- Keep 4-space indentation\n"
                    ),
                    "thinking": "",
                    "tool_calls": [],
                }
            },
            {"message": {"content": "Approved.", "thinking": "", "tool_calls": []}},
        ]
        agent.llm.responses = [
            {
                "content": "",
                "thinking": "",
                "tool_calls": [{"name": "read_file", "arguments": {"path": "README.md"}}],
                "done": False,
                "native_tools_supported": True,
            },
            {
                "content": "",
                "thinking": "",
                "tool_calls": [
                    {
                        "name": "edit_file",
                        "arguments": {
                            "path": "src/example.py",
                            "target_content": 'return "ok"',
                            "replacement_content": 'return "great"',
                        },
                    }
                ],
                "done": False,
                "native_tools_supported": True,
            },
            {
                "content": "Done.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        updates = []
        response = agent.process_message(
            "Update the example",
            on_plan_update=lambda plan, conventions: updates.append(([dict(item) for item in plan], list(conventions))),
        )

        self.assertIn("Done.", response)
        self.assertGreaterEqual(len(updates), 4)
        self.assertEqual(
            [item["status"] for item in updates[0][0]],
            ["in_progress", "pending", "pending"],
        )
        self.assertEqual(
            [item["status"] for item in updates[1][0]],
            ["completed", "in_progress", "pending"],
        )
        self.assertEqual(
            [item["status"] for item in updates[2][0]],
            ["completed", "completed", "in_progress"],
        )
        self.assertEqual(
            [item["status"] for item in updates[-1][0]],
            ["completed", "completed", "completed"],
        )
        self.assertIn('return "great"', self.example_path.read_text(encoding="utf-8"))

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_parallel_agent_mode_runs_planner_and_previewer_before_execution(self):
        config = NeuDevConfig(
            model="auto",
            response_language="English",
            agent_mode="parallel",
            show_thinking=False,
        )
        agent = Agent(config, str(self.workspace))
        agent.permissions.auto_approve = True
        agent.llm.team = AgentTeam(
            planner="qwen3:latest",
            executor="qwen2.5-coder:7b",
            reviewer="deepseek-coder:6.7b",
            executor_candidates=("qwen2.5-coder:7b", "qwen3:latest"),
            route_reason="code generation and editing",
        )

        started = set()
        release = threading.Event()
        lock = threading.Lock()

        def chat_handler(messages, tools=None, stream=False, think=False, model_name=None):
            system_text = messages[0]["content"]
            if "planning specialist" in system_text:
                role = "planner"
                content = "Plan: inspect README, edit code, verify."
            elif "preflight reviewer specialist" in system_text:
                role = "reviewer-pre"
                content = "- Check changed files.\n- Run verification."
            elif "reviewer specialist" in system_text:
                role = "reviewer"
                content = "Approved."
            else:
                raise AssertionError("Unexpected chat prompt")

            if role in {"planner", "reviewer-pre"}:
                with lock:
                    started.add(role)
                    if started == {"planner", "reviewer-pre"}:
                        release.set()
                self.assertTrue(release.wait(1), "planner and reviewer-pre did not run concurrently")

            return {"message": {"content": content, "thinking": "", "tool_calls": []}}

        agent.llm.chat_handler = chat_handler
        # Add extra responses for potential retry/completion guard calls
        agent.llm.responses = [
            {
                "content": "Implemented the feature.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
            {
                "content": "Implemented the feature.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        phases = []
        response = agent.process_message(
            "Implement the feature",
            on_phase=lambda phase, model_name: phases.append((phase, model_name)),
        )

        self.assertIn(("planner", "qwen3:latest"), phases)
        self.assertIn(("reviewer-pre", "deepseek-coder:6.7b"), phases)
        self.assertIn(("executor", "qwen2.5-coder:7b"), phases)
        self.assertEqual(started, {"planner", "reviewer-pre"})
        runtime_messages = agent.llm.chat_with_tools_calls[0]["messages"]
        system_messages = [msg["content"] for msg in runtime_messages if msg.get("role") == "system"]
        self.assertTrue(any("Internal execution brief" in msg for msg in system_messages))
        self.assertTrue(any("Internal pre-review checklist" in msg for msg in system_messages))
        fallback_lists = [call["preferred_models"] for call in agent.llm.chat_with_fallback_calls[:2]]
        self.assertCountEqual(
            fallback_lists,
            [
                ["qwen3:latest", "deepseek-coder:6.7b", "qwen2.5-coder:7b"],
                ["deepseek-coder:6.7b", "qwen3:latest", "qwen2.5-coder:7b"],
            ],
        )
        self.assertEqual(response, "Implemented the feature.")

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_external_editor_changes_are_detected_and_injected_into_runtime_messages(self):
        agent = Agent(self.config, str(self.workspace))
        agent.permissions.auto_approve = True
        self.readme_path.write_text(self.original_readme + "\neditor change\n", encoding="utf-8")
        # Add extra responses for potential retry/completion guard calls
        agent.llm.responses = [
            {
                "content": "I checked the latest changes.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
            {
                "content": "I checked the latest changes.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        detected = []
        response = agent.process_message(
            "Please fix the latest error",
            on_workspace_change=lambda changes: detected.append(changes),
        )

        self.assertEqual(response, "I checked the latest changes.")
        self.assertEqual(len(detected), 1)
        self.assertIn("README.md", detected[0]["modified"])
        runtime_messages = agent.llm.chat_with_tools_calls[0]["messages"]
        hidden_notes = [
            msg["content"]
            for msg in runtime_messages
            if msg.get("role") == "system" and "External workspace edits were detected" in msg.get("content", "")
        ]
        self.assertEqual(len(hidden_notes), 1)
        self.assertIn("README.md", hidden_notes[0])

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_tool_status_events_include_file_line_counts(self):
        config = NeuDevConfig(
            model="auto",
            response_language="English",
            agent_mode="single",
            show_thinking=False,
        )
        agent = Agent(config, str(self.workspace))
        agent.permissions.auto_approve = True
        agent.llm.responses = [
            {
                "content": "",
                "thinking": "",
                "tool_calls": [
                    {
                        "name": "write_file",
                        "arguments": {
                            "path": "notes.txt",
                            "content": "line 1\nline 2\n",
                        },
                    }
                ],
                "done": False,
                "native_tools_supported": True,
            },
            {
                "content": "Created the note.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        events = []
        response = agent.process_message("Create a note", on_status=lambda name, payload: events.append((name, dict(payload))))

        self.assertIn("Created the note.", response)
        result_event = next(
            payload for name, payload in events if name == "write_file" and payload.get("event") == "result"
        )
        self.assertEqual(result_event["lines_added"], 2)
        self.assertEqual(result_event["lines_deleted"], 0)
        self.assertTrue(result_event["success"])

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_process_message_passes_stop_event_into_tool_execution(self):
        agent = Agent(self.config, str(self.workspace))
        agent.permissions.auto_approve = True
        stop_event = threading.Event()
        received = {}
        tool = agent.tool_registry.get("run_command")
        agent.llm.responses = [
            {
                "content": "",
                "thinking": "",
                "tool_calls": [{"name": "run_command", "arguments": {"command": "python --version"}}],
                "done": False,
                "native_tools_supported": True,
            },
            {
                "content": "Done.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        def fake_execute(**kwargs):
            received["stop_event"] = kwargs.get("stop_event")
            return "ok"

        with patch.object(tool, "execute", side_effect=fake_execute):
            response = agent.process_message("Run a command", stop_event=stop_event)

        self.assertEqual(response, "Done.")
        self.assertIs(received["stop_event"], stop_event)

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_process_message_emits_progress_when_waiting_for_executor_model(self):
        agent = Agent(self.config, str(self.workspace))
        agent.llm.responses = [
            {
                "content": "Done.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            }
        ]

        progress_updates = []
        response = agent.process_message("Write a short greeting", on_progress=progress_updates.append)

        self.assertEqual(response, "Done.")
        self.assertTrue(progress_updates)
        self.assertEqual(progress_updates[0]["event"], "model_wait")
        self.assertEqual(progress_updates[0]["phase"], "executor")

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_process_message_retries_when_repo_task_skips_initial_inspection(self):
        agent = Agent(self.config, str(self.workspace))
        agent.llm.responses = [
            {
                "content": "I can fix the CLI flow directly without checking the repo.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
            {
                "content": "",
                "thinking": "",
                "tool_calls": [{"name": "read_file", "arguments": {"path": "README.md"}}],
                "done": False,
                "native_tools_supported": True,
            },
            {
                "content": "I inspected the README and confirmed the current CLI flow.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        response = agent.process_message("Fix the CLI project creation flow")

        self.assertEqual(response, "I inspected the README and confirmed the current CLI flow.")
        self.assertTrue(any(action.action == "read" for action in agent.session.actions))
        self.assertTrue(
            any(
                "No repository inspection tools were used yet." in message.get("content", "")
                for call in agent.llm.chat_with_tools_calls
                for message in call["messages"]
            )
        )
        self.assertTrue(
            any(
                "Use focused inspection tools first" in message.get("content", "")
                for call in agent.llm.chat_with_tools_calls
                for message in call["messages"]
            )
        )

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_process_message_persists_recent_turn_memory(self):
        memory_dir = self.workspace / ".memory_store_test"
        shutil.rmtree(memory_dir, ignore_errors=True)
        with patch("neudev.project_memory.PROJECT_MEMORY_DIR", memory_dir):
            agent = Agent(self.config, str(self.workspace))
            agent.llm.responses = [
                {
                    "content": "",
                    "thinking": "",
                    "tool_calls": [{"name": "read_file", "arguments": {"path": "README.md"}}],
                    "done": False,
                    "native_tools_supported": True,
                },
                {
                    "content": "README inspected.",
                    "thinking": "",
                    "tool_calls": [],
                    "done": True,
                    "native_tools_supported": True,
                },
            ]

            response = agent.process_message("Analyze the README flow")

            self.assertEqual(response, "README inspected.")
            reloaded = Agent(self.config, str(self.workspace))
            prompt = reloaded.conversation[0]["content"]
            self.assertIn("Recent work:", prompt)
            self.assertIn("Analyze the README flow", prompt)
            self.assertIn("README.md", prompt)
        shutil.rmtree(memory_dir, ignore_errors=True)

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_system_prompt_describes_fullstack_backend_and_frontend_components(self):
        agent = Agent(self.config, str(FULLSTACK_FIXTURE_ROOT))
        system_prompt = agent.conversation[0]["content"]

        self.assertIn("Project type: fullstack", system_prompt)
        self.assertIn("Technologies: Python, FastAPI, Node.js, React", system_prompt)
        self.assertIn("- backend [backend/python]", system_prompt)
        self.assertIn("- frontend [frontend/node]", system_prompt)
        self.assertIn("Project Memory:", system_prompt)
        self.assertIn("Preferred stack:", system_prompt)

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_system_prompt_adds_frontend_stack_guardrails_for_react_workspaces(self):
        agent = Agent(self.config, str(REACT_FIXTURE_ROOT))
        system_prompt = agent.conversation[0]["content"]

        self.assertIn("Project type: frontend app", system_prompt)
        self.assertIn("Primary role: frontend", system_prompt)
        self.assertIn("Likely entry files: src/main.tsx", system_prompt)
        self.assertIn("Stack guardrails:", system_prompt)
        self.assertIn("Do not introduce unrelated Python", system_prompt)
        self.assertIn("Do not create files in a different language or framework than the active component", system_prompt)

    @patch("neudev.agent.OllamaClient", FakeOllamaClient)
    def test_project_memory_persists_user_directed_style_changes(self):
        memory_dir = self.workspace / ".memory_store_test"
        shutil.rmtree(memory_dir, ignore_errors=True)
        with patch("neudev.project_memory.PROJECT_MEMORY_DIR", memory_dir):
            agent = Agent(self.config, str(self.workspace))
            changed = agent.context.apply_user_memory_directives(
                "Use React with single quotes and 2 spaces for the frontend."
            )
            agent.refresh_context()

            self.assertTrue(changed)
            prompt = agent.conversation[0]["content"]
            self.assertIn("String literals should use single quotes.", prompt)
            self.assertIn("Indentation should use 2 spaces.", prompt)
            self.assertIn("Preferred stack:", prompt)
            self.assertIn("React", prompt)

            reloaded = Agent(self.config, str(self.workspace))
            reloaded_prompt = reloaded.conversation[0]["content"]
            self.assertIn("String literals should use single quotes.", reloaded_prompt)
            self.assertIn("Indentation should use 2 spaces.", reloaded_prompt)
        shutil.rmtree(memory_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
