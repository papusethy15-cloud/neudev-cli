import unittest
from unittest.mock import patch

from neudev.permissions import PermissionManager


class PermissionManagerTests(unittest.TestCase):
    @patch("neudev.permissions.console.print")
    def test_request_permission_reprompts_after_blank_input(self, _mock_print):
        manager = PermissionManager()

        with patch("neudev.permissions.console.input", side_effect=["", "y"]) as mock_input:
            allowed = manager.request_permission("write_file", "Write README.md")

        self.assertTrue(allowed)
        self.assertEqual(mock_input.call_count, 2)

    @patch("neudev.permissions.console.print")
    def test_request_permission_only_auto_approves_tool_after_explicit_always(self, _mock_print):
        manager = PermissionManager()

        with patch("neudev.permissions.console.input", return_value="a"):
            allowed = manager.request_permission("write_file", "Write README.md")

        self.assertTrue(allowed)
        self.assertTrue(manager._session_approvals["write_file"])

    @patch("neudev.permissions.console.print")
    def test_grant_once_is_consumed_after_single_use(self, _mock_print):
        manager = PermissionManager()
        manager.grant_once("write_file")

        self.assertTrue(manager.request_permission("write_file", "Write README.md"))

        with patch("neudev.permissions.console.input", return_value="n"):
            self.assertFalse(manager.request_permission("write_file", "Write README.md"))


if __name__ == "__main__":
    unittest.main()
