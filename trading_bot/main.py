import sys
import logging
from fastapi import FastAPI, HTTPException, Request
import os
from typing import Dict, Any
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
import asyncio
import time
import base64
import aiohttp
import json
import redis

# Import hack voor ontbrekende module
from trading_bot.services.chart_service.tradingview_selenium import TradingViewSeleniumService
sys.modules['trading_bot.services.chart_service.tradingview_puppeteer'] = type('', (), {
    'TradingViewPuppeteerService': TradingViewSeleniumService
})()

# Import de constanten
from trading_bot.services.telegram_service.bot import (
    WELCOME_MESSAGE, 
    START_KEYBOARD,
    HELP_MESSAGE
)

# Correcte absolute imports
from trading_bot.services.telegram_service.bot import TelegramService
from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.database.db import Database

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

@app.on_event("startup")
async def startup_event():
    """Initialize async services on startup"""
    await telegram.initialize()
    
    # Initialize chart service
    try:
        await chart.initialize()
        logger.info("Chart service initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing chart service: {str(e)}")
    
    webhook_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if webhook_url:
        # Strip any trailing characters including semicolons
        webhook_url = webhook_url.strip().rstrip(';')
        full_url = f"https://{webhook_url}/webhook"
        await telegram.set_webhook(full_url)
        logger.info(f"Webhook set to: {full_url}")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown"""
    try:
        await chart.cleanup()
        logger.info("Chart service resources cleaned up")
    except Exception as e:
        logger.error(f"Error cleaning up chart service: {str(e)}")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/webhook")
async def webhook(request: Request):
    """Webhook endpoint voor Telegram updates"""
    try:
        logger.info("Webhook aangeroepen")
        data = await request.json()
        logger.info(f"Webhook data: {data}")
        
        # Verwerk de update
        await telegram.process_update(data)
        
        return {"status": "success"}
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

@app.post("/signal")
async def receive_signal(signal: Dict[str, Any]):
    """Receive and process trading signal"""
    try:
        logger.info(f"Received TradingView signal: {signal}")
        
        # Detect market type
        market_type = _detect_market(signal.get('instrument', ''))
        signal['market'] = market_type
        
        # Broadcast signal to subscribers
        await telegram.broadcast_signal(signal)
        
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error processing signal: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.post("/test-signal")
async def send_test_signal():
    """Endpoint om een test signaal te versturen"""
    try:
        await telegram.send_test_signal()
        return {"status": "success", "message": "Test signal sent"}
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

@app.get("/test-tradingview/{instrument}")
async def test_tradingview(instrument: str):
    """Test endpoint voor de TradingView integratie"""
    try:
        logger.info(f"Test TradingView endpoint aangeroepen voor instrument: {instrument}")
        
        # Normaliseer instrument
        instrument = instrument.upper().replace("/", "")
        
        # Controleer of we een link hebben voor dit instrument
        if instrument in chart.chart_links:
            chart_url = chart.chart_links[instrument]
            
            # Haal screenshot op
            if chart.tradingview and chart.tradingview.is_logged_in:
                screenshot = await chart.tradingview.get_chart_screenshot(chart_url)
                
                if screenshot:
                    logger.info(f"Successfully got TradingView screenshot for {instrument}")
                    
                    # Converteer de bytes naar base64 voor weergave in de browser
                    screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                    
                    # Retourneer een HTML-pagina met de afbeelding
                    html_content = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>TradingView Test</title>
                    </head>
                    <body>
                        <h1>TradingView Screenshot for {instrument}</h1>
                        <img src="data:image/png;base64,{screenshot_base64}" alt="TradingView Screenshot for {instrument}" />
                    </body>
                    </html>
                    """
                    
                    from fastapi.responses import HTMLResponse
                    return HTMLResponse(content=html_content)
                else:
                    return {"status": "error", "message": f"Failed to get TradingView screenshot for {instrument}"}
            else:
                return {"status": "error", "message": "TradingView service not initialized or not logged in"}
        else:
            return {"status": "error", "message": f"No chart link found for instrument: {instrument}"}
    except Exception as e:
        logger.error(f"Error in test TradingView endpoint: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/health-tradingview")
async def health_tradingview():
    """Controleer de gezondheid van de TradingView service"""
    try:
        if chart.tradingview and chart.tradingview.is_logged_in:
            return {
                "status": "healthy",
                "tradingview": "logged_in",
                "message": "TradingView service is running and logged in"
            }
        elif chart.tradingview:
            return {
                "status": "warning",
                "tradingview": "initialized_not_logged_in",
                "message": "TradingView service is running but not logged in"
            }
        else:
            return {
                "status": "warning",
                "tradingview": "not_initialized",
                "message": "TradingView service is not initialized"
            }
    except Exception as e:
        return {
            "status": "error",
            "tradingview": "error",
            "message": f"Error checking TradingView service: {str(e)}"
        }

@app.get("/login-tradingview")
async def login_tradingview():
    """Handmatig inloggen op TradingView"""
    try:
        if not chart.tradingview:
            # We gebruiken nu de ChartService die intern Puppeteer gebruikt
            pass
        
        if chart.tradingview.is_logged_in:
            return {
                "status": "success",
                "message": "Already logged in to TradingView"
            }
        
        success = await chart.tradingview.login()
        if success:
            return {
                "status": "success",
                "message": "Successfully logged in to TradingView"
            }
        else:
            return {
                "status": "error",
                "message": "Failed to log in to TradingView"
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error logging in to TradingView: {str(e)}"
        }

def initialize_services():
    """Initialize all services"""
    return {
        "db": db,
        "telegram": telegram,
        "chart": chart
    }

def main():
    # ... bestaande code ...
    
    # Commentaar de TradingView code uit
    # Initialiseer TradingView service
    # tradingview_service = TradingViewService()
    
    # Haal inloggegevens uit omgevingsvariabelen
    # tradingview_username = os.getenv("TRADINGVIEW_USERNAME")
    # tradingview_password = os.getenv("TRADINGVIEW_PASSWORD")
    
    # Log in op TradingView
    # if tradingview_username and tradingview_password:
    #     tradingview_service.login_tradingview(tradingview_username, tradingview_password)
    
    # ... bestaande code ...
    
    # Zorg ervoor dat de driver wordt afgesloten bij het afsluiten van de applicatie
    try:
        # ... bestaande code ...
        pass
    finally:
        # tradingview_service.close()
        pass

# ... bestaande code ...

@app.get("/batch-screenshots")
async def batch_screenshots(symbols: str = None, timeframes: str = None):
    """Verbeterde API endpoint voor screenshots met betere error handling"""
    try:
        # Log de request
        logger.info(f"Batch screenshots request with symbols={symbols}, timeframes={timeframes}")
        
        # Converteer comma-gescheiden strings naar lijsten
        symbol_list = symbols.split(",") if symbols else None
        timeframe_list = timeframes.split(",") if timeframes else None
        
        # Controleer TradingView service
        if not hasattr(chart, 'tradingview'):
            logger.error("TradingView service not initialized")
            return {
                "status": "error",
                "message": "TradingView service niet geïnitialiseerd"
            }
            
        # Controleer login status
        if not chart.tradingview.is_logged_in:
            logger.warning("TradingView service not logged in, attempting login")
            login_success = await chart.tradingview.login()
            if not login_success:
                return {
                    "status": "error",
                    "message": "Kon niet inloggen bij TradingView"
                }
        
        # Roep de batch capture functie aan
        results = await chart.tradingview.batch_capture_charts(
            symbols=symbol_list,
            timeframes=timeframe_list
        )
        
        if not results:
            logger.error("Batch capture returned no results")
            return {
                "status": "error",
                "message": "Geen screenshots gemaakt"
            }
        
        # Converteer resultaten naar base64 voor de response
        response_data = {}
        for symbol, timeframe_data in results.items():
            response_data[symbol] = {}
            for timeframe, screenshot in timeframe_data.items():
                if screenshot is not None:
                    response_data[symbol][timeframe] = base64.b64encode(screenshot).decode('utf-8')
        
        logger.info(f"Successfully generated {sum(len(tf) for tf in response_data.values())} screenshots")
        
        return {
            "status": "success",
            "data": response_data
        }
        
    except Exception as e:
        logger.error(f"Error in batch screenshots endpoint: {str(e)}")
        return {"status": "error", "message": str(e)}
