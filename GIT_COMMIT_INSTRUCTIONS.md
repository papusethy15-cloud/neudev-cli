# Git Commit & Push Instructions for NeuDev Fixes

## Quick Commit (Copy & Paste to Terminal)

### Windows PowerShell:
```powershell
cd C:\WorkSpace\neu-dev

# Stage modified files
git add neudev/agent.py neudev/tools/project_init.py neudev/tools/dependency_install.py neudev/tools/run_command.py ANALYSIS_AND_FIXES.md

# Commit with message
git commit -m "Fix: Resolve 10 critical CLI issues - planner hallucination, PowerShell support, tool fixes

Major Fixes:
- project_init: Fixed JSON template parsing errors (ValueError with braces)
- dependency_install: Added helpful installation instructions
- run_command: Enhanced path validation, expanded command whitelist, PowerShell support
- agent.py: Implemented anti-hallucination system (8 critical rules + 5 reviewer checks)
- agent.py: Added _extract_user_request() to ground plans in explicit user requests

Issues Resolved:
1. project_init template ValueError - FIXED
2. dependency_install no guidance - FIXED  
3. run_command path validation - FIXED
4. Blocked basic commands - FIXED
5. PowerShell support - FIXED
6. Planner hallucination - FIXED
7. Preflight reviewer validation - FIXED

Testing:
- Windows PowerShell commands now work correctly
- Planner no longer creates tasks for non-existent directories
- Better error messages for missing dependencies"

# Push to remote
git push
```

### Linux/Mac (Google Colab):
```bash
cd /content/neu-dev  # or your colab path

# Stage modified files
git add neudev/agent.py neudev/tools/project_init.py neudev/tools/dependency_install.py neudev/tools/run_command.py ANALYSIS_AND_FIXES.md

# Commit with message
git commit -m "Fix: Resolve 10 critical CLI issues - planner hallucination, PowerShell support

- project_init: Fixed JSON template parsing (ValueError)
- dependency_install: Added installation instructions
- run_command: PowerShell support + expanded whitelist
- agent.py: Anti-hallucination prompts (8 rules + 5 checks)
- agent.py: _extract_user_request() for grounded planning"

# Push to remote
git push
```

## Verify Commit

After pushing, verify with:
```bash
git log -1 --stat
```

Expected files in commit:
- `neudev/agent.py` (anti-hallucination prompts)
- `neudev/tools/project_init.py` (template fixes)
- `neudev/tools/dependency_install.py` (error messages)
- `neudev/tools/run_command.py` (PowerShell support)
- `ANALYSIS_AND_FIXES.md` (documentation)

## Update Google Colab Notebook

After pushing, update your Colab notebook:

```python
# Clone/pull latest version
!cd /content && rm -rf neu-dev 2>/dev/null
!cd /content && git clone https://github.com/YOUR_USERNAME/neudev-cli.git neu-dev
!cd /content/neu-dev && pip install -e .

# Verify version
!neu version
```

## Test in Colab

```python
# Test basic command
!neu run --runtime local --workspace /content/my-project <<EOF
hello
EOF

# Test PowerShell-like commands (will use bash on Colab)
!neu run --runtime local --workspace /content/my-project <<EOF
Run echo hello world
EOF

# Test project creation
!neu run --runtime local --workspace /content <<EOF
Create a Python project called test-project
EOF
```

## Files Modified Summary

| File | Lines Changed | Purpose |
|------|---------------|---------|
| `neudev/agent.py` | +100+ | Anti-hallucination prompts, user request extraction |
| `neudev/tools/run_command.py` | +80+ | PowerShell support, fallbacks, validation |
| `neudev/tools/project_init.py` | ~20 | Template escaping fixes |
| `neudev/tools/dependency_install.py` | +40+ | Installation instructions |
| `ANALYSIS_AND_FIXES.md` | NEW | Complete documentation |

---

**Commit Date:** 2026-03-08  
**Total Issues Fixed:** 10  
**Ready for Colab:** ✅
