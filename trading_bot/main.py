from fastapi import FastAPI, HTTPException, Request
import logging
import os
from typing import Dict, Any
from telegram import Update, InlineKeyboardMarkup
import asyncio
import time
import base64
import aiohttp

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

class TradingBot:
    def __init__(self):
        self.db = Database()
        self.telegram = TelegramService(self.db)
        self.chart = ChartService()
        

# Initialiseer de bot
bot = TradingBot()

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
        
        # Sla chat op als het een tekst bericht is
        if 'message' in data and 'text' in data['message']:
            chat_text = data['message']['text']
            
        if 'update_id' in data:
            update = Update.de_json(data, telegram.application.bot)
            
            # 1. Eerst commands afhandelen
            if update.message and update.message.text and update.message.text.startswith('/'):
                await telegram.application.process_update(update)
                return {"status": "success"}
            
            # 2. Dan callback queries
            if update.callback_query:
                callback_query = update.callback_query
                data = callback_query.data
                logger.info(f"Received callback data: {data}")
                
                # 3. Specifieke handlers
                if data.startswith('back_'):
                    back_type = data.split('_')[1]
                    await telegram.handle_back(callback_query, back_type)
                    return {"status": "success"}
                
                elif data == 'signals_add':
                    await telegram.show_market_selection(callback_query, 'signals')
                    return {"status": "success"}
                
                elif data == 'signals_manage':
                    await telegram.manage_preferences(callback_query)
                    return {"status": "success"}
                
                elif data.startswith('menu_'):
                    await telegram.menu_choice(update, {})
                    return {"status": "success"}
                
                elif data.startswith('analysis_'):
                    if data == 'analysis_technical':
                        await telegram.show_market_selection(callback_query, 'technical')
                    elif data == 'analysis_sentiment':
                        await telegram.show_market_selection(callback_query, 'sentiment')
                    elif data == 'analysis_calendar':
                        await telegram.handle_calendar_button(callback_query.to_dict(), None)
                    return {"status": "success"}
                
                elif data.startswith('market_'):
                    market = data.split('_')[1]
                    analysis_type = data.split('_')[-1]
                    await telegram.show_instruments(callback_query, market, analysis_type)
                    return {"status": "success"}
                
                elif data.startswith('instrument_'):
                    parts = data.split('_')
                    instrument = parts[1]
                    analysis_type = parts[2]
                    if analysis_type == 'sentiment':
                        await telegram.show_sentiment_analysis(callback_query, instrument)
                    return {"status": "success"}
                
                elif data.startswith('signals_'):
                    await telegram.signals_choice(update, {})
                    return {"status": "success"}
                
                # Handle delete preferences
                if data == 'delete_prefs':
                    await telegram.handle_delete_preferences(callback_query)
                    return {"status": "success"}
                elif data.startswith('delete_pref_'):
                    await telegram.delete_single_preference(callback_query)
                    return {"status": "success"}
                
                # 4. Fallback voor andere callbacks
                await telegram.application.process_update(update)
                return {"status": "success"}
            
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
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

def initialize_services():
    """Initialize all services"""
    return {
        "db": db,
        "telegram": telegram,
        "chart": chart,
    }
