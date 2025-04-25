#!/usr/bin/env python3
"""
Clean start script for the trading bot.
This script ensures proper cleanup before starting the bot.
"""

import os
import sys
import logging
import asyncio
import subprocess
from telegram import Bot
from telegram.error import TelegramError

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get bot token from environment or use the default one
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7328581013:AAFMGu8mz746nbj1eh6BuOp0erKl4Nb_-QQ")

async def cleanup_before_start():
    """Clean up any existing bot instances and webhooks"""
    try:
        # Step 1: Stop any existing bot processes
        logger.info("Stopping any existing bot processes...")
        subprocess.run(["python3", "stop_existing_bots.py"], check=True)
        
        # Step 2: Delete webhook with drop_pending_updates
        logger.info("Deleting webhook and dropping pending updates...")
        bot = Bot(token=BOT_TOKEN)
        
        # Try to get webhook info first
        webhook_info = await bot.get_webhook_info()
        if webhook_info.url:
            logger.info(f"Found existing webhook at: {webhook_info.url}")
            if webhook_info.pending_update_count > 0:
                logger.info(f"Webhook has {webhook_info.pending_update_count} pending updates that will be dropped")
        
        # Try to delete webhook with multiple retries
        for attempt in range(3):
            try:
                await bot.delete_webhook(drop_pending_updates=True)
                logger.info("Successfully deleted webhook and dropped pending updates")
                break
            except Exception as e:
                logger.error(f"Error deleting webhook (attempt {attempt+1}/3): {e}")
                if attempt < 2:  # Don't sleep on the last attempt
                    await asyncio.sleep(2)
                    
        # Step 3: Check webhook status
        webhook_info = await bot.get_webhook_info()
        if webhook_info.url:
            logger.warning(f"Webhook is still set: {webhook_info.url}")
        else:
            logger.info("Webhook removed successfully, ready for polling")
            
        # Step 4: Try to send a getUpdates request with a short timeout 
        # This can help clear any existing getUpdates connections
        try:
            logger.info("Sending test getUpdates to clear any existing connections...")
            await bot.get_updates(timeout=1, offset=-1, limit=1)
            logger.info("Test getUpdates sent successfully")
        except Exception as e:
            logger.warning(f"Expected error during test getUpdates: {e}")
            # This error is actually expected in many cases
            
        # Return success status
        return True
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        return False

async def main():
    """Main function to clean up and start the bot"""
    try:
        # Perform cleanup
        logger.info("Starting cleanup process...")
        cleanup_successful = await cleanup_before_start()
        
        if cleanup_successful:
            logger.info("Cleanup successful, starting bot...")
            # Start the main script with proper environmental variables
            os.environ["FORCE_POLLING"] = "true"
            # Change directory to the root to ensure imports work correctly
            os.chdir(os.path.dirname(os.path.abspath(__file__)))
            subprocess.run(["python3", "trading_bot/main.py"], check=True)
        else:
            logger.error("Cleanup failed, not starting bot")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Error in main function: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 
