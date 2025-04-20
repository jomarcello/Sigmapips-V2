#!/bin/bash

echo "Starting SigmaPips Trading Bot..."
cd /app
echo "Starting main application..."

# Detecteer de hostname en maak een volledige URL
HOSTNAME=$(hostname -f 2>/dev/null || echo "localhost")
PUBLIC_URL=${PUBLIC_URL:-"https://$HOSTNAME"}

# Maak .env bestand aan
echo "Creating .env file..."
cat > .env << EOL
# Telegram Bot configuratie
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-"YOUR_TELEGRAM_BOT_TOKEN"}

# Webhook configuratie
WEBHOOK_URL=${WEBHOOK_URL:-"$PUBLIC_URL/webhook"}
WEBHOOK_PATH=${WEBHOOK_PATH:-"/webhook"}
PORT=${PORT:-8080}

# Force polling mode als je wilt testen zonder webhook (standaard uit voor Railway)
FORCE_POLLING=${FORCE_POLLING:-"false"}
EOL

# Check and install essential missing packages
echo "Checking for essential packages..."
python -c "import tavily" 2>/dev/null || {
    echo "Installing missing tavily package..."
    pip install tavily-python
}

# Check if we're using the old structure (trading_bot/main.py) or new structure (main.py in root)
if [ -f "trading_bot/main.py" ]; then
    echo "Found main.py in trading_bot directory"
    # Run with a timeout to prevent getting stuck
    timeout ${TIMEOUT_SECONDS:-180} python -m trading_bot.main || {
        echo "Application timed out after ${TIMEOUT_SECONDS:-180} seconds, restarting..."
        python -m trading_bot.main
    }
elif [ -f "main.py" ]; then
    echo "Found main.py in root directory"
    # Run with a timeout to prevent getting stuck
    timeout ${TIMEOUT_SECONDS:-180} python main.py || {
        echo "Application timed out after ${TIMEOUT_SECONDS:-180} seconds, restarting..."
        python main.py
    }
else
    echo "main.py not found in either location, falling back to trading_bot.main module"
    # Fall back to the module-based import
    timeout ${TIMEOUT_SECONDS:-180} python -m trading_bot.main || {
        echo "Application timed out after ${TIMEOUT_SECONDS:-180} seconds, restarting..."
        python -m trading_bot.main
    }
fi
