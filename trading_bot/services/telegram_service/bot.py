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
            return MENU
    
    return wrapper

# API keys with robust sanitization
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "").strip()

# Set environment variables for the API keys with sanitization
os.environ["PERPLEXITY_API_KEY"] = PERPLEXITY_API_KEY

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
        application.add_handler(CommandHandler("set_payment_failed", self.set_payment_failed_command))
        application.add_handler(CommandHandler("setpaymentfailed", self.set_payment_failed_command))
        
        # Add specific handlers for menu navigation first
        application.add_handler(CallbackQueryHandler(self.menu_analyse_callback, pattern="^menu_analyse$"))
        application.add_handler(CallbackQueryHandler(self.menu_signals_callback, pattern="^menu_signals$"))
        
        # Add specific handlers for signal analysis flows
        application.add_handler(CallbackQueryHandler(self.analysis_technical_callback, pattern="^analysis_technical$"))
        application.add_handler(CallbackQueryHandler(self.analysis_technical_callback, pattern="^analysis_technical_signal_.*$"))
        
        application.add_handler(CallbackQueryHandler(self.analysis_sentiment_callback, pattern="^analysis_sentiment$"))
        application.add_handler(CallbackQueryHandler(self.analysis_sentiment_callback, pattern="^analysis_sentiment_signal_.*$"))
        
        application.add_handler(CallbackQueryHandler(self.analysis_calendar_callback, pattern="^analysis_calendar$"))
        application.add_handler(CallbackQueryHandler(self.analysis_calendar_callback, pattern="^analysis_calendar_signal_.*$"))
        
        # Add handler for market selection
        application.add_handler(CallbackQueryHandler(self.market_callback, pattern="^market_.*$"))
        
        # Add handlers for instrument selection
        application.add_handler(CallbackQueryHandler(self.instrument_callback, pattern="^instrument_.*$"))
        
        # Add handlers for signals management
        application.add_handler(CallbackQueryHandler(self.market_signals_callback, pattern="^market_signals_.*$"))
        application.add_handler(CallbackQueryHandler(self.instrument_signals_callback, pattern="^instrument_signals_.*$"))
        
        # Add handlers for back navigation
        application.add_handler(CallbackQueryHandler(self.back_menu_callback, pattern="^back_menu$"))
        application.add_handler(CallbackQueryHandler(self.back_market_callback, pattern="^back_market$"))
        application.add_handler(CallbackQueryHandler(self.back_instrument_callback, pattern="^back_instrument$"))
        application.add_handler(CallbackQueryHandler(self.analysis_callback, pattern="^back_to_analysis$"))
        application.add_handler(CallbackQueryHandler(self.analysis_callback, pattern="^back_analysis$"))
        
        # Add handler for analyze_from_signal
        application.add_handler(CallbackQueryHandler(self.analyze_from_signal_callback, pattern="^analyze_from_signal_.*$"))
        
        application.add_handler(CallbackQueryHandler(self.back_to_signal_callback, pattern="^back_to_signal$"))
        
        # Signal flow analysis handlers
        application.add_handler(CallbackQueryHandler(
            self.signal_technical_callback, pattern="^signal_technical$"))
        application.add_handler(CallbackQueryHandler(
            self.signal_sentiment_callback, pattern="^signal_sentiment$"))
        application.add_handler(CallbackQueryHandler(
            self.signal_calendar_callback, pattern="^signal_calendar$"))
        application.add_handler(CallbackQueryHandler(
            self.back_to_signal_analysis_callback, pattern="^back_to_signal_analysis$"))
        
        # Callback query handler for all other button presses (should be last)
        application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Ensure signal handlers are registered
        logger.info("Enabling and initializing signals functionality")
        
        # Load any saved signals
        self._load_signals()
        
        logger.info("All handlers registered successfully")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Send a welcome message when the bot is started."""
        user = update.effective_user
        user_id = user.id
        first_name = user.first_name
        
        # Reset signal flow status when starting a new session
        if context and hasattr(context, 'user_data'):
            if 'in_signals_flow' in context.user_data:
                context.user_data['in_signals_flow'] = False
                logger.info(f"Resetting in_signals_flow to False for user {user_id} in start_command")
        
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
            # Set in_signals_flow to False since we are in the main menu flow
            if context and hasattr(context, 'user_data'):
                context.user_data['in_signals_flow'] = False
                logger.info("Setting in_signals_flow to False in menu_analyse_callback")
            
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
        
        # Set in_signals_flow to False since we are in the main menu flow
        if context and hasattr(context, 'user_data'):
            context.user_data['in_signals_flow'] = False
            logger.info("Setting in_signals_flow to False in menu_signals_callback")
        
        # Show the signals menu
        await query.edit_message_text(
            text="What would you like to do with trading signals?",
            reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
        )
        
        return CHOOSE_SIGNALS

    async def analysis_callback(self, update: Update, context=None) -> int:
        """Handle analysis callback"""
        query = update.callback_query
        
        # Reset signal flow status and clear signal-related context
        if context and hasattr(context, 'user_data'):
            context.user_data['in_signals_flow'] = False
            logger.info("Setting in_signals_flow to False in analysis_callback")
            
            # Clear any signal-related context
            if 'from_signal' in context.user_data:
                del context.user_data['from_signal']
            if 'previous_state' in context.user_data and context.user_data['previous_state'] == 'SIGNAL':
                del context.user_data['previous_state']
        
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

    async def help_callback(self, update: Update, context=None) -> int:
        """Handle help callback"""
        query = update.callback_query
        
        try:
            # Toon help informatie
            await query.edit_message_text(
                text=HELP_MESSAGE,
                parse_mode=ParseMode.HTML
            )
            
            return MENU
        except Exception as e:
            logger.error(f"Error in help_callback: {str(e)}")
            try:
                await query.message.reply_text(
                    text=HELP_MESSAGE,
                    parse_mode=ParseMode.HTML
                )
                return MENU
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                return MENU

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
                
                # First check if we're in signals flow
                in_signals_flow = context.user_data.get('in_signals_flow', False)
                
                # Set from_signal if this came via signal flow
                if is_from_signal:
                    context.user_data['from_signal'] = True
                    context.user_data['previous_state'] = 'SIGNAL'
                    if instrument:
                        context.user_data['instrument'] = instrument
                
                # Only use signal context if we're specifically in signals flow
                if in_signals_flow and (context.user_data.get('from_signal') or context.user_data.get('previous_state') == 'SIGNAL') and (instrument or context.user_data.get('instrument')):
                    instrument = instrument or context.user_data.get('instrument')
                    logger.info(f"Using instrument from signal: {instrument} for technical analysis (in_signals_flow={in_signals_flow})")
                    
                    # Go directly to technical analysis for this instrument
                    return await self.show_technical_analysis(update, context, instrument=instrument)
                elif not in_signals_flow and (context.user_data.get('from_signal') or context.user_data.get('previous_state') == 'SIGNAL'):
                    # Clear signal-related context when we're not in signals flow
                    logger.info("Clearing signal context because we're not in signals flow")
                    if 'from_signal' in context.user_data:
                        del context.user_data['from_signal']
                    if 'previous_state' in context.user_data and context.user_data['previous_state'] == 'SIGNAL':
                        del context.user_data['previous_state']
            
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
                
                # First check if we're in signals flow
                in_signals_flow = context.user_data.get('in_signals_flow', False)
                
                # Set from_signal if this came via signal flow
                if is_from_signal:
                    context.user_data['from_signal'] = True
                    context.user_data['previous_state'] = 'SIGNAL'
                    if instrument:
                        context.user_data['instrument'] = instrument
                
                # Only use signal context if we're specifically in signals flow
                if in_signals_flow and (context.user_data.get('from_signal') or context.user_data.get('previous_state') == 'SIGNAL') and (instrument or context.user_data.get('instrument')):
                    instrument = instrument or context.user_data.get('instrument')
                    logger.info(f"Using instrument from signal: {instrument} for sentiment analysis (in_signals_flow={in_signals_flow})")
                    
                    # Go directly to sentiment analysis for this instrument
                    return await self.show_sentiment_analysis(update, context, instrument=instrument)
                elif not in_signals_flow and (context.user_data.get('from_signal') or context.user_data.get('previous_state') == 'SIGNAL'):
                    # Clear signal-related context when we're not in signals flow
                    logger.info("Clearing signal context because we're not in signals flow")
                    if 'from_signal' in context.user_data:
                        del context.user_data['from_signal']
                    if 'previous_state' in context.user_data and context.user_data['previous_state'] == 'SIGNAL':
                        del context.user_data['previous_state']
            
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
            # Check if we need to clear signal context when not in signals flow
            if context and hasattr(context, 'user_data'):
                in_signals_flow = context.user_data.get('in_signals_flow', False)
                if not in_signals_flow and (context.user_data.get('from_signal') or context.user_data.get('previous_state') == 'SIGNAL'):
                    # Clear signal-related context when we're not in signals flow
                    logger.info("Clearing signal context because we're not in signals flow")
                    if 'from_signal' in context.user_data:
                        del context.user_data['from_signal']
                    if 'previous_state' in context.user_data and context.user_data['previous_state'] == 'SIGNAL':
                        del context.user_data['previous_state']
            
            # Show loading message
            await query.edit_message_text(
                text="Please wait, fetching economic calendar data..."
            )
            
            # Get global calendar events directly
            calendar_data = await self.calendar.get_instrument_calendar("GLOBAL")
            
            # Create keyboard with back button
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_ANALYSIS)]]
            
            # Show the calendar with back button
            await query.edit_message_text(
                text=calendar_data,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            return SHOW_RESULT
            
        except Exception as e:
            logger.error(f"Error in analysis_calendar_callback: {str(e)}")
            logger.exception(e)
            
            # Show error message
            await query.edit_message_text(
                text="Sorry, I couldn't retrieve the economic calendar at this time. Please try again later.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_ANALYSIS)
                ]])
            )
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
                # Explicitly mark that we're not in signals flow
                context.user_data['in_signals_flow'] = False
                logger.info(f"Stored in context: market={market}, analysis_type={analysis_type}, in_signals_flow=False")
            
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
                            InlineKeyboardButton("Back", callback_data="back_to_signal" if is_from_signal else "back_to_analysis")  # Change from back_analysis to back_to_analysis
                        ]]),
                        parse_mode=ParseMode.HTML
                    )
                    
                    return SHOW_RESULT
                    
                except Exception as e:
                    logger.error(f"Error showing calendar: {str(e)}")
                    await query.edit_message_text(
                        text="An error occurred while fetching the calendar. Please try again later.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("Back", callback_data="back_to_signal" if is_from_signal else "back_to_analysis")  # Change from back_analysis to back_to_analysis
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
        """Handle back_to_signal callback to return to signal message"""
        query = update.callback_query
        await query.answer()
        
        # Get user ID for tracking purposes
        user_id = update.effective_user.id
        logger.info(f"Back to signal callback invoked by user {user_id}")
        
        try:
            # Debug: Log message type and attributes
            logger.info(f"Message type: {type(query.message)}")
            logger.info(f"Message has photo: {hasattr(query.message, 'photo')}")
            logger.info(f"Message has caption: {hasattr(query.message, 'caption')}")
            if hasattr(query.message, 'message_id'):
                logger.info(f"Message ID: {query.message.message_id}")
            
            # Check if we're coming from a photo message
            from_photo = False
            
            # Check for caption or photo property on the message
            if hasattr(query.message, 'caption') and query.message.caption:
                from_photo = True
                logger.info(f"Photo detected via caption: {query.message.caption}")
                
            if hasattr(query.message, 'photo') and query.message.photo:
                from_photo = True
                logger.info(f"Photo detected via photo attribute")
            
            # Check context flag and photo-related keys
            if context and hasattr(context, 'user_data'):
                logger.info(f"Context keys: {list(context.user_data.keys())}")
                
                # Check for photo flag
                if context.user_data.get('from_photo', False):
                    from_photo = True
                    logger.info("Photo detected via from_photo flag in context")
                
                # Check for photo-related keys
                photo_keys = [key for key in context.user_data.keys() if 'photo' in key.lower()]
                if photo_keys:
                    logger.info(f"Found photo-related keys: {photo_keys}")
                    from_photo = True
                
                # Log technical message info if available
                if 'technical_message_id' in context.user_data:
                    logger.info(f"Technical message ID in context: {context.user_data['technical_message_id']}")
                
                # Clear the photo flag after reading it
                if 'from_photo' in context.user_data:
                    del context.user_data['from_photo']
                    logger.info("Cleared from_photo flag")
                
                # Set in_signals_flow to True when returning to a signal
                context.user_data['in_signals_flow'] = True
                logger.info("Setting in_signals_flow to True in back_to_signal_callback")
            
            # Debug: Log detection result
            logger.info(f"Is from photo? {from_photo}")
            
            # Ensure signals are loaded from file
            self._load_signals()
            
            # Find the original message ID we should use for editing
            target_message_id = None
            target_chat_id = None
            
            if context and hasattr(context, 'user_data'):
                # If this is a photo message, use the technical_message_id as target
                if from_photo and 'technical_message_id' in context.user_data:
                    target_message_id = context.user_data.get('technical_message_id')
                    target_chat_id = context.user_data.get('technical_chat_id')
                    logger.info(f"Using technical_message_id: {target_message_id} for editing")
                else:
                    # Just use the current message
                    target_message_id = query.message.message_id
                    target_chat_id = query.message.chat_id
                    logger.info(f"Using current message ID: {target_message_id} for editing")
            
            # Continue with the existing logic for returning to signal...
            # FIRST PRIORITY: Use signal_message from context if available
            if context and hasattr(context, 'user_data') and 'signal_message' in context.user_data and context.user_data.get('instrument'):
                instrument = context.user_data.get('instrument')
                message = context.user_data['signal_message']
                
                # Recreate the original keyboard
                keyboard = [
                    [
                        InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_from_signal_{instrument}")
                    ]
                ]
                
                # Edit message to show the original signal
                if from_photo and target_message_id and target_message_id != query.message.message_id:
                    # We need to edit a different message than the current one
                    try:
                        await self.bot.edit_message_text(
                            text=message,
                            chat_id=target_chat_id,
                            message_id=target_message_id,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                        logger.info(f"Edited different message ID: {target_message_id} with signal data")
                        
                        # Try to delete the photo message if possible
                        try:
                            await query.message.delete()
                            logger.info(f"Deleted photo message: {query.message.message_id}")
                        except Exception as del_e:
                            logger.warning(f"Could not delete photo message: {str(del_e)}")
                    except Exception as edit_e:
                        logger.error(f"Error editing different message: {str(edit_e)}")
                        # Fall back to editing the current message
                        await query.edit_message_text(
                            text=message,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                else:
                    # Edit the current message
                    await query.edit_message_text(
                        text=message,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                
                logger.info(f"Successfully returned to original signal from context for {instrument}")
                
                # Make sure user_signals is updated with this message
                if user_id in self.user_signals:
                    self.user_signals[user_id]['message'] = message
                    self.user_signals[user_id]['instrument'] = instrument
                    # Also update other fields from context if available
                    for key in ['direction', 'price', 'stop_loss', 'take_profits', 'timeframe', 'strategy']:
                        signal_key = f'signal_{key}'
                        if signal_key in context.user_data:
                            self.user_signals[user_id][key] = context.user_data[signal_key]
                    self._save_signals()
                
                return SIGNAL_DETAILS
            
            # SECOND PRIORITY: Recreate message from signal-prefixed context values
            if context and hasattr(context, 'user_data') and context.user_data.get('instrument'):
                instrument = context.user_data.get('instrument')
                
                # If we have signal_* prefixed fields in context, use those to recreate the message
                if any(key.startswith('signal_') for key in context.user_data.keys()):
                    logger.info("Recreating signal message from context with signal_ prefixed fields")
                    
                    # Extract data with signal_ prefix
                    direction = context.user_data.get('signal_direction', 'UNKNOWN')
                    price = context.user_data.get('signal_price', 'N/A')
                    stop_loss = context.user_data.get('signal_stop_loss', 'N/A')
                    take_profits = context.user_data.get('signal_take_profits', [])
                    timeframe = context.user_data.get('signal_timeframe', '1h')
                    strategy = context.user_data.get('signal_strategy', 'Unknown')
                    
                    # Format the message
                    message = self._format_signal_message(
                        instrument=instrument,
                        direction=direction,
                        price=price,
                        stop_loss=stop_loss,
                        take_profits=take_profits,
                        timeframe=timeframe,
                        strategy=strategy
                    )
                    
                    # Update context with the formatted message
                    context.user_data['signal_message'] = message
                    
                    # Update user_signals
                    self.user_signals[user_id] = {
                        'instrument': instrument,
                        'direction': direction,
                        'price': price,
                        'stop_loss': stop_loss,
                        'take_profits': take_profits,
                        'message': message,
                        'base_message': message,
                        'timestamp': self._get_formatted_timestamp(),
                        'timeframe': timeframe,
                        'strategy': strategy
                    }
                    self._save_signals()
                    
                    # Recreate the original keyboard
                    keyboard = [
                        [
                            InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_from_signal_{instrument}")
                        ]
                    ]
                    
                    # Edit message to show the recreated signal
                    if from_photo and target_message_id and target_message_id != query.message.message_id:
                        # We need to edit a different message than the current one
                        try:
                            await self.bot.edit_message_text(
                                text=message,
                                chat_id=target_chat_id,
                                message_id=target_message_id,
                                reply_markup=InlineKeyboardMarkup(keyboard),
                                parse_mode=ParseMode.HTML
                            )
                            logger.info(f"Edited different message ID: {target_message_id} with recreated signal data")
                            
                            # Try to delete the photo message if possible
                            try:
                                await query.message.delete()
                                logger.info(f"Deleted photo message: {query.message.message_id}")
                            except Exception as del_e:
                                logger.warning(f"Could not delete photo message: {str(del_e)}")
                        except Exception as edit_e:
                            logger.error(f"Error editing different message: {str(edit_e)}")
                            # Fall back to editing the current message
                            await query.edit_message_text(
                                text=message,
                                reply_markup=InlineKeyboardMarkup(keyboard),
                                parse_mode=ParseMode.HTML
                            )
                    else:
                        # Edit the current message
                        await query.edit_message_text(
                            text=message,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                    
                    logger.info(f"Successfully returned to recreated signal from context data for {instrument}")
                    return SIGNAL_DETAILS
            
            # THIRD PRIORITY: Check user_signals data
            if user_id in self.user_signals:
                signal_data = self.user_signals[user_id]
                logger.info(f"Found signal data in user_signals for user {user_id}")
                
                # If we have a valid message
                if 'message' in signal_data:
                    # Prefer base_message if available (without the verdict), otherwise use the full message
                    message = signal_data.get('base_message', signal_data['message'])
                    signal_instrument = signal_data.get('instrument', 'Unknown')
                    
                    # If we have instrument in context, prioritize that one over what's in user_signals
                    if context and hasattr(context, 'user_data') and 'instrument' in context.user_data:
                        instrument_from_context = context.user_data.get('instrument')
                        if instrument_from_context and instrument_from_context != signal_instrument:
                            logger.info(f"Instrument mismatch: context has {instrument_from_context} but user_signals has {signal_instrument}. Using context value.")
                            signal_instrument = instrument_from_context
                            
                            # Update the message with the correct instrument
                            # Use regex to replace the instrument in the message
                            message = re.sub(
                                r'Instrument:\s+[A-Z0-9]+', 
                                f'Instrument: {signal_instrument}', 
                                message
                            )
                    
                    # Recreate the original keyboard
                    keyboard = [
                        [
                            InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_from_signal_{signal_instrument}")
                        ]
                    ]
                    
                    # Edit message to show the original signal
                    if from_photo and target_message_id and target_message_id != query.message.message_id:
                        # We need to edit a different message than the current one
                        try:
                            await self.bot.edit_message_text(
                                text=message,
                                chat_id=target_chat_id,
                                message_id=target_message_id,
                                reply_markup=InlineKeyboardMarkup(keyboard),
                                parse_mode=ParseMode.HTML
                            )
                            logger.info(f"Edited different message ID: {target_message_id} with user_signals data")
                            
                            # Try to delete the photo message if possible
                            try:
                                await query.message.delete()
                                logger.info(f"Deleted photo message: {query.message.message_id}")
                            except Exception as del_e:
                                logger.warning(f"Could not delete photo message: {str(del_e)}")
                        except Exception as edit_e:
                            logger.error(f"Error editing different message: {str(edit_e)}")
                            # Fall back to editing the current message
                            await query.edit_message_text(
                                text=message,
                                reply_markup=InlineKeyboardMarkup(keyboard),
                                parse_mode=ParseMode.HTML
                            )
                    else:
                        # Edit the current message
                        await query.edit_message_text(
                            text=message,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                    
                    logger.info(f"Successfully returned to original signal from user_signals for {signal_instrument}")
                    
                    # Also update context with this message
                    if context and hasattr(context, 'user_data'):
                        context.user_data['signal_message'] = message
                    
                    return SIGNAL_DETAILS
                else:
                    logger.warning(f"Signal data found for user {user_id} but no message")
                    logger.info(f"Signal data keys: {signal_data.keys()}")
            
            # FOURTH PRIORITY: Fallback to extracting data from anything we can find
            # Fallback: Try to extract instrument from current message or context
            instrument = None
            
            # Try context if available
            if context and hasattr(context, 'user_data'):
                instrument = context.user_data.get('instrument')
                logger.info(f"Found instrument in context: {instrument}")
            
            # Try to find from message text as last resort
            if not instrument and hasattr(query.message, 'text'):
                # Look for patterns like "EURUSD" or "XAUUSD" in the message
                instrument_match = re.search(r'(?:Instrument|analysis for|chart for|for\s+):\s*([A-Z0-9]{4,8})', query.message.text, re.IGNORECASE)
                if instrument_match:
                    instrument = instrument_match.group(1)
                    logger.info(f"Extracted instrument from message text: {instrument}")
                else:
                    # Try more general pattern
                    any_instrument = re.search(r'([A-Z]{3}[A-Z]{3}|XAU[A-Z]{3}|XAG[A-Z]{3})', query.message.text)
                    if any_instrument:
                        instrument = any_instrument.group(1)
                        logger.info(f"Extracted instrument from general pattern: {instrument}")
            
            # LAST RESORT: recreate a basic signal message from context data
            if context and hasattr(context, 'user_data'):
                # Extract data from context
                instrument = instrument or context.user_data.get('instrument', 'Unknown')
                
                # Try to get signal data from context with prefix or direct keys
                direction = context.user_data.get('signal_direction', context.user_data.get('direction', 'UNKNOWN'))
                price = context.user_data.get('signal_price', context.user_data.get('price', 'N/A'))
                stop_loss = context.user_data.get('signal_stop_loss', context.user_data.get('stop_loss', 'N/A'))
                take_profits = context.user_data.get('signal_take_profits', context.user_data.get('take_profits', []))
                timeframe = context.user_data.get('signal_timeframe', context.user_data.get('timeframe', '1h'))
                strategy = context.user_data.get('signal_strategy', context.user_data.get('strategy', 'Unknown'))
                
                # Use the helper method to format the signal message
                fallback_message = self._format_signal_message(
                    instrument=instrument,
                    direction=direction,
                    price=price,
                    stop_loss=stop_loss,
                    take_profits=take_profits,
                    timeframe=timeframe,
                    strategy=strategy
                )
                
                keyboard = [
                    [
                        InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_from_signal_{instrument}")
                    ]
                ]
                
                # Edit message to show the fallback signal
                if from_photo and target_message_id and target_message_id != query.message.message_id:
                    # We need to edit a different message than the current one
                    try:
                        await self.bot.edit_message_text(
                            text=fallback_message,
                            chat_id=target_chat_id,
                            message_id=target_message_id,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                        logger.info(f"Edited different message ID: {target_message_id} with fallback signal")
                        
                        # Try to delete the photo message if possible
                        try:
                            await query.message.delete()
                            logger.info(f"Deleted photo message: {query.message.message_id}")
                        except Exception as del_e:
                            logger.warning(f"Could not delete photo message: {str(del_e)}")
                    except Exception as edit_e:
                        logger.error(f"Error editing different message: {str(edit_e)}")
                        # Fall back to editing the current message
                        await query.edit_message_text(
                            text=fallback_message,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                else:
                    # Edit the current message
                    await query.edit_message_text(
                        text=fallback_message,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                
                # Store this message in context and user_signals for future use
                # Store the sent photo message ID in context for possible reference later
                if context and hasattr(context, 'user_data'):
                    context.user_data['photo_message_id'] = sent_photo.message_id
                    context.user_data['photo_chat_id'] = sent_photo.chat_id
                    logger.info(f"Stored photo message info: message_id={sent_photo.message_id}")
                    
                    # Make sure we retain the "in_signals_flow" flag if we were in a signal
                    if is_from_signal:
                        context.user_data['in_signals_flow'] = True
                        logger.info("Retained in_signals_flow=True after sending photo")
                
                # Edit the original message to indicate the analysis was sent
                await query.edit_message_text(
                    text=f"Here's your technical analysis for {instrument}:",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal" if is_from_signal else "back_instrument")
                    ]])
                )
                
            except Exception as chart_error:
                logger.error(f"Error generating chart: {str(chart_error)}")
                logger.exception(chart_error)
                await query.edit_message_text(
                    text=f"Sorry, there was a problem generating the chart for {instrument}. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_instrument")
                    ]])
                )
            
            return SHOW_RESULT
            
        except Exception as e:
            logger.error(f"Error in show_technical_analysis: {str(e)}")
            logger.exception(e)
            
            # Send fallback message
            try:
                await query.edit_message_text(
                    text=f"Sorry, I couldn't analyze {instrument} at this time. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_instrument")
                    ]])
                )
            except Exception as inner_e:
                logger.error(f"Failed to send fallback message: {str(inner_e)}")
            
            return MENU

    async def show_sentiment_analysis(self, update: Update, context=None, instrument: str = None) -> int:
        """Show sentiment analysis for a specific instrument"""
        query = update.callback_query
        
        try:
            # Check if we're coming from a signal
            is_from_signal = False
            if context and hasattr(context, 'user_data'):
                is_from_signal = context.user_data.get('from_signal', False)
                
            # First, show a loading message
            await query.edit_message_text(
                text=f"Analyzing market sentiment for {instrument}. Please wait..."
            )
            
            # Store the analysis type in context for proper back button handling
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'sentiment'
                
                # Determine and store the market type based on the instrument
                market = self._detect_market(instrument) if instrument else 'forex'
                context.user_data['market'] = market
                logger.info(f"Stored context for back navigation: analysis_type=sentiment, market={market}")
            
            # Log what we're doing
            logger.info(f"Toon sentiment analyse voor {instrument}")
            
            # Get sentiment analysis from the service
            sentiment = await self.get_sentiment_analysis(instrument)
            
            # Create button to go back - choose back_to_signal if coming from a signal
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_instrument_sentiment")]
            ]
            
            # Send the sentiment analysis
            await query.edit_message_text(
                text=sentiment,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            return SHOW_RESULT
            
        except Exception as e:
            logger.error(f"Error in show_sentiment_analysis: {str(e)}")
            logger.exception(e)
            
            # Send fallback message
            try:
                await query.edit_message_text(
                    text=f"Sorry, I couldn't analyze sentiment for {instrument} at this time. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_instrument_sentiment")
                    ]])
                )
            except Exception as inner_e:
                logger.error(f"Failed to send fallback message: {str(inner_e)}")
            
            return MENU

    async def show_economic_calendar(self, update: Update, context=None, instrument: str = None) -> int:
        """Show economic calendar for a specific instrument"""
        query = update.callback_query
        
        try:
            # Check if we're coming from a signal
            is_from_signal = False
            if context and hasattr(context, 'user_data'):
                is_from_signal = context.user_data.get('from_signal', False)
                
            # First, show a loading message
            await query.edit_message_text(
                text=f"Fetching economic calendar for {instrument if instrument else 'global markets'}. Please wait..."
            )
            
            # Log what we're doing
            logger.info(f"Toon economic calendar voor {instrument if instrument else 'global markets'}")
            
            try:
                # Get calendar data
                calendar_data = await self.calendar.get_instrument_calendar(instrument or "GLOBAL")
                
                # Create button to go back
                keyboard = [
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_instrument")]
                ]
                
                # Send the calendar analysis
                await query.edit_message_text(
                    text=calendar_data,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                return SHOW_RESULT
                
            except Exception as e:
                logger.error(f"Error getting calendar data: {str(e)}")
                logger.exception(e)
                
                # Show error message
                await query.edit_message_text(
                    text=f"Sorry, I couldn't retrieve the economic calendar at this time. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_instrument")
                    ]])
                )
                
                return MENU
            
        except Exception as e:
            logger.error(f"Error in show_economic_calendar: {str(e)}")
            logger.exception(e)
            
            # Show error message
            try:
                await query.edit_message_text(
                    text=f"Sorry, I couldn't retrieve the economic calendar at this time. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_instrument")
                    ]])
                )
            except Exception as inner_e:
                logger.error(f"Failed to send fallback message: {str(inner_e)}")
            
            return MENU

    def _format_signal_message(self, instrument, direction, price, stop_loss, take_profits, timeframe='1h', strategy='Unknown'):
        """Format a signal message in a standardized way"""
        try:
            # Determine emoji for direction
            direction = str(direction).upper()
            direction_emoji = "📈" if direction == "BUY" else "📉"
            
            # Format take profits
            tp_lines = []
            if isinstance(take_profits, list) and take_profits:
                for i, tp in enumerate(take_profits, 1):
                    # Handle price formatting manually since we can't call async methods from sync
                    if isinstance(tp, str):
                        tp_formatted = tp
                    else:
                        # Basic formatting without async call
                        try:
                            if 'JPY' in str(instrument):
                                tp_formatted = f"{float(tp):.3f}"
                            else:
                                tp_formatted = f"{float(tp):.5f}"
                        except:
                            tp_formatted = str(tp)
                    
                    tp_lines.append(f"Take Profit {i}: {tp_formatted} 🎯")
            
            tp_text = "\n".join(tp_lines) if tp_lines else "No take profit levels defined"
            
            # Format price and stop loss without async calls
            if isinstance(price, str):
                price_formatted = price
            else:
                try:
                    if 'JPY' in str(instrument):
                        price_formatted = f"{float(price):.3f}"
                    else:
                        price_formatted = f"{float(price):.5f}"
                except:
                    price_formatted = str(price)
                    
            if isinstance(stop_loss, str):
                sl_formatted = stop_loss
            else:
                try:
                    if 'JPY' in str(instrument):
                        sl_formatted = f"{float(stop_loss):.3f}"
                    else:
                        sl_formatted = f"{float(stop_loss):.5f}"
                except:
                    sl_formatted = str(stop_loss)
            
            # Create message in the same format as original signals
            signal_message = (
                f"🎯 Trading Signal 🎯\n\n"
                f"Instrument: {instrument}\n"
                f"Action: {direction} {direction_emoji}\n\n"
                f"Entry Price: {price_formatted}\n"
                f"Stop Loss: {sl_formatted} 🔴\n"
                f"{tp_text}\n\n"
                f"Timeframe: {timeframe}\n"
                f"Strategy: {strategy}\n\n"
                f"————————————————————\n\n"
                f"Risk Management:\n"
                f"• Position size: 1-2% max\n"
                f"• Use proper stop loss\n"
                f"• Follow your trading plan\n\n"
                f"————————————————————\n\n"
                f"🤖 SigmaPips AI"
            )
            
            return signal_message
        except Exception as e:
            logger.error(f"Error formatting signal message: {str(e)}", exc_info=True)
            return f"Trading Signal for {instrument}"
            
    def _get_formatted_timestamp(self):
        """Get current timestamp formatted in a human-readable way"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
    async def _format_price(self, price):
        """Format price with appropriate number of decimal places"""
        try:
            if isinstance(price, str):
                price = float(price)
            
            # Format with 5 decimal places for most forex, 2 for JPY pairs
            if 'JPY' in str(price):
                return f"{price:.3f}"
            else:
                return f"{price:.5f}"
        except:
            return str(price)

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
        
        # Clear transition between flows - guarantee proper flow state
        if context and hasattr(context, 'user_data'):
            # Main menu flows - explicitly mark when starting main menu flows
            if query.data == "menu_analyse" or query.data == "menu_signals" or query.data == "back_menu":
                if context.user_data.get('in_signals_flow', False) == True:
                    # We're switching from signal flow to menu flow - clean up signal context
                    context.user_data['in_signals_flow'] = False
                    logger.info("Transition from signal flow to menu flow - cleaning up signal context")
                    # Clear signal-related context
                    for key in ['from_signal', 'previous_state', 'signal_message', 'from_signal_message']:
                        if key in context.user_data:
                            del context.user_data[key]
            
            # Signal flows - explicitly mark when starting signal flow
            elif query.data.startswith("analyze_from_signal_") or query.data == "back_to_signal":
                context.user_data['in_signals_flow'] = True
                logger.info("Transition to signal flow")
                
                # Special handling for back_to_signal - check if we're coming from a photo message
                if query.data == "back_to_signal":
                    current_message_id = query.message.message_id
                    photo_message_id = context.user_data.get('photo_message_id')
                    
                    if photo_message_id and current_message_id == photo_message_id:
                        logger.info(f"Back to signal request from photo message (ID: {current_message_id})")
                        context.user_data['from_photo'] = True
                    
                    # Also check if the message has a photo (another way to detect)
                    if hasattr(query.message, 'photo') and query.message.photo:
                        logger.info(f"Back to signal request from a message with photo")
                        context.user_data['from_photo'] = True
                        
                    # If we're coming from a message with caption, it's likely a photo too
                    if hasattr(query.message, 'caption') and query.message.caption:
                        logger.info(f"Back to signal request from a message with caption: {query.message.caption}")
                        context.user_data['from_photo'] = True
                        
                    if context.user_data.get('from_photo', False):
                        logger.info("Setting from_photo=True for back_to_signal navigation")

    async def show_technical_analysis(self, update: Update, context=None, instrument: str = None, timeframe: str = "1h", fullscreen: bool = False) -> int:
        """Show technical analysis for a specific instrument"""
        query = update.callback_query
        
        try:
            # Check if we're coming from a signal
            is_from_signal = False
            if context and hasattr(context, 'user_data'):
                is_from_signal = context.user_data.get('from_signal', False)
                logger.info(f"Technical analysis request - is_from_signal: {is_from_signal}")
                
                # Store the current message ID and chat ID for later reference
                if is_from_signal:
                    context.user_data['technical_message_id'] = query.message.message_id
                    context.user_data['technical_chat_id'] = query.message.chat_id
                    logger.info(f"Stored technical analysis message info: message_id={query.message.message_id}")
            
            # First, show a loading message
            await query.edit_message_text(
                text=f"Generating technical analysis for {instrument}. Please wait..."
            )
            
            # Generate the chart using the chart service
            try:
                # Generate chart image using get_chart instead of generate_chart
                chart_data = await self.chart.get_chart(instrument, timeframe=timeframe, fullscreen=fullscreen)
                
                if not chart_data:
                    # If chart generation fails, send a text message
                    logger.error(f"Failed to generate chart for {instrument}")
                    await query.edit_message_text(
                        text=f"Sorry, I couldn't generate a chart for {instrument} at this time. Please try again later.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Back to Signal" if is_from_signal else "⬅️ Back", 
                                                callback_data="back_to_signal" if is_from_signal else "back_instrument")
                        ]])
                    )
                    return MENU
                
                # Create caption with analysis
                caption = f"<b>Technical Analysis for {instrument}</b>"
                
                # Add buttons for different actions - back button depends on where we came from
                keyboard = [
                    [InlineKeyboardButton("⬅️ Back to Signal" if is_from_signal else "⬅️ Back", 
                                         callback_data="back_to_signal" if is_from_signal else "back_instrument")]
                ]
                
                # Send the chart with caption
                from io import BytesIO
                photo = BytesIO(chart_data)
                photo.name = f"{instrument}_chart.png"
                
                # Send the photo and get the sent message
                sent_photo = await query.message.reply_photo(
                    photo=photo,
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                # Store the sent photo message ID in context for possible reference later
                if context and hasattr(context, 'user_data'):
                    context.user_data['photo_message_id'] = sent_photo.message_id
                    context.user_data['photo_chat_id'] = sent_photo.chat_id
                    # Explicitly set from_photo flag to True
                    context.user_data['from_photo'] = True
                    logger.info(f"Stored photo message info: message_id={sent_photo.message_id}, and set from_photo=True")
                    
                    # Make sure we retain the "in_signals_flow" flag if we were in a signal
                    if is_from_signal:
                        context.user_data['in_signals_flow'] = True
                        logger.info("Retained in_signals_flow=True after sending photo")
                
                # Edit the original message to indicate the analysis was sent
                await query.edit_message_text(
                    text=f"Here's your technical analysis for {instrument}:",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Signal" if is_from_signal else "⬅️ Back", 
                                           callback_data="back_to_signal" if is_from_signal else "back_instrument")
                    ]])
                )
                
            except Exception as chart_error:
                logger.error(f"Error generating chart: {str(chart_error)}")
                logger.exception(chart_error)
                await query.edit_message_text(
                    text=f"Sorry, there was a problem generating the chart for {instrument}. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Signal" if is_from_signal else "⬅️ Back", 
                                           callback_data="back_to_signal" if is_from_signal else "back_instrument")
                    ]])
                )
            
            return SHOW_RESULT
        except Exception as e:
            logger.error(f"Error in show_technical_analysis: {str(e)}")
            logger.exception(e)
            
            # Send fallback message
            try:
                await query.edit_message_text(
                    text=f"Sorry, I couldn't analyze {instrument} at this time. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_instrument")
                    ]])
                )
            except Exception as inner_e:
                logger.error(f"Failed to send fallback message: {str(inner_e)}")
            
            return MENU
