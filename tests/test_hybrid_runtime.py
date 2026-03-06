import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from neudev.agent import Agent
from neudev.config import NeuDevConfig
from neudev.hosted_llm import HostedLLMClient
from neudev.llm import LLMError
from neudev.server import HostedSessionService, create_server


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "workspace_basic"


class FakeInferenceOllamaClient:
    def __init__(self, config):
        self.config = config
        self.model = config.model
        self.last_used_model = None
        self.last_route_reason = ""
        self.last_messages = []
        self.last_tools = None
        self.responses = []
        self.stream_responses = []

    def list_models(self):
        active_name = self.last_used_model if self.model == "auto" else self.model
        return [
            {
                "name": "qwen3:latest",
                "size": 5_200_000_000,
                "active": active_name == "qwen3:latest",
                "role": "Planner / Reasoner",
            },
            {
                "name": "qwen2.5-coder:7b",
                "size": 4_700_000_000,
                "active": active_name == "qwen2.5-coder:7b",
                "role": "Main Coder",
            },
        ]

    def preview_auto_model(self):
        return ("qwen3:latest", "hybrid routing preview")

    def get_display_model(self):
        if self.model == "auto":
            return "auto -> qwen3:latest"
        return self.model

    def chat(self, messages, tools=None, stream=False, think=False, model_name=None):
        self.last_used_model = model_name or self.model
        self.last_messages = messages
        self.last_tools = tools
        if stream:
            if not self.stream_responses:
                raise AssertionError("No fake hosted inference stream configured")
            chunks = self.stream_responses.pop(0)

            def iterator():
                for chunk in chunks:
                    yield chunk

            return iterator()
        if not self.responses:
            raise AssertionError("No fake hosted inference responses configured")
        return self.responses.pop(0)


class HybridRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tempdir.name) / "workspace"
        self.session_store = Path(self.tempdir.name) / "hosted_sessions"
        shutil.copytree(FIXTURE_ROOT, self.workspace)

        self.inference_patch = patch("neudev.server.OllamaClient", FakeInferenceOllamaClient)
        self.inference_patch.start()

        base_config = NeuDevConfig(model="auto", agent_mode="single", multi_agent=False)
        self.service = HostedSessionService(
            base_config,
            str(self.workspace),
            api_key="secret",
            storage_dir=str(self.session_store),
        )
        self.server = create_server("127.0.0.1", 0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.inference_patch.stop()
        self.tempdir.cleanup()

    def test_hosted_llm_lists_models_and_supports_auto_switch(self):
        config = NeuDevConfig(model="auto", runtime_mode="hybrid", agent_mode="single", multi_agent=False)
        llm = HostedLLMClient(config, self.base_url, "secret")

        models = llm.list_models()

        self.assertEqual(models[0]["name"], "qwen3:latest")
        self.assertTrue(any(item["role"] == "Main Coder" for item in models))
        self.assertEqual(llm.preview_auto_model()[0], "qwen3:latest")

        llm.switch_model("qwen2.5-coder:7b")
        self.assertEqual(llm.get_display_model(), "qwen2.5-coder:7b")

        llm.switch_model("auto")
        self.assertEqual(config.model, "auto")
        self.assertIn("auto ->", llm.get_display_model())

    def test_hosted_llm_rejects_invalid_api_key(self):
        config = NeuDevConfig(model="auto", runtime_mode="hybrid", agent_mode="single", multi_agent=False)

        with self.assertRaises(LLMError) as cm:
            HostedLLMClient(config, self.base_url, "wrong-key")

        self.assertIn("API key", str(cm.exception))

    def test_hosted_inference_stream_emits_raw_chunks(self):
        config = NeuDevConfig(model="qwen3:latest", runtime_mode="hybrid", agent_mode="single", multi_agent=False)
        llm = HostedLLMClient(config, self.base_url, "secret")
        hosted_inference = self.service._get_inference_client()
        hosted_inference.stream_responses = [
            [
                {"message": {"content": "Hello", "thinking": ""}, "done": False},
                {"message": {"content": " world", "thinking": ""}, "done": False},
                {"message": {"content": "", "thinking": ""}, "done": True},
            ]
        ]

        chunks = list(
            llm.chat(
                [{"role": "user", "content": "Say hello"}],
                stream=True,
                model_name="qwen3:latest",
            )
        )

        self.assertEqual([chunk["message"]["content"] for chunk in chunks[:2]], ["Hello", " world"])
        self.assertTrue(chunks[-1]["done"])

    def test_hybrid_agent_edits_local_workspace_using_hosted_inference(self):
        config = NeuDevConfig(
            model="qwen2.5-coder:7b",
            runtime_mode="hybrid",
            agent_mode="single",
            multi_agent=False,
            show_thinking=False,
        )
        llm = HostedLLMClient(config, self.base_url, "secret")
        hosted_inference = self.service._get_inference_client()
        hosted_inference.responses = [
            {
                "message": {
                    "content": "",
                    "thinking": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "write_file",
                                "arguments": {"path": "notes.txt", "content": "hello from hybrid\n"},
                            }
                        }
                    ],
                }
            },
            {
                "message": {
                    "content": "Created the local note.",
                    "thinking": "",
                    "tool_calls": [],
                }
            },
        ]

        with patch("neudev.agent.OllamaClient", side_effect=AssertionError("local Ollama should not be created")):
            agent = Agent(config, str(self.workspace), llm_client=llm)

        agent.permissions.auto_approve = True
        response = agent.process_message("Create a note in this repo.")

        self.assertIn("Created the local note.", response)
        self.assertEqual((self.workspace / "notes.txt").read_text(encoding="utf-8"), "hello from hybrid\n")
        self.assertEqual(hosted_inference.last_used_model, "qwen2.5-coder:7b")

    def test_hybrid_agent_runs_local_command_using_hosted_inference(self):
        config = NeuDevConfig(
            model="qwen2.5-coder:7b",
            runtime_mode="hybrid",
            agent_mode="single",
            multi_agent=False,
            show_thinking=False,
        )
        llm = HostedLLMClient(config, self.base_url, "secret")
        hosted_inference = self.service._get_inference_client()
        hosted_inference.responses = [
            {
                "message": {
                    "content": "",
                    "thinking": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "run_command",
                                "arguments": {
                                    "command": "python -c \"from pathlib import Path; Path('cmd-output.txt').write_text('hybrid command\\n', encoding='utf-8')\""
                                },
                            }
                        }
                    ],
                }
            },
            {
                "message": {
                    "content": "Ran the local command.",
                    "thinking": "",
                    "tool_calls": [],
                }
            },
        ]

        with patch("neudev.agent.OllamaClient", side_effect=AssertionError("local Ollama should not be created")):
            agent = Agent(config, str(self.workspace), llm_client=llm)

        agent.permissions.auto_approve = True
        response = agent.process_message("Create a file by running a local command.")

        self.assertIn("Ran the local command.", response)
        self.assertEqual((self.workspace / "cmd-output.txt").read_text(encoding="utf-8"), "hybrid command\n")
        self.assertEqual(hosted_inference.last_used_model, "qwen2.5-coder:7b")

    def test_hybrid_redacts_sensitive_values_before_hosted_inference(self):
        config = NeuDevConfig(
            model="qwen3:latest",
            runtime_mode="hybrid",
            agent_mode="single",
            multi_agent=False,
            hybrid_redact_secrets=True,
        )
        llm = HostedLLMClient(config, self.base_url, "secret")
        hosted_inference = self.service._get_inference_client()
        hosted_inference.responses = [
            {
                "message": {
                    "content": "sanitized",
                    "thinking": "",
                    "tool_calls": [],
                }
            }
        ]

        response = llm.chat(
            [
                {
                    "role": "user",
                    "content": (
                        "API_KEY=abc123\n"
                        "Authorization: Bearer secret-token\n"
                        "secret_key: top-secret\n"
                    ),
                }
            ],
            model_name="qwen3:latest",
        )

        self.assertEqual(response["message"]["content"], "sanitized")
        serialized_messages = str(hosted_inference.last_messages)
        self.assertIn("[REDACTED]", serialized_messages)
        self.assertNotIn("abc123", serialized_messages)
        self.assertNotIn("secret-token", serialized_messages)
        self.assertGreaterEqual(llm.last_redaction_count, 2)

    def test_hybrid_rejects_payloads_above_configured_limit(self):
        config = NeuDevConfig(
            model="qwen3:latest",
            runtime_mode="hybrid",
            agent_mode="single",
            multi_agent=False,
            hybrid_max_payload_bytes=256,
        )
        llm = HostedLLMClient(config, self.base_url, "secret")

        with self.assertRaises(LLMError) as cm:
            llm.chat(
                [{"role": "user", "content": "x" * 2048}],
                model_name="qwen3:latest",
            )

        self.assertIn("payload is too large", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()
