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

# Import TelegramService with improved error handling
try:
    # Import from the package - this will use the fixed __init__.py which includes fallback mechanisms
    from trading_bot.services.telegram_service import TelegramService
    logger.info("Successfully imported TelegramService from package")
    
    # Verify that we have a usable TelegramService by checking basic attributes
    import inspect
    if not inspect.isclass(TelegramService):
        logger.warning("TelegramService is not a class, possibly using minimal implementation")
    else:
        # Check if the TelegramService has the run method
        if not hasattr(TelegramService, 'run') or not inspect.iscoroutinefunction(getattr(TelegramService, 'run')):
            logger.warning("TelegramService does not have a proper async run method, possibly using minimal implementation")
except ImportError as e:
    # Log detailed error 
    logger.error(f"Critical error importing TelegramService: {str(e)}")
    
    # Create minimal TelegramService implementation here as a last resort
    logger.warning("Creating emergency minimal TelegramService implementation in main.py")
    
    class TelegramService:
        """Emergency minimal TelegramService implementation"""
        def __init__(self, db, stripe_service=None, bot_token=None, proxy_url=None, lazy_init=False):
            self.db = db
            self.stripe_service = stripe_service
            self.bot_token = bot_token
            self.proxy_url = proxy_url
            self.application = None
            self.bot = None
            logger.warning("Using emergency minimal TelegramService implementation")
            
        async def run(self):
            logger.error("Emergency minimal implementation of TelegramService.run() called")
            while True:
                await asyncio.sleep(3600)  # Sleep forever
                
        async def initialize_services(self):
            logger.error("Emergency minimal implementation of TelegramService.initialize_services() called")
            return
            
        @property
        def signals_enabled(self):
            return False
    
    logger.warning("Emergency minimal TelegramService implementation created")
except Exception as e:
    # Handle unexpected errors
    logger.error(f"Unexpected error importing TelegramService: {str(e)}")
    raise ImportError(f"Cannot find TelegramService class in module: {str(e)}")

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
        
        # Check available parameters before initializing TelegramService
        try:
            import inspect
            init_signature = inspect.signature(TelegramService.__init__)
            has_bot_token_param = 'bot_token' in init_signature.parameters
            has_proxy_url_param = 'proxy_url' in init_signature.parameters
            has_lazy_init_param = 'lazy_init' in init_signature.parameters
            
            # Log the available parameters
            logger.info(f"TelegramService parameters - bot_token: {has_bot_token_param}, proxy_url: {has_proxy_url_param}, lazy_init: {has_lazy_init_param}")
            
            # Create kwargs based on available parameters
            kwargs = {'db': db, 'stripe_service': stripe_service}
            if has_bot_token_param:
                kwargs['bot_token'] = bot_token
            if has_proxy_url_param:
                kwargs['proxy_url'] = proxy_url
            if has_lazy_init_param:
                kwargs['lazy_init'] = True
                
            # Initialize with available parameters
            telegram_service = TelegramService(**kwargs)
            
        except Exception as e:
            logger.warning(f"Error checking parameters: {str(e)}, falling back to basic initialization")
            # Fallback to basic initialization with just required parameters
            telegram_service = TelegramService(db, stripe_service)
            
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
