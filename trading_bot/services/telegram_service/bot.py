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
import telegram.error  # Add this import for BadRequest error handling

from trading_bot.services.database.db import Database
from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
from trading_bot.services.calendar_service.calendar import EconomicCalendarService, MAJOR_CURRENCIES, CURRENCY_FLAG
from trading_bot.services.payment_service.stripe_service import StripeService
from trading_bot.services.payment_service.stripe_config import get_subscription_features
from trading_bot.services.telegram_service.states import (
    MENU, ANALYSIS, SIGNALS, CHOOSE_MARKET, CHOOSE_INSTRUMENT, CHOOSE_STYLE,
    CHOOSE_ANALYSIS, SIGNAL_DETAILS,
    CALLBACK_MENU_ANALYSE, CALLBACK_MENU_SIGNALS, CALLBACK_ANALYSIS_TECHNICAL,
    CALLBACK_ANALYSIS_SENTIMENT, CALLBACK_ANALYSIS_CALENDAR, CALLBACK_SIGNALS_ADD,
    CALLBACK_SIGNALS_MANAGE, CALLBACK_BACK_MENU
)
import trading_bot.services.telegram_service.gif_utils as gif_utils
from trading_bot.services.telegram_service.gif_utils import get_signals_gif

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
🚀 <b>Sigmapips AI - Main Menu</b> 🚀

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
    [InlineKeyboardButton("⚙️ Manage Signals", callback_data=CALLBACK_SIGNALS_MANAGE)],
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
        InlineKeyboardButton("US30", callback_data="instrument_US30_chart"),
        InlineKeyboardButton("US500", callback_data="instrument_US500_chart"),
        InlineKeyboardButton("US100", callback_data="instrument_US100_chart")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Indices keyboard voor signals - Fix de "Terug" knop naar "Back"
INDICES_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("US30", callback_data="instrument_US30_signals"),
        InlineKeyboardButton("US500", callback_data="instrument_US500_signals")
    ],
    [
        InlineKeyboardButton("UK100", callback_data="instrument_UK100_signals"),
        InlineKeyboardButton("DE40", callback_data="instrument_DE40_signals")
    ],
    [
        InlineKeyboardButton("AU200", callback_data="instrument_AU200_signals"),
        InlineKeyboardButton("HK50", callback_data="instrument_HK50_signals")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
]

# Commodities keyboard voor analyse
COMMODITIES_KEYBOARD = [
    [
        InlineKeyboardButton("GOLD", callback_data="instrument_XAUUSD_chart"),
        InlineKeyboardButton("SILVER", callback_data="instrument_XAGUSD_chart"),
        InlineKeyboardButton("OIL", callback_data="instrument_USOIL_chart")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Commodities keyboard voor signals - Fix de "Terug" knop naar "Back"
COMMODITIES_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD_signals"),
        InlineKeyboardButton("XTIUSD", callback_data="instrument_XTIUSD_signals")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Forex keyboard for signals
FOREX_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD_signals"),
        InlineKeyboardButton("EURGBP", callback_data="instrument_EURGBP_signals"),
        InlineKeyboardButton("EURCAD", callback_data="instrument_EURCAD_signals")
    ],
    [
        InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD_signals"),
        InlineKeyboardButton("GBPCAD", callback_data="instrument_GBPCAD_signals"),
        InlineKeyboardButton("GBPCHF", callback_data="instrument_GBPCHF_signals")
    ],
    [
        InlineKeyboardButton("USDCAD", callback_data="instrument_USDCAD_signals"),
        InlineKeyboardButton("USDCHF", callback_data="instrument_USDCHF_signals"),
        InlineKeyboardButton("GBPNZD", callback_data="instrument_GBPNZD_signals")
    ],
    [
        InlineKeyboardButton("EURAUD", callback_data="instrument_EURAUD_signals"),
        InlineKeyboardButton("EURJPY", callback_data="instrument_EURJPY_signals"),
        InlineKeyboardButton("EURCHF", callback_data="instrument_EURCHF_signals")
    ],
    [
        InlineKeyboardButton("AUDJPY", callback_data="instrument_AUDJPY_signals"),
        InlineKeyboardButton("AUDCHF", callback_data="instrument_AUDCHF_signals"),
        InlineKeyboardButton("AUDCAD", callback_data="instrument_AUDCAD_signals")
    ],
    [
        InlineKeyboardButton("NZDJPY", callback_data="instrument_NZDJPY_signals"),
        InlineKeyboardButton("NZDUSD", callback_data="instrument_NZDUSD_signals"),
        InlineKeyboardButton("NZDCAD", callback_data="instrument_NZDCAD_signals")
    ],
    [
        InlineKeyboardButton("NZDCHF", callback_data="instrument_NZDCHF_signals"),
        InlineKeyboardButton("GBPAUD", callback_data="instrument_GBPAUD_signals"),
        InlineKeyboardButton("CADCHF", callback_data="instrument_CADCHF_signals")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
]

# Crypto keyboard for signals
CRYPTO_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD_signals"),
        InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD_signals")
    ],
    [
        InlineKeyboardButton("BNBUSD", callback_data="instrument_BNBUSD_signals"),
        InlineKeyboardButton("DOTUSD", callback_data="instrument_DOTUSD_signals")
    ],
    [
        InlineKeyboardButton("DOGEUSD", callback_data="instrument_DOGEUSD_signals"),
        InlineKeyboardButton("SOLUSD", callback_data="instrument_SOLUSD_signals")
    ],
    [
        InlineKeyboardButton("LINKUSD", callback_data="instrument_LINKUSD_signals"),
        InlineKeyboardButton("XLMUSD", callback_data="instrument_XLMUSD_signals")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
]

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
            
            # Register command handlers
            application.add_handler(CommandHandler("start", self.start_command))
            application.add_handler(CommandHandler("menu", self.menu_command))
            application.add_handler(CommandHandler("help", self.help_command))
            
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
        """Show help information when /help command is used"""
        await update.message.reply_text(
            text=HELP_MESSAGE,
            parse_mode=ParseMode.HTML
        )

    async def analysis_technical_callback(self, update: Update, context=None) -> int:
        """Handle technical analysis button press from a signal"""
        query = update.callback_query
        await query.answer()
        
        # Get callback data
        callback_data = query.data
        
        # Extract instrument and signal ID
        # Format: "analysis_technical_EURUSD_123456789"
        parts = callback_data.split("_")
        if len(parts) >= 4:
            instrument = parts[2]
            signal_id = parts[3]
            
            # Temporary response while actual analysis is prepared
            try:
                await query.edit_message_text(
                    text=f"Sorry, I couldn't generate the technical analysis chart. Please try again later.",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                # If the message is unchanged, this will fail, so we catch it
                logger.error(f"Error updating message: {str(e)}")
        else:
            await query.message.reply_text("Invalid technical analysis callback data")
            
        return MAIN_MENU

    async def analysis_sentiment_callback(self, update: Update, context=None) -> int:
        """Handle market sentiment button press from a signal"""
        query = update.callback_query
        await query.answer()
        
        # Get callback data
        callback_data = query.data
        
        # Extract instrument and signal ID
        # Format: "analysis_sentiment_EURUSD_123456789"
        parts = callback_data.split("_")
        if len(parts) >= 4:
            instrument = parts[2]
            signal_id = parts[3]
            
            # Temporary response while actual sentiment analysis is prepared
            try:
                await query.edit_message_text(
                    text=f"Sorry, I couldn't analyze the market sentiment. Please try again later.",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                # If the message is unchanged, this will fail, so we catch it
                logger.error(f"Error updating message: {str(e)}")
        else:
            await query.message.reply_text("Invalid sentiment analysis callback data")
            
        return MAIN_MENU
        
    async def back_to_signal_callback(self, update: Update, context=None) -> int:
        """Handle back to signal button press"""
        query = update.callback_query
        await query.answer()
        
        # Get callback data and extract signal ID
        # Format: "back_to_signal_123456789"
        callback_data = query.data
        parts = callback_data.split("_")
        
        if len(parts) >= 3:
            signal_id = parts[3]
            user_id = str(update.effective_user.id)
            
            # Get original signal message if available
            if user_id in self.user_signals and signal_id in self.user_signals[user_id]:
                signal_data = self.user_signals[user_id][signal_id]
                message = signal_data.get('message', 'Signal information not available')
                
                try:
                    keyboard = [
                        [
                            InlineKeyboardButton("📊 Technical Analysis", callback_data=f"analysis_technical_{signal_data.get('instrument')}_signal_id"),
                            InlineKeyboardButton("📰 Market Sentiment", callback_data=f"analysis_sentiment_{signal_data.get('instrument')}_signal_id")
                        ],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]
                    ]
                    
                    await query.edit_message_text(
                        text=message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as e:
                    logger.error(f"Error updating message: {str(e)}")
            else:
                await query.edit_message_text(
                    text="Sorry, I couldn't find the original signal information.",
                    parse_mode=ParseMode.HTML
                )
        else:
            await query.message.reply_text("Invalid back to signal callback data")
            
        return MAIN_MENU

    async def analysis_calendar_callback(self, update: Update, context=None) -> int:
        """Handle analysis_calendar button press"""
        try:
            query = update.callback_query
            chat_id = update.effective_chat.id
            
            # Set callback answer
            try:
                await query.answer()
            except Exception as e:
                self.logger.error(f"Could not answer callback: {str(e)}")
            
            # Verwijder het huidige bericht/media voordat we de loading animatie tonen
            try:
                # Stap 1: Probeer het bericht te verwijderen
                await query.message.delete()
                self.logger.info("Successfully deleted previous message")
            except Exception as delete_error:
                self.logger.warning(f"Could not delete message: {str(delete_error)}")
                
                # Stap 2: Als verwijderen niet lukt, vervang met transparante GIF
                has_photo = bool(query.message.photo) or query.message.animation is not None
                
                if has_photo:
                    try:
                        # Gebruik een transparante GIF om de huidige afbeelding te vervangen
                        transparent_gif_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/Transparent.gif/1px-Transparent.gif"
                        
                        await query.edit_message_media(
                            media=InputMediaDocument(
                                media=transparent_gif_url,
                                caption="Loading calendar..."
                            )
                        )
                        self.logger.info("Replaced media with transparent GIF")
                    except Exception as media_error:
                        self.logger.warning(f"Could not replace media: {str(media_error)}")
                        
                        # Stap 3: Als laatste optie, pas alleen het bijschrift aan
                        try:
                            await query.edit_message_caption(
                                caption="Loading calendar...",
                            )
                            self.logger.info("Updated caption only")
                        except Exception as caption_error:
                            self.logger.warning(f"Could not update caption: {str(caption_error)}")
            
            # BELANGRIJK: Toon de loading animatie
            animation_url = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"
            
            # Verstuur de animatie
            try:
                loading_message = await context.bot.sendAnimation(
                    chat_id=chat_id,
                    animation=animation_url,
                    caption="<b>📅 Fetching economic calendar data...</b>",
                    parse_mode=ParseMode.HTML
                )
                self.logger.info("Successfully sent loading animation")
                
                # Check if it's an instrument-specific calendar request
                if query.data.startswith("analysis_calendar_signal_"):
                    instrument = query.data.replace("analysis_calendar_signal_", "")
                    self.logger.info(f"Showing economic calendar for instrument: {instrument}")
                    await self.show_economic_calendar(update, context, instrument, loading_message)
                else:
                    # Show calendar for all currencies
                    self.logger.info("Showing economic calendar for all currencies")
                    await self.show_economic_calendar(update, context, None, loading_message)
                
            except Exception as e:
                self.logger.error(f"Failed to send loading animation: {str(e)}")
                # Als de animatie mislukt, stuur een tekst bericht als fallback
                try:
                    loading_message = await context.bot.sendMessage(
                        chat_id=chat_id,
                        text="<b>📅 Loading economic calendar...</b>",
                        parse_mode=ParseMode.HTML
                    )
                    self.logger.info("Sent text loading message as fallback")
                    
                    # Check if it's an instrument-specific calendar request
                    if query.data.startswith("analysis_calendar_signal_"):
                        instrument = query.data.replace("analysis_calendar_signal_", "")
                        self.logger.info(f"Showing economic calendar for instrument: {instrument}")
                        await self.show_economic_calendar(update, context, instrument, loading_message)
                    else:
                        # Show calendar for all currencies
                        self.logger.info("Showing economic calendar for all currencies")
                        await self.show_economic_calendar(update, context, None, loading_message)
                except Exception as text_error:
                    self.logger.error(f"Failed to send text loading message: {str(text_error)}")
                    # Direct call to show_economic_calendar as last resort
                    if query.data.startswith("analysis_calendar_signal_"):
                        instrument = query.data.replace("analysis_calendar_signal_", "")
                        await self.show_economic_calendar(update, context, instrument)
                    else:
                        await self.show_economic_calendar(update, context)
            
            return ANALYSIS
        except Exception as e:
            self.logger.error(f"Error in analysis_calendar_callback: {str(e)}")
            self.logger.exception(e)
            
            chat_id = update.effective_chat.id
            
            # Create keyboard with retry button
            keyboard = [
                [InlineKeyboardButton("🔄 Try Again", callback_data="analysis_calendar")],
                [InlineKeyboardButton("⬅️ Back", callback_data="menu_analyse")]
            ]
            
            # Send error message
            await context.bot.send_message(
                chat_id=chat_id,
                text="<b>⚠️ Error showing economic calendar</b>\n\nSorry, there was an error retrieving the calendar data. Please try again later.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            return ANALYSIS

    async def show_economic_calendar(self, update: Update, context: CallbackContext, currency=None, loading_message=None):
        """Show the economic calendar for a specific currency"""
        try:
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
                # Get instrument-specific calendar
                instrument_calendar = await calendar_service.get_instrument_calendar(currency)
                
                # Extract the raw data for formatting
                try:
                    # Check if we can get the flattened data directly
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
                # Get all currencies data
                try:
                    calendar_data = await calendar_service.get_calendar()
                except Exception as e:
                    self.logger.warning(f"Error getting calendar data: {str(e)}")
                    calendar_data = []
            
            # Check if data is empty
            if not calendar_data or len(calendar_data) == 0:
                self.logger.warning("Calendar data is empty, trying mock data...")
                # Generate mock data
                today_date = datetime.now().strftime("%B %d, %Y")
                mock_data = calendar_service._generate_mock_calendar_data(MAJOR_CURRENCIES, today_date)
                
                # Flatten the mock data
                flattened_mock = []
                for currency, events in mock_data.items():
                    for event in events:
                        flattened_mock.append({
                            "time": event.get("time", ""),
                            "country": currency,
                            "country_flag": CURRENCY_FLAG.get(currency, ""),
                            "title": event.get("event", ""),
                            "impact": event.get("impact", "Low")
                        })
                
                calendar_data = flattened_mock
                self.logger.info(f"Generated {len(flattened_mock)} mock calendar events")
            
            # Format the calendar data in chronological order
            message = await self._format_calendar_events(calendar_data)
            
            # Create keyboard with back button
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="menu_analyse")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Probeer eerst het loading bericht te verwijderen
            if loading_message:
                try:
                    # Verwijder het loading bericht
                    await loading_message.delete()
                    self.logger.info("Successfully deleted loading message")
                except Exception as delete_error:
                    self.logger.warning(f"Could not delete loading message: {str(delete_error)}")
                    
                    # Als verwijderen niet lukt, probeer het te bewerken
                    try:
                        await context.bot.editMessageText(
                            chat_id=chat_id,
                            message_id=loading_message.message_id,
                            text=message,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                        self.logger.info("Edited loading message with calendar data")
                        return  # Skip sending a new message
                    except Exception as edit_error:
                        self.logger.warning(f"Could not edit loading message: {str(edit_error)}")
            
            # Send the message as a new message
            await context.bot.sendMessage(
                chat_id=chat_id,
                text=message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            self.logger.info("Sent calendar data as new message")
        
        except Exception as e:
            self.logger.error(f"Error showing economic calendar: {str(e)}")
            self.logger.exception(e)
            
            # Send error message
            chat_id = update.effective_chat.id
            await context.bot.sendMessage(
                chat_id=chat_id,
                text="<b>⚠️ Error showing economic calendar</b>\n\nSorry, there was an error retrieving the economic calendar data. Please try again later.",
                parse_mode=ParseMode.HTML
            )

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
        await query.answer()
        callback_data = query.data
        
        # Parse the market from callback data
        parts = callback_data.split("_")
        market = parts[1]  # Extract market type (forex, crypto, etc.)
        
        # Improved logging for debugging
        logger.info(f"Market callback processing: {callback_data}, parts={parts}")
        
        # Check if signal-specific context
        is_signals_context = False
        if callback_data.endswith("_signals"):
            is_signals_context = True
            logger.info(f"Signal context detected from callback_data: {callback_data}")
        elif context and hasattr(context, 'user_data'):
            is_signals_context = context.user_data.get('is_signals_context', False)
            logger.info(f"Signal context from user_data: {is_signals_context}")
        
        # Store market in context
        if context and hasattr(context, 'user_data'):
            context.user_data['market'] = market
            context.user_data['is_signals_context'] = is_signals_context
        
        logger.info(f"Market callback: market={market}, signals_context={is_signals_context}")
        
        # Determine which keyboard to show based on market and context
        keyboard = None
        text = ""
        back_data = ""
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
            
            # Specifieke keyboards voor verschillende analyse types
            if analysis_type == "sentiment":
                if market == "forex":
                    keyboard = FOREX_SENTIMENT_KEYBOARD
                elif market == "crypto":
                    keyboard = CRYPTO_SENTIMENT_KEYBOARD
                elif market == "indices":
                    keyboard = INDICES_SENTIMENT_KEYBOARD
                elif market == "commodities":
                    keyboard = COMMODITIES_SENTIMENT_KEYBOARD
                
                text = f"Select a {market} instrument for sentiment analysis:"
            elif analysis_type == "calendar":
                text = f"Select a {market} instrument for economic calendar:"
            else:
                text = f"Select a {market} instrument for analysis:"
            
            back_data = "back_to_analysis"  # Changed to back_to_analysis voor consistentie
        
        # DO NOT add back button here - they should already be included in keyboard definitions
        
        # Before updating message, check if the content has changed
        current_text = ""
        try:
            # Try to get current text or caption
            if query.message.caption:
                current_text = query.message.caption
            elif query.message.text:
                current_text = query.message.text
                
            # If content is the same, log and return without updating
            if current_text.strip() == text.strip():
                logger.info(f"Content already matches, skipping update. Current: '{current_text}', New: '{text}'")
                return CHOOSE_INSTRUMENT
        except Exception as e:
            logger.warning(f"Error checking current message content: {str(e)}")
        
        # Use the safe message update method
        success = await self._safe_message_update(query, text, keyboard)
        if not success:
            logger.error("Failed to update message in market_callback")
        
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
                # If the helper function failed, try our own update method
                await self._safe_message_update(
                    query, 
                    "Trading Signals Options:", 
                    SIGNALS_KEYBOARD
                )
            
            return CHOOSE_SIGNALS
        except Exception as e:
            logger.error(f"Error in menu_signals_callback: {str(e)}")
            
            # If we can't update with GIF, use the safe method
            await self._safe_message_update(
                query, 
                "Trading Signals Options:", 
                SIGNALS_KEYBOARD
            )
            return CHOOSE_SIGNALS

    async def signals_add_callback(self, update: Update, context=None) -> int:
        """Handle signals_add button press - show market selection for adding signals"""
        query = update.callback_query
        await query.answer()
        
        # Set the signals context flag
        if context and hasattr(context, 'user_data'):
            context.user_data['is_signals_context'] = True
        
        message = "Select market for signal subscription:"
        keyboard = MARKET_KEYBOARD_SIGNALS
        
        # Before updating message, check if the content has already been updated
        current_text = ""
        try:
            # Try to get current text or caption
            if query.message.caption:
                current_text = query.message.caption
            elif query.message.text:
                current_text = query.message.text
                
            # If content is the same, log and return without updating
            if current_text.strip() == message.strip():
                logger.info("Content already matches in signals_add_callback, skipping update")
                return CHOOSE_MARKET
        except Exception as e:
            logger.warning(f"Error checking current message content: {str(e)}")
        
        # Use the safer message update method
        success = await self._safe_message_update(query, message, keyboard)
        if not success:
            logger.error("Failed to update message in signals_add_callback")
        
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
            
            # Check if user already has this subscription
            user_id = update.effective_user.id
            
            # Check ONLY in the new table
            has_subscription = False
            
            try:
                # Only check the new signal_subscriptions table
                signal_subs = self.db.supabase.table('signal_subscriptions').select('*').eq('user_id', user_id).eq('instrument', instrument).execute()
                if signal_subs.data:
                    has_subscription = True
                    logger.info(f"User {user_id} already has a subscription for {instrument}")
                else:
                    logger.info(f"No existing subscription found for user {user_id} and instrument {instrument}")
            except Exception as e:
                logger.error(f"Error checking signal_subscriptions: {str(e)}")
            
            # If user already has this subscription, show a message
            if has_subscription:
                message = f"⚠️ You are already subscribed to {instrument} signals."
                keyboard = [
                    [InlineKeyboardButton("➕ Add Different Pair", callback_data="signals_add")],
                    [InlineKeyboardButton("⬅️ Back to Signals", callback_data="back_signals")]
                ]
                
                # Try multiple ways to update the message
                await self._safe_message_update(query, message, keyboard)
                return CHOOSE_SIGNALS
            
            # Directly subscribe the user to this instrument with its fixed timeframe
            success = await self.db.subscribe_to_instrument(user_id, instrument, timeframe)
            
            # Prepare message based on success
            if success:
                success_message = f"✅ Successfully subscribed to {instrument} ({timeframe_display}) signals!"
            else:
                success_message = f"⚠️ Your choice of {instrument} was saved, but there was an issue with the database. Please try again later or contact support."
            
            # Create a clean keyboard with only one "Add More Pairs" and one "Back to Signals" button
            keyboard = [
                [InlineKeyboardButton("➕ Add More Pairs", callback_data="signals_add")],
                [InlineKeyboardButton("⬅️ Back to Signals", callback_data="back_signals")]
            ]
            
            # Try multiple ways to update the message
            await self._safe_message_update(query, success_message, keyboard)
            return CHOOSE_SIGNALS
        else:
            # Instrument not found in mapping
            error_message = f"❌ Sorry, {instrument} is currently not available for signal subscription."
            
            # Show error and back button
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]]
            
            # Try multiple ways to update the message
            await self._safe_message_update(query, error_message, keyboard)
            return CHOOSE_MARKET
    
    async def _safe_message_update(self, query, message, keyboard):
        """Helper method to safely update message with multiple fallbacks"""
        try:
            # Check if message has media
            has_media = bool(query.message.photo) or query.message.animation is not None
            
            if has_media:
                # First try to edit the caption as it's most likely to succeed with media
                try:
                    await query.edit_message_caption(
                        caption=message,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    return True
                except Exception as caption_error:
                    logger.warning(f"Failed to update caption for media message: {str(caption_error)}")
                    
                    # As a fallback, try to delete and resend
                    try:
                        chat_id = query.message.chat_id
                        await query.message.delete()
                        await query.bot.send_message(
                            chat_id=chat_id,
                            text=message,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                        return True
                    except Exception as delete_error:
                        logger.warning(f"Failed to delete and resend message: {str(delete_error)}")
            
            # If no media or media handling failed, try normal text update
            await query.edit_message_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return True
        except Exception as text_error:
            logger.warning(f"Failed to update message text: {str(text_error)}")
            
            try:
                # Try to update caption as fallback
                await query.edit_message_caption(
                    caption=message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                return True
            except Exception as caption_error:
                logger.warning(f"Failed to update caption: {str(caption_error)}")
                
                try:
                    # Last resort: send a new message
                    await query.message.reply_text(
                        text=message,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    return True
                except Exception as e:
                    logger.error(f"All message update methods failed: {str(e)}")
                    return False
    
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
        
        # Prepare keyboard for analysis menu
        keyboard = ANALYSIS_KEYBOARD
        text = "Select your analysis type:"
        
        # Gebruik de juiste analyse GIF URL
        gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
        
        # Check if the message has a photo or animation that needs to be removed
        has_media = bool(query.message.photo) or query.message.animation is not None
        
        # Multi-step aanpak voor het verwijderen van media
        if has_media:
            # Stap 1: Probeer het bericht volledig te verwijderen en een nieuw bericht met GIF te sturen
            try:
                await query.message.delete()
                # Stuur een nieuw bericht met de analyse GIF
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=gif_url,
                    caption=text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                return CHOOSE_ANALYSIS
            except Exception as delete_error:
                logger.warning(f"Could not delete message: {str(delete_error)}")
                
                # Stap 2: Als verwijderen niet lukt, probeer de media te vervangen met de analyse GIF
                try:
                    # Vervang de huidige media met de analyse GIF
                    await query.edit_message_media(
                        media=InputMediaAnimation(
                            media=gif_url,
                            caption=text
                        ),
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return CHOOSE_ANALYSIS
                except Exception as media_error:
                    logger.warning(f"Could not replace media: {str(media_error)}")
                    
                    # Stap 3: Als laatste optie, probeer alleen het bijschrift te bewerken
                    try:
                        await query.edit_message_caption(
                            caption=text,
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        return CHOOSE_ANALYSIS
                    except Exception as caption_error:
                        logger.error(f"Could not edit caption: {str(caption_error)}")
                        
                        # Laatste redmiddel: stuur gewoon een nieuw bericht met GIF
                        await context.bot.send_animation(
                            chat_id=update.effective_chat.id,
                            animation=gif_url,
                            caption=text,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
        else:
            # Geen media, stuur een nieuw bericht met de analyse GIF
            try:
                # Verwijder het huidige bericht
                await query.message.delete()
                # Stuur een nieuw bericht met de analyse GIF
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=gif_url,
                    caption=text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.warning(f"Could not handle text message update: {str(e)}")
                # Probeer tekst te updaten met nieuwe tekst
                try:
                    await query.edit_message_text(
                        text=text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as text_error:
                    logger.error(f"Could not edit message text: {str(text_error)}")
                    # Laatste redmiddel: stuur een nieuw bericht met GIF
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif_url,
                        caption=text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
        
        return CHOOSE_ANALYSIS

    async def back_menu_callback(self, update: Update, context=None) -> int:
        """Handle back to main menu button press"""
        query = update.callback_query
        await query.answer()
        
        # Gebruik ALTIJD de correcte welkomst-GIF URL, nooit een dynamische URL
        welkomst_gif = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
        
        # Simpelere benadering: altijd bericht verwijderen en nieuw bericht sturen
        try:
            # Verwijder het huidige bericht
            await query.message.delete()
            
            # Stuur een nieuw bericht met de welkomst-GIF
            await context.bot.send_animation(
                chat_id=update.effective_chat.id,
                animation=welkomst_gif,
                caption=WELCOME_MESSAGE,
                reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                parse_mode=ParseMode.HTML
            )
            return MENU
        except Exception as e:
            logger.error(f"Fout bij terugkeer naar menu: {str(e)}")
            
            # Als verwijderen niet lukt, stuur toch een nieuw bericht
            try:
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=welkomst_gif,
                    caption=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
                return MENU
            except Exception as send_error:
                logger.error(f"Kon geen nieuw bericht sturen: {str(send_error)}")
                
                # Als laatste poging, probeer het bestaande bericht aan te passen
                try:
                    await query.edit_message_media(
                        media=InputMediaAnimation(
                            media=welkomst_gif,
                            caption=WELCOME_MESSAGE
                        ),
                        reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                    )
                except Exception as media_error:
                    logger.error(f"Kon media niet updaten: {str(media_error)}")
                    
                    # Als helemaal niets lukt, probeer tenminste de tekst te updaten
                    try:
                        await query.edit_message_text(
                            text=WELCOME_MESSAGE,
                            reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as text_error:
                        logger.error(f"Kon tekst niet updaten: {str(text_error)}")
        
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
            signal_data: Dict containing signal information from TradingView
                Expected format:
                {
                    "instrument": "{{ticker}}",
                    "signal": "{{strategy.order.action}}",
                    "price": {{close}},
                    "tp1": {{plot_0}},
                    "tp2": {{plot_1}},
                    "tp3": {{plot_2}},
                    "sl": {{plot_3}},
                    "interval": {{interval}}
                }
                
        Returns:
            bool: True if signal was processed successfully, False otherwise
        """
        try:
            # Extract required fields
            instrument = signal_data.get('instrument')
            timeframe = signal_data.get('timeframe', signal_data.get('interval'))
            
            # Get entry price and stop loss
            entry_price = signal_data.get('entry', signal_data.get('price'))
            stop_loss = signal_data.get('stop_loss', signal_data.get('sl'))
            
            # Determine signal direction based on stop loss position relative to entry
            if entry_price is not None and stop_loss is not None:
                try:
                    entry_price_float = float(entry_price)
                    stop_loss_float = float(stop_loss)
                    
                    # If stop loss is lower than entry, it's a BUY signal
                    # If stop loss is higher than entry, it's a SELL signal
                    direction = "buy" if stop_loss_float < entry_price_float else "sell"
                except (ValueError, TypeError):
                    # If we can't convert to float, use the provided signal
                    direction = signal_data.get('direction', signal_data.get('signal', '')).lower()
            else:
                # Fallback to signal field if no price comparison possible
                direction = signal_data.get('direction', signal_data.get('signal', '')).lower()
            
            # Basic validation
            if not instrument:
                logger.error("Missing instrument in signal data")
                return False
            
            if direction not in ['buy', 'sell']:
                logger.error(f"Invalid direction {direction} in signal data")
                return False
            
            # Extract take profit levels
            take_profit_1 = signal_data.get('take_profit', signal_data.get('tp1'))
            take_profit_2 = signal_data.get('tp2')
            take_profit_3 = signal_data.get('tp3')
            
            # Strategy name
            strategy = signal_data.get('strategy', 'TradingView Signal')
            
            # Format direction for display (uppercase)
            direction_display = "BUY 📈" if direction == "buy" else "SELL 📉"
            
            # Create signal ID for tracking
            signal_id = f"{instrument}_{direction}_{timeframe}_{int(time.time())}"

            # Generate AI verdict text
            if direction == "buy":
                ai_verdict = f"The {instrument} buy signal shows a promising setup with defined entry at {entry_price} and stop loss at {stop_loss}. Multiple take profit levels provide opportunities for partial profit taking."
            else:
                ai_verdict = f"The {instrument} sell signal presents a strong bearish opportunity with entry at {entry_price} and stop loss at {stop_loss}. The defined take profit levels allow for strategic exits."

            # Create signal message in the required format
            signal_message = f"""🎯 New Trading Signal 🎯

Instrument: {instrument}
Action: {direction_display}

Entry Price: {entry_price}
Stop Loss: {stop_loss} 🔴"""

            # Add take profit levels if available
            if take_profit_1:
                signal_message += f"\nTake Profit 1: {take_profit_1} 🎯"
            if take_profit_2:
                signal_message += f"\nTake Profit 2: {take_profit_2} 🎯"
            if take_profit_3:
                signal_message += f"\nTake Profit 3: {take_profit_3} 🎯"

            signal_message += f"""

Timeframe: {timeframe}
Strategy: {strategy}

————————————————————

Risk Management:
• Position size: 1-2% max
• Use proper stop loss
• Follow your trading plan

————————————————————

🤖 SigmaPips AI Verdict:
{ai_verdict}
"""
            
            # Determine market type for the instrument
            market_type = self.db._detect_market(instrument)
            
            # Create signal data structure for storage and future reference
            formatted_signal = {
                'id': signal_id,
                'timestamp': datetime.now().isoformat(),
                'instrument': instrument,
                'direction': direction,
                'timeframe': timeframe,
                'entry': entry_price,
                'stop_loss': stop_loss, 
                'take_profit_1': take_profit_1,
                'take_profit_2': take_profit_2,
                'take_profit_3': take_profit_3,
                'strategy': strategy,
                'market': market_type,
                'message': signal_message,
                'ai_verdict': ai_verdict
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
                        [
                            InlineKeyboardButton("📊 Technical Analysis", callback_data=f"analysis_technical_{instrument}_{signal_id}"),
                            InlineKeyboardButton("📰 Market Sentiment", callback_data=f"analysis_sentiment_{instrument}_{signal_id}")
                        ],
                        [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"analysis_calendar_{instrument}_{signal_id}")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]
                    ]
                    
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
        """Initialize the bot"""
        try:
            self.logger.info("Initializing bot")
            
            # Load signals and subscribers from database
            self._load_signals()
            
            # Setup the bot's webhook
            if use_webhook:
                self.logger.info(f"Setting webhook to {self.webhook_url}")
                await self.bot.set_webhook(url=self.webhook_url)
                self.logger.info("Webhook set")
            else:
                # Remove any existing webhook and clear all pending updates
                self.logger.info("Using polling method, removing any existing webhook")
                await self.bot.delete_webhook(drop_pending_updates=True)
                
                # Wait a short time to ensure webhook is fully removed
                await asyncio.sleep(1)
                
                # Try to get updates with a high offset to clear the queue
                try:
                    # Forcefully clear pending updates
                    self.logger.info("Forcefully clearing update queue")
                    await self.bot.get_updates(offset=-1, limit=1, timeout=1)
                    await self.bot.get_updates(offset=999999999, timeout=1)
                    self.logger.info("Update queue cleared")
                    
                    # Give some time for Telegram servers to process
                    await asyncio.sleep(2)
                    
                    if hasattr(self, 'application') and hasattr(self.application, 'update_queue'):
                        # Also clear the application queue
                        while not self.application.update_queue.empty():
                            try:
                                self.application.update_queue.get_nowait()
                            except:
                                break
                                
                except Exception as e:
                    self.logger.warning(f"Error clearing update queue: {str(e)}")
            
            self.initialized = True
            self.logger.info("Bot initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Error initializing bot: {str(e)}")
            self.logger.exception(e)

    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Show the main menu when /menu command is used"""
        # Directly call the show_main_menu method
        await self.show_main_menu(update, context)

    async def _format_calendar_events(self, calendar_data):
        """Format calendar events in chronological order"""
        # Format the calendar message
        message = f"<b>📅 Economic Calendar for Today</b>\n\n"
        
        if not calendar_data or len(calendar_data) == 0:
            return message + "No economic events scheduled for today.\n"
        
        # Sort events by time
        calendar_data.sort(key=lambda x: self._parse_time_for_sorting(x.get('time', '00:00')))
        
        # Format each event in chronological order
        for event in calendar_data:
            time = event.get('time', 'N/A')
            country = event.get('country', 'N/A')
            country_flag = event.get('country_flag', '')
            title = event.get('title', 'N/A')
            impact = event.get('impact', 'Low')
            
            # Format impact with emoji
            impact_emoji = "🔴" if impact == "High" else "🟠" if impact == "Medium" else "🟢"
            
            # Add event to message
            message += f"{time} - {country_flag} {country} - {title} {impact_emoji}\n"
        
        # Add impact legend at the bottom
        message += "\n-------------------\n"
        message += "🔴 High Impact\n"
        message += "🟠 Medium Impact\n"
        message += "🟢 Low Impact"
        
        return message
    
    def _parse_time_for_sorting(self, time_str: str) -> int:
        """Parse time string to minutes for sorting"""
        # Default value
        minutes = 0
        
        try:
            # Extract only time part if it contains timezone
            if " " in time_str:
                time_parts = time_str.split(" ")
                time_str = time_parts[0]
                
            # Handle AM/PM format
            if "AM" in time_str.upper() or "PM" in time_str.upper():
                # Parse 12h format
                time_only = time_str.upper().replace("AM", "").replace("PM", "").strip()
                parts = time_only.split(":")
                hours = int(parts[0])
                minutes_part = int(parts[1]) if len(parts) > 1 else 0
                
                # Add 12 hours for PM times (except 12 PM)
                if "PM" in time_str.upper() and hours < 12:
                    hours += 12
                # 12 AM should be 0
                if "AM" in time_str.upper() and hours == 12:
                    hours = 0
                
                minutes = hours * 60 + minutes_part
            else:
                # Handle 24h format
                parts = time_str.split(":")
                if len(parts) >= 2:
                    hours = int(parts[0])
                    minutes_part = int(parts[1])
                    minutes = hours * 60 + minutes_part
        except Exception:
            # In case of parsing error, default to 0
            minutes = 0
            
        return minutes

    def _get_calendar_service(self):
        """Get or create an instance of the EconomicCalendarService"""
        try:
            if not hasattr(self, 'calendar_service') or self.calendar_service is None:
                self.logger.info("Creating new EconomicCalendarService instance")
                from trading_bot.services.calendar_service.calendar import EconomicCalendarService
                self.calendar_service = EconomicCalendarService()
            return self.calendar_service
        except Exception as e:
            self.logger.error(f"Error getting calendar service: {str(e)}")
            self.logger.exception(e)
            # If all else fails, create a new instance
            from trading_bot.services.calendar_service.calendar import EconomicCalendarService
            return EconomicCalendarService()

    async def signals_manage_callback(self, update: Update, context=None) -> int:
        """Handle signals_manage callback to manage signal preferences"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get user's current subscriptions ONLY from the new table
            user_id = update.effective_user.id
            
            # Get subscriptions from the new table only
            signal_subs = self.db.supabase.table('signal_subscriptions').select('*').eq('user_id', user_id).execute()
            preferences = signal_subs.data if signal_subs.data else []
            
            # No longer using the old table data
            # old_subs = self.db.supabase.table('subscriber_preferences').select('*').eq('user_id', user_id).execute()
            # if old_subs.data:
            #    preferences.extend(old_subs.data)
            
            if not preferences:
                # No subscriptions yet
                message = "You don't have any signal subscriptions yet. Add some first!"
                keyboard = [
                    [InlineKeyboardButton("➕ Add Signal Pairs", callback_data=CALLBACK_SIGNALS_ADD)],
                    [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_SIGNALS)]
                ]
                
                # Use safe message update
                await self._safe_message_update(query, message, keyboard)
                return CHOOSE_SIGNALS
            
            # Format current subscriptions
            message = "<b>Your Signal Subscriptions:</b>\n\n"
            
            # Store preferences in context for later use in deletion
            if context and hasattr(context, 'user_data'):
                context.user_data['preferences'] = preferences
            
            # Create keyboard with delete buttons for each preference
            keyboard = []
            
            for i, pref in enumerate(preferences, 1):
                pref_id = pref.get('id', 'unknown')
                market = pref.get('market', 'unknown')
                instrument = pref.get('instrument', 'unknown')
                timeframe = pref.get('timeframe', '1h')
                
                # Add text to the message
                message += f"{i}. {market.upper()} - {instrument} ({timeframe})\n"
                
                # Add a delete button for this preference
                keyboard.append([InlineKeyboardButton(f"🗑️ Delete {instrument}", callback_data=f"delete_pref_{pref_id}")])
            
            # Add general navigation buttons
            keyboard.append([InlineKeyboardButton("➕ Add More", callback_data=CALLBACK_SIGNALS_ADD)])
            keyboard.append([InlineKeyboardButton("🗑️ Delete All", callback_data="remove_all_subscriptions")])
            keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_SIGNALS)])
            
            # Use our safe message update method
            success = await self._safe_message_update(query, message, keyboard)
            if not success:
                logger.error("Failed to update message in signals_manage_callback")
                
                # Try one more time with a simpler message as a last resort
                simple_message = "Error displaying your subscriptions. Please try again."
                simple_keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_SIGNALS)]]
                await self._safe_message_update(query, simple_message, simple_keyboard)
            
            return CHOOSE_SIGNALS
        except Exception as e:
            logger.error(f"Error in signals_manage_callback: {str(e)}")
            logger.exception(e)
            
            # Use safe message update for error handling
            message = "An error occurred while retrieving your subscriptions. Please try again."
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_SIGNALS)]]
            await self._safe_message_update(query, message, keyboard)
            
            return CHOOSE_SIGNALS

    async def remove_subscription_callback(self, update: Update, context=None) -> int:
        """Handle removal of a subscription"""
        query = update.callback_query
        await query.answer()
        
        # Extract the subscription ID from the callback data
        callback_data = query.data
        
        try:
            if callback_data.startswith("delete_pref_"):
                # Extract the preference ID
                pref_id = callback_data.split("_")[2]
                logger.info(f"Attempting to delete subscription with ID: {pref_id}")
                
                # Only delete from the new table
                success = False
                
                try:
                    # Try to delete from the new table
                    response = self.db.supabase.table('signal_subscriptions').delete().eq('id', pref_id).execute()
                    if response and response.data:
                        success = True
                        logger.info(f"Successfully deleted subscription with ID {pref_id}")
                    else:
                        logger.warning(f"No rows affected when deleting subscription with ID {pref_id}")
                except Exception as e:
                    logger.error(f"Error deleting from signal_subscriptions: {str(e)}")
                
                # Provide feedback
                if success:
                    message = f"Subscription was deleted successfully."
                else:
                    message = f"Failed to delete subscription. Please try again."
                
                # Show a temporary feedback message with safe update
                keyboard = [[InlineKeyboardButton("⬅️ Back to Subscriptions", callback_data=CALLBACK_SIGNALS_MANAGE)]]
                await self._safe_message_update(query, message, keyboard)
                
                return CHOOSE_SIGNALS
                
            elif callback_data == "remove_all_subscriptions":
                # Delete all subscriptions for this user
                user_id = update.effective_user.id
                logger.info(f"Attempting to delete all subscriptions for user {user_id}")
                
                # Only delete from the new table
                try:
                    # Delete from the new table only
                    response = self.db.supabase.table('signal_subscriptions').delete().eq('user_id', user_id).execute()
                    
                    # Check if any rows were affected
                    if response and response.data and len(response.data) > 0:
                        success = True
                        num_deleted = len(response.data)
                        logger.info(f"Successfully deleted {num_deleted} subscriptions for user {user_id}")
                    else:
                        success = False
                        logger.warning(f"No subscriptions found to delete for user {user_id}")
                except Exception as e:
                    success = False
                    logger.error(f"Error deleting all subscriptions: {str(e)}")
                
                if success:
                    message = f"All your subscriptions have been deleted."
                else:
                    message = "No subscriptions found to delete."
                
                # Show a temporary feedback message with safe update
                keyboard = [[InlineKeyboardButton("⬅️ Back to Signals", callback_data=CALLBACK_BACK_SIGNALS)]]
                await self._safe_message_update(query, message, keyboard)
                
                return CHOOSE_SIGNALS
        
        except Exception as e:
            logger.error(f"Error in remove_subscription_callback: {str(e)}")
            logger.exception(e)
            
            # Use safe message update for error
            message = "An error occurred while processing your request."
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_SIGNALS)]]
            await self._safe_message_update(query, message, keyboard)
            
            return CHOOSE_SIGNALS

    async def back_signals_callback(self, update: Update, context=None) -> int:
        """Handle back to signals menu button press"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get the signals GIF URL
            from trading_bot.services.telegram_service.gif_utils import get_signals_gif
            gif_url = await get_signals_gif()
            
            # Try using the gif_utils helper first
            from trading_bot.services.telegram_service.gif_utils import update_message_with_gif
            success = await update_message_with_gif(
                query=query,
                gif_url=gif_url,
                text="Trading Signals Options:",
                reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
            )
            
            if not success:
                # If gif update fails, use our safe message update
                await self._safe_message_update(
                    query,
                    "Trading Signals Options:",
                    SIGNALS_KEYBOARD
                )
            
            return CHOOSE_SIGNALS
        except Exception as e:
            logger.error(f"Error in back_signals_callback: {str(e)}")
            
            # Use safe message update as fallback
            await self._safe_message_update(
                query,
                "Trading Signals Options:",
                SIGNALS_KEYBOARD
            )
            
            return CHOOSE_SIGNALS

    async def back_analysis_callback(self, update: Update, context=None) -> int:
        """Handle back to analysis menu button press"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Show the analysis menu
            await query.edit_message_text(
                text="Choose an analysis type:",
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                parse_mode=ParseMode.HTML
            )
            
            return CHOOSE_ANALYSIS
        except Exception as e:
            # If there's an error with editing message text, it might be a media message
            if "There is no text in the message to edit" in str(e):
                try:
                    await query.edit_message_caption(
                        caption="Choose an analysis type:",
                        reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                    return CHOOSE_ANALYSIS
                except Exception as caption_e:
                    logger.error(f"Failed to edit caption: {str(caption_e)}")
            
            # Last resort fallback
            logger.error(f"Error in back_analysis_callback: {str(e)}")
            try:
                await query.message.reply_text(
                    text="Choose an analysis type:",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
            except Exception as reply_e:
                logger.error(f"Could not send reply message: {str(reply_e)}")
            
            return CHOOSE_ANALYSIS

    async def button_callback(self, update: Update, context=None) -> int:
        """Handle all button callbacks"""
        query = update.callback_query
        callback_data = query.data
        
        try:
            # For multi-chain callbacks, answer right away
            await query.answer()
            
            # Log the callback data for debugging
            logger.info(f"Button callback received: {callback_data}")
            
            # Main menu actions
            if callback_data == CALLBACK_MENU_ANALYSE:
                return await self.menu_analyse_callback(update, context)
            elif callback_data == CALLBACK_MENU_SIGNALS:
                return await self.menu_signals_callback(update, context)
            
            # Analysis actions
            elif callback_data == CALLBACK_ANALYSIS_TECHNICAL:
                return await self.analysis_technical_callback(update, context)
            elif callback_data == CALLBACK_ANALYSIS_SENTIMENT:
                return await self.analysis_sentiment_callback(update, context)
            elif callback_data == CALLBACK_ANALYSIS_CALENDAR:
                return await self.analysis_calendar_callback(update, context)
            
            # Signal analysis actions from new format signals
            elif callback_data.startswith("analysis_technical_"):
                return await self.analysis_technical_callback(update, context)
            elif callback_data.startswith("analysis_sentiment_"):
                return await self.analysis_sentiment_callback(update, context)
            elif callback_data.startswith("back_to_signal_"):
                return await self.back_to_signal_callback(update, context)
            
            # Back actions
            elif callback_data == CALLBACK_BACK_MENU:
                return await self.back_menu_callback(update, context)
            elif callback_data == CALLBACK_BACK_ANALYSIS:
                return await self.back_analysis_callback(update, context)
            elif callback_data == CALLBACK_BACK_MARKET:
                return await self.back_market_callback(update, context)
            elif callback_data == CALLBACK_BACK_INSTRUMENT:
                return await self.back_instrument_callback(update, context)
            elif callback_data == CALLBACK_BACK_SIGNALS:
                return await self.back_signals_callback(update, context)
                
            # Signal callbacks
            elif callback_data == CALLBACK_SIGNALS_ADD:
                return await self.signals_add_callback(update, context)
            elif callback_data == CALLBACK_SIGNALS_MANAGE:
                return await self.signals_manage_callback(update, context)
            
            # Subscription management
            elif callback_data == "remove_all_subscriptions" or callback_data.startswith("delete_pref_"):
                return await self.remove_subscription_callback(update, context)
            
            # Market and instrument selection
            # Handle market selection for signals differently from regular market selection
            elif callback_data.startswith("market_") and callback_data.endswith("_signals"):
                logger.info(f"Routing to market_callback for signals: {callback_data}")
                # Set signals context flag first
                if context and hasattr(context, 'user_data'):
                    context.user_data['is_signals_context'] = True
                return await self.market_callback(update, context)
            elif callback_data.startswith("market_"):
                logger.info(f"Routing to market_callback for analysis: {callback_data}")
                # Clear signals context flag
                if context and hasattr(context, 'user_data'):
                    context.user_data['is_signals_context'] = False
                return await self.market_callback(update, context)
            elif callback_data.startswith("instrument_") and callback_data.endswith("_signals"):
                logger.info(f"Routing to instrument_signals_callback: {callback_data}")
                return await self.instrument_signals_callback(update, context)
            elif callback_data.startswith("instrument_"):
                logger.info(f"Routing to instrument_callback for analysis: {callback_data}")
                return await self.instrument_callback(update, context)
            
            # Signal analysis callbacks
            elif callback_data == "signal_technical":
                return await self.signal_technical_callback(update, context)
            elif callback_data == "signal_sentiment":
                return await self.signal_sentiment_callback(update, context)
            elif callback_data == "signal_calendar":
                return await self.signal_calendar_callback(update, context)
            elif callback_data == "back_to_signal":
                return await self.back_to_signal_callback(update, context)
            elif callback_data == "back_to_signal_analysis":
                return await self.back_to_signal_analysis_callback(update, context)
            elif callback_data.startswith("analyze_from_signal_"):
                return await self.analyze_from_signal_callback(update, context)
            
            # Subscription management
            elif callback_data.startswith("subscribe_"):
                return await self.handle_subscription_callback(update, context)
            
            logger.warning(f"Unknown callback data: {callback_data}")
            return MENU
            
        except Exception as e:
            logger.error(f"Error handling button callback: {str(e)}")
            logger.exception(e)
            return MENU
