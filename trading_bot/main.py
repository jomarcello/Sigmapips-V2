#!/usr/bin/env python3
import logging
import os
import sys
import asyncio
import time
import re
import uuid
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from telegram import Bot
from telegram.ext import Application

# Create a unique instance ID for this process
INSTANCE_ID = str(uuid.uuid4())
os.environ["BOT_INSTANCE_ID"] = INSTANCE_ID
print(f"Starting bot instance with ID: {INSTANCE_ID}")

# Force polling for local development unless explicitly set otherwise
if not os.getenv("WEBHOOK_URL") and os.getenv("FORCE_POLLING") is None:
    os.environ["FORCE_POLLING"] = "true"
    print("Setting FORCE_POLLING=true for local development")

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

# Global variable to track if bot is running
bot_running = False
telegram_service = None

# Function to read the bot token from .env file
def read_token_from_env_file():
    """Read the Telegram bot token directly from the .env file"""
    try:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
        if not os.path.exists(env_path):
            logger.error(f"❌ .env bestand niet gevonden op {env_path}")
            return None
            
        with open(env_path, 'r') as file:
            for line in file:
                # Skip comments and empty lines
                if line.strip().startswith('#') or not line.strip():
                    continue
                    
                # Look for TELEGRAM_BOT_TOKEN
                match = re.match(r'TELEGRAM_BOT_TOKEN\s*=\s*(.+)', line)
                if match:
                    token = match.group(1).strip()
                    return token
                    
        logger.error("❌ TELEGRAM_BOT_TOKEN niet gevonden in .env bestand")
        return None
    except Exception as e:
        logger.error(f"❌ Fout bij het lezen van .env bestand: {str(e)}")
        return None

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
        instance_id = os.getenv("BOT_INSTANCE_ID", "unknown")
        logger.info(f"Main process starting with instance ID: {instance_id}")
        
        # Add environment flag to indicate this is the main process 
        os.environ["MAIN_PROCESS"] = "true"
        
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
        
        # Get the Telegram bot token from environment variables
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        # If not found in env, read directly from .env file
        if not bot_token:
            logger.info("TELEGRAM_BOT_TOKEN niet gevonden in omgevingsvariabelen, lezen uit .env bestand...")
            bot_token = read_token_from_env_file()
            
        # Ensure we have a valid token
        if not bot_token:
            logger.error("❌ Geen geldige TELEGRAM_BOT_TOKEN gevonden. Gebruik python check_telegram_token.py voor hulp.")
            sys.exit(1)
        
        logger.info(f"Using Telegram bot token: {bot_token[:10]}...")
        
        # Initialize Telegram service with database and Stripe service
        # Enable lazy initialization to defer heavy service loading
        global telegram_service, bot_running
        telegram_start_time = time.time()
        
        try:
            # Check if the bot is already running in FastAPI
            if bot_running and telegram_service:
                logger.info(f"Bot already running from FastAPI, skipping duplicate initialization")
                # Just wait and keep the script alive
                while True:
                    await asyncio.sleep(60)
                
            telegram_service = TelegramService(db, stripe_service, bot_token=bot_token, lazy_init=True)
            telegram_time = time.time() - telegram_start_time
            logger.info(f"Telegram service initialized with lazy loading in {telegram_time:.2f} seconds")
            
            # Start the bot with enhanced error handling
            bot_start_time = time.time()
            try:
                # Initialize services for charts and other necessary components
                await telegram_service.initialize_services()
                logger.info("Services initialized successfully")
                
                # Start the bot with our new robust run() method that handles retries
                # This will automatically retry on service unavailable errors
                logger.info("Starting bot with retry mechanism...")
                bot_task = asyncio.create_task(telegram_service.run())
                
                # Give the bot a moment to connect and detect any immediate failures
                await asyncio.sleep(5)
                
                # Check if the bot task is still running or if it failed immediately
                if bot_task.done():
                    exception = bot_task.exception()
                    if exception:
                        logger.error(f"Bot failed to start: {str(exception)}")
                        raise exception
                
                bot_running = True
                logger.info(f"Bot started successfully with instance ID: {instance_id}")
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
                
                # Keep the bot task running without awaiting it 
                # so that other asynchronous tasks (like FastAPI) can run concurrently
                while True:
                    # Check periodically if the bot is still running
                    if bot_task.done():
                        exception = bot_task.exception()
                        if exception:
                            logger.error(f"Bot task stopped with error: {str(exception)}")
                            # Restart the bot task if it fails
                            logger.info("Restarting bot task...")
                            bot_task = asyncio.create_task(telegram_service.run())
                    
                    await asyncio.sleep(60)
                    
            except Exception as e:
                logger.error(f"Error starting bot: {str(e)}")
                bot_running = False
                # Re-raise to handle at a higher level
                raise
            
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            # Re-raise to handle at a higher level
            raise
    
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

app = FastAPI()

# Add CORS middleware to allow requests from other domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add health check endpoint for Railway
@app.get("/health")
async def health_check():
    """Health check endpoint for Railway"""
    return {"status": "ok"}

@app.on_event("startup")
async def startup_event():
    global bot_running, telegram_service
    
    try:
        # Log startup status
        logger.info("FastAPI startup event triggered")
        instance_id = os.getenv("BOT_INSTANCE_ID", "unknown")
        logger.info(f"FastAPI startup with instance ID: {instance_id}")
        
        # First ensure any existing bot is stopped to avoid conflicts
        await stop_bot()
        
        # Check if this is the first instance or if the main app already started the bot
        # We can track this with the global bot_running flag
        if bot_running and telegram_service:
            logger.info(f"Bot already running (instance {instance_id}), skipping init in FastAPI startup")
            return
            
        # Only initialize and start the bot if it's not already running
        # This prevents conflicts when both main.py and FastAPI try to start the bot
        if not bot_running and not telegram_service:
            logger.info("Bot not running, initializing services from FastAPI startup")
            
            # Import services
            from trading_bot.services.telegram_service.bot import TelegramService
            from trading_bot.services.database.db import Database
            from trading_bot.services.payment_service.stripe_service import StripeService
            
            # Initialize database
            db = Database()
            logger.info("Database initialized")
            
            # Initialize Stripe service
            stripe_service = StripeService(db)
            
            # Get the Telegram bot token from environment variables
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
            # If not found in env, read directly from .env file
            if not bot_token:
                bot_token = read_token_from_env_file()
                
            # Ensure we have a valid token
            if not bot_token:
                logger.error("No valid TELEGRAM_BOT_TOKEN found.")
                return
            
            # Initialize Telegram service with robust settings
            telegram_service = TelegramService(db, stripe_service, bot_token=bot_token, lazy_init=True)
            logger.info("Telegram service initialized with robust settings")
            
            # Initialize services first
            await telegram_service.initialize_services()
            logger.info("Services initialized successfully")
            
            # Create a background task to run the bot with retry mechanism
            # This uses the enhanced run() method that handles connection issues
            logger.info("Starting bot as background task...")
            asyncio.create_task(telegram_service.run())
            bot_running = True
            logger.info(f"Bot started with instance ID: {instance_id}")
            
        else:
            logger.info(f"Bot already running: {bot_running}, telegram_service exists: {telegram_service is not None}")
            # If the bot was started by main.py, just ensure the chart service is initialized
            if telegram_service and not bot_running:
                logger.info("Telegram service exists but bot not marked as running, initializing services")
                await telegram_service.initialize_services()
                bot_running = True
        
        # Register signal endpoint and ensure it's available
        logger.info("Registering signal endpoint")
        
    except Exception as e:
        logger.error(f"Error initializing services: {str(e)}")
        logger.exception(e)
        # Don't raise the exception to let the FastAPI app continue to start

async def stop_bot():
    """Safely stop the bot polling to prevent conflicts"""
    global bot_running
    
    # Only try to stop if we think it's running
    if bot_running and telegram_service and hasattr(telegram_service, 'polling_started') and telegram_service.polling_started:
        try:
            logger.info("Stopping telegram bot updater...")
            instance_id = os.getenv("BOT_INSTANCE_ID", "unknown")
            logger.info(f"Stopping bot with instance ID: {instance_id}")
            
            # First try to delete webhook and reset update session
            try:
                await telegram_service.bot.delete_webhook(drop_pending_updates=True)
                logger.info("Webhook cleared during bot stop")
                
                # Send a dummy request to reset update session
                await telegram_service.bot.get_updates(offset=-1, limit=1, timeout=1, allowed_updates=[])
                logger.info("Reset update session during bot stop")
            except Exception as clear_e:
                logger.warning(f"Error clearing webhook during stop: {str(clear_e)}")
            
            # Then stop the updater if it's running
            if hasattr(telegram_service, 'application') and telegram_service.application:
                if hasattr(telegram_service.application, 'updater') and telegram_service.application.updater.running:
                    await telegram_service.application.updater.stop()
                    logger.info("Updater stopped successfully")
                
                # Stop and shutdown the application
                try:
                    await telegram_service.application.stop()
                    logger.info("Application stopped successfully")
                except Exception as stop_e:
                    logger.warning(f"Error stopping application: {str(stop_e)}")
                    
                try:
                    await telegram_service.application.shutdown()
                    logger.info("Application shutdown successfully")
                except Exception as shutdown_e:
                    logger.warning(f"Error shutting down application: {str(shutdown_e)}")
                    
            telegram_service.polling_started = False
            bot_running = False
            logger.info("Telegram bot stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping telegram bot: {str(e)}")
            logger.exception(e)
            # Even if there's an error, mark the bot as not running
            telegram_service.polling_started = False if telegram_service else False
            bot_running = False
    else:
        logger.info("No bot running or polling not started, nothing to stop")

# Register the signal endpoint outside the startup event to ensure it's always available
@app.post("/signal")
async def process_tradingview_signal(request: Request):
    """Process TradingView webhook signal"""
    try:
        # Ensure telegram service is initialized
        if not telegram_service:
            return {"status": "error", "message": "Telegram service not initialized"}
            
        # Get the signal data from the request
        signal_data = await request.json()
        logger.info(f"Received TradingView webhook signal: {signal_data}")
        
        # Process the signal
        success = await telegram_service.process_signal(signal_data)
        
        if success:
            return {"status": "success", "message": "Signal processed successfully"}
        else:
            return {"status": "error", "message": "Failed to process signal"}
            
    except Exception as e:
        logger.error(f"Error processing TradingView webhook signal: {str(e)}")
        logger.exception(e)
        return {"status": "error", "message": str(e)} 
