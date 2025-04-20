import os
import ssl
import asyncio
import logging
import aiohttp
from typing import Dict, Any, List, Optional, Union
import traceback
from datetime import datetime, timedelta

from telegram import Bot, Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ConversationHandler, CommandHandler, CallbackQueryHandler
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    ContextTypes,
    CallbackContext,
    MessageHandler,
    filters
)

from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.calendar_service import EconomicCalendarService
from trading_bot.services.database.db import Database
from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
import trading_bot.services.telegram_service.gif_utils as gif_utils
from trading_bot.services.telegram_service.states import (
    MENU, ANALYSIS, SIGNALS, CHOOSE_MARKET, CHOOSE_INSTRUMENT, CHOOSE_STYLE,
    CHOOSE_ANALYSIS, SIGNAL_DETAILS,
    CALLBACK_MENU_ANALYSE, CALLBACK_MENU_SIGNALS, CALLBACK_ANALYSIS_TECHNICAL,
    CALLBACK_ANALYSIS_SENTIMENT, CALLBACK_ANALYSIS_CALENDAR, CALLBACK_SIGNALS_ADD,
    CALLBACK_SIGNALS_MANAGE, CALLBACK_BACK_MENU
)

# Get logger
logger = logging.getLogger(__name__)

class TelegramService:
    def __init__(self, db: Database, stripe_service=None, bot_token: Optional[str] = None, proxy_url: Optional[str] = None):
        """Initialize the bot with given database and config."""
        
        # Store database reference
        self.db = db
        
        # Setup configuration 
        self.stripe_service = stripe_service
        self.user_signals = {}
        self.signals_dir = "data/signals"
        self.signals_enabled_val = True
        
        # Setup logger
        self.logger = logging.getLogger(__name__)
        
        # GIF utilities for UI
        self.gif_utils = gif_utils  # Initialize gif_utils as an attribute
        
        # Setup the bot and application
        self.bot = None
        self.application = None
        
        # Telegram Bot configuratie
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.token = self.bot_token  # Aliased for backward compatibility
        self.proxy_url = proxy_url or os.getenv("TELEGRAM_PROXY_URL", "")
        
        # Configure custom request handler with improved connection settings
        request = HTTPXRequest(
            connection_pool_size=50,
            connect_timeout=15.0,
            read_timeout=45.0,
            write_timeout=30.0,
            pool_timeout=60.0,
        )
        
        # Initialize the bot directly with connection pool settings
        self.bot = Bot(token=self.bot_token, request=request)
        self.application = None  # Will be initialized in setup()
        
        # Webhook configuration
        self.webhook_url = os.getenv("WEBHOOK_URL", "")
        self.webhook_path = "/webhook"  # Always use this path
        if self.webhook_url.endswith("/"):
            self.webhook_url = self.webhook_url[:-1]  # Remove trailing slash
            
        logger.info(f"Bot initialized with webhook URL: {self.webhook_url} and path: {self.webhook_path}")
        
        # Initialize API services
        self.chart_service = ChartService()  # Initialize chart service
        self.calendar_service = EconomicCalendarService()  # Economic calendar service
        self.sentiment_service = None  # Will be initialized in initialize_services
        
        # Cache for sentiment analysis
        self.sentiment_cache = {}
        self.sentiment_cache_ttl = 60 * 60  # 1 hour in seconds
        
        # Start the bot
        try:
            # Check for bot token
            if not self.bot_token:
                raise ValueError("Missing Telegram bot token")
            
            # Initialize the bot
            self.bot = Bot(token=self.bot_token)
        
            # Initialize the application
            self.application = Application.builder().bot(self.bot).build()
        
            # Register the handlers
            self._register_handlers(self.application)
            
            logger.info("Telegram service initialized")
            
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            raise
            
    async def initialize_services(self, lazy_load: bool = False):
        """Initialize services like chart service and sentiment service"""
        # Initialize chart_service connection if not initialized yet
        if not hasattr(self, 'chart_service') or self.chart_service is None:
            try:
                # Log more detailed info on what we're trying to do
                logger.info("Initializing chart service...")
                
                from trading_bot.services.chart_service.chart import ChartService
                self.chart_service = ChartService()
                
                logger.info("Chart service initialized")
            except Exception as e:
                logger.error(f"Failed to initialize chart service: {str(e)}")
                logger.error(traceback.format_exc())
                
        # Initialize calendar service
        if not hasattr(self, 'calendar_service') or self.calendar_service is None:
            try:
                logger.info("Initializing calendar service...")
                self.calendar_service = EconomicCalendarService()
                logger.info("Calendar service initialized")
            except Exception as e:
                logger.error(f"Failed to initialize calendar service: {str(e)}")
                
        # Initialize sentiment service
        if not hasattr(self, 'sentiment_service') or self.sentiment_service is None:
            try:
                logger.info("Initializing sentiment service...")
                from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
                self.sentiment_service = MarketSentimentService()
                
                # Only load cache if not lazy loading
                if not lazy_load:
                    # Explicitly load the cache asynchronously
                    await self.sentiment_service.load_cache()
                
                logger.info("Sentiment service initialized")
            except Exception as e:
                logger.error(f"Failed to initialize sentiment service: {str(e)}")
        
        # Load signals
        try:
            logger.info("Loading signals...")
            # Code to load signals would go here
            logger.info("Signals loaded successfully")
        except Exception as e:
            logger.error(f"Error loading signals: {str(e)}")
    
    # Rest of the class methods...
    def _register_handlers(self, application):
        """Register all necessary handlers for the bot"""
        logger.info("Registering handlers...")
        # Handler registration code would go here
        logger.info("Handlers registered successfully")

    async def send_signal(self, chat_id: str, signal: Dict[str, Any], sentiment: str = None, chart: str = None, events: list = None):
        try:
            message = self._format_signal_message(signal, sentiment, events)
            
            # Log de verzendpoging
            logger.info(f"Attempting to send message to chat_id: {chat_id}")
            logger.debug(f"Message content: {message}")
            
            await self.bot.send_message(
                chat_id=chat_id, 
                text=message, 
                parse_mode=ParseMode.HTML
            )
            
            if chart:
                await self.bot.send_photo(chat_id=chat_id, photo=chart)
                
            logger.info(f"Successfully sent message to chat_id: {chat_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {str(e)}", exc_info=True)
            return False
            
    def _format_signal_message(self, signal: Dict[str, Any], sentiment: str = None, events: list = None) -> str:
        """Format signal data into a readable message"""
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
            for event in events[:3]:  # Show max 3 events
                message += f"• {event}\n"
                
        return message
