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
SHOW_RESULT = 4
CHOOSE_TIMEFRAME = 5
SIGNAL_DETAILS = 6
SUBSCRIBE = 7

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
            self._register_handlers()
            
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
            signals_to_save = {str(k): v for k, v in self.user_signals.items()}
            with open('data/signals.json', 'w') as f:
                json.dump(signals_to_save, f)
            logger.info(f"Saved {len(self.user_signals)} signals to file")
        except Exception as e:
            logger.error(f"Error saving signals: {str(e)}")
            
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

    def _register_handlers(self):
        """Register all command and callback handlers with the application"""
        # Ensure application is initialized
        if not self.application:
            logger.error("Cannot register handlers: application not initialized")
            return
        
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("menu", self.show_main_menu))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("set_subscription", self.set_subscription_command))
        
        # Register the payment failed command with both underscore and no-underscore versions
        self.application.add_handler(CommandHandler("set_payment_failed", self.set_payment_failed_command))
        self.application.add_handler(CommandHandler("setpaymentfailed", self.set_payment_failed_command))
        
        # Callback query handler for all button presses
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        
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
        
        try:
            # Debug logging
            logger.info("analysis_technical_callback aangeroepen")
            
            # Store analysis type in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'technical'
                
                # Check if we have an instrument from signal
                if context.user_data.get('from_signal') and context.user_data.get('instrument'):
                    instrument = context.user_data.get('instrument')
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
        
        try:
            # Debug logging
            logger.info("analysis_sentiment_callback aangeroepen")
            
            # Store analysis type in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'sentiment'
                
                # Check if we have an instrument from signal
                if context.user_data.get('from_signal') and context.user_data.get('instrument'):
                    instrument = context.user_data.get('instrument')
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
        
        try:
            # Debug logging
            logger.info("analysis_calendar_callback aangeroepen")
            
            # Store analysis type in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'calendar'
                
                # Check if we have an instrument from signal
                if context.user_data.get('from_signal') and context.user_data.get('instrument'):
                    instrument = context.user_data.get('instrument')
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
        """Handle back_to_signal callback to return to signal message"""
        query = update.callback_query
        await query.answer()
        
        # Get user ID for tracking purposes
        user_id = update.effective_user.id
        logger.info(f"Back to signal callback invoked by user {user_id}")
        
        try:
            # Try to retrieve the original message ID and chat ID from context
            if context and hasattr(context, 'user_data'):
                instrument = context.user_data.get('instrument', '')
                original_message_id = context.user_data.get('message_id')
                chat_id = context.user_data.get('chat_id')
                logger.info(f"Retrieved from context - message_id: {original_message_id}, chat_id: {chat_id}, instrument: {instrument}")
                
                # Check if we have the original signal in user_signals
                if user_id in self.user_signals:
                    signal_data = self.user_signals[user_id]
                    logger.info(f"Found signal data for user {user_id}: {signal_data}")
                    
                    # Check if instrument matches or if message_id matches
                    if signal_data.get('instrument') == instrument or signal_data.get('message_id') == original_message_id:
                        # We found the matching signal - use its message if available
                        if 'message' in signal_data and signal_data['message']:
                            logger.info(f"Using stored signal message for user {user_id}")
                            message = signal_data['message']
                            
                            # Recreate the original keyboard
                            keyboard = [
                                [
                                    InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_from_signal_{instrument}")
                                ]
                            ]
                            
                            # Edit message to original signal
                            await query.edit_message_text(
                                text=message,
                                reply_markup=InlineKeyboardMarkup(keyboard),
                                parse_mode=ParseMode.HTML
                            )
                            return SIGNAL
                        else:
                            logger.warning(f"Signal data found but no message for user {user_id}")
                    else:
                        logger.warning(f"Instrument mismatch in signal data. Context: {instrument}, Stored: {signal_data.get('instrument')}")
            
            # Fallback: recreate a basic signal message from context data if available
            logger.info(f"Falling back to recreating signal from context data for user {user_id}")
            
            if context and hasattr(context, 'user_data'):
                # Extract all possible signal data from context
                instrument = context.user_data.get('instrument', 'Unknown')
                direction = context.user_data.get('direction', 'UNKNOWN')
                price = context.user_data.get('price', 'N/A')
                stop_loss = context.user_data.get('stop_loss', 'N/A')
                tp1 = context.user_data.get('tp1', 'N/A')
                timeframe = context.user_data.get('timeframe', '1h')
                strategy = context.user_data.get('strategy', 'Unknown')
                
                # Create a simple fallback message
                emoji = "🟢" if direction == "BUY" else "🔴" if direction == "SELL" else "⚪"
                
                fallback_message = (
                    f"<b>{emoji} SIGNAL {direction} {instrument}</b>\n"
                    f"<b>Price:</b> {price}\n"
                    f"<b>Stop Loss:</b> {stop_loss}\n"
                    f"<b>Take Profit:</b> {tp1}\n"
                    f"<b>Timeframe:</b> {timeframe}\n"
                    f"<b>Strategy:</b> {strategy}\n"
                    f"\n<i>Note: This is a recreated signal as the original could not be found.</i>"
                )
                
                keyboard = [
                    [
                        InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_from_signal_{instrument}")
                    ]
                ]
                
                await query.edit_message_text(
                    text=fallback_message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Created fallback signal message for {instrument} for user {user_id}")
                return SIGNAL
            
            # Ultimate fallback if we can't recreate a proper signal
            logger.warning(f"Could not retrieve or recreate signal for user {user_id}, returning to menu")
            await query.edit_message_text(
                text="Sorry, I couldn't find the original signal. Please return to the main menu.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]])
            )
            return MENU
            
        except Exception as e:
            logger.error(f"Error in back_to_signal_callback: {str(e)}", exc_info=True)
            # Send an error message
            await query.edit_message_text(
                text="Sorry, an error occurred while trying to return to the signal. Please try again or go back to the main menu.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]])
            )
            return MENU

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Show the main menu with all bot features"""
        user_id = update.effective_user.id
        
        # Check if the user has a subscription
        is_subscribed = await self.db.is_user_subscribed(user_id)
        
        # Check if payment has failed
        payment_failed = await self.db.has_payment_failed(user_id)
        
        if not is_subscribed or payment_failed:
            # Bot to use for sending messages
            bot = context.bot if context is not None else self.bot
            
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
                
                await bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=failed_payment_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                # Show the welcome message with trial option for non-subscribed users
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
                
                await bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=welcome_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            return
        
        # Show the normal menu with all options for subscribed users
        reply_markup = InlineKeyboardMarkup(START_KEYBOARD)
        
        # Use context.bot if available, otherwise use self.bot
        bot = context.bot if context is not None else self.bot
        
        await bot.send_message(
            chat_id=update.effective_chat.id,
            text=WELCOME_MESSAGE,
            parse_mode='HTML',
            reply_markup=reply_markup
        )

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
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
        
        # Analysis type handlers
        if query.data.startswith("analysis_"):
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
            
        if query.data == "signals_manage" or query.data == CALLBACK_SIGNALS_MANAGE:
            return await self.signals_manage_callback(update, context)
            
        if query.data == "remove_subscriptions":
            return await self.remove_subscriptions_callback(update, context)
        
        if query.data.startswith("delete_subscription_"):
            return await self.delete_subscription_callback(update, context)
        
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
            
        return MENU

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

    # Voeg de decorator toe aan relevante functies
    @require_subscription
    async def market_choice(self, update: Update, context=None) -> int:
        keyboard = []
        markets = ["forex", "crypto", "indices", "commodities"]
        
        for market in markets:
            keyboard.append([InlineKeyboardButton(market.capitalize(), callback_data=f"market_{market}")])
        
        keyboard.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Choose a market:", reply_markup=reply_markup)
        return MARKET_CHOICE

    @require_subscription
    async def instrument_callback(self, update: Update, context=None) -> int:
        """Handle instrument selection"""
        query = update.callback_query
        data = query.data
        
        # Check if this is actually a market selection (e.g., market_forex_sentiment) instead of an instrument
        if data.startswith('market_'):
            logger.info(f"Redirecting market selection to market_callback: {data}")
            return await self.market_callback(update, context)
        
        # Extract instrument from callback data
        parts = data.split('_')
        instrument = parts[1]
        analysis_type = parts[2] if len(parts) > 2 else "chart"  # Default naar 'chart' als niet gespecificeerd
        
        # Debug logging
        logger.info(f"Instrument callback: instrument={instrument}, analysis_type={analysis_type}, callback_data={data}")
        
        try:
            await query.answer()
            
            # Store the analysis type and instrument in context for future reference
            if context and hasattr(context, 'user_data'):
                # Store analysis type to ensure proper back button navigation
                if analysis_type == "sentiment":
                    context.user_data['analysis_type'] = 'sentiment'
                elif analysis_type == "chart":
                    context.user_data['analysis_type'] = 'technical'
                elif analysis_type == "calendar":
                    context.user_data['analysis_type'] = 'calendar'
                
                # Store the detected market type based on instrument
                market = self._detect_market(instrument)
                context.user_data['market'] = market
                
                # Add debug log to see what's being stored in context
                logger.info(f"Stored in context: analysis_type={context.user_data.get('analysis_type')}, market={context.user_data.get('market')}")
            
            # Maak de juiste analyse op basis van het type
            if analysis_type == "chart":
                logger.info(f"Toon technische analyse (chart) voor {instrument}")
                await self.show_technical_analysis(update, context, instrument, timeframe="1h", fullscreen=True)
                return CHOOSE_TIMEFRAME
            elif analysis_type == "sentiment":
                logger.info(f"Toon sentiment analyse voor {instrument}")
                # Always use show_sentiment_analysis for sentiment, never show_technical_analysis
                await self.show_sentiment_analysis(update, context, instrument)
                return SHOW_RESULT
            elif analysis_type == "calendar":
                logger.info(f"Toon economische kalender voor {instrument}")
                await self.show_economic_calendar(update, context, instrument)
                return CHOOSE_TIMEFRAME
            else:
                # Als het type niet herkend wordt, toon technische analyse als fallback
                logger.info(f"Onbekend analyse type: {analysis_type}, toon technische analyse voor {instrument}")
                await self.show_technical_analysis(update, context, instrument, fullscreen=True)
                return CHOOSE_TIMEFRAME
        except Exception as e:
            logger.error(f"Error in instrument_callback: {str(e)}")
            logger.exception(e)
            return MENU

    async def send_message_to_user(self, user_id: int, text: str, reply_markup=None, parse_mode=ParseMode.HTML):
        """Stuur een bericht naar een specifieke gebruiker"""
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            logger.error(f"Error sending message to user {user_id}: {str(e)}")
            return False

    # Zoek of voeg deze functie toe aan de TelegramService class
    async def handle_subscription_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Process subscription button clicks"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "subscribe_monthly":
            user_id = query.from_user.id
            
            # Use the Stripe checkout URL provided by the user
            checkout_url = "https://buy.stripe.com/3cs3eF9Hu9256NW9AA"
            
            # Create keyboard with checkout link
            keyboard = [
                [InlineKeyboardButton("🔥 Start Trial", url=checkout_url)]
            ]
            
            await query.edit_message_text(
                text="""
✨ <b>Almost ready!</b> ✨

Click the button below to start your FREE 14-day trial.

- No obligations during trial
- Cancel anytime
- After 14 days, regular rate of $29.99/month will be charged if you don't cancel
            """,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return SUBSCRIBE
            
        elif query.data == "subscription_info":
            # Show more information about the subscription
            subscription_features = get_subscription_features("monthly")
            
            info_text = f"""
💡 <b>SigmaPips Trading Signals - Subscription Details</b> 💡

<b>Price:</b> {subscription_features.get('price')}
<b>Trial period:</b> 14 days FREE

<b>Included signals:</b>
"""
            for signal in subscription_features.get('signals', []):
                info_text += f"✅ {signal}\n"
                
            info_text += f"""
<b>Timeframes:</b> {', '.join(subscription_features.get('timeframes', []))}

<b>How it works:</b>
1. Start your free trial
2. Get immediate access to all signals
3. Easily cancel before day 14 if not satisfied
4. No cancellation = automatic renewal at $29.99/month
            """
            
            keyboard = [
                [InlineKeyboardButton("🔥 Start FREE Trial", callback_data="subscribe_monthly")]
            ]
            
            await query.edit_message_text(
                text=info_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return SUBSCRIBE

        return MENU

    async def get_sentiment_analysis(self, instrument: str) -> str:
        """Get sentiment analysis for a specific instrument"""
        try:
            # In a real implementation, this would call an external API or use ML models
            # For now, return mock data
            sentiment_data = self._generate_mock_sentiment_data(instrument)
            return self._format_sentiment_data(instrument, sentiment_data)
        except Exception as e:
            logger.error(f"Error getting sentiment analysis: {str(e)}")
            return self._get_fallback_sentiment(instrument)
    
    def _generate_mock_sentiment_data(self, instrument: str) -> Dict:
        """Generate mock sentiment data for demo purposes"""
        import random
        
        # Extract currencies from instrument
        currencies = []
        common_currencies = ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"]
        for currency in common_currencies:
            if currency in instrument:
                currencies.append(currency)
        
        # Generate random sentiment scores (weighted towards neutral-slightly bullish)
        bull_score = random.uniform(45, 65)
        bear_score = 100 - bull_score
        
        # Generate random sentiment changes
        bull_change = random.uniform(-5, 10)
        
        # Generate random pressure data
        buy_pressure = random.uniform(40, 70)
        sell_pressure = 100 - buy_pressure
        
        # Generate random volume data
        volume_change = random.uniform(-10, 20)
        
        # Generate key levels
        current_price = random.uniform(1.0, 1.5) if "USD" in instrument and "EUR" in instrument else random.uniform(100, 150)
        resistance = current_price * (1 + random.uniform(0.01, 0.05))
        support = current_price * (1 - random.uniform(0.01, 0.05))
        
        # Generate random news sentiment
        news_count = random.randint(5, 15)
        news_sentiment = random.uniform(-1, 1)
        
        return {
            "instrument": instrument,
            "currencies": currencies,
            "bull_score": bull_score,
            "bear_score": bear_score,
            "bull_change": bull_change,
            "buy_pressure": buy_pressure,
            "sell_pressure": sell_pressure,
            "volume_change": volume_change,
            "current_price": current_price,
            "resistance": resistance,
            "support": support,
            "news_count": news_count,
            "news_sentiment": news_sentiment,
            "timestamp": datetime.now()
        }
    
    def _format_sentiment_data(self, instrument: str, data: Dict) -> str:
        """Format sentiment data into a readable message"""
        bull_score = data.get("bull_score", 50)
        bear_score = data.get("bear_score", 50)
        bull_change = data.get("bull_change", 0)
        buy_pressure = data.get("buy_pressure", 50)
        sell_pressure = data.get("sell_pressure", 50)
        volume_change = data.get("volume_change", 0)
        current_price = data.get("current_price", 0)
        resistance = data.get("resistance", 0)
        support = data.get("support", 0)
        news_count = data.get("news_count", 0)
        news_sentiment = data.get("news_sentiment", 0)
        timestamp = data.get("timestamp", datetime.now())
        
        # Determine overall sentiment
        overall = "Bullish" if bull_score > 60 else "Bearish" if bull_score < 40 else "Neutral"
        sentiment_emoji = "🟢" if bull_score > 60 else "🔴" if bull_score < 40 else "⚪"
        
        # Format change indicators
        change_arrow = "↗️" if bull_change > 0 else "↘️" if bull_change < 0 else "↔️"
        volume_arrow = "↗️" if volume_change > 0 else "↘️" if volume_change < 0 else "↔️"
        
        # Format the message
        message = f"<b>📊 Market Sentiment Analysis: {instrument}</b>\n\n"
        
        # Overall sentiment
        message += f"<b>Overall Sentiment:</b> {sentiment_emoji} {overall}\n"
        message += f"<b>Last Updated:</b> {timestamp.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        
        # Sentiment breakdown
        message += "<b>Sentiment Breakdown:</b>\n"
        message += f"Bullish: {bull_score:.1f}% {change_arrow} ({bull_change:+.1f}%)\n"
        message += f"Bearish: {bear_score:.1f}%\n\n"
        
        # Market pressure
        message += "<b>Market Pressure:</b>\n"
        message += f"Buy Pressure: {buy_pressure:.1f}%\n"
        message += f"Sell Pressure: {sell_pressure:.1f}%\n\n"
        
        # Volume analysis
        message += "<b>Volume Analysis:</b>\n"
        message += f"Volume Change (24h): {volume_arrow} {volume_change:+.1f}%\n\n"
        
        # Key levels
        message += "<b>Key Price Levels:</b>\n"
        message += f"Current: {current_price:.5f}\n"
        message += f"Resistance: {resistance:.5f}\n"
        message += f"Support: {support:.5f}\n\n"
        
        # News sentiment
        news_sentiment_text = "Positive" if news_sentiment > 0.3 else "Negative" if news_sentiment < -0.3 else "Neutral"
        news_emoji = "📈" if news_sentiment > 0.3 else "📉" if news_sentiment < -0.3 else "📊"
        message += "<b>News Sentiment:</b>\n"
        message += f"{news_emoji} {news_sentiment_text} ({news_count} articles analyzed)\n\n"
        
        return message
    
    def _get_fallback_sentiment(self, instrument: str) -> str:
        """Get fallback sentiment in case of error"""
        return f"""<b>📊 Market Sentiment Analysis: {instrument}</b>

<i>Unable to fetch real-time sentiment data. Here is a general market overview:</i>

<b>Overall Sentiment:</b> ⚪ Neutral
<b>Last Updated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}

<b>Market Overview:</b>
• Mixed trading activity across major markets
• Volume levels are within normal ranges
• Volatility indicators show neutral conditions

<i>Note: This is a general overview and not instrument-specific analysis.</i>
"""

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
            self._register_handlers()
                
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

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Send a help message when the command /help is issued."""
        await update.message.reply_text(
            text=HELP_MESSAGE,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]
            ])
        )
        
    async def process_signal(self, signal_data: dict, users=None, test_mode=False) -> bool:
        """Process incoming signal and send to users"""
        try:
            # Log more visible test message for verification
            logger.info("="*50)
            logger.info(f"SIGNAL TEST: Successfully received signal for processing")
            logger.info(f"SIGNAL DATA: {json.dumps(signal_data, indent=2)}")
            logger.info("="*50)
            
            # Check if signals are enabled (add fallback)
            try:
                if not getattr(self, '_signals_enabled', True):
                    logger.warning("Signal processing is disabled")
                    return False
            except Exception as attr_e:
                logger.warning(f"Error checking signals_enabled, proceeding anyway: {str(attr_e)}")
            
            # Regular processing log
            logger.info(f"Processing signal: {signal_data}")
            
            # Handle TradingView format conversion (tp1, tp2, tp3, sl -> take_profits, stop_loss)
            # Check if we need to convert from TradingView format
            if 'tp1' in signal_data or 'sl' in signal_data:
                take_profits = []
                
                # Add all available TP levels
                if 'tp1' in signal_data and signal_data['tp1']:
                    take_profits.append(float(signal_data['tp1']))
                if 'tp2' in signal_data and signal_data['tp2']:
                    take_profits.append(float(signal_data['tp2']))
                if 'tp3' in signal_data and signal_data['tp3']:
                    take_profits.append(float(signal_data['tp3']))
                
                # Convert sl to stop_loss
                stop_loss = None
                if 'sl' in signal_data and signal_data['sl']:
                    stop_loss = float(signal_data['sl'])
                
                # Update signal data with converted format
                signal_data['take_profits'] = take_profits
                if stop_loss:
                    signal_data['stop_loss'] = stop_loss
                    
                logger.info(f"Converted TradingView format to internal format: {signal_data}")
                
            # Extract required fields with validation
            required_fields = ['instrument', 'signal', 'price']
            missing_fields = [field for field in required_fields if field not in signal_data or not signal_data[field]]
            
            if missing_fields:
                logger.error(f"Missing required signal data: {missing_fields}")
                return False
            
            # Extract signal components
            instrument = signal_data.get('instrument', '').upper()
            direction = signal_data.get('signal', '').upper()
            price = float(signal_data.get('price', 0))
            
            # Extract optional fields with fallbacks
            take_profits = signal_data.get('take_profits', [])
            stop_loss = signal_data.get('stop_loss', 0)
            interval = signal_data.get('interval', '1h')
            strategy = signal_data.get('strategy', 'Unknown')
            market = signal_data.get('market', self._detect_market(instrument))
            
            # Get relevant users
            if users is None:
                users = await self._get_signal_subscribers(market, instrument)
            
            logger.info(f"Subscribers for {market}/{instrument}: {users}")
            
            # Add admin users for testing
            if test_mode and hasattr(self, 'admin_users') and self.admin_users:
                logger.info(f"Adding admin users for testing: {self.admin_users}")
                users.extend(self.admin_users)
            
            if not users:
                logger.warning(f"No subscribers found for {market}/{instrument}")
                return True  # Return True because signal was processed successfully (just no subscribers)
            
            # Format take profits for display
            tp_values = []
            for i, tp in enumerate(take_profits, 1):
                tp_formatted = self._format_price(tp)
                tp_values.append(f"TP{i}: {tp_formatted}")
            
            tp_text = "\n".join(tp_values) if tp_values else "No take profit levels defined"
            
            # Generate emoji based on signal direction
            emoji = "🟢" if direction == "BUY" else "🔴" if direction == "SELL" else "⚪"
            
            # Generate verdict using sentiment and chart analysis
            verdict = "Signal analysis not available"
            try:
                verdict_result = await self._generate_signal_verdict(
                    instrument, 
                    direction, 
                    price, 
                    stop_loss, 
                    take_profits[0] if take_profits else 0,
                    take_profits[1] if len(take_profits) > 1 else 0,
                    take_profits[2] if len(take_profits) > 2 else 0,
                    interval
                )
                if verdict_result:
                    verdict = verdict_result
            except Exception as e:
                logger.error(f"Error generating verdict: {e}")
            
            # Format the message
            timestamp = self._get_formatted_timestamp()
            
            message = (
                f"<b>{emoji} SIGNAL {direction} {instrument}</b>\n\n"
                f"<b>Entry price:</b> {self._format_price(price)}\n"
                f"<b>Stop loss:</b> {self._format_price(stop_loss)}\n\n"
                f"{tp_text}\n\n"
                f"<b>Timeframe:</b> {interval}\n"
                f"<b>Strategy:</b> {strategy}\n"
                f"<b>Time:</b> {timestamp}\n\n"
                f"<b>Analysis:</b>\n{verdict}"
            )
            
            # Create keyboard for signal message
            keyboard = [
                [
                    InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_from_signal_{instrument}")
                ]
            ]
            
            # Store signal for each user
            for user_id in users:
                try:
                    # Store signal information for later use
                    self.user_signals[user_id] = {
                        'instrument': instrument,
                        'direction': direction,
                        'price': price,
                        'stop_loss': stop_loss,
                        'take_profits': take_profits,
                        'message': message,
                        'timestamp': timestamp,
                        'timeframe': interval,
                        'strategy': strategy
                    }
                    
                    # Send the signal
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    logger.info(f"Signal sent to user {user_id}")
                    
                except BadRequest as e:
                    logger.error(f"Bad request error processing signal: {str(e)}")
                except TelegramError as e:
                    logger.error(f"Error processing signal: {str(e)}")
                except Exception as e:
                    logger.error(f"Unexpected error sending signal to user {user_id}: {str(e)}")
            
            # Save signals
            self._save_signals()
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing signal: {str(e)}")
            logger.exception(e)
            return False

    async def _generate_signal_verdict(self, instrument: str, direction: str, price: float, stop_loss: float, tp1: float, tp2: float, tp3: float, timeframe: str) -> str:
        """Generate AI verdict for a trading signal"""
        try:
            # Create a simple verdict based on the signal parameters
            risk = abs(float(price) - float(stop_loss))
            reward = abs(float(tp1) - float(price)) if tp1 else 0
            
            if direction == "BUY":
                verdict = f"The {instrument} buy signal shows a promising setup with defined entry at {price} and stop loss at {stop_loss}."
            else:
                verdict = f"The {instrument} sell signal presents a strategic opportunity with entry at {price} and stop loss at {stop_loss}."
                
            # Add take profit analysis
            if tp1 and tp2 and tp3:
                verdict += f" Multiple take profit levels provide opportunities for partial profit taking."
            elif tp1:
                verdict += f" The take profit target suggests a favorable risk-to-reward ratio."
                
            # Add timeframe context
            if timeframe == "1h" or timeframe == "1":
                verdict += f" This hourly timeframe signal could provide a short-term trading opportunity."
            elif timeframe == "4h" or timeframe == "4":
                verdict += f" The 4-hour timeframe provides a good balance between noise and meaningful price action."
            elif timeframe == "1d" or timeframe == "D":
                verdict += f" This daily timeframe signal has potential for a longer-term position."
            elif timeframe == "15m" or timeframe == "15":
                verdict += f" This 15-minute timeframe signal may be suitable for scalping or quick trades."
                
            return verdict
            
        except Exception as e:
            logger.error(f"Error generating signal verdict: {str(e)}")
            return f"The {instrument} {direction.lower()} signal shows a defined entry and exit strategy. Consider this setup within your overall trading plan."

    def _detect_market(self, instrument: str) -> str:
        """Detect market type from instrument"""
        # Crypto markers
        if instrument.endswith('USDT') or instrument.endswith('BTC') or instrument.endswith('ETH') or 'BTC' in instrument:
            return 'crypto'
            
        # Forex markers
        if all(c in instrument for c in ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'NZD', 'CAD', 'CHF']):
            return 'forex'
            
        # Indices markers
        if any(idx in instrument for idx in ['SPX', 'NDX', 'DJI', 'FTSE', 'DAX', 'CAC', 'NIKKEI']):
            return 'indices'
            
        # Commodities markers
        if any(com in instrument for com in ['GOLD', 'XAU', 'SILVER', 'XAG', 'OIL', 'GAS', 'USOIL']):
            return 'commodities'
            
        # Default to forex
        return 'forex'
        
    def _format_price(self, price) -> str:
        """Format price value for display"""
        try:
            # Convert to float if it's not already
            price_val = float(price)
            
            # Format with appropriate precision based on value
            if price_val < 0.01:
                return f"{price_val:.8f}"
            elif price_val < 1:
                return f"{price_val:.4f}"
            elif price_val < 100:
                return f"{price_val:.2f}"
            else:
                return f"{price_val:.0f}"
        except (ValueError, TypeError):
            # If conversion fails, return as is
            return str(price)
            
    def _get_formatted_timestamp(self) -> str:
        """Get formatted timestamp for signals"""
        now = datetime.now()
        return now.strftime("%d-%b-%Y %H:%M UTC")
        
    async def _get_signal_subscribers(self, market: str, instrument: str) -> List[int]:
        """Get list of subscribers for a specific market and instrument"""
        try:
            # Haal alle subscribers op
            response = await self.db.get_subscribers()
            
            # Check if the response is valid and has data
            if not hasattr(response, 'data') or not response.data:
                logger.info(f"No subscribers found in database")
                return []
                
            all_subscribers = response.data
            logger.info(f"Found {len(all_subscribers)} total subscribers in database")
            
            # Filter subscribers op basis van market en instrument
            matching_subscribers = []
            
            for subscriber in all_subscribers:
                try:
                    # Haal preferences op voor deze subscriber
                    user_id = subscriber['user_id']
                    preferences_response = await self.db.get_subscriber_preferences(user_id)
                    
                    logger.info(f"Checking preferences for user {user_id}")
                    
                    # Log each preference for debugging
                    for pref in preferences_response:
                        pref_market = pref.get('market', '').lower()
                        pref_instrument = pref.get('instrument', '').upper()
                        logger.info(f"User {user_id} has preference: market={pref_market}, instrument={pref_instrument}")
                        
                        # Check if this preference matches our signal
                        is_market_match = pref_market == market.lower()
                        is_instrument_match = pref_instrument == instrument.upper() or pref_instrument == 'ALL'
                        
                        if is_market_match and is_instrument_match:
                            logger.info(f"Found matching preference for user {user_id}: {pref}")
                            matching_subscribers.append(user_id)
                            break
                        else:
                            logger.info(f"No match for user {user_id}: Signal({market.lower()},{instrument.upper()}) vs Pref({pref_market},{pref_instrument})")
                            
                except Exception as inner_e:
                    logger.error(f"Error processing subscriber {subscriber}: {str(inner_e)}")
            
            logger.info(f"Found {len(matching_subscribers)} subscribers matching {market}/{instrument}")
            return matching_subscribers
            
        except Exception as e:
            logger.error(f"Error getting signal subscribers: {str(e)}")
            return []

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
                    
                    # Store the signal in a test file for verification
                    try:
                        os.makedirs('data', exist_ok=True)
                        with open('data/test_signals.json', 'a') as f:
                            f.write(json.dumps(signal_data) + "\n")
                        logger.info(f"TEST SUCCESS: Signal saved to test_signals.json: {signal_data}")
                    except Exception as write_error:
                        logger.error(f"Error saving test signal: {str(write_error)}")
                    
                    # Debug logging for self.signals_enabled property
                    logger.info(f"DEBUG: TelegramService instance attributes: {', '.join(dir(self))}")
                    logger.info(f"DEBUG: _signals_enabled attribute exists: {'_signals_enabled' in dir(self)}")
                    try:
                        logger.info(f"DEBUG: signals_enabled property value: {self.signals_enabled}")
                    except Exception as attr_error:
                        logger.error(f"DEBUG: Error accessing signals_enabled: {str(attr_error)}")
                        
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

    async def back_menu_callback(self, update: Update, context=None) -> int:
        """Handle back_menu callback to return to the main menu"""
        query = update.callback_query
        
        try:
            # Show the main menu
            await query.edit_message_text(
                text=WELCOME_MESSAGE,
                reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                parse_mode=ParseMode.HTML
            )
            
            return MENU
        except Exception as e:
            logger.error(f"Error in back_menu_callback: {str(e)}")
            try:
                await query.message.reply_text(
                    text=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
                return MENU
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                return MENU
                
    async def back_market_callback(self, update: Update, context=None) -> int:
        """Handle back_market callback to return to market selection"""
        query = update.callback_query
        
        try:
            # Get the analysis type if stored in context
            analysis_type = context.user_data.get('analysis_type', 'technical') if context and hasattr(context, 'user_data') else 'technical'
            
            # Choose the correct keyboard based on analysis type
            keyboard = MARKET_KEYBOARD
            
            if analysis_type == 'technical':
                message_text = "Select a market for technical analysis:"
                keyboard = MARKET_KEYBOARD
            elif analysis_type == 'sentiment':
                message_text = "Select a market for sentiment analysis:"
                keyboard = MARKET_SENTIMENT_KEYBOARD
            elif analysis_type == 'calendar':
                message_text = "Select a market for economic calendar:"
                keyboard = MARKET_KEYBOARD
            else:
                message_text = "Select a market:"
                
            # Log the analysis type and keyboard being used
            logger.info(f"Back to market selection with analysis_type={analysis_type}")
                
            # Show the market selection
            await query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return CHOOSE_MARKET
        except Exception as e:
            logger.error(f"Error in back_market_callback: {str(e)}")
            try:
                await query.message.reply_text(
                    text="Select a market:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
                return CHOOSE_MARKET
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                return MENU
                
    async def back_instrument_callback(self, update: Update, context=None) -> int:
        """Handle back_instrument callback to return to instrument selection"""
        query = update.callback_query
        
        try:
            # Default to forex keyboard if no market specified
            market = context.user_data.get('market', 'forex') if context and hasattr(context, 'user_data') else 'forex'
            analysis_type = context.user_data.get('analysis_type', 'technical') if context and hasattr(context, 'user_data') else 'technical'
            
            # Log the context data we're getting here for debugging
            logger.info(f"Back to instrument with context data: market={market}, analysis_type={analysis_type}")
            
            # Check from callback data if this is a sentiment back button
            is_sentiment_back = query.data == "back_instrument_sentiment"
            if is_sentiment_back:
                analysis_type = 'sentiment'
                logger.info(f"Overriding analysis type to 'sentiment' based on callback data: {query.data}")
                # Make sure to update context for future navigation
                if context and hasattr(context, 'user_data'):
                    context.user_data['analysis_type'] = 'sentiment'
            
            # Choose the appropriate keyboard based on market and analysis type
            message_text = f"Select an instrument for {market} "
            keyboard = FOREX_KEYBOARD  # Default
            
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
                
            # Show the instrument selection
            await query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return CHOOSE_INSTRUMENT
        except Exception as e:
            logger.error(f"Error in back_instrument_callback: {str(e)}")
            
            # Try to preserve context even in error condition
            analysis_type = 'technical'  # Default
            
            # Check if this is a sentiment back button
            is_sentiment_back = query.data == "back_instrument_sentiment"
            if is_sentiment_back:
                analysis_type = 'sentiment'
                logger.info("Using sentiment keyboard for error recovery based on callback data")
            elif context and hasattr(context, 'user_data') and 'analysis_type' in context.user_data:
                analysis_type = context.user_data.get('analysis_type', 'technical')
                
            try:
                # Choose appropriate keyboard based on analysis type
                keyboard = FOREX_KEYBOARD  # Default to forex
                message_text = "Select an instrument:"
                
                if analysis_type == 'sentiment':
                    keyboard = FOREX_SENTIMENT_KEYBOARD
                    message_text = "Select an instrument for sentiment analysis:"
                
                await query.message.reply_text(
                    text=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return CHOOSE_INSTRUMENT
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                return MENU

    async def signals_add_callback(self, update: Update, context=None) -> int:
        """Handle signals_add callback to add new signal preferences"""
        query = update.callback_query
        
        try:
            # Show market selection for signals
            await query.edit_message_text(
                text="Select a market for trading signals:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
            )
            
            return CHOOSE_MARKET
        except Exception as e:
            logger.error(f"Error in signals_add_callback: {str(e)}")
            try:
                await query.message.reply_text(
                    text="Select a market for trading signals:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
                )
                return CHOOSE_MARKET
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                return MENU
                
    async def signals_manage_callback(self, update: Update, context=None) -> int:
        """Handle signals_manage callback to manage signal preferences"""
        query = update.callback_query
        
        try:
            # Get user's current subscriptions
            user_id = update.effective_user.id
            preferences = await self.db.get_subscriber_preferences(user_id)
            
            if not preferences:
                # No subscriptions yet
                await query.edit_message_text(
                    text="You don't have any signal subscriptions yet. Add some first!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("➕ Add Signal Pairs", callback_data=CALLBACK_SIGNALS_ADD)],
                        [InlineKeyboardButton("⬅️ Back to Menu", callback_data=CALLBACK_BACK_MENU)]
                    ])
                )
                return CHOOSE_SIGNALS
            
            # Format current subscriptions
            message = "<b>Your Signal Subscriptions:</b>\n\n"
            
            for i, pref in enumerate(preferences, 1):
                market = pref.get('market', 'unknown')
                instrument = pref.get('instrument', 'unknown')
                timeframe = pref.get('timeframe', 'ALL')
                
                message += f"{i}. {market.upper()} - {instrument} ({timeframe})\n"
            
            # Add buttons to manage subscriptions
            keyboard = [
                [InlineKeyboardButton("➕ Add More", callback_data=CALLBACK_SIGNALS_ADD)],
                [InlineKeyboardButton("🗑️ Remove Subscriptions", callback_data="remove_subscriptions")],
                [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_SIGNALS)]
            ]
            
            await query.edit_message_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            return CHOOSE_SIGNALS
        except Exception as e:
            logger.error(f"Error in signals_manage_callback: {str(e)}")
            logger.exception(e)
            
            try:
                await query.edit_message_text(
                    text="An error occurred while retrieving your subscriptions. Please try again.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_SIGNALS)]
                    ])
                )
                return CHOOSE_SIGNALS
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                return MENU

    async def show_technical_analysis(self, update: Update, context=None, instrument: str = None, timeframe: str = "1h", fullscreen: bool = False) -> int:
        """Show technical analysis for a specific instrument"""
        query = update.callback_query
        
        try:
            # Check if we're coming from a signal
            is_from_signal = False
            if context and hasattr(context, 'user_data'):
                is_from_signal = context.user_data.get('from_signal', False)
            
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
                            InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_instrument")
                        ]])
                    )
                    return MENU
                
                # Create caption with analysis
                caption = f"<b>Technical Analysis for {instrument}</b>"
                
                # Add buttons for different actions - back button depends on where we came from
                keyboard = [
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_instrument")]
                ]
                
                # Send the chart with caption
                from io import BytesIO
                photo = BytesIO(chart_data)
                photo.name = f"{instrument}_chart.png"
                
                await query.message.reply_photo(
                    photo=photo,
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                # Delete the loading message
                await query.edit_message_text(
                    text=f"Here's your technical analysis for {instrument}:"
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
            
            # Get sentiment data directly from the sentiment service with a timeout
            try:
                # Use a timeout to prevent hanging
                sentiment_data_task = self.sentiment.get_market_sentiment(instrument)
                sentiment_data = await asyncio.wait_for(sentiment_data_task, timeout=60.0)  # 60 second timeout
                
                logger.info(f"Sentiment data received for {instrument}")
                
                # Extract sentiment data
                bullish_score = sentiment_data.get('bullish_percentage', 50)
                bearish_score = 100 - bullish_score
                overall = sentiment_data.get('overall_sentiment', 'neutral').capitalize()
                
                # Determine emoji based on sentiment
                if overall.lower() == 'bullish':
                    emoji = "📈"
                elif overall.lower() == 'bearish':
                    emoji = "📉"
                else:
                    emoji = "⚖️"
                
                # Get the analysis content
                analysis = sentiment_data.get('analysis', 'Analysis not available')
                
                # Clean up any markdown formatting that might be in the analysis
                analysis = re.sub(r'^```html\s*', '', analysis)
                analysis = re.sub(r'\s*```$', '', analysis)
                
                # Create button to go back - choose back_to_signal if coming from a signal
                keyboard = [
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_instrument_sentiment")]
                ]
                
                # Send the sentiment analysis
                await query.edit_message_text(
                    text=analysis,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                return SHOW_RESULT
                
            except asyncio.TimeoutError:
                logger.error(f"Timeout getting sentiment data for {instrument}")
                return await self._show_sentiment_error(query, instrument, "The sentiment analysis is taking too long. Please try again later.", is_from_signal)
                
            except asyncio.CancelledError:
                logger.warning(f"Sentiment analysis was cancelled for {instrument}")
                return await self._show_sentiment_error(query, instrument, "The sentiment analysis was interrupted. Please try again.", is_from_signal)
                
            except Exception as e:
                logger.error(f"Error getting sentiment data: {str(e)}")
                logger.exception(e)
                return await self._show_sentiment_error(query, instrument, is_from_signal=is_from_signal)
            
        except Exception as e:
            logger.error(f"Error in show_sentiment_analysis: {str(e)}")
            logger.exception(e)

    async def _show_sentiment_error(self, query, instrument, message=None, is_from_signal=False):
        """Show error message when sentiment analysis fails"""
        try:
            error_text = message if message else f"Sorry, I couldn't analyze {instrument} at this time. Please try again later."
            
            await query.edit_message_text(
                text=error_text,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_instrument_sentiment")
                ]])
            )
            
            return MENU
        except Exception as e:
            logger.error(f"Error showing sentiment error: {str(e)}")
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

    async def instrument_signals_callback(self, update: Update, context=None) -> int:
        """Handle instrument selection for signals"""
        query = update.callback_query
        
        try:
            # Extract instrument from callback data
            instrument = query.data.replace('instrument_', '').replace('_signals', '')
            
            # Log the instrument selection
            logger.info(f"Instrument callback for signals: instrument={instrument}")
            
            # Initialize market variable
            market = "forex"  # Default market
            
            # Store the instrument in user context
            if context and hasattr(context, 'user_data'):
                context.user_data['in_signals_flow'] = True
                context.user_data['instrument'] = instrument
                
                # Get the market that was previously selected
                market = context.user_data.get('market')
                if not market:
                    # If market not in context, detect it based on the instrument
                    market = self._detect_market(instrument)
                    context.user_data['market'] = market
                
                logger.info(f"Market for signals: {market}")
            else:
                # If context is not available, detect market based on instrument
                market = self._detect_market(instrument)
                logger.info(f"Detected market from instrument: {market}")
            
            # Get the allowed timeframe for this instrument
            timeframe = INSTRUMENT_TIMEFRAME_MAP.get(instrument)
            if timeframe:
                # If instrument has a specific timeframe, inform the user and save directly
                
                # Translate MT4/MT5 style timeframes to display format for user feedback
                if timeframe == 'M15':
                    display_timeframe = '15 minute'
                elif timeframe == 'M30':
                    display_timeframe = '30 minute'
                elif timeframe == 'H1':
                    display_timeframe = '1 hour'
                elif timeframe == 'H4':
                    display_timeframe = '4 hour'
                else:
                    display_timeframe = timeframe
                
                # Get user ID for database operations
                user_id = update.effective_user.id
                
                try:
                    # Log the exact timeframe format being used
                    logger.info(f"Using exact timeframe from map: {timeframe} for instrument {instrument}")
                    
                    # Add the preference with the exact timeframe from the map
                    success = await self.db.add_subscriber_preference(
                        user_id=user_id,
                        market=market,
                        instrument=instrument,
                        timeframe=timeframe  # Use the exact timeframe from INSTRUMENT_TIMEFRAME_MAP
                    )
                    
                    if success:
                        # Show success message
                        await query.edit_message_text(
                            text=f"✅ You have successfully subscribed to {instrument} signals!\n\n"
                                f"You will receive {instrument} trading signals for the {display_timeframe} timeframe when they become available.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("➕ Add More Instruments", callback_data=CALLBACK_SIGNALS_ADD)],
                                [InlineKeyboardButton("⚙️ Manage Preferences", callback_data=CALLBACK_SIGNALS_MANAGE)],
                                [InlineKeyboardButton("⬅️ Back to Menu", callback_data=CALLBACK_BACK_MENU)]
                            ])
                        )
                        
                        logger.info(f"User {user_id} subscribed to {instrument} signals with timeframe {timeframe}")
                        return CHOOSE_SIGNALS
                    else:
                        # Handle failure
                        await query.edit_message_text(
                            text=f"❌ Error: Could not save your preference for {instrument}. Please try again later.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_SIGNALS)]
                            ])
                        )
                        return CHOOSE_SIGNALS
                    
                except Exception as db_error:
                    logger.error(f"Database error adding signal preference: {str(db_error)}")
                    await query.edit_message_text(
                        text=f"❌ Error: Could not save your preference for {instrument}. Please try again later.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_SIGNALS)]
                        ])
                    )
                    return CHOOSE_SIGNALS
            else:
                # If the instrument is not in our predefined list, show an error
                await query.edit_message_text(
                    text=f"⚠️ The instrument {instrument} is not currently available for trading signals.\n\n"
                         f"Please select a different instrument.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_SIGNALS)]
                    ])
                )
                return CHOOSE_SIGNALS
                
        except Exception as e:
            logger.error(f"Error in instrument_signals_callback: {str(e)}")
            
            # Show error message
            try:
                await query.edit_message_text(
                    text="An error occurred while processing your selection. Please try again.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_SIGNALS)]
                    ])
                )
            except Exception as inner_e:
                logger.error(f"Failed to show error message: {str(inner_e)}")
                
            return MENU

    async def remove_subscriptions_callback(self, update: Update, context=None) -> int:
        """Handle remove_subscriptions callback to show a list of subscriptions to remove"""
        query = update.callback_query
        
        try:
            # Get user ID
            user_id = update.effective_user.id
            
            # Get user's subscriptions
            preferences = await self.db.get_subscriber_preferences(user_id)
            
            if not preferences or len(preferences) == 0:
                await query.edit_message_text(
                    text="You don't have any signal subscriptions to remove.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Back to Signals", callback_data=CALLBACK_SIGNALS_MANAGE)]
                    ])
                )
                return CHOOSE_SIGNALS
            
            # Create keyboard with preferences to delete
            keyboard = []
            
            # Store preference IDs in context or in a temporary dictionary
            if context and hasattr(context, 'user_data'):
                context.user_data['subscriptions'] = {}
                
                for i, pref in enumerate(preferences):
                    # Store preference ID for later use
                    subscription_key = f"subscription_{i}"
                    context.user_data['subscriptions'][subscription_key] = pref['id']
                    
                    # Create button with preference info
                    instrument = pref.get('instrument', 'Unknown')
                    timeframe = pref.get('timeframe', 'ALL')
                    market = pref.get('market', 'Unknown').upper()
                    
                    button_text = f"{instrument} ({market} - {timeframe})"
                    keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_subscription_{i}")])
            else:
                # If context is not available, use a simpler approach
                for pref in preferences:
                    instrument = pref.get('instrument', 'Unknown')
                    timeframe = pref.get('timeframe', 'ALL')
                    market = pref.get('market', 'Unknown').upper()
                    pref_id = pref.get('id')
                    
                    button_text = f"{instrument} ({market} - {timeframe})"
                    keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_subscription_{pref_id}")])
            
            # Add back button
            keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_SIGNALS_MANAGE)])
            
            await query.edit_message_text(
                text="Select a subscription to remove:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return CHOOSE_SIGNALS
            
        except Exception as e:
            logger.error(f"Error in remove_subscriptions_callback: {str(e)}")
            logger.exception(e)
            
            try:
                await query.edit_message_text(
                    text="An error occurred while retrieving your subscriptions. Please try again.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_SIGNALS_MANAGE)]
                    ])
                )
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                
            return CHOOSE_SIGNALS
            
    async def delete_subscription_callback(self, update: Update, context=None) -> int:
        """Handle deletion of a specific signal subscription"""
        query = update.callback_query
        
        try:
            # Extract subscription index/id from callback data
            subscription_id = query.data.replace('delete_subscription_', '')
            
            # Get the actual database ID
            pref_id = None
            
            # If using context
            if context and hasattr(context, 'user_data') and 'subscriptions' in context.user_data:
                # This is an index into the subscriptions dict
                if subscription_id.isdigit():
                    subscription_key = f"subscription_{subscription_id}"
                    pref_id = context.user_data['subscriptions'].get(subscription_key)
            else:
                # Direct ID from callback
                if subscription_id.isdigit():
                    pref_id = int(subscription_id)
            
            if not pref_id:
                await query.edit_message_text(
                    text="Error: Could not identify the subscription to delete.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_SIGNALS_MANAGE)]
                    ])
                )
                return CHOOSE_SIGNALS
            
            # Delete the subscription
            success = await self.db.delete_preference_by_id(pref_id)
            
            if success:
                await query.edit_message_text(
                    text="✅ The selected subscription has been removed successfully.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⚙️ Manage More Subscriptions", callback_data=CALLBACK_SIGNALS_MANAGE)],
                        [InlineKeyboardButton("🏠 Back to Menu", callback_data=CALLBACK_BACK_MENU)]
                    ])
                )
            else:
                await query.edit_message_text(
                    text="❌ Failed to remove the subscription. Please try again.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_SIGNALS_MANAGE)]
                    ])
                )
            
            return CHOOSE_SIGNALS
            
        except Exception as e:
            logger.error(f"Error in delete_subscription_callback: {str(e)}")
            logger.exception(e)
            
            try:
                await query.edit_message_text(
                    text="An error occurred while removing the subscription. Please try again.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_SIGNALS_MANAGE)]
                    ])
                )
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                
            return CHOOSE_SIGNALS

    async def analyze_from_signal_callback(self, update: Update, context=None) -> int:
        """Handle analyze_from_signal callback to show analysis options for instrument from signal"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get user ID
            user_id = update.effective_user.id
            
            # Extract instrument from callback data
            # Extract instrument from callback data
            instrument = query.data.replace('analyze_from_signal_', '')
            logger.info(f"Analyze from signal callback for instrument: {instrument}")
            
            # Store the instrument in context for later use
            if context and hasattr(context, 'user_data'):
                context.user_data['instrument'] = instrument
                context.user_data['from_signal'] = True
                context.user_data['from_signal_message'] = True
                context.user_data['message_id'] = update.callback_query.message.message_id
                context.user_data['chat_id'] = update.callback_query.message.chat_id
            
            # Show analysis options for this instrument (similar to analysis_callback but with preselected instrument)
            keyboard = [
                [
                    InlineKeyboardButton("📈 Technical Analysis", callback_data="analysis_technical"),
                    InlineKeyboardButton("💬 Sentiment Analysis", callback_data="analysis_sentiment")
                ],
                [
                    InlineKeyboardButton("📅 Economic Calendar", callback_data="analysis_calendar")
                ],
                [InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]
            ]
            
            await query.edit_message_text(
                text=f"Choose analysis type for {instrument}:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return CHOOSE_ANALYSIS
        except Exception as e:
            logger.error(f"Error in analyze_from_signal_callback: {str(e)}")
            return MENU

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
