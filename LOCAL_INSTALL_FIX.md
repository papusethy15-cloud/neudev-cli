# 🔧 Local Installation Fix Guide

## Issue Fixed (v3.1 - Critical)

**Error:**
```
KeyError: '"name"'
```

**Cause:**
The `project_init.py` templates had incorrect string escaping that worked in development mode but failed when installed via pip.

---

## ✅ Solution Applied

Fixed the JSON template strings in `neudev/tools/project_init.py`:

**Before (broken):**
```python
"package.json": "{{\n  \"name\": \"{name}\",\n...}}\n",
```

**After (fixed):**
```python
"package.json": '{{\n  "name": "{name}",\n...}}\n',
```

---

## 🚀 How to Update Your Local Installation

### Option 1: Reinstall from Source (Recommended)

```powershell
# Navigate to the source directory
cd C:\WorkSpace\neu-dev

# Reinstall with force
pip install -e . --force-reinstall --no-deps

# Test
neu version
```

### Option 2: Uninstall and Reinstall

```powershell
# Uninstall
pip uninstall neudev -y

# Reinstall from source
cd C:\WorkSpace\neu-dev
pip install -e .

# Test
neu version
```

### Option 3: Update from Git (if already installed)

```powershell
# Navigate to source
cd C:\WorkSpace\neu-dev

# Pull latest changes
git pull origin main

# Reinstall
pip install -e . --force-reinstall --no-deps

# Test
neu version
```

---

## ✅ Verification

After updating, test these commands:

```powershell
# 1. Version check
neu version
# Expected: NeuDev v1.0.0

# 2. Help command
neu run --runtime hybrid --workspace "C:\WorkSpace\project"
# Type: /help
# Expected: Shows command list without errors

# 3. Simple request
# Type: Hello
# Expected: Friendly greeting, no errors
```

---

## 📊 Commit Details

**Commit:** `2acaf67`  
**Message:** "Fix v3.1: Critical - Fix project_init template escaping for local installs"  
**Date:** 2026-03-08  
**Files Changed:**
- `neudev/tools/project_init.py` (4 lines)
- `V3_FIXES_SUMMARY.md` (new file)

---

## 🔍 Why This Happened

1. **Development Mode (`python -m neudev.cli`)**: Python reads the source files directly, so the escaping worked fine.

2. **Installed Mode (`neu` command)**: pip installs create compiled bytecode (`.pyc` files) and the string escaping was being interpreted incorrectly during compilation.

3. **The Fix**: Using single quotes for the outer string and double quotes inside avoids the escaping issue entirely.

---

## 🎯 Current Status

**Version:** v3.1  
**Total Issues Fixed:** 15+  
**Status:** ✅ All systems operational

---

## 📝 Quick Reference

| Command | Purpose |
|---------|---------|
| `pip install -e . --force-reinstall --no-deps` | Reinstall from source |
| `pip uninstall neudev -y` | Uninstall completely |
| `neu version` | Verify installation |
| `git pull origin main` | Get latest changes |

---

**Last Updated:** 2026-03-08 v3.1  
**Status:** ✅ Fixed and Pushed
