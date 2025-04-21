from fastapi import FastAPI
import asyncio
import logging
import os
import sys

# Add the current directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Create a FastAPI app - don't try to import from trading_bot.main
app = FastAPI()

logger = logging.getLogger(__name__)

# Basic health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for Railway's healthcheck."""
    return {"status": "ok", "message": "Bot is running"}

# Import the bot and run it
@app.on_event("startup")
async def startup_event():
    """Start the bot when the FastAPI app starts."""
    try:
        # Direct implementation to start the bot without importing main
        logger.info("Starting bot directly within asgi.py")
        
        # Import required modules
        from trading_bot.services.telegram_service.bot import TelegramService
        from trading_bot.services.database.db import Database
        from trading_bot.services.payment_service.stripe_service import StripeService
        
        # Create and start services
        async def start_bot():
            # Initialize database
            db = Database()
            logger.info("Database initialized")
            
            # Initialize Stripe service
            stripe_service = StripeService(db)
            logger.info("Stripe service initialized")
            
            # Initialize Telegram service with database and Stripe service
            telegram_service = TelegramService(db, stripe_service, lazy_init=True)
            logger.info("Telegram service initialized")
            
            # Start the bot
            await telegram_service.run()
            logger.info("Bot started successfully")
            
            # Keep the task running
            while True:
                await asyncio.sleep(60)
        
        # Start in background
        asyncio.create_task(start_bot())
        logger.info("Bot startup task created")
        
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        logger.exception(e) 
