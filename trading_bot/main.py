from fastapi import FastAPI, HTTPException, Request
import logging
import os
from typing import Dict, Any
from telegram import Update
import asyncio
import time
import base64

# Correcte absolute imports
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
        
        # Check of dit een Telegram update is
        if 'update_id' in data:
            # Dit is een Telegram update
            if 'callback_query' in data:
                callback_query = data['callback_query']
                data_parts = callback_query['data'].split('_')
                action = data_parts[0]
                
                if action == 'analysis':
                    analysis_type = data_parts[1]
                    if analysis_type == 'sentiment':
                        # Haal instrument uit user data of gebruik default
                        instrument = "EURUSD"  # Default instrument
                        await telegram.handle_sentiment_button(callback_query, instrument)
                        return {"status": "success"}
                    elif analysis_type == 'calendar':
                        # Voor calendar hoeven we geen instrument te hebben
                        await telegram.handle_calendar_button(callback_query, None)
                        return {"status": "success"}
                
                elif action in ['chart', 'sentiment', 'calendar']:
                    instrument = data_parts[1]
                    if action == 'chart':
                        timeframe = data_parts[2] if len(data_parts) > 2 else "1h"
                        await telegram.handle_chart_button(callback_query, instrument, timeframe)
                    elif action == 'sentiment':
                        await telegram.handle_sentiment_button(callback_query, instrument)
                    elif action == 'calendar':
                        await telegram.handle_calendar_button(callback_query, instrument)
                    return {"status": "success"}
            
            # Laat de application handler dit afhandelen
            await telegram.application.update_queue.put(Update.de_json(data, telegram.application.bot))
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

def _detect_market(symbol: str) -> str:
    """Detecteer market type gebaseerd op symbol"""
    symbol = symbol.upper()
    
    # Commodities eerst checken (uitgebreide lijst)
    commodities = [
        "XAUUSD",  # Gold
        "XAGUSD",  # Silver
        "WTIUSD",  # Oil WTI
        "BCOUSD",  # Oil Brent
        "NATGAS",  # Natural Gas
        "COPPER",  # Copper
        "PLATINUM", # Platinum
        "PALLADIUM" # Palladium
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
