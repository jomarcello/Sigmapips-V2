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

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, InputMediaPhoto, BotCommand
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
from trading_bot.services.telegram_service.gif_utils import get_welcome_gif, get_menu_gif, get_analyse_gif, get_signals_gif, send_welcome_gif, send_menu_gif, send_analyse_gif, send_signals_gif, send_gif_with_caption, update_message_with_gif, embed_gif_in_text
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

# Forex keyboard voor technical analyse
FOREX_KEYBOARD = [
    [
        InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD_chart"),
        InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD_chart"),
        InlineKeyboardButton("USDJPY", callback_data="instrument_USDJPY_chart")
    ],
    [
        InlineKeyboardButton("AUDUSD", callback_data="instrument_AUDUSD_chart"),
        InlineKeyboardButton("USDCAD", callback_data="instrument_USDCAD_chart"),
        InlineKeyboardButton("EURGBP", callback_data="instrument_EURGBP_chart")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Forex keyboard voor sentiment analyse
FOREX_SENTIMENT_KEYBOARD = [
    [
        InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD_sentiment"),
        InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD_sentiment"),
        InlineKeyboardButton("USDJPY", callback_data="instrument_USDJPY_sentiment")
    ],
    [
        InlineKeyboardButton("AUDUSD", callback_data="instrument_AUDUSD_sentiment"),
        InlineKeyboardButton("USDCAD", callback_data="instrument_USDCAD_sentiment"),
        InlineKeyboardButton("EURGBP", callback_data="instrument_EURGBP_sentiment")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
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
        self.chart = ChartService()  # Chart generation service
        self.calendar = EconomicCalendarService()  # Economic calendar service
        self.sentiment = MarketSentimentService()  # Market sentiment service
        
        # Initialize chart service
        asyncio.create_task(self.chart.initialize())
        
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
        
        # Command handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("menu", self.show_main_menu))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("set_subscription", self.set_subscription_command))
        
        # Register the payment failed command with both underscore and no-underscore versions
        application.add_handler(CommandHandler("set_payment_failed", self.set_payment_failed_command))
        application.add_handler(CommandHandler("setpaymentfailed", self.set_payment_failed_command))
        
        # Add specific handlers for signal analysis flows
        application.add_handler(CallbackQueryHandler(self.analysis_technical_callback, pattern="^analysis_technical$"))
        application.add_handler(CallbackQueryHandler(self.analysis_technical_callback, pattern="^analysis_technical_signal_.*$"))
        
        application.add_handler(CallbackQueryHandler(self.analysis_sentiment_callback, pattern="^analysis_sentiment$"))
        application.add_handler(CallbackQueryHandler(self.analysis_sentiment_callback, pattern="^analysis_sentiment_signal_.*$"))
        
        application.add_handler(CallbackQueryHandler(self.analysis_calendar_callback, pattern="^analysis_calendar$"))
        application.add_handler(CallbackQueryHandler(self.analysis_calendar_callback, pattern="^analysis_calendar_signal_.*$"))
        
        application.add_handler(CallbackQueryHandler(self.back_to_signal_callback, pattern="^back_to_signal$"))
        
        # Callback query handler for all button presses
        application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Ensure signal handlers are registered
        logger.info("Enabling and initializing signals functionality")
        
        # Load any saved signals
        self._load_signals()
        
        logger.info("All handlers registered successfully")

        # Signal flow analysis handlers
        application.add_handler(CallbackQueryHandler(
            self.signal_technical_callback, pattern="^signal_technical$"))
        application.add_handler(CallbackQueryHandler(
            self.signal_sentiment_callback, pattern="^signal_sentiment$"))
        application.add_handler(CallbackQueryHandler(
            self.signal_calendar_callback, pattern="^signal_calendar$"))
        application.add_handler(CallbackQueryHandler(
            self.back_to_signal_analysis_callback, pattern="^back_to_signal_analysis$"))

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
            
            # Enable signals functionality in webhook mode
            logger.info("Initializing signal processing in webhook mode")
            self._load_signals()
            
            return app
            
        except Exception as e:
            logger.error(f"Error setting up webhook: {str(e)}")
            logger.exception(e)
            return app

    async def process_update(self, update_data: dict):
        """Process an update from the Telegram webhook."""
        try:
            # Parse the update
            update = Update.de_json(data=update_data, bot=self.bot)
            logger.info(f"Received Telegram update: {update.update_id}")
            
            # Check if this is a command message
            if update.message and update.message.text and update.message.text.startswith('/'):
                command = update.message.text.split(' ')[0].lower()
                logger.info(f"Received command: {command}")
                
                # Direct command handling with None context (will use self.bot internally)
                try:
                    if command == '/start':
                        await self.start_command(update, None)
                        return
                    elif command == '/menu':
                        await self.show_main_menu(update, None)
                        return
                    elif command == '/help':
                        await self.help_command(update, None)
                        return
                except asyncio.CancelledError:
                    logger.warning(f"Command processing was cancelled for update {update.update_id}")
                    return
                except Exception as cmd_e:
                    logger.error(f"Error handling command {command}: {str(cmd_e)}")
                    logger.exception(cmd_e)
                    # Try to send an error message to the user
                    try:
                        await self.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text="Sorry, there was an error processing your command. Please try again later."
                        )
                    except Exception:
                        pass  # Ignore if we can't send the error message
                    return
            
            # Check if this is a callback query (button press)
            if update.callback_query:
                try:
                    logger.info(f"Received callback query: {update.callback_query.data}")
                    await self.button_callback(update, None)
                    return
                except asyncio.CancelledError:
                    logger.warning(f"Button callback processing was cancelled for update {update.update_id}")
                    return
                except Exception as cb_e:
                    logger.error(f"Error handling callback query {update.callback_query.data}: {str(cb_e)}")
                    logger.exception(cb_e)
                    # Try to notify the user
                    try:
                        await update.callback_query.answer(text="Error processing. Please try again.")
                    except Exception:
                        pass  # Ignore if we can't send the error message
                    return
            
            # Try to process the update with the application if it's initialized
            try:
                # First check if the application is initialized
                if self.application:
                    try:
                        # Process the update with a timeout
                        await asyncio.wait_for(
                            self.application.process_update(update),
                            timeout=45.0  # Increased from 30 to 45 seconds timeout
                        )
                    except asyncio.CancelledError:
                        logger.warning(f"Application processing was cancelled for update {update.update_id}")
                    except RuntimeError as re:
                        if "not initialized" in str(re).lower():
                            logger.warning("Application not initialized, trying to initialize it")
                            try:
                                await self.application.initialize()
                                await self.application.process_update(update)
                            except Exception as init_e:
                                logger.error(f"Failed to initialize application on-the-fly: {str(init_e)}")
                    except asyncio.TimeoutError:
                        logger.warning(f"Update {update.update_id} processing timed out, continuing with next update")
                    except Exception as e:
                        logger.error(f"Error processing update with application: {str(e)}")
                        logger.error(traceback.format_exc())
                else:
                    logger.warning("Application not available to process update")
            except Exception as e:
                logger.error(f"Error in update processing: {str(e)}")
                logger.error(traceback.format_exc())
        except Exception as e:
            logger.error(f"Failed to process update data: {str(e)}")
            logger.error(traceback.format_exc())

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
            
            # Welcome GIF URL
            welcome_gif_url = "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExaWVkdzcxZHMydm8ybnBjYW9rNjd3b2gzeng2b3BhMjA0d3p5dDV1ZSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/gSzIKNrqtotEYrZv7i/giphy.gif"
            
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
        """Handle menu_analyse callback"""
        query = update.callback_query
        await query.answer()  # Respond to prevent loading icon
        
        try:
            # Get an analysis GIF URL
            gif_url = await get_analyse_gif()
            
            # Update the message with the GIF using the helper function
            success = await update_message_with_gif(
                query=query,
                gif_url=gif_url,
                text="Select your analysis type:",
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            )
            
            if not success:
                # If the helper function failed, try a direct approach as fallback
                try:
                    # First try to edit message text
                    await query.edit_message_text(
                        text="Select your analysis type:",
                        reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as text_error:
                    # If that fails due to caption, try editing caption
                    if "There is no text in the message to edit" in str(text_error):
                        await query.edit_message_caption(
                            caption="Select your analysis type:",
                            reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                            parse_mode=ParseMode.HTML
                        )
            
            return CHOOSE_ANALYSIS
        except Exception as e:
            logger.error(f"Error in menu_analyse_callback: {str(e)}")
            
            # If we can't edit the message, try again with a simpler approach as fallback
            try:
                # First try editing the caption
                try:
                    await query.edit_message_caption(
                        caption="Select your analysis type:",
                        reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as caption_error:
                    # If that fails, try editing text
                    await query.edit_message_text(
                        text="Select your analysis type:",
                        reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                return CHOOSE_ANALYSIS
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                
                # Last resort: send a new message
                try:
                    await query.message.reply_text(
                        text="Select your analysis type:",
                        reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                    logger.warning("Fallback to sending new message - ideally this should be avoided")
                except Exception:
                    pass
                    
                return MENU

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
            
            # If we should show the GIF
            if not skip_gif:
                try:
                    # Get the menu GIF URL
                    gif_url = await get_menu_gif()
                    
                    # For message commands we can use reply_animation
                    if hasattr(update, 'message') and update.message:
                        # Send the GIF using regular animation method
                        await update.message.reply_animation(
                            animation=gif_url,
                            caption=WELCOME_MESSAGE,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                    else:
                        # For callback queries or other updates where we don't have a direct message
                        # Use the invisible character trick with HTML
                        text = f'<a href="{gif_url}">&#8205;</a>\n{WELCOME_MESSAGE}'
                        
                        if hasattr(update, 'callback_query') and update.callback_query:
                            # Edit the existing message
                            await update.callback_query.edit_message_text(
                                text=text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup
                            )
                        else:
                            # Final fallback - try to send a new message
                            await update.message.reply_text(
                                text=text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup
                            )
                except Exception as e:
                    logger.error(f"Failed to send menu GIF: {str(e)}")
                    # Fallback to text-only approach
                    await update.message.reply_text(
                        text=WELCOME_MESSAGE,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
            else:
                # Skip GIF mode - just send text
                await update.message.reply_text(
                    text=WELCOME_MESSAGE,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
        else:
            # Handle non-subscribed users similar to start command
            await self.start_command(update, context)
            
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Show help information when /help command is used"""
        await update.message.reply_text(
            text=HELP_MESSAGE,
            parse_mode=ParseMode.HTML
        )

    async def analysis_technical_callback(self, update: Update, context=None) -> int:
        """Handle analysis_technical button press"""
        query = update.callback_query
        await query.answer()
        
        # Check if signal-specific data is present in callback data
        signal_data = None
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
                    logger.error(f"Failed to update caption for technical analysis: {str(e)}")
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
        
        # Set analysis type in context
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'sentiment'
        
        # Check if signal-specific data is present in callback data
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
                reply_markup=InlineKeyboardMarkup(MARKET_SENTIMENT_KEYBOARD)
            )
        except Exception as text_error:
            # If that fails due to caption, try editing caption
            if "There is no text in the message to edit" in str(text_error):
                try:
                    await query.edit_message_caption(
                        caption="Select market for sentiment analysis:",
                        reply_markup=InlineKeyboardMarkup(MARKET_SENTIMENT_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to update caption for sentiment analysis: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text="Select market for sentiment analysis:",
                        reply_markup=InlineKeyboardMarkup(MARKET_SENTIMENT_KEYBOARD),
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
        
        # Set analysis type in context
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'calendar'
        
        # Check if signal-specific data is present in callback data
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
        
        # Show the market selection menu
        try:
            # First try to edit message text
            await query.edit_message_text(
                text="Select market for economic calendar analysis:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
            )
        except Exception as text_error:
            # If that fails due to caption, try editing caption
            if "There is no text in the message to edit" in str(text_error):
                try:
                    await query.edit_message_caption(
                        caption="Select market for economic calendar analysis:",
                        reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to update caption for calendar analysis: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text="Select market for economic calendar analysis:",
                        reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
            else:
                # Re-raise for other errors
                raise
        
        return CHOOSE_MARKET

    async def signal_technical_callback(self, update: Update, context=None) -> int:
        """Handle signal_technical button press"""
        query = update.callback_query
        await query.answer()
        
        # Save analysis type in context
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'technical'
        
        # Get the instrument from context
        instrument = None
        if context and hasattr(context, 'user_data'):
            instrument = context.user_data.get('instrument')
        
        if instrument:
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
        
        # Save analysis type in context
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'calendar'
        
        # Get the instrument from context
        instrument = None
        if context and hasattr(context, 'user_data'):
            instrument = context.user_data.get('instrument')
        
        if instrument:
            # Show calendar analysis for this instrument
            return await self.show_calendar_analysis(update, context, instrument=instrument)
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
                        logger.error(f"Failed to update caption in signal_calendar_callback: {str(e)}")
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

    async def back_to_signal_callback(self, update: Update, context=None) -> int:
        """Handle back_to_signal button press"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get signal data from context
            signal_id = None
            if context and hasattr(context, 'user_data'):
                signal_id = context.user_data.get('current_signal_id')
            
            if not signal_id:
                # No signal ID, return to main menu
                await query.edit_message_text(
                    text="Signal not found. Returning to main menu...",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
                return MENU
            
            # Get the original signal from context or database
            signal = None
            if context and hasattr(context, 'user_data'):
                signal = context.user_data.get('current_signal')
            
            if not signal:
                # Try to get signal from the database or cached signals
                user_id = update.effective_user.id
                if str(user_id) in self.user_signals:
                    signal = self.user_signals[str(user_id)]
            
            if not signal:
                # Still no signal, return to main menu
                await query.edit_message_text(
                    text="Signal details not found. Returning to main menu...",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
                return MENU
            
            # Show the signal again with the analysis options
            signal_text = signal.get('message', 'Signal details not available')
            
            # Format the keyboard for signal analysis
            keyboard = SIGNAL_ANALYSIS_KEYBOARD
            
            # Show the signal with analysis options
            await query.edit_message_text(
                text=signal_text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
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
            return await self.market_signals_callback(update, context)
        
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

    async def back_to_signal_analysis_callback(self, update: Update, context=None) -> int:
        """Handle back_to_signal_analysis to return to the signal analysis menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            logger.info(f"Back to signal analysis for user {update.effective_user.id}")
            
            # Get instrument from context
            instrument = None
            if context and hasattr(context, 'user_data'):
                instrument = context.user_data.get('instrument')
            
            # Format message text
            text = f"Choose analysis type for {instrument}:" if instrument else "Choose analysis type:"
            
            # Show analysis options
            await query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(SIGNAL_ANALYSIS_KEYBOARD)
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
                    ]])
                )
            except Exception:
                pass
            
            return CHOOSE_ANALYSIS

    async def menu_signals_callback(self, update: Update, context=None) -> int:
        """Handle menu_signals callback"""
        query = update.callback_query
        await query.answer()  # Respond to prevent loading icon
        
        try:
            # Get the signals GIF URL
            gif_url = await get_signals_gif()
            
            # Update the message with the GIF using the helper function
            success = await update_message_with_gif(
                query=query,
                gif_url=gif_url,
                text="What would you like to do with trading signals?",
                reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
            )
            
            if not success:
                # If the helper function failed, try a direct approach as fallback
                try:
                    # First try to edit message text
                    await query.edit_message_text(
                        text="What would you like to do with trading signals?",
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                    )
                except Exception as text_error:
                    # If that fails due to caption, try editing caption
                    if "There is no text in the message to edit" in str(text_error):
                        await query.edit_message_caption(
                            caption="What would you like to do with trading signals?",
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                        )
            
            return CHOOSE_SIGNALS
        except Exception as e:
            logger.error(f"Error in menu_signals_callback: {str(e)}")
            
            # If we can't edit the message, try again with a simpler approach as fallback
            try:
                # First try editing the caption
                try:
                    await query.edit_message_caption(
                        caption="What would you like to do with trading signals?",
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                    )
                except Exception as caption_error:
                    # If that fails, try editing text
                    await query.edit_message_text(
                        text="What would you like to do with trading signals?",
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                    )
                return CHOOSE_SIGNALS
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                
                # Last resort: send a new message
                try:
                    await query.message.reply_text(
                        text="What would you like to do with trading signals?",
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                    )
                    logger.warning("Fallback to sending new message - ideally this should be avoided")
                except Exception:
                    pass
                    
                return MENU

    async def signals_add_callback(self, update: Update, context=None) -> int:
        """Handle signals_add callback to add new signal preferences"""
        query = update.callback_query
        await query.answer()  # Respond to prevent loading icon
        
        try:
            # Get a signals GIF URL
            gif_url = await get_signals_gif()
            
            # Update the message with the GIF using the helper function
            success = await update_message_with_gif(
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
                        await query.edit_message_caption(
                            caption="Select a market for trading signals:",
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
                        )
            
            return CHOOSE_MARKET
        except Exception as e:
            logger.error(f"Error in signals_add_callback: {str(e)}")
            
            # If we can't edit the message, try again with a simpler approach as fallback
            try:
                # First try editing the caption
                try:
                    await query.edit_message_caption(
                        caption="Select a market for trading signals:",
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
                    )
                except Exception as caption_error:
                    # If that fails, try editing text
                    await query.edit_message_text(
                        text="Select a market for trading signals:",
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
                    )
                return CHOOSE_MARKET
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                
                # Last resort: send a new message
                try:
                    await query.message.reply_text(
                        text="Select a market for trading signals:",
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
                    )
                    logger.warning("Fallback to sending new message - ideally this should be avoided")
                except Exception:
                    pass
                    
                return MENU

    async def back_menu_callback(self, update: Update, context=None) -> int:
        """Handle back_menu callback to return to the main menu"""
        query = update.callback_query
        await query.answer()  # Respond to prevent loading icon
        
        try:
            # Get the menu GIF URL
            gif_url = await get_menu_gif()
            
            # Update the message with the GIF using the helper function
            success = await update_message_with_gif(
                query=query,
                gif_url=gif_url,
                text=WELCOME_MESSAGE,
                reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
            )
            
            if not success:
                # If the helper function failed, try a direct approach as fallback
                try:
                    # First try to edit message text
                    await query.edit_message_text(
                        text=WELCOME_MESSAGE,
                        reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as text_error:
                    # If that fails due to caption, try editing caption
                    if "There is no text in the message to edit" in str(text_error):
                        await query.edit_message_caption(
                            caption=WELCOME_MESSAGE,
                            reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                            parse_mode=ParseMode.HTML
                        )
            
            return MENU
        except Exception as e:
            logger.error(f"Error in back_menu_callback: {str(e)}")
            
            # If we can't edit the message, try again with a simpler approach as fallback
            try:
                # First try editing the caption
                try:
                    await query.edit_message_caption(
                        caption=WELCOME_MESSAGE,
                        reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as caption_error:
                    # If that fails, try editing text
                    await query.edit_message_text(
                        text=WELCOME_MESSAGE,
                        reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                return MENU
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                
                # Last resort: send a new message
                try:
                    await query.message.reply_text(
                        text=WELCOME_MESSAGE,
                        reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                    logger.warning("Fallback to sending new message - ideally this should be avoided")
                except Exception:
                    pass
                    
                return MENU

    async def market_callback(self, update: Update, context=None) -> int:
        """Handle market_ callback for selecting markets"""
        query = update.callback_query
        await query.answer()
        
        # Extract the market type and check if it's a signal context
        callback_data = query.data
        is_signal_context = callback_data.endswith("_signals")
        is_sentiment_context = callback_data.endswith("_sentiment")
        
        # Set message text based on context
        if is_signal_context:
            message_text = "Select an instrument for signals:"
        elif is_sentiment_context:
            message_text = "Select an instrument for sentiment analysis:"
        else:
            message_text = "Select an instrument for analysis:"
        
        # Determine which market was selected
        if "forex" in callback_data:
            if is_signal_context:
                keyboard = FOREX_KEYBOARD_SIGNALS
            elif is_sentiment_context:
                keyboard = FOREX_SENTIMENT_KEYBOARD
            else:
                keyboard = FOREX_KEYBOARD
        elif "crypto" in callback_data:
            if is_signal_context:
                keyboard = CRYPTO_KEYBOARD_SIGNALS
            elif is_sentiment_context:
                keyboard = CRYPTO_SENTIMENT_KEYBOARD
            else:
                keyboard = CRYPTO_KEYBOARD
        elif "indices" in callback_data:
            if is_signal_context:
                keyboard = INDICES_KEYBOARD_SIGNALS
            else:
                keyboard = INDICES_KEYBOARD
        elif "commodities" in callback_data:
            if is_signal_context:
                keyboard = COMMODITIES_KEYBOARD_SIGNALS
            else:
                keyboard = COMMODITIES_KEYBOARD
        else:
            # Default to forex if market type not recognized
            if is_signal_context:
                keyboard = FOREX_KEYBOARD_SIGNALS
            else:
                keyboard = FOREX_KEYBOARD
        
        # Try to update the message with the appropriate keyboard
        try:
            # First try to edit message text
            await query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        except Exception as text_error:
            # If that fails due to caption, try editing caption
            if "There is no text in the message to edit" in str(text_error):
                try:
                    await query.edit_message_caption(
                        caption=message_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to update caption in market_callback: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text=message_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    logger.warning("Fallback to sending new message in market_callback - ideally this should be avoided")
            else:
                # Re-raise for other errors
                raise
        
        # Save the selected market in the context if available
        if context and hasattr(context, 'user_data'):
            market_type = callback_data.replace("market_", "").replace("_signals", "").replace("_sentiment", "")
            context.user_data['market'] = market_type
            
        return CHOOSE_INSTRUMENT

    async def analysis_callback(self, update: Update, context=None) -> int:
        """Handle back to analysis menu callbacks"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get an analysis GIF URL
            gif_url = await get_analyse_gif()
            
            # Update the message with the GIF using the helper function
            success = await update_message_with_gif(
                query=query,
                gif_url=gif_url,
                text="Select your analysis type:",
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            )
            
            if not success:
                # If the helper function failed, try a direct approach as fallback
                try:
                    # First try to edit message text
                    await query.edit_message_text(
                        text="Select your analysis type:",
                        reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as text_error:
                    # If that fails due to caption, try editing caption
                    if "There is no text in the message to edit" in str(text_error):
                        try:
                            await query.edit_message_caption(
                                caption="Select your analysis type:",
                                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                                parse_mode=ParseMode.HTML
                            )
                        except Exception as e:
                            logger.error(f"Failed to update caption in analysis_callback: {str(e)}")
                            # Try to send a new message as last resort
                            await query.message.reply_text(
                                text="Select your analysis type:",
                                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                                parse_mode=ParseMode.HTML
                            )
                            logger.warning("Fallback to sending new message in analysis_callback")
                    else:
                        # Re-raise for other errors
                        raise
            
            return CHOOSE_ANALYSIS
        except Exception as e:
            logger.error(f"Error in analysis_callback: {str(e)}")
            
            # If we can't edit the message, try again with a simpler approach as fallback
            try:
                # First try editing the caption
                try:
                    await query.edit_message_caption(
                        caption="Select your analysis type:",
                        reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as caption_error:
                    # If that fails, try editing text
                    await query.edit_message_text(
                        text="Select your analysis type:",
                        reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                return CHOOSE_ANALYSIS
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                
                # Last resort: send a new message
                try:
                    await query.message.reply_text(
                        text="Select your analysis type:",
                        reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                    logger.warning("Fallback to sending new message - ideally this should be avoided")
                except Exception:
                    pass
                    
                return MENU

    async def back_market_callback(self, update: Update, context=None) -> int:
        """Handle back_market button to return to market selection"""
        query = update.callback_query
        await query.answer()
        
        # Check if we're in a signal context by looking in the context
        is_signals_context = False
        analysis_type = None
        
        if context and hasattr(context, 'user_data'):
            analysis_type = context.user_data.get('analysis_type')
            is_signals_context = context.user_data.get('is_signals_context', False)
        
        # Determine which keyboard to show based on context
        if is_signals_context:
            keyboard = MARKET_KEYBOARD_SIGNALS
            message_text = "Select a market for trading signals:"
        elif analysis_type == 'sentiment':
            keyboard = MARKET_SENTIMENT_KEYBOARD
            message_text = "Select market for sentiment analysis:"
        elif analysis_type == 'calendar':
            keyboard = MARKET_KEYBOARD  # Use general market keyboard
            message_text = "Select market for economic calendar analysis:"
        else:
            # Default to technical analysis
            keyboard = MARKET_KEYBOARD
            message_text = "Select market for technical analysis:"
        
        try:
            # First try to edit message text
            await query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        except Exception as text_error:
            # If that fails due to caption, try editing caption
            if "There is no text in the message to edit" in str(text_error):
                try:
                    await query.edit_message_caption(
                        caption=message_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to update caption in back_market_callback: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text=message_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    logger.warning("Fallback to sending new message in back_market_callback")
            else:
                # Re-raise for other errors
                raise
                
        return CHOOSE_MARKET

    async def back_instrument_callback(self, update: Update, context=None) -> int:
        """Handle back_instrument button to return to instrument selection"""
        query = update.callback_query
        await query.answer()
        
        # Check context for market and analysis type
        market = None
        analysis_type = None
        is_signals_context = False
        
        if context and hasattr(context, 'user_data'):
            market = context.user_data.get('market')
            analysis_type = context.user_data.get('analysis_type')
            is_signals_context = context.user_data.get('is_signals_context', False)
        
        # Default to forex if no market is found
        if not market:
            market = "forex"
        
        # Set the message text
        if is_signals_context:
            message_text = f"Select an instrument from {market} for signals:"
        else:
            message_text = f"Select an instrument from {market} for analysis:"
        
        # Determine which keyboard to use based on market and context
        keyboard = None
        
        if market == "forex":
            if is_signals_context:
                keyboard = FOREX_KEYBOARD_SIGNALS
            elif analysis_type == 'sentiment':
                keyboard = FOREX_SENTIMENT_KEYBOARD
            else:
                keyboard = FOREX_KEYBOARD
        elif market == "crypto":
            if is_signals_context:
                keyboard = CRYPTO_KEYBOARD_SIGNALS
            elif analysis_type == 'sentiment':
                keyboard = CRYPTO_SENTIMENT_KEYBOARD
            else:
                keyboard = CRYPTO_KEYBOARD
        elif market == "indices":
            if is_signals_context:
                keyboard = INDICES_KEYBOARD_SIGNALS
            else:
                keyboard = INDICES_KEYBOARD
        elif market == "commodities":
            if is_signals_context:
                keyboard = COMMODITIES_KEYBOARD_SIGNALS
            else:
                keyboard = COMMODITIES_KEYBOARD
        else:
            # Default to forex
            if is_signals_context:
                keyboard = FOREX_KEYBOARD_SIGNALS
            else:
                keyboard = FOREX_KEYBOARD
        
        try:
            # First try to edit message text
            await query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        except Exception as text_error:
            # If that fails due to caption, try editing caption
            if "There is no text in the message to edit" in str(text_error):
                try:
                    await query.edit_message_caption(
                        caption=message_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to update caption in back_instrument_callback: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text=message_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    logger.warning("Fallback to sending new message in back_instrument_callback")
            else:
                # Re-raise for other errors
                raise
                
        return CHOOSE_INSTRUMENT

    async def instrument_callback(self, update: Update, context=None) -> int:
        """Handle instrument selection for analyses"""
        query = update.callback_query
        await query.answer()
        
        # Extract instrument and type from callback data
        callback_data = query.data
        parts = callback_data.split("_")
        
        # Determine the type of analysis
        analysis_type = None
        if "_chart" in callback_data:
            analysis_type = "technical"
        elif "_sentiment" in callback_data:
            analysis_type = "sentiment"
        elif "_calendar" in callback_data:
            analysis_type = "calendar"
        else:
            # Default to technical analysis
            analysis_type = "technical"
            
        # Extract instrument name (could be between instrument_ and _type)
        instrument = None
        if len(parts) >= 3:
            # For format like "instrument_BTCUSD_chart"
            instrument = parts[1]
        elif len(parts) == 2:
            # For simple format like "instrument_BTCUSD"
            instrument = parts[1]
            
        # Save instrument and analysis type to context
        if context and hasattr(context, 'user_data'):
            context.user_data['instrument'] = instrument
            context.user_data['analysis_type'] = analysis_type
            
        # Log the detected instrument and analysis type
        logger.info(f"Selected instrument: {instrument}, analysis type: {analysis_type}")
        
        # Redirect to the appropriate analysis function
        if analysis_type == "technical":
            return await self.show_technical_analysis(update, context, instrument=instrument)
        elif analysis_type == "sentiment":
            return await self.show_sentiment_analysis(update, context, instrument=instrument)
        elif analysis_type == "calendar":
            return await self.show_calendar_analysis(update, context, instrument=instrument)
        else:
            # Default to technical analysis
            return await self.show_technical_analysis(update, context, instrument=instrument)

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
        success = await update_message_with_gif(
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

    async def instrument_signals_callback(self, update: Update, context=None) -> int:
        """Handle instrument selection for signals"""
        query = update.callback_query
        await query.answer()
        
        # Extract instrument from callback data
        callback_data = query.data
        parts = callback_data.split("_")
        
        # Get instrument name from the parts
        instrument = None
        if len(parts) >= 3:
            # Format like "instrument_EURUSD_signals"
            instrument = parts[1]
        
        # Save in context
        if context and hasattr(context, 'user_data'):
            context.user_data['instrument'] = instrument
            context.user_data['is_signals_context'] = True
        
        # Log the selection
        logger.info(f"Selected instrument for signals: {instrument}")
        
        # Get the allowed timeframes for this instrument
        allowed_timeframe = INSTRUMENT_TIMEFRAME_MAP.get(instrument, "H1")
        
        # Show the styles menu with appropriate timeframes
        styles_text = f"Select trading style for {instrument}:"
        
        try:
            # First try to edit message text
            await query.edit_message_text(
                text=styles_text,
                reply_markup=InlineKeyboardMarkup(STYLE_KEYBOARD),
                parse_mode=ParseMode.HTML
            )
        except Exception as text_error:
            # If that fails due to caption, try editing caption
            if "There is no text in the message to edit" in str(text_error):
                try:
                    await query.edit_message_caption(
                        caption=styles_text,
                        reply_markup=InlineKeyboardMarkup(STYLE_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to update caption in instrument_signals_callback: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text=styles_text,
                        reply_markup=InlineKeyboardMarkup(STYLE_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
            else:
                # Re-raise for other errors
                raise
                
        return CHOOSE_STYLE

    async def analyze_from_signal_callback(self, update: Update, context=None) -> int:
        """Handle analyze_from_signal_[instrument] callback to show analysis menu for a signal"""
        query = update.callback_query
        await query.answer()
        
        # Extract instrument from callback data
        callback_data = query.data
        parts = callback_data.split("_")
        
        # Expected format is "analyze_from_signal_[instrument]"
        instrument = None
        if len(parts) >= 4:
            instrument = parts[3]  # Get the instrument from the callback data
        
        # Save instrument in context
        if context and hasattr(context, 'user_data'):
            context.user_data['instrument'] = instrument
            
        logger.info(f"Analyze from signal for instrument: {instrument}")
        
        # Define the signal analysis keyboard
        # This is typically a keyboard with options for Technical, Sentiment, and Calendar analysis
        keyboard = [
            [
                InlineKeyboardButton("📈 Technical Analysis", callback_data="signal_technical"),
                InlineKeyboardButton("🧠 Sentiment Analysis", callback_data="signal_sentiment")
            ],
            [
                InlineKeyboardButton("📅 Economic Calendar", callback_data="signal_calendar"),
                InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")
            ]
        ]
        
        # Set the message text
        text = f"Choose analysis type for {instrument}:" if instrument else "Choose analysis type:"
        
        try:
            # First try to edit message text
            await query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        except Exception as text_error:
            # If that fails due to caption, try editing caption
            if "There is no text in the message to edit" in str(text_error):
                try:
                    await query.edit_message_caption(
                        caption=text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to update caption in analyze_from_signal_callback: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text=text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
            else:
                # Re-raise for other errors
                raise
                
        return CHOOSE_ANALYSIS
