"""Project scaffolding tool for NeuDev — create standard project structures."""

from __future__ import annotations

from pathlib import Path

from neudev.tools.base import BaseTool, ToolError


TEMPLATES: dict[str, dict[str, str | list[str]]] = {
    "python": {
        "description": "Python project with pyproject.toml, src layout, and tests",
        "directories": ["src", "tests", "docs"],
        "files": {
            "pyproject.toml": """[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "{name}"
version = "0.1.0"
description = ""
readme = "README.md"
requires-python = ">=3.10"
""",
            "README.md": "# {name}\n\nA new Python project.\n",
            "src/__init__.py": "",
            "tests/__init__.py": "",
            "tests/test_placeholder.py": (
                'def test_placeholder():\n    """Placeholder test."""\n    assert True\n'
            ),
            ".gitignore": (
                "__pycache__/\n*.pyc\n*.pyo\n.venv/\nvenv/\n"
                "dist/\n*.egg-info/\n.pytest_cache/\n.mypy_cache/\n"
            ),
        },
    },
    "node": {
        "description": "Node.js project with package.json and src directory",
        "directories": ["src", "tests"],
        "files": {
            "package.json": "{{\n  \"name\": \"{name}\",\n  \"version\": \"1.0.0\",\n  \"description\": \"\",\n  \"main\": \"src/index.js\",\n  \"scripts\": {{\n    \"start\": \"node src/index.js\",\n    \"test\": \"echo \\\\\"Error: no test specified\\\\\" && exit 1\"\n  }},\n  \"keywords\": [],\n  \"license\": \"MIT\"\n}}\n",
            "README.md": "# {name}\n\nA new Node.js project.\n",
            "src/index.js": 'console.log("Hello from {name}!");\n',
            ".gitignore": "node_modules/\ndist/\n.env\n*.log\n",
        },
    },
    "react": {
        "description": "React + Vite project structure",
        "directories": ["src", "src/components", "public"],
        "files": {
            "package.json": "{{\n  \"name\": \"{name}\",\n  \"version\": \"0.1.0\",\n  \"private\": true,\n  \"scripts\": {{\n    \"dev\": \"vite\",\n    \"build\": \"vite build\"\n  }},\n  \"dependencies\": {{\n    \"react\": \"^18.3.0\",\n    \"react-dom\": \"^18.3.0\"\n  }},\n  \"devDependencies\": {{\n    \"vite\": \"^5.0.0\",\n    \"@vitejs/plugin-react\": \"^4.0.0\"\n  }}\n}}\n",
            "README.md": "# {name}\n\nA new React + Vite project.\n",
            "index.html": (
                '<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="UTF-8">\n'
                '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
                "  <title>{name}</title>\n</head>\n<body>\n"
                '  <div id="root"></div>\n  <script type="module" src="/src/main.jsx"></script>\n'
                "</body>\n</html>\n"
            ),
            "src/main.jsx": (
                "import React from 'react';\nimport ReactDOM from 'react-dom/client';\n"
                "import App from './App';\n\n"
                "ReactDOM.createRoot(document.getElementById('root')).render(\n"
                "  <React.StrictMode>\n    <App />\n  </React.StrictMode>\n);\n"
            ),
            "src/App.jsx": (
                "export default function App() {\n"
                "  return <h1>Hello from {name}!</h1>;\n}\n"
            ),
            ".gitignore": "node_modules/\ndist/\n.env\n*.log\n",
        },
    },
    "fastapi": {
        "description": "FastAPI project with app structure",
        "directories": ["app", "app/routers", "tests"],
        "files": {
            "pyproject.toml": """[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "{name}"
version = "0.1.0"
dependencies = ["fastapi>=0.110.0", "uvicorn>=0.29.0"]
""",
            "requirements.txt": "fastapi>=0.110.0\nuvicorn>=0.29.0\n",
            "README.md": "# {name}\n\nA new FastAPI project.\n",
            "app/__init__.py": "",
            "app/main.py": (
                "from fastapi import FastAPI\n\napp = FastAPI(title=\"{name}\")\n\n\n"
                "@app.get(\"/\")\ndef root():\n    return {\"message\": \"Hello from {name}!\"}\n"
            ),
            "app/routers/__init__.py": "",
            "tests/__init__.py": "",
            ".gitignore": (
                "__pycache__/\n*.pyc\n.venv/\nvenv/\n.env\n"
                "*.egg-info/\n.pytest_cache/\n"
            ),
        },
    },
}


class ProjectInitTool(BaseTool):
    """Scaffold a new project from a template."""

    @property
    def name(self) -> str:
        return "project_init"

    @property
    def description(self) -> str:
        templates = ", ".join(TEMPLATES.keys())
        return (
            f"Scaffold a new project structure from a template. "
            f"Available templates: {templates}. "
            f"Creates directory layout, config files, and README. "
            f"Will not overwrite existing files."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "template": {
                    "type": "string",
                    "description": f"Project template: {', '.join(TEMPLATES.keys())}",
                },
                "name": {
                    "type": "string",
                    "description": "Project name (used for package.json, pyproject.toml, etc.)",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to scaffold in (defaults to workspace root).",
                },
            },
            "required": ["template", "name"],
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        template = args.get("template", "unknown")
        name = args.get("name", "project")
        directory = args.get("directory", ".")
        return f"Scaffold '{template}' project '{name}' in: {directory}"

    def execute(
        self,
        template: str,
        name: str,
        directory: str = "",
        **kwargs,
    ) -> str:
        template_key = template.strip().lower()
        if template_key not in TEMPLATES:
            raise ToolError(
                f"Unknown template: {template}. "
                f"Available: {', '.join(TEMPLATES.keys())}"
            )

        if not name or not name.strip():
            raise ToolError("Project name is required.")

        name = name.strip()
        base = self.resolve_directory(directory or None)

        tmpl = TEMPLATES[template_key]
        created_dirs: list[str] = []
        created_files: list[str] = []
        skipped_files: list[str] = []

        # Create directories
        for dir_name in tmpl.get("directories", []):
            dir_path = base / dir_name
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                created_dirs.append(dir_name)

        # Create files
        for file_rel, content_template in tmpl.get("files", {}).items():
            file_path = base / file_rel
            if file_path.exists():
                skipped_files.append(file_rel)
                continue
            file_path.parent.mkdir(parents=True, exist_ok=True)
            content = str(content_template).format(name=name)
            file_path.write_text(content, encoding="utf-8")
            created_files.append(file_rel)

        lines = [f"Scaffolded '{template_key}' project: {name}"]
        if created_dirs:
            lines.append(f"Created directories: {', '.join(created_dirs)}")
        if created_files:
            lines.append(f"Created files: {', '.join(created_files)}")
        if skipped_files:
            lines.append(f"Skipped (already exist): {', '.join(skipped_files)}")
        if not created_files and not created_dirs:
            lines.append("All files already exist — nothing was created.")

        return "\n".join(lines)
