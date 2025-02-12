from fastapi import FastAPI, HTTPException
import logging
import os
from typing import Dict, Any
import asyncio
from supabase import create_client

# Update imports om de package structuur te gebruiken
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

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
