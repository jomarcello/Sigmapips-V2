import json
import os
import logging
import asyncio
import aiohttp
import time
import random
import numpy as np
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union, Callable, Awaitable, TypeVar, Set, Tuple
from html.parser import HTMLParser
from fastapi import FastAPI

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    MessageEntity,
    ParseMode, 
    Bot,
    InputMediaPhoto,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    Application,
    CallbackContext,
    TypeHandler,
    PicklePersistence,
)
from telegram.request import HTTPXRequest

from trading_bot.core.database import Database, DatabaseProvider
from trading_bot.services.telegram_service.states import *
from trading_bot.services.telegram_service import gif_utils
from trading_bot.services.chart_service.chart_service import ChartService
from trading_bot.services.calendar_service.calendar_fix import EconomicCalendarService
from trading_bot.services.sentiment_service.sentiment_service import MarketSentimentService
from trading_bot.services.telegram_service.logger import logger
from trading_bot.services.models import TradingSignal
import trading_bot.services.telegram_service.keyboards as kb
from trading_bot.services.telegram_service.keyboards import (
    START_KEYBOARD,
    MARKET_KEYBOARD,
    ANALYSIS_KEYBOARD,
    SIGNALS_KEYBOARD,
    MARKET_KEYBOARD_SIGNALS,
    FOREX_KEYBOARD,
    CRYPTO_KEYBOARD,
    INDICES_KEYBOARD,
    COMMODITIES_KEYBOARD,
    FOREX_KEYBOARD_SIGNALS,
    CRYPTO_KEYBOARD_SIGNALS,
    INDICES_KEYBOARD_SIGNALS,
    COMMODITIES_KEYBOARD_SIGNALS,
    TIMEFRAME_KEYBOARD,
    TIMEFRAME_KEYBOARD_SIGNALS,
    TECHNICAL_ANALYSIS_KEYBOARD,
    SENTIMENT_ANALYSIS_KEYBOARD,
    CALENDAR_ANALYSIS_KEYBOARD,
    SIGNAL_ANALYSIS_KEYBOARD,
    SIGNAL_MENU_KEYBOARD,
    RISK_KEYBOARD,
    LANGUAGES,
    CURRENCY_FLAG,
)

class SignalContextManager:
    """
    Manages signal context information across different bot conversation flows.
    
    This class provides a more robust way to store and retrieve signal information
    during user navigation, preventing data loss when users switch between different
    bot conversation flows.
    """
    
    def __init__(self, telegram_service):
        self.telegram_service = telegram_service
        self.logger = logging.getLogger(__name__)
        self.user_signal_context = {}  # user_id -> signal context
    
    def store_signal_context(self, user_id, instrument=None, direction=None, timeframe=None, signal_id=None):
        """Store signal context for a user with proper validation"""
        user_id = str(user_id)
        
        if user_id not in self.user_signal_context:
            self.user_signal_context[user_id] = {}
        
        # Only update fields that are provided (not None)
        if instrument is not None:
            self.user_signal_context[user_id]['instrument'] = instrument
        if direction is not None:
            self.user_signal_context[user_id]['direction'] = direction
        if timeframe is not None:
            self.user_signal_context[user_id]['timeframe'] = timeframe
        if signal_id is not None:
            self.user_signal_context[user_id]['signal_id'] = signal_id
            
        self.logger.info(f"Stored signal context for user {user_id}: {self.user_signal_context[user_id]}")
        return self.user_signal_context[user_id]
    
    def get_signal_context(self, user_id):
        """Get the current signal context for a user"""
        user_id = str(user_id)
        return self.user_signal_context.get(user_id, {})
    
    def clear_signal_context(self, user_id):
        """Clear the signal context for a user"""
        user_id = str(user_id)
        if user_id in self.user_signal_context:
            del self.user_signal_context[user_id]
            self.logger.info(f"Cleared signal context for user {user_id}")
    
    def update_from_context(self, user_id, context):
        """Update signal context from the conversation context object"""
        if not context or not hasattr(context, 'user_data'):
            return {}
            
        user_id = str(user_id)
        signal_context = {}
        
        # Extract data from context with fallbacks
        instrument = context.user_data.get('signal_instrument_backup') or context.user_data.get('signal_instrument')
        direction = context.user_data.get('signal_direction_backup') or context.user_data.get('signal_direction')
        timeframe = context.user_data.get('signal_timeframe_backup') or context.user_data.get('signal_timeframe')
        signal_id = context.user_data.get('signal_id_backup') or context.user_data.get('signal_id')
        
        # Update our context store
        return self.store_signal_context(
            user_id, 
            instrument=instrument,
            direction=direction, 
            timeframe=timeframe,
            signal_id=signal_id
        )
    
    def sync_to_context(self, user_id, context):
        """Sync our signal context to the conversation context object"""
        if not context or not hasattr(context, 'user_data'):
            return
            
        user_id = str(user_id)
        signal_context = self.get_signal_context(user_id)
        
        if not signal_context:
            return
            
        # Update context with our stored data
        context.user_data['signal_instrument'] = signal_context.get('instrument')
        context.user_data['signal_direction'] = signal_context.get('direction')
        context.user_data['signal_timeframe'] = signal_context.get('timeframe')
        context.user_data['signal_id'] = signal_context.get('signal_id')
        
        # Also update backup fields
        context.user_data['signal_instrument_backup'] = signal_context.get('instrument')
        context.user_data['signal_direction_backup'] = signal_context.get('direction')
        context.user_data['signal_timeframe_backup'] = signal_context.get('timeframe')
        context.user_data['signal_id_backup'] = signal_context.get('signal_id')
        
        self.logger.info(f"Synced signal context to conversation context for user {user_id}")
        
    def find_matching_signal(self, user_id):
        """Find a matching signal based on stored context"""
        user_id = str(user_id)
        signal_context = self.get_signal_context(user_id)
        
        if not signal_context:
            self.logger.warning(f"No signal context found for user {user_id}")
            return None
            
        # Extract context values
        instrument = signal_context.get('instrument')
        direction = signal_context.get('direction')
        timeframe = signal_context.get('timeframe')
        signal_id = signal_context.get('signal_id')
        
        if not instrument:
            self.logger.warning("No instrument found in signal context")
            return None
            
        # If we have a signal_id and it exists, return it directly
        if signal_id and user_id in self.telegram_service.user_signals:
            if signal_id in self.telegram_service.user_signals[user_id]:
                return self.telegram_service.user_signals[user_id][signal_id]
        
        # Otherwise search for matching signals
        if user_id in self.telegram_service.user_signals:
            user_signal_dict = self.telegram_service.user_signals[user_id]
            matching_signals = []
            
            for sig_id, sig in user_signal_dict.items():
                instrument_match = sig.get('instrument') == instrument
                direction_match = True  # Default to true if we don't have direction data
                timeframe_match = True  # Default to true if we don't have timeframe data
                
                if direction:
                    direction_match = sig.get('direction') == direction
                if timeframe:
                    timeframe_match = sig.get('interval') == timeframe
                
                if instrument_match and direction_match and timeframe_match:
                    matching_signals.append((sig_id, sig))
            
            # Sort by timestamp, newest first
            if matching_signals:
                matching_signals.sort(key=lambda x: x[1].get('timestamp', ''), reverse=True)
                signal_id, signal_data = matching_signals[0]
                
                # Update the signal_id in our context
                self.store_signal_context(user_id, signal_id=signal_id)
                
                self.logger.info(f"Found matching signal with ID: {signal_id}")
                return signal_data
                
            # If no exact match, try with just the instrument
            if not matching_signals:
                self.logger.warning(f"No exact match found, trying with just instrument")
                matching_signals = []
                for sig_id, sig in user_signal_dict.items():
                    if sig.get('instrument') == instrument:
                        matching_signals.append((sig_id, sig))
                
                if matching_signals:
                    matching_signals.sort(key=lambda x: x[1].get('timestamp', ''), reverse=True)
                    signal_id, signal_data = matching_signals[0]
                    
                    # Update the signal_id in our context
                    self.store_signal_context(user_id, signal_id=signal_id)
                    
                    self.logger.info(f"Found signal with just instrument match, ID: {signal_id}")
                    return signal_data
        
        self.logger.warning(f"No matching signal found for user {user_id}")
        return None

# Additional helper functions for interpreting signals
def _detect_market(instrument: str) -> str:
    """Detecteer market type gebaseerd op instrument"""
    instrument = instrument.upper()
    
    # Commodities eerst checken
    commodities = [
        "XAUUSD",  # Gold
        "XAGUSD",  # Silver
        "WTIUSD",  # Oil WTI
        "BCOUSD",  # Oil Brent
    ]
    if instrument in commodities:
        logger.info(f"Detected {instrument} as commodity")
        return "commodities"
    
    # Crypto pairs
    crypto_base = ["BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "DOT", "LINK"]
    if any(c in instrument for c in crypto_base):
        logger.info(f"Detected {instrument} as crypto")
        return "crypto"
    
    # Major indices
    indices = [
        "US30", "US500", "US100",  # US indices
        "UK100", "DE40", "FR40",   # European indices
        "JP225", "AU200", "HK50"   # Asian indices
    ]
    if instrument in indices:
        logger.info(f"Detected {instrument} as index")
        return "indices"
    
    # Forex pairs als default
    logger.info(f"Detected {instrument} as forex")
    return "forex"

def require_subscription(func):
    """Check if user has an active subscription"""
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        
        # Check subscription status
        is_subscribed = await self.db.is_user_subscribed(user_id)
        
        # Check if payment has failed
        payment_failed = await self.db.has_payment_failed(user_id)
        
        if is_subscribed and not payment_failed:
            # User has subscription, proceed with function
            return await func(self, update, context, *args, **kwargs)
        else:
            if payment_failed:
                # Show payment failure message
                failed_payment_text = f"""
❗ <b>Subscription Payment Failed</b> ❗

Your subscription payment could not be processed and your service has been deactivated.

To continue using Sigmapips AI and receive trading signals, please reactivate your subscription by clicking the button below.
                """
                
                # Use direct URL link for reactivation
                reactivation_url = "https://buy.stripe.com/9AQcPf3j63HL5JS145"
                
                # Create button for reactivation
                keyboard = [
                    [InlineKeyboardButton("🔄 Reactivate Subscription", url=reactivation_url)]
                ]
            else:
                # Show subscription screen with the welcome message from the screenshot
                failed_payment_text = f"""
🚀 <b>Welcome to Sigmapips AI!</b> 🚀

<b>Discover powerful trading signals for various markets:</b>
• <b>Forex</b> - Major and minor currency pairs
• <b>Crypto</b> - Bitcoin, Ethereum and other top cryptocurrencies
• <b>Indices</b> - Global market indices
• <b>Commodities</b> - Gold, silver and oil

<b>Features:</b>
✅ Real-time trading signals

✅ Multi-timeframe analysis (1m, 15m, 1h, 4h)

✅ Advanced chart analysis

✅ Sentiment indicators

✅ Economic calendar integration

<b>Start today with a FREE 14-day trial!</b>
                """
                
                # Use direct URL link instead of callback for the trial button
                reactivation_url = "https://buy.stripe.com/3cs3eF9Hu9256NW9AA"
                
                # Create button for trial
                keyboard = [
                    [InlineKeyboardButton("🔥 Start 14-day FREE Trial", url=reactivation_url)]
                ]
            
            # Handle both message and callback query updates
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    text=failed_payment_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    text=failed_payment_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            return MENU
    
    return wrapper

# API keys with robust sanitization
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "").strip()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "72df8ae1c5dd4d95b6a54c09bcf1b39e").strip()

# Ensure the Tavily API key is properly formatted with 'tvly-' prefix and sanitized
raw_tavily_key = os.getenv("TAVILY_API_KEY", "KbIKVL3UfDfnxRx3Ruw6XhL3OB9qSF9l").strip()
TAVILY_API_KEY = raw_tavily_key.replace('\n', '').replace('\r', '')  # Remove any newlines/carriage returns

# If the key doesn't start with "tvly-", add the prefix
if TAVILY_API_KEY and not TAVILY_API_KEY.startswith("tvly-"):
    TAVILY_API_KEY = f"tvly-{TAVILY_API_KEY}"
    logger.info("Added 'tvly-' prefix to Tavily API key")
    
# Log API key (partially masked)
if TAVILY_API_KEY:
    masked_key = f"{TAVILY_API_KEY[:7]}...{TAVILY_API_KEY[-4:]}" if len(TAVILY_API_KEY) > 11 else f"{TAVILY_API_KEY[:4]}..."
    logger.info(f"Using Tavily API key: {masked_key}")
else:
    logger.warning("No Tavily API key configured")
    
# Set environment variables for the API keys with sanitization
os.environ["PERPLEXITY_API_KEY"] = PERPLEXITY_API_KEY
os.environ["DEEPSEEK_API_KEY"] = DEEPSEEK_API_KEY
os.environ["TAVILY_API_KEY"] = TAVILY_API_KEY

class TelegramService:
    def __init__(self, db: Database, stripe_service=None, bot_token: Optional[str] = None, proxy_url: Optional[str] = None):
        """Initialize the bot with given database and config."""
        # Database connection
        self.db = db
        
        # Setup configuration 
        self.stripe_service = stripe_service
        self.user_signals = {}
        self.signals_dir = "data/signals"
        self.signals_enabled_val = True
        self.polling_started = False
        self.admin_users = [1093307376]  # Add your Telegram ID here for testing
        self._signals_enabled = True  # Enable signals by default
        
        # Initialize signal context manager for persistent signal tracking
        self.signal_contexts = {}  # user_id -> {instrument, direction, timeframe, signal_id}
        
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
            connection_pool_size=50,  # Increase from 20 to 50
            connect_timeout=15.0,     # Increase from 10.0 to 15.0
            read_timeout=45.0,        # Increase from 30.0 to 45.0
            write_timeout=30.0,       # Increase from 20.0 to 30.0
            pool_timeout=60.0,        # Increase from 30.0 to 60.0
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
        self.sentiment_service = MarketSentimentService()  # Market sentiment service
        
        # Don't use asyncio.create_task here - it requires a running event loop
        # We'll initialize chart service later when the event loop is running
        
        # Bot application initialization
        self.persistence = None
        self.bot_started = False
        
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
            
            # Load stored signals
            self._load_signals()
        
            logger.info("Telegram service initialized")
            
            # Keep track of processed updates
            self.processed_updates = set()
            
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            raise

    async def initialize_services(self):
        """Initialize services that require an asyncio event loop"""
        try:
            # Initialize chart service
            await self.chart_service.initialize()
            logger.info("Chart service initialized")
        except Exception as e:
            logger.error(f"Error initializing services: {str(e)}")
            raise
            
    # Calendar service helpers
    def _get_calendar_service(self):
        """Get the calendar service instance"""
        self.logger.info("Getting calendar service")
        return self.calendar_service

    async def _format_calendar_events(self, calendar_data):
        """Format the calendar data into a readable HTML message"""
        self.logger.info(f"Formatting calendar data with {len(calendar_data)} events")
        if not calendar_data:
            return "<b>📅 Economic Calendar</b>\n\nNo economic events found for today."
        
        # Sort events by time
        try:
            # Try to parse time for sorting
            def parse_time_for_sorting(event):
                time_str = event.get('time', '')
                try:
                    # Extract hour and minute if in format like "08:30 EST"
                    if ':' in time_str:
                        parts = time_str.split(' ')[0].split(':')
                        hour = int(parts[0])
                        minute = int(parts[1])
                        return hour * 60 + minute
                    return 0
                except:
                    return 0
            
            # Sort the events by time
            sorted_events = sorted(calendar_data, key=parse_time_for_sorting)
        except Exception as e:
            self.logger.error(f"Error sorting calendar events: {str(e)}")
            sorted_events = calendar_data
        
        # Format the message
        message = "<b>📅 Economic Calendar</b>\n\n"
        
        # Get current date
        current_date = datetime.now().strftime("%B %d, %Y")
        message += f"<b>Date:</b> {current_date}\n\n"
        
        # Add impact legend
        message += "<b>Impact:</b> 🔴 High   🟠 Medium   🟢 Low\n\n"
        
        # Group events by country
        events_by_country = {}
        for event in sorted_events:
            country = event.get('country', 'Unknown')
            if country not in events_by_country:
                events_by_country[country] = []
            events_by_country[country].append(event)
        
        # Format events by country
        for country, events in events_by_country.items():
            country_flag = CURRENCY_FLAG.get(country, '')
            message += f"<b>{country_flag} {country}</b>\n"
            
            for event in events:
                time = event.get('time', 'TBA')
                title = event.get('title', 'Unknown Event')
                impact = event.get('impact', 'Low')
                impact_emoji = {'High': '🔴', 'Medium': '🟠', 'Low': '🟢'}.get(impact, '🟢')
                
                message += f"{time} - {impact_emoji} {title}\n"
            
            message += "\n"  # Add extra newline between countries
        
        return message
        
    # Utility functions that might be missing
    async def update_message(self, query, text, keyboard=None, parse_mode=ParseMode.HTML):
        """Utility to update a message with error handling"""
        try:
            self.logger.info("Updating message")
            # Try to edit message text first
            await query.edit_message_text(
                text=text,
                reply_markup=keyboard,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            self.logger.warning(f"Could not update message text: {str(e)}")
            
            # If text update fails, try to edit caption
            try:
                await query.edit_message_caption(
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=parse_mode
                )
                return True
            except Exception as e2:
                self.logger.error(f"Could not update caption either: {str(e2)}")
                
                # As a last resort, send a new message
                try:
                    chat_id = query.message.chat_id
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=keyboard,
                        parse_mode=parse_mode
                    )
                    return True
                except Exception as e3:
                    self.logger.error(f"Failed to send new message: {str(e3)}")
                    return False
    
    # Missing handler implementations
    async def back_signals_callback(self, update: Update, context=None) -> int:
        """Handle back_signals button press"""
        query = update.callback_query
        await query.answer()
        
        self.logger.info("back_signals_callback called")
        
        # Make sure we're in the signals flow context
        if context and hasattr(context, 'user_data'):
            # Keep is_signals_context flag but reset from_signal flag
            context.user_data['is_signals_context'] = True
            context.user_data['from_signal'] = False
            
            # Clear other specific analysis keys but maintain signals context
            keys_to_remove = [
                'instrument', 'market', 'analysis_type', 'timeframe', 
                'signal_id', 'signal_instrument', 'signal_direction', 'signal_timeframe',
                'loading_message'
            ]
            
            for key in keys_to_remove:
                if key in context.user_data:
                    del context.user_data[key]
            
            self.logger.info(f"Updated context in back_signals_callback: {context.user_data}")
        
        # Create keyboard for signal menu
        keyboard = [
            [InlineKeyboardButton("📊 Add Signal", callback_data="signals_add")],
            [InlineKeyboardButton("⚙️ Manage Signals", callback_data="signals_manage")],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Get the signals GIF URL for better UX
        signals_gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
        
        # Try to update with GIF for better visual feedback
        try:
            # First try to delete and send new message with GIF
            await query.message.delete()
            await context.bot.send_animation(
                chat_id=update.effective_chat.id,
                animation=signals_gif_url,
                caption="<b>📈 Signal Management</b>\n\nManage your trading signals",
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            return SIGNALS
        except Exception as delete_error:
            self.logger.warning(f"Could not delete message: {str(delete_error)}")
            
            # Fallback to update message
            await self.update_message(
                query=query,
                text="<b>📈 Signal Management</b>\n\nManage your trading signals",
                keyboard=reply_markup
            )
        
        return SIGNALS
        
    async def get_subscribers_for_instrument(self, instrument: str, timeframe: str = None) -> List[int]:
        """
        Get a list of subscribed user IDs for a specific instrument and timeframe
        
        Args:
            instrument: The trading instrument (e.g., EURUSD)
            timeframe: Optional timeframe filter
            
        Returns:
            List of subscribed user IDs
        """
        try:
            logger.info(f"Getting subscribers for {instrument} timeframe: {timeframe}")
            
            # Get all subscribers from the database
            # Note: Using get_signal_subscriptions instead of find_all
            subscribers = await self.db.get_signal_subscriptions(instrument, timeframe)
            
            if not subscribers:
                logger.warning(f"No subscribers found for {instrument}")
                return []
                
            # Filter out subscribers that don't have an active subscription
            active_subscribers = []
            for subscriber in subscribers:
                user_id = subscriber['user_id']
                
                # Check if user is subscribed
                is_subscribed = await self.db.is_user_subscribed(user_id)
                
                # Check if payment has failed
                payment_failed = await self.db.has_payment_failed(user_id)
                
                if is_subscribed and not payment_failed:
                    active_subscribers.append(user_id)
                else:
                    logger.info(f"User {user_id} doesn't have an active subscription, skipping signal")
            
            return active_subscribers
            
        except Exception as e:
            logger.error(f"Error getting subscribers: {str(e)}")
            # FOR TESTING: Add admin users if available
            if hasattr(self, 'admin_users') and self.admin_users:
                logger.info(f"Returning admin users for testing: {self.admin_users}")
                return self.admin_users
            return []

    async def process_signal(self, signal_data: Dict[str, Any]) -> bool:
        """
        Process a trading signal from TradingView webhook or API
        
        Supports two formats:
        1. TradingView format: instrument, signal, price, sl, tp1, tp2, tp3, interval
        2. Custom format: instrument, direction, entry, stop_loss, take_profit, timeframe
        
        Returns:
            bool: True if signal was processed successfully, False otherwise
        """
        try:
            # Log the incoming signal data
            logger.info(f"Processing signal: {signal_data}")
            
            # Check which format we're dealing with and normalize it
            instrument = signal_data.get('instrument')
            
            # Handle TradingView format (price, sl, interval)
            if 'price' in signal_data and 'sl' in signal_data:
                price = signal_data.get('price')
                sl = signal_data.get('sl')
                tp1 = signal_data.get('tp1')
                tp2 = signal_data.get('tp2')
                tp3 = signal_data.get('tp3')
                interval = signal_data.get('interval', '1h')
                
                # Determine signal direction based on price and SL relationship
                direction = "BUY" if float(sl) < float(price) else "SELL"
                
                # Create normalized signal data
                normalized_data = {
                    'instrument': instrument,
                    'direction': direction,
                    'entry': price,
                    'stop_loss': sl,
                    'take_profit': tp1,  # Use first take profit level
                    'timeframe': interval
                }
                
                # Add optional fields if present
                normalized_data['tp1'] = tp1
                normalized_data['tp2'] = tp2
                normalized_data['tp3'] = tp3
            
            # Handle custom format (direction, entry, stop_loss, timeframe)
            elif 'direction' in signal_data and 'entry' in signal_data:
                direction = signal_data.get('direction')
                entry = signal_data.get('entry')
                stop_loss = signal_data.get('stop_loss')
                take_profit = signal_data.get('take_profit')
                timeframe = signal_data.get('timeframe', '1h')
                
                # Create normalized signal data
                normalized_data = {
                    'instrument': instrument,
                    'direction': direction,
                    'entry': entry,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'timeframe': timeframe
                }
            else:
                logger.error(f"Missing required signal data")
                return False
            
            # Basic validation
            if not normalized_data.get('instrument') or not normalized_data.get('direction') or not normalized_data.get('entry'):
                logger.error(f"Missing required fields in normalized signal data: {normalized_data}")
                return False
                
            # Create signal ID for tracking
            signal_id = f"{normalized_data['instrument']}_{normalized_data['direction']}_{normalized_data['timeframe']}_{int(time.time())}"
            
            # Format the signal message
            message = self._format_signal_message(normalized_data)
            
            # Determine market type for the instrument
            market_type = _detect_market(instrument)
            
            # Store the full signal data for reference
            normalized_data['id'] = signal_id
            normalized_data['timestamp'] = datetime.now().isoformat()
            normalized_data['message'] = message
            normalized_data['market'] = market_type
            
            # Save signal for history tracking
            if not os.path.exists(self.signals_dir):
                os.makedirs(self.signals_dir, exist_ok=True)
                
            # Save to signals directory
            with open(f"{self.signals_dir}/{signal_id}.json", 'w') as f:
                json.dump(normalized_data, f)
            
            # FOR TESTING: Always send to admin for testing
            if hasattr(self, 'admin_users') and self.admin_users:
                try:
                    logger.info(f"Sending signal to admin users for testing: {self.admin_users}")
                    for admin_id in self.admin_users:
                        # Prepare keyboard with analysis options
                        keyboard = [
                            [InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_from_signal_{instrument}_{signal_id}")]
                        ]
                        
                        # Send the signal
                        await self.bot.send_message(
                            chat_id=admin_id,
                            text=message,
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        logger.info(f"Test signal sent to admin {admin_id}")
                        
                        # Store signal reference for quick access
                        if not hasattr(self, 'user_signals'):
                            self.user_signals = {}
                            
                        admin_str_id = str(admin_id)
                        if admin_str_id not in self.user_signals:
                            self.user_signals[admin_str_id] = {}
                        
                        self.user_signals[admin_str_id][signal_id] = normalized_data
                except Exception as e:
                    logger.error(f"Error sending test signal to admin: {str(e)}")
            
            # Get subscribers for this instrument
            timeframe = normalized_data.get('timeframe', '1h')
            subscribers = await self.get_subscribers_for_instrument(instrument, timeframe)
            
            if not subscribers:
                logger.warning(f"No subscribers found for {instrument}")
                return True  # Successfully processed, just no subscribers
            
            # Send signal to all subscribers
            logger.info(f"Sending signal {signal_id} to {len(subscribers)} subscribers")
            
            sent_count = 0
            for user_id in subscribers:
                try:
                    # Prepare keyboard with analysis options
                    keyboard = [
                        [InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_from_signal_{instrument}_{signal_id}")]
                    ]
                    
                    # Send the signal
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    
                    sent_count += 1
                    
                    # Store signal reference for quick access
                    if not hasattr(self, 'user_signals'):
                        self.user_signals = {}
                        
                    user_str_id = str(user_id)
                    if user_str_id not in self.user_signals:
                        self.user_signals[user_str_id] = {}
                    
                    self.user_signals[user_str_id][signal_id] = normalized_data
                    
                except Exception as e:
                    logger.error(f"Error sending signal to user {user_id}: {str(e)}")
            
            logger.info(f"Successfully sent signal {signal_id} to {sent_count}/{len(subscribers)} subscribers")
            return True
            
        except Exception as e:
            logger.error(f"Error processing signal: {str(e)}")
            logger.exception(e)
            return False

    def _format_signal_message(self, signal_data: Dict[str, Any]) -> str:
        """Format signal data into a nice message for Telegram"""
        try:
            # Extract fields from signal data
            instrument = signal_data.get('instrument', 'Unknown')
            direction = signal_data.get('direction', 'Unknown')
            entry = signal_data.get('entry', 'Unknown')
            stop_loss = signal_data.get('stop_loss')
            take_profit = signal_data.get('take_profit')
            timeframe = signal_data.get('timeframe', '1h')
            
            # Get multiple take profit levels if available
            tp1 = signal_data.get('tp1', take_profit)
            tp2 = signal_data.get('tp2')
            tp3 = signal_data.get('tp3')
            
            # Add emoji based on direction
            direction_emoji = "🟢" if direction.upper() == "BUY" else "🔴"
            
            # Format the message with multiple take profits if available
            message = f"<b>🎯 New Trading Signal 🎯</b>\n\n"
            message += f"<b>Instrument:</b> {instrument}\n"
            message += f"<b>Action:</b> {direction.upper()} {direction_emoji}\n\n"
            message += f"<b>Entry Price:</b> {entry}\n"
            
            if stop_loss:
                message += f"<b>Stop Loss:</b> {stop_loss} 🔴\n"
            
            # Add take profit levels
            if tp1:
                message += f"<b>Take Profit 1:</b> {tp1} 🎯\n"
            if tp2:
                message += f"<b>Take Profit 2:</b> {tp2} 🎯\n"
            if tp3:
                message += f"<b>Take Profit 3:</b> {tp3} 🎯\n"
            
            message += f"\n<b>Timeframe:</b> {timeframe}\n"
            message += f"<b>Strategy:</b> TradingView Signal\n\n"
            
            message += "————————————————————\n\n"
            message += "<b>Risk Management:</b>\n"
            message += "• Position size: 1-2% max\n"
            message += "• Use proper stop loss\n"
            message += "• Follow your trading plan\n\n"
            
            message += "————————————————————\n\n"
            
            # Generate AI verdict
            ai_verdict = f"The {instrument} {direction.lower()} signal shows a promising setup with defined entry at {entry} and stop loss at {stop_loss}. Multiple take profit levels provide opportunities for partial profit taking."
            message += f"<b>🤖 SigmaPips AI Verdict:</b>\n{ai_verdict}"
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting signal message: {str(e)}")
            # Return simple message on error
            return f"New {signal_data.get('instrument', 'Unknown')} {signal_data.get('direction', 'Unknown')} Signal"

    def _register_handlers(self, application):
        """Register event handlers for bot commands and callback queries"""
        try:
            logger.info("Registering command handlers")
            
            # Initialize the application without using run_until_complete
            try:
                # Instead of using loop.run_until_complete, directly call initialize 
                # which will be properly awaited by the caller
                self.init_task = application.initialize()
                logger.info("Telegram application initialization ready to be awaited")
            except Exception as init_e:
                logger.error(f"Error during application initialization: {str(init_e)}")
                logger.exception(init_e)
                
            # Set bot commands for menu
            commands = [
                BotCommand("start", "Start the bot and get the welcome message"),
                BotCommand("menu", "Show the main menu"),
                BotCommand("help", "Show available commands and how to use the bot")
            ]
            
            # Store the set_commands task to be awaited later
            try:
                # Instead of asyncio.create_task, we will await this in the startup event
                self.set_commands_task = self.bot.set_my_commands(commands)
                logger.info("Bot commands ready to be set")
            except Exception as cmd_e:
                logger.error(f"Error preparing bot commands: {str(cmd_e)}")
            
            # Register command handlers
            application.add_handler(CommandHandler("start", self.start_command))
            application.add_handler(CommandHandler("menu", self.menu_command))
            application.add_handler(CommandHandler("help", self.help_command))
            
            # Register callback handlers
            application.add_handler(CallbackQueryHandler(self.menu_analyse_callback, pattern="^menu_analyse$"))
            application.add_handler(CallbackQueryHandler(self.menu_signals_callback, pattern="^menu_signals$"))
            application.add_handler(CallbackQueryHandler(self.signals_add_callback, pattern="^signals_add$"))
            application.add_handler(CallbackQueryHandler(self.signals_manage_callback, pattern="^signals_manage$"))
            application.add_handler(CallbackQueryHandler(self.market_callback, pattern="^market_"))
            application.add_handler(CallbackQueryHandler(self.instrument_callback, pattern="^instrument_(?!.*_signals)"))
            application.add_handler(CallbackQueryHandler(self.instrument_signals_callback, pattern="^instrument_.*_signals$"))
            
            # Add handler for back buttons
            application.add_handler(CallbackQueryHandler(self.back_market_callback, pattern="^back_market$"))
            application.add_handler(CallbackQueryHandler(self.back_instrument_callback, pattern="^back_instrument$"))
            application.add_handler(CallbackQueryHandler(self.back_signals_callback, pattern="^back_signals$"))
            application.add_handler(CallbackQueryHandler(self.back_menu_callback, pattern="^back_menu$"))
            
            # Analysis handlers for regular flow
            application.add_handler(CallbackQueryHandler(self.analysis_technical_callback, pattern="^analysis_technical$"))
            application.add_handler(CallbackQueryHandler(self.analysis_sentiment_callback, pattern="^analysis_sentiment$"))
            application.add_handler(CallbackQueryHandler(self.analysis_calendar_callback, pattern="^analysis_calendar$"))
            
            # Analysis handlers for signal flow - with instrument embedded in callback
            application.add_handler(CallbackQueryHandler(self.analysis_technical_callback, pattern="^analysis_technical_signal_.*$"))
            application.add_handler(CallbackQueryHandler(self.analysis_sentiment_callback, pattern="^analysis_sentiment_signal_.*$"))
            application.add_handler(CallbackQueryHandler(self.analysis_calendar_callback, pattern="^analysis_calendar_signal_.*$"))
            
            # Signal analysis flow handlers
            application.add_handler(CallbackQueryHandler(self.signal_technical_callback, pattern="^signal_technical$"))
            application.add_handler(CallbackQueryHandler(self.signal_sentiment_callback, pattern="^signal_sentiment$"))
            application.add_handler(CallbackQueryHandler(self.signal_calendar_callback, pattern="^signal_calendar$"))
            application.add_handler(CallbackQueryHandler(self.signal_calendar_callback, pattern="^signal_flow_calendar_.*$"))
            application.add_handler(CallbackQueryHandler(self.back_to_signal_callback, pattern="^back_to_signal$"))
            application.add_handler(CallbackQueryHandler(self.back_to_signal_analysis_callback, pattern="^back_to_signal_analysis$"))
            
            # Signal from analysis
            application.add_handler(CallbackQueryHandler(self.analyze_from_signal_callback, pattern="^analyze_from_signal_.*$"))
            
            # Catch-all handler for any other callbacks
            application.add_handler(CallbackQueryHandler(self.button_callback))
            
            # Load signals
            self._load_signals()
            
            logger.info("Bot setup completed successfully")
            
        except Exception as e:
            logger.error(f"Error setting up bot handlers: {str(e)}")
            logger.exception(e)

    @property
    def signals_enabled(self):
        """Get whether signals processing is enabled"""
        return self._signals_enabled
    
    @signals_enabled.setter
    def signals_enabled(self, value):
        """Set whether signals processing is enabled"""
        self._signals_enabled = bool(value)
        logger.info(f"Signal processing is now {'enabled' if value else 'disabled'}")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Send a welcome message when the bot is started."""
        user = update.effective_user
        user_id = user.id
        first_name = user.first_name
        
        # Try to add the user to the database if they don't exist yet
        try:
            # Get user subscription since we can't check if user exists directly
            existing_subscription = await self.db.get_user_subscription(user_id)
            
            if not existing_subscription:
                # Add new user
                logger.info(f"New user started: {user_id}, {first_name}")
                await self.db.save_user(user_id, first_name, None, user.username)
            else:
                logger.info(f"Existing user started: {user_id}, {first_name}")
                
        except Exception as e:
            logger.error(f"Error registering user: {str(e)}")
        
        # Check if the user has a subscription 
        is_subscribed = await self.db.is_user_subscribed(user_id)
        
        # Check if payment has failed
        payment_failed = await self.db.has_payment_failed(user_id)
        
        if is_subscribed and not payment_failed:
            # For subscribed users, direct them to use the /menu command instead
            await update.message.reply_text(
                text="Welcome back! Please use the /menu command to access all features.",
                parse_mode=ParseMode.HTML
            )
            return
        elif payment_failed:
            # Show payment failure message
            failed_payment_text = f"""
❗ <b>Subscription Payment Failed</b> ❗

Your subscription payment could not be processed and your service has been deactivated.

To continue using Sigmapips AI and receive trading signals, please reactivate your subscription by clicking the button below.
            """
            
            # Use direct URL link for reactivation
            reactivation_url = "https://buy.stripe.com/9AQcPf3j63HL5JS145"
            
            # Create button for reactivation
            keyboard = [
                [InlineKeyboardButton("🔄 Reactivate Subscription", url=reactivation_url)]
            ]
            
            await update.message.reply_text(
                text=failed_payment_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        else:
            # Show the welcome message with trial option from the screenshot
            welcome_text = """
🚀 Welcome to Sigmapips AI! 🚀

Discover powerful trading signals for various markets:
• Forex - Major and minor currency pairs

• Crypto - Bitcoin, Ethereum and other top
 cryptocurrencies

• Indices - Global market indices

• Commodities - Gold, silver and oil

Features:
✅ Real-time trading signals

✅ Multi-timeframe analysis (1m, 15m, 1h, 4h)

✅ Advanced chart analysis

✅ Sentiment indicators

✅ Economic calendar integration

Start today with a FREE 14-day trial!
            """
            
            # Use direct URL link instead of callback for the trial button
            checkout_url = "https://buy.stripe.com/3cs3eF9Hu9256NW9AA"
            
            # Create buttons - Trial button goes straight to Stripe checkout
            keyboard = [
                [InlineKeyboardButton("🔥 Start 14-day FREE Trial", url=checkout_url)]
            ]
            
            # Gebruik de juiste welkomst-GIF URL
            welcome_gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
            
            try:
                # Send the GIF with caption containing the welcome message
                await update.message.reply_animation(
                    animation=welcome_gif_url,
                    caption=welcome_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Error sending welcome GIF with caption: {str(e)}")
                # Fallback to text-only message if GIF fails
                await update.message.reply_text(
                    text=welcome_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
    async def set_subscription_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Secret command to manually set subscription status for a user"""
        # Check if the command has correct arguments
        if not context.args or len(context.args) < 3:
            await update.message.reply_text("Usage: /set_subscription [chatid] [status] [days]")
            return
            
        try:
            # Parse arguments
            chat_id = int(context.args[0])
            status = context.args[1].lower()
            days = int(context.args[2])
            
            # Validate status
            if status not in ["active", "inactive"]:
                await update.message.reply_text("Status must be 'active' or 'inactive'")
                return
                
            # Calculate dates
            now = datetime.now()
            
            if status == "active":
                # Set active subscription
                start_date = now
                end_date = now + timedelta(days=days)
                
                # Save subscription to database
                await self.db.save_user_subscription(
                    chat_id, 
                    "monthly", 
                    start_date, 
                    end_date
                )
                await update.message.reply_text(f"✅ Subscription set to ACTIVE for user {chat_id} for {days} days")
                
            else:
                # Set inactive subscription by setting end date in the past
                start_date = now - timedelta(days=30)
                end_date = now - timedelta(days=1)
                
                # Save expired subscription to database
                await self.db.save_user_subscription(
                    chat_id, 
                    "monthly", 
                    start_date, 
                    end_date
                )
                await update.message.reply_text(f"✅ Subscription set to INACTIVE for user {chat_id}")
                
            logger.info(f"Manually set subscription status to {status} for user {chat_id}")
            
        except ValueError:
            await update.message.reply_text("Invalid arguments. Chat ID and days must be numbers.")
        except Exception as e:
            logger.error(f"Error setting subscription: {str(e)}")
            await update.message.reply_text(f"Error: {str(e)}")
            
    async def set_payment_failed_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Secret command to set a user's subscription to the payment failed state"""
        logger.info(f"set_payment_failed command received: {update.message.text}")
        
        try:
            # Extract chat_id directly from the message text if present
            command_parts = update.message.text.split()
            if len(command_parts) > 1:
                try:
                    chat_id = int(command_parts[1])
                    logger.info(f"Extracted chat ID from message: {chat_id}")
                except ValueError:
                    logger.error(f"Invalid chat ID format in message: {command_parts[1]}")
                    await update.message.reply_text(f"Invalid chat ID format: {command_parts[1]}")
                    return
            # Fallback to context args if needed
            elif context and context.args and len(context.args) > 0:
                chat_id = int(context.args[0])
                logger.info(f"Using chat ID from context args: {chat_id}")
            else:
                # Default to the user's own ID
                chat_id = update.effective_user.id
                logger.info(f"No chat ID provided, using sender's ID: {chat_id}")
            
            # Set payment failed status in database
            success = await self.db.set_payment_failed(chat_id)
            
            if success:
                message = f"✅ Payment status set to FAILED for user {chat_id}"
                logger.info(f"Manually set payment failed status for user {chat_id}")
                
                # Show the payment failed interface immediately
                failed_payment_text = f"""
❗ <b>Subscription Payment Failed</b> ❗

Your subscription payment could not be processed and your service has been deactivated.

To continue using Sigmapips AI and receive trading signals, please reactivate your subscription by clicking the button below.
                """
                
                # Use direct URL link for reactivation
                reactivation_url = "https://buy.stripe.com/9AQcPf3j63HL5JS145"
                
                # Create button for reactivation
                keyboard = [
                    [InlineKeyboardButton("🔄 Reactivate Subscription", url=reactivation_url)]
                ]
                
                # First send success message
                await update.message.reply_text(message)
                
                # Then show payment failed interface
                await update.message.reply_text(
                    text=failed_payment_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            else:
                message = f"❌ Could not set payment failed status for user {chat_id}"
                logger.error("Database returned failure")
                await update.message.reply_text(message)
                
        except ValueError as e:
            error_msg = f"Invalid argument. Chat ID must be a number. Error: {str(e)}"
            logger.error(error_msg)
            await update.message.reply_text(error_msg)
        except Exception as e:
            error_msg = f"Error setting payment failed status: {str(e)}"
            logger.error(error_msg)
            await update.message.reply_text(error_msg)

    async def menu_analyse_callback(self, update: Update, context=None) -> int:
        """Handle menu_analyse button press"""
        query = update.callback_query
        await query.answer()
        
        # Set proper context to ensure we're in menu flow, not signal flow
        if context and hasattr(context, 'user_data'):
            # Reset all context data to ensure clean separation between flows
            context.user_data.clear()
            
            # Explicitly set the signals context flag to False - this is critical
            context.user_data['is_signals_context'] = False
            context.user_data['from_signal'] = False
            
            logger.info(f"Set menu flow context: {context.user_data}")
        
        # Gebruik de juiste analyse GIF URL
        gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
        
        # Probeer eerst het huidige bericht te verwijderen en een nieuw bericht te sturen met de analyse GIF
        try:
            await query.message.delete()
            await context.bot.send_animation(
                chat_id=update.effective_chat.id,
                animation=gif_url,
                caption="Select your analysis type:",
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                parse_mode=ParseMode.HTML
            )
            return CHOOSE_ANALYSIS
        except Exception as delete_error:
            logger.warning(f"Could not delete message: {str(delete_error)}")
            
            # Als verwijderen mislukt, probeer de media te updaten
            try:
                await query.edit_message_media(
                    media=InputMediaAnimation(
                        media=gif_url,
                        caption="Select your analysis type:"
                    ),
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
                return CHOOSE_ANALYSIS
            except Exception as media_error:
                logger.warning(f"Could not update media: {str(media_error)}")
                
                # Als media update mislukt, probeer tekst te updaten
                try:
                    await query.edit_message_text(
                        text="Select your analysis type:",
                        reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as text_error:
                    # Als tekst updaten mislukt, probeer bijschrift te updaten
                    if "There is no text in the message to edit" in str(text_error):
                        try:
                            await query.edit_message_caption(
                                caption="Select your analysis type:",
                                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                                parse_mode=ParseMode.HTML
                            )
                        except Exception as caption_error:
                            logger.error(f"Failed to update caption: {str(caption_error)}")
                            # Laatste redmiddel: stuur een nieuw bericht
                            await context.bot.send_animation(
                                chat_id=update.effective_chat.id,
                                animation=gif_url,
                                caption="Select your analysis type:",
                                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                                parse_mode=ParseMode.HTML
                            )
                    else:
                        logger.error(f"Failed to update message: {str(text_error)}")
                        # Laatste redmiddel: stuur een nieuw bericht
                        await context.bot.send_animation(
                            chat_id=update.effective_chat.id,
                            animation=gif_url,
                            caption="Select your analysis type:",
                            reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                            parse_mode=ParseMode.HTML
                        )
        
        return CHOOSE_ANALYSIS

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None, skip_gif=False) -> None:
        """Show the main menu when /menu command is used"""
        # Use context.bot if available, otherwise use self.bot
        bot = context.bot if context is not None else self.bot
        
        # Check if the user has a subscription
        user_id = update.effective_user.id
        is_subscribed = await self.db.is_user_subscribed(user_id)
        payment_failed = await self.db.has_payment_failed(user_id)
        
        if is_subscribed and not payment_failed:
            # Show the main menu for subscribed users
            reply_markup = InlineKeyboardMarkup(START_KEYBOARD)
            
            # Forceer altijd de welkomst GIF
            gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
            
            # If we should show the GIF
            if not skip_gif:
                try:
                    # For message commands we can use reply_animation
                    if hasattr(update, 'message') and update.message:
                        # Verwijder eventuele vorige berichten met callback query
                        if hasattr(update, 'callback_query') and update.callback_query:
                            try:
                                await update.callback_query.message.delete()
                            except Exception:
                                pass
                        
                        # Send the GIF using regular animation method
                        await update.message.reply_animation(
                            animation=gif_url,
                            caption=WELCOME_MESSAGE,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                    else:
                        # Voor callback_query, verwijder huidige bericht en stuur nieuw bericht
                        if hasattr(update, 'callback_query') and update.callback_query:
                            try:
                                # Verwijder het huidige bericht
                                await update.callback_query.message.delete()
                                
                                # Stuur nieuw bericht met de welkomst GIF
                                await bot.send_animation(
                                    chat_id=update.effective_chat.id,
                                    animation=gif_url,
                                    caption=WELCOME_MESSAGE,
                                    parse_mode=ParseMode.HTML,
                                    reply_markup=reply_markup
                                )
                            except Exception as e:
                                logger.error(f"Failed to handle callback query: {str(e)}")
                                # Valt terug op tekstwijziging als verwijderen niet lukt
                                await update.callback_query.edit_message_text(
                                    text=WELCOME_MESSAGE,
                                    parse_mode=ParseMode.HTML,
                                    reply_markup=reply_markup
                                )
                        else:
                            # Final fallback - try to send a new message
                            await bot.send_animation(
                                chat_id=update.effective_chat.id,
                                animation=gif_url,
                                caption=WELCOME_MESSAGE,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup
                            )
                except Exception as e:
                    logger.error(f"Failed to send menu GIF: {str(e)}")
                    # Fallback to text-only approach
                    if hasattr(update, 'message') and update.message:
                        await update.message.reply_text(
                            text=WELCOME_MESSAGE,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                    else:
                        await bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=WELCOME_MESSAGE,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
            else:
                # Skip GIF mode - just send text
                if hasattr(update, 'message') and update.message:
                    await update.message.reply_text(
                        text=WELCOME_MESSAGE,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
                else:
                    await bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=WELCOME_MESSAGE,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
        else:
            # Handle non-subscribed users similar to start command
            await self.start_command(update, context)
            
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Send a message when the command /help is issued."""
        await self.show_main_menu(update, context)
        
    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Send a message when the command /menu is issued."""
        await self.show_main_menu(update, context)
        
    async def analysis_technical_callback(self, update: Update, context=None) -> int:
        """Handle analysis_technical button press"""
        query = update.callback_query
        await query.answer()
        
        # Check if signal-specific data is present in callback data
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'technical'
        
        # Set the callback data
        callback_data = query.data
        
        # Set the instrument if it was passed in the callback data
        if callback_data.startswith("analysis_technical_signal_"):
            # Extract instrument from the callback data
            instrument = callback_data.replace("analysis_technical_signal_", "")
            if context and hasattr(context, 'user_data'):
                context.user_data['instrument'] = instrument
            
            logger.info(f"Technical analysis for specific instrument: {instrument}")
            
            # Show analysis directly for this instrument
            return await self.show_technical_analysis(update, context, instrument=instrument)
        
        # Show the market selection menu
        try:
            # First try to edit message text
            await query.edit_message_text(
                text="Select market for technical analysis:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
            )
        except Exception as text_error:
            # If that fails due to caption, try editing caption
            if "There is no text in the message to edit" in str(text_error):
                try:
                    await query.edit_message_caption(
                        caption="Select market for technical analysis:",
                        reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to update caption in analysis_technical_callback: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text="Select market for technical analysis:",
                        reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
            else:
                # Re-raise for other errors
                raise
        
        return CHOOSE_MARKET
        
    async def analysis_sentiment_callback(self, update: Update, context=None) -> int:
        """Handle analysis_sentiment button press"""
        query = update.callback_query
        await query.answer()
        
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'sentiment'
        
        # Set the callback data
        callback_data = query.data
        
        # Set the instrument if it was passed in the callback data
        if callback_data.startswith("analysis_sentiment_signal_"):
            # Extract instrument from the callback data
            instrument = callback_data.replace("analysis_sentiment_signal_", "")
            if context and hasattr(context, 'user_data'):
                context.user_data['instrument'] = instrument
            
            logger.info(f"Sentiment analysis for specific instrument: {instrument}")
            
            # Show analysis directly for this instrument
            return await self.show_sentiment_analysis(update, context, instrument=instrument)
            
        # Show the market selection menu
        try:
            # First try to edit message text
            await query.edit_message_text(
                text="Select market for sentiment analysis:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
            )
        except Exception as text_error:
            # If that fails due to caption, try editing caption
            if "There is no text in the message to edit" in str(text_error):
                try:
                    await query.edit_message_caption(
                        caption="Select market for sentiment analysis:",
                        reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to update caption in analysis_sentiment_callback: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text="Select market for sentiment analysis:",
                        reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
            else:
                # Re-raise for other errors
                raise
        
        return CHOOSE_MARKET
        
    async def analysis_calendar_callback(self, update: Update, context=None) -> int:
        """Handle analysis_calendar button press"""
        query = update.callback_query
        await query.answer()
        
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'calendar'
            
        # Set the callback data
        callback_data = query.data
        
        # Set the instrument if it was passed in the callback data
        if callback_data.startswith("analysis_calendar_signal_"):
            # Extract instrument from the callback data
            instrument = callback_data.replace("analysis_calendar_signal_", "")
            if context and hasattr(context, 'user_data'):
                context.user_data['instrument'] = instrument
            
            logger.info(f"Calendar analysis for specific instrument: {instrument}")
            
            # Show analysis directly for this instrument
            return await self.show_calendar_analysis(update, context, instrument=instrument)
        
        # Skip market selection and go directly to calendar analysis
        logger.info("Showing economic calendar without market selection")
        return await self.show_calendar_analysis(update, context)

    async def show_economic_calendar(self, update: Update, context: CallbackContext, currency=None, loading_message=None):
        """Show the economic calendar for a specific currency"""
        try:
            # VERIFICATION MARKER: SIGMAPIPS_CALENDAR_FIX_APPLIED
            self.logger.info("VERIFICATION MARKER: SIGMAPIPS_CALENDAR_FIX_APPLIED")
            
            chat_id = update.effective_chat.id
            query = update.callback_query
            
            # Log that we're showing the calendar
            self.logger.info(f"Showing economic calendar for all major currencies")
            
            # Initialize the calendar service
            calendar_service = self._get_calendar_service()
            cache_size = len(getattr(calendar_service, 'cache', {}))
            self.logger.info(f"Calendar service initialized, cache size: {cache_size}")
            
            # Check if API key is available
            tavily_api_key = os.environ.get("TAVILY_API_KEY", "")
            if tavily_api_key:
                masked_key = f"{tavily_api_key[:4]}..." if len(tavily_api_key) > 7 else "***"
                self.logger.info(f"Tavily API key is available: {masked_key}")
            else:
                self.logger.warning("No Tavily API key found, will use mock data")
            
            # Get calendar data for ALL major currencies, regardless of the supplied parameter
            self.logger.info(f"Requesting calendar data for all major currencies")
            
            calendar_data = []
            
            # Get all currencies data
            try:
                if hasattr(calendar_service, 'get_calendar'):
                    calendar_data = await calendar_service.get_calendar()
                else:
                    self.logger.warning("calendar_service.get_calendar method not available, using mock data")
                    calendar_data = []
            except Exception as e:
                self.logger.warning(f"Error getting calendar data: {str(e)}")
                calendar_data = []
            
            # Check if data is empty
            if not calendar_data or len(calendar_data) == 0:
                self.logger.warning("Calendar data is empty, using mock data...")
                # Generate mock data
                today_date = datetime.now().strftime("%B %d, %Y")
                
                # Use the mock data generator from the calendar service if available
                if hasattr(calendar_service, '_generate_mock_calendar_data'):
                    mock_data = calendar_service._generate_mock_calendar_data(MAJOR_CURRENCIES, today_date)
                else:
                    # Otherwise use our own implementation
                    mock_data = self._generate_mock_calendar_data(MAJOR_CURRENCIES, today_date)
                
                # Flatten the mock data
                flattened_mock = []
                for currency_code, events in mock_data.items():
                    for event in events:
                        flattened_mock.append({
                            "time": event.get("time", ""),
                            "country": currency_code,
                            "country_flag": CURRENCY_FLAG.get(currency_code, ""),
                            "title": event.get("event", ""),
                            "impact": event.get("impact", "Low")
                        })
                
                calendar_data = flattened_mock
                self.logger.info(f"Generated {len(flattened_mock)} mock calendar events")
            
            # Format the calendar data in chronological order
            if hasattr(self, '_format_calendar_events'):
                message = await self._format_calendar_events(calendar_data)
            else:
                # Fallback to calendar service formatting if the method doesn't exist on TelegramService
                if hasattr(calendar_service, '_format_calendar_response'):
                    message = await calendar_service._format_calendar_response(calendar_data, "ALL")
                else:
                    # Simple formatting fallback
                    message = "<b>📅 Economic Calendar</b>\n\n"
                    for event in calendar_data[:10]:  # Limit to first 10 events
                        country = event.get('country', 'Unknown')
                        title = event.get('title', 'Unknown Event')
                        time = event.get('time', 'Unknown Time')
                        message += f"{country}: {time} - {title}\n\n"
            
            # Create keyboard with back button if not provided from caller
            keyboard = None
            if context and hasattr(context, 'user_data') and context.user_data.get('from_signal', False):
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")]])
            else:
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_analyse")]])
            
            # Try to delete loading message first if it exists
            if loading_message:
                try:
                    await loading_message.delete()
                    self.logger.info("Successfully deleted loading message")
                except Exception as delete_error:
                    self.logger.warning(f"Could not delete loading message: {str(delete_error)}")
                    
                    # If deletion fails, try to edit it
                    try:
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=loading_message.message_id,
                            text=message,
                            parse_mode=ParseMode.HTML,
                            reply_markup=keyboard
                        )
                        self.logger.info("Edited loading message with calendar data")
                        return  # Skip sending a new message
                    except Exception as edit_error:
                        self.logger.warning(f"Could not edit loading message: {str(edit_error)}")
            
            # Send the message as a new message
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
            self.logger.info("Sent calendar data as new message")
        
        except Exception as e:
            self.logger.error(f"Error showing economic calendar: {str(e)}")
            self.logger.exception(e)
            
            # Send error message
            chat_id = update.effective_chat.id
            await context.bot.send_message(
                chat_id=chat_id,
                text="<b>⚠️ Error showing economic calendar</b>\n\nSorry, there was an error retrieving the economic calendar data. Please try again later.",
                parse_mode=ParseMode.HTML
            )
            
    def _generate_mock_calendar_data(self, currencies, date):
        """Generate mock calendar data if the real service fails"""
        self.logger.info(f"Generating mock calendar data for {len(currencies)} currencies")
        mock_data = {}
        
        # Impact levels
        impact_levels = ["High", "Medium", "Low"]
        
        # Possible event titles
        events = [
            "Interest Rate Decision",
            "Non-Farm Payrolls",
            "GDP Growth Rate",
            "Inflation Rate",
            "Unemployment Rate",
            "Retail Sales",
            "Manufacturing PMI",
            "Services PMI",
            "Trade Balance",
            "Consumer Confidence",
            "Building Permits",
            "Central Bank Speech",
            "Housing Starts",
            "Industrial Production"
        ]
        
        # Generate random events for each currency
        for currency in currencies:
            num_events = random.randint(1, 5)  # Random number of events per currency
            currency_events = []
            
            for _ in range(num_events):
                # Generate a random time (hour between 7-18, minute 00, 15, 30 or 45)
                hour = random.randint(7, 18)
                minute = random.choice([0, 15, 30, 45])
                time_str = f"{hour:02d}:{minute:02d} EST"
                
                # Random event and impact
                event = random.choice(events)
                impact = random.choice(impact_levels)
                
                currency_events.append({
                    "time": time_str,
                    "event": event,
                    "impact": impact
                })
            
            # Sort events by time
            mock_data[currency] = sorted(currency_events, key=lambda x: x["time"])
        
        return mock_data

    async def signal_technical_callback(self, update: Update, context=None) -> int:
        """Handle signal_technical button press"""
        query = update.callback_query
        await query.answer()
        
        # Add detailed debug logging
        logger.info(f"signal_technical_callback called with query data: {query.data}")
        
        # Save analysis type in context
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'technical'
        
        # Get the instrument from context
        instrument = None
        if context and hasattr(context, 'user_data'):
            instrument = context.user_data.get('instrument')
            # Debug log for instrument
            logger.info(f"Instrument from context: {instrument}")
        
        if instrument:
            # Set flag to indicate we're in signal flow
            if context and hasattr(context, 'user_data'):
                context.user_data['from_signal'] = True
                logger.info("Set from_signal flag to True")
            
            # Try to show loading animation first
            loading_gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
            loading_text = f"Loading {instrument} chart..."
            
            # Store the current message ID to ensure we can find it later
            message_id = query.message.message_id
            chat_id = update.effective_chat.id
            logger.info(f"Current message_id: {message_id}, chat_id: {chat_id}")
            
            loading_message = None
            
            try:
                # Try to update with animated GIF first (best visual experience)
                await query.edit_message_media(
                    media=InputMediaAnimation(
                        media=loading_gif_url,
                        caption=loading_text
                    )
                )
                logger.info(f"Successfully showed loading GIF for {instrument}")
            except Exception as media_error:
                logger.warning(f"Could not update with GIF: {str(media_error)}")
                
                # If GIF fails, try to update the text
                try:
                    loading_message = await query.edit_message_text(
                        text=loading_text
                    )
                    if context and hasattr(context, 'user_data'):
                        context.user_data['loading_message'] = loading_message
                except Exception as text_error:
                    logger.warning(f"Could not update text: {str(text_error)}")
                    
                    # If text update fails, try to update caption
                    try:
                        await query.edit_message_caption(
                            caption=loading_text
                        )
                    except Exception as caption_error:
                        logger.warning(f"Could not update caption: {str(caption_error)}")
                        
                        # Last resort - send a new message with loading GIF
                        try:
                            from trading_bot.services.telegram_service.gif_utils import send_loading_gif
                            await send_loading_gif(
                                self.bot,
                                update.effective_chat.id,
                                caption=f"⏳ <b>Analyzing technical data for {instrument}...</b>"
                            )
                        except Exception as gif_error:
                            logger.warning(f"Could not show loading GIF: {str(gif_error)}")
            
            # Show technical analysis for this instrument
            return await self.show_technical_analysis(update, context, instrument=instrument)
        else:
            # Error handling - go back to signal analysis menu
            try:
                # First try to edit message text
                await query.edit_message_text(
                    text="Could not find the instrument. Please try again.",
                    reply_markup=InlineKeyboardMarkup(SIGNAL_ANALYSIS_KEYBOARD)
                )
            except Exception as text_error:
                # If that fails due to caption, try editing caption
                if "There is no text in the message to edit" in str(text_error):
                    try:
                        await query.edit_message_caption(
                            caption="Could not find the instrument. Please try again.",
                            reply_markup=InlineKeyboardMarkup(SIGNAL_ANALYSIS_KEYBOARD),
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.error(f"Failed to update caption in signal_technical_callback: {str(e)}")
                        # Try to send a new message as last resort
                        await query.message.reply_text(
                            text="Could not find the instrument. Please try again.",
                            reply_markup=InlineKeyboardMarkup(SIGNAL_ANALYSIS_KEYBOARD),
                            parse_mode=ParseMode.HTML
                        )
                else:
                    # Re-raise for other errors
                    raise
            return CHOOSE_ANALYSIS

    async def signal_sentiment_callback(self, update: Update, context=None) -> int:
        """Handle signal_sentiment button press"""
        query = update.callback_query
        await query.answer()
        
        # Save analysis type in context
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'sentiment'
        
        # Get the instrument from context
        instrument = None
        if context and hasattr(context, 'user_data'):
            instrument = context.user_data.get('instrument')
        
        if instrument:
            # Set flag to indicate we're in signal flow
            if context and hasattr(context, 'user_data'):
                context.user_data['from_signal'] = True
            
            # Try to show loading animation first
            loading_gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
            loading_text = f"Loading sentiment analysis for {instrument}..."
            
            try:
                # Try to update with animated GIF first (best visual experience)
                await query.edit_message_media(
                    media=InputMediaAnimation(
                        media=loading_gif_url,
                        caption=loading_text
                    )
                )
                logger.info(f"Successfully showed loading GIF for {instrument} sentiment analysis")
            except Exception as media_error:
                logger.warning(f"Could not update with GIF: {str(media_error)}")
                
                # If GIF fails, try to update the text
                try:
                    loading_message = await query.edit_message_text(
                        text=loading_text
                    )
                    if context and hasattr(context, 'user_data'):
                        context.user_data['loading_message'] = loading_message
                except Exception as text_error:
                    logger.warning(f"Could not update text: {str(text_error)}")
                    
                    # If text update fails, try to update caption
                    try:
                        await query.edit_message_caption(
                            caption=loading_text
                        )
                    except Exception as caption_error:
                        logger.warning(f"Could not update caption: {str(caption_error)}")
                        
                        # Last resort - send a new message with loading GIF
                        try:
                            from trading_bot.services.telegram_service.gif_utils import send_loading_gif
                            await send_loading_gif(
                                self.bot,
                                update.effective_chat.id,
                                caption=f"⏳ <b>Analyzing market sentiment for {instrument}...</b>"
                            )
                        except Exception as gif_error:
                            logger.warning(f"Could not show loading GIF: {str(gif_error)}")
            
            # Show sentiment analysis for this instrument
            return await self.show_sentiment_analysis(update, context, instrument=instrument)
        else:
            # Error handling - go back to signal analysis menu
            try:
                # First try to edit message text
                await query.edit_message_text(
                    text="Could not find the instrument. Please try again.",
                    reply_markup=InlineKeyboardMarkup(SIGNAL_ANALYSIS_KEYBOARD)
                )
            except Exception as text_error:
                # If that fails due to caption, try editing caption
                if "There is no text in the message to edit" in str(text_error):
                    try:
                        await query.edit_message_caption(
                            caption="Could not find the instrument. Please try again.",
                            reply_markup=InlineKeyboardMarkup(SIGNAL_ANALYSIS_KEYBOARD),
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.error(f"Failed to update caption in signal_sentiment_callback: {str(e)}")
                        # Try to send a new message as last resort
                        await query.message.reply_text(
                            text="Could not find the instrument. Please try again.",
                            reply_markup=InlineKeyboardMarkup(SIGNAL_ANALYSIS_KEYBOARD),
                            parse_mode=ParseMode.HTML
                        )
                else:
                    # Re-raise for other errors
                    raise
        return CHOOSE_ANALYSIS

    async def signal_calendar_callback(self, update: Update, context=None) -> int:
        """Handle signal_calendar button press"""
        query = update.callback_query
        await query.answer()
        
        # Add detailed debug logging
        logger.info(f"signal_calendar_callback called with data: {query.data}")
        
        # Save analysis type in context
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'calendar'
            # Make sure we save the original signal data to return to later
            signal_instrument = context.user_data.get('instrument')
            signal_direction = context.user_data.get('signal_direction')
            signal_timeframe = context.user_data.get('signal_timeframe') 
            
            # Save these explicitly to ensure they're preserved
            context.user_data['signal_instrument_backup'] = signal_instrument
            context.user_data['signal_direction_backup'] = signal_direction
            context.user_data['signal_timeframe_backup'] = signal_timeframe
            
            # Log for debugging
            logger.info(f"Saved signal data before calendar analysis: instrument={signal_instrument}, direction={signal_direction}, timeframe={signal_timeframe}")
        
        # Get the instrument from context (voor tracking van context en eventuele toekomstige functionaliteit)
        instrument = None
        if context and hasattr(context, 'user_data'):
            instrument = context.user_data.get('instrument')
            logger.info(f"Instrument from context: {instrument}")
        
        # Check if the callback data contains an instrument
        if query.data.startswith("signal_flow_calendar_"):
            parts = query.data.split("_")
            if len(parts) >= 4:
                instrument = parts[3]  # Extract instrument from callback data
                logger.info(f"Extracted instrument from callback data: {instrument}")
                # Save to context
                if context and hasattr(context, 'user_data'):
                    context.user_data['instrument'] = instrument
        
        # Set flag to indicate we're in signal flow
        if context and hasattr(context, 'user_data'):
            context.user_data['from_signal'] = True
            logger.info(f"Set from_signal flag to True for calendar analysis")
        
        # Try to show loading animation first
        loading_gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
        loading_text = f"Loading economic calendar..."
        
        try:
            # Try to update with animated GIF first (best visual experience)
            await query.edit_message_media(
                media=InputMediaAnimation(
                    media=loading_gif_url,
                    caption=loading_text
                )
            )
            logger.info(f"Successfully showed loading GIF for economic calendar")
        except Exception as media_error:
            logger.warning(f"Could not update with GIF: {str(media_error)}")
            
            # If GIF fails, try to update the text
            try:
                loading_message = await query.edit_message_text(
                    text=loading_text
                )
                if context and hasattr(context, 'user_data'):
                    context.user_data['loading_message'] = loading_message
            except Exception as text_error:
                logger.warning(f"Could not update text: {str(text_error)}")
                
                # If text update fails, try to update caption
                try:
                    await query.edit_message_caption(
                        caption=loading_text
                    )
                except Exception as caption_error:
                    logger.warning(f"Could not update caption: {str(caption_error)}")
                    
                    # Last resort - send a new message with loading GIF
                    try:
                        from trading_bot.services.telegram_service.gif_utils import send_loading_gif
                        await send_loading_gif(
                            self.bot,
                            update.effective_chat.id,
                            caption=f"⏳ <b>Loading economic calendar...</b>"
                        )
                    except Exception as gif_error:
                        logger.warning(f"Could not show loading GIF: {str(gif_error)}")
        
        # Show calendar analysis for ALL major currencies
        return await self.show_calendar_analysis(update, context, instrument=None)

    async def back_to_signal_callback(self, update: Update, context=None) -> int:
        """Handle back_to_signal button press"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get the current signal being viewed
            user_id = str(update.effective_user.id)
            
            # Initialize signal context if needed
            if user_id not in self.signal_contexts:
                self.signal_contexts[user_id] = {}
            
            # First try to get signal data from backup in context
            signal_instrument = None
            signal_direction = None
            signal_timeframe = None
            
            if context and hasattr(context, 'user_data'):
                # Try to get from backup fields first (these are more reliable after navigation)
                signal_instrument = context.user_data.get('signal_instrument_backup') or context.user_data.get('signal_instrument')
                signal_direction = context.user_data.get('signal_direction_backup') or context.user_data.get('signal_direction')
                signal_timeframe = context.user_data.get('signal_timeframe_backup') or context.user_data.get('signal_timeframe')
                
                # Store in persistent signal context
                if signal_instrument:
                    self.signal_contexts[user_id]['instrument'] = signal_instrument
                if signal_direction:
                    self.signal_contexts[user_id]['direction'] = signal_direction
                if signal_timeframe:
                    self.signal_contexts[user_id]['timeframe'] = signal_timeframe
                
                # Reset signal flow flags but keep the signal info
                context.user_data['from_signal'] = True
                
                # Log retrieved values for debugging
                logger.info(f"Retrieved signal data from context: instrument={signal_instrument}, direction={signal_direction}, timeframe={signal_timeframe}")
            else:
                # Try to get from persistent signal context if context is not available
                signal_instrument = self.signal_contexts[user_id].get('instrument')
                signal_direction = self.signal_contexts[user_id].get('direction') 
                signal_timeframe = self.signal_contexts[user_id].get('timeframe')
                logger.info(f"Retrieved signal data from persistent context: instrument={signal_instrument}, direction={signal_direction}, timeframe={signal_timeframe}")
            
            # Find the most recent signal for this user based on context data
            signal_data = None
            signal_id = None
            
            # First check if we have a cached signal_id
            if 'signal_id' in self.signal_contexts[user_id]:
                cached_signal_id = self.signal_contexts[user_id]['signal_id']
                if user_id in self.user_signals and cached_signal_id in self.user_signals[user_id]:
                    signal_data = self.user_signals[user_id][cached_signal_id]
                    signal_id = cached_signal_id
                    logger.info(f"Found signal using cached signal_id: {signal_id}")
            
            # If no cached signal found, search based on parameters
            if not signal_data and signal_instrument:
                # Find matching signal based on instrument and direction
                if user_id in self.user_signals:
                    user_signal_dict = self.user_signals[user_id]
                    # Find signals matching instrument, direction and timeframe
                    matching_signals = []
                    
                    for sig_id, sig in user_signal_dict.items():
                        instrument_match = sig.get('instrument') == signal_instrument
                        direction_match = True  # Default to true if we don't have direction data
                        timeframe_match = True  # Default to true if we don't have timeframe data
                        
                        if signal_direction:
                            direction_match = sig.get('direction') == signal_direction
                        if signal_timeframe:
                            timeframe_match = sig.get('interval') == signal_timeframe
                        
                        if instrument_match and direction_match and timeframe_match:
                            matching_signals.append((sig_id, sig))
                    
                    # Sort by timestamp, newest first
                    if matching_signals:
                        matching_signals.sort(key=lambda x: x[1].get('timestamp', ''), reverse=True)
                        signal_id, signal_data = matching_signals[0]
                        
                        # Store the found signal_id in persistent context
                        self.signal_contexts[user_id]['signal_id'] = signal_id
                        
                        logger.info(f"Found matching signal with ID: {signal_id}")
                    else:
                        logger.warning(f"No matching signals found for instrument={signal_instrument}, direction={signal_direction}, timeframe={signal_timeframe}")
                        # If no exact match, try with just the instrument
                        matching_signals = []
                        for sig_id, sig in user_signal_dict.items():
                            if sig.get('instrument') == signal_instrument:
                                matching_signals.append((sig_id, sig))
                        
                        if matching_signals:
                            matching_signals.sort(key=lambda x: x[1].get('timestamp', ''), reverse=True)
                            signal_id, signal_data = matching_signals[0]
                            
                            # Store the found signal_id in persistent context
                            self.signal_contexts[user_id]['signal_id'] = signal_id
                            
                            logger.info(f"Found signal with just instrument match, ID: {signal_id}")
            
            if not signal_data:
                # Fallback message if signal not found
                await query.edit_message_text(
                    text="Signal not found. Please use the main menu to continue.",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
                return MENU
            
            # Show the signal details with analyze button
            # Prepare analyze button with signal info embedded
            keyboard = [
                [InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_from_signal_{signal_instrument}_{signal_id}")]
            ]
            
            # Get the formatted message from the signal
            signal_message = signal_data.get('message', "Signal details not available.")
            
            # Edit current message to show signal
            await query.edit_message_text(
                text=signal_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            return SIGNAL_DETAILS
            
        except Exception as e:
            logger.error(f"Error in back_to_signal_callback: {str(e)}")
            
            # Error recovery
            try:
                await query.edit_message_text(
                    text="An error occurred. Please try again from the main menu.",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
            except Exception:
                pass
            
            return MENU

    async def analyze_from_signal_callback(self, update: Update, context=None) -> int:
        """Handle Analyze Market button from signal notifications"""
        query = update.callback_query
        logger.info(f"analyze_from_signal_callback called with data: {query.data}")
        
        try:
            # Extract signal information from callback data
            parts = query.data.split('_')
            user_id = str(update.effective_user.id)
            
            # Initialize signal context if needed
            if user_id not in self.signal_contexts:
                self.signal_contexts[user_id] = {}
            
            # Format: analyze_from_signal_INSTRUMENT_SIGNALID
            if len(parts) >= 4:
                instrument = parts[3]
                signal_id = parts[4] if len(parts) >= 5 else None
                
                # Store in persistent context
                self.signal_contexts[user_id]['instrument'] = instrument
                if signal_id:
                    self.signal_contexts[user_id]['signal_id'] = signal_id
                
                # Store in conversation context too
                if context and hasattr(context, 'user_data'):
                    context.user_data['instrument'] = instrument
                    context.user_data['signal_instrument'] = instrument
                    context.user_data['signal_instrument_backup'] = instrument
                    
                    if signal_id:
                        context.user_data['signal_id'] = signal_id
                        context.user_data['signal_id_backup'] = signal_id
                
                # Also store info from the actual signal if available
                if signal_id and user_id in self.user_signals and signal_id in self.user_signals[user_id]:
                    signal = self.user_signals[user_id][signal_id]
                    if signal:
                        direction = signal.get('direction')
                        timeframe = signal.get('interval')
                        
                        # Store in persistent context
                        self.signal_contexts[user_id]['direction'] = direction
                        self.signal_contexts[user_id]['timeframe'] = timeframe
                        
                        # Store in conversation context
                        if context and hasattr(context, 'user_data'):
                            context.user_data['signal_direction'] = direction
                            context.user_data['signal_timeframe'] = timeframe
                            # Backup copies
                            context.user_data['signal_direction_backup'] = direction
                            context.user_data['signal_timeframe_backup'] = timeframe
                            logger.info(f"Stored signal details: direction={direction}, timeframe={timeframe}")
            else:
                # Legacy support - just extract the instrument
                instrument = parts[3] if len(parts) >= 4 else None
                
                if instrument:
                    # Store in persistent context
                    self.signal_contexts[user_id]['instrument'] = instrument
                    
                    # Store in conversation context
                    if context and hasattr(context, 'user_data'):
                        context.user_data['instrument'] = instrument
                        context.user_data['signal_instrument'] = instrument
                        context.user_data['signal_instrument_backup'] = instrument
            
            # Show analysis options for this instrument
            # Format message
            # Use the SIGNAL_ANALYSIS_KEYBOARD for consistency
            keyboard = SIGNAL_ANALYSIS_KEYBOARD
            
            # Try to edit the message text
            try:
                await query.edit_message_text(
                    text=f"Select your analysis type:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Error in analyze_from_signal_callback: {str(e)}")
                # Fall back to sending a new message
                await query.message.reply_text(
                    text=f"Select your analysis type:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            
            return CHOOSE_ANALYSIS
        
        except Exception as e:
            logger.error(f"Error in analyze_from_signal_callback: {str(e)}")
            logger.exception(e)
            
            try:
                await query.edit_message_text(
                    text="An error occurred. Please try again from the main menu.",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
            except Exception:
                pass
            
            return MENU

    async def button_callback(self, update: Update, context=None) -> int:
        """Handle button presses from inline keyboards"""
        query = update.callback_query
        logger.info(f"Button callback opgeroepen met data: {query.data}")
        
        # Beantwoord de callback query met een timeout-afhandeling
        try:
            # Answer without a timeout parameter (it's not supported in python-telegram-bot v20)
            await query.answer()
        except Exception as e:
            # Log de fout, maar ga door met afhandeling (voorkomt blokkering)
            logger.warning(f"Kon callback query niet beantwoorden: {str(e)}")
        
        # Signal flow specific handlers (completely separate flow)
        if query.data.startswith("signal_flow_technical_"):
            # Extract instrument and timeframe
            parts = query.data.split("_")
            if len(parts) >= 4:
                instrument = parts[3]
                timeframe = parts[4] if len(parts) > 4 else "1h"
                
                # Set signal flow context
                if context and hasattr(context, 'user_data'):
                    context.user_data['from_signal'] = True
                    context.user_data['analysis_type'] = 'technical'
                
                # Direct to technical analysis for this instrument
                return await self.show_technical_analysis(update, context, instrument=instrument, timeframe=timeframe)
                
        if query.data.startswith("signal_flow_sentiment_"):
            # Extract instrument
            instrument = query.data.replace("signal_flow_sentiment_", "")
            
            # Set signal flow context
            if context and hasattr(context, 'user_data'):
                context.user_data['from_signal'] = True
                context.user_data['analysis_type'] = 'sentiment'
            
            # Direct to sentiment analysis for this instrument
            return await self.show_sentiment_analysis(update, context, instrument=instrument)
            
        if query.data.startswith("signal_flow_calendar_"):
            # Extract instrument
            instrument = query.data.replace("signal_flow_calendar_", "")
            
            # Set signal flow context
            if context and hasattr(context, 'user_data'):
                context.user_data['from_signal'] = True
                context.user_data['analysis_type'] = 'calendar'
            
            # Direct to calendar analysis for this instrument
            return await self.show_calendar_analysis(update, context, instrument=instrument)
            
        # Regular flow handlers (old code continues below)
        # Special signal flow handlers for the dedicated signal analysis
        if query.data == "signal_technical":
            return await self.signal_technical_callback(update, context)
        elif query.data == "signal_sentiment":
            return await self.signal_sentiment_callback(update, context)
        elif query.data == "signal_calendar":
            return await self.signal_calendar_callback(update, context)
        elif query.data == "back_to_signal_analysis":
            return await self.back_to_signal_analysis_callback(update, context)
        
        # Special signal flow handlers for the regular analysis
        # Technical analysis from signal
        if query.data.startswith("analysis_technical_signal_"):
            return await self.analysis_technical_callback(update, context)
        
        # Sentiment analysis from signal
        if query.data.startswith("analysis_sentiment_signal_"):
            return await self.analysis_sentiment_callback(update, context)
        
        # Calendar analysis from signal
        if query.data.startswith("analysis_calendar_signal_"):
            return await self.analysis_calendar_callback(update, context)
        
        # Basic analysis types without signal context
        if query.data == "analysis_technical":
            return await self.analysis_technical_callback(update, context)
        
        if query.data == "analysis_sentiment":
            return await self.analysis_sentiment_callback(update, context)
        
        if query.data == "analysis_calendar":
            return await self.analysis_calendar_callback(update, context)
        
        # Analyze from signal handler
        if query.data.startswith("analyze_from_signal_"):
            return await self.analyze_from_signal_callback(update, context)
        
        # Back to signal handler
        if query.data == "back_to_signal":
            return await self.back_to_signal_callback(update, context)
        
        # Handle menu_analyse callback
        if query.data == "menu_analyse":
            return await self.menu_analyse_callback(update, context)
        
        # Handle menu_signals callback
        if query.data == "menu_signals":
            return await self.menu_signals_callback(update, context)
        
        # Handle back buttons
        if query.data == "back_menu":
            return await self.back_menu_callback(update, context)
        
        if query.data == "back_to_analysis" or query.data == "back_analysis":
            return await self.analysis_callback(update, context)
        
        if query.data == "back_market":
            return await self.back_market_callback(update, context)
        
        if query.data == "back_instrument":
            return await self.back_instrument_callback(update, context)
        
        if query.data == "back_instrument_sentiment":
            # Set the analysis type to sentiment before going back
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'sentiment'
                logger.info("Setting analysis_type to 'sentiment' for back navigation")
            return await self.back_instrument_callback(update, context)
        
        if query.data == "back_signals":
            return await self.back_signals_callback(update, context)
        
        # Handle refresh sentiment analysis 
        if query.data.startswith("instrument_") and query.data.endswith("_sentiment"):
            # Extract the instrument from the callback data
            parts = query.data.split("_")
            instrument = "_".join(parts[1:-1]) if len(parts) > 2 else parts[1]
            logger.info(f"Refreshing sentiment analysis for {instrument}")
            
            # Set analysis type to sentiment
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'sentiment'
            
            # Call show_sentiment_analysis with the instrument
            return await self.show_sentiment_analysis(update, context, instrument=instrument)
        
        # Verwerk abonnementsacties
        if query.data == "subscribe_monthly" or query.data == "subscription_info":
            return await self.handle_subscription_callback(update, context)
        
        # Analysis type handlers - other types not already handled above
        if query.data.startswith("analysis_") and not any([
            query.data.startswith("analysis_technical_signal_"),
            query.data.startswith("analysis_sentiment_signal_"),
            query.data.startswith("analysis_calendar_signal_"),
            query.data == "analysis_technical",
            query.data == "analysis_sentiment", 
            query.data == "analysis_calendar"
        ]):
            return await self.analysis_choice(update, context)
        
        # Handle show_ta_ callbacks (show technical analysis with specific timeframe)
        if query.data.startswith("show_ta_"):
            # Extract instrument and timeframe from callback data
            parts = query.data.split("_")
            if len(parts) >= 3:
                instrument = parts[2]
                timeframe = parts[3] if len(parts) > 3 else "1h"  # Default to 1h
                return await self.show_technical_analysis(update, context, instrument=instrument, timeframe=timeframe)
        
        # Verwerk instrument keuzes met specifiek type (chart, sentiment, calendar)
        if "_chart" in query.data or "_sentiment" in query.data or "_calendar" in query.data:
            # Direct doorsturen naar de instrument_callback methode
            logger.info(f"Specifiek instrument type gedetecteerd in: {query.data}")
            return await self.instrument_callback(update, context)
        
        # Handle instrument signal choices
        if "_signals" in query.data and query.data.startswith("instrument_"):
            logger.info(f"Signal instrument selection detected: {query.data}")
            return await self.instrument_signals_callback(update, context)
        
        # Speciale afhandeling voor markt keuzes
        if query.data.startswith("market_"):
            return await self.market_callback(update, context)
        
        # Signals handlers
        if query.data == "signals_add" or query.data == CALLBACK_SIGNALS_ADD:
            return await self.signals_add_callback(update, context)
            
        # Manage signals handler
        if query.data == "signals_manage" or query.data == CALLBACK_SIGNALS_MANAGE:
            return await self.signals_manage_callback(update, context)
            
        # Handle delete signal
        if query.data.startswith("delete_signal_"):
            # Extract signal ID from callback data
            signal_id = query.data.replace("delete_signal_", "")
            
            try:
                # Delete the signal subscription
                response = self.db.supabase.table('signal_subscriptions').delete().eq('id', signal_id).execute()
                
                if response and response.data:
                    # Successfully deleted
                    await query.answer("Signal subscription removed successfully")
                else:
                    # Failed to delete
                    await query.answer("Failed to remove signal subscription")
                
                # Refresh the manage signals view
                return await self.signals_manage_callback(update, context)
                
            except Exception as e:
                logger.error(f"Error deleting signal subscription: {str(e)}")
                await query.answer("Error removing signal subscription")
                return await self.signals_manage_callback(update, context)
                
        # Handle delete all signals
        if query.data == "delete_all_signals":
            user_id = update.effective_user.id
            
            try:
                # Delete all signal subscriptions for this user
                response = self.db.supabase.table('signal_subscriptions').delete().eq('user_id', user_id).execute()
                
                if response and response.data:
                    # Successfully deleted
                    await query.answer("All signal subscriptions removed successfully")
                else:
                    # Failed to delete
                    await query.answer("Failed to remove signal subscriptions")
                
                # Refresh the manage signals view
                return await self.signals_manage_callback(update, context)
                
            except Exception as e:
                logger.error(f"Error deleting all signal subscriptions: {str(e)}")
                await query.answer("Error removing signal subscriptions")
                return await self.signals_manage_callback(update, context)

    async def market_signals_callback(self, update: Update, context=None) -> int:
        """Handle signals market selection"""
        query = update.callback_query
        await query.answer()
        
        # Set the signal context flag
        if context and hasattr(context, 'user_data'):
            context.user_data['is_signals_context'] = True
        
        # Get the signals GIF URL
        gif_url = await get_signals_gif()
        
        # Update the message with the GIF and keyboard
        success = await gif_utils.update_message_with_gif(
            query=query,
            gif_url=gif_url,
            text="Select a market for trading signals:",
            reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
        )
        
        if not success:
            # If the helper function failed, try a direct approach as fallback
            try:
                # First try to edit message text
                await query.edit_message_text(
                    text="Select a market for trading signals:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
                )
            except Exception as text_error:
                # If that fails due to caption, try editing caption
                if "There is no text in the message to edit" in str(text_error):
                    try:
                        await query.edit_message_caption(
                            caption="Select a market for trading signals:",
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
                        )
                    except Exception as e:
                        logger.error(f"Failed to update caption in market_signals_callback: {str(e)}")
                        # Try to send a new message as last resort
                        await query.message.reply_text(
                            text="Select a market for trading signals:",
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
                        )
                else:
                    # Re-raise for other errors
                    raise
                    
        return CHOOSE_MARKET

    async def instrument_callback(self, update: Update, context=None) -> int:
        """Handle instrument selections with specific types (chart, sentiment, calendar)"""
        query = update.callback_query
        callback_data = query.data
        
        # Parse the callback data to extract the instrument and type
        parts = callback_data.split("_")
        # For format like "instrument_EURUSD_sentiment" or "market_forex_sentiment"
        
        if callback_data.startswith("instrument_"):
            # Extract the instrument, handling potential underscores in instrument name
            instrument_parts = []
            analysis_type = ""
            
            # Find where the type specifier starts
            for i, part in enumerate(parts[1:], 1):  # Skip "instrument_" prefix
                if part in ["chart", "sentiment", "calendar", "signals"]:
                    analysis_type = part
                    break
                instrument_parts.append(part)
            
            # Join the instrument parts if we have any
            instrument = "_".join(instrument_parts) if instrument_parts else ""
            
            logger.info(f"Instrument callback: instrument={instrument}, type={analysis_type}")
            
            # Store in context
            if context and hasattr(context, 'user_data'):
                context.user_data['instrument'] = instrument
                context.user_data['analysis_type'] = analysis_type
            
            # Handle the different analysis types
            if analysis_type == "chart":
                return await self.show_technical_analysis(update, context, instrument=instrument)
            elif analysis_type == "sentiment":
                return await self.show_sentiment_analysis(update, context, instrument=instrument)
            elif analysis_type == "calendar":
                return await self.show_calendar_analysis(update, context, instrument=instrument)
            elif analysis_type == "signals":
                # This should be handled by instrument_signals_callback
                return await self.instrument_signals_callback(update, context)
        
        elif callback_data.startswith("market_"):
            # Handle market_*_sentiment callbacks
            market = parts[1]
            analysis_type = parts[2] if len(parts) > 2 else ""
            
            logger.info(f"Market callback with analysis type: market={market}, type={analysis_type}")
            
            # Store in context
            if context and hasattr(context, 'user_data'):
                context.user_data['market'] = market
                context.user_data['analysis_type'] = analysis_type
            
            # Determine which keyboard to show based on market and analysis type
            if analysis_type == "sentiment":
                if market == "forex":
                    keyboard = FOREX_SENTIMENT_KEYBOARD
                elif market == "crypto":
                    keyboard = CRYPTO_SENTIMENT_KEYBOARD
                elif market == "indices":
                    keyboard = INDICES_SENTIMENT_KEYBOARD
                elif market == "commodities":
                    keyboard = COMMODITIES_SENTIMENT_KEYBOARD
                else:
                    keyboard = MARKET_SENTIMENT_KEYBOARD
                
                try:
                    await query.edit_message_text(
                        text=f"Select instrument for sentiment analysis:",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Error updating message in instrument_callback: {str(e)}")
                    try:
                        await query.edit_message_caption(
                            caption=f"Select instrument for sentiment analysis:",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.error(f"Error updating caption in instrument_callback: {str(e)}")
                        # Last resort - send a new message
                        await query.message.reply_text(
                            text=f"Select instrument for sentiment analysis:",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
            else:
                # For other market types, call the market_callback method
                return await self.market_callback(update, context)
        
        return CHOOSE_INSTRUMENT

    async def show_technical_analysis(self, update: Update, context=None, instrument=None, timeframe=None) -> int:
        """Show technical analysis for a specific instrument and timeframe"""
        query = update.callback_query
        
        try:
            # Add detailed debug logging
            logger.info(f"show_technical_analysis called for instrument: {instrument}, timeframe: {timeframe}")
            if query:
                logger.info(f"Query data: {query.data}")
            
            # Check if we're in signal flow
            from_signal = False
            if context and hasattr(context, 'user_data'):
                from_signal = context.user_data.get('from_signal', False)
                logger.info(f"From signal flow: {from_signal}")
                logger.info(f"Context user_data: {context.user_data}")
            
            # If no instrument is provided, try to extract it from callback data
            if not instrument and query:
                callback_data = query.data
                
                # Extract instrument from various callback data formats
                if callback_data.startswith("instrument_"):
                    # Format: instrument_EURUSD_chart
                    parts = callback_data.split("_")
                    instrument = parts[1]
                    
                elif callback_data.startswith("show_ta_"):
                    # Format: show_ta_EURUSD_1h
                    parts = callback_data.split("_")
                    if len(parts) >= 3:
                        instrument = parts[2]
                        if len(parts) >= 4:
                            timeframe = parts[3]
            
            # If still no instrument, check user data
            if not instrument and context and hasattr(context, 'user_data'):
                instrument = context.user_data.get('instrument')
                if not timeframe:
                    timeframe = context.user_data.get('timeframe')
            
            # If still no instrument, show error
            if not instrument:
                await query.edit_message_text(
                    text="Error: No instrument specified for technical analysis.",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
                return CHOOSE_ANALYSIS
            
            # Default timeframe if not provided
            if not timeframe:
                timeframe = "1h"
            
            # Get chart URL
            logger.info(f"Getting technical analysis chart for {instrument} on {timeframe} timeframe")
            
            # Check if we have a loading message in context.user_data
            loading_message = None
            if context and hasattr(context, 'user_data'):
                loading_message = context.user_data.get('loading_message')
            
            # If no loading message in context or not in signal flow, create one
            if not loading_message:
                # Show loading message with GIF - similar to sentiment analysis
                loading_text = f"Loading {instrument} chart..."
                loading_gif = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"
                
                try:
                    # Try to show animated GIF for loading
                    await query.edit_message_media(
                        media=InputMediaAnimation(
                            media=loading_gif,
                            caption=loading_text
                        )
                    )
                    logger.info(f"Successfully showed loading GIF for {instrument} technical analysis")
                except Exception as gif_error:
                    logger.warning(f"Could not show loading GIF: {str(gif_error)}")
                    # Fallback to text loading message
                    try:
                        loading_message = await query.edit_message_text(
                            text=loading_text
                        )
                    except Exception as e:
                        logger.error(f"Failed to show loading message: {str(e)}")
                        # Try to edit caption as last resort
                        try:
                            await query.edit_message_caption(caption=loading_text)
                        except Exception as caption_error:
                            logger.error(f"Failed to update caption: {str(caption_error)}")
            
            # Initialize the chart service if needed
            if not hasattr(self, 'chart_service') or not self.chart_service:
                from trading_bot.services.chart_service.chart import ChartService
                self.chart_service = ChartService()
            
            # Get the chart image
            chart_image = await self.chart_service.get_chart(instrument, timeframe)
            
            if not chart_image:
                # Fallback to error message
                error_text = f"Failed to generate chart for {instrument}. Please try again later."
                await query.edit_message_text(
                    text=error_text,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
                return MENU
            
            # Create the keyboard with appropriate back button based on flow
            keyboard = []
            
            # Add the appropriate back button based on whether we're in signal flow or menu flow
            if from_signal:
                keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")])
            else:
                keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_instrument")])
            
            # Show the chart
            try:
                logger.info(f"Sending chart image for {instrument} {timeframe}")
                # Try to send a new message with the chart
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=chart_image,
                    caption=f"{instrument} Technical Analysis",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Delete the original message (the one with the loading indicator)
                logger.info(f"Deleting original message {query.message.message_id}")
                await query.delete_message()
                logger.info("Original message deleted successfully")
                
                return SHOW_RESULT
                
            except Exception as e:
                logger.error(f"Failed to send chart: {str(e)}")
                
                # Fallback error handling
                try:
                    if loading_message:
                        await loading_message.edit_text(
                            text=f"Error sending chart for {instrument}. Please try again later.",
                            reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                        )
                    else:
                        await query.edit_message_text(
                            text=f"Error sending chart for {instrument}. Please try again later.",
                            reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                        )
                except Exception:
                    pass
                
                return MENU
        
        except Exception as e:
            logger.error(f"Error in show_technical_analysis: {str(e)}")
            # Error recovery
            try:
                await query.edit_message_text(
                    text="An error occurred. Please try again from the main menu.",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
            except Exception:
                pass
            
            return MENU

    async def show_sentiment_analysis(self, update: Update, context=None, instrument=None) -> int:
        """Show sentiment analysis for a selected instrument"""
        query = update.callback_query
        await query.answer()
        
        user_id = str(update.effective_user.id)
        
        # Check if we're in the signal flow
        is_from_signal = False
        if context and hasattr(context, 'user_data'):
            is_from_signal = context.user_data.get('from_signal', False)
            # Add debug logging
            logger.info(f"show_sentiment_analysis: from_signal = {is_from_signal}")
            logger.info(f"Context user_data: {context.user_data}")
        
        # Get instrument from parameter or context
        if not instrument:
            # First check persistent signal context
            if user_id in self.signal_contexts and 'instrument' in self.signal_contexts[user_id]:
                instrument = self.signal_contexts[user_id]['instrument']
                logger.info(f"Retrieved instrument from persistent context: {instrument}")
            # Then check conversation context
            elif context and hasattr(context, 'user_data'):
                instrument = context.user_data.get('instrument')
        
        if not instrument:
            logger.error("No instrument provided for sentiment analysis")
            try:
                await query.edit_message_text(
                    text="Please select an instrument first.",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
            except Exception as e:
                logger.error(f"Error updating message: {str(e)}")
            return CHOOSE_MARKET
        
        # Store the instrument in our persistent context
        if user_id not in self.signal_contexts:
            self.signal_contexts[user_id] = {}
        self.signal_contexts[user_id]['instrument'] = instrument
        
        logger.info(f"Showing sentiment analysis for instrument: {instrument}")
        
        # Clean instrument name (without _SELL_4h etc)
        clean_instrument = instrument.split('_')[0] if '_' in instrument else instrument
        
        # Check if we already have a loading message from context
        loading_message = None
        if context and hasattr(context, 'user_data'):
            loading_message = context.user_data.get('loading_message')
        
        # If we don't have a loading message from context, create one
        if not loading_message:
            # Toon loading message met GIF
            loading_text = "Generating sentiment analysis..."
            loading_gif = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"
            
            try:
                # Probeer de loading GIF te tonen
                await query.edit_message_media(
                    media=InputMediaAnimation(
                        media=loading_gif,
                        caption=loading_text
                    )
                )
            except Exception as e:
                logger.warning(f"Could not show loading GIF: {str(e)}")
                # Fallback naar tekstupdate
                try:
                    await query.edit_message_text(text=loading_text)
                except Exception as inner_e:
                    try:
                        await query.edit_message_caption(caption=loading_text)
                    except Exception as inner_e2:
                        logger.error(f"Could not update loading message: {str(inner_e2)}")
        
        try:
            # Initialize sentiment service if needed
            if not hasattr(self, 'sentiment_service') or self.sentiment_service is None:
                self.sentiment_service = MarketSentimentService()
            
            # Get sentiment data using clean instrument name
            sentiment_data = await self.sentiment_service.get_sentiment(clean_instrument)
            
            if not sentiment_data:
                # Determine which back button to use based on flow
                back_callback = "back_to_signal_analysis" if is_from_signal else "back_to_analysis"
                await query.message.reply_text(
                    text=f"Failed to get sentiment data. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data=back_callback)
                    ]])
                )
                return CHOOSE_ANALYSIS
            
            # Extract data
            bullish = sentiment_data.get('bullish', 50)
            bearish = sentiment_data.get('bearish', 30)
            neutral = sentiment_data.get('neutral', 20)
            
            # Determine sentiment
            if bullish > bearish + neutral:
                overall = "Bullish"
                emoji = "📈"
            elif bearish > bullish + neutral:
                overall = "Bearish"
                emoji = "📉"
            else:
                overall = "Neutral"
                emoji = "⚖️"
            
            # Get analysis text
            analysis_text = ""
            if isinstance(sentiment_data.get('analysis'), str):
                analysis_text = sentiment_data['analysis']
            
            # Prepare the message format without relying on regex
            # This will help avoid HTML parsing errors
            title = f"<b>🎯 {clean_instrument} Market Analysis</b>"
            overall_sentiment = f"<b>Overall Sentiment:</b> {overall} {emoji}"
            
            # Check if the provided analysis already has a title
            if analysis_text and "<b>🎯" in analysis_text and "Market Analysis</b>" in analysis_text:
                # Extract the title from the analysis
                title_start = analysis_text.find("<b>🎯")
                title_end = analysis_text.find("</b>", title_start) + 4
                title = analysis_text[title_start:title_end]
                
                # Remove the title from the analysis
                analysis_text = analysis_text[:title_start] + analysis_text[title_end:]
                analysis_text = analysis_text.strip()
            
            # Clean up the analysis text
            analysis_text = analysis_text.replace("</b><b>", "</b> <b>")  # Fix malformed tags
            
            # Zorgen dat ALLE kopjes in de analyse direct in bold staan
            headers = [
                "Market Sentiment Breakdown:",
                "Market Direction:",
                "Latest News & Events:",
                "Risk Factors:",
                "Conclusion:",
                "Technical Outlook:",
                "Fundamental Analysis:",
                "Support & Resistance:",
                "Sentiment Breakdown:"
            ]
            
            # Eerst verwijderen we bestaande bold tags bij headers om dubbele tags te voorkomen
            for header in headers:
                if f"<b>{header}</b>" in analysis_text:
                    # Als header al bold is, niet opnieuw toepassen
                    continue
                
                # Vervang normale tekst door bold tekst, met regex om exacte match te garanderen
                pattern = re.compile(r'(\n|^)(' + re.escape(header) + r')')
                analysis_text = pattern.sub(r'\1<b>\2</b>', analysis_text)
            
            # Verwijder extra witruimte tussen secties
            analysis_text = re.sub(r'\n{3,}', '\n\n', analysis_text)  # Replace 3+ newlines with 2
            analysis_text = re.sub(r'^\n+', '', analysis_text)  # Remove leading newlines
            
            # Verbeter de layout van het bericht
            # Specifiek verwijder witruimte tussen Overall Sentiment en Market Sentiment Breakdown
            full_message = f"{title}\n\n{overall_sentiment}"
            
            # If there's analysis text, add it with compact formatting
            if analysis_text:
                found_header = False
                
                # Controleer specifiek op Market Sentiment Breakdown header
                if "<b>Market Sentiment Breakdown:</b>" in analysis_text:
                    parts = analysis_text.split("<b>Market Sentiment Breakdown:</b>", 1)
                    full_message += f"\n\n<b>Market Sentiment Breakdown:</b>{parts[1]}"
                    found_header = True
                elif "Market Sentiment Breakdown:" in analysis_text:
                    # Als de header er wel is maar niet bold, fix het
                    parts = analysis_text.split("Market Sentiment Breakdown:", 1)
                    full_message += f"\n\n<b>Market Sentiment Breakdown:</b>{parts[1]}"
                    found_header = True
                
                # Als de Market Sentiment header niet gevonden is, zoek andere headers
                if not found_header:
                    for header in headers:
                        header_bold = f"<b>{header}</b>"
                        if header_bold in analysis_text:
                            parts = analysis_text.split(header_bold, 1)
                            full_message += f"\n\n{header_bold}{parts[1]}"
                            found_header = True
                            break
                        elif header in analysis_text:
                            # Als de header er wel is maar niet bold, fix het
                            parts = analysis_text.split(header, 1)
                            full_message += f"\n\n<b>{header}</b>{parts[1]}"
                            found_header = True
                            break
                
                # Als geen headers gevonden, voeg de volledige analyse toe
                if not found_header:
                    full_message += f"\n\n{analysis_text}"
            else:
                # No analysis text, add a manual breakdown without extra spacing
                full_message += f"""
<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish}%
🔴 Bearish: {bearish}%
⚪️ Neutral: {neutral}%"""

            # Verwijder alle dubbele newlines om nog meer witruimte te voorkomen
            full_message = re.sub(r'\n{3,}', '\n\n', full_message)
            
            # Create reply markup with back button - use correct back button based on flow
            back_callback = "back_to_signal_analysis" if is_from_signal else "back_to_analysis"
            logger.info(f"Using back button callback: {back_callback} (from_signal: {is_from_signal})")
            reply_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Back", callback_data=back_callback)
            ]])
            
            # Validate HTML formatting
            try:
                # Test if HTML parsing works by creating a re-sanitized version
                from html.parser import HTMLParser
                
                class HTMLValidator(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.errors = []
                        self.open_tags = []
                    
                    def handle_starttag(self, tag, attrs):
                        self.open_tags.append(tag)
                    
                    def handle_endtag(self, tag):
                        if self.open_tags and self.open_tags[-1] == tag:
                            self.open_tags.pop()
                        else:
                            self.errors.append(f"Unexpected end tag: {tag}")
                
                validator = HTMLValidator()
                validator.feed(full_message)
                
                if validator.errors:
                    logger.warning(f"HTML validation errors: {validator.errors}")
                    # Fallback to plaintext if HTML is invalid
                    full_message = re.sub(r'<[^>]+>', '', full_message)
            except Exception as html_error:
                logger.warning(f"HTML validation failed: {str(html_error)}")
            
            # Send a completely new message to avoid issues with previous message
            try:
                # First try to edit the existing message when possible
                try:
                    await query.edit_message_text(
                        text=full_message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
                    logger.info("Successfully edited existing message with sentiment analysis")
                except Exception as edit_error:
                    logger.warning(f"Could not edit message, will create new one: {str(edit_error)}")
                    
                    # If editing fails, delete and create new message
                    await query.message.delete()
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=full_message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
                    logger.info("Created new message with sentiment analysis after deleting old one")
            except Exception as msg_error:
                logger.error(f"Error sending message: {str(msg_error)}")
                # Try without HTML parsing if that's the issue
                if "Can't parse entities" in str(msg_error):
                    try:
                        # Try to edit first
                        await query.edit_message_text(
                            text=re.sub(r'<[^>]+>', '', full_message),  # Strip HTML tags
                            reply_markup=reply_markup
                        )
                    except Exception:
                        # If editing fails, send new message
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=re.sub(r'<[^>]+>', '', full_message),  # Strip HTML tags
                            reply_markup=reply_markup
                        )
            
            return CHOOSE_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error in sentiment analysis: {str(e)}")
            # Determine which back button to use based on flow
            back_callback = "back_to_signal_analysis" if is_from_signal else "back_to_analysis"
            error_text = "Error generating sentiment analysis. Please try again."
            try:
                await query.edit_message_text(
                    text=error_text,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data=back_callback)
                    ]])
                )
            except Exception as text_error:
                logger.error(f"Could not update error message: {str(text_error)}")
            
            return CHOOSE_ANALYSIS

    async def show_calendar_analysis(self, update: Update, context=None, instrument=None, timeframe=None) -> int:
        """Show economic calendar for a specific currency/instrument"""
        query = update.callback_query
        
        try:
            # Check if we're in signal flow
            from_signal = False
            if context and hasattr(context, 'user_data'):
                from_signal = context.user_data.get('from_signal', False)
            
            # If no instrument is provided, try to extract it from callback data
            if not instrument and query:
                callback_data = query.data
                
                # Extract instrument from callback data
                if callback_data.startswith("instrument_"):
                    parts = callback_data.split("_")
                    instrument = parts[1]
            
            # If still no instrument, check user data
            if not instrument and context and hasattr(context, 'user_data'):
                instrument = context.user_data.get('instrument')
            
            # For currency pairs, extract the base currency (alleen voor logging doeleinden)
            if instrument and len(instrument) >= 6 and instrument[3] == '/':
                # Traditional format like EUR/USD
                base_currency = instrument[:3]
            elif instrument and len(instrument) >= 6:
                # Format like EURUSD
                base_currency = instrument[:3]
            else:
                base_currency = instrument
            
            # Check if we have a message with media
            has_photo = False
            if query and query.message:
                has_photo = bool(query.message.photo) or query.message.animation is not None
                
            # Show loading message with GIF
            loading_text = f"Loading economic calendar..."
            loading_gif = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"
            loading_message = None
            
            try:
                # Show loading animation if we're not already displaying an image
                if not has_photo:
                    # Try to show animated GIF for loading
                    await query.edit_message_text(
                        text=loading_text
                    )
                else:
                    # Try to show animated GIF for loading
                    await query.edit_message_media(
                        media=InputMediaAnimation(
                            media=loading_gif,
                            caption=loading_text
                        )
                    )
                logger.info(f"Successfully showed loading indicator for economic calendar")
            except Exception as gif_error:
                logger.warning(f"Could not show loading indicator: {str(gif_error)}")
                # Fallback to updating caption
                try:
                    await query.edit_message_caption(caption=loading_text)
                except Exception as caption_error:
                    logger.error(f"Failed to update caption: {str(caption_error)}")
            
            # Create the keyboard with appropriate back button based on flow
            keyboard = []
            if from_signal:
                keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")])
            else:
                keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_analysis")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Get the economic calendar data
            # We always get data for ALL major currencies, regardless of the instrument
            calendar_data = []
            message_text = ""
            
            # Initialize the calendar service and get data
            calendar_service = self._get_calendar_service()
            try:
                if hasattr(calendar_service, 'get_calendar'):
                    calendar_data = await calendar_service.get_calendar()
                
                # Format the calendar data
                if hasattr(self, '_format_calendar_events'):
                    message_text = await self._format_calendar_events(calendar_data)
                else:
                    # Fallback to calendar service formatting
                    if hasattr(calendar_service, '_format_calendar_response'):
                        message_text = await calendar_service._format_calendar_response(calendar_data, "ALL")
                    else:
                        # Simple formatting fallback
                        message_text = "<b>📅 Economic Calendar</b>\n\n"
                        for event in calendar_data[:10]:
                            country = event.get('country', 'Unknown')
                            title = event.get('title', 'Unknown Event')
                            time = event.get('time', 'Unknown Time')
                            message_text += f"{country}: {time} - {title}\n\n"
            except Exception as e:
                logger.error(f"Error getting calendar data: {str(e)}")
                message_text = "<b>⚠️ Error</b>\n\nCould not retrieve economic calendar data."
            
            # Multi-step approach to remove loading GIF and display calendar data
            try:
                # Step 1: Try to delete the message and send a new one
                chat_id = update.effective_chat.id
                message_id = query.message.message_id
                
                try:
                    # Try to delete the current message
                    await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                    # Send a new message with the calendar data
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
                    logger.info("Successfully deleted loading message and sent new calendar data")
                except Exception as delete_error:
                    logger.warning(f"Could not delete message: {str(delete_error)}")
                    
                    # Step 2: If deletion fails, try replacing with transparent GIF
                    try:
                        transparent_gif = "https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/Transparent.gif/1px-Transparent.gif"
                        if has_photo:
                            await query.edit_message_media(
                                media=InputMediaDocument(
                                    media=transparent_gif,
                                    caption=message_text,
                                    parse_mode=ParseMode.HTML
                                ),
                                reply_markup=reply_markup
                            )
                            logger.info("Replaced loading GIF with transparent GIF and updated calendar data")
                        else:
                            # If no media, just update the text
                            await query.edit_message_text(
                                text=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup
                            )
                            logger.info("Updated text with calendar data")
                    except Exception as media_error:
                        logger.warning(f"Could not update media: {str(media_error)}")
                        
                        # Step 3: As last resort, only update the caption
                        try:
                            await query.edit_message_caption(
                                caption=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup
                            )
                            logger.info("Updated caption with calendar data")
                        except Exception as caption_error:
                            logger.error(f"Failed to update caption: {str(caption_error)}")
                            # Send a new message as absolutely last resort
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup
                            )
            except Exception as e:
                logger.error(f"Error displaying calendar data: {str(e)}")
                # Error recovery - send new message
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="<b>⚠️ Error</b>\n\nFailed to display economic calendar data.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            
            return SHOW_RESULT
            
        except Exception as e:
            logger.error(f"Error in show_calendar_analysis: {str(e)}")
            # Error recovery
            try:
                await query.edit_message_text(
                    text="An error occurred loading the economic calendar. Please try again later.",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
            except Exception:
                pass
            
            return MENU

    async def show_economic_calendar(self, update: Update, context: CallbackContext, currency=None, loading_message=None):
        """Show the economic calendar for a specific currency"""
        try:
            # VERIFICATION MARKER: SIGMAPIPS_CALENDAR_FIX_APPLIED
            self.logger.info("VERIFICATION MARKER: SIGMAPIPS_CALENDAR_FIX_APPLIED")
            
            chat_id = update.effective_chat.id
            query = update.callback_query
            
            # Log that we're showing the calendar
            self.logger.info(f"Showing economic calendar for {currency if currency else 'all currencies'}")
            
            # Initialize the calendar service
            calendar_service = self._get_calendar_service()
            cache_size = len(getattr(calendar_service, 'cache', {}))
            self.logger.info(f"Calendar service initialized, cache size: {cache_size}")
            
            # Check if API key is available
            tavily_api_key = os.environ.get("TAVILY_API_KEY", "")
            if tavily_api_key:
                masked_key = f"{tavily_api_key[:4]}..." if len(tavily_api_key) > 7 else "***"
                self.logger.info(f"Tavily API key is available: {masked_key}")
            else:
                self.logger.warning("No Tavily API key found, will use mock data")
            
            # Get the calendar data based on currency
            self.logger.info(f"Requesting calendar data for {currency if currency else 'all currencies'}")
            
            calendar_data = []
            
            # Get calendar data
            if currency and currency in MAJOR_CURRENCIES:
                try:
                    # Check if calendar service has get_instrument_calendar method
                    if hasattr(calendar_service, 'get_instrument_calendar'):
                        # Get instrument-specific calendar
                        instrument_calendar = await calendar_service.get_instrument_calendar(currency)
                        
                        # Extract the raw data for formatting
                        try:
                            # Check if we can get the flattened data directly
                            if hasattr(calendar_service, 'get_calendar'):
                                calendar_data = await calendar_service.get_calendar()
                                # Filter for specified currency
                                calendar_data = [event for event in calendar_data if event.get('country') == currency]
                        except Exception as e:
                            # If no flattened data available, use the formatted text
                            self.logger.warning(f"Could not get raw calendar data, using text data: {str(e)}")
                            # Send the formatted text directly
                            message = instrument_calendar
                            calendar_data = []
                    else:
                        # Fallback to mock data if method doesn't exist
                        self.logger.warning("calendar_service.get_instrument_calendar method not available, using mock data")
                        calendar_data = []
                except Exception as e:
                    self.logger.warning(f"Error getting instrument calendar: {str(e)}")
                    calendar_data = []
            else:
                # Get all currencies data
                try:
                    if hasattr(calendar_service, 'get_calendar'):
                        calendar_data = await calendar_service.get_calendar()
                    else:
                        self.logger.warning("calendar_service.get_calendar method not available, using mock data")
                        calendar_data = []
                except Exception as e:
                    self.logger.warning(f"Error getting calendar data: {str(e)}")
                    calendar_data = []
            
            # Check if data is empty
            if not calendar_data or len(calendar_data) == 0:
                self.logger.warning("Calendar data is empty, using mock data...")
                # Generate mock data
                today_date = datetime.now().strftime("%B %d, %Y")
                
                # Use the mock data generator from the calendar service if available
                if hasattr(calendar_service, '_generate_mock_calendar_data'):
                    mock_data = calendar_service._generate_mock_calendar_data(MAJOR_CURRENCIES, today_date)
                else:
                    # Otherwise use our own implementation
                    mock_data = self._generate_mock_calendar_data(MAJOR_CURRENCIES, today_date)
                
                # Flatten the mock data
                flattened_mock = []
                for currency_code, events in mock_data.items():
                    for event in events:
                        flattened_mock.append({
                            "time": event.get("time", ""),
                            "country": currency_code,
                            "country_flag": CURRENCY_FLAG.get(currency_code, ""),
                            "title": event.get("event", ""),
                            "impact": event.get("impact", "Low")
                        })
                
                calendar_data = flattened_mock
                self.logger.info(f"Generated {len(flattened_mock)} mock calendar events")
            
            # Format the calendar data in chronological order
            if hasattr(self, '_format_calendar_events'):
                message = await self._format_calendar_events(calendar_data)
            else:
                # Fallback to calendar service formatting if the method doesn't exist on TelegramService
                if hasattr(calendar_service, '_format_calendar_response'):
                    message = await calendar_service._format_calendar_response(calendar_data, "ALL")
                else:
                    # Simple formatting fallback
                    message = "<b>📅 Economic Calendar</b>\n\n"
                    for event in calendar_data[:10]:  # Limit to first 10 events
                        country = event.get('country', 'Unknown')
                        title = event.get('title', 'Unknown Event')
                        time = event.get('time', 'Unknown Time')
                        message += f"{country}: {time} - {title}\n\n"
            
            # Create keyboard with back button if not provided from caller
            keyboard = None
            if context and hasattr(context, 'user_data') and context.user_data.get('from_signal', False):
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")]])
            else:
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_analyse")]])
            
            # Try to delete loading message first if it exists
            if loading_message:
                try:
                    await loading_message.delete()
                    self.logger.info("Successfully deleted loading message")
                except Exception as delete_error:
                    self.logger.warning(f"Could not delete loading message: {str(delete_error)}")
                    
                    # If deletion fails, try to edit it
                    try:
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=loading_message.message_id,
                            text=message,
                            parse_mode=ParseMode.HTML,
                            reply_markup=keyboard
                        )
                        self.logger.info("Edited loading message with calendar data")
                        return  # Skip sending a new message
                    except Exception as edit_error:
                        self.logger.warning(f"Could not edit loading message: {str(edit_error)}")
            
            # Send the message as a new message
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
            self.logger.info("Sent calendar data as new message")
        
        except Exception as e:
            self.logger.error(f"Error showing economic calendar: {str(e)}")
            self.logger.exception(e)
            
            # Send error message
            chat_id = update.effective_chat.id
            await context.bot.send_message(
                chat_id=chat_id,
                text="<b>⚠️ Error showing economic calendar</b>\n\nSorry, there was an error retrieving the economic calendar data. Please try again later.",
                parse_mode=ParseMode.HTML
            )
            
    def _generate_mock_calendar_data(self, currencies, date):
        """Generate mock calendar data if the real service fails"""
        self.logger.info(f"Generating mock calendar data for {len(currencies)} currencies")
        mock_data = {}
        
        # Impact levels
        impact_levels = ["High", "Medium", "Low"]
        
        # Possible event titles
        events = [
            "Interest Rate Decision",
            "Non-Farm Payrolls",
            "GDP Growth Rate",
            "Inflation Rate",
            "Unemployment Rate",
            "Retail Sales",
            "Manufacturing PMI",
            "Services PMI",
            "Trade Balance",
            "Consumer Confidence",
            "Building Permits",
            "Central Bank Speech",
            "Housing Starts",
            "Industrial Production"
        ]
        
        # Generate random events for each currency
        for currency in currencies:
            num_events = random.randint(1, 5)  # Random number of events per currency
            currency_events = []
            
            for _ in range(num_events):
                # Generate a random time (hour between 7-18, minute 00, 15, 30 or 45)
                hour = random.randint(7, 18)
                minute = random.choice([0, 15, 30, 45])
                time_str = f"{hour:02d}:{minute:02d} EST"
                
                # Random event and impact
                event = random.choice(events)
                impact = random.choice(impact_levels)
                
                currency_events.append({
                    "time": time_str,
                    "event": event,
                    "impact": impact
                })
            
            # Sort events by time
            mock_data[currency] = sorted(currency_events, key=lambda x: x["time"])
        
        return mock_data

    async def back_to_signal_analysis_callback(self, update: Update, context=None) -> int:
        """Handle back_to_signal_analysis to return to the signal analysis menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = str(update.effective_user.id)
            logger.info(f"Back to signal analysis for user {user_id}")
            
            # Get instrument from persistent context first, then fallback to conversation context
            instrument = None
            
            # Check persistent context
            if user_id in self.signal_contexts:
                instrument = self.signal_contexts[user_id].get('instrument')
                logger.info(f"Retrieved instrument from persistent context: {instrument}")
            
            # If not found in persistent context, check conversation context
            if not instrument and context and hasattr(context, 'user_data'):
                instrument = context.user_data.get('instrument')
                logger.info(f"Retrieved instrument from conversation context: {instrument}")
                
                # Store in persistent context for future use
                if instrument and user_id not in self.signal_contexts:
                    self.signal_contexts[user_id] = {}
                if instrument:
                    self.signal_contexts[user_id]['instrument'] = instrument
            
            # Format message text
            text = f"Select analysis type for {instrument}:" if instrument else "Select analysis type:"
            
            # Show analysis options
            await query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(SIGNAL_ANALYSIS_KEYBOARD),
                parse_mode=ParseMode.HTML
            )
            
            return CHOOSE_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error in back_to_signal_analysis_callback: {str(e)}")
            logger.exception(e)
            
            try:
                await query.edit_message_text(
                    text="An error occurred. Please try again or go back to the signal.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")
                    ]]),
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
                
            return CHOOSE_ANALYSIS

    async def handle_subscription_callback(self, update: Update, context=None) -> int:
        """Handle subscription button press"""
        query = update.callback_query
        await query.answer()
        
        # Check if we have Stripe service configured
        if not self.stripe_service:
            logger.error("Stripe service not configured")
            await query.edit_message_text(
                text="Sorry, subscription service is not available right now. Please try again later.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]])
            )
            return MENU
        
        # Get the subscription URL
        subscription_url = "https://buy.stripe.com/3cs3eF9Hu9256NW9AA"  # 14-day free trial URL
        features = get_subscription_features()
        
        # Format the subscription message
        message = f"""
🚀 <b>Welcome to Sigmapips AI!</b> 🚀

<b>Discover powerful trading signals for various markets:</b>
• <b>Forex</b> - Major and minor currency pairs
• <b>Crypto</b> - Bitcoin, Ethereum and other top cryptocurrencies
• <b>Indices</b> - Global market indices
• <b>Commodities</b> - Gold, silver and oil

<b>Features:</b>
✅ Real-time trading signals
✅ Multi-timeframe analysis (1m, 15m, 1h, 4h)
✅ Advanced chart analysis
✅ Sentiment indicators
✅ Economic calendar integration

<b>Start today with a FREE 14-day trial!</b>
"""
        
        # Create keyboard with subscription button
        keyboard = [
            [InlineKeyboardButton("🔥 Start 14-day FREE Trial", url=subscription_url)],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
        ]
        
        # Update message with subscription information
        try:
            # Get a welcome GIF URL
            gif_url = await get_welcome_gif()
            
            # Update the message with the GIF using the helper function
            success = await gif_utils.update_message_with_gif(
                query=query,
                gif_url=gif_url,
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            if not success:
                # If the helper function failed, try a direct approach as fallback
                try:
                    await query.edit_message_text(
                        text=message,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as text_error:
                    # If that fails due to caption, try editing caption
                    if "There is no text in the message to edit" in str(text_error):
                        await query.edit_message_caption(
                            caption=message,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
        except Exception as e:
            logger.error(f"Error updating message with subscription info: {str(e)}")
            # Try to send a new message as fallback
            await query.message.reply_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        
        return SUBSCRIBE
        
    async def get_subscribers_for_instrument(self, instrument: str, timeframe: str = None) -> List[int]:
        """
        Get a list of subscribed user IDs for a specific instrument and timeframe
        
        Args:
            instrument: The trading instrument (e.g., EURUSD)
            timeframe: Optional timeframe filter
            
        Returns:
            List of subscribed user IDs
        """
        try:
            logger.info(f"Getting subscribers for {instrument} timeframe: {timeframe}")
            
            # Get all subscribers from the database
            # Note: Using get_signal_subscriptions instead of find_all
            subscribers = await self.db.get_signal_subscriptions(instrument, timeframe)
            
            if not subscribers:
                logger.warning(f"No subscribers found for {instrument}")
                return []
                
            # Filter out subscribers that don't have an active subscription
            active_subscribers = []
            for subscriber in subscribers:
                user_id = subscriber['user_id']
                
                # Check if user is subscribed
                is_subscribed = await self.db.is_user_subscribed(user_id)
                
                # Check if payment has failed
                payment_failed = await self.db.has_payment_failed(user_id)
                
                if is_subscribed and not payment_failed:
                    active_subscribers.append(user_id)
                else:
                    logger.info(f"User {user_id} doesn't have an active subscription, skipping signal")
            
            return active_subscribers
            
        except Exception as e:
            logger.error(f"Error getting subscribers: {str(e)}")
            # FOR TESTING: Add admin users if available
            if hasattr(self, 'admin_users') and self.admin_users:
                logger.info(f"Returning admin users for testing: {self.admin_users}")
                return self.admin_users
            return []

    async def process_signal(self, signal_data: Dict[str, Any]) -> bool:
        """
        Process a trading signal from TradingView webhook or API
        
        Supports two formats:
        1. TradingView format: instrument, signal, price, sl, tp1, tp2, tp3, interval
        2. Custom format: instrument, direction, entry, stop_loss, take_profit, timeframe
        
        Returns:
            bool: True if signal was processed successfully, False otherwise
        """
        try:
            # Log the incoming signal data
            logger.info(f"Processing signal: {signal_data}")
            
            # Check which format we're dealing with and normalize it
            instrument = signal_data.get('instrument')
            
            # Handle TradingView format (price, sl, interval)
            if 'price' in signal_data and 'sl' in signal_data:
                price = signal_data.get('price')
                sl = signal_data.get('sl')
                tp1 = signal_data.get('tp1')
                tp2 = signal_data.get('tp2')
                tp3 = signal_data.get('tp3')
                interval = signal_data.get('interval', '1h')
                
                # Determine signal direction based on price and SL relationship
                direction = "BUY" if float(sl) < float(price) else "SELL"
                
                # Create normalized signal data
                normalized_data = {
                    'instrument': instrument,
                    'direction': direction,
                    'entry': price,
                    'stop_loss': sl,
                    'take_profit': tp1,  # Use first take profit level
                    'timeframe': interval
                }
                
                # Add optional fields if present
                normalized_data['tp1'] = tp1
                normalized_data['tp2'] = tp2
                normalized_data['tp3'] = tp3
            
            # Handle custom format (direction, entry, stop_loss, timeframe)
            elif 'direction' in signal_data and 'entry' in signal_data:
                direction = signal_data.get('direction')
                entry = signal_data.get('entry')
                stop_loss = signal_data.get('stop_loss')
                take_profit = signal_data.get('take_profit')
                timeframe = signal_data.get('timeframe', '1h')
                
                # Create normalized signal data
                normalized_data = {
                    'instrument': instrument,
                    'direction': direction,
                    'entry': entry,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'timeframe': timeframe
                }
            else:
                logger.error(f"Missing required signal data")
                return False
            
            # Basic validation
            if not normalized_data.get('instrument') or not normalized_data.get('direction') or not normalized_data.get('entry'):
                logger.error(f"Missing required fields in normalized signal data: {normalized_data}")
                return False
                
            # Create signal ID for tracking
            signal_id = f"{normalized_data['instrument']}_{normalized_data['direction']}_{normalized_data['timeframe']}_{int(time.time())}"
            
            # Format the signal message
            message = self._format_signal_message(normalized_data)
            
            # Determine market type for the instrument
            market_type = _detect_market(instrument)
            
            # Store the full signal data for reference
            normalized_data['id'] = signal_id
            normalized_data['timestamp'] = datetime.now().isoformat()
            normalized_data['message'] = message
            normalized_data['market'] = market_type
            
            # Save signal for history tracking
            if not os.path.exists(self.signals_dir):
                os.makedirs(self.signals_dir, exist_ok=True)
                
            # Save to signals directory
            with open(f"{self.signals_dir}/{signal_id}.json", 'w') as f:
                json.dump(normalized_data, f)
            
            # FOR TESTING: Always send to admin for testing
            if hasattr(self, 'admin_users') and self.admin_users:
                try:
                    logger.info(f"Sending signal to admin users for testing: {self.admin_users}")
                    for admin_id in self.admin_users:
                        # Prepare keyboard with analysis options
                        keyboard = [
                            [InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_from_signal_{instrument}_{signal_id}")]
                        ]
                        
                        # Send the signal
                        await self.bot.send_message(
                            chat_id=admin_id,
                            text=message,
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        logger.info(f"Test signal sent to admin {admin_id}")
                        
                        # Store signal reference for quick access
                        if not hasattr(self, 'user_signals'):
                            self.user_signals = {}
                            
                        admin_str_id = str(admin_id)
                        if admin_str_id not in self.user_signals:
                            self.user_signals[admin_str_id] = {}
                        
                        self.user_signals[admin_str_id][signal_id] = normalized_data
                except Exception as e:
                    logger.error(f"Error sending test signal to admin: {str(e)}")
            
            # Get subscribers for this instrument
            timeframe = normalized_data.get('timeframe', '1h')
            subscribers = await self.get_subscribers_for_instrument(instrument, timeframe)
            
            if not subscribers:
                logger.warning(f"No subscribers found for {instrument}")
                return True  # Successfully processed, just no subscribers
            
            # Send signal to all subscribers
            logger.info(f"Sending signal {signal_id} to {len(subscribers)} subscribers")
            
            sent_count = 0
            for user_id in subscribers:
                try:
                    # Prepare keyboard with analysis options
                    keyboard = [
                        [InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_from_signal_{instrument}_{signal_id}")]
                    ]
                    
                    # Send the signal
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    
                    sent_count += 1
                    
                    # Store signal reference for quick access
                    if not hasattr(self, 'user_signals'):
                        self.user_signals = {}
                        
                    user_str_id = str(user_id)
                    if user_str_id not in self.user_signals:
                        self.user_signals[user_str_id] = {}
                    
                    self.user_signals[user_str_id][signal_id] = normalized_data
                    
                except Exception as e:
                    logger.error(f"Error sending signal to user {user_id}: {str(e)}")
            
            logger.info(f"Successfully sent signal {signal_id} to {sent_count}/{len(subscribers)} subscribers")
            return True
            
        except Exception as e:
            logger.error(f"Error processing signal: {str(e)}")
            logger.exception(e)
            return False

    def _format_signal_message(self, signal_data: Dict[str, Any]) -> str:
        """Format signal data into a nice message for Telegram"""
        try:
            # Extract fields from signal data
            instrument = signal_data.get('instrument', 'Unknown')
            direction = signal_data.get('direction', 'Unknown')
            entry = signal_data.get('entry', 'Unknown')
            stop_loss = signal_data.get('stop_loss')
            take_profit = signal_data.get('take_profit')
            timeframe = signal_data.get('timeframe', '1h')
            
            # Get multiple take profit levels if available
            tp1 = signal_data.get('tp1', take_profit)
            tp2 = signal_data.get('tp2')
            tp3 = signal_data.get('tp3')
            
            # Add emoji based on direction
            direction_emoji = "🟢" if direction.upper() == "BUY" else "🔴"
            
            # Format the message with multiple take profits if available
            message = f"<b>🎯 New Trading Signal 🎯</b>\n\n"
            message += f"<b>Instrument:</b> {instrument}\n"
            message += f"<b>Action:</b> {direction.upper()} {direction_emoji}\n\n"
            message += f"<b>Entry Price:</b> {entry}\n"
            
            if stop_loss:
                message += f"<b>Stop Loss:</b> {stop_loss} 🔴\n"
            
            # Add take profit levels
            if tp1:
                message += f"<b>Take Profit 1:</b> {tp1} 🎯\n"
            if tp2:
                message += f"<b>Take Profit 2:</b> {tp2} 🎯\n"
            if tp3:
                message += f"<b>Take Profit 3:</b> {tp3} 🎯\n"
            
            message += f"\n<b>Timeframe:</b> {timeframe}\n"
            message += f"<b>Strategy:</b> TradingView Signal\n\n"
            
            message += "————————————————————\n\n"
            message += "<b>Risk Management:</b>\n"
            message += "• Position size: 1-2% max\n"
            message += "• Use proper stop loss\n"
            message += "• Follow your trading plan\n\n"
            
            message += "————————————————————\n\n"
            
            # Generate AI verdict
            ai_verdict = f"The {instrument} {direction.lower()} signal shows a promising setup with defined entry at {entry} and stop loss at {stop_loss}. Multiple take profit levels provide opportunities for partial profit taking."
            message += f"<b>🤖 SigmaPips AI Verdict:</b>\n{ai_verdict}"
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting signal message: {str(e)}")
            # Return simple message on error
            return f"New {signal_data.get('instrument', 'Unknown')} {signal_data.get('direction', 'Unknown')} Signal"

    async def _load_signals(self):
        """Load and cache previously saved signals"""
        try:
            # Initialize user_signals dictionary if it doesn't exist
            if not hasattr(self, 'user_signals'):
                self.user_signals = {}
                
            # If we have a database connection, load signals from there
            if self.db:
                # Get all active signals from the database
                signals = await self.db.get_active_signals()
                
                # Organize signals by user_id for quick access
                for signal in signals:
                    user_id = str(signal.get('user_id'))
                    signal_id = signal.get('id')
                    
                    # Initialize user dictionary if needed
                    if user_id not in self.user_signals:
                        self.user_signals[user_id] = {}
                    
                    # Store the signal
                    self.user_signals[user_id][signal_id] = signal
                
                logger.info(f"Loaded {len(signals)} signals for {len(self.user_signals)} users")
            else:
                logger.warning("No database connection available for loading signals")
                
        except Exception as e:
            logger.error(f"Error loading signals: {str(e)}")
            logger.exception(e)
            # Initialize empty dict on error
            self.user_signals = {}

    async def back_signals_callback(self, update: Update, context=None) -> int:
        """Handle back_signals button press"""
        query = update.callback_query
        await query.answer()
        
        self.logger.info("back_signals_callback called")
        
        # Create keyboard for signal menu
        keyboard = [
            [InlineKeyboardButton("📊 Add Signal", callback_data="signals_add")],
            [InlineKeyboardButton("⚙️ Manage Signals", callback_data="signals_manage")],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Update message
        await self.update_message(
            query=query,
            text="<b>📈 Signal Management</b>\n\nManage your trading signals",
            keyboard=reply_markup
        )
        
        return SIGNALS

    async def analysis_callback(self, update: Update, context=None) -> int:
        """Handle back button from market selection to analysis menu"""
        query = update.callback_query
        await query.answer()
        
        logger.info("analysis_callback called - returning to analysis menu")
        
        # Determine if we have a photo or animation
        has_photo = False
        if query and query.message:
            has_photo = bool(query.message.photo) or query.message.animation is not None
            
        # Get the analysis GIF URL
        gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
        
        # Multi-step approach to handle media messages
        try:
            # Step 1: Try to delete the message and send a new one
            chat_id = update.effective_chat.id
            message_id = query.message.message_id
            
            try:
                # Try to delete the current message
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                # Send a new message with the analysis menu
                await context.bot.send_animation(
                    chat_id=chat_id,
                    animation=gif_url,
                    caption="Select your analysis type:",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
                logger.info("Successfully deleted message and sent new analysis menu")
                return CHOOSE_ANALYSIS
            except Exception as delete_error:
                logger.warning(f"Could not delete message: {str(delete_error)}")
                
                # Step 2: If deletion fails, try replacing with a GIF or transparent GIF
                try:
                    if has_photo:
                        # Replace with the analysis GIF
                        await query.edit_message_media(
                            media=InputMediaAnimation(
                                media=gif_url,
                                caption="Select your analysis type:"
                            ),
                            reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                        )
                    else:
                        # Just update the text
                        await query.edit_message_text(
                            text="Select your analysis type:",
                            reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                            parse_mode=ParseMode.HTML
                        )
                    logger.info("Updated message with analysis menu")
                    return CHOOSE_ANALYSIS
                except Exception as media_error:
                    logger.warning(f"Could not update media: {str(media_error)}")
                    
                    # Step 3: As last resort, only update the caption
                    try:
                        await query.edit_message_caption(
                            caption="Select your analysis type:",
                            reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                            parse_mode=ParseMode.HTML
                        )
                        logger.info("Updated caption with analysis menu")
                        return CHOOSE_ANALYSIS
                    except Exception as caption_error:
                        logger.error(f"Failed to update caption in analysis_callback: {str(caption_error)}")
                        # Send a new message as absolutely last resort
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text="Select your analysis type:",
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                        )
        except Exception as e:
            logger.error(f"Error in analysis_callback: {str(e)}")
            # Send a new message as fallback
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Select your analysis type:",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            )
            
        return CHOOSE_ANALYSIS

    async def back_menu_callback(self, update: Update, context=None) -> int:
        """Handle back_menu button press to return to main menu.
        
        This function properly separates the /menu flow from the signal flow
        by clearing context data to prevent mixing of flows.
        """
        query = update.callback_query
        await query.answer()
        
        try:
            # Reset all context data to ensure clean separation between flows
            if context and hasattr(context, 'user_data'):
                # Log the current context for debugging
                logger.info(f"Clearing user context data: {context.user_data}")
                
                # List of keys to remove to ensure separation of flows
                keys_to_remove = [
                    'instrument', 'market', 'analysis_type', 'timeframe',
                    'signal_id', 'from_signal', 'is_signals_context',
                    'signal_instrument', 'signal_direction', 'signal_timeframe',
                    'signal_instrument_backup', 'signal_direction_backup', 'signal_timeframe_backup',
                    'signal_id_backup', 'loading_message'
                ]
                
                # Remove all flow-specific keys
                for key in keys_to_remove:
                    if key in context.user_data:
                        del context.user_data[key]
                
                # Explicitly set the signals context flag to False
                context.user_data['is_signals_context'] = False
                context.user_data['from_signal'] = False
                
                logger.info(f"Set menu flow context: {context.user_data}")
            
            # GIF URL for the welcome animation
            gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
            
            try:
                # First approach: delete the current message and send a new one
                await query.message.delete()
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=gif_url,
                    caption=WELCOME_MESSAGE,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
                return MENU
            except Exception as delete_e:
                logger.warning(f"Could not delete message: {str(delete_e)}")
                
                # Try to replace with a GIF
                try:
                    # If message has photo or animation, replace media
                    if query.message.photo or query.message.animation:
                        await query.edit_message_media(
                            media=InputMediaAnimation(
                                media=gif_url,
                                caption=WELCOME_MESSAGE
                            ),
                            reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                        )
                    else:
                        # Otherwise just update text
                        await query.edit_message_text(
                            text=WELCOME_MESSAGE,
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                        )
                except Exception as e:
                    logger.warning(f"Could not update message media/text: {str(e)}")
                    
                    # Last resort: try to update just the caption
                    try:
                        await query.edit_message_caption(
                            caption=WELCOME_MESSAGE,
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                        )
                    except Exception as caption_e:
                        logger.error(f"Failed to update caption in back_menu_callback: {str(caption_e)}")
                        
                        # Absolute last resort: send a new message
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=WELCOME_MESSAGE,
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                        )
            
            return MENU
        except Exception as e:
            logger.error(f"Error in back_menu_callback: {str(e)}")
            # Try to recover by sending a basic menu as fallback
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=WELCOME_MESSAGE,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
            )
            return MENU

    async def menu_signals_callback(self, update: Update, context=None) -> int:
        """Handle menu_signals button press to show signals management menu.
        
        This function properly sets up the signals flow context to ensure it doesn't
        mix with the regular menu flow.
        """
        query = update.callback_query
        await query.answer()
        
        logger.info("menu_signals_callback called")
        
        try:
            # Set the signals context flag to True and reset other context
            if context and hasattr(context, 'user_data'):
                # First clear any previous flow-specific data to prevent mixing
                context.user_data.clear()
                
                # Set flags specifically for signals flow
                context.user_data['is_signals_context'] = True
                context.user_data['from_signal'] = False
                
                logger.info(f"Set signal flow context: {context.user_data}")
            
            # Get the signals GIF URL for better UX
            signals_gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
            
            # Create keyboard for signals menu
            keyboard = [
                [InlineKeyboardButton("📊 Add Signal", callback_data="signals_add")],
                [InlineKeyboardButton("⚙️ Manage Signals", callback_data="signals_manage")],
                [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Try to update with GIF for better visual feedback
            try:
                # First try to delete and send new message with GIF
                await query.message.delete()
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=signals_gif_url,
                    caption="<b>📈 Signal Management</b>\n\nManage your trading signals",
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
                return SIGNALS
            except Exception as delete_error:
                logger.warning(f"Could not delete message: {str(delete_error)}")
                
                # If deletion fails, try replacing with a GIF
                try:
                    # If message has photo or animation, replace media
                    if hasattr(query.message, 'photo') and query.message.photo or hasattr(query.message, 'animation') and query.message.animation:
                        await query.edit_message_media(
                            media=InputMediaAnimation(
                                media=signals_gif_url,
                                caption="<b>📈 Signal Management</b>\n\nManage your trading signals"
                            ),
                            reply_markup=reply_markup
                        )
                    else:
                        # Otherwise just update text
                        await query.edit_message_text(
                            text="<b>📈 Signal Management</b>\n\nManage your trading signals",
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                    return SIGNALS
                except Exception as e:
                    logger.warning(f"Could not update message media/text: {str(e)}")
                    
                    # Last resort: try to update just the caption
                    try:
                        await query.edit_message_caption(
                            caption="<b>📈 Signal Management</b>\n\nManage your trading signals",
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                    except Exception as caption_e:
                        logger.error(f"Failed to update caption in menu_signals_callback: {str(caption_e)}")
                        
                        # Absolute last resort: send a new message
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text="<b>📈 Signal Management</b>\n\nManage your trading signals",
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
            
            return SIGNALS
        except Exception as e:
            logger.error(f"Error in menu_signals_callback: {str(e)}")
            # Fallback approach on error
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="<b>📈 Signal Management</b>\n\nManage your trading signals",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
            )
            return SIGNALS
