import unittest
from pathlib import Path

from neudev.context import WorkspaceContext


REACT_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "workspace_react_app"


class WorkspaceContextTests(unittest.TestCase):
    def test_react_workspace_reports_frontend_role_entrypoints_and_stack_guardrails(self):
        context = WorkspaceContext(str(REACT_FIXTURE_ROOT))

        info = context.analyze()

        self.assertEqual(info["project_type"], "frontend app")
        self.assertEqual(info["primary_role"], "frontend")
        self.assertIn("Node.js", info["technologies"])
        self.assertIn("React", info["technologies"])
        self.assertIn("TypeScript", info["technologies"])
        self.assertIn("src/main.tsx", info["entry_files"])
        self.assertIn("src/App.tsx", info["entry_files"])
        self.assertTrue(any("Do not introduce unrelated Python" in item for item in info["stack_guardrails"]))

        system_context = context.get_system_context()
        self.assertIn("Project type: frontend app", system_context)
        self.assertIn("Primary role: frontend", system_context)
        self.assertIn("Likely entry files: src/main.tsx", system_context)
        self.assertIn("Stack guardrails:", system_context)


if __name__ == "__main__":
    unittest.main()
