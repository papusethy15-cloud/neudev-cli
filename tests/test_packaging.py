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
            ROOT / "pyproject.toml",
            ROOT / "docs" / "release.md",
            ROOT / "bin" / "neu.js",
            ROOT / "scripts" / "npm-postinstall.js",
            ROOT / "scripts" / "npm-uninstall.js",
        ]
        for path in expected:
            self.assertTrue(path.exists(), f"Missing release asset: {path}")


if __name__ == "__main__":
    unittest.main()
