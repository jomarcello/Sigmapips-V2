import logging
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
import asyncio

# Configureer logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Laad omgevingsvariabelen
load_dotenv()

# Global variable to track if bot is running
bot_running = False

# Initialiseer de FastAPI app - do this before any imports that might reference this app
app = FastAPI()

# Mark app as explicitly exported
__all__ = ['app']

# IMPORTANT: Move imports after app initialization to prevent circular imports
# Importeer alleen de essentiële services direct - andere worden lazy-loaded
from trading_bot.services.database.db import Database
from trading_bot.services.payment_service.stripe_config import STRIPE_WEBHOOK_SECRET

# Use delayed import to prevent circular imports
# These imports are executed only when needed
def get_telegram_service():
    """Get or create telegram service instance"""
    global telegram_service
    if not telegram_service:
        # Import when needed
        from trading_bot.services.telegram_service import TelegramService
        from trading_bot.services.payment_service.stripe_service import StripeService
        
        # Initialiseer de database
        db = Database()
        
        # Initialize only the critical services immediately
        stripe_service = StripeService(db)
        
        # Initialize telegram service with lazy loading option
        telegram_service = TelegramService(db, lazy_init=True)
        
        # Connect the services - chart service will be initialized lazily
        telegram_service.stripe_service = stripe_service
        stripe_service.telegram_service = telegram_service
    
    return telegram_service

# Initialize them only when needed - Use None as placeholder
db = None
stripe_service = None
telegram_service = None

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

async def stop_bot():
    """Safely stop the bot polling to prevent conflicts"""
    global bot_running, telegram_service
    
    # Only try to stop if we think it's running
    if bot_running and telegram_service:
        try:
            logger.info("Stopping telegram bot updater...")
            instance_id = os.getenv("BOT_INSTANCE_ID", "unknown")
            logger.info(f"Stopping bot with instance ID: {instance_id}")
            
            # Check if the service has polling enabled
            if not hasattr(telegram_service, 'polling_started'):
                logger.warning("Telegram service doesn't have polling_started attribute")
                bot_running = False
                return
                
            if not telegram_service.polling_started:
                logger.info("Telegram polling not started, just clearing webhook")
                try:
                    await telegram_service.bot.delete_webhook(drop_pending_updates=True)
                except Exception as e:
                    logger.warning(f"Error clearing webhook: {str(e)}")
                bot_running = False
                return
                
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
                    try:
                        await telegram_service.application.updater.stop()
                        logger.info("Updater stopped successfully")
                    except Exception as e:
                        logger.warning(f"Error stopping updater: {str(e)}")
                
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
            if telegram_service:
                telegram_service.polling_started = False
            bot_running = False
    else:
        logger.info(f"Not stopping bot: running={bot_running}, telegram_service exists={telegram_service is not None}")

@app.on_event("startup")
async def startup_event():
    global bot_running, telegram_service
    
    try:
        # First ensure any existing bot is stopped
        await stop_bot()
        
        # Initialize the services
        logger.info("Initializing services...")
        
        # Lazy load the telegram service
        telegram_service = get_telegram_service()
        logger.info("Telegram service loaded")
        
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
        
        # Set the commands
        commands = [
            BotCommand("start", "Start the bot and get the welcome message"),
            BotCommand("menu", "Show the main menu"),
            BotCommand("help", "Show available commands and how to use the bot")
        ]
        
        # Initialize the application and start in polling mode
        await telegram_service.application.initialize()
        await telegram_service.application.start()
        
        # Generate a unique identifier for this instance
        instance_id = os.getenv("BOT_INSTANCE_ID", "unknown")
        logger.info(f"Bot instance ID: {instance_id}")
        
        # Determine if we should use polling based on environment
        use_polling = os.getenv("FORCE_POLLING", "").lower() == "true"
        is_local_env = not webhook_url or webhook_url == ""
        
        if use_polling or is_local_env:
            logger.info("Starting bot in polling mode...")
            # Make sure the updater isn't already running
            if hasattr(telegram_service.application, 'updater') and telegram_service.application.updater.running:
                await telegram_service.application.updater.stop()
            
            # Reset any existing sessions to prevent conflicts
            try:
                await telegram_service.bot.delete_webhook(drop_pending_updates=True)
                await asyncio.sleep(1)  # Brief pause after webhook deletion
            except Exception as e:
                logger.warning(f"Error clearing webhook: {str(e)}")
            
            # Start polling with improved parameters
            poll_interval = float(os.getenv("POLL_INTERVAL", "2.0"))
            poll_timeout = int(os.getenv("POLL_TIMEOUT", "60"))
            logger.info(f"Using poll_interval={poll_interval}s, timeout={poll_timeout}s")
            
            try:
                # Use more robust polling options
                await telegram_service.application.updater.start_polling(
                    poll_interval=poll_interval, 
                    timeout=poll_timeout,
                    drop_pending_updates=True,
                    allowed_updates=["message", "callback_query"],
                    read_timeout=90.0,
                    write_timeout=60.0
                )
                telegram_service.polling_started = True
                bot_running = True
                logger.info(f"Bot started in polling mode with instance ID: {instance_id}")
            except Exception as e:
                logger.error(f"Error starting polling: {str(e)}")
                # Continue anyway to allow webhook mode
        else:
            logger.info("Setting up webhook mode...")
            
            # Clear any existing webhook and pending updates
            await telegram_service.bot.delete_webhook(drop_pending_updates=True)
            await asyncio.sleep(1)  # Brief pause
            
            # Set the webhook
            await telegram_service.bot.set_webhook(
                url=f"{webhook_url}/webhook",
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"]
            )
            
            telegram_service.polling_started = False
            bot_running = True
            logger.info(f"Bot set up in webhook mode with URL: {webhook_url}/webhook")
        
        # Set the commands
        await telegram_service.application.bot.set_my_commands(commands)
        
        # Load signals
        await telegram_service._load_signals()
        
        logger.info("Telegram bot initialization completed successfully")
        
        # Manually register signal endpoints
        @app.post("/signal")
        async def process_tradingview_signal(request: Request):
            """Process TradingView webhook signal"""
            try:
                # Make sure we have the telegram service
                global telegram_service
                if not telegram_service:
                    telegram_service = get_telegram_service()
                
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

@app.on_event("shutdown")
async def shutdown_event():
    """Stop the bot when the application shuts down"""
    logger.info("Application shutting down, stopping telegram bot...")
    await stop_bot()

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
    try:
        # Check key services
        services_status = {
            "app": "healthy",
            "telegram_bot": "healthy" if bot_running else "not_running",
            "database": "connected" if db.is_connected() else "disconnected"
        }
        
        # Add additional diagnostics
        diagnostics = {
            "polling_mode": telegram_service.polling_started if hasattr(telegram_service, "polling_started") else "unknown",
            "timestamp": time.time()
        }
        
        logger.info(f"Health check called: {services_status}")
        
        return {
            "status": "healthy",
            "services": services_status,
            "diagnostics": diagnostics
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        logger.exception(e)
        # Still return 200 status but with error details
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": time.time()
        }

@app.get("/restart-bot")
async def restart_bot():
    """Endpoint to restart the telegram bot service"""
    global bot_running
    
    try:
        # First stop the bot if it's running
        await stop_bot()
        
        # Wait a moment to ensure everything is cleared
        await asyncio.sleep(2)
        
        # Restart the bot
        logger.info("Restarting telegram bot...")
        
        # Create new application instance
        telegram_service.application = Application.builder().bot(telegram_service.bot).build()
        
        # Register command handlers manually
        telegram_service.application.add_handler(CommandHandler("start", telegram_service.start_command))
        telegram_service.application.add_handler(CommandHandler("menu", telegram_service.show_main_menu))
        telegram_service.application.add_handler(CommandHandler("help", telegram_service.help_command))
        telegram_service.application.add_handler(CommandHandler("set_subscription", telegram_service.set_subscription_command))
        telegram_service.application.add_handler(CommandHandler("set_payment_failed", telegram_service.set_payment_failed_command))
        telegram_service.application.add_handler(CallbackQueryHandler(telegram_service.button_callback))
        
        # Set the commands
        commands = [
            BotCommand("start", "Start the bot and get the welcome message"),
            BotCommand("menu", "Show the main menu"),
            BotCommand("help", "Show available commands and how to use the bot")
        ]
        
        # Initialize the application and start in polling mode
        await telegram_service.application.initialize()
        await telegram_service.application.start()
        
        # Determine if we should use polling based on environment
        webhook_url = os.getenv("WEBHOOK_URL", "")
        use_polling = os.getenv("FORCE_POLLING", "").lower() == "true"
        is_local_env = not webhook_url or webhook_url == ""
        
        if use_polling or is_local_env:
            logger.info("Restarting bot in polling mode...")
            # Start polling with a longer timeout
            await telegram_service.application.updater.start_polling(poll_interval=1.0, timeout=30)
            telegram_service.polling_started = True
            bot_running = True
            logger.info("Bot restarted in polling mode")
        else:
            logger.info("Skipping polling mode as bot is likely running in webhook mode")
            telegram_service.polling_started = False
            bot_running = True
        
        # Set the commands
        await telegram_service.application.bot.set_my_commands(commands)
        
        # Load signals
        await telegram_service._load_signals()
        
        logger.info("Telegram bot restarted successfully")
        
        return {"status": "success", "message": "Bot restarted successfully"}
    except Exception as e:
        logger.error(f"Error restarting bot: {str(e)}")
        return {"status": "error", "message": str(e)}

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
    # Gebruik PORT environment variabele indien beschikbaar
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("trading_bot.main:app", host="0.0.0.0", port=port)

app = app  # Expliciete herbevestiging van de app variabele
