import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from neudev.tools import create_tool_registry
from neudev.tools.changed_files_diagnostics import ChangedFilesDiagnosticsTool
from neudev.tools.js_ts_symbol_edit import JsTsSymbolEditTool
from neudev.tools.symbol_search import SymbolSearchTool


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "workspace_basic"


class SmartAgentToolTests(unittest.TestCase):
    def setUp(self):
        self.ts_path = FIXTURE_ROOT / "web" / "sample.ts"
        self.original_ts = self.ts_path.read_text(encoding="utf-8")

    def tearDown(self):
        self.ts_path.write_text(self.original_ts, encoding="utf-8")

    def test_tool_registry_includes_smart_agent_tools(self):
        registry = create_tool_registry()
        names = {tool["name"] for tool in registry.list_tools()}

        self.assertIn("js_ts_symbol_edit", names)
        self.assertIn("symbol_search", names)
        self.assertIn("changed_files_diagnostics", names)

    def test_js_ts_symbol_edit_replaces_class_method(self):
        tool = JsTsSymbolEditTool()
        tool.bind_workspace(FIXTURE_ROOT)

        result = tool.execute(
            path="web/sample.ts",
            symbol="Widget.run",
            replacement_code=(
                "run(): string {\n"
                "    return \"done\";\n"
                "}"
            ),
        )

        updated = self.ts_path.read_text(encoding="utf-8")
        self.assertIn("Structured edited", result)
        self.assertIn('return "done";', updated)

    def test_symbol_search_finds_python_and_typescript_definitions(self):
        tool = SymbolSearchTool()
        tool.bind_workspace(FIXTURE_ROOT)

        py_result = tool.execute(symbol="greet", definitions_only=True)
        ts_result = tool.execute(symbol="Widget.run", definitions_only=True)

        self.assertIn("src/sample_module.py:1 function greet", py_result)
        self.assertIn("web/sample.ts:6 method Widget.run", ts_result)

    def test_changed_files_diagnostics_targets_related_python_tests(self):
        tool = ChangedFilesDiagnosticsTool()
        tool.bind_workspace(FIXTURE_ROOT)

        responses = [
            subprocess.CompletedProcess(args=["git"], returncode=0, stdout="true\n", stderr=""),
            subprocess.CompletedProcess(args=["git"], returncode=0, stdout=" M src/sample_module.py\n", stderr=""),
            subprocess.CompletedProcess(
                args=["python", "-m", "pytest", "-q", "tests/sample_module_test.py"],
                returncode=1,
                stdout="",
                stderr="No module named pytest",
            ),
            subprocess.CompletedProcess(
                args=["python", "-m", "unittest", "tests.sample_module_test"],
                returncode=0,
                stdout="OK",
                stderr="",
            ),
        ]

        with patch("subprocess.run", side_effect=responses) as run_mock:
            result = tool.execute(directory=".", checks=["tests"], timeout=30)

        self.assertIn("[PASS] tests [python]", result)
        self.assertIn("tests/sample_module_test.py", result)
        self.assertIn("python -m unittest tests.sample_module_test", result)
        self.assertEqual(run_mock.call_args_list[2].args[0][-1], "tests/sample_module_test.py")


if __name__ == "__main__":
    unittest.main()
