#!/bin/bash

echo "========================================"
echo "SigmaPips Trading Bot - Fix All Issues"
echo "========================================"

echo ""
echo "Step 1: Fixing sentiment service..."
python3 fix_sentiment_service.py

echo ""
echo "Step 2: Fixing bot imports..."
python3 fix_bot_imports.py

echo ""
echo "Step 3: Fixing register handlers method..."
python3 fix_register_handlers.py

echo ""
echo "All fixes applied!"
echo ""
echo "========================================"
echo "Instructions for running the bot:"
echo "========================================"
echo ""
echo "Option 1: Run with Docker"
echo "  ./rebuild_container.sh"
echo ""
echo "Option 2: Run locally"
echo "  python3 -m trading_bot.main"
echo ""
echo "========================================"
