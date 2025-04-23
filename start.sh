#!/bin/bash
echo "Starting SigmaPips Trading Bot with Health Check Server..."

# Start the virtual display for browser automation
Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 &
export DISPLAY=:99

# Set correct directory
cd /app

# Create main application to run 
cat > railway_server.py << 'EOF'
#!/usr/bin/env python3
"""
Entry point for Railway deployment that combines bot and API server
"""

import os
import sys
import logging
import asyncio
import time
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add the current directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Create FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for Railway"""
    return {"status": "ok"}

# Global variable for bot
bot_task = None
bot_running = False

# Import bot module after FastAPI setup
try:
    from trading_bot.services.telegram_service.bot import TelegramService
    from trading_bot.services.database.db import Database
    from trading_bot.services.payment_service.stripe_service import StripeService
    logger.info("Bot modules imported successfully")
except Exception as e:
    logger.error(f"Error importing bot modules: {e}")
    raise

# Function to start the bot
async def start_bot():
    """Start the bot in a background task"""
    global bot_running
    
    try:
        logger.info("Initializing bot...")
        
        # Initialize database
        db = Database()
        logger.info("Database initialized")
        
        # Initialize Stripe service
        stripe_service = StripeService(db)
        logger.info("Stripe service initialized")
        
        # Get bot token
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            logger.error("No bot token found")
            return
        
        # Initialize telegram service
        telegram_service = TelegramService(db, stripe_service, bot_token=bot_token)
        logger.info("Telegram service initialized")
        
        # Start the bot
        await telegram_service.run()
        bot_running = True
        
        # Keep the bot running
        while True:
            await asyncio.sleep(60)
    
    except Exception as e:
        logger.error(f"Error in bot task: {e}")
        bot_running = False

@app.on_event("startup")
async def startup_event():
    """Start the bot when the FastAPI app starts"""
    global bot_task
    
    # Start the bot in a background task
    bot_task = asyncio.create_task(start_bot())
    logger.info("Bot started in background task")

# Standard uvicorn entrypoint
if __name__ == "__main__":
    logger.info("Starting combined FastAPI and Bot server")
    uvicorn.run("railway_server:app", host="0.0.0.0", port=8000)
EOF

# Make the script executable
chmod +x railway_server.py

# Start the server
echo "Starting railway server..."
python railway_server.py
