from fastapi import FastAPI, HTTPException, Request
import logging
import os
from typing import Dict, Any
from telegram import Update
import asyncio
import time

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
        results = await asyncio.gather(*tasks)
        formatted_signal, chart_image, sentiment_data, calendar_data = results
        
        # Sla de resultaten op in Redis voor snelle toegang
        message_key = f"preload:{signal['symbol']}:{int(time.time())}"
        
        # Sla text data op in normale Redis
        text_cache = {
            'formatted_signal': formatted_signal,
            'sentiment': sentiment_data,
            'calendar': calendar_data,
            'timestamp': str(int(time.time())),
            'symbol': signal['symbol'],
            'timeframe': signal['timeframe']
        }
        telegram.redis.hmset(f"{message_key}:text", text_cache)
        telegram.redis.expire(f"{message_key}:text", 3600)
        
        # Sla binary data op in binary Redis
        if chart_image:
            telegram.redis_binary.set(f"{message_key}:chart", chart_image)
            telegram.redis_binary.expire(f"{message_key}:chart", 3600)
        
        # Stuur het signaal met de gecachede data
        await telegram.broadcast_signal(signal, message_key)
        
        return {"status": "success", "message": "Signal processed and sent"}
        
    except Exception as e:
        logger.error(f"Error processing signal: {str(e)}")
        logger.exception(e)
        return {"status": "error", "message": str(e)}
