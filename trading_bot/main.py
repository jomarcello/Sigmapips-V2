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
        full_url = f"https://{webhook_url}"
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
    try:
        logger.info(f"Received signal: {signal}")
        
        # Genereer message key eerst
        message_key = f"preload:{signal['symbol']}:{int(time.time())}"
        logger.info(f"Generated message key: {message_key}")
        
        # Pre-load alle services
        tasks = []
        
        # 1. Format het basis signaal
        formatted_signal_task = telegram.format_signal_with_ai(signal)
        tasks.append(formatted_signal_task)
        
        # 2. Genereer chart
        chart_task = telegram.chart.generate_chart(signal['symbol'], signal['timeframe'])
        tasks.append(chart_task)
        
        # 3. Haal market sentiment op
        sentiment_task = telegram.sentiment.get_market_sentiment(signal)
        tasks.append(sentiment_task)
        
        # 4. Haal economic calendar op
        calendar_task = telegram.calendar.get_economic_calendar()
        tasks.append(calendar_task)
        
        # Wacht tot alle data geladen is
        logger.info("Waiting for all tasks to complete...")
        results = await asyncio.gather(*tasks)
        formatted_signal, chart_image, sentiment_data, calendar_data = results
        logger.info("All tasks completed successfully")
        
        # Converteer binary data naar base64
        chart_base64 = base64.b64encode(chart_image).decode('utf-8') if chart_image else None
        logger.info(f"Chart image converted to base64: {bool(chart_base64)}")
        
        # Sla alles op in Redis
        cache_data = {
            'formatted_signal': formatted_signal,
            'chart_image': chart_base64,
            'sentiment': sentiment_data,
            'calendar': calendar_data,
            'timestamp': str(int(time.time())),
            'symbol': signal['symbol'],
            'timeframe': signal['timeframe']
        }
        
        # Log cache data sizes
        logger.info(f"Cache data sizes:")
        for key, value in cache_data.items():
            logger.info(f"- {key}: {len(str(value)) if value else 0} bytes")
        
        # Sla op in Redis en verifieer
        logger.info(f"Saving data to Redis with key: {message_key}")
        telegram.redis.hmset(message_key, cache_data)
        telegram.redis.expire(message_key, 3600)
        
        # Verifieer dat de data is opgeslagen
        saved_data = telegram.redis.hgetall(message_key)
        if not saved_data:
            logger.error(f"Failed to save data in Redis for key: {message_key}")
            return {"status": "error", "message": "Failed to cache data"}
        
        logger.info(f"Data successfully saved in Redis. Found keys: {list(saved_data.keys())}")
        
        # Stuur het signaal met de gecachede data
        logger.info("Broadcasting signal to subscribers...")
        await telegram.broadcast_signal(signal, message_key)
        
        return {"status": "success", "message": "Signal processed and sent"}
        
    except Exception as e:
        logger.error(f"Error processing signal: {str(e)}")
        logger.exception(e)
        return {"status": "error", "message": str(e)}
