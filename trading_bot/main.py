#!/usr/bin/env python3
import logging
import os
import sys
import asyncio
import time

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Track startup time
startup_start_time = time.time()
logger.info("Starting SigmaPips Trading Bot...")

# Add the current directory to the path so we can import from trading_bot
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    # Import the proper bot class
    import_start_time = time.time()
    from trading_bot.services.telegram_service.bot import TelegramService
    from trading_bot.services.database.db import Database
    from trading_bot.services.payment_service.stripe_service import StripeService
    
    import_time = time.time() - import_start_time
    logger.info(f"Imports successful in {import_time:.2f} seconds")
    
    # Create a function to run the bot
    async def main():
        initialization_start_time = time.time()
        logger.info("Initializing services...")
            
        # Initialize database
        db_start_time = time.time()
        db = Database()
        db_time = time.time() - db_start_time
        logger.info(f"Database initialized in {db_time:.2f} seconds")
        
        # Initialize Stripe service
        stripe_start_time = time.time()
        stripe_service = StripeService(db)
        stripe_time = time.time() - stripe_start_time
        logger.info(f"Stripe service initialized in {stripe_time:.2f} seconds")
        
        # Initialize Telegram service with database and Stripe service
        # Enable lazy initialization to defer heavy service loading
        telegram_start_time = time.time()
        telegram_service = TelegramService(db, stripe_service, lazy_init=True)
        telegram_time = time.time() - telegram_start_time
        logger.info(f"Telegram service initialized with lazy loading in {telegram_time:.2f} seconds")
        
        # Start the bot immediately without initializing services
        # Services will be initialized on first use
        bot_start_time = time.time()
        await telegram_service.run()
        bot_time = time.time() - bot_start_time
        logger.info(f"Bot started successfully in {bot_time:.2f} seconds")
        
        # Calculate total initialization time
        total_init_time = time.time() - initialization_start_time
        logger.info(f"Total services initialization time: {total_init_time:.2f} seconds")
        
        # Total startup time
        total_startup_time = time.time() - startup_start_time
        logger.info(f"TOTAL STARTUP TIME: {total_startup_time:.2f} seconds")
        
        # Log performance metrics to a file for tracking
        try:
            with open("startup_performance_new.txt", "a") as f:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"{timestamp} - Startup time: {total_startup_time:.2f}s (Imports: {import_time:.2f}s, " +
                        f"DB: {db_time:.2f}s, Stripe: {stripe_time:.2f}s, " + 
                        f"Telegram: {telegram_time:.2f}s, Bot: {bot_time:.2f}s)\n")
        except Exception as e:
            logger.error(f"Error writing performance metrics: {str(e)}")
        
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
