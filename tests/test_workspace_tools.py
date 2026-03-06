import tempfile
import unittest
from pathlib import Path

from neudev.tools.list_dir import ListDirectoryTool
from neudev.tools.read_file import ReadFileTool


class WorkspaceBoundToolTests(unittest.TestCase):
    def test_read_file_uses_workspace_relative_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "README.md").write_text("hello\n", encoding="utf-8")

            tool = ReadFileTool()
            tool.bind_workspace(root)
            result = tool.execute("README.md")

            self.assertIn("README.md", result)
            self.assertIn("hello", result)

    def test_workspace_name_prefix_maps_back_to_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "README.md").write_text("hello\n", encoding="utf-8")

            tool = ReadFileTool()
            tool.bind_workspace(root)
            result = tool.execute(f"{root.name}/README.md")

            self.assertIn("hello", result)

    def test_list_directory_defaults_to_workspace_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()

            tool = ListDirectoryTool()
            tool.bind_workspace(root)
            result = tool.execute()

            self.assertIn("src/", result)


if __name__ == "__main__":
    unittest.main()
