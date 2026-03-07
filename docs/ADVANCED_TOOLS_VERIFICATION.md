# Advanced Tools & Agent Intelligence Verification

**Date**: 2026-03-07  
**Version**: 2.0.4  
**Status**: ⚠️ **PARTIALLY IMPLEMENTED**

---

## Executive Summary

### ✅ **Advanced Tools: ALL IMPLEMENTED**

All 5 proposed advanced tools are fully implemented and registered:

1. ✅ `web_search` - Web search with DuckDuckGo lite API
2. ✅ `url_fetch` - URL content extraction with HTML-to-text
3. ✅ `patch_file` - Unified diff patch application
4. ✅ `dependency_install` - Smart package manager detection
5. ✅ `project_init` - Project scaffolding (Python, Node, React)

### ❌ **Agent Intelligence: NOT IMPLEMENTED**

Critical agent intelligence features are **MISSING** and need implementation:

1. ❌ Conversation pruning for long sessions
2. ❌ Self-correction on repeated tool errors
3. ❌ Dynamic tool selection guidance
4. ⚠️ Response streaming (partially implemented in llm.py, not used by agent)

---

## Detailed Verification

### 1. Advanced Tools ✅

#### 1.1 web_search.py ✅

**Status**: ✅ **FULLY IMPLEMENTED**

**Location**: `neudev/tools/web_search.py`

**Features**:
- ✅ Searches web for documentation, error solutions, API references
- ✅ Uses DuckDuckGo lite API (no API key required)
- ✅ Returns top 5 results with title, URL, and snippet
- ✅ Permission-gated (network access)
- ✅ HTML-to-text conversion for snippets

**Implementation**:
```python
class WebSearchTool(BaseTool):
    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for documentation, error solutions, code examples, "
            "and API references. Returns top results with title, URL, and snippet."
        )

    @property
    def requires_permission(self) -> bool:
        return True  # Network access requires permission
```

**API**:
```python
web_search(query: str, max_results: int = 5) -> str
```

---

#### 1.2 url_fetch.py ✅

**Status**: ✅ **FULLY IMPLEMENTED**

**Location**: `neudev/tools/url_fetch.py`

**Features**:
- ✅ Fetches and extracts text content from URLs
- ✅ Converts HTML to readable text
- ✅ Useful for documentation, READMEs, API docs
- ✅ Permission-gated (network access)
- ✅ Truncates output to 5000 chars

**Implementation**:
```python
class UrlFetchTool(BaseTool):
    @property
    def name(self) -> str:
        return "url_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch text content from a URL. Converts HTML to readable text. "
            "Output is truncated to 5000 characters."
        )

    @property
    def requires_permission(self) -> bool:
        return True  # Network access
```

**API**:
```python
url_fetch(url: str, max_chars: int = 5000) -> str
```

---

#### 1.3 patch_file.py ✅

**Status**: ✅ **FULLY IMPLEMENTED**

**Location**: `neudev/tools/patch_file.py`

**Features**:
- ✅ Applies unified diff patches to files
- ✅ Better for multi-region edits than find/replace
- ✅ Validates patch before applying
- ✅ Shows clear diff preview
- ✅ Permission-gated

**Implementation**:
```python
class PatchFileTool(BaseTool):
    @property
    def name(self) -> str:
        return "patch_file"

    @property
    def description(self) -> str:
        return (
            "Apply a unified diff (patch) to a file. Better than edit_file for "
            "multi-region edits. The patch is validated before applying."
        )

    def execute(self, path: str, patch: str, **kwargs) -> str:
        # Validates and applies patch
        hunks = self._parse_hunks(patch)
        result_lines, applied_count, total_hunks = self._apply_hunks(original_lines, hunks)
```

**API**:
```python
patch_file(path: str, patch: str) -> str
```

---

#### 1.4 dependency_install.py ✅

**Status**: ✅ **FULLY IMPLEMENTED**

**Location**: `neudev/tools/dependency_install.py`

**Features**:
- ✅ Smart package installation
- ✅ Detects package manager (pip, npm, cargo, etc.)
- ✅ Reads project config to determine correct manager
- ✅ Permission-gated
- ✅ Restricted-mode compatible

**Supported Package Managers**:
- `pip` (requirements.txt, pyproject.toml, setup.py)
- `npm` (package.json)
- `yarn` (yarn.lock)
- `pnpm` (pnpm-lock.yaml)
- `cargo` (Cargo.toml)
- `go` (go.mod)

**Implementation**:
```python
PACKAGE_MANAGERS = {
    "pip": {
        "config_files": ["requirements.txt", "pyproject.toml", "setup.py"],
        "install_cmd": ["pip", "install"],
    },
    "npm": {
        "config_files": ["package.json"],
        "install_cmd": ["npm", "install"],
    },
    # ... cargo, go, yarn, pnpm
}

class DependencyInstallTool(BaseTool):
    def _detect_manager(self) -> str:
        # Auto-detects from config files
```

**API**:
```python
dependency_install(packages: str = "", manager: str = "", dev: bool = False) -> str
```

---

#### 1.5 project_init.py ✅

**Status**: ✅ **FULLY IMPLEMENTED**

**Location**: `neudev/tools/project_init.py`

**Features**:
- ✅ Scaffolds common project structures
- ✅ Templates: Python, Node.js, React
- ✅ Creates directory layout, config files, README
- ✅ Detects existing project and avoids overwriting

**Templates**:
- **Python**: pyproject.toml, src layout, tests, README, .gitignore
- **Node.js**: package.json, src directory, README, .gitignore
- **React**: Vite setup, components, public, index.html

**Implementation**:
```python
TEMPLATES = {
    "python": {
        "directories": ["src", "tests", "docs"],
        "files": {
            "pyproject.toml": "...",
            "README.md": "# {name}\n\n...",
            "src/__init__.py": "",
        }
    },
    "node": { ... },
    "react": { ... },
}

class ProjectInitTool(BaseTool):
    def execute(self, name: str, template: str = "python", force: bool = False) -> str:
        # Creates project structure
```

**API**:
```python
project_init(name: str, template: str = "python", force: bool = False) -> str
```

---

#### 1.6 Tool Registration ✅

**Status**: ✅ **FULLY REGISTERED**

**Location**: `neudev/tools/__init__.py`

```python
from neudev.tools.web_search import WebSearchTool
from neudev.tools.url_fetch import UrlFetchTool
from neudev.tools.patch_file import PatchFileTool
from neudev.tools.dependency_install import DependencyInstallTool
from neudev.tools.project_init import ProjectInitTool

def create_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(WebSearchTool())
    registry.register(UrlFetchTool())
    registry.register(PatchFileTool())
    registry.register(DependencyInstallTool())
    registry.register(ProjectInitTool())
    # ... other tools
    return registry
```

---

### 2. Agent Intelligence ❌

#### 2.1 Conversation Pruning ❌

**Status**: ❌ **NOT IMPLEMENTED**

**Proposed**:
```python
def _prune_conversation(self, messages: list[dict], max_messages: int = 40) -> list[dict]:
    """Keep system prompt + last N messages, summarizing old context."""
    if len(messages) <= max_messages:
        return messages
    system = [m for m in messages if m["role"] == "system"]
    recent = messages[-max_messages:]
    return system + recent
```

**Current State**: No conversation pruning logic found in `agent.py`.

**Impact**: Long sessions may hit context limits and fail.

**Fix Required**: Implement in `neudev/agent.py`.

---

#### 2.2 Self-Correction on Tool Errors ❌

**Status**: ❌ **NOT IMPLEMENTED**

**Proposed**:
```python
def _should_suggest_alternative(self, tool_name: str, consecutive_failures: int) -> str | None:
    if consecutive_failures >= 2:
        alternatives = {
            "edit_file": "Try smart_edit_file or write_file",
            "grep_search": "Try symbol_search or search_files",
            "run_command": "Check if command exists with 'which' first",
        }
        return alternatives.get(tool_name)
    return None
```

**Current State**: No consecutive failure tracking or alternative suggestions.

**Impact**: Agent repeats failing strategies instead of adapting.

**Fix Required**: Implement in `neudev/agent.py`.

---

#### 2.3 Dynamic Tool Selection Guidance ❌

**Status**: ❌ **NOT IMPLEMENTED**

**Proposed**:
```python
# For debugging tasks, prioritize: grep_search -> read_file -> diagnostics -> edit_file
# For coding tasks, prioritize: list_directory -> read_file -> write_file -> run_command
```

**Current State**: No task-based tool prioritization.

**Impact**: Agent may use suboptimal tool sequences.

**Fix Required**: Implement in `neudev/agent.py` system prompt.

---

#### 2.4 Response Streaming ⚠️

**Status**: ⚠️ **PARTIALLY IMPLEMENTED**

**Location**: `neudev/llm.py:220-275`

**Implemented**:
```python
def chat(self, messages, tools=None, stream=False, think=False, model_name=None):
    """
    If stream=True: Generator yielding response chunks
    """
    if stream:
        # ... streaming logic
        for line in response:
            if line.startswith("data:"):
                yield json.loads(line.decode("utf-8"))
```

**Missing**:
- Agent doesn't use streaming (`agent.py` calls `chat()` with `stream=False`)
- No incremental tool call parsing during streaming
- No real-time display integration

**Impact**: Users wait for full response instead of seeing real-time progress.

**Fix Required**: Update `agent.py` to use streaming and integrate with CLI.

---

## Summary Table

| Feature | Status | Location | Priority |
|---------|--------|----------|----------|
| **Advanced Tools** | | | |
| web_search | ✅ Implemented | `tools/web_search.py` | High |
| url_fetch | ✅ Implemented | `tools/url_fetch.py` | High |
| patch_file | ✅ Implemented | `tools/patch_file.py` | High |
| dependency_install | ✅ Implemented | `tools/dependency_install.py` | High |
| project_init | ✅ Implemented | `tools/project_init.py` | Medium |
| Tool registration | ✅ Implemented | `tools/__init__.py` | High |
| **Agent Intelligence** | | | |
| Conversation pruning | ❌ Missing | `agent.py` | **Critical** |
| Self-correction | ❌ Missing | `agent.py` | **High** |
| Dynamic tool selection | ❌ Missing | `agent.py` | Medium |
| Response streaming | ⚠️ Partial | `llm.py` + `agent.py` | High |

---

## Required Fixes

### Critical Priority

#### 1. Add Conversation Pruning

**File**: `neudev/agent.py`

```python
def _prune_conversation(self, messages: list[dict], max_messages: int = 40) -> list[dict]:
    """Keep system prompt + last N messages, summarizing old context."""
    if len(messages) <= max_messages:
        return messages

    # Keep system prompt
    system = [m for m in messages if m["role"] == "system"]

    # Keep last N messages
    recent = messages[-max_messages:]

    return system + recent
```

**Usage**: Call in `process_message()` before sending to LLM.

---

#### 2. Add Self-Correction on Tool Errors

**File**: `neudev/agent.py`

```python
@dataclass
class Agent:
    # ... existing fields ...
    _consecutive_failures: dict[str, int] = field(default_factory=dict)

    def _track_tool_failure(self, tool_name: str) -> None:
        """Track consecutive failures for a tool."""
        self._consecutive_failures[tool_name] = (
            self._consecutive_failures.get(tool_name, 0) + 1
        )

    def _reset_tool_failure(self, tool_name: str) -> None:
        """Reset failure count on success."""
        self._consecutive_failures.pop(tool_name, None)

    def _should_suggest_alternative(self, tool_name: str) -> str | None:
        """Suggest alternative tool after repeated failures."""
        failures = self._consecutive_failures.get(tool_name, 0)
        if failures >= 2:
            alternatives = {
                "edit_file": "Try smart_edit_file or write the entire file with write_file",
                "grep_search": "Try symbol_search or search_files instead",
                "run_command": "Check if the command exists with 'which' first",
                "read_file": "Try search_files to locate the correct file first",
            }
            return alternatives.get(tool_name)
        return None
```

---

#### 3. Add Dynamic Tool Selection Guidance

**File**: `neudev/agent.py` (SYSTEM_PROMPT)

Add to system prompt:

```python
SYSTEM_PROMPT = """
...

## Tool Selection Strategy
Choose tools based on your task type:

**For debugging tasks** (errors, bugs, issues):
1. grep_search - Find error messages in code
2. read_file - Examine relevant files
3. diagnostics - Run tests/lint to confirm issue
4. edit_file - Fix the problem
5. run_command - Verify the fix

**For coding tasks** (new features, implementations):
1. list_directory - Understand project structure
2. read_file - Review existing code
3. write_file - Create new files
4. run_command - Test your changes

**For refactoring tasks**:
1. symbol_search - Find all usages
2. read_files_batch - Review all affected files
3. patch_file - Apply structured changes
4. diagnostics - Verify nothing broke

**For research tasks**:
1. web_search - Find external information
2. url_fetch - Read documentation
3. read_file - Check existing implementations
"""
```

---

#### 4. Enable Response Streaming

**File**: `neudev/agent.py`

Update `process_message()` to use streaming:

```python
def process_message(
    self,
    user_message: str,
    on_status=None,
    on_text=None,  # New callback for streaming
    on_thinking=None,
    # ...
) -> str:
    # ... existing setup ...

    # Use streaming if callback provided
    use_streaming = on_text is not None

    for iteration in range(max_iterations):
        # ... existing logic ...

        # Stream response if enabled
        if use_streaming:
            response_stream = self.llm.chat(
                working_conversation,
                tools=tool_defs,
                stream=True,
                think=use_thinking,
                model_name=preferred_model,
            )

            full_response = ""
            for chunk in response_stream:
                if "message" in chunk:
                    content = chunk["message"].get("content", "")
                    if content:
                        full_response += content
                        on_text(content)  # Stream to UI

            # Parse tool calls from full response if needed
            tool_calls = self._parse_tool_calls(full_response)
        else:
            # Existing non-streaming logic
            response = self.llm.chat(...)
```

---

## Testing Plan

### Test Advanced Tools

```bash
# Test web_search
neu run --runtime local
# Ask: "Search for Python async best practices"

# Test url_fetch
# Ask: "Fetch content from https://docs.python.org/3/library/asyncio.html"

# Test patch_file
# Create a patch file and ask: "Apply this patch to neudev/agent.py"

# Test dependency_install
# Ask: "Install dependencies for this Python project"

# Test project_init
# Ask: "Create a new Python project called mylib"
```

### Test Agent Intelligence (After Implementation)

```bash
# Test conversation pruning
# Have a long conversation (50+ messages) and verify no context overflow

# Test self-correction
# Ask agent to edit a non-existent file twice
# Verify it suggests alternative after 2 failures

# Test streaming
# Ask a complex question and verify real-time response display
```

---

## Conclusion

**Advanced Tools**: ✅ **100% Complete** - All 5 tools implemented and registered.

**Agent Intelligence**: ❌ **0% Complete** - Critical features missing:
- Conversation pruning (risk of context overflow)
- Self-correction (repeats failing strategies)
- Dynamic tool selection (suboptimal tool usage)
- Response streaming (poor UX for long responses)

**Recommendation**: Implement agent intelligence features as **Critical Priority** to match the advanced tool capabilities.

---

**Verified By**: Automated Code Analysis  
**Verification Date**: 2026-03-07  
**Overall Status**: ⚠️ **PARTIAL - Tools Complete, Agent Intelligence Missing**
