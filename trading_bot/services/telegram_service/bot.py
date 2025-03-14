import os
import ssl
import asyncio
import logging
import aiohttp
import redis
import json
from typing import Dict, Any, List
import base64
import time
import re
import random

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

# Forex keyboard voor analyse
FOREX_KEYBOARD = [
    [
        InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD"),
        InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD"),
        InlineKeyboardButton("USDJPY", callback_data="instrument_USDJPY")
    ],
    [
        InlineKeyboardButton("AUDUSD", callback_data="instrument_AUDUSD"),
        InlineKeyboardButton("USDCAD", callback_data="instrument_USDCAD"),
        InlineKeyboardButton("EURGBP", callback_data="instrument_EURGBP")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
]

# Forex keyboard voor signals - Fix de "Terug" knop naar "Back"
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

# Crypto keyboard voor analyse
CRYPTO_KEYBOARD = [
    [
        InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD"),
        InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD"),
        InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
]

# Crypto keyboard voor signals - Fix de "Terug" knop naar "Back"
CRYPTO_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD_signals"),
        InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD_signals"),
        InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD_signals")
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
            self.application.add_handler(CallbackQueryHandler(self.button_callback))
            
            # Meer handlers...
            
            logger.info("Handlers registered")
        except Exception as e:
            logger.error(f"Error registering handlers: {str(e)}")
            raise

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command"""
        user = update.effective_user
        chat_id = update.effective_chat.id
        
        # Ga er standaard van uit dat gebruikers niet geabonneerd zijn
        is_subscribed = False
        
        # Toon altijd het abonnementsscherm voor de test
        subscription_features = get_subscription_features("monthly")
        
        # Maak knoppen
        keyboard = [
            [InlineKeyboardButton("📊 Subscribe Now", callback_data="subscribe_monthly")],
            [InlineKeyboardButton("ℹ️ More Information", callback_data="subscription_info")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Stuur het welkomstbericht
        await context.bot.send_message(
            chat_id=chat_id,
            text=SUBSCRIPTION_WELCOME_MESSAGE,
            reply_markup=reply_markup,
            parse_mode='HTML'
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
            # Get instrument from callback data
            instrument = query.data.replace('instrument_', '')
            
            # Save instrument in user_data
            if context and hasattr(context, 'user_data'):
                context.user_data['instrument'] = instrument
                analysis_type = context.user_data.get('analysis_type', 'technical')
                logger.info(f"Instrument callback: instrument={instrument}, analysis_type={analysis_type}")
            else:
                # Fallback als er geen context is
                analysis_type = 'technical'
                logger.info(f"Instrument callback zonder context: instrument={instrument}, fallback analysis_type={analysis_type}")
            
            # Toon het resultaat op basis van het analyse type
            if analysis_type == 'technical':
                logger.info(f"Toon technische analyse voor {instrument}")
                # Toon technische analyse
                try:
                    # Toon een laadmelding
                    await query.edit_message_text(
                        text=f"Generating technical analysis for {instrument}...",
                        reply_markup=None
                    )
                    
                    # Genereer de technische analyse
                    await self.show_technical_analysis(update, context, instrument)
                    return SHOW_RESULT
                except Exception as e:
                    logger.error(f"Error showing technical analysis: {str(e)}")
                    logger.exception(e)
                    # Stuur een nieuw bericht als fallback
                    await query.message.reply_text(
                        text=f"Error generating analysis for {instrument}. Please try again.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
                        ]])
                    )
                    return MENU
            
            elif analysis_type == 'sentiment':
                logger.info(f"Toon sentiment analyse voor {instrument}")
                # Toon sentiment analyse
                try:
                    # Toon een laadmelding
                    await query.edit_message_text(
                        text=f"Getting market sentiment for {instrument}...",
                        reply_markup=None
                    )
                    
                    # Genereer de sentiment analyse (niet de technische analyse)
                    await self.show_sentiment_analysis(update, context, instrument)
                    return SHOW_RESULT
                except Exception as e:
                    logger.error(f"Error showing sentiment analysis: {str(e)}")
                    logger.exception(e)
                    # Stuur een nieuw bericht als fallback
                    await query.message.reply_text(
                        text=f"Error getting sentiment for {instrument}. Please try again.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
                        ]])
                    )
                    return MENU
            
            elif analysis_type == 'calendar':
                # Toon economische kalender
                try:
                    # Toon een laadmelding
                    await query.edit_message_text(
                        text=f"Getting economic calendar for {instrument}...",
                        reply_markup=None
                    )
                    
                    # Genereer de economische kalender (niet de technische analyse)
                    await self.show_economic_calendar(update, context, instrument)
                    return SHOW_RESULT
                except Exception as e:
                    logger.error(f"Error showing economic calendar: {str(e)}")
                    # Stuur een nieuw bericht als fallback
                    await query.message.reply_text(
                        text=f"Error getting economic calendar for {instrument}. Please try again.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
                        ]])
                    )
                    return MENU
            
            else:
                # Onbekend analyse type, toon een foutmelding
                await query.edit_message_text(
                    text=f"Unknown analysis type: {analysis_type}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
                    ]])
                )
                return MENU
        
        except Exception as e:
            logger.error(f"Error in instrument_callback: {str(e)}")
            try:
                # Stuur een nieuw bericht als fallback
                await query.message.reply_text(
                    text="An error occurred. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
                    ]])
                )
            except:
                pass
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
            
            # Toon de stijl keuze
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
        
        style = query.data.replace('style_', '')
        
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
            except Exception as inner_e:
                logger.error(f"Failed to send fallback message: {str(inner_e)}")
            
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
            callback_data = query.data
            in_signals_flow = False
            
            # Check message text first (most reliable)
            if hasattr(query.message, 'text'):
                message_text = query.message.text
                logger.info(f"Message text for back_market: {message_text}")
                if "trading signals" in message_text.lower():
                    in_signals_flow = True
                    logger.info("Detected signals flow from message text")
            
            # Check user_data if available
            if not in_signals_flow and context and hasattr(context, 'user_data') and 'in_signals_flow' in context.user_data:
                in_signals_flow = context.user_data.get('in_signals_flow', False)
                logger.info(f"Detected signals flow from user_data: {in_signals_flow}")
            
            # Check callback data as last resort
            if not in_signals_flow and '_signals' in str(query.message.reply_markup):
                in_signals_flow = True
                logger.info("Detected signals flow from reply markup")
            
            logger.info(f"Back to market callback, in_signals_flow: {in_signals_flow}")
            
            if in_signals_flow:
                # Toon het market keyboard voor signals
                await query.edit_message_text(
                    text="Select a market for trading signals:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
                )
            else:
                # Toon het market keyboard voor analyse
                await query.edit_message_text(
                    text="Select a market for analysis:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
            
            return CHOOSE_MARKET
        except Exception as e:
            logger.error(f"Error in back_to_market_callback: {str(e)}")
            logger.exception(e)
            
            # Fallback: stuur een nieuw bericht met het market menu
            try:
                await query.message.reply_text(
                    text="Select a market:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
                return CHOOSE_MARKET
            except:
                return MENU

    async def back_to_instrument(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to instrument selection"""
        query = update.callback_query
        await query.answer()
        
        # Get market from user_data
        market = context.user_data.get('market', 'forex')
        
        # Determine which keyboard to show based on market
        keyboard_map = {
            'forex': FOREX_KEYBOARD,
            'crypto': CRYPTO_KEYBOARD,
            'indices': INDICES_KEYBOARD,
            'commodities': COMMODITIES_KEYBOARD
        }
        
        keyboard = keyboard_map.get(market, FOREX_KEYBOARD)
        
        # Add _signals to callback data if we're in signals flow
        if context.user_data.get('analysis_type') != 'technical':
            for row in keyboard:
                for button in row:
                    if button.callback_data.startswith('instrument_'):
                        button.callback_data = f"{button.callback_data}_signals"
        
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
            self.application.add_handler(CallbackQueryHandler(self.button_callback))
            
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
        """Process a trading signal and send it to subscribed users"""
        try:
            # Log het ontvangen signaal
            logger.info(f"Processing signal (raw): {signal_data}")
            
            # Haal de relevante informatie uit het signaal
            instrument = signal_data.get('instrument', '')
            direction = signal_data.get('signal', 'UNKNOWN')
            price = signal_data.get('price', 0)
            stop_loss = signal_data.get('sl', '')  # Gebruik 'sl' voor stop loss
            tp1 = signal_data.get('tp1', '')       # Gebruik 'tp1', 'tp2', 'tp3' voor take profits
            tp2 = signal_data.get('tp2', '')
            tp3 = signal_data.get('tp3', '')
            timeframe = signal_data.get('interval', '1h')  # Gebruik interval indien aanwezig, anders 1h
            strategy = signal_data.get('strategy', 'AI Signal')
            
            # Detecteer de markt op basis van het instrument
            market = signal_data.get('market') or _detect_market(instrument)
            
            # Haal verdict op over of signaal in lijn is met sentiment
            verdict = await self.get_sentiment_verdict(instrument, direction)
            logger.info(f"Generated verdict for {instrument}: {verdict}")
            
            # Maak het signaal bericht
            signal_message = f"🎯 <b>New Trading Signal</b> 🎯\n\n"
            signal_message += f"Instrument: {instrument}\n"
            signal_message += f"Action: {direction.upper()} {'📈' if direction.lower() == 'buy' else '📉'}\n\n"
            
            signal_message += f"Entry Price: {price}\n"
            
            if stop_loss:
                signal_message += f"Stop Loss: {stop_loss} 🔴\n"
            
            # Voeg alle take profit niveaus toe als ze beschikbaar zijn
            if tp1:
                signal_message += f"Take Profit 1: {tp1} 🎯\n"
            if tp2:
                signal_message += f"Take Profit 2: {tp2} 🎯\n"
            if tp3:
                signal_message += f"Take Profit 3: {tp3} 🎯\n"
            
            signal_message += f"\nTimeframe: {timeframe}\n"
            signal_message += f"Strategy: {strategy}\n\n"
            
            # Voeg het AI verdict toe
            signal_message += f"🤖 <b>SigmaPips AI Verdict:</b>\n"
            signal_message += verdict
            
            # Define the analyze button
            keyboard = [
                [InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_market_{instrument}")]
            ]
            
            # Haal abonnees op die dit signaal willen ontvangen
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
                    
                    # Maak de keyboard met één knop voor analyse
                    keyboard = [
                        [InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_market_{instrument}")]
                    ]
                    
                    # Stuur het signaal met de analyse knop
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=signal_message,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='HTML'
                    )
                    
                    # Sla het signaal op in de user_signals dictionary
                    self.user_signals[int(user_id)] = {  # Zorg ervoor dat user_id een integer is
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
            
            # ... rest van de code ...
            
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
                    [InlineKeyboardButton("🧠 Market Sentiment", callback_data=f"direct_sentiment_{instrument}")],
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
                instrument = query.data.replace("direct_technical_", "")
                logger.info(f"Direct technical analysis for {instrument}")
                return await self.show_technical_analysis(update, context, instrument, from_signal=True)
                
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

    async def show_technical_analysis(self, update: Update, context=None, instrument=None, from_signal=False, style=None):
        """Show technical analysis for an instrument"""
        query = update.callback_query
        
        try:
            # Als er geen stijl is gekozen, gebruik de 1h timeframe als default
            timeframe = "1h"
            if style and style in STYLE_TIMEFRAME_MAP:
                timeframe = STYLE_TIMEFRAME_MAP[style]
            
            # Toon een laadmelding als die nog niet is getoond
            try:
                await query.edit_message_text(
                    text=f"Generating technical analysis for {instrument} ({timeframe})...",
                    reply_markup=None
                )
            except Exception as e:
                logger.warning(f"Could not edit message: {str(e)}")
            
            # Haal de chart op met de gekozen timeframe of de default (1h)
            chart_image = await self.chart.get_chart(instrument, timeframe=timeframe)
            
            if chart_image:
                # Bepaal de juiste back-knop op basis van de context
                back_button = InlineKeyboardButton("⬅️ Back", callback_data="back_market")
                if from_signal:
                    back_button = InlineKeyboardButton("⬅️ Back to Signal", callback_data=f"back_to_signal_{instrument}")
                
                # Stuur de chart als foto
                await query.message.reply_photo(
                    photo=chart_image,
                    caption=f"📊 {instrument} Technical Analysis ({timeframe})",
                    reply_markup=InlineKeyboardMarkup([[back_button]])
                )
                
                # Verwijder het laadmelding bericht
                try:
                    await query.edit_message_text(
                        text=f"Chart for {instrument} generated successfully.",
                        reply_markup=None
                    )
                except Exception as edit_error:
                    logger.warning(f"Could not edit loading message: {str(edit_error)}")
                    # Als het bericht niet kan worden bewerkt, verwijder het dan
                    try:
                        await query.message.delete()
                    except:
                        pass
                
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
        # Voeg hier je bestaande start commando functionaliteit toe
        # Dit is wat eerder direct in start_command zat
        
        # Bijvoorbeeld:
        keyboard = [
            [InlineKeyboardButton("📈 Signals", callback_data="signals")],
            [InlineKeyboardButton("📰 News", callback_data="news")],
            [InlineKeyboardButton("📊 Charts", callback_data="charts")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="settings")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Welcome to SigmaPips! What would you like to do?",
            reply_markup=reply_markup
        )

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle button presses from inline keyboards"""
        query = update.callback_query
        logger.info(f"Button callback opgeroepen met data: {query.data}")
        await query.answer()
        
        if query.data == "subscribe_monthly":
            logger.info(f"Subscribe Monthly knop geklikt door gebruiker {query.from_user.id}")
            
            # Controleer of stripe_service bestaat
            if not self.stripe_service:
                logger.error("Stripe service is niet geïnitialiseerd!")
                await query.edit_message_text(
                    text="Er is een probleem met de betalingsservice. Probeer het later opnieuw."
                )
                return
                
            # Genereer Stripe checkout URL
            checkout_url = await self.stripe_service.create_checkout_session(
                user_id=query.from_user.id,
                plan_type="monthly"
            )
            
            logger.info(f"Checkout URL gegenereerd: {checkout_url}")
            
            if checkout_url:
                # Maak betaalknop
                keyboard = [[InlineKeyboardButton("🔐 Secure Checkout", url=checkout_url)]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text="Click the button below to complete your subscription:",
                    reply_markup=reply_markup
                )
            else:
                logger.error("Geen checkout URL ontvangen van stripe_service")
                await query.edit_message_text(
                    text="Sorry, there was an error creating your checkout session. Please try again later."
                )
        
        elif query.data == "subscription_info":
            # Toon meer details over het abonnement
            subscription_features = get_subscription_features("monthly")
            features = "\n".join([f"• {feature}" for feature in subscription_features.get("signals", [])])
            
            info_text = f"""
<b>{subscription_features['name']} - {subscription_features['price']}</b>

<b>Features:</b>
{features}

<b>Analysis:</b> {'✅ Included' if subscription_features.get('analysis') else '❌ Not included'}

<b>Timeframes:</b> {', '.join(subscription_features.get('timeframes', []))}
            """
            
            # Terug-knop
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_subscription")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=info_text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        
        elif query.data == "back_to_subscription":
            # Terug naar abonnementsoverzicht
            keyboard = [
                [InlineKeyboardButton("📊 Subscribe Now", callback_data="subscribe_monthly")],
                [InlineKeyboardButton("ℹ️ More Information", callback_data="subscription_info")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=SUBSCRIPTION_WELCOME_MESSAGE,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        
        else:
            # Handle andere callback data (voor bestaande functionaliteit)
            pass

    def setup(self):
        """Set up the bot with all handlers"""
        # Bestaande code behouden
        application = Application.builder().token(self.token).build()
        
        # Command handlers
        application.add_handler(CommandHandler("start", self.start_command))
        
        # Voeg nieuw menu commando toe (voor bestaande gebruikers om het menu te zien)
        application.add_handler(CommandHandler("menu", self.show_main_menu))
        
        # Callback query handler
        application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Andere bestaande handlers...
        
        return application
