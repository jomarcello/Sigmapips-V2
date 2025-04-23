import os
import json
import asyncio
import traceback
from typing import Dict, Any, List, Optional, Union, Tuple, Set
from datetime import datetime, timedelta
import logging
import copy
import re
import time
import random

from fastapi import FastAPI, Request, HTTPException, status
from telegram import Bot, Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, InputMediaPhoto, InputMediaAnimation, InputMediaDocument, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile
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
from trading_bot.services.calendar_service import EconomicCalendarService
from trading_bot.services.payment_service.stripe_service import StripeService
from trading_bot.services.payment_service.stripe_config import get_subscription_features
from trading_bot.services.telegram_service.states import (
    MENU, ANALYSIS, SIGNALS, CHOOSE_MARKET, CHOOSE_INSTRUMENT, CHOOSE_STYLE,
    CHOOSE_ANALYSIS, SIGNAL_DETAILS, SIGNAL_ANALYSIS,
    CALLBACK_MENU_ANALYSE, CALLBACK_MENU_SIGNALS, CALLBACK_ANALYSIS_TECHNICAL,
    CALLBACK_ANALYSIS_SENTIMENT, CALLBACK_ANALYSIS_CALENDAR, CALLBACK_SIGNALS_ADD,
    CALLBACK_SIGNALS_MANAGE, CALLBACK_BACK_MENU,
    MARKET_FOREX, MARKET_CRYPTO, MARKET_COMMODITIES, MARKET_INDICES
)
import trading_bot.services.telegram_service.gif_utils as gif_utils

# Initialize logger
logger = logging.getLogger(__name__)

# Major currencies to focus on
MAJOR_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"]

# Currency to flag emoji mapping
CURRENCY_FLAG = {
    "USD": "🇺🇸",
    "EUR": "🇪🇺",
    "GBP": "🇬🇧",
    "JPY": "🇯🇵",
    "CHF": "🇨🇭",
    "AUD": "🇦🇺",
    "NZD": "🇳🇿",
    "CAD": "🇨🇦"
}

# Map of instruments to their corresponding currencies
INSTRUMENT_CURRENCY_MAP = {
    # Special case for global view
    "GLOBAL": MAJOR_CURRENCIES,
    
    # Forex
    "EURUSD": ["EUR", "USD"],
    "GBPUSD": ["GBP", "USD"],
    "USDJPY": ["USD", "JPY"],
    "USDCHF": ["USD", "CHF"],
    "AUDUSD": ["AUD", "USD"],
    "NZDUSD": ["NZD", "USD"],
    "USDCAD": ["USD", "CAD"],
    "EURGBP": ["EUR", "GBP"],
    "EURJPY": ["EUR", "JPY"],
    "GBPJPY": ["GBP", "JPY"],
    
    # Indices (mapped to their related currencies)
    "US30": ["USD"],
    "US100": ["USD"],
    "US500": ["USD"],
    "UK100": ["GBP"],
    "GER40": ["EUR"],
    "FRA40": ["EUR"],
    "ESP35": ["EUR"],
    "JP225": ["JPY"],
    "AUS200": ["AUD"],
    
    # Commodities (mapped to USD primarily)
    "XAUUSD": ["USD", "XAU"],  # Gold
    "XAGUSD": ["USD", "XAG"],  # Silver
    "USOIL": ["USD"],          # Oil (WTI)
    "UKOIL": ["USD", "GBP"],   # Oil (Brent)
    
    # Crypto
    "BTCUSD": ["USD", "BTC"],
    "ETHUSD": ["USD", "ETH"],
    "LTCUSD": ["USD", "LTC"],
    "XRPUSD": ["USD", "XRP"]
}

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

# Signal analysis keyboard
SIGNAL_ANALYSIS_KEYBOARD = [
    [InlineKeyboardButton("📈 Technical Analysis", callback_data="signal_technical")],
    [InlineKeyboardButton("🧠 Market Sentiment", callback_data="signal_sentiment")],
    [InlineKeyboardButton("📅 Economic Calendar", callback_data="signal_calendar")],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal")]
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
        InlineKeyboardButton("US500", callback_data="instrument_US500_signals"),
        InlineKeyboardButton("US100", callback_data="instrument_US100_signals")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
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
    "USDJPY": "H1",  # USDJPY toegevoegd voor signaalabonnementen
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
    "DE40": "M30",
    "BTCUSD": "M30",  # Added for consistency with CRYPTO_KEYBOARD_SIGNALS
    "US100": "M30",   # Added for consistency with INDICES_KEYBOARD_SIGNALS
    "XAGUSD": "M15",  # Added for consistency with COMMODITIES_KEYBOARD_SIGNALS
    "USOIL": "M30"    # Added for consistency with COMMODITIES_KEYBOARD_SIGNALS
    
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
    def __init__(self, db: Database, stripe_service=None, bot_token: Optional[str] = None, proxy_url: Optional[str] = None, lazy_init: bool = False):
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
        
        # Configure custom request handler with significantly improved connection settings
        # These increased timeout values should help with "service unavailable" errors
        request = HTTPXRequest(
            connection_pool_size=100,    # Increased from 50
            connect_timeout=30.0,        # Increased from 15.0
            read_timeout=90.0,           # Increased from 45.0 
            write_timeout=60.0,          # Increased from 30.0
            pool_timeout=120.0           # Increased from 60.0
        )
        
        # Initialize the bot directly with connection pool settings
        try:
            self.bot = Bot(token=self.bot_token, request=request)
            logger.info("Bot instance created successfully with improved connection settings")
        except Exception as e:
            logger.error(f"Error creating Bot instance: {str(e)}")
            raise
            
        self.application = None  # Will be initialized in setup()
        
        # Webhook configuration
        self.webhook_url = os.getenv("WEBHOOK_URL", "")
        self.webhook_path = "/webhook"  # Always use this path
        if self.webhook_url.endswith("/"):
            self.webhook_url = self.webhook_url[:-1]  # Remove trailing slash
            
        logger.info(f"Bot initialized with webhook URL: {self.webhook_url} and path: {self.webhook_path}")
        
        # Initialize API services
        self.chart_service = ChartService()  # Initialize chart service
        # Lazy load services only when needed
        self._calendar_service = None
        self._sentiment_service = None
        
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
            
            # Application initialization with additional parameters for reliability
            self.application = Application.builder().bot(self.bot).concurrent_updates(True).build()
        
            # Register the handlers
            self._register_handlers(self.application)
            
            # Initialize user_signals dictionary (will be populated later)
            self.user_signals = {}
        
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
            
    async def run(self):
        """Run the telegram service with retry mechanism for Telegram API connection issues"""
        logger.info("TelegramService.run() called")
        instance_id = os.getenv("BOT_INSTANCE_ID", "unknown")
        logger.info(f"Bot instance ID: {instance_id}")
        
        # Record last reset time to avoid excessive resets
        last_reset_time = 0
        
        # First try to initialize and set up the bot properly
        try:
            # Create a file-based lock to ensure only one instance is running at a time
            # This is the most reliable method to prevent conflicts between bot instances
            lock_path = "/tmp/telegram_bot.lock"
            
            # Try to create a lock file
            try:
                # Get process ID
                pid = os.getpid()
                
                # Check if lock file exists
                if os.path.exists(lock_path):
                    # Read the existing lock file
                    try:
                        with open(lock_path, 'r') as f:
                            existing_pid_str = f.read().strip()
                            existing_instance = f.read().strip()
                            logger.warning(f"Existing lock file found with PID: {existing_pid_str}, instance: {existing_instance}")
                            
                            # Try to check if process is still running (Linux/Unix only)
                            if os.name != 'nt':  # Not Windows
                                try:
                                    existing_pid = int(existing_pid_str)
                                    os.kill(existing_pid, 0)  # This will raise OSError if process is not running
                                    logger.error(f"⚠️ Another bot instance is already running with PID {existing_pid}! Using this instance {instance_id} as backup.")
                                except (ValueError, OSError):
                                    # Process is not running, we can take over
                                    logger.info(f"Taking over lock from non-running process: {existing_pid_str}")
                                    os.remove(lock_path)
                    except Exception as read_err:
                        logger.warning(f"Error reading lock file: {str(read_err)}")
                        os.remove(lock_path)
                
                # Create our lock file
                with open(lock_path, 'w') as f:
                    f.write(f"{pid}\n{instance_id}")
                logger.info(f"Created lock file for instance {instance_id} with PID {pid}")
            except Exception as lock_err:
                logger.warning(f"Error managing lock file: {str(lock_err)}")
            
            # Initialize the application if not already initialized
            if not hasattr(self.application, '_initialized') or not self.application._initialized:
                await self.application.initialize()
                logger.info("Application initialized successfully")
            
            # Start the application (this starts the required components)
            if not hasattr(self.application, '_running') or not self.application._running:
                await self.application.start()
                logger.info("Application started successfully")
            
            # Determine if we should use polling based on environment or settings
            use_polling = os.getenv("FORCE_POLLING", "").lower() == "true"
            is_local_env = not self.webhook_url or self.webhook_url == ""
            
            # ALWAYS clear the webhook first - this helps prevent the conflict error
            logger.info("🔥 Force-clearing webhook and pending updates to prevent conflicts")
            try:
                await self.bot.delete_webhook(drop_pending_updates=True)
                # Allow time for webhook deletion to propagate
                await asyncio.sleep(2)
                logger.info("Webhook cleared successfully")
                
                # Send a dummy getUpdates with a specific offset to reset any existing sessions
                # This helps break free from the "terminated by other getUpdates request" error
                await self.bot.get_updates(offset=-1, limit=1, timeout=1, allowed_updates=[])
                logger.info("Successfully reset update session with dummy request")
            except Exception as clear_e:
                logger.warning(f"Error while clearing webhook: {str(clear_e)}")
                # Don't fail completely on this error, continue trying
            
            # First validate connection to Telegram with a getMe request before deciding polling/webhook
            # Special handling for service unavailable errors
            logger.info("Testing connection to Telegram API with getMe...")
            connection_attempts = 0
            max_connection_attempts = 20  # Increased from 5 to 20
            connection_delay = 5  # Start with 5 seconds
            
            # Keep trying to connect until we succeed or reach max attempts
            while connection_attempts < max_connection_attempts:
                try:
                    # Send a test request to Telegram API
                    me = await self.bot.get_me()
                    logger.info(f"✅ Successfully connected to Telegram API. Bot: {me.first_name} (@{me.username})")
                    # Break the loop if we succeeded
                    break
                except telegram.error.Conflict as conflict_err:
                    connection_attempts += 1
                    logger.error(f"Conflict error during connection attempt {connection_attempts}: {str(conflict_err)}")
                    
                    # Perform a reset procedure to break out of conflict state
                    try:
                        # More aggressive session reset with random jitter to avoid collisions
                        wait_time = 3 + random.uniform(0, 5)
                        logger.info(f"Waiting {wait_time:.1f}s before conflict recovery...")
                        await asyncio.sleep(wait_time)
                        
                        # Try to reset the session state 
                        await self.bot.delete_webhook(drop_pending_updates=True)
                        # Use a very large offset to reset getUpdates state
                        await self.bot.get_updates(offset=999999999, limit=1, timeout=1)
                        
                        # If we've tried multiple times without success, try to rebuild the bot
                        if connection_attempts > 5:
                            logger.info("Rebuilding bot instance after multiple conflict errors")
                            
                            # Create new request handler
                            request = HTTPXRequest(
                                connection_pool_size=100,
                                connect_timeout=30.0,
                                read_timeout=90.0,
                                write_timeout=60.0,
                                pool_timeout=120.0
                            )
                            
                            # Create new bot instance
                            self.bot = Bot(token=self.bot_token, request=request)
                            
                            # Create new application with the bot
                            self.application = Application.builder().bot(self.bot).build()
                            self._register_handlers(self.application)
                            
                            # Initialize and start the new application
                            await self.application.initialize()
                            await self.application.start()
                    except Exception as reset_err:
                        logger.error(f"Error during conflict recovery: {str(reset_err)}")
                    
                    # Increase delay for next attempt
                    connection_delay = min(30, connection_delay * 1.2)
                except Exception as e:
                    connection_attempts += 1
                    
                    # Log the specific error type to help diagnose the issue
                    error_type = type(e).__name__
                    error_msg = str(e)
                    logger.error(f"Connection attempt {connection_attempts}/{max_connection_attempts} failed: {error_type} - {error_msg}")
                    
                    # Check if we've hit the maximum attempts
                    if connection_attempts >= max_connection_attempts:
                        logger.error(f"⚠️ Maximum connection attempts ({max_connection_attempts}) reached. Cannot connect to Telegram API.")
                        # We'll continue to the next part as a last resort but log this clearly
                        logger.error("Continuing despite connection failure, but this may cause issues")
                        break
                    
                    # Use a different message format to better track in logs
                    logger.info(f"Attempt #{connection_attempts} failed with service unavailable. Retrying in {connection_delay}s...")
                    
                    # Wait before retrying with a moderately increasing delay
                    await asyncio.sleep(connection_delay)
                    # Increase delay with some randomness, but cap it to avoid very long waits
                    # Use a gentler backoff for service unavailable
                    connection_delay = min(30, connection_delay * 1.2 + random.uniform(0, 2))
                    
                    # Try to recover by clearing the session every few attempts
                    if connection_attempts % 5 == 0:
                        logger.info("Attempting recovery by clearing webhook and session...")
                        try:
                            await self.bot.delete_webhook(drop_pending_updates=True)
                            # Try a different approach to reset session
                            await self.bot.get_updates(offset=999999999, limit=1, timeout=1)
                        except Exception:
                            pass  # Ignore errors during recovery attempt
            
            # Try to use a proxy if connection failed despite retries
            if connection_attempts >= max_connection_attempts:
                logger.warning("Attempting to set up bot with proxy as direct connection failed")
                try:
                    # Check if we have a proxy URL in environment
                    proxy_url = os.getenv("TELEGRAM_PROXY_URL", "")
                    if proxy_url:
                        logger.info(f"Trying connection with proxy: {proxy_url}")
                        # Create a new request handler with proxy
                        proxy_request = HTTPXRequest(
                            connection_pool_size=100,
                            connect_timeout=30.0,
                            read_timeout=90.0,
                            write_timeout=60.0,
                            pool_timeout=120.0,
                            proxy=proxy_url
                        )
                        # Create a new bot instance with proxy
                        proxy_bot = Bot(token=self.bot_token, request=proxy_request)
                        # Test the connection
                        me = await proxy_bot.get_me()
                        logger.info(f"✅ Successfully connected via proxy. Bot: {me.first_name}")
                        # Replace our bot instance with the proxy-enabled one
                        self.bot = proxy_bot
                        # Recreate application with proxy-enabled bot
                        self.application = Application.builder().bot(self.bot).build()
                        self._register_handlers(self.application)
                        await self.application.initialize()
                        await self.application.start()
                    else:
                        logger.warning("No proxy URL available to try as fallback")
                except Exception as proxy_e:
                    logger.error(f"Failed to connect with proxy: {str(proxy_e)}")
            
            # Use polling if there's no webhook URL or explicitly forced
            if use_polling or is_local_env:
                logger.info("Starting bot in polling mode...")
                # Make sure the updater isn't already running
                if hasattr(self.application, 'updater') and self.application.updater.running:
                    await self.application.updater.stop()
                
                # Delete any existing webhook
                await self.bot.delete_webhook(drop_pending_updates=True)
                
                # Start polling with drop_pending_updates to avoid old message conflicts
                try:
                    # Custom parameters to help with network issues
                    poll_interval = float(os.getenv("POLL_INTERVAL", "1.0"))
                    poll_timeout = int(os.getenv("POLL_TIMEOUT", "30"))
                    logger.info(f"Using poll_interval={poll_interval}s, timeout={poll_timeout}s")
                    
                    await self.application.updater.start_polling(
                        poll_interval=poll_interval, 
                        timeout=poll_timeout, 
                        drop_pending_updates=True,
                        allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
                        read_timeout=90.0,  # Increased read timeout
                        write_timeout=60.0  # Increased write timeout
                    )
                    self.polling_started = True
                    logger.info("Bot started in polling mode")
                except telegram.error.Conflict as conflict_err:
                    # Handle the conflict error specifically
                    logger.error(f"Conflict error when starting polling: {conflict_err}")
                    
                    # Only do a hard reset if we haven't done one recently
                    current_time = time.time()
                    if current_time - last_reset_time > 60:  # Only reset once per minute maximum
                        logger.info("🚨 Detected conflict with another bot instance. Attempting recovery...")
                        last_reset_time = current_time
                        
                        # Wait for a random time to avoid multiple instances trying to recover simultaneously
                        wait_time = 5 + random.randint(1, 10)
                        logger.info(f"Waiting {wait_time} seconds before recovery attempt...")
                        await asyncio.sleep(wait_time)
                        
                        # Try to send a more aggressive reset request
                        try:
                            # Force close any existing sessions
                            await self.bot.delete_webhook(drop_pending_updates=True)
                            # Use a very large offset to force Telegram to reset the session
                            await self.bot.get_updates(offset=999999999, limit=1, timeout=1)
                            logger.info("Reset complete. Retrying from the beginning...")
                            
                            # Restart the application
                            if hasattr(self.application, 'updater') and self.application.updater.running:
                                await self.application.updater.stop()
                            await self.application.stop()
                            await self.application.shutdown()
                            
                            # Recreate the application
                            self.application = Application.builder().bot(self.bot).build()
                            self._register_handlers(self.application)
                            
                            # Restart initialization from the beginning
                            return await self.run()
                        except Exception as reset_err:
                            logger.error(f"Failed to reset: {reset_err}")
                    else:
                        logger.info("Skipping reset as one was performed recently. Waiting for retry...")
                    
                    # Continue with the main loop to retry later
                except Exception as poll_err:
                    # Log other polling errors
                    logger.error(f"Error starting polling: {type(poll_err).__name__} - {str(poll_err)}")
                    # Continue to heartbeat loop
            elif self.webhook_url:
                # In webhook mode, ensure webhook is properly set
                logger.info(f"Bot is set up for webhook mode at {self.webhook_url}{self.webhook_path}")
                # Clear any existing webhook
                await self.bot.delete_webhook(drop_pending_updates=True)
                # Wait a moment to ensure webhook is cleared
                await asyncio.sleep(1)
                # Set up the webhook
                await self.bot.set_webhook(
                    url=f"{self.webhook_url}{self.webhook_path}",
                    drop_pending_updates=True,
                    allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"]
                )
                logger.info("Webhook set successfully")
            else:
                # No webhook URL and not using polling - use a fake polling to keep bot responsive
                logger.info("No webhook URL provided and polling not forced. Using fallback polling mode.")
                # Delete any existing webhook
                await self.bot.delete_webhook(drop_pending_updates=True)
                
                # Start polling with drop_pending_updates to avoid old message conflicts
                if hasattr(self.application, 'updater'):
                    try:
                        await self.application.updater.start_polling(
                            poll_interval=1.0, 
                            timeout=30, 
                            drop_pending_updates=True,
                            allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"]
                        )
                        self.polling_started = True
                        logger.info("Bot started in fallback polling mode")
                    except telegram.error.Conflict as conflict_err:
                        logger.error(f"Conflict error in fallback mode: {conflict_err}")
                        # Skip polling in this case and continue with heartbeat
                    except Exception as poll_err:
                        logger.error(f"Error starting fallback polling: {str(poll_err)}")
            
            # At this point, we've either succeeded in setting up the bot or failed
            # Let's log our state clearly
            if self.polling_started:
                logger.info("✅ Bot is set up and polling has started successfully")
            elif self.webhook_url:
                logger.info("✅ Bot is set up in webhook mode")
            else:
                logger.warning("⚠️ Bot setup completed but neither polling nor webhook is active")
            
            # Keep the service running with a heartbeat
            max_retries = 10
            retry_count = 0
            retry_delay = 10  # Start with 10 seconds
            
            # Log heartbeat start
            logger.info("Starting heartbeat loop to maintain connection...")
            
            while True:
                try:
                    # Send a getMe request to keep the connection alive and verify bot is working
                    bot_info = await self.bot.get_me()
                    logger.info(f"Bot heartbeat successful: {bot_info.first_name} (@{bot_info.username})")
                    # Reset retry counters on success
                    retry_count = 0
                    retry_delay = 10
                    # Sleep for 30 minutes between heartbeats
                    await asyncio.sleep(1800)
                    
                except telegram.error.Conflict as conflict_err:
                    # Handle conflict specifically
                    logger.error(f"Conflict detected during heartbeat: {conflict_err}")
                    # Only perform recovery if we haven't done one recently
                    current_time = time.time()
                    if current_time - last_reset_time > 60:
                        logger.info("🚨 Detected conflict during heartbeat. Attempting recovery...")
                        last_reset_time = current_time
                        
                        # Wait for a random time to prevent collisions
                        wait_time = 5 + random.randint(1, 10)
                        await asyncio.sleep(wait_time)
                        
                        # Reset the bot's session
                        try:
                            # Reset webhook and pending updates
                            await self.bot.delete_webhook(drop_pending_updates=True)
                            # Reset the get_updates session
                            await self.bot.get_updates(offset=999999999, limit=1, timeout=1, allowed_updates=[])
                            logger.info("Session reset complete, continuing heartbeat...")
                        except Exception as reset_err:
                            logger.error(f"Reset failed: {reset_err}")
                    
                    # Wait a bit longer and continue
                    await asyncio.sleep(30)
                    continue
                
                except telegram.error.TimedOut as timeout_err:
                    # Handle timeout errors differently - these are common and can be ignored
                    logger.warning(f"Heartbeat timed out: {str(timeout_err)}")
                    # Use a shorter delay for timeouts as they're less severe
                    await asyncio.sleep(30)
                    continue
                    
                except Exception as e:
                    retry_count += 1
                    error_type = type(e).__name__
                    logger.error(f"Bot heartbeat failed (attempt {retry_count}/{max_retries}): {error_type} - {str(e)}")
                    
                    if retry_count >= max_retries:
                        logger.error("Maximum retries reached, restarting bot initialization")
                        # Try to restart the bot
                        try:
                            # Stop the application components
                            if hasattr(self, 'application') and self.application:
                                if hasattr(self.application, 'updater') and self.application.updater.running:
                                    await self.application.updater.stop()
                                await self.application.stop()
                                await self.application.shutdown()
                            
                            # Reinitialize the bot with a new application
                            self.application = Application.builder().bot(self.bot).build()
                            self._register_handlers(self.application)
                            
                            # Restart initialization from the beginning
                            retry_count = 0
                            return await self.run()
                        except Exception as restart_error:
                            logger.error(f"Failed to restart bot: {str(restart_error)}")
                            # If we couldn't restart, continue with the retry cycle
                    
                    # Wait with exponential backoff
                    logger.info(f"Attempt #{retry_count} failed in heartbeat. Continuing to retry for {retry_delay}s")
                    await asyncio.sleep(retry_delay)
                    # Increase retry delay with some randomness to avoid synchronized retries
                    retry_delay = min(300, retry_delay * 1.5)  # Cap at 5 minutes
        
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"Error in bot run loop: {error_type} - {str(e)}")
            raise

    # Calendar service helpers
    @property
    def calendar_service(self):
        """Lazy loaded calendar service"""
        if self._calendar_service is None:
            # Only initialize the calendar service when it's first accessed
            self.logger.info("Lazy loading calendar service")
            self._calendar_service = EconomicCalendarService()
        return self._calendar_service
        
    def _get_calendar_service(self):
        """Get the calendar service instance"""
        self.logger.info("Getting calendar service")
        return self.calendar_service

    async def _format_calendar_events(self, calendar_data):
        """Format the calendar data into a readable HTML message"""
        self.logger.info(f"Formatting calendar data with type {type(calendar_data)}")
        
        # Check for pre-formatted message from TradingView calendar service
        if isinstance(calendar_data, str) and "<b>📅 Economic Calendar</b>" in calendar_data:
            self.logger.info("Using pre-formatted message from TradingView calendar")
            return calendar_data
        
        # First check if we have a CalendarResult object and extract the events
        if hasattr(calendar_data, 'events'):
            # If it's a CalendarResult object, extract the events
            self.logger.info("Received CalendarResult object, extracting events")
            events = calendar_data.events
            
            # If there's a pre-formatted message, just return it
            if hasattr(calendar_data, 'message') and calendar_data.message:
                self.logger.info("Using pre-formatted message from CalendarResult")
                return calendar_data.message
        elif isinstance(calendar_data, dict) and 'events' in calendar_data:
            # If it's a dictionary with events key
            events = calendar_data.get('events', [])
            
            # If there's a pre-formatted message, just return it
            if 'message' in calendar_data and calendar_data['message']:
                self.logger.info("Using pre-formatted message from dictionary")
                return calendar_data['message']
        else:
            # Assume it's already a list of events
            events = calendar_data
        
        self.logger.info(f"Processing {len(events) if events else 0} events")
        
        # Debug log for the first 3 events
        if events and len(events) > 0:
            for i, event in enumerate(events[:3]):
                self.logger.info(f"Event {i+1}: {json.dumps(event)}")
        
        if not events:
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
                except Exception as e:
                    self.logger.error(f"Error parsing time for sorting: {str(e)} for time: {time_str}")
                    return 0
            
            # Sort the events by time
            sorted_events = sorted(events, key=parse_time_for_sorting)
            self.logger.info(f"Sorted {len(sorted_events)} events by time")
        except Exception as e:
            self.logger.error(f"Error sorting calendar events: {str(e)}")
            sorted_events = events
        
        # Format the message
        message = "<b>📅 Economic Calendar</b>\n\n"
        
        # Get current date
        current_date = datetime.now().strftime("%B %d, %Y")
        message += f"<b>Date:</b> {current_date}\n\n"
        
        # Add impact legend
        message += "<b>Impact:</b> 🔴 High   🟠 Medium   🟢 Low\n\n"
        
        # Check if events have "country" or "currency" field
        has_country = any('country' in event for event in sorted_events[:5])
        has_currency = any('currency' in event for event in sorted_events[:5])
        
        country_field = 'currency' if has_currency and not has_country else 'country'
        self.logger.info(f"Using '{country_field}' as country identifier")
        
        # Format all events in chronological order
        for event in sorted_events:
            # Get event details with fallbacks
            time = event.get('time', 'TBA')
            title = event.get('title', event.get('event', 'Unknown Event'))  # Support both title and event fields
            impact = event.get('impact', 'Low')
            impact_emoji = {'High': '🔴', 'Medium': '🟠', 'Low': '🟢'}.get(impact, '🟢')
            
            # Get country/currency flag and code
            country = event.get(country_field, 'Unknown')
            country_flag = CURRENCY_FLAG.get(country, '')
            
            # Format event line including the country/currency flag
            event_line = f"{time} - {impact_emoji} {title}"
            
            # Only add the country flag+code if available
            if country_flag:
                event_line = f"{time} - {country_flag} {country} - {impact_emoji} {title}"
            
            message += f"{event_line}\n"
        
        # Mark the formatted message
        message += "\n-------------------\n"
        message += "<i>Powered by SigmaPips AI</i>"
        
        self.logger.info(f"Finished formatting calendar with {len(sorted_events)} events into message of length {len(message)}")
        return message
        
    # Utility functions that might be missing
    async def update_message(self, query, text, keyboard=None, parse_mode=ParseMode.HTML):
        """Utility to update a message with error handling"""
        try:
            logger.info("Updating message")
            # Try to edit message text first
            await query.edit_message_text(
                text=text,
                reply_markup=keyboard,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            logger.warning(f"Could not update message text: {str(e)}")
            
            # If text update fails, try to edit caption
            try:
                await query.edit_message_caption(
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=parse_mode
                )
                return True
            except Exception as e2:
                logger.error(f"Could not update caption either: {str(e2)}")
                
                # As a last resort, send a new message
                try:
                    chat_id = query.message.chat_id
                    await query.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=keyboard,
                        parse_mode=parse_mode
                    )
                    return True
                except Exception as e3:
                    logger.error(f"Failed to send new message: {str(e3)}")
                    return False
    
    # Missing handler implementations
    async def back_signals_callback(self, update: Update, context=None) -> int:
        """Handle back_signals button press"""
        query = update.callback_query
        await query.answer()
        
        logger.info("back_signals_callback called")
        
        # Check if we're coming from a signal (signal analysis flow)
        from_signal = False
        if context and hasattr(context, 'user_data'):
            from_signal = context.user_data.get('from_signal', False)
        
        # If coming from a signal, redirect to signal page
        if from_signal:
            logger.info("Coming from signal flow, redirecting to back_to_signal_callback")
            return await self.back_to_signal_callback(update, context)
        
        # Otherwise, continue with normal signals flow
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
            
            logger.info(f"Updated context in back_signals_callback: {context.user_data}")
        
        # Create keyboard for signal menu
        keyboard = [
            [InlineKeyboardButton("📊 Add Signal", callback_data="signals_add")],
            [InlineKeyboardButton("⚙️ Manage Signals", callback_data="signals_manage")],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Get the signals GIF URL for better UX
        signals_gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
        
        # Update the message
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
        """Register all telegram command handlers"""
        try:
            # Register basic commands
            application.add_handler(CommandHandler("start", self.start_command))
            application.add_handler(CommandHandler("menu", self.menu_command))
            application.add_handler(CommandHandler("help", self.help_command))
            
            # Register specific signal handlers with highest priority
            # These need to be registered first to ensure they handle their patterns
            application.add_handler(CallbackQueryHandler(self.signal_technical_callback, pattern="^signal_technical$"))
            application.add_handler(CallbackQueryHandler(self.signal_sentiment_callback, pattern="^signal_sentiment$"))
            application.add_handler(CallbackQueryHandler(self.signal_calendar_callback, pattern="^signal_calendar$"))
            
            # Register main callback handlers - alleen de essentiële handlers
            application.add_handler(CallbackQueryHandler(self.menu_analyse_callback, pattern="^menu_analyse$"))
            application.add_handler(CallbackQueryHandler(self.menu_signals_callback, pattern="^menu_signals$"))
            application.add_handler(CallbackQueryHandler(self.analysis_technical_callback, pattern="^analysis_technical$"))
            application.add_handler(CallbackQueryHandler(self.analysis_sentiment_callback, pattern="^analysis_sentiment$"))
            application.add_handler(CallbackQueryHandler(self.analysis_calendar_callback, pattern="^analysis_calendar$"))
            
            # Market and instrument handlers
            application.add_handler(CallbackQueryHandler(self.market_callback, pattern="^market_"))
            application.add_handler(CallbackQueryHandler(self.instrument_callback, pattern="^instrument_"))
            
            # Back button handlers
            application.add_handler(CallbackQueryHandler(self.back_instrument_callback, pattern="^back_instrument$"))
            application.add_handler(CallbackQueryHandler(self.back_market_callback, pattern="^back_market$"))
            application.add_handler(CallbackQueryHandler(self.back_menu_callback, pattern="^back_menu$"))
            application.add_handler(CallbackQueryHandler(self.back_analysis_callback, pattern="^back_analysis$"))
            application.add_handler(CallbackQueryHandler(self.analysis_callback, pattern="^back_to_analysis$"))
            application.add_handler(CallbackQueryHandler(self.back_to_signal_analysis_callback, pattern="^back_to_signal_analysis$"))
            application.add_handler(CallbackQueryHandler(self.back_to_signal_callback, pattern="^back_to_signal$"))
            application.add_handler(CallbackQueryHandler(self.back_signals_callback, pattern="^back_signals$"))
            
            # Signal analysis handlers
            application.add_handler(CallbackQueryHandler(self.analyze_from_signal_callback, pattern="^analyze_from_signal_"))
            
            # Catch-all handler voor overige callback queries
            application.add_handler(CallbackQueryHandler(self.button_callback))
            
            logger.info("All handlers registered successfully")
        except Exception as e:
            logger.error(f"Error registering handlers: {str(e)}")
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
        
        # Handle backward compatibility for signal-specific calendar
        callback_data = query.data
        instrument = None
        if callback_data.startswith("analysis_calendar_signal_"):
            # Extract instrument from the callback data
            instrument = callback_data.replace("analysis_calendar_signal_", "")
            logger.info(f"Backward compatibility: Calendar analysis for instrument: {instrument}")
            if context and hasattr(context, 'user_data'):
                context.user_data['instrument'] = instrument
        
        # Set menu flow context flags properly
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'calendar'
            context.user_data['from_signal'] = False
            context.user_data['in_signal_flow'] = False
            
            logger.info(f"Menu calendar context set, instrument: {instrument}")
        
        # Set loading message
        loading_message = "Loading economic calendar..."
        
        try:
            # Show initial loading message
            await query.edit_message_text(text=loading_message)
            
            # Use the show_calendar_analysis method
            return await self.show_calendar_analysis(
                update=update,
                context=context,
                instrument=instrument
            )
            
        except Exception as e:
            logger.error(f"Error in analysis_calendar_callback: {str(e)}")
            try:
                # Error message with back button
                await query.edit_message_text(
                    text=f"Error loading economic calendar. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]])
                )
            except Exception:
                pass
            
            return CHOOSE_ANALYSIS

    async def show_economic_calendar(self, update: Update, context: CallbackContext, currency=None, loading_message=None):
        """Show the economic calendar for a specific currency or instrument"""
        try:
            # VERIFICATION MARKER: SIGMAPIPS_CALENDAR_FIX_APPLIED
            self.logger.info("VERIFICATION MARKER: SIGMAPIPS_CALENDAR_FIX_APPLIED")
            
            chat_id = update.effective_chat.id
            query = update.callback_query
            
            # Determine if we're in a signal flow
            is_from_signal = False
            instrument = None
            if context and hasattr(context, 'user_data'):
                is_from_signal = context.user_data.get('from_signal', False)
                # Set in_signal_flow flag to ensure proper return path
                if is_from_signal:
                    context.user_data['in_signal_flow'] = True
                    
                # Get instrument from context if currency not provided
                if not currency and 'instrument' in context.user_data:
                    instrument = context.user_data.get('instrument')
                    # Extract currency from instrument
                    if instrument and instrument in INSTRUMENT_CURRENCY_MAP:
                        currencies = INSTRUMENT_CURRENCY_MAP[instrument]
                        if currencies:
                            currency = currencies[0]
                            self.logger.info(f"Extracted currency {currency} from instrument {instrument}")
                
                # Check if we have a loading message from the context
                if not loading_message and 'loading_message' in context.user_data:
                    loading_message = context.user_data.get('loading_message')
                    self.logger.info(f"Found loading message in context: {loading_message.message_id if loading_message else 'None'}")
            
            # Log that we're showing the calendar
            self.logger.info(f"Showing economic calendar - currency: {currency}, instrument: {instrument}, is_from_signal: {is_from_signal}")
            
            # Initialize the calendar service
            calendar_service = self._get_calendar_service()
            
            # Create loading message if one doesn't exist
            if not loading_message and query:
                try:
                    loading_text = "Loading economic calendar data..."
                    loading_message = await query.edit_message_text(
                        text=loading_text,
                        parse_mode=ParseMode.HTML
                    )
                    self.logger.info("Created new loading message")
                except Exception as e:
                    self.logger.warning(f"Could not create loading message by editing: {str(e)}")
                    # Try to send a new message as fallback
                    try:
                        loading_message = await context.bot.send_message(
                            chat_id=chat_id,
                            text="Loading economic calendar data...",
                            parse_mode=ParseMode.HTML
                        )
                        self.logger.info("Created new loading message by sending new message")
                    except Exception as send_error:
                        self.logger.error(f"Could not send loading message: {str(send_error)}")
            
            # Get calendar data from the TradingView service directly
            try:
                if hasattr(calendar_service, 'tradingview_calendar'):
                    # Access the TradingView calendar service directly
                    tv_service = calendar_service.tradingview_calendar
                    self.logger.info("Using TradingView calendar service directly")
                    
                    # Get calendar events directly - if currency is specified, highlight that currency's events
                    events = await tv_service.get_calendar(days_ahead=1, min_impact="Low", currency=currency)
                    self.logger.info(f"Got {len(events)} events from TradingView service")
                    
                    # Use the TradingView formatting function
                    message = await tv_service.format_calendar_for_telegram(events)
                    self.logger.info("Formatted calendar using TradingView formatter")
                else:
                    # Fallback to standard calendar service
                    self.logger.info("Using standard calendar service")
                    calendar_result = await calendar_service.get_calendar(currency=currency)
                    
                    # Format the result
                    message = await self._format_calendar_events(calendar_result)
                    self.logger.info("Formatted calendar using standard formatter")
            except Exception as e:
                self.logger.error(f"Error getting calendar data: {str(e)}")
                self.logger.exception(e)
                
                # Try the generic calendar service as backup
                try:
                    calendar_result = await calendar_service.get_calendar(currency=currency)
                    message = await self._format_calendar_events(calendar_result)
                    self.logger.info("Used generic calendar service as backup")
                except Exception as e2:
                    self.logger.error(f"Backup calendar service also failed: {str(e2)}")
                    message = None
            
            # If we couldn't get a message, generate mock data
            if not message:
                self.logger.warning("Using mock calendar data as fallback")
                # Generate mock data
                today_date = datetime.now().strftime("%B %d, %Y")
                
                # Determine which currencies to include
                calendar_currencies = [currency] if currency else MAJOR_CURRENCIES
                if instrument and instrument in INSTRUMENT_CURRENCY_MAP:
                    calendar_currencies = INSTRUMENT_CURRENCY_MAP[instrument]
                
                # Use the mock data generator from the calendar service if available
                if hasattr(calendar_service, '_generate_mock_calendar_data'):
                    mock_data = calendar_service._generate_mock_calendar_data(calendar_currencies, today_date)
                else:
                    # Otherwise use our own implementation
                    mock_data = self._generate_mock_calendar_data(calendar_currencies, today_date)
                
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
                
                # Format the mock data
                message = await self._format_calendar_events(flattened_mock)
            
            # Create keyboard with back button based on flow context
            keyboard = None
            if is_from_signal:
                # When we're coming from a signal, the back button should go to signal analysis
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Signal", callback_data="back_to_signal_analysis")]])
                self.logger.info("Using back_to_signal_analysis button for signal flow")
            else:
                # Regular menu flow - go back to the analysis menu
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_analysis")]])
                self.logger.info("Using back_analysis button for menu flow")
            
            # If we have a query, try to edit message directly
            if query:
                try:
                    await query.edit_message_text(
                        text=message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard
                    )
                    self.logger.info("Successfully edited message with calendar data")
                    
                    # Clear any loading message from context if it exists
                    if context and hasattr(context, 'user_data') and 'loading_message' in context.user_data:
                        del context.user_data['loading_message']
                        
                    # Return appropriate state based on flow
                    return SIGNAL_ANALYSIS if is_from_signal else CHOOSE_ANALYSIS
                except Exception as edit_error:
                    self.logger.warning(f"Could not edit message: {str(edit_error)}")
                    # Fall through to send a new message
            
            # If we couldn't edit or have a loading message reference, try to delete and send new message
            sent_new_message = False
            if loading_message:
                try:
                    # Check if loading_message is a Message object
                    if hasattr(loading_message, 'message_id'):
                        # Try to delete the loading message
                        await context.bot.delete_message(chat_id=chat_id, message_id=loading_message.message_id)
                        self.logger.info(f"Successfully deleted loading message {loading_message.message_id}")
                    else:
                        self.logger.warning(f"Loading message doesn't have message_id attribute: {type(loading_message)}")
                except Exception as delete_error:
                    self.logger.warning(f"Could not delete loading message: {str(delete_error)}")
            
            # Send a new message if we couldn't edit
            if not sent_new_message:
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard
                    )
                    self.logger.info("Sent new message with calendar data")
                    sent_new_message = True
                except Exception as send_error:
                    self.logger.error(f"Could not send new message: {str(send_error)}")
            
            # Clear any loading message from context if it exists
            if context and hasattr(context, 'user_data') and 'loading_message' in context.user_data:
                del context.user_data['loading_message']
                
            # Return appropriate state
            return SIGNAL_ANALYSIS if is_from_signal else CHOOSE_ANALYSIS
            
        except Exception as e:
            self.logger.error(f"Error in show_economic_calendar: {str(e)}")
            self.logger.exception(e)
            
            # Try to send an error message
            try:
                if update.callback_query:
                    try:
                        await update.callback_query.edit_message_text(
                            text="Sorry, there was an error loading the economic calendar. Please try again.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]])
                        )
                    except Exception:
                        # If editing fails, send a new message
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text="Sorry, there was an error loading the economic calendar. Please try again.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]])
                        )
            except Exception:
                pass
                
            # Return to appropriate state
            if context and hasattr(context, 'user_data') and context.user_data.get('from_signal', False):
                return SIGNAL_ANALYSIS
            return CHOOSE_ANALYSIS

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
        
        # Check and maintain signal flow context
        is_from_signal = False
        if context and hasattr(context, 'user_data'):
            is_from_signal = context.user_data.get('from_signal', False)
            # Make sure we stay in the signal flow
            context.user_data['from_signal'] = True
            context.user_data['is_signals_context'] = False  # Not in signals context anymore
            context.user_data['analysis_type'] = 'technical'
        
        # Check if we're in the right flow
        if not is_from_signal:
            logger.warning("signal_technical_callback called outside signal flow context")
            # We want to be strict about this - if not from signal, send back to menu
            # This shouldn't happen but is an extra safeguard
            try:
                await query.edit_message_text(
                    text="Please start from a trading signal to use this feature.",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
            except Exception as e:
                logger.error(f"Error in signal_technical_callback redirect: {str(e)}")
            return MENU
        
        # Get the instrument from context
        instrument = None
        if context and hasattr(context, 'user_data'):
            instrument = context.user_data.get('instrument')
            logger.info(f"Signal technical callback - instrument: {instrument}, from signal: {is_from_signal}")
        
        if not instrument:
            # No instrument specified
            await query.edit_message_text(
                text="Please specify an instrument first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")]])
            )
            return SIGNAL_ANALYSIS
        
        # Get timeframe from context or use default
        timeframe = "1h"
        if context and hasattr(context, 'user_data') and 'signal_timeframe' in context.user_data:
            timeframe = context.user_data.get('signal_timeframe')
        
        logger.info(f"Getting technical analysis for {instrument} ({timeframe}) from signal")
        
        # Call the show_technical_analysis method
        if hasattr(self, 'show_technical_analysis'):
            # This will handle the technical analysis display
            return await self.show_technical_analysis(update, context, instrument, timeframe)
        else:
            # Fallback if method not available
            await query.edit_message_text(
                text=f"Technical analysis for {instrument} is being prepared...",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")]])
            )
            return SIGNAL_ANALYSIS

    async def signal_sentiment_callback(self, update: Update, context=None) -> int:
        """Handle signal_sentiment button press"""
        query = update.callback_query
        await query.answer()
        
        # Check and maintain signal flow context
        is_from_signal = False
        if context and hasattr(context, 'user_data'):
            is_from_signal = context.user_data.get('from_signal', False)
            # Make sure we stay in the signal flow
            context.user_data['from_signal'] = True
            context.user_data['is_signals_context'] = False  # Not in signals context anymore
            context.user_data['analysis_type'] = 'sentiment'
        
        # Check if we're in the right flow
        if not is_from_signal:
            logger.warning("signal_sentiment_callback called outside signal flow context")
            try:
                await query.edit_message_text(
                    text="Please start from a trading signal to use this feature.",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
            except Exception as e:
                logger.error(f"Error in signal_sentiment_callback redirect: {str(e)}")
            return MENU
        
        # Get the instrument from context
        instrument = None
        if context and hasattr(context, 'user_data'):
            instrument = context.user_data.get('instrument')
            logger.info(f"Signal sentiment callback - instrument: {instrument}, from signal: {is_from_signal}")
        
        if not instrument:
            # No instrument specified
            await query.edit_message_text(
                text="Please specify an instrument first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")]])
            )
            return SIGNAL_ANALYSIS
        
        # Get market from instrument
        market = _detect_market(instrument)
        
        # Show loading message
        loading_text = f"Loading sentiment analysis for {instrument}..."
        loading_gif = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"
        
        try:
            # Try to show animated loading GIF
            await query.edit_message_media(
                media=InputMediaAnimation(
                    media=loading_gif,
                    caption=loading_text
                )
            )
        except Exception as gif_error:
            logger.warning(f"Could not show loading GIF: {str(gif_error)}")
            # Fall back to text loading message
            try:
                await query.edit_message_text(text=loading_text)
            except Exception:
                pass
        
        # Create back button for this context
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")]]
        
        # Get sentiment analysis
        try:
            # Initialize chart service if needed
            if not hasattr(self, 'chart_service') or not self.chart_service:
                from trading_bot.services.chart_service.chart import ChartService
                self.chart_service = ChartService()
            
            # Get sentiment analysis
            sentiment_data = await self.chart_service.get_sentiment_analysis(instrument)
            
            if not sentiment_data:
                # Instead of edit_message_text, send a new message and delete the old one
                chat_id = update.effective_chat.id
                message_id = update.effective_message.message_id
                
                # Send a new message with the error
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"No sentiment data available for {instrument}.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                # Delete the original message with the loading GIF
                try:
                    await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
                except Exception as e:
                    logger.warning(f"Could not delete original message: {str(e)}")
                
                return SIGNAL_ANALYSIS
            
            # Format sentiment data into text
            sentiment_text = f"<b>Sentiment Analysis for {instrument}</b>\n\n"
            sentiment_text += sentiment_data
            
            # Using the same approach - send a new message with the results
            chat_id = update.effective_chat.id
            message_id = update.effective_message.message_id
            
            # Send the sentiment analysis as a new message
            await self.bot.send_message(
                chat_id=chat_id,
                text=sentiment_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            # Delete the original message with the loading GIF
            try:
                await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception as e:
                logger.warning(f"Could not delete original message: {str(e)}")
            
            return SIGNAL_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error getting sentiment analysis: {str(e)}")
            # Error message using same approach
            try:
                chat_id = update.effective_chat.id
                message_id = update.effective_message.message_id
                
                # Send error message
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"Error getting sentiment analysis for {instrument}. Please try again.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                # Delete the original message
                try:
                    await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
                except Exception as del_e:
                    logger.warning(f"Could not delete original message: {str(del_e)}")
            except Exception as msg_e:
                logger.error(f"Failed to send error message: {str(msg_e)}")
            
            return SIGNAL_ANALYSIS

    async def signal_calendar_callback(self, update: Update, context=None) -> int:
        """Handle signal_calendar button press for showing economic calendar in signal flow"""
        query = update.callback_query
        await query.answer()
        
        # Set the flow type explicitly to signal
        if context and hasattr(context, 'user_data'):
            context.user_data['flow_type'] = 'signal'
            logger.info("Set flow_type to 'signal' in signal_calendar_callback")
        
        # Enhanced logging for debugging
        logger.info(f"signal_calendar_callback called with data: {query.data}")
        
        # Get current signal information
        instrument = None
        signal_id = None
        signal_direction = None
        signal_timeframe = None
        
        # Set signal flow context flags properly
        if context and hasattr(context, 'user_data'):
            # First, store original signal information
            instrument = context.user_data.get('instrument')
            signal_id = context.user_data.get('signal_id')
            signal_direction = context.user_data.get('signal_direction')
            signal_timeframe = context.user_data.get('signal_timeframe')
            
            # Set signal flow flags
            context.user_data['from_signal'] = True
            context.user_data['in_signal_flow'] = True
            context.user_data['analysis_type'] = 'calendar'
            
            # Ensure we store backup copies of all signal data
            if instrument:
                context.user_data['signal_instrument_backup'] = instrument
            if signal_id:
                context.user_data['signal_id_backup'] = signal_id
            if signal_direction:
                context.user_data['signal_direction_backup'] = signal_direction
            if signal_timeframe:
                context.user_data['signal_timeframe_backup'] = signal_timeframe
            
            # Debug current context
            logger.info(f"Signal calendar context set: {context.user_data}")
            
        # Set loading message
        loading_message = "Loading economic calendar..."
        
        try:
            # Try to edit the message first
            try:
                await query.edit_message_text(text=loading_message)
                logger.info("Successfully edited message to show loading indicator")
            except Exception as edit_error:
                # If editing fails, send a new message
                logger.warning(f"Could not edit message: {str(edit_error)}")
                chat_id = update.effective_chat.id
                loading_sent = await context.bot.send_message(
                    chat_id=chat_id,
                    text=loading_message
                )
                # Store the loading message for later reference
                if context and hasattr(context, 'user_data'):
                    context.user_data['loading_message'] = loading_sent
                logger.info("Sent new loading message instead of editing")
            
            # No instrument required - use the show_calendar_analysis method
            # This is the exact same as used in the menu flow
            return await self.show_calendar_analysis(
                update=update,
                context=context
            )
            
        except Exception as e:
            logger.error(f"Error in signal_calendar_callback: {str(e)}")
            try:
                # Error message with back button - try editing first
                try:
                    await query.edit_message_text(
                        text=f"Error loading economic calendar. Please try again.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_SIGNAL_BACK_TO_SIGNAL_ANALYSIS)]])
                    )
                except Exception:
                    # If editing fails, send a new message
                    chat_id = update.effective_chat.id
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"Error loading economic calendar. Please try again.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_SIGNAL_BACK_TO_SIGNAL_ANALYSIS)]])
                    )
            except Exception as send_error:
                logger.error(f"Failed to send error message: {str(send_error)}")
        
        return SIGNAL_ANALYSIS

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

    async def signals_add_callback(self, update: Update, context=None) -> int:
        """Handle signals_add button press to add new signal subscriptions"""
        query = update.callback_query
        await query.answer()
        
        logger.info("signals_add_callback called")
        
        # Make sure we're in the signals flow context
        if context and hasattr(context, 'user_data'):
            context.user_data['is_signals_context'] = True
            context.user_data['from_signal'] = False
            
            # Set flag for adding signals
            context.user_data['adding_signals'] = True
            
            logger.info(f"Set signal flow context: {context.user_data}")
        
        # Create keyboard for market selection
        keyboard = MARKET_KEYBOARD_SIGNALS
        
        # Update message with market selection
        await self.update_message(
            query=query,
            text="Select a market for trading signals:",
            keyboard=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        
        return CHOOSE_MARKET
        
    async def signals_manage_callback(self, update: Update, context=None) -> int:
        """Handle signals_manage callback to manage signal preferences"""
        query = update.callback_query
        await query.answer()
        
        logger.info("signals_manage_callback called")
        
        try:
            # Get user's current subscriptions
            user_id = update.effective_user.id
            
            # Fetch user's signal subscriptions from the database
            try:
                response = self.db.supabase.table('signal_subscriptions').select('*').eq('user_id', user_id).execute()
                preferences = response.data if response and hasattr(response, 'data') else []
            except Exception as db_error:
                logger.error(f"Database error fetching signal subscriptions: {str(db_error)}")
                preferences = []
            
            if not preferences:
                # No subscriptions yet
                text = "You don't have any signal subscriptions yet. Add some first!"
                keyboard = [
                    [InlineKeyboardButton("➕ Add Signal Pairs", callback_data="signals_add")],
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
                ]
                
                await self.update_message(
                    query=query,
                    text=text,
                    keyboard=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
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
                [InlineKeyboardButton("➕ Add More", callback_data="signals_add")],
                [InlineKeyboardButton("🗑️ Remove All", callback_data="delete_all_signals")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
            ]
            
            # Add individual delete buttons if there are preferences
            if preferences:
                for i, pref in enumerate(preferences):
                    signal_id = pref.get('id')
                    if signal_id:
                        instrument = pref.get('instrument', 'unknown')
                        keyboard.insert(-1, [InlineKeyboardButton(f"❌ Delete {instrument}", callback_data=f"delete_signal_{signal_id}")])
            
            await self.update_message(
                query=query,
                text=message,
                keyboard=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            return CHOOSE_SIGNALS
            
        except Exception as e:
            logger.error(f"Error in signals_manage_callback: {str(e)}")
            
            # Error recovery - go back to signals menu
            keyboard = [
                [InlineKeyboardButton("📊 Add Signal", callback_data="signals_add")],
                [InlineKeyboardButton("⚙️ Manage Signals", callback_data="signals_manage")],
                [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self.update_message(
                query=query,
                text="<b>📈 Signal Management</b>\n\nManage your trading signals",
                keyboard=reply_markup,
                parse_mode=ParseMode.HTML
            )
            
            return CHOOSE_SIGNALS
        
    async def back_instrument_callback(self, update: Update, context=None) -> int:
        """Handle back_instrument button press"""
        try:
            query = update.callback_query
            if query:
                await query.answer()
                
            logger.info("Back to analysis menu")
            
            # Check if the current message has a photo or animation
            has_photo = bool(query.message.photo) or query.message.animation is not None
            
            # Create the text and keyboard for the analysis menu
            menu_text = "Select your analysis type:"
            keyboard = ANALYSIS_KEYBOARD
            
            # Get random gif for analysis menu if needed for a new message
            gif_url = random.choice(gif_utils.ANALYSIS_GIFS)
            
            if has_photo:
                try:
                    # Probeer foto/media te vervangen met transparante afbeelding en menu tekst
                    transparent_gif = "https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/Transparent.gif/1px-Transparent.gif"
                    
                    await query.edit_message_media(
                        media=InputMediaDocument(
                            media=transparent_gif,
                            caption=menu_text,
                            parse_mode=ParseMode.HTML
                        ),
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    logger.info("Successfully replaced media with transparent image")
                except Exception as media_error:
                    logger.warning(f"Could not edit media message: {str(media_error)}")
                    
                    # Als media bewerking mislukt, stuur een nieuw bericht
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=menu_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    
                    # Probeer het oorspronkelijke bericht te verwijderen
                    try:
                        await query.delete_message()
                        logger.info("Deleted original message after sending new message")
                    except Exception as delete_error:
                        logger.warning(f"Could not delete original message: {str(delete_error)}")
            else:
                # Voor tekstberichten gebruiken we de standaard bewerkingsmethode
                try:
                    await query.edit_message_text(
                        text=menu_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    logger.info("Successfully edited text message")
                except Exception as text_error:
                    logger.warning(f"Could not update message text: {str(text_error)}")
                    
                    # Probeer caption te bewerken als fallback
                    try:
                        await query.edit_message_caption(
                            caption=menu_text,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                        logger.info("Successfully edited caption")
                    except Exception as caption_error:
                        logger.warning(f"Could not update caption: {str(caption_error)}")
                        
                        # Stuur een nieuw bericht als laatste redmiddel
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=menu_text,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                        logger.info("Sent new message as fallback")
            
            return CHOOSE_ANALYSIS
                
        except Exception as e:
            logger.error(f"Failed to handle back_instrument_callback: {str(e)}")
            # Poging tot herstel door naar analyse selectie te gaan
            try:
                if update and update.effective_chat:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="Select your analysis type:",
                        reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                        parse_mode=ParseMode.HTML
                    )
                return CHOOSE_ANALYSIS
            except Exception:
                # Laatste redmiddel - update bericht met foutmelding
                if query:
                    await self.update_message(
                        query, 
                        "Sorry, an error occurred. Please use /menu to start again.", 
                        keyboard=None
                    )
                return ConversationHandler.END

    async def market_callback(self, update: Update, context=None) -> int:
        """Handle market selection callbacks (forex, crypto, etc.)"""
        query = update.callback_query
        await query.answer()
        
        logger.info(f"market_callback called with data: {query.data}")
        
        # Extract the market and flow context from the callback data
        data = query.data  # e.g. "market_forex", "market_crypto_signals", "market_forex_sentiment"
        parts = data.split("_")
        
        if len(parts) < 2:
            logger.error(f"Invalid market callback data: {data}")
            return MENU
            
        market = parts[1]  # forex, crypto, commodities, indices
        is_signals_context = "signals" in parts or (context and context.user_data.get('is_signals_context', False))
        is_sentiment_context = "sentiment" in parts
        is_calendar_context = "calendar" in parts
        
        # Set the market in user context
        if context and hasattr(context, 'user_data'):
            context.user_data['market'] = market
            context.user_data['is_signals_context'] = is_signals_context
            
            # Store flow-specific context flags
            context.user_data['is_sentiment_context'] = is_sentiment_context
            context.user_data['is_calendar_context'] = is_calendar_context
            
            logger.info(f"Set market context: {context.user_data}")
        
        # Determine which keyboard to use based on the context
        keyboard = None
        
        if is_signals_context:
            # Signals flow
            if market == MARKET_FOREX:
                keyboard = FOREX_KEYBOARD_SIGNALS
            elif market == MARKET_CRYPTO:
                keyboard = CRYPTO_KEYBOARD_SIGNALS
            elif market == MARKET_COMMODITIES:
                keyboard = COMMODITIES_KEYBOARD_SIGNALS
            elif market == MARKET_INDICES:
                keyboard = INDICES_KEYBOARD_SIGNALS
        elif is_sentiment_context:
            # Sentiment analysis flow
            if market == MARKET_FOREX:
                keyboard = FOREX_SENTIMENT_KEYBOARD
            elif market == MARKET_CRYPTO:
                keyboard = CRYPTO_SENTIMENT_KEYBOARD
            elif market == MARKET_COMMODITIES:
                keyboard = COMMODITIES_SENTIMENT_KEYBOARD
            elif market == MARKET_INDICES:
                keyboard = INDICES_SENTIMENT_KEYBOARD
        elif is_calendar_context:
            # Calendar analysis flow
            if market == MARKET_FOREX:
                keyboard = FOREX_CALENDAR_KEYBOARD
            # For other markets, there might not be specific calendar keyboards
            # so we'll fall back to the standard ones
        else:
            # Regular technical analysis flow
            if market == MARKET_FOREX:
                keyboard = FOREX_KEYBOARD
            elif market == MARKET_CRYPTO:
                keyboard = CRYPTO_KEYBOARD
            elif market == MARKET_COMMODITIES:
                keyboard = COMMODITIES_KEYBOARD
            elif market == MARKET_INDICES:
                keyboard = INDICES_KEYBOARD
        
        if not keyboard:
            logger.error(f"No keyboard found for market: {market} in context: signals={is_signals_context}, sentiment={is_sentiment_context}")
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]]
        
        # Show instrument selection
        message_text = f"Select an instrument from {market.capitalize()}:"
        
        await self.update_message(
            query=query,
            text=message_text,
            keyboard=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        
        return CHOOSE_INSTRUMENT

    async def instrument_callback(self, update: Update, context=None) -> int:
        """Handle instrument selection callbacks (EURUSD, BTCUSD, etc.)"""
        query = update.callback_query
        await query.answer()
        
        logger.info(f"instrument_callback called with data: {query.data}")
        
        # Extract the instrument and flow context from the callback data
        data = query.data  # e.g. "instrument_EURUSD_chart", "instrument_BTCUSD_signals"
        parts = data.split("_")
        
        if len(parts) < 2:
            logger.error(f"Invalid instrument callback data: {data}")
            return MENU
            
        instrument = parts[1]  # EURUSD, BTCUSD, etc.
        
        # Determine the context based on callback data
        is_signals_context = "signals" in parts or (context and context.user_data.get('is_signals_context', False))
        is_chart_context = "chart" in parts
        is_sentiment_context = "sentiment" in parts
        is_calendar_context = "calendar" in parts
        
        # Set the instrument in user context
        if context and hasattr(context, 'user_data'):
            context.user_data['instrument'] = instrument
            
            # Store flow-specific context flags
            context.user_data['is_signals_context'] = is_signals_context
            context.user_data['is_chart_context'] = is_chart_context
            context.user_data['is_sentiment_context'] = is_sentiment_context
            context.user_data['is_calendar_context'] = is_calendar_context
            
            logger.info(f"Set instrument context: {context.user_data}")
        
        # Handle different flows based on context
        if is_signals_context:
            # If in signals flow, show timeframe/style selection
            message_text = f"Select trading style for {instrument}:"
            keyboard = STYLE_KEYBOARD
            
            await self.update_message(
                query=query,
                text=message_text,
                keyboard=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return CHOOSE_STYLE
            
        elif is_sentiment_context:
            # For sentiment analysis, proceed directly to showing sentiment
            try:
                # Show loading message
                loading_text = f"Loading sentiment analysis for {instrument}..."
                loading_gif = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"
                
                try:
                    # Try to show animated loading GIF
                    await query.edit_message_media(
                        media=InputMediaAnimation(
                            media=loading_gif,
                            caption=loading_text
                        )
                    )
                except Exception as gif_error:
                    logger.warning(f"Could not show loading GIF: {str(gif_error)}")
                    # Fall back to text loading message
                    try:
                        await query.edit_message_text(text=loading_text)
                    except Exception:
                        pass
                
                # Initialize chart service if needed
                if not hasattr(self, 'chart_service') or not self.chart_service:
                    from trading_bot.services.chart_service.chart import ChartService
                    self.chart_service = ChartService()
                
                # Get sentiment analysis
                sentiment_data = await self.chart_service.get_sentiment_analysis(instrument)
                
                # Prepare back button based on context
                back_button = "back_market"
                if context and hasattr(context, 'user_data'):
                    market = context.user_data.get('market', 'forex')
                    back_button = f"back_market_{market}"
                
                keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data=back_button)]]
                
                if not sentiment_data:
                    await query.edit_message_text(
                        text=f"No sentiment data available for {instrument}.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    return CHOOSE_INSTRUMENT
                
                # Format sentiment data into text
                sentiment_text = f"<b>Sentiment Analysis for {instrument}</b>\n\n"
                sentiment_text += sentiment_data
                
                await query.edit_message_text(
                    text=sentiment_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                return CHOOSE_INSTRUMENT
                
            except Exception as e:
                logger.error(f"Error getting sentiment analysis: {str(e)}")
                # Error message
                keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_market")]]
                await query.edit_message_text(
                    text=f"Error getting sentiment analysis for {instrument}. Please try again.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                return CHOOSE_INSTRUMENT
                
        elif is_calendar_context:
            # For calendar analysis, show economic calendar for the instrument
            try:
                # Extract currencies from the instrument
                currencies = []
                if instrument in INSTRUMENT_CURRENCY_MAP:
                    currencies = INSTRUMENT_CURRENCY_MAP[instrument]
                
                # Show loading message
                loading_text = f"Loading economic calendar for {instrument}..."
                
                # Show loading message - method handles proper error cases
                if hasattr(self, 'show_economic_calendar'):
                    return await self.show_economic_calendar(
                        update, 
                        context, 
                        currency=currencies[0] if currencies else None,
                        loading_message=loading_text
                    )
                else:
                    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_market")]]
                    await query.edit_message_text(
                        text=f"Economic calendar for {instrument} is not available.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    return CHOOSE_INSTRUMENT
                    
            except Exception as e:
                logger.error(f"Error showing economic calendar: {str(e)}")
                keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_market")]]
                await query.edit_message_text(
                    text=f"Error getting economic calendar for {instrument}. Please try again.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                return CHOOSE_INSTRUMENT
                
        else:
            # Default to technical analysis - show timeframe selection or proceed directly
            message_text = f"Select timeframe for {instrument} technical analysis:"
            
            # If we're in a regular chart context, show timeframes
            timeframe_keyboard = [
                [InlineKeyboardButton("1m", callback_data=f"timeframe_{instrument}_1m")],
                [InlineKeyboardButton("15m", callback_data=f"timeframe_{instrument}_15m")],
                [InlineKeyboardButton("1h", callback_data=f"timeframe_{instrument}_1h")],
                [InlineKeyboardButton("4h", callback_data=f"timeframe_{instrument}_4h")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
            ]
            
            await self.update_message(
                query=query,
                text=message_text,
                keyboard=InlineKeyboardMarkup(timeframe_keyboard),
                parse_mode=ParseMode.HTML
            )
            return CHOOSE_TIMEFRAME

    async def initialize_services(self):
        """Initialize required services"""
        try:
            # Initialize chart service
            await self.chart_service.initialize()
            logger.info("Chart service initialized")
        except Exception as e:
            logger.error(f"Error initializing services: {str(e)}")
            raise

    async def initialize(self):
        """Initialize the application and start the bot"""
        try:
            # Set up commands for the bot
            commands = [
                BotCommand("start", "Start the bot and show welcome message"),
                BotCommand("menu", "Show the main menu"),
                BotCommand("help", "Show help information"),
            ]
            
            # Set the commands
            await self.bot.set_my_commands(commands)
            
            # Initialize services that require asyncio
            await self.initialize_services()
            
            # Reset webhook to avoid conflicts with multiple bot instances
            if self.webhook_url:
                logger.info(f"Setting webhook to: {self.webhook_url}{self.webhook_path}")
                # Delete existing webhook and drop pending updates to avoid conflicts
                await self.bot.delete_webhook(drop_pending_updates=True)
                # Wait to ensure webhook is fully removed
                await asyncio.sleep(1)
                # Set the new webhook
                await self.bot.set_webhook(
                    url=f"{self.webhook_url}{self.webhook_path}", 
                    drop_pending_updates=True
                )
                logger.info("Webhook successfully set")
            else:
                logger.info("Starting bot in polling mode")
                # Delete webhook if polling is being used
                await self.bot.delete_webhook(drop_pending_updates=True)
                
            self.bot_started = True
            logger.info("Bot successfully initialized and started")
            
        except Exception as e:
            logger.error(f"Error initializing bot: {str(e)}")
            raise

    async def back_to_signal_analysis_callback(self, update: Update, context=None) -> int:
        """Handle back_to_signal_analysis button press to return to signal analysis menu"""
        try:
            query = update.callback_query
            await query.answer()
            
            logger.info("back_to_signal_analysis_callback called")
            
            # Get the instrument from context
            instrument = None
            signal_id = None
            signal_direction = None
            signal_timeframe = None
            
            if context and hasattr(context, 'user_data'):
                # Ensure the from_signal flag stays set to maintain correct flow
                context.user_data['from_signal'] = True
                
                # Get all relevant signal data
                instrument = context.user_data.get('instrument')
                signal_id = context.user_data.get('signal_id')
                signal_direction = context.user_data.get('signal_direction')
                signal_timeframe = context.user_data.get('signal_timeframe')
                
                logger.info(f"Signal flow maintained for: {instrument}, from_signal={context.user_data.get('from_signal', False)}")
            
            # Create the signal analysis menu - vertical layout with 3 options
            keyboard = [
                [InlineKeyboardButton("📊 Technical Analysis", callback_data="signal_technical")],
                [InlineKeyboardButton("🔍 Market Sentiment", callback_data="signal_sentiment")],
                [InlineKeyboardButton("📅 Economic Calendar", callback_data="signal_calendar")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal")]
            ]
            
            message_text = f"<b>Signal Analysis for {instrument or 'Unknown Instrument'}</b>\n\nChoose analysis type:"
            
            # Controleer of het bericht een foto/media bevat
            has_photo = bool(query.message.photo) or query.message.animation is not None
            
            if has_photo:
                try:
                    # Als het een foto/media bevat, gebruik edit_message_media om terug te gaan
                    # Stuur een transparante afbeelding om de foto te vervangen door tekst
                    transparent_gif = "https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/Transparent.gif/1px-Transparent.gif"
                    
                    await query.edit_message_media(
                        media=InputMediaDocument(
                            media=transparent_gif,
                            caption=message_text,
                            parse_mode=ParseMode.HTML
                        ),
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as media_error:
                    logger.warning(f"Could not edit media message: {str(media_error)}")
                    
                    # Als media bewerken mislukt, probeer een nieuw bericht te sturen
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=message_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    
                    # Probeer het oorspronkelijke bericht te verwijderen
                    try:
                        await query.delete_message()
                    except Exception as delete_error:
                        logger.warning(f"Could not delete original message: {str(delete_error)}")
            else:
                # Als het een tekstbericht is, gebruik de standaard edit_message_text
                try:
                    await query.edit_message_text(
                        text=message_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as text_error:
                    logger.warning(f"Could not edit text message: {str(text_error)}")
                    
                    # Als tekstbericht bewerken mislukt, probeer caption te bewerken
                    try:
                        await query.edit_message_caption(
                            caption=message_text,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as caption_error:
                        logger.warning(f"Could not edit caption: {str(caption_error)}")
                        
                        # Als alles mislukt, stuur een nieuw bericht
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=message_text,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
            
            return SIGNAL_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error in back_to_signal_analysis_callback: {str(e)}")
            
            # Error recovery - try to get back to menu
            try:
                # Stuur een nieuw bericht als fallback
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="An error occurred. Please use the main menu to continue.",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
                
            return MENU

    async def show_technical_analysis(self, update: Update, context=None, instrument=None, timeframe=None) -> int:
        """Show technical analysis for an instrument"""
        try:
            query = update.callback_query
            from_signal = False
            
            # Check if we're in signal flow
            if context and hasattr(context, 'user_data') and context.user_data.get('from_signal'):
                from_signal = True
                logger.info("In signal flow, from_signal=True")
            
            # Get the current user data
            context_user_data = context.user_data if context and hasattr(context, 'user_data') else {}
            
            # Extract instrument and timeframe from callback data if not provided
            if not instrument:
                callback_data = query.data
                logger.info(f"Processing callback: {callback_data}")
                
                if callback_data.startswith("instrument_chart_"):
                    # Format: instrument_chart_BTCUSD_1h
                    parts = callback_data.split("_")
                    if len(parts) >= 3:
                        instrument = parts[2]
                        # Handle timeframe if provided in callback
                        if len(parts) >= 4:
                            timeframe = parts[3]
            
            # If still no instrument, check user data
            if not instrument and context and hasattr(context, 'user_data'):
                instrument = context_user_data.get('instrument')
                if not timeframe:
                    timeframe = context_user_data.get('timeframe')
            
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
            
            # Store the current information in context
            if context and hasattr(context, 'user_data'):
                context.user_data['instrument'] = instrument
                context.user_data['timeframe'] = timeframe
            
            # Log what we're doing
            logger.info(f"Getting technical analysis chart for {instrument} on {timeframe} timeframe")
            
            # Show loading message - efficiently start getting the chart and analysis in parallel
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
            except Exception as gif_error:
                logger.warning(f"Could not show loading GIF: {str(gif_error)}")
                # Fallback to text loading message
                try:
                    await query.edit_message_text(text=loading_text)
                except Exception:
                    pass
            
            # Start chart service initialization if needed
            if not hasattr(self, 'chart_service') or not self.chart_service:
                from trading_bot.services.chart_service.chart import ChartService
                self.chart_service = ChartService()
            
            # Start both requests in parallel
            chart_task = asyncio.create_task(self.chart_service.get_chart(instrument, timeframe))
            analysis_task = asyncio.create_task(self.chart_service.get_technical_analysis(instrument, timeframe))
            
            # Wait for both tasks to complete
            chart_image, analysis_text = await asyncio.gather(chart_task, analysis_task)
            
            # Clean up the analysis text
            if analysis_text:
                analysis_text = analysis_text.replace("  \n", "\n").strip()
            else:
                analysis_text = f"Technical analysis for {instrument} ({timeframe})"
            
            # Create the keyboard with appropriate back button based on flow
            keyboard = []
            
            # Add the appropriate back button based on whether we're in signal flow or menu flow
            if from_signal:
                keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")])
            else:
                # Make sure this matches exactly with the registered pattern in _register_handlers
                keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_instrument")])
            
            # Check if chart_image is valid
            if not chart_image:
                # Fallback to error message
                error_text = f"Failed to generate chart for {instrument}. Please try again later."
                await query.edit_message_text(
                    text=error_text,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
                return MENU
            
            # Handle local file paths by opening and sending the file directly
            if isinstance(chart_image, str) and os.path.exists(chart_image):
                logger.info(f"Chart data is a local file path: {chart_image}")
                try:
                    # Open the file and send it as a photo
                    with open(chart_image, 'rb') as file:
                        photo_file = file.read()
                        
                        # Truncate the analysis text to fit within Telegram's caption limit
                        if analysis_text and len(analysis_text) > 1000:
                            truncated_caption = analysis_text[:997] + "..."
                            logger.info(f"Truncated caption for local file from {len(analysis_text)} to {len(truncated_caption)} characters")
                        else:
                            truncated_caption = analysis_text
                        
                        # Update message with photo file
                        await query.edit_message_media(
                            media=InputMediaPhoto(
                                media=photo_file,
                                caption=truncated_caption,
                                parse_mode=ParseMode.HTML
                            ),
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        logger.info(f"Successfully sent chart file and analysis for {instrument}")
                        
                        # If the analysis text was truncated, send the full analysis as a separate message
                        if analysis_text and len(analysis_text) > 1000 and not from_signal:
                            # Split the text into chunks of 4000 characters (Telegram message limit)
                            chunks = [analysis_text[i:i+4000] for i in range(0, len(analysis_text), 4000)]
                            
                            # Send each chunk as a separate message
                            for chunk in chunks:
                                await context.bot.send_message(
                                    chat_id=update.effective_chat.id,
                                    text=chunk,
                                    parse_mode=ParseMode.HTML
                                )
                except Exception as file_error:
                    logger.error(f"Error sending local file: {str(file_error)}")
                    # Try to send as a new message
                    try:
                        with open(chart_image, 'rb') as file:
                            # Truncate caption to Telegram's limit if needed
                            if analysis_text and len(analysis_text) > 1000:
                                truncated_caption = analysis_text[:997] + "..."
                            else:
                                truncated_caption = analysis_text
                                
                            await query.message.reply_photo(
                                photo=file,
                                caption=truncated_caption,
                                parse_mode=ParseMode.HTML,
                                reply_markup=InlineKeyboardMarkup(keyboard)
                            )
                            
                            # Send full analysis as separate message if truncated
                            if analysis_text and len(analysis_text) > 1000 and not from_signal:
                                chunks = [analysis_text[i:i+4000] for i in range(0, len(analysis_text), 4000)]
                                for chunk in chunks:
                                    await context.bot.send_message(
                                        chat_id=update.effective_chat.id,
                                        text=chunk,
                                        parse_mode=ParseMode.HTML
                                    )
                    except Exception as fallback_error:
                        logger.error(f"Failed to send local file as fallback: {str(fallback_error)}")
                        await query.message.reply_text(
                            text=f"Error sending chart. Analysis: {analysis_text[:1000] if analysis_text else 'Not available'}",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                return SHOW_RESULT
            
            # Show the chart - directly delete and send new message which is faster than editing
            try:
                # Truncate the analysis text to fit within Telegram's caption limit (1024 characters)
                if analysis_text and len(analysis_text) > 1000:
                    # Truncate and add indicator that text was cut
                    truncated_analysis = analysis_text[:997] + "..."
                    logger.info(f"Truncated analysis text from {len(analysis_text)} to {len(truncated_analysis)} characters")
                else:
                    truncated_analysis = analysis_text
                
                # Probeer het originele bericht te bewerken in plaats van te verwijderen en een nieuw bericht te versturen
                try:
                    await query.edit_message_media(
                        media=InputMediaPhoto(
                            media=chart_image,
                            caption=truncated_analysis,
                            parse_mode=ParseMode.HTML
                        ),
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    logger.info(f"Successfully edited message with chart for {instrument}")
                except Exception as edit_error:
                    logger.warning(f"Could not edit message media: {str(edit_error)}")
                    
                    # Als bewerken niet lukt, dan versturen we een nieuw bericht
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=chart_image,
                        caption=truncated_analysis,
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    
                    # Alleen verwijderen als het nieuwe bericht succesvol is verstuurd
                    await query.delete_message()
                
                # If the analysis text was truncated, send the full analysis as a separate message
                if analysis_text and len(analysis_text) > 1000 and not from_signal:
                    # Split the text into chunks of 4000 characters (Telegram message limit)
                    chunks = [analysis_text[i:i+4000] for i in range(0, len(analysis_text), 4000)]
                    
                    # Send each chunk as a separate message
                    for chunk in chunks:
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=chunk,
                            parse_mode=ParseMode.HTML
                        )
                
                return SHOW_RESULT
                
            except Exception as e:
                logger.error(f"Failed to send chart: {str(e)}")
                
                # Simple fallback error handling
                try:
                    await query.edit_message_text(
                        text=f"Error sending chart for {instrument}. Please try again later.",
                        reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                    )
                except Exception:
                    pass
                
                return MENU
                
        except Exception as e:
            logger.error(f"Error in show_technical_analysis: {str(e)}")
            
            # Try to recover
            try:
                if update and update.callback_query:
                    await update.callback_query.edit_message_text(
                        text="Sorry, an error occurred. Please try again.",
                        reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                    )
            except Exception:
                pass
                
            return MENU

    async def button_callback(self, update: Update, context=None) -> int:
        """Handle button callbacks for the main app flow"""
        query = update.callback_query
        data = query.data
        
        self.logger.info(f"Button callback opgeroepen met data: {data}")
        
        # Always acknowledge the callback to prevent timeouts
        try:
            await query.answer()
        except Exception as e:
            self.logger.error(f"Error answering callback query: {str(e)}")
        
        try:
            # Main menu buttons
            if data == "menu_analyse":
                return await self.menu_analyse_callback(update, context)
            elif data == "menu_signals":
                return await self.menu_signals_callback(update, context)
            
            # Analysis submenu buttons
            elif data == CALLBACK_ANALYSIS_TECHNICAL:
                return await self.analysis_technical_callback(update, context)
            elif data == CALLBACK_ANALYSIS_SENTIMENT:
                return await self.analysis_sentiment_callback(update, context)
            elif data == CALLBACK_ANALYSIS_CALENDAR:
                return await self.analysis_calendar_callback(update, context)
                
            # Signal analysis buttons
            elif data == "signal_technical":
                return await self.signal_technical_callback(update, context)
            elif data == "signal_sentiment":
                return await self.signal_sentiment_callback(update, context)
            elif data == "signal_calendar":
                return await self.signal_calendar_callback(update, context)
                
            # Back buttons
            elif data == CALLBACK_BACK_MENU:
                return await self.back_menu_callback(update, context)
            elif data == CALLBACK_BACK_ANALYSIS:
                return await self.back_analysis_callback(update, context)
            elif data == CALLBACK_BACK_SIGNALS:
                return await self.back_signals_callback(update, context)
            elif data == CALLBACK_BACK_MARKET:
                return await self.back_market_callback(update, context)
            elif data == CALLBACK_BACK_INSTRUMENT:
                return await self.back_instrument_callback(update, context)
            elif data == "back_to_signal":
                return await self.back_to_signal_callback(update, context)
            elif data == "back_to_signal_analysis":
                return await self.back_to_signal_analysis_callback(update, context)
                
            # Signal management buttons
            elif data == CALLBACK_SIGNALS_ADD:
                return await self.signals_add_callback(update, context)
            elif data == CALLBACK_SIGNALS_MANAGE:
                return await self.signals_manage_callback(update, context)
                
            # Market selection buttons
            elif data.startswith("market_"):
                return await self.market_callback(update, context)
                
            # Instrument selection buttons
            elif data.startswith("instrument_"):
                return await self.instrument_callback(update, context)
            elif data.startswith("instrument_signals_"):
                return await self.instrument_signals_callback(update, context)
                
            # Analysis buttons
            elif data.startswith("analysis_"):
                return await self.analysis_callback(update, context)
                
            # Signal analysis flow
            elif data.startswith("analyze_from_signal_"):
                return await self.analyze_from_signal_callback(update, context)
            
            else:
                self.logger.warning(f"Unhandled callback_data: {data}")
                return MENU
                
        except Exception as e:
            self.logger.error(f"Error handling button callback: {str(e)}")
            self.logger.exception(e)
            
            # Keep users from getting stuck
            try:
                # Try to return to menu on error
                await query.edit_message_text(
                    text="An error occurred. Please try again.",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
            except Exception as edit_error:
                self.logger.error(f"Error sending error message: {str(edit_error)}")
            
            return MENU

    async def back_to_signal_callback(self, update: Update, context=None) -> int:
        """Handle the back to signal callback to return to signals menu"""
        # Implementation...
        
    async def back_signals_callback(self, update: Update, context=None) -> int:
        """Handle the back to signals menu callback"""
        # Implementation...
        
    async def back_market_callback(self, update: Update, context=None) -> int:
        """Handle the back to market selection callback"""
        query = update.callback_query
        await query.answer()
        
        logger.info("back_market_callback called")
        
        # Determine if we're in signals context based on user data
        is_signals_context = False
        if context and hasattr(context, 'user_data'):
            is_signals_context = context.user_data.get('is_signals_context', False)
            is_sentiment_context = context.user_data.get('is_sentiment_context', False)
            is_calendar_context = context.user_data.get('is_calendar_context', False)
        
        # Decide which keyboard to show based on the context
        keyboard = None
        message_text = "Select market:"
        
        # Choose the appropriate keyboard based on context
        if is_signals_context:
            keyboard = MARKET_KEYBOARD_SIGNALS
            message_text = "Select market for signals:"
        elif is_sentiment_context:
            keyboard = MARKET_KEYBOARD_SENTIMENT
            message_text = "Select market for sentiment analysis:"
        elif is_calendar_context:
            keyboard = MARKET_KEYBOARD_CALENDAR
            message_text = "Select market for economic calendar:"
        else:
            # Default to standard analysis keyboard
            keyboard = MARKET_KEYBOARD
            message_text = "Select market for analysis:"
        
        # Update the message with the market selection keyboard
        await self.update_message(
            query=query,
            text=message_text,
            keyboard=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        
        return CHOOSE_MARKET
    
    async def back_analysis_callback(self, update: Update, context=None) -> int:
        """Handle the back to analysis selection callback"""
        query = update.callback_query
        await query.answer()
        
        logger.info("back_analysis_callback called")
        
        # Show analysis selection keyboard
        message_text = "Select analysis type:"
        
        await self.update_message(
            query=query,
            text=message_text,
            keyboard=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
            parse_mode=ParseMode.HTML
        )
        
        return CHOOSE_ANALYSIS
    
    async def analysis_callback(self, update: Update, context=None) -> int:
        """Handle the back to analysis callback"""
        query = update.callback_query
        await query.answer()
        
        logger.info("analysis_callback called")
        
        # This is similar to back_analysis_callback, but might be used in different contexts
        message_text = "Select analysis type:"
        
        await self.update_message(
            query=query,
            text=message_text,
            keyboard=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
            parse_mode=ParseMode.HTML
        )
        
        return CHOOSE_ANALYSIS
    
    async def analyze_from_signal_callback(self, update: Update, context=None) -> int:
        """Handle callback for analyzing from a signal"""
        query = update.callback_query
        await query.answer()
        
        logger.info(f"analyze_from_signal_callback called with data: {query.data}")
        
        # Extract the instrument and possibly timeframe from the callback data
        # Expected format: analyze_from_signal_EURUSD_1h
        callback_data = query.data
        parts = callback_data.split("_")
        
        if len(parts) < 4:
            logger.error(f"Invalid analyze_from_signal callback data: {callback_data}")
            return MENU
        
        instrument = parts[3]  # e.g., EURUSD
        timeframe = parts[4] if len(parts) > 4 else "1h"  # Default to 1h if not specified
        
        # Store instrument and timeframe in context
        if context and hasattr(context, 'user_data'):
            context.user_data['instrument'] = instrument
            context.user_data['timeframe'] = timeframe
            
            # We're going into technical analysis from a signal
            context.user_data['is_signals_context'] = False
            context.user_data['is_sentiment_context'] = False
            context.user_data['is_calendar_context'] = False
            
            logger.info(f"Set analysis context for signal: {context.user_data}")
        
        # Show technical analysis for the instrument
        return await self.show_technical_analysis(update, context, instrument=instrument, timeframe=timeframe)
        
    async def get_subscribers_for_instrument(self, instrument: str, timeframe: str = None) -> List[int]:
        """Get all subscribers for a given instrument and timeframe"""
        # Implementation...
