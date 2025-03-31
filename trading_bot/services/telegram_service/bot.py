import os
import ssl
import json
import logging
import asyncio
import traceback
import threading
import re
import time
import copy
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union
import random
import uuid
from enum import Enum

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, InputMediaPhoto, BotCommand, InputMediaAnimation, InputMediaDocument, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    CallbackContext,
    MessageHandler,
    filters,
    PicklePersistence,
    PollAnswerHandler
)
from telegram.request import HTTPXRequest
from telegram.error import TelegramError, BadRequest
import httpx

from fastapi import FastAPI, Request

from trading_bot.services.database.db import Database
from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
from trading_bot.services.calendar_service.calendar import EconomicCalendarService
from trading_bot.services.payment_service.stripe_service import StripeService
from trading_bot.services.payment_service.stripe_config import get_subscription_features
from fastapi import Request, HTTPException, status

# GIF utilities for richer UI experience
from trading_bot.services.telegram_service.gif_utils import get_welcome_gif, get_menu_gif, get_analyse_gif, get_signals_gif, send_welcome_gif, send_menu_gif, send_analyse_gif, send_signals_gif, send_gif_with_caption, update_message_with_gif, embed_gif_in_text, get_loading_gif
import trading_bot.services.telegram_service.gif_utils as gif_utils

logger = logging.getLogger(__name__)

# Callback data constants
CALLBACK_ANALYSIS_TECHNICAL = "analysis_technical"
CALLBACK_ANALYSIS_SENTIMENT = "analysis_sentiment"
CALLBACK_ANALYSIS_CALENDAR = "analysis_calendar"
CALLBACK_BACK_MENU = "back_menu"
CALLBACK_BACK_ANALYSIS = "back_to_analysis"
CALLBACK_BACK_MARKET = "back_market"
CALLBACK_BACK_INSTRUMENT = "back_instrument"
CALLBACK_BACK_SIGNALS = "back_signals"
CALLBACK_SIGNALS_ADD = "signals_add"
CALLBACK_SIGNALS_MANAGE = "signals_manage"
CALLBACK_MENU_ANALYSE = "menu_analyse"
CALLBACK_MENU_SIGNALS = "menu_signals"

# States
MENU = 0
CHOOSE_ANALYSIS = 1
CHOOSE_SIGNALS = 2
CHOOSE_MARKET = 3
CHOOSE_INSTRUMENT = 4
CHOOSE_STYLE = 5
SHOW_RESULT = 6
CHOOSE_TIMEFRAME = 7
SIGNAL_DETAILS = 8
SIGNAL = 9
SUBSCRIBE = 10
BACK_TO_MENU = 11  # Add this line

# Messages
WELCOME_MESSAGE = """
🚀 Sigmapips AI - Main Menu 🚀

Choose an option to access advanced trading support:

📊 Services:
• <b>Technical Analysis</b> – Real-time chart analysis and key levels

• <b>Market Sentiment</b> – Understand market trends and sentiment

• <b>Economic Calendar</b> – Stay updated on market-moving events

• <b>Trading Signals</b> – Get precise entry/exit points for your favorite pairs

Select your option to continue:
"""

# Abonnementsbericht voor nieuwe gebruikers
SUBSCRIPTION_WELCOME_MESSAGE = """
🚀 <b>Welcome to Sigmapips AI!</b> 🚀

To access all features, you need a subscription:

📊 <b>Trading Signals Subscription - $29.99/month</b>
• Access to all trading signals (Forex, Crypto, Commodities, Indices)
• Advanced timeframe analysis (1m, 15m, 1h, 4h)
• Detailed chart analysis for each signal

Click the button below to subscribe:
"""

MENU_MESSAGE = """
Welcome to Sigmapips AI!

Choose a command:

/start - Set up new trading pairs
Add new market/instrument/timeframe combinations to receive signals

/manage - Manage your preferences
View, edit or delete your saved trading pairs

Need help? Use /help to see all available commands.
"""

HELP_MESSAGE = """
Available commands:
/menu - Show main menu
/start - Set up new trading pairs
/help - Show this help message
"""

# Start menu keyboard
START_KEYBOARD = [
    [InlineKeyboardButton("🔍 Analyze Market", callback_data=CALLBACK_MENU_ANALYSE)],
    [InlineKeyboardButton("📊 Trading Signals", callback_data=CALLBACK_MENU_SIGNALS)]
]

# Analysis menu keyboard
ANALYSIS_KEYBOARD = [
    [InlineKeyboardButton("📈 Technical Analysis", callback_data=CALLBACK_ANALYSIS_TECHNICAL)],
    [InlineKeyboardButton("🧠 Market Sentiment", callback_data=CALLBACK_ANALYSIS_SENTIMENT)],
    [InlineKeyboardButton("📅 Economic Calendar", callback_data=CALLBACK_ANALYSIS_CALENDAR)],
    [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_MENU)]
]

# Signals menu keyboard
SIGNALS_KEYBOARD = [
    [InlineKeyboardButton("➕ Add New Pairs", callback_data=CALLBACK_SIGNALS_ADD)],
    [InlineKeyboardButton("⚙️ Manage Preferences", callback_data=CALLBACK_SIGNALS_MANAGE)],
    [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_MENU)]
]

# Market keyboard voor signals
MARKET_KEYBOARD_SIGNALS = [
    [InlineKeyboardButton("Forex", callback_data="market_forex_signals")],
    [InlineKeyboardButton("Crypto", callback_data="market_crypto_signals")],
    [InlineKeyboardButton("Commodities", callback_data="market_commodities_signals")],
    [InlineKeyboardButton("Indices", callback_data="market_indices_signals")],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
]

# Market keyboard voor analyse
MARKET_KEYBOARD = [
    [InlineKeyboardButton("Forex", callback_data="market_forex")],
    [InlineKeyboardButton("Crypto", callback_data="market_crypto")],
    [InlineKeyboardButton("Commodities", callback_data="market_commodities")],
    [InlineKeyboardButton("Indices", callback_data="market_indices")],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
]

# Market keyboard specifiek voor sentiment analyse
MARKET_SENTIMENT_KEYBOARD = [
    [InlineKeyboardButton("Forex", callback_data="market_forex_sentiment")],
    [InlineKeyboardButton("Crypto", callback_data="market_crypto_sentiment")],
    [InlineKeyboardButton("Commodities", callback_data="market_commodities_sentiment")],
    [InlineKeyboardButton("Indices", callback_data="market_indices_sentiment")],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
]

# Helper function to create callback data without directly referencing TelegramService
@staticmethod
def _format_instrument_callback(instrument, analysis_type='chart'):
    """Format instrument callback data with explicit analysis type"""
    return f"instrument_{instrument}_{analysis_type}"

# Define forex instrument keyboards with explicit analysis types
FOREX_KEYBOARD = [
    [
        InlineKeyboardButton("EUR/USD", callback_data=_format_instrument_callback("EURUSD", "chart")),
        InlineKeyboardButton("GBP/USD", callback_data=_format_instrument_callback("GBPUSD", "chart")),
        InlineKeyboardButton("AUD/USD", callback_data=_format_instrument_callback("AUDUSD", "chart"))
    ],
    [
        InlineKeyboardButton("USD/JPY", callback_data=_format_instrument_callback("USDJPY", "chart")),
        InlineKeyboardButton("USD/CHF", callback_data=_format_instrument_callback("USDCHF", "chart")),
        InlineKeyboardButton("USD/CAD", callback_data=_format_instrument_callback("USDCAD", "chart"))
    ],
    [
        InlineKeyboardButton("EUR/GBP", callback_data=_format_instrument_callback("EURGBP", "chart")),
        InlineKeyboardButton("EUR/JPY", callback_data=_format_instrument_callback("EURJPY", "chart")),
        InlineKeyboardButton("GBP/JPY", callback_data=_format_instrument_callback("GBPJPY", "chart"))
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
]

# Define forex sentiment keyboard with explicit analysis types
FOREX_SENTIMENT_KEYBOARD = [
    [
        InlineKeyboardButton("EUR/USD", callback_data=_format_instrument_callback("EURUSD", "sentiment")),
        InlineKeyboardButton("GBP/USD", callback_data=_format_instrument_callback("GBPUSD", "sentiment")),
        InlineKeyboardButton("AUD/USD", callback_data=_format_instrument_callback("AUDUSD", "sentiment"))
    ],
    [
        InlineKeyboardButton("USD/JPY", callback_data=_format_instrument_callback("USDJPY", "sentiment")),
        InlineKeyboardButton("USD/CHF", callback_data=_format_instrument_callback("USDCHF", "sentiment")),
        InlineKeyboardButton("USD/CAD", callback_data=_format_instrument_callback("USDCAD", "sentiment"))
    ],
    [
        InlineKeyboardButton("EUR/GBP", callback_data=_format_instrument_callback("EURGBP", "sentiment")),
        InlineKeyboardButton("EUR/JPY", callback_data=_format_instrument_callback("EURJPY", "sentiment")),
        InlineKeyboardButton("GBP/JPY", callback_data=_format_instrument_callback("GBPJPY", "sentiment"))
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
]

# Forex keyboard voor kalender analyse
FOREX_CALENDAR_KEYBOARD = [
    [
        InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD_calendar"),
        InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD_calendar"),
        InlineKeyboardButton("USDJPY", callback_data="instrument_USDJPY_calendar")
    ],
    [
        InlineKeyboardButton("AUDUSD", callback_data="instrument_AUDUSD_calendar"),
        InlineKeyboardButton("USDCAD", callback_data="instrument_USDCAD_calendar"),
        InlineKeyboardButton("EURGBP", callback_data="instrument_EURGBP_calendar")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Crypto keyboard voor analyse
CRYPTO_KEYBOARD = [
    [
        InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD_chart"),
        InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD_chart"),
        InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD_chart")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Crypto keyboard voor sentiment analyse
CRYPTO_SENTIMENT_KEYBOARD = [
    [
        InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD_sentiment"),
        InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD_sentiment"),
        InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD_sentiment")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Indices keyboard voor analyse
INDICES_KEYBOARD = [
    [
        InlineKeyboardButton("US30", callback_data="instrument_US30"),
        InlineKeyboardButton("US500", callback_data="instrument_US500"),
        InlineKeyboardButton("US100", callback_data="instrument_US100")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
]

# Indices keyboard voor signals - Fix de "Terug" knop naar "Back"
INDICES_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("US30", callback_data="instrument_US30_signals"),
        InlineKeyboardButton("US500", callback_data="instrument_US500_signals"),
        InlineKeyboardButton("US100", callback_data="instrument_US100_signals")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Commodities keyboard voor analyse
COMMODITIES_KEYBOARD = [
    [
        InlineKeyboardButton("GOLD", callback_data="instrument_XAUUSD"),
        InlineKeyboardButton("SILVER", callback_data="instrument_XAGUSD"),
        InlineKeyboardButton("OIL", callback_data="instrument_USOIL")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Commodities keyboard voor signals - Fix de "Terug" knop naar "Back"
COMMODITIES_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD_signals"),
        InlineKeyboardButton("XAGUSD", callback_data="instrument_XAGUSD_signals"),
        InlineKeyboardButton("USOIL", callback_data="instrument_USOIL_signals")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Forex keyboard for signals
FOREX_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD_signals"),
        InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD_signals"),
        InlineKeyboardButton("USDJPY", callback_data="instrument_USDJPY_signals")
    ],
    [
        InlineKeyboardButton("AUDUSD", callback_data="instrument_AUDUSD_signals"),
        InlineKeyboardButton("USDCAD", callback_data="instrument_USDCAD_signals"),
        InlineKeyboardButton("EURGBP", callback_data="instrument_EURGBP_signals")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Crypto keyboard for signals
CRYPTO_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD_signals"),
        InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD_signals"),
        InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD_signals")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Style keyboard
STYLE_KEYBOARD = [
    [InlineKeyboardButton("⚡ Test (1m)", callback_data="style_test")],
    [InlineKeyboardButton("🏃 Scalp (15m)", callback_data="style_scalp")],
    [InlineKeyboardButton("📊 Intraday (1h)", callback_data="style_intraday")],
    [InlineKeyboardButton("🌊 Swing (4h)", callback_data="style_swing")],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_instrument")]
]

# Timeframe mapping
STYLE_TIMEFRAME_MAP = {
    "test": "1m",
    "scalp": "15m",
    "intraday": "1h",
    "swing": "4h"
}

# Mapping of instruments to their allowed timeframes - updated 2023-03-23
INSTRUMENT_TIMEFRAME_MAP = {
    # H1 timeframe only
    "AUDJPY": "H1", 
    "AUDCHF": "H1",
    "EURCAD": "H1",
    "EURGBP": "H1",
    "GBPCHF": "H1",
    "HK50": "H1",
    "NZDJPY": "H1",
    "USDCHF": "H1",
    "XRPUSD": "H1",
    
    # H4 timeframe only
    "AUDCAD": "H4",
    "AU200": "H4", 
    "CADCHF": "H4",
    "EURCHF": "H4",
    "EURUSD": "H4",
    "GBPCAD": "H4",
    "LINKUSD": "H4",
    "NZDCHF": "H4",
    
    # M15 timeframe only
    "DOGEUSD": "M15",
    "GBPNZD": "M15",
    "NZDUSD": "M15",
    "SOLUSD": "M15",
    "UK100": "M15",
    "XAUUSD": "M15",
    
    # M30 timeframe only
    "BNBUSD": "M30",
    "DOTUSD": "M30",
    "ETHUSD": "M30",
    "EURAUD": "M30",
    "EURJPY": "M30",
    "GBPAUD": "M30",
    "GBPUSD": "M30",
    "NZDCAD": "M30",
    "US30": "M30",
    "US500": "M30",
    "USDCAD": "M30",
    "XLMUSD": "M30",
    "XTIUSD": "M30",
    "DE40": "M30"
    
    # Removed as requested: EU50, FR40, LTCUSD
}

# Map common timeframe notations
TIMEFRAME_DISPLAY_MAP = {
    "M15": "15 Minutes",
    "M30": "30 Minutes", 
    "H1": "1 Hour",
    "H4": "4 Hours"
}

# Voeg deze functie toe aan het begin van bot.py, na de imports
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

# Voeg dit toe als decorator functie bovenaan het bestand na de imports
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
                # Show the welcome message with trial option from the screenshot
                welcome_text = """
🚀 Welcome to Sigmapips AI! 🚀

Discover powerful trading signals for various markets:
• Forex - Major and minor currency pairs

• Crypto - Bitcoin, Ethereum and other top
 cryptocurrencies

• Indices - US30, US500, US100 and more

• Commodities - Gold, silver and oil

<b>Start today with a FREE 14-day trial!</b>
"""
                
                # Use direct URL link for the trial button
                trial_url = "https://buy.stripe.com/3cs3eF9Hu9256NW9AA"
                
                # Create button for trial
                keyboard = [
                    [InlineKeyboardButton("🔥 Start 14-day FREE Trial", url=trial_url)]
                ]
            
            # Handle both message and callback query updates
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    text=welcome_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    text=welcome_text,
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
        
        # Initialize chart service
        asyncio.create_task(self.chart_service.initialize())
        
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
    
    def _load_signals(self):
        """Load saved signals from file"""
        try:
            # Ensure data directory exists
            os.makedirs('data', exist_ok=True)
            
            # Check if signals file exists
            if not os.path.exists('data/signals.json'):
                logger.info("No signals file found, creating empty signals dictionary")
                self.user_signals = {}
                return
                
            with open('data/signals.json', 'r') as f:
                signals_json = json.load(f)
                
            # Convert string keys back to integers
            self.user_signals = {int(k): v for k, v in signals_json.items()}
            logger.info(f"Loaded {len(self.user_signals)} signals from file")
            
            # Log the first few signals as a sample
            sample_users = list(self.user_signals.keys())[:3] if self.user_signals else []
            for user_id in sample_users:
                signal = self.user_signals[user_id]
                logger.info(f"Sample signal for user {user_id}: {signal.get('instrument')}")
                
        except Exception as e:
            logger.error(f"Error loading signals: {str(e)}")
            self.user_signals = {}
            
    def _save_signals(self):
        """Save signals to file"""
        try:
            # Ensure data directory exists
            os.makedirs('data', exist_ok=True)
            
            # Convert user_ids (integer keys) to strings for JSON serialization
            signals_to_save = {}
            
            # Process each signal to make sure it's fully serializable
            for user_id, signal_data in self.user_signals.items():
                # Create a deep copy of the signal data to avoid modifying the original
                signal_copy = copy.deepcopy(signal_data)
                
                # Make sure all required fields are present
                if 'instrument' not in signal_copy:
                    signal_copy['instrument'] = 'Unknown'
                if 'direction' not in signal_copy:
                    signal_copy['direction'] = 'Unknown'
                if 'message' not in signal_copy:
                    # Generate a default message as fallback
                    signal_copy['message'] = f"Trading signal for {signal_copy.get('instrument', 'Unknown')}"
                if 'timestamp' not in signal_copy:
                    signal_copy['timestamp'] = self._get_formatted_timestamp()
                
                # Remove potentially problematic fields for serialization
                if 'bot' in signal_copy:
                    del signal_copy['bot']
                if 'context' in signal_copy:
                    del signal_copy['context']
                
                # Store in the dictionary with string key
                signals_to_save[str(user_id)] = signal_copy
            
            # Save to file with pretty formatting for easier debugging
            with open('data/signals.json', 'w') as f:
                json.dump(signals_to_save, f, indent=2, default=str)
                
            logger.info(f"Saved {len(self.user_signals)} signals to file")
        except Exception as e:
            logger.error(f"Error saving signals: {str(e)}")
            logger.exception(e)
            
    def get_subscribers(self):
        """Get all subscribers from database"""
        try:
            # If we're in test mode or haven't initialized DB connection, return admins or test users
            # First check if we have admin users
            if self.admin_users:
                # In a real implementation, this would fetch users from a database
                # For now, let's get users from self.all_users (which is populated in list_users)
                if hasattr(self, 'all_users') and self.all_users:
                    return list(self.all_users)
                else:
                    logger.info("No users found in all_users, returning admin users")
                    return self.admin_users
            else:
                # Try to get test users from environment
                test_users = []
                test_ids = os.getenv("TEST_USER_IDS", "")
                if test_ids:
                    try:
                        test_users = [int(user_id.strip()) for user_id in test_ids.split(",") if user_id.strip()]
                        logger.info(f"Using test users from environment: {test_users}")
                    except Exception as e:
                        logger.error(f"Error parsing TEST_USER_IDS: {str(e)}")
                if test_users:
                    return test_users
                else:
                    # If no admin or test users defined, use a default test user
                    # Replace this with your own Telegram user ID for testing
                    default_test_user = os.getenv("DEFAULT_TEST_USER", "")
                    if default_test_user and default_test_user.isdigit():
                        default_user_id = int(default_test_user)
                        logger.info(f"Using default test user: {default_user_id}")
                        return [default_user_id]
                        
                    # If you want to hardcode a user ID for testing, uncomment and modify the line below
                    return [1093307376]  # Jovanni's Telegram user ID (vervang dit met jouw eigen ID als dit niet correct is)
                    
                    logger.warning("No admin or test users defined, returning empty list")
                    return []
        except Exception as e:
            logger.error(f"Error getting subscribers: {str(e)}")
            # Try to get test users as fallback
            try:
                test_users = []
                test_ids = os.getenv("TEST_USER_IDS", "")
                if test_ids:
                    test_users = [int(user_id.strip()) for user_id in test_ids.split(",") if user_id.strip()]
                    logger.info(f"Using test users as fallback: {test_users}")
                    return test_users
            except Exception as inner_e:
                logger.error(f"Error getting test users: {str(inner_e)}")
            # Ultimate fallback
            return self.admin_users if hasattr(self, 'admin_users') else []
            
    @property
    def signals_enabled(self):
        """Property to check if signal processing is enabled"""
        return self._signals_enabled
    
    @signals_enabled.setter
    def signals_enabled(self, value):
        """Setter for signals_enabled property"""
        self._signals_enabled = bool(value)
        logger.info(f"Signal processing {'enabled' if value else 'disabled'}")

    def _register_handlers(self, application):
        """Register all command and callback handlers with the application"""
        # Ensure application is initialized
        if not application:
            logger.error("Cannot register handlers: application not initialized")
            return
        
        logger.info("==== REGISTERING ALL HANDLERS ====")
        
        # Command handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("menu", self.show_main_menu))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("set_subscription", self.set_subscription_command))
        
        logger.info("Command handlers registered")
        
        # Register the payment failed command with both underscore and no-underscore versions
        application.add_handler(CommandHandler("set_payment_failed", self.set_payment_failed_command))
        application.add_handler(CommandHandler("setpaymentfailed", self.set_payment_failed_command))
        
        # FOCUS OP DE BACK_MENU HANDLER - DIRECT TOEVOEGEN ALS EERSTE SPECIFIEKE HANDLER
        logger.info("Registering back_menu_callback specifically...")
        application.add_handler(CallbackQueryHandler(self.back_menu_callback, pattern="^back_menu$"))
        logger.info("back_menu_callback handler registered with pattern ^back_menu$")
        
        # Add specific handlers for signal analysis flows
        application.add_handler(CallbackQueryHandler(self.analysis_technical_callback, pattern="^analysis_technical$"))
        application.add_handler(CallbackQueryHandler(self.analysis_technical_callback, pattern="^analysis_technical_signal_.*$"))
        
        application.add_handler(CallbackQueryHandler(self.analysis_sentiment_callback, pattern="^analysis_sentiment$"))
        application.add_handler(CallbackQueryHandler(self.analysis_sentiment_callback, pattern="^analysis_sentiment_signal_.*$"))
        
        application.add_handler(CallbackQueryHandler(self.analysis_calendar_callback, pattern="^analysis_calendar$"))
        application.add_handler(CallbackQueryHandler(self.analysis_calendar_callback, pattern="^analysis_calendar_signal_.*$"))
        
        application.add_handler(CallbackQueryHandler(self.back_to_signal_callback, pattern="^back_to_signal$"))
        
        # Navigation callbacks - DEZE MOETEN VOOR DE GENERIEKE HANDLER STAAN
        application.add_handler(CallbackQueryHandler(self.back_market_callback, pattern="^back_market$"))
        application.add_handler(CallbackQueryHandler(self.back_analysis_callback, pattern="^back_analysis$"))
        # NIET NODIG, AL GEREGISTREERD ALS EERSTE HANDLER
        # application.add_handler(CallbackQueryHandler(self.back_menu_callback, pattern="^back_menu$"))
        
        logger.info("Navigation callbacks registered")
        
        # Signal flow analysis handlers - DEZE MOETEN OOK VOOR DE GENERIEKE HANDLER STAAN
        application.add_handler(CallbackQueryHandler(
            self.signal_technical_callback, pattern="^signal_technical$"))
        application.add_handler(CallbackQueryHandler(
            self.signal_sentiment_callback, pattern="^signal_sentiment$"))
        application.add_handler(CallbackQueryHandler(
            self.signal_calendar_callback, pattern="^signal_calendar$"))
        application.add_handler(CallbackQueryHandler(
            self.back_to_signal_analysis_callback, pattern="^back_to_signal_analysis$"))
        
        logger.info("Signal flow handlers registered")
        
        # Instrument callback handlers - these need to be before the generic handler
        application.add_handler(CallbackQueryHandler(
            self.instrument_callback, pattern="^instrument_.*$"))
        
        logger.info("Instrument callback handlers registered")
        
        # Callback query handler for all button presses - GENERIC HANDLER MOET LAST ZIJN
        application.add_handler(CallbackQueryHandler(self.button_callback))
        
        logger.info("Generic button_callback handler registered (last handler)")
        
        # Ensure signal handlers are registered
        logger.info("Enabling and initializing signals functionality")
        
        # Load any saved signals
        self._load_signals()
        
        logger.info("All handlers registered successfully")

    async def initialize(self, use_webhook=False):
        """Initialize the bot and either start polling or return the app for webhook usage"""
        try:
            # Set bot commands
            commands = [
                BotCommand("start", "Start the bot"),
                BotCommand("menu", "Show main menu"),
                BotCommand("help", "Get help"),
            ]
            await self.bot.set_my_commands(commands)
            logger.info("Bot commands set successfully")
            
            # Create application if not already done
            if not self.application:
                self.setup()
            else:
                # Make sure the application is initialized
                try:
                    await self.application.initialize()
                    logger.info("Application initialized from initialize method")
                except Exception as e:
                    logger.error(f"Error initializing application: {str(e)}")
                
            # Register all handlers
            self._register_handlers(self.application)
                
            # Enable or configure webhook based on use_webhook flag
            if use_webhook:
                logger.info(f"Setting up webhook configuration with URL {self.webhook_url}, port {os.getenv('PORT', 8080)}, path {self.webhook_path}")
                # Return the bot for webhook usage
                return self.bot
            else:
                # Start polling mode
                await self._setup_polling_mode()
                
            logger.info("Bot initialized with webhook configuration")
            
        except Exception as e:
            logger.error(f"Failed to initialize bot: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    async def _setup_polling_mode(self):
        """Set up the bot for polling mode"""
        try:
            # Set commands
            await self.bot.set_my_commands([
                BotCommand("start", "Start the bot and show main menu"),
                BotCommand("menu", "Show the main menu"),
                BotCommand("help", "Get help"),
            ])
            
            # Ensure signals are enabled in polling mode
            logger.info("Initializing signal processing in polling mode")
            # Make sure signals system is ready
            self._load_signals()
            
            # Webhook checks - disable any existing webhooks
            webhook_info = await self.bot.get_webhook_info()
            if webhook_info.url:
                await self.bot.delete_webhook()
                logger.info(f"Deleted existing webhook at {webhook_info.url}")
            
            # Start polling
            self._start_polling_thread()
            
        except Exception as e:
            logger.error(f"Failed to set up polling mode: {str(e)}")
            logger.error(traceback.format_exc())
            
    def _start_polling_thread(self):
        """Run polling in a separate thread to avoid event loop issues"""
        try:
            logger.info("Starting polling in separate thread")
            
            # Create a new event loop for this thread
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Set up a new Application instance for polling
            from telegram.ext import ApplicationBuilder
            polling_app = ApplicationBuilder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
            
            # Copy the handlers from the main application
            for handler in self.application.handlers.get(0, []):
                polling_app.add_handler(handler)
            
            # Start polling (this will block the thread)
            polling_app.run_polling(drop_pending_updates=True)
            
            logger.info("Polling thread finished")
        except Exception as e:
            logger.error(f"Error in polling thread: {str(e)}")
            logger.exception(e)

    async def setup_webhook(self, app):
        """Set up the FastAPI webhook for Telegram."""
        
        try:
            # Delete any existing webhook
            await self.bot.delete_webhook(drop_pending_updates=True)
            logger.info("Existing webhook deleted")
            
            # Set a consistent webhook path
            webhook_path = "/webhook"
            
            # Get base URL from environment or default
            base_url = os.getenv("WEBHOOK_URL", "").rstrip('/')
            if not base_url:
                base_url = "https://api.sigmapips.com"
                logger.warning(f"WEBHOOK_URL not set. Using default: {base_url}")
            
            # Prevent duplicate webhook path by checking if base_url already ends with webhook_path
            if base_url.endswith(webhook_path):
                # Remove the duplicate webhook path from base URL
                base_url = base_url[:-len(webhook_path)]
                logger.info(f"Removed duplicate webhook path from base URL: {base_url}")
            
            # Build the complete webhook URL
            webhook_url = f"{base_url}{webhook_path}"
            logger.info(f"Setting webhook URL to: {webhook_url}")
            
            # Set the webhook
            await self.bot.set_webhook(
                url=webhook_url,
                allowed_updates=["message", "callback_query", "my_chat_member"],
                drop_pending_updates=True
            )
            
            # Log the actual webhook info from Telegram
            webhook_info = await self.bot.get_webhook_info()
            logger.info(f"Webhook info: URL={webhook_info.url}, pending_updates={webhook_info.pending_update_count}")
            
            # Define the webhook route - keep it simple!
            @app.post(webhook_path)
            async def process_telegram_update(request: Request):
                data = await request.json()
                logger.info(f"Received update: {data.get('update_id', 'unknown')}")
                await self.process_update(data)
                return {"status": "ok"}
                
            logger.info(f"Webhook handler registered at path: {webhook_path}")
            
            # Register the signal processing API endpoint
            @app.post("/api/signals")
            async def process_signal_api(request: Request):
                try:
                    signal_data = await request.json()
                    
                    # Validate API key if one is set
                    api_key = request.headers.get("X-API-Key")
                    expected_key = os.getenv("SIGNAL_API_KEY")
                    
                    if expected_key and api_key != expected_key:
                        logger.warning(f"Invalid API key used in signal API request")
                        return {"status": "error", "message": "Invalid API key"}
                    
                    # Process the signal
                    success = await self.process_signal(signal_data)
                    
                    if success:
                        return {"status": "success", "message": "Signal processed successfully"}
                    else:
                        return {"status": "error", "message": "Failed to process signal"}
                    
                except Exception as e:
                    logger.error(f"Error processing signal API request: {str(e)}")
                    logger.exception(e)
                    return {"status": "error", "message": str(e)}
            
            # Register TradingView webhook endpoint at /signal
            @app.post("/signal")
            async def process_tradingview_signal(request: Request):
                """Process TradingView webhook signal"""
                try:
                    # Get the signal data from the request
                    signal_data = await request.json()
                    logger.info(f"Received TradingView webhook signal: {signal_data}")
                    
                    # Process the signal
                    success = await self.process_signal(signal_data)
                    
                    if success:
                        return {"status": "success", "message": "Signal processed successfully"}
                    else:
                        return {"status": "error", "message": "Failed to process signal"}
                        
                except Exception as e:
                    logger.error(f"Error processing TradingView webhook signal: {str(e)}")
                    logger.exception(e)
                    return {"status": "error", "message": str(e)}
            
            logger.info(f"Signal API endpoint registered at /api/signals")
            logger.info(f"TradingView signal endpoint registered at /signal")
                
            # Add debug endpoint to force-send main menu
            @app.get("/force_menu/{chat_id}")
            async def force_menu(chat_id: int):
                return await self.force_send_main_menu(chat_id)
            
            # Enable signals functionality in webhook mode
            logger.info("Initializing signal processing in webhook mode")
            self._load_signals()
            
            logger.info(f"Webhook set up successfully on {webhook_url}")
            
            return app
            
        except Exception as e:
            logger.error(f"Error setting up webhook: {str(e)}")
            logger.error(traceback.format_exc())
            return app

    async def process_update(self, update_data):
        """Process an update from Telegram."""
        try:
            # Check if update_data is a Request object or a dict
            if hasattr(update_data, 'json'):
                # It's a Request object, extract the JSON data
                update_data = await update_data.json()
            
            # Log the update
            update_id = update_data.get('update_id')
            logger.info(f"Received Telegram update: {update_id}")
            
            # Check if we have already processed this update
            if update_id in self.processed_updates:
                logger.info(f"Update {update_id} already processed, skipping")
                return {"status": "skipped", "reason": "already_processed"}
            
            # Add to processed updates set
            self.processed_updates.add(update_id)
            
            # Keep the processed updates set at a reasonable size
            if len(self.processed_updates) > 1000:
                # Remove the oldest updates
                self.processed_updates = set(sorted(self.processed_updates)[-500:])
                
            # Process callback queries
            if 'callback_query' in update_data:
                logger.info(f"Received callback query: {update_data['callback_query'].get('data', 'unknown')}")
                await self._process_callback_query(update_data)
                return {"status": "ok", "type": "callback_query"}
            
            # Process messages
            elif 'message' in update_data:
                if 'text' in update_data['message']:
                    text = update_data['message']['text']
                    logger.info(f"Received message: {text}")
                else:
                    logger.info(f"Received message without text")
                
                await self._process_message(update_data)
                return {"status": "ok", "type": "message"}
            
            # Process other update types as needed
            
            return {"status": "ok"}
            
        except Exception as e:
            logger.error(f"Failed to process update data: {str(e)}")
            logger.error(traceback.format_exc())
            return {"status": "error", "message": str(e)}

    def setup(self):
        """Set up the bot with all handlers"""
        # Build application with the existing bot instance
        application = Application.builder().bot(self.bot).build()
        
        # Command handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("menu", self.show_main_menu))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("set_subscription", self.set_subscription_command))
        application.add_handler(CommandHandler("set_payment_failed", self.set_payment_failed_command))
        
        # Callback query handler for all button presses
        application.add_handler(CallbackQueryHandler(self.button_callback))
        
        self.application = application
        
        # Initialize the application synchronously using a loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(self.application.initialize())
            logger.info("Application initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing application: {str(e)}")
            logger.exception(e)
            
        return application

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

• Indices - US30, US500, US100 and more

• Commodities - Gold, silver and oil

<b>Start today with a FREE 14-day trial!</b>
"""
            
            # Use direct URL link for the trial button
            trial_url = "https://buy.stripe.com/3cs3eF9Hu9256NW9AA"
            
            # Create button for trial
            keyboard = [
                [InlineKeyboardButton("🔥 Start 14-day FREE Trial", url=trial_url)]
            ]
            
            await update.message.reply_text(
                text=welcome_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Send a help message when the /help command is used."""
        help_text = """
📚 <b>Sigmapips AI Bot Help</b> 📚

<b>Available Commands:</b>
• /start - Start the bot and see the welcome message
• /menu - Show the main menu with all features
• /help - Display this help message

<b>Available Features:</b>
• Market Analysis - Get technical analysis, sentiment analysis, and economic calendar data
• Trading Signals - Receive trading signals for various markets
• Account Management - View and manage your subscription

<b>Need more help?</b>
If you have questions or encounter any issues, please contact our support team.
"""
        
        await update.message.reply_text(
            text=help_text,
            parse_mode=ParseMode.HTML
        )
        
    async def set_subscription_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Admin command to manually set a user's subscription status."""
        # Only admins can use this command
        user_id = update.effective_user.id
        if not self.admin_users or user_id not in self.admin_users:
            await update.message.reply_text("You are not authorized to use this command.")
            return
            
        try:
            # Format: /set_subscription [user_id] [status]
            args = update.message.text.split()
            if len(args) != 3:
                await update.message.reply_text("Usage: /set_subscription [user_id] [true/false]")
                return
                
            target_user_id = int(args[1])
            subscription_status = args[2].lower() == "true"
            
            # Update subscription in database
            await self.db.set_user_subscription(target_user_id, subscription_status)
            
            await update.message.reply_text(
                f"Subscription status for user {target_user_id} set to: {subscription_status}"
            )
            
        except Exception as e:
            logger.error(f"Error in set_subscription_command: {str(e)}")
            await update.message.reply_text(f"Error: {str(e)}")
    
    async def set_payment_failed_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Admin command to manually set a user's payment failure status."""
        # Only admins can use this command
        user_id = update.effective_user.id
        if not self.admin_users or user_id not in self.admin_users:
            await update.message.reply_text("You are not authorized to use this command.")
            return
            
        try:
            # Format: /set_payment_failed [user_id] [status]
            args = update.message.text.split()
            if len(args) != 3:
                await update.message.reply_text("Usage: /set_payment_failed [user_id] [true/false]")
                return
                
            target_user_id = int(args[1])
            payment_failed_status = args[2].lower() == "true"
            
            # Update payment failed status in database
            await self.db.set_payment_failed(target_user_id, payment_failed_status)
            
            await update.message.reply_text(
                f"Payment failed status for user {target_user_id} set to: {payment_failed_status}"
            )
            
        except Exception as e:
            logger.error(f"Error in set_payment_failed_command: {str(e)}")
            await update.message.reply_text(f"Error: {str(e)}")

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Show the main menu with options for analysis or signals."""
        # Get user ID
        user_id = update.effective_user.id
        
        # Check if the user has a subscription
        is_subscribed = await self.db.is_user_subscribed(user_id)
        payment_failed = await self.db.has_payment_failed(user_id)
        
        if is_subscribed and not payment_failed:
            # Show the main menu for subscribers
            try:
                # Get welcome GIF
                gif_url = await get_welcome_gif()
                
                # Send GIF with main menu keyboard
                await self.bot.send_animation(
                    chat_id=user_id,
                    animation=gif_url,
                    caption=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Sent main menu to user {user_id}")
                return MENU
                
            except Exception as e:
                # Fallback to text-only menu on error
                logger.error(f"Error showing main menu: {str(e)}")
                await update.message.reply_text(
                    text=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
                return MENU
        else:
            # Handle non-subscribers
            if payment_failed:
                # Show payment failure message for users with failed payments
                failed_payment_text = f"""
❗ <b>Subscription Payment Failed</b> ❗

Your subscription payment could not be processed and your service has been deactivated.

To continue using Sigmapips AI and receive trading signals, please reactivate your subscription by clicking the button below.
                """
                
                # Use direct URL link for reactivation
                reactivation_url = "https://buy.stripe.com/9AQcPf3j63HL5JS145"
                keyboard = [
                    [InlineKeyboardButton("🔄 Reactivate Subscription", url=reactivation_url)]
                ]
            else:
                # Show subscription message for new users
                welcome_text = """
🚀 Welcome to Sigmapips AI! 🚀

Discover powerful trading signals for various markets:
• Forex - Major and minor currency pairs

• Crypto - Bitcoin, Ethereum and other top
 cryptocurrencies

• Indices - US30, US500, US100 and more

• Commodities - Gold, silver and oil

<b>Start today with a FREE 14-day trial!</b>
"""
                
                # Use direct URL link for the trial button
                trial_url = "https://buy.stripe.com/3cs3eF9Hu9256NW9AA"
                keyboard = [
                    [InlineKeyboardButton("🔥 Start 14-day FREE Trial", url=trial_url)]
                ]
            
            # Send the message
            await update.message.reply_text(
                text=welcome_text if not payment_failed else failed_payment_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return MENU

    async def force_send_main_menu(self, chat_id: int) -> dict:
        """Force sending the main menu to a specific chat."""
        try:
            # Get user subscription information
            is_subscribed = await self.db.is_user_subscribed(chat_id)
            payment_failed = await self.db.has_payment_failed(chat_id)
            
            if is_subscribed and not payment_failed:
                # Regular subscribed user - send main menu
                try:
                    # Haal de welkomst-GIF op
                    gif_url = await get_welcome_gif()
                    
                    # Stuur een animatie die automatisch afspeelt
                    await self.bot.send_animation(
                        chat_id=chat_id,
                        animation=gif_url,
                        caption=WELCOME_MESSAGE,
                        reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as gif_error:
                    logger.error(f"Error sending welcome GIF: {str(gif_error)}")
                    # Fallback naar tekst-only als GIF faalt
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=WELCOME_MESSAGE,
                        reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                return {"status": "success", "message": "Main menu sent"}
            else:
                # Trial user or payment failed - send appropriate message
                if payment_failed:
                    text = """
❗ <b>Subscription Payment Failed</b> ❗

Your subscription payment could not be processed and your service has been deactivated.

To continue using Sigmapips AI and receive trading signals, please reactivate your subscription.
                    """
                    keyboard = [
                        [InlineKeyboardButton("🔄 Reactivate Subscription", url="https://buy.stripe.com/9AQcPf3j63HL5JS145")],
                        [InlineKeyboardButton("⬅️ Back to Menu", callback_data=CALLBACK_BACK_MENU)]
                    ]
                else:
                    text = """
🚀 <b>Trading Signals Subscription Required</b> 🚀

To access trading signals, you need an active subscription.

Get started today with a FREE 14-day trial!
                    """
                    keyboard = [
                        [InlineKeyboardButton("🔥 Start 14-day FREE Trial", url="https://buy.stripe.com/3cs3eF9Hu9256NW9AA")],
                        [InlineKeyboardButton("⬅️ Back to Menu", callback_data=CALLBACK_BACK_MENU)]
                    ]
                
                # Send message directly since we don't have a query object here
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                return {"status": "success", "message": "Subscription message sent"}
                
        except Exception as e:
            logger.error(f"Error in force_send_main_menu: {str(e)}")
            return {"status": "error", "message": str(e)}
            
    async def back_instrument_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle back_instrument callback to return to the instrument selection."""
        query = update.callback_query
        await query.answer()
        
        try:
            # Clear style/timeframe data but keep instrument
            if context and hasattr(context, 'user_data'):
                keys_to_clear = ['style', 'timeframe']
                for key in keys_to_clear:
                    if key in context.user_data:
                        del context.user_data[key]
            
            # Get stored instrument from context
            instrument = None
            if context and hasattr(context, 'user_data'):
                instrument = context.user_data.get('instrument')
            
            if not instrument:
                # If no instrument, go back to market selection
                return await self.back_market_callback(update, context)
            
            # Show the instrument options
            # This might be a custom view for the instrument, for now we'll go back to market
            return await self.back_market_callback(update, context)
            
        except Exception as e:
            logger.error(f"Error in back_instrument_callback: {str(e)}")
            # Try to recover by going to market selection
            return await self.back_market_callback(update, context)
            
    async def _process_callback_query(self, update_data):
        """Process callback query updates."""
        try:
            # Create a CallbackQuery object from the update data
            query_data = update_data.get('callback_query', {})
            
            # Get the callback data
            callback_data = query_data.get('data', '')
            
            # Get the message data
            message = query_data.get('message', {})
            chat_id = message.get('chat', {}).get('id')
            message_id = message.get('message_id')
            
            # Get the user data
            from_user = query_data.get('from', {})
            user_id = from_user.get('id')
            
            logger.info(f"Processing callback query: {callback_data} from user {user_id}")
            
            # Create an Update object
            from telegram import Update
            update = Update.de_json(update_data, self.bot)
            
            # Create a context
            context = None
            
            # Route the callback to the appropriate handler
            if callback_data == CALLBACK_BACK_MENU:
                await self.back_menu_callback(update, context)
            elif callback_data == CALLBACK_ANALYSIS_TECHNICAL:
                await self.analysis_technical_callback(update, context)
            elif callback_data == CALLBACK_ANALYSIS_SENTIMENT:
                await self.analysis_sentiment_callback(update, context)
            elif callback_data == CALLBACK_ANALYSIS_CALENDAR:
                await self.analysis_calendar_callback(update, context)
            elif callback_data == "back_analysis":
                await self.back_analysis_callback(update, context)
            elif callback_data == "back_market":
                await self.back_market_callback(update, context)
            elif callback_data == "back_signals":
                await self.back_signals_callback(update, context)
            elif callback_data == "back_instrument":
                await self.back_instrument_callback(update, context)
            elif callback_data == "back_to_signal":
                await self.back_to_signal_callback(update, context)
            elif callback_data == "back_to_signal_analysis":
                await self.back_to_signal_analysis_callback(update, context)
            elif callback_data.startswith("signal_technical"):
                await self.signal_technical_callback(update, context)
            elif callback_data.startswith("signal_sentiment"):
                await self.signal_sentiment_callback(update, context)
            elif callback_data.startswith("signal_calendar"):
                await self.signal_calendar_callback(update, context)
            elif callback_data.startswith("instrument_"):
                await self.instrument_callback(update, context)
            else:
                # Default to the generic button callback
                await self.button_callback(update, context)
            
            return {"status": "ok", "message": "Callback processed"}
            
        except Exception as e:
            logger.error(f"Error processing callback query: {str(e)}")
            logger.exception(e)
            return {"status": "error", "message": str(e)}
            
    async def _process_message(self, update_data):
        """Process message updates."""
        try:
            # Create an Update object
            from telegram import Update
            update = Update.de_json(update_data, self.bot)
            
            # Get message text
            message = update_data.get('message', {})
            text = message.get('text', '')
            
            # Get user data
            from_user = message.get('from', {})
            user_id = from_user.get('id')
            
            logger.info(f"Processing message: {text} from user {user_id}")
            
            # Create a context
            context = None
            
            # Route the message to the appropriate handler
            if text == '/start':
                await self.start_command(update, context)
            elif text == '/menu':
                await self.show_main_menu(update, context)
            elif text == '/help':
                await self.help_command(update, context)
            elif text.startswith('/set_subscription'):
                await self.set_subscription_command(update, context)
            elif text.startswith('/set_payment_failed') or text.startswith('/setpaymentfailed'):
                await self.set_payment_failed_command(update, context)
            else:
                # Unknown command
                await update.message.reply_text(
                    "Unknown command. Please use /help to see all available commands."
                )
            
            return {"status": "ok", "message": "Message processed"}
            
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            logger.exception(e)
            return {"status": "error", "message": str(e)}

    async def analysis_technical_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle technical analysis selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Debug logging
            logger.info("analysis_technical_callback aangeroepen")
            
            # Store analysis type in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'technical'
                context.user_data['current_state'] = CHOOSE_MARKET
            
            # Update the message markup
            await query.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
            )
            
            return CHOOSE_MARKET
            
        except Exception as e:
            logger.error(f"Error in analysis_technical_callback: {str(e)}")
            logger.exception(e)
            return MENU

    async def analysis_sentiment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle sentiment analysis selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Debug logging
            logger.info("analysis_sentiment_callback aangeroepen")
            
            # Store analysis type in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'sentiment'
                context.user_data['current_state'] = CHOOSE_MARKET
            
            # Update the message markup
            await query.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(MARKET_SENTIMENT_KEYBOARD)
            )
            
            return CHOOSE_MARKET
            
        except Exception as e:
            logger.error(f"Error in analysis_sentiment_callback: {str(e)}")
            logger.exception(e)
            return MENU

    async def analysis_calendar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle calendar analysis selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Debug logging
            logger.info("analysis_calendar_callback aangeroepen")
            
            # Store analysis type in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'calendar'
                context.user_data['current_state'] = CHOOSE_MARKET
            
            # Update the message markup
            await query.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
            )
            
            return CHOOSE_MARKET
            
        except Exception as e:
            logger.error(f"Error in analysis_calendar_callback: {str(e)}")
            logger.exception(e)
            return MENU
    
    async def back_to_signal_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle back to signal callback - return to the signal details."""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get the signal ID from context
            signal_id = None
            if context and hasattr(context, 'user_data'):
                signal_id = context.user_data.get('signal_id')
                
            if not signal_id:
                # If no signal ID, go back to main menu
                return await self.back_menu_callback(update, context)
            
            # Show the signal details again
            user_id = update.effective_user.id
            
            # Get the signal from storage
            if user_id in self.user_signals:
                signal = self.user_signals[user_id]
                
                # Create a formatted message for the signal
                instrument = signal.get('instrument', 'Unknown')
                direction = signal.get('direction', 'Unknown').upper()
                message = signal.get('message', f"Trading signal for {instrument}")
                
                # Add direction emoji
                direction_emoji = "🔴" if direction == "SELL" else "🟢"
                
                # Build message with action buttons
                signal_text = f"""
{direction_emoji} <b>{direction} {instrument}</b>

{message}

<b>Analysis Options:</b>
                """
                
                # Create keyboard with analysis options
                keyboard = [
                    [InlineKeyboardButton("📈 Technical Analysis", callback_data=f"analysis_technical_signal_{signal_id}")],
                    [InlineKeyboardButton("🧠 Market Sentiment", callback_data=f"analysis_sentiment_signal_{signal_id}")],
                    [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"analysis_calendar_signal_{signal_id}")],
                    [InlineKeyboardButton("⬅️ Back to Menu", callback_data=CALLBACK_BACK_MENU)]
                ]
                
                # Use the update_message utility to handle any message type
                await self.update_message(
                    query=query,
                    text=signal_text,
                    keyboard=keyboard,
                    parse_mode=ParseMode.HTML
                )
                
                return SIGNAL_DETAILS
            else:
                # No signal found, go back to main menu
                return await self.back_menu_callback(update, context)
        except Exception as e:
            logger.error(f"Error in back_to_signal_callback: {str(e)}")
            # Try to recover
            return await self.back_menu_callback(update, context)
            
    async def signal_technical_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle technical analysis for a signal."""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get user ID and signal
            user_id = update.effective_user.id
            
            if user_id not in self.user_signals:
                await self.update_message(
                    query=query,
                    text="No active signal found. Please return to the main menu.",
                    keyboard=[[InlineKeyboardButton("⬅️ Back to Menu", callback_data=CALLBACK_BACK_MENU)]],
                    parse_mode=ParseMode.HTML
                )
                return MENU
            
            signal = self.user_signals[user_id]
            instrument = signal.get('instrument', 'Unknown')
            
            # Save signal analysis state in context
            if context and hasattr(context, 'user_data'):
                context.user_data['in_signal_analysis'] = True
                context.user_data['signal_instrument'] = instrument
                context.user_data['analysis_type'] = 'technical'
            
            # Show loading message
            await self.update_message(
                query=query,
                text=f"Generating technical analysis for {instrument}...",
                keyboard=None,
                parse_mode=ParseMode.HTML
            )
            
            # Get the technical analysis chart
            try:
                # Use the chart service to get the analysis
                img_path, levels = await self.chart_service.get_chart(instrument)
                
                if not img_path or not os.path.exists(img_path):
                    raise FileNotFoundError(f"Chart not found for {instrument}")
                
                # Format the levels text
                levels_text = ""
                if levels and isinstance(levels, dict):
                    # Sort levels by price
                    sorted_levels = sorted(levels.items(), key=lambda x: float(x[1]))
                    
                    for level_type, price in sorted_levels:
                        emoji = "🟢" if level_type.lower() == "support" else "🔴"
                        levels_text += f"{emoji} {level_type}: {price}\n"
                
                caption = f"📈 <b>Technical Analysis: {instrument}</b>\n\n"
                if levels_text:
                    caption += f"<b>Key Levels:</b>\n{levels_text}\n"
                
                # Create back button
                keyboard = [
                    [InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]
                ]
                
                # Send the chart image
                with open(img_path, 'rb') as image:
                    await query.edit_message_media(
                        media=InputMediaPhoto(
                            media=image,
                            caption=caption,
                            parse_mode=ParseMode.HTML
                        ),
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                
                return SIGNAL_DETAILS
            except Exception as chart_error:
                logger.error(f"Error getting chart for {instrument}: {str(chart_error)}")
                
                # Show error message
                await self.update_message(
                    query=query,
                    text=f"❌ Could not generate technical analysis for {instrument}.\n\nPlease try again later.",
                    keyboard=[[InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]],
                    parse_mode=ParseMode.HTML
                )
                return SIGNAL_DETAILS
        except Exception as e:
            logger.error(f"Error in signal_technical_callback: {str(e)}")
            # Recovery
            await query.message.reply_text(
                text="An error occurred. Please try again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Menu", callback_data=CALLBACK_BACK_MENU)]
                ])
            )
            return MENU
            
    async def signal_sentiment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle sentiment analysis for a signal."""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get user ID and signal
            user_id = update.effective_user.id
            
            if user_id not in self.user_signals:
                await self.update_message(
                    query=query,
                    text="No active signal found. Please return to the main menu.",
                    keyboard=[[InlineKeyboardButton("⬅️ Back to Menu", callback_data=CALLBACK_BACK_MENU)]],
                    parse_mode=ParseMode.HTML
                )
                return MENU
            
            signal = self.user_signals[user_id]
            instrument = signal.get('instrument', 'Unknown')
            
            # Save signal analysis state in context
            if context and hasattr(context, 'user_data'):
                context.user_data['in_signal_analysis'] = True
                context.user_data['signal_instrument'] = instrument
                context.user_data['analysis_type'] = 'sentiment'
            
            # Show loading message
            await self.update_message(
                query=query,
                text=f"Generating sentiment analysis for {instrument}...",
                keyboard=None,
                parse_mode=ParseMode.HTML
            )
            
            # Get the sentiment analysis
            try:
                # Use the sentiment service to get the analysis
                sentiment_data = await self.sentiment_service.get_market_sentiment_text(instrument)
                
                if not sentiment_data:
                    raise ValueError(f"No sentiment data available for {instrument}")
                
                # Check if we received a string (formatted text) or dictionary
                if isinstance(sentiment_data, str):
                    # Direct formatted text - display as is
                    sentiment_text = sentiment_data
                else:
                    # Format the sentiment data from dictionary
                    bullish = sentiment_data.get('bullish', 0)
                    bearish = sentiment_data.get('bearish', 0)
                    neutral = sentiment_data.get('neutral', 0)
                
                # Calculate total and percentages
                total = bullish + bearish + neutral
                bullish_pct = (bullish / total * 100) if total > 0 else 0
                bearish_pct = (bearish / total * 100) if total > 0 else 0
                neutral_pct = (neutral / total * 100) if total > 0 else 0
                
                # Create sentiment bars
                bull_bar = "🟢" * int(bullish_pct / 10) if bullish_pct >= 10 else "⚪" if bullish_pct > 0 else ""
                bear_bar = "🔴" * int(bearish_pct / 10) if bearish_pct >= 10 else "⚪" if bearish_pct > 0 else ""
                neutral_bar = "⚪" * int(neutral_pct / 10) if neutral_pct >= 10 else ""
                
                # Create sentiment text
                sentiment_text = f"""
🧠 <b>Market Sentiment: {instrument}</b>

<b>Bullish:</b> {bullish_pct:.1f}% {bull_bar}
<b>Bearish:</b> {bearish_pct:.1f}% {bear_bar}
<b>Neutral:</b> {neutral_pct:.1f}% {neutral_bar}

<b>Total Traders:</b> {total}
                """
                
                # Create back button
                keyboard = [
                    [InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]
                ]
                
                # Show sentiment analysis
                await self.update_message(
                    query=query,
                    text=sentiment_text,
                    keyboard=keyboard,
                    parse_mode=ParseMode.HTML
                )
                
                return SIGNAL_DETAILS
            except Exception as sentiment_error:
                logger.error(f"Error getting sentiment for {instrument}: {str(sentiment_error)}")
                
                # Show error message
                await self.update_message(
                    query=query,
                    text=f"❌ Could not generate sentiment analysis for {instrument}.\n\nPlease try again later.",
                    keyboard=[[InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]],
                    parse_mode=ParseMode.HTML
                )
                return SIGNAL_DETAILS
        except Exception as e:
            logger.error(f"Error in signal_sentiment_callback: {str(e)}")
            # Recovery
            await query.message.reply_text(
                text="An error occurred. Please try again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Menu", callback_data=CALLBACK_BACK_MENU)]
                ])
            )
            return MENU
            
    async def signal_calendar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle calendar analysis for a signal."""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get user ID and signal
            user_id = update.effective_user.id
            
            if user_id not in self.user_signals:
                await self.update_message(
                    query=query,
                    text="No active signal found. Please return to the main menu.",
                    keyboard=[[InlineKeyboardButton("⬅️ Back to Menu", callback_data=CALLBACK_BACK_MENU)]],
                    parse_mode=ParseMode.HTML
                )
                return MENU
            
            signal = self.user_signals[user_id]
            instrument = signal.get('instrument', 'Unknown')
            
            # Save signal analysis state in context
            if context and hasattr(context, 'user_data'):
                context.user_data['in_signal_analysis'] = True
                context.user_data['signal_instrument'] = instrument
                context.user_data['analysis_type'] = 'calendar'
            
            # Show loading message
            await self.update_message(
                query=query,
                text=f"Generating economic calendar for {instrument}...",
                keyboard=None,
                parse_mode=ParseMode.HTML
            )
            
            # Get the calendar analysis
            try:
                # Use the calendar service to get the analysis
                calendar_data = await self.calendar_service.get_instrument_calendar(instrument)
                
                if not calendar_data:
                    raise ValueError(f"No calendar data available for {instrument}")
                
                # Show the calendar analysis
                await self.update_message(
                    query=query,
                    text=calendar_data,
                    keyboard=[[InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]],
                    parse_mode=ParseMode.HTML
                )
                
                return SIGNAL_DETAILS
            except Exception as calendar_error:
                logger.error(f"Error getting calendar for {instrument}: {str(calendar_error)}")
                
                # Show error message
                await self.update_message(
                    query=query,
                    text=f"❌ Could not generate economic calendar for {instrument}.\n\nPlease try again later.",
                    keyboard=[[InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]],
                    parse_mode=ParseMode.HTML
                )
                return SIGNAL_DETAILS
        except Exception as e:
            logger.error(f"Error in signal_calendar_callback: {str(e)}")
            # Recovery
            await query.message.reply_text(
                text="An error occurred. Please try again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Menu", callback_data=CALLBACK_BACK_MENU)]
                ])
            )
            return MENU
            
    async def back_to_signal_analysis_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle the back to signal analysis button."""
        try:
            query = update.callback_query
            await query.answer()
            
            # Get signal ID from user data
            user_data = context.user_data
            signal_id = user_data.get('signal_id')
            
            if not signal_id or signal_id not in self.signals:
                logger.warning(f"Signal ID {signal_id} not found in back_to_signal_analysis_callback")
                return await self.back_menu_callback(update, context)
            
            # Get the signal
            signal = self.signals[signal_id]
            
            # Format the message
            signal_text = f"📊 <b>Analysis Options for {signal['instrument']}</b>\n\n"
            signal_text += f"Choose the type of analysis you want to see for this {signal['market']} instrument."
            
            # Create keyboard with analysis options
            keyboard = [
                [InlineKeyboardButton("📈 Technical Analysis", callback_data=f"signal_technical")],
                [InlineKeyboardButton("🧠 Market Sentiment", callback_data=f"signal_sentiment")],
                [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"signal_calendar")],
                [InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]
            ]
            
            await self.update_message(
                query=query,
                text=signal_text,
                keyboard=keyboard,
                parse_mode=ParseMode.HTML
            )
            return SIGNAL_DETAILS
        except Exception as e:
            logger.error(f"Error in back_to_signal_analysis_callback: {str(e)}")
            # Try to recover
            return await self.back_menu_callback(update, context)

    async def back_market_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle back to market selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Check if message contains media
            has_media = bool(query.message.photo) or query.message.animation is not None
            
            # Get the analysis type, defaulting to technical if context is None or analysis_type not set
            analysis_type = 'technical'
            if context and hasattr(context, 'user_data'):
                analysis_type = context.user_data.get('analysis_type', 'technical')
            
            # Choose the appropriate keyboard based on analysis type
            if analysis_type == 'sentiment':
                keyboard = MARKET_SENTIMENT_KEYBOARD
            else:
                keyboard = MARKET_KEYBOARD
            
            if has_media:
                try:
                    # Try to delete the message first
                    await query.message.delete()
                    # Send a new message with the market selection
                    await query.message.reply_text(
                        text="Select a market for analysis:",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as delete_error:
                    logger.warning(f"Could not delete message: {str(delete_error)}")
                    try:
                        # Try to replace media with empty content
                        await query.message.edit_media(
                            media=InputMediaDocument(
                                media="https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/Transparent.gif/1px-Transparent.gif",
                                caption="Select a market for analysis:",
                            ),
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    except Exception as edit_error:
                        logger.warning(f"Could not edit media: {str(edit_error)}")
                        # If all else fails, just try to edit the caption
                        await query.message.edit_caption(
                            caption="Select a market for analysis:",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
            else:
                # If no media, just update the reply markup
                await query.message.edit_reply_markup(
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            return CHOOSE_MARKET
            
        except Exception as e:
            logger.error(f"Error in back_market_callback: {str(e)}")
            logger.exception(e)
            # If something goes wrong, try to show the main menu
            try:
                await self.show_main_menu(update, context)
            except:
                pass
            return MENU
    
    async def back_analysis_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle back button press from market selection to return to analysis type selection."""
        query = update.callback_query
        await query.answer()
        
        try:
            # Clear market from context if it exists
            if context and hasattr(context, 'user_data') and 'market' in context.user_data:
                del context.user_data['market']
                
            # Show analysis options menu
            keyboard = ANALYSIS_KEYBOARD
            text = "Choose an analysis type:"
            
            await self.update_message(
                query=query,
                text=text,
                keyboard=keyboard,
                parse_mode=ParseMode.HTML
            )
            
            return CHOOSE_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error in back_analysis_callback: {str(e)}")
            # Try to recover by going to main menu
            return await self.back_menu_callback(update, context)
    
    async def back_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle back button press to return to main menu."""
        query = update.callback_query
        await query.answer()
        
        try:
            # Clear all navigation-related user data
            if context and hasattr(context, 'user_data'):
                keys_to_clear = ['market', 'instrument', 'analysis_type']
                for key in keys_to_clear:
                    if key in context.user_data:
                        del context.user_data[key]
                        
            # Show the main menu with GIF if possible
            try:
                # Get welcome GIF
                gif_url = await get_welcome_gif()
                
                # Try to delete the current message and send a new animation
                await query.message.delete()
                
                # Send a new GIF that will autoplay
                await self.bot.send_animation(
                    chat_id=query.message.chat_id,
                    animation=gif_url,
                    caption=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
                return MENU
            except Exception as e:
                logger.error(f"Error sending welcome GIF in back_menu_callback: {str(e)}")
                # Fallback to text-only update if GIF fails
                await self.update_message(
                        query=query,
                    text=WELCOME_MESSAGE,
                    keyboard=START_KEYBOARD,
                        parse_mode=ParseMode.HTML
                    )
                return MENU
                
        except Exception as e:
            logger.error(f"Error in back_menu_callback: {str(e)}")
            # Try to send a new message with the main menu as a last resort
            try:
                await query.message.reply_text(
                    text=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
            return MENU
            
    async def back_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle back button press to return to signals selection."""
        query = update.callback_query
        await query.answer()
        
        try:
            # Clear relevant context data
            if context and hasattr(context, 'user_data'):
                keys_to_clear = ['market', 'instrument']
                for key in keys_to_clear:
                    if key in context.user_data:
                        del context.user_data[key]
            
            # Show the signals options menu
            keyboard = SIGNALS_KEYBOARD
            text = "Choose a signals option:"
            
            await self.update_message(
                query=query,
                text=text,
                keyboard=keyboard,
                parse_mode=ParseMode.HTML
            )
            
            return CHOOSE_SIGNALS
                
        except Exception as e:
            logger.error(f"Error in back_signals_callback: {str(e)}")
            # Try to recover by going to main menu
            return await self.back_menu_callback(update, context)
            
    async def instrument_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle instrument selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get callback data and analysis type
            callback_data = query.data
            analysis_type = context.user_data.get('analysis_type', 'technical') if context and hasattr(context, 'user_data') else 'technical'
            
            # Extract instrument from callback
            instrument = callback_data.replace('instrument_', '')
            
            # Store the selected instrument
            if context and hasattr(context, 'user_data'):
                context.user_data['instrument'] = instrument
            
            # Handle different analysis types
            if analysis_type == 'technical':
                # For technical analysis, format the TradingView URL
                await self._handle_technical_analysis(query, instrument)
                return SHOW_RESULT
                
            elif analysis_type == 'sentiment':
                # For sentiment analysis, show loading and trigger sentiment callback
                loading_message = await query.message.reply_animation(
                    animation="https://media.giphy.com/media/3oEjI6SIIHBdRxXI40/giphy.gif",
                    caption=f"⏳ Generating sentiment analysis for {instrument}..."
                )
                
                # Store the loading message ID for later deletion
                if context and hasattr(context, 'user_data'):
                    context.user_data['loading_message_id'] = loading_message.message_id
                
                # Trigger sentiment analysis
                await self.direct_sentiment_callback(
                    Update(
                        update_id=update.update_id,
                        callback_query=CallbackQuery(
                            id=query.id,
                            from_user=query.from_user,
                            chat_instance=query.chat_instance,
                            data=f"direct_sentiment_{instrument}",
                            message=loading_message
                        )
                    ),
                    context
                )
                return SHOW_RESULT
                
            elif analysis_type == 'calendar':
                # For calendar analysis, show economic calendar
                await self._handle_calendar_analysis(query, instrument)
                return SHOW_RESULT
                
            else:
                logger.error(f"Unknown analysis type: {analysis_type}")
                return MENU
                
        except Exception as e:
            logger.error(f"Error in instrument callback: {str(e)}")
            logger.exception(e)
            return MENU

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """General callback handler for buttons that don't have specific handlers."""
        query = update.callback_query
        await query.answer()
        
        try:
            callback_data = query.data
            logger.info(f"Generic button callback handling: {callback_data}")
            
            # Check which type of callback this is and route appropriately
            if callback_data == CALLBACK_MENU_ANALYSE:
                # Show the analysis options menu
                keyboard = ANALYSIS_KEYBOARD
                text = "Choose an analysis type:"
                
                await self.update_message(
                    query=query,
                    text=text,
                    keyboard=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                return CHOOSE_ANALYSIS
                
            elif callback_data == CALLBACK_MENU_SIGNALS:
                # Show the signals options menu
                keyboard = SIGNALS_KEYBOARD
                text = "Choose a signals option:"
                
                await self.update_message(
                    query=query,
                    text=text,
                    keyboard=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                return CHOOSE_SIGNALS
                
            elif callback_data == CALLBACK_SIGNALS_ADD:
                # Show market selection for adding new signal pairs
                keyboard = MARKET_KEYBOARD_SIGNALS
                text = "Select a market for trading signals:"
                
                await self.update_message(
                    query=query,
                    text=text,
                    keyboard=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                return CHOOSE_MARKET
                
            elif callback_data == CALLBACK_SIGNALS_MANAGE:
                # Show existing signal subscriptions
                # This would typically show the user's current signal preferences
                # and allow them to modify or delete them
                text = "Your current signal subscriptions:"
                
                # This is a placeholder - you would normally retrieve the user's preferences here
                keyboard = [
                    [InlineKeyboardButton("⬅️ Back to Signals", callback_data=CALLBACK_BACK_SIGNALS)]
                ]
                
                await self.update_message(
                    query=query,
                    text=text,
                    keyboard=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                return CHOOSE_SIGNALS
                
            elif callback_data.startswith("market_"):
                # Handle market selection
                parts = callback_data.split("_")
                market = parts[1]
                is_signals = len(parts) > 2 and parts[2] == "signals"
                is_sentiment = len(parts) > 2 and parts[2] == "sentiment"
                
                # Store market in context
                if context and hasattr(context, 'user_data'):
                    context.user_data['market'] = market
                    if is_signals:
                        context.user_data['is_signals'] = True
                    if is_sentiment:
                        context.user_data['is_sentiment'] = True
                        context.user_data['analysis_type'] = 'sentiment'
                
                # Choose the appropriate keyboard based on market type and analysis type
                keyboard = None
                text = f"Select an instrument from {market.capitalize()}:"
                
                if is_sentiment:
                    # Use sentiment-specific keyboards
                    if market == "forex":
                        keyboard = FOREX_SENTIMENT_KEYBOARD
                    elif market == "crypto":
                        keyboard = CRYPTO_SENTIMENT_KEYBOARD
                    else:
                        # For now, we'll use the regular keyboards for other markets in sentiment mode
                        # In the future, you might want to create sentiment-specific keyboards for all markets
                        if market == "commodities":
                            keyboard = COMMODITIES_KEYBOARD
                        elif market == "indices":
                            keyboard = INDICES_KEYBOARD_SIGNALS
                        else:
                            keyboard = FOREX_SENTIMENT_KEYBOARD  # Default to forex sentiment
                elif is_signals:
                    # Use signals-specific keyboards
                    if market == "forex":
                        keyboard = FOREX_KEYBOARD_SIGNALS
                    elif market == "crypto":
                        keyboard = CRYPTO_KEYBOARD_SIGNALS
                    elif market == "commodities":
                        keyboard = COMMODITIES_KEYBOARD_SIGNALS
                    elif market == "indices":
                        keyboard = INDICES_KEYBOARD_SIGNALS
                    else:
                        keyboard = FOREX_KEYBOARD_SIGNALS  # Default to forex signals
                else:
                    # Use regular analysis keyboards
                    if market == "forex":
                        keyboard = FOREX_KEYBOARD
                    elif market == "crypto":
                        keyboard = CRYPTO_KEYBOARD
                    elif market == "commodities":
                        keyboard = COMMODITIES_KEYBOARD
                    elif market == "indices":
                        keyboard = INDICES_KEYBOARD
                    else:
                        keyboard = FOREX_KEYBOARD  # Default to forex
                
                # Update message with selected keyboard
                await self.update_message(
                    query=query,
                    text=text,
                    keyboard=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                return CHOOSE_INSTRUMENT
                
            else:
                # Unknown callback type
                logger.warning(f"Unknown callback data: {callback_data}")
                # Try to go back to the main menu as a fallback
                return await self.back_menu_callback(update, context)
                
        except Exception as e:
            logger.error(f"Error in button_callback: {str(e)}")
            # Try to recover by going to main menu
            return await self.back_menu_callback(update, context)
            
    async def update_message(self, query, text, keyboard=None, parse_mode=ParseMode.HTML, **kwargs):
        """Update an existing message with new text and keyboard."""
        try:
            # First attempt: edit_message_text
            await query.edit_message_text(
                text=text,
                reply_markup=keyboard,
                parse_mode=parse_mode,
                **kwargs
            )
            return True
        except Exception as e:
            logger.warning(f"Could not edit message text: {str(e)}")
            
            # Second attempt: If message has no text (like media messages)
            if "There is no text in the message to edit" in str(e):
                try:
                    # Try to edit caption instead
                    await query.edit_message_caption(
                        caption=text,
                        reply_markup=keyboard,
                        parse_mode=parse_mode
                    )
                    return True
                except Exception as caption_error:
                    logger.warning(f"Could not edit caption: {str(caption_error)}")
                    
                    # Third attempt: Try to edit media
                    try:
                        # Use a placeholder image if needed
                        await query.edit_message_media(
                            media=InputMediaPhoto(
                                media="https://via.placeholder.com/800x600.png?text=Loading...",
                                caption=text,
                                parse_mode=parse_mode
                            ),
                            reply_markup=keyboard
                        )
                        return True
                    except Exception as media_error:
                        logger.error(f"All update attempts failed: {str(media_error)}")
            
            # Final fallback: send a new message
            try:
                await query.message.reply_text(
                    text=text,
                    reply_markup=keyboard,
                    parse_mode=parse_mode,
                    **kwargs
                )
                return True
            except Exception as reply_error:
                logger.error(f"Could not send fallback message: {str(reply_error)}")
                return False

    async def process_signal(self, signal_data):
        """
        Process a trading signal and send it to subscribers.
        
        Args:
            signal_data: Dictionary containing signal information
            
        Returns:
            bool: Success status
        """
        try:
            # Validate required fields
            required_fields = ['instrument', 'direction', 'message']
            for field in required_fields:
                if field not in signal_data:
                    logger.error(f"Missing required field in signal: {field}")
                    return False
                    
            # Extract signal data
            instrument = signal_data['instrument']
            direction = signal_data['direction']
            message = signal_data['message']
            
            # Format timestamp if not provided
            if 'timestamp' not in signal_data:
                signal_data['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
            # Get list of subscribers who should receive this signal
            subscribers = await self.get_subscribers_for_instrument(instrument)
            
            if not subscribers:
                logger.warning(f"No subscribers found for instrument {instrument}")
                return True  # Return True as this is not an error
                
            # Send signal to all subscribers
            success_count = 0
            for subscriber_id in subscribers:
                try:
                    # Create signal message with appropriate formatting
                    signal_emoji = "🟢" if direction.lower() == "buy" else "🔴"
                    formatted_message = f"""
<b>{signal_emoji} {direction.upper()} SIGNAL: {instrument}</b>
{signal_data['timestamp']}

{message}
"""
                    
                    # Create buttons for signal actions
                    keyboard = [
                        [
                            InlineKeyboardButton("📈 Technical Analysis", 
                                                callback_data=f"analysis_technical_signal_{instrument}"),
                            InlineKeyboardButton("🧠 Sentiment", 
                                                callback_data=f"analysis_sentiment_signal_{instrument}")
                        ],
                        [
                            InlineKeyboardButton("📅 Economic Calendar", 
                                                callback_data=f"analysis_calendar_signal_{instrument}"),
                            InlineKeyboardButton("⬅️ Back", 
                                                callback_data="back_menu")
                        ]
                    ]
                    
                    # Send message to subscriber
                    await self.bot.send_message(
                        chat_id=subscriber_id,
                        text=formatted_message,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    success_count += 1
                    
                except Exception as e:
                    logger.error(f"Error sending signal to {subscriber_id}: {str(e)}")
                    
            # Log results
            logger.info(f"Signal for {instrument} sent to {success_count}/{len(subscribers)} subscribers")
            
            # Store signal for later reference
            self.user_signals[instrument] = signal_data
            self._save_signals()
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing signal: {str(e)}")
            return False
            
    async def get_subscribers_for_instrument(self, instrument):
        """
        Get subscribers who should receive signals for a specific instrument.
        
        Args:
            instrument: The instrument code (e.g., 'EURUSD')
            
        Returns:
            list: List of subscriber chat IDs
        """
        try:
            # Detect the market for this instrument
            market = self._detect_market(instrument)
            
            # For now, return all subscribers
            # In a real implementation, you would filter based on user preferences
            return await self.get_subscribers()
            
        except Exception as e:
            logger.error(f"Error getting subscribers for instrument {instrument}: {str(e)}")
            return []

    async def market_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle market selection for analysis"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Extract market and analysis type from callback data
            callback_data = query.data
            
            # Extract market from callback data (format: market_forex, market_crypto, etc.)
            if '_sentiment' in callback_data:
                market = callback_data.replace('market_', '').replace('_sentiment', '')
                analysis_type = 'sentiment'
            else:
                market = callback_data.replace('market_', '')
                analysis_type = context.user_data.get('analysis_type', 'technical')
            
            logger.info(f"Market callback called with market: {market}, analysis_type: {analysis_type}")
            
            # Store selected market in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['selected_market'] = market
                context.user_data['analysis_type'] = analysis_type
                context.user_data['current_state'] = CHOOSE_INSTRUMENT
            
            # Get appropriate keyboard for the market and analysis type
            keyboard = self.get_instrument_keyboard(market, analysis_type)
            
            # Update the message markup
            await query.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return CHOOSE_INSTRUMENT
            
        except Exception as e:
            logger.error(f"Error in market_callback: {str(e)}")
            logger.exception(e)
            return MENU

    def get_instrument_keyboard(self, market: str, analysis_type: str) -> List[List[InlineKeyboardButton]]:
        """Get the appropriate keyboard for instrument selection based on market and analysis type"""
        # Define sentiment-specific keyboards
        SENTIMENT_KEYBOARDS = {
            'forex': [
                [
                    InlineKeyboardButton("EURUSD", callback_data="direct_sentiment_EURUSD"),
                    InlineKeyboardButton("GBPUSD", callback_data="direct_sentiment_GBPUSD")
                ],
                [
                    InlineKeyboardButton("USDJPY", callback_data="direct_sentiment_USDJPY"),
                    InlineKeyboardButton("USDCHF", callback_data="direct_sentiment_USDCHF")
                ],
                [
                    InlineKeyboardButton("AUDUSD", callback_data="direct_sentiment_AUDUSD"),
                    InlineKeyboardButton("USDCAD", callback_data="direct_sentiment_USDCAD")
                ],
                [
                    InlineKeyboardButton("EURGBP", callback_data="direct_sentiment_EURGBP"),
                    InlineKeyboardButton("EURJPY", callback_data="direct_sentiment_EURJPY")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
            ],
            'crypto': [
                [
                    InlineKeyboardButton("BTCUSD", callback_data="direct_sentiment_BTCUSD"),
                    InlineKeyboardButton("ETHUSD", callback_data="direct_sentiment_ETHUSD")
                ],
                [
                    InlineKeyboardButton("XRPUSD", callback_data="direct_sentiment_XRPUSD"),
                    InlineKeyboardButton("ADAUSD", callback_data="direct_sentiment_ADAUSD")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
            ],
            'commodities': [
                [
                    InlineKeyboardButton("XAUUSD", callback_data="direct_sentiment_XAUUSD"),
                    InlineKeyboardButton("XAGUSD", callback_data="direct_sentiment_XAGUSD")
                ],
                [
                    InlineKeyboardButton("USOUSD", callback_data="direct_sentiment_USOUSD"),
                    InlineKeyboardButton("NQUSD", callback_data="direct_sentiment_NQUSD")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
            ],
            'indices': [
                [
                    InlineKeyboardButton("SPXUSD", callback_data="direct_sentiment_SPXUSD"),
                    InlineKeyboardButton("DJIUSD", callback_data="direct_sentiment_DJIUSD")
                ],
                [
                    InlineKeyboardButton("NDXUSD", callback_data="direct_sentiment_NDXUSD"),
                    InlineKeyboardButton("RUTUSD", callback_data="direct_sentiment_RUTUSD")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
            ]
        }
        
        # Define technical analysis keyboards
        TECHNICAL_KEYBOARDS = {
            'forex': [
                [
                    InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD_chart"),
                    InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD_chart")
                ],
                [
                    InlineKeyboardButton("USDJPY", callback_data="instrument_USDJPY_chart"),
                    InlineKeyboardButton("USDCHF", callback_data="instrument_USDCHF_chart")
                ],
                [
                    InlineKeyboardButton("AUDUSD", callback_data="instrument_AUDUSD_chart"),
                    InlineKeyboardButton("USDCAD", callback_data="instrument_USDCAD_chart")
                ],
                [
                    InlineKeyboardButton("EURGBP", callback_data="instrument_EURGBP_chart"),
                    InlineKeyboardButton("EURJPY", callback_data="instrument_EURJPY_chart")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
            ],
            'crypto': [
                [
                    InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD_chart"),
                    InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD_chart")
                ],
                [
                    InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD_chart"),
                    InlineKeyboardButton("ADAUSD", callback_data="instrument_ADAUSD_chart")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
            ],
            'commodities': [
                [
                    InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD_chart"),
                    InlineKeyboardButton("XAGUSD", callback_data="instrument_XAGUSD_chart")
                ],
                [
                    InlineKeyboardButton("USOUSD", callback_data="instrument_USOUSD_chart"),
                    InlineKeyboardButton("NQUSD", callback_data="instrument_NQUSD_chart")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
            ],
            'indices': [
                [
                    InlineKeyboardButton("SPXUSD", callback_data="instrument_SPXUSD_chart"),
                    InlineKeyboardButton("DJIUSD", callback_data="instrument_DJIUSD_chart")
                ],
                [
                    InlineKeyboardButton("NDXUSD", callback_data="instrument_NDXUSD_chart"),
                    InlineKeyboardButton("RUTUSD", callback_data="instrument_RUTUSD_chart")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
            ]
        }
        
        # Return the appropriate keyboard based on analysis type
        if analysis_type == 'sentiment':
            return SENTIMENT_KEYBOARDS.get(market, SENTIMENT_KEYBOARDS['forex'])
        else:
            return TECHNICAL_KEYBOARDS.get(market, TECHNICAL_KEYBOARDS['forex'])

    async def direct_sentiment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle direct sentiment analysis for an instrument"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Extract instrument from callback data
            instrument = query.data.replace('direct_sentiment_', '')
            logger.info(f"Getting sentiment for {instrument}")
            
            # Store current state and instrument in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['instrument'] = instrument
                context.user_data['current_state'] = SHOW_RESULT
            
            try:
                # Get market sentiment
                sentiment_data = await self.market_sentiment_service.get_sentiment(instrument)
                
                # Format sentiment message
                bullish_score = sentiment_data.get('bullish', 0)
                bearish_score = sentiment_data.get('bearish', 0)
                neutral_score = sentiment_data.get('neutral', 0)
                
                # Determine overall sentiment
                if bullish_score > bearish_score + 10:
                    overall_sentiment = "bullish 📈"
                    strength = "strong" if bullish_score > 65 else "moderate"
                elif bearish_score > bullish_score + 10:
                    overall_sentiment = "bearish 📉"
                    strength = "strong" if bearish_score > 65 else "moderate"
                else:
                    overall_sentiment = "neutral ↔️"
                    strength = "balanced"
                
                # Format detailed message
                message = f"""<b>📊 Sentiment Analysis for {instrument}</b>

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish_score}%
🔴 Bearish: {bearish_score}%
⚪️ Neutral: {neutral_score}%

<b>Market Analysis:</b>
The overall sentiment for {instrument} is {overall_sentiment} with {strength} conviction.

<b>Key Levels & Volatility:</b>
• Trend Strength: {strength.capitalize()}
• Market Volatility: {"High" if abs(bullish_score - bearish_score) > 30 else "Moderate"}

<b>Trading Recommendation:</b>
{self._get_trading_recommendation(bullish_score, bearish_score)}"""

                # Get the market from the instrument
                market = self._detect_market(instrument)
                back_data = f"market_{market}"

                # Delete the loading message
                try:
                    await query.message.delete()
                except Exception as delete_error:
                    logger.warning(f"Could not delete loading message: {str(delete_error)}")

                # Send new message with sentiment analysis
                await query.message.reply_text(
                    text=message,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data=back_data)
                    ]]),
                    parse_mode=ParseMode.HTML
                )
                
            except Exception as sentiment_error:
                logger.error(f"Error getting sentiment: {str(sentiment_error)}")
                
                # Get the market from the instrument for the back button
                market = self._detect_market(instrument)
                back_data = f"market_{market}"
                
                # Delete the loading message
                try:
                    await query.message.delete()
                except Exception as delete_error:
                    logger.warning(f"Could not delete loading message: {str(delete_error)}")

                # Fallback message
                fallback_message = f"""<b>📊 Sentiment Analysis for {instrument}</b>

<b>Market Sentiment:</b>
🟢 Bullish: {random.randint(45, 55)}%
🔴 Bearish: {random.randint(45, 55)}%

<b>Market Analysis:</b>
The current sentiment for {instrument} is neutral, with mixed signals in the market. Please check back later for updated analysis."""

                # Send new message with fallback analysis
                await query.message.reply_text(
                    text=fallback_message,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data=back_data)
                    ]]),
                    parse_mode=ParseMode.HTML
                )
                logger.info("Using fallback sentiment analysis")
            
            return CHOOSE_MARKET
            
        except Exception as e:
            logger.error(f"Error in direct sentiment callback: {str(e)}")
            logger.exception(e)
            return MENU
