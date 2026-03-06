import unittest
from pathlib import Path

from neudev.tools.list_dir import ListDirectoryTool
from neudev.tools.read_file import ReadFileTool


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "workspace_basic"


class WorkspaceBoundToolTests(unittest.TestCase):
    def test_read_file_uses_workspace_relative_path(self):
        tool = ReadFileTool()
        tool.bind_workspace(FIXTURE_ROOT)
        result = tool.execute("README.md")

        self.assertIn("README.md", result)
        self.assertIn("hello", result)

    def test_workspace_name_prefix_maps_back_to_root(self):
        tool = ReadFileTool()
        tool.bind_workspace(FIXTURE_ROOT)
        result = tool.execute(f"{FIXTURE_ROOT.name}/README.md")

        self.assertIn("hello", result)

    def test_list_directory_defaults_to_workspace_root(self):
        tool = ListDirectoryTool()
        tool.bind_workspace(FIXTURE_ROOT)
        result = tool.execute()

        self.assertIn("src/", result)


if __name__ == "__main__":
    unittest.main()
