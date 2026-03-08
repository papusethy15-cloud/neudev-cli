#!/bin/bash
# Server Update Script for NeuDev CLI
# This script updates the server to the latest version from git

set -e

echo "=========================================="
echo "🔄 Updating NeuDev CLI Server"
echo "=========================================="

cd /root/neudev-cli

echo ""
echo "📥 Pulling latest changes from git..."
git pull origin main

echo ""
echo "🧹 Clearing Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

echo ""
echo "📦 Reinstalling package..."
pip install -e . --force-reinstall --no-deps -q

echo ""
echo "✅ Update complete!"
echo ""
echo "📊 Current version:"
git log -1 --oneline

echo ""
echo "🔄 Please restart the server now:"
echo "   nohup bash scripts/lightning_entrypoint.sh > server.log 2>&1 &"
echo ""
echo "=========================================="
