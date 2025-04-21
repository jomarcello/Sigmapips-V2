#!/bin/bash
set -e

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
echo "Step 4: Fixing syntax error in health_check function"

# First use Python to fix health_check function (previously in fix_health_check.py)
python3 - << 'EOF'
import os
import re
import sys
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_health_check_function(file_path):
    """Fix the health_check function in main.py"""
    logger.info(f"Checking file: {file_path}")
    
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return False
    
    # Read the file content
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Create a backup
    backup_path = f"{file_path}.bak"
    with open(backup_path, 'w', encoding='utf-8') as file:
        file.write(content)
    
    # Pattern to find return statement with import on same line
    pattern = r'(return\s*{"status":\s*"healthy",\s*"timestamp":\s*time\.time\(\)})(.+)'
    
    # Check if the pattern exists
    match = re.search(pattern, content)
    if match:
        # Replace with just the return statement
        fixed_content = re.sub(pattern, r'\1', content)
        logger.info(f"Found and fixed syntax error in health_check function")
        
        # Write the fixed content back
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(fixed_content)
        
        return True
    else:
        logger.info("No syntax error found in health_check function")
        return False

# Fix the health_check function
success = fix_health_check_function("/app/trading_bot/main.py")
EOF

# Then use bash to check/fix the issue as a fallback
echo "Bash fallback check for syntax error in main.py health_check function"
if grep -q 'return.*time\.time().*import' /app/trading_bot/main.py; then
    echo "Found syntax error in health_check function - fixing with sed"
    # Replace the problematic line with the correct one
    sed -i 's/\(return {"status": "healthy", "timestamp": time\.time()}\)import.*/\1/g' /app/trading_bot/main.py
    echo "Fixed syntax error in health_check function"
else
    echo "No syntax error found in health_check function with bash grep"
fi

echo ""
echo "Step 5: Making health_check function safe"
echo "Making health_check function safe"
# Find the line with the health_check return statement
line_num=$(grep -n 'return {"status": "healthy", "timestamp": time\.time()}' /app/trading_bot/main.py | cut -d':' -f1)
if [ -n "$line_num" ]; then
    # Make sure there's a blank line after it
    next_line=$((line_num + 1))
    if [ -n "$(sed -n "${next_line}p" /app/trading_bot/main.py)" ]; then
        # Insert a blank line after
        sed -i "${line_num}a\\" /app/trading_bot/main.py
        echo "Added blank line after health_check return statement"
    fi
fi

# Final direct fix attempt for the specific error
sed -i 's/return {"status": "healthy", "timestamp": time.time()}import logging/return {"status": "healthy", "timestamp": time.time()}/g' /app/trading_bot/main.py

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
