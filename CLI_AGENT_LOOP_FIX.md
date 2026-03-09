# CLI Agent Loop Fix - Website Creation Issue

## Problem Summary

The NeuDev CLI agent was stuck in an infinite loop when users requested website creation. The agent would:
1. Call `project_init` tool successfully (files were created)
2. Immediately call `project_init` again with the same parameters
3. Repeat this 11+ times until hitting the maximum iteration limit (20)
4. Fail with "Reached maximum iterations. The task may be incomplete."

### Example from Trace
```
TOOL    DONE . Scaffolded 'html' project: Travel GO | 4.0s
...
Auto-approved: project_init
    TOOL    START Using project_init started 12:34:06 AM
    TOOL    DONE project_init Scaffolded 'html' project: Travel GO | 0.0s
(repeated 11 times)
```

### Additional Issues Found
1. **Wrong Model Selection**: Only using `qwen2.5-coder:7b`, not using `deepseek-coder-v2:16b` (better coding model)
2. **Path Hallucination**: Executor using placeholder paths like `path/to/your/file` from tool descriptions
3. **edit_file Misuse**: Missing parameters, wrong file paths, TypeError errors
4. **write_file Not Using overwrite=true**: Can't update existing files after scaffolding
5. **Planner TODOs Still Vague**: "Scaffold HTML/CSS/JS structure" is still somewhat tool-focused

## Root Cause Analysis

### 1. Planner Creating Tool-Specific TODO Items
The planner was creating TODO items like:
- ❌ "Run project_init with project name 'Travel GO' to scaffold HTML/CSS/JS files"

This is a **tool instruction**, not a **task outcome**. After the tool ran, the executor (a weaker model `qwen2.5-coder:7b`) didn't understand that:
- The task was complete (scaffolding done)
- It should move on to customizing the files
- It should NOT call `project_init` again

### 2. No Loop Detection
The agent had no mechanism to detect when the same tool was being called repeatedly with identical arguments.

### 3. Insufficient Feedback from project_init
When `project_init` ran a second time, it would skip existing files but the output message didn't clearly tell the executor:
- "Files already exist - do NOT call this tool again"
- "Use write_file or edit_file to customize instead"

### 4. Model Routing Not Optimal
- `qwen2.5-coder:7b` was being selected for all coding tasks
- `deepseek-coder-v2:16b` (coding score 9.9) has better multi-file coordination ability
- Website creation needs strong coding ability but wasn't being routed to best model

### 5. Path Hallucination
- Executor model was using placeholder paths from tool descriptions (`path/to/your/file`)
- No explicit warning in system prompt against using example paths
- Weaker model (`qwen2.5-coder:7b`) more prone to hallucination

## Fixes Applied

### Fix 1: Updated Planner Instructions (`neudev/agent.py`)

**Location:** Lines 1449-1472 in `_run_planner()` method

**Changes:**
- Added rules 13-15 to the "CRITICAL RULES TO PREVENT HALLUCINATION" section
- Explicitly forbids TODO items that mention tool names
- Requires TODO items to describe USER-VISIBLE outcomes, not tool calls
- Provides clear examples of WRONG vs CORRECT TODO items

**Before:**
```
TODO: "Run project_init with template=html and name=Travel GO"
```

**After:**
```
TODO: 
- "Scaffold HTML/CSS/JS website structure for Travel GO"
- "Create index.html with Travel GO branding, navigation, and hero section"
- "Style css/style.css with modern travel website theme"
- "Add interactive features to js/script.js"
```

### Fix 2: Enhanced project_init Tool Feedback (`neudev/tools/project_init.py`)

**Location:** Lines 208-220 in `execute()` method

**Changes:**
- When all files already exist, the tool now returns detailed guidance:
  - "IMPORTANT: The project structure already exists. Do NOT call project_init again."
  - "Next steps: Use write_file or edit_file to customize the existing files"
  - Lists specific files to edit (index.html, css/style.css, js/script.js)

**Before:**
```
All files already exist — nothing was created.
```

**After:**
```
All files already exist — nothing was created.

IMPORTANT: The project structure already exists. Do NOT call project_init again.
Next steps: Use write_file or edit_file to customize the existing files:
  - Edit index.html to customize the HTML content for 'Travel GO'
  - Edit css/style.css to customize the styling for 'Travel GO'
  - Edit js/script.js to add custom JavaScript for 'Travel GO'
```

### Fix 3: Updated project_init Tool Description (`neudev/tools/project_init.py`)

**Location:** Lines 98-108 in `description` property

**Changes:**
- Added explicit warnings in the tool description:
  - "USE THIS TOOL ONLY ONCE at the start of a new project"
  - "After scaffolding, use write_file or edit_file to customize the created files"
  - "DO NOT call this tool multiple times for the same project"

This helps the executor model understand the tool's intended usage pattern.

### Fix 4: Added Loop Detection Mechanism (`neudev/agent.py`)

**Location:** 
- Lines 224-227: Added tracking fields in `__init__()`
- Lines 373-409: Added `_check_tool_loop()` and `_clear_loop_detection()` methods
- Lines 965-983: Integrated loop detection into executor loop
- Lines 566-568: Clear loop detection after successful turn completion

**How it works:**
1. Tracks recent tool calls as `(tool_name, args_hash)` tuples
2. Maintains a sliding window of recent calls
3. Detects when the same tool+args is called 3+ times consecutively
4. When a loop is detected:
   - Injects a system message explaining the loop
   - Tells the model to check if the tool already succeeded
   - Suggests using write_file/edit_file instead
   - Clears the loop detection to allow progress

**Code Example:**
```python
def _check_tool_loop(self, tool_name: str, tool_args: dict) -> bool:
    """Check if the same tool is being called repeatedly with same args."""
    args_hash = hashlib.md5(str(sorted(tool_args.items())).encode()).hexdigest()
    call_signature = (tool_name, args_hash)
    
    self._recent_tool_calls.append(call_signature)
    
    # Check if same call made 3 times in a row
    if len(self._recent_tool_calls) >= 3:
        recent = self._recent_tool_calls[-3:]
        if all(call == call_signature for call in recent):
            return True  # Loop detected
    return False
```

### Fix 5: Added User Content Reminder (`neudev/agent.py`)

**Location:** Lines 1479-1481 in `_run_planner()` method

**Changes:**
- Added explicit reminder in the user content section:
  - "CRITICAL: TODO items must describe OUTCOMES (what to build), not TOOL CALLS (how to build)."
  - "Example: Write 'Create index.html with Travel GO branding' NOT 'Run project_init'."

### Fix 6: Improved Model Routing for Website Creation (`neudev/model_routing.py`)

**Location:**
- Lines 254-267: Added `WEBSITE_KEYWORDS` set for website task detection
- Lines 408-495: Updated `_classify_task()` to detect website creation tasks
- Lines 547-570: Added `website_creation` task type to preference order
- Lines 581-595: Added `website_creation` trait weights (coding=2.0, reasoning=0.9, tool_use=0.9)

**Changes:**
- Added new `website_creation` task type with high scoring for website-related keywords
- Website tasks now route to `deepseek-coder-v2:16b` (coding score 9.9) instead of `qwen2.5-coder:7b` (coding score 9.6)
- Position-weighted scoring: website keywords in first 5 words get 1.5x multiplier
- Phrase boosting: 2+ website keyword hits add +5.0 to score

**Model Preference Order for website_creation:**
1. `deepseek-coder-v2:16b` - Best for complex multi-file coding
2. `qwen2.5-coder:7b` - Strong coding alternative
3. `qwen3:latest` - Good generalist with tool use
4. `deepseek-coder:6.7b` - Debugging specialist
5. `starcoder2:7b` - Quick edits
6. `codellama:7b` - Legacy fallback

### Fix 7: System Prompt Updates to Prevent Path Hallucination (`neudev/agent.py`)

**Location:**
- Lines 75-94: Updated website creation tool selection strategy
- Lines 145-155: Added critical rules about path hallucination

**Changes:**
- Added explicit warning: "Call project_init ONLY ONCE - it creates the same files each time"
- Added write_file guidance: "use write_file(path='index.html', content=FULL_CONTENT, overwrite=true)"
- Added CRITICAL warnings:
  - "Use actual file paths like 'index.html', 'css/style.css', 'js/script.js'"
  - "NEVER use placeholder paths like 'path/to/your/file' or 'your-file.html'"
  - "When using edit_file or write_file, ALWAYS use real file paths from the workspace"
- Added rules:
  - "NEVER use placeholder or example paths from tool descriptions"
  - "ALWAYS use real file paths that exist in the workspace or that you intend to create"
  - "If you see 'path/to/...' in your thoughts, STOP - that's an example path, not a real file"

### Fix 8: Updated Test Expectations (`tests/test_model_routing.py`)

**Location:** Multiple test methods

**Changes:**
- Updated tests to expect `deepseek-coder-v2:16b` for coding tasks (was `qwen2.5-coder:7b`)
- Tests now verify improved model routing for:
  - Plain code generation
  - React/TypeScript implementation
  - Analysis + implementation tasks
  - Agent team executor selection

## Testing

All existing tests pass:
```
====================== 128 passed, 10 skipped in 20.67s =======================
```

No regressions introduced.

## Expected Behavior After Fix

When a user requests: "please create a single page website using HTML,CSS and JS. this website name is 'Travel GO'"

**Expected Flow:**
1. **Planner creates TODO list:**
   - "Scaffold HTML/CSS/JS website structure for Travel GO"
   - "Create index.html with Travel GO branding, navigation, and hero section"
   - "Style css/style.css with modern travel website theme"
   - "Add interactive features to js/script.js"

2. **Executor runs project_init ONCE** → Creates files

3. **Executor moves to next TODO** → Uses write_file to customize index.html

4. **Executor continues** → Customizes css/style.css and js/script.js

5. **Task completes successfully** without hitting iteration limit

**If project_init is called again accidentally:**
- Tool output clearly states "Do NOT call project_init again"
- Loop detection triggers after 3 identical calls
- System message injected: "Loop Detected... use write_file or edit_file instead"
- Executor course-corrects and uses appropriate tools

## Files Modified

1. `neudev/agent.py` - Planner instructions, loop detection, executor loop, system prompt
2. `neudev/tools/project_init.py` - Enhanced feedback, updated description
3. `neudev/model_routing.py` - Website task detection, model preference order, trait weights
4. `tests/test_model_routing.py` - Updated test expectations for new model routing
5. `CLI_AGENT_LOOP_FIX.md` - Comprehensive documentation of the issue and fixes

## Future Improvements

1. **Visual progress indicator** - Show file creation status in real-time
2. **Template customization** - Allow users to specify theme/colors in project_init
3. **Post-scaffold preview** - Automatically open created website in browser
4. **Model fallback on error** - Switch to stronger model if executor fails repeatedly

## Related Issues

This fix addresses the core issues where:
- AI agent creates folders and files but doesn't complete the website
- Agent gets stuck in tool call loops (project_init called 11+ times)
- Maximum iterations reached without task completion
- Wrong model selection (qwen2.5-coder:7b instead of deepseek-coder-v2:16b)
- Path hallucination (using 'path/to/your/file' from tool descriptions)
- edit_file misuse (missing parameters, wrong paths)
- write_file not using overwrite=true for existing files

The fix makes the agent more robust by:
- Better planning (outcome-based TODOs, not tool instructions)
- Better feedback (clear "don't call again" messages from project_init)
- Loop detection (automatic course correction after 3 repeated calls)
- Better tool descriptions (usage guidelines in tool definition)
- Better model routing (deepseek-coder-v2:16b for complex coding tasks)
- Path hallucination prevention (explicit warnings in system prompt)
- Website task detection (special handling for multi-file website creation)
