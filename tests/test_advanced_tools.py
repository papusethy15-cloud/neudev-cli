import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from neudev.tools.diagnostics import DiagnosticsTool
from neudev.tools.git_diff_review import GitDiffReviewTool
from neudev.tools.python_ast_edit import PythonAstEditTool


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "workspace_basic"


class AdvancedToolTests(unittest.TestCase):
    def setUp(self):
        self.sample_path = FIXTURE_ROOT / "src" / "sample_module.py"
        self.original_sample = self.sample_path.read_text(encoding="utf-8")

    def tearDown(self):
        self.sample_path.write_text(self.original_sample, encoding="utf-8")

    def test_python_ast_edit_replaces_top_level_function(self):
        tool = PythonAstEditTool()
        tool.bind_workspace(FIXTURE_ROOT)

        result = tool.execute(
            path="src/sample_module.py",
            symbol="greet",
            replacement_code=(
                "def greet(name: str) -> str:\n"
                "    return f\"Hi, {name}!\""
            ),
        )

        updated = self.sample_path.read_text(encoding="utf-8")
        self.assertIn("AST edited", result)
        self.assertIn("Hi, {name}!", updated)

    def test_python_ast_edit_replaces_class_method(self):
        tool = PythonAstEditTool()
        tool.bind_workspace(FIXTURE_ROOT)

        result = tool.execute(
            path="src/sample_module.py",
            symbol="Worker.run",
            replacement_code=(
                "def run(self) -> str:\n"
                "    return \"done\""
            ),
        )

        updated = self.sample_path.read_text(encoding="utf-8")
        self.assertIn("Worker.run", result)
        self.assertIn('return "done"', updated)

    def test_diagnostics_falls_back_from_pytest_to_unittest(self):
        tool = DiagnosticsTool()
        tool.bind_workspace(FIXTURE_ROOT)

        first = subprocess.CompletedProcess(
            args=["python", "-m", "pytest", "-q"],
            returncode=1,
            stdout="",
            stderr="No module named pytest",
        )
        second = subprocess.CompletedProcess(
            args=["python", "-m", "unittest", "discover", "-s", "tests"],
            returncode=0,
            stdout="OK",
            stderr="",
        )

        with patch("subprocess.run", side_effect=[first, second]):
            result = tool.execute(directory=".", checks=["tests"], timeout=30)

        self.assertIn("[PASS] tests", result)
        self.assertIn("python -m unittest discover", result)
        self.assertNotIn("python -m pytest -q", result)

    def test_git_diff_review_summarizes_status_and_patch(self):
        tool = GitDiffReviewTool()
        tool.bind_workspace(FIXTURE_ROOT)

        responses = [
            subprocess.CompletedProcess(args=["git"], returncode=0, stdout="true\n", stderr=""),
            subprocess.CompletedProcess(args=["git"], returncode=0, stdout=" M src/sample_module.py\n?? notes.txt\n", stderr=""),
            subprocess.CompletedProcess(args=["git"], returncode=0, stdout=" src/sample_module.py | 2 +-\n 1 file changed, 1 insertion(+), 1 deletion(-)\n", stderr=""),
            subprocess.CompletedProcess(args=["git"], returncode=0, stdout="diff --git a/src/sample_module.py b/src/sample_module.py\n@@ -1 +1 @@\n-old\n+new\n", stderr=""),
        ]

        with patch("subprocess.run", side_effect=responses):
            result = tool.execute(directory=".")

        self.assertIn("Git diff review", result)
        self.assertIn("src/sample_module.py", result)
        self.assertIn("Diff Stat:", result)
        self.assertIn("Patch:", result)

    def test_git_diff_review_scopes_relative_paths_to_repo_directory(self):
        tool = GitDiffReviewTool()
        tool.bind_workspace(FIXTURE_ROOT.parent)

        responses = [
            subprocess.CompletedProcess(args=["git"], returncode=0, stdout="true\n", stderr=""),
            subprocess.CompletedProcess(args=["git"], returncode=0, stdout=" M src/sample_module.py\n", stderr=""),
            subprocess.CompletedProcess(args=["git"], returncode=0, stdout=" src/sample_module.py | 1 +\n", stderr=""),
            subprocess.CompletedProcess(args=["git"], returncode=0, stdout="diff --git a/src/sample_module.py b/src/sample_module.py\n", stderr=""),
        ]

        with patch("subprocess.run", side_effect=responses) as run_mock:
            tool.execute(directory="workspace_basic", paths=["src/sample_module.py"])

        status_command = run_mock.call_args_list[1].args[0]
        diff_command = run_mock.call_args_list[3].args[0]
        self.assertEqual(status_command[-1], "src/sample_module.py")
        self.assertEqual(diff_command[-1], "src/sample_module.py")


if __name__ == "__main__":
    unittest.main()
