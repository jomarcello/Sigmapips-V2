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

# Import FastAPI wanneer het beschikbaar is, met een fallback optie
try:
    from fastapi import FastAPI, Request, HTTPException, status
except ImportError:
    # Mock klassen als fallback
    class FastAPI:
        def __init__(self, *args, **kwargs):
            pass
    class Request:
        def __init__(self, *args, **kwargs):
            pass
    class HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            self.status_code = status_code
            self.detail = detail
    class status:
        HTTP_200_OK = 200
        HTTP_400_BAD_REQUEST = 400
        HTTP_500_INTERNAL_SERVER_ERROR = 500

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

# Verwijder of vervang imports die naar 'trading_bot.utils' verwijzen
# Eenvoudige ConfigManager implementatie lokaal definiëren
class ConfigManager:
    """Simple config manager that reads from environment variables"""
    def __init__(self):
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
        
    def get(self, key, default=None):
        """Get a configuration value from environment variables"""
        return os.getenv(key, default)

# Relatieve imports gebruiken voor lokale modules
try:
    from ..chart_service.chart import ChartService
except ImportError:
    # Fallback dummy implementation
    class ChartService:
        async def get_chart(self, instrument, timeframe=None):
            return None
        async def get_technical_analysis(self, instrument, timeframe=None):
            return f"Technical analysis for {instrument} not available"

# Helper functions voor instrument management
def get_markets_for_instrument(instrument):
    """Get available markets for a given instrument"""
    # Eenvoudige implementatie
    forex_instruments = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "EURGBP"]
    crypto_instruments = ["BTCUSD", "ETHUSD", "XRPUSD"]
    indices_instruments = ["US30", "US500", "US100"]
    commodities_instruments = ["XAUUSD", "XAGUSD", "USOIL"]
    
    if instrument in forex_instruments:
        return ["forex"]
    elif instrument in crypto_instruments:
        return ["crypto"]
    elif instrument in indices_instruments:
        return ["indices"]
    elif instrument in commodities_instruments:
        return ["commodities"]
    else:
        return []

def get_instruments():
    """Get all available instruments"""
    return [
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "EURGBP",
        "BTCUSD", "ETHUSD", "XRPUSD",
        "US30", "US500", "US100",
        "XAUUSD", "XAGUSD", "USOIL"
    ]

# Overige imports met fallbacks
try:
    from ..database.db import Database
except ImportError:
    # Dummy Database class als fallback
    class Database:
        async def is_user_subscribed(self, user_id):
            return True
        async def has_payment_failed(self, user_id):
            return False
        async def get_user_subscription(self, user_id):
            return {"active": True}
        async def save_user(self, user_id, first_name, last_name, username):
            pass

try:
    from ..sentiment_service.sentiment import MarketSentimentService
except ImportError:
    # Dummy MarketSentimentService class als fallback
    class MarketSentimentService:
        async def get_sentiment(self, instrument):
            return {"summary": "Neutral", "details": "Sentiment analysis not available"}

try:
    from ..calendar_service.calendar import EconomicCalendarService
except ImportError:
    # Dummy EconomicCalendarService class als fallback
    class EconomicCalendarService:
        async def get_calendar(self):
            return []

try:
    from ..payment_service.stripe_service import StripeService
    from ..payment_service.stripe_config import get_subscription_features
except ImportError:
    # Dummy implementaties als fallback
    class StripeService:
        pass
    def get_subscription_features():
        return {}

# Probeer de states te importeren
try:
    from . import states
except ImportError:
    # Dummy states als fallback
    class states:
        MAIN_MENU = "MAIN_MENU"
        VIEW_MARKETS = "VIEW_MARKETS"
        VIEW_INSTRUMENTS = "VIEW_INSTRUMENTS"
        VIEW_NOTIFICATIONS = "VIEW_NOTIFICATIONS"
        SELECT_INSTRUMENT = "SELECT_INSTRUMENT"
        SELECT_MARKET = "SELECT_MARKET"
        EDIT_MARKET_NOTIFICATION = "EDIT_MARKET_NOTIFICATION"
        SIGNAL_MENU = "SIGNAL_MENU"
        SIGNAL_INSTRUMENT = "SIGNAL_INSTRUMENT"

# Lokale import voor gif_utils
try:
    from . import gif_utils
except ImportError:
    # Dummy gif_utils als fallback
    class gif_utils:
        @staticmethod
        async def send_loading_gif(bot, chat_id, caption=None):
            pass

# Calendar services
try:
    from ..calendar_service.tradingview_calendar import TradingViewCalendarService
    from ..calendar_service.__init__ import debug_tradingview_api, get_all_calendar_events
except ImportError:
    # Dummy implementaties
    class TradingViewCalendarService:
        async def get_calendar(self):
            return []
    def debug_tradingview_api():
        pass
    def get_all_calendar_events():
        return []

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
        """Initialize the Telegram service"""
        self.db = db
        self.stripe_service = stripe_service
        self.signals_enabled_flag = False
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.proxy_url = proxy_url
        self._chart_service = None
        self._sentiment_service = None
        self._calendar_service = None
        self.application = None # Added application attribute initialization
        self.polling_started = False # Added polling_started attribute

        # Initialize the bot instance
        if self.bot_token:
            request_settings = {}
            if self.proxy_url:
                request_settings['proxy_url'] = self.proxy_url
            
            request = HTTPXRequest(**request_settings) if request_settings else None
            self.bot = Bot(token=self.bot_token, request=request)
            logger.info(f"Telegram Bot instance created with token: {self.bot_token[:4]}...{self.bot_token[-4:]}")
        else:
            logger.error("TELEGRAM_BOT_TOKEN not provided. Cannot initialize bot.")
            self.bot = None  # Ensure self.bot exists even if initialization fails
        
        # Only initialize services if not lazy_init
        if not lazy_init:
            self._initialize_services()
    
    def _initialize_services(self):
        """Initialize required services"""
        logger.info("Initializing Telegram Bot Services")
        # Initialize the chart service
        if not self._chart_service:
            self._chart_service = ChartService()
        
        # Initialize other services as needed
        
    async def run(self):
        """Run the Telegram bot"""
        logger.info("Starting Telegram Bot")
        # Implement bot run logic here
        
    async def initialize_services(self):
        """Initialize services asynchronously"""
        logger.info("Initializing services asynchronously")
        # Implement async initialization here
        # Example: Initialize chart service if not already done
        if not self._chart_service:
             self._chart_service = ChartService()
             logger.info("Chart service initialized asynchronously.")
        # Initialize sentiment service
        if not self._sentiment_service:
            # Assuming MarketSentimentService can be initialized without args here
            # Or pass necessary args if required
            self._sentiment_service = MarketSentimentService()
            logger.info("Market sentiment service initialized asynchronously.")
        # Initialize calendar service
        if not self._calendar_service:
            # Assuming EconomicCalendarService can be initialized without args here
            self._calendar_service = EconomicCalendarService()
            logger.info("Economic calendar service initialized asynchronously.")

    # --- Added Command Handlers and Helpers ---

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None, skip_gif=False) -> None:
        """Show the main menu when /menu command is used"""
        # Use context.bot if available, otherwise use self.bot
        bot = context.bot if context is not None and hasattr(context, 'bot') else self.bot
        if not bot:
             logger.error("Bot instance not found in show_main_menu")
             return

        # Check if the user has a subscription
        user_id = update.effective_user.id
        try:
            is_subscribed = await self.db.is_user_subscribed(user_id)
            payment_failed = await self.db.has_payment_failed(user_id)
        except Exception as db_error:
            logger.error(f"Database error in show_main_menu for user {user_id}: {db_error}")
            await update.effective_message.reply_text("Could not retrieve subscription status. Please try again later.")
            return


        if is_subscribed and not payment_failed:
            # Show the main menu for subscribed users
            reply_markup = InlineKeyboardMarkup(START_KEYBOARD)

            # Forceer altijd de welkomst GIF
            gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"

            # If we should show the GIF
            if not skip_gif:
                try:
                    current_message = update.effective_message
                    # For message commands or if no current message to edit
                    if isinstance(update, Update) and update.message:
                         # Send the GIF using regular animation method
                        await update.message.reply_animation(
                            animation=gif_url,
                            caption=WELCOME_MESSAGE,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                    # For callback queries, try to edit the existing message
                    elif isinstance(update, Update) and update.callback_query and update.callback_query.message:
                         query = update.callback_query
                         try:
                            await query.edit_message_media(
                                media=InputMediaAnimation(media=gif_url, caption=WELCOME_MESSAGE, parse_mode=ParseMode.HTML),
                                reply_markup=reply_markup
                            )
                         except telegram.error.BadRequest as e:
                             if "message is not modified" in str(e):
                                 logger.warning("Menu message already shown (not modified).")
                             elif "message can't be edited" in str(e) or "there is no media in the message to edit" in str(e):
                                 logger.warning(f"Cannot edit message media ({e}), sending new message.")
                                 # Delete old and send new
                                 try: await query.message.delete()
                                 except Exception: pass
                                 await bot.send_animation(
                                     chat_id=update.effective_chat.id,
                                     animation=gif_url,
                                     caption=WELCOME_MESSAGE,
                                     parse_mode=ParseMode.HTML,
                                     reply_markup=reply_markup
                                 )
                             else:
                                 raise # Re-raise other BadRequest errors
                         except Exception as e:
                             logger.error(f"Error editing message for menu GIF: {e}")
                             # Fallback: delete old and send new
                             try: await query.message.delete()
                             except Exception: pass
                             await bot.send_animation(
                                 chat_id=update.effective_chat.id,
                                 animation=gif_url,
                                 caption=WELCOME_MESSAGE,
                                 parse_mode=ParseMode.HTML,
                                 reply_markup=reply_markup
                             )
                    else:
                         # Fallback if no message or callback_query context
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
                    try:
                        if update.callback_query:
                             await update.callback_query.edit_message_text(text=WELCOME_MESSAGE, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
                        elif update.message:
                             await update.message.reply_text(text=WELCOME_MESSAGE, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
                        else:
                             await bot.send_message(chat_id=update.effective_chat.id, text=WELCOME_MESSAGE, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
                    except Exception as send_error:
                         logger.error(f"Failed to send text menu: {str(send_error)}")
            else:
                # Skip GIF mode - just send text
                try:
                    if update.callback_query:
                         await update.callback_query.edit_message_text(text=WELCOME_MESSAGE, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
                    elif update.message:
                         await update.message.reply_text(text=WELCOME_MESSAGE, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
                    else:
                         await bot.send_message(chat_id=update.effective_chat.id, text=WELCOME_MESSAGE, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
                except Exception as send_error:
                     logger.error(f"Failed to send text menu (skip_gif): {str(send_error)}")
        else:
            # Handle non-subscribed users or payment failed
            await self.start_command(update, context) # Calls start_command logic


    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Send a welcome message when the bot is started."""
        user = update.effective_user
        user_id = user.id
        first_name = user.first_name
        username = user.username

        # Try to add the user to the database if they don't exist yet
        try:
            # Check if user exists (assuming a method like get_user exists)
            # If not, use get_user_subscription as a proxy check
            existing_subscription = await self.db.get_user_subscription(user_id)

            if not existing_subscription:
                # Add new user
                logger.info(f"New user started: {user_id}, {first_name}, @{username}")
                # Make sure save_user can handle potential None for last_name
                await self.db.save_user(user_id, first_name, user.last_name, username)
            else:
                logger.info(f"Existing user started: {user_id}, {first_name}, @{username}")

        except Exception as e:
            logger.error(f"Error registering user {user_id}: {str(e)}")

        # Check subscription status again after potential registration
        is_subscribed = False
        payment_failed = False
        try:
            is_subscribed = await self.db.is_user_subscribed(user_id)
            payment_failed = await self.db.has_payment_failed(user_id)
        except Exception as e:
             logger.error(f"Error checking subscription status for user {user_id}: {str(e)}")
             await update.message.reply_text("Could not check your subscription status. Please try again later.")
             return


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

            # Use direct URL link for reactivation (ensure this is the correct link)
            reactivation_url = os.getenv("STRIPE_REACTIVATION_LINK", "https://buy.stripe.com/9AQcPf3j63HL5JS145") # Get from env or use default

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
            # Show the welcome message with trial option
            welcome_text = """
🚀 Welcome to Sigmapips AI! 🚀

Discover powerful trading signals for various markets:
• Forex - Major and minor currency pairs
• Crypto - Bitcoin, Ethereum and other top cryptocurrencies
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

            # Use direct URL link instead of callback for the trial button (ensure this is correct)
            checkout_url = os.getenv("STRIPE_TRIAL_CHECKOUT_LINK", "https://buy.stripe.com/3cs3eF9Hu9256NW9AA") # Get from env or use default

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
        # Add admin check here if needed
        # e.g., if update.effective_user.id not in ADMIN_IDS: return

        if not context.args or len(context.args) < 3:
            await update.message.reply_text("Usage: /set_subscription [chat_id] [active|inactive] [days]")
            return

        try:
            chat_id = int(context.args[0])
            status = context.args[1].lower()
            days = int(context.args[2])

            if status not in ["active", "inactive"]:
                await update.message.reply_text("Status must be 'active' or 'inactive'")
                return

            now = datetime.now(timezone.utc) # Use timezone aware datetime

            if status == "active":
                start_date = now
                end_date = now + timedelta(days=days)
                # Plan type might need to be configurable or fetched
                plan_type = "basic" # Example plan type
                await self.db.save_user_subscription(chat_id, plan_type, start_date, end_date)
                # Also ensure payment failed is false
                await self.db.set_payment_failed(chat_id, status=False)
                await update.message.reply_text(f"✅ Subscription set to ACTIVE for user {chat_id} for {days} days.")
            else: # inactive
                start_date = now - timedelta(days=30) # Arbitrary past date
                end_date = now - timedelta(days=1)   # Expired date
                plan_type = "basic" # Example plan type
                await self.db.save_user_subscription(chat_id, plan_type, start_date, end_date)
                # Optionally set payment failed to False as well if they are explicitly made inactive
                await self.db.set_payment_failed(chat_id, status=False)
                await update.message.reply_text(f"✅ Subscription set to INACTIVE for user {chat_id}.")

            logger.info(f"Manually set subscription status to {status} for user {chat_id}")

        except ValueError:
            await update.message.reply_text("Invalid arguments. Chat ID and days must be numbers.")
        except Exception as e:
            logger.error(f"Error in set_subscription_command for {context.args}: {str(e)}")
            await update.message.reply_text(f"An error occurred: {str(e)}")

    async def set_payment_failed_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Secret command to set a user's subscription to the payment failed state"""
        # Add admin check here if needed
        logger.info(f"set_payment_failed command received: {update.message.text}")

        try:
            if not context.args or len(context.args) < 2:
                 await update.message.reply_text("Usage: /set_payment_failed [chat_id] [true|false]")
                 return

            chat_id = int(context.args[0])
            failed_status_str = context.args[1].lower()

            if failed_status_str not in ["true", "false"]:
                await update.message.reply_text("Status must be 'true' or 'false'")
                return

            failed_status = failed_status_str == "true"

            # Call database function to set the status
            # Assuming db.set_payment_failed takes status argument
            success = await self.db.set_payment_failed(chat_id, status=failed_status)

            if success:
                status_text = "FAILED" if failed_status else "NOT FAILED"
                message = f"✅ Payment status set to {status_text} for user {chat_id}"
                logger.info(f"Manually set payment failed status to {failed_status} for user {chat_id}")
                await update.message.reply_text(message)

                # If setting to failed, show the notification message
                if failed_status:
                    failed_payment_text = f"""
❗ <b>Subscription Payment Failed</b> ❗

Your subscription payment could not be processed and your service has been deactivated.

To continue using Sigmapips AI and receive trading signals, please reactivate your subscription by clicking the button below.
                    """
                    reactivation_url = os.getenv("STRIPE_REACTIVATION_LINK", "https://buy.stripe.com/9AQcPf3j63HL5JS145")
                    keyboard = [[InlineKeyboardButton("🔄 Reactivate Subscription", url=reactivation_url)]]
                    # Send the notification as a new message
                    await context.bot.send_message( # Use context.bot to send to the target chat_id
                         chat_id=chat_id,
                         text=failed_payment_text,
                         reply_markup=InlineKeyboardMarkup(keyboard),
                         parse_mode=ParseMode.HTML
                     )
            else:
                status_text = "FAILED" if failed_status else "NOT FAILED"
                message = f"❌ Could not set payment status to {status_text} for user {chat_id}"
                logger.error(f"Database returned failure for set_payment_failed for user {chat_id}")
                await update.message.reply_text(message)

        except ValueError:
            await update.message.reply_text("Invalid arguments. Chat ID must be a number.")
        except Exception as e:
            error_msg = f"Error setting payment failed status for {context.args}: {str(e)}"
            logger.error(error_msg)
            await update.message.reply_text(error_msg)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Send a message when the command /help is issued."""
        # Consider sending a specific help message instead of just the menu
        # await update.message.reply_text(HELP_MESSAGE, parse_mode=ParseMode.HTML)
        # For now, showing the main menu as per original file structure
        await self.show_main_menu(update, context)

    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Send a message when the command /menu is issued."""
        await self.show_main_menu(update, context)

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> Optional[int]:
        """Handle button callback queries by routing to specific handlers."""
        query = update.callback_query
        # Ensure query and message exist
        if not query or not query.message:
            logger.warning("button_callback received without query or message.")
            return None

        callback_data = query.data
        logger.info(f"Button callback received: {callback_data} from user {update.effective_user.id}")

        # Answer the callback query immediately
        try:
            await query.answer()
        except Exception as answer_err:
            logger.warning(f"Failed to answer callback query: {answer_err}")

        try:
            # --- Route to specific handlers ---
            if callback_data == CALLBACK_MENU_ANALYSE:
                return await self.menu_analyse_callback(update, context)
            elif callback_data == CALLBACK_MENU_SIGNALS:
                return await self.menu_signals_callback(update, context)
            elif callback_data == CALLBACK_ANALYSIS_TECHNICAL:
                return await self.analysis_technical_callback(update, context)
            elif callback_data == CALLBACK_ANALYSIS_SENTIMENT:
                return await self.analysis_sentiment_callback(update, context)
            elif callback_data == CALLBACK_ANALYSIS_CALENDAR:
                return await self.analysis_calendar_callback(update, context)
            elif callback_data == CALLBACK_SIGNAL_TECHNICAL:
                return await self.signal_technical_callback(update, context)
            elif callback_data == CALLBACK_SIGNAL_SENTIMENT:
                return await self.signal_sentiment_callback(update, context)
            elif callback_data == CALLBACK_SIGNAL_CALENDAR:
                return await self.signal_calendar_callback(update, context)
            elif callback_data.startswith("analyze_from_signal_"):
                 return await self.analyze_from_signal_callback(update, context)
            elif callback_data.startswith("market_"):
                 # Separate handlers for analysis and signals context
                 if context and context.user_data.get('is_signals_context'):
                     return await self.market_signals_callback(update, context)
                 else:
                     return await self.market_callback(update, context) # Needs market_callback implementation
            elif callback_data.startswith("instrument_"):
                 # Separate handlers for analysis and signals context
                 if context and context.user_data.get('is_signals_context'):
                     return await self.instrument_signals_callback(update, context)
                 else:
                     return await self.instrument_callback(update, context) # Needs instrument_callback implementation
            elif callback_data.startswith("back_"):
                 return await self.handle_back_button(update, context) # Centralized back handler
            elif callback_data == CALLBACK_SIGNALS_ADD:
                return await self.signals_add_callback(update, context)
            elif callback_data == CALLBACK_SIGNALS_MANAGE:
                return await self.signals_manage_callback(update, context)
            elif callback_data.startswith("timeframe_"):
                return await self.timeframe_callback(update, context) # Needs timeframe_callback implementation
            elif callback_data == "subscribe_now":
                return await self.handle_subscription_callback(update, context) # Needs handle_subscription_callback

            # Fallback for unhandled callbacks
            else:
                logger.warning(f"Unhandled callback data in button_callback: {callback_data}")
                try:
                    await query.answer("Action not recognized.") # Notify user
                except Exception: pass
                return None # Return None or a default state if using ConversationHandler

        except Exception as e:
            logger.error(f"Error processing button callback '{callback_data}': {str(e)}")
            logger.exception(e)
            try:
                 # Use query.edit_message_text if possible, otherwise reply
                 # await query.edit_message_text("An error occurred processing your request. Please try again.")
                 await update.effective_message.reply_text("An error occurred processing your request. Please try again.")
            except Exception as notify_error:
                logger.error(f"Could not notify user about callback error: {notify_error}")
            return None # Return None or a default state

    # --- Placeholder methods needed by button_callback ---
    # These need full implementation from .original file later

    async def menu_analyse_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: menu_analyse_callback called.")
        query = update.callback_query
        await query.answer()
        # Needs ANALYSIS_KEYBOARD defined
        try:
             # Assume ANALYSIS_KEYBOARD is defined globally
             await query.edit_message_text(
                  text="Select analysis type:",
                  reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD),
                  parse_mode=ParseMode.HTML
             )
             # Return state if using ConversationHandler, otherwise None
             return states.CHOOSE_ANALYSIS if hasattr(states, 'CHOOSE_ANALYSIS') else None
        except Exception as e:
             logger.error(f"Error in placeholder menu_analyse_callback: {e}")
             await query.message.reply_text("Error showing analysis menu.")
             return None

    async def menu_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: menu_signals_callback called.")
        query = update.callback_query
        await query.answer()
         # Needs SIGNALS_KEYBOARD defined
        try:
             # Assume SIGNALS_KEYBOARD is defined globally
             await query.edit_message_text(
                  text="Select signal action:",
                  reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD),
                  parse_mode=ParseMode.HTML
             )
             # Return state if using ConversationHandler, otherwise None
             return states.CHOOSE_SIGNALS if hasattr(states, 'CHOOSE_SIGNALS') else None
        except Exception as e:
             logger.error(f"Error in placeholder menu_signals_callback: {e}")
             await query.message.reply_text("Error showing signals menu.")
             return None


    async def analysis_technical_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: analysis_technical_callback called.")
        query = update.callback_query
        await query.answer()
        # Needs MARKET_KEYBOARD defined
        try:
             # Assume MARKET_KEYBOARD is defined globally
             await query.edit_message_text(
                 text="Select market for technical analysis:",
                 reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
             )
             # Return state if using ConversationHandler, otherwise None
             return states.CHOOSE_MARKET if hasattr(states, 'CHOOSE_MARKET') else None
        except Exception as e:
             logger.error(f"Error in placeholder analysis_technical_callback: {e}")
             await query.message.reply_text("Error showing market selection.")
             return None

    async def analysis_sentiment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: analysis_sentiment_callback called.")
        query = update.callback_query
        await query.answer()
        # Needs MARKET_SENTIMENT_KEYBOARD defined
        try:
             # Assume MARKET_SENTIMENT_KEYBOARD is defined globally
             await query.edit_message_text(
                 text="Select market for sentiment analysis:",
                 reply_markup=InlineKeyboardMarkup(MARKET_SENTIMENT_KEYBOARD)
             )
             return states.CHOOSE_MARKET if hasattr(states, 'CHOOSE_MARKET') else None
        except Exception as e:
             logger.error(f"Error in placeholder analysis_sentiment_callback: {e}")
             await query.message.reply_text("Error showing market selection.")
             return None


    async def analysis_calendar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: analysis_calendar_callback called. Needs implementation.")
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Economic Calendar feature not fully implemented yet.")
        # Should call show_calendar_analysis or show_economic_calendar
        return None

    async def signal_technical_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: signal_technical_callback called. Needs implementation.")
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Signal Technical Analysis feature not fully implemented yet.")
        # Should call show_technical_analysis with signal context
        return None

    async def signal_sentiment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: signal_sentiment_callback called. Needs implementation.")
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Signal Sentiment Analysis feature not fully implemented yet.")
         # Should call show_sentiment_analysis with signal context
        return None

    async def signal_calendar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: signal_calendar_callback called. Needs implementation.")
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Signal Economic Calendar feature not fully implemented yet.")
        # Should call show_calendar_analysis with signal context
        return None

    async def analyze_from_signal_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: analyze_from_signal_callback called. Needs implementation.")
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Analyze from Signal feature not fully implemented yet.")
        # Needs SIGNAL_ANALYSIS_KEYBOARD defined
        # Should show analysis options for the specific signal instrument
        return states.CHOOSE_ANALYSIS if hasattr(states, 'CHOOSE_ANALYSIS') else None


    async def market_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: market_signals_callback called. Needs implementation.")
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Market selection for signals not fully implemented yet.")
        # Needs specific instrument keyboards (_SIGNALS versions)
        return states.CHOOSE_INSTRUMENT if hasattr(states, 'CHOOSE_INSTRUMENT') else None

    async def market_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: market_callback called. Needs implementation.")
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Market selection for analysis not fully implemented yet.")
        # Needs specific instrument keyboards (_chart, _sentiment versions)
        return states.CHOOSE_INSTRUMENT if hasattr(states, 'CHOOSE_INSTRUMENT') else None

    async def instrument_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: instrument_signals_callback called. Needs implementation.")
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Instrument selection for signals not fully implemented yet.")
        # Needs timeframe selection keyboard
        return states.CHOOSE_TIMEFRAME if hasattr(states, 'CHOOSE_TIMEFRAME') else None


    async def instrument_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: instrument_callback called. Needs implementation.")
        query = update.callback_query
        await query.answer()
        # This needs to route to the correct analysis function based on user_data['analysis_type']
        analysis_type = context.user_data.get('analysis_type', 'technical') # Default or get from context
        await query.edit_message_text(f"Instrument selected. Showing {analysis_type} analysis (not implemented).")
        # Should call show_technical_analysis, show_sentiment_analysis, etc.
        return None # Or final state like SHOW_RESULT

    async def handle_back_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        """Handles various back buttons by routing to appropriate menu."""
        query = update.callback_query
        callback_data = query.data
        logger.info(f"Handling back button: {callback_data}")
        await query.answer()

        # Determine the target menu based on callback data or context
        target_state = None
        try:
            if callback_data == CALLBACK_BACK_MENU:
                await self.show_main_menu(update, context)
                target_state = states.MENU if hasattr(states, 'MENU') else None
            elif callback_data == CALLBACK_BACK_ANALYSIS:
                # Go back to analysis type selection
                await self.menu_analyse_callback(update, context)
                target_state = states.CHOOSE_ANALYSIS if hasattr(states, 'CHOOSE_ANALYSIS') else None
            elif callback_data == CALLBACK_BACK_MARKET:
                 # Go back to market selection (depends on context: analysis or signals)
                if context and context.user_data.get('is_signals_context'):
                     await self.signals_add_callback(update, context) # Back to market selection for signals
                     target_state = states.CHOOSE_MARKET if hasattr(states, 'CHOOSE_MARKET') else None # Or SIGNALS state?
                else:
                     await self.analysis_technical_callback(update, context) # Example: back to market for tech analysis
                     # Need logic to go back to correct analysis type market selection
                     target_state = states.CHOOSE_MARKET if hasattr(states, 'CHOOSE_MARKET') else None
            elif callback_data == CALLBACK_BACK_INSTRUMENT:
                 # Go back to instrument selection (depends on context)
                 if context and context.user_data.get('is_signals_context'):
                      await self.market_signals_callback(update, context) # Back to instrument list for signals
                      target_state = states.CHOOSE_INSTRUMENT if hasattr(states, 'CHOOSE_INSTRUMENT') else None
                 else:
                      await self.market_callback(update, context) # Back to instrument list for analysis
                      target_state = states.CHOOSE_INSTRUMENT if hasattr(states, 'CHOOSE_INSTRUMENT') else None
            elif callback_data == CALLBACK_BACK_SIGNALS:
                 # Go back to signals add/manage menu
                 await self.menu_signals_callback(update, context)
                 target_state = states.CHOOSE_SIGNALS if hasattr(states, 'CHOOSE_SIGNALS') else None # Or SIGNALS state?
            elif callback_data == "back_to_signal_analysis":
                 # Needs back_to_signal_analysis_callback implementation
                 logger.warning("Placeholder: back_to_signal_analysis called. Needs implementation.")
                 await query.edit_message_text("Back to Signal Analysis (not implemented).")
                 target_state = states.CHOOSE_ANALYSIS if hasattr(states, 'CHOOSE_ANALYSIS') else None
            elif callback_data == "back_to_signal":
                 # Needs back_to_signal_callback implementation
                 logger.warning("Placeholder: back_to_signal called. Needs implementation.")
                 await query.edit_message_text("Back to Signal Details (not implemented).")
                 target_state = states.SIGNAL_DETAILS if hasattr(states, 'SIGNAL_DETAILS') else None
            else:
                 logger.warning(f"Unhandled back button: {callback_data}")
                 await self.show_main_menu(update, context) # Default to main menu
                 target_state = states.MENU if hasattr(states, 'MENU') else None

            return target_state

        except Exception as e:
             logger.error(f"Error handling back button {callback_data}: {e}")
             await query.message.reply_text("Error going back. Returning to main menu.")
             await self.show_main_menu(update, context)
             return states.MENU if hasattr(states, 'MENU') else None


    async def signals_add_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: signals_add_callback called.")
        query = update.callback_query
        await query.answer()
         # Needs MARKET_KEYBOARD_SIGNALS defined
        try:
             # Assume MARKET_KEYBOARD_SIGNALS is defined globally
             await query.edit_message_text(
                  text="Select market to add signals for:",
                  reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS),
                  parse_mode=ParseMode.HTML
             )
             return states.CHOOSE_MARKET if hasattr(states, 'CHOOSE_MARKET') else None
        except Exception as e:
             logger.error(f"Error in placeholder signals_add_callback: {e}")
             await query.message.reply_text("Error showing market selection for signals.")
             return None


    async def signals_manage_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: signals_manage_callback called. Needs implementation.")
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Signal Management feature not fully implemented yet.")
        return None

    async def timeframe_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        logger.warning("Placeholder: timeframe_callback called. Needs implementation.")
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Timeframe selection processing not fully implemented yet.")
        # Should save selection and confirm or show results
        return None

    async def handle_subscription_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
         logger.warning("Placeholder: handle_subscription_callback called. Needs implementation.")
         query = update.callback_query
         await query.answer()
         await query.edit_message_text("Subscription handling not fully implemented yet.")
         # Should likely show Stripe link or process subscription
         return None

    # Add other placeholder methods as needed...

    # --- End Added Command Handlers ---

    # Add more methods as needed from the original implementation

# Assume constants like START_KEYBOARD, WELCOME_MESSAGE, ANALYSIS_KEYBOARD, etc.
# are defined globally in this file or imported correctly.
# Assume the 'states' object/enum is also available.

# Example definitions (replace with actual ones from the original file)
# These need to be outside the class if they are used directly by handlers
# Or passed into the class instance if preferred design

# Define states if not imported
class states:
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
    BACK_TO_MENU = 11
    INSTRUMENT_ANALYSIS = 12

# Define callback data constants
CALLBACK_MENU_ANALYSE = "menu_analyse"
CALLBACK_MENU_SIGNALS = "menu_signals"
CALLBACK_ANALYSIS_TECHNICAL = "analysis_technical"
CALLBACK_ANALYSIS_SENTIMENT = "analysis_sentiment"
CALLBACK_ANALYSIS_CALENDAR = "analysis_calendar"
CALLBACK_SIGNAL_TECHNICAL = "signal_technical"
CALLBACK_SIGNAL_SENTIMENT = "signal_sentiment"
CALLBACK_SIGNAL_CALENDAR = "signal_calendar"
CALLBACK_BACK_MENU = "back_menu"
CALLBACK_BACK_ANALYSIS = "back_analysis"
CALLBACK_BACK_MARKET = "back_market"
CALLBACK_BACK_INSTRUMENT = "back_instrument"
CALLBACK_BACK_SIGNALS = "back_signals"
CALLBACK_SIGNALS_ADD = "signals_add"
CALLBACK_SIGNALS_MANAGE = "signals_manage"


# Define Keyboards (ensure these match the callbacks used)
START_KEYBOARD = [
    [InlineKeyboardButton("🔍 Analyze Market", callback_data=CALLBACK_MENU_ANALYSE)],
    [InlineKeyboardButton("📊 Trading Signals", callback_data=CALLBACK_MENU_SIGNALS)]
]

ANALYSIS_KEYBOARD = [
    [InlineKeyboardButton("📈 Technical Analysis", callback_data=CALLBACK_ANALYSIS_TECHNICAL)],
    [InlineKeyboardButton("🧠 Market Sentiment", callback_data=CALLBACK_ANALYSIS_SENTIMENT)],
    [InlineKeyboardButton("📅 Economic Calendar", callback_data=CALLBACK_ANALYSIS_CALENDAR)],
    [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_MENU)] # Ensure BACK_MENU handler works
]

SIGNALS_KEYBOARD = [
    [InlineKeyboardButton("➕ Add New Pairs", callback_data=CALLBACK_SIGNALS_ADD)],
    [InlineKeyboardButton("⚙️ Manage Signals", callback_data=CALLBACK_SIGNALS_MANAGE)],
    [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_MENU)]
]

MARKET_KEYBOARD = [ # Example for technical analysis
    [InlineKeyboardButton("Forex", callback_data="market_forex")],
    [InlineKeyboardButton("Crypto", callback_data="market_crypto")],
    [InlineKeyboardButton("Commodities", callback_data="market_commodities")],
    [InlineKeyboardButton("Indices", callback_data="market_indices")],
    [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_ANALYSIS)] # Back to analysis type selection
]

MARKET_SENTIMENT_KEYBOARD = [ # Example for sentiment
    [InlineKeyboardButton("Forex", callback_data="market_forex_sentiment")],
    [InlineKeyboardButton("Crypto", callback_data="market_crypto_sentiment")],
    [InlineKeyboardButton("Commodities", callback_data="market_commodities_sentiment")],
    [InlineKeyboardButton("Indices", callback_data="market_indices_sentiment")],
    [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_ANALYSIS)]
]

MARKET_KEYBOARD_SIGNALS = [ # Example for signals
    [InlineKeyboardButton("Forex", callback_data="market_forex_signals")],
    [InlineKeyboardButton("Crypto", callback_data="market_crypto_signals")],
    [InlineKeyboardButton("Commodities", callback_data="market_commodities_signals")],
    [InlineKeyboardButton("Indices", callback_data="market_indices_signals")],
    [InlineKeyboardButton("⬅️ Back", callback_data=CALLBACK_BACK_SIGNALS)] # Back to signals menu
]

# Define Welcome Message
WELCOME_MESSAGE = """
🚀 <b>Sigmapips AI - Main Menu</b> 🚀

Choose an option:
""" # Simplified, use full message from original
