import logging
import os
import json
import time
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import stripe

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Import only the essential services directly - others will be lazy-loaded
from trading_bot.services.database.db import Database
from trading_bot.services.payment_service.stripe_config import STRIPE_WEBHOOK_SECRET

# Import directly from the module to avoid circular imports through __init__.py
from trading_bot.services.payment_service.stripe_service import StripeService

# Initialize the FastAPI app with optimized settings
app = FastAPI(
    title="Trading Bot API",
    description="API for the trading bot services",
    version="1.0.0"
)

# Global services - some will be initialized on demand (lazy loading)
db = None
stripe_service = None
telegram_service = None

def convert_interval_to_timeframe(interval):
    """Convert TradingView interval value to readable timeframe format"""
    if not interval:
        return "1h"  # Default timeframe
    
    # Convert to string in case it comes in as a number
    interval_str = str(interval).lower()
    
    # Check if it already has a format like "1m", "5m", etc.
    if interval_str.endswith('m') or interval_str.endswith('h') or interval_str.endswith('d') or interval_str.endswith('w'):
        return interval_str
    
    # Mapping of numeric values to timeframe format
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
    
    # Special cases for 1
    if interval_str == "1":
        return "1m"  # Default 1 = 1 minute
    
    # Check if we have a direct mapping
    if interval_str in interval_map:
        return interval_map[interval_str]
    
    # If it's a number without mapping, try to guess
    try:
        interval_num = int(interval_str)
        if interval_num < 60:
            return f"{interval_num}m"  # Minutes
        elif interval_num < 1440:
            hours = interval_num // 60
            return f"{hours}h"  # Hours
        elif interval_num < 10080:
            days = interval_num // 1440
            return f"{days}d"  # Days
        else:
            weeks = interval_num // 10080
            return f"{weeks}w"  # Weeks
    except ValueError:
        # If it's not a number, return as is
        return interval_str


async def initialize_core_services():
    """Initialize only the critical services needed for startup"""
    global db, stripe_service
    
    # Initialize database if not already done
    if db is None:
        db = Database()
        logger.info("Database initialized")
    
    # Initialize stripe service if not already done
    if stripe_service is None:
        stripe_service = StripeService(db)
        logger.info("Stripe service initialized")
    
    return True


async def initialize_telegram_service(lazy_init=True):
    """Initialize the telegram service separately and only when needed"""
    global telegram_service, db, stripe_service
    
    # Ensure core services are initialized
    await initialize_core_services()
    
    if telegram_service is None:
        # Import here to avoid circular imports and speed up startup
        from trading_bot.services.telegram_service.bot import TelegramService
        
        start_time = time.time()
        telegram_service = TelegramService(db, lazy_init=lazy_init)
        telegram_service.stripe_service = stripe_service
        stripe_service.telegram_service = telegram_service
        
        # Only set up bot commands and start polling if lazy_init is False
        # Otherwise, these will be set up when needed
        if not lazy_init:
            await setup_telegram_bot()
            
        logger.info(f"Telegram service initialized in {time.time() - start_time:.2f}s (lazy_init={lazy_init})")
    
    return telegram_service


async def setup_telegram_bot():
    """Set up the telegram bot separately from service initialization"""
    global telegram_service
    
    # Ensure telegram service is initialized
    if telegram_service is None:
        await initialize_telegram_service()
    
    if not telegram_service.polling_started:
        from telegram import BotCommand
        from telegram.ext import CommandHandler, CallbackQueryHandler
    
        # Create application instance if not already done
        if telegram_service.application is None:
            from telegram.ext import Application
            telegram_service.application = Application.builder().bot(telegram_service.bot).build()
        
        # Register command handlers
        telegram_service.application.add_handler(CommandHandler("start", telegram_service.start_command))
        telegram_service.application.add_handler(CommandHandler("menu", telegram_service.show_main_menu))
        telegram_service.application.add_handler(CommandHandler("help", telegram_service.help_command))
        telegram_service.application.add_handler(CommandHandler("set_subscription", telegram_service.set_subscription_command))
        telegram_service.application.add_handler(CommandHandler("set_payment_failed", telegram_service.set_payment_failed_command))
        telegram_service.application.add_handler(CallbackQueryHandler(telegram_service.button_callback))
        
        # Load signals
        telegram_service._load_signals()
        
        # Set bot commands
        commands = [
            BotCommand("start", "Start the bot and get the welcome message"),
            BotCommand("menu", "Show the main menu"),
            BotCommand("help", "Show available commands and how to use the bot")
        ]
        
        # Initialize and start in polling mode
        await telegram_service.application.initialize()
        await telegram_service.application.start()
        await telegram_service.application.updater.start_polling()
        telegram_service.polling_started = True
        
        # Set the commands
        await telegram_service.bot.set_my_commands(commands)
        
        logger.info("Telegram bot initialized successfully in polling mode")
    

@app.on_event("startup")
async def startup_event():
    """Initialize services on app startup"""
    try:
        start_time = time.time()
        logger.info("Starting application initialization...")
        
        # Initialize core services synchronously - these are required immediately
        await initialize_core_services()
        
        # Log environment variables
        webhook_url = os.getenv("WEBHOOK_URL", "")
        logger.info(f"WEBHOOK_URL from environment: '{webhook_url}'")
        
        # Initialize telegram service in the background to not block startup
        # This will initialize it with lazy loading enabled
        asyncio.create_task(initialize_telegram_service(lazy_init=True))
        
        logger.info(f"Application startup completed in {time.time() - start_time:.2f}s")
    except Exception as e:
        logger.error(f"Error initializing services: {str(e)}")
        logger.exception(e)
        raise


# Define webhook routes

# Manual signal endpoint registration
@app.post("/signal")
async def process_tradingview_signal(request: Request):
    """Process TradingView webhook signal"""
    try:
        global telegram_service
        # Initialize telegram service if not already done
        if telegram_service is None:
            await initialize_telegram_service()
        
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


@app.post("/tradingview-signal")
async def tradingview_signal(request: Request):
    """Endpoint for TradingView signals only"""
    try:
        global telegram_service
        
        # Initialize telegram service if not already done
        if telegram_service is None:
            await initialize_telegram_service()
        
        # Log the incoming request
        body = await request.body()
        logger.info(f"Received TradingView signal: {body.decode('utf-8')}")
        
        # Process signal data
        try:
            signal_data = json.loads(body)
        except json.JSONDecodeError:
            logger.error("Invalid JSON in TradingView signal")
            return JSONResponse({"status": "error", "message": "Invalid JSON format"})
        
        # Process the signal
        success = await telegram_service.process_signal(signal_data)
        
        if success:
            return JSONResponse({"status": "success", "message": "Signal processed successfully"})
        else:
            return JSONResponse({"status": "error", "message": "Failed to process signal"})
            
    except Exception as e:
        logger.error(f"Error processing TradingView signal: {str(e)}")
        logger.exception(e)
        return JSONResponse({"status": "error", "message": str(e)})


# Stripe webhook route
@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events"""
    try:
        # Ensure stripe service is initialized
        await initialize_core_services()
        
        # Get the webhook signature header
        signature = request.headers.get("stripe-signature")
        
        if not signature:
            logger.warning("No Stripe signature in webhook request")
            raise HTTPException(status_code=400, detail="No Stripe signature")
        
        # Get the webhook body
        payload = await request.body()
        payload_str = payload.decode("utf-8")
        
        # Verify and construct the event
        try:
            event = stripe.Webhook.construct_event(
                payload_str, signature, STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            logger.error(f"Invalid Stripe webhook payload: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid Stripe signature: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid signature")
        
        # Process the event
        await stripe_service.handle_webhook_event(event)
        
        return {"status": "success"}
    
    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error processing Stripe webhook: {str(e)}")
        logger.exception(e)
        raise HTTPException(status_code=500, detail=f"Error processing webhook: {str(e)}")


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": time.time()}import logging
import os
import json
import time
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import stripe

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Import only the essential services directly - others will be lazy-loaded
from trading_bot.services.database.db import Database
from trading_bot.services.payment_service.stripe_config import STRIPE_WEBHOOK_SECRET

# Import directly from the module to avoid circular imports through __init__.py
from trading_bot.services.payment_service.stripe_service import StripeService

# Initialize the FastAPI app with optimized settings
app = FastAPI(
    title="Trading Bot API",
    description="API for the trading bot services",
    version="1.0.0"
)

# Global services - some will be initialized on demand (lazy loading)
db = None
stripe_service = None
telegram_service = None

def convert_interval_to_timeframe(interval):
    """Convert TradingView interval value to readable timeframe format"""
    if not interval:
        return "1h"  # Default timeframe
    
    # Convert to string in case it comes in as a number
    interval_str = str(interval).lower()
    
    # Check if it already has a format like "1m", "5m", etc.
    if interval_str.endswith('m') or interval_str.endswith('h') or interval_str.endswith('d') or interval_str.endswith('w'):
        return interval_str
    
    # Mapping of numeric values to timeframe format
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
    
    # Special cases for 1
    if interval_str == "1":
        return "1m"  # Default 1 = 1 minute
    
    # Check if we have a direct mapping
    if interval_str in interval_map:
        return interval_map[interval_str]
    
    # If it's a number without mapping, try to guess
    try:
        interval_num = int(interval_str)
        if interval_num < 60:
            return f"{interval_num}m"  # Minutes
        elif interval_num < 1440:
            hours = interval_num // 60
            return f"{hours}h"  # Hours
        elif interval_num < 10080:
            days = interval_num // 1440
            return f"{days}d"  # Days
        else:
            weeks = interval_num // 10080
            return f"{weeks}w"  # Weeks
    except ValueError:
        # If it's not a number, return as is
        return interval_str


async def initialize_core_services():
    """Initialize only the critical services needed for startup"""
    global db, stripe_service
    
    # Initialize database if not already done
    if db is None:
        db = Database()
        logger.info("Database initialized")
    
    # Initialize stripe service if not already done
    if stripe_service is None:
        stripe_service = StripeService(db)
        logger.info("Stripe service initialized")
    
    return True


async def initialize_telegram_service(lazy_init=True):
    """Initialize the telegram service separately and only when needed"""
    global telegram_service, db, stripe_service
    
    # Ensure core services are initialized
    await initialize_core_services()
    
    if telegram_service is None:
        # Import here to avoid circular imports and speed up startup
        from trading_bot.services.telegram_service.bot import TelegramService
        
        start_time = time.time()
        telegram_service = TelegramService(db, lazy_init=lazy_init)
        telegram_service.stripe_service = stripe_service
        stripe_service.telegram_service = telegram_service
        
        # Only set up bot commands and start polling if lazy_init is False
        # Otherwise, these will be set up when needed
        if not lazy_init:
            await setup_telegram_bot()
            
        logger.info(f"Telegram service initialized in {time.time() - start_time:.2f}s (lazy_init={lazy_init})")
    
    return telegram_service


async def setup_telegram_bot():
    """Set up the telegram bot separately from service initialization"""
    global telegram_service
    
    # Ensure telegram service is initialized
    if telegram_service is None:
        await initialize_telegram_service()
    
    if not telegram_service.polling_started:
        from telegram import BotCommand
        from telegram.ext import CommandHandler, CallbackQueryHandler
    
        # Create application instance if not already done
        if telegram_service.application is None:
            from telegram.ext import Application
            telegram_service.application = Application.builder().bot(telegram_service.bot).build()
        
        # Register command handlers
        telegram_service.application.add_handler(CommandHandler("start", telegram_service.start_command))
        telegram_service.application.add_handler(CommandHandler("menu", telegram_service.show_main_menu))
        telegram_service.application.add_handler(CommandHandler("help", telegram_service.help_command))
        telegram_service.application.add_handler(CommandHandler("set_subscription", telegram_service.set_subscription_command))
        telegram_service.application.add_handler(CommandHandler("set_payment_failed", telegram_service.set_payment_failed_command))
        telegram_service.application.add_handler(CallbackQueryHandler(telegram_service.button_callback))
        
        # Load signals
        telegram_service._load_signals()
        
        # Set bot commands
        commands = [
            BotCommand("start", "Start the bot and get the welcome message"),
            BotCommand("menu", "Show the main menu"),
            BotCommand("help", "Show available commands and how to use the bot")
        ]
        
        # Initialize and start in polling mode
        await telegram_service.application.initialize()
        await telegram_service.application.start()
        await telegram_service.application.updater.start_polling()
        telegram_service.polling_started = True
        
        # Set the commands
        await telegram_service.bot.set_my_commands(commands)
        
        logger.info("Telegram bot initialized successfully in polling mode")
    

@app.on_event("startup")
async def startup_event():
    """Initialize services on app startup"""
    try:
        start_time = time.time()
        logger.info("Starting application initialization...")
        
        # Initialize core services synchronously - these are required immediately
        await initialize_core_services()
        
        # Log environment variables
        webhook_url = os.getenv("WEBHOOK_URL", "")
        logger.info(f"WEBHOOK_URL from environment: '{webhook_url}'")
        
        # Initialize telegram service in the background to not block startup
        # This will initialize it with lazy loading enabled
        asyncio.create_task(initialize_telegram_service(lazy_init=True))
        
        logger.info(f"Application startup completed in {time.time() - start_time:.2f}s")
    except Exception as e:
        logger.error(f"Error initializing services: {str(e)}")
        logger.exception(e)
        raise


# Define webhook routes

# Manual signal endpoint registration
@app.post("/signal")
async def process_tradingview_signal(request: Request):
    """Process TradingView webhook signal"""
    try:
        global telegram_service
        # Initialize telegram service if not already done
        if telegram_service is None:
            await initialize_telegram_service()
        
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


@app.post("/tradingview-signal")
async def tradingview_signal(request: Request):
    """Endpoint for TradingView signals only"""
    try:
        global telegram_service
        
        # Initialize telegram service if not already done
        if telegram_service is None:
            await initialize_telegram_service()
        
        # Log the incoming request
        body = await request.body()
        logger.info(f"Received TradingView signal: {body.decode('utf-8')}")
        
        # Process signal data
        try:
            signal_data = json.loads(body)
        except json.JSONDecodeError:
            logger.error("Invalid JSON in TradingView signal")
            return JSONResponse({"status": "error", "message": "Invalid JSON format"})
        
        # Process the signal
        success = await telegram_service.process_signal(signal_data)
        
        if success:
            return JSONResponse({"status": "success", "message": "Signal processed successfully"})
        else:
            return JSONResponse({"status": "error", "message": "Failed to process signal"})
            
    except Exception as e:
        logger.error(f"Error processing TradingView signal: {str(e)}")
        logger.exception(e)
        return JSONResponse({"status": "error", "message": str(e)})


# Stripe webhook route
@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events"""
    try:
        # Ensure stripe service is initialized
        await initialize_core_services()
        
        # Get the webhook signature header
        signature = request.headers.get("stripe-signature")
        
        if not signature:
            logger.warning("No Stripe signature in webhook request")
            raise HTTPException(status_code=400, detail="No Stripe signature")
        
        # Get the webhook body
        payload = await request.body()
        payload_str = payload.decode("utf-8")
        
        # Verify and construct the event
        try:
            event = stripe.Webhook.construct_event(
                payload_str, signature, STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            logger.error(f"Invalid Stripe webhook payload: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid Stripe signature: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid signature")
        
        # Process the event
        await stripe_service.handle_webhook_event(event)
        
        return {"status": "success"}
    
    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error processing Stripe webhook: {str(e)}")
        logger.exception(e)
        raise HTTPException(status_code=500, detail=f"Error processing webhook: {str(e)}")


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": time.time()}import logging
import os
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import stripe
import time
# Import telegram components only when needed to reduce startup time
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
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

# Initialiseer de FastAPI app
app = FastAPI()

# Initialiseer de database
db = Database()

# Initialize only the critical services immediately
stripe_service = StripeService(db)

# Initialize telegram service with lazy loading option
telegram_service = TelegramService(db, lazy_init=True)

# Connect the services - chart service will be initialized lazily
telegram_service.stripe_service = stripe_service
stripe_service.telegram_service = telegram_service

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

@app.on_event("startup")
async def startup_event():
    try:
        # Initialize the services
        logger.info("Initializing services...")
        
        # No need to manually connect the database - it's done automatically in the constructor
        # The log shows "Successfully connected to Supabase" already
        logger.info("Database initialized")
        
        # Initialize chart service through the telegram service's initialize_services method
        # This is the only service we need to initialize eagerly
        await telegram_service.initialize_services()
        logger.info("Chart service initialized through telegram service")
        
        # Log environment variables
        webhook_url = os.getenv("WEBHOOK_URL", "")
        logger.info(f"WEBHOOK_URL from environment: '{webhook_url}'")
        
        # Don't use the telegram_service.initialize method since it has issues
        # Instead, set up the bot manually
        logger.info("Setting up Telegram bot manually")
        
        # Create application instance
        telegram_service.application = Application.builder().bot(telegram_service.bot).build()
        
        # Register command handlers manually
        telegram_service.application.add_handler(CommandHandler("start", telegram_service.start_command))
        telegram_service.application.add_handler(CommandHandler("menu", telegram_service.show_main_menu))
        telegram_service.application.add_handler(CommandHandler("help", telegram_service.help_command))
        telegram_service.application.add_handler(CommandHandler("set_subscription", telegram_service.set_subscription_command))
        telegram_service.application.add_handler(CommandHandler("set_payment_failed", telegram_service.set_payment_failed_command))
        telegram_service.application.add_handler(CallbackQueryHandler(telegram_service.button_callback))
        
        # Load signals
        telegram_service._load_signals()
        
        # Set bot commands
        commands = [
            BotCommand("start", "Start the bot and get the welcome message"),
            BotCommand("menu", "Show the main menu"),
            BotCommand("help", "Show available commands and how to use the bot")
        ]
        
        # Initialize the application and start in polling mode
        await telegram_service.application.initialize()
        await telegram_service.application.start()
        await telegram_service.application.updater.start_polling()
        telegram_service.polling_started = True
        
        # Set the commands
        await telegram_service.bot.set_my_commands(commands)
        
        logger.info("Telegram bot initialized successfully in polling mode")
        
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

# Define webhook routes

# Comment out this route as it conflicts with the telegram webhook
# @app.get("/webhook")
# async def webhook_info():
#     """Return webhook info"""
#     return {"status": "Telegram webhook endpoint", "info": "Use POST method to send updates"}

@app.post("/tradingview-signal")
async def tradingview_signal(request: Request):
    """Endpoint for TradingView signals only"""
    try:
        # Log de binnenkomende request
        body = await request.body()
        logger.info(f"Received TradingView signal: {body.decode('utf-8')}")
        
        # Parse de JSON data
        data = await request.json()
        
        # Verwerk als TradingView signaal
        if telegram_service:
            success = await telegram_service.process_signal(data)
            if success:
                return JSONResponse(content={"status": "success", "message": "Signal processed"})
            else:
                raise HTTPException(status_code=500, detail="Failed to process signal")
        
        # Als we hier komen, konden we het verzoek niet verwerken
        raise HTTPException(status_code=400, detail="Could not process TradingView signal")
    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/signals")
async def receive_signal(request: Request):
    """Endpoint for receiving trading signals"""
    try:
        # Haal de data op
        signal_data = await request.json()
        
        # Process the signal directly without checking if enabled
        success = await telegram_service.process_signal(signal_data)
        
        if success:
            return {"status": "success", "message": "Signal processed successfully"}
        else:
            return {"status": "error", "message": "Failed to process signal"}
    except Exception as e:
        logger.error(f"Error processing signal: {str(e)}")
        return {"status": "error", "message": str(e)}

# Voeg deze nieuwe route toe voor het enkelvoudige '/signal' eindpunt
@app.post("/signal")
async def receive_single_signal(request: Request):
    """Endpoint for receiving trading signals (singular form)"""
    # Stuur gewoon door naar de bestaande eindpunt-functie
    return await receive_signal(request)

@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature")
    
    # Uitgebreidere logging
    logger.info(f"Webhook payload begin: {payload[:100]}")  # Log begin van payload
    logger.info(f"Signature header: {sig_header}")
    
    # Test verschillende webhook secrets
    test_secrets = [
        os.getenv("STRIPE_WEBHOOK_SECRET"),
        "whsec_ylBJwcxgeTj66Y8e2zcXDjY3IlTvhPPa",  # Je huidige secret
        # Voeg hier andere mogelijke secrets toe
    ]
    
    event = None
    # Probeer elk secret
    for secret in test_secrets:
        if not secret:
            continue
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, secret)
            logger.info(f"Signature validatie succesvol met secret: {secret[:5]}...")
            break
        except Exception:
            continue
            
    # Als geen enkel secret werkt, accepteer zonder validatie (voor testen)
    if not event:
        logger.warning("Geen enkel webhook secret werkt, webhook accepteren zonder validatie")
        data = json.loads(payload)
        event = {"type": data.get("type"), "data": {"object": data}}
    
    # Verwerk het event
    await stripe_service.handle_webhook_event(event)
    
    return {"status": "success"}

@app.get("/create-subscription-link/{user_id}/{plan_type}")
async def create_subscription_link(user_id: int, plan_type: str = 'basic'):
    """Maak een Stripe Checkout URL voor een gebruiker"""
    try:
        checkout_url = await stripe_service.create_checkout_session(user_id, plan_type)
        
        if checkout_url:
            return {"status": "success", "checkout_url": checkout_url}
        else:
            raise HTTPException(status_code=500, detail="Failed to create checkout session")
    except Exception as e:
        logger.error(f"Error creating subscription link: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/test-webhook")
async def test_webhook(request: Request):
    """Test endpoint for webhook processing"""
    try:
        # Log de request
        body = await request.body()
        logger.info(f"Test webhook received: {body.decode('utf-8')}")
        
        # Parse de data
        data = await request.json()
        
        # Simuleer een checkout.session.completed event
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_" + str(int(time.time())),
                    "client_reference_id": str(data.get("user_id")),
                    "customer": "cus_test_" + str(int(time.time())),
                    "subscription": "sub_test_" + str(int(time.time())),
                    "metadata": {
                        "user_id": str(data.get("user_id"))
                    }
                }
            }
        }
        
        # Process the test event
        result = await stripe_service.handle_webhook_event(event)
        
        return {"status": "success", "processed": result}
    except Exception as e:
        logger.error(f"Error processing test webhook: {str(e)}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("trading_bot.main:app", host="0.0.0.0", port=8080)

# Expliciet de app exporteren
__all__ = ['app']

app = app  # Expliciete herbevestiging van de app variabele
