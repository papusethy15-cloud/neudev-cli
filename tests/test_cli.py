import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from neudev.cli import run_login_setup
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


if __name__ == "__main__":
    unittest.main()
