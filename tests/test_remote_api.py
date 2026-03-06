import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from neudev.config import NeuDevConfig
from neudev.remote_api import RemoteAPIError, RemoteNeuDevClient, RemoteSessionClient
from neudev.server import HostedSessionService, create_server, create_websocket_server


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "workspace_basic"


class FakeHostedOllamaClient:
    def __init__(self, config):
        self.config = config
        self.model = config.model
        self.last_used_model = config.model
        self.last_route_reason = ""
        self.responses = []

    def chat_with_tools(self, messages, tools=None, think=False, preferred_models=None, route_reason=None):
        self.last_used_model = self.model
        self.last_route_reason = route_reason or ""
        if not self.responses:
            raise AssertionError("No fake responses configured")
        return self.responses.pop(0)

    def get_display_model(self):
        return self.last_used_model or self.model

    def list_models(self):
        return [
            {"name": "qwen3:latest", "size": 6100000000, "active": self.model == "qwen3:latest", "role": "Planner / Reasoner"},
            {"name": "qwen2.5-coder:7b", "size": 4400000000, "active": self.model == "qwen2.5-coder:7b", "role": "Main Coder"},
        ]

    def switch_model(self, model_name: str):
        self.model = model_name
        self.last_used_model = model_name
        self.last_route_reason = "manual selection"
        return True

    def preview_auto_model(self):
        return ("qwen3:latest", "test routing")


class RemoteAPITests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tempdir.name) / "workspace"
        self.session_store = Path(self.tempdir.name) / "hosted_sessions"
        shutil.copytree(FIXTURE_ROOT, self.workspace)

        self.ollama_patch = patch("neudev.agent.OllamaClient", FakeHostedOllamaClient)
        self.ollama_patch.start()

        base_config = NeuDevConfig(model="qwen3:latest", agent_mode="single", multi_agent=False)
        self.service = HostedSessionService(
            base_config,
            str(self.workspace),
            api_key="secret",
            storage_dir=str(self.session_store),
        )

        self.websocket_server = create_websocket_server("127.0.0.1", 0, self.service)
        self.websocket_thread = threading.Thread(target=self.websocket_server.serve_forever, daemon=True)
        self.websocket_thread.start()

        self.server = create_server(
            "127.0.0.1",
            0,
            self.service,
            websocket_port=self.websocket_server.server_port,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.ws_url = f"ws://127.0.0.1:{self.websocket_server.server_port}/v1/stream"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.websocket_server.shutdown()
        self.websocket_thread.join(timeout=2)
        self.ollama_patch.stop()
        self.tempdir.cleanup()

    def _client(self) -> RemoteNeuDevClient:
        return RemoteNeuDevClient(self.base_url, "secret", websocket_url=self.ws_url)

    def test_remote_api_rejects_invalid_api_key(self):
        client = RemoteNeuDevClient(self.base_url, "wrong-key")

        with self.assertRaises(RemoteAPIError) as cm:
            client.create_session(workspace=".")

        self.assertEqual(cm.exception.status_code, 401)

    def test_remote_session_create_and_send_message(self):
        client = self._client()
        session = RemoteSessionClient.create(client, workspace=".")
        hosted = self.service.sessions[session.session_id]
        hosted.agent.llm.responses = [
            {
                "content": "Hosted answer",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            }
        ]

        payload = session.send_message("Analyze this project")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["response"], "Hosted answer")
        self.assertEqual(payload["session_id"], session.session_id)

    def test_remote_permission_approval_retries_message(self):
        client = self._client()
        session = RemoteSessionClient.create(client, workspace=".")
        hosted = self.service.sessions[session.session_id]
        hosted.agent.llm.responses = [
            {
                "content": "",
                "thinking": "",
                "tool_calls": [{"name": "write_file", "arguments": {"path": "notes.txt", "content": "hello\n"}}],
                "done": False,
                "native_tools_supported": True,
            },
            {
                "content": "",
                "thinking": "",
                "tool_calls": [{"name": "write_file", "arguments": {"path": "notes.txt", "content": "hello\n"}}],
                "done": False,
                "native_tools_supported": True,
            },
            {
                "content": "File created remotely.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        first = session.send_message("Create a note")
        self.assertEqual(first["status"], "approval_required")

        second = session.respond_to_approval(first["approval_id"], True)
        self.assertEqual(second["status"], "ok")
        self.assertIn("File created remotely.", second["response"])
        self.assertTrue((self.workspace / "notes.txt").exists())

    def test_remote_config_and_model_switch(self):
        client = self._client()
        session = RemoteSessionClient.create(client, workspace=".")

        config = session.get_config()
        self.assertEqual(config["runtime_mode"], "remote")
        self.assertEqual(config["agent_mode"], "single")

        switched = session.switch_model("qwen2.5-coder:7b")
        self.assertEqual(switched["selected_model"], "qwen2.5-coder:7b")

    def test_remote_sse_stream_emits_live_events(self):
        client = self._client()
        session = RemoteSessionClient.create(client, workspace=".")
        session.update_config(show_thinking=True)
        hosted = self.service.sessions[session.session_id]
        hosted.agent.llm.responses = [
            {
                "content": "",
                "thinking": "Need to inspect README.",
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

        events = list(session.stream_message("Inspect README", transport="sse"))
        event_names = [item["event"] for item in events]
        final_payload = next(item["data"] for item in events if item["event"] == "result")

        self.assertIn("thinking", event_names)
        self.assertIn("status", event_names)
        self.assertIn("text", event_names)
        self.assertEqual(final_payload["status"], "ok")
        self.assertEqual(final_payload["response"], "README inspected.")

    def test_remote_websocket_stream_emits_live_events(self):
        client = self._client()
        client.health()
        session = RemoteSessionClient.create(client, workspace=".")
        hosted = self.service.sessions[session.session_id]
        hosted.agent.llm.responses = [
            {
                "content": "WebSocket answer",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            }
        ]

        events = list(session.stream_message("Use websocket", transport="websocket"))
        event_names = [item["event"] for item in events]
        final_payload = next(item["data"] for item in events if item["event"] == "result")

        self.assertIn("result", event_names)
        self.assertIn("done", event_names)
        self.assertEqual(final_payload["response"], "WebSocket answer")

    def test_remote_sessions_persist_and_resume(self):
        client = self._client()
        session = RemoteSessionClient.create(client, workspace=".")
        hosted = self.service.sessions[session.session_id]
        hosted.agent.llm.responses = [
            {
                "content": "First hosted reply",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            }
        ]
        first = session.send_message("First message")
        self.assertEqual(first["status"], "ok")

        reloaded_service = HostedSessionService(
            NeuDevConfig(model="qwen3:latest", agent_mode="single", multi_agent=False),
            str(self.workspace),
            api_key="secret",
            storage_dir=str(self.session_store),
        )
        self.assertIn(session.session_id, reloaded_service.sessions)

        websocket_server = create_websocket_server("127.0.0.1", 0, reloaded_service)
        websocket_thread = threading.Thread(target=websocket_server.serve_forever, daemon=True)
        websocket_thread.start()
        server = create_server(
            "127.0.0.1",
            0,
            reloaded_service,
            websocket_port=websocket_server.server_port,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            base_url = f"http://127.0.0.1:{server.server_port}"
            ws_url = f"ws://127.0.0.1:{websocket_server.server_port}/v1/stream"
            new_client = RemoteNeuDevClient(base_url, "secret", websocket_url=ws_url)
            new_client.health()
            listed = new_client.list_sessions()
            self.assertTrue(any(item["session_id"] == session.session_id for item in listed["sessions"]))

            resumed = RemoteSessionClient.resume(new_client, session.session_id)
            reloaded_service.sessions[session.session_id].agent.llm.responses = [
                {
                    "content": "Second hosted reply",
                    "thinking": "",
                    "tool_calls": [],
                    "done": True,
                    "native_tools_supported": True,
                }
            ]
            second = resumed.send_message("Second message")
            self.assertEqual(second["status"], "ok")
            self.assertEqual(second["response"], "Second hosted reply")

            summary = resumed.get_summary()
            self.assertEqual(summary["messages_count"], 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            websocket_server.shutdown()
            websocket_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
