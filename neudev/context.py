"""Workspace context management for NeuDev."""

import os
from pathlib import Path
from typing import Optional


# Project type detection patterns
PROJECT_SIGNATURES = {
    "python": ["setup.py", "pyproject.toml", "requirements.txt", "Pipfile", "setup.cfg"],
    "node": ["package.json", "yarn.lock", "pnpm-lock.yaml"],
    "rust": ["Cargo.toml"],
    "go": ["go.mod"],
    "java": ["pom.xml", "build.gradle"],
    "dotnet": ["*.csproj", "*.sln"],
    "flutter": ["pubspec.yaml"],
    "ruby": ["Gemfile"],
}

EXCLUDE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".env", ".idea", ".vscode", "dist", "build", ".tox",
    "target", ".gradle", ".dart_tool",
}


class WorkspaceContext:
    """Tracks and analyzes the current workspace."""

    def __init__(self, workspace_path: str):
        self.workspace = Path(workspace_path).resolve()
        self.recent_files: list[str] = []
        self._project_type: Optional[str] = None
        self._file_count: int = 0
        self._dir_count: int = 0

    def analyze(self) -> dict:
        """Analyze the workspace and return summary info."""
        if not self.workspace.exists():
            return {"error": f"Workspace not found: {self.workspace}"}

        self._project_type = self._detect_project_type()
        self._file_count, self._dir_count = self._count_contents()

        return {
            "path": str(self.workspace),
            "project_type": self._project_type or "unknown",
            "file_count": self._file_count,
            "dir_count": self._dir_count,
            "key_files": self._find_key_files(),
        }

    def _detect_project_type(self) -> Optional[str]:
        """Detect the project type based on signature files."""
        for ptype, signatures in PROJECT_SIGNATURES.items():
            for sig in signatures:
                if "*" in sig:
                    # Glob pattern
                    if list(self.workspace.glob(sig)):
                        return ptype
                else:
                    if (self.workspace / sig).exists():
                        return ptype
        return None

    def _count_contents(self) -> tuple[int, int]:
        """Count files and directories."""
        files = 0
        dirs = 0
        try:
            for root, dirnames, filenames in os.walk(self.workspace):
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
                files += len(filenames)
                dirs += len(dirnames)
                if files > 10000:  # Safety cap
                    break
        except PermissionError:
            pass
        return files, dirs

    def _find_key_files(self) -> list[str]:
        """Find key/important files in the project."""
        key_patterns = [
            "README.md", "README.rst", "README.txt",
            "setup.py", "pyproject.toml", "package.json",
            "Makefile", "Dockerfile", "docker-compose.yml",
            ".gitignore", "requirements.txt",
            "main.py", "app.py", "index.js", "index.ts",
        ]
        found = []
        for pattern in key_patterns:
            path = self.workspace / pattern
            if path.exists():
                found.append(pattern)
        return found

    def track_file_access(self, path: str) -> None:
        """Track a file access for context."""
        abs_path = str(Path(path).resolve())
        if abs_path in self.recent_files:
            self.recent_files.remove(abs_path)
        self.recent_files.insert(0, abs_path)
        # Keep only last 20
        self.recent_files = self.recent_files[:20]

    def get_system_context(self) -> str:
        """Generate workspace context string for the agent's system prompt."""
        info = self.analyze()

        parts = [
            f"Workspace: {info['path']}",
            f"Project type: {info['project_type']}",
            f"Files: {info['file_count']}, Directories: {info['dir_count']}",
        ]

        if info.get("key_files"):
            parts.append(f"Key files: {', '.join(info['key_files'])}")

        if self.recent_files:
            recent = [Path(f).name for f in self.recent_files[:5]]
            parts.append(f"Recently accessed: {', '.join(recent)}")

        return "\n".join(parts)
