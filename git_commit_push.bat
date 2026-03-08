@echo off
cd /d C:\WorkSpace\neu-dev
echo ========================================
echo Git Status
echo ========================================
git status
echo.
echo ========================================
echo Git Diff (summary)
echo ========================================
git diff --stat
echo.
echo ========================================
echo Adding modified files
echo ========================================
git add neudev/agent.py neudev/tools/project_init.py neudev/tools/dependency_install.py neudev/tools/run_command.py ANALYSIS_AND_FIXES.md
echo.
echo ========================================
echo Committing changes
echo ========================================
git commit -m "Fix: Resolve 10 critical CLI issues - planner hallucination, PowerShell support, tool fixes

Major Fixes:
- project_init: Fixed JSON template parsing errors (ValueError with braces)
- dependency_install: Added helpful installation instructions for missing package managers
- run_command: Enhanced path validation, expanded command whitelist
- run_command: Added full PowerShell support for Windows with automatic Unix command fallbacks
- agent.py: Implemented anti-hallucination system with 8 critical rules for planner
- agent.py: Added 5 preflight reviewer checks to catch hallucinated tasks
- agent.py: Added _extract_user_request() to ground plans in explicit user requests

Issues Resolved:
1. project_init template ValueError - FIXED
2. dependency_install no guidance - FIXED  
3. run_command path validation - FIXED
4. Blocked basic commands - FIXED (added echo, curl, wget, powershell, etc.)
5. PowerShell support - FIXED (parsing, fallbacks, -Command flag)
6. Planner hallucination - FIXED (anti-hallucination prompts)
7. Preflight reviewer validation - FIXED (enhanced checks)
8. Session state clearing - VERIFIED
9. Tool result summaries - DOCUMENTED
10. Hybrid runtime restrictions - FIXED (expanded whitelist)

Testing:
- Windows PowerShell commands now work correctly
- Planner no longer creates tasks for non-existent directories
- Better error messages for missing dependencies
- Unix command fallbacks on Windows (ls -> Get-ChildItem, etc.)"

if %ERRORLEVEL% NEQ 0 (
    echo Commit failed. Please check for unstaged changes.
    exit /b %ERRORLEVEL%
)

echo.
echo ========================================
echo Pushing to remote
echo ========================================
git push

if %ERRORLEVEL% NEQ 0 (
    echo Push failed. Please check your remote connection.
    exit /b %ERRORLEVEL%
)

echo.
echo ========================================
echo SUCCESS: Changes committed and pushed!
echo ========================================
git log -1 --oneline
