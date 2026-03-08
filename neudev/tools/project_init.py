"""Project scaffolding tool for NeuDev — create standard project structures."""

from __future__ import annotations

from pathlib import Path

from neudev.tools.base import BaseTool, ToolError


TEMPLATES: dict[str, dict[str, str | list[str]]] = {
    "html": {
        "description": "Simple HTML/CSS/JS website with single-page structure",
        "directories": ["css", "js", "assets"],
        "files": {
            "index.html": '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>{name}</title>\n    <link rel="stylesheet" href="css/style.css">\n</head>\n<body>\n    <header>\n        <nav>\n            <h1>{name}</h1>\n            <ul>\n                <li><a href="#home">Home</a></li>\n                <li><a href="#about">About</a></li>\n                <li><a href="#contact">Contact</a></li>\n            </ul>\n        </nav>\n    </header>\n    <main>\n        <section id="home">\n            <h2>Welcome to {name}</h2>\n            <p>Your amazing content here</p>\n        </section>\n    </main>\n    <footer>\n        <p>&copy; 2024 {name}. All rights reserved.</p>\n    </footer>\n    <script src="js/script.js"></script>\n</body>\n</html>\n',
            "css/style.css": "/* Modern CSS Reset */\n* {\n    margin: 0;\n    padding: 0;\n    box-sizing: border-box;\n}\n\nbody {\n    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;\n    line-height: 1.6;\n    color: #333;\n}\n\nheader {\n    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);\n    color: white;\n    padding: 1rem;\n}\n\nnav {\n    display: flex;\n    justify-content: space-between;\n    align-items: center;\n    max-width: 1200px;\n    margin: 0 auto;\n}\n\nnav ul {\n    display: flex;\n    list-style: none;\n    gap: 2rem;\n}\n\nnav a {\n    color: white;\n    text-decoration: none;\n}\n\nmain {\n    max-width: 1200px;\n    margin: 2rem auto;\n    padding: 0 1rem;\n}\n\nsection {\n    margin-bottom: 3rem;\n}\n\nfooter {\n    background: #333;\n    color: white;\n    text-align: center;\n    padding: 2rem;\n    margin-top: 3rem;\n}\n",
            "js/script.js": "// Modern JavaScript\nconsole.log('{name} - Website Loaded');\n\n// Smooth scrolling for navigation\ndocument.querySelectorAll('a[href^=\"#\"]').forEach(anchor => {\n    anchor.addEventListener('click', function (e) {\n        e.preventDefault();\n        const target = document.querySelector(this.getAttribute('href'));\n        if (target) {\n            target.scrollIntoView({ behavior: 'smooth' });\n        }\n    });\n});\n\n// Add your custom JavaScript here\n",
            "README.md": "# {name}\n\nA modern single-page website.\n\n## Structure\n\n- `index.html` - Main HTML file\n- `css/style.css` - Modern CSS styling\n- `js/script.js` - JavaScript interactivity\n\n## Usage\n\nOpen `index.html` in a web browser.\n",
        },
    },
    "python": {
        "description": "Python project with pyproject.toml, src layout, and tests",
        "directories": ["src", "tests", "docs"],
        "files": {
            "pyproject.toml": '[build-system]\nrequires = ["setuptools>=68.0", "wheel"]\nbuild-backend = "setuptools.build_meta"\n\n[project]\nname = "{name}"\nversion = "0.1.0"\ndescription = ""\nreadme = "README.md"\nrequires-python = ">=3.10"\n',
            "README.md": "# {name}\n\nA new Python project.\n",
            "src/__init__.py": "",
            "tests/__init__.py": "",
            "tests/test_placeholder.py": 'def test_placeholder():\n    """Placeholder test."""\n    assert True\n',
            ".gitignore": "__pycache__/\n*.pyc\n*.pyo\n.venv/\nvenv/\ndist/\n*.egg-info/\n.pytest_cache/\n.mypy_cache/\n",
        },
    },
    "node": {
        "description": "Node.js project with package.json and src directory",
        "directories": ["src", "tests"],
        "files": {
            "package.json": '{{\n  "name": "{name}",\n  "version": "1.0.0",\n  "description": "",\n  "main": "src/index.js",\n  "scripts": {{\n    "start": "node src/index.js",\n    "test": "echo \\"Error: no test specified\\" && exit 1"\n  }},\n  "keywords": [],\n  "license": "MIT"\n}}\n',
            "README.md": "# {name}\n\nA new Node.js project.\n",
            "src/index.js": 'console.log("Hello from {name}!");\n',
            ".gitignore": "node_modules/\ndist/\n.env\n*.log\n",
        },
    },
    "react": {
        "description": "React + Vite project structure",
        "directories": ["src", "src/components", "public"],
        "files": {
            "package.json": '{{\n  "name": "{name}",\n  "version": "0.1.0",\n  "private": true,\n  "scripts": {{\n    "dev": "vite",\n    "build": "vite build"\n  }},\n  "dependencies": {{\n    "react": "^18.3.0",\n    "react-dom": "^18.3.0"\n  }},\n  "devDependencies": {{\n    "vite": "^5.0.0",\n    "@vitejs/plugin-react": "^4.0.0"\n  }}\n}}\n',
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
            "pyproject.toml": '[build-system]\nrequires = ["setuptools>=68.0"]\nbuild-backend = "setuptools.build_meta"\n\n[project]\nname = "{name}"\nversion = "0.1.0"\ndependencies = ["fastapi>=0.110.0", "uvicorn>=0.29.0"]\n',
            "requirements.txt": "fastapi>=0.110.0\nuvicorn>=0.29.0\n",
            "README.md": "# {name}\n\nA new FastAPI project.\n",
            "app/__init__.py": "",
            "app/main.py": "from fastapi import FastAPI\n\napp = FastAPI(title=\"{name}\")\n\n\n@app.get(\"/\")\ndef root():\n    return {\"message\": \"Hello from {name}!\"}\n",
            "app/routers/__init__.py": "",
            "tests/__init__.py": "",
            ".gitignore": "__pycache__/\n*.pyc\n.venv/\nvenv/\n.env\n*.egg-info/\n.pytest_cache/\n",
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
            f"Creates directory layout, config files, and source files. "
            f"Will not overwrite existing files. "
            f"IMPORTANT: You MUST provide BOTH 'template' and 'name' parameters. "
            f"Example: project_init(template='html', name='My Website', directory='.') for HTML sites, "
            f"or project_init(template='python', name='my-app') for Python projects."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "template": {
                    "type": "string",
                    "description": f"Project template to use. MUST be one of: {', '.join(TEMPLATES.keys())}. For HTML/CSS/JS websites use 'html'. For Python backends use 'python'. For Node.js use 'node'. For React apps use 'react'.",
                },
                "name": {
                    "type": "string",
                    "description": "Project name (used in files, titles, etc.). Example: 'Travel GO', 'my-app', 'portfolio-website'. MUST be provided.",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to scaffold in. Use '.' for workspace root (default), or a subdirectory name like 'my-project'.",
                    "default": ".",
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
        directory: str = ".",
        **kwargs,
    ) -> str:
        # Validate template parameter
        if not template or not template.strip():
            raise ToolError(
                "Missing required 'template' parameter. "
                f"Available templates: {', '.join(TEMPLATES.keys())}. "
                "Example: project_init(template='html', name='My Website')"
            )
        
        template_key = template.strip().lower()
        if template_key not in TEMPLATES:
            raise ToolError(
                f"Unknown template: '{template}'. "
                f"Available templates are: {', '.join(TEMPLATES.keys())}. "
                f"For HTML/CSS/JS websites use 'html'. "
                f"Example: project_init(template='html', name='Travel GO')"
            )

        # Validate name parameter
        if not name or not name.strip():
            raise ToolError(
                "Missing required 'name' parameter. "
                "Provide a project name like 'my-app' or 'Travel GO'. "
                "Example: project_init(template='html', name='My Website')"
            )

        # Validate directory parameter - reject obvious mistakes
        directory = directory.strip() if directory else "."
        invalid_directory_values = ["/path/to/workspace", "workspace_root", "workspace", ".", "./", ""]
        if directory in invalid_directory_values or directory.startswith("/path"):
            # Use workspace root instead
            base = Path(self.workspace) if self.workspace else Path.cwd()
        else:
            base = self.resolve_directory(directory if directory != "." else None)

        name = name.strip()
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
