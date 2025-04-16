#!/bin/bash

# Kill any existing Python processes running the bot
echo "Stopping existing bot processes..."
pkill -f "python.*bot.py"

# Wait a moment to ensure processes are stopped
sleep 2

# Double check no processes are left
if pgrep -f "python.*bot.py" > /dev/null; then
    echo "Force killing remaining processes..."
    pkill -9 -f "python.*bot.py"
    sleep 1
fi

echo "Cleanup complete" 