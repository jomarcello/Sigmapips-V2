from fastapi import FastAPI, HTTPException, Request
import logging
import os
from typing import Dict, Any
import asyncio
from supabase import create_client
from telegram import Update

# Gebruik absolute imports
from trading_bot.services.telegram_service.bot import TelegramService
from trading_bot.services.news_ai_service.sentiment import NewsAIService
from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.calendar_service.calendar import CalendarService
from trading_bot.services.database.db import Database

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
port = int(os.getenv("PORT", 8080))

# Initialize services
db = Database()
telegram = TelegramService(db)
news_ai = NewsAIService(db)
chart = ChartService()
calendar = CalendarService(db)

@app.on_event("startup")
async def startup_event():
    """Initialize async services on startup"""
    await telegram.initialize()
    
    # Set webhook URL using Railway URL
    webhook_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if webhook_url:
        full_url = f"https://{webhook_url}"
        await telegram.set_webhook(full_url)
        logger.info(f"Webhook set to: {full_url}")
    else:
        logger.warning("RAILWAY_PUBLIC_DOMAIN not set, bot will not receive updates")

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
