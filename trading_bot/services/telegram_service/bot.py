import os
import json
import asyncio
import traceback
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
import logging
import copy
import re
import time
import random
import base64
import socket
import sys
import tempfile

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
from trading_bot.services.calendar_service.calendar import EconomicCalendarService
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
from trading_bot.services.calendar_service.tradingview_calendar import TradingViewCalendarService
from trading_bot.services.calendar_service.__init__ import debug_tradingview_api, get_all_calendar_events

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
CALLBACK_SIGNAL_TECHNICAL = "signal_technical"
CALLBACK_SIGNAL_SENTIMENT = "signal_sentiment"
CALLBACK_SIGNAL_CALENDAR = "signal_calendar"

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
INSTRUMENT_ANALYSIS = 12  # Add this line for technical analysis flow

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
            
            # Initialize the bot
            self.bot = Bot(token=self.bot_token)
        
            # Initialize the application
            self.application = Application.builder().bot(self.bot).build()
        
            # Register the handlers
            self._register_handlers(self.application)
            
            # Initialize signals dictionary but don't load them yet (will be done in initialize_services)
            self.user_signals = {}
        
            logger.info("Telegram service initialized")
            
            # Keep track of processed updates
            self.processed_updates = set()
            
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            raise

        # --- Calendar Service Initialization ---
        self._calendar_service = None
        self._calendar_service_instance = None # Store the specific instance (e.g., TradingView)

        if not lazy_init:
            self._initialize_services()
        else:
            self.logger.info("Lazy initialization enabled. Services will be loaded on demand.")

    def _initialize_services(self):
        """Initialize external services."""
        self.logger.info("Initializing external services...")
        try:
            # Initialiseer andere services...
            self.chart = ChartService()
            self.sentiment = MarketSentimentService()
            self.logger.info("Chart and Sentiment services initialized.")

            # --- Initialize Calendar Service ---
            try:
                 self.logger.info("Attempting to initialize TradingViewCalendarService...")
                 # Remove the direct instantiation here, let EconomicCalendarService handle it if needed
                 # self._calendar_service_instance = TradingViewCalendarService() 
                 self.logger.info("TradingViewCalendarService instance creation attempt logged (now handled within ECS).")
                 # Log the module path of the EconomicCalendarService class being used
                 self.logger.info(f"Attempting to use EconomicCalendarService from: {EconomicCalendarService.__module__}")
                 # Create the main EconomicCalendarService wrapper, REMOVING the instance argument
                 self._calendar_service = EconomicCalendarService() # REMOVED calendar_service_instance
                 self.logger.info("EconomicCalendarService initialized (potentially with internal TradingView).")
            except ImportError as e:
                 self.logger.error(f"Failed to import or initialize TradingViewCalendarService dependencies: {e}")
                 self.logger.warning("Falling back to basic EconomicCalendarService.")
                 # Initialize without the instance, REMOVING the instance argument
                 # Log the module path of the EconomicCalendarService class being used in fallback
                 self.logger.info(f"Attempting to use fallback EconomicCalendarService from: {EconomicCalendarService.__module__}")
                 self._calendar_service = EconomicCalendarService() # REMOVED calendar_service_instance
            except Exception as e:
                 self.logger.error(f"An unexpected error occurred during calendar service initialization: {e}")
                 self.logger.error(traceback.format_exc())
                 self.logger.warning("Falling back to basic EconomicCalendarService due to error.")
                 # Log the module path of the EconomicCalendarService class being used in fallback
                 self.logger.info(f"Attempting to use fallback EconomicCalendarService from: {EconomicCalendarService.__module__}")
                 self._calendar_service = EconomicCalendarService() # REMOVED calendar_service_instance

            # ... (rest of service initializations)

        except Exception as e:
            self.logger.error(f"Failed to initialize one or more services: {str(e)}")
            self.logger.error(traceback.format_exc())
            # Optionally decide how to handle this - e.g., set services to None or raise

    @property
    def calendar_service(self):
        """Lazy load calendar service if not initialized."""
        if self._calendar_service is None:
            self.logger.info("Lazy loading calendar service...")
            self._initialize_services() # Ensure all services are initialized
            if self._calendar_service is None: # If initialization failed
                 self.logger.error("Failed to lazy-load calendar service!")
                 # Return a temporary mock or raise an error
                 # Log the module path of the EconomicCalendarService class being used in lazy load fallback
                 self.logger.info(f"Attempting to use lazy-load fallback EconomicCalendarService from: {EconomicCalendarService.__module__}")
                 # REMOVED calendar_service_instance=None - let the default init handle it
                 return EconomicCalendarService() 
        return self._calendar_service

    # Calendar service helpers
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
                    'timeframe': interval,
                    'sentiment_verdict': signal_data.get('sentiment_verdict') # Copy verdict here
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
                take_profit = signal_data.get('take_profit') # Default TP
                timeframe = signal_data.get('timeframe', '1h')
                
                # Create normalized signal data
                normalized_data = {
                    'instrument': instrument,
                    'direction': direction,
                    'entry': entry,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit, # Store default TP
                    'timeframe': timeframe,
                    'sentiment_verdict': signal_data.get('sentiment_verdict') # Also copy verdict here
                }

                # <<< FIX: Explicitly add tp1, tp2, tp3 if they exist in the original signal data >>>
                if 'tp1' in signal_data:
                    normalized_data['tp1'] = signal_data['tp1']
                elif take_profit: # Fallback to take_profit if tp1 missing but take_profit exists
                     normalized_data['tp1'] = take_profit
                if 'tp2' in signal_data:
                    normalized_data['tp2'] = signal_data['tp2']
                if 'tp3' in signal_data:
                    normalized_data['tp3'] = signal_data['tp3']
                # <<< END FIX >>>
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
            logger.info(f"[process_signal] Before _format_signal_message, normalized_data: {json.dumps(normalized_data)}")
            message = self._format_signal_message(normalized_data)
            logger.info(f"[process_signal] After _format_signal_message, message: {message[:100]}...")
            
            # Determine market type for the instrument
            market_type = _detect_market(instrument)
            
            # Store the full signal data for reference
            normalized_data['id'] = signal_id
            normalized_data['timestamp'] = datetime.now(timezone.utc).isoformat() # Use imported class directly
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
            # <<< DEBUG LOGGING START >>>
            logger.info(f"[_format_signal_message] Received signal_data: {json.dumps(signal_data)}")
            # <<< DEBUG LOGGING END >>>

            # Extract fields from signal data
            instrument = signal_data.get('instrument', 'Unknown')
            direction = signal_data.get('direction', 'Unknown')
            entry = signal_data.get('entry', 'Unknown')
            stop_loss = signal_data.get('stop_loss')
            take_profit = signal_data.get('take_profit')
            timeframe = signal_data.get('timeframe', '1h')
            tp1 = signal_data.get('tp1', take_profit)
            tp2 = signal_data.get('tp2')
            tp3 = signal_data.get('tp3')
            direction_emoji = "🟢" if direction.upper() == "BUY" else "🔴"
            
            # <<< DEBUG LOGGING START >>>
            logger.info(f"[_format_signal_message] Extracted TPs: tp1='{tp1}', tp2='{tp2}', tp3='{tp3}'")
            # <<< DEBUG LOGGING END >>>

            # --- Basic message structure --- 
            message = f"<b>🎯 New Trading Signal 🎯</b>\n\n"
            message += f"<b>Instrument:</b> {instrument}\n"
            message += f"<b>Action:</b> {direction.upper()} {direction_emoji}\n\n"
            message += f"<b>Entry Price:</b> {entry}\n"
            if stop_loss:
                message += f"<b>Stop Loss:</b> {stop_loss} 🔴\n"
            if tp1:
                message += f"<b>Take Profit 1:</b> {tp1} 🎯\n"
            if tp2:
                message += f"<b>Take Profit 2:</b> {tp2} 🎯\n"
            if tp3:
                message += f"<b>Take Profit 3:</b> {tp3} 🎯\n"
            message += f"\n{timeframe}\n"
            message += f"{signal_data.get('strategy', 'TradingView Signal')}\n\n"
            message += "————————————————————\n\n"
            message += "<b>Risk Management:</b>\n\n"
            message += "• Position size: 1-2% max\n"
            message += "• Use proper stop loss\n"
            message += "• Follow your trading plan\n\n"
            message += "————————————————————\n\n"
            message += "<b>🤖 SigmaPips AI Verdict:</b>\n\n"
            
            # --- Construct AI Verdict --- 
            # Directly add the sentiment_verdict if it exists, with an appropriate emoji.
            sentiment_verdict = signal_data.get('sentiment_verdict')
            verdict_emoji = ""
            if sentiment_verdict:
                logger.info(f"[_format_signal_message] Adding sentiment verdict: {sentiment_verdict}")
                if "aligns" in sentiment_verdict.lower():
                    verdict_emoji = "✅ "
                elif "does not align" in sentiment_verdict.lower() or "contradicts" in sentiment_verdict.lower():
                    verdict_emoji = "❌ "
                # Add other conditions for neutral etc. if needed, otherwise no emoji
                
                message += f"{verdict_emoji}{sentiment_verdict}"
            else:
                logger.warning("[_format_signal_message] No sentiment_verdict found in signal_data.")
                message += "AI analysis could not be completed." # Fallback message

            # <<< UPDATED DISCLAIMER >>>
            message += f"\n\n⚠️ <b>Disclaimer:</b> <i>Trading involves substantial risk of loss and is not suitable for all investors. Past performance is not indicative of future results.</i>"
            # <<< END UPDATED DISCLAIMER >>>
            
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
            
            # Add handler for market_signals pattern
            application.add_handler(CallbackQueryHandler(self.market_signals_callback, pattern="^market_.*_signals$"))
            
            # Add back to signals markets button handler
            application.add_handler(CallbackQueryHandler(self.signals_add_callback, pattern="^back_to_signals_markets$"))
            
            # Add handler for back from instruments signals to market selection
            application.add_handler(CallbackQueryHandler(self.back_to_signals_markets_callback, pattern="^back_to_instruments_signals$"))
            
            # Add handler for back buttons
            application.add_handler(CallbackQueryHandler(self.back_market_callback, pattern="^back_market$"))
            application.add_handler(CallbackQueryHandler(self.back_instrument_callback, pattern="^back_instrument$"))
            application.add_handler(CallbackQueryHandler(self.back_signals_callback, pattern="^back_signals$"))
            application.add_handler(CallbackQueryHandler(self.back_menu_callback, pattern="^back_menu$"))
            
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
            
            # Ensure back_instrument is properly handled
            application.add_handler(CallbackQueryHandler(self.back_instrument_callback, pattern="^back_instrument$"))
            
            # Catch-all handler for any other callbacks
            # application.add_handler(CallbackQueryHandler(self.button_callback)) # REMOVED
            
            # Don't load signals here - it will be done in initialize_services
            # self._load_signals()
            
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

        # <<< ADDED LINE: Explicitly set context for analysis flow >>>
        if context and hasattr(context, 'user_data'):
            context.user_data.clear() # Clear previous context first
            context.user_data['is_signals_context'] = False
            logger.info(f"Set analysis flow context: {context.user_data}")
        # <<< END ADDED LINE >>>

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
            
            # Show analysis directly for this instrument
            return await self.show_calendar_analysis(update, context, instrument=instrument)
        
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
            # Log the full context for debugging
            logger.info(f"Current context user_data: {context.user_data}")
        
        # Get the instrument from context with fallbacks
        instrument = None
        timeframe = None
        if context and hasattr(context, 'user_data'):
            # Try to get the instrument from different possible context locations
            instrument = context.user_data.get('instrument')
            
            # If instrument is not found, try to get from backup fields
            if not instrument:
                instrument = context.user_data.get('signal_instrument_backup')
                logger.info(f"Using backup instrument from context: {instrument}")
            
            # Still not found, check original signal for instrument mention
            if not instrument and 'original_signal_message' in context.user_data:
                # Extract instrument from original signal message if possible
                original_message = context.user_data.get('original_signal_message', '')
                match = re.search(r'Instrument:\s*([A-Za-z0-9]+)', original_message)
                if match:
                    instrument = match.group(1)
                    logger.info(f"Extracted instrument from original signal message: {instrument}")
                    # Save it back to context for future use
                    context.user_data['instrument'] = instrument
            
            # Try to get timeframe from context
            timeframe = context.user_data.get('signal_timeframe')
            if not timeframe:
                timeframe = context.user_data.get('signal_timeframe_backup')
                logger.info(f"Using backup timeframe from context: {timeframe}")
            
            # Debug log for instrument
            logger.info(f"Final instrument selected: {instrument}, timeframe: {timeframe}")
        
        if instrument:
            # Set flag to indicate we're in signal flow
            if context and hasattr(context, 'user_data'):
                context.user_data['from_signal'] = True
                context.user_data['instrument'] = instrument  # Ensure instrument is stored in the primary location
                logger.info("Set from_signal flag to True")
            
            # Try to show loading animation first
            loading_gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
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
            
            # Show technical analysis for this instrument with timeframe if available
            return await self.show_technical_analysis(update, context, instrument=instrument, timeframe=timeframe)
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
        
        # Add detailed debug logging
        logger.info(f"signal_sentiment_callback called with query data: {query.data}")
        
        # Save analysis type in context
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'sentiment'
            # Log the full context for debugging
            logger.info(f"Current context user_data: {context.user_data}")
        
        # Get the instrument from context with fallbacks
        instrument = None
        if context and hasattr(context, 'user_data'):
            # Try to get the instrument from different possible context locations
            instrument = context.user_data.get('instrument')
            
            # If instrument is not found, try to get from backup fields
            if not instrument:
                instrument = context.user_data.get('signal_instrument_backup')
                logger.info(f"Using backup instrument from context: {instrument}")
            
            # Still not found, check original signal for instrument mention
            if not instrument and 'original_signal_message' in context.user_data:
                # Extract instrument from original signal message if possible
                original_message = context.user_data.get('original_signal_message', '')
                match = re.search(r'Instrument:\s*([A-Za-z0-9]+)', original_message)
                if match:
                    instrument = match.group(1)
                    logger.info(f"Extracted instrument from original signal message: {instrument}")
                    # Save it back to context for future use
                    context.user_data['instrument'] = instrument
            
            # Debug log for instrument
            logger.info(f"Final instrument selected: {instrument}")
        
        if instrument:
            # Set flag to indicate we're in signal flow
            if context and hasattr(context, 'user_data'):
                context.user_data['from_signal'] = True
                context.user_data['instrument'] = instrument  # Ensure instrument is stored in the primary location
                logger.info("Set from_signal flag to True")
            
            # Try to show loading animation first
            loading_gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
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
        logger.info(f"signal_calendar_callback called with query data: {query.data}")
        
        # Save analysis type in context
        if context and hasattr(context, 'user_data'):
            context.user_data['analysis_type'] = 'calendar'
            # Log the full context for debugging
            logger.info(f"Current context user_data: {context.user_data}")
        
        # Get the instrument from context with fallbacks
        instrument = None
        if context and hasattr(context, 'user_data'):
            # Try to get the instrument from different possible context locations
            instrument = context.user_data.get('instrument')
            
            # If instrument is not found, try to get from backup fields
            if not instrument:
                instrument = context.user_data.get('signal_instrument_backup')
                logger.info(f"Using backup instrument from context: {instrument}")
            
            # Still not found, check original signal for instrument mention
            if not instrument and 'original_signal_message' in context.user_data:
                # Extract instrument from original signal message if possible
                original_message = context.user_data.get('original_signal_message', '')
                match = re.search(r'Instrument:\s*([A-Za-z0-9]+)', original_message)
                if match:
                    instrument = match.group(1)
                    logger.info(f"Extracted instrument from original signal message: {instrument}")
                    # Save it back to context for future use
                    context.user_data['instrument'] = instrument
            
            # Debug log for instrument
            logger.info(f"Final instrument selected: {instrument}")
        
        if instrument:
            # Set flag to indicate we're in signal flow
            if context and hasattr(context, 'user_data'):
                context.user_data['from_signal'] = True
                context.user_data['instrument'] = instrument  # Ensure instrument is stored in the primary location
                logger.info("Set from_signal flag to True")
            
            # Try to get related currencies for this instrument
            currencies = INSTRUMENT_CURRENCY_MAP.get(instrument.upper(), [])
            
            if not currencies:
                # Try to guess currencies from instrument name (assuming the standard is BaseCurrencyQuoteCurrency)
                if len(instrument) >= 6:
                    try:
                        base_currency = instrument[0:3].upper()
                        quote_currency = instrument[3:6].upper()
                        currencies = [base_currency, quote_currency]
                    except:
                        pass
            
            # Try to show loading animation first
            loading_gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
            
            if currencies:
                currency_list = ", ".join(currencies)
                loading_text = f"Loading economic calendar for {currency_list}..."
            else:
                loading_text = f"Loading economic calendar for {instrument}..."
            
            try:
                # Try to update with animated GIF first (best visual experience)
                await query.edit_message_media(
                    media=InputMediaAnimation(
                        media=loading_gif_url,
                        caption=loading_text
                    )
                )
                logger.info(f"Successfully showed loading GIF for {instrument} calendar")
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
                                caption=f"⏳ <b>Loading economic calendar for {instrument}...</b>"
                            )
                        except Exception as gif_error:
                            logger.warning(f"Could not show loading GIF: {str(gif_error)}")
            
            # Show calendar for this instrument
            return await self.show_economic_calendar(update, context, currency=instrument)
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
        """Handle back_to_signal button press. Deletes the current message and sends a new one with the original signal info."""
        query = update.callback_query
        await query.answer()

        try:
            logger.info("ENTERING: back_to_signal_callback")
            user_id = update.effective_user.id
            chat_id = update.effective_chat.id

            instrument_to_use = None
            signal_id_to_use = None
            original_signal_message_fallback = None

            if context and hasattr(context, 'user_data'):
                logger.info(f"Context user_data at start of back_to_signal_callback: {context.user_data}")
                # --- Prioritize backup values stored when entering signal analysis flow ---
                instrument_to_use = context.user_data.get('signal_instrument_backup')
                signal_id_to_use = context.user_data.get('signal_id_backup')
                original_signal_message_fallback = context.user_data.get('original_signal_message') # Keep for fallback

                # If backups are missing, try current context values (less reliable)
                if not instrument_to_use:
                    instrument_to_use = context.user_data.get('signal_instrument')
                    logger.warning("Using current signal_instrument from context as backup instrument was missing.")
                if not signal_id_to_use:
                    signal_id_to_use = context.user_data.get('signal_id')
                    logger.warning("Using current signal_id from context as backup ID was missing.")

                context.user_data['from_signal'] = True # Ensure we stay in signal context
                logger.info(f"Prioritized context values: instrument='{instrument_to_use}', signal_id='{signal_id_to_use}'")

            # --- Find the signal message ---
            signal_data = None
            signal_message = None

            # 1. Try retrieving signal data from cache using the prioritized ID
            if signal_id_to_use and str(user_id) in self.user_signals:
                 signal_data = self.user_signals[str(user_id)].get(signal_id_to_use)
                 if signal_data:
                      signal_message = signal_data.get('message')
                      logger.info(f"Retrieved signal message from cache using ID: {signal_id_to_use}")
                 else:
                      logger.warning(f"Signal ID {signal_id_to_use} not found in cache for user {user_id}.")

            # 2. If not found via ID, try the original_signal_message from context as fallback
            if not signal_message and original_signal_message_fallback:
                signal_message = original_signal_message_fallback
                logger.info("Using original signal message from context as fallback.")

            # 3. Final fallback if no message found
            if not signal_message:
                 logger.error(f"Could not find signal message for user {user_id}, ID '{signal_id_to_use}', instrument '{instrument_to_use}'.")
                 signal_message = "Signal details not available." # Final fallback text

            # --- Construct the Analyze Market button ---
            if not instrument_to_use:
                 logger.error("Signal instrument is missing, cannot create Analyze button callback data.")
                 try:
                    await query.message.delete() # Delete the analysis message
                 except Exception: pass
                 await context.bot.send_message(
                     chat_id=chat_id,
                     text=f"Error: Could not determine the instrument for signal '{signal_id_to_use}'. Please use /menu.",
                     reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                 )
                 return MENU

            # Use the most reliable signal_id found
            analyze_callback_data = f"analyze_from_signal_{instrument_to_use}_{signal_id_to_use}"
            keyboard = [[InlineKeyboardButton("🔍 Analyze Market", callback_data=analyze_callback_data)]]

            # --- Send the message ---
            # Delete the current message (technical analysis/chart)
            try:
                await query.message.delete()
                logger.info(f"Deleted message {query.message.message_id}")
            except Exception as delete_error:
                logger.error(f"Could not delete message {query.message.message_id}: {str(delete_error)}")
                # Continue anyway, try sending the new message

            # Send a NEW message with the signal details
            await context.bot.send_message(
                chat_id=chat_id,
                text=signal_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Sent new message with signal details for {instrument_to_use} (ID: {signal_id_to_use})")

            # <<< Make sure we return the correct state >>>
            # We are back at the signal details view, awaiting potential analysis requests
            return SIGNAL_DETAILS # This state indicates viewing signal details

        except Exception as e:
            logger.error(f"Error in back_to_signal_callback: {str(e)}")
            logger.exception(e)

            # Error recovery: Try to send user back to main menu
            try:
                # Try deleting the current message first
                if query and query.message:
                     await query.message.delete()
                # Send main menu message
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="An error occurred. Please try again from the main menu.",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
            except Exception as recovery_error:
                logger.error(f"Error during error recovery in back_to_signal_callback: {recovery_error}")

            return MENU

    async def back_to_signal_analysis_callback(self, update: Update, context=None) -> int:
        """Handle back_to_signal_analysis button press - returns to analysis options for the signal"""
        query = update.callback_query
        await query.answer()
        
        logger.info("back_to_signal_analysis_callback called")
        
        try:
            # Get or restore instrument from context
            instrument = None
            if context and hasattr(context, 'user_data'):
                logger.info(f"Context at start of back_to_signal_analysis: {context.user_data}")
                
                # First try to get from backup values (most reliable)
                instrument = context.user_data.get('signal_instrument_backup')
                
                # Fallback to current values if backup not available
                if not instrument:
                    instrument = context.user_data.get('signal_instrument')
                
                # Last resort - try the general instrument field
                if not instrument:
                    instrument = context.user_data.get('instrument')
                
                # Ensure we're still in signal flow
                context.user_data['from_signal'] = True
                context.user_data['is_signals_context'] = True
                
                logger.info(f"Selected instrument for signal analysis: {instrument}")
            
            # Show analysis options keyboard (SIGNAL_ANALYSIS_KEYBOARD)
            keyboard = SIGNAL_ANALYSIS_KEYBOARD
            
            # First delete the current message
            try:
                await query.message.delete()
                logger.info(f"Deleted message {query.message.message_id}")
            except Exception as delete_error:
                logger.error(f"Could not delete message {query.message.message_id}: {str(delete_error)}")
                # Continue anyway, we'll try sending a new message
            
            # Send a new message with the signal analysis options
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"Select your analysis type for {instrument}:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Sent new message with signal analysis options for {instrument}")
            
            return CHOOSE_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error in back_to_signal_analysis_callback: {str(e)}")
            logger.exception(e)
            
            # Generic error handling
            try:
                # Try to delete the current message if it exists
                if query and query.message:
                    await query.message.delete()
                # Send a new message with the main menu
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
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
            
            # Signal analysis type selection
            elif callback_data == CALLBACK_SIGNAL_TECHNICAL or callback_data == "signal_technical":
                return await self.signal_technical_callback(update, context)
            elif callback_data == CALLBACK_SIGNAL_SENTIMENT or callback_data == "signal_sentiment":
                return await self.signal_sentiment_callback(update, context)
            elif callback_data == CALLBACK_SIGNAL_CALENDAR or callback_data == "signal_calendar":
                return await self.signal_calendar_callback(update, context)
                
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
            
            # Market type selection (handle sentiment separately)
            if callback_data.startswith("market_") and "sentiment" in callback_data:
                return await self.analysis_sentiment_callback(update, context, market_selected=True)
            elif callback_data.startswith("market_"):
                return await self.market_callback(update, context)
            elif callback_data.startswith("market_"):
                return await self.market_callback(update, context)
                
            # Handle back buttons
            if callback_data == CALLBACK_BACK_MENU or callback_data == "back_menu":
                 return await self.back_menu_callback(update, context)
            elif callback_data == CALLBACK_BACK_ANALYSIS or callback_data == "back_analysis":
                 return await self.back_analysis_callback(update, context)
            elif callback_data == CALLBACK_BACK_MARKET or callback_data == "back_market":
                 return await self.back_market_callback(update, context)
            elif callback_data == CALLBACK_BACK_INSTRUMENT or callback_data == "back_instrument":
                 return await self.back_instrument_callback(update, context)
            elif callback_data == CALLBACK_BACK_SIGNALS or callback_data == "back_signals":
                 return await self.back_signals_callback(update, context)
                 
            # >>> SIGNAL FLOW SPECIFIC BACK BUTTONS <<<
            elif callback_data == "back_to_signal_analysis": # Back to Tech/Sentiment/Calendar for the signal (Corrected from back_to_signal_analysis_options)
                # return await self.analyze_from_signal_callback(update, context) # INCORRECT: This was causing the wrong flow
                return await self.back_to_signal_analysis_callback(update, context) # CORRECT: Route to the proper handler
            elif callback_data == "back_to_signal": # Back to the original signal message
                return await self.back_to_signal_callback(update, context)

            # Handle timeframe selection (voor Technical Analysis)
            if callback_data.startswith("timeframe_"):
                return await self.timeframe_callback(update, context)
            
            # Handle subscription button
            if callback_data == "subscribe_now":
                return await self.handle_subscription_callback(update, context)

            # Handle add/manage signals buttons
            if callback_data == CALLBACK_SIGNALS_ADD or callback_data == "signals_add":
                return await self.signals_add_callback(update, context)
            elif callback_data == CALLBACK_SIGNALS_MANAGE or callback_data == "signals_manage":
                return await self.signals_manage_callback(update, context)
            
            # >>> GENERIC INSTRUMENT HANDLING (fallback) <<<
            # Dit vangt callback data zoals "instrument_EURUSD" op
            # Let op: Zorg dat specifiekere handlers (zoals _chart, _sentiment) hierboven staan.
            if callback_data.startswith("instrument_"):
                 logger.info(f"Generic instrument callback detected: {callback_data}. Handling with instrument_callback.")
                 return await self.instrument_callback(update, context) # Gebruik de bestaande handler

            # Fallback for unhandled callbacks
            logger.warning(f"Unhandled callback data: {callback_data}")
            # Optionally send a message back to the user
            # await query.message.reply_text("Sorry, I didn't understand that action.")
            return MENU # Return to main menu or another default state

        except Exception as e:
            logger.error(f"Error processing button callback '{callback_data}': {str(e)}")
            logger.exception(e) # <<< CORRECTE INDENTATIE
            # Attempt to notify the user about the error
            try:
                await update.effective_message.reply_text("An error occurred while processing your request. Please try again later.")
            except Exception as notify_error:
                logger.error(f"Could not notify user about callback error: {notify_error}")
            # Fallback to a safe state
            return MENU

    # <<< ADDED METHOD >>>
    async def menu_signals_callback(self, update: Update, context=None) -> int:
        """Handle menu_signals button press"""
        query = update.callback_query
        await query.answer()
        
        # Clear any previous context variables to avoid confusion
        if context and hasattr(context, 'user_data'):
            # Keep only essential data
            preserved_data = {}
            for key in ['user_id', 'username', 'first_name', 'subscription']:
                if key in context.user_data:
                    preserved_data[key] = context.user_data[key]
            
            # Reset user_data and restore only what we need
            context.user_data.clear()
            for key, value in preserved_data.items():
                context.user_data[key] = value
            
            # Set flags for proper menu navigation
            context.user_data['from_signal'] = False
            context.user_data['is_signals_context'] = True
            
            logger.info(f"Updated context in menu_signals_callback: {context.user_data}")
        
        # Create keyboard for signal menu
        keyboard = [
            [InlineKeyboardButton("➕ Add Signal", callback_data="signals_add")],
            [InlineKeyboardButton("📊 Manage Signals", callback_data="signals_manage")],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Get the signals GIF URL for better UX
        signals_gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
        signals_caption = "<b>📈 Signal Management</b>\n\nManage your trading signals"
        
        # Try to update the message with the GIF and caption
        try:
            # First, try deleting the old message and sending a new one with the GIF
            try:
                await query.message.delete()
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=signals_gif_url,
                    caption=signals_caption,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            except Exception as delete_error:
                logger.warning(f"Could not delete message, trying media update: {delete_error}")
                # If deletion fails, try editing the media
                try:
                    await query.edit_message_media(
                        media=InputMediaAnimation(
                            media=signals_gif_url,
                            caption=signals_caption,
                            parse_mode=ParseMode.HTML
                        ),
                        reply_markup=reply_markup
                    )
                except Exception as media_error:
                    logger.warning(f"Could not update media, trying text update: {media_error}")
                    # If media edit fails, try editing text/caption
                    try:
                        await query.edit_message_text(
                            text=signals_caption,
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as text_error:
                        if "There is no text in the message to edit" in str(text_error):
                            try:
                                await query.edit_message_caption(
                                    caption=signals_caption,
                                    reply_markup=reply_markup,
                                    parse_mode=ParseMode.HTML
                                )
                            except Exception as caption_error:
                                logger.error(f"Failed to update caption: {caption_error}")
                                # Last resort: Send a new message
                                await context.bot.send_animation(
                                    chat_id=update.effective_chat.id,
                                    animation=signals_gif_url,
                                    caption=signals_caption,
                                    reply_markup=reply_markup,
                                    parse_mode=ParseMode.HTML
                                )
                        else:
                            logger.error(f"Failed to update text message: {text_error}")
                            # Last resort: Send a new message
                            await context.bot.send_animation(
                                chat_id=update.effective_chat.id,
                                animation=signals_gif_url,
                                caption=signals_caption,
                                reply_markup=reply_markup,
                                parse_mode=ParseMode.HTML
                            )
        except Exception as e:
            logger.error(f"Error updating message: {e}")
            # Absolute last resort
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=signals_caption,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            except Exception as final_error:
                logger.error(f"All message update attempts failed: {final_error}")
        
        return SIGNALS  # Return the signals menu state
    async def show_sentiment_analysis(self, update: Update, context: CallbackContext, instrument: str, loading_message=None):
        """Show the market sentiment analysis for a specific instrument."""
        try:
            self.logger.info(f"Showing sentiment analysis for instrument: {instrument}")
            chat_id = update.effective_chat.id
            query = update.callback_query

            # Initialize the sentiment service (assuming _sentiment_service is initialized elsewhere)
            if not hasattr(self, '_sentiment_service') or self._sentiment_service is None:
                 # Attempt lazy initialization if needed (adjust based on actual init logic)
                 self._initialize_services() 
            
            if not hasattr(self, '_sentiment_service') or self._sentiment_service is None:
                self.logger.error("Sentiment service is not initialized.")
                await self.update_message(query, "Error: Sentiment analysis service is unavailable.", keyboard=self._get_back_keyboard(context))
                return CHOOSE_ANALYSIS # Or appropriate state

            sentiment_service = self._sentiment_service
            
            # --- Get Sentiment Data ---
            sentiment_data = None
            try:
                # Assuming sentiment service has a method like get_sentiment
                sentiment_data = await sentiment_service.get_sentiment(instrument) 
                if not sentiment_data:
                     raise ValueError("Received no data from sentiment service")
                self.logger.info(f"Received sentiment data for {instrument}")

            except Exception as e:
                self.logger.error(f"Error getting sentiment data for {instrument}: {str(e)}")
                # Provide more specific error message based on exception type if possible
                error_message = f"Could not fetch sentiment data for {instrument}. Please try again later."
                await self.update_message(query, error_message, keyboard=self._get_back_keyboard(context))
                return CHOOSE_ANALYSIS # Or appropriate state

            # --- Format Sentiment Message ---
            # TODO: Implement proper formatting based on the structure of sentiment_data
            # Example basic formatting (replace with actual logic):
            message = f"<b>📊 Market Sentiment for {instrument}</b>\n\n"
            if isinstance(sentiment_data, dict):
                 # Example: Assuming dict like {'summary': 'Positive', 'score': 0.75, 'details': '...'}
                 summary = sentiment_data.get('summary', 'N/A')
                 score = sentiment_data.get('score') 
                 message += f"Overall Sentiment: <b>{summary}</b>\n"
                 if score is not None:
                      message += f"Confidence Score: {score:.2f}\n"
                 message += f"\nDetails: {sentiment_data.get('details', 'Not available')}"
            elif isinstance(sentiment_data, str):
                 message += sentiment_data # If the service returns a pre-formatted string
            else:
                 message += "Sentiment data format not recognized."
            
            # --- Determine Keyboard ---
            keyboard = self._get_back_keyboard(context)

            # --- Send Message ---
            # Try deleting loading message first
            loading_message_to_delete = context.user_data.get('loading_message')
            if loading_message_to_delete:
                try:
                    await loading_message_to_delete.delete()
                    self.logger.info("Successfully deleted loading message")
                except Exception as delete_error:
                    self.logger.warning(f"Could not delete loading message: {str(delete_error)}")
                    # Attempt to edit instead if deletion failed
                    try:
                         await self.update_message(query, message, keyboard=keyboard)
                         self.logger.info(f"Edited loading message with sentiment data for {instrument}")
                         return CHOOSE_ANALYSIS # Or appropriate state
                    except Exception as edit_error:
                         self.logger.warning(f"Could not edit loading message: {str(edit_error)}. Sending new message.")
            
            # Send as a new message or edit the existing one if deletion failed
            if query and query.message:
                 await self.update_message(query, message, keyboard=keyboard)
                 self.logger.info(f"Sent sentiment analysis message for {instrument}")
            else:
                 # Fallback if query/message is not available (e.g., called directly)
                 await context.bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML, reply_markup=keyboard)
                 self.logger.info(f"Sent sentiment analysis as new message for {instrument}")


        except Exception as e:
            self.logger.exception(f"Unhandled error in show_sentiment_analysis for {instrument}: {str(e)}")
            error_message = "An unexpected error occurred while showing sentiment analysis."
            if query:
                 await self.update_message(query, error_message, keyboard=self._get_back_keyboard(context))
            else:
                 # Fallback send
                 await context.bot.send_message(chat_id=chat_id, text=error_message, reply_markup=self._get_back_keyboard(context))

        # Return the state for conversation handler (assuming CHOOSE_ANALYSIS is correct)
        return CHOOSE_ANALYSIS

    # Helper to get the correct back button based on context
    def _get_back_keyboard(self, context):
         if context and hasattr(context, 'user_data') and context.user_data.get('from_signal', False):
             return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")]])
         else:
             # Default back to main analysis menu
             return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_analyse")]])

    async def show_technical_analysis(self, update: Update, context: CallbackContext, instrument: str, timeframe: str = None, loading_message=None):
        """Show the technical analysis chart for a specific instrument."""
        try:
            self.logger.info(f"Showing technical analysis for instrument: {instrument}, timeframe: {timeframe}")
            chat_id = update.effective_chat.id
            query = update.callback_query

            # Initialize the chart service if needed
            if not hasattr(self, 'chart_service') or self.chart_service is None:
                # Attempt lazy initialization if needed
                self._initialize_services()
            
            if not hasattr(self, 'chart_service') or self.chart_service is None:
                self.logger.error("Chart service is not initialized.")
                await self.update_message(query, "Error: Chart service is unavailable.", keyboard=self._get_back_keyboard(context))
                return CHOOSE_ANALYSIS

            chart_service = self.chart_service
            
            # --- Get Chart Data ---
            try:
                # Get the chart image based on instrument and timeframe
                chart_image = None
                chart_caption = f"<b>📊 Technical Analysis: {instrument}</b>"
                
                if timeframe:
                    chart_caption += f" ({timeframe})"
                    self.logger.info(f"Generating chart for {instrument} with timeframe {timeframe}")
                    chart_image = await chart_service.get_chart(instrument, timeframe=timeframe)
                else:
                    self.logger.info(f"Generating chart for {instrument} with default timeframe")
                    chart_image = await chart_service.get_chart(instrument)
                
                if not chart_image:
                    raise ValueError(f"Could not generate chart for {instrument}")
                
                self.logger.info(f"Successfully generated chart for {instrument}")
                
                # Get technical analysis text
                # <<< ADDED LOGGING >>>
                self.logger.info("[BOT.PY] Attempting to call chart_service.get_technical_analysis...")
                technical_analysis = await chart_service.get_technical_analysis(instrument, timeframe)
                # <<< ADDED LOGGING >>>
                self.logger.info(f"[BOT.PY] chart_service.get_technical_analysis returned (type: {type(technical_analysis)}, len: {len(technical_analysis) if technical_analysis else 0})")
                
                # Update the caption with technical analysis
                if technical_analysis:
                    chart_caption = technical_analysis
                
                # --- Determine Keyboard ---
                keyboard = self._get_back_keyboard(context)
                
                # --- Delete loading message if it exists ---
                loading_message_to_delete = context.user_data.get('loading_message')
                if loading_message_to_delete:
                    try:
                        await loading_message_to_delete.delete()
                        self.logger.info("Successfully deleted loading message")
                    except Exception as delete_error:
                        self.logger.warning(f"Could not delete loading message: {str(delete_error)}")
                
                # --- Send the chart image ---
                if query and query.message:
                    try:
                        await query.edit_message_media(
                            media=InputMediaPhoto(
                                media=chart_image,
                                caption=chart_caption,
                                parse_mode=ParseMode.HTML
                            ),
                            reply_markup=keyboard
                        )
                        self.logger.info(f"Updated message with chart for {instrument}")
                    except Exception as e:
                        self.logger.error(f"Could not update message with chart: {str(e)}")
                        # If update fails, try sending a new message
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=chart_image,
                            caption=chart_caption,
                            parse_mode=ParseMode.HTML,
                            reply_markup=keyboard
                        )
                        self.logger.info(f"Sent new message with chart for {instrument}")
                else:
                    # Fallback if query/message is not available
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=chart_image,
                        caption=chart_caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard
                    )
                    self.logger.info(f"Sent chart as new message for {instrument}")
            
            except Exception as e:
                self.logger.error(f"Error generating chart for {instrument}: {str(e)}")
                error_message = f"Could not generate technical analysis chart for {instrument}. Please try again later."
                if query:
                    await self.update_message(query, error_message, keyboard=self._get_back_keyboard(context))
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=error_message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=self._get_back_keyboard(context)
                    )
            
            # Return to the appropriate state
            return CHOOSE_ANALYSIS if context.user_data.get('from_signal', False) else INSTRUMENT_ANALYSIS

        except Exception as e:
            self.logger.exception(f"Unhandled error in show_technical_analysis for {instrument}: {str(e)}")
            error_message = "An unexpected error occurred while showing technical analysis."
            if query:
                await self.update_message(query, error_message, keyboard=self._get_back_keyboard(context))
            else:
                # Fallback send
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=error_message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=self._get_back_keyboard(context)
                )
            
            return CHOOSE_ANALYSIS if context.user_data.get('from_signal', False) else INSTRUMENT_ANALYSIS

    # Add the missing signals_add_callback method
    async def signals_add_callback(self, update: Update, context=None) -> int:
        """Handle signals_add button press"""
        query = update.callback_query
        await query.answer()
        
        logger.info("signals_add_callback called")
        
        # Make sure we're in the signals flow context
        if context and hasattr(context, 'user_data'):
            context.user_data['is_signals_context'] = True
            context.user_data['from_signal'] = False
            
            logger.info(f"Updated context in signals_add_callback: {context.user_data}")
        
        # Create keyboard for market selection (similar to the one in menu_analyse_callback)
        keyboard = []
        
        # Add market buttons
        for market in MARKETS:
            button_text = market.get('emoji', '') + ' ' + market.get('name', 'Unknown')
            callback_data = f"market_{market.get('id', 'unknown')}_signals"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        # Add back button
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_signals")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Update the message
        await self.update_message(
            query=query,
            text="<b>📊 Add Signal</b>\n\nSelect a market to add signals for:",
            keyboard=reply_markup
        )
        
        return SIGNALS
        
    async def market_signals_callback(self, update: Update, context=None) -> int:
        """Handle market selection for signals"""
        query = update.callback_query
        callback_data = query.data
        await query.answer()
        
        logger.info(f"market_signals_callback called with data: {callback_data}")
        
        # Extract market ID from callback data (format: "market_{market_id}_signals")
        market_id = callback_data.split('_')[1]
        
        # Store the selected market in user_data
        if context and hasattr(context, 'user_data'):
            context.user_data['selected_market'] = market_id
            context.user_data['is_signals_context'] = True
            logger.info(f"Selected market for signals: {market_id}")
        
        # Get instruments for the selected market
        instruments = []
        for market in MARKETS:
            if market.get('id') == market_id:
                instruments = market.get('instruments', [])
                break
        
        # Create keyboard with instruments
        keyboard = []
        
        # Add instrument buttons (in groups of 2 for better layout)
        row = []
        for i, instrument in enumerate(instruments):
            button_text = instrument.get('name', 'Unknown')
            callback_data = f"instrument_{instrument.get('id', 'unknown')}_signals"
            
            row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
            
            # Add row after every 2 instruments or at the end
            if (i + 1) % 2 == 0 or i == len(instruments) - 1:
                if row:
                    keyboard.append(row)
                    row = []
        
        # Add back button
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_signals_markets")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Get the selected market name for better UX
        market_name = "Unknown"
        market_emoji = ""
        for market in MARKETS:
            if market.get('id') == market_id:
                market_name = market.get('name', 'Unknown')
                market_emoji = market.get('emoji', '')
                break
        
        # Update the message
        await self.update_message(
            query=query,
            text=f"<b>📊 Add Signal: {market_emoji} {market_name}</b>\n\nSelect an instrument to add signals for:",
            keyboard=reply_markup
        )
        
        return SIGNALS
        
    async def instrument_signals_callback(self, update: Update, context=None) -> int:
        """Handle instrument selection for signals"""
        query = update.callback_query
        callback_data = query.data
        await query.answer()
        
        logger.info(f"instrument_signals_callback called with data: {callback_data}")
        
        # Extract instrument ID from callback data (format: "instrument_{instrument_id}_signals")
        instrument_id = callback_data.split('_')[1]
        
        # Store the selected instrument in user_data
        if context and hasattr(context, 'user_data'):
            context.user_data['selected_instrument'] = instrument_id
            context.user_data['is_signals_context'] = True
            logger.info(f"Selected instrument for signals: {instrument_id}")
        
        # Get the instrument and market details
        instrument_name = "Unknown"
        market_id = context.user_data.get('selected_market', 'unknown')
        market_name = "Unknown"
        market_emoji = ""
        
        for market in MARKETS:
            if market.get('id') == market_id:
                market_name = market.get('name', 'Unknown')
                market_emoji = market.get('emoji', '')
                
                # Find the instrument within this market
                for instrument in market.get('instruments', []):
                    if instrument.get('id') == instrument_id:
                        instrument_name = instrument.get('name', 'Unknown')
                        break
                break
        
        # Create keyboard with timeframe options
        keyboard = [
            [
                InlineKeyboardButton("5m", callback_data=f"timeframe_5m_signals"),
                InlineKeyboardButton("15m", callback_data=f"timeframe_15m_signals"),
                InlineKeyboardButton("30m", callback_data=f"timeframe_30m_signals")
            ],
            [
                InlineKeyboardButton("1h", callback_data=f"timeframe_1h_signals"),
                InlineKeyboardButton("4h", callback_data=f"timeframe_4h_signals"),
                InlineKeyboardButton("1d", callback_data=f"timeframe_1d_signals")
            ],
            [
                InlineKeyboardButton("⬅️ Back", callback_data="back_to_instruments_signals")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Update the message
        await self.update_message(
            query=query,
            text=f"<b>📊 Add Signal: {market_emoji} {market_name} - {instrument_name}</b>\n\nSelect a timeframe for the signal:",
            keyboard=reply_markup
        )
        
        return SIGNALS
        
    async def back_to_signals_markets_callback(self, update: Update, context=None) -> int:
        """Handle back button from instrument selection to market selection in signals flow"""
        query = update.callback_query
        await query.answer()
        
        logger.info("back_to_signals_markets_callback called")
        
        # Make sure we're in the signals flow context
        if context and hasattr(context, 'user_data'):
            context.user_data['is_signals_context'] = True
            context.user_data['from_signal'] = False
            
            # Clear the selected instrument but keep the market
            if 'selected_instrument' in context.user_data:
                del context.user_data['selected_instrument']
                
            logger.info(f"Updated context in back_to_signals_markets_callback: {context.user_data}")
            
            # Get the selected market if available
            market_id = context.user_data.get('selected_market')
            if market_id:
                # We need to show instruments for this market
                return await self.market_signals_callback(update, context)
            
        # If no market was selected or context is missing, return to market selection
        return await self.signals_add_callback(update, context)

    # <<< ADDED METHOD: analyze_from_signal_callback >>>
    async def analyze_from_signal_callback(self, update: Update, context=None) -> int:
        """Handle the 'Analyze Market' button press from a signal message."""
        query = update.callback_query
        await query.answer()
        logger.info(f"analyze_from_signal_callback called with data: {query.data}")

        try:
            # Extract instrument and signal ID from callback data
            # Format: analyze_from_signal_{instrument}_{signal_id}
            parts = query.data.split('_')
            if len(parts) < 4:
                logger.error(f"Invalid callback data format for analyze_from_signal: {query.data}")
                await query.message.reply_text("Error: Could not process the request. Invalid signal data.")
                return MENU # Or appropriate error state

            instrument = parts[3]
            signal_id = "_".join(parts[4:]) # Rejoin potentially split signal IDs

            logger.info(f"Extracted for analysis: instrument='{instrument}', signal_id='{signal_id}'")

            # Store crucial signal context and backups
            if context and hasattr(context, 'user_data'):
                context.user_data.clear() # Start fresh for signal flow
                context.user_data['instrument'] = instrument
                context.user_data['signal_id'] = signal_id
                context.user_data['from_signal'] = True
                context.user_data['is_signals_context'] = True # Mark as signal context

                # --- Store backups ---
                context.user_data['signal_instrument_backup'] = instrument
                context.user_data['signal_id_backup'] = signal_id
                # Store the original message text/caption if available
                if query.message.text:
                    context.user_data['original_signal_message'] = query.message.text_html # Use HTML for formatting
                elif query.message.caption:
                    context.user_data['original_signal_message'] = query.message.caption_html

                # --- Store timeframe if available in original message ---
                timeframe = None
                original_message_content = context.user_data.get('original_signal_message', '')
                # Look for timeframe patterns (e.g., M15, H1, 1h, 4h)
                tf_match = re.search(r'\b(M5|M15|M30|H1|H4|D1|1m|5m|15m|30m|1h|4h|1d)\b', original_message_content, re.IGNORECASE)
                if tf_match:
                    timeframe = tf_match.group(1).upper()
                    # Normalize timeframe (e.g., 1H -> H1)
                    if timeframe.endswith('M'): timeframe = timeframe.replace('M', 'm') # 5m, 15m, 30m
                    if timeframe.endswith('H'): timeframe = 'H' + timeframe[:-1] # H1, H4
                    if timeframe.endswith('D'): timeframe = 'D' + timeframe[:-1] # D1
                    if timeframe == '1M': timeframe = '1m' # Fix case
                    context.user_data['signal_timeframe'] = timeframe
                    context.user_data['signal_timeframe_backup'] = timeframe
                    logger.info(f"Extracted timeframe from signal message: {timeframe}")
                else:
                    logger.warning(f"Could not extract timeframe from signal message for {instrument}")


                logger.info(f"Set signal context: {context.user_data}")

            else:
                logger.error("Context or user_data not available in analyze_from_signal_callback")
                await query.message.reply_text("Error: Internal context error.")
                return MENU

            # Create keyboard for signal analysis options
            keyboard = [
                # Add instrument to callback data for direct use
                [InlineKeyboardButton("📈 Technical Analysis", callback_data=f"signal_technical")],
                [InlineKeyboardButton("🧠 Market Sentiment", callback_data=f"signal_sentiment")],
                [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"signal_calendar")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal")] # Back to original signal msg
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Update the message to show analysis options
            message_text = f"<b>📊 Analyze Signal: {instrument}</b>\n\nSelect analysis type:"

            try:
                # Try editing the existing message
                await query.edit_message_text(
                    text=message_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            except telegram.error.BadRequest as e:
                if "message is not modified" in str(e):
                    logger.warning("Message not modified, likely already showing analysis options.")
                elif "message to edit not found" in str(e):
                     logger.error("Original message to edit was not found.")
                     # Send a new message as fallback
                     await context.bot.send_message(
                         chat_id=update.effective_chat.id,
                         text=message_text,
                         reply_markup=reply_markup,
                         parse_mode=ParseMode.HTML
                     )
                else:
                    # Handle other potential edit errors (e.g., trying to edit media as text)
                    logger.warning(f"Could not edit message text ({e}), trying to delete and send new.")
                    try:
                         await query.message.delete()
                    except Exception:
                         logger.error("Failed to delete message during fallback.")
                    # Send a new message
                    await context.bot.send_message(
                         chat_id=update.effective_chat.id,
                         text=message_text,
                         reply_markup=reply_markup,
                         parse_mode=ParseMode.HTML
                     )
            except Exception as e:
                 logger.error(f"Unexpected error editing message in analyze_from_signal_callback: {e}")
                 # Send a new message as fallback
                 await context.bot.send_message(
                     chat_id=update.effective_chat.id,
                     text=message_text,
                     reply_markup=reply_markup,
                     parse_mode=ParseMode.HTML
                 )


            return CHOOSE_ANALYSIS # State for choosing analysis type

        except Exception as e:
            logger.error(f"Error in analyze_from_signal_callback: {str(e)}")
            logger.exception(e)
            await query.message.reply_text("An error occurred while processing your request.")
            return MENU # Fallback to main menu

    # <<< END ADDED METHOD >>>
