#!/usr/bin/env python3
import logging
import os
import sys
import asyncio
import time
import re
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from telegram import Bot
from telegram.ext import Application

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
        telegram_service = TelegramService(db, stripe_service, bot_token=bot_token, lazy_init=True)
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
        # First ensure any existing bot is stopped
        await stop_bot()
        
        # Initialize the services if they're not already initialized
        if not telegram_service:
            logger.warning("Telegram service not initialized, initializing now...")
            # Import the proper bot class
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
            
            # Initialize Telegram service
            telegram_service = TelegramService(db, stripe_service, bot_token=bot_token)
        
        # Initialize chart service through the telegram service's initialize_services method
        # This is the only service we need to initialize eagerly
        await telegram_service.initialize_services()
        logger.info("Chart service initialized through telegram service")
        
        # Log environment variables
        webhook_url = os.getenv("WEBHOOK_URL", "")
        logger.info(f"WEBHOOK_URL from environment: '{webhook_url}'")
        
        # Clear all existing update sessions to avoid conflicts
        logger.info("Clearing existing update sessions...")
        try:
            # Delete webhook first to clear any pending updates
            await telegram_service.bot.delete_webhook(drop_pending_updates=True)
            logger.info("Successfully cleared webhook and dropped pending updates")
            
            # Send a dummy getUpdates request to clear any conflicting sessions
            await telegram_service.bot.get_updates(offset=-1, limit=1, timeout=1)
            logger.info("Sent dummy getUpdates request to clear sessions")
        except Exception as e:
            logger.error(f"Error clearing update sessions: {str(e)}")
        
        # Set up the application and register all handlers explicitly
        logger.info("Setting up application and registering handlers...")
        # Import Application here to avoid circular imports
        from telegram.ext import Application
        telegram_service.application = Application.builder().bot(telegram_service.bot).build()
        
        # Register handlers (this calls _register_handlers internally)
        logger.info("Registering command and callback handlers...")
        telegram_service._register_handlers(telegram_service.application)
        
        # Initialize the application
        await telegram_service.application.initialize()
        await telegram_service.application.start()
        
        # Determine if we should use polling based on environment
        use_polling = os.getenv("FORCE_POLLING", "").lower() == "true"
        is_local_env = not webhook_url or webhook_url == ""
        
        if use_polling or is_local_env:
            logger.info("Starting bot in polling mode...")
            # Make sure the updater isn't already running
            if hasattr(telegram_service.application, 'updater') and telegram_service.application.updater.running:
                await telegram_service.application.updater.stop()
            
            # Start polling with a longer timeout to reduce conflicts
            await telegram_service.application.updater.start_polling(poll_interval=1.0, timeout=30, drop_pending_updates=True)
            telegram_service.polling_started = True
            bot_running = True
            logger.info("Bot started in polling mode")
        else:
            logger.info("Skipping polling mode as bot is likely running in webhook mode")
            # Set webhook URL if it's not already set
            await telegram_service.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            telegram_service.polling_started = False
            bot_running = True
            logger.info(f"Webhook set to {webhook_url}")
        
        # Manually register signal endpoints
        @app.post("/signal")
        async def process_tradingview_signal(request: Request):
            """Process TradingView webhook signal"""
            try:
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
        
        logger.info("Signal endpoints registered directly on FastAPI app")
        
    except Exception as e:
        logger.error(f"Error initializing services: {str(e)}")
        logger.exception(e)
        raise 

async def stop_bot():
    """Safely stop the bot polling to prevent conflicts"""
    global bot_running
    
    # Only try to stop if we think it's running
    if bot_running and telegram_service and hasattr(telegram_service, 'polling_started') and telegram_service.polling_started:
        try:
            logger.info("Stopping telegram bot updater...")
            if hasattr(telegram_service, 'application') and telegram_service.application:
                if hasattr(telegram_service.application, 'updater') and telegram_service.application.updater.running:
                    await telegram_service.application.updater.stop()
                await telegram_service.application.stop()
                await telegram_service.application.shutdown()
            telegram_service.polling_started = False
            bot_running = False
            logger.info("Telegram bot stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping telegram bot: {str(e)}")
            logger.exception(e)
    else:
        logger.info("No bot running, nothing to stop") 
