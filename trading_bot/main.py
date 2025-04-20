#!/usr/bin/env python3
import logging
import os
import sys
import asyncio

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Starting SigmaPips Trading Bot...")

# Add the current directory to the path so we can import from trading_bot
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    # Import the proper bot class
    from trading_bot.services.telegram_service.bot import TelegramService
    from trading_bot.services.database.db import Database
    from trading_bot.services.payment_service.stripe_service import StripeService
    
    logger.info("Imports successful")
    
    # Create a function to run the bot
    async def main():
        logger.info("Initializing services...")
        
        # Initialize database
        db = Database()
        logger.info("Database initialized")
        
        # Initialize Stripe service
        stripe_service = StripeService(db)
        logger.info("Stripe service initialized")
        
        # Initialize Telegram service with database and Stripe service
        telegram_service = TelegramService(db, stripe_service)
        logger.info("Telegram service initialized")
        
        # Initialize services
        await telegram_service.initialize_services()
        logger.info("Services initialized")
        
        # Start the bot
        await telegram_service.run()
        logger.info("Bot started successfully")
        
        # Keep the script running
        while True:
            await asyncio.sleep(60)
    
    # Run the main function
    if __name__ == "__main__":
        logger.info("Starting main application...")
        asyncio.run(main())
        
except ImportError as e:
    logger.error(f"Import error: {e}")
    raise

except Exception as e:
    logger.error(f"Error starting the bot: {e}")
    raise 
