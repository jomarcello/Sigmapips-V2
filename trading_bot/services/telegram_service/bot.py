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
import time
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

# Lock file path to track running instance
LOCK_FILE = "/tmp/telegbot_instance.lock"

def create_lock_file():
    """Create a lock file with the current process ID"""
    try:
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"Created lock file at {LOCK_FILE} with PID {os.getpid()}")
        return True
    except Exception as e:
        logger.error(f"Error creating lock file: {e}")
        return False

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
        
        # Step 5: Set environment variables to force polling
        logger.info("Setting environment variables to force polling mode...")
        os.environ["FORCE_POLLING"] = "true"
        os.environ["WEBHOOK_URL"] = ""  # Clear any webhook URL
        
        # Step 6: Create a lock file for this process
        create_lock_file()
            
        # Return success status
        return True
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        return False

def monitor_process(process):
    """Monitor a child process and restart it if needed"""
    try:
        while True:
            # Check if process is still running
            if process.poll() is not None:
                exit_code = process.returncode
                logger.error(f"Bot process exited with code {exit_code}")
                
                # If the process crashed, wait a bit before restarting to prevent rapid restarts
                if exit_code != 0:
                    logger.info("Waiting 10 seconds before cleanup and restart...")
                    time.sleep(10)
                    
                    # Run cleanup asynchronously
                    asyncio.run(cleanup_before_start())
                    
                    # Restart the process
                    logger.info("Restarting bot process...")
                    process = subprocess.Popen(["python3", "main.py"])
                else:
                    # Normal exit
                    logger.info("Bot process exited normally.")
                    break
            
            # Sleep for a while before checking again
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt. Shutting down...")
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
    except Exception as e:
        logger.error(f"Error in process monitor: {e}")
        if process and process.poll() is None:
            process.terminate()

async def main():
    """Main function to clean up and start the bot"""
    try:
        # Perform cleanup
        logger.info("Starting cleanup process...")
        cleanup_successful = await cleanup_before_start()
        
        if cleanup_successful:
            logger.info("Cleanup successful, starting bot...")
            # Start the main script but monitor it to restart if needed
            process = subprocess.Popen(["python3", "main.py"])
            
            # Monitor the process in the current thread
            monitor_process(process)
        else:
            logger.error("Cleanup failed, not starting bot")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Error in main function: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 
