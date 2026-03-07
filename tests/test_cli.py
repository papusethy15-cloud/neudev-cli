import threading
import time
import tempfile
import unittest
from argparse import Namespace
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import neudev.cli as cli_module
from rich.panel import Panel

from neudev.cli import (
    ExecutionTraceState,
    InteractivePermissionManager,
    QueuedLocalTaskRunner,
    build_trace_summary_lines,
    build_live_status_lines,
    build_plan_panel_content,
    build_parser,
    handle_local_queue_command,
    handle_local_permission_input,
    handle_local_stop,
    resolve_local_command_policy,
    run_local_agent_loop,
    run_hybrid_cli,
    run_local_cli,
    run_login_setup,
    run_logout,
    run_uninstall,
    should_use_live_trace_panel,
)
from neudev.config import NeuDevConfig
from neudev.permissions import PermissionManager
from neudev.tools.run_command import RunCommandTool


class CLITests(unittest.TestCase):
    @staticmethod
    def _wait_for_pending_permission(manager: InteractivePermissionManager, timeout: float = 1.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if manager.pending_request() is not None:
                return True
            time.sleep(0.01)
        return False

    def test_login_persists_hosted_settings(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config_dir = Path(tempdir) / ".neudev"
            config_file = config_dir / "config.json"
            args = Namespace(
                runtime="remote",
                api_base_url="https://example.com/",
                api_key="secret-token",
                ws_base_url="wss://example.com/v1/stream/",
            )

            with patch("neudev.config.CONFIG_DIR", config_dir), patch("neudev.config.CONFIG_FILE", config_file), patch(
                "neudev.cli.CONFIG_DIR", config_dir
            ), patch("neudev.cli.console.print"):
                run_login_setup(args)
                saved = NeuDevConfig.load()

        self.assertEqual(saved.runtime_mode, "remote")
        self.assertEqual(saved.api_base_url, "https://example.com")
        self.assertEqual(saved.api_key, "secret-token")
        self.assertEqual(saved.websocket_base_url, "wss://example.com/v1/stream")

    def test_build_trace_summary_lines_includes_flow_tools_and_touched_targets(self):
        trace = ExecutionTraceState()
        trace.phases = [
            ("understand", "request + workspace context"),
            ("planner", "qwen3:latest"),
            ("executor", "qwen2.5-coder:7b"),
            ("reviewer", "qwen3:latest"),
        ]
        trace.plan_total = 3
        trace.plan_completed = 2
        trace.active_plan_item = "Run changed-file diagnostics"
        trace.tool_counts = {"read_file": 2, "write_file": 1}
        trace.changed_targets = ["src/App.tsx"]
        trace.workspace_delta_counts["modified"] = 1

        lines = build_trace_summary_lines(trace)
        summary = "\n".join(lines)

        self.assertIn("UNDERSTAND -> PLAN -> EXECUTE -> REVIEW", summary)
        self.assertIn("2/3 completed", summary)
        self.assertIn("read_file x2, write_file x1", summary)
        self.assertIn("1 modified", summary)
        self.assertIn("src/App.tsx", summary)

    def test_build_trace_summary_lines_uses_touched_targets_when_nothing_changed(self):
        trace = ExecutionTraceState()
        trace.phases = [("understand", "request + workspace context"), ("executor", "qwen2.5-coder:7b")]
        trace.tool_counts = {"read_file": 1}
        trace.touched_targets = ["README.md"]

        lines = build_trace_summary_lines(trace)
        summary = "\n".join(lines)

        self.assertIn("UNDERSTAND -> EXECUTE", summary)
        self.assertIn("read_file x1", summary)
        self.assertIn("README.md", summary)

    def test_build_live_status_lines_shows_current_step_and_waiting_reason(self):
        trace = ExecutionTraceState()
        trace.current_phase = "executor"
        trace.current_model = "qwen2.5-coder:7b"
        trace.current_detail = "Waiting for the executor model to decide the next step."
        trace.waiting_for_model = True
        trace.plan_total = 2
        trace.plan_completed = 1
        trace.active_plan_item = "Verify generated files"

        lines = build_live_status_lines(trace)
        status = "\n".join(lines)

        self.assertIn("EXECUTE", status)
        self.assertIn("qwen2.5-coder:7b", status)
        self.assertIn("1/2 completed", status)
        self.assertIn("Waiting for the model", status)

    def test_build_plan_panel_content_renders_full_plan_only_once(self):
        trace = ExecutionTraceState()
        plan_update = {
            "plan": [
                {"text": "Create index.html", "status": "in_progress"},
                {"text": "Add style.css", "status": "pending"},
                {"text": "Implement script.js", "status": "pending"},
            ],
            "conventions": [
                "Use semantic HTML5",
                "Mobile-first responsive CSS",
            ],
        }

        first = build_plan_panel_content(plan_update, trace=trace)
        second = build_plan_panel_content(plan_update, trace=trace)

        self.assertIsNotNone(first)
        title, lines = first
        body = "\n".join(lines)
        self.assertIn("Plan Update", title)
        self.assertIn("Execution Plan", body)
        self.assertIn("Repository Conventions", body)
        self.assertIsNone(second)

    def test_build_plan_panel_content_switches_to_compact_progress_updates(self):
        trace = ExecutionTraceState()
        initial = {
            "plan": [
                {"text": "Create index.html", "status": "in_progress"},
                {"text": "Add style.css", "status": "pending"},
                {"text": "Implement script.js", "status": "pending"},
            ],
            "conventions": ["Use semantic HTML5"],
        }
        progress = {
            "plan": [
                {"text": "Create index.html", "status": "completed"},
                {"text": "Add style.css", "status": "in_progress"},
                {"text": "Implement script.js", "status": "pending"},
            ],
            "conventions": ["Use semantic HTML5"],
        }

        build_plan_panel_content(initial, trace=trace)
        updated = build_plan_panel_content(progress, trace=trace)

        self.assertIsNotNone(updated)
        title, lines = updated
        body = "\n".join(lines)
        self.assertIn("Plan Progress", title)
        self.assertIn("Completed", body)
        self.assertIn("Create index.html", body)
        self.assertIn("In Progress", body)
        self.assertIn("Add style.css", body)
        self.assertNotIn("Repository Conventions", body)

    def test_should_use_live_trace_panel_requires_main_thread_terminal(self):
        with patch.object(type(cli_module.console), "is_terminal", new_callable=PropertyMock, return_value=True), patch(
            "neudev.cli.threading.current_thread", return_value=threading.main_thread()
        ):
            self.assertTrue(should_use_live_trace_panel())

        with patch.object(type(cli_module.console), "is_terminal", new_callable=PropertyMock, return_value=True), patch(
            "neudev.cli.threading.current_thread", return_value=object()
        ):
            self.assertFalse(should_use_live_trace_panel())

        with patch.object(type(cli_module.console), "is_terminal", new_callable=PropertyMock, return_value=False), patch(
            "neudev.cli.threading.current_thread", return_value=threading.main_thread()
        ):
            self.assertFalse(should_use_live_trace_panel())

    def test_logout_clears_saved_api_key_only(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config_dir = Path(tempdir) / ".neudev"
            config_file = config_dir / "config.json"
            config = NeuDevConfig(
                runtime_mode="remote",
                api_base_url="https://example.com",
                api_key="secret-token",
                websocket_base_url="wss://example.com/v1/stream",
            )

            with patch("neudev.config.CONFIG_DIR", config_dir), patch("neudev.config.CONFIG_FILE", config_file), patch(
                "neudev.cli.CONFIG_DIR", config_dir
            ), patch("neudev.cli.CONFIG_FILE", config_file), patch("neudev.cli.console.print"):
                config.save()
                run_logout(Namespace(all=False))
                saved = NeuDevConfig.load()

        self.assertEqual(saved.api_base_url, "https://example.com")
        self.assertEqual(saved.api_key, "")
        self.assertEqual(saved.websocket_base_url, "wss://example.com/v1/stream")

    def test_uninstall_purge_config_removes_local_files(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config_dir = Path(tempdir) / ".neudev"
            config_file = config_dir / "config.json"
            history_file = config_dir / "history.txt"
            config = NeuDevConfig(api_key="secret-token")

            with patch("neudev.config.CONFIG_DIR", config_dir), patch("neudev.config.CONFIG_FILE", config_file), patch(
                "neudev.cli.CONFIG_DIR", config_dir
            ), patch("neudev.cli.CONFIG_FILE", config_file), patch("neudev.cli.HISTORY_FILE", history_file), patch(
                "neudev.cli.console.print"
            ):
                config.save()
                history_file.parent.mkdir(parents=True, exist_ok=True)
                history_file.write_text("hello\n", encoding="utf-8")
                run_uninstall(Namespace(purge_config=True))

        self.assertFalse(config_file.exists())
        self.assertFalse(history_file.exists())

    def test_parser_supports_auth_and_uninstall_commands(self):
        parser = build_parser()

        auth_args = parser.parse_args(
            [
                "auth",
                "login",
                "--runtime",
                "remote",
                "--api-base-url",
                "https://example.com",
                "--api-key",
                "secret-token",
            ]
        )
        uninstall_args = parser.parse_args(["uninstall", "--purge-config"])

        self.assertEqual(auth_args.command, "auth")
        self.assertEqual(auth_args.auth_command, "login")
        self.assertEqual(uninstall_args.command, "uninstall")
        self.assertTrue(uninstall_args.purge_config)

    def test_parser_accepts_command_policy_flag(self):
        parser = build_parser()

        args = parser.parse_args(["run", "--command-policy", "disabled"])

        self.assertEqual(args.command_policy, "disabled")

    def test_resolve_local_command_policy_defaults_to_restricted_for_hybrid(self):
        policy, reason = resolve_local_command_policy(NeuDevConfig(command_policy="auto"), "hybrid", "C:/repo")

        self.assertEqual(policy, "restricted")
        self.assertEqual(reason, "hybrid default")

    def test_resolve_local_command_policy_defaults_to_restricted_for_lightning_workspace(self):
        policy, reason = resolve_local_command_policy(
            NeuDevConfig(command_policy="auto"),
            "local",
            "/teamspace/studios/this_studio/neudev-cli",
        )

        self.assertEqual(policy, "restricted")
        self.assertEqual(reason, "Lightning workspace default")

    def test_local_task_runner_queues_follow_up_messages(self):
        started = threading.Event()
        release = threading.Event()
        processed = []

        def fake_processor(agent, message, *, stop_event=None):
            processed.append(("start", message))
            if message == "first":
                started.set()
                release.wait(1)
            processed.append(("done", message, bool(stop_event and stop_event.is_set())))

        with patch("neudev.cli.console.print"):
            runner = QueuedLocalTaskRunner(object(), processor=fake_processor)
            try:
                self.assertEqual(runner.submit("first"), 0)
                self.assertTrue(started.wait(1))
                self.assertEqual(runner.submit("second"), 1)
                active, pending = runner.snapshot()
                self.assertEqual(active, "first")
                self.assertEqual(pending, ["second"])
                release.set()
                self.assertTrue(runner.wait_until_idle(timeout=1))
            finally:
                runner.shutdown(cancel_pending=True, stop_current=True)

        self.assertEqual(
            [item[1] for item in processed if item[0] == "start"],
            ["first", "second"],
        )

    def test_local_task_runner_stop_requests_cancel_on_active_task(self):
        started = threading.Event()
        stopped = threading.Event()

        def fake_processor(agent, message, *, stop_event=None):
            started.set()
            while stop_event is not None and not stop_event.is_set():
                time.sleep(0.01)
            stopped.set()

        with patch("neudev.cli.console.print"):
            runner = QueuedLocalTaskRunner(object(), processor=fake_processor)
            try:
                runner.submit("long running task")
                self.assertTrue(started.wait(1))
                self.assertTrue(runner.request_stop())
                self.assertTrue(stopped.wait(1))
                self.assertTrue(runner.wait_until_idle(timeout=1))
            finally:
                runner.shutdown(cancel_pending=True, stop_current=True)

    def test_local_queue_command_adds_explicit_follow_up(self):
        runner = MagicMock()
        runner.submit.return_value = 2

        with patch("neudev.cli.console.print"):
            handle_local_queue_command(runner, "add inspect npm error log")

        runner.submit.assert_called_once_with("inspect npm error log")

    def test_local_queue_command_can_clear_pending_tasks(self):
        started = threading.Event()
        release = threading.Event()

        def fake_processor(agent, message, *, stop_event=None):
            started.set()
            release.wait(1)

        with patch("neudev.cli.console.print"):
            runner = QueuedLocalTaskRunner(object(), processor=fake_processor)
            try:
                self.assertEqual(runner.submit("first"), 0)
                self.assertTrue(started.wait(1))
                self.assertEqual(runner.submit("second"), 1)
                self.assertEqual(runner.submit("third"), 2)
                handle_local_queue_command(runner, "clear")
                active, pending = runner.snapshot()
                self.assertEqual(active, "first")
                self.assertEqual(pending, [])
            finally:
                release.set()
                runner.shutdown(cancel_pending=True, stop_current=True)

    def test_local_permission_input_approves_pending_request_once(self):
        manager = InteractivePermissionManager()
        outcome = {}

        def request_permission():
            outcome["allowed"] = manager.request_permission("run_command", "Run command: pytest")

        with patch("neudev.cli.console.print"):
            worker = threading.Thread(target=request_permission, daemon=True)
            worker.start()
            self.assertTrue(self._wait_for_pending_permission(manager))
            self.assertTrue(handle_local_permission_input(manager, "y"))
            worker.join(1)

        self.assertFalse(worker.is_alive())
        self.assertTrue(outcome["allowed"])
        self.assertIsNone(manager.pending_request())

    def test_local_permission_input_supports_slash_approve_all(self):
        manager = InteractivePermissionManager()
        outcome = {}

        def request_permission():
            outcome["allowed"] = manager.request_permission("write_file", "Write README.md")

        with patch("neudev.cli.console.print"):
            worker = threading.Thread(target=request_permission, daemon=True)
            worker.start()
            self.assertTrue(self._wait_for_pending_permission(manager))
            self.assertTrue(handle_local_permission_input(manager, "/approve all"))
            worker.join(1)

        self.assertFalse(worker.is_alive())
        self.assertTrue(outcome["allowed"])
        self.assertTrue(manager.auto_approve)

    def test_local_permission_panel_lists_main_prompt_choices(self):
        manager = InteractivePermissionManager()
        outcome = {}

        def request_permission():
            outcome["allowed"] = manager.request_permission("run_command", "Run command: npm install")

        with patch("neudev.cli.console.print") as print_mock:
            worker = threading.Thread(target=request_permission, daemon=True)
            worker.start()
            self.assertTrue(self._wait_for_pending_permission(manager))
            deadline = time.time() + 1
            panel = None
            while time.time() < deadline and panel is None:
                panel = next(
                    (call.args[0] for call in print_mock.call_args_list if call.args and isinstance(call.args[0], Panel)),
                    None,
                )
                if panel is None:
                    time.sleep(0.01)
            self.assertIsNotNone(panel)
            manager.resolve_pending("deny")
            worker.join(1)

        self.assertFalse(worker.is_alive())
        self.assertFalse(outcome["allowed"])
        body = str(panel.renderable)
        self.assertIn("approve once", body)
        self.assertIn("/approve tool", body)
        self.assertIn("/approve all", body)
        self.assertIn("/stop", body)

    def test_handle_local_stop_denies_pending_permission(self):
        manager = InteractivePermissionManager()
        outcome = {}

        class FakeRunner:
            @staticmethod
            def request_stop():
                return True

        def request_permission():
            outcome["allowed"] = manager.request_permission("delete_file", "Delete app.py")

        with patch("neudev.cli.console.print"):
            worker = threading.Thread(target=request_permission, daemon=True)
            worker.start()
            self.assertTrue(self._wait_for_pending_permission(manager))
            handle_local_stop(FakeRunner(), manager)
            worker.join(1)

        self.assertFalse(worker.is_alive())
        self.assertFalse(outcome["allowed"])

    def test_run_local_agent_loop_ignores_plain_text_while_busy(self):
        class FakePromptSession:
            def __init__(self):
                self._inputs = iter(["C:\\WorkSpace\\my-react-project>npm install", "/exit"])

            def prompt(self, *_args, **_kwargs):
                return next(self._inputs)

        fake_agent = MagicMock()
        fake_agent.permissions = InteractivePermissionManager()
        fake_runner = MagicMock()
        fake_runner.is_busy.return_value = True
        fake_runner.pending_count.return_value = 0

        with patch("neudev.cli.build_prompt_session", return_value=FakePromptSession()), patch(
            "neudev.cli.QueuedLocalTaskRunner", return_value=fake_runner
        ), patch("neudev.cli.patch_stdout", return_value=nullcontext()), patch(
            "neudev.cli.handle_local_exit"
        ), patch("neudev.cli.console.print") as print_mock:
            run_local_agent_loop(fake_agent, NeuDevConfig(), runtime_mode="hybrid")

        fake_runner.submit.assert_not_called()
        self.assertIn(
            (((), {"cancel_pending": True, "stop_current": True})),
            [(call.args, call.kwargs) for call in fake_runner.shutdown.call_args_list],
        )
        self.assertTrue(any("Ignored plain-text input" in str(call.args[0]) for call in print_mock.call_args_list if call.args))

    def test_run_local_cli_installs_interactive_permission_manager(self):
        fake_agent = MagicMock()
        fake_agent.permissions = PermissionManager()
        fake_agent.config = NeuDevConfig(auto_permission=True)
        fake_agent.workspace = "."
        fake_agent.llm.get_display_model.return_value = "qwen3:latest"
        fake_agent.tool_registry.get_all.return_value = [object(), object()]
        fake_agent.tool_registry.get.return_value = None

        with patch("neudev.cli.Agent", return_value=fake_agent), patch(
            "neudev.cli.console.status", return_value=nullcontext()
        ), patch("neudev.cli.print_banner"), patch("neudev.cli.print_status_block"), patch(
            "neudev.cli.run_local_agent_loop"
        ), patch("neudev.cli.console.print"):
            run_local_cli(NeuDevConfig(auto_permission=True), workspace=".")

        self.assertIsInstance(fake_agent.permissions, InteractivePermissionManager)
        self.assertTrue(fake_agent.permissions.auto_approve)

    def test_run_local_cli_applies_explicit_command_policy_to_run_command(self):
        config = NeuDevConfig(command_policy="disabled")
        run_command = RunCommandTool()
        fake_agent = MagicMock()
        fake_agent.permissions = PermissionManager()
        fake_agent.config = config
        fake_agent.workspace = "."
        fake_agent.llm.get_display_model.return_value = "qwen3:latest"
        fake_agent.tool_registry.get_all.return_value = [run_command, object()]
        fake_agent.tool_registry.get.side_effect = lambda name: run_command if name == "run_command" else None

        with patch("neudev.cli.Agent", return_value=fake_agent), patch(
            "neudev.cli.console.status", return_value=nullcontext()
        ), patch("neudev.cli.print_banner"), patch("neudev.cli.print_status_block"), patch(
            "neudev.cli.run_local_agent_loop"
        ), patch("neudev.cli.console.print"):
            run_local_cli(config, workspace=".")

        self.assertEqual(run_command.execution_mode, "disabled")

    def test_run_hybrid_cli_defaults_run_command_to_restricted(self):
        config = NeuDevConfig(
            runtime_mode="hybrid",
            command_policy="auto",
            api_base_url="https://example.com",
            api_key="secret",
        )
        run_command = RunCommandTool()
        fake_agent = MagicMock()
        fake_agent.permissions = PermissionManager()
        fake_agent.config = config
        fake_agent.workspace = "C:/repo"
        fake_agent.llm.get_display_model.return_value = "qwen3:latest"
        fake_agent.tool_registry.get_all.return_value = [run_command, object()]
        fake_agent.tool_registry.get.side_effect = lambda name: run_command if name == "run_command" else None

        with patch.object(config, "update", side_effect=lambda **kwargs: config.apply_runtime_updates(persist=False, **kwargs)), patch(
            "neudev.cli.HostedLLMClient", return_value=MagicMock()
        ), patch("neudev.cli.Agent", return_value=fake_agent), patch(
            "neudev.cli.console.status", return_value=nullcontext()
        ), patch("neudev.cli.print_banner"), patch("neudev.cli.print_status_block"), patch(
            "neudev.cli.run_local_agent_loop"
        ), patch("neudev.cli.console.print"):
            run_hybrid_cli(config, workspace="C:/repo")

        self.assertEqual(run_command.execution_mode, "restricted")


if __name__ == "__main__":
    unittest.main()
