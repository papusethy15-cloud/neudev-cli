#!/bin/bash
# NeuDev Deployment Script - Lightning Studio
# This script commits changes and provides deployment instructions

set -e

echo "=========================================="
echo "  ⚡ NeuDev Deployment to Lightning Studio"
echo "=========================================="
echo ""

# Step 1: Git Commit & Push
echo "📦 Step 1: Committing changes to git..."
echo ""

git add -A
git status

echo ""
read -p "Enter commit message (or press Enter for default): " commit_message
if [ -z "$commit_message" ]; then
    commit_message="feat: Add advanced agent intelligence and new tools

- Implement conversation pruning to prevent context overflow
- Add self-correction on tool errors with alternative suggestions
- Add dynamic tool selection guidance in system prompt
- Implement find_replace tool for multi-location text replacement
- Enhance write_file with explicit override mode
- Update model routing with VRAM-aware scoring
- Enhance CLI UI with descriptive status and permission countdown
- Total: 27 tools available

Version: 2.2.0"
fi

git commit -m "$commit_message"
git push origin main

echo ""
echo "✅ Code pushed to GitHub!"
echo ""

# Step 2: Lightning Studio Instructions
echo "=========================================="
echo "  🌩️  Lightning Studio Deployment"
echo "=========================================="
echo ""
echo "📋 Follow these steps on your Lightning Studio:"
echo ""
echo "1. SSH into your Lightning Studio or open terminal"
echo ""
echo "2. Navigate to NeuDev directory:"
echo "   cd ~/neudev-cli  # or your NeuDev path"
echo ""
echo "3. Pull latest changes:"
echo "   git pull origin main"
echo ""
echo "4. Install dependencies:"
echo "   python -m pip install -e ."
echo ""
echo "5. Verify Ollama is running:"
echo "   ollama serve &"
echo "   ollama list"
echo ""
echo "6. Start the hosted server:"
echo "   export NEUDEV_API_KEY=\"your-secret-key-here\""
echo "   neu serve \\"
echo "     --host 0.0.0.0 \\"
echo "     --port 8765 \\"
echo "     --ws-port 8766 \\"
echo "     --workspace \"\$PWD\" \\"
echo "     --api-key \"\$NEUDEV_API_KEY\" \\"
echo "     --session-store \"\$HOME/.neudev/hosted_sessions\" \\"
echo "     --ollama-host http://127.0.0.1:11434 \\"
echo "     --model auto \\"
echo "     --agents parallel"
echo ""
echo "7. Note the server URL (use cloudflare tunnel if needed):"
echo "   bash scripts/lightning_quick_tunnel.sh"
echo ""
echo "=========================================="
echo "  💻 Local Testing (Hybrid Mode)"
echo "=========================================="
echo ""
echo "On your LOCAL machine (Windows/Mac/Linux):"
echo ""
echo "1. Install/update the CLI:"
echo "   cd C:\\WorkSpace\\neu-dev"
echo "   python -m pip install -e ."
echo ""
echo "2. Configure for hybrid mode:"
echo "   neu auth login --runtime hybrid \\"
echo "     --api-base-url https://YOUR-LIGHTNING-URL \\"
echo "     --api-key your-secret-key-here"
echo ""
echo "3. Test the enhanced AI:"
echo "   neu run --runtime hybrid --workspace ."
echo ""
echo "4. Try these test commands:"
echo "   - 'Create a single page website using modern design'"
echo "   - 'Fix the ImportError in neudev/agent.py'"
echo "   - 'Rename all old_function to new_function in *.py'"
echo "   - 'Search for Python async best practices'"
echo ""
echo "=========================================="
echo "  ✨ New Features to Test"
echo "=========================================="
echo ""
echo "1. Conversation Pruning:"
echo "   Have a 50+ message conversation - no overflow!"
echo ""
echo "2. Self-Correction:"
echo "   Ask to edit a non-existent file twice"
echo "   Agent will suggest alternatives after 2 failures"
echo ""
echo "3. New Tools:"
echo "   - find_replace: Multi-location text replacement"
echo "   - write_file (enhanced): Explicit override mode"
echo ""
echo "4. Enhanced UI:"
echo "   - Descriptive live status panel"
echo "   - Permission prompt with countdown timer"
echo "   - Workspace-relative paths"
echo "   - Diff preview in turn summary"
echo ""
echo "=========================================="
echo "  🎯 Verification Commands"
echo "=========================================="
echo ""
echo "Test model routing:"
echo "  python -c \"from neudev.model_routing import rank_models; print('Model routing OK')\""
echo ""
echo "Test new tools:"
echo "  python -c \"from neudev.tools import create_tool_registry; r = create_tool_registry(); print(f'Tools available: {len(r.get_all())}')\""
echo ""
echo "Test agent intelligence:"
echo "  python -c \"from neudev.agent import Agent; from neudev.config import NeuDevConfig; a = Agent(NeuDevConfig(), '.'); print('Agent intelligence OK')\""
echo ""
echo "=========================================="
echo "  🎉 Deployment Complete!"
echo "=========================================="
echo ""
