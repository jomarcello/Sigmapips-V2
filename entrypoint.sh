#!/bin/bash
set -e

# Maximum number of attempts to fix the file
MAX_ATTEMPTS=3

echo "Running syntax error fixers..."

# Run our comprehensive fix_all_issues.sh script first
echo "Running comprehensive fix_all_issues.sh script..."
bash /app/fix_all_issues.sh

# Run our specific fix_health_check.py script
echo "Running specific fix_health_check.py script for health_check function..."
python3 /app/fix_health_check.py /app/trading_bot/main.py

# Then try the specific health_check fix script
echo "Attempt 1: Running fix_syntax_error.py for specific health_check function..."
python3 /app/fix_syntax_error.py /app/trading_bot/main.py

# Then run the more general fix_deployment.py as a backup
echo "Attempt 2: Running fix_deployment.py for general fixes..."
python3 /app/fix_deployment.py /app/trading_bot/main.py

# As a last resort, try a direct sed command to fix the exact error
echo "Attempt 3: Using direct sed command to fix the specific error..."
sed -i 's/return {"status": "healthy", "timestamp": time.time()}import logging/return {"status": "healthy", "timestamp": time.time()}/g' /app/trading_bot/main.py

echo "All fix attempts completed. Proceeding with application startup."

# Start the application
echo "Starting the application..."
exec "$@" 
