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

# Conditional import of FastAPI - only attempt to import if needed
try:
    from fastapi import FastAPI, Request, HTTPException, status
except ImportError:
    # FastAPI not installed, which is fine if we're not using webhook mode
    pass

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
/menu - Show the main menu
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
        # Start timing the initialization
        init_start_time = time.time()
        
        # Database connection
        self.db = db
        
        # Setup configuration 
        self.stripe_service = stripe_service
        self.user_signals = {}
        self.signals_dir = "data/signals"
        self.signals_enabled_val = True
        self.polling_started = False
        self.admin_users = [1093307376, 2004519703]  # Add your Telegram ID here for testing
        self._signals_enabled = True  # Enable signals by default
        
        # Store the lazy_init flag
        self.lazy_init = lazy_init
        logger.info(f"Initializing TelegramService with lazy_init={lazy_init}")
        
        # Setup logger
        self.logger = logging.getLogger(__name__)
        
        # GIF utilities for UI
        self.gif_utils = gif_utils  # Initialize gif_utils as an attribute
        
        # Telegram Bot configuratie
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "7328581013:AAFMGu8mz746nbj1eh6BuOp0erKl4Nb_-QQ")
        logger.info(f"Using bot token: {self.bot_token[:10]}...")
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
        
        # Initialize the bot
        self.bot = None
        self.application = None  # Will be initialized in setup()
        
        # Background tasks for asyncio
        self._background_tasks = []
        
        # Webhook configuration
        self.webhook_url = os.getenv("WEBHOOK_URL", "")
        self.webhook_path = "/webhook"  # Always use this path
        if self.webhook_url.endswith("/"):
            self.webhook_url = self.webhook_url[:-1]  # Remove trailing slash
        # Voorkom duplicatie van /webhook in de URL
        if self.webhook_url.endswith("/webhook"):
            self.webhook_path = ""  # Geen pad nodig als het al in de URL zit
        
        # Flag to track handler registration
        self._handlers_registered = False
        self._handler_registration_lock = asyncio.Lock()
        
        # Initialize API services - all with deferred/lazy loading
        self._chart_service = None  # Defer chart service initialization 
        self._calendar_service = None
        self._sentiment_service = None
        
        # Configure sentiment service with optimized settings when using lazy loading
        self._sentiment_service_config = {
            'fast_mode': True,  # Always enable fast mode for better performance
            'cache_ttl_minutes': 120 if lazy_init else 60,  # Longer cache TTL for lazy loading
            'persistent_cache': True
        }
        
        # Bot application initialization
        self.persistence = None
        self.bot_started = False
        
        # Cache for sentiment analysis - optimize caching when using lazy loading
        self.sentiment_cache = {}
        self.sentiment_cache_ttl = 120 * 60 if lazy_init else 60 * 60  # 2 hours or 1 hour in seconds
            
        # Start the bot
        try:
            # Check for bot token
            if not self.bot_token:
                logger.error("Missing bot token, using fallback token")
                self.bot_token = "7328581013:AAFMGu8mz746nbj1eh6BuOp0erKl4Nb_-QQ"
            
            # Zorg ervoor dat we een geldige token hebben
            logger.info(f"Using bot token: {self.bot_token[:10]}...")
            
            # Initialize the bot only once with connection pool settings
            # Use the provided token from initialization
            logger.info(f"Initializing bot with token: {self.bot_token[:10]}...")
            self.bot = Bot(token=self.bot_token, request=request)
            logger.info(f"Bot initialized with webhook URL: {self.webhook_url} and path: {self.webhook_path}")
        
            # Initialize the application
            self.application = Application.builder().bot(self.bot).build()
        
            # We'll register handlers later during run() instead of here,
            # to avoid racing conditions and ensure proper order
            logger.info("Handlers will be registered during application startup")
            
            # Only load signals if not using lazy initialization
            if not lazy_init:
                # Use asyncio.create_task to properly handle the coroutine
                asyncio.create_task(self._load_signals())
            else:
                # When using lazy init, we should not create a background task as there's no event loop
                # Instead, log that signals will be loaded on first use
                logger.info("Signals will be loaded on first use (lazy_init=True)")
                # Store the signals load status
                self._signals_loaded = False
            
            logger.info("Bot setup completed successfully")
            logger.info("Telegram service initialized")
            
            # Keep track of processed updates
            self.processed_updates = set()
            
            # Log the initialization time
            init_time = time.time() - init_start_time
            logger.info(f"TelegramService initialization completed in {init_time:.2f} seconds")
        
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            raise

    async def initialize_services(self):
        """Initialize services that require an asyncio event loop"""
        try:
            if getattr(self, 'lazy_init', False):
                # Skip initialization when lazy_init is enabled
                logger.info("Services configured for lazy initialization - deferring service setup until first use")
                return
                
            # For backward compatibility, initialize services here when lazy_init is False
            logger.info("Initializing services upfront (lazy_init=False)")
            
            # Initialize chart service if not already initialized
            if self._chart_service is None:
                self._chart_service = ChartService()
                logger.info("Chart service initialized")
                
            # Initialize sentiment service if not already initialized
            if self._sentiment_service is None:
                self._sentiment_service = MarketSentimentService(
                    fast_mode=self._sentiment_service_config['fast_mode'],
                    cache_ttl_minutes=self._sentiment_service_config['cache_ttl_minutes'],
                    persistent_cache=self._sentiment_service_config['persistent_cache']
                )
                logger.info("Sentiment service initialized")
                
            # Initialize calendar service if not already initialized
            if self._calendar_service is None:
                self._calendar_service = EconomicCalendarService()
                logger.info("Calendar service initialized")
                
        except Exception as e:
            logger.error(f"Error initializing services: {str(e)}")
            raise
            
    @property
    def chart_service(self):
        """Lazy loaded chart service"""
        if self._chart_service is None:
            # Only initialize the chart service when it's first accessed
            init_start_time = time.time()
            logger.info("Lazy loading chart service")
            self._chart_service = ChartService()
            init_time = time.time() - init_start_time
            logger.info(f"Chart service initialized in {init_time:.2f} seconds")
        return self._chart_service
        
    # Calendar service helpers
    @property
    def calendar_service(self):
        """Lazy loaded calendar service"""
        if self._calendar_service is None:
            # Only initialize the calendar service when it's first accessed
            init_start_time = time.time()
            logger.info("Lazy loading calendar service")
            self._calendar_service = EconomicCalendarService()
            init_time = time.time() - init_start_time
            logger.info(f"Calendar service initialized in {init_time:.2f} seconds")
        return self._calendar_service
        
    def _get_calendar_service(self):
        """Get the calendar service instance"""
        self.logger.info("Getting calendar service")
        return self.calendar_service

    async def _format_calendar_events(self, calendar_data):
        """Format the calendar data into a readable HTML message"""
        self.logger.info(f"Formatting calendar data with {len(calendar_data)} events")
        if not calendar_data:
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
                except:
                    return 0
            
            # Sort the events by time
            sorted_events = sorted(calendar_data, key=parse_time_for_sorting)
        except Exception as e:
            self.logger.error(f"Error sorting calendar events: {str(e)}")
            sorted_events = calendar_data
        
        # Format the message
        message = "<b>📅 Economic Calendar</b>\n\n"
        
        # Get current date
        current_date = datetime.now().strftime("%B %d, %Y")
        message += f"<b>Date:</b> {current_date}\n\n"
        
        # Add impact legend
        message += "<b>Impact:</b> 🔴 High   🟠 Medium   🟢 Low\n\n"
        
        # Group events by country
        events_by_country = {}
        for event in sorted_events:
            country = event.get('country', 'Unknown')
            if country not in events_by_country:
                events_by_country[country] = []
            events_by_country[country].append(event)
        
        # Format events by country
        for country, events in events_by_country.items():
            country_flag = CURRENCY_FLAG.get(country, '')
            message += f"<b>{country_flag} {country}</b>\n"
            
            for event in events:
                time = event.get('time', 'TBA')
                title = event.get('title', 'Unknown Event')
                impact = event.get('impact', 'Low')
                impact_emoji = {'High': '🔴', 'Medium': '🟠', 'Low': '🟢'}.get(impact, '🟢')
                
                message += f"{time} - {impact_emoji} {title}\n"
            
            message += "\n"  # Add extra newline between countries
        
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
                        
                        # Store signal reference for quick access - use the signals property indirectly
                        admin_str_id = str(admin_id)
                        user_signals = self.signals  # This will trigger lazy loading if needed
                        if admin_str_id not in user_signals:
                            user_signals[admin_str_id] = {}
                        
                        user_signals[admin_str_id][signal_id] = normalized_data
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

    async def _register_handlers(self, application):
        """Register event handlers for bot commands and callback queries"""
        # Use a lock to prevent multiple simultaneous registrations
        async with self._handler_registration_lock:
            # Check if handlers are already registered
            if self._handlers_registered:
                logger.info("Handlers already registered, skipping registration")
                return
            
            try:
                logger.info("Registering command handlers")
                
                # Set bot commands for menu
                self.commands = [
                    BotCommand("start", "Start the bot and get the welcome message"),
                    BotCommand("menu", "Show the main menu"),
                    BotCommand("help", "Get help with using the bot"),
                ]
                logger.info("Bot commands ready to be set")
                
                # Register command handlers immediately
                application.add_handler(CommandHandler("start", self.start_command))
                application.add_handler(CommandHandler("menu", self.show_main_menu))
                application.add_handler(CommandHandler("help", self.help_command))
                
                # Add admin commands
                application.add_handler(CommandHandler("set_subscription", self.set_subscription_command))
                application.add_handler(CommandHandler("set_payment_failed", self.set_payment_failed_command))
                
                logger.info("Essential command handlers registered")
                
                # Clear any previously registered handlers for callbacks
                if hasattr(application, 'handlers') and application.handlers:
                    # Find the existing callback query handlers
                    for group_id, handlers in application.handlers.items():
                        new_handlers = []
                        for handler in handlers:
                            # Keep only command handlers, remove callback query handlers
                            if not isinstance(handler, CallbackQueryHandler):
                                new_handlers.append(handler)
                        
                        # Replace with filtered handlers
                        application.handlers[group_id] = new_handlers
                
                # Register specific callback handlers first in a specific order
                # IMPORTANT: Order from most specific to least specific patterns
                
                # Signal with embedded parameters
                application.add_handler(CallbackQueryHandler(self.analysis_technical_callback, pattern="^analysis_technical_signal_.*$"))
                application.add_handler(CallbackQueryHandler(self.analysis_sentiment_callback, pattern="^analysis_sentiment_signal_.*$"))
                application.add_handler(CallbackQueryHandler(self.analysis_calendar_callback, pattern="^analysis_calendar_signal_.*$"))
                application.add_handler(CallbackQueryHandler(self.analyze_from_signal_callback, pattern="^analyze_from_signal_.*$"))
                application.add_handler(CallbackQueryHandler(self.signal_calendar_callback, pattern="^signal_flow_calendar_.*$"))
                application.add_handler(CallbackQueryHandler(self.instrument_signals_callback, pattern="^instrument_.*_signals$"))
                
                # Regular static callback patterns
                application.add_handler(CallbackQueryHandler(self.market_callback, pattern="^market_"))
                application.add_handler(CallbackQueryHandler(self.instrument_callback, pattern="^instrument_(?!.*_signals)"))
                
                # Main menu options
                application.add_handler(CallbackQueryHandler(self.menu_analyse_callback, pattern="^menu_analyse$"))
                application.add_handler(CallbackQueryHandler(self.menu_signals_callback, pattern="^menu_signals$"))
                application.add_handler(CallbackQueryHandler(self.signals_add_callback, pattern="^signals_add$"))
                application.add_handler(CallbackQueryHandler(self.signals_manage_callback, pattern="^signals_manage$"))
                
                # Analysis options
                application.add_handler(CallbackQueryHandler(self.analysis_technical_callback, pattern="^analysis_technical$"))
                application.add_handler(CallbackQueryHandler(self.analysis_sentiment_callback, pattern="^analysis_sentiment$"))
                application.add_handler(CallbackQueryHandler(self.analysis_calendar_callback, pattern="^analysis_calendar$"))
                application.add_handler(CallbackQueryHandler(self.signal_technical_callback, pattern="^signal_technical$"))
                application.add_handler(CallbackQueryHandler(self.signal_sentiment_callback, pattern="^signal_sentiment$"))
                application.add_handler(CallbackQueryHandler(self.signal_calendar_callback, pattern="^signal_calendar$"))
                
                # Navigation buttons
                application.add_handler(CallbackQueryHandler(self.back_market_callback, pattern="^back_market$"))
                application.add_handler(CallbackQueryHandler(self.back_instrument_callback, pattern="^back_instrument$"))
                application.add_handler(CallbackQueryHandler(self.back_signals_callback, pattern="^back_signals$"))
                application.add_handler(CallbackQueryHandler(self.back_menu_callback, pattern="^back_menu$"))
                application.add_handler(CallbackQueryHandler(self.back_to_signal_analysis_callback, pattern="^back_to_signal_analysis$"))
                application.add_handler(CallbackQueryHandler(self.back_to_signal_callback, pattern="^back_to_signal$"))
                application.add_handler(CallbackQueryHandler(self.analysis_callback, pattern="^back_analysis$"))
                
                # Catch-all handler for any other callbacks - MUST BE LAST
                application.add_handler(CallbackQueryHandler(self.button_callback))
                
                # Mark handlers as registered
                self._handlers_registered = True
                
                # Create background task for loading signals
                try:
                    self._background_tasks.append(asyncio.create_task(self._load_signals()))
                    logger.info("Created background task for loading signals")
                except Exception as e:
                    logger.error(f"Error creating background task for loading signals: {str(e)}")
                
                logger.info("Bot handlers registered successfully")
                
            except Exception as e:
                logger.error(f"Error setting up bot handlers: {str(e)}")
                logger.error(traceback.format_exc())

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
        """Show the main menu."""
        try:
            # Get the chat ID
            if update.effective_chat:
                chat_id = update.effective_chat.id
            elif update.callback_query and update.callback_query.message:
                chat_id = update.callback_query.message.chat_id
            else:
                logger.error("Could not determine chat ID in show_main_menu")
                return
                
            # Get user ID
            user_id = None
            if update.effective_user:
                user_id = update.effective_user.id
            elif update.callback_query and update.callback_query.from_user:
                user_id = update.callback_query.from_user.id
                
            logger.info(f"Showing main menu for user {user_id} in chat {chat_id}")
                
            # Check if the user has a subscription
            is_subscribed = False
            if user_id:
                try:
                    is_subscribed = await self.db.is_user_subscribed(user_id)
                    logger.info(f"User {user_id} subscription status: {is_subscribed}")
                except Exception as e:
                    logger.error(f"Error checking user subscription: {str(e)}")
                    logger.error(traceback.format_exc())
                    # Continue anyway and treat as not subscribed
            
            # Define the welcome text
            welcome_text = """
<b>🚀 Welcome to Sigmapips AI Bot! 🚀</b>

I can help you with:

📊 <b>Technical Analysis</b>
Get detailed analysis for any market including support/resistance levels, trend indicators, and key price levels.

📈 <b>Trading Signals</b>
Set up personalized trading signals for your favorite markets and timeframes.

What would you like to do today?
            """
            
            # Define simplified keyboard when user is not subscribed
            if not is_subscribed:
                # Show trial option
                keyboard = [
                    [InlineKeyboardButton("🔍 Analysis", callback_data="menu_analyse")],
                    [InlineKeyboardButton("📊 Trading Signals", callback_data="menu_signals")],
                    [InlineKeyboardButton("🔔 Start 14-Day Free Trial", url="https://buy.stripe.com/3cs3eF9Hu9256NW9AA")]
                ]
            else:
                # Full menu for subscribed users
                keyboard = [
                    [InlineKeyboardButton("🔍 Analysis", callback_data="menu_analyse")],
                    [InlineKeyboardButton("📊 Trading Signals", callback_data="menu_signals")],
                    [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
                ]
            
            # Define the reply markup
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Handle the case where update comes from a callback query
            if update.callback_query:
                query = update.callback_query
                
                # Try to get a GIF for welcome message
                gif_url = "https://media.giphy.com/media/8lKyuiFprZaj2/giphy.gif"
                
                # Check if we should skip showing GIF (e.g., during edit)
                if skip_gif:
                    # Just update the text and keyboard
                    try:
                        await query.edit_message_text(
                            text=welcome_text,
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML
                        )
                        logger.info("Main menu updated via callback (no GIF)")
                    except Exception as e:
                        logger.error(f"Error updating main menu text: {str(e)}")
                        
                        # Try to send a new message if editing fails
                        await query.message.reply_text(
                            text=welcome_text,
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML
                        )
                        logger.info("Main menu sent as new message after edit failure")
                else:
                    # Use the helper function to update with GIF
                    success = await gif_utils.update_message_with_gif(
                        query=query,
                        gif_url=gif_url,
                        text=welcome_text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.HTML
                    )
                    
                    if not success:
                        # Fallback to text-only update
                        try:
                            await query.edit_message_text(
                                text=welcome_text,
                                reply_markup=reply_markup,
                                parse_mode=ParseMode.HTML
                            )
                            logger.info("Main menu updated with text only (GIF failed)")
                        except Exception as e:
                            logger.error(f"Error in fallback text update: {str(e)}")
                            
                            # Last resort: send a new message
                            await query.message.reply_text(
                                text=welcome_text,
                                reply_markup=reply_markup,
                                parse_mode=ParseMode.HTML
                            )
                            logger.info("Main menu sent as new message after all fallbacks")
            else:
                # Handle the case of a command (not a callback)
                if skip_gif:
                    # Text-only response
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=welcome_text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.HTML
                    )
                    logger.info("Main menu sent via command (no GIF)")
                else:
                    # Try to send with GIF
                    try:
                        # Get a GIF URL for the welcome message
                        gif_url = "https://media.giphy.com/media/8lKyuiFprZaj2/giphy.gif"
                        
                        # Send the GIF with caption
                        await self.bot.send_animation(
                            chat_id=chat_id,
                            animation=gif_url,
                            caption=welcome_text,
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML
                        )
                        logger.info("Main menu sent with GIF via command")
                    except Exception as e:
                        logger.error(f"Error sending menu with GIF: {str(e)}")
                        
                        # Fallback to text-only
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=welcome_text,
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML
                        )
                        logger.info("Main menu sent with text only after GIF failure")
                        
        except Exception as e:
            logger.error(f"Error in show_main_menu: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Try to recover by sending a simple message
            try:
                await update.effective_chat.send_message(
                    "Sorry, there was an error showing the menu. Please try the /menu command again."
                )
            except Exception:
                # If all else fails, just log the error
                logger.error("Could not send recovery message in show_main_menu")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Display help information for the bot."""
        try:
            # Create a keyboard for help topics
            keyboard = [
                [InlineKeyboardButton("📈 How to Use", callback_data="help_usage")],
                [InlineKeyboardButton("💲 Subscription", callback_data="help_subscription")],
                [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                text="<b>SigmaPips Help</b>\n\nSelect a help topic:",
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error in help_command: {str(e)}")
            # Send a new message as fallback
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Select your analysis type:",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            )
            
        return CHOOSE_ANALYSIS

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
        
        logger.info(f"back_instrument_callback aangeroepen met data: {query.data}")
        
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

    async def run(self):
        """Run the bot with polling"""
        try:
            # Always use polling mode, regardless of webhook URL
            logger.info("Starting bot with long polling mode")
            
            # Start the bot without blocking
            await self.application.initialize()
            await self.application.start()
            
            # Re-register handlers to ensure they're in the correct order
            await self._register_handlers(self.application)
            logger.info("Handlers registered after application initialization")
            
            # Set the bot commands
            try:
                logger.info("Setting bot commands...")
                await self.bot.set_my_commands(self.commands)
                logger.info("Bot commands set successfully")
            except Exception as e:
                logger.error(f"Error setting bot commands: {str(e)}")
            
            # Start polling
            logger.info("Starting polling for updates...")
            await self.application.updater.start_polling()
            self.polling_started = True
            logger.info("Polling started successfully")
            
            # Start services only if not using lazy initialization
            if not getattr(self, 'lazy_init', False):
                await self.initialize_services()
            else:
                logger.info("Skipping services initialization due to lazy_init=True")
            
            # Keep-alive task to prevent the application from exiting
            async def keepalive():
                """Keep the application active to prevent Railway from timing out"""
                while True:
                    logger.debug("Keepalive ping")
                    await asyncio.sleep(60)
            
            # Start the keepalive task
            self._background_tasks.append(asyncio.create_task(keepalive()))
            
            # Wait for the application to stop
            await self.application.idle()
            
            return None
        except Exception as e:
            logger.error(f"Error running bot: {str(e)}")
            logger.error(traceback.format_exc())
            raise
            
    async def analysis_technical_callback(self, update: Update, context=None) -> int:
        """Handle technical analysis selection."""
        try:
            query = update.callback_query
            await query.answer()
            
            # Extract additional data from the callback if available
            callback_data = query.data
            instrument_from_callback = None
            timeframe_from_callback = None
            
            # Check if callback has instrument and timeframe info
            if callback_data.startswith("analysis_technical_signal_"):
                parts = callback_data.replace("analysis_technical_signal_", "").split("_")
                if len(parts) >= 2:
                    instrument_from_callback = parts[0]
                    timeframe_from_callback = parts[1]
            
            if context and hasattr(context, 'user_data'):
                # Use callback data if available, otherwise user context
                if instrument_from_callback:
                    context.user_data['instrument'] = instrument_from_callback
                    logger.info(f"Setting instrument from callback: {instrument_from_callback}")
                
                if timeframe_from_callback:
                    context.user_data['timeframe'] = timeframe_from_callback
                    logger.info(f"Setting timeframe from callback: {timeframe_from_callback}")
                
                # If we have both instrument and timeframe, skip to loading analysis
                if 'instrument' in context.user_data and 'timeframe' in context.user_data:
                    instrument = context.user_data['instrument']
                    timeframe = context.user_data['timeframe']
                    
                    # Show loading message
                    loading_msg = await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"⏳ <b>Analyzing {instrument} ({timeframe})</b>\n\nPlease wait while I fetch the latest data...",
                        parse_mode=ParseMode.HTML
                    )
                    context.user_data['loading_message'] = loading_msg
                    
                    try:
                        # Get chart image
                        chart_service = self.chart_service
                        chart_bytes = await chart_service.get_chart(instrument, timeframe)
                        
                        # Get technical analysis text
                        analysis_text = await chart_service.get_technical_analysis(instrument, timeframe)
                        
                        # Send the chart with analysis
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=chart_bytes,
                            caption=analysis_text,
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("⬅️ Back to Analysis", callback_data="back_to_analysis")],
                                [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
                            ])
                        )
                        
                        # Delete loading message
                        if 'loading_message' in context.user_data:
                            await context.user_data['loading_message'].delete()
                            del context.user_data['loading_message']
                        
                        return SHOW_RESULT
                        
                    except Exception as e:
                        logger.error(f"Error getting technical analysis: {str(e)}")
                        logger.error(traceback.format_exc())
                        
                        # Delete loading message if it exists
                        if 'loading_message' in context.user_data:
                            await context.user_data['loading_message'].delete()
                            del context.user_data['loading_message']
                        
                        # Send error message
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"⚠️ <b>Error</b>\n\nSorry, I couldn't get the technical analysis for {instrument}. Please try again later.",
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("⬅️ Back to Analysis", callback_data="back_to_analysis")],
                                [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
                            ])
                        )
                        return SHOW_RESULT
                
                # If coming from signal flow or regular flow
                if context.user_data.get('from_signal', False):
                    # Show market selection for signals
                    market_keyboard = [
                        [InlineKeyboardButton("💱 Forex", callback_data="market_forex_signals")],
                        [InlineKeyboardButton("💰 Crypto", callback_data="market_crypto_signals")],
                        [InlineKeyboardButton("📈 Indices", callback_data="market_indices_signals")],
                        [InlineKeyboardButton("🛢️ Commodities", callback_data="market_commodities_signals")],
                        [InlineKeyboardButton("⬅️ Back to Signals", callback_data="back_signals")]
                    ]
                else:
                    # Show regular market selection
                    market_keyboard = [
                        [InlineKeyboardButton("💱 Forex", callback_data="market_forex")],
                        [InlineKeyboardButton("💰 Crypto", callback_data="market_crypto")],
                        [InlineKeyboardButton("📈 Indices", callback_data="market_indices")],
                        [InlineKeyboardButton("🛢️ Commodities", callback_data="market_commodities")],
                        [InlineKeyboardButton("⬅️ Back to Analysis", callback_data="back_to_analysis")]
                    ]
                
                await query.edit_message_text(
                    text="Select the market type:",
                    reply_markup=InlineKeyboardMarkup(market_keyboard)
                )
                
                # Store analysis type in context
                context.user_data['analysis_type'] = 'technical'
                
                return CHOOSE_MARKET
                
            else:
                logger.error("No context available in technical analysis callback")
                await self.update_message(
                    query, 
                    "❌ Error: Could not process your request. Please try again by typing /menu.",
                    keyboard=[[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]]
                )
                return MENU
                
        except Exception as e:
            logger.error(f"Error in analysis_technical_callback: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Fallback response
            try:
                if update and update.effective_chat:
                    await update.effective_chat.send_message(
                        "Sorry, there was an error processing your request. Please try again.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]])
                    )
            except Exception:
                logger.error("Failed to send fallback message in analysis_technical_callback")
                
            return MENU

    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Show the main menu."""
        try:
            logger.info("Menu command called, showing main menu")
            
            # Reset any context flags that might be set
            if context and hasattr(context, 'user_data'):
                # Clear all specific state flags but keep login information
                keys_to_preserve = ['user_id', 'username', 'first_name', 'last_name']
                preserved_data = {k: context.user_data[k] for k in keys_to_preserve if k in context.user_data}
                
                # Clear and restore preserved data
                context.user_data.clear()
                context.user_data.update(preserved_data)
                
                logger.info(f"Reset context in menu_command, preserving: {preserved_data.keys()}")
            
            # Show the main menu
            await self.show_main_menu(update, context)
            
        except Exception as e:
            logger.error(f"Error in menu_command: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Try to recover by sending a simple message with the menu
            try:
                keyboard = [
                    [InlineKeyboardButton("🔍 Analysis", callback_data="menu_analyse")],
                    [InlineKeyboardButton("📊 Trading Signals", callback_data="menu_signals")]
                ]
                
                await update.effective_chat.send_message(
                    "Welcome to Sigmapips AI Bot! What would you like to do?",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                logger.info("Sent fallback menu after error")
            except Exception:
                logger.error("Could not send fallback menu in menu_command")
                
    async def analysis_callback(self, update: Update, context=None) -> int:
        """Handle back to analysis button press."""
        try:
            query = update.callback_query
            await query.answer()
            
            # Prepare analysis keyboard
            analysis_keyboard = [
                [InlineKeyboardButton("📈 Technical Analysis", callback_data="analysis_technical")],
                [InlineKeyboardButton("🧠 Market Sentiment", callback_data="analysis_sentiment")],
                [InlineKeyboardButton("📅 Economic Calendar", callback_data="analysis_calendar")],
                [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
            ]
            
            # Edit message to show analysis options
            await query.edit_message_text(
                text="<b>Analysis Options</b>\n\nSelect the type of analysis you want to see:",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(analysis_keyboard)
            )
            
            return CHOOSE_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error in analysis_callback: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Fallback response
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Select your analysis type:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(analysis_keyboard)
                )
            except Exception:
                logger.error("Failed to send fallback message in analysis_callback")
            
            return CHOOSE_ANALYSIS

    async def _process_callback_query_with_retry(self, update_data, max_retries=3):
        """
        Process a callback query with retries for robustness.
        Direct processing of callback queries to avoid routing issues.
        
        Args:
            update_data: The raw update data from webhook
            max_retries: Maximum number of retry attempts
        """
        try:
            # Extract callback data
            callback_data = update_data.get('callback_query', {}).get('data', '')
            
            if not callback_data:
                logger.warning("Empty callback_data in _process_callback_query_with_retry")
                return
                
            # Create Update object
            update = Update.de_json(update_data, self.bot)
            
            # Create an empty context for compatibility
            context = None
            
            # Process with retries
            retry_count = 0
            last_error = None
            
            while retry_count < max_retries:
                try:
                    logger.info(f"Processing callback: {callback_data} (attempt {retry_count+1}/{max_retries})")
                    
                    # Direct dispatcher based on callback data
                    if callback_data == "menu_analyse":
                        await self.menu_analyse_callback(update, context)
                        break
                    elif callback_data == "menu_signals":
                        await self.menu_signals_callback(update, context)
                        break
                    elif callback_data == "signals_add":
                        await self.signals_add_callback(update, context)
                        break
                    elif callback_data == "signals_manage":
                        await self.signals_manage_callback(update, context)
                        break
                    elif callback_data.startswith("market_"):
                        await self.market_callback(update, context)
                        break
                    elif callback_data.startswith("instrument_") and "_signals" in callback_data:
                        await self.instrument_signals_callback(update, context)
                        break
                    elif callback_data.startswith("instrument_"):
                        await self.instrument_callback(update, context)
                        break
                    elif callback_data == "analysis_technical":
                        await self.analysis_technical_callback(update, context)
                        break
                    elif callback_data == "analysis_sentiment":
                        await self.analysis_sentiment_callback(update, context)
                        break
                    elif callback_data == "analysis_calendar":
                        await self.analysis_calendar_callback(update, context)
                        break
                    elif callback_data.startswith("analysis_technical_signal_"):
                        await self.analysis_technical_callback(update, context)
                        break
                    elif callback_data.startswith("analysis_sentiment_signal_"):
                        await self.analysis_sentiment_callback(update, context)
                        break
                    elif callback_data.startswith("analysis_calendar_signal_"):
                        await self.analysis_calendar_callback(update, context)
                        break
                    elif callback_data == "signal_technical":
                        await self.signal_technical_callback(update, context)
                        break
                    elif callback_data == "signal_sentiment":
                        await self.signal_sentiment_callback(update, context)
                        break
                    elif callback_data == "signal_calendar":
                        await self.signal_calendar_callback(update, context)
                        break
                    elif callback_data.startswith("signal_flow_calendar_"):
                        await self.signal_calendar_callback(update, context)
                        break
                    elif callback_data == "back_menu":
                        await self.back_menu_callback(update, context)
                        break
                    elif callback_data == "back_analysis":
                        await self.analysis_callback(update, context)
                        break
                    elif callback_data == "back_signals":
                        await self.back_signals_callback(update, context)
                        break
                    elif callback_data == "back_market":
                        await self.back_market_callback(update, context)
                        break
                    elif callback_data == "back_instrument":
                        await self.back_instrument_callback(update, context)
                        break
                    elif callback_data == "back_to_signal_analysis":
                        await self.back_to_signal_analysis_callback(update, context)
                        break
                    elif callback_data == "back_to_signal":
                        await self.back_to_signal_callback(update, context)
                        break
                    elif callback_data.startswith("analyze_from_signal_"):
                        await self.analyze_from_signal_callback(update, context)
                        break
                    else:
                        logger.warning(f"Unknown callback data in retry processor: {callback_data}")
                        # Try fallback to general button handler
                        if hasattr(self, 'button_callback'):
                            await self.button_callback(update, context)
                        break
                        
                except Exception as e:
                    retry_count += 1
                    last_error = e
                    logger.error(f"Error in retry {retry_count}: {str(e)}")
                    await asyncio.sleep(0.5)  # Short delay before retry
            
            if retry_count >= max_retries:
                logger.error(f"Max retries exceeded for callback: {callback_data}")
                if last_error:
                    logger.error(f"Last error: {str(last_error)}")
                
        except Exception as e:
            logger.error(f"Error in _process_callback_query_with_retry: {str(e)}")
            logger.error(traceback.format_exc())
            
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """General callback handler for button presses that aren't handled by specific callbacks."""
        try:
            query = update.callback_query
            callback_data = query.data
            
            logger.info(f"Generic button callback with data: {callback_data}")
            await query.answer()
            
            # Redirect to specific handlers based on callback data
            if callback_data == "menu_analyse":
                return await self.menu_analyse_callback(update, context)
            elif callback_data == "menu_signals":
                return await self.menu_signals_callback(update, context)
            elif callback_data == "signals_add":
                return await self.signals_add_callback(update, context)
            elif callback_data == "signals_manage":
                return await self.signals_manage_callback(update, context)
            elif callback_data == "back_menu":
                return await self.back_menu_callback(update, context)
            elif callback_data == "back_signals":
                return await self.back_signals_callback(update, context)
            elif callback_data == "back_instrument":
                return await self.back_instrument_callback(update, context)
            elif callback_data == "analysis_technical":
                return await self.analysis_technical_callback(update, context)
            elif callback_data.startswith("analysis_technical_signal_"):
                return await self.analysis_technical_callback(update, context)
            # Add other callback data patterns as needed
            else:
                logger.warning(f"Unknown callback data: {callback_data}")
                await query.edit_message_text(
                    text="Sorry, I don't understand that command. Please try using the main menu.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")
                    ]])
                )
                return MENU
                
        except Exception as e:
            logger.error(f"Error in button_callback: {str(e)}")
            logger.error(traceback.format_exc())
            try:
                await update.effective_chat.send_message(
                    "Sorry, there was an error processing your request. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")
                    ]])
                )
            except Exception:
                logger.error("Could not send error message in button_callback")
            return MENU
            
    async def _load_signals(self):
        """Load signals from the database in the background to avoid startup delays.
        
        This method is called during initialization as a background task.
        """
        try:
            logger.info("Loading signals in background task...")
            
            # Add a slight delay to avoid overloading during startup
            await asyncio.sleep(2.0)
            
            if not hasattr(self, 'db') or not self.db:
                logger.warning("Database not initialized, cannot load signals")
                return
                
            # Load active signal subscriptions
            try:
                logger.info("Loading active signal subscriptions from database...")
                response = self.db.supabase.table('signal_subscriptions').select('*').execute()
                
                if response and hasattr(response, 'data'):
                    self._signal_subscriptions = response.data
                    logger.info(f"Loaded {len(self._signal_subscriptions)} signal subscriptions")
                else:
                    self._signal_subscriptions = []
                    logger.warning("No signal subscriptions found or invalid response")
            except Exception as e:
                logger.error(f"Error loading signal subscriptions: {str(e)}")
                self._signal_subscriptions = []
            
            # Load any active signals
            try:
                logger.info("Loading active signals from database...")
                response = self.db.supabase.table('active_signals').select('*').execute()
                
                if response and hasattr(response, 'data'):
                    self._active_signals = response.data
                    logger.info(f"Loaded {len(self._active_signals)} active signals")
                else:
                    self._active_signals = []
                    logger.warning("No active signals found or invalid response")
            except Exception as e:
                logger.error(f"Error loading active signals: {str(e)}")
                self._active_signals = []
                
            # Update the signals_loaded flag
            self._signals_loaded = True
            logger.info("Signal loading completed successfully")
            
        except Exception as e:
            logger.error(f"Error in _load_signals: {str(e)}")
            logger.error(traceback.format_exc())
            
    async def back_market_callback(self, update: Update, context=None) -> int:
        """Handle back_market button press to return to market selection."""
        try:
            query = update.callback_query
            await query.answer()
            
            # Determine if we're in signals or analysis flow
            is_signals_context = context.user_data.get('is_signals_context', False) if context and hasattr(context, 'user_data') else False
            
            # Prepare keyboard based on whether we're in signals or analysis flow
            if is_signals_context:
                # Signal flow keyboard
                keyboard = [
                    [InlineKeyboardButton("📊 Add Signal", callback_data="signals_add")],
                    [InlineKeyboardButton("⚙️ Manage Signals", callback_data="signals_manage")],
                    [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
                ]
                text = "<b>📈 Signal Management</b>\n\nManage your trading signals"
            else:
                # Analysis flow keyboard
                keyboard = [
                    [InlineKeyboardButton("📈 Technical Analysis", callback_data="analysis_technical")],
                    [InlineKeyboardButton("🧠 Market Sentiment", callback_data="analysis_sentiment")],
                    [InlineKeyboardButton("📅 Economic Calendar", callback_data="analysis_calendar")],
                    [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
                ]
                text = "<b>Analysis Options</b>\n\nSelect the type of analysis you want to see:"
            
            # Update the message
            await query.edit_message_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # Return to the appropriate state
            return SIGNALS if is_signals_context else CHOOSE_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error in back_market_callback: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Try to recover by sending a simple message
            try:
                keyboard = [
                    [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
                ]
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Sorry, there was an error. Please try using the menu again.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception:
                logger.error("Could not send recovery message in back_market_callback")
            
            return MENU
