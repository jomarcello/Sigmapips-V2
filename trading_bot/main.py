import sys
import logging
from fastapi import FastAPI, HTTPException, Request, Depends
import os
from typing import Dict, Any
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import asyncio
import time
import base64
import aiohttp
import json
import redis
from fastapi.responses import JSONResponse

# Import de constanten
from trading_bot.services.telegram_service.bot import (
    WELCOME_MESSAGE, 
    START_KEYBOARD,
    HELP_MESSAGE
)

# Correcte imports
from trading_bot.services.telegram_service.bot import TelegramService
from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.database.db import Database
from trading_bot.services.chart_service.session_refresher import SessionRefresher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
port = int(os.getenv("PORT", 8080))

# Initialize services once
db = Database()
telegram = TelegramService(db)
asyncio.create_task(telegram.initialize(use_webhook=True))
chart = ChartService()

# Redis configuratie
redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", 6379))
redis_password = os.getenv("REDIS_PASSWORD", None)

# Verbeterde Redis-verbinding met retry-logica
try:
    redis_client = redis.Redis(
        host=redis_host,
        port=redis_port,
        password=redis_password,
        db=0,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_keepalive=True,
        retry_on_timeout=True,
        health_check_interval=30
    )
    # Test de verbinding
    redis_client.ping()
    logger.info(f"Redis connection established to {redis_host}:{redis_port}")
except Exception as redis_error:
    logger.warning(f"Redis connection failed: {str(redis_error)}. Using local caching.")
    redis_client = None

# Remove TradingBot class or update it
class TradingBot:
    def __init__(self):
        self.db = db  # Use existing instance
        self.telegram = telegram  # Use existing instance
        self.chart = chart  # Use existing instance

# Initialiseer de bot
bot = TradingBot()

# Initialiseer de session refresher
session_refresher = SessionRefresher()

@app.on_event("startup")
async def startup_event():
    """Startup event handler"""
    try:
        # Initialize telegram service
        await telegram.initialize(use_webhook=True)
        
        # Initialize chart service
        await initialize_chart_service_background()
        
        # Set webhook URL
        webhook_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
        if webhook_url:
            # Strip any trailing characters including semicolons
            webhook_url = webhook_url.strip().rstrip(';')
            full_url = f"https://{webhook_url}/webhook"
            
            # Verwijder eerst eventuele bestaande webhook
            await telegram.bot.delete_webhook()
            
            # Stel de nieuwe webhook in
            await telegram.bot.set_webhook(url=full_url)
            
            # Haal webhook info op om te controleren
            webhook_info = await telegram.bot.get_webhook_info()
            
            logger.info(f"Webhook succesvol ingesteld op: {full_url}")
            logger.info(f"Webhook info: {webhook_info}")
        
        # Start een achtergrondtaak voor periodieke health checks
        asyncio.create_task(periodic_health_check())
        
    except Exception as e:
        logger.error(f"Error in startup event: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown"""
    try:
        await chart.cleanup()
        logger.info("Chart service resources cleaned up")
    except Exception as e:
        logger.error(f"Error cleaning up chart service: {str(e)}")
    
    # Stop de session refresher
    await session_refresher.stop()

@app.get("/health")
async def health_check():
    """Health check endpoint voor Railway"""
    return {"status": "ok"}

@app.post("/webhook")
async def webhook(request: Request):
    """Webhook endpoint voor Telegram"""
    try:
        logger.info("Webhook aangeroepen")
        
        # Haal de update data op
        update_data = await request.json()
        
        # Log de update data
        logger.info(f"Webhook data: {update_data}")
        
        # Controleer of het een callback query is
        if 'callback_query' in update_data:
            callback_data = update_data['callback_query']['data']
            logger.info(f"Callback data: {callback_data}")
            
            # Als het een analyze_market callback is, verwerk deze direct
            if callback_data.startswith('analyze_market_'):
                logger.info(f"Verwerking analyze_market callback: {callback_data}")
                
                # Maak een Update object
                update = Update.de_json(data=update_data, bot=telegram.bot)
                
                # Stuur de update naar de telegram service voor verwerking
                # Laat de application de context aanmaken
                await telegram.process_update(update_data)
                
                return {"status": "success"}
        
        # Stuur de update naar de telegram service
        success = await telegram.process_update(update_data)
        
        if success:
            return {"status": "success"}
        else:
            return {"status": "error", "message": "Failed to process update"}
    
    except Exception as e:
        logger.error(f"Error in webhook: {str(e)}")
        logger.exception(e)
        return {"status": "error", "message": str(e)}

def _detect_market(symbol: str) -> str:
    """Detecteer market type gebaseerd op symbol"""
    symbol = symbol.upper()
    
    # Commodities eerst checken
    commodities = [
        "XAUUSD",  # Gold
        "XAGUSD",  # Silver
        "WTIUSD",  # Oil WTI
        "BCOUSD",  # Oil Brent
    ]
    if symbol in commodities:
        logger.info(f"Detected {symbol} as commodity")
        return "commodities"
    
    # Crypto pairs
    crypto_base = ["BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "DOT", "LINK"]
    if any(c in symbol for c in crypto_base):
        logger.info(f"Detected {symbol} as crypto")
        return "crypto"
    
    # Major indices
    indices = [
        "US30", "US500", "US100",  # US indices
        "UK100", "DE40", "FR40",   # European indices
        "JP225", "AU200", "HK50"   # Asian indices
    ]
    if symbol in indices:
        logger.info(f"Detected {symbol} as index")
        return "indices"
    
    # Forex pairs als default
    logger.info(f"Detected {symbol} as forex")
    return "forex"

@app.post("/webhook/signal")
async def signal_webhook(request: Request):
    """Handle trading signal webhook"""
    try:
        # Haal de signal data op uit de request
        signal_data = await request.json()
        logger.info(f"Received signal data: {signal_data}")
        
        # Valideer de signal data
        required_fields = ['instrument', 'direction', 'price']
        missing_fields = [field for field in required_fields if field not in signal_data]
        
        if missing_fields:
            logger.error(f"Missing required fields in signal data: {missing_fields}")
            return {"status": "error", "message": f"Missing required fields: {', '.join(missing_fields)}"}
        
        # Gebruik DeepSeek om het signaal te verwerken en te formatteren
        try:
            formatted_signal = await process_signal_with_deepseek(signal_data)
            if formatted_signal:
                signal_data = formatted_signal
        except Exception as deepseek_error:
            logger.error(f"Error processing signal with DeepSeek: {str(deepseek_error)}")
            # Ga door met het originele signaal als DeepSeek faalt
        
        # Detecteer de markt op basis van het instrument
        market = _detect_market(signal_data['instrument'])
        signal_data['market'] = market
        
        # Verwerk het signaal
        if hasattr(telegram, 'process_signal'):
            # Roep de methode aan met de juiste parameters
            success = await telegram.process_signal(signal_data)
        else:
            logger.error("process_signal method not found on telegram service")
            success = False
        
        # Stuur een test bericht met knoppen
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            
            keyboard = [
                [InlineKeyboardButton("Test Button", callback_data="test_button")]
            ]
            
            await telegram.bot.send_message(
                chat_id="YOUR_TEST_CHAT_ID",  # Vervang dit door je eigen chat ID
                text="Test button:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            logger.info("Sent test button directly from webhook")
        except Exception as button_error:
            logger.error(f"Error sending test button: {str(button_error)}")
            logger.exception(button_error)
        
        if success:
            return {"status": "success", "message": "Signal processed successfully"}
        else:
            return {"status": "error", "message": "Failed to process signal"}
    except Exception as e:
        logger.error(f"Error in signal webhook: {str(e)}")
        return {"status": "error", "message": str(e)}

async def process_signal_with_deepseek(signal_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gebruik DeepSeek AI om het signaal te verwerken en te formatteren.
    
    Args:
        signal_data: Het ruwe signaal dat is ontvangen
        
    Returns:
        Dict: Het geformatteerde signaal
    """
    try:
        import aiohttp
        
        # DeepSeek API configuratie
        api_key = "sk-274ea5952e7e4b87aba4b14de3990c7d"
        api_url = "https://api.deepseek.com/v1/chat/completions"
        
        # Maak een prompt voor DeepSeek
        prompt = f"""
        You are an expert trading signal processor. Your task is to analyze the following raw trading signal and format it into a structured format.

        Raw signal data:
        {json.dumps(signal_data, indent=2)}
        
        Process this signal and provide a structured JSON output with the following fields:
        - instrument: The trading instrument (e.g., EURUSD, BTCUSD)
        - direction: The direction of the trade (buy or sell)
        - price: The entry price
        - stop_loss: The stop loss level (if available)
        - take_profit: The take profit level (if available)
        - timeframe: The timeframe of the trade (e.g., 1m, 15m, 1h, 4h)
        - strategy: A short name for the strategy (e.g., "Trend Following", "Breakout", "Support/Resistance")
        - risk_management: A list of risk management tips (e.g., ["Position size: 1-2% max", "Use proper stop loss"])
        - message: A detailed analysis of the trade
        - verdict: A short conclusion about the trade setup
        
        If fields are missing in the raw signal, try to extract them from the available text or fill them in based on your expertise.
        All content must be in English.
        Only return the JSON output, no additional text.
        """
        
        # Maak de request naar DeepSeek
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are an expert trading signal processor."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 1000
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    ai_response = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    # Probeer de JSON uit de response te extraheren
                    try:
                        # Zoek naar JSON in de response
                        import re
                        json_match = re.search(r'```json\n(.*?)\n```', ai_response, re.DOTALL)
                        
                        if json_match:
                            json_str = json_match.group(1)
                        else:
                            # Als er geen code block is, probeer de hele tekst als JSON te parsen
                            json_str = ai_response
                        
                        formatted_signal = json.loads(json_str)
                        logger.info(f"DeepSeek formatted signal: {formatted_signal}")
                        return formatted_signal
                    except json.JSONDecodeError as json_error:
                        logger.error(f"Error parsing DeepSeek response as JSON: {str(json_error)}")
                        logger.error(f"DeepSeek response: {ai_response}")
                        return None
                else:
                    logger.error(f"DeepSeek API error: {response.status} - {await response.text()}")
                    return None
    except Exception as e:
        logger.error(f"Error in process_signal_with_deepseek: {str(e)}")
        return None

@app.post("/signal")
async def receive_signal(signal: Dict[str, Any]):
    """Receive and process trading signal"""
    try:
        logger.info(f"Received TradingView signal: {signal}")
        
        # Detect market type
        market_type = _detect_market(signal.get('instrument', ''))
        signal['market'] = market_type
        
        # Maak een mock request object
        class MockRequest:
            async def json(self):
                return signal
        
        # Stuur het signaal naar de webhook
        mock_request = MockRequest()
        return await signal_webhook(mock_request)
        
    except Exception as e:
        logger.error(f"Error processing signal: {str(e)}")
        logger.exception(e)  # Log de volledige stacktrace
        return {"status": "error", "message": str(e)}

@app.post("/test-signal")
async def send_test_signal():
    """Endpoint om een test signaal te versturen"""
    try:
        # Maak een test signaal
        test_signal = {
            "instrument": "EURUSD",
            "direction": "buy",
            "price": 1.0850,
            "stop_loss": 1.0800,
            "take_profit": 1.0950,
            "timeframe": "1h",
            "message": "Strong bullish momentum detected on EURUSD. Entry at 1.0850 with stop loss at 1.0800 and take profit at 1.0950."
        }
        
        # Maak een mock request object
        class MockRequest:
            async def json(self):
                return test_signal
        
        # Stuur het test signaal naar de webhook
        response = await signal_webhook(MockRequest())
        
        return {"status": "success", "message": "Test signal sent", "response": response}
    except Exception as e:
        logger.error(f"Error sending test signal: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.post("/test-webhook")
async def test_webhook():
    """Test endpoint voor de webhook"""
    logger.info("Test webhook endpoint aangeroepen")
    return {"status": "success"}

@app.get("/test-chart/{instrument}")
async def test_chart(instrument: str):
    """Test endpoint voor de chart service"""
    try:
        logger.info(f"Test chart endpoint aangeroepen voor instrument: {instrument}")
        
        # Haal de chart op
        chart_image = await chart.get_chart(instrument)
        
        if not chart_image:
            logger.error(f"Failed to get chart for {instrument}")
            return {"status": "error", "message": f"Failed to get chart for {instrument}"}
        
        logger.info(f"Successfully got chart for {instrument}, size: {len(chart_image)} bytes")
        
        # Converteer de bytes naar base64 voor weergave in de browser
        chart_base64 = base64.b64encode(chart_image).decode('utf-8')
        
        # Retourneer een HTML-pagina met de afbeelding
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Chart Test</title>
        </head>
        <body>
            <h1>Chart for {instrument}</h1>
            <img src="data:image/png;base64,{chart_base64}" alt="Chart for {instrument}" />
        </body>
        </html>
        """
        
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error in test chart endpoint: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/test-button")
async def test_button():
    """Test endpoint voor knoppen"""
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = [[InlineKeyboardButton("Test Button", callback_data="test_button")]]
        
        # Stuur een bericht naar een specifieke gebruiker (vervang dit door een echte gebruikers-ID)
        user_id = 123456789  # Vervang dit door een echte gebruikers-ID
        
        await telegram.bot.send_message(
            chat_id=user_id,
            text="Test button:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return {"status": "success", "message": "Test button sent"}
    except Exception as e:
        logger.error(f"Error sending test button: {str(e)}")
        logger.exception(e)
        return {"status": "error", "message": str(e)}

@app.get("/test-callback/{instrument}")
async def test_callback(instrument: str):
    """Test endpoint voor callbacks"""
    try:
        # Maak een mock update
        update_data = {
            "update_id": 123456789,
            "callback_query": {
                "id": "123456789",
                "from": {
                    "id": 2004519703,
                    "is_bot": False,
                    "first_name": "Test",
                    "username": "test_user"
                },
                "message": {
                    "message_id": 123,
                    "from": {
                        "id": 7328581013,
                        "is_bot": True,
                        "first_name": "SigmapipsAI",
                        "username": "SignapipsAI_bot"
                    },
                    "chat": {
                        "id": 2004519703,
                        "first_name": "Test",
                        "username": "test_user",
                        "type": "private"
                    },
                    "date": int(time.time()),
                    "text": "Test message"
                },
                "chat_instance": "123456789",
                "data": f"analyze_market_{instrument}"
            }
        }
        
        # Maak een Update object
        update = Update.de_json(data=update_data, bot=telegram.bot)
        
        # Maak een context object
        context = ContextTypes.DEFAULT_TYPE.context
        context.user_data = {}
        
        # Verwerk de callback direct
        await telegram.callback_query_handler(update, context)
        
        return {"status": "success", "message": f"Test callback for {instrument} processed"}
    except Exception as e:
        logger.error(f"Error in test callback: {str(e)}")
        logger.exception(e)
        return {"status": "error", "message": str(e)}

# Rest van de code blijft hetzelfde...

async def initialize_chart_service_background():
    """Initialize chart service in the background"""
    try:
        global chart
        logger.info("Initializing chart service...")
        success = await chart.initialize()
        if success:
            logger.info(f"Chart service initialized with: {type(chart.tradingview).__name__ if chart.tradingview else 'None'}")
        else:
            logger.warning("Chart service initialization failed, will use fallback methods")
        
        # Start de session refresher
        asyncio.create_task(session_refresher.start())
    except Exception as e:
        logger.error(f"Error initializing chart service: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

async def periodic_health_check():
    """Periodieke health check om te controleren of de applicatie nog draait"""
    while True:
        try:
            logger.info("Periodic health check: Application is running")
            await asyncio.sleep(60)  # Elke minuut
        except Exception as e:
            logger.error(f"Error in periodic health check: {str(e)}")

# Verplaats deze code naar het einde van het bestand
if __name__ == "__main__":
    # Controleer of de bot correct is geïnitialiseerd
    if telegram:
        logger.info(f"Bot instance: {telegram.bot}")

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/debug/subscribers")
async def debug_subscribers():
    """Debug endpoint om alle abonnees te bekijken"""
    try:
        # Haal alle abonnees op
        subscribers = await db.execute_query("SELECT * FROM subscriber_preferences")
        
        return {"status": "success", "subscribers": subscribers}
    except Exception as e:
        logger.error(f"Error getting subscribers: {str(e)}")
        return {"status": "error", "message": str(e)} 
