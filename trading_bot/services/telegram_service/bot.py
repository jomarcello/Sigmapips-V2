import os
import ssl
import asyncio
import logging
import aiohttp
import redis
import json
from typing import Dict, Any, List, Optional
import base64
import time
import re
import random
import threading

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
from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
from trading_bot.services.calendar_service.calendar import EconomicCalendarService
from trading_bot.services.payment_service.stripe_service import StripeService
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
        InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD"),
        InlineKeyboardButton("XAGUSD", callback_data="instrument_XAGUSD"),
        InlineKeyboardButton("USOIL", callback_data="instrument_USOIL")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
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
        
        if is_subscribed:
            # User has subscription, proceed with function
            return await func(self, update, context, *args, **kwargs)
        else:
            # Show subscription screen
            subscription_features = get_subscription_features("monthly")
            
            # Update message to emphasize the trial period
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
                [InlineKeyboardButton("🔥 Start FREE Trial", callback_data="subscribe_monthly")],
                [InlineKeyboardButton("ℹ️ More Information", callback_data="subscription_info")]
            ]
            
            await update.message.reply_text(
                text=welcome_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return MENU
    
    return wrapper

# API Keys
PERPLEXITY_API_KEY = "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"
DEEPSEEK_API_KEY = "72df8ae1c5dd4d95b6a54c09bcf1b39e"

class TelegramService:
    def __init__(self, db: Database, stripe_service=None):
        """Initialize the TelegramBot class"""
        self.db = db  # Database connection
        self.stripe_service = stripe_service  # Payment service
        
        # API services
        self.chart = ChartService()  # Chart generation service
        self.sentiment = MarketSentimentService()  # Sentiment analysis service
        self.calendar = EconomicCalendarService()  # Economic calendar service
        
        # Bot application
        self.application = None
        self.persistence = None
        self.bot_started = False
        
        # Cache voor sentiment analyse resultaten
        self.sentiment_cache = {}
        self.sentiment_cache_ttl = 60 * 60  # 1 uur in seconden
        
        # Signal storage
        self.user_signals = {}
        
        try:
            # Initialiseer de bot
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
            if not bot_token:
                raise ValueError("Missing Telegram bot token")
            
            # Initialiseer de bot
            self.bot = Bot(token=bot_token)
            
            # Initialiseer de application
            self.application = Application.builder().bot(self.bot).build()
            
            # Registreer de handlers
            self._register_handlers()
            
            logger.info("Telegram service initialized")
            
            # Houd bij welke updates al zijn verwerkt
            self.processed_updates = set()
            
            self.stripe_service = stripe_service  # Stripe service toevoegen
            
            # Initialize sentiment cache with TTL of 60 minutes
            self.sentiment_cache = {}
            self.sentiment_cache_ttl = 60 * 60  # 60 minutes in seconds
            
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
            
            # Voeg een CommandHandler toe voor /help
            self.application.add_handler(CommandHandler("help", self.help_command))
            
            # Voeg een CallbackQueryHandler toe voor knoppen
            self.application.add_handler(CallbackQueryHandler(self.button_callback))
            
            # Meer handlers...
            
            logger.info("Handlers registered")
        except Exception as e:
            logger.error(f"Error registering handlers: {str(e)}")
            raise

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a welcome message when the bot is started."""
        user = update.effective_user
        user_id = user.id
        first_name = user.first_name
        
        # Try to add the user to the database if they don't exist yet
        try:
            # Check if user already exists in the database
            existing_user = await self.db.get_user(user_id)
            
            if not existing_user:
                # Add new user
                logger.info(f"New user started: {user_id}, {first_name}")
                await self.db.add_user(user_id, first_name, user.username)
            else:
                logger.info(f"Existing user started: {user_id}, {first_name}")
                
        except Exception as e:
            logger.error(f"Error registering user: {str(e)}")
        
        # Check if the user has a subscription
        is_subscribed = await self.db.is_user_subscribed(user_id)
        
        if is_subscribed:
            # Show the normal welcome message with all features
            await self.show_main_menu(update, context)
        else:
            # Show the welcome message with trial option
            welcome_text = f"""
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
            
            # Create buttons
            keyboard = [
                [InlineKeyboardButton("🔥 Start 14-day FREE Trial", callback_data="subscribe_monthly")],
                [InlineKeyboardButton("ℹ️ More Information", callback_data="subscription_info")]
            ]
            
            await update.message.reply_text(
                text=welcome_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )

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
            
            # Show market selection for technical analysis
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
            
            # Show market selection for sentiment analysis
            await query.edit_message_text(
                text="Select a market for sentiment analysis:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
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
            
            # Show market selection for calendar analysis
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
        market = query.data.replace('market_', '')
        
        try:
            # Toon het juiste keyboard op basis van de markt en analyse type
            await query.answer()
            
            # Bepaal het analyse type
            analysis_type = 'technical'  # Standaard technische analyse
            if context and hasattr(context, 'user_data') and 'analysis_type' in context.user_data:
                analysis_type = context.user_data['analysis_type']
            
            logger.info(f"Market callback: market={market}, analysis_type={analysis_type}")
            
            # Kies het juiste toetsenbord op basis van markt en analyse type
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
                keyboard = INDICES_KEYBOARD
                message_text += "analysis:"
            elif market == 'commodities':
                keyboard = COMMODITIES_KEYBOARD
                message_text += "analysis:"
            else:
                # Onbekende markt, toon een foutmelding
                await query.edit_message_text(
                    text=f"Unknown market: {market}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
                    ]])
                )
                return MENU
            
            # Toon het juiste toetsenbord
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

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show the main menu with all bot features"""
        # Toon het originele hoofdmenu met alle opties
        reply_markup = InlineKeyboardMarkup(START_KEYBOARD)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=WELCOME_MESSAGE,
            parse_mode='HTML',
            reply_markup=reply_markup
        )

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle button presses from inline keyboards"""
        query = update.callback_query
        logger.info(f"Button callback opgeroepen met data: {query.data}")
        await query.answer()
        
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
            
        if query.data == "back_signals":
            return await self.market_signals_callback(update, context)
        
        # Verwerk abonnementsacties
        if query.data == "subscribe_monthly" or query.data == "subscription_info":
            return await self.handle_subscription_callback(update, context)
        
        # Analysis type handlers
        if query.data.startswith("analysis_"):
            return await self.analysis_choice(update, context)
        
        # Verwerk instrument keuzes met specifiek type (chart, sentiment, calendar)
        if "_chart" in query.data or "_sentiment" in query.data or "_calendar" in query.data:
            # Direct doorsturen naar de instrument_callback methode
            logger.info(f"Specifiek instrument type gedetecteerd in: {query.data}")
            return await self.instrument_callback(update, context)
        
        # Speciale afhandeling voor markt keuzes
        if query.data.startswith("market_"):
            return await self.market_callback(update, context)
        
        # Signals handlers
        if query.data == "signals_add" or query.data == CALLBACK_SIGNALS_ADD:
            return await self.signals_add_callback(update, context)
            
        if query.data == "signals_manage" or query.data == CALLBACK_SIGNALS_MANAGE:
            return await self.signals_manage_callback(update, context)
        
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
        # Bestaande code behouden
        application = Application.builder().token(self.token).build()
        
        # Command handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("menu", self.show_main_menu))
        application.add_handler(CommandHandler("help", self.help_command))
        
        # Callback query handler for all button presses
        application.add_handler(CallbackQueryHandler(self.button_callback))
        
        self.application = application
        
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
        
        # Extract instrument from callback data
        parts = data.split('_')
        instrument = parts[1]
        analysis_type = parts[2] if len(parts) > 2 else "chart"  # Default naar 'chart' als niet gespecificeerd
        
        # Debug logging
        logger.info(f"Instrument callback: instrument={instrument}, analysis_type={analysis_type}, callback_data={data}")
        
        try:
            await query.answer()
            
            # Maak de juiste analyse op basis van het type
            if analysis_type == "chart":
                logger.info(f"Toon technische analyse (chart) voor {instrument}")
                await self.show_technical_analysis(update, context, instrument)
                return CHOOSE_TIMEFRAME
            elif analysis_type == "sentiment":
                logger.info(f"Toon sentiment analyse voor {instrument}")
                await self.show_sentiment_analysis(update, context, instrument)
                return CHOOSE_TIMEFRAME
            elif analysis_type == "calendar":
                logger.info(f"Toon economische kalender voor {instrument}")
                await self.show_economic_calendar(update, context, instrument)
                return CHOOSE_TIMEFRAME
            else:
                # Als het type niet herkend wordt, toon technische analyse als fallback
                logger.info(f"Onbekend analyse type: {analysis_type}, toon technische analyse voor {instrument}")
                await self.show_technical_analysis(update, context, instrument)
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
            
            # Use the fixed Stripe checkout URL for testing
            checkout_url = "https://buy.stripe.com/test_6oE4kkdLefcT8Fy6oo"
            
            # Create keyboard with checkout link
            keyboard = [
                [InlineKeyboardButton("🔥 Start Trial", url=checkout_url)],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]
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
                [InlineKeyboardButton("🔥 Start FREE Trial", callback_data="subscribe_monthly")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]
            ]
            
            await query.edit_message_text(
                text=info_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return SUBSCRIBE

        return MENU

    async def get_sentiment_analysis(self, instrument: str) -> str:
        """Get sentiment analysis using Perplexity and DeepSeek APIs with caching"""
        try:
            # Check cache first
            current_time = time.time()
            if instrument in self.sentiment_cache:
                cache_time, cached_data = self.sentiment_cache[instrument]
                # If cache is still valid (less than TTL seconds old)
                if current_time - cache_time < self.sentiment_cache_ttl:
                    logger.info(f"Using cached sentiment data for {instrument}")
                    return cached_data
            
            logger.info(f"Fetching fresh sentiment data for {instrument}")
            
            # Step 1: Use Perplexity API to get latest news
            perplexity_data = await self.get_perplexity_data(instrument)
            
            # Step 2: Use DeepSeek to format the response
            sentiment_analysis = await self.format_with_deepseek(instrument, perplexity_data)
            
            # Cache the result
            self.sentiment_cache[instrument] = (current_time, sentiment_analysis)
            
            return sentiment_analysis
        except Exception as e:
            logger.error(f"Error getting sentiment analysis: {str(e)}")
            
            # Check if we have a cached version even if it's expired
            if instrument in self.sentiment_cache:
                logger.info(f"Using expired cached data for {instrument} due to API error")
                return self.sentiment_cache[instrument][1]
                
            # If no cache exists, return fallback sentiment
            return self.get_fallback_sentiment(instrument)
    
    async def get_perplexity_data(self, instrument: str) -> str:
        """Use Perplexity API to get latest news about the instrument"""
        try:
            headers = {
                "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                "Content-Type": "application/json"
            }
            
            # Prepare the query based on the instrument
            query = f"What is the latest market sentiment and news about {instrument}? Include important price levels, recent developments and trader sentiment."
            
            # Set a timeout for the API call to prevent hanging
            timeout = aiohttp.ClientTimeout(total=15)  # 15 seconds timeout
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                try:
                    async with session.post(
                        "https://api.perplexity.ai/chat/completions",
                        headers=headers,
                        json={
                            "model": "sonar-medium-online",
                            "messages": [{"role": "user", "content": query}],
                            "temperature": 0.7,
                            "max_tokens": 1024
                        }
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            return data["choices"][0]["message"]["content"]
                        else:
                            error_text = await response.text()
                            logger.error(f"Perplexity API error: {response.status}, {error_text}")
                            return f"Failed to fetch sentiment data for {instrument} due to API error. Will use fallback data."
                except asyncio.TimeoutError:
                    logger.error(f"Timeout when calling Perplexity API for {instrument}")
                    return f"Timeout when fetching data for {instrument}. Will use fallback data."
        except Exception as e:
            logger.error(f"Error calling Perplexity API: {str(e)}")
            return f"Error fetching sentiment data for {instrument}: {str(e)}"
    
    async def format_with_deepseek(self, instrument: str, perplexity_data: str) -> str:
        """Use DeepSeek API to format the data into a well-structured sentiment analysis"""
        try:
            # If Perplexity already failed, don't try DeepSeek
            if perplexity_data.startswith("Failed to fetch") or perplexity_data.startswith("Timeout") or perplexity_data.startswith("Error fetching"):
                return self.get_fallback_sentiment(instrument)
                
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            prompt = f"""
            Format the following market data about {instrument} into a well-structured sentiment analysis 
            that is suitable for a Telegram bot message. The message should include:
            
            1. A title with the instrument name
            2. Overall sentiment (Bullish/Bearish/Neutral) with emoji
            3. Key support and resistance levels
            4. Recent news summary
            5. Trading recommendation
            
            Use HTML formatting for Telegram (bold tags for headers, etc.) and include relevant emoji.
            
            Raw data:
            {perplexity_data}
            """
            
            # Set a timeout for the API call
            timeout = aiohttp.ClientTimeout(total=20)  # 20 seconds timeout
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                try:
                    async with session.post(
                        "https://api.deepseek.com/v1/chat/completions",
                        headers=headers,
                        json={
                            "model": "deepseek-chat",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.4,
                            "max_tokens": 1024
                        }
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            formatted_content = data["choices"][0]["message"]["content"]
                            
                            # Ensure the content has proper HTML formatting for Telegram
                            if "<b>" not in formatted_content:
                                formatted_content = f"""<b>🧠 Market Sentiment Analysis: {instrument}</b>

{formatted_content}"""
                            
                            return formatted_content
                        else:
                            error_text = await response.text()
                            logger.error(f"DeepSeek API error: {response.status}, {error_text}")
                            return self.format_fallback_response(instrument, perplexity_data)
                except asyncio.TimeoutError:
                    logger.error(f"Timeout when calling DeepSeek API for {instrument}")
                    return self.format_fallback_response(instrument, perplexity_data)
        except Exception as e:
            logger.error(f"Error calling DeepSeek API: {str(e)}")
            return self.format_fallback_response(instrument, perplexity_data)
    
    def format_fallback_response(self, instrument: str, perplexity_data: str) -> str:
        """Format the perplexity data if DeepSeek fails"""
        try:
            return f"""<b>🧠 Market Sentiment Analysis: {instrument}</b>

<b>Latest Market News:</b>
{perplexity_data[:1500]}...

<i>Note: This is a simplified analysis. For more details, please check financial news sources.</i>
"""
        except:
            return self.get_fallback_sentiment(instrument)
    
    def get_fallback_sentiment(self, instrument: str) -> str:
        """Generate fallback sentiment when APIs fail"""
        import random
        
        sentiment_options = ["Bullish", "Bearish", "Neutral"]
        sentiment = random.choice(sentiment_options)
        
        emoji = "📈" if sentiment == "Bullish" else "📉" if sentiment == "Bearish" else "⚖️"
        
        bullish_percentage = random.randint(30, 70)
        bearish_percentage = 100 - bullish_percentage
        
        return f"""<b>🧠 Market Sentiment Analysis: {instrument}</b>

<b>Overall Sentiment:</b> {sentiment} {emoji}

<b>Sentiment Breakdown:</b>
• Bullish: {bullish_percentage}%
• Bearish: {bearish_percentage}%

<b>Note:</b> This is a fallback analysis as we couldn't fetch real-time data.
Consider checking financial news sources for more accurate information.
"""

    async def initialize(self, use_webhook=False):
        """Initialize the bot and start polling or webhook"""
        try:
            if not self.application:
                raise ValueError("Application not initialized")
                
            # Initialize the application in all cases
            await self.application.initialize()
            
            # Controleer of we moeten forceren om polling te gebruiken
            force_polling = os.getenv("FORCE_POLLING", "false").lower() == "true"
            if force_polling:
                logger.info("FORCE_POLLING is set to true, using polling mode instead of webhook")
                use_webhook = False
                
            if use_webhook and not force_polling:
                # Configureer webhook settings
                webhook_url = os.getenv("WEBHOOK_URL")
                webhook_port = int(os.getenv("PORT", "8000"))
                webhook_path = os.getenv("WEBHOOK_PATH", "/webhook")
                
                if not webhook_url:
                    logger.warning("WEBHOOK_URL not set, falling back to polling mode")
                    # Start polling mode instead
                    await self._setup_polling_mode()
                else:    
                    logger.info(f"Setting up webhook configuration with URL {webhook_url}, port {webhook_port}, path {webhook_path}")
                    
                    # Store webhook configuration for later use
                    self.webhook_path = webhook_path
                    self.webhook_url = webhook_url
                    self.webhook_port = webhook_port
                
                    # Set commands
                    await self.bot.set_my_commands([
                        BotCommand("start", "Start the bot and show main menu"),
                        BotCommand("menu", "Show main menu"),
                        BotCommand("help", "Show help information")
                    ])
                
                    logger.info("Bot initialized with webhook configuration")
            else:
                # For polling mode
                logger.info("Using polling mode as requested")
                await self._setup_polling_mode()
                
            self.bot_started = True
            
        except Exception as e:
            logger.error(f"Error initializing bot: {str(e)}")
            logger.exception(e)
            raise
    
    async def _setup_polling_mode(self):
        """Set up the bot for polling mode"""
        try:
            # Set commands
            await self.bot.set_my_commands([
                BotCommand("start", "Start the bot and show main menu"),
                BotCommand("menu", "Show main menu"),
                BotCommand("help", "Show help information")
            ])
            
            # Start polling in a separate thread to avoid event loop issues
            polling_thread = threading.Thread(target=self._start_polling_thread)
            polling_thread.daemon = True
            polling_thread.start()
            
            logger.info("Bot initialized for polling mode in a separate thread")
        except Exception as e:
            logger.error(f"Error setting up polling mode: {str(e)}")
            logger.exception(e)
            raise
            
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

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a help message when the command /help is issued."""
        await update.message.reply_text(
            text=HELP_MESSAGE,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]
            ])
        )
        
    async def process_signal(self, signal_data: Dict[str, Any]) -> bool:
        """Process trading signals received from API or webhook"""
        try:
            logger.info(f"Processing signal: {signal_data}")
            
            # Extract signal details
            symbol = signal_data.get('symbol', '').upper()
            direction = signal_data.get('direction', '').upper()
            price = signal_data.get('price', 0)
            stop_loss = signal_data.get('stop_loss', 0)
            take_profit = signal_data.get('take_profit', 0)
            timeframe = signal_data.get('timeframe', '1h')
            notes = signal_data.get('notes', '')
            market = signal_data.get('market', self._detect_market(symbol)).lower()
            
            # Valideer de signal data
            if not symbol or not direction or not price:
                logger.error(f"Invalid signal data: missing required fields")
                return False
                
            # Format signal message
            message = f"""
📊 <b>NEW TRADING SIGNAL</b> 📊

<b>Symbol:</b> {symbol}
<b>Market:</b> {market.title()}
<b>Direction:</b> {'🔴 SELL' if direction == 'SELL' else '🟢 BUY'}
<b>Entry Price:</b> {price}
<b>Stop Loss:</b> {stop_loss if stop_loss else 'Not specified'}
<b>Take Profit:</b> {take_profit if take_profit else 'Not specified'}
<b>Timeframe:</b> {timeframe}
<b>Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}

{notes if notes else ''}
"""
            
            # Haal subscribers op die dit signaal zouden moeten ontvangen
            subscribers = await self._get_signal_subscribers(market, symbol)
            
            # Stuur het signaal naar relevante subscribers
            send_count = 0
            for user_id in subscribers:
                try:
                    # Stuur het bericht naar de gebruiker
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode=ParseMode.HTML
                    )
                    send_count += 1
                except Exception as e:
                    logger.error(f"Error sending signal to user {user_id}: {str(e)}")
            
            logger.info(f"Signal sent to {send_count}/{len(subscribers)} subscribers")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing signal: {str(e)}")
            logger.exception(e)
            return False
            
    def _detect_market(self, symbol: str) -> str:
        """Detect market type from symbol"""
        # Crypto markers
        if symbol.endswith('USDT') or symbol.endswith('BTC') or symbol.endswith('ETH') or 'BTC' in symbol:
            return 'crypto'
            
        # Forex markers
        if all(c in symbol for c in ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'NZD', 'CAD', 'CHF']):
            return 'forex'
            
        # Indices markers
        if any(idx in symbol for idx in ['SPX', 'NDX', 'DJI', 'FTSE', 'DAX', 'CAC', 'NIKKEI']):
            return 'indices'
            
        # Commodities markers
        if any(com in symbol for com in ['GOLD', 'XAU', 'SILVER', 'XAG', 'OIL', 'GAS', 'USOIL']):
            return 'commodities'
            
        # Default to forex
        return 'forex'
        
    async def _get_signal_subscribers(self, market: str, symbol: str) -> List[int]:
        """Get list of subscribers for a specific market and symbol"""
        try:
            # Haal alle subscribers op
            all_subscribers = await self.db.get_subscribers()
            
            # Filter subscribers op basis van market en symbol
            matching_subscribers = []
            
            for subscriber in all_subscribers:
                # Haal preferences op voor deze subscriber
                preferences = await self.db.get_subscriber_preferences(subscriber['user_id'])
                
                # Controleer of de subscriber geïnteresseerd is in deze market en symbol
                for pref in preferences:
                    if pref['market'].lower() == market.lower() and (
                       pref['instrument'].upper() == symbol.upper() or 
                       pref['instrument'] == 'ALL'):  # 'ALL' betekent dat ze alle signalen willen
                        matching_subscribers.append(subscriber['user_id'])
                        break
            
            return matching_subscribers
            
        except Exception as e:
            logger.error(f"Error getting signal subscribers: {str(e)}")
            return []

    async def process_update(self, update_data: dict):
        """Process updates from webhook"""
        try:
            logger.info(f"Processing update: {update_data}")
            
            # Controleer of de update al is verwerkt
            update_id = update_data.get('update_id')
            if update_id in self.processed_updates:
                logger.info(f"Update {update_id} already processed, skipping")
                return
                
            # Convert dictionary to Update object
            update = Update.de_json(data=update_data, bot=self.bot)
            if not update:
                logger.error("Failed to parse update")
                return
                
            # Process the update
            await self.application.process_update(update)
            
            # Mark as processed
            self.processed_updates.add(update_id)
            
            # Trim processed_updates set if it gets too large
            if len(self.processed_updates) > 1000:
                # Keep only the 500 most recent updates
                self.processed_updates = set(sorted(self.processed_updates)[-500:])
                
        except Exception as e:
            logger.error(f"Error processing update: {str(e)}")
            logger.exception(e)

    async def setup_webhook(self, app):
        """Set up webhook for FastAPI application"""
        try:
            if not hasattr(self, 'webhook_path') or not self.webhook_url:
                logger.warning("Webhook configuration is incomplete. Cannot set up webhook.")
                return
                
            logger.info(f"Setting up webhook at {self.webhook_path} with URL {self.webhook_url}")
            
            # Import FastAPI dependencies
            from fastapi import Request
            
            # Define the webhook endpoint in the FastAPI app - maar alleen als deze nog niet bestaat
            if not any(route.path == self.webhook_path for route in app.routes):
                @app.post(self.webhook_path)
                async def telegram_webhook(request: Request):
                    """Handle webhook updates from Telegram"""
                    try:
                        # Parse the JSON data from the request
                        update_data = await request.json()
                        
                        # Process the update
                        await self.process_update(update_data)
                        return {"status": "ok"}
                    except Exception as e:
                        logger.error(f"Error processing webhook: {str(e)}")
                        return {"status": "error", "message": str(e)}
            
            # Set the webhook URL in Telegram
            # Controleer of de webhook URL begint met https://
            if not self.webhook_url.startswith("https://"):
                self.webhook_url = "https://" + self.webhook_url
                
            # Zorg dat de webhook URL geen dubbele slashes bevat tussen domain en path
            if self.webhook_url.endswith("/") and self.webhook_path.startswith("/"):
                webhook_url = self.webhook_url + self.webhook_path[1:]
            else:
                webhook_url = self.webhook_url if self.webhook_url.endswith(self.webhook_path) else self.webhook_url + self.webhook_path
                
            logger.info(f"Setting webhook URL to: {webhook_url}")
            await self.bot.set_webhook(url=webhook_url)
            
            logger.info(f"Webhook set up successfully at {webhook_url}")
            
            # Get webhook info for debugging
            try:
                webhook_info = await self.bot.get_webhook_info()
                logger.info(f"Current webhook info: {webhook_info}")
            except Exception as e:
                logger.error(f"Error getting webhook info: {str(e)}")
            
        except Exception as e:
            logger.error(f"Error setting up webhook: {str(e)}")
            logger.exception(e)
            raise

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
            
            # Show appropriate message based on analysis type
            if analysis_type == 'technical':
                message_text = "Select a market for technical analysis:"
            elif analysis_type == 'sentiment':
                message_text = "Select a market for sentiment analysis:"
            else:
                message_text = "Select a market:"
                
            # Show the market selection
            await query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
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
                keyboard = INDICES_KEYBOARD
                message_text += "analysis:"
            elif market == 'commodities':
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
            try:
                await query.message.reply_text(
                    text="Select an instrument:",
                    reply_markup=InlineKeyboardMarkup(FOREX_KEYBOARD)  # Default to forex
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
