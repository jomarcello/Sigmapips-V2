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
from trading_bot.services.chart_service.session_refresher import SessionRefresher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
port = int(os.getenv("PORT", 8080))

# Initialize services once
db = Database()
telegram = TelegramService(db)
chart = ChartService()

# Redis configuratie met verbeterde private endpoint support
redis_url = os.getenv("REDIS_URL")
redis_private_host = os.getenv("REDIS_PRIVATE_HOST")
redis_private_port = os.getenv("REDIS_PRIVATE_PORT")
redis_password = os.getenv("REDIS_PASSWORD")

# Verbeterde Redis-verbinding met private endpoint support
try:
    # Probeer eerst het privé-eindpunt als dat beschikbaar is
    if redis_private_host and redis_private_port:
        logger.info(f"Attempting to connect to Redis using private endpoint: {redis_private_host}:{redis_private_port}")
        redis_client = redis.Redis(
            host=redis_private_host,
            port=int(redis_private_port),
            password=redis_password,
            db=0,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            retry_on_timeout=True,
            health_check_interval=30
        )
    # Fallback naar REDIS_URL als privé-eindpunt niet beschikbaar is
    elif redis_url:
        logger.info(f"Attempting to connect to Redis using URL: {redis_url}")
        redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            retry_on_timeout=True,
            health_check_interval=30
        )
    # Fallback naar standaard host/port als geen van beide beschikbaar is
    else:
        redis_host = os.getenv("REDIS_HOST", "redis")
        redis_port = int(os.getenv("REDIS_PORT", 6379))
        logger.info(f"Attempting to connect to Redis using default host/port: {redis_host}:{redis_port}")
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
    logger.info("Redis connection established successfully")
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
    """Initialize async services on startup"""
    # Sla de starttijd op
    app.state.start_time = time.time()
    app.state.is_ready = False
    app.state.services_status = {
        "telegram": False,
        "chart": False,
        "db": True  # Database is al geïnitialiseerd
    }
    
    # Setup Playwright browsers
    try:
        # Inline setup in plaats van import
        import subprocess
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info("Setting up Playwright browsers")
        result = subprocess.run(["playwright", "install", "chromium"], 
                               capture_output=True, text=True)
        
        if result.returncode == 0:
            logger.info("Playwright browsers installed successfully")
        else:
            logger.error(f"Error installing Playwright browsers: {result.stderr}")
    except Exception as e:
        logger.error(f"Error setting up Playwright: {str(e)}")
    
    # Initialize telegram service
    try:
        await telegram.initialize()
        app.state.services_status["telegram"] = True
        logger.info("Telegram service initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing telegram service: {str(e)}")
    
    # Initialize chart service
    try:
        await chart.initialize()
        app.state.services_status["chart"] = True
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

    # Start een achtergrondtaak voor periodieke health checks
    asyncio.create_task(periodic_health_check())

    # Start de session refresher
    asyncio.create_task(session_refresher.start())
    
    # Markeer de applicatie als klaar
    app.state.is_ready = True
    logger.info("Application startup complete")

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
    """Eenvoudige health check endpoint voor Railway"""
    # Deze endpoint moet altijd snel reageren en een 200 OK status retourneren
    return {
        "status": "ok",
        "timestamp": time.time(),
        "app": "trading_bot",
        "version": "1.0.0"
    }

@app.get("/readiness")
async def readiness_check():
    """Readiness check endpoint voor Railway"""
    try:
        # Controleer of de applicatie klaar is om verkeer te ontvangen
        is_ready = getattr(app.state, "is_ready", False)
        services_status = getattr(app.state, "services_status", {
            "telegram": False,
            "chart": False,
            "db": False
        })
        
        return {
            "status": "ok" if is_ready else "not_ready",
            "services": services_status,
            "uptime": time.time() - getattr(app.state, "start_time", time.time()),
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"Error in readiness check: {str(e)}")
        # Zelfs bij een fout, retourneer een 200 OK status
        return {"status": "warning", "message": str(e)}

@app.get("/liveness")
async def liveness_check():
    """Liveness check endpoint voor Railway"""
    try:
        # Controleer of de applicatie nog steeds draait
        return {
            "status": "ok",
            "uptime": time.time() - getattr(app.state, "start_time", time.time()),
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"Error in liveness check: {str(e)}")
        # Zelfs bij een fout, retourneer een 200 OK status
        return {"status": "warning", "message": str(e)}

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
    """Test endpoint voor de
