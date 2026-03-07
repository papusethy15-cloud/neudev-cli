#!/bin/bash
# Quick fix deployment script

cd C:/WorkSpace/neu-dev

echo "Fixing bugs..."

# Add fixed files
git add neudev/cli.py
git add neudev/observability.py
git add tests/test_cli.py

# Commit fixes
git commit -m "fix: Fix TypeError in build_trace_summary_lines and defer OpenTelemetry imports

- Fix workspace_delta_counts type error (dict not list)
- Defer OpenTelemetry imports to avoid AttributeError
- Update tests to match new output format
- Fix permission panel test for Live panel implementation"

# Push
git push origin main

echo "✅ Fixes pushed!"
echo ""
echo "Now on Lightning Studio:"
echo "  cd ~/neudev-cli"
echo "  git pull origin main"
echo "  bash scripts/lightning_entrypoint.sh"
