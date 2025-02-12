from fastapi import FastAPI, HTTPException
import logging
import os
from typing import Dict, Any
import asyncio
from supabase import create_client

# Update deze imports om de nieuwe structuur te gebruiken
from trading_bot.services.telegram_service import TelegramService
from trading_bot.services.news_ai_service import NewsAIService
from trading_bot.services.chart_service import ChartService
from trading_bot.services.calendar_service import CalendarService
from trading_bot.services.database import Database 