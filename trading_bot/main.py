from fastapi import FastAPI, HTTPException, Request
import logging
import os
from typing import Dict, Any
from telegram import Update

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
async def receive_signal(signal: dict):
    """Receive trading signal and forward to subscribers"""
    try:
        logger.info(f"Received signal: {signal}")
        
        # Get matching subscribers
        subscribers = await db.match_subscribers(signal)
        logger.info(f"Found {len(subscribers)} matching subscribers")
        
        # Send signal to each subscriber
        for subscriber in subscribers:
            try:
                await telegram.send_signal(
                    chat_id=subscriber['chat_id'],
                    signal=signal
                )
            except Exception as e:
                logger.error(f"Failed to send signal to subscriber {subscriber['chat_id']}: {str(e)}")
                continue
                
        return {"status": "success", "message": f"Signal sent to {len(subscribers)} subscribers"}
        
    except Exception as e:
        logger.error(f"Error processing signal: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
