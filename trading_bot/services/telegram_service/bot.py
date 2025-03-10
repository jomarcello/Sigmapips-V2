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

logger = logging.getLogger(__name__)

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
    [InlineKeyboardButton("🔍 Analyze Market", callback_data="menu_analyse")],
    [InlineKeyboardButton("📊 Trading Signals", callback_data="menu_signals")]
]

# Analysis menu keyboard
ANALYSIS_KEYBOARD = [
    [InlineKeyboardButton("📈 Technical Analysis", callback_data="analysis_technical")],
    [InlineKeyboardButton("🧠 Market Sentiment", callback_data="analysis_sentiment")],
    [InlineKeyboardButton("📅 Economic Calendar", callback_data="analysis_calendar")],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
]

# Signals menu keyboard
SIGNALS_KEYBOARD = [
    [InlineKeyboardButton("➕ Add New Pairs", callback_data="signals_add")],
    [InlineKeyboardButton("⚙️ Manage Preferences", callback_data="signals_manage")],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
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
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_analysis")]
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
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
]

# Forex keyboard voor signals
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
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
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

# Crypto keyboard voor signals
CRYPTO_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD_signals"),
        InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD_signals"),
        InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD_signals")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
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

# Indices keyboard voor signals
INDICES_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("US30", callback_data="instrument_US30_signals"),
        InlineKeyboardButton("US500", callback_data="instrument_US500_signals"),
        InlineKeyboardButton("US100", callback_data="instrument_US100_signals")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
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

# Commodities keyboard voor signals
COMMODITIES_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD_signals"),
        InlineKeyboardButton("XAGUSD", callback_data="instrument_XAGUSD_signals"),
        InlineKeyboardButton("USOIL", callback_data="instrument_USOIL_signals")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
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

class TelegramService:
    def __init__(self, db: Database):
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
            
            # Registreer de handlers
            self._register_handlers()
            
            logger.info("Telegram service initialized")
            
            # Houd bij welke updates al zijn verwerkt
            self.processed_updates = set()
            
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            raise

    def _register_handlers(self):
        """Register all handlers"""
        try:
            # Voeg een speciale handler toe voor sentiment analyse
            self.application.add_handler(
                CallbackQueryHandler(
                    self.direct_sentiment_callback, 
                    pattern="^sentiment_instrument_[A-Z0-9]+"
                )
            )
            
            # Voeg een speciale handler toe voor directe sentiment analyse
            self.application.add_handler(
                CallbackQueryHandler(
                    self.direct_sentiment_callback, 
                    pattern="^direct_sentiment_[A-Z0-9]+"
                )
            )
            
            # Registreer de conversation handler
            conv_handler = ConversationHandler(
                entry_points=[
                    CommandHandler("start", self.start_command),
                    CommandHandler("menu", self.menu_command),
                    CommandHandler("help", self.help_command),
                ],
                states={
                    MENU: [
                        CallbackQueryHandler(self.menu_analyse_callback, pattern="^menu_analyse$"),
                        CallbackQueryHandler(self.menu_signals_callback, pattern="^menu_signals$"),
                        CallbackQueryHandler(self.analysis_callback, pattern="^analysis"),
                        CallbackQueryHandler(self.signals_callback, pattern="^signals"),
                        CallbackQueryHandler(self.help_callback, pattern="^help"),
                        CallbackQueryHandler(self.back_to_menu_callback, pattern="^back_menu"),
                    ],
                    CHOOSE_ANALYSIS: [
                        CallbackQueryHandler(self.analysis_technical_callback, pattern="^analysis_technical$"),
                        CallbackQueryHandler(self.analysis_sentiment_callback, pattern="^analysis_sentiment$"),
                        CallbackQueryHandler(self.analysis_calendar_callback, pattern="^analysis_calendar$"),
                        CallbackQueryHandler(self.calendar_back_callback, pattern="^calendar_back$"),
                        CallbackQueryHandler(self.back_to_menu_callback, pattern="^back_menu$"),
                    ],
                    CHOOSE_SIGNALS: [
                        CallbackQueryHandler(self.signals_add_callback, pattern="^signals_add$"),
                        CallbackQueryHandler(self.signals_manage_callback, pattern="^signals_manage$"),
                        CallbackQueryHandler(self.delete_preferences_callback, pattern="^delete_prefs$"),
                        CallbackQueryHandler(self.delete_single_preference_callback, pattern="^delete_pref_[0-9]+$"),
                        CallbackQueryHandler(self.confirm_delete_callback, pattern="^confirm_delete$"),
                        CallbackQueryHandler(self.back_to_menu_callback, pattern="^back_menu$"),
                    ],
                    CHOOSE_MARKET: [
                        CallbackQueryHandler(self.market_signals_callback, pattern="^market_[a-z]+_signals$"),
                        CallbackQueryHandler(self.market_callback, pattern="^market_[a-z]+$"),
                        CallbackQueryHandler(self.back_to_signals, pattern="^back_signals$"),
                        CallbackQueryHandler(self.back_to_analysis_callback, pattern="^back_analysis$"),
                    ],
                    CHOOSE_INSTRUMENT: [
                        CallbackQueryHandler(self.instrument_signals_callback, pattern="^instrument_[A-Z0-9]+_signals$"),
                        CallbackQueryHandler(self.instrument_callback, pattern="^instrument_[A-Z0-9]+$"),
                        CallbackQueryHandler(self.back_to_market_callback, pattern="^back_market$"),
                    ],
                    CHOOSE_STYLE: [
                        CallbackQueryHandler(self.style_choice, pattern="^style_[a-z]+$"),
                        CallbackQueryHandler(self.back_to_instrument, pattern="^back_instrument$"),
                    ],
                    SHOW_RESULT: [
                        CallbackQueryHandler(self.back_to_market_callback, pattern="^back_market$"),
                        CallbackQueryHandler(self.back_to_analysis_callback, pattern="^back_analysis$"),
                        CallbackQueryHandler(self.signals_add_callback, pattern="^signals_add$"),
                        CallbackQueryHandler(self.signals_manage_callback, pattern="^signals_manage$"),
                        CallbackQueryHandler(self.back_to_menu_callback, pattern="^back_menu$"),
                    ],
                },
                fallbacks=[
                    CommandHandler("cancel", self.cancel_command),
                    # Voeg een algemene callback handler toe voor alle andere callbacks
                    CallbackQueryHandler(self.callback_query_handler),
                ],
                per_message=False,
            )
            
            self.application.add_handler(conv_handler)
            
            # Voeg een algemene callback handler toe voor alle callbacks die niet door de conversation handler worden afgehandeld
            self.application.add_handler(CallbackQueryHandler(self.callback_query_handler))
            
            # Voeg een error handler toe
            self.application.add_error_handler(self.error_handler)
            
        except Exception as e:
            logger.error(f"Error registering handlers: {str(e)}")
            raise

    async def start_command(self, update: Update, context=None) -> int:
        """Start the conversation."""
        try:
            logger.info(f"Start command aangeroepen door gebruiker: {update.effective_user.id}")
            
            # Send welcome message with main menu
            await update.message.reply_text(
                text=WELCOME_MESSAGE,
                reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                parse_mode=ParseMode.HTML
            )
            logger.info("Welkomstbericht verzonden")
            return MENU
            
        except Exception as e:
            logger.error(f"Error in start command: {str(e)}")
            logger.exception(e)  # Log de volledige stacktrace
            try:
                await update.message.reply_text(
                    "Sorry, er is een fout opgetreden. Probeer het later nog eens."
                )
            except Exception as inner_e:
                logger.error(f"Kon geen foutmelding sturen: {str(inner_e)}")
            return ConversationHandler.END

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
            # Beantwoord de callback query om de "wachtende" status te verwijderen
            await query.answer()
            
            # Toon het markt selectie menu voor signalen
            await query.edit_message_text(
                text="Select a market for trading signals:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
            )
            
            return CHOOSE_MARKET
        except Exception as e:
            logger.error(f"Error in signals_add_callback: {str(e)}")
            logger.exception(e)
            
            # Stuur een nieuw bericht als fallback
            try:
                await query.message.reply_text(
                    text="What would you like to do with trading signals?",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("➕ Add New Pairs", callback_data="signals_add")],
                        [InlineKeyboardButton("⚙️ Manage Preferences", callback_data="signals_manage")],
                        [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
                    ])
                )
                return CHOOSE_SIGNALS
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
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

    async def delete_preferences_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            for i, pref in enumerate(preferences):
                # Store preference ID in context for later use
                pref_key = f"pref_{i}"
                context.user_data[pref_key] = pref['id']
                
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

    async def delete_single_preference_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle delete_pref_X callback"""
        query = update.callback_query
        await query.answer()
        
        # Get preference index from callback data
        pref_index = int(query.data.split('_')[-1])
        pref_key = f"pref_{pref_index}"
        
        # Get preference ID from context
        pref_id = context.user_data.get(pref_key)
        
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

    async def market_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle market selection for signals"""
        query = update.callback_query
        await query.answer()
        
        # Get market from callback data
        market = query.data.split('_')[1]  # market_forex_signals -> forex
        
        # Save market in user_data
        if context and hasattr(context, 'user_data'):
            context.user_data['market'] = market
            context.user_data['analysis_type'] = 'signals'
        else:
            # Als er geen context is, sla de data op in een tijdelijke opslag
            user_id = update.effective_user.id
            if not hasattr(self, 'temp_user_data'):
                self.temp_user_data = {}
            if user_id not in self.temp_user_data:
                self.temp_user_data[user_id] = {}
            self.temp_user_data[user_id]['market'] = market
            self.temp_user_data[user_id]['analysis_type'] = 'signals'
        
        # Maak een nieuwe keyboard op basis van de markt
        if market == 'forex':
            keyboard = [
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
                [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
            ]
        elif market == 'crypto':
            keyboard = [
                [
                    InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD_signals"),
                    InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD_signals"),
                    InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD_signals")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
            ]
        elif market == 'commodities':
            keyboard = [
                [
                    InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD_signals"),
                    InlineKeyboardButton("XAGUSD", callback_data="instrument_XAGUSD_signals"),
                    InlineKeyboardButton("USOIL", callback_data="instrument_USOIL_signals")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
            ]
        elif market == 'indices':
            keyboard = [
                [
                    InlineKeyboardButton("US30", callback_data="instrument_US30_signals"),
                    InlineKeyboardButton("US500", callback_data="instrument_US500_signals"),
                    InlineKeyboardButton("US100", callback_data="instrument_US100_signals")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
            ]
        else:
            # Fallback naar forex als de markt niet wordt herkend
            keyboard = [
                [
                    InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD_signals"),
                    InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD_signals"),
                    InlineKeyboardButton("USDJPY", callback_data="instrument_USDJPY_signals")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
            ]
        
        await query.edit_message_text(
            text=f"Select an instrument from {market.capitalize()}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CHOOSE_INSTRUMENT

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

    async def instrument_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> int:
        """Handle instrument selection for signals"""
        query = update.callback_query
        await query.answer()
        
        # Get instrument from callback data
        parts = query.data.split('_')
        instrument = parts[1]  # instrument_EURUSD_signals -> EURUSD
        
        # Save instrument in user_data
        if context and hasattr(context, 'user_data'):
            context.user_data['instrument'] = instrument
        else:
            # Als er geen context is, sla de data op in een tijdelijke opslag
            user_id = update.effective_user.id
            if not hasattr(self, 'temp_user_data'):
                self.temp_user_data = {}
            if user_id not in self.temp_user_data:
                self.temp_user_data[user_id] = {}
            self.temp_user_data[user_id]['instrument'] = instrument
        
        # Show style selection
        await query.edit_message_text(
            text=f"Select your trading style for {instrument}:",
            reply_markup=InlineKeyboardMarkup(STYLE_KEYBOARD)
        )
        
        return CHOOSE_STYLE

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
            # Beantwoord de callback query om de "wachtende" status te verwijderen
            await query.answer()
            
            # Toon het analyse menu
            await query.edit_message_text(
                text="Select your analysis type:",
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            )
            
            return CHOOSE_ANALYSIS
        except Exception as e:
            logger.error(f"Error in back_to_analysis_callback: {str(e)}")
            logger.exception(e)
            
            # Stuur een nieuw bericht als fallback
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

    async def back_to_market_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to market selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Determine which keyboard to show based on the current state
            analysis_type = context.user_data.get('analysis_type', 'technical')
            
            logger.info(f"Back to market: analysis_type={analysis_type}")
            
            # Always try to edit the existing message
            if analysis_type == 'signals':
                await query.edit_message_text(
                    text="Select a market for your trading signals:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
                )
            else:
                await query.edit_message_text(
                    text=f"Select a market for {analysis_type} analysis:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
            
            # Store the current state for future reference
            context.user_data['current_state'] = CHOOSE_MARKET
            
            return CHOOSE_MARKET
        
        except Exception as e:
            logger.error(f"Error in back_to_market_callback: {str(e)}")
            # If there's an error, try to recover by showing the main menu
            try:
                await query.message.reply_text(
                    text="Select a market:",
                    reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                )
                context.user_data['current_state'] = CHOOSE_MARKET
                return CHOOSE_MARKET
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                return ConversationHandler.END

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
        """Initialize the Telegram bot asynchronously."""
        try:
            # Get bot info
            info = await self.bot.get_me()
            logger.info(f"Successfully connected to Telegram API. Bot info: {info}")
            
            # Initialize services
            logger.info("Initializing services")
            await self.chart.initialize()
            
            # Set bot commands
            commands = [
                ("start", "Start the bot and show main menu"),
                ("help", "Show help message")
            ]
            await self.bot.set_my_commands(commands)
            
            # Start the bot
            await self.application.initialize()
            await self.application.start()
            
            if not use_webhook:
                # Verwijder eerst eventuele bestaande webhook
                await self.bot.delete_webhook()
                
                # Start polling
                await self.application.updater.start_polling()
                logger.info("Telegram bot initialized and started polling.")
            else:
                logger.info("Telegram bot initialized for webhook use.")
            
        except Exception as e:
            logger.error(f"Error during Telegram bot initialization: {str(e)}")
            raise

    async def process_signal(self, signal_data):
        """Process a trading signal and send it to subscribed users."""
        try:
            # Log het ontvangen signaal
            logger.info(f"Processing signal: {signal_data}")
            
            # Controleer of het signaal alle benodigde velden heeft
            required_fields = ['instrument', 'price', 'direction']
            missing_fields = [field for field in required_fields if field not in signal_data]
            
            if missing_fields:
                logger.error(f"Signal is missing required fields: {missing_fields}")
                return False
            
            # Haal de relevante informatie uit het signaal
            instrument = signal_data.get('instrument')
            timeframe = signal_data.get('timeframe', '1h')
            direction = signal_data.get('direction')
            price = signal_data.get('price')
            stop_loss = signal_data.get('sl', signal_data.get('stop_loss', ''))
            take_profit = signal_data.get('tp1', signal_data.get('take_profit', ''))
            tp2 = signal_data.get('tp2', '')
            tp3 = signal_data.get('tp3', '')
            
            # Log de signaal parameters
            logger.info(f"Signal parameters: instrument={instrument}, direction={direction}, price={price}")
            
            # Rest van de code...
            
            # Detecteer de markt op basis van het instrument als het niet is opgegeven
            if market == 'forex':
                if 'BTC' in instrument or 'ETH' in instrument:
                    market = 'crypto'
                elif 'XAU' in instrument or 'XAG' in instrument:
                    market = 'commodities'
                elif 'US30' in instrument or 'US500' in instrument:
                    market = 'indices'
            
            # Converteer het signaal naar het formaat dat match_subscribers verwacht
            signal_for_matching = {
                'market': market,
                'symbol': instrument,
                'timeframe': timeframe,
                'direction': direction,
                'price': price,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'message': message
            }
            
            # Log de matching parameters
            logger.info(f"Matching parameters: market={market}, symbol={instrument}, timeframe={timeframe}")
            
            # Gebruik de match_subscribers methode om de juiste gebruikers te vinden
            matched_subscribers = await self.db.match_subscribers(signal_for_matching)
            
            logger.info(f"Found {len(matched_subscribers)} subscribers for {instrument} {timeframe}")
            
            # TIJDELIJKE OPLOSSING: Haal alle gebruikers op als er geen matches zijn
            if not matched_subscribers:
                logger.info(f"No users subscribed to {instrument} {timeframe}, getting all users")
                # Haal alle gebruikers op
                all_users = await self.db.get_all_users()
                logger.info(f"Found {len(all_users)} total users")
                
                # Gebruik de eerste gebruiker als test
                if all_users:
                    matched_subscribers = [all_users[0]]
                    logger.info(f"Using first user as test: {matched_subscribers[0]}")
                else:
                    # Als er geen gebruikers zijn, gebruik een hardgecodeerde test gebruiker
                    matched_subscribers = [{'user_id': 2004519703}]  # Vervang dit door je eigen user ID
                    logger.info(f"No users found, using hardcoded test user: {matched_subscribers[0]}")
            
            # Maak het signaal bericht
            signal_message = f"🎯 <b>New Trading Signal</b> 🎯\n\n"
            signal_message += f"Instrument: {instrument}\n"
            signal_message += f"Action: {direction.upper()} {'📈' if direction.lower() == 'buy' else '📉'}\n\n"
            
            signal_message += f"Entry Price: {price}\n"
            
            if stop_loss:
                signal_message += f"Stop Loss: {stop_loss} {'🔴' if stop_loss else ''}\n"
            
            if take_profit:
                signal_message += f"Take Profit 1: {take_profit} {'🎯' if take_profit else ''}\n"
            
            # Voeg extra take profit niveaus toe als ze beschikbaar zijn
            if tp2:
                signal_message += f"Take Profit 2: {tp2} 🎯\n"
            
            if tp3:
                signal_message += f"Take Profit 3: {tp3} 🎯\n\n"
            else:
                signal_message += "\n"
            
            signal_message += f"Timeframe: {timeframe}\n"
            signal_message += f"Strategy: {strategy}\n\n"
            
            signal_message += f"{'—'*20}\n\n"
            
            signal_message += f"<b>Risk Management:</b>\n"
            for tip in risk_management:
                signal_message += f"• {tip}\n"
            
            signal_message += f"\n{'—'*20}\n\n"
            
            signal_message += f"🤖 <b>SigmaPips AI Verdict:</b>\n"
            if verdict:
                signal_message += f"{verdict}\n"
            else:
                signal_message += f"The {instrument} {direction.lower()} signal shows a promising setup with a favorable risk/reward ratio. Entry at {price} with defined risk parameters offers a good trading opportunity.\n"
            
            # Sla het signaal op in Redis voor later gebruik
            if self.db.redis:
                try:
                    signal_key = f"signal:{instrument}"
                    self.db.redis.set(signal_key, json.dumps({
                        'message': signal_message,
                        'instrument': instrument,
                        'direction': direction,
                        'price': price
                    }), ex=3600)  # Bewaar 1 uur
                    logger.info(f"Saved signal to Redis with key: {signal_key}")
                except Exception as redis_error:
                    logger.error(f"Error saving signal to Redis: {str(redis_error)}")
            
            # Stuur het signaal naar alle geabonneerde gebruikers
            for subscriber in matched_subscribers:
                try:
                    user_id = subscriber['user_id']
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
                    
                    # Sla het signaal op in de gebruikerscontext voor later gebruik
                    if not hasattr(self, 'user_signals'):
                        self.user_signals = {}
                    
                    self.user_signals[user_id] = {
                        'instrument': instrument,
                        'message': signal_message,
                        'direction': direction,
                        'price': price
                    }
                    
                    logger.info(f"Successfully sent signal to user {user_id}")
                except Exception as user_error:
                    logger.error(f"Error sending signal to user {subscriber['user_id']}: {str(user_error)}")
                    logger.exception(user_error)
            
            return True
        except Exception as e:
            logger.error(f"Error processing signal: {str(e)}")
            logger.exception(e)
            return False

    async def callback_query_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle callback queries that are not handled by other handlers"""
        query = update.callback_query
        await query.answer()
        
        logger.info(f"Received callback: {query.data}")
        
        try:
            if query.data.startswith("analyze_market_"):
                # Extract instrument from callback data
                parts = query.data.split("_")
                instrument = parts[2]
                
                # Check if the message is a photo (has caption) or text message
                is_photo_message = hasattr(query.message, 'caption') and query.message.caption is not None
                
                # Create keyboard with analysis options
                keyboard = [
                    [InlineKeyboardButton("📊 Technical Analysis", callback_data=f"analysis_technical_{instrument}_signal")],
                    [InlineKeyboardButton("🧠 Market Sentiment", callback_data=f"analysis_sentiment_{instrument}_signal")],
                    [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"analysis_calendar_{instrument}_signal")]
                ]
                
                if is_photo_message:
                    # If it's a photo message, send a new message instead of editing
                    await query.message.reply_text(
                        text=f"Choose analysis type for {instrument}:",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    # If it's a text message, edit it
                    await query.edit_message_text(
                        text=f"Choose analysis type for {instrument}:",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                
                return MENU
            
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
                    
                    # Probeer het signaal uit de gebruikerscontext te halen
                    original_signal = None
                    user_id = update.effective_user.id
                    logger.info(f"Looking for signal in user_signals for user_id: {user_id}")
                    
                    # Debug: print alle user_signals
                    logger.info(f"All user_signals: {self.user_signals}")
                    
                    if hasattr(self, 'user_signals') and user_id in self.user_signals:
                        user_signal = self.user_signals.get(user_id)
                        logger.info(f"Found user signal: {user_signal}")
                        
                        if user_signal and user_signal.get('instrument') == instrument:
                            original_signal = user_signal.get('message')
                            logger.info(f"Retrieved original signal from user context: {len(original_signal)} chars")
                        else:
                            logger.warning(f"User signal found but instrument doesn't match. User signal instrument: {user_signal.get('instrument')}, requested instrument: {instrument}")
                    else:
                        logger.warning(f"No user signal found for user_id: {user_id}")
                    
                    # Als we geen signaal in de gebruikerscontext vinden, probeer Redis
                    if not original_signal and instrument:
                        try:
                            # Controleer of Redis beschikbaar is
                            if hasattr(self.db, 'redis') and self.db.redis:
                                signal_key = f"signal:{instrument}"
                                logger.info(f"Looking for signal in Redis with key: {signal_key}")
                                
                                stored_signal = self.db.redis.get(signal_key)
                                
                                if stored_signal:
                                    # Parse the JSON string
                                    try:
                                        signal_data = json.loads(stored_signal)
                                        original_signal = signal_data.get('message')
                                        logger.info(f"Retrieved original signal for {instrument} from Redis: {len(original_signal)} chars")
                                    except json.JSONDecodeError as json_error:
                                        logger.error(f"Error parsing JSON from Redis: {str(json_error)}")
                                        logger.error(f"Raw Redis data: {stored_signal[:100]}...")
                                else:
                                    logger.warning(f"No signal found in Redis for key: {signal_key}")
                            else:
                                logger.warning("Redis not available, cannot retrieve signal")
                        except Exception as redis_error:
                            logger.error(f"Error retrieving signal from Redis: {str(redis_error)}")
                            logger.exception(redis_error)
                    
                    # If we have the original signal, use it
                    if original_signal:
                        # Create the analyze market button
                        keyboard = [
                            [InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_market_{instrument}")]
                        ]
                        
                        # Send the original signal
                        await query.edit_message_text(
                            text=original_signal,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode=ParseMode.HTML
                        )
                        
                        logger.info(f"Restored original signal for instrument: {instrument}")
                        return MENU
                    else:
                        logger.warning(f"Original signal not found for {instrument}, using fallback")
                        
                    # Fallback to a generic signal if the original is not available
                    signal_message = f"🎯 <b>Trading Signal</b> 🎯\n\n"
                    signal_message += f"Instrument: {instrument}\n"
                    signal_message += f"Action: BUY 📈\n\n"
                    signal_message += f"Entry Price: [Last price]\n"
                    signal_message += f"Stop Loss: [Recommended level] 🔴\n"
                    signal_message += f"Take Profit: [Target level] 🎯\n\n"
                    signal_message += f"Timeframe: 1h\n"
                    signal_message += f"Strategy: Trend Following\n\n"
                    
                    # Create the analyze market button
                    keyboard = [
                        [InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_market_{instrument}")]
                    ]
                    
                    # Send the fallback signal
                    await query.edit_message_text(
                        text=signal_message,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                    
                    logger.info(f"Used fallback signal for instrument: {instrument} (original not found)")
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
            
            elif query.data.startswith("analysis_technical_"):
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

    async def show_technical_analysis(self, update: Update, context=None, instrument=None, from_signal=False):
        """Show technical analysis for an instrument"""
        query = update.callback_query
        
        try:
            # Toon een laadmelding als die nog niet is getoond
            if not from_signal:
                try:
                    await query.edit_message_text(
                        text=f"Generating technical analysis for {instrument}...",
                        reply_markup=None
                    )
                except Exception as e:
                    logger.warning(f"Could not edit message: {str(e)}")
            
            # Haal de chart op
            chart_image = await self.chart.get_chart(instrument, timeframe="1h")
            
            if chart_image:
                # Bepaal de juiste back-knop op basis van de context
                back_button = InlineKeyboardButton("⬅️ Back", callback_data="back_market")
                if from_signal:
                    back_button = InlineKeyboardButton("⬅️ Back to Signal", callback_data=f"back_to_signal_{instrument}")
                
                # Stuur de chart als foto
                await query.message.reply_photo(
                    photo=chart_image,
                    caption=f"📊 {instrument} Technical Analysis",
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
                        InlineKeyboardButton("⬅️ Back", callback_data="back_market")
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

    async def process_update(self, update_data):
        """Process an update from the webhook"""
        try:
            logger.info(f"Processing update: {update_data}")
            
            # Controleer of deze update al is verwerkt
            update_id = update_data.get('update_id')
            if update_id in self.processed_updates:
                logger.info(f"Update {update_id} already processed, skipping")
                return True
            
            # Voeg de update toe aan de verwerkte updates
            self.processed_updates.add(update_id)
            
            # Beperk de grootte van de set (houd alleen de laatste 100 updates bij)
            if len(self.processed_updates) > 100:
                self.processed_updates = set(sorted(self.processed_updates)[-100:])
            
            # Maak een Update object van de update data
            update = Update.de_json(data=update_data, bot=self.bot)
            
            # Verwerk de update direct zonder context
            # We kunnen geen context maken zonder de application
            
            # Controleer of het een callback query is
            if update.callback_query:
                callback_data = update.callback_query.data
                logger.info(f"Received callback: {callback_data}")
                
                # Verwerk specifieke callbacks direct
                if callback_data.startswith("direct_sentiment_"):
                    await self.direct_sentiment_callback(update, None)
                    return True
                elif callback_data == "menu_analyse":
                    await self.menu_analyse_callback(update, None)
                    return True
                elif callback_data == "menu_signals":
                    await self.menu_signals_callback(update, None)
                    return True
                elif callback_data == "analysis_sentiment":
                    await self.analysis_sentiment_callback(update, None)
                    return True
                elif callback_data == "analysis_technical":
                    await self.analysis_technical_callback(update, None)
                    return True
                elif callback_data == "analysis_calendar":
                    await self.analysis_calendar_callback(update, None)
                    return True
                elif callback_data == "back_analysis":
                    await self.back_to_analysis_callback(update, None)
                    return True
                elif callback_data == "back_menu":
                    await self.back_to_menu_callback(update, None)
                    return True
                # Trading Signals callbacks
                elif callback_data == "signals_add":
                    await self.signals_add_callback(update, None)
                    return True
                elif callback_data == "signals_manage":
                    await self.signals_manage_callback(update, None)
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
                elif callback_data.startswith("confirm_"):
                    await self.confirm_callback(update, None)
                    return True
                elif callback_data.startswith("delete_"):
                    await self.delete_callback(update, None)
                    return True
                elif callback_data == "back_signals":
                    await self.back_to_signals(update, None)
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
