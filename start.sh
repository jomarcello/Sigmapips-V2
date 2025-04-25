#!/bin/bash

# Set environment variables from .env file if it exists
if [ -f .env ]; then
    echo "Loading environment variables from .env file"
    export $(grep -v '^#' .env | xargs)
fi

# Stop any existing bot instances first
echo "Stopping any existing bot instances..."
python stop_existing_bots.py

# Sleep to allow Telegram API sessions to clear
echo "Waiting for Telegram API sessions to clear..."
sleep 5

# Start the bot in a clean environment
echo "Starting bot..."
python -m trading_bot.services.telegram_service.bot

# Keep the container running
tail -f /dev/null
