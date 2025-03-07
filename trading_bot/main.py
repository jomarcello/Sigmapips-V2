import sys
import logging
from fastapi import FastAPI, HTTPException, Request, Depends
import os
from typing import Dict, Any
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
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
async def telegram_webhook(request: Request):
    """Handle Telegram webhook"""
    try:
        # Log dat de webhook is aangeroepen
        logger.info("Webhook aangeroepen")
        
        # Haal de update data op
        update_data = await request.json()
        logger.info(f"Webhook data: {update_data}")
        
        # Verwerk de update via de TelegramService
        await telegram.process_update(update_data)
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error in webhook: {str(e)}")
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
        
        # Voeg de process_signal methode toe aan TelegramService als deze nog niet bestaat
        if not hasattr(telegram, 'process_signal'):
            # Implementeer de methode dynamisch
            async def process_signal(self, signal_data):
                """Process a trading signal and send it to subscribed users."""
                try:
                    # Log het ontvangen signaal
                    logger.info(f"Processing signal: {signal_data}")
                    
                    # Haal de relevante informatie uit het signaal
                    instrument = signal_data.get('instrument')
                    timeframe = signal_data.get('timeframe', '1h')  # Default to 1h if not provided
                    direction = signal_data.get('direction')
                    price = signal_data.get('price')
                    stop_loss = signal_data.get('stop_loss')
                    take_profit = signal_data.get('take_profit')
                    message = signal_data.get('message')
                    market = signal_data.get('market', 'forex')
                    strategy = signal_data.get('strategy', 'Test Strategy')
                    risk_management = signal_data.get('risk_management', ["Position size: 1-2% max", "Use proper stop loss", "Follow your trading plan"])
                    verdict = signal_data.get('verdict', '')
                    
                    # Converteer het signaal naar het formaat dat match_subscribers verwacht
                    signal_for_matching = {
                        'market': market,
                        'symbol': instrument,
                        'timeframe': timeframe,
                        'direction': direction,
                        'price': price,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'message': message
                    }
                    
                    # Gebruik de match_subscribers methode om de juiste gebruikers te vinden
                    matched_subscribers = await self.db.match_subscribers(signal_for_matching)
                    
                    if not matched_subscribers:
                        logger.info(f"No users subscribed to {instrument} {timeframe} signals")
                        return True
                    
                    # Maak het signaal bericht
                    signal_message = f"🎯 <b>New Trading Signal</b> 🎯\n\n"
                    signal_message += f"Instrument: {instrument}\n"
                    signal_message += f"Action: {direction.upper()} {'📈' if direction.lower() == 'buy' else '📉'}\n\n"
                    
                    signal_message += f"Entry Price: {price}\n"
                    
                    if stop_loss:
                        signal_message += f"Stop Loss: {stop_loss} {'🔴' if stop_loss else ''}\n"
                    
                    if take_profit:
                        signal_message += f"Take Profit: {take_profit} {'🎯' if take_profit else ''}\n\n"
                    
                    signal_message += f"Timeframe: {timeframe}\n"
                    signal_message += f"Strategy: {strategy}\n\n"
                    
                    signal_message += f"{'—'*20}\n\n"
                    
                    signal_message += f"<b>Risk Management:</b>\n"
                    for tip in risk_management:
                        signal_message += f"• {tip}\n"
                    
                    signal_message += f"\n{'—'*20}\n\n"
                    
                    signal_message += f"🤖 <b>SigmaPips AI Verdict:</b>\n"
                    if verdict:
                        signal_message += f"{verdict}\n"
                    else:
                        signal_message += f"The {instrument} {direction.lower()} signal shows a promising setup with a favorable risk/reward ratio. Entry at {price} with defined risk parameters offers a good trading opportunity.\n"
                    
                    # Stuur het signaal naar alle geabonneerde gebruikers
                    for subscriber in matched_subscribers:
                        try:
                            user_id = subscriber['user_id']
                            await self.bot.send_message(
                                chat_id=user_id,
                                text=signal_message,
                                parse_mode='HTML'
                            )
                            logger.info(f"Sent signal to user {user_id}")
                        except Exception as user_error:
                            logger.error(f"Error sending signal to user {subscriber['user_id']}: {str(user_error)}")
                    
                    return True
                except Exception as e:
                    logger.error(f"Error processing signal: {str(e)}")
                    return False
            
            # Voeg de methode toe aan de TelegramService klasse
            import types
            telegram.process_signal = types.MethodType(process_signal, telegram)
        
        # Verwerk het signaal
        success = await telegram.process_signal(signal_data)
        
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
        return await signal_webhook(MockRequest())
        
    except Exception as e:
        logger.error(f"Error processing signal: {str(e)}")
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

# Rest van de code blijft hetzelfde... 
