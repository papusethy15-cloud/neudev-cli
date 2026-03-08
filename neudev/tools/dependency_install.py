"""Smart dependency installation tool for NeuDev."""

from __future__ import annotations

import subprocess
from pathlib import Path

from neudev.tools.base import BaseTool, ToolError


PACKAGE_MANAGERS = {
    "pip": {
        "config_files": ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg"],
        "install_cmd": ["pip", "install"],
        "install_dev_cmd": ["pip", "install", "-e", "."],
        "add_cmd": ["pip", "install"],
    },
    "npm": {
        "config_files": ["package.json"],
        "install_cmd": ["npm", "install"],
        "add_cmd": ["npm", "install"],
    },
    "yarn": {
        "config_files": ["yarn.lock"],
        "install_cmd": ["yarn", "install"],
        "add_cmd": ["yarn", "add"],
    },
    "pnpm": {
        "config_files": ["pnpm-lock.yaml"],
        "install_cmd": ["pnpm", "install"],
        "add_cmd": ["pnpm", "add"],
    },
    "cargo": {
        "config_files": ["Cargo.toml"],
        "install_cmd": ["cargo", "build"],
        "add_cmd": ["cargo", "add"],
    },
    "go": {
        "config_files": ["go.mod"],
        "install_cmd": ["go", "mod", "download"],
        "add_cmd": ["go", "get"],
    },
}


class DependencyInstallTool(BaseTool):
    """Detect the package manager and install dependencies."""

    @property
    def name(self) -> str:
        return "dependency_install"

    @property
    def description(self) -> str:
        return (
            "Install project dependencies or add new packages. Automatically "
            "detects the package manager (pip, npm, yarn, pnpm, cargo, go) from "
            "project config files. Can install all dependencies or add specific packages."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "packages": {
                    "type": "string",
                    "description": (
                        "Space-separated package names to install. "
                        "Leave empty to install all project dependencies."
                    ),
                },
                "manager": {
                    "type": "string",
                    "description": (
                        "Override the package manager (pip, npm, yarn, pnpm, cargo, go). "
                        "Auto-detected if not specified."
                    ),
                },
                "dev": {
                    "type": "boolean",
                    "description": "Install as development dependency (default false).",
                },
            },
            "required": [],
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        packages = args.get("packages", "")
        manager = args.get("manager", "auto-detect")
        if packages:
            return f"Install packages: {packages} (using {manager})"
        return f"Install all project dependencies (using {manager})"

    def execute(
        self,
        packages: str = "",
        manager: str = "",
        dev: bool = False,
        **kwargs,
    ) -> str:
        workspace = self.workspace or Path.cwd()
        detected_manager = manager.strip().lower() if manager else self._detect_manager(workspace)
        if not detected_manager:
            raise ToolError(
                "Could not detect package manager. No config file found "
                "(package.json, requirements.txt, Cargo.toml, go.mod, etc.). "
                "Specify the manager explicitly or create a config file first."
            )

        if detected_manager not in PACKAGE_MANAGERS:
            raise ToolError(
                f"Unsupported package manager: {detected_manager}. "
                f"Supported: {', '.join(PACKAGE_MANAGERS.keys())}"
            )

        pm = PACKAGE_MANAGERS[detected_manager]
        package_list = packages.strip().split() if packages and packages.strip() else []

        if package_list:
            cmd = list(pm["add_cmd"]) + package_list
            if dev:
                if detected_manager == "pip":
                    pass  # pip doesn't have --dev
                elif detected_manager in ("npm", "yarn", "pnpm"):
                    cmd.append("--save-dev" if detected_manager == "npm" else "-D")
                elif detected_manager == "cargo":
                    cmd.extend(["--dev"])
        else:
            cmd = list(pm["install_cmd"])

        try:
            result = subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            # Provide helpful fallback based on manager type
            fallback_suggestions = {
                "npm": (
                    "npm is not installed. Install Node.js from https://nodejs.org/ or use:\n"
                    "  - Windows: winget install OpenJS.NodeJS.LTS\n"
                    "  - macOS: brew install node\n"
                    "  - Linux: sudo apt install npm  or  sudo dnf install npm"
                ),
                "pip": (
                    "pip is not installed. Ensure Python is installed from https://python.org/\n"
                    "Or use: python -m ensurepip --upgrade"
                ),
                "yarn": (
                    "yarn is not installed. Install with: npm install -g yarn"
                ),
                "pnpm": (
                    "pnpm is not installed. Install with: npm install -g pnpm"
                ),
                "cargo": (
                    "cargo is not installed. Install Rust from https://rustup.rs/"
                ),
                "go": (
                    "go is not installed. Install from https://go.dev/dl/"
                ),
            }
            suggestion = fallback_suggestions.get(
                detected_manager,
                f"Please install {detected_manager} and ensure it's in your PATH."
            )
            raise ToolError(
                f"Package manager '{detected_manager}' is not installed or not in PATH.\n\n"
                f"💡 {suggestion}"
            )
        except subprocess.TimeoutExpired:
            raise ToolError(f"Installation timed out after 120 seconds.")
        except Exception as e:
            raise ToolError(f"Installation failed: {type(e).__name__}: {e}")

        output = ""
        if result.stdout:
            output += result.stdout.strip()
        if result.stderr:
            output += ("\n" if output else "") + result.stderr.strip()
        if len(output) > 3000:
            output = output[:3000] + "\n... (output truncated)"

        status = "✅ Success" if result.returncode == 0 else f"❌ Failed (exit {result.returncode})"
        action = f"Installing {' '.join(package_list)}" if package_list else "Installing all dependencies"

        return (
            f"{action}\n"
            f"Manager: {detected_manager}\n"
            f"Command: {' '.join(cmd)}\n"
            f"Status: {status}\n\n"
            f"{output or '(no output)'}"
        )

    @staticmethod
    def _detect_manager(workspace: Path) -> str | None:
        """Detect package manager from config files in workspace."""
        # Check in priority order (more specific lockfiles first)
        priority_order = [
            ("pnpm-lock.yaml", "pnpm"),
            ("yarn.lock", "yarn"),
            ("package-lock.json", "npm"),
            ("package.json", "npm"),
            ("Cargo.toml", "cargo"),
            ("go.mod", "go"),
            ("pyproject.toml", "pip"),
            ("requirements.txt", "pip"),
            ("setup.py", "pip"),
        ]
        for config_file, manager in priority_order:
            if (workspace / config_file).exists():
                return manager
        return None
