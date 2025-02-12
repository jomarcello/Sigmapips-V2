import os
import ssl
import asyncio
import logging
import aiohttp
from typing import Dict, Any

from telegram import Bot, Update
from telegram.ext import Application
from telegram.constants import ParseMode

# Fix de import
from trading_bot.services.database.db import Database

logger = logging.getLogger(__name__)

class TelegramService:
    def __init__(self, db: Database):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError("Missing TELEGRAM_BOT_TOKEN")
            
        self.db = db
        
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        self.app = Application.builder().token(self.token).build()
        self.bot = self.app.bot
        
        logger.info("Telegram service initialized")
            
    async def initialize(self):
        try:
            info = await self.bot.get_me()
            logger.info(f"Successfully connected to Telegram API. Bot info: {info}")
        except Exception as e:
            logger.error(f"Failed to connect to Telegram API: {str(e)}")
            raise
            
    async def send_signal(self, chat_id: str, signal: Dict[str, Any], sentiment: str = None, chart: str = None, events: list = None):
        try:
            message = self._format_signal_message(signal, sentiment, events)
            logger.info(f"Attempting to send message to chat_id: {chat_id}")
            await self.bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
            if chart:
                await self.bot.send_photo(chat_id=chat_id, photo=chart)
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {str(e)}", exc_info=True)
            return False
            
    def _format_signal_message(self, signal: Dict[str, Any], sentiment: str = None, events: list = None) -> str:
        message = f"🚨 <b>New Signal Alert</b>\n\n"
        message += f"Symbol: {signal['symbol']}\n"
        message += f"Action: {signal['action']}\n"
        message += f"Price: {signal['price']}\n"
        message += f"Stop Loss: {signal['stopLoss']}\n"
        message += f"Take Profit: {signal['takeProfit']}\n"
        message += f"Timeframe: {signal.get('timeframe', 'Not specified')}\n"
        
        if sentiment:
            message += f"\n📊 <b>Sentiment Analysis</b>\n{sentiment}\n"
            
        if events and len(events) > 0:
            message += f"\n📅 <b>Upcoming Events</b>\n"
            for event in events[:3]:
                message += f"• {event}\n"
                
        return message
