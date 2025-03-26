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

# Conversation states
MAIN_MENU, ANALYZE_MENU, SIGNALS_MENU, MARKET_CHOICE, INSTRUMENT_CHOICE, TIMEFRAME_CHOICE = range(6)
ANALYSIS_CHOICE, SIGNAL_DETAILS, CHOOSE_ANALYSIS, MANAGE_PREFERENCES = range(6, 10)
DELETE_PREFERENCES, CONFIRM_DELETE = range(10, 12)

# Messages
WELCOME_MESSAGE = """
🚀 <b>Welcome to SigmaPips Trading Bot!</b> 🚀

I'm your AI-powered trading assistant, designed to help you make better trading decisions.

📊 <b>My Services:</b>
• <b>Technical Analysis</b> - Get real-time chart analysis and key levels

• <b>Market Sentiment</b> - Understand market sentiment and trends

• <b>Economic Calendar</b> - Stay updated on market-moving events

• <b>Trading Signals</b> - Receive precise entry/exit points for your favorite pairs

Select an option below to get started:
"""

# Abonnementsbericht voor nieuwe gebruikers
SUBSCRIPTION_WELCOME_MESSAGE = """
🚀 <b>Welcome to SigmaPips Trading Bot!</b> 🚀

To access all features, you need a subscription:

📊 <b>Trading Signals Subscription - $29.99/month</b>
• Access to all trading signals (Forex, Crypto, Commodities, Indices)
• Advanced timeframe analysis (1m, 15m, 1h, 4h)
• Detailed chart analysis for each signal

Click the button below to subscribe:
"""

MENU_MESSAGE = """
Welcome to SigmaPips Trading Bot!

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
            return MAIN_MENU
    
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

# Conversation states
MAIN_MENU, ANALYZE_MENU, SIGNALS_MENU, MARKET_CHOICE, INSTRUMENT_CHOICE, TIMEFRAME_CHOICE = range(6)
ANALYSIS_CHOICE, SIGNAL_DETAILS, CHOOSE_ANALYSIS, MANAGE_PREFERENCES = range(6, 10)
DELETE_PREFERENCES, CONFIRM_DELETE = range(10, 12)

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
                    return [1234567890]  # Default test user ID
        except Exception as e:
            logger.error(f"Error getting subscribers: {str(e)}")
            return []

    @property
    def signals_enabled(self):
        """Property to check if signal processing is enabled"""
        return self._signals_enabled
    
    @signals_enabled.setter
    def signals_enabled(self, value):
        """Setter for signals_enabled property"""
        self._signals_enabled = bool(value)
        logger.info(f"Signal processing {'enabled' if value else 'disabled'}")

    def _register_handlers(self, application: Application):
        try:
            # Register all command handlers first
            application.add_handler(CommandHandler("start", self.start_command))
            application.add_handler(CommandHandler("help", self.help_command))
            application.add_handler(CommandHandler("menu", self.show_main_menu))
            application.add_handler(CommandHandler("set_subscription", self.set_subscription_command))
            application.add_handler(CommandHandler("signals", self.signals_command))
            application.add_handler(CommandHandler("analyze", self.analyze_command))
            application.add_handler(CommandHandler("settings", self.settings_command))
            application.add_handler(CommandHandler("cancel", self.cancel_command))
            
            # Admin commands
            application.add_handler(CommandHandler("broadcast", self.broadcast_command))
            application.add_handler(CommandHandler("list_users", self.list_users_command))
            application.add_handler(CommandHandler("get_user", self.get_user_command))
            application.add_handler(CommandHandler("delete_user", self.delete_user_command))
            application.add_handler(CommandHandler("update_user", self.update_user_command))
            application.add_handler(CommandHandler("add_user", self.add_user_command))
            application.add_handler(CommandHandler("enable_signals", self.enable_signals_command))
            application.add_handler(CommandHandler("disable_signals", self.disable_signals_command))
            
            # Register error handler
            application.add_error_handler(self.error_handler)
            
            # Register callback query handler last
            application.add_handler(CallbackQueryHandler(self.button_callback))
            
            logger.info("All handlers registered successfully")
        except Exception as e:
            logger.error(f"Error registering handlers: {str(e)}")
            raise

    async def button_callback(self, update: Update, context=None) -> int:
        """Handle button presses from inline keyboards"""
        query = update.callback_query
        logger.info(f"Button callback called with data: {query.data}")
        
        try:
            # Answer the callback query
            await query.answer()
            
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
            elif query.data == "analysis_sentiment":
                return await self.analysis_sentiment_callback(update, context)
            elif query.data == "analysis_calendar":
                return await self.analysis_calendar_callback(update, context)
                
            # Menu navigation
            if query.data == CALLBACK_MENU_ANALYSE:
                return await self.menu_analyse_callback(update, context)
            elif query.data == CALLBACK_MENU_SIGNALS:
                return await self.menu_signals_callback(update, context)
            elif query.data == CALLBACK_BACK_MENU:
                return await self.show_main_menu(update, context)
                
            # Market selection
            if query.data.startswith("market_"):
                return await self.market_callback(update, context)
                
            # Signal management
            if query.data == "signals_add":
                return await self.signals_add_callback(update, context)
            elif query.data == "signals_manage":
                return await self.signals_manage_callback(update, context)
            elif query.data == "delete_prefs":
                return await self.delete_preferences_callback(update, context)
            elif query.data.startswith("delete_pref_"):
                return await self.delete_single_preference_callback(update, context)
                
            # Back navigation
            if query.data == "back_signals":
                return await self.market_signals_callback(update, context)
            elif query.data == "back_to_signal":
                return await self.back_to_signal_callback(update, context)
                
            # Log unhandled callbacks
            logger.warning(f"Unhandled callback data: {query.data}")
            
            # Default: return to main menu
            try:
                await query.edit_message_text(
                    text="Command not recognized. Returning to main menu.",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
            except Exception as e:
                logger.error(f"Error showing default menu: {str(e)}")
                
            return MAIN_MENU
            
        except Exception as e:
            logger.error(f"Error in button_callback: {str(e)}")
            logger.exception(e)
            
            try:
                await query.edit_message_text(
                    text="An error occurred. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]])
                )
            except Exception:
                pass
                
            return MAIN_MENU

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
            # Show the normal welcome message with all features
            await self.show_main_menu(update, context)
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
            welcome_text = f"""
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
            checkout_url = "https://buy.stripe.com/3cs3eF9Hu9256NW9AA"
            
            # Create buttons - Trial button goes straight to Stripe checkout
            keyboard = [
                [InlineKeyboardButton("🔥 Start 14-day FREE Trial", url=checkout_url)]
            ]
            
            await update.message.reply_text(
                text=welcome_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Show the main menu with analysis and signals options."""
        try:
            # Get user ID
            user_id = update.effective_user.id
            
            # Check if user has an active subscription
            is_subscribed = await self.db.is_user_subscribed(user_id)
            
            # Check if payment has failed
            payment_failed = await self.db.has_payment_failed(user_id)
            
            if is_subscribed and not payment_failed:
                # Show the normal welcome message with all features
                message_text = WELCOME_MESSAGE
                keyboard = START_KEYBOARD
            elif payment_failed:
                # Show payment failure message
                message_text = """
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
                # Show the welcome message with trial option
                message_text = """
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
                
                # Use direct URL link for trial
                checkout_url = "https://buy.stripe.com/3cs3eF9Hu9256NW9AA"
                
                # Create button for trial
                keyboard = [
                    [InlineKeyboardButton("🔥 Start 14-day FREE Trial", url=checkout_url)]
                ]
            
            # Handle both message and callback query updates
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    text=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    text=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            
            return MAIN_MENU
            
        except Exception as e:
            logger.error(f"Error showing main menu: {str(e)}")
            logger.exception(e)
            
            # Try to send a fallback message
            try:
                if update.callback_query:
                    await update.callback_query.message.reply_text(
                        text="An error occurred. Please try /start to begin again.",
                        reply_markup=None
                    )
                else:
                    await update.message.reply_text(
                        text="An error occurred. Please try /start to begin again.",
                        reply_markup=None
                    )
            except Exception:
                pass
            
            return ConversationHandler.END

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
        
        try:
            # Show the analysis menu
            await query.edit_message_text(
                text="Select your analysis type:",
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            )
            
            return CHOOSE_ANALYSIS
        except Exception as e:
            logger.error(f"Error in menu_analyse_callback: {str(e)}")
            try:
                await query.message.reply_text(
                    text="Select your analysis type:",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
                return CHOOSE_ANALYSIS
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                return MENU

    async def menu_signals_callback(self, update: Update, context=None) -> int:
        """Handle menu_signals callback"""
        query = update.callback_query
        
        # Show the signals menu
        await query.edit_message_text(
            text="What would you like to do with trading signals?",
            reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
        )
        
        return CHOOSE_SIGNALS

    async def analysis_callback(self, update: Update, context=None) -> int:
        """Handle analysis callback"""
        query = update.callback_query
        
        # Toon het analyse menu
        try:
            await query.edit_message_text(
                text="Select your analysis type:",
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            )
            return CHOOSE_ANALYSIS
        except Exception as e:
            logger.error(f"Error in analysis_callback: {str(e)}")
            try:
                await query.message.reply_text(
                    text="Select your analysis type:",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
                return CHOOSE_ANALYSIS
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                return MENU

    async def signals_callback(self, update: Update, context=None) -> int:
        """Handle signals callback"""
        query = update.callback_query
        
        # Toon het signals menu
        await query.edit_message_text(
            text="What would you like to do with trading signals?",
            reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
        )
        
        return CHOOSE_SIGNALS

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Send a help message when the /help command is issued."""
        try:
            # Send help message
            await update.message.reply_text(
                text=HELP_MESSAGE,
                parse_mode=ParseMode.HTML
            )
            return MAIN_MENU
        except Exception as e:
            logger.error(f"Error in help command: {str(e)}")
            await update.message.reply_text(
                text="An error occurred. Please try /start to begin again."
            )
            return ConversationHandler.END

    async def analysis_technical_callback(self, update: Update, context=None) -> int:
        """Handle technical analysis selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Debug logging
            logger.info("analysis_technical_callback aangeroepen")
            
            # Extract instrument if this came from a signal
            is_from_signal = False
            instrument = None
            
            if query.data.startswith("analysis_technical_signal_"):
                is_from_signal = True
                instrument = query.data.replace("analysis_technical_signal_", "")
                logger.info(f"Technical analysis for instrument {instrument} from signal")
            
            # Store analysis type in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'technical'
                
                # Set from_signal if this came via signal flow
                if is_from_signal:
                    context.user_data['from_signal'] = True
                    context.user_data['previous_state'] = 'SIGNAL'
                    if instrument:
                        context.user_data['instrument'] = instrument
                
                # Check if we have an instrument from signal
                if (context.user_data.get('from_signal') or context.user_data.get('previous_state') == 'SIGNAL') and (instrument or context.user_data.get('instrument')):
                    instrument = instrument or context.user_data.get('instrument')
                    logger.info(f"Using instrument from signal: {instrument} for technical analysis")
                    
                    # Go directly to technical analysis for this instrument
                    return await self.show_technical_analysis(update, context, instrument=instrument)
            
            # If not coming from signal, show normal market selection
            await query.edit_message_text(
                text="Select a market for technical analysis:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
            )
            
            return CHOOSE_MARKET
        except Exception as e:
            logger.error(f"Error in analysis_technical_callback: {str(e)}")
            logger.exception(e)
            return MENU
    
    async def analysis_sentiment_callback(self, update: Update, context=None) -> int:
        """Handle sentiment analysis selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Debug logging
            logger.info("analysis_sentiment_callback aangeroepen")
            
            # Extract instrument if this came from a signal
            is_from_signal = False
            instrument = None
            
            if query.data.startswith("analysis_sentiment_signal_"):
                is_from_signal = True
                instrument = query.data.replace("analysis_sentiment_signal_", "")
                logger.info(f"Sentiment analysis for instrument {instrument} from signal")
            
            # Store analysis type in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'sentiment'
                
                # Set from_signal if this came via signal flow
                if is_from_signal:
                    context.user_data['from_signal'] = True
                    context.user_data['previous_state'] = 'SIGNAL'
                    if instrument:
                        context.user_data['instrument'] = instrument
                
                # Check if we have an instrument from signal
                if (context.user_data.get('from_signal') or context.user_data.get('previous_state') == 'SIGNAL') and (instrument or context.user_data.get('instrument')):
                    instrument = instrument or context.user_data.get('instrument')
                    logger.info(f"Using instrument from signal: {instrument} for sentiment analysis")
                    
                    # Go directly to sentiment analysis for this instrument
                    return await self.show_sentiment_analysis(update, context, instrument=instrument)
            
            # If not coming from signal, show normal market selection
            await query.edit_message_text(
                text="Select a market for sentiment analysis:",
                reply_markup=InlineKeyboardMarkup(MARKET_SENTIMENT_KEYBOARD)
            )
            
            return CHOOSE_MARKET
        except Exception as e:
            logger.error(f"Error in analysis_sentiment_callback: {str(e)}")
            logger.exception(e)
            return MENU
    
    async def analysis_calendar_callback(self, update: Update, context=None) -> int:
        """Handle economic calendar selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Debug logging
            logger.info("analysis_calendar_callback aangeroepen")
            
            # Extract instrument if this came from a signal
            is_from_signal = False
            instrument = None
            
            if query.data.startswith("analysis_calendar_signal_"):
                is_from_signal = True
                instrument = query.data.replace("analysis_calendar_signal_", "")
                logger.info(f"Calendar analysis for instrument {instrument} from signal")
            
            # Store analysis type in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'calendar'
                
                # Set from_signal if this came via signal flow
                if is_from_signal:
                    context.user_data['from_signal'] = True
                    context.user_data['previous_state'] = 'SIGNAL'
                    if instrument:
                        context.user_data['instrument'] = instrument
                
                # Check if we have an instrument from signal
                if (context.user_data.get('from_signal') or context.user_data.get('previous_state') == 'SIGNAL') and (instrument or context.user_data.get('instrument')):
                    instrument = instrument or context.user_data.get('instrument')
                    logger.info(f"Using instrument from signal: {instrument} for economic calendar")
                    
                    # Go directly to economic calendar for this instrument
                    return await self.show_economic_calendar(update, context, instrument=instrument)
            
            # If not coming from signal, show normal market selection
            await query.edit_message_text(
                text="Select a market for economic calendar:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
            )
            
            return CHOOSE_MARKET
        except Exception as e:
            logger.error(f"Error in analysis_calendar_callback: {str(e)}")
            logger.exception(e)
            return MENU

    async def calendar_back_callback(self, update: Update, context=None) -> int:
        """Handle back from calendar"""
        query = update.callback_query
        
        try:
            # Show the analysis menu
            await query.edit_message_text(
                text="Select your analysis type:",
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            )
            
            return CHOOSE_ANALYSIS
        except Exception as e:
            logger.error(f"Error in calendar_back_callback: {str(e)}")
            try:
                await query.message.reply_text(
                    text="Select your analysis type:",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
                return CHOOSE_ANALYSIS
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                return MENU

    async def signals_add_callback(self, update: Update, context=None) -> int:
        """Handle signals_add callback"""
        query = update.callback_query
        
        try:
            # Markeer dat we in de signals flow zitten
            if context and hasattr(context, 'user_data'):
                context.user_data['in_signals_flow'] = True
            
            # Toon het market keyboard voor signals
            await query.edit_message_text(
                text="Select a market for trading signals:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
            )
            
            return CHOOSE_MARKET
        except Exception as e:
            logger.error(f"Error in signals_add_callback: {str(e)}")
            return MENU

    async def signals_manage_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle signals_manage callback"""
        query = update.callback_query
        await query.answer()
        
        # Get preferences from database
        user_id = update.effective_user.id
        
        try:
            preferences = await self.db.get_user_preferences(user_id)
            
            if not preferences or len(preferences) == 0:
                await query.edit_message_text(
                    text="You haven't set any preferences yet.\n\nUse 'Add New Pairs' to set up your first trading pair.",
                    reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                )
                return CHOOSE_SIGNALS
            
            # Format preferences text
            prefs_text = "Your current preferences:\n\n"
            for i, pref in enumerate(preferences, 1):
                prefs_text += f"{i}. {pref['market']} - {pref['instrument']}\n"
                prefs_text += f"   Style: {pref['style']}, Timeframe: {pref['timeframe']}\n\n"
            
            keyboard = [
                [InlineKeyboardButton("➕ Add More", callback_data="signals_add")],
                [InlineKeyboardButton("🗑 Delete Preferences", callback_data="delete_prefs")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
            ]
            
            await query.edit_message_text(
                text=prefs_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logger.error(f"Error getting preferences: {str(e)}")
            await query.edit_message_text(
                text="An error occurred while retrieving your preferences. Please try again later.",
                reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
            )
        
        return CHOOSE_SIGNALS

    async def delete_preferences_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle delete_prefs callback"""
        query = update.callback_query
        await query.answer()
        
        # Get user ID
        user_id = update.effective_user.id
        
        try:
            # Get user preferences
            preferences = await self.db.get_user_preferences(user_id)
            
            if not preferences or len(preferences) == 0:
                await query.edit_message_text(
                    text="You don't have any preferences to delete.",
                    reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                )
                return CHOOSE_SIGNALS
            
            # Create keyboard with preferences to delete
            keyboard = []
            
            # Maak een tijdelijke opslag voor preference IDs als er geen context is
            if not hasattr(self, 'temp_pref_ids'):
                self.temp_pref_ids = {}
            
            self.temp_pref_ids[user_id] = {}
            
            for i, pref in enumerate(preferences):
                # Store preference ID for later use
                pref_key = f"pref_{i}"
                
                if context and hasattr(context, 'user_data'):
                    context.user_data[pref_key] = pref['id']
                else:
                    # Sla op in tijdelijke opslag
                    self.temp_pref_ids[user_id][pref_key] = pref['id']
                
                # Create button with preference info
                button_text = f"{pref['market']} - {pref['instrument']} ({pref['timeframe']})"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_pref_{i}")])
            
            # Add back button
            keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="signals_manage")])
            
            await query.edit_message_text(
                text="Select a preference to delete:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return CHOOSE_SIGNALS
            
        except Exception as e:
            logger.error(f"Error in delete preferences: {str(e)}")
            await query.edit_message_text(
                text="An error occurred. Please try again later.",
                reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
            )
            return CHOOSE_SIGNALS

    async def delete_single_preference_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle delete_pref_X callback"""
        query = update.callback_query
        await query.answer()
        
        # Get user ID
        user_id = update.effective_user.id
        
        # Get preference index from callback data
        pref_index = int(query.data.split('_')[-1])
        pref_key = f"pref_{pref_index}"
        
        # Get preference ID from context or temp storage
        pref_id = None
        if context and hasattr(context, 'user_data'):
            pref_id = context.user_data.get(pref_key)
        elif hasattr(self, 'temp_pref_ids') and user_id in self.temp_pref_ids:
            pref_id = self.temp_pref_ids[user_id].get(pref_key)
        
        if not pref_id:
            await query.edit_message_text(
                text="Error: Could not find the selected preference.",
                reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
            )
            return CHOOSE_SIGNALS
        
        try:
            # Delete the preference
            success = await self.db.delete_preference_by_id(pref_id)
            
            if success:
                await query.edit_message_text(
                    text="✅ The selected preference has been deleted successfully.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⚙️ Manage More Preferences", callback_data="signals_manage")],
                        [InlineKeyboardButton("🏠 Back to Start", callback_data="back_menu")]
                    ])
                )
            else:
                await query.edit_message_text(
                    text="❌ Failed to delete the preference. Please try again.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⚙️ Back to Preferences", callback_data="signals_manage")]
                    ])
                )
            
            return CHOOSE_SIGNALS
            
        except Exception as e:
            logger.error(f"Error deleting preference: {str(e)}")
            await query.edit_message_text(
                text="An error occurred while deleting the preference. Please try again later.",
                reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
            )
            return CHOOSE_SIGNALS

    async def confirm_delete_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle confirm_delete callback"""
        query = update.callback_query
        await query.answer()
        
        # Get user ID
        user_id = update.effective_user.id
        
        try:
            # Delete all preferences
            await self.db.delete_all_preferences(user_id)
            
            # Show success message
            await query.edit_message_text(
                text="✅ All your preferences have been deleted successfully.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Add New Pairs", callback_data="signals_add")],
                    [InlineKeyboardButton("🏠 Back to Start", callback_data="back_menu")]
                ])
            )
            
            return CHOOSE_SIGNALS
            
        except Exception as e:
            logger.error(f"Error deleting preferences: {str(e)}")
            await query.edit_message_text(
                text="An error occurred while deleting your preferences. Please try again later.",
                reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
            )
            return CHOOSE_SIGNALS

    async def market_callback(self, update: Update, context=None) -> int:
        """Handle market selection for analysis"""
        query = update.callback_query
        callback_data = query.data
        
        # Check if this is a signals market selection
        if '_signals' in callback_data:
            market = callback_data.replace('market_', '').replace('_signals', '')
            
            try:
                # Store in user_data for future use
                if context and hasattr(context, 'user_data'):
                    context.user_data['market'] = market
                    context.user_data['in_signals_flow'] = True
                    logger.info(f"Stored in context for signals: market={market}")
                
                # Choose appropriate keyboard based on market
                keyboard = None
                message_text = f"Select a {market} instrument for trading signals:"
                
                if market == 'forex':
                    keyboard = FOREX_KEYBOARD_SIGNALS
                elif market == 'crypto':
                    keyboard = CRYPTO_KEYBOARD_SIGNALS
                elif market == 'indices':
                    keyboard = INDICES_KEYBOARD_SIGNALS
                elif market == 'commodities':
                    keyboard = COMMODITIES_KEYBOARD_SIGNALS
                else:
                    # Unknown market, show an error
                    await query.edit_message_text(
                        text=f"Unknown market: {market}",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Back", callback_data="back_signals")
                        ]])
                    )
                    return MENU
                
                # Show the keyboard
                await query.edit_message_text(
                    text=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                return CHOOSE_INSTRUMENT
            except Exception as e:
                logger.error(f"Error in market_callback for signals: {str(e)}")
                logger.exception(e)
                return MENU
        
        # Extract market and check if this is from sentiment menu
        if '_sentiment' in callback_data:
            market = callback_data.replace('market_', '').replace('_sentiment', '')
            analysis_type = 'sentiment'
        else:
            market = callback_data.replace('market_', '')
            # Determine analysis type from context or default to technical
            analysis_type = 'technical'  # Default
            if context and hasattr(context, 'user_data') and 'analysis_type' in context.user_data:
                analysis_type = context.user_data['analysis_type']
        
        try:
            # Answer the callback query
            await query.answer()
            
            # Log the market and analysis type
            logger.info(f"Market callback: market={market}, analysis_type={analysis_type}, callback_data={callback_data}")
            
            # Store in user_data for future use
            if context and hasattr(context, 'user_data'):
                context.user_data['market'] = market
                context.user_data['analysis_type'] = analysis_type
                logger.info(f"Stored in context: market={market}, analysis_type={analysis_type}")
            
            # Choose the keyboard based on market and analysis type
            keyboard = None
            message_text = f"Select a {market} pair for "
            
            if market == 'forex':
                if analysis_type == 'technical':
                    keyboard = FOREX_KEYBOARD
                    message_text += "technical analysis:"
                elif analysis_type == 'sentiment':
                    keyboard = FOREX_SENTIMENT_KEYBOARD
                    message_text += "sentiment analysis:"
                elif analysis_type == 'calendar':
                    keyboard = FOREX_CALENDAR_KEYBOARD
                    message_text += "economic calendar:"
                else:
                    keyboard = FOREX_KEYBOARD
                    message_text += "analysis:"
            elif market == 'crypto':
                if analysis_type == 'technical':
                    keyboard = CRYPTO_KEYBOARD
                    message_text += "technical analysis:"
                elif analysis_type == 'sentiment':
                    keyboard = CRYPTO_SENTIMENT_KEYBOARD
                    message_text += "sentiment analysis:"
                else:
                    keyboard = CRYPTO_KEYBOARD
                    message_text += "analysis:"
            elif market == 'indices':
                if analysis_type == 'technical':
                    keyboard = INDICES_KEYBOARD
                    message_text += "technical analysis:"
                elif analysis_type == 'sentiment':
                    keyboard = INDICES_SENTIMENT_KEYBOARD
                    message_text += "sentiment analysis:"
                else:
                    keyboard = INDICES_KEYBOARD
                    message_text += "analysis:"
            elif market == 'commodities':
                if analysis_type == 'technical':
                    keyboard = COMMODITIES_KEYBOARD
                    message_text += "technical analysis:"
                elif analysis_type == 'sentiment':
                    keyboard = COMMODITIES_SENTIMENT_KEYBOARD
                    message_text += "sentiment analysis:"
                else:
                    keyboard = COMMODITIES_KEYBOARD
                    message_text += "analysis:"
            else:
                # Unknown market, show an error
                await query.edit_message_text(
                    text=f"Unknown market: {market}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
                    ]])
                )
                return MENU
            
            # Show the keyboard
            await query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return CHOOSE_INSTRUMENT
        except Exception as e:
            logger.error(f"Error in market_callback: {str(e)}")
            logger.exception(e)
            return MENU

    async def market_signals_callback(self, update: Update, context=None) -> int:
        """Handle back_signals callback"""
        query = update.callback_query
        
        try:
            # Beantwoord de callback query
            await query.answer()
            
            # Toon het signals menu
            await query.edit_message_text(
                text="What would you like to do with trading signals?",
                reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
            )
            
            return CHOOSE_SIGNALS
        except Exception as e:
            logger.error(f"Error in back_signals_callback: {str(e)}")
            logger.exception(e)
            
            # Fallback: stuur een nieuw bericht met het signals menu
            try:
                await query.message.reply_text(
                    text="What would you like to do with trading signals?",
                    reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                )
                return CHOOSE_SIGNALS
            except:
                return MENU

    async def analysis_choice(self, update: Update, context=None) -> int:
        """Handle analysis type selection"""
        query = update.callback_query
        
        try:
            # Answer the callback query
            await query.answer()
            
            # Determine which type of analysis was chosen
            analysis_type = query.data.replace('analysis_', '')
            
            # Check if we're coming from a signal and have an instrument
            is_from_signal = False
            instrument = None
            if context and hasattr(context, 'user_data'):
                is_from_signal = context.user_data.get('from_signal', False)
                instrument = context.user_data.get('instrument')
                logger.info(f"Analysis choice with from_signal={is_from_signal}, instrument={instrument}")
            
            if analysis_type == 'calendar':
                # Show economic calendar directly without market selection
                try:
                    # Show loading message
                    await query.edit_message_text(
                        text="Please wait, fetching economic calendar...",
                        reply_markup=None
                    )
                    
                    # Get calendar data - use instrument if available, otherwise global view
                    calendar_data = await self.calendar.get_instrument_calendar("GLOBAL" if not instrument else instrument)
                    
                    # Show the calendar with back button
                    await query.edit_message_text(
                        text=calendar_data,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_to_analysis")  # Change from back_analysis to back_to_analysis
                        ]]),
                        parse_mode=ParseMode.HTML
                    )
                    
                    return SHOW_RESULT
                    
                except Exception as e:
                    logger.error(f"Error showing calendar: {str(e)}")
                    await query.edit_message_text(
                        text="An error occurred while fetching the calendar. Please try again later.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_to_analysis")  # Change from back_analysis to back_to_analysis
                        ]])
                    )
                    return MENU
            
            elif analysis_type == 'technical':
                # If we have an instrument from signal, go directly to analysis
                if is_from_signal and instrument:
                    logger.info(f"Going directly to technical analysis for instrument: {instrument}")
                    return await self.show_technical_analysis(update, context, instrument=instrument)
                
                # Otherwise show market selection
                await query.edit_message_text(
                    text="Select a market for technical analysis:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
                return CHOOSE_MARKET
                
            elif analysis_type == 'sentiment':
                # If we have an instrument from signal, go directly to analysis
                if is_from_signal and instrument:
                    logger.info(f"Going directly to sentiment analysis for instrument: {instrument}")
                    return await self.show_sentiment_analysis(update, context, instrument=instrument)
                
                # Otherwise show market selection
                await query.edit_message_text(
                    text="Select a market for sentiment analysis:",
                    reply_markup=InlineKeyboardMarkup(MARKET_SENTIMENT_KEYBOARD)
                )
                return CHOOSE_MARKET
                
            else:
                logger.warning(f"Unknown analysis type: {analysis_type}")
                await query.edit_message_text(
                    text="Unknown analysis type. Please try again.",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
                return CHOOSE_ANALYSIS
                
        except Exception as e:
            logger.error(f"Error in analysis_choice: {str(e)}")
            logger.exception(e)
            
            # Send a new message as fallback
            try:
                await query.message.reply_text(
                    text="An error occurred. Please try again.",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
            except:
                pass
            
            return CHOOSE_ANALYSIS

    async def back_to_signal_callback(self, update: Update, context=None) -> int:
        """Handle back to signal callback to return to the signal details"""
        query = update.callback_query
        await query.answer()
        
        try:
            logger.info(f"Back to signal callback invoked by user {update.effective_user.id}")
            
            # Check for context
            if context and hasattr(context, 'user_data'):
                # Log available context
                logger.info(f"Available context: {context.user_data.keys()}")
                
                # Check if we're in a signal flow
                from_signal = context.user_data.get('from_signal', False)
                logger.info(f"from_signal: {from_signal}")
                
                # Get previous state if available
                previous_state = context.user_data.get('previous_state')
                logger.info(f"previous_state: {previous_state}")
                
                # Get instrument if available
                instrument = context.user_data.get('instrument')
                logger.info(f"instrument: {instrument}")
                
                # If we came from a signal and have an instrument, show that signal
                if from_signal and instrument:
                    logger.info(f"Back to signal from analysis for user {update.effective_user.id}")
                    logger.info(f"Found instrument in context: {instrument}")
                    
                    # Try to find this signal in user signals
                    user_id = update.effective_user.id
                    user_signals = {}
                    
                    # Load signals if available
                    if hasattr(self, 'user_signals'):
                        user_signals = self.user_signals.get(user_id, {})
                    
                    signal_data = None
                    signal_id = None
                    
                    # Look for the signal with this instrument
                    logger.info(f"Looking for signal with instrument: {instrument} for user: {user_id}")
                    for sid, data in user_signals.items():
                        if data.get('instrument') == instrument:
                            signal_data = data
                            signal_id = sid
                            break
                    
                    # If signal found, format response with that data
                    if signal_data:
                        # Format signal message
                        message_text = self._format_signal_message(signal_data, signal_id)
                        
                        # Create keyboard
                        keyboard = [
                            [
                                InlineKeyboardButton("📊 Analyze", callback_data=f"analyze_signal_{signal_id}")
                            ],
                            [
                                InlineKeyboardButton("📤 Share", callback_data=f"share_signal_{signal_id}"),
                                InlineKeyboardButton("❌ Delete", callback_data=f"delete_signal_{signal_id}")
                            ],
                            [InlineKeyboardButton("⬅️ Back to Signals", callback_data="signals_manage")]
                        ]
                        
                        # Show the signal
                        await query.edit_message_text(
                            text=message_text,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True
                        )
                        
                        return SIGNAL_DETAILS
                    else:
                        # If signal not found, create a fallback message
                        logger.info(f"Created fallback signal message for {instrument} for user {user_id}")
                        
                        # Create basic message with instrument
                        message_text = f"<b>{instrument} Signal</b>\n\n"
                        message_text += "This is a basic signal view. You can go back to the signals list or view analysis."
                        
                        # Create keyboard with limited options
                        keyboard = [
                            [
                                InlineKeyboardButton("📊 Analysis", callback_data=f"analyze_from_signal_{instrument}")
                            ],
                            [InlineKeyboardButton("⬅️ Back to Signals", callback_data="signals_manage")]
                        ]
                        
                        # Show the fallback signal view
                        await query.edit_message_text(
                            text=message_text,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                        
                        return SIGNAL_DETAILS
                
                # Default fallback - return to signals list
                await query.edit_message_text(
                    text="Your trading signals:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📝 Manage Signals", callback_data="signals_manage")],
                        [InlineKeyboardButton("➕ Add Signal", callback_data="signals_add")],
                        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]
                    ]),
                    parse_mode=ParseMode.HTML
                )
                
                return SIGNALS_MENU
            
            # No context available
            logger.warning("No context available for back to signal, returning to signals menu")
            await query.edit_message_text(
                text="Your trading signals:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📝 Manage Signals", callback_data="signals_manage")],
                    [InlineKeyboardButton("➕ Add Signal", callback_data="signals_add")],
                    [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]
                ]),
                parse_mode=ParseMode.HTML
            )
            
            return SIGNALS_MENU
            
        except Exception as e:
            logger.error(f"Error in back_to_signal_callback: {str(e)}")
            logger.exception(e)
            
            try:
                await query.edit_message_text(
                    text="An error occurred. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
                )
            except Exception:
                pass
                
            return ConversationHandler.END

    async def signal_technical_callback(self, update: Update, context=None) -> int:
        """Handle signal_technical callback to show technical analysis for the selected instrument"""
        query = update.callback_query
        await query.answer()
        callback_data = query.data
        
        try:
            # Extract instrument from callback data if it's in the format signal_technical_INSTRUMENT
            instrument = None
            if callback_data.startswith('signal_technical_'):
                instrument = callback_data[len('signal_technical_'):]
                logger.info(f"Extracted instrument {instrument} from callback data {callback_data}")
                # Store instrument in context for consistent back navigation
                if context and hasattr(context, 'user_data'):
                    context.user_data['instrument'] = instrument
            
            # If instrument not found in callback, try to get from context
            if not instrument and context and hasattr(context, 'user_data'):
                instrument = context.user_data.get('instrument')
                logger.info(f"Using instrument {instrument} from context")
            
            # If still no instrument, try to find it in user's signals
            if not instrument and context and hasattr(context, 'user_data'):
                user_id = update.effective_user.id
                signals = context.user_data.get('signals', {})
                if signals:
                    # Get the most recent signal's instrument
                    latest_signal = list(signals.values())[-1]
                    instrument = latest_signal.get('instrument')
                    logger.info(f"Using instrument {instrument} from user's signals")
            
            if not instrument:
                logger.warning(f"Could not determine instrument for technical analysis for user {update.effective_user.id}")
                await query.edit_message_text(
                    text="Error: Could not determine which instrument to analyze. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")]])
                )
                return CHOOSE_ANALYSIS
            
            logger.info(f"Showing technical analysis for {instrument} to user {update.effective_user.id}")
            
            # Show loading message (ONE edit_message_text call only)
            await query.edit_message_text(
                text=f"Generating technical analysis for {instrument}...",
                parse_mode=ParseMode.HTML
            )
            
            # Generate the chart
            try:
                # Get timeframe from context or use default
                timeframe = context.user_data.get('timeframe', '1h')
                
                # Generate chart
                chart_data = await self.chart.get_chart(instrument, timeframe=timeframe, fullscreen=False)
                
                if not chart_data:
                    logger.error(f"Failed to generate chart for {instrument}")
                    await query.edit_message_text(
                        text=f"Sorry, I couldn't generate a chart for {instrument} at this time. Please try again later.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Back to Signal Analysis", callback_data="back_to_signal_analysis")
                        ]])
                    )
                    return CHOOSE_ANALYSIS
                
                # Create caption
                caption = f"<b>Technical Analysis for {instrument}</b> ({timeframe})"
                
                # Create keyboard with back button - FIX: Use back_to_signal_analysis instead of back_to_signal
                keyboard = [
                    [InlineKeyboardButton("⬅️ Back to Signal Analysis", callback_data="back_to_signal_analysis")]
                ]
                
                # Send the chart
                from io import BytesIO
                photo = BytesIO(chart_data)
                photo.name = f"{instrument}_chart.png"
                
                # Send photo and replace loading message in one step to avoid double messages
                await query.message.reply_photo(
                    photo=photo,
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                # Change existing message to prevent error
                try:
                    # Update the loading message, but catch errors if it doesn't work
                    await query.edit_message_text(
                        text=f"Here's your technical analysis for {instrument}:"
                    )
                except Exception as e:
                    # Ignore message not modified errors
                    logger.warning(f"Couldn't update loading message: {str(e)}")
                
                return SIGNAL_DETAILS
                
            except Exception as chart_error:
                logger.error(f"Error generating chart: {str(chart_error)}")
                logger.exception(chart_error)
                await query.edit_message_text(
                    text=f"Sorry, there was a problem generating the chart for {instrument}. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Signal Analysis", callback_data="back_to_signal_analysis")
                    ]])
                )
                return CHOOSE_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error in signal_technical_callback: {str(e)}")
            logger.exception(e)
            
            try:
                await query.edit_message_text(
                    text=f"An error occurred while generating the technical analysis. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Signal Analysis", callback_data="back_to_signal_analysis")
                    ]])
                )
            except Exception:
                pass
                
            return CHOOSE_ANALYSIS
            
    async def signal_sentiment_callback(self, update: Update, context=None) -> int:
        """Handle signal_sentiment callback to show sentiment analysis for the selected instrument"""
        query = update.callback_query
        await query.answer()
        callback_data = query.data
        
        try:
            # Extract instrument from callback data if available
            instrument = None
            if callback_data.startswith("signal_sentiment_"):
                instrument = callback_data[len("signal_sentiment_"):]
                logger.info(f"Extracted instrument {instrument} from callback data {callback_data}")
                # Store instrument in context for consistent back navigation
                if context and hasattr(context, 'user_data'):
                    context.user_data['instrument'] = instrument
            
            # If instrument not found in callback, try to get from context
            if not instrument and context and hasattr(context, 'user_data'):
                instrument = context.user_data.get('instrument')
                logger.info(f"Using instrument {instrument} from context")
            
            # If still no instrument, try to find it in user's signals
            if not instrument and context and hasattr(context, 'user_data'):
                user_id = update.effective_user.id
                signals = context.user_data.get('signals', {})
                if signals:
                    # Get the most recent signal's instrument
                    latest_signal = list(signals.values())[-1]
                    instrument = latest_signal.get('instrument')
                    logger.info(f"Using instrument {instrument} from user's signals")
            
            if not instrument:
                logger.warning(f"Could not determine instrument for sentiment analysis for user {update.effective_user.id}")
                await query.edit_message_text(
                    text="Error: Could not determine which instrument to analyze. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")]])
                )
                return CHOOSE_ANALYSIS
            
            logger.info(f"Showing sentiment analysis for {instrument} to user {update.effective_user.id}")
            
            # Show loading message
            await query.edit_message_text(
                text=f"Analyzing market sentiment for {instrument}...",
                parse_mode=ParseMode.HTML
            )
            
            # Get sentiment analysis
            try:
                # Use the sentiment service
                sentiment_data_task = self.sentiment.get_market_sentiment(instrument)
                sentiment_data = await asyncio.wait_for(sentiment_data_task, timeout=60.0)
                
                if not sentiment_data:
                    logger.error(f"Failed to get sentiment data for {instrument}")
                    await query.edit_message_text(
                        text=f"Sorry, I couldn't generate sentiment analysis for {instrument} at this time.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Back to Signal Analysis", callback_data="back_to_signal_analysis")
                        ]])
                    )
                    return CHOOSE_ANALYSIS
                
                # Extract the analysis text
                analysis = sentiment_data.get('analysis', 'Analysis not available')
                
                # Clean up formatting
                analysis = re.sub(r'^```html\s*', '', analysis)
                analysis = re.sub(r'\s*```$', '', analysis)
                
                # Create keyboard with back button
                keyboard = [
                    [InlineKeyboardButton("⬅️ Back to Signal Analysis", callback_data="back_to_signal_analysis")]
                ]
                
                # Send the analysis
                await query.edit_message_text(
                    text=analysis,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                return SIGNAL_DETAILS
                
            except Exception as sentiment_error:
                logger.error(f"Error getting sentiment data: {str(sentiment_error)}")
                logger.exception(sentiment_error)
                await query.edit_message_text(
                    text=f"Sorry, there was a problem generating sentiment analysis for {instrument}. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Signal Analysis", callback_data="back_to_signal_analysis")
                    ]])
                )
                return CHOOSE_ANALYSIS
        
        except Exception as e:
            logger.error(f"Error in signal_sentiment_callback: {str(e)}")
            logger.exception(e)
            
            try:
                await query.edit_message_text(
                    text=f"An error occurred while generating the sentiment analysis. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Signal Analysis", callback_data="back_to_signal_analysis")
                    ]])
                )
            except Exception:
                pass
                
            return CHOOSE_ANALYSIS
            
    async def signal_calendar_callback(self, update: Update, context=None) -> int:
        """Handle signal_calendar callback to show economic calendar for the selected instrument"""
        query = update.callback_query
        await query.answer()
        callback_data = query.data
        
        try:
            # Extract instrument from callback data if available
            instrument = None
            if callback_data.startswith("signal_calendar_"):
                instrument = callback_data[len("signal_calendar_"):]
                logger.info(f"Extracted instrument {instrument} from callback data {callback_data}")
                # Store instrument in context for consistent back navigation
                if context and hasattr(context, 'user_data'):
                    context.user_data['instrument'] = instrument
            
            # If instrument not found in callback, try to get from context
            if not instrument and context and hasattr(context, 'user_data'):
                instrument = context.user_data.get('instrument')
                logger.info(f"Using instrument {instrument} from context")
            
            # If still no instrument, try to find it in user's signals
            if not instrument and context and hasattr(context, 'user_data'):
                user_id = update.effective_user.id
                signals = context.user_data.get('signals', {})
                if signals:
                    # Get the most recent signal's instrument
                    latest_signal = list(signals.values())[-1]
                    instrument = latest_signal.get('instrument')
                    logger.info(f"Using instrument {instrument} from user's signals")
            
            if not instrument:
                logger.warning(f"Could not determine instrument for economic calendar for user {update.effective_user.id}")
                await query.edit_message_text(
                    text="Error: Could not determine which instrument to analyze. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")]])
                )
                return CHOOSE_ANALYSIS
            
            logger.info(f"Showing economic calendar for {instrument} to user {update.effective_user.id}")
            
            # Show loading message
            await query.edit_message_text(
                text=f"Fetching economic calendar data for {instrument}...",
                parse_mode=ParseMode.HTML
            )
            
            # Extract currency codes from the instrument
            currency_codes = self._extract_currency_codes(instrument)
            
            if not currency_codes:
                logger.warning(f"No currency codes found for instrument {instrument}")
                await query.edit_message_text(
                    text=f"Could not extract currencies from {instrument} for economic calendar.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Signal Analysis", callback_data="back_to_signal_analysis")
                    ]])
                )
                return CHOOSE_ANALYSIS
            
            # Get calendar data
            try:
                # Use the calendar service
                calendar_data_task = self.calendar.get_calendar_data(currency_codes)
                calendar_data = await asyncio.wait_for(calendar_data_task, timeout=60.0)
                
                if not calendar_data or not calendar_data.get('events'):
                    logger.error(f"Failed to get calendar data for {instrument}")
                    await query.edit_message_text(
                        text=f"Sorry, no economic calendar events found for {instrument}.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Back to Signal Analysis", callback_data="back_to_signal_analysis")
                        ]])
                    )
                    return CHOOSE_ANALYSIS
                
                # Format the calendar data
                events = calendar_data.get('events', [])
                calendar_text = f"<b>📅 Economic Calendar for {instrument}</b>\n\n"
                
                # Add relevant events
                for event in events[:15]:  # Limit to first 15 events to stay within message limits
                    date = event.get('date', 'Unknown')
                    time = event.get('time', 'Unknown')
                    currency = event.get('currency', 'Unknown')
                    description = event.get('description', 'Unknown')
                    impact = event.get('impact', 'Unknown')
                    
                    # Format impact with emoji
                    impact_emoji = "🔴" if impact == "High" else "🟠" if impact == "Medium" else "🟢"
                    
                    calendar_text += f"{date} {time} - {currency}\n"
                    calendar_text += f"{impact_emoji} <b>{description}</b>\n\n"
                
                if len(events) > 15:
                    calendar_text += f"\n<i>Showing 15 of {len(events)} events...</i>"
                
                # Create keyboard with back button
                keyboard = [
                    [InlineKeyboardButton("⬅️ Back to Signal Analysis", callback_data="back_to_signal_analysis")]
                ]
                
                # Send the calendar
                await query.edit_message_text(
                    text=calendar_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                return SIGNAL_DETAILS
                
            except Exception as calendar_error:
                logger.error(f"Error getting calendar data: {str(calendar_error)}")
                logger.exception(calendar_error)
                await query.edit_message_text(
                    text=f"Sorry, there was a problem fetching the economic calendar for {instrument}. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Signal Analysis", callback_data="back_to_signal_analysis")
                    ]])
                )
                return CHOOSE_ANALYSIS
        
        except Exception as e:
            logger.error(f"Error in signal_calendar_callback: {str(e)}")
            logger.exception(e)
            
            try:
                await query.edit_message_text(
                    text=f"An error occurred while fetching the economic calendar. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Signal Analysis", callback_data="back_to_signal_analysis")
                    ]])
                )
            except Exception:
                pass
                
            return CHOOSE_ANALYSIS
            
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
            
            # Format message text and create keyboard
            if instrument:
                text = f"<b>Choose Analysis Type for {instrument}</b>\n\nSelect what type of analysis you want to view:"
                
                # Create dynamic keyboard with the instrument
                keyboard = [
                    [InlineKeyboardButton("📊 Technical Analysis", callback_data=f"signal_technical_{instrument}")],
                    [InlineKeyboardButton("💭 Sentiment Analysis", callback_data=f"signal_sentiment_{instrument}")],
                    [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"signal_calendar_{instrument}")],
                    [InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]
                ]
            else:
                # Fallback text and keyboard
                text = "Choose analysis type:"
                
                # Generic keyboard without instrument
                keyboard = [
                    [
                        InlineKeyboardButton("📈 Technical Analysis", callback_data="signal_technical"),
                        InlineKeyboardButton("🧠 Sentiment Analysis", callback_data="signal_sentiment")
                    ],
                    [
                        InlineKeyboardButton("📅 Economic Calendar", callback_data="signal_calendar")
                    ],
                    [InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]
                ]
            
            # Show analysis options
            await query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
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
                    ]])
                )
            except Exception:
                pass
                
            return CHOOSE_ANALYSIS

    def _extract_currency_codes(self, instrument: str) -> List[str]:
        """Extract currency codes from instrument string like EURUSD or XAUUSD"""
        if not instrument:
            return []
            
        # Known currencies
        known_currencies = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'NZD', 'CAD', 'CHF']
        
        # Special case for gold/silver
        if instrument.startswith('XAU'):
            return ['USD']  # For gold, just return USD
        if instrument.startswith('XAG'):
            return ['USD']  # For silver, just return USD
            
        # Extract currency codes from forex pair
        result = []
        instrument = instrument.upper()
        for currency in known_currencies:
            if currency in instrument:
                result.append(currency)
                
        logger.info(f"Extracted currencies {result} from instrument {instrument}")
        return result
        
    def _get_instrument_currency(self, instrument: str) -> str:
        """Get the primary currency from an instrument"""
        if not instrument:
            return None
            
        # Handle special cases
        if instrument.startswith('XAU'):
            return 'USD'  # For gold
        if instrument.startswith('XAG'):
            return 'USD'  # For silver
            
        # For normal forex pairs, return the first 3 letters
        if len(instrument) >= 3:
            return instrument[:3]
            
        return None

# Indices keyboard voor sentiment analyse
INDICES_SENTIMENT_KEYBOARD = [
    [
        InlineKeyboardButton("US30", callback_data="instrument_US30_sentiment"),
        InlineKeyboardButton("US500", callback_data="instrument_US500_sentiment"),
        InlineKeyboardButton("US100", callback_data="instrument_US100_sentiment")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Commodities keyboard voor sentiment analyse
COMMODITIES_SENTIMENT_KEYBOARD = [
    [
        InlineKeyboardButton("GOLD", callback_data="instrument_XAUUSD_sentiment"),
        InlineKeyboardButton("SILVER", callback_data="instrument_XAGUSD_sentiment"),
        InlineKeyboardButton("OIL", callback_data="instrument_USOIL_sentiment")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

async def analyze_from_signal_callback(self, update: Update, context=None) -> int:
    """Handle analyze_from_signal callback to show analysis options for the selected signal"""
    query = update.callback_query
    await query.answer()
    
    try:
        logger.info(f"Analyze from signal callback invoked by user {update.effective_user.id}")
        
        # Get signal ID or instrument from the callback data if available
        callback_data = query.data
        signal_id = None
        instrument = None
        
        # Check if format is analyze_signal_ID
        if callback_data.startswith("analyze_signal_"):
            signal_id = callback_data[len("analyze_signal_"):]
            logger.info(f"Signal ID extracted from callback: {signal_id}")
        
        # Check if format is analyze_from_signal_INSTRUMENT
        elif callback_data.startswith("analyze_from_signal_"):
            instrument = callback_data[len("analyze_from_signal_"):]
            logger.info(f"Instrument extracted directly from callback: {instrument}")
        
        # Check if we have user data context
        if context and hasattr(context, 'user_data'):
            user_id = update.effective_user.id
            
            # Mark that we're in the signal flow and coming from a signal
            context.user_data['in_signal_flow'] = True
            context.user_data['from_signal'] = True
            
            # Try to get the signal from signals
            if not instrument and signal_id:
                # Try to get the instrument from user's signals if available
                logger.info(f"Loading user signals for {user_id}")
                if hasattr(self, 'user_signals') and user_id in self.user_signals:
                    # If we have a signal ID, try to get the instrument from it
                    signals = self.user_signals.get(user_id, {})
                    if signal_id in signals:
                        instrument = signals[signal_id].get('instrument')
                        logger.info(f"Found instrument {instrument} from signal_id {signal_id}")
                    
            # If instrument was found, store it in context for later use
            if instrument:
                context.user_data['instrument'] = instrument
                logger.info(f"Stored instrument {instrument} in context for user {user_id}")
            else:
                # Try to get from context if already set
                instrument = context.user_data.get('instrument')
                logger.info(f"Using instrument {instrument} from context")
            
            # Format message text
            if instrument:
                text = f"<b>Choose Analysis Type for {instrument}</b>\n\nSelect what type of analysis you want to view:"
                
                # Create dynamic keyboard with the instrument
                keyboard = [
                    [InlineKeyboardButton("📊 Technical Analysis", callback_data=f"signal_technical_{instrument}")],
                    [InlineKeyboardButton("💭 Sentiment Analysis", callback_data=f"signal_sentiment_{instrument}")],
                    [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"signal_calendar_{instrument}")],
                    [InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]
                ]
            else:
                logger.warning(f"No instrument found for analyze_from_signal for user {user_id}")
                text = "Could not determine which instrument to analyze."
                keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal")]]
            
            # Edit message to show analysis options
            await query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            return CHOOSE_ANALYSIS
            
        else:
            logger.warning("No context available for signal analysis")
            await query.edit_message_text(
                text="Error: Could not retrieve analysis context.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal")]])
            )
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"Error in analyze_from_signal_callback: {str(e)}")
        logger.exception(e)
        
        try:
            await query.edit_message_text(
                text="An error occurred. Please try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
            )
        except Exception:
            pass
            
        return ConversationHandler.END
