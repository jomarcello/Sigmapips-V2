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
import uuid

def get_logger(name: str) -> logging.Logger:
    """Create and return a logger instance with the given name."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

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
    CHOOSE_ANALYSIS, SIGNAL_DETAILS,
    CALLBACK_MENU_ANALYSE, CALLBACK_MENU_SIGNALS, CALLBACK_ANALYSIS_TECHNICAL,
    CALLBACK_ANALYSIS_SENTIMENT, CALLBACK_ANALYSIS_CALENDAR, CALLBACK_SIGNALS_ADD,
    CALLBACK_SIGNALS_MANAGE, CALLBACK_BACK_MENU
)
import trading_bot.services.telegram_service.gif_utils as gif_utils

# Initialize logger
logger = get_logger(__name__)

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
        """Format the calendar data in chronological order - COMPLETE MANUAL IMPLEMENTATION"""
        try:
            # Check if calendar_data is a CalendarResult object
            if hasattr(calendar_data, 'get'):
                # If calendar_data is a CalendarResult object, get the message
                if calendar_data.get('message'):
                    return calendar_data.get('message')
                # If there is an error, return an error message
                if calendar_data.get('error'):
                    return f"<b>📅 Economic Calendar</b>\n\nError: {calendar_data.get('message', 'Unknown error')}"
                # Get events as array
                events = calendar_data.get('events', [])
            else:
                # Fallback for the case calendar_data is a list (as previously expected)
                events = calendar_data or []
            
            # Get the current date in different formats
            today = datetime.now()
            today_formatted = today.strftime("%B %d, %Y")
            
            # Build the message header with HTML formatting for the emoji
            message = "<b>📅 Economic Calendar</b>\n\n"
            message += f"Date: {today_formatted}\n\n"
            message += "Impact: 🔴 High   🟠 Medium   🟢 Low\n\n"
            
            # Empty result if there is no data
            if not events or len(events) == 0:
                return message + "No economic events scheduled for today."
            
            # Currency code mapping (country to currency code)
            COUNTRY_TO_CURRENCY = {
                'UNITED STATES': 'USD',
                'EURO ZONE': 'EUR',
                'UNITED KINGDOM': 'GBP',
                'JAPAN': 'JPY',
                'SWITZERLAND': 'CHF',
                'CANADA': 'CAD',
                'AUSTRALIA': 'AUD',
                'NEW ZEALAND': 'NZD'
            }
            
            # Configuration for filtering on current month/day
            current_month = today.strftime("%b").lower()
            months_abbr = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
            months_full = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
            current_day = today.strftime("%d").lstrip("0")  # day without leading zeros
            
            # Filter events based on date references
            filtered_events = []
            for event in events:
                # Basic event info
                country = event.get('country', 'unknown').upper()
                title = event.get('title', 'Unknown Event')
                time = event.get('time', 'TBD')
                impact = event.get('impact', 'low').lower()
                
                # Apply date filtering (simplified version)
                # ... [filtering logic would go here, omitted for clarity]
                
                # For events that pass the filter
                impact_emoji = "🟢"  # Default Low
                if impact == "high":
                    impact_emoji = "🔴"
                elif impact == "medium":
                    impact_emoji = "🟠"
                
                # Get currency code from country
                currency_code = COUNTRY_TO_CURRENCY.get(country, country)
                
                # Add flag to the currency code
                flag = CURRENCY_FLAG.get(country, '')
                
                # Add the event to the filtered list
                filtered_events.append({
                    'country': country,
                    'currency_code': currency_code,
                    'flag': flag,
                    'time': time,
                    'title': title,
                    'impact_emoji': impact_emoji,
                    'sort_time': self._parse_time_for_sorting(event)
                })
            
            # Check if we have events after filtering
            if not filtered_events:
                return message + "No major economic events scheduled for today."
            
            # Sort events by currency and time
            filtered_events.sort(key=lambda x: (x['currency_code'], x['sort_time']))
            
            # Group events by currency
            events_by_currency = {}
            for event in filtered_events:
                currency_code = event['currency_code']
                if currency_code not in events_by_currency:
                    events_by_currency[currency_code] = []
                events_by_currency[currency_code].append(event)
            
            # Add events to the message, grouped by currency
            for currency_code, events in events_by_currency.items():
                # Show currency header with flag
                flag = events[0]['flag']
                message += f"{flag} {currency_code}\n"
                
                # Show events for this currency
                for event in sorted(events, key=lambda x: x['sort_time']):
                    # Simplify event name by removing date references
                    title = event['title']
                    # Remove quarter indicators (Q1), (Q2) etc.
                    title = re.sub(r'\s*\(Q[1-4]\)\s*', ' ', title)
                    # Remove month/year indicators like (Mar), (Apr), etc.
                    title = re.sub(r'\s*\([A-Za-z]{3}\)\s*', ' ', title)
                    # Remove change period indicators like (MoM), (YoY), (QoQ)
                    title = re.sub(r'\s*\((?:MoM|YoY|QoQ)\)\s*', ' ', title)
                    # Remove date patterns like (Jan/2024)
                    title = re.sub(r'\s*\([A-Za-z]{3}/\d{4}\)\s*', ' ', title)
                    # Remove trailing spaces
                    title = title.strip()
                    
                    message += f"{event['time']} - {event['impact_emoji']} {title}\n"
                
                # Empty line between currencies
                message += "\n"
            
            # Only add the note once
            message += "Note: Only showing events scheduled for today."
            
            return message
            
        except Exception as e:
            self.logger.error(f"Error formatting calendar events: {str(e)}")
            self.logger.exception(e)
            
            # Super simple fallback in case of an error
            return "<b>📅 Economic Calendar</b>\n\nUnable to format calendar data correctly. Please try again later."
    
    def _parse_time_for_sorting(self, event):
        """Helper function to parse time for sorting events"""
        time_str = event.get('time', '00:00')
        try:
            if ':' in time_str:
                parts = time_str.split(':')
                hour = int(parts[0])
                minute = int(parts[1].split()[0])
                return hour * 60 + minute
            else:
                return 0
        except (ValueError, IndexError):
            return 0

    async def update_message(self, query, text, keyboard=None, parse_mode=ParseMode.HTML):
        """Update a message, properly handling media removal if necessary"""
        try:
            # Check if the message contains media (photo or animation)
            has_media = bool(query.message.photo) or query.message.animation is not None
            
            if has_media:
                try:
                    # Step 1: Try to delete the message and send a new one
                    await query.message.delete()
                    await self.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=text,
                        reply_markup=keyboard,
                        parse_mode=parse_mode
                    )
                    return
                except Exception as e:
                    logger.warning(f"Could not delete message: {str(e)}, trying alternative approach")
                    
                    try:
                        # Step 2: Replace with transparent GIF as document to avoid Telegram's animation
                        transparent_gif_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/Transparent.gif/1px-Transparent.gif"
                        await query.edit_message_media(
                            media=InputMediaDocument(
                                media=transparent_gif_url,
                                caption=text,
                                parse_mode=parse_mode
                            ),
                            reply_markup=keyboard
                        )
                        return
                    except Exception as e:
                        logger.warning(f"Could not replace with transparent GIF: {str(e)}, falling back to caption edit")
                        
                        # Step 3: Just update the caption as last resort
                        try:
                            await query.edit_message_caption(
                                caption=text,
                                reply_markup=keyboard,
                                parse_mode=parse_mode
                            )
                            return
                        except Exception as e:
                            logger.error(f"Could not update caption: {str(e)}")
            
            # Normal text message update
            await query.edit_message_text(
                text=text,
                reply_markup=keyboard,
                parse_mode=parse_mode
            )
            
        except Exception as e:
            logger.error(f"Error updating message: {str(e)}")
            # Try to send a completely new message if all else fails
            try:
                await self.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"Error updating previous message. {text}",
                    reply_markup=keyboard,
                    parse_mode=parse_mode
                )
            except Exception as e2:
                logger.error(f"Could not send new message: {str(e2)}")
    
    # Missing handler implementations
    async def back_signals_callback(self, update: Update, context=None) -> int:
        """Handle back_signals button press"""
        query = update.callback_query
        await query.answer()
        
        logger.info("back_signals_callback called")
        
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
            direction_emoji = "📈" if direction.upper() == "BUY" else "📉"
            
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
            application.add_handler(CallbackQueryHandler(self.back_analysis_callback, pattern="^back_analysis$"))
            
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
        
        # Set analysis type in context
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'technical'
            logger.info("Set analysis_type to technical")
        
        # Check if signal-specific data is present in callback data
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
            
            # Toon een loading message
            try:
                # Probeer eerst een loading GIF te tonen
                loading_gif = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"
                today_date = datetime.now().strftime("%B %d, %Y")
                loading_text = f"⏳ Loading economic calendar for {today_date}..."
                
                try:
                    loading_message = await query.edit_message_media(
                        media=InputMediaAnimation(
                            media=loading_gif,
                            caption=loading_text
                        )
                    )
                    logger.info("Successfully showed loading GIF for calendar analysis")
                except Exception as gif_error:
                    logger.warning(f"Could not show loading GIF: {str(gif_error)}")
                    # Fallback naar tekstbericht
                    loading_message = await query.edit_message_text(
                        text=loading_text
                    )
                
                # Sla loading message op in context
                if context and hasattr(context, 'user_data'):
                    context.user_data['loading_message'] = loading_message
            except Exception as e:
                logger.error(f"Error showing loading message: {str(e)}")
                # Ga gewoon door als dit mislukt
            
            # Show analysis directly for this instrument
            return await self.show_calendar_analysis(update, context, instrument=instrument)
        
        # Toon een loading message voordat we de economische kalender tonen
        try:
            # Probeer eerst een loading GIF te tonen
            loading_gif = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"
            today_date = datetime.now().strftime("%B %d, %Y")
            loading_text = f"⏳ Loading economic calendar for {today_date}..."
            
            try:
                loading_message = await query.edit_message_media(
                    media=InputMediaAnimation(
                        media=loading_gif,
                        caption=loading_text
                    )
                )
                logger.info("Successfully showed loading GIF for general calendar analysis")
            except Exception as gif_error:
                logger.warning(f"Could not show loading GIF: {str(gif_error)}")
                # Fallback naar tekstbericht
                loading_message = await query.edit_message_text(
                    text=loading_text
                )
            
            # Sla loading message op in context
            if context and hasattr(context, 'user_data'):
                context.user_data['loading_message'] = loading_message
                # Voeg een notitie toe dat we alleen events van vandaag laten zien
                context.user_data['show_today_only_note'] = True
        except Exception as e:
            logger.error(f"Error showing loading message: {str(e)}")
            # Ga gewoon door als dit mislukt
        
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
            loading_gif_url = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"
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
            loading_gif_url = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"
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
        loading_gif_url = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"
        loading_text = f"Loading economic calendar data..."
        
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
            user_id = update.effective_user.id
            
            # First try to get signal data from backup in context
            signal_instrument = None
            signal_direction = None
            signal_timeframe = None
            
            if context and hasattr(context, 'user_data'):
                # Try to get from backup fields first (these are more reliable after navigation)
                signal_instrument = context.user_data.get('signal_instrument_backup') or context.user_data.get('signal_instrument')
                signal_direction = context.user_data.get('signal_direction_backup') or context.user_data.get('signal_direction')
                signal_timeframe = context.user_data.get('signal_timeframe_backup') or context.user_data.get('signal_timeframe')
                
                # Reset signal flow flags but keep the signal info
                context.user_data['from_signal'] = True
                
                # Log retrieved values for debugging
                logger.info(f"Retrieved signal data from context: instrument={signal_instrument}, direction={signal_direction}, timeframe={signal_timeframe}")
            
            # Find the most recent signal for this user based on context data
            signal_data = None
            signal_id = None
            
            # Find matching signal based on instrument and direction
            if str(user_id) in self.user_signals:
                user_signal_dict = self.user_signals[str(user_id)]
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
            
            # Format: analyze_from_signal_INSTRUMENT_SIGNALID
            if len(parts) >= 4:
                instrument = parts[3]
                signal_id = parts[4] if len(parts) >= 5 else None
                
                # Store in context for other handlers
                if context and hasattr(context, 'user_data'):
                    context.user_data['instrument'] = instrument
                    if signal_id:
                        context.user_data['signal_id'] = signal_id
                    
                    # Make a backup copy to ensure we can return to signal later
                    context.user_data['signal_instrument_backup'] = instrument
                    if signal_id:
                        context.user_data['signal_id_backup'] = signal_id
                    
                    # Also store info from the actual signal if available
                    if str(update.effective_user.id) in self.user_signals and signal_id in self.user_signals[str(update.effective_user.id)]:
                        signal = self.user_signals[str(update.effective_user.id)][signal_id]
                        if signal:
                            context.user_data['signal_direction'] = signal.get('direction')
                            context.user_data['signal_timeframe'] = signal.get('interval')
                            # Backup copies
                            context.user_data['signal_direction_backup'] = signal.get('direction')
                            context.user_data['signal_timeframe_backup'] = signal.get('interval')
                            logger.info(f"Stored signal details: direction={signal.get('direction')}, timeframe={signal.get('interval')}")
            else:
                # Legacy support - just extract the instrument
                instrument = parts[3] if len(parts) >= 4 else None
                
                if instrument and context and hasattr(context, 'user_data'):
                    context.user_data['instrument'] = instrument
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
        """Handle button callback queries"""
        try:
            query = update.callback_query
            callback_data = query.data
            
            # Log the callback data
            logger.info(f"Button callback opgeroepen met data: {callback_data}")
            
            # Answer the callback query to stop the loading indicator
            await query.answer()
            
            # Handle analyze from signal button
            if callback_data.startswith("analyze_from_signal_"):
                return await self.analyze_from_signal_callback(update, context)
                
            # Help button
            if callback_data == "help":
                await self.help_command(update, context)
                return MENU
                
            # Menu navigation
            if callback_data == CALLBACK_MENU_ANALYSE:
                return await self.menu_analyse_callback(update, context)
            elif callback_data == CALLBACK_MENU_SIGNALS:
                return await self.menu_signals_callback(update, context)
            
            # Analysis type selection
            elif callback_data == CALLBACK_ANALYSIS_TECHNICAL or callback_data == "analysis_technical":
                return await self.analysis_technical_callback(update, context)
            elif callback_data == CALLBACK_ANALYSIS_SENTIMENT or callback_data == "analysis_sentiment":
                return await self.analysis_sentiment_callback(update, context)
            elif callback_data == CALLBACK_ANALYSIS_CALENDAR or callback_data == "analysis_calendar":
                return await self.analysis_calendar_callback(update, context)
                
            # Direct instrument_timeframe callbacks  
            if "_timeframe_" in callback_data:
                # Format: instrument_EURUSD_timeframe_H1
                parts = callback_data.split("_")
                instrument = parts[1]
                timeframe = parts[3] if len(parts) > 3 else "1h"  # Default to 1h
                return await self.show_technical_analysis(update, context, instrument=instrument, timeframe=timeframe)
            
            # Verwerk instrument keuzes met specifiek type (chart, sentiment, calendar)
            if "_chart" in callback_data or "_sentiment" in callback_data or "_calendar" in callback_data:
                # Direct doorsturen naar de instrument_callback methode
                logger.info(f"Specifiek instrument type gedetecteerd in: {callback_data}")
                return await self.instrument_callback(update, context)
            
            # Handle instrument signal choices
            if "_signals" in callback_data and callback_data.startswith("instrument_"):
                logger.info(f"Signal instrument selection detected: {callback_data}")
                return await self.instrument_signals_callback(update, context)
            
            # Speciale afhandeling voor markt keuzes
            if callback_data.startswith("market_"):
                return await self.market_callback(update, context)
            
            # Signals handlers
            if callback_data == "signals_add" or callback_data == CALLBACK_SIGNALS_ADD:
                return await self.signals_add_callback(update, context)
                
            # Manage signals handler
            if callback_data == "signals_manage" or callback_data == CALLBACK_SIGNALS_MANAGE:
                return await self.signals_manage_callback(update, context)
            
            # Back navigation handlers
            if callback_data == "back_menu" or callback_data == CALLBACK_BACK_MENU:
                return await self.back_menu_callback(update, context)
            elif callback_data == "back_analysis" or callback_data == CALLBACK_BACK_ANALYSIS:
                return await self.analysis_callback(update, context)
            elif callback_data == "back_signals" or callback_data == CALLBACK_BACK_SIGNALS:
                return await self.back_signals_callback(update, context)
            elif callback_data == "back_market" or callback_data == CALLBACK_BACK_MARKET:
                return await self.back_market_callback(update, context)
            elif callback_data == "back_instrument":
                return await self.back_instrument_callback(update, context)
            elif callback_data == "back_to_signal":
                return await self.back_to_signal_callback(update, context)
                
            # Handle delete signal
            if callback_data.startswith("delete_signal_"):
                # Extract signal ID from callback data
                signal_id = callback_data.replace("delete_signal_", "")
                
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
            if callback_data == "delete_all_signals":
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
                    
                    
            # Default handling if no specific callback found, go back to menu
            logger.warning(f"Unhandled callback_data: {callback_data}")
            return MENU
            
        except Exception as e:
            logger.error(f"Error in button_callback: {str(e)}")
            logger.exception(e)
            return MENU

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
        
    async def market_callback(self, update: Update, context=None) -> int:
        """Handle market selection and show appropriate instruments"""
        query = update.callback_query
        await query.answer()
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
        message_text = f"Select a {market.upper()} instrument:"
        
        if is_signals_context:
            # Signal-specific keyboards
            if market == 'forex':
                keyboard = FOREX_KEYBOARD_SIGNALS
            elif market == 'crypto':
                keyboard = CRYPTO_KEYBOARD_SIGNALS
            elif market == 'indices':
                keyboard = INDICES_KEYBOARD_SIGNALS
            elif market == 'commodities':
                keyboard = COMMODITIES_KEYBOARD_SIGNALS
            else:
                # Default keyboard for unknown market
                keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]]
                message_text = f"Unknown market: {market}"
        else:
            # Analysis-specific keyboards
            analysis_type = context.user_data.get('analysis_type', 'technical') if context and hasattr(context, 'user_data') else 'technical'
            
            if analysis_type == 'sentiment':
                if market == 'forex':
                    keyboard = FOREX_SENTIMENT_KEYBOARD
                elif market == 'crypto':
                    keyboard = CRYPTO_SENTIMENT_KEYBOARD
                elif market == 'indices':
                    keyboard = INDICES_SENTIMENT_KEYBOARD
                elif market == 'commodities':
                    keyboard = COMMODITIES_SENTIMENT_KEYBOARD
                else:
                    keyboard = MARKET_SENTIMENT_KEYBOARD
                message_text = f"Select instrument for sentiment analysis:"
            elif analysis_type == 'calendar':
                if market == 'forex':
                    keyboard = FOREX_CALENDAR_KEYBOARD
                else:
                    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]]
                message_text = f"Select currency for economic calendar:"
            else:
                # Default to technical analysis
                if market == 'forex':
                    keyboard = FOREX_KEYBOARD
                elif market == 'crypto':
                    keyboard = CRYPTO_KEYBOARD
                elif market == 'indices':
                    keyboard = INDICES_KEYBOARD
                elif market == 'commodities':
                    keyboard = COMMODITIES_KEYBOARD
                else:
                    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]]
                    message_text = f"Unknown market: {market}"
                message_text = f"Select instrument for technical analysis:"
        
        # Get the welcome GIF URL to maintain it during navigation
        try:
            # Get welcome GIF URL
            welcome_gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
            
            # Use update_message_with_gif to keep the welcome GIF visible
            success = await gif_utils.update_message_with_gif(
                query=query,
                gif_url=welcome_gif_url,
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            if not success:
                logger.warning("Failed to update message with GIF, falling back to standard update")
                # Fallback to standard message update if GIF update fails
                await self.update_message(
                    query=query,
                    text=message_text,
                    keyboard=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.error(f"Error updating message in market_callback: {str(e)}")
            # Try to create a new message as fallback
            try:
                await query.message.reply_text(
                    text=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            except Exception as e2:
                logger.error(f"Error sending new message in market_callback: {str(e2)}")
        
        return CHOOSE_INSTRUMENT
        
    async def back_market_callback(self, update: Update, context=None) -> int:
        """Handle back_market button press"""
        query = update.callback_query
        await query.answer()
        
        logger.info("back_market_callback called")
        
        # Determine if we need to go back to signals or analysis flow
        is_signals_context = False
        if context and hasattr(context, 'user_data'):
            is_signals_context = context.user_data.get('is_signals_context', False)
        
        if is_signals_context:
            # Go back to signals menu
            return await self.back_signals_callback(update, context)
        else:
            # Go back to analysis selection
            return await self.analysis_callback(update, context)

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
        
        # Get applicable timeframes for this instrument
        timeframes = []
        if instrument in INSTRUMENT_TIMEFRAME_MAP:
            # If the instrument has a predefined timeframe mapping
            timeframe = INSTRUMENT_TIMEFRAME_MAP[instrument]
            timeframe_display = TIMEFRAME_DISPLAY_MAP.get(timeframe, timeframe)
            timeframes = [(timeframe, timeframe_display)]
        else:
            # Default timeframes
            for tf, display in TIMEFRAME_DISPLAY_MAP.items():
                timeframes.append((tf, display))
                
        # Create keyboard for timeframe selection or direct subscription
        keyboard = []
        
        if len(timeframes) == 1:
            # Only one timeframe, offer direct subscription
            timeframe, timeframe_display = timeframes[0]
            
            # Store in context
            if context and hasattr(context, 'user_data'):
                context.user_data['timeframe'] = timeframe
            
            # Create a subscription for this instrument/timeframe
            user_id = update.effective_user.id
            
            try:
                # Check if subscription already exists
                response = self.db.supabase.table('signal_subscriptions').select('*').eq('user_id', user_id).eq('instrument', instrument).eq('timeframe', timeframe).execute()
                
                if response and response.data and len(response.data) > 0:
                    # Subscription already exists
                    message = f"✅ You are already subscribed to <b>{instrument}</b> signals on {timeframe_display} timeframe!"
                else:
                    # Create new subscription
                    market = _detect_market(instrument)
                    
                    subscription_data = {
                        'user_id': user_id,
                        'instrument': instrument,
                        'timeframe': timeframe,
                        'market': market,
                        'created_at': datetime.now().isoformat()
                    }
                    
                    insert_response = self.db.supabase.table('signal_subscriptions').insert(subscription_data).execute()
                    
                    if insert_response and insert_response.data:
                        message = f"✅ Successfully subscribed to <b>{instrument}</b> signals on {timeframe_display} timeframe!"
                    else:
                        message = f"❌ Error creating subscription for {instrument} on {timeframe_display} timeframe. Please try again."
            except Exception as e:
                logger.error(f"Error creating signal subscription: {str(e)}")
                message = f"❌ Error creating subscription: {str(e)}"
                
            # Show confirmation and options to add more or manage
            keyboard = [
                [InlineKeyboardButton("➕ Add More", callback_data="signals_add")],
                [InlineKeyboardButton("⚙️ Manage Signals", callback_data="signals_manage")],
                [InlineKeyboardButton("⬅️ Back to Signals", callback_data="back_signals")]
            ]
            
            # Update message
            await self.update_message(
                query=query,
                text=message,
                keyboard=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            return CHOOSE_SIGNALS
        else:
            # Multiple timeframes, let user select
            message = f"Select timeframe for <b>{instrument}</b> signals:"
            
            for tf, display in timeframes:
                keyboard.append([InlineKeyboardButton(display, callback_data=f"timeframe_{instrument}_{tf}")])
            
            # Add back button
            keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_signals")])
            
            # Update message
            await self.update_message(
                query=query,
                text=message,
                keyboard=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            return CHOOSE_TIMEFRAME

    async def instrument_callback(self, update: Update, context=None) -> int:
        """Handle instrument callback"""
        query = update.callback_query
        await query.answer()
        
        # Get the instrument and type from the callback data
        callback_data = query.data
        parts = callback_data.split("_")
        
        # Extract instrument and type
        instrument = parts[1]
        instrument_type = parts[2] if len(parts) > 2 else None  # chart, sentiment, calendar
        
        # Map instrument_type to analysis_type
        if instrument_type == "chart":
            analysis_type = "technical"
        elif instrument_type == "sentiment":
            analysis_type = "sentiment"
        elif instrument_type == "calendar":
            analysis_type = "calendar"
        else:
            # Get from context
            analysis_type = context.user_data.get('analysis_type') if context and hasattr(context, 'user_data') else None
        
        logger.info(f"Selected instrument: {instrument}, type: {analysis_type}")
        
        # Save instrument and analysis type in context
        if context and hasattr(context, 'user_data'):
            context.user_data['instrument'] = instrument
            if analysis_type:
                context.user_data['analysis_type'] = analysis_type
        
        try:
            # Handle different analysis types
            if analysis_type == "technical" or instrument_type == "chart":
                # Verwijder het instrument bericht direct
                await self.remove_message_with_animation(query)
                
                # Show loading message first with loading GIF
                loading_message = None
                try:
                    # Get loading GIF URL
                    loading_gif_url = await gif_utils.get_loading_gif()
                    logger.info(f"Using loading GIF URL: {loading_gif_url}")
                    
                    # Try to show the loading GIF
                    try:
                        # First try to send a new animation message
                        loading_message = await context.bot.send_animation(
                            chat_id=update.effective_chat.id,
                            animation=loading_gif_url,
                            caption=f"⏳ Analyzing {instrument} on 1h timeframe... Please wait.",
                            parse_mode=ParseMode.HTML
                        )
                        logger.info(f"Sent new message with loading GIF")
                    except Exception as animation_error:
                        logger.error(f"Error sending animation: {str(animation_error)}")
                        # Fall back to sending a simple text message
                        loading_message = await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"⏳ Analyzing {instrument} on 1h timeframe... Please wait."
                        )
                except Exception as e:
                    logger.error(f"Error showing loading GIF: {str(e)}")
                
                # Small delay to ensure the loading GIF is visible
                await asyncio.sleep(1)
                
                # Store loading message in context for later reference
                if context and hasattr(context, 'user_data') and loading_message:
                    context.user_data['loading_message'] = loading_message
                
                # Get the chart service
                if not hasattr(self, 'chart_service') or self.chart_service is None:
                    from trading_bot.services.chart_service.chart import ChartService
                    logger.info("Initializing chart service")
                    self.chart_service = ChartService()
                    await self.chart_service.initialize()
                
                try:
                    # Get the chart and analysis directly
                    timeframe = "1h"  # Default timeframe
                    chart_image_path, analysis_text = await self.chart_service.get_technical_analysis(instrument, timeframe)
                    
                    # Verwijder het loading bericht als het bestaat
                    if loading_message:
                        try:
                            await loading_message.delete()
                        except Exception as e:
                            logger.warning(f"Could not delete loading message: {str(e)}")
                            # Probeer het bericht te vervangen met een transparante GIF
                            await self.remove_message_with_animation(loading_message)
                    
                    # We hoeven het instrument bericht niet meer te verwijderen omdat we dit al eerder deden
                    
                    if chart_image_path and os.path.exists(chart_image_path):
                        # Create a keyboard with Back button that goes to market selection
                        keyboard = [
                            [
                                InlineKeyboardButton("⬅️ Back", callback_data="back_market")
                            ]
                        ]
                        
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        logger.info(f"Setting up back button with callback_data='back_market'")
                        
                        # Send the chart with analysis
                        with open(chart_image_path, 'rb') as photo:
                            await context.bot.send_photo(
                                chat_id=query.message.chat_id,
                                photo=photo,
                                caption=analysis_text,
                                reply_markup=reply_markup,
                                parse_mode=ParseMode.HTML
                            )
                        
                        # Clean up the chart file
                        try:
                            os.remove(chart_image_path)
                        except Exception as cleanup_error:
                            logger.error(f"Error cleaning up chart file: {str(cleanup_error)}")
                        
                        return CHOOSE_ANALYSIS
                        
                    else:
                        # If no chart image is available, just send the analysis text
                        keyboard = [
                            [
                                InlineKeyboardButton("⬅️ Back", callback_data="back_market")
                            ]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        await query.message.reply_text(
                            text=analysis_text or f"Sorry, analysis for {instrument} is not available at this time.",
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML
                        )
                        return CHOOSE_ANALYSIS
                        
                except Exception as e:
                    logger.error(f"Error in instrument_callback: {str(e)}")
                    # Verwijder het instrument bericht ook bij een fout
                    await self.remove_message_with_animation(query)
                    
                    # Send error message
                    keyboard = [
                        [
                            InlineKeyboardButton("⬅️ Back", callback_data="back_market")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=f"Error analyzing {instrument}. Please try again later.",
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.HTML
                    )
                    return CHOOSE_ANALYSIS
                    
            elif analysis_type == "sentiment" or instrument_type == "sentiment":
                # Verwijder het instrument bericht direct
                await self.remove_message_with_animation(query)
                
                # Show loading GIF for sentiment analysis
                try:
                    # Get loading GIF URL
                    loading_gif_url = await gif_utils.get_loading_gif()
                    logger.info(f"Using loading GIF URL for sentiment: {loading_gif_url}")
                    
                    # Send new message with loading GIF
                    loading_message = await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=loading_gif_url,
                        caption=f"Loading sentiment analysis for {instrument}... Please wait.",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Error showing loading GIF for sentiment analysis: {str(e)}")
                    # Fallback to standard text message
                    try:
                        loading_message = await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"Loading sentiment analysis for {instrument}... Please wait."
                        )
                    except Exception as msg_error:
                        logger.error(f"Error sending loading message: {str(msg_error)}")
                
                # Store loading message in context for later reference
                if context and hasattr(context, 'user_data') and loading_message:
                    context.user_data['loading_message'] = loading_message
                
                return await self.show_sentiment_analysis(update, context, instrument=instrument)
                    
            elif analysis_type == "calendar" or instrument_type == "calendar":
                # Verwijder het instrument bericht direct
                await self.remove_message_with_animation(query)
                
                # Show loading GIF for calendar analysis
                try:
                    # Get loading GIF URL
                    loading_gif_url = await gif_utils.get_loading_gif()
                    logger.info(f"Using loading GIF URL for calendar: {loading_gif_url}")
                    
                    # Send new message with loading GIF
                    loading_message = await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=loading_gif_url,
                        caption=f"Loading economic calendar... Please wait.",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Error showing loading GIF for calendar analysis: {str(e)}")
                    # Fallback to standard text message
                    try:
                        loading_message = await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"Loading economic calendar... Please wait."
                        )
                    except Exception as msg_error:
                        logger.error(f"Error sending loading message: {str(msg_error)}")
                
                # Store loading message in context for later reference
                if context and hasattr(context, 'user_data') and loading_message:
                    context.user_data['loading_message'] = loading_message
                
                return await self.show_calendar_analysis(update, context)
                
        except Exception as e:
            logger.error(f"Error in instrument_callback: {str(e)}")
            logger.error(traceback.format_exc())
            
            # In case of error, show a generic error message and go back to instrument selection
            try:
                keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_market")]]
                await query.edit_message_text(
                    text=f"An error occurred. Please try again or select a different instrument.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                # Fallback to caption update
                try:
                    await query.edit_message_caption(
                        caption=f"An error occurred. Please try again or select a different instrument.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as caption_error:
                    logger.error(f"Error updating caption in fallback: {str(caption_error)}")
                    # Last resort - send a new message
                    await query.message.reply_text(
                        text=f"An error occurred. Please try again or select a different instrument.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
            
            return CHOOSE_MARKET
        
        # For other market types, call the market_callback method
        return await self.market_callback(update, context)

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
        """Handle back button to return to instrument selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Clear style/timeframe data but keep instrument
            if context and hasattr(context, 'user_data'):
                keys_to_clear = ['style', 'timeframe']
                for key in keys_to_clear:
                    if key in context.user_data:
                        del context.user_data[key]
            
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
            
            # If we're in signals context, go back to signals menu
            if is_signals_context and hasattr(self, 'back_signals_callback'):
                return await self.back_signals_callback(update, context)
            
            # Otherwise go back to market selection
            return await self.back_market_callback(update, context)
            
        except Exception as e:
            logger.error(f"Failed to handle back_instrument_callback: {str(e)}")
            # Try to recover by going to market selection
            if hasattr(self, 'back_market_callback'):
                return await self.back_market_callback(update, context)
            else:
                # Last resort fallback - update message with error
                await self.update_message(
                    query, 
                    "Sorry, an error occurred. Please use /menu to start again.", 
                    keyboard=None
                )
                return ConversationHandler.END

    async def back_analysis_callback(self, update: Update, context=None) -> int:
        """Handle back button press from market selection to return to analysis type selection."""
        query = update.callback_query
        await query.answer()
        
        try:
            # Clear market from context if it exists
            if context and hasattr(context, 'user_data') and 'market' in context.user_data:
                del context.user_data['market']
                
            # Show analysis options menu
            text = "Choose an analysis type:"
            keyboard = InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            
            # Use our improved update_message method to handle media properly
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
            try:
                await self.show_main_menu(update, context)
            except Exception as e2:
                logger.error(f"Could not show main menu as fallback: {str(e2)}")
            return MENU

    async def back_to_signal_analysis_callback(self, update: Update, context=None) -> int:
        """Handle back_to_signal_analysis button press"""
        query = update.callback_query
        await query.answer()
        
        logger.info("back_to_signal_analysis_callback called")
        
        # Restore any backed up signal data if available
        if context and hasattr(context, 'user_data'):
            # Check for backed up signal data
            if 'signal_instrument_backup' in context.user_data:
                context.user_data['instrument'] = context.user_data['signal_instrument_backup']
                
            if 'signal_direction_backup' in context.user_data:
                context.user_data['signal_direction'] = context.user_data['signal_direction_backup']
                
            if 'signal_timeframe_backup' in context.user_data:
                context.user_data['signal_timeframe'] = context.user_data['signal_timeframe_backup']
                
            # Keep from_signal flag
            context.user_data['from_signal'] = True
            
            logger.info(f"Restored signal context: {context.user_data}")
        
        # Create keyboard for signal analysis options
        keyboard = InlineKeyboardMarkup(SIGNAL_ANALYSIS_KEYBOARD)
        
        # Update the message
        await self.update_message(
            query=query,
            text=f"<b>🔍 Signal Analysis</b>\n\nChoose analysis type for this signal:",
            keyboard=keyboard
        )
        
        return CHOOSE_ANALYSIS

    def _load_signals(self):
        """Load signals from the signals directory"""
        try:
            logger.info("Loading signals from directory")
            
            # Initialize signals cache
            self.user_signals = {}
            
            # Check if signals directory exists
            if not os.path.exists(self.signals_dir):
                os.makedirs(self.signals_dir, exist_ok=True)
                logger.info(f"Created signals directory: {self.signals_dir}")
                return
            
            # List signal files
            signal_files = [f for f in os.listdir(self.signals_dir) if f.endswith('.json')]
            
            if not signal_files:
                logger.info("No signal files found")
                return
                
            # Load each signal file
            for signal_file in signal_files:
                try:
                    with open(os.path.join(self.signals_dir, signal_file), 'r') as f:
                        signal_data = json.load(f)
                        
                    # Extract signal ID
                    signal_id = signal_data.get('id')
                    
                    if not signal_id:
                        # Try to extract from filename
                        signal_id = signal_file.replace('.json', '')
                        
                    # Initialize for admin users
                    if hasattr(self, 'admin_users') and self.admin_users:
                        for admin_id in self.admin_users:
                            admin_str_id = str(admin_id)
                            if admin_str_id not in self.user_signals:
                                self.user_signals[admin_str_id] = {}
                            
                            # Store signal for admin
                            self.user_signals[admin_str_id][signal_id] = signal_data
                except Exception as e:
                    logger.error(f"Error loading signal file {signal_file}: {str(e)}")
                    continue
                    
            logger.info(f"Loaded {len(signal_files)} signal files")
            
        except Exception as e:
            logger.error(f"Error loading signals: {str(e)}")

    async def remove_message_with_animation(self, query: CallbackQuery) -> bool:
        """
        Remove a message using a multi-step approach:
        1. Try to delete the entire message
        2. If that fails, replace with a transparent GIF
        3. If that fails, just edit the caption
        """
        try:
            # Stap 1: Probeer het hele bericht te verwijderen
            try:
                await query.message.delete()
                logger.info("Message successfully deleted")
                return True
            except Exception as delete_error:
                logger.warning(f"Could not delete message: {str(delete_error)}")
                
                # Stap 2: Vervang met transparante GIF
                try:
                    transparent_gif = "https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/Transparent.gif/1px-Transparent.gif"
                    await query.edit_message_media(
                        media=InputMediaDocument(
                            media=transparent_gif,
                            caption=""
                        )
                    )
                    logger.info("Message replaced with transparent GIF")
                    return True
                except Exception as gif_error:
                    logger.warning(f"Could not replace with transparent GIF: {str(gif_error)}")
                    
                    # Stap 3: Bewerk alleen het bijschrift
                    try:
                        await query.edit_message_caption(caption="")
                        logger.info("Message caption cleared")
                        return True
                    except Exception as caption_error:
                        logger.error(f"Could not clear caption: {str(caption_error)}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error in remove_message_with_animation: {str(e)}")
            return False

    async def show_sentiment_analysis(self, update: Update, context=None, instrument=None) -> int:
        """Show sentiment analysis for a selected instrument"""
        query = update.callback_query
        await query.answer()
        
        try:
            chat_id = update.effective_chat.id
            
            # Check if we're in the signal flow
            is_from_signal = False
            if context and hasattr(context, 'user_data'):
                is_from_signal = context.user_data.get('from_signal', False)
                # Add debug logging
                logger.info(f"show_sentiment_analysis: from_signal = {is_from_signal}")
                logger.info(f"Context user_data: {context.user_data}")
            
            # Get instrument from parameter or context
            if not instrument and context and hasattr(context, 'user_data'):
                instrument = context.user_data.get('instrument')
            
            # Check if we have a loading message from context
            loading_message = None
            if context and hasattr(context, 'user_data'):
                loading_message = context.user_data.get('loading_message')
                # Remove reference to avoid memory leaks
                if 'loading_message' in context.user_data:
                    del context.user_data['loading_message']
            
            if not instrument:
                logger.error("No instrument provided for sentiment analysis")
                
                # Verwijder het loading bericht als het bestaat
                if loading_message:
                    try:
                        await loading_message.delete()
                    except Exception as e:
                        logger.warning(f"Could not delete loading message: {str(e)}")
                
                # Stuur een nieuw bericht met de foutmelding
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Please select an instrument first.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_market")]])
                )
                return CHOOSE_MARKET
            
            logger.info(f"Showing sentiment analysis for {instrument}")
            
            # Initialize sentiment service if needed
            if not hasattr(self, 'sentiment_service') or not self.sentiment_service:
                from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
                self.sentiment_service = MarketSentimentService()
            
            try:
                # Get sentiment analysis
                sentiment_data = await self.sentiment_service.get_sentiment(instrument)
                
                # Format the sentiment message
                message = f"<b>🧠 Market Sentiment Analysis for {instrument}</b>\n\n"
                
                # Overall sentiment score
                sentiment_score = sentiment_data.get('sentiment_score', 0)
                sentiment_emoji = "📈" if sentiment_score > 0 else "📉" if sentiment_score < 0 else "➡️"
                message += f"Overall Sentiment: {sentiment_emoji} "
                
                if sentiment_score > 0.5:
                    message += "Strongly Bullish"
                elif sentiment_score > 0:
                    message += "Slightly Bullish"
                elif sentiment_score < -0.5:
                    message += "Strongly Bearish"
                elif sentiment_score < 0:
                    message += "Slightly Bearish"
                else:
                    message += "Neutral"
                    
                message += f" ({sentiment_score:.2f})\n\n"
                
                # Add sentiment breakdown
                message += "<b>Sentiment Breakdown:</b>\n"
                message += f"• Technical Indicators: {sentiment_data.get('technical_score', 'N/A')}\n"
                message += f"• News Sentiment: {sentiment_data.get('news_score', 'N/A')}\n"
                message += f"• Social Media: {sentiment_data.get('social_score', 'N/A')}\n\n"
                
                # Add recent news headlines if available
                if 'news_headlines' in sentiment_data and sentiment_data['news_headlines']:
                    message += "<b>Recent Market News:</b>\n"
                    for headline in sentiment_data['news_headlines'][:3]:
                        message += f"• {headline}\n"
                    message += "\n"
                
                # Add market mood
                message += "<b>Market Mood Indicators:</b>\n"
                message += f"• Volatility: {sentiment_data.get('volatility', 'Normal')}\n"
                message += f"• Volume: {sentiment_data.get('volume', 'Normal')}\n"
                message += f"• Trend Strength: {sentiment_data.get('trend_strength', 'Moderate')}\n\n"
                
                # Add time of analysis
                message += f"Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                
                # Create keyboard with back button
                keyboard = None
                if is_from_signal:
                    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")]]
                else:
                    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_market")]]
                
                # Verwijder het loading bericht als het bestaat
                if loading_message:
                    try:
                        await loading_message.delete()
                    except Exception as e:
                        logger.warning(f"Could not delete loading message: {str(e)}")
                        # Probeer het bericht te vervangen met een transparante GIF 
                        if hasattr(loading_message, 'message'):
                            try:
                                await self.remove_message_with_animation(loading_message)
                            except Exception as e2:
                                logger.error(f"Failed to remove loading message with animation: {str(e2)}")
                
                # Stuur een nieuw bericht met de sentiment analyse
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                return CHOOSE_ANALYSIS
                
            except Exception as e:
                logger.error(f"Error getting sentiment analysis: {str(e)}")
                
                # Verwijder het loading bericht als het bestaat
                if loading_message:
                    try:
                        await loading_message.delete()
                    except Exception as del_e:
                        logger.warning(f"Could not delete loading message: {str(del_e)}")
                
                # Show error message with back button
                keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_market")]]
                
                # Stuur een nieuw bericht met de foutmelding
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Error analyzing sentiment for {instrument}. Please try again later.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                return CHOOSE_ANALYSIS
                
        except Exception as e:
            logger.error(f"Error in show_sentiment_analysis: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Try to recover by sending a simple error message
            if context:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="An error occurred. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_market")]])
                )
                
            return CHOOSE_ANALYSIS

    async def analysis_callback(self, update: Update, context=None) -> int:
        """Handle analysis menu callback"""
        query = update.callback_query
        await query.answer()
        
        logger.info("analysis_callback called")
        
        try:
            # Reset analysis specific context
            if context and hasattr(context, 'user_data'):
                keys_to_remove = ['market', 'instrument', 'timeframe', 'analysis_type']
                for key in keys_to_remove:
                    if key in context.user_data:
                        del context.user_data[key]
            
            # Show analysis options menu
            text = "Select your analysis type:"
            keyboard = InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            
            # Try to update with GIF
            gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
            
            try:
                # First try to delete and send new message
                await query.message.delete()
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=gif_url,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.warning(f"Could not send new message with GIF: {str(e)}")
                # Fall back to updating existing message
                await self.update_message(
                    query=query,
                    text=text,
                    keyboard=keyboard,
                    parse_mode=ParseMode.HTML
                )
            
            return CHOOSE_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error in analysis_callback: {str(e)}")
            # Try to recover by showing main menu
            await self.show_main_menu(update, context)
            return MENU

    async def show_calendar_analysis(self, update: Update, context: CallbackContext, instrument: str = None) -> int:
        """Show economic calendar analysis"""
        try:
            query = update.callback_query
            chat_id = update.effective_chat.id
            
            logger.info(f"Showing calendar analysis for {instrument if instrument else 'all currencies'}")
            
            # Get the calendar service
            calendar_service = self._get_calendar_service()
            
            # Check if we have a loading message from context
            loading_message = None
            show_today_only_note = False
            if context and hasattr(context, 'user_data'):
                loading_message = context.user_data.get('loading_message')
                show_today_only_note = context.user_data.get('show_today_only_note', False)
                # Verwijder referenties om memory leaks te voorkomen
                if 'loading_message' in context.user_data:
                    del context.user_data['loading_message']
                if 'show_today_only_note' in context.user_data:
                    del context.user_data['show_today_only_note']
            
            try:
                # Get calendar data
                calendar_data = await calendar_service.get_calendar()
                
                # Format the calendar data
                message = await self._format_calendar_events(calendar_data)
                
                # Voeg notitie toe indien nodig
                if show_today_only_note:
                    message += "\n<i>Note: Only showing events scheduled for today.</i>"
                
                # Create keyboard with back button
                keyboard = None
                if context and hasattr(context, 'user_data') and context.user_data.get('from_signal', False):
                    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")]]
                else:
                    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_market")]]
                
                # Verwijder het loading bericht als het bestaat
                if loading_message:
                    try:
                        await loading_message.delete()
                    except Exception as e:
                        logger.warning(f"Could not delete loading message: {str(e)}")
                        # Probeer het bericht te vervangen met een transparante GIF 
                        if hasattr(loading_message, 'message'):
                            try:
                                await self.remove_message_with_animation(loading_message)
                            except Exception as e2:
                                logger.error(f"Failed to remove loading message with animation: {str(e2)}")
                
                # Stuur een nieuw bericht met de kalender informatie
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
                return CHOOSE_ANALYSIS
                
            except Exception as e:
                logger.error(f"Error getting calendar data: {str(e)}")
                
                # Verwijder het loading bericht als het bestaat
                if loading_message:
                    try:
                        await loading_message.delete()
                    except Exception as del_e:
                        logger.warning(f"Could not delete loading message: {str(del_e)}")
                
                # Show error message
                keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_market")]]
                
                # Stuur een nieuw bericht met de foutmelding
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Error loading economic calendar. Please try again later.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                return CHOOSE_ANALYSIS
                
        except Exception as e:
            logger.error(f"Error in show_calendar_analysis: {str(e)}")
            logger.error(traceback.format_exc())
            return CHOOSE_ANALYSIS

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
                await self.chart_service.initialize()
            
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
