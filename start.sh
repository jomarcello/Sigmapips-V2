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

# Force polling mode als je wilt testen zonder webhook
FORCE_POLLING=${FORCE_POLLING:-"true"}
EOL

echo "Starting FastAPI application..."
# Start de FastAPI applicatie
cd /app
uvicorn trading_bot.main:app --host 0.0.0.0 --port ${PORT:-8080} 
