import json
import tomllib
import unittest
from pathlib import Path

from neudev import __version__


ROOT = Path(__file__).resolve().parent.parent


class PackagingTests(unittest.TestCase):
    def test_python_and_npm_versions_match(self):
        package_json = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package_json["version"], __version__)

    def test_pyproject_has_expected_metadata(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = pyproject["project"]

        self.assertEqual(project["name"], "neudev")
        self.assertIn("ollama>=0.4.0", project["dependencies"])
        self.assertEqual(project["scripts"]["neu"], "neudev.cli:main")

    def test_release_assets_exist(self):
        expected = [
            ROOT / "LICENSE",
            ROOT / "MANIFEST.in",
            ROOT / ".env.lightning.example",
            ROOT / "pyproject.toml",
            ROOT / "docs" / "lightning-deployment.md",
            ROOT / "docs" / "release.md",
            ROOT / "bin" / "neu.js",
            ROOT / "scripts" / "lightning_bootstrap.sh",
            ROOT / "scripts" / "npm-postinstall.js",
            ROOT / "scripts" / "npm-uninstall.js",
            ROOT / "scripts" / "lightning_quick_tunnel.sh",
        ]
        for path in expected:
            self.assertTrue(path.exists(), f"Missing release asset: {path}")

    def test_lightning_entrypoint_uses_repo_python_module(self):
        script = (ROOT / "scripts" / "lightning_entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn('cd "$ROOT_DIR"', script)
        self.assertIn('-m neudev.cli serve', script)
        self.assertIn("/api/tags", script)
        self.assertNotIn('set -- neu serve', script)

    def test_lightning_bootstrap_has_auto_install_and_full_model_defaults(self):
        script = (ROOT / "scripts" / "lightning_bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn("NEUDEV_INSTALL_OLLAMA", script)
        self.assertIn("https://ollama.com/install.sh", script)
        self.assertIn("starcoder2:7b", script)


if __name__ == "__main__":
    unittest.main()
