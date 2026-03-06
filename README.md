# ⚡ NeuDev — Advanced AI Coding Agent

NeuDev is a professional AI coding agent powered by **Ollama** and **Qwen 3.5**, featuring a rich interactive terminal interface inspired by RovoDev CLI.

## ✨ Features

- **ReAct Agent Loop** — Think → Plan → Act → Observe reasoning engine
- **9 Built-in Tools** — File read/write/edit/delete, search, grep, directory listing, command execution, code outline
- **Rich Terminal UI** — Syntax-highlighted output, spinners, color-coded messages, markdown rendering
- **Permission System** — Prompts before destructive operations (write, edit, delete, run command)
- **Session Tracking** — Full action history, file backups, undo support, session summary on exit
- **Model Switching** — Switch between any downloaded Ollama models with `/models`
- **Workspace Awareness** — Auto-detects project type, key files, and structure

## 📦 Installation

```bash
cd c:\WorkSpace\neu-dev
pip install -e .
```

This registers the `neu` command globally.

## 🚀 Usage

```bash
# Start the interactive agent in the current directory
neu run

# Start in a specific workspace
neu run --workspace /path/to/project

# Use a specific model
neu run --model qwen2:1.5b

# Show version
neu --version
```

## 💬 Slash Commands

| Command    | Action                                    |
|------------|-------------------------------------------|
| `/help`    | Show all commands and usage               |
| `/models`  | List downloaded Ollama models, switch     |
| `/clear`   | Clear conversation history                |
| `/remove`  | Undo last file change                     |
| `/history` | Show session action history               |
| `/config`  | Show current configuration                |
| `/version` | Show version info                         |
| `/exit`    | End session with summary                  |

## 🔧 Built-in Tools

| Tool           | Permission | Description                        |
|----------------|:----------:|------------------------------------|
| `read_file`    | No         | Read file contents with line range |
| `write_file`   | Yes        | Create/overwrite files             |
| `edit_file`    | Yes        | Find/replace editing with diff     |
| `delete_file`  | Yes        | Delete files                       |
| `search_files` | No         | Find files by name/glob            |
| `grep_search`  | No         | Search file contents               |
| `list_directory`| No        | Directory tree listing             |
| `run_command`  | Yes        | Shell command execution            |
| `file_outline` | No         | Code structure (AST for Python)    |

## ⚙️ Configuration

Configuration is stored in `~/.neudev/config.json`:

```json
{
  "model": "qwen3.5:0.8b",
  "temperature": 0.7,
  "max_tokens": 4096,
  "ollama_host": "http://localhost:11434",
  "max_iterations": 20,
  "command_timeout": 30
}
```

## 📋 Requirements

- Python ≥ 3.10
- [Ollama](https://ollama.com) running locally
- At least one model pulled (e.g., `ollama pull qwen3.5:0.8b`)

## 📄 License

MIT
