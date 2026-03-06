"""Workspace context management for NeuDev."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Optional

from neudev.project_memory import ProjectMemoryStore


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
COMPONENT_PARENTS = {"apps", "packages", "services", "projects"}
FRONTEND_MARKERS = {"frontend", "front-end", "client", "web", "ui"}
BACKEND_MARKERS = {"backend", "back-end", "server", "api", "service", "services"}
MOBILE_MARKERS = {"mobile", "android", "ios", "app"}
FRONTEND_PACKAGES = {"react", "next", "vite", "vue", "nuxt", "svelte", "@angular/core"}
BACKEND_PACKAGES = {"express", "fastify", "koa", "@nestjs/core", "hono"}
BACKEND_PYTHON_MARKERS = {"fastapi", "django", "flask", "uvicorn", "starlette"}
NODE_TECH_PACKAGES = {
    "React": {"react"},
    "Next.js": {"next"},
    "Vue": {"vue"},
    "Nuxt": {"nuxt"},
    "Svelte": {"svelte"},
    "Angular": {"@angular/core"},
    "Vite": {"vite"},
    "TypeScript": {"typescript"},
    "Tailwind CSS": {"tailwindcss"},
    "Express": {"express"},
    "NestJS": {"@nestjs/core"},
}
PYTHON_TECH_MARKERS = {
    "FastAPI": {"fastapi", "uvicorn", "starlette"},
    "Django": {"django"},
    "Flask": {"flask"},
    "Pydantic": {"pydantic"},
    "SQLAlchemy": {"sqlalchemy"},
    "Pytest": {"pytest"},
}
FLUTTER_TECH_MARKERS = {
    "Flutter": {"flutter"},
    "Dart": {"sdk: flutter", "environment:", "dependencies:"},
    "Riverpod": {"riverpod"},
    "Bloc": {"flutter_bloc", "bloc"},
}
KEY_FILE_PATTERNS = [
    "README.md", "README.rst", "README.txt",
    "setup.py", "pyproject.toml", "package.json", "pubspec.yaml",
    "Makefile", "Dockerfile", "docker-compose.yml",
    ".gitignore", "requirements.txt", "tsconfig.json",
    "main.py", "app.py", "index.js", "index.ts",
]
STYLE_FILE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".dart"}
DOUBLE_QUOTE_RE = re.compile(r'"[^"\n]*"')
SINGLE_QUOTE_RE = re.compile(r"'[^'\n]*'")
PYTHON_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+\w+\s*\(", re.MULTILINE)
PYTHON_TYPED_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+\w+\s*\([^)]*\)\s*->", re.MULTILINE)
JS_EXPORT_RE = re.compile(r"^\s*export\s+(?:default\s+)?(?:function|class|const|let|var)\b", re.MULTILINE)


class WorkspaceContext:
    """Tracks and analyzes the current workspace."""

    def __init__(self, workspace_path: str):
        self.workspace = Path(workspace_path).resolve()
        self.recent_files: list[str] = []
        self._project_type: Optional[str] = None
        self._file_count: int = 0
        self._dir_count: int = 0
        self._snapshot: dict[str, tuple[int, int]] = self._capture_snapshot()
        self.last_external_changes: dict[str, list[str]] = {
            "created": [],
            "modified": [],
            "deleted": [],
        }
        self.memory = ProjectMemoryStore(self.workspace)

    def analyze(self) -> dict:
        """Analyze the workspace and return summary info."""
        if not self.workspace.exists():
            return {"error": f"Workspace not found: {self.workspace}"}

        return self._analyze_workspace(sync_memory=True)

    def apply_user_memory_directives(self, user_message: str) -> bool:
        """Persist explicit user style or stack changes before the turn runs."""
        return self.memory.apply_user_directives(user_message)

    def _analyze_workspace(self, *, sync_memory: bool) -> dict:
        components = self._detect_components()
        root_type = self._detect_project_type()
        project_type = self._summarize_project_type(root_type, components)
        technologies = self._detect_technologies(root_type, components)
        observed_conventions = self._detect_conventions(components, technologies)
        self._project_type = project_type
        self._file_count, self._dir_count = self._count_contents()

        info = {
            "path": str(self.workspace),
            "project_type": project_type or "unknown",
            "file_count": self._file_count,
            "dir_count": self._dir_count,
            "key_files": self._find_key_files(self.workspace),
            "components": components,
            "technologies": technologies,
            "observed_conventions": observed_conventions,
            "external_changes": self.last_external_changes,
        }

        if sync_memory:
            self.memory.sync_from_analysis(info)

        info["conventions"] = self.memory.get_active_conventions(observed_conventions)
        info["memory_notes"] = self.memory.get_prompt_notes(info)
        return info

    def _detect_project_type(self, base: Optional[Path] = None) -> Optional[str]:
        """Detect the project type based on signature files."""
        target = base or self.workspace
        for ptype, signatures in PROJECT_SIGNATURES.items():
            for sig in signatures:
                if "*" in sig:
                    if list(target.glob(sig)):
                        return ptype
                elif (target / sig).exists():
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
                if files > 10000:
                    break
        except PermissionError:
            pass
        return files, dirs

    def _find_key_files(self, base: Path) -> list[str]:
        """Find key/important files in the project."""
        found = []
        for pattern in KEY_FILE_PATTERNS:
            path = base / pattern
            if path.exists():
                found.append(pattern)
        return found

    def _detect_components(self) -> list[dict]:
        """Detect major project components such as backend/frontend apps."""
        components = []
        seen: set[str] = set()
        for directory in self._candidate_component_dirs():
            project_type = self._detect_project_type(directory)
            if project_type is None:
                continue

            rel_path = self._relative_path(directory)
            if rel_path in seen:
                continue
            seen.add(rel_path)
            technologies = self._detect_component_technologies(directory, project_type)
            components.append({
                "name": directory.name if directory != self.workspace else self.workspace.name,
                "path": rel_path,
                "project_type": project_type,
                "role": self._detect_component_role(directory, project_type, technologies),
                "key_files": self._find_key_files(directory)[:5],
                "technologies": technologies,
            })

        return components

    def _candidate_component_dirs(self) -> list[Path]:
        """Return likely component directories to analyze."""
        candidates = [self.workspace]
        try:
            children = sorted(
                child for child in self.workspace.iterdir()
                if child.is_dir() and child.name not in EXCLUDE_DIRS
            )
        except OSError:
            return candidates

        for child in children:
            candidates.append(child)
            if child.name.lower() in COMPONENT_PARENTS:
                try:
                    grandchildren = sorted(
                        item for item in child.iterdir()
                        if item.is_dir() and item.name not in EXCLUDE_DIRS
                    )
                except OSError:
                    continue
                candidates.extend(grandchildren)
        return candidates

    def _detect_component_role(self, directory: Path, project_type: str, technologies: list[str]) -> str:
        """Infer the logical role of a component."""
        if directory == self.workspace:
            return "workspace"

        name_parts = {part.lower() for part in directory.relative_to(self.workspace).parts}
        if name_parts & FRONTEND_MARKERS:
            return "frontend"
        if name_parts & BACKEND_MARKERS:
            return "backend"
        if name_parts & MOBILE_MARKERS:
            return "mobile"

        if "Flutter" in technologies or project_type == "flutter":
            return "mobile"
        if any(tech in technologies for tech in ("React", "Next.js", "Vue", "Nuxt", "Svelte", "Angular")):
            return "frontend"
        if any(tech in technologies for tech in ("FastAPI", "Django", "Flask", "Express", "NestJS")):
            return "backend"

        if project_type == "node":
            package_data = self._read_package_json(directory)
            if package_data:
                deps = set(package_data.get("dependencies", {}).keys()) | set(package_data.get("devDependencies", {}).keys())
                if deps & FRONTEND_PACKAGES:
                    return "frontend"
                if deps & BACKEND_PACKAGES:
                    return "backend"

        if project_type == "python":
            config_text = self._read_python_config_text(directory)
            if any(marker in config_text for marker in BACKEND_PYTHON_MARKERS):
                return "backend"

        return project_type

    def _detect_component_technologies(self, directory: Path, project_type: str) -> list[str]:
        """Infer framework and language tags for a component."""
        technologies = []
        if project_type == "python":
            technologies.append("Python")
            config_text = self._read_python_config_text(directory)
            for name, markers in PYTHON_TECH_MARKERS.items():
                if any(marker in config_text for marker in markers):
                    technologies.append(name)
        elif project_type == "node":
            technologies.append("Node.js")
            package_data = self._read_package_json(directory)
            deps = set(package_data.get("dependencies", {}).keys()) | set(package_data.get("devDependencies", {}).keys())
            scripts = json.dumps(package_data.get("scripts", {})).lower()
            for name, markers in NODE_TECH_PACKAGES.items():
                if deps & markers:
                    technologies.append(name)
            if "vite" in scripts and "Vite" not in technologies:
                technologies.append("Vite")
            if (directory / "tsconfig.json").exists() or any(path.suffix.lower() in {".ts", ".tsx"} for path in directory.rglob("*")):
                technologies.append("TypeScript")
        elif project_type == "flutter":
            pubspec_text = self._read_pubspec_text(directory)
            for name, markers in FLUTTER_TECH_MARKERS.items():
                if any(marker in pubspec_text for marker in markers):
                    technologies.append(name)
            if "Flutter" not in technologies:
                technologies.append("Flutter")
            if "Dart" not in technologies:
                technologies.append("Dart")
        elif project_type:
            technologies.append(project_type.capitalize())

        return self._dedupe_preserve_order(technologies)

    def _detect_technologies(self, root_type: Optional[str], components: list[dict]) -> list[str]:
        """Summarize the workspace technology stack."""
        stack = []
        if root_type == "python":
            stack.append("Python")
        elif root_type == "node":
            stack.append("Node.js")
        elif root_type == "flutter":
            stack.extend(["Flutter", "Dart"])

        for component in components:
            stack.extend(component.get("technologies", []))

        return self._dedupe_preserve_order(stack)

    def _summarize_project_type(self, root_type: Optional[str], components: list[dict]) -> str:
        """Collapse component roles into a higher-level project description."""
        roles = {component["role"] for component in components if component["role"] not in {"workspace", "unknown"}}
        project_types = {component["project_type"] for component in components}
        non_root_components = [component for component in components if component["path"] != "."]

        if "frontend" in roles and "backend" in roles:
            return "fullstack"
        if "mobile" in roles and "backend" in roles:
            return "fullstack-mobile"
        if roles == {"mobile"}:
            return "mobile app"
        if len(non_root_components) > 1:
            return "multi-component"
        if len(project_types) > 1:
            return "polyglot"
        return root_type or (components[0]["project_type"] if components else "unknown")

    def poll_external_changes(self) -> dict[str, list[str]]:
        """Detect file changes since the last committed workspace snapshot."""
        current_snapshot = self._capture_snapshot()
        previous_paths = set(self._snapshot)
        current_paths = set(current_snapshot)

        created = sorted(current_paths - previous_paths)
        deleted = sorted(previous_paths - current_paths)
        modified = sorted(
            path for path in previous_paths & current_paths
            if self._snapshot[path] != current_snapshot[path]
        )

        self._snapshot = current_snapshot
        self.last_external_changes = {
            "created": created,
            "modified": modified,
            "deleted": deleted,
        }
        return self.last_external_changes

    def mark_workspace_state(self) -> None:
        """Commit the current workspace as the clean baseline for the next turn."""
        self._snapshot = self._capture_snapshot()
        self.last_external_changes = {"created": [], "modified": [], "deleted": []}

    def has_external_changes(self) -> bool:
        """Return True if any external changes are currently recorded."""
        return any(self.last_external_changes.values())

    def track_file_access(self, path: str) -> None:
        """Track a file access for context."""
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        abs_path = str(candidate.resolve())
        if abs_path in self.recent_files:
            self.recent_files.remove(abs_path)
        self.recent_files.insert(0, abs_path)
        self.recent_files = self.recent_files[:20]

    def get_system_context(self) -> str:
        """Generate workspace context string for the agent's system prompt."""
        info = self.analyze()

        parts = [
            f"Workspace: {info['path']}",
            f"Project type: {info['project_type']}",
            f"Files: {info['file_count']}, Directories: {info['dir_count']}",
        ]

        if info.get("technologies"):
            parts.append(f"Technologies: {', '.join(info['technologies'][:8])}")
        if info.get("key_files"):
            parts.append(f"Key files: {', '.join(info['key_files'])}")

        components = info.get("components") or []
        if components:
            component_lines = []
            for component in components[:6]:
                keys = f" | key files: {', '.join(component['key_files'])}" if component["key_files"] else ""
                tech = f" | tech: {', '.join(component['technologies'][:4])}" if component.get("technologies") else ""
                component_lines.append(
                    f"- {component['path']} [{component['role']}/{component['project_type']}]"
                    f"{tech}{keys}"
                )
            parts.append("Components:\n" + "\n".join(component_lines))

        memory_notes = info.get("memory_notes") or []
        if memory_notes:
            parts.append("Project Memory:\n" + "\n".join(f"- {item}" for item in memory_notes[:6]))

        conventions = info.get("conventions") or []
        if conventions:
            parts.append("Conventions:\n" + "\n".join(f"- {item}" for item in conventions[:6]))

        if self.recent_files:
            recent = [Path(f).name for f in self.recent_files[:5]]
            parts.append(f"Recently accessed: {', '.join(recent)}")

        if self.has_external_changes():
            parts.append(self._format_external_changes(self.last_external_changes))

        return "\n".join(parts)

    def _capture_snapshot(self, limit: int = 15000) -> dict[str, tuple[int, int]]:
        """Capture a lightweight workspace snapshot for external change detection."""
        snapshot: dict[str, tuple[int, int]] = {}
        if not self.workspace.exists():
            return snapshot

        try:
            for root, dirnames, filenames in os.walk(self.workspace):
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
                for filename in filenames:
                    filepath = Path(root) / filename
                    try:
                        stat = filepath.stat()
                    except OSError:
                        continue
                    snapshot[self._relative_path(filepath)] = (stat.st_mtime_ns, stat.st_size)
                    if len(snapshot) >= limit:
                        return snapshot
        except PermissionError:
            return snapshot
        return snapshot

    def _detect_conventions(self, components: list[dict], technologies: list[str]) -> list[str]:
        """Infer lightweight repository conventions from representative source files."""
        source_files = self._representative_source_files(limit=12)
        if not source_files:
            return self._component_conventions(components, technologies)

        indent_sizes = []
        tab_indentation = 0
        double_quotes = 0
        single_quotes = 0
        python_defs = 0
        python_typed_defs = 0
        js_exports = 0

        for filepath in source_files:
            try:
                source = filepath.read_text(encoding="utf-8")
            except OSError:
                continue

            for line in source.splitlines():
                stripped = line.lstrip(" \t")
                if not stripped:
                    continue
                if line.startswith("\t"):
                    tab_indentation += 1
                elif line.startswith(" "):
                    indent = len(line) - len(line.lstrip(" "))
                    if indent > 0:
                        indent_sizes.append(indent)

            double_quotes += len(DOUBLE_QUOTE_RE.findall(source))
            single_quotes += len(SINGLE_QUOTE_RE.findall(source))

            suffix = filepath.suffix.lower()
            if suffix == ".py":
                python_defs += len(PYTHON_DEF_RE.findall(source))
                python_typed_defs += len(PYTHON_TYPED_DEF_RE.findall(source))
            elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
                js_exports += len(JS_EXPORT_RE.findall(source))

        conventions = self._component_conventions(components, technologies)

        indent_note = self._indentation_convention(indent_sizes, tab_indentation)
        if indent_note:
            conventions.append(indent_note)

        if double_quotes or single_quotes:
            preferred = "double quotes" if double_quotes >= single_quotes else "single quotes"
            conventions.append(f"String literals mostly use {preferred}.")

        if python_defs and python_typed_defs >= max(1, math.ceil(python_defs / 2)):
            conventions.append("Python functions commonly include return type hints.")

        if js_exports:
            conventions.append("JS/TS modules commonly use explicit `export` declarations.")

        test_note = self._test_layout_convention()
        if test_note:
            conventions.append(test_note)

        return self._dedupe_preserve_order(conventions)[:6]

    def _representative_source_files(self, limit: int = 12) -> list[Path]:
        """Collect a small set of representative source files for convention inference."""
        ordered: list[Path] = []
        seen: set[str] = set()

        for path_str in self.recent_files:
            path = Path(path_str)
            if path.exists() and path.is_file() and path.suffix.lower() in STYLE_FILE_EXTENSIONS:
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    ordered.append(path)
                if len(ordered) >= limit:
                    return ordered

        try:
            for root, dirnames, filenames in os.walk(self.workspace):
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
                for filename in sorted(filenames):
                    filepath = Path(root) / filename
                    if filepath.suffix.lower() not in STYLE_FILE_EXTENSIONS:
                        continue
                    key = str(filepath)
                    if key in seen:
                        continue
                    seen.add(key)
                    ordered.append(filepath)
                    if len(ordered) >= limit:
                        return ordered
        except PermissionError:
            return ordered

        return ordered

    def _component_conventions(self, components: list[dict], technologies: list[str]) -> list[str]:
        """Derive high-level structural conventions from detected components."""
        roles = {component["role"] for component in components}
        conventions = []
        if "frontend" in roles and "backend" in roles:
            conventions.append("Keep backend and frontend changes within their existing component boundaries.")
        elif "mobile" in roles and "backend" in roles:
            conventions.append("Keep mobile app and backend changes within their existing component boundaries.")
        elif len([component for component in components if component["path"] != "."]) > 1:
            conventions.append("Preserve the existing multi-component directory structure when editing.")

        if "Flutter" in technologies:
            conventions.append("Preserve the existing Flutter widget and state-management structure.")
        return conventions

    @staticmethod
    def _indentation_convention(indent_sizes: list[int], tab_indentation: int) -> str:
        """Summarize the dominant indentation style."""
        if tab_indentation and not indent_sizes:
            return "Indentation is tab-based."
        if not indent_sizes:
            return ""

        normalized = [size for size in indent_sizes if 0 < size <= 8]
        if not normalized:
            normalized = indent_sizes

        unit = normalized[0]
        for size in normalized[1:]:
            unit = math.gcd(unit, size)
        if unit <= 0:
            return ""
        if unit == 1 and len(set(normalized)) == 1:
            unit = normalized[0]
        return f"Indentation mostly uses {unit} spaces."

    def _test_layout_convention(self) -> str:
        """Summarize how tests are organized in the repository."""
        tests_dir = self.workspace / "tests"
        if tests_dir.exists():
            if any(path.name.startswith("test_") for path in tests_dir.rglob("*.py")):
                return "Tests live under `tests/` and commonly use `test_*.py` naming."
            if any(path.name.endswith("_test.py") for path in tests_dir.rglob("*.py")):
                return "Tests live under `tests/` and commonly use `*_test.py` naming."
            if any(path.name.endswith((".test.ts", ".test.js", ".spec.ts", ".spec.js")) for path in tests_dir.rglob("*")):
                return "Tests live under `tests/` and commonly use `.test` or `.spec` naming."

        if any(path.name.startswith("test_") for path in self.workspace.rglob("*.py")):
            return "Python tests commonly use `test_*.py` naming."
        if any(path.name.endswith("_test.py") for path in self.workspace.rglob("*.py")):
            return "Python tests commonly use `*_test.py` naming."
        return ""

    def _relative_path(self, path: Path) -> str:
        """Convert an absolute path to a workspace-relative path."""
        return str(path.relative_to(self.workspace)).replace("\\", "/") if path != self.workspace else "."

    @staticmethod
    def _format_external_changes(changes: dict[str, list[str]], limit: int = 8) -> str:
        """Format external changes for the system prompt."""
        parts = []
        for label in ("created", "modified", "deleted"):
            items = changes.get(label) or []
            if not items:
                continue
            shown = items[:limit]
            suffix = " ..." if len(items) > limit else ""
            parts.append(f"{label}: {', '.join(shown)}{suffix}")
        return "External changes since last turn: " + " | ".join(parts)

    @staticmethod
    def _read_package_json(directory: Path) -> dict:
        """Read package.json when present."""
        package_file = directory / "package.json"
        if not package_file.exists():
            return {}
        try:
            return json.loads(package_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _read_python_config_text(directory: Path) -> str:
        """Read common Python dependency/config files as lowercase text."""
        texts = []
        for name in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile"):
            path = directory / name
            if not path.exists():
                continue
            try:
                texts.append(path.read_text(encoding="utf-8").lower())
            except OSError:
                continue
        return "\n".join(texts)

    @staticmethod
    def _read_pubspec_text(directory: Path) -> str:
        """Read pubspec.yaml when present."""
        pubspec = directory / "pubspec.yaml"
        if not pubspec.exists():
            return ""
        try:
            return pubspec.read_text(encoding="utf-8").lower()
        except OSError:
            return ""

    @staticmethod
    def _dedupe_preserve_order(values: list[str]) -> list[str]:
        seen = set()
        deduped = []
        for value in values:
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(value)
        return deduped
