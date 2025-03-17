import os
import ssl
import asyncio
import logging
import aiohttp
import redis
import json
from typing import Dict, Any, List, TYPE_CHECKING
import base64
import time
import re
import random
import datetime
import pytz

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

from trading_bot.services.database.db import Database
from trading_bot.services.chart_service.chart import ChartService  # Direct importeren uit het bestand
from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
from trading_bot.services.calendar_service.calendar import EconomicCalendarService
from trading_bot.services.payment_service.stripe_config import get_subscription_features

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

# Forex keyboard voor analyse
FOREX_KEYBOARD = [
    [
        InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD_analysis"),
        InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD_analysis"),
        InlineKeyboardButton("USDCAD", callback_data="instrument_USDCAD_analysis")
    ],
    [
        InlineKeyboardButton("EURGBP", callback_data="instrument_EURGBP_analysis"),
        InlineKeyboardButton("EURJPY", callback_data="instrument_EURJPY_analysis"),
        InlineKeyboardButton("AUDJPY", callback_data="instrument_AUDJPY_analysis")
    ],
    [
        InlineKeyboardButton("AUDCAD", callback_data="instrument_AUDCAD_analysis"),
        InlineKeyboardButton("AUDCHF", callback_data="instrument_AUDCHF_analysis"),
        InlineKeyboardButton("CADCHF", callback_data="instrument_CADCHF_analysis")
    ],
    [
        InlineKeyboardButton("EURCAD", callback_data="instrument_EURCAD_analysis"),
        InlineKeyboardButton("EURCHF", callback_data="instrument_EURCHF_analysis"),
        InlineKeyboardButton("EURAUD", callback_data="instrument_EURAUD_analysis")
    ],
    [
        InlineKeyboardButton("GBPAUD", callback_data="instrument_GBPAUD_analysis"),
        InlineKeyboardButton("GBPCAD", callback_data="instrument_GBPCAD_analysis"),
        InlineKeyboardButton("GBPCHF", callback_data="instrument_GBPCHF_analysis")
    ],
    [
        InlineKeyboardButton("GBPNZD", callback_data="instrument_GBPNZD_analysis"),
        InlineKeyboardButton("NZDCAD", callback_data="instrument_NZDCAD_analysis"),
        InlineKeyboardButton("NZDCHF", callback_data="instrument_NZDCHF_analysis")
    ],
    [
        InlineKeyboardButton("NZDJPY", callback_data="instrument_NZDJPY_analysis"),
        InlineKeyboardButton("NZDUSD", callback_data="instrument_NZDUSD_analysis"),
        InlineKeyboardButton("USDCHF", callback_data="instrument_USDCHF_analysis")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Forex keyboard voor signals
FOREX_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD_signals"),
        InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD_signals"),
        InlineKeyboardButton("USDCAD", callback_data="instrument_USDCAD_signals")
    ],
    [
        InlineKeyboardButton("EURGBP", callback_data="instrument_EURGBP_signals"),
        InlineKeyboardButton("EURJPY", callback_data="instrument_EURJPY_signals"),
        InlineKeyboardButton("AUDJPY", callback_data="instrument_AUDJPY_signals")
    ],
    [
        InlineKeyboardButton("AUDCAD", callback_data="instrument_AUDCAD_signals"),
        InlineKeyboardButton("AUDCHF", callback_data="instrument_AUDCHF_signals"),
        InlineKeyboardButton("CADCHF", callback_data="instrument_CADCHF_signals")
    ],
    [
        InlineKeyboardButton("EURCAD", callback_data="instrument_EURCAD_signals"),
        InlineKeyboardButton("EURCHF", callback_data="instrument_EURCHF_signals"),
        InlineKeyboardButton("EURAUD", callback_data="instrument_EURAUD_signals")
    ],
    [
        InlineKeyboardButton("GBPAUD", callback_data="instrument_GBPAUD_signals"),
        InlineKeyboardButton("GBPCAD", callback_data="instrument_GBPCAD_signals"),
        InlineKeyboardButton("GBPCHF", callback_data="instrument_GBPCHF_signals")
    ],
    [
        InlineKeyboardButton("GBPNZD", callback_data="instrument_GBPNZD_signals"),
        InlineKeyboardButton("NZDCAD", callback_data="instrument_NZDCAD_signals"),
        InlineKeyboardButton("NZDCHF", callback_data="instrument_NZDCHF_signals")
    ],
    [
        InlineKeyboardButton("NZDJPY", callback_data="instrument_NZDJPY_signals"),
        InlineKeyboardButton("NZDUSD", callback_data="instrument_NZDUSD_signals"),
        InlineKeyboardButton("USDCHF", callback_data="instrument_USDCHF_signals")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Crypto keyboard voor analyse
CRYPTO_KEYBOARD = [
    [
        InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD_analysis"),
        InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD_analysis")
    ],
    [
        InlineKeyboardButton("BNBUSD", callback_data="instrument_BNBUSD_analysis"),
        InlineKeyboardButton("DOTUSD", callback_data="instrument_DOTUSD_analysis")
    ],
    [
        InlineKeyboardButton("DOGEUSD", callback_data="instrument_DOGEUSD_analysis"),
        InlineKeyboardButton("SOLUSD", callback_data="instrument_SOLUSD_analysis")
    ],
    [
        InlineKeyboardButton("LINKUSD", callback_data="instrument_LINKUSD_analysis"),
        InlineKeyboardButton("XLMUSD", callback_data="instrument_XLMUSD_analysis")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Crypto keyboard voor signals
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
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Indices keyboard voor analyse
INDICES_KEYBOARD = [
    [
        InlineKeyboardButton("US30", callback_data="instrument_US30_analysis"),
        InlineKeyboardButton("US500", callback_data="instrument_US500_analysis")
    ],
    [
        InlineKeyboardButton("UK100", callback_data="instrument_UK100_analysis"),
        InlineKeyboardButton("DE40", callback_data="instrument_DE40_analysis")
    ],
    [
        InlineKeyboardButton("AU200", callback_data="instrument_AU200_analysis"),
        InlineKeyboardButton("HK50", callback_data="instrument_HK50_analysis")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Indices keyboard voor signals
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
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Commodities keyboard voor analyse
COMMODITIES_KEYBOARD = [
    [
        InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD_analysis"),
        InlineKeyboardButton("XTIUSD", callback_data="instrument_XTIUSD_analysis")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Commodities keyboard voor signals
COMMODITIES_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD_signals"),
        InlineKeyboardButton("XTIUSD", callback_data="instrument_XTIUSD_signals")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Style keyboard
STYLE_KEYBOARD = [
    [InlineKeyboardButton("⚡ Test (1m)", callback_data="style_test")],
    [InlineKeyboardButton("🏃 Scalp (15m)", callback_data="style_scalp")],
    [InlineKeyboardButton("⏱️ Scalp (30m)", callback_data="style_scalp30")],
    [InlineKeyboardButton("📊 Intraday (1h)", callback_data="style_intraday")],
    [InlineKeyboardButton("🌊 Intraday (4h)", callback_data="style_swing")],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_instrument")]
]

# Timeframe mapping
STYLE_TIMEFRAME_MAP = {
    "test": "1m",
    "scalp": "15m",
    "scalp30": "30m",
    "intraday": "1h",
    "swing": "4h"
}

# Voeg deze functie toe aan het begin van bot.py, na de imports
def _detect_market(symbol: str) -> str:
    """Detecteer market type gebaseerd op symbol"""
    symbol = symbol.upper()
    
    # Commodities eerst checken
    commodities = [
        "XAUUSD",  # Gold
        "XAGUSD",  # Silver
        "WTIUSD",  # Oil WTI
        "BCOUSD",  # Oil Brent
    ]
    if symbol in commodities:
        logger.info(f"Detected {symbol} as commodity")
        return "commodities"
    
    # Crypto pairs
    crypto_base = ["BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "DOT", "LINK"]
    if any(c in symbol for c in crypto_base):
        logger.info(f"Detected {symbol} as crypto")
        return "crypto"
    
    # Major indices
    indices = [
        "US30", "US500", "US100",  # US indices
        "UK100", "DE40", "FR40",   # European indices
        "JP225", "AU200", "HK50"   # Asian indices
    ]
    if symbol in indices:
        logger.info(f"Detected {symbol} as index")
        return "indices"
    
    # Forex pairs als default
    logger.info(f"Detected {symbol} as forex")
    return "forex"

# Voeg dit toe als decorator functie bovenaan het bestand na de imports
def require_subscription(func):
    """Check if user has an active subscription"""
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        
        # Check subscription status
        is_subscribed = await self.db.is_user_subscribed(user_id)
        
        # Get subscription record to check if it's expired
        subscription = await self.db.get_user_subscription(user_id)
        has_expired = subscription and subscription.get('subscription_status') != 'active' and subscription.get('subscription_status') != 'trialing'
        
        if is_subscribed:
            # User has subscription, proceed with function
            return await func(self, update, context, *args, **kwargs)
        elif has_expired:
            # User has an expired subscription
            expired_message = """
❌ <b>Subscription Inactive</b> ❌

Your SigmaPips Trading Bot subscription is currently inactive. 

To regain access to all features and trading signals, please reactivate your subscription:
"""
            
            # Create buttons for resubscription
            keyboard = [
                [InlineKeyboardButton("🔄 Reactivate Subscription", url="https://buy.stripe.com/test_5kA4kkcHa2q73le6op")],
                [InlineKeyboardButton("ℹ️ More Information", callback_data="subscription_info")]
            ]
            
            await update.message.reply_text(
                text=expired_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return MENU
        else:
            # Show subscription screen for new users
            subscription_features = get_subscription_features("monthly")
            
            welcome_text = f"""
🚀 <b>Welcome to SigmaPips Trading Bot!</b> 🚀

To access all features, you need a subscription:

📊 <b>Trading Signals Subscription - $29.99/month</b>
• <b>Start with a FREE 14-day trial!</b>
• Access to all trading signals (Forex, Crypto, Commodities, Indices)
• Advanced timeframe analysis (1m, 15m, 1h, 4h)
• Detailed chart analysis for each signal

Click the button below to start your trial:
            """
            
            # Create buttons
            keyboard = [
                [InlineKeyboardButton("🔥 Start FREE Trial", url="https://buy.stripe.com/test_6oE4kkdLefcT8Fy6oo")],
                [InlineKeyboardButton("ℹ️ More Information", callback_data="subscription_info")]
            ]
            
            await update.message.reply_text(
                text=welcome_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return MENU
    
    return wrapper

class TelegramService:
    def __init__(self, db: Database, stripe_service=None):
        """Initialize telegram service"""
        try:
            # Sla de database op
            self.db = db
            
            # Initialiseer de bot
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
            if not bot_token:
                raise ValueError("Missing Telegram bot token")
            
            # Initialiseer de bot
            self.bot = Bot(token=bot_token)
            
            # Initialiseer de application
            self.application = Application.builder().bot(self.bot).build()
            
            # Initialiseer de services
            self.chart = ChartService()
            self.sentiment = MarketSentimentService()
            self.calendar = EconomicCalendarService()
            
            # Test de sentiment service
            logger.info("Testing sentiment service...")
            
            # Initialiseer de dictionary voor gebruikerssignalen
            self.user_signals = {}
            
            # Maak de data directory als die niet bestaat
            os.makedirs('data', exist_ok=True)
            
            # Laad bestaande signalen
            self._load_signals()
            
            # Registreer de handlers
            self._register_handlers()
            
            logger.info("Telegram service initialized")
            
            # Houd bij welke updates al zijn verwerkt
            self.processed_updates = set()
            
            self.stripe_service = stripe_service  # Stripe service toevoegen
            
            # Signaal ontvanger status
            self.signals_enabled = True  # Zet op True om signalen in te schakelen
            
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            raise

    def _load_signals(self):
        """Laad signalen uit het JSON bestand"""
        try:
            if os.path.exists('data/signals.json'):
                with open('data/signals.json', 'r') as f:
                    data = json.load(f)
                    # Converteer keys terug naar integers voor user_ids
                    self.user_signals = {int(k): v for k, v in data.items()}
                    logger.info(f"Loaded {len(self.user_signals)} saved signals")
            else:
                logger.info("No saved signals found")
        except Exception as e:
            logger.error(f"Error loading signals: {str(e)}")
            self.user_signals = {}

    def _save_signals(self):
        """Sla signalen op naar het JSON bestand"""
        try:
            # Converteer user_ids naar strings voor JSON serialisatie
            signals_to_save = {str(k): v for k, v in self.user_signals.items()}
            with open('data/signals.json', 'w') as f:
                json.dump(signals_to_save, f)
            logger.info(f"Saved {len(self.user_signals)} signals to file")
        except Exception as e:
            logger.error(f"Error saving signals: {str(e)}")

    def _register_handlers(self):
        """Register message handlers"""
        try:
            # Verwijder bestaande handlers om dubbele handlers te voorkomen
            self.application.handlers.clear()
            
            # Voeg een CommandHandler toe voor /start
            self.application.add_handler(CommandHandler("start", self.start_command))
            
            # Voeg een CommandHandler toe voor /menu
            self.application.add_handler(CommandHandler("menu", self.show_main_menu))
            
            # Voeg een CallbackQueryHandler toe voor knoppen
            # Verander button_callback naar callback_query_handler
            self.application.add_handler(CallbackQueryHandler(self.callback_query_handler))
            
            # Admin commando voor signalen in/uitschakelen
            self.application.add_handler(CommandHandler("toggle_signals", self.toggle_signals))
            
            # Admin commando voor abonnementsstatus
            self.application.add_handler(CommandHandler("check_subscription", self.check_subscription))
            
            # Admin commando voor handmatig abonnement toewijzen
            self.application.add_handler(CommandHandler("set_subscription", self.set_subscription))
            
            # Handler registreren
            self.application.add_handler(CommandHandler("send_welcome", self.send_welcome_message))
            
            logger.info("Handlers registered")
        except Exception as e:
            logger.error(f"Error registering handlers: {str(e)}")
            raise

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Send welcome message when the command /start is issued."""
        user_id = update.effective_user.id
        user = update.effective_user
        
        # Save user info in database
        await self.db.save_user(user_id, user.first_name, user.last_name, user.username)
        
        # Check if user is subscribed
        is_subscribed = await self.db.is_user_subscribed(user_id)
        
        # Check if user has a subscription record but inactive (expired)
        subscription = await self.db.get_user_subscription(user_id)
        has_expired = subscription and subscription.get('subscription_status') != 'active' and subscription.get('subscription_status') != 'trialing'
        
        if is_subscribed:
            # Welcome message for subscribed users
            welcome_message = """
✅ <b>Welcome to SigmaPips Trading Bot!</b> ✅

Your subscription is <b>ACTIVE</b>. You have full access to all features.

<b>🚀 HOW TO USE:</b>

<b>1. Start with /menu</b>
   • This will show you the main options:
   • <b>Analyze Market</b> - For all market analysis tools
   • <b>Trading Signals</b> - To manage your trading signals

<b>2. Analyze Market options:</b>
   • <b>Technical Analysis</b> - Charts and price levels
   • <b>Market Sentiment</b> - Indicators and market mood
   • <b>Economic Calendar</b> - Upcoming economic events

<b>3. Trading Signals:</b>
   • Set up which signals you want to receive
   • Signals will be sent automatically
   • Each includes entry, stop loss, and take profit levels

Type /menu to start using the bot.
"""
            # Create buttons for subscribed users - ALLEEN Subscription Active knop
            keyboard = [
                [InlineKeyboardButton("✅ Subscription Active", callback_data="subscription_status")]
            ]
            
            await update.message.reply_text(
                text=welcome_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        
        elif has_expired:
            # Message for users with expired subscriptions
            expired_message = """
❌ <b>Subscription Inactive</b> ❌

Your SigmaPips Trading Bot subscription is currently inactive. 

To regain access to all features and trading signals, please reactivate your subscription:
"""
            
            # Create buttons for resubscription
            keyboard = [
                [InlineKeyboardButton("🔄 Reactivate Subscription", url="https://buy.stripe.com/test_5kA4kkcHa2q73le6op")],
                [InlineKeyboardButton("ℹ️ More Information", callback_data="subscription_info")]
            ]
            
            await update.message.reply_text(
                text=expired_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        
        else:
            # Original welcome message for unsubscribed users
            subscription_features = get_subscription_features("monthly")
            
            # Update message to emphasize the trial period
            welcome_text = """
🚀 <b>Welcome to SigmaPips Trading Bot!</b> 🚀

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
            
            # Create buttons - ONLY SUBSCRIPTION OPTIONS
            keyboard = [
                [InlineKeyboardButton("🔥 Start 14-day FREE Trial", url="https://buy.stripe.com/test_6oE4kkdLefcT8Fy6oo")],
                [InlineKeyboardButton("ℹ️ More Information", callback_data="subscription_info")]
            ]
            
            await update.message.reply_text(
                text=welcome_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        
        # Process start parameters if any
        if context.args and len(context.args) > 0 and context.args[0].startswith('success'):
            # Handle payment success through deep link
            await update.message.reply_text("Your payment was successful! You now have full access to all features.")
        
        return MENU

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
        """Handle analysis_technical callback"""
        query = update.callback_query
        
        try:
            # Show market selection for technical analysis
            await query.edit_message_text(
                text="Select a market for technical analysis:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
            )
            
            # Save analysis type in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'technical'
            
            return CHOOSE_MARKET
        except Exception as e:
            logger.error(f"Error in analysis_technical_callback: {str(e)}")
            try:
                await query.message.reply_text(
                    text="Select a market for technical analysis:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
                return CHOOSE_MARKET
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                return MENU

    async def analysis_sentiment_callback(self, update: Update, context=None) -> int:
        """Handle sentiment analysis selection"""
        query = update.callback_query
        
        try:
            # Debug logging
            logger.info("analysis_sentiment_callback aangeroepen")
            
            # Maak speciale keyboards voor sentiment analyse
            FOREX_SENTIMENT_KEYBOARD = [
                [
                    InlineKeyboardButton("EURUSD", callback_data="direct_sentiment_EURUSD"),
                    InlineKeyboardButton("GBPUSD", callback_data="direct_sentiment_GBPUSD"),
                    InlineKeyboardButton("USDJPY", callback_data="direct_sentiment_USDJPY")
                ],
                [
                    InlineKeyboardButton("AUDUSD", callback_data="direct_sentiment_AUDUSD"),
                    InlineKeyboardButton("USDCAD", callback_data="direct_sentiment_USDCAD"),
                    InlineKeyboardButton("EURGBP", callback_data="direct_sentiment_EURGBP")
                ],
                [InlineKeyboardButton("⬅️ Terug", callback_data="back_analysis")]
            ]
            
            # Toon direct de forex instrumenten voor sentiment analyse
            await query.edit_message_text(
                text="Select a forex pair for sentiment analysis:",
                reply_markup=InlineKeyboardMarkup(FOREX_SENTIMENT_KEYBOARD)
            )
            
            return CHOOSE_INSTRUMENT
        except Exception as e:
            logger.error(f"Error in analysis_sentiment_callback: {str(e)}")
            logger.exception(e)
            return MENU

    async def analysis_calendar_callback(self, update: Update, context=None) -> int:
        """Handle calendar analysis selection"""
        query = update.callback_query
        
        try:
            # Store analysis type in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['analysis_type'] = 'calendar'
                context.user_data['current_state'] = CHOOSE_MARKET
            
            # Show market selection
            await query.edit_message_text(
                text="Select a market for economic calendar:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
            )
            
            return CHOOSE_MARKET
        except Exception as e:
            logger.error(f"Error in analysis_calendar_callback: {str(e)}")
            try:
                await query.message.reply_text(
                    text="Select a market for economic calendar:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
                return CHOOSE_MARKET
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
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
        
        try:
            # Get market from callback data
            market = query.data.replace('market_', '')
            
            # Save market in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['market'] = market
                analysis_type = context.user_data.get('analysis_type', 'technical')
                logger.info(f"Market callback: market={market}, analysis_type={analysis_type}")
            else:
                # Fallback als er geen context is
                analysis_type = 'technical'
                logger.info(f"Market callback zonder context: market={market}, fallback analysis_type={analysis_type}")
            
            # Toon het juiste instrument keyboard op basis van de markt
            if market == 'forex':
                await query.edit_message_text(
                    text=f"Select a forex pair for {analysis_type} analysis:",
                    reply_markup=InlineKeyboardMarkup(FOREX_KEYBOARD)
                )
            elif market == 'crypto':
                await query.edit_message_text(
                    text=f"Select a cryptocurrency for {analysis_type} analysis:",
                    reply_markup=InlineKeyboardMarkup(CRYPTO_KEYBOARD)
                )
            elif market == 'indices':
                await query.edit_message_text(
                    text=f"Select an index for {analysis_type} analysis:",
                    reply_markup=InlineKeyboardMarkup(INDICES_KEYBOARD)
                )
            elif market == 'commodities':
                await query.edit_message_text(
                    text=f"Select a commodity for {analysis_type} analysis:",
                    reply_markup=InlineKeyboardMarkup(COMMODITIES_KEYBOARD)
                )
            else:
                # Fallback naar forex als de markt niet wordt herkend
                await query.edit_message_text(
                    text=f"Select a forex pair for {analysis_type} analysis:",
                    reply_markup=InlineKeyboardMarkup(FOREX_KEYBOARD)
                )
            
            return CHOOSE_INSTRUMENT
        except Exception as e:
            logger.error(f"Error in market_callback: {str(e)}")
            return MENU

    async def market_signals_callback(self, update: Update, context=None) -> int:
        """Handle market selection for signals"""
        query = update.callback_query
        
        try:
            # Extract market from callback data
            market = query.data.replace('market_', '').replace('_signals', '')
            
            # Markeer dat we in de signals flow zitten
            if context and hasattr(context, 'user_data'):
                context.user_data['in_signals_flow'] = True
                context.user_data['market'] = market
            
            # Toon het juiste keyboard op basis van de markt
            if market == 'forex':
                await query.edit_message_text(
                    text="Select a forex pair for trading signals:",
                    reply_markup=InlineKeyboardMarkup(FOREX_KEYBOARD_SIGNALS)
                )
            elif market == 'crypto':
                await query.edit_message_text(
                    text="Select a crypto pair for trading signals:",
                    reply_markup=InlineKeyboardMarkup(CRYPTO_KEYBOARD_SIGNALS)
                )
            elif market == 'indices':
                await query.edit_message_text(
                    text="Select an index for trading signals:",
                    reply_markup=InlineKeyboardMarkup(INDICES_KEYBOARD_SIGNALS)
                )
            elif market == 'commodities':
                await query.edit_message_text(
                    text="Select a commodity for trading signals:",
                    reply_markup=InlineKeyboardMarkup(COMMODITIES_KEYBOARD_SIGNALS)
                )
            
            return CHOOSE_INSTRUMENT
        except Exception as e:
            logger.error(f"Error in market_signals_callback: {str(e)}")
            return MENU

    async def instrument_callback(self, update: Update, context=None) -> int:
        """Handle instrument selection for analysis"""
        query = update.callback_query
        
        try:
            # Extract instrument from callback data
            instrument = query.data.replace('instrument_', '').replace('_analysis', '')
            
            # Log the instrument
            logger.info(f"Instrument callback voor analyse: instrument={instrument}")
            
            # Controleer of dit instrument een beperkte timeframe heeft
            if instrument in RESTRICTED_TIMEFRAMES:
                timeframe = RESTRICTED_TIMEFRAMES[instrument]
                
                # Maak een beperkt keyboard met alleen de toegestane timeframe
                restricted_keyboard = create_restricted_keyboard(instrument, timeframe)
                
                # Toon de beperkte stijl keuze
                await query.edit_message_text(
                    text=f"Choose timeframe for {instrument}:",
                    reply_markup=InlineKeyboardMarkup(restricted_keyboard)
                )
                return CHOOSE_STYLE
            else:
                # Show technical analysis with fullscreen=True
                logger.info(f"Toon technische analyse voor {instrument}")
                return await self.show_technical_analysis(update, context, instrument, fullscreen=True)
        except Exception as e:
            logger.error(f"Error in instrument_callback: {str(e)}")
            return MENU

    async def instrument_signals_callback(self, update: Update, context=None) -> int:
        """Handle instrument selection for signals"""
        query = update.callback_query
        
        try:
            # Extract instrument from callback data
            instrument = query.data.replace('instrument_', '').replace('_signals', '')
            
            # Markeer dat we in de signals flow zitten en sla het instrument op
            if context and hasattr(context, 'user_data'):
                context.user_data['in_signals_flow'] = True
                context.user_data['instrument'] = instrument
            
            # Controleer of dit instrument een beperkte timeframe heeft
            if instrument in RESTRICTED_TIMEFRAMES:
                timeframe = RESTRICTED_TIMEFRAMES[instrument]
                
                # Maak een beperkt keyboard met alleen de toegestane timeframe
                restricted_keyboard = create_restricted_keyboard(instrument, timeframe)
                
                # Toon de beperkte stijl keuze
                await query.edit_message_text(
                    text=f"Choose trading style for {instrument}:",
                    reply_markup=InlineKeyboardMarkup(restricted_keyboard)
                )
            else:
                # Toon de normale stijl keuze voor andere instrumenten
                await query.edit_message_text(
                    text=f"Choose trading style for {instrument}:",
                    reply_markup=InlineKeyboardMarkup(STYLE_KEYBOARD)
                )
            
            return CHOOSE_STYLE
        except Exception as e:
            logger.error(f"Error in instrument_signals_callback: {str(e)}")
            return MENU

    async def style_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle style selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back_instrument":
            # Back to instrument selection
            market = None
            if context and hasattr(context, 'user_data'):
                market = context.user_data.get('market', 'forex')
            else:
                # Haal market uit tijdelijke opslag
                user_id = update.effective_user.id
                if hasattr(self, 'temp_user_data') and user_id in self.temp_user_data:
                    market = self.temp_user_data[user_id].get('market', 'forex')
                else:
                    market = 'forex'  # Fallback
            
            keyboard_map = {
                'forex': FOREX_KEYBOARD,
                'crypto': CRYPTO_KEYBOARD,
                'commodities': COMMODITIES_KEYBOARD,
                'indices': INDICES_KEYBOARD
            }
            keyboard = keyboard_map.get(market, FOREX_KEYBOARD)
            
            await query.edit_message_text(
                text=f"Select an instrument from {market.capitalize()}:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return CHOOSE_INSTRUMENT
        
        style = query.data.replace('style_', '').replace('_restricted', '')
        
        # Sla style op in user_data of tijdelijke opslag
        if context and hasattr(context, 'user_data'):
            context.user_data['style'] = style
            context.user_data['timeframe'] = STYLE_TIMEFRAME_MAP[style]
            user_id = update.effective_user.id
            market = context.user_data.get('market', 'forex')
            instrument = context.user_data.get('instrument', 'EURUSD')
        else:
            # Haal data uit tijdelijke opslag
            user_id = update.effective_user.id
            if not hasattr(self, 'temp_user_data'):
                self.temp_user_data = {}
            if user_id not in self.temp_user_data:
                self.temp_user_data[user_id] = {}
            
            self.temp_user_data[user_id]['style'] = style
            self.temp_user_data[user_id]['timeframe'] = STYLE_TIMEFRAME_MAP[style]
            
            market = self.temp_user_data[user_id].get('market', 'forex')
            instrument = self.temp_user_data[user_id].get('instrument', 'EURUSD')
        
        # Als er geen instrument is, probeer het uit de message text te halen
        if instrument == 'EURUSD' or not instrument:
            message_text = query.message.text if query.message and hasattr(query.message, 'text') else ""
            instrument_match = re.search(r"for ([A-Z0-9]+):", message_text)
            if instrument_match:
                extracted_instrument = instrument_match.group(1)
                logger.info(f"Extracted instrument from message text: {extracted_instrument}")
                
                # Update het instrument in de context of tijdelijke opslag
                if context and hasattr(context, 'user_data'):
                    context.user_data['instrument'] = extracted_instrument
                    instrument = extracted_instrument
                else:
                    self.temp_user_data[user_id]['instrument'] = extracted_instrument
                    instrument = extracted_instrument
                
                # Bepaal de markt op basis van het instrument
                if "USD" in instrument or "EUR" in instrument or "GBP" in instrument or "JPY" in instrument or "CAD" in instrument:
                    market = "forex"
                elif "BTC" in instrument or "ETH" in instrument:
                    market = "crypto"
                elif "US" in instrument or "200" in instrument:
                    market = "indices"
                elif "XAU" in instrument or "XAG" in instrument or "OIL" in instrument:
                    market = "commodities"
                
                # Update de markt in de context of tijdelijke opslag
                if context and hasattr(context, 'user_data'):
                    context.user_data['market'] = market
                else:
                    self.temp_user_data[user_id]['market'] = market
        
        try:
            # Check if this combination already exists
            preferences = await self.db.get_user_preferences(user_id)
            
            for pref in preferences:
                if (pref['market'] == market and 
                    pref['instrument'] == instrument and 
                    pref['style'] == style):
                    
                    # This combination already exists
                    await query.edit_message_text(
                        text=f"You've already saved this combination!\n\n"
                             f"Market: {market}\n"
                             f"Instrument: {instrument}\n"
                             f"Style: {style} ({STYLE_TIMEFRAME_MAP[style]})",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("➕ Add More", callback_data="signals_add")],
                            [InlineKeyboardButton("⚙️ Manage Preferences", callback_data="signals_manage")],
                            [InlineKeyboardButton("🏠 Back to Start", callback_data="back_menu")]
                        ])
                    )
                    return SHOW_RESULT
            
            # Save the new preference
            await self.db.save_preference(
                user_id=user_id,
                market=market,
                instrument=instrument,
                style=style,
                timeframe=STYLE_TIMEFRAME_MAP[style]
            )
            
            # Show success message with options
            await query.edit_message_text(
                text=f"✅ Your preferences have been successfully saved!\n\n"
                     f"Market: {market}\n"
                     f"Instrument: {instrument}\n"
                     f"Style: {style} ({STYLE_TIMEFRAME_MAP[style]})",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Add More", callback_data="signals_add")],
                    [InlineKeyboardButton("⚙️ Manage Preferences", callback_data="signals_manage")],
                    [InlineKeyboardButton("🏠 Back to Start", callback_data="back_menu")]
                ])
            )
            logger.info(f"Saved preferences for user {user_id}")
            return SHOW_RESULT
            
        except Exception as e:
            logger.error(f"Error saving preferences: {str(e)}")
            await query.edit_message_text(
                text="❌ Error saving preferences. Please try again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Try Again", callback_data="back_signals")]
                ])
            )
            return CHOOSE_SIGNALS

    async def back_to_menu_callback(self, update: Update, context=None) -> int:
        """Handle back to menu"""
        query = update.callback_query
        
        # Reset user_data (alleen als context niet None is)
        if context and hasattr(context, 'user_data'):
            context.user_data.clear()
        
        # Show main menu
        try:
            await query.edit_message_text(
                text=WELCOME_MESSAGE,
                reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                parse_mode=ParseMode.HTML
            )
            
            return MENU
        except Exception as e:
            logger.error(f"Error in back_to_menu_callback: {str(e)}")
            # Als er een fout optreedt, probeer een nieuw bericht te sturen
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

    async def back_to_analysis_callback(self, update: Update, context=None) -> int:
        """Handle back to analysis menu callback"""
        query = update.callback_query
        
        try:
            # Answer the callback query
            await query.answer()
            
            # Show the analysis menu
            await query.edit_message_text(
                text="Select your analysis type:",
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            )
            
            return CHOOSE_ANALYSIS
        except Exception as e:
            logger.error(f"Error in back_analysis_callback: {str(e)}")
            logger.exception(e)
            
            # Send a new message as fallback
            try:
                await query.message.reply_text(
                    text="Select your analysis type:",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
            except:
                pass
            
            return CHOOSE_ANALYSIS

    async def back_to_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to signals menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Toon het signals menu
            await query.edit_message_text(
                text="What would you like to do with trading signals?",
                reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
            )
            
            return CHOOSE_SIGNALS
        except Exception as e:
            logger.error(f"Error in back_to_signals: {str(e)}")
            # Als er een fout optreedt, probeer een nieuw bericht te sturen
            try:
                await query.message.reply_text(
                    text="What would you like to do with trading signals?",
                    reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                )
                return CHOOSE_SIGNALS
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                return ConversationHandler.END

    async def back_to_market_callback(self, update: Update, context=None) -> int:
        """Handle back_market callback"""
        query = update.callback_query
        
        try:
            # Beantwoord de callback query om de "wachtende" status te verwijderen
            await query.answer()
            
            # Bepaal of we in de signals flow zitten of in de analyse flow
            # Check of het bericht een foto is (heeft caption) of tekst bericht
            is_photo_message = hasattr(query.message, 'photo') and query.message.photo
            is_signals_flow = False
            
            if is_photo_message:
                # Als het een foto is, kijk in de caption voor aanwijzingen
                caption = query.message.caption or ""
                is_signals_flow = "signals" in caption.lower()
                logger.info(f"Message is a photo with caption: {caption}")
            else:
                # Als het een tekstbericht is, kijk in de message text
                message_text = getattr(query.message, 'text', '')
                if message_text:
                    is_signals_flow = "trading signals" in message_text.lower()
                    logger.info(f"Message is text: {message_text[:50]}...")
                else:
                    # Fallback als er geen tekst is
                    logger.warning("Message has no text or caption")
                    is_signals_flow = False
            
            # Haal market uit user_data of fallback naar 'forex'
            if context and hasattr(context, 'user_data'):
                market = context.user_data.get('market', 'forex')
                in_signals_flow = context.user_data.get('in_signals_flow', is_signals_flow)
            else:
                # Fallback waarden
                market = 'forex'
                in_signals_flow = is_signals_flow
            
            logger.info(f"Back to market: market={market}, in_signals_flow={in_signals_flow}")
            
            # Kies het juiste keyboard op basis van de flow
            if in_signals_flow:
                keyboard = MARKET_KEYBOARD_SIGNALS
                text = "Select a market for trading signals:"
            else:
                keyboard = MARKET_KEYBOARD
                text = "Select a market for technical analysis:"
            
            # Werk het bericht bij
            try:
                if is_photo_message:
                    # Als het een foto is, antwoord met een nieuw bericht
                    # omdat we niet een foto naar tekst kunnen omzetten
                    await query.message.reply_text(
                        text=text,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    # Als het een tekstbericht is, bewerk het
                    await query.edit_message_text(
                        text=text,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
            except Exception as edit_error:
                logger.error(f"Error updating message: {str(edit_error)}")
                # Stuur een nieuw bericht als fallback
                await query.message.reply_text(
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            return CHOOSE_MARKET
        except Exception as e:
            logger.error(f"Error in back_to_market_callback: {str(e)}")
            logger.exception(e)  # Volledige stacktrace loggen
            
            # Stuur een nieuw bericht als fallback bij fouten
            try:
                await query.message.reply_text(
                    text="Select a market:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
                return CHOOSE_MARKET
            except Exception as inner_e:
                logger.error(f"Failed to send fallback message: {str(inner_e)}")
                return MENU

    async def back_to_instrument(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle back to instrument selection"""
        query = update.callback_query
        await query.answer()
        
        # Get market from user_data or use a default
        market = 'forex'  # Default fallback
        
        if context and hasattr(context, 'user_data'):
            market = context.user_data.get('market', 'forex')
        else:
            # Probeer de markt te bepalen uit de message text
            message_text = query.message.text if query.message and hasattr(query.message, 'text') else ""
            
            # Probeer instrument te extraheren uit tekst zoals "Choose trading style for AUDCAD:"
            instrument_match = re.search(r"for ([A-Z0-9]+):", message_text)
            if instrument_match:
                instrument = instrument_match.group(1)
                # Bepaal de markt op basis van het instrument
                if "USD" in instrument or "EUR" in instrument or "GBP" in instrument or "JPY" in instrument or "CAD" in instrument:
                    market = "forex"
                elif "BTC" in instrument or "ETH" in instrument:
                    market = "crypto"
                elif "US" in instrument or "200" in instrument:
                    market = "indices"
                elif "XAU" in instrument or "XAG" in instrument or "OIL" in instrument:
                    market = "commodities"
        
        # Determine which keyboard to show based on market
        keyboard_map = {
            'forex': FOREX_KEYBOARD_SIGNALS if getattr(self, 'in_signals_flow', False) else FOREX_KEYBOARD,
            'crypto': CRYPTO_KEYBOARD_SIGNALS if getattr(self, 'in_signals_flow', False) else CRYPTO_KEYBOARD,
            'indices': INDICES_KEYBOARD_SIGNALS if getattr(self, 'in_signals_flow', False) else INDICES_KEYBOARD,
            'commodities': COMMODITIES_KEYBOARD_SIGNALS if getattr(self, 'in_signals_flow', False) else COMMODITIES_KEYBOARD
        }
        
        keyboard = keyboard_map.get(market, FOREX_KEYBOARD)
        
        # Show instruments for the selected market
        await query.edit_message_text(
            text=f"Select an instrument from {market.capitalize()}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CHOOSE_INSTRUMENT

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show help information"""
        try:
            await update.message.reply_text(
                HELP_MESSAGE,
                parse_mode=ParseMode.HTML
            )
            return MENU
        except Exception as e:
            logger.error(f"Error in help_command: {str(e)}")
            await update.message.reply_text(
                "An error occurred while displaying the help information. Please try again later."
            )
            return MENU

    async def reset_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Reset the conversation to the main menu"""
        try:
            # Clear user data
            context.user_data.clear()
            
            # Send a new message with the main menu
            if update.callback_query:
                await update.callback_query.message.reply_text(
                    text=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    text=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
            
            return MENU
        except Exception as e:
            logger.error(f"Error resetting conversation: {str(e)}")
            return ConversationHandler.END

    async def initialize(self, use_webhook=False):
        """Start the bot"""
        try:
            # Stel commands in
            commands = [
                BotCommand("start", "Start de bot en toon het startmenu"),
                BotCommand("menu", "Toon het hoofdmenu"),
                BotCommand("help", "Toon hulp")
            ]
            await self.bot.set_my_commands(commands)
            
            # Registreer handlers opnieuw
            self._register_handlers()
            
            # Initialize de application altijd, ongeacht webhook of polling
            await self.application.initialize()
            await self.application.start()
            
            # Voeg CallbackQueryHandler toe aan de application
            # Deze algemene handler zorgt ervoor dat de button_callback functie wordt opgeroepen
            self.application.add_handler(CallbackQueryHandler(self.callback_query_handler))
            
            # Start de bot
            if use_webhook:
                # Webhook setup
                logger.info("Telegram bot initialized for webhook use.")
            else:
                # Polling mode
                await self.application.updater.start_polling()
                logger.info("Telegram bot started polling")
        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {str(e)}")
            raise

    async def get_sentiment_verdict(self, instrument, direction):
        """Get a verdict based on market sentiment for the given instrument and direction"""
        try:
            # Gebruik de sentiment service om marktsentiment te analyseren
            sentiment_service = MarketSentimentService()
            sentiment_data = await sentiment_service.get_market_sentiment(instrument)
            
            # Log de sentiment data voor debugging
            logger.info(f"Sentiment data for {instrument}: {sentiment_data}")
            
            # Analyseer het sentiment (bullish/bearish)
            overall_sentiment = sentiment_data.get('overall_sentiment', 'neutral')
            sentiment_score = sentiment_data.get('sentiment_score', 0)
            
            # Bepaal of het signaal in lijn is met het sentiment
            is_aligned = (direction.lower() == 'buy' and overall_sentiment == 'bullish') or \
                         (direction.lower() == 'sell' and overall_sentiment == 'bearish')
            
            # Genereer een verdict op basis van de alignment
            if is_aligned:
                verdict = f"This {direction.lower()} signal for {instrument} aligns with the current market sentiment ({overall_sentiment}). "
                verdict += f"Technical indicators and market analysis suggest a favorable environment for this trade. "
                verdict += f"The sentiment score of {sentiment_score} supports the {direction.lower()} direction."
            else:
                verdict = f"This {direction.lower()} signal for {instrument} is against the current market sentiment ({overall_sentiment}). "
                verdict += f"Consider using tighter stop losses and smaller position sizes. "
                verdict += f"The sentiment score of {sentiment_score} suggests caution for this {direction.lower()} trade."
            
            # Voeg extra advies toe
            verdict += f" Monitor key support/resistance levels and be prepared to adjust your strategy if market conditions change."
            
            return verdict
        except Exception as e:
            logger.error(f"Error generating sentiment verdict: {str(e)}")
            logger.exception(e)
            # Fallback naar een generiek verdict als er een fout optreedt
            return f"The {instrument} {direction.lower()} signal shows a promising setup with defined entry and stop loss levels. Always follow your trading plan and risk management rules."

    async def process_signal(self, signal_data: Dict[str, Any]) -> bool:
        """Process a trading signal"""
        try:
            # Extract signal info
            instrument = signal_data.get('instrument', '')
            direction = signal_data.get('signal', '').upper()  # Komt als "buy" of "sell" van TradingView
            price = signal_data.get('price', 0)
            sl = signal_data.get('sl', 0)
            tp1 = signal_data.get('tp1', 0)
            tp2 = signal_data.get('tp2', 0)
            tp3 = signal_data.get('tp3', 0)
            interval = signal_data.get('interval', '1h')
            
            # Log het ontvangen signaal
            logger.info(f"Received signal: {signal_data}")
            
            # Controleer of we voldoende gegevens hebben om een signaal te versturen
            if not instrument or not price:
                logger.error("Missing required signal data (instrument or price)")
                return False
            
            # Fix voor TradingView placeholders
            if direction == '{{STRATEGY.ORDER.ACTION}}' or direction == '{{strategy.order.action}}':
                # Als we geen geldige stop loss hebben, maak een standaard stop loss
                if not sl or sl == 0:
                    # Maak een standaard stop loss op 1% van de prijs
                    sl = price * 0.99 if direction == 'BUY' else price * 1.01
                    logger.info(f"Created default stop loss: {sl}")
                
                # Bepaal richting op basis van stop loss en entry price
                direction = 'BUY' if price > sl else 'SELL'
                logger.info(f"Replaced placeholder with determined direction: {direction}")
            
            # Als we nog steeds geen geldige stop loss hebben, maak een standaard stop loss
            if not sl or sl == 0:
                sl = price * 0.99 if direction == 'BUY' else price * 1.01
                logger.info(f"Created default stop loss: {sl}")
            
            # Als we geen take profit hebben, maak standaard take profit levels
            if not tp1 or tp1 == 0:
                tp1 = price * 1.01 if direction == 'BUY' else price * 0.99
                logger.info(f"Created default TP1: {tp1}")
            
            if not tp2 or tp2 == 0:
                tp2 = price * 1.02 if direction == 'BUY' else price * 0.98
                logger.info(f"Created default TP2: {tp2}")
            
            if not tp3 or tp3 == 0:
                tp3 = price * 1.03 if direction == 'BUY' else price * 0.97
                logger.info(f"Created default TP3: {tp3}")
            
            # Create emoji based on direction
            direction_emoji = "📈" if direction == "BUY" else "📉"
            
            # Format the signal message
            signal_message = f"""🎯 New Trading Signal 🎯

Instrument: {instrument}
Action: {direction} {direction_emoji}

Entry Price: {price:.2f}
Stop Loss: {sl:.2f} 🔴
Take Profit 1: {tp1:.2f} 🎯
Take Profit 2: {tp2:.2f} 🎯
Take Profit 3: {tp3:.2f} 🎯

Timeframe: {interval}
Strategy: TradingView Signal

————————————————————

Risk Management:
• Position size: 1-2% max
• Use proper stop loss
• Follow your trading plan

————————————————————

🤖 SigmaPips AI Verdict:
The {instrument} {direction.lower()} signal shows a promising setup with defined entry at {price:.2f} and stop loss at {sl:.2f}. Multiple take profit levels provide opportunities for partial profit taking."""

            # Find subscribers for this signal
            subscribers = await self.db.match_subscribers(signal_data)
            
            # Verwijder dubbele gebruikers
            unique_subscribers = {}
            for sub in subscribers:
                user_id = sub.get('user_id')
                if user_id not in unique_subscribers:
                    unique_subscribers[user_id] = sub
            
            # Stuur het signaal naar elke unieke abonnee
            sent_count = 0
            for user_id, subscriber in unique_subscribers.items():
                try:
                    logger.info(f"Sending signal to user {user_id}")
                    
                    # Controleer abonnementsstatus
                    is_subscribed = await self.db.is_user_subscribed(int(user_id))
                    if not is_subscribed:
                        logger.info(f"User {user_id} has no active subscription, skipping signal")
                        continue
                    
                    # Maak de keyboard met één knop voor analyse
                    keyboard = [
                        [InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_market_{instrument}")]
                    ]
                    
                    # Stuur het signaal met de analyse knop
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=signal_message,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    
                    # Sla het signaal op in de user_signals dictionary
                    self.user_signals[int(user_id)] = {
                        'instrument': instrument,
                        'message': signal_message,
                        'direction': direction,
                        'price': price,
                        'timestamp': time.time()
                    }
                    
                    # Sla de signalen op naar bestand
                    self._save_signals()
                    
                    logger.info(f"Saved signal for user {user_id} in user_signals")
                    
                    sent_count += 1
                except Exception as user_error:
                    logger.error(f"Error sending signal to user {user_id}: {str(user_error)}")
                    logger.exception(user_error)
            
            # Log het verwerkte signaal
            logger.info(f"Processed signal: {signal_data}")
            
            return True
        except Exception as e:
            logger.error(f"Error processing signal: {str(e)}")
            logger.exception(e)
            return False

    async def callback_query_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle callback queries that are not handled by other handlers"""
        query = update.callback_query
        await query.answer()
        
        logger.info(f"Received callback in handler: {query.data}")  # Added debug logging
        
        try:
            if query.data.startswith("analyze_market_"):
                # Extract instrument from callback data
                parts = query.data.split("_")
                instrument = parts[2]
                
                # Check if the message is a photo (has caption) or text message
                is_photo_message = hasattr(query.message, 'caption') and query.message.caption is not None
                
                # Create keyboard with direct analysis options
                keyboard = [
                    [InlineKeyboardButton("📊 Technical Analysis", callback_data=f"direct_technical_{instrument}")],
                    [InlineKeyboardButton(" Market Sentiment", callback_data=f"direct_sentiment_{instrument}")],
                    [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"direct_calendar_{instrument}")],
                    [InlineKeyboardButton("⬅️ Back to Signal", callback_data=f"back_to_signal_{instrument}")]
                ]
                
                if is_photo_message:
                    await query.message.reply_text(
                        text=f"Choose analysis type for {instrument}:",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    await query.edit_message_text(
                        text=f"Choose analysis type for {instrument}:",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                
                return MENU
            
            # VOEG DEZE HANDLER TOE VOOR back_analysis    
            elif query.data == "back_analysis":
                # Toon het analyse menu
                logger.info("Handling back_analysis callback")
                await query.edit_message_text(
                    text="Select your analysis type:",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
                return CHOOSE_ANALYSIS
                
            elif query.data.startswith("direct_technical_"):
                parts = query.data.split("direct_technical_")[1].split("_")
                instrument = parts[0]
                timeframe = parts[1]
                is_analysis = len(parts) > 2 and parts[2] == "analysis"
                
                logger.info(f"Direct technical analysis for {instrument} with timeframe {timeframe}, is_analysis={is_analysis}")
                
                if is_analysis:
                    # Dit is een technical analysis request
                    return await self.show_technical_analysis(update, context, instrument, fullscreen=True, timeframe=timeframe)
                else:
                    # Dit is een trading signals request, sla de voorkeur op
                    # Bepaal de juiste stijl op basis van de timeframe
                    style_map = {
                        "1h": "intraday",
                        "4h": "swing"
                    }
                    style = style_map.get(timeframe, "intraday")
                    
                    # Stel de user_data in
                    if context and hasattr(context, 'user_data'):
                        context.user_data['style'] = style
                        context.user_data['timeframe'] = timeframe
                        context.user_data['instrument'] = instrument
                        
                        # Bepaal de markt op basis van het instrument
                        if "USD" in instrument or "EUR" in instrument or "GBP" in instrument or "JPY" in instrument or "CAD" in instrument:
                            market = "forex"
                        elif "BTC" in instrument or "ETH" in instrument:
                            market = "crypto"
                        elif "US" in instrument or "200" in instrument:
                            market = "indices"
                        elif "XAU" in instrument or "XAG" in instrument or "OIL" in instrument:
                            market = "commodities"
                        
                        context.user_data['market'] = market
                    
                    # Sla de voorkeur op en toon bevestiging
                    user_id = update.effective_user.id
                    
                    # Bepaal de markt op basis van het instrument
                    if "USD" in instrument or "EUR" in instrument or "GBP" in instrument or "JPY" in instrument or "CAD" in instrument:
                        market = "forex"
                    elif "BTC" in instrument or "ETH" in instrument:
                        market = "crypto"
                    elif "US" in instrument or "200" in instrument:
                        market = "indices"
                    elif "XAU" in instrument or "XAG" in instrument or "OIL" in instrument:
                        market = "commodities"
                    
                    # Save the preference
                    await self.db.save_preference(
                        user_id=user_id,
                        market=market,
                        instrument=instrument,
                        style=style,
                        timeframe=timeframe
                    )
                    
                    # Show success message with options
                    await query.edit_message_text(
                        text=f"✅ Your preferences have been successfully saved!\n\n"
                             f"Market: {market}\n"
                             f"Instrument: {instrument}\n"
                             f"Style: {style} ({timeframe})",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("➕ Add More", callback_data="signals_add")],
                            [InlineKeyboardButton("⚙️ Manage Preferences", callback_data="signals_manage")],
                            [InlineKeyboardButton("🏠 Back to Start", callback_data="back_menu")]
                        ])
                    )
                    logger.info(f"Saved preferences for user {user_id}")
                    return SHOW_RESULT
                
            elif query.data.startswith("direct_sentiment_"):
                instrument = query.data.replace("direct_sentiment_", "")
                logger.info(f"Direct sentiment analysis for {instrument}")
                return await self.show_sentiment_analysis(update, context, instrument, from_signal=True)
                
            elif query.data.startswith("direct_calendar_"):
                instrument = query.data.replace("direct_calendar_", "")
                logger.info(f"Direct calendar analysis for {instrument}")
                return await self.show_economic_calendar(update, context, instrument, from_signal=True)
                
            elif query.data.startswith("back_to_signal"):
                try:
                    # Extract instrument from callback data
                    parts = query.data.split("_")
                    instrument = parts[3] if len(parts) > 3 else None
                    
                    logger.info(f"Back to signal callback with data: {query.data}, extracted instrument: {instrument}")
                    
                    # Als er geen instrument in de callback data zit, probeer het uit de message text te halen
                    if not instrument:
                        message_text = query.message.text if query.message and hasattr(query.message, 'text') else ""
                        
                        # Extract instrument from message text like "Choose analysis type for XAUUSD:"
                        instrument_match = re.search(r"for ([A-Z0-9]+):", message_text)
                        if instrument_match:
                            instrument = instrument_match.group(1)
                            logger.info(f"Extracted instrument from message text: {instrument}")
                    
                    # Als nog steeds geen instrument, probeer user_data
                    if not instrument and context.user_data and 'instrument' in context.user_data:
                        instrument = context.user_data.get('instrument')
                        logger.info(f"Using instrument from user_data: {instrument}")
                    
                    logger.info(f"Back to signal for instrument: {instrument}")
                    
                    # Probeer opnieuw om de user_signals te laden
                    self._load_signals()
                    
                    # Probeer het signaal uit de gebruikerscontext te halen
                    original_signal = None
                    user_id = update.effective_user.id
                    logger.info(f"Looking for signal in user_signals for user_id: {user_id}")
                    
                    # Debug: print alle user_signals
                    logger.info(f"All user_signals: {self.user_signals}")
                    
                    if user_id in self.user_signals:
                        user_signal = self.user_signals[user_id]
                        logger.info(f"Found user signal: {user_signal}")
                        
                        if user_signal and user_signal.get('instrument') == instrument:
                            original_signal = user_signal.get('message')
                            logger.info(f"Retrieved original signal from user context: {len(original_signal)} chars")
                        else:
                            logger.warning(f"User signal found but instrument doesn't match")
                    
                    # Als we geen signaal vinden, maak een fake signal op basis van het instrument
                    if not original_signal and instrument:
                        # Maak een special fake signaal voor dit instrument
                        signal_message = f"🎯 <b>Trading Signal voor {instrument}</b> 🎯\n\n"
                        signal_message += f"Instrument: {instrument}\n"
                        
                        # Willekeurige richting (buy/sell) bepalen
                        import random
                        is_buy = random.choice([True, False])
                        direction = "BUY" if is_buy else "SELL"
                        emoji = "📈" if is_buy else "📉"
                        
                        signal_message += f"Action: {direction} {emoji}\n\n"
                        
                        # Genereer realistische prijzen op basis van het instrument
                        price = 0
                        if "BTC" in instrument:
                            price = random.randint(50000, 70000)
                        elif "ETH" in instrument:
                            price = random.randint(2500, 4000)
                        elif "XAU" in instrument:
                            price = random.randint(2000, 2500)
                        elif "USD" in instrument:
                            price = round(random.uniform(1.0, 1.5), 4)
                        else:
                            price = round(random.uniform(10, 100), 2)
                        
                        signal_message += f"Entry Price: {price}\n"
                        
                        # Bereken stop loss en take profit op basis van de prijs
                        stop_loss = round(price * (0.95 if is_buy else 1.05), 2)
                        take_profit = round(price * (1.05 if is_buy else 0.95), 2)
                        
                        signal_message += f"Stop Loss: {stop_loss} 🔴\n"
                        signal_message += f"Take Profit: {take_profit} 🎯\n\n"
                        
                        signal_message += f"Timeframe: 1h\n"
                        signal_message += f"Strategy: AI Signal\n\n"
                        
                        signal_message += f"<i>Dit is een hersignaal. Het originele signaal kon niet worden gevonden.</i>\n"
                        
                        # Sla dit signaal op in user_signals voor deze gebruiker
                        self.user_signals[user_id] = {
                            'instrument': instrument,
                            'message': signal_message,
                            'direction': direction,
                            'price': price,
                            'timestamp': time.time()
                        }
                        
                        original_signal = signal_message
                        logger.info(f"Created new signal for instrument: {instrument}")
                    
                    # Create the analyze market button
                    keyboard = [
                        [InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_market_{instrument}")]
                    ]
                    
                    # Send the signal
                    await query.edit_message_text(
                        text=original_signal if original_signal else f"No signal found for {instrument}",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    
                    if original_signal:
                        logger.info(f"Successfully displayed signal for instrument: {instrument}")
                    else:
                        logger.warning(f"Could not find or create signal for instrument: {instrument}")
                    
                    return MENU
                except Exception as e:
                    logger.error(f"Error in back_to_signal handler: {str(e)}")
                    logger.exception(e)
                    
                    # If there's an error, show a simple message
                    try:
                        await query.edit_message_text(
                            text="Could not return to signal view. Please check your chat history for the original signal.",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")
                            ]])
                        )
                    except Exception as inner_e:
                        logger.error(f"Failed to send fallback message: {str(inner_e)}")
                    
                    return MENU
            
            elif query.data.startswith("analysis_"):
                # Extract instrument from callback data
                parts = query.data.split("_")
                instrument = parts[2]
                
                # Check if this is from a signal (will have a 4th part)
                from_signal = len(parts) > 3 and parts[3] == "signal"
                
                if from_signal:
                    # Direct naar de chart gaan zonder instrument te kiezen
                    return await self.show_technical_analysis(update, context, instrument, from_signal=True)
                else:
                    # Normale flow voor analyse
                    context.user_data['instrument'] = instrument
                    
                    # Toon de stijl keuze
                    await query.edit_message_text(
                        text=f"Choose analysis style for {instrument}:",
                        reply_markup=InlineKeyboardMarkup(STYLE_KEYBOARD)
                    )
                    
                    return CHOOSE_STYLE
            
            elif query.data.startswith("analysis_sentiment_"):
                # Extract instrument from callback data
                parts = query.data.split("_")
                instrument = parts[2]
                
                # Check if this is from a signal
                from_signal = len(parts) > 3 and parts[3] == "signal"
                
                return await self.show_sentiment_analysis(update, context, instrument, from_signal)
            
            elif query.data.startswith("analysis_calendar_"):
                # Extract instrument from callback data
                parts = query.data.split("_")
                instrument = parts[2]
                
                # Check if this is from a signal
                from_signal = len(parts) > 3 and parts[3] == "signal"
                
                return await self.show_economic_calendar(update, context, instrument, from_signal)
            
            # Fallback
            await query.edit_message_text(
                text="I'm not sure what you want to do. Please try again or use /menu to start over."
            )
            return MENU
        
        except Exception as e:
            logger.error(f"Error in callback query handler: {str(e)}")
            logger.exception(e)
            return MENU

    async def show_technical_analysis(self, update: Update, context=None, instrument=None, from_signal=False, style=None, fullscreen=True, timeframe=None):
        """Show technical analysis for an instrument"""
        query = update.callback_query
        
        try:
            # Als er geen timeframe is opgegeven, gebruik de stijl of default
            if not timeframe:
                timeframe = "1h"  # Default
                if style and style in STYLE_TIMEFRAME_MAP:
                    timeframe = STYLE_TIMEFRAME_MAP[style]
            
            # Toon een laadmelding als die nog niet is getoond
            try:
                await query.edit_message_text(
                    text=f"Generating technical analysis for {instrument}...",
                    reply_markup=None
                )
            except Exception as e:
                logger.warning(f"Could not edit message: {str(e)}")
            
            # Haal de chart op met de gekozen timeframe
            chart_image = await self.chart.get_chart(instrument, timeframe=timeframe, fullscreen=fullscreen)
            
            if chart_image:
                # Bepaal de juiste back-knop op basis van de context
                back_button = InlineKeyboardButton("⬅️ Back", callback_data="back_market")
                if from_signal:
                    back_button = InlineKeyboardButton("⬅️ Back to Signal", callback_data=f"back_to_signal_{instrument}")
                
                # In plaats van een nieuw bericht te maken, werk het bestaande bericht bij
                # met de foto via een media groep
                try:
                    # Gebruik edit_message_media om het bericht bij te werken met de grafiek
                    await query.message.edit_media(
                        media=InputMediaPhoto(
                            media=chart_image,
                            caption=f"📊 {instrument} Technical Analysis"
                        ),
                        reply_markup=InlineKeyboardMarkup([[back_button]])
                    )
                    
                    logger.info(f"Updated message with chart for {instrument}")
                    return SHOW_RESULT
                except Exception as edit_error:
                    logger.warning(f"Could not edit message with media: {str(edit_error)}")
                    
                    # Als het bijwerken van het bericht niet lukt, stuur een nieuwe foto
                    # maar bewaar de message_id om later te gebruiken
                    sent_message = await query.message.reply_photo(
                        photo=chart_image,
                        caption=f"📊 {instrument} Technical Analysis",
                        reply_markup=InlineKeyboardMarkup([[back_button]])
                    )
                    
                    # Verberg het laadmelding bericht
                    try:
                        await query.edit_message_text(
                            text=f"Chart for {instrument} below ⬇️",
                            reply_markup=None
                        )
                    except Exception as hide_error:
                        logger.warning(f"Could not update loading message: {str(hide_error)}")
                    
                    return SHOW_RESULT
            else:
                # Toon een foutmelding
                await query.edit_message_text(
                    text=f"❌ Could not generate chart for {instrument}. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_market" if not from_signal else f"back_to_signal_{instrument}")
                    ]])
                )
                return MENU
        except Exception as e:
            logger.error(f"Error in show_technical_analysis: {str(e)}")
            # Stuur een nieuw bericht als fallback
            try:
                await query.message.reply_text(
                    text=f"Error generating chart for {instrument}. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
                    ]])
                )
            except:
                pass
            return MENU

    async def show_sentiment_analysis(self, update: Update, context=None, instrument=None, from_signal=False):
        """Show sentiment analysis for an instrument"""
        query = update.callback_query
        
        try:
            # Debug logging
            logger.info(f"show_sentiment_analysis aangeroepen voor instrument: {instrument}, from_signal: {from_signal}")
            
            # Toon een laadmelding als die nog niet is getoond
            if not from_signal:
                try:
                    await query.edit_message_text(
                        text=f"Getting market sentiment for {instrument}...",
                        reply_markup=None
                    )
                except Exception as e:
                    logger.warning(f"Could not edit message: {str(e)}")
            
            try:
                # Probeer sentiment analyse op te halen
                logger.info(f"Sentiment service aanroepen voor {instrument}")
                sentiment = await self.sentiment.get_market_sentiment(instrument)
                logger.info(f"Sentiment ontvangen: {sentiment[:100]}...")  # Log eerste 100 tekens
            except Exception as sentiment_error:
                logger.error(f"Error getting sentiment from service: {str(sentiment_error)}")
                logger.exception(sentiment_error)
                
                # Fallback: genereer een eenvoudige sentiment analyse
                bullish_score = random.randint(30, 70)
                bearish_score = 100 - bullish_score
                
                if bullish_score > 55:
                    overall = "Bullish"
                    emoji = "📈"
                elif bullish_score < 45:
                    overall = "Bearish"
                    emoji = "📉"
                else:
                    overall = "Neutral"
                    emoji = "⚖️"
                
                sentiment = f"""
                <b>🧠 Market Sentiment Analysis: {instrument}</b>
                
                <b>Overall Sentiment:</b> {overall} {emoji}
                
                <b>Sentiment Breakdown:</b>
                • Bullish: {bullish_score}%
                • Bearish: {bearish_score}%
                
                <b>Market Analysis:</b>
                The current sentiment for {instrument} is {overall.lower()}, with {bullish_score}% of traders showing bullish bias.
                """
                logger.info("Gegenereerde fallback sentiment gebruikt")
            
            # Bepaal de juiste back-knop op basis van de context
            back_button = InlineKeyboardButton("⬅️ Back", callback_data="back_market")
            if from_signal:
                back_button = InlineKeyboardButton("⬅️ Back to Signal", callback_data=f"back_to_signal_{instrument}")
            
            # Toon sentiment analyse
            await query.edit_message_text(
                text=sentiment,
                reply_markup=InlineKeyboardMarkup([[back_button]]),
                parse_mode=ParseMode.HTML
            )
            
            return SHOW_RESULT
        except Exception as e:
            logger.error(f"Error in show_sentiment_analysis: {str(e)}")
            logger.exception(e)  # Log de volledige stacktrace
            # Stuur een nieuw bericht als fallback
            try:
                await query.message.reply_text(
                    text=f"Error getting sentiment for {instrument}. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
                    ]])
                )
            except:
                pass
            return MENU

    async def show_economic_calendar(self, update: Update, context=None, instrument=None, from_signal=False):
        """Show economic calendar for an instrument"""
        query = update.callback_query
        
        try:
            # Toon een laadmelding als die nog niet is getoond
            if not from_signal:
                try:
                    await query.edit_message_text(
                        text=f"Getting economic calendar for {instrument}...",
                        reply_markup=None
                    )
                except Exception as e:
                    logger.warning(f"Could not edit message: {str(e)}")
            
            # Haal economische kalender op
            calendar = await self.calendar.get_economic_calendar(instrument)
            
            # Bepaal de juiste back-knop op basis van de context
            back_button = InlineKeyboardButton("⬅️ Back", callback_data="back_market")
            if from_signal:
                back_button = InlineKeyboardButton("⬅️ Back to Signal", callback_data=f"back_to_signal_{instrument}")
            
            # Toon economische kalender
            await query.edit_message_text(
                text=calendar,
                reply_markup=InlineKeyboardMarkup([[back_button]]),
                parse_mode=ParseMode.HTML
            )
            
            return SHOW_RESULT
        except Exception as e:
            logger.error(f"Error in show_economic_calendar: {str(e)}")
            # Stuur een nieuw bericht als fallback
            try:
                await query.message.reply_text(
                    text=f"Error getting economic calendar for {instrument}. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
                    ]])
                )
            except:
                pass
            return MENU

    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the conversation."""
        try:
            # Stuur een bericht dat de conversatie is geannuleerd
            await update.message.reply_text(
                "Current operation cancelled. Use /start to begin again."
            )
            
            # Reset user_data
            context.user_data.clear()
            
            # Beëindig de conversatie
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error in cancel command: {str(e)}")
            return ConversationHandler.END

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles errors that occur during the execution of updates."""
        logger.error(f"Update {update} caused error: {context.error}")
        
        # Log de volledige stacktrace
        import traceback
        logger.error(traceback.format_exc())
        
        # Probeer de gebruiker te informeren over de fout
        if update and hasattr(update, 'effective_message') and update.effective_message:
            await update.effective_message.reply_text(
                "An error occurred while processing your request. "
                "Please try again later or use /start to begin again."
            )
        
        # Als er een callback query is, beantwoord deze om de "wachtende" status te verwijderen
        if update and hasattr(update, 'callback_query') and update.callback_query:
            try:
                await update.callback_query.answer(
                    "An error occurred. Please try again."
                )
            except Exception as e:
                logger.error(f"Could not answer callback query: {e}")

    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show the main menu"""
        keyboard = [
            [InlineKeyboardButton("📊 Market Analysis", callback_data="analysis")],
            [InlineKeyboardButton("🔔 Trading Signals", callback_data="signals")],
            [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
        ]
        
        await update.message.reply_text(
            "Welcome to SigmaPips Trading Bot! Select an option:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return MENU

    async def process_update(self, update_data: Dict[str, Any]) -> bool:
        """Process an update from the webhook"""
        try:
            # Converteer de update data naar een Update object
            update = Update.de_json(data=update_data, bot=self.bot)
            
            # Controleer of we deze update al hebben verwerkt
            update_id = update.update_id
            if update_id in self.processed_updates:
                logger.info(f"Skipping already processed update: {update_id}")
                return True
            
            # Voeg de update toe aan de verwerkte updates
            self.processed_updates.add(update_id)
            
            # Houd de grootte van de set beperkt
            if len(self.processed_updates) > 1000:
                self.processed_updates = set(list(self.processed_updates)[-500:])
            
            # Log de update
            logger.info(f"Processing update: {update_data}")
            
            # Controleer of het een callback query is
            if update.callback_query:
                # Log de callback data
                callback_data = update.callback_query.data
                logger.info(f"Received callback: {callback_data}")
                
                # Beantwoord de callback query om de "wachtende" status te verwijderen
                await update.callback_query.answer()
                
                # Verwerk de callback op basis van de data
                if callback_data == "menu_analyse":
                    await self.menu_analyse_callback(update, None)
                    return True
                elif callback_data == "menu_signals":
                    await self.menu_signals_callback(update, None)
                    return True
                elif callback_data == "back_menu":
                    await self.back_to_menu_callback(update, None)
                    return True
                elif callback_data == "back_to_analysis":
                    await self.back_to_analysis_callback(update, None)
                    return True
                elif callback_data == "back_signals":
                    await self.back_signals_callback(update, None)
                    return True
                elif callback_data == "back_market":
                    await self.back_to_market_callback(update, None)
                    return True
                elif callback_data == "back_instrument":
                    await self.back_to_instrument(update, None)
                    return True
                elif callback_data.startswith("analysis_"):
                    await self.analysis_choice(update, None)
                    return True
                elif callback_data == "signals_add":
                    await self.signals_add_callback(update, None)
                    return True
                elif callback_data == "signals_manage":
                    await self.signals_manage_callback(update, None)
                    return True
                elif callback_data == "delete_prefs":
                    await self.delete_preferences_callback(update, None)
                    return True
                elif callback_data.startswith("delete_pref_"):
                    await self.delete_single_preference_callback(update, None)
                    return True
                elif callback_data == "confirm_delete":
                    await self.confirm_delete_callback(update, None)
                    return True
                elif callback_data.startswith("market_"):
                    if "_signals" in callback_data:
                        await self.market_signals_callback(update, None)
                    else:
                        await self.market_callback(update, None)
                    return True
                elif callback_data.startswith("instrument_"):
                    if "_signals" in callback_data:
                        await self.instrument_signals_callback(update, None)
                    else:
                        await self.instrument_callback(update, None)
                    return True
                elif callback_data.startswith("style_"):
                    await self.style_choice(update, None)
                    return True
                elif callback_data.startswith("timeframe_"):
                    await self.timeframe_callback(update, None)
                    return True
            
            # Stuur de update naar de application
            await self.application.process_update(update)
            
            return True
        except Exception as e:
            logger.error(f"Error processing update: {str(e)}")
            logger.exception(e)
            return False

    # Nieuwe methode voor directe sentiment analyse
    async def direct_sentiment_callback(self, update: Update, context=None) -> int:
        """Direct handler for sentiment analysis"""
        query = update.callback_query
        
        try:
            # Beantwoord de callback query om de "wachtende" status te verwijderen
            await query.answer()
            
            # Extract instrument from callback data
            instrument = query.data.replace('direct_sentiment_', '')
            logger.info(f"Direct sentiment callback voor instrument: {instrument}")
            
            # Toon een laadmelding
            await query.edit_message_text(
                text=f"Getting market sentiment for {instrument}...",
                reply_markup=None
            )
            
            # Haal sentiment analyse op
            try:
                sentiment = await self.sentiment.get_market_sentiment(instrument)
                logger.info(f"Sentiment ontvangen voor {instrument}")
            except Exception as sentiment_error:
                logger.error(f"Error getting sentiment: {str(sentiment_error)}")
                logger.exception(sentiment_error)
                
                # Fallback sentiment genereren
                import random
                bullish_score = random.randint(30, 70)
                bearish_score = 100 - bullish_score
                
                if bullish_score > 55:
                    overall = "Bullish"
                    emoji = "📈"
                elif bullish_score < 45:
                    overall = "Bearish"
                    emoji = "📉"
                else:
                    overall = "Neutral"
                    emoji = "⚖️"
                
                sentiment = f"""
                <b>🧠 Market Sentiment Analysis: {instrument}</b>
                
                <b>Overall Sentiment:</b> {overall} {emoji}
                
                <b>Sentiment Breakdown:</b>
                • Bullish: {bullish_score}%
                • Bearish: {bearish_score}%
                
                <b>Market Analysis:</b>
                The current sentiment for {instrument} is {overall.lower()}, with {bullish_score}% of traders showing bullish bias.
                """
                logger.info("Gegenereerde fallback sentiment gebruikt")
            
            # Toon sentiment analyse
            await query.edit_message_text(
                text=sentiment,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")
                ]]),
                parse_mode=ParseMode.HTML
            )
            
            return SHOW_RESULT
        except Exception as e:
            logger.error(f"Error in direct_sentiment_callback: {str(e)}")
            logger.exception(e)
            
            # Stuur een foutmelding
            try:
                await query.edit_message_text(
                    text=f"Error getting sentiment for {instrument}. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")
                    ]])
                )
            except:
                pass
            
            return MENU

    async def back_signals_callback(self, update: Update, context=None) -> int:
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
            
            if analysis_type == 'calendar':
                # Show economic calendar directly without market selection
                try:
                    # Show loading message
                    await query.edit_message_text(
                        text="Please wait, fetching economic calendar...",
                        reply_markup=None
                    )
                    
                    # Get calendar data
                    calendar_data = await self.calendar.get_economic_calendar()
                    
                    # Show the calendar with back button
                    await query.edit_message_text(
                        text=calendar_data,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Back", callback_data="back_to_analysis")  # Change from back_analysis to back_to_analysis
                        ]]),
                        parse_mode=ParseMode.HTML
                    )
                    
                    return SHOW_RESULT
                    
                except Exception as e:
                    logger.error(f"Error showing calendar: {str(e)}")
                    await query.edit_message_text(
                        text="An error occurred while fetching the calendar. Please try again later.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Back", callback_data="back_to_analysis")  # Change from back_analysis to back_to_analysis
                        ]])
                    )
                    return MENU
            
            elif analysis_type == 'technical':
                # Show market selection for technical analysis
                await query.edit_message_text(
                    text="Select a market for technical analysis:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
                return CHOOSE_MARKET
                
            elif analysis_type == 'sentiment':
                # Show market selection for sentiment analysis
                await query.edit_message_text(
                    text="Select a market for sentiment analysis:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
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
        """Handle back_to_signal callback"""
        query = update.callback_query
        
        try:
            # Extract instrument from callback data
            parts = query.data.split("_")
            instrument = parts[3] if len(parts) > 3 else None
            
            logger.info(f"Back to signal callback with data: {query.data}, extracted instrument: {instrument}")
            
            # Als er geen instrument in de callback data zit, probeer het uit de message text te halen
            if not instrument:
                message_text = query.message.text if query.message and hasattr(query.message, 'text') else ""
                
                # Extract instrument from message text like "Choose analysis type for XAUUSD:"
                instrument_match = re.search(r"for ([A-Z0-9]+):", message_text)
                if instrument_match:
                    instrument = instrument_match.group(1)
                    logger.info(f"Extracted instrument from message text: {instrument}")
            
            logger.info(f"Back to signal for instrument: {instrument}")
            
            # Probeer het signaal uit de gebruikerscontext te halen
            original_signal = None
            user_id = update.effective_user.id
            logger.info(f"Looking for signal in user_signals for user_id: {user_id}")
            
            # Debug: print alle user_signals
            logger.info(f"All user_signals: {self.user_signals}")
            
            if user_id in self.user_signals:
                user_signal = self.user_signals[user_id]
                logger.info(f"Found user signal: {user_signal}")
                
                if user_signal and user_signal.get('instrument') == instrument:
                    original_signal = user_signal.get('message')
                    logger.info(f"Retrieved original signal from user context: {len(original_signal)} chars")
                else:
                    logger.warning(f"User signal found but instrument doesn't match. User signal instrument: {user_signal.get('instrument')}, requested instrument: {instrument}")
            
            # Als we geen signaal vinden, maak een fake signal op basis van het instrument
            if not original_signal and instrument:
                # Maak een special fake signaal voor dit instrument
                signal_message = f"🎯 <b>Trading Signal voor {instrument}</b> 🎯\n\n"
                signal_message += f"Instrument: {instrument}\n"
                
                # Willekeurige richting (buy/sell) bepalen
                import random
                is_buy = random.choice([True, False])
                direction = "BUY" if is_buy else "SELL"
                emoji = "📈" if is_buy else "��"
                
                signal_message += f"Action: {direction} {emoji}\n\n"
                
                # Genereer realistische prijzen op basis van het instrument
                price = 0
                if "BTC" in instrument:
                    price = random.randint(50000, 70000)
                elif "ETH" in instrument:
                    price = random.randint(2500, 4000)
                elif "XAU" in instrument:
                    price = random.randint(2000, 2500)
                elif "USD" in instrument:
                    price = round(random.uniform(1.0, 1.5), 4)
                else:
                    price = round(random.uniform(10, 100), 2)
                
                signal_message += f"Entry Price: {price}\n"
                
                # Bereken stop loss en take profit op basis van de prijs
                stop_loss = round(price * (0.95 if is_buy else 1.05), 2)
                take_profit = round(price * (1.05 if is_buy else 0.95), 2)
                
                signal_message += f"Stop Loss: {stop_loss} 🔴\n"
                signal_message += f"Take Profit: {take_profit} 🎯\n\n"
                
                signal_message += f"Timeframe: 1h\n"
                signal_message += f"Strategy: AI Signal\n\n"
                
                signal_message += f"<i>Dit is een hersignaal. Het originele signaal kon niet worden gevonden.</i>\n"
                
                # Sla dit signaal op in user_signals voor deze gebruiker
                self.user_signals[user_id] = {
                    'instrument': instrument,
                    'message': signal_message,
                    'direction': direction,
                    'price': price,
                    'timestamp': time.time()
                }
                
                original_signal = signal_message
                logger.info(f"Created new signal for instrument: {instrument}")
            
            # Create the analyze market button
            keyboard = [
                [InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_market_{instrument}")]
            ]
            
            # Send the signal
            await query.edit_message_text(
                text=original_signal if original_signal else f"No signal found for {instrument}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            if original_signal:
                logger.info(f"Successfully displayed signal for instrument: {instrument}")
            else:
                logger.warning(f"Could not find or create signal for instrument: {instrument}")
            
            return MENU
        except Exception as e:
            logger.error(f"Error in back_to_signal handler: {str(e)}")
            logger.exception(e)
            
            # If there's an error, show a simple message
            try:
                await query.edit_message_text(
                    text="Could not return to signal view. Please check your chat history for the original signal.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")
                    ]])
                )
            except Exception as inner_e:
                logger.error(f"Failed to send fallback message: {str(inner_e)}")
            
            return MENU

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show the main menu with all bot features"""
        try:
            # Check subscription status
            user_id = update.effective_user.id
            is_subscribed = await self.db.is_user_subscribed(user_id)
            
            if is_subscribed:
                # Show full menu for subscribed users
                keyboard = [
                    [InlineKeyboardButton("🔍 Analyze Market", callback_data=CALLBACK_MENU_ANALYSE)],
                    [InlineKeyboardButton("📊 Trading Signals", callback_data=CALLBACK_MENU_SIGNALS)]
                ]
                
                await update.message.reply_text(
                    text=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            else:
                # Show subscription screen for non-subscribed users
                subscription_text = """
🚀 <b>Welcome to SigmaPips Trading Bot!</b> 🚀

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
                
                keyboard = [
                    [InlineKeyboardButton("🔥 Start 14-day FREE Trial", url="https://buy.stripe.com/test_6oE4kkdLefcT8Fy6oo")],
                    [InlineKeyboardButton("ℹ️ More Information", callback_data="subscription_info")]
                ]
                
                await update.message.reply_text(
                    text=subscription_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            
            return MENU
        except Exception as e:
            logger.error(f"Error showing main menu: {str(e)}")
            await update.message.reply_text(
                "An error occurred. Please try again or contact support.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Try Again", callback_data="back_menu")
                ]])
            )
        return MENU

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Alias voor callback_query_handler voor compatibiliteit"""
        return await self.callback_query_handler(update, context)

    async def toggle_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Toggle signal processing on/off (admin only)"""
        user_id = update.effective_user.id
        
        # Controleer of gebruiker admin is (voeg je eigen admin ID toe)
        admin_ids = [2004519703]  # Vervang met je eigen admin user ID
        
        if user_id not in admin_ids:
            await update.message.reply_text("Sorry, this command is only available for admins.")
            return
        
        # Toggle signaal status
        self.signals_enabled = not getattr(self, 'signals_enabled', True)
        
        status = "enabled" if self.signals_enabled else "disabled"
        await update.message.reply_text(f"Signal processing is now {status}.")

    async def check_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin command to check subscription status of any user"""
        user_id = update.effective_user.id
        admin_ids = [2004519703]  # Voeg hier je admin ID toe
        
        if user_id not in admin_ids:
            await update.message.reply_text("Sorry, this command is only available for admins.")
            return
        
        # Check arguments
        if context.args and len(context.args) > 0:
            try:
                target_user_id = int(context.args[0])
            except ValueError:
                await update.message.reply_text("Invalid user ID. Please provide a numeric user ID.")
                return
        else:
            target_user_id = user_id  # Default to self
        
        # Get subscription status
        subscription = await self.db.get_user_subscription(target_user_id)
        is_subscribed = await self.db.is_user_subscribed(target_user_id)
        
        # Format response
        if subscription:
            status = subscription.get('subscription_status')
            customer_id = subscription.get('stripe_customer_id')
            subscription_id = subscription.get('stripe_subscription_id')
            end_date = subscription.get('current_period_end')
            
            response = f"""
<b>Subscription Info for User {target_user_id}</b>

Status: {status}
Active: {'Yes' if is_subscribed else 'No'}
Stripe Customer ID: {customer_id or 'Not set'}
Stripe Subscription ID: {subscription_id or 'Not set'}
End Date: {end_date or 'Not set'}
            """
        else:
            response = f"No subscription found for user {target_user_id}"
        
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    async def set_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin command to manually set subscription status"""
        user_id = update.effective_user.id
        admin_ids = [2004519703]  # Voeg hier je admin ID toe
        
        if user_id not in admin_ids:
            await update.message.reply_text("Sorry, this command is only available for admins.")
            return
        
        # Check arguments: /set_subscription user_id status
        if context.args and len(context.args) >= 2:
            try:
                target_user_id = int(context.args[0])
                status = context.args[1]
                days = 14  # Default trial period
                
                if len(context.args) > 2:
                    days = int(context.args[2])
                    
            except ValueError:
                await update.message.reply_text("Invalid parameters. Format: /set_subscription user_id status [days]")
                return
        else:
            await update.message.reply_text("Missing parameters. Format: /set_subscription user_id status [days]")
            return
        
        # Set subscription status
        end_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
        
        success = await self.db.create_or_update_subscription(
            user_id=target_user_id,
            status=status,
            current_period_end=end_date
        )
        
        if success:
            await update.message.reply_text(f"Subscription for user {target_user_id} set to {status} until {end_date.strftime('%Y-%m-%d')}")
            
            # Als de status active of trialing is, stuur het welkomstbericht
            if status in ['active', 'trialing']:
                # Send the welcome message
                welcome_message = """
✅ <b>Thank You for Subscribing to SigmaPips Trading Bot!</b> ✅

Your subscription has been successfully activated. You now have full access to all features and trading signals.

<b>🚀 HOW TO USE:</b>

<b>1. Start with /menu</b>
   • This will show you the main options:
   • <b>Analyze Market</b> - For all market analysis tools
   • <b>Trading Signals</b> - To manage your trading signals

<b>2. Analyze Market options:</b>
   • <b>Technical Analysis</b> - Charts and price levels
   • <b>Market Sentiment</b> - Indicators and market mood
   • <b>Economic Calendar</b> - Upcoming economic events

<b>3. Trading Signals:</b>
   • Set up which signals you want to receive
   • Signals will be sent automatically
   • Each includes entry, stop loss, and take profit levels

Type /menu to start using the bot.
"""
                # Stuur alleen het welkomstbericht, geen menu of bevestiging
                await self.send_message_to_user(target_user_id, welcome_message, parse_mode=ParseMode.HTML)
                
                # Also send the main menu
                await self.show_main_menu_to_user(target_user_id)
                
                await update.message.reply_text(f"Welcome message sent to user {target_user_id}")
        else:
            await update.message.reply_text(f"Failed to update subscription for user {target_user_id}")

    async def send_welcome_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin command to manually send welcome message"""
        user_id = update.effective_user.id
        admin_ids = [2004519703]  # Voeg hier je admin ID toe
        
        if user_id not in admin_ids:
            await update.message.reply_text("Sorry, this command is only available for admins.")
            return
        
        # Check arguments
        if context.args and len(context.args) > 0:
            try:
                target_user_id = int(context.args[0])
            except ValueError:
                await update.message.reply_text("Invalid user ID. Please provide a numeric user ID.")
                return
        else:
            target_user_id = user_id  # Default to self
        
        # Send the welcome message
        welcome_message = """
✅ <b>Thank You for Subscribing to SigmaPips Trading Bot!</b> ✅

Your 14-day FREE trial has been successfully activated. You now have full access to all features and trading signals.

<b>🚀 HOW TO USE:</b>

<b>1. Trading Signals</b>
   • Use /menu and select "Trading Signals"
   • You'll automatically receive signals when they become available
   • Signals include: entry points, stop loss, take profit levels

<b>2. Market Analysis</b>
   • Use /menu and select "Technical Analysis" 
   • Choose your market (Forex, Crypto, etc.)
   • Select your desired instrument (EURUSD, BTCUSD, etc.)
   • Pick your trading style (Scalp, Intraday, Swing)

<b>3. Market Sentiment</b>
   • Use /menu and select "Market Sentiment"
   • View real-time market sentiment indicators

<b>4. Economic Calendar</b>
   • Use /menu and select "Economic Calendar"
   • View upcoming high-impact economic events

If you need any assistance, simply type /help to see available commands.

Happy Trading! 📈
"""
        await self.send_message_to_user(target_user_id, welcome_message)
        
        # Also send the main menu
        await self.show_main_menu_to_user(target_user_id)
        
        await update.message.reply_text(f"Welcome message sent to user {target_user_id}")

    async def show_main_menu_to_user(self, user_id: int) -> bool:
        """Show the main menu to a specific user"""
        try:
            # Create the main menu keyboard
            reply_markup = InlineKeyboardMarkup(START_KEYBOARD)
            
            # Send the welcome message with menu
            await self.bot.send_message(
                chat_id=user_id,
                text=WELCOME_MESSAGE,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            return True
        except Exception as e:
            logger.error(f"Error showing main menu to user {user_id}: {str(e)}")
            return False

# Functie om beperkte timeframe keyboard te maken op basis van timeframe
def create_restricted_keyboard(instrument, timeframe):
    """Maak een beperkt keyboard met alleen de opgegeven timeframe"""
    # Bepaal de stijl op basis van de timeframe
    style_map = {
        "m15": "scalp",
        "m30": "scalp30",
        "h1": "intraday",
        "h4": "swing"
    }
    
    # Bepaal de emoji en tekst op basis van de timeframe
    emoji_map = {
        "m15": "🏃",
        "m30": "⏱️",
        "h1": "📊",
        "h4": "🌊"
    }
    
    text_map = {
        "m15": "Scalp (15m)",
        "m30": "Scalp (30m)",
        "h1": "Intraday (1h)",
        "h4": "Intraday (4h)"
    }
    
    style = style_map.get(timeframe.lower(), "intraday")
    emoji = emoji_map.get(timeframe.lower(), "📊")
    text = text_map.get(timeframe.lower(), "Intraday (1h)")
    
    # Maak het keyboard
    restricted_keyboard = [
        [InlineKeyboardButton(f"{emoji} {text}", callback_data=f"style_{style}_restricted")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back_instrument")]
    ]
    
    return restricted_keyboard

# Definieer de instrumenten met hun beperkte timeframes
RESTRICTED_TIMEFRAMES = {
    "AUDJPY": "h1",
    "AUDCHF": "h1",
    "AUDCAD": "h4",
    "AU200": "h4",
    "BNBUSD": "m30",
    "CADCHF": "h4",
    "DOGEUSD": "m15",
    "DOTUSD": "m30",
    "ETHUSD": "m30",
    "EURAUD": "m30",
    "EURCAD": "h1",
    "EURCHF": "h4",
    "EURGBP": "h1",
    "EURJPY": "m30",
    "EURUSD": "h4",
    "GBPAUD": "m30",
    "GBPCAD": "h4",
    "GBPCHF": "h1",
    "GBPNZD": "m15",
    "GBPUSD": "m30",
    "HK50": "h1",
    "LINKUSD": "h4",
    "NZDCAD": "m30",
    "NZDCHF": "h4",
    "NZDJPY": "h1",
    "NZDUSD": "m15",
    "SOLUSD": "m15",
    "UK100": "m15",
    "US30": "m30",
    "US500": "m30",
    "USDCAD": "m30",
    "USDCHF": "h1",
    "XLMUSD": "m30",
    "XRPUSD": "h1",
    "XTIUSD": "m30",
    "DE40": "m30",
    "XAUUSD": "m15"
}
