import os
import json
import asyncio
import traceback
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import logging
import copy
import re
import time
import random

from fastapi import FastAPI, Request, HTTPException, status
from telegram import Bot, Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, InputMediaPhoto, InputMediaAnimation, InputMediaDocument
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
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
from telegram.error import TelegramError, BadRequest
import httpx

from trading_bot.services.database.db import Database
from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
from trading_bot.services.calendar_service.calendar import EconomicCalendarService
from trading_bot.services.payment_service.stripe_service import StripeService
from trading_bot.services.payment_service.stripe_config import get_subscription_features
from trading_bot.services.telegram_service.states import *
import trading_bot.services.telegram_service.gif_utils as gif_utils

# Initialize logger
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

# Keyboard for signal-specific analysis options
SIGNAL_ANALYSIS_KEYBOARD = [
    [InlineKeyboardButton("📈 Technical Analysis", callback_data="signal_technical")],
    [InlineKeyboardButton("🧠 Market Sentiment", callback_data="signal_sentiment")],
    [InlineKeyboardButton("📅 Economic Calendar", callback_data="signal_calendar")],
    [InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]
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

    def _register_handlers(self, application):
        """Register event handlers for bot commands and callback queries"""
        try:
            logger.info("Registering command handlers")
            
            # Initialize the application without using run_until_complete
            try:
                # Instead of using loop.run_until_complete, directly call initialize 
                # which will be properly awaited by the caller
                asyncio.create_task(application.initialize())
                logger.info("Telegram application initialization task created")
            except Exception as init_e:
                logger.error(f"Error during application initialization: {str(init_e)}")
                logger.exception(init_e)
                
            # Set bot commands for menu
            commands = [
                BotCommand("start", "Start the bot and get the welcome message"),
                BotCommand("menu", "Show the main menu"),
                BotCommand("help", "Show available commands and how to use the bot")
            ]
            
            # Set the commands asynchronously
            try:
                # Create a task instead of blocking with run_until_complete
                asyncio.create_task(self.bot.set_my_commands(commands))
                logger.info("Bot commands set task created")
            except Exception as cmd_e:
                logger.error(f"Error setting bot commands: {str(cmd_e)}")
            
            # Load signals
            self._load_signals()
            
            logger.info("Bot setup completed successfully")
            
        except Exception as e:
            logger.error(f"Error setting up bot: {str(e)}")
            logger.exception(e)
            raise

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
            gif_url = await gif_utils.get_analyse_gif()
            
            # Update the message with the GIF using the helper function
            success = await gif_utils.update_message_with_gif(
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
                    gif_url = await gif_utils.get_menu_gif()
                    
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
        
        # Show loading message
        try:
            await query.edit_message_text(
                text="Loading economic calendar data for today...",
                parse_mode=ParseMode.HTML
            )
        except Exception as text_error:
            # If that fails due to caption, try editing caption
            if "There is no text in the message to edit" in str(text_error):
                try:
                    await query.edit_message_caption(
                        caption="Loading economic calendar data for today...",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to update caption: {str(e)}")
            else:
                # Re-raise for other errors
                raise
                
        # Initialize EconomicCalendarService if it's not already initialized
        if not hasattr(self, 'calendar_service') or self.calendar_service is None:
            self.calendar_service = EconomicCalendarService()
            
        # Get today's calendar data
        try:
            # Get today's calendar data without filtering by instrument
            calendar_data = await self.calendar_service.get_calendar()
            
            if not calendar_data:
                raise Exception("Failed to get calendar data")
            
            # Format the calendar message
            message = f"📅 <b>Economic Calendar for Today</b>\n\n"
            
            # Add calendar events
            if calendar_data and len(calendar_data) > 0:
                # Sort events by time
                calendar_data.sort(key=lambda x: x.get('time', '00:00'))
                
                for event in calendar_data:
                    # Extract event details
                    time = event.get('time', 'N/A')
                    country = event.get('country', 'N/A')
                    title = event.get('title', 'N/A')
                    impact = event.get('impact', 'N/A')
                    
                    # Format impact with emoji
                    impact_emoji = "🔴" if impact.lower() == "high" else "🟠" if impact.lower() == "medium" else "🟢"
                    
                    # Add event to message
                    message += f"{time} - {country} - {title} {impact_emoji}\n"
            else:
                message += "No economic events scheduled for today.\n"
            
            # Create keyboard with only a back button
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="back_to_analysis")]
            ]
            
            # Update message with calendar data
            try:
                await query.edit_message_text(
                    text=message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Error updating message with calendar: {str(e)}")
                # Try to send a new message as fallback
                await query.message.reply_text(
                    text=message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
            return CHOOSE_ANALYSIS
                
        except Exception as e:
            logger.error(f"Error loading calendar data: {str(e)}")
            error_text = "Error loading economic calendar data. Please try again."
            try:
                await query.edit_message_text(
                    text=error_text,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Back", callback_data="back_to_analysis")]
                    ])
                )
            except Exception as e:
                logger.error(f"Error updating error message: {str(e)}")
                try:
                    await query.edit_message_caption(
                        caption=error_text,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_analysis")]
                        ])
                    )
                except Exception as e:
                    logger.error(f"Error updating error caption: {str(e)}")
                    
            return BACK_TO_MENU

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
                    keyboard = INDICES_KEYBOARD
                elif market == "commodities":
                    keyboard = COMMODITIES_KEYBOARD
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
        """Show technical analysis for a selected instrument"""
        query = update.callback_query
        await query.answer()
        
        # Get instrument from parameter or context
        if not instrument and context and hasattr(context, 'user_data'):
            instrument = context.user_data.get('instrument')
        
        if not instrument:
            logger.error("No instrument provided for technical analysis")
            try:
                await query.edit_message_text(
                    text="Please select an instrument first.",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
            except Exception as e:
                logger.error(f"Error updating message: {str(e)}")
            return CHOOSE_MARKET
        
        logger.info(f"Showing technical analysis for instrument: {instrument}")
        
        try:
            # Show loading message with GIF
            loading_text = f"Generating technical analysis for {instrument}..."
            loading_gif = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"
            
            try:
                # Try to show loading GIF with message
                await query.edit_message_media(
                    media=InputMediaAnimation(
                        media=loading_gif,
                        caption=loading_text,
                        parse_mode=ParseMode.HTML
                    )
                )
            except Exception as e:
                logger.warning(f"Could not show loading GIF: {str(e)}")
                # Fall back to just text
                try:
                    await query.edit_message_text(text=loading_text)
                except Exception as e:
                    logger.warning(f"Could not edit message text: {str(e)}")
                    try:
                        await query.edit_message_caption(caption=loading_text)
                    except Exception as e:
                        logger.error(f"Could not edit message caption: {str(e)}")
            
            # Get chart from chart service
            chart_url = await self.chart_service.get_chart(instrument)
            
            if not chart_url:
                raise Exception("Failed to generate chart")
            
            # Create keyboard with only a back button
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="back_to_analysis")]
            ]
            
            # Update message with chart - replace the loading GIF
            try:
                await query.edit_message_media(
                    media=InputMediaPhoto(
                        media=chart_url,
                        caption=f"📊 Technical Analysis for {instrument}",
                        parse_mode=ParseMode.HTML
                    ),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Error updating message with chart: {str(e)}")
                # Try to send a new message as fallback
                await query.message.reply_photo(
                    photo=chart_url,
                    caption=f"📊 Technical Analysis for {instrument}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            return CHOOSE_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error generating technical analysis: {str(e)}")
            error_text = f"Error generating technical analysis for {instrument}. Please try again."
            try:
                await query.edit_message_text(
                    text=error_text,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Back", callback_data="back_market")],
                    ])
                )
            except Exception as e:
                logger.error(f"Error updating error message: {str(e)}")
                try:
                    await query.edit_message_caption(
                        caption=error_text,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⬅️ Back", callback_data="back_market")],
                        ])
                    )
                except Exception as e:
                    logger.error(f"Error updating error caption: {str(e)}")
            
            return BACK_TO_MENU

    async def show_sentiment_analysis(self, update: Update, context=None, instrument=None) -> int:
        """Show sentiment analysis for a selected instrument"""
        query = update.callback_query
        await query.answer()
        
        # Get instrument from parameter or context
        if not instrument and context and hasattr(context, 'user_data'):
            instrument = context.user_data.get('instrument')
        
        if not instrument:
            logger.error("No instrument provided for sentiment analysis")
            try:
                await query.edit_message_text(
                    text="Please select an instrument first.",
                    reply_markup=InlineKeyboardMarkup(MARKET_SENTIMENT_KEYBOARD)
                )
            except Exception as e:
                logger.error(f"Error updating message: {str(e)}")
            return CHOOSE_MARKET
        
        logger.info(f"Showing sentiment analysis for instrument: {instrument}")
        
        try:
            # Show simple loading text instead of GIF to avoid mixed content issues
            loading_text = f"Generating sentiment analysis for {instrument}..."
            
            try:
                # Probeer eerst de caption te updaten (als het een media bericht is)
                try:
                    await query.edit_message_caption(
                        caption=loading_text,
                        parse_mode=ParseMode.HTML
                    )
                    is_media_message = True
                except Exception as caption_error:
                    logger.info(f"Message doesn't have caption or is not media: {str(caption_error)}")
                    is_media_message = False
                    
                # Als caption update faalt, probeer tekst te updaten
                if not is_media_message:
                    await query.edit_message_text(
                        text=loading_text,
                        parse_mode=ParseMode.HTML
                    )
            except Exception as e:
                logger.warning(f"Could not update loading message: {str(e)}")
            
            # Get sentiment analysis from sentiment service
            # Initialize MarketSentimentService if it's not already initialized
            if not hasattr(self, 'sentiment_service') or self.sentiment_service is None:
                self.sentiment_service = MarketSentimentService()
            
            # Get sentiment data with error handling
            try:
                sentiment_data = await self.sentiment_service.get_sentiment(instrument)
                if not sentiment_data:
                    raise ValueError("Sentiment service returned empty data")
            except Exception as e:
                logger.error(f"Error getting sentiment data: {str(e)}")
                raise ValueError(f"Failed to get sentiment data: {str(e)}")
            
            # Extract sentiment data
            bullish = sentiment_data.get('bullish', 50)
            bearish = sentiment_data.get('bearish', 30)
            neutral = sentiment_data.get('neutral', 20)
            
            # Ensure percentages add up to 100%
            total = bullish + bearish + neutral
            if total != 100:
                factor = 100 / total if total > 0 else 1
                bullish = round(bullish * factor)
                bearish = round(bearish * factor)
                neutral = 100 - bullish - bearish
            
            # Determine overall sentiment
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
            elif isinstance(sentiment_data.get('analysis'), dict) and 'content' in sentiment_data['analysis']:
                analysis_text = sentiment_data['analysis']['content']
            
            # Limit analysis length
            if len(analysis_text) > 2000:
                analysis_text = analysis_text[:2000] + "..."
                
            # Format the sentiment message
            message = f"""<b>🧠 Market Sentiment Analysis: {instrument}</b>

<b>Overall Sentiment:</b> {overall} {emoji}

<b>Sentiment Breakdown:</b>
- Bullish: {bullish}%
- Bearish: {bearish}%
- Neutral: {neutral}%

"""
            
            # Add analysis if available
            if analysis_text:
                message += f"{analysis_text}\n"
            
            # Create keyboard with back button
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="back_to_analysis")]
            ]
            
            # Show sentiment results - GEBRUIK ALTIJD EEN NIEUWE MESSAGE OM FOUTEN TE VOORKOMEN
            await query.message.reply_text(
                text=message,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return CHOOSE_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error generating sentiment analysis: {str(e)}")
            logger.exception(e)
            
            error_text = f"Error generating sentiment analysis for {instrument}. Please try again."
            
            # Altijd een nieuw bericht sturen bij een fout
            await query.message.reply_text(
                text=error_text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")],
                ])
            )
            
            return BACK_TO_MENU

    async def show_calendar_analysis(self, update: Update, context=None, instrument=None) -> int:
        """Show economic calendar analysis for a selected instrument"""
        query = update.callback_query
        await query.answer()
        
        # Get instrument from parameter or context
        if not instrument and context and hasattr(context, 'user_data'):
            instrument = context.user_data.get('instrument')
        
        if not instrument:
            logger.error("No instrument provided for calendar analysis")
            try:
                await query.edit_message_text(
                    text="Please select an instrument first.",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
            except Exception as e:
                logger.error(f"Error updating message: {str(e)}")
            return CHOOSE_MARKET
        
        logger.info(f"Showing economic calendar analysis for instrument: {instrument}")
        
        try:
            # Show loading message
            loading_text = f"Generating economic calendar for {instrument}..."
            try:
                await query.edit_message_text(text=loading_text)
            except Exception as e:
                logger.warning(f"Could not edit message text: {str(e)}")
                try:
                    await query.edit_message_caption(caption=loading_text)
                except Exception as e:
                    logger.error(f"Could not edit message caption: {str(e)}")
            
            # Get calendar data from calendar service
            calendar_data = await self.calendar_service.get_events(instrument)
            
            if not calendar_data:
                raise Exception("Failed to get calendar data")
            
            # Format the calendar message
            message = f"📅 <b>Economic Calendar for {instrument}</b>\n\n"
            
            # Add events if available
            if "events" in calendar_data and calendar_data["events"]:
                events = calendar_data["events"]
                for event in events[:10]:  # Limit to first 10 events to avoid message too long
                    impact = "🔴" if event.get("impact") == "high" else "🟡" if event.get("impact") == "medium" else "🟢"
                    message += f"{impact} <b>{event.get('date', 'Unknown date')}:</b> {event.get('title', 'Unknown event')}\n"
                    if "forecast" in event and event["forecast"]:
                        message += f"   Forecast: {event['forecast']}\n"
                    if "previous" in event and event["previous"]:
                        message += f"   Previous: {event['previous']}\n"
                    message += "\n"
                
                if len(events) > 10:
                    message += f"<i>+{len(events) - 10} more events...</i>\n"
            else:
                message += "No upcoming economic events found for this instrument.\n"
            
            # Add impact explanation if available
            if "explanation" in calendar_data:
                message += f"\n<b>Potential Market Impact:</b>\n{calendar_data['explanation']}\n"
            
            # Create keyboard for navigation and refresh
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh Calendar", callback_data=f"instrument_{instrument}_calendar")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_market")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]
            ]
            
            # Update message with calendar
            try:
                await query.edit_message_text(
                    text=message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Error updating message with calendar: {str(e)}")
                # Try to send a new message as fallback
                await query.message.reply_text(
                    text=message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            return CHOOSE_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error generating calendar analysis: {str(e)}")
            error_text = f"Error generating economic calendar for {instrument}. Please try again."
            try:
                await query.edit_message_text(
                    text=error_text,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Back", callback_data="back_market")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]
                    ])
                )
            except Exception as e:
                logger.error(f"Error updating error message: {str(e)}")
                try:
                    await query.edit_message_caption(
                        caption=error_text,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⬅️ Back", callback_data="back_market")],
                            [InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]
                        ])
                    )
                except Exception as e:
                    logger.error(f"Error updating error caption: {str(e)}")
            
            return BACK_TO_MENU

    async def back_to_signal_analysis_callback(self, update: Update, context=None) -> int:
        """Handle back_to_signal_analysis button press"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get the instrument from context
            instrument = None
            if context and hasattr(context, 'user_data'):
                instrument = context.user_data.get('instrument')
            
            if not instrument:
                logger.error("No instrument found in context")
                return await self.show_main_menu(update, context)
            
            # Create keyboard for signal analysis options
            keyboard = [
                [InlineKeyboardButton("📊 Technical Analysis", callback_data=f"signal_technical")],
                [InlineKeyboardButton("🧠 Market Sentiment", callback_data=f"signal_sentiment")],
                [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"signal_calendar")],
                [InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]
            ]
            
            # Update message with analysis options
            try:
                await query.edit_message_text(
                    text=f"Select analysis type for {instrument}:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            except Exception as text_error:
                # If that fails due to caption, try editing caption
                if "There is no text in the message to edit" in str(text_error):
                    try:
                        await query.edit_message_caption(
                            caption=f"Select analysis type for {instrument}:",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.error(f"Failed to update caption: {str(e)}")
                        # Try to send a new message as last resort
                        await query.message.reply_text(
                            text=f"Select analysis type for {instrument}:",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                else:
                    # Re-raise for other errors
                    raise
            
            return SIGNAL_DETAILS
            
        except Exception as e:
            logger.error(f"Error in back_to_signal_analysis_callback: {str(e)}")
            # Try to recover by going back to main menu
            try:
                await query.edit_message_text(
                    text="An error occurred. Returning to main menu...",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
            except Exception:
                pass
            return MENU

    async def market_callback(self, update: Update, context=None) -> int:
        """Handle market selection and show appropriate instruments"""
        query = update.callback_query
        callback_data = query.data
        
        # Parse the market from callback data
        parts = callback_data.split("_")
        market = parts[1]  # Extract market type (forex, crypto, etc.)
        
        # Check if signal-specific context
        is_signals_context = False
        if callback_data.endswith("_signals"):
            is_signals_context = True
        elif context and hasattr(context, 'user_data'):
            is_signals_context = context.user_data.get('is_signals_context', False)
        
        # Store market in context
        if context and hasattr(context, 'user_data'):
            context.user_data['market'] = market
            context.user_data['is_signals_context'] = is_signals_context
        
        logger.info(f"Market callback: market={market}, signals_context={is_signals_context}")
        
        # Determine which keyboard to show based on market and context
        keyboard = None
        if is_signals_context or callback_data.endswith("_signals"):
            # Keyboards for signals
            if market == "forex":
                keyboard = FOREX_KEYBOARD_SIGNALS
            elif market == "crypto":
                keyboard = CRYPTO_KEYBOARD_SIGNALS
            elif market == "indices":
                keyboard = INDICES_KEYBOARD_SIGNALS
            elif market == "commodities":
                keyboard = COMMODITIES_KEYBOARD_SIGNALS
            else:
                keyboard = MARKET_KEYBOARD_SIGNALS
            
            text = f"Select a {market} instrument for signals:"
            back_data = "back_signals"
        else:
            # Keyboards for analysis
            if market == "forex":
                keyboard = FOREX_KEYBOARD
            elif market == "crypto":
                keyboard = CRYPTO_KEYBOARD
            elif market == "indices":
                keyboard = INDICES_KEYBOARD
            elif market == "commodities":
                keyboard = COMMODITIES_KEYBOARD
            else:
                keyboard = MARKET_KEYBOARD
            
            # Set analysis type if present in callback data
            analysis_type = ""
            if len(parts) > 2:
                analysis_type = parts[2]
                if context and hasattr(context, 'user_data'):
                    context.user_data['analysis_type'] = analysis_type
            
            # Specific text for different analysis types
            if analysis_type == "sentiment":
                text = f"Select a {market} instrument for sentiment analysis:"
            elif analysis_type == "calendar":
                text = f"Select a {market} instrument for economic calendar:"
            else:
                text = f"Select a {market} instrument for analysis:"
            
            back_data = "back_analysis"
        
        # Update message with appropriate keyboard
        try:
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
                    logger.error(f"Failed to update caption in market_callback: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text=text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
            else:
                # Re-raise for other errors
                raise
        
        return CHOOSE_INSTRUMENT

    async def menu_signals_callback(self, update: Update, context=None) -> int:
        """Handle menu_signals callback - show signals menu"""
        query = update.callback_query
        await query.answer()  # Respond to prevent loading icon
        
        try:
            # Get a signals GIF URL
            gif_url = await get_signals_gif()
            
            # Update the message with the GIF using the helper function
            success = await gif_utils.update_message_with_gif(
                query=query,
                gif_url=gif_url,
                text="Trading Signals Options:",
                reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
            )
            
            if not success:
                # If the helper function failed, try a direct approach as fallback
                try:
                    # First try to edit message text
                    await query.edit_message_text(
                        text="Trading Signals Options:",
                        reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as text_error:
                    # If that fails due to caption, try editing caption
                    if "There is no text in the message to edit" in str(text_error):
                        await query.edit_message_caption(
                            caption="Trading Signals Options:",
                            reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD),
                            parse_mode=ParseMode.HTML
                        )
            
            return CHOOSE_SIGNALS
        except Exception as e:
            logger.error(f"Error in menu_signals_callback: {str(e)}")
            
            # If we can't edit the message, try again with a simpler approach as fallback
            try:
                # First try editing the caption
                try:
                    await query.edit_message_caption(
                        caption="Trading Signals Options:",
                        reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as caption_error:
                    # If that fails, try editing text
                    await query.edit_message_text(
                        text="Trading Signals Options:",
                        reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                return CHOOSE_SIGNALS
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                
                # Last resort: send a new message
                try:
                    await query.message.reply_text(
                        text="Trading Signals Options:",
                        reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                    logger.warning("Fallback to sending new message - ideally this should be avoided")
                except Exception:
                    pass
                    
                return MENU

    async def signals_add_callback(self, update: Update, context=None) -> int:
        """Handle signals_add button press - show market selection for adding signals"""
        query = update.callback_query
        await query.answer()
        
        # Set the signals context flag
        if context and hasattr(context, 'user_data'):
            context.user_data['is_signals_context'] = True
        
        try:
            await query.edit_message_text(
                text="Select market for signal subscription:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS),
                parse_mode=ParseMode.HTML
            )
        except Exception as text_error:
            # If that fails due to caption, try editing caption
            if "There is no text in the message to edit" in str(text_error):
                try:
                    await query.edit_message_caption(
                        caption="Select market for signal subscription:",
                        reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to update caption in signals_add_callback: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text="Select market for signal subscription:",
                        reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS),
                        parse_mode=ParseMode.HTML
                    )
            else:
                # Re-raise for other errors
                raise
        
        return CHOOSE_MARKET

    async def instrument_signals_callback(self, update: Update, context=None) -> int:
        """Handle instrument selection for signals"""
        query = update.callback_query
        await query.answer()
        callback_data = query.data
        
        # Extract the instrument from the callback data
        # Format: "instrument_EURUSD_signals"
        parts = callback_data.split("_")
        instrument_parts = []
        
        # Find where the "signals" specifier starts
        for i, part in enumerate(parts[1:], 1):  # Skip "instrument_" prefix
            if part == "signals":
                break
            instrument_parts.append(part)
        
        # Join the instrument parts
        instrument = "_".join(instrument_parts) if instrument_parts else ""
        
        # Store instrument in context
        if context and hasattr(context, 'user_data'):
            context.user_data['instrument'] = instrument
            context.user_data['is_signals_context'] = True
        
        logger.info(f"Instrument signals callback: instrument={instrument}")
        
        if not instrument:
            logger.error("No instrument found in callback data")
            await query.edit_message_text(
                text="Invalid instrument selection. Please try again.",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
            )
            return CHOOSE_MARKET
        
        # Each instrument has only one timeframe available, get it directly
        if instrument in INSTRUMENT_TIMEFRAME_MAP:
            # Get the predefined timeframe for this instrument
            timeframe = INSTRUMENT_TIMEFRAME_MAP[instrument]
            timeframe_display = TIMEFRAME_DISPLAY_MAP.get(timeframe, timeframe)
            
            # Directly subscribe the user to this instrument with its fixed timeframe
            user_id = update.effective_user.id
            await self.db.subscribe_to_instrument(user_id, instrument, timeframe)
            
            # Show success message
            success_message = f"✅ Successfully subscribed to {instrument} ({timeframe_display}) signals!"
            
            # Create keyboard with options to add more or go back
            keyboard = [
                [InlineKeyboardButton("➕ Add More Pairs", callback_data="signals_add")],
                [InlineKeyboardButton("⬅️ Back to Signals", callback_data="back_signals")]
            ]
            
            try:
                await query.edit_message_text(
                    text=success_message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            except Exception as text_error:
                # If that fails due to caption, try editing caption
                if "There is no text in the message to edit" in str(text_error):
                    try:
                        await query.edit_message_caption(
                            caption=success_message,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.error(f"Failed to update caption: {str(e)}")
                        # Try to send a new message as last resort
                        await query.message.reply_text(
                            text=success_message,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                else:
                    # Re-raise for other errors
                    raise
            
            return CHOOSE_SIGNALS
        else:
            # Instrument not found in mapping
            error_message = f"❌ Sorry, {instrument} is currently not available for signal subscription."
            
            # Show error and back button
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_market")]]
            
            try:
                await query.edit_message_text(
                    text=error_message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            except Exception as text_error:
                # If that fails due to caption, try editing caption
                if "There is no text in the message to edit" in str(text_error):
                    try:
                        await query.edit_message_caption(
                            caption=error_message,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.error(f"Failed to update caption: {str(e)}")
                        # Try to send a new message as last resort
                        await query.message.reply_text(
                            text=error_message,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                else:
                    # Re-raise for other errors
                    raise
            
            return CHOOSE_MARKET
    
    async def back_market_callback(self, update: Update, context=None) -> int:
        """Handle back button to return to market selection"""
        query = update.callback_query
        await query.answer()
        
        # Get analysis type from context
        analysis_type = None
        if context and hasattr(context, 'user_data'):
            analysis_type = context.user_data.get('analysis_type')
            is_signals_context = context.user_data.get('is_signals_context', False)
        
        # Determine which keyboard to show based on analysis type
        if is_signals_context:
            # For signals, always go back to the signals market keyboard
            keyboard = MARKET_KEYBOARD_SIGNALS
            text = "Select market for signal subscription:"
        else:
            # For analysis, select appropriate keyboard based on analysis type
            if analysis_type == "sentiment":
                keyboard = MARKET_SENTIMENT_KEYBOARD
                text = "Select market for sentiment analysis:"
            elif analysis_type == "calendar":
                keyboard = MARKET_KEYBOARD
                text = "Select market for economic calendar:"
            else:
                # Default to regular market keyboard
                keyboard = MARKET_KEYBOARD
                text = "Select market for analysis:"
        
        # Update message with the appropriate keyboard
        try:
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
                    logger.error(f"Failed to update caption in back_market_callback: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text=text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
            else:
                # Re-raise for other errors
                raise
        
        return CHOOSE_MARKET
    
    async def back_instrument_callback(self, update: Update, context=None) -> int:
        """Handle back button to return to instrument selection"""
        query = update.callback_query
        await query.answer()
        
        # Get market and analysis type from context
        market = None
        analysis_type = None
        if context and hasattr(context, 'user_data'):
            market = context.user_data.get('market')
            analysis_type = context.user_data.get('analysis_type')
            is_signals_context = context.user_data.get('is_signals_context', False)
        
        if not market:
            logger.warning("No market found in context, defaulting to forex")
            market = "forex"
        
        # Determine which keyboard to show based on market and analysis type
        keyboard = None
        if is_signals_context:
            # For signals context
            if market == "forex":
                keyboard = FOREX_KEYBOARD_SIGNALS
            elif market == "crypto":
                keyboard = CRYPTO_KEYBOARD_SIGNALS
            elif market == "indices":
                keyboard = INDICES_KEYBOARD_SIGNALS
            elif market == "commodities":
                keyboard = COMMODITIES_KEYBOARD_SIGNALS
            else:
                keyboard = MARKET_KEYBOARD_SIGNALS
            
            text = f"Select a {market} instrument for signals:"
        else:
            # For analysis context
            if analysis_type == "sentiment":
                # Sentiment-specific keyboards
                if market == "forex":
                    keyboard = FOREX_SENTIMENT_KEYBOARD
                elif market == "crypto":
                    keyboard = CRYPTO_SENTIMENT_KEYBOARD
                else:
                    keyboard = MARKET_SENTIMENT_KEYBOARD
                
                text = f"Select a {market} instrument for sentiment analysis:"
            else:
                # Regular analysis keyboards
                if market == "forex":
                    keyboard = FOREX_KEYBOARD
                elif market == "crypto":
                    keyboard = CRYPTO_KEYBOARD
                elif market == "indices":
                    keyboard = INDICES_KEYBOARD
                elif market == "commodities":
                    keyboard = COMMODITIES_KEYBOARD
                else:
                    keyboard = MARKET_KEYBOARD
                
                text = f"Select a {market} instrument for analysis:"
        
        # Update message with the appropriate keyboard
        try:
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
                    logger.error(f"Failed to update caption in back_instrument_callback: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text=text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
            else:
                # Re-raise for other errors
                raise
        
        return CHOOSE_INSTRUMENT
    
    async def analysis_callback(self, update: Update, context=None) -> int:
        """Handle back button to return to analysis menu"""
        query = update.callback_query
        await query.answer()
        
        # Check if the message has a photo or animation that needs to be removed
        has_photo = bool(query.message.photo) or query.message.animation is not None
        
        # Get an analysis GIF URL for the menu
        gif_url = await gif_utils.get_analyse_gif()
        
        # Prepare keyboard for analysis menu
        keyboard = ANALYSIS_KEYBOARD
        text = "Select your analysis type:"
        
        if has_photo:
            try:
                # Try to delete the message first (cleanest approach)
                await query.message.delete()
                # Send a new message with the analysis selection
                await query.message.reply_text(
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            except Exception as delete_error:
                logger.warning(f"Could not delete message: {str(delete_error)}")
                try:
                    # Try to replace media with transparent GIF
                    await query.message.edit_media(
                        media=InputMediaDocument(
                            media="https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/Transparent.gif/1px-Transparent.gif",
                            caption=text,
                            parse_mode=ParseMode.HTML
                        ),
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as edit_error:
                    logger.warning(f"Could not edit media with transparent GIF: {str(edit_error)}")
                    # If all else fails, just try to edit the caption
                    try:
                        await query.message.edit_caption(
                            caption=text,
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    except Exception as caption_error:
                        logger.error(f"Could not edit caption: {str(caption_error)}")
                        # Last resort - send a new message
                        await query.message.reply_text(
                            text=text,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
        else:
            # No photo or animation to remove, just update the text and keyboard
            success = await gif_utils.update_message_with_gif(
                query=query,
                gif_url=gif_url,
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            if not success:
                # If the helper function failed, try a direct approach as fallback
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
                            logger.error(f"Failed to update caption: {str(e)}")
                            # Try to send a new message as last resort
                            await query.message.reply_text(
                                text=text,
                                reply_markup=InlineKeyboardMarkup(keyboard),
                                parse_mode=ParseMode.HTML
                            )
                    else:
                        # Re-raise for other errors
                        logger.error(f"Error updating message: {str(text_error)}")
                        # Send a new message as last resort
                        await query.message.reply_text(
                            text=text,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
        
        return CHOOSE_ANALYSIS

    async def back_menu_callback(self, update: Update, context=None) -> int:
        """Handle back to main menu button press"""
        query = update.callback_query
        await query.answer()
        
        # Get a menu GIF URL
        gif_url = await gif_utils.get_menu_gif()
        
        # Update the message with the GIF using the helper function
        success = await gif_utils.update_message_with_gif(
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
                    try:
                        await query.edit_message_caption(
                            caption=WELCOME_MESSAGE,
                            reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.error(f"Failed to update caption in back_menu_callback: {str(e)}")
                        # Try to send a new message as last resort
                        await query.message.reply_text(
                            text=WELCOME_MESSAGE,
                            reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                            parse_mode=ParseMode.HTML
                        )
                else:
                    # Re-raise for other errors
                    raise
        
        return MENU
    
    async def analyze_from_signal_callback(self, update: Update, context=None) -> int:
        """Handle analyze from signal button press"""
        query = update.callback_query
        await query.answer()
        
        # Get instrument and signal ID from callback data or context
        callback_data = query.data
        instrument = None
        
        # Extract instrument from callback data if present
        # Format: "analyze_from_signal_EURUSD_123"
        if callback_data.startswith("analyze_from_signal_"):
            parts = callback_data.split("_")
            if len(parts) >= 4:
                # Get the instrument, handling potential underscores in instrument name
                instrument_parts = []
                signal_id = None
                
                for i, part in enumerate(parts[3:], 3):
                    if i == len(parts) - 1:
                        # Last part is the signal ID
                        signal_id = part
                        break
                    instrument_parts.append(part)
                
                instrument = "_".join(instrument_parts)
                
                # Store in context
                if context and hasattr(context, 'user_data'):
                    context.user_data['instrument'] = instrument
                    context.user_data['current_signal_id'] = signal_id
        
        if not instrument and context and hasattr(context, 'user_data'):
            instrument = context.user_data.get('instrument')
        
        if not instrument:
            logger.error("No instrument found for signal analysis")
            # Go back to main menu
            return await self.back_menu_callback(update, context)
        
        # Show the analysis options for the signal
        keyboard = [
            [InlineKeyboardButton("📈 Technical Analysis", callback_data=f"signal_technical")],
            [InlineKeyboardButton("🧠 Market Sentiment", callback_data=f"signal_sentiment")],
            [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"signal_calendar")],
            [InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal")]
        ]
        
        # Update message with analysis options
        try:
            await query.edit_message_text(
                text=f"Select analysis type for {instrument}:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        except Exception as text_error:
            # If that fails due to caption, try editing caption
            if "There is no text in the message to edit" in str(text_error):
                try:
                    await query.edit_message_caption(
                        caption=f"Select analysis type for {instrument}:",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to update caption in analyze_from_signal_callback: {str(e)}")
                    # Try to send a new message as last resort
                    await query.message.reply_text(
                        text=f"Select analysis type for {instrument}:",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
            else:
                # Re-raise for other errors
                raise
        
        return SIGNAL_DETAILS

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
            # Get all subscribers from the database
            subscribers = await self.db.get_signal_subscriptions(instrument, timeframe)
            
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
            logger.error(f"Error getting subscribers for {instrument}: {str(e)}")
            return []
    
    async def process_signal(self, signal_data: Dict[str, Any]) -> bool:
        """
        Process a trading signal and send it to subscribed users
        
        Args:
            signal_data: Dict containing signal information
                Required keys:
                - instrument: The trading pair/instrument (e.g., EURUSD)
                - direction: "buy" or "sell"
                - timeframe: The signal timeframe (e.g., "1h", "4h", "M15", etc.)
                
                Optional keys:
                - entry: Entry price point
                - stop_loss: Stop loss price
                - take_profit: Take profit target
                - risk_reward: Risk-reward ratio
                - confidence: Signal confidence level (1-100)
                - notes: Additional notes about the signal
                - chart_url: URL to chart image
                
        Returns:
            bool: True if signal was processed successfully, False otherwise
        """
        try:
            # Extract required fields
            instrument = signal_data.get('instrument')
            direction = signal_data.get('direction', '').lower()
            timeframe = signal_data.get('timeframe')
            
            # Basic validation
            if not instrument or not direction:
                logger.error(f"Missing required fields in signal data: {signal_data}")
                return False
                
            if direction not in ['buy', 'sell']:
                logger.error(f"Invalid direction {direction} in signal data")
                return False
            
            # Optional fields with defaults
            entry = signal_data.get('entry', 'Market')
            stop_loss = signal_data.get('stop_loss', 'Not specified')
            take_profit = signal_data.get('take_profit', 'Not specified')
            risk_reward = signal_data.get('risk_reward', 'Not specified')
            confidence = signal_data.get('confidence', 'Not specified')
            notes = signal_data.get('notes', '')
            chart_url = signal_data.get('chart_url', '')
            
            # Create signal ID for tracking
            signal_id = f"{instrument}_{direction}_{timeframe}_{int(time.time())}"
            
            # Create signal message
            direction_emoji = "🟢 BUY" if direction == "buy" else "🔴 SELL"
            signal_message = f"""
🔔 <b>NEW SIGNAL ALERT</b> 🔔

<b>Instrument:</b> {instrument}
<b>Direction:</b> {direction_emoji}
<b>Timeframe:</b> {timeframe}

<b>Entry:</b> {entry}
<b>Stop Loss:</b> {stop_loss}
<b>Take Profit:</b> {take_profit}
<b>Risk/Reward:</b> {risk_reward}
<b>Confidence:</b> {confidence}

{notes}
"""
            
            # Determine market type for the instrument
            market_type = _detect_market(instrument)
            
            # Create signal data structure for storage and future reference
            formatted_signal = {
                'id': signal_id,
                'timestamp': datetime.now().isoformat(),
                'instrument': instrument,
                'direction': direction,
                'timeframe': timeframe,
                'entry': entry,
                'stop_loss': stop_loss, 
                'take_profit': take_profit,
                'risk_reward': risk_reward,
                'confidence': confidence,
                'notes': notes,
                'chart_url': chart_url,
                'market': market_type,
                'message': signal_message
            }
            
            # Save signal for history tracking
            if not os.path.exists(self.signals_dir):
                os.makedirs(self.signals_dir, exist_ok=True)
                
            # Save to signals directory
            with open(f"{self.signals_dir}/{signal_id}.json", 'w') as f:
                json.dump(formatted_signal, f)
            
            # Get subscribers for this instrument
            subscribers = await self.get_subscribers_for_instrument(instrument, timeframe)
            
            if not subscribers:
                logger.info(f"No subscribers found for {instrument} {timeframe}")
                return True  # Successfully processed, just no subscribers
            
            # Send signal to all subscribers
            logger.info(f"Sending signal {signal_id} to {len(subscribers)} subscribers")
            
            sent_count = 0
            for user_id in subscribers:
                try:
                    # Prepare keyboard with analysis options
                    keyboard = [
                        [InlineKeyboardButton("🔍 Analyze", callback_data=f"analyze_from_signal_{instrument}_{signal_id}")],
                        [InlineKeyboardButton("📊 Charts", callback_data=f"charts_from_signal_{instrument}_{signal_id}")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]
                    ]
                    
                    # If we have a chart URL, send it as a photo
                    if chart_url:
                        try:
                            await self.bot.send_photo(
                                chat_id=user_id,
                                photo=chart_url,
                                caption=signal_message,
                                parse_mode=ParseMode.HTML,
                                reply_markup=InlineKeyboardMarkup(keyboard)
                            )
                        except Exception as photo_e:
                            # If photo fails, fallback to just text
                            logger.error(f"Could not send photo for signal {signal_id}: {str(photo_e)}")
                            await self.bot.send_message(
                                chat_id=user_id,
                                text=signal_message,
                                parse_mode=ParseMode.HTML,
                                reply_markup=InlineKeyboardMarkup(keyboard)
                            )
                    else:
                        # Send as regular message
                        await self.bot.send_message(
                            chat_id=user_id,
                            text=signal_message,
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    
                    sent_count += 1
                    # Store signal reference in user data for quick access
                    if str(user_id) not in self.user_signals:
                        self.user_signals[str(user_id)] = {}
                    
                    self.user_signals[str(user_id)][signal_id] = formatted_signal
                    
                except Exception as e:
                    logger.error(f"Error sending signal to user {user_id}: {str(e)}")
            
            logger.info(f"Successfully sent signal {signal_id} to {sent_count}/{len(subscribers)} subscribers")
            return True
            
        except Exception as e:
            logger.error(f"Error processing signal: {str(e)}")
            logger.exception(e)
            return False
            
    def _load_signals(self):
        """Load stored signals from the signals directory"""
        if not os.path.exists(self.signals_dir):
            os.makedirs(self.signals_dir, exist_ok=True)
            return
            
        # Load all signal files
        signal_files = [f for f in os.listdir(self.signals_dir) if f.endswith('.json')]
        
        if not signal_files:
            logger.info("No stored signals found")
            return
            
        signals_count = 0
        for signal_file in signal_files:
            try:
                with open(f"{self.signals_dir}/{signal_file}", 'r') as f:
                    signal = json.load(f)
                    
                signal_id = signal.get('id')
                if not signal_id:
                    continue
                    
                # Store in memory for quick access
                # Here we organize by instrument for easier lookup
                instrument = signal.get('instrument')
                if instrument:
                    signals_count += 1
            except Exception as e:
                logger.error(f"Error loading signal file {signal_file}: {str(e)}")
                
        logger.info(f"Loaded {signals_count} signals from storage")

    def register_api_endpoints(self, app: FastAPI):
        """Register FastAPI endpoints for webhook and signal handling"""
        if not app:
            logger.warning("No FastAPI app provided, skipping API endpoint registration")
            return
            
        # Register the signal processing API endpoint
        @app.post("/api/signals")
        async def process_signal_api(request: Request):
            try:
                signal_data = await request.json()
                
                # Validate API key if one is set
                api_key = request.headers.get("X-API-Key")
                expected_key = os.getenv("SIGNAL_API_KEY")
                
                if expected_key and api_key != expected_key:
                    logger.warning("Invalid API key used in signal API request")
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
        
        # Register TradingView webhook endpoint
        @app.post("/signal")
        async def process_tradingview_signal(request: Request):
            try:
                signal_data = await request.json()
                logger.info(f"Received TradingView webhook signal: {signal_data}")
                
                success = await self.process_signal(signal_data)
                
                if success:
                    return {"status": "success", "message": "Signal processed successfully"}
                else:
                    return {"status": "error", "message": "Failed to process signal"}
                    
            except Exception as e:
                logger.error(f"Error processing TradingView webhook signal: {str(e)}")
                logger.exception(e)
                return {"status": "error", "message": str(e)}
        
        # Register Telegram webhook endpoint
        @app.post(self.webhook_path)
        async def telegram_webhook(request: Request):
            try:
                update_data = await request.json()
                await self.process_update(update_data)
                return {"status": "success"}
            except Exception as e:
                logger.error(f"Error processing Telegram webhook: {str(e)}")
                logger.exception(e)
                return {"status": "error", "message": str(e)}
                
        logger.info(f"API endpoints registered at /api/signals, /signal, and {self.webhook_path}")

    async def initialize(self, use_webhook=False):
        """Initialize the bot and set up handlers"""
        try:
            # Create application instance
            self.application = Application.builder().bot(self.bot).build()
            
            # Register handlers
            self._register_handlers(self.application)
            
            # Initialize in polling mode if not using webhook
            if not use_webhook:
                logger.info("Starting bot in polling mode")
                await self.application.initialize()
                await self.application.start()
                await self.application.updater.start_polling()
                self.polling_started = True
            else:
                logger.info("Bot will be initialized in webhook mode")
                await self.application.initialize()
                
            logger.info("Bot initialization completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing bot: {str(e)}")
            logger.exception(e)
            return False
