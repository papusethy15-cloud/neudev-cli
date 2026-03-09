import unittest
from unittest.mock import patch

from neudev.config import NeuDevConfig
from neudev.llm import LLMError, ModelNotFoundError, OllamaClient, ToolsNotSupportedError
from neudev.model_routing import build_agent_team, rank_models, should_enable_thinking


MODELS = [
    {"name": "starcoder2:7b", "size": 3800000000},
    {"name": "codellama:7b", "size": 3600000000},
    {"name": "deepseek-coder:6.7b", "size": 3600000000},
    {"name": "deepseek-coder-v2:16b", "size": 8900000000},
    {"name": "nomic-embed-text", "size": 274000000},
    {"name": "qwen2.5-coder:7b", "size": 4400000000},
    {"name": "qwen3:4b", "size": 2900000000},
    {"name": "qwen3:latest", "size": 6100000000},
]


class RoutingClient(OllamaClient):
    def _test_connection(self) -> None:
        pass


class ModelRoutingTests(unittest.TestCase):
    def test_rank_models_prefers_qwen3_for_tool_heavy_analysis(self):
        ranked, reason = rank_models(
            MODELS,
            [{"role": "user", "content": "Deeply analyze this repository architecture and explain the agent workflow"}],
            has_tools=True,
        )

        self.assertEqual(ranked[0]["name"], "qwen3:latest")
        self.assertIn("analysis", reason)

    def test_rank_models_prefers_qwen25_coder_for_plain_code_generation(self):
        ranked, reason = rank_models(
            MODELS,
            [{"role": "user", "content": "Write a Python function and generate tests"}],
            has_tools=False,
        )

        # Now prefers deepseek-coder-v2 for substantial coding tasks
        self.assertEqual(ranked[0]["name"], "deepseek-coder-v2:16b")
        self.assertIn("code", reason)

    def test_rank_models_prefers_deepseek_v2_for_complex_refactors(self):
        ranked, reason = rank_models(
            MODELS,
            [{"role": "user", "content": "Refactor this module across multiple files and migrate the API surface"}],
            has_tools=True,
        )

        self.assertEqual(ranked[0]["name"], "deepseek-coder-v2:16b")
        self.assertIn("refactor", reason)

    def test_rank_models_prefers_deepseek_coder_for_plain_debugging(self):
        ranked, reason = rank_models(
            MODELS,
            [{"role": "user", "content": "Debug this failing test and fix the traceback"}],
            has_tools=False,
        )

        self.assertEqual(ranked[0]["name"], "deepseek-coder:6.7b")
        self.assertIn("debug", reason)

    def test_rank_models_prefers_starcoder_for_quick_edits_without_tools(self):
        ranked, reason = rank_models(
            MODELS,
            [{"role": "user", "content": "Make a quick one-line typo fix in this file"}],
            has_tools=False,
        )

        self.assertEqual(ranked[0]["name"], "starcoder2:7b")
        self.assertIn("quick", reason)

    def test_rank_models_detects_react_typescript_stack_from_workspace_context(self):
        ranked, reason = rank_models(
            MODELS,
            [
                {"role": "system", "content": "Workspace: app\nTechnologies: React, TypeScript, Node.js"},
                {"role": "user", "content": "Implement the dashboard component and wire the page route"},
            ],
            has_tools=True,
        )

        # Now prefers deepseek-coder-v2 for implementation tasks with React stack
        self.assertEqual(ranked[0]["name"], "deepseek-coder-v2:16b")
        self.assertIn("React/TypeScript", reason)

    def test_rank_models_detects_flutter_stack_for_planning(self):
        ranked, reason = rank_models(
            MODELS,
            [
                {"role": "system", "content": "Workspace: app\nTechnologies: Flutter, Dart"},
                {"role": "user", "content": "Analyze the mobile app architecture and plan the next change"},
            ],
            has_tools=True,
        )

        self.assertEqual(ranked[0]["name"], "qwen3:latest")
        self.assertIn("Flutter/Dart", reason)

    def test_rank_models_prefers_qwen25_for_react_analysis_then_implementation(self):
        ranked, reason = rank_models(
            MODELS,
            [
                {
                    "role": "system",
                    "content": (
                        "Workspace: app\n"
                        "Project type: frontend app\n"
                        "Primary role: frontend\n"
                        "Technologies: Node.js, React, TypeScript, Vite\n"
                        "Likely entry files: src/main.tsx, src/App.tsx"
                    ),
                },
                {
                    "role": "user",
                    "content": "Deeply analyze this React app and complete the missing dashboard page and route wiring",
                },
            ],
            has_tools=True,
        )

        # Now prefers deepseek-coder-v2 for complex analysis+implementation tasks
        self.assertEqual(ranked[0]["name"], "deepseek-coder-v2:16b")
        self.assertIn("implementation", reason)
        self.assertIn("React/TypeScript", reason)

    def test_rank_models_ignores_embeddings_for_code_search(self):
        ranked, reason = rank_models(
            MODELS,
            [{"role": "user", "content": "Find where this symbol is used across the repo"}],
            has_tools=True,
        )

        self.assertEqual(ranked[0]["name"], "qwen3:latest")
        self.assertTrue(all(model["name"] != "nomic-embed-text" for model in ranked))
        self.assertIn("search", reason)

    def test_thinking_is_disabled_for_weaker_or_unstable_profiles(self):
        self.assertTrue(should_enable_thinking("qwen3:latest", True))
        self.assertFalse(should_enable_thinking("deepseek-coder:6.7b", True))
        self.assertFalse(should_enable_thinking("codellama:7b", True))

    def test_build_agent_team_splits_roles_for_auto_mode(self):
        team = build_agent_team(
            MODELS,
            [{"role": "user", "content": "Implement a Python function and create tests"}],
            has_tools=True,
        )

        self.assertEqual(team.planner, "qwen3:latest")
        # Now prefers deepseek-coder-v2 for coding tasks
        self.assertEqual(team.executor, "deepseek-coder-v2:16b")
        self.assertNotEqual(team.reviewer, team.executor)
        self.assertIn("qwen3:latest", team.executor_candidates)

    def test_build_agent_team_uses_coding_executor_for_react_analysis_and_build_requests(self):
        team = build_agent_team(
            MODELS,
            [
                {
                    "role": "system",
                    "content": (
                        "Workspace: app\n"
                        "Project type: frontend app\n"
                        "Primary role: frontend\n"
                        "Technologies: Node.js, React, TypeScript, Vite\n"
                        "Likely entry files: src/main.tsx, src/App.tsx"
                    ),
                },
                {
                    "role": "user",
                    "content": "Deeply analyze this React app and complete the missing dashboard page and route wiring",
                },
            ],
            has_tools=True,
        )

        self.assertEqual(team.planner, "qwen3:latest")
        # Now prefers deepseek-coder-v2 for complex implementation tasks
        self.assertEqual(team.executor, "deepseek-coder-v2:16b")
        self.assertNotEqual(team.reviewer, team.executor)
        self.assertIn("React/TypeScript", team.route_reason)

    def test_chat_with_tools_falls_back_to_next_candidate(self):
        client = RoutingClient(NeuDevConfig(model="auto"))
        client._resolve_candidate_models = lambda messages, tools, preferred_models=None, route_reason=None: (
            ["deepseek-coder:6.7b", "qwen3:latest"],
            "deep analysis and workspace reasoning",
        )

        calls = []

        def fake_chat(messages, tools=None, stream=False, think=False, model_name=None):
            calls.append((model_name, bool(tools), think))
            if model_name == "deepseek-coder:6.7b" and tools:
                raise ToolsNotSupportedError("no tools")
            return {"message": {"content": "ok", "thinking": "", "tool_calls": []}}

        client.chat = fake_chat
        result = client.chat_with_tools(
            [{"role": "user", "content": "Analyze this project and inspect files"}],
            tools=[{"function": {"name": "read_file"}}],
            think=True,
        )

        self.assertEqual(result["model"], "qwen3:latest")
        self.assertTrue(result["native_tools_supported"])
        self.assertEqual(calls[0][0], "deepseek-coder:6.7b")
        self.assertEqual(calls[1][0], "qwen3:latest")

    def test_chat_with_tools_routes_code_tasks_to_qwen25_coder(self):
        client = RoutingClient(NeuDevConfig(model="auto"))
        client._fetch_installed_models = lambda: MODELS

        calls = []

        def fake_chat(messages, tools=None, stream=False, think=False, model_name=None):
            calls.append((model_name, bool(tools), think))
            return {"message": {"content": "ok", "thinking": "", "tool_calls": []}}

        client.chat = fake_chat
        result = client.chat_with_tools(
            [{"role": "user", "content": "Implement a Python function and create tests"}],
            tools=[{"function": {"name": "write_file"}}],
            think=True,
        )

        # Now prefers deepseek-coder-v2 for coding tasks
        self.assertEqual(result["model"], "deepseek-coder-v2:16b")
        self.assertEqual(calls[0][0], "deepseek-coder-v2:16b")

    def test_chat_with_tools_extracts_bare_json_tool_call_text(self):
        client = RoutingClient(NeuDevConfig(model="auto"))
        client._fetch_installed_models = lambda: MODELS

        def fake_chat(messages, tools=None, stream=False, think=False, model_name=None):
            return {
                "message": {
                    "content": '{"name": "write_file", "arguments": {"path": "index.html", "content": "<!doctype html>"}}',
                    "thinking": "",
                    "tool_calls": [],
                }
            }

        client.chat = fake_chat
        result = client.chat_with_tools(
            [{"role": "user", "content": "Create a single page portfolio website"}],
            tools=[{"function": {"name": "write_file"}}],
            think=True,
        )

        self.assertEqual(result["tool_call_mode"], "text")
        self.assertFalse(result["done"])
        self.assertEqual(
            result["tool_calls"],
            [{"name": "write_file", "arguments": {"path": "index.html", "content": "<!doctype html>"}}],
        )
        self.assertEqual(result["content"], "")

    def test_chat_with_tools_falls_back_when_first_model_times_out(self):
        client = RoutingClient(NeuDevConfig(model="auto"))
        client._resolve_candidate_models = lambda messages, tools, preferred_models=None, route_reason=None: (
            ["qwen2.5-coder:7b", "qwen3:latest"],
            "code generation and editing",
        )

        calls = []

        def fake_chat(messages, tools=None, stream=False, think=False, model_name=None):
            calls.append((model_name, bool(tools), think))
            if model_name == "qwen2.5-coder:7b":
                raise LLMError("Request timed out")
            return {"message": {"content": "ok", "thinking": "", "tool_calls": []}}

        client.chat = fake_chat
        result = client.chat_with_tools(
            [{"role": "user", "content": "Implement a Python function and create tests"}],
            tools=[{"function": {"name": "write_file"}}],
            think=True,
        )

        self.assertEqual(result["model"], "qwen3:latest")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(calls[0][0], "qwen2.5-coder:7b")
        self.assertEqual(calls[1][0], "qwen3:latest")

    def test_manual_selection_falls_back_to_auto_candidates_on_runtime_failure(self):
        client = RoutingClient(NeuDevConfig(model="qwen2.5-coder:7b"))
        client._fetch_installed_models = lambda: MODELS

        calls = []

        def fake_chat(messages, tools=None, stream=False, think=False, model_name=None):
            calls.append((model_name, bool(tools), think))
            if model_name == "qwen2.5-coder:7b":
                raise ModelNotFoundError("missing")
            return {"message": {"content": "ok", "thinking": "", "tool_calls": []}}

        client.chat = fake_chat
        result = client.chat_with_tools(
            [{"role": "user", "content": "Deeply analyze this repository and inspect the files"}],
            tools=[{"function": {"name": "read_file"}}],
            think=True,
        )

        self.assertEqual(result["model"], "qwen3:latest")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(calls[0][0], "qwen2.5-coder:7b")
        self.assertEqual(calls[1][0], "qwen3:latest")
        self.assertIn("runtime model fallback", result["route_reason"])

    def test_chat_with_fallback_uses_next_specialist_when_first_model_is_missing(self):
        client = RoutingClient(NeuDevConfig(model="auto"))
        client._resolve_candidate_models = lambda messages, tools, preferred_models=None, route_reason=None: (
            ["qwen3:latest", "deepseek-coder-v2:16b"],
            "planner selection; deep analysis and workspace reasoning",
        )

        calls = []

        def fake_chat(messages, tools=None, stream=False, think=False, model_name=None):
            calls.append((model_name, bool(tools), think))
            if model_name == "qwen3:latest":
                raise ModelNotFoundError("missing")
            return {"message": {"content": "plan", "thinking": "", "tool_calls": []}}

        client.chat = fake_chat
        result = client.chat_with_fallback(
            [{"role": "user", "content": "Analyze this project and plan the fix"}],
            think=False,
            preferred_models=["qwen3:latest", "deepseek-coder-v2:16b"],
            route_reason="planner selection; deep analysis and workspace reasoning",
        )

        self.assertEqual(result["model"], "deepseek-coder-v2:16b")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(calls[0][0], "qwen3:latest")
        self.assertEqual(calls[1][0], "deepseek-coder-v2:16b")

    def test_switch_model_accepts_auto(self):
        client = RoutingClient(NeuDevConfig(model="qwen3:latest"))
        client._fetch_installed_models = lambda: MODELS

        with patch.object(client.config, "save", return_value=None):
            switched = client.switch_model("auto")

        self.assertTrue(switched)
        self.assertEqual(client.model, "auto")
        self.assertEqual(client.last_used_model, "qwen3:latest")

    def test_switch_model_rejects_embedding_only_models(self):
        client = RoutingClient(NeuDevConfig(model="auto"))
        client._fetch_installed_models = lambda: MODELS

        with self.assertRaises(LLMError):
            client.switch_model("nomic-embed-text")


if __name__ == "__main__":
    unittest.main()
