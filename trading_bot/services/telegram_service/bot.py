import os
import ssl
import asyncio
import logging
import aiohttp
import json
import time
import random
import traceback
import threading
import re
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import copy

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, InputMediaPhoto, BotCommand, InputMediaAnimation, InputMediaDocument
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    CallbackContext,
    MessageHandler,
    filters,
    PicklePersistence
)
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from telegram.error import TelegramError, BadRequest
import httpx

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
                await send_gif_with_caption(
                    update=update,
                    gif_url=gif_url,
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
                        [InlineKeyboardButton("🔄 Reactivate Subscription", url="https://buy.stripe.com/9AQcPf3j63HL5JS145")]
                    ]
                else:
                    text = """
🚀 Welcome to Sigmapips AI! 🚀

Discover powerful trading signals for various markets.

<b>Start today with a FREE 14-day trial!</b>
                    """
                    keyboard = [
                        [InlineKeyboardButton("🔥 Start 14-day FREE Trial", url="https://buy.stripe.com/3cs3eF9Hu9256NW9AA")]
                    ]
                
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                return {"status": "success", "message": "Trial message sent"}
                
        except Exception as e:
            logger.error(f"Error force-sending main menu: {str(e)}")
            return {"status": "error", "message": str(e)}

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Show help information when the /help command is used."""
        try:
            # Send the help message
            await update.message.reply_text(
                text=HELP_MESSAGE,
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Sent help message to user {update.effective_user.id}")
            return MENU
        except Exception as e:
            logger.error(f"Error showing help: {str(e)}")
            # Try a simpler message if HTML parsing fails
            await update.message.reply_text(
                text="Available commands:\n/menu - Show main menu\n/start - Set up new trading pairs\n/help - Show this help message"
            )
            return MENU
            
    async def set_subscription_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Admin command to set a user's subscription status."""
        # Check if the user is an admin
        user_id = update.effective_user.id
        if user_id not in self.admin_users:
            await update.message.reply_text("This command is only available to administrators.")
            return MENU
            
        try:
            # Expected format: /set_subscription {user_id} {1/0}
            args = context.args if context and hasattr(context, 'args') else []
            
            if len(args) < 2:
                await update.message.reply_text("Usage: /set_subscription {user_id} {1/0}")
                return MENU
                
            target_user_id = int(args[0])
            status = int(args[1]) == 1
            
            # Set the subscription status
            if status:
                # Add subscription
                await self.db.save_subscription(
                    user_id=target_user_id,
                    customer_id=f"admin_set_{int(time.time())}",
                    subscription_id=f"admin_set_{int(time.time())}",
                    status="active",
                    plan_id="admin_set",
                    payment_failed=False
                )
                await update.message.reply_text(f"User {target_user_id} subscription set to active.")
            else:
                # Remove subscription
                await self.db.cancel_subscription(target_user_id)
                await update.message.reply_text(f"User {target_user_id} subscription removed.")
                
            return MENU
        except Exception as e:
            logger.error(f"Error setting subscription: {str(e)}")
            await update.message.reply_text(f"Error: {str(e)}")
            return MENU
            
    async def set_payment_failed_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Admin command to set a user's payment failed status."""
        # Check if the user is an admin
        user_id = update.effective_user.id
        if user_id not in self.admin_users:
            await update.message.reply_text("This command is only available to administrators.")
            return MENU
            
        try:
            # Expected format: /set_payment_failed {user_id} {1/0}
            args = context.args if context and hasattr(context, 'args') else []
            
            if len(args) < 2:
                await update.message.reply_text("Usage: /set_payment_failed {user_id} {1/0}")
                return MENU
                
            target_user_id = int(args[0])
            status = int(args[1]) == 1
            
            # Set the payment failed status
            await self.db.set_payment_failed_status(target_user_id, status)
            await update.message.reply_text(
                f"User {target_user_id} payment failed status set to {status}."
            )
                
            return MENU
        except Exception as e:
            logger.error(f"Error setting payment failed status: {str(e)}")
            await update.message.reply_text(f"Error: {str(e)}")
            return MENU

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle button callback queries."""
        query = update.callback_query
        await query.answer()  # Answer the callback query to stop the loading animation
        
        # Get the callback data
        callback_data = query.data
        logger.info(f"Received callback: {callback_data}")
        
        # Get user_id from update
        user_id = update.effective_user.id
        
        try:
            # Menu navigation callbacks
            if callback_data == CALLBACK_MENU_ANALYSE:
                # Show analysis options
                await query.edit_message_text(
                    text="Choose an analysis type:",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
                return CHOOSE_ANALYSIS
                
            elif callback_data == CALLBACK_MENU_SIGNALS:
                # Check subscription before showing signals options
                is_subscribed = await self.db.is_user_subscribed(user_id)
                payment_failed = await self.db.has_payment_failed(user_id)
                
                if is_subscribed and not payment_failed:
                    # Show signals options
                    await query.edit_message_text(
                        text="Trading Signals Menu:",
                        reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                    )
                    return CHOOSE_SIGNALS
                else:
                    # Show subscription message
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
                    
                    await query.edit_message_text(
                        text=text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    return MENU
            
            # Analysis type callbacks
            elif callback_data == CALLBACK_ANALYSIS_TECHNICAL:
                # Show markets for technical analysis
                await query.edit_message_text(
                    text="Select a market for technical analysis:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
                # Save the analysis type in context
                if context and hasattr(context, 'user_data'):
                    context.user_data['analysis_type'] = 'technical'
                return CHOOSE_MARKET
                
            elif callback_data == CALLBACK_ANALYSIS_SENTIMENT:
                # Show markets for sentiment analysis
                await query.edit_message_text(
                    text="Select a market for sentiment analysis:",
                    reply_markup=InlineKeyboardMarkup(MARKET_SENTIMENT_KEYBOARD)
                )
                # Save the analysis type in context
                if context and hasattr(context, 'user_data'):
                    context.user_data['analysis_type'] = 'sentiment'
                return CHOOSE_MARKET
                
            elif callback_data == CALLBACK_ANALYSIS_CALENDAR:
                # Show markets for calendar analysis
                await query.edit_message_text(
                    text="Select a market for economic calendar analysis:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)  # Use the same market keyboard
                )
                # Save the analysis type in context
                if context and hasattr(context, 'user_data'):
                    context.user_data['analysis_type'] = 'calendar'
                return CHOOSE_MARKET
                
            # Market selection callbacks
            elif callback_data.startswith("market_"):
                # Handle market selection
                parts = callback_data.split("_")
                market_type = parts[1]  # e.g., "forex", "crypto", etc.
                
                # Check if this is a signal-specific market selection
                is_signals = len(parts) > 2 and parts[2] == "signals"
                
                # Save market in context
                if context and hasattr(context, 'user_data'):
                    context.user_data['market'] = market_type
                    if is_signals:
                        context.user_data['in_signals_flow'] = True
                
                # Process market callback
                return await self.market_callback(update, context)
                
            # Back button callbacks
            elif callback_data == "back_analysis":
                # Back to analysis menu
                await query.edit_message_text(
                    text="Choose an analysis type:",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
                return CHOOSE_ANALYSIS
                
            # Generic callback - log the data for debugging
            logger.warning(f"Unhandled callback data: {callback_data}")
            return MENU
            
        except Exception as e:
            logger.error(f"Error in button_callback: {str(e)}")
            logger.exception(e)
            # Try to recover by going back to main menu
            try:
                await query.edit_message_text(
                    text="An error occurred. Returning to main menu...",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
            except Exception:
                pass
            return MENU
            
    async def back_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle back_menu callback to return to the main menu."""
        query = update.callback_query
        await query.answer()
        
        try:
            # Clear any context data for a fresh start
            if context and hasattr(context, 'user_data'):
                # Only clear navigation-related data
                keys_to_clear = ['market', 'instrument', 'analysis_type', 'in_signals_flow']
                for key in keys_to_clear:
                    if key in context.user_data:
                        del context.user_data[key]
            
            # Show the main menu with GIF if possible
            try:
                # Get the menu GIF
                gif_url = await get_menu_gif()
                
                # Create formatted text with GIF
                formatted_text = await embed_gif_in_text(gif_url, WELCOME_MESSAGE)
                
                # Edit the message with GIF and menu
                await query.edit_message_text(
                    text=formatted_text,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
                logger.info("Back to main menu with GIF")
            except Exception as e:
                logger.error(f"Error showing main menu with GIF: {str(e)}")
                # Fallback to text-only menu
                await query.edit_message_text(
                    text=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
                logger.info("Back to main menu with text only")
            
            return MENU
        except Exception as e:
            logger.error(f"Error in back_menu_callback: {str(e)}")
            # Try to recover with simple text
            try:
                await query.edit_message_text(
                    text="Main Menu",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                )
            except Exception:
                pass
            return MENU

    async def market_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle market selection."""
        query = update.callback_query
        await query.answer()
        
        try:
            # Extract market from callback data
            callback_data = query.data
            parts = callback_data.split('_')
            
            # Get market type from parts
            market_type = parts[1] if len(parts) > 1 else 'forex'  # Default to forex
            
            # Get analysis type from context or from callback data
            analysis_type = None
            if context and hasattr(context, 'user_data'):
                analysis_type = context.user_data.get('analysis_type')
            
            # If analysis_type is not in context, check if it's in the callback data
            if not analysis_type and len(parts) > 2:
                analysis_type = parts[2]  # e.g., "sentiment", "calendar", "signals"
            
            # Determine if we're in signals flow
            is_signals_flow = 'signals' in callback_data or (context and hasattr(context, 'user_data') and context.user_data.get('in_signals_flow', False))
            
            # Save to context
            if context and hasattr(context, 'user_data'):
                context.user_data['market'] = market_type
                context.user_data['in_signals_flow'] = is_signals_flow
                if analysis_type:
                    context.user_data['analysis_type'] = analysis_type
            
            # Prepare the keyboard based on market type and analysis type
            logger.info(f"Processing market: {market_type}, analysis: {analysis_type}")
            
            # Choose caption prefix based on analysis type
            analysis_type_name = "Technical Analysis"
            if analysis_type == 'sentiment':
                analysis_type_name = "Market Sentiment"
            elif analysis_type == 'calendar':
                analysis_type_name = "Economic Calendar"
            elif analysis_type == 'signals':
                analysis_type_name = "Trading Signals"
            
            # Get market name for display
            market_name = market_type.capitalize()
            
            # Build caption with analysis and market types
            caption_prefix = f"{market_name} "
            caption = f"{caption_prefix}{analysis_type_name}:"
            logger.info(f"Using caption: {caption}")
            
            # Determine which keyboard to show based on market and analysis type
            if market_type == 'forex':
                if analysis_type == 'sentiment':
                    keyboard = FOREX_SENTIMENT_KEYBOARD
                elif analysis_type == 'calendar':
                    keyboard = FOREX_CALENDAR_KEYBOARD
                elif analysis_type == 'signals':
                    keyboard = FOREX_KEYBOARD_SIGNALS
                else:  # Default to technical analysis
                    keyboard = FOREX_KEYBOARD
            elif market_type == 'crypto':
                if analysis_type == 'sentiment':
                    keyboard = CRYPTO_SENTIMENT_KEYBOARD
                elif analysis_type == 'signals':
                    keyboard = CRYPTO_KEYBOARD_SIGNALS
                else:  # Default to technical analysis
                    keyboard = CRYPTO_KEYBOARD
            elif market_type == 'indices':
                if analysis_type == 'signals':
                    keyboard = INDICES_KEYBOARD_SIGNALS
                else:  # Default to technical analysis
                    keyboard = INDICES_KEYBOARD
            elif market_type == 'commodities':
                if analysis_type == 'signals':
                    keyboard = COMMODITIES_KEYBOARD_SIGNALS
                else:  # Default to technical analysis
                    keyboard = COMMODITIES_KEYBOARD
            else:
                logger.error(f"Unknown market type: {market_type}, falling back to forex")
                keyboard = FOREX_KEYBOARD
                market_type = 'forex'
            
            # Add back button to keyboard if not already present
            if isinstance(keyboard, list) and len(keyboard) > 0:
                has_back_button = False
                for row in keyboard:
                    for btn in row:
                        if hasattr(btn, 'callback_data') and (
                            btn.callback_data == "back_analysis" or 
                            btn.callback_data == "back_signals" or
                            btn.callback_data == "back_market"
                        ):
                            has_back_button = True
                            break
                if not has_back_button:
                    # Add appropriate back button based on flow
                    if is_signals_flow:
                        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_signals")])
                    else:
                        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")])
            
            # Get the analyse GIF URL
            gif_url = await get_analyse_gif()
            
            # Update the message with the GIF and new keyboard
            try:
                # First try updating with embed_gif_in_text
                formatted_text = await embed_gif_in_text(gif_url, caption)
                await query.edit_message_text(
                    text=formatted_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Message updated with {analysis_type_name} for {market_name}")
            except Exception as e:
                logger.warning(f"Could not edit message with GIF: {str(e)}")
                # Fallback to regular text
                await query.edit_message_text(
                    text=caption,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            
            return CHOOSE_INSTRUMENT
        
        except Exception as e:
            logger.error(f"Error in market_callback: {str(e)}")
            logger.exception(e)
            # Try to recover by going back to main menu
            try:
                await query.edit_message_text(
                    text="An error occurred. Returning to main menu...",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
            except Exception:
                pass
            return MENU
            
    async def back_analysis_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle back_analysis callback to return to the analysis menu."""
        query = update.callback_query
        await query.answer()
        
        try:
            # Clear market data
            if context and hasattr(context, 'user_data'):
                if 'market' in context.user_data:
                    del context.user_data['market']
                if 'instrument' in context.user_data:
                    del context.user_data['instrument']
            
            # Show analysis menu
            await query.edit_message_text(
                text="Choose an analysis type:",
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                parse_mode=ParseMode.HTML
            )
            
            return CHOOSE_ANALYSIS
        except Exception as e:
            logger.error(f"Error in back_analysis_callback: {str(e)}")
            # Try simplified recovery
            try:
                await query.edit_message_text(
                    text="Analysis Options",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
            except Exception:
                pass
            return CHOOSE_ANALYSIS
