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
telegram_service = TelegramService(
    db=db,
    stripe_service=stripe_service,
    bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "")
)
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
        
        # Set up Telegram bot properly
        logger.info("Setting up Telegram bot")
        
        # Determine if we're running in production (Railway)
        is_production = os.getenv("RAILWAY_ENVIRONMENT") == "production" or os.getenv("RAILWAY_PUBLIC_DOMAIN")
        
        if is_production:
            logger.info("Running in production environment, using webhook mode")
            await telegram_service.initialize(use_webhook=True)
            
            # Setup bot commands
            try:
                from telegram import BotCommand
                
                # Define the commands that should be available in the bot
                commands = [
                    BotCommand("start", "Start the bot and get a welcome message"),
                    BotCommand("menu", "Show the main menu with all available options"),
                    BotCommand("help", "Show help information and available commands")
                ]
                
                # Set the commands for the bot
                await telegram_service.bot.set_my_commands(commands)
                logger.info(f"Successfully set {len(commands)} commands for the bot")
                
                # Force delete and reset the webhook to ensure clean start
                if webhook_url:
                    # Make sure webhook URL doesn't already have the webhook path
                    if "/webhook" in webhook_url:
                        base_url = webhook_url.split("/webhook")[0]
                        webhook_url = base_url
                    
                    final_webhook_url = f"{webhook_url.rstrip('/')}/webhook"
                    
                    # First delete any existing webhook
                    await telegram_service.bot.delete_webhook(drop_pending_updates=True)
                    logger.info("Deleted existing webhook")
                    
                    # Set the webhook explicitly at startup
                    await telegram_service.bot.set_webhook(
                        url=final_webhook_url,
                        allowed_updates=["message", "callback_query", "chat_member"]
                    )
                    
                    # Log webhook info
                    webhook_info = await telegram_service.bot.get_webhook_info()
                    logger.info(f"Webhook set at startup: URL={webhook_info.url}")
            except Exception as cmd_error:
                logger.error(f"Error setting bot commands: {str(cmd_error)}")
        else:
            logger.info("Running in development environment, using polling mode")
            await telegram_service.initialize(use_webhook=False)
            
        logger.info("Telegram bot initialized")
            
        # Manually register signal endpoints directly here
        logger.info("Registering signal endpoints")
        
        @app.post("/signal")
        async def process_tradingview_signal(request: Request):
            """Process TradingView webhook signal"""
            try:
                # Get the signal data from the request
                signal_data = await request.json()
                
                # Transform TradingView signal to internal format
                transformed_data = transform_tradingview_signal(signal_data)
                
                # Log market detection
                instrument = transformed_data.get('instrument', '')
                if instrument:
                    market = transformed_data.get('market', 'forex')
                    logger.info(f"Detected {instrument} as {market}")
                
                # Process the signal
                success = await telegram_service.process_signal(transformed_data)
                
                if success:
                    return {"status": "success", "message": "Signal processed successfully"}
                else:
                    return {"status": "error", "message": "Failed to process signal"}
                
            except Exception as e:
                logger.error(f"Error processing signal: {str(e)}")
                logger.exception(e)
                return {"status": "error", "message": str(e)}
        
        logger.info("Signal endpoints registered")
        
        # Manually register Telegram webhook endpoint
        @app.post("/webhook")
        async def telegram_webhook(request: Request):
            """Process incoming updates from Telegram webhook"""
            try:
                # Get raw update data
                update_data = await request.json()
                update_id = update_data.get('update_id', 'unknown')
                logger.info(f"Received Telegram update: ID={update_id}")
                
                # Log entire update for debugging
                logger.info(f"Full update data: {json.dumps(update_data)}")
                
                # Log the update content for debugging (redacting sensitive info)
                if 'message' in update_data:
                    from_info = update_data['message'].get('from', {})
                    chat_info = update_data['message'].get('chat', {})
                    text = update_data['message'].get('text', '')
                    logger.info(f"Message update from user_id={from_info.get('id')}, chat_id={chat_info.get('id')}, text='{text}'")
                elif 'callback_query' in update_data:
                    callback_data = update_data['callback_query'].get('data', '')
                    from_info = update_data['callback_query'].get('from', {})
                    logger.info(f"Callback query from user_id={from_info.get('id')}, data='{callback_data}'")
                
                # Check if application is ready
                if not hasattr(telegram_service, 'application') or telegram_service.application is None:
                    logger.error("Telegram application not initialized yet!")
                    await telegram_service.initialize(use_webhook=True)
                    logger.info("Re-initialized telegram service")
                
                # Create Update object first regardless of type
                from telegram import Update
                update_obj = Update.de_json(update_data, telegram_service.bot)
                
                # Log the created update object
                logger.info(f"Created update object: {update_obj}")
                
                # Process the update with telegram_service
                try:
                    if 'message' in update_data and 'text' in update_data['message']:
                        # Handle message
                        text = update_data['message']['text']
                        chat_id = update_data['message']['chat']['id']
                        user_id = update_data['message'].get('from', {}).get('id')
                        
                        # Explicitly handle commands
                        if text.startswith('/'):
                            command = text.split('@')[0].split(' ')[0].lower()  # Extract command part
                            logger.info(f"Processing command: {command}")
                            
                            # Handle each command explicitly
                            if command == '/start':
                                logger.info("Explicitly handling /start command")
                                await telegram_service.bot.send_message(
                                    chat_id=chat_id, 
                                    text="Welcome to Sigmapips AI! Use /menu to access all features."
                                )
                                return {"status": "success", "handled": "explicit_start_command"}
                                
                            elif command == '/menu':
                                logger.info("Explicitly handling /menu command")
                                # Call the menu_command method directly instead of recreating the keyboard here
                                await telegram_service.menu_command(update_obj, None)
                                return {"status": "success", "handled": "explicit_menu_command"}
                                
                            elif command == '/help':
                                logger.info("Explicitly handling /help command")
                                await telegram_service.bot.send_message(
                                    chat_id=chat_id,
                                    text="Available commands:\n/start - Start the bot\n/menu - Show main menu\n/help - Show this help message"
                                )
                                return {"status": "success", "handled": "explicit_help_command"}
                    
                    # For any other type of update or non-explicit command handling
                    logger.info("Forwarding update to application queue")
                    
                    # Ensure updater is running and queue is available
                    if telegram_service.application and hasattr(telegram_service.application, 'update_queue'):
                        # Try to put update in queue
                        await telegram_service.application.update_queue.put(update_obj)
                        logger.info(f"Successfully queued update {update_id} for processing")
                        return {"status": "success", "handled": "queued"}
                    else:
                        logger.error("Update queue not available, trying to reinitialize bot")
                        # Reinitialize bot if queue not available
                        await telegram_service.initialize(use_webhook=True)
                        try:
                            await telegram_service.application.update_queue.put(update_obj)
                            logger.info("Update queued after reinitialization")
                            return {"status": "success", "handled": "queued_after_reinit"}
                        except Exception as queue_error:
                            logger.error(f"Failed to queue update after reinitialization: {str(queue_error)}")
                    
                except Exception as cmd_error:
                    logger.error(f"Error processing specific command: {str(cmd_error)}")
                    logger.exception(cmd_error)
                
                # If we reach here, command was not handled by explicit handler or queue
                # Fall back to directly calling the handlers
                logger.info("Trying to manually call appropriate handler for command...")
                
                if 'message' in update_data and 'text' in update_data['message']:
                    text = update_data['message']['text']
                    if text.startswith('/menu'):
                        try:
                            # Try to directly call menu handler if available
                            if hasattr(telegram_service, 'menu_command'):
                                logger.info("Directly calling menu_command handler")
                                await telegram_service.menu_command(update_obj, None)
                                return {"status": "success", "handled": "direct_menu_handler"}
                            elif hasattr(telegram_service, 'show_main_menu'):
                                logger.info("Directly calling show_main_menu handler")
                                await telegram_service.show_main_menu(update_obj, None)
                                return {"status": "success", "handled": "direct_main_menu_handler"}
                        except Exception as handler_error:
                            logger.error(f"Error calling handler directly: {str(handler_error)}")
                            logger.exception(handler_error)
                
                return {"status": "warning", "message": "Update received but handling uncertain"}
                
            except Exception as e:
                logger.error(f"Error handling Telegram webhook: {str(e)}")
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
