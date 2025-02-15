from fastapi import FastAPI, HTTPException, Request
import logging
import os
from typing import Dict, Any
from telegram import Update
import asyncio
import time
import base64

from trading_bot.services.telegram_service.bot import TelegramService
from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.database.db import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
port = int(os.getenv("PORT", 8080))

# Initialize services
db = Database()
telegram = TelegramService(db)
chart = ChartService()

@app.on_event("startup")
async def startup_event():
    """Initialize async services on startup"""
    await telegram.initialize()
    
    webhook_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if webhook_url:
        # Verwijder eventuele trailing karakters
        webhook_url = webhook_url.strip(';').strip()
        full_url = f"https://{webhook_url}/webhook"  # Voeg /webhook toe aan het pad
        await telegram.set_webhook(full_url)
        logger.info(f"Webhook set to: {full_url}")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle Telegram webhook updates"""
    try:
        update = Update.de_json(await request.json(), telegram.bot)
        await telegram.app.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/signal")
async def receive_signal(signal: Dict[str, Any]):
    """Handle incoming signals from TradingView"""
    try:
        logger.info(f"Received TradingView signal: {signal}")
        
        # Converteer TradingView formaat naar ons formaat
        converted_signal = {
            "symbol": signal["instrument"],
            "action": signal["signal"],
            "price": signal["price"],
            "stopLoss": signal["sl"],
            "takeProfit1": signal["tp1"],
            "takeProfit2": signal["tp2"],
            "takeProfit3": signal["tp3"],
            "timeframe": signal["timeframe"],
            "market": _detect_market(signal["instrument"])
        }
        
        # Genereer message key
        message_key = f"preload:{converted_signal['symbol']}:{int(time.time())}"
        
        # Pre-load alle services
        tasks = []
        tasks.append(telegram.format_signal_with_ai(converted_signal))
        tasks.append(telegram.chart.generate_chart(converted_signal['symbol'], converted_signal['timeframe']))
        tasks.append(telegram.sentiment.get_market_sentiment(converted_signal))
        tasks.append(telegram.calendar.get_economic_calendar())
        
        # Wacht op alle data
        results = await asyncio.gather(*tasks)
        formatted_signal, chart_image, sentiment_data, calendar_data = results
        
        # Cache de data
        cache_data = {
            'formatted_signal': formatted_signal,
            'chart_image': base64.b64encode(chart_image).decode('utf-8') if chart_image else None,
            'sentiment': sentiment_data,
            'calendar': calendar_data,
            'timestamp': str(int(time.time())),
            'symbol': converted_signal['symbol'],
            'timeframe': converted_signal['timeframe']
        }
        
        # Sla op in Redis
        telegram.redis.hmset(message_key, cache_data)
        telegram.redis.expire(message_key, 3600)
        
        # Broadcast naar subscribers
        await telegram.broadcast_signal(converted_signal, message_key)
        
        return {"status": "success", "message": "Signal processed and sent"}
        
    except Exception as e:
        logger.error(f"Error processing signal: {str(e)}")
        return {"status": "error", "message": str(e)}

def _detect_market(symbol: str) -> str:
    """Detecteer market type gebaseerd op symbol"""
    symbol = symbol.upper()
    
    # Commodities eerst checken
    commodities = ["XAUUSD", "XAGUSD", "WTI", "BRENT", "NGAS"]
    if symbol in commodities:
        return "commodities"
    
    # Crypto
    crypto_symbols = ["BTC", "ETH", "XRP", "SOL", "LTC"]
    if any(c in symbol for c in crypto_symbols):
        return "crypto"
        
    # Indices
    indices = ["SPX500", "NAS100", "US30", "DAX40", "FTSE100"]
    if symbol in indices:
        return "indices"
    
    # Forex pairs als laatste (default)
    if len(symbol) == 6 and symbol.isalpha():
        return "forex"
        
    return "forex"  # Fallback
