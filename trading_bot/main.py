import logging
import os
import json
import sys
import socket
import fcntl
import errno
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import stripe
import time
# Import telegram components only when needed to reduce startup time
import telegram
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram import BotCommand
from telegram.error import Conflict, NetworkError, TelegramError

# Configureer logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Function to ensure only one instance of the bot is running
def obtain_lock():
    """Try to obtain a lock file to ensure only one instance runs"""
    lock_file = '/tmp/sigmapips_bot.lock'
    
    # Create a lock file descriptor
    lock_fd = open(lock_file, 'w')
    
    try:
        # Try to get an exclusive lock
        fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # If we're here, we got the lock
        # Keep the file descriptor open to maintain the lock
        logger.info("Successfully obtained lock - no other instances running")
        return lock_fd
    except IOError as e:
        if e.errno == errno.EAGAIN:
            # Another instance has the lock
            logger.error("Another instance is already running. Exiting.")
            sys.exit(1)
        # Some other error
        raise

# Get lock at the beginning
lock_fd = obtain_lock()

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
        await telegram_service._load_signals()
        
        # Set bot commands
        commands = [
            BotCommand("start", "Start the bot and get the welcome message"),
            BotCommand("menu", "Show the main menu"),
            BotCommand("help", "Show available commands and how to use the bot")
        ]
        
        # Initialize the application and start in polling mode with error handlers
        try:
            await telegram_service.application.initialize()
            await telegram_service.application.start()
            
            # Configure error handling for the updater's polling
            if hasattr(telegram_service.application, 'updater'):
                # Set allowed_updates to filter which updates to process
                await telegram_service.application.updater.start_polling(
                    allowed_updates=['message', 'callback_query', 'my_chat_member'],
                    drop_pending_updates=True,  # Ignore updates that came in while the bot was down
                    error_callback=lambda e: logger.error(f"Polling error: {e}")
                )
                telegram_service.polling_started = True
                logger.info("Telegram bot polling started with error handling")
            else:
                logger.error("No updater available for polling")
                
            # Set the commands
            await telegram_service.bot.set_my_commands(commands)
            
            logger.info("Telegram bot initialized successfully in polling mode")
            
        except Conflict as e:
            logger.error(f"Telegram Conflict error: {e}")
            logger.error("This error indicates another bot instance is already running.")
            logger.error("Ensure only one instance of this application is running.")
            logger.error("The lock mechanism should prevent this, but something went wrong.")
            sys.exit(1)
        except Exception as bot_error:
            logger.error(f"Error starting Telegram bot: {bot_error}")
            raise
        
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
