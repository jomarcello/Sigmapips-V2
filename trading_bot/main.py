import logging
import os
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import stripe
import time
import asyncio
# Import telegram components only when needed to reduce startup time
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram import BotCommand, Update
from contextlib import asynccontextmanager
import telegram
from typing import Dict, Any
from datetime import datetime, timedelta, timezone
from fastapi.middleware.cors import CORSMiddleware

# Configureer logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Laad omgevingsvariabelen
load_dotenv()

# Importeer alleen de essentiële services direct - andere worden lazy-loaded
from .services.database.db import Database
from .services.payment_service.stripe_config import STRIPE_WEBHOOK_SECRET

# Import directly from the module to avoid circular imports through __init__.py
from .services.telegram_service.bot import TelegramService
from .services.payment_service.stripe_service import StripeService

# Initialize global services outside of FastAPI context
db = Database()
stripe_service = StripeService(db)
telegram_service = TelegramService(db, lazy_init=True)

# Create a simple webhook handler class
class WebhookHandler:
    """Handler for Telegram webhooks"""
    
    def __init__(self):
        """Initialize the webhook handler"""
        self.logger = logging.getLogger(__name__)
    
    async def handle_webhook(self, request: Request):
        """Handle a webhook request"""
        try:
            # Log the incoming request
            body = await request.body()
            self.logger.info(f"Received webhook payload: {body.decode('utf-8')[:100]}...")
            
            # Parse JSON data
            try:
                data = await request.json()
            except json.JSONDecodeError:
                self.logger.error("Invalid JSON in request body")
                return JSONResponse(content={"status": "error", "message": "Invalid JSON"}, status_code=400)
            
            # Log the parsed data
            self.logger.info(f"Webhook data: {data}")
            
            # Return success
            return JSONResponse(content={"status": "success", "message": "Webhook received"})
        except Exception as e:
            self.logger.error(f"Error processing webhook: {str(e)}")
            return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)
            
    async def register_routes(self, app: FastAPI):
        """Register webhook routes to the FastAPI app"""
        
        @app.post("/webhook")
        async def webhook(request: Request):
            """Main webhook endpoint"""
            return await self.handle_webhook(request)
            
        @app.post("/webhook/webhook")
        async def webhook_doubled(request: Request):
            """Handle doubled webhook path"""
            self.logger.info("Received request on doubled webhook path")
            return await self.handle_webhook(request)
            
        self.logger.info("Webhook routes registered")

# Create a singleton instance of the webhook handler
webhook_handler = WebhookHandler()

# Connect the services - chart service will be initialized lazily
telegram_service.stripe_service = stripe_service
stripe_service.telegram_service = telegram_service

# Define lifespan context manager for modern FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code
    try:
        logger.info("Initializing services...")
        
        # Register webhook routes
        await webhook_handler.register_routes(app)
        logger.info("Webhook routes registered")
        
        # Log that database is already initialized
        logger.info("Database initialized")
        
        # Initialize chart service through the telegram service's initialize_services method
        await telegram_service.initialize_services()
        logger.info("Chart service initialized through telegram service")
        
        # Log environment variables
        webhook_url = os.getenv("WEBHOOK_URL", "")
        logger.info(f"WEBHOOK_URL from environment: '{webhook_url}'")
        
        logger.info("Setting up Telegram bot manually")
        
        # Create application instance
        telegram_service.application = Application.builder().bot(telegram_service.bot).build()
        
        # Register command handlers manually
        telegram_service.application.add_handler(CommandHandler("start", telegram_service.start_command))
        telegram_service.application.add_handler(CommandHandler("menu", telegram_service.menu_command))
        telegram_service.application.add_handler(CommandHandler("help", telegram_service.help_command))
        telegram_service.application.add_handler(CommandHandler("set_subscription", telegram_service.set_subscription_command))
        telegram_service.application.add_handler(CommandHandler("set_payment_failed", telegram_service.set_payment_failed_command))
        telegram_service.application.add_handler(CallbackQueryHandler(telegram_service.button_callback))
        
        # Load signals - use await with the async method
        await telegram_service._load_signals()
        
        # Set bot commands
        commands = [
            BotCommand("start", "Start the bot and get the welcome message"),
            BotCommand("menu", "Show the main menu"),
            BotCommand("help", "Show available commands and how to use the bot")
        ]
        
        # Initialize the application and start in polling mode
        await telegram_service.application.initialize()
        await telegram_service.application.start()
        
        # Check if we should force webhook mode
        force_webhook = os.getenv("FORCE_WEBHOOK", "false").lower() == "true"
        
        # Get webhook URL and path from environment variables
        webhook_path = os.getenv("WEBHOOK_PATH", "/webhook")
        
        # Ensure webhook_url doesn't end with a slash
        if webhook_url.endswith("/"):
            webhook_url = webhook_url[:-1]
            
        # Ensure webhook_path starts with a slash
        if not webhook_path.startswith("/"):
            webhook_path = "/" + webhook_path
        
        # Set the webhook if we're using webhook mode
        if force_webhook and webhook_url:
            full_webhook_url = f"{webhook_url}{webhook_path}"
            logger.info(f"Setting webhook to {full_webhook_url}")
            logger.info(f"Bot token: {telegram_service.bot_token[:4]}...{telegram_service.bot_token[-4:]}")
            
            # Try to set webhook with more detailed error handling
            try:
                await telegram_service.bot.set_webhook(
                    url=full_webhook_url,
                    drop_pending_updates=True
                )
                
                # Verify webhook was set correctly
                webhook_info = await telegram_service.bot.get_webhook_info()
                logger.info(f"Webhook info after setting: {webhook_info.to_dict()}")
                
                telegram_service.polling_started = False
                logger.info(f"Webhook set successfully. Bot is running in webhook mode.")
            except Exception as e:
                logger.error(f"Error setting webhook: {str(e)}")
                raise
        # Check for existing bot instances if not forcing webhook mode
        elif not force_webhook:
            try:
                logger.info("Checking for existing bot instances...")
                # Use a small limit and timeout to check if another instance is running
                await telegram_service.bot.get_updates(limit=1, timeout=1, offset=-1)
                logger.info("No other bot instances running, starting polling...")
                
                # Start polling since no other instance is running
                await telegram_service.application.updater.start_polling(drop_pending_updates=True)
                telegram_service.polling_started = True
                logger.info("Polling started successfully")
            except telegram.error.Conflict as e:
                logger.warning(f"Another bot instance is already running: {str(e)}")
                logger.warning("This instance will run in webhook mode only and not poll for updates")
                # Don't start polling, but continue with the application
                telegram_service.polling_started = False
            except Exception as e:
                logger.error(f"Error starting polling: {str(e)}")
                # Continue without polling
                telegram_service.polling_started = False
        
        # Set the commands
        await telegram_service.bot.set_my_commands(commands)
        
        logger.info("Telegram bot initialized successfully")
        
    except Exception as e:
        logger.error(f"Error initializing services: {str(e)}")
        logger.exception(e)
        raise
    
    yield  # FastAPI is running
    
    # Shutdown code - cleanup resources
    logger.info("Shutting down application...")
    if telegram_service.application:
        try:
            await telegram_service.application.stop()
            await telegram_service.application.shutdown()
            logger.info("Telegram application stopped")
        except Exception as e:
            logger.error(f"Error stopping Telegram application: {str(e)}")

# Initialiseer de FastAPI app with lifespan
app = FastAPI(lifespan=lifespan)

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

# Signal endpoint registration directly on FastAPI
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

# Define webhook routes

# Telegram webhook endpoint
@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Endpoint for Telegram webhook updates"""
    try:
        # Log de binnenkomende request
        body = await request.body()
        logger.info(f"Received Telegram webhook update: {body.decode('utf-8')[:100]}...")
        
        # Parse de JSON data
        data = await request.json()
        
        # Stuur de update naar de telegram application
        if telegram_service and telegram_service.application:
            update = Update.de_json(data=data, bot=telegram_service.bot)
            await telegram_service.application.update_queue.put(update)
            return {"status": "success"}
        else:
            logger.error("Telegram service or application not initialized")
            raise HTTPException(status_code=500, detail="Telegram service not initialized")
    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        logger.error(f"Error processing Telegram webhook: {str(e)}")
        logger.exception(e)
        raise HTTPException(status_code=500, detail=str(e))

# Add endpoint to handle doubled webhook path (/webhook/webhook)
@app.post("/webhook/webhook")
async def telegram_webhook_doubled(request: Request):
    """Endpoint for handling doubled webhook path"""
    logger.info("Received request on doubled webhook path, redirecting to main webhook handler")
    return await telegram_webhook(request)

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
    import sys
    import os
    
    # Geef hier aan dat we het moderne app.py starten
    print("Starting SigmaPips Trading Bot...")
    print("Starting the application...")
    
    # Fix voor de "could not import module main" error
    # Gebruik het juiste module pad voor de huidige file
    current_module = __name__.rsplit('.', 1)[0] if '.' in __name__ else "trading_bot.main"
    
    # Log wat we gaan starten
    print(f"Starting app using module: {current_module}")
    
    # Start de app met het juiste module pad
    uvicorn.run(f"{current_module}:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))

# Expliciet de app exporteren
__all__ = ['app']

app = app  # Expliciete herbevestiging van de app variabele
