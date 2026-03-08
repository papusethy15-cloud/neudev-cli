import shutil
import tempfile
import threading
import time
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

    def chat(self, messages, tools=None, stream=False, think=False, model_name=None):
        """Fallback chat method for when chat_with_tools is not used."""
        self.last_used_model = model_name or self.model
        if not self.responses:
            raise AssertionError("No fake responses configured")
        response = self.responses.pop(0)
        # Wrap response in message format if needed
        if "message" not in response:
            return {"message": response}
        return response

    def chat_with_fallback(self, messages, think=False, preferred_models=None, route_reason=None):
        """Chat with fallback - uses chat method."""
        self.last_used_model = self.model
        self.last_route_reason = route_reason or ""
        return self.chat(messages, think=think, model_name=preferred_models[0] if preferred_models else None)

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

    def test_remote_api_wraps_socket_abort_as_remote_api_error(self):
        client = RemoteNeuDevClient("http://127.0.0.1:9999", "secret")

        with patch("urllib.request.urlopen", side_effect=ConnectionAbortedError(10053, "aborted")):
            with self.assertRaises(RemoteAPIError) as cm:
                client.list_sessions()

        self.assertEqual(cm.exception.status_code, 503)

    def test_remote_session_create_and_send_message(self):
        client = self._client()
        session = RemoteSessionClient.create(client, workspace=".")
        hosted = self.service.sessions[session.session_id]
        # Set up responses for all possible LLM method calls
        hosted.agent.llm.responses = [
            {
                "content": "Hosted answer",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
            {
                "content": "Hosted answer",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]
        # Also set chat_responses for chat_with_fallback calls
        hosted.agent.llm.chat_responses = [
            {
                "message": {
                    "content": "Hosted answer",
                    "thinking": "",
                    "tool_calls": [],
                }
            },
            {
                "message": {
                    "content": "Hosted answer",
                    "thinking": "",
                    "tool_calls": [],
                }
            },
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

    def test_remote_once_approval_does_not_persist_for_next_message(self):
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
                "content": "Created the file once.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        first = session.send_message("Create the note once")
        self.assertEqual(first["status"], "approval_required")

        second = session.respond_to_approval(first["approval_id"], True, scope="once")
        self.assertEqual(second["status"], "ok")
        self.assertTrue((self.workspace / "notes.txt").exists())

        hosted.agent.llm.responses = [
            {
                "content": "",
                "thinking": "",
                "tool_calls": [{"name": "write_file", "arguments": {"path": "notes-again.txt", "content": "again\n"}}],
                "done": False,
                "native_tools_supported": True,
            }
        ]

        third = session.send_message("Create another note")
        self.assertEqual(third["status"], "approval_required")

    def test_remote_tool_scope_approval_persists_for_same_tool(self):
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
                "content": "Created the first file.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        first = session.send_message("Create the first note")
        self.assertEqual(first["status"], "approval_required")

        second = session.respond_to_approval(first["approval_id"], True, scope="tool")
        self.assertEqual(second["status"], "ok")
        self.assertTrue((self.workspace / "notes.txt").exists())

        hosted.agent.llm.responses = [
            {
                "content": "",
                "thinking": "",
                "tool_calls": [{"name": "write_file", "arguments": {"path": "notes-two.txt", "content": "two\n"}}],
                "done": False,
                "native_tools_supported": True,
            },
            {
                "content": "Created the second file without another prompt.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        third = session.send_message("Create the second note")
        self.assertEqual(third["status"], "ok")
        self.assertIn("without another prompt", third["response"])
        self.assertTrue((self.workspace / "notes-two.txt").exists())

    def test_remote_all_scope_approval_enables_session_auto_permission(self):
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
                "content": "Created the first file.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        first = session.send_message("Create the first note")
        self.assertEqual(first["status"], "approval_required")

        second = session.respond_to_approval(first["approval_id"], True, scope="all")
        self.assertEqual(second["status"], "ok")
        self.assertTrue(hosted.agent.permissions.auto_approve)
        self.assertTrue(session.get_config()["auto_permission"])

        hosted.agent.llm.responses = [
            {
                "content": "",
                "thinking": "",
                "tool_calls": [
                    {
                        "name": "run_command",
                        "arguments": {
                            "command": "python --version"
                        },
                    }
                ],
                "done": False,
                "native_tools_supported": True,
            },
            {
                "content": "Ran the command without another prompt.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        third = session.send_message("Run a command now")
        self.assertEqual(third["status"], "ok")
        self.assertIn("without another prompt", third["response"])
        history = session.get_history()
        self.assertEqual(history["actions"][-1]["action"], "command")
        self.assertEqual(history["actions"][-1]["target"], "python --version")

    def test_hosted_sessions_use_restricted_run_command_policy_by_default(self):
        session = RemoteSessionClient.create(self._client(), workspace=".")
        hosted = self.service.sessions[session.session_id]
        run_command = hosted.agent.tool_registry.get("run_command")

        self.assertIsNotNone(run_command)
        self.assertEqual(getattr(run_command, "execution_mode", None), "restricted")

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

    def test_remote_stop_requests_cancel_active_hosted_turn(self):
        client = self._client()
        session = RemoteSessionClient.create(client, workspace=".", auto_permission=True)
        hosted = self.service.sessions[session.session_id]
        hosted.agent.llm.responses = [
            {
                "content": "",
                "thinking": "",
                "tool_calls": [{"name": "run_command", "arguments": {"command": "python --version"}}],
                "done": False,
                "native_tools_supported": True,
            },
            {
                "content": "This response should not be used.",
                "thinking": "",
                "tool_calls": [],
                "done": True,
                "native_tools_supported": True,
            },
        ]

        run_command = hosted.agent.tool_registry.get("run_command")
        started = threading.Event()
        events = []

        def long_running_execute(command, cwd=None, timeout=30, progress_callback=None, stop_event=None, **kwargs):
            started.set()
            while stop_event is not None and not stop_event.is_set():
                time.sleep(0.01)
            return f"Command stopped by user: {command}"

        with patch.object(run_command, "execute", side_effect=long_running_execute):
            worker = threading.Thread(
                target=lambda: events.extend(list(session.stream_message("Run a slow command", transport="sse"))),
                daemon=True,
            )
            worker.start()
            self.assertTrue(started.wait(1))

            stop_result = session.request_stop()

            worker.join(timeout=3)

        self.assertFalse(worker.is_alive())
        self.assertEqual(stop_result["status"], "stop_requested")
        final_payload = next(item["data"] for item in events if item["event"] == "result")
        self.assertEqual(final_payload["status"], "ok")
        self.assertEqual(final_payload["response"], "Stopped by user before completion.")

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
