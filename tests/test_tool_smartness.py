import subprocess
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from neudev.agent import Agent
from neudev.config import NeuDevConfig
from neudev.tools.base import ToolError
from neudev.tools.grep_search import GrepSearchTool
from neudev.tools.read_files_batch import ReadFilesBatchTool
from neudev.tools.run_command import RunCommandTool
from neudev.tools.search_files import SearchFilesTool
from neudev.tools.smart_edit_file import SmartEditFileTool


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "workspace_basic"


class DummyOllamaClient:
    def __init__(self, config):
        self.config = config


class ToolSmartnessTests(unittest.TestCase):
    def setUp(self):
        self.config = NeuDevConfig(model="auto", agent_mode="single", show_thinking=False)
        self.example_path = FIXTURE_ROOT / "src" / "example.py"
        self.original_example = self.example_path.read_text(encoding="utf-8")

    def tearDown(self):
        self.example_path.write_text(self.original_example, encoding="utf-8")

    @patch("neudev.agent.OllamaClient", DummyOllamaClient)
    def test_read_file_falls_back_to_list_directory_for_directory_paths(self):
        agent = Agent(self.config, str(FIXTURE_ROOT))
        result = agent._execute_tool("read_file", {"path": "src"})

        self.assertIn("Automatic fallback", result)
        self.assertIn("example.py", result)

    @patch("neudev.agent.OllamaClient", DummyOllamaClient)
    def test_list_directory_falls_back_to_read_file_for_file_paths(self):
        agent = Agent(self.config, str(FIXTURE_ROOT))
        result = agent._execute_tool("list_directory", {"path": "README.md"})

        self.assertIn("Automatic fallback", result)
        self.assertIn("hello", result)

    @patch("neudev.agent.OllamaClient", DummyOllamaClient)
    def test_edit_file_falls_back_to_smart_edit_file(self):
        agent = Agent(self.config, str(FIXTURE_ROOT))
        agent.permissions.auto_approve = True

        result = agent._execute_tool(
            "edit_file",
            {
                "path": "src/example.py",
                "target_content": "def  demo():\n      return   \"ok\"",
                "replacement_content": "def demo():\n    return \"great\"",
            },
        )

        self.assertIn("Automatic fallback", result)
        self.assertIn("smart_edit_file", result)
        self.assertIn("great", self.example_path.read_text(encoding="utf-8"))

    def test_smart_edit_file_accepts_common_alias_argument_names(self):
        tool = SmartEditFileTool()
        tool.bind_workspace(FIXTURE_ROOT)

        result = tool.execute(
            path="src/example.py",
            old_text='return "ok"',
            new_text='return "better"',
        )

        self.assertIn("Edited", result)
        self.assertIn("better", self.example_path.read_text(encoding="utf-8"))

    def test_smart_edit_file_reports_missing_text_as_tool_error(self):
        tool = SmartEditFileTool()
        tool.bind_workspace(FIXTURE_ROOT)

        with self.assertRaisesRegex(ToolError, "smart_edit_file requires a replace target"):
            tool.execute(path="src/example.py")

    @patch("neudev.agent.OllamaClient", DummyOllamaClient)
    def test_agent_passes_stop_event_into_run_command(self):
        agent = Agent(self.config, str(FIXTURE_ROOT))
        agent.permissions.auto_approve = True
        stop_event = threading.Event()
        received = {}

        tool = agent.tool_registry.get("run_command")

        def fake_execute(**kwargs):
            received["stop_event"] = kwargs.get("stop_event")
            return "ok"

        with patch.object(tool, "execute", side_effect=fake_execute):
            result = agent._execute_tool("run_command", {"command": "python --version"}, stop_event=stop_event)

        self.assertEqual(result, "ok")
        self.assertIs(received["stop_event"], stop_event)

    def test_search_files_uses_fuzzy_name_fallback(self):
        tool = SearchFilesTool()
        tool.bind_workspace(FIXTURE_ROOT)

        result = tool.execute(pattern="readme", directory=".")

        self.assertIn("Automatic fallback", result)
        self.assertIn("README.md", result)

    def test_grep_search_uses_case_insensitive_fallback(self):
        tool = GrepSearchTool()
        tool.bind_workspace(FIXTURE_ROOT)

        result = tool.execute(query="DEMO", directory="src")

        self.assertIn("Automatic fallback", result)
        self.assertIn("example.py:1", result)

    def test_run_command_uses_python_module_fallback(self):
        tool = RunCommandTool()
        tool.bind_workspace(FIXTURE_ROOT)

        first = subprocess.CompletedProcess(
            args="pytest --version",
            returncode=1,
            stdout="",
            stderr="'pytest' is not recognized as an internal or external command",
        )
        second = subprocess.CompletedProcess(
            args="python -m pytest --version",
            returncode=0,
            stdout="pytest 8.4.1",
            stderr="",
        )

        with patch("subprocess.run", side_effect=[first, second]) as run_mock:
            result = tool.execute("pytest --version")

        self.assertEqual(run_mock.call_count, 2)
        self.assertIn("Automatic fallback command: python -m pytest --version", result)
        self.assertIn("pytest 8.4.1", result)

    def test_run_command_restricted_mode_uses_shell_false(self):
        tool = RunCommandTool()
        tool.bind_workspace(FIXTURE_ROOT)
        tool.set_execution_mode("restricted")

        completed = subprocess.CompletedProcess(
            args=["python", "--version"],
            returncode=0,
            stdout="Python 3.14.0",
            stderr="",
        )

        with patch("neudev.tools.run_command.shutil.which", return_value=None), patch(
            "subprocess.run", return_value=completed
        ) as run_mock:
            result = tool.execute("python --version")

        self.assertIn("Python 3.14.0", result)
        self.assertEqual(run_mock.call_args.args[0], ["python", "--version"])
        self.assertFalse(run_mock.call_args.kwargs["shell"])

    def test_run_command_restricted_mode_resolves_windows_command_wrappers(self):
        tool = RunCommandTool()
        tool.bind_workspace(FIXTURE_ROOT)
        tool.set_execution_mode("restricted")

        completed = subprocess.CompletedProcess(
            args=[r"C:\Program Files\nodejs\npm.cmd", "install"],
            returncode=0,
            stdout="added 1 package",
            stderr="",
        )

        with patch(
            "neudev.tools.run_command.shutil.which",
            return_value=r"C:\Program Files\nodejs\npm.cmd",
        ), patch("subprocess.run", return_value=completed) as run_mock:
            result = tool.execute("npm install")

        self.assertIn("added 1 package", result)
        self.assertEqual(run_mock.call_args.args[0], [r"C:\Program Files\nodejs\npm.cmd", "install"])
        self.assertFalse(run_mock.call_args.kwargs["shell"])

    def test_run_command_restricted_mode_rejects_inline_execution(self):
        tool = RunCommandTool()
        tool.bind_workspace(FIXTURE_ROOT)
        tool.set_execution_mode("restricted")

        with self.assertRaises(Exception) as cm:
            tool.execute("python -c \"print('nope')\"")

        self.assertIn("inline execution flags", str(cm.exception))

    def test_run_command_emits_background_wait_progress_for_long_commands(self):
        tool = RunCommandTool()
        tool.bind_workspace(FIXTURE_ROOT)
        events = []

        class FakeProcess:
            def __init__(self):
                self.returncode = 0
                self.calls = 0

            def communicate(self, timeout=None):
                self.calls += 1
                if self.calls < 3:
                    raise subprocess.TimeoutExpired("python --version", timeout)
                return ("Python 3.14.0", "")

            def kill(self):
                self.returncode = 1

        monotonic_values = [0.0, 0.0, 2.5, 7.8, 8.0]
        with patch("subprocess.Popen", return_value=FakeProcess()), patch(
            "time.monotonic", side_effect=monotonic_values
        ):
            result = tool.execute("python --version", progress_callback=events.append)

        self.assertIn("Python 3.14.0", result)
        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[0]["event"], "progress")
        self.assertEqual(events[0]["mode"], "background_wait")
        self.assertEqual(events[0]["command"], "python --version")

    def test_run_command_honors_stop_requests(self):
        tool = RunCommandTool()
        tool.bind_workspace(FIXTURE_ROOT)
        stop_event = threading.Event()
        events = []

        class FakeProcess:
            def __init__(self):
                self.returncode = 0
                self.calls = 0
                self.killed = False
                self.pid = 12345  # Fake PID for process group operations

            def communicate(self, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    stop_event.set()
                    raise subprocess.TimeoutExpired("python --version", timeout)
                return ("", "")

            def kill(self):
                self.killed = True
                self.returncode = 1

        process = FakeProcess()
        
        # On Windows, os.killpg doesn't exist, so we only patch on Unix
        import os
        if os.name != 'nt':
            killpg_patch = patch("os.killpg")
            getpgid_patch = patch("os.getpgid", return_value=12345)
        else:
            killpg_patch = patch("os.killpg", create=True)  # create=True allows patching non-existent attributes
            getpgid_patch = patch("os.getpgid", return_value=12345, create=True)
        
        with patch("subprocess.Popen", return_value=process), patch("time.monotonic", side_effect=[0.0, 0.0, 0.5]), killpg_patch as mock_killpg, getpgid_patch:
            with self.assertRaises(Exception) as cm:
                tool.execute("python --version", progress_callback=events.append, stop_event=stop_event)

        # Check that either process.kill() or os.killpg() was called
        self.assertTrue(process.killed or mock_killpg.called)
        self.assertIn("Command stopped by user", str(cm.exception))
        self.assertEqual(events[-1]["mode"], "stop_requested")

    def test_read_files_batch_reads_multiple_related_files(self):
        tool = ReadFilesBatchTool()
        tool.bind_workspace(FIXTURE_ROOT)

        result = tool.execute(paths=["README.md", "src/example.py"])

        self.assertIn("README.md", result)
        self.assertIn("example.py", result)
        self.assertIn("hello", result)
        self.assertIn('return "ok"', result)


if __name__ == "__main__":
    unittest.main()
