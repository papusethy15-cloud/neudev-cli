import threading
import time
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from neudev.cli import QueuedLocalTaskRunner, build_parser, run_login_setup, run_logout, run_uninstall
from neudev.config import NeuDevConfig


class CLITests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
