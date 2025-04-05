import logging
import os
import json
from fastapi import FastAPI, Request, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import stripe
import time
import asyncio
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram import BotCommand
from typing import Dict, Any

# Configureer logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Laad omgevingsvariabelen
load_dotenv()

# Importeer de benodigde services
from trading_bot.services.database.db import Database
from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
from trading_bot.services.calendar_service.calendar import EconomicCalendarService

# Import directly from the module to avoid circular imports through __init__.py
from trading_bot.services.telegram_service.bot import TelegramService
from trading_bot.services.payment_service.stripe_service import StripeService
from trading_bot.services.payment_service.stripe_config import STRIPE_WEBHOOK_SECRET

# Initialiseer de FastAPI app
app = FastAPI()

# Initialiseer de database
db = Database()

# Initialiseer de services in de juiste volgorde
stripe_service = StripeService(db)
telegram_service = TelegramService(db)
chart_service = ChartService()

# Voeg de services aan elkaar toe na initialisatie
telegram_service.stripe_service = stripe_service
stripe_service.telegram_service = telegram_service
telegram_service.chart_service = chart_service

# Transformatiefunctie voor TradingView webhook data
def transform_tradingview_signal(signal_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform TradingView webhook format to the format expected by the signal processor
    
    Args:
        signal_data: Original signal data from TradingView webhook
        
    Returns:
        Transformed signal data ready for processing
    """
    # Maak een kopie om de originele data niet te wijzigen
    transformed = signal_data.copy()
    
    # Verplichte velden transformeren
    
    # 1. Richting: 'signal' naar 'direction' en omzetten naar lowercase
    if 'signal' in transformed and 'direction' not in transformed:
        # Convert to lowercase and ensure it's either 'buy' or 'sell'
        signal = transformed.pop('signal', '').lower()
        if signal in ['buy', 'sell']:
            transformed['direction'] = signal
        elif signal in ['long']:
            transformed['direction'] = 'buy'
        elif signal in ['short']:
            transformed['direction'] = 'sell'
        else:
            # Default to buy if we can't determine
            logger.warning(f"Unknown signal type: {signal}, defaulting to 'buy'")
            transformed['direction'] = 'buy'
    
    # 2. Timeframe: 'interval' naar 'timeframe'
    if 'interval' in transformed and 'timeframe' not in transformed:
        interval = transformed.pop('interval')
        transformed['timeframe'] = convert_interval_to_timeframe(interval)
    
    # 3. Entry price: 'price' naar 'entry'
    if 'price' in transformed and 'entry' not in transformed:
        transformed['entry'] = transformed['price']
    
    # 4. Stop Loss: 'sl' naar 'stop_loss'
    if 'sl' in transformed and 'stop_loss' not in transformed:
        transformed['stop_loss'] = transformed['sl']
    
    # 5. Take Profit: 'tp1' naar 'take_profit'
    if 'tp1' in transformed and 'take_profit' not in transformed:
        transformed['take_profit'] = transformed['tp1']
    
    # 6. Instrument: 'ticker' naar 'instrument'
    if 'ticker' in transformed and 'instrument' not in transformed:
        transformed['instrument'] = transformed.pop('ticker')
    
    # 7. Auto-determine direction based on stop loss vs entry if both exist
    if ('entry' in transformed or 'price' in transformed) and ('stop_loss' in transformed or 'sl' in transformed):
        entry_price = transformed.get('entry', transformed.get('price'))
        stop_loss = transformed.get('stop_loss', transformed.get('sl'))
        
        try:
            entry_float = float(entry_price)
            sl_float = float(stop_loss)
            
            # If stop loss is lower than entry, it's a BUY signal
            # If stop loss is higher than entry, it's a SELL signal
            direction = 'buy' if sl_float < entry_float else 'sell'
            transformed['direction'] = direction
            logger.info(f"Auto-detected signal direction: {direction} based on entry: {entry_price}, stop loss: {stop_loss}")
        except (ValueError, TypeError):
            logger.warning("Could not auto-determine direction from price values")
    
    # 8. Market: voeg toe als het ontbreekt
    if 'market' not in transformed:
        # Detecteer markttype op basis van instrument
        instrument = transformed.get('instrument', '')
        if any(crypto in instrument.upper() for crypto in ['BTC', 'ETH', 'XRP']):
            transformed['market'] = 'crypto'
        elif any(index in instrument.upper() for index in ['SPX', 'NDX', 'DJI']):
            transformed['market'] = 'indices'
        else:
            transformed['market'] = 'forex'
    
    # Log de transformatie voor debugging
    logger.info(f"Transformed signal: {transformed}")
    
    return transformed

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
        
        # Initialize chart service first
        await chart_service.initialize()
        logger.info("Chart service initialized")
        
        # Log environment variables
        webhook_url = os.getenv("WEBHOOK_URL", "")
        logger.info(f"WEBHOOK_URL from environment: '{webhook_url}'")
        
        # Set up Telegram bot with improved error handling
        logger.info("Setting up Telegram bot")
        
        # Create application instance
        telegram_service.application = Application.builder().bot(telegram_service.bot).build()
        
        # Register handlers
        telegram_service._register_handlers(telegram_service.application)
        
        # Load signals
        telegram_service._load_signals()
        
        # Set bot commands
        commands = [
            BotCommand("start", "Start the bot and get the welcome message"),
            BotCommand("menu", "Show the main menu"),
            BotCommand("help", "Show available commands and how to use the bot")
        ]
        
        # Check if we should use webhook mode (preferred for Railway)
        is_production = os.getenv("RAILWAY_ENVIRONMENT") == "production" or os.getenv("RAILWAY_PUBLIC_DOMAIN")
        
        if is_production and webhook_url:
            # Production mode: use webhook 
            logger.info(f"Running in production mode on Railway. Using webhook URL: {webhook_url}")
            
            # Delete any existing webhook and clear pending updates
            await telegram_service.bot.delete_webhook(drop_pending_updates=True)
            
            # Initialize the application
            await telegram_service.application.initialize()
            await telegram_service.application.start()
            
            # Set webhook with no secret token for now
            await telegram_service.bot.set_webhook(url=f"{webhook_url}/webhook")
            logger.info(f"Webhook set to {webhook_url}/webhook")
            
            # Log the webhook info
            webhook_info = await telegram_service.bot.get_webhook_info()
            logger.info(f"Webhook info: {webhook_info.url}, pending updates: {webhook_info.pending_update_count}")
        else:
            # Development mode: use polling
            logger.info("Running in development mode. Using polling for updates.")
            
            # Make sure webhook is removed
            await telegram_service.bot.delete_webhook(drop_pending_updates=True)
            
            # Initialize the application and start in polling mode
            await telegram_service.application.initialize()
            await telegram_service.application.start()
            await telegram_service.application.updater.start_polling(drop_pending_updates=True)
            telegram_service.polling_started = True
            logger.info("Telegram bot started in polling mode")
        
        # Set the commands
        await telegram_service.bot.set_my_commands(commands)
        
        logger.info("Telegram bot initialization completed")
        
        # Manually register signal endpoints
        @app.post("/signal")
        async def process_tradingview_signal(request: Request):
            """Process TradingView webhook signal"""
            try:
                # Get the signal data from the request
                signal_data = await request.json()
                logger.info(f"Received TradingView webhook signal: {signal_data}")
                
                # Transform the signal data to the expected format
                transformed_signal = transform_tradingview_signal(signal_data)
                
                # Process the transformed signal
                success = await telegram_service.process_signal(transformed_signal)
                
                if success:
                    return {"status": "success", "message": "Signal processed successfully"}
                else:
                    return {"status": "error", "message": "Failed to process signal"}
                    
            except Exception as e:
                logger.error(f"Error processing TradingView webhook signal: {str(e)}")
                logger.exception(e)
                return {"status": "error", "message": str(e)}
        
        logger.info("Signal endpoints registered directly on FastAPI app")
        
        # Manually register Telegram webhook endpoint
        @app.post("/webhook")
        async def telegram_webhook(request: Request):
            """Process incoming updates from Telegram webhook"""
            try:
                # Get raw update data
                update_data = await request.json()
                logger.info(f"Received Telegram update: {update_data.get('update_id', 'unknown')}")
                
                # Process the update with the application's process_update method
                # This is the proper way to handle webhook updates in python-telegram-bot v20+
                await telegram_service.application.process_update(update_data)
                return {"status": "success"}
            except Exception as e:
                logger.error(f"Error processing Telegram webhook: {str(e)}")
                logger.exception(e)
                return {"status": "error", "message": str(e)}
        
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
        
        # Transformeer de data naar het juiste format
        transformed_data = transform_tradingview_signal(data)
        
        # Verwerk als TradingView signaal
        if telegram_service:
            success = await telegram_service.process_signal(transformed_data)
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
        
        # Transformeer de data naar het juiste format
        transformed_data = transform_tradingview_signal(signal_data)
        
        # Process the signal directly without checking if enabled
        success = await telegram_service.process_signal(transformed_data)
        
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
    """Endpoint for receiving trading signals in TradingView format"""
    try:
        # Get the signal data from the request
        signal_data = await request.json()
        logger.info(f"Received TradingView webhook signal: {signal_data}")
        
        # Transform the signal data to match our requirements
        transformed_signal = transform_tradingview_signal(signal_data)
        
        # Process the transformed signal
        success = await telegram_service.process_signal(transformed_signal)
        
        if success:
            return {"status": "success", "message": "Signal processed successfully"}
        else:
            return {"status": "error", "message": "Failed to process signal"}
            
    except Exception as e:
        logger.error(f"Error processing TradingView webhook signal: {str(e)}")
        logger.exception(e)
        return {"status": "error", "message": str(e)}

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
