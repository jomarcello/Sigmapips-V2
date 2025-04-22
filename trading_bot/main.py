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

# Import directly from the module to avoid circular imports through __init__.py
from trading_bot.services.telegram_service.bot import TelegramService
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
        
        # Create application instance using HTTPX with optimized connection settings
        request = HTTPXRequest(
            connection_pool_size=50,
            connect_timeout=10.0,
            read_timeout=30.0,
            write_timeout=20.0,
            pool_timeout=30.0,
        )
        perf_logs.append(f"HTTP request initialized: {time.time() - start_time:.2f}s")
        
        # Set up the bot in a more optimized way
        logger.info("Setting up Telegram bot with optimized configuration")
        
        # Create application instance with optimized HTTP client
        telegram_service.application = Application.builder().bot(telegram_service.bot).build()
        perf_logs.append(f"Telegram application built: {time.time() - start_time:.2f}s")
        
        # Register only essential command handlers for startup
        # Other handlers will be registered when needed
        telegram_service.application.add_handler(CommandHandler("start", telegram_service.start_command))
        telegram_service.application.add_handler(CommandHandler("menu", telegram_service.show_main_menu))
        telegram_service.application.add_handler(CallbackQueryHandler(telegram_service.button_callback))
        perf_logs.append(f"Essential handlers registered: {time.time() - start_time:.2f}s")
        
        # Defer loading signals to background task
        # This will run after startup is complete
        asyncio.create_task(telegram_service._load_signals())
        
        # Set essential bot commands only
        commands = [
            BotCommand("start", "Start the bot and get the welcome message"),
            BotCommand("menu", "Show the main menu"),
            BotCommand("help", "Show available commands and how to use the bot")
        ]
        perf_logs.append(f"Commands prepared: {time.time() - start_time:.2f}s")
        
        try:
            # Initialize the application and start in polling mode
            # Wrap in try-except to continue even if Telegram fails
            await telegram_service.application.initialize()
            perf_logs.append(f"Application initialized: {time.time() - start_time:.2f}s")
            
            await telegram_service.application.start()
            perf_logs.append(f"Application started: {time.time() - start_time:.2f}s")
            
            await telegram_service.application.updater.start_polling()
            telegram_service.polling_started = True
            perf_logs.append(f"Polling started: {time.time() - start_time:.2f}s")
            
            # Set the commands
            await telegram_service.bot.set_my_commands(commands)
            perf_logs.append(f"Bot commands set: {time.time() - start_time:.2f}s")
            
            logger.info("Telegram bot initialized successfully in polling mode")
        except Exception as e:
            logger.error(f"Telegram initialization error (non-critical): {str(e)}")
            perf_logs.append(f"Telegram error (continuing): {time.time() - start_time:.2f}s")
        
        # Register remaining handlers in background task
        asyncio.create_task(register_additional_handlers(telegram_service))
        
        logger.info("Basic signal endpoints registered, additional handlers queued")
        perf_logs.append(f"Setup complete: {time.time() - start_time:.2f}s")
        
        # Log all performance measurements
        logger.info("=== STARTUP PERFORMANCE MEASUREMENTS ===")
        for log in perf_logs:
            logger.info(log)
        logger.info(f"Total startup time: {time.time() - start_time:.2f}s")
        logger.info("=========================================")
        
        # Write measurements to a file for reference
        with open("startup_performance.txt", "w") as f:
            f.write("=== STARTUP PERFORMANCE MEASUREMENTS ===\n")
            for log in perf_logs:
                f.write(f"{log}\n")
            f.write(f"Total startup time: {time.time() - start_time:.2f}s\n")
            f.write("=========================================\n")
        
        # Houdt het bot-proces in leven
        logger.info("Bot is running in polling mode. Press Ctrl+C to stop.")
        
        # Eenvoudige HTTP gezondheidsstatus eindpunt
        async def health_check():
            while True:
                try:
                    await asyncio.sleep(30)  # Check elke 30 seconden
                    logger.debug("Health check: Bot is running")
                    
                    # Controleer de telegram-bot status
                    if not telegram_service.polling_started:
                        logger.warning("Polling is gestopt, proberen te herstarten...")
                        try:
                            await telegram_service.application.updater.start_polling()
                            telegram_service.polling_started = True
                            logger.info("Polling succesvol herstart")
                        except Exception as e:
                            logger.error(f"Kon polling niet herstarten: {str(e)}")
                except Exception as e:
                    logger.error(f"Error in health check: {str(e)}")
        
        # Start health check task
        health_task = asyncio.create_task(health_check())
        
        # Wacht voor altijd (of totdat er een uitzondering optreedt)
        await asyncio.Future()
        
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
