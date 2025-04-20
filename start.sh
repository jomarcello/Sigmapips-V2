#!/bin/bash

echo "Starting SigmaPips Trading Bot..."

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

echo "Starting main application..."

# Run with a timeout to prevent getting stuck
timeout ${TIMEOUT_SECONDS:-180} python main.py || {
    echo "Application timed out after ${TIMEOUT_SECONDS:-180} seconds, restarting..."
    python main.py
}
