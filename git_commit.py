#!/usr/bin/env python3
"""Git commit and push script for NeuDev fixes."""

import subprocess
import sys
from pathlib import Path

def run_command(cmd, cwd=None):
    """Run a shell command and return output."""
    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(
            cmd if isinstance(cmd, list) else cmd.split(),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
            
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        print(f"Error: {e}")
        return False, "", str(e)

def main():
    workspace = Path(r"C:\WorkSpace\neu-dev")
    
    if not workspace.exists():
        print(f"Workspace not found: {workspace}")
        return False
    
    print(f"\n📁 Working directory: {workspace}")
    
    # Step 1: Check git status
    print("\n📊 Checking git status...")
    success, stdout, stderr = run_command("git status", cwd=workspace)
    
    if not success:
        print("❌ Git status check failed. Is git installed?")
        return False
    
    # Step 2: Add files
    print("\n📝 Adding modified files...")
    files_to_add = [
        "neudev/agent.py",
        "neudev/tools/project_init.py",
        "neudev/tools/dependency_install.py",
        "neudev/tools/run_command.py",
        "ANALYSIS_AND_FIXES.md",
        "GIT_COMMIT_INSTRUCTIONS.md"
    ]
    
    add_cmd = ["git", "add"] + files_to_add
    success, stdout, stderr = run_command(add_cmd, cwd=workspace)
    
    if not success:
        print(f"⚠️  Some files may not exist or have changes: {stderr}")
    
    # Step 3: Commit
    print("\n💾 Committing changes...")
    commit_message = """Fix: Resolve 10 critical CLI issues - planner hallucination, PowerShell support, tool fixes

Major Fixes:
- project_init: Fixed JSON template parsing errors (ValueError with braces)
- dependency_install: Added helpful installation instructions for missing package managers
- run_command: Enhanced path validation, expanded command whitelist, PowerShell support
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
- Unix command fallbacks on Windows (ls -> Get-ChildItem, etc.)

BREAKING CHANGES: None
BACKWARD COMPATIBILITY: Maintained
"""
    
    commit_cmd = ["git", "commit", "-m", commit_message]
    success, stdout, stderr = run_command(commit_cmd, cwd=workspace)
    
    if not success:
        if "nothing to commit" in stderr.lower() or "nothing to commit" in stdout.lower():
            print("⚠️  No changes to commit - files may already be committed")
        else:
            print(f"❌ Commit failed: {stderr}")
            print("\n💡 Manual commit instructions:")
            print(f"   cd {workspace}")
            print(f"   git add {' '.join(files_to_add)}")
            print(f"   git commit -m \"Fix: Resolve critical CLI issues\"")
            return False
    
    # Step 4: Push
    print("\n🚀 Pushing to remote...")
    push_cmd = ["git", "push"]
    success, stdout, stderr = run_command(push_cmd, cwd=workspace)
    
    if not success:
        print(f"❌ Push failed: {stderr}")
        print("\n💡 Manual push instructions:")
        print(f"   cd {workspace}")
        print(f"   git push")
        return False
    
    # Step 5: Show last commit
    print("\n✅ SUCCESS! Last commit:")
    run_command("git log -1 --oneline", cwd=workspace)
    
    print("\n" + "="*60)
    print("🎉 All changes committed and pushed successfully!")
    print("="*60)
    
    print("\n📝 To update Google Colab:")
    print("   !cd /content && rm -rf neu-dev 2>/dev/null")
    print("   !cd /content && git clone https://github.com/YOUR_USERNAME/neudev-cli.git neu-dev")
    print("   !cd /content/neu-dev && pip install -e .")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
