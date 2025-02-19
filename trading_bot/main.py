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
async def webhook(request: Request):
    """Handle Telegram webhook"""
    try:
        data = await request.json()
        logger.info(f"Received webhook: {data}")
        
        # Check of dit een callback query is
        if 'callback_query' in data:
            callback_query = data['callback_query']
            data = callback_query['data']  # bijv. 'chart_BTCUSD_1m'
            
            # Parse callback data
            action, *params = data.split('_')
            
            if action == 'chart':
                instrument, timeframe = params
                await telegram.handle_chart_button(callback_query, instrument, timeframe)
            elif action == 'sentiment':
                instrument = params[0]
                await telegram.handle_sentiment_button(callback_query, instrument)
            elif action == 'calendar':
                instrument = params[0]
                await telegram.handle_calendar_button(callback_query, instrument)
                
            return {"status": "success"}
            
        # Anders is het een trading signal
        signal = data
        logger.info(f"Received TradingView signal: {signal}")
        
        # Validate required fields
        required_fields = ['instrument', 'timeframe', 'signal', 'price', 'sl', 'tp']
        if not all(field in signal for field in required_fields):
            logger.error(f"Missing required fields in signal. Required: {required_fields}, Received: {list(signal.keys())}")
            return {"status": "error", "message": "Invalid signal format"}
            
        # Broadcast signal
        await telegram.broadcast_signal(signal)
        
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.post("/signal")
async def receive_signal(signal: Dict[str, Any]):
    """Receive and process trading signal"""
    try:
        logger.info(f"Received TradingView signal: {signal}")
        
        # Broadcast signal to subscribers
        await telegram.broadcast_signal(signal)
        
        return {"status": "success"}
        
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
