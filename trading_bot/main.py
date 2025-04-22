import logging
import os
import json
import time
from dotenv import load_dotenv
import stripe
import asyncio

# Import telegram components only when needed to reduce startup time
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram.request import HTTPXRequest
from telegram import BotCommand

# Configureer logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Laad omgevingsvariabelen
load_dotenv()

# Importeer alleen de essentiële services direct - andere worden lazy-loaded
from trading_bot.services.database.db import Database
from trading_bot.services.payment_service.stripe_config import STRIPE_WEBHOOK_SECRET

# Import TelegramService with fallback mechanisms
try:
    # First attempt - direct import
    from trading_bot.services.telegram_service.bot import TelegramService
except ImportError:
    try:
        # Second attempt - import from package
        from trading_bot.services.telegram_service import TelegramService
    except ImportError:
        # Last resort - dynamically load the class
        import importlib.util
        import sys
        
        # Path to the bot.py file
        bot_module_path = os.path.join(os.path.dirname(__file__), 'services', 'telegram_service', 'bot.py')
        
        if os.path.exists(bot_module_path):
            print(f"Loading TelegramService directly from {bot_module_path}")
            # Load the module from the file path
            spec = importlib.util.spec_from_file_location("telegram_service_bot", bot_module_path)
            telegram_bot_module = importlib.util.module_from_spec(spec)
            sys.modules["telegram_service_bot"] = telegram_bot_module
            spec.loader.exec_module(telegram_bot_module)
            
            # Check if the module has TelegramService
            if hasattr(telegram_bot_module, 'TelegramService'):
                TelegramService = telegram_bot_module.TelegramService
            else:
                # Try to find the TelegramService class in the module by looking at class definitions
                print("TelegramService not found directly, scanning module content...")
                for attr_name in dir(telegram_bot_module):
                    attr = getattr(telegram_bot_module, attr_name)
                    if isinstance(attr, type) and (attr_name == "TelegramService" or 
                            (hasattr(attr, '__module__') and attr.__module__ == 'telegram_service_bot')):
                        print(f"Found matching class: {attr_name}")
                        TelegramService = attr
                        # Also add it to the module for consistency
                        telegram_bot_module.TelegramService = attr
                        break
                else:
                    raise ImportError("Cannot find TelegramService class in module")
        else:
            raise ImportError("Cannot import TelegramService: bot.py file not found")

from trading_bot.services.payment_service.stripe_service import StripeService

# Voeg deze functie toe bovenaan het bestand, na de imports
def convert_interval_to_timeframe(interval):
    """Convert TradingView interval value to readable timeframe format"""
    if not interval:
        return "1h"  # Default timeframe
    
    # Converteer naar string voor het geval het als getal binnenkomt
    interval_str = str(interval).lower()
    
    # Controleer of het al een formaat heeft zoals "1m", "5m", etc.
    if interval_str.endswith('m') or interval_str.endswith('h') or interval_str.endswith('d') or interval_str.endswith('w'):
        return interval_str
    
    # Vertaal numerieke waarden naar timeframe formaat
    interval_map = {
        "1": "1m",
        "3": "3m",
        "5": "5m",
        "15": "15m",
        "30": "30m",
        "60": "1h",
        "120": "2h",
        "240": "4h",
        "360": "6h",
        "480": "8h",
        "720": "12h",
        "1440": "1d",
        "10080": "1w",
        "43200": "1M"
    }
    
    # Speciale gevallen voor 1
    if interval_str == "1":
        return "1m"  # Standaard 1 = 1 minuut
    
    # Controleer of we een directe mapping hebben
    if interval_str in interval_map:
        return interval_map[interval_str]
    
    # Als het een getal is zonder mapping, probeer te raden
    try:
        interval_num = int(interval_str)
        if interval_num < 60:
            return f"{interval_num}m"  # Minuten
        elif interval_num < 1440:
            hours = interval_num // 60
            return f"{hours}h"  # Uren
        elif interval_num < 10080:
            days = interval_num // 1440
            return f"{days}d"  # Dagen
        else:
            weeks = interval_num // 10080
            return f"{weeks}w"  # Weken
    except ValueError:
        # Als het geen getal is, geef het terug zoals het is
        return interval_str

# Function to register additional handlers after startup is complete
async def register_additional_handlers(telegram_service):
    try:
        # Add secondary command handlers
        telegram_service.application.add_handler(CommandHandler("help", telegram_service.help_command))
        telegram_service.application.add_handler(CommandHandler("set_subscription", telegram_service.set_subscription_command))
        telegram_service.application.add_handler(CommandHandler("set_payment_failed", telegram_service.set_payment_failed_command))
        
        logger.info("Additional command handlers registered")
        
    except Exception as e:
        logger.error(f"Error registering additional handlers: {str(e)}")

# Background task for processing signals
async def process_signal_background(signal_data: dict, telegram_service):
    try:
        # Process the signal in the background
        success = await telegram_service.process_signal(signal_data)
        
        if not success:
            logger.error(f"Failed to process signal in background: {signal_data}")
    except Exception as e:
        logger.error(f"Error in background signal processing: {str(e)}")
        logger.exception(e)

async def start_bot():
    """Main entry point for starting the bot"""
    start_time = time.time()
    perf_logs = []
    
    try:
        # Initialize the services
        logger.info("Initializing services...")
        perf_logs.append(f"Starting initialization: 0.00s")
        
        # Initialiseer database
        logger.info("Initializing database...")
        db = Database()
        logger.info("Database initialized successfully")
        perf_logs.append(f"Database initialized: {time.time() - start_time:.2f}s")
        
        # Initialiseer Stripe service
        logger.info("Initializing Stripe service...")
        stripe_service = StripeService(db)
        logger.info("Stripe service initialized successfully")
        perf_logs.append(f"Stripe service initialized: {time.time() - start_time:.2f}s")
        
        # Initialiseer en start de Telegram bot
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        proxy_url = os.environ.get("TELEGRAM_PROXY_URL")
        
        logger.info("Initializing Telegram service...")
        telegram_service = TelegramService(db, stripe_service, bot_token=bot_token, proxy_url=proxy_url, lazy_init=True)
        logger.info("Telegram service initialized successfully")
        perf_logs.append(f"Telegram service initialized: {time.time() - start_time:.2f}s")
        
        # Connect the services - chart service will be initialized lazily
        telegram_service.stripe_service = stripe_service
        stripe_service.telegram_service = telegram_service
        
        # Log environment variables
        webhook_url = os.getenv("WEBHOOK_URL", "")
        logger.info(f"WEBHOOK_URL from environment: '{webhook_url}'")
        
        # Log all performance measurements
        logger.info("=== STARTUP PERFORMANCE MEASUREMENTS ===")
        for log in perf_logs:
            logger.info(log)
        logger.info(f"Pre-run startup time: {time.time() - start_time:.2f}s")
        logger.info("=========================================")
        
        # Always use polling mode, ignoring webhook configuration
        logger.info("Starting bot in polling mode regardless of WEBHOOK_URL")
        logger.info("Starting bot using TelegramService.run()")
        await telegram_service.run()
        
        # We should never reach here as run() should block indefinitely
        logger.warning("Bot exited unexpectedly")
        
    except Exception as e:
        # Log performance even when there's an error
        logger.error(f"Error initializing services: {str(e)}")
        logger.exception(e)
        
        # Log performance up to the error
        logger.info("=== STARTUP PERFORMANCE (WITH ERRORS) ===")
        for log in perf_logs:
            logger.info(log)
        logger.info(f"Error occurred at: {time.time() - start_time:.2f}s")
        logger.info("=========================================")
        
        # Write measurements to a file for reference
        with open("startup_performance_error.txt", "w") as f:
            f.write("=== STARTUP PERFORMANCE (WITH ERRORS) ===\n")
            for log in perf_logs:
                f.write(f"{log}\n")
            f.write(f"Error occurred at: {time.time() - start_time:.2f}s\n")
            f.write("=========================================\n")
        
        raise

# Run the bot
if __name__ == "__main__":
    asyncio.run(start_bot())
