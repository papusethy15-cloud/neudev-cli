import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from neudev.agent import Agent
from neudev.config import NeuDevConfig
from neudev.tools.grep_search import GrepSearchTool
from neudev.tools.read_files_batch import ReadFilesBatchTool
from neudev.tools.run_command import RunCommandTool
from neudev.tools.search_files import SearchFilesTool


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

        with patch("subprocess.run", return_value=completed) as run_mock:
            result = tool.execute("python --version")

        self.assertIn("Python 3.14.0", result)
        self.assertEqual(run_mock.call_args.args[0], ["python", "--version"])
        self.assertFalse(run_mock.call_args.kwargs["shell"])

    def test_run_command_restricted_mode_rejects_inline_execution(self):
        tool = RunCommandTool()
        tool.bind_workspace(FIXTURE_ROOT)
        tool.set_execution_mode("restricted")

        with self.assertRaises(Exception) as cm:
            tool.execute("python -c \"print('nope')\"")

        self.assertIn("inline execution flags", str(cm.exception))

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
