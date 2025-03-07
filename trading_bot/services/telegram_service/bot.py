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
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_signals")]
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
            
            # Registreer de handlers
            self._register_handlers()
            
            logger.info("Telegram service initialized")
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            raise

    def _register_handlers(self):
        """Register all handlers"""
        try:
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

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation."""
        try:
            # Send welcome message with main menu
            await update.message.reply_text(
                text=WELCOME_MESSAGE,
                reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                parse_mode=ParseMode.HTML
            )
            return MENU
            
        except Exception as e:
            logger.error(f"Error in start command: {str(e)}")
            await update.message.reply_text(
                "Sorry, something went wrong. Please try again later."
            )
            return ConversationHandler.END

    async def menu_analyse_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle menu_analyse callback"""
        query = update.callback_query
        await query.answer()
        
        # Show the analysis menu
        await query.edit_message_text(
            text="Select your analysis type:",
            reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
        )
        
        return CHOOSE_ANALYSIS

    async def menu_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle menu_signals callback"""
        query = update.callback_query
        await query.answer()
        
        # Show the signals menu
        await query.edit_message_text(
            text="What would you like to do with trading signals?",
            reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
        )
        
        return CHOOSE_SIGNALS

    async def analysis_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle analysis callback"""
        query = update.callback_query
        await query.answer()
        
        # Toon het analyse menu
        await query.edit_message_text(
            text="Select your analysis type:",
            reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
        )
        
        return CHOOSE_ANALYSIS

    async def signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle signals callback"""
        query = update.callback_query
        await query.answer()
        
        # Toon het signals menu
        await query.edit_message_text(
            text="What would you like to do with trading signals?",
            reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
        )
        
        return CHOOSE_SIGNALS

    async def help_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle help callback"""
        query = update.callback_query
        await query.answer()
        
        # Toon help informatie
        await query.edit_message_text(
            text=HELP_MESSAGE,
            parse_mode=ParseMode.HTML
        )
        
        return MENU

    async def analysis_technical_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle analysis_technical callback"""
        query = update.callback_query
        await query.answer()
        
        # Show market selection for technical analysis
        await query.edit_message_text(
            text="Select a market for technical analysis:",
            reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
        )
        
        # Save analysis type in user_data
        context.user_data['analysis_type'] = 'technical'
        
        return CHOOSE_MARKET

    async def analysis_sentiment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle sentiment analysis selection"""
        query = update.callback_query
        await query.answer()
        
        # Store analysis type in user_data
        context.user_data['analysis_type'] = 'sentiment'
        context.user_data['current_state'] = CHOOSE_MARKET
        
        # Show market selection
        await query.edit_message_text(
            text="Select a market for sentiment analysis:",
            reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
        )
        
        return CHOOSE_MARKET

    async def analysis_calendar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle economic calendar selection"""
        query = update.callback_query
        await query.answer()
        
        # Store analysis type in user_data
        context.user_data['analysis_type'] = 'calendar'
        context.user_data['current_state'] = CHOOSE_ANALYSIS
        
        try:
            # Show loading message
            await query.edit_message_text(
                text="Retrieving economic calendar data...",
                reply_markup=None
            )
            
            # Get calendar data
            calendar_data = await self.calendar.get_economic_calendar()
            
            # Use a unique callback data for the back button
            back_button = InlineKeyboardButton("⬅️ Back to Menu", callback_data="calendar_back")
            
            # Show calendar data
            await query.edit_message_text(
                text=calendar_data,
                reply_markup=InlineKeyboardMarkup([[back_button]]),
                parse_mode=ParseMode.HTML
            )
            
            return CHOOSE_ANALYSIS
        
        except Exception as e:
            logger.error(f"Error getting calendar data: {str(e)}")
            await query.edit_message_text(
                text="An error occurred while retrieving the economic calendar. Please try again later.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back to Menu", callback_data="calendar_back")
                ]]),
                parse_mode=ParseMode.HTML
            )
            return CHOOSE_ANALYSIS

    async def calendar_back_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back from calendar to analysis menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            logger.info("Handling calendar_back_callback")
            
            # Edit the current message instead of sending a new one
            await query.edit_message_text(
                text="Select your analysis type:",
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            )
            
            # Update state in user_data
            context.user_data['current_state'] = CHOOSE_ANALYSIS
            
            return CHOOSE_ANALYSIS
        
        except Exception as e:
            logger.error(f"Error in calendar_back_callback: {str(e)}")
            # If there's an error, try to recover by showing the main menu
            try:
                await query.edit_message_text(
                    text=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
                context.user_data['current_state'] = MENU
                return MENU
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")

    async def signals_add_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle signals_add callback"""
        query = update.callback_query
        await query.answer()
        
        # Show market selection for signals
        await query.edit_message_text(
            text="Select a market for your trading signals:",
            reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
        )
        
        return CHOOSE_MARKET

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

    async def market_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle market selection for analysis"""
        query = update.callback_query
        await query.answer()
        
        # Get market from callback data
        market = query.data.replace('market_', '')
        
        # Save market in user_data
        context.user_data['market'] = market
        
        # Determine which keyboard to show based on market
        keyboard_map = {
            'forex': FOREX_KEYBOARD,
            'crypto': CRYPTO_KEYBOARD,
            'indices': INDICES_KEYBOARD,
            'commodities': COMMODITIES_KEYBOARD
        }
        
        keyboard = keyboard_map.get(market, FOREX_KEYBOARD)
        
        # Show instruments for the selected market
        await query.edit_message_text(
            text=f"Select an instrument from {market.capitalize()}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CHOOSE_INSTRUMENT

    async def market_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle market selection for signals"""
        query = update.callback_query
        await query.answer()
        
        # Get market from callback data
        market = query.data.split('_')[1]  # market_forex_signals -> forex
        
        # Save market in user_data
        context.user_data['market'] = market
        context.user_data['analysis_type'] = 'signals'
        
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
                [InlineKeyboardButton("⬅️ Terug", callback_data="back_signals")]
            ]
        elif market == 'crypto':
            keyboard = [
                [
                    InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD_signals"),
                    InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD_signals"),
                    InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD_signals")
                ],
                [InlineKeyboardButton("⬅️ Terug", callback_data="back_signals")]
            ]
        elif market == 'commodities':
            keyboard = [
                [
                    InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD_signals"),
                    InlineKeyboardButton("XAGUSD", callback_data="instrument_XAGUSD_signals"),
                    InlineKeyboardButton("USOIL", callback_data="instrument_USOIL_signals")
                ],
                [InlineKeyboardButton("⬅️ Terug", callback_data="back_signals")]
            ]
        elif market == 'indices':
            keyboard = [
                [
                    InlineKeyboardButton("US30", callback_data="instrument_US30_signals"),
                    InlineKeyboardButton("US500", callback_data="instrument_US500_signals"),
                    InlineKeyboardButton("US100", callback_data="instrument_US100_signals")
                ],
                [InlineKeyboardButton("⬅️ Terug", callback_data="back_signals")]
            ]
        else:
            # Fallback naar forex als de markt niet wordt herkend
            keyboard = [
                [
                    InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD_signals"),
                    InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD_signals"),
                    InlineKeyboardButton("USDJPY", callback_data="instrument_USDJPY_signals")
                ],
                [InlineKeyboardButton("⬅️ Terug", callback_data="back_signals")]
            ]
        
        await query.edit_message_text(
            text=f"Select an instrument from {market.capitalize()}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CHOOSE_INSTRUMENT

    async def instrument_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle instrument selection for analysis"""
        query = update.callback_query
        await query.answer()
        
        # Get instrument from callback data
        instrument = query.data.replace('instrument_', '')
        
        # Store instrument in user_data
        context.user_data['instrument'] = instrument
        context.user_data['current_state'] = SHOW_RESULT
        
        # Get analysis type from user_data
        analysis_type = context.user_data.get('analysis_type', 'technical')
        
        try:
            if analysis_type == 'technical':
                # Show loading message
                await query.edit_message_text(
                    text=f"Generating chart for {instrument}...",
                    reply_markup=None
                )
                
                try:
                    # Get chart image - only get a single timeframe (1h)
                    chart_image = await self.chart.get_chart(instrument, timeframe="1h")
                    
                    if chart_image:
                        # Show chart image
                        await query.message.reply_photo(
                            photo=chart_image,
                            caption=f"📊 {instrument} Technical Analysis",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("⬅️ Back", callback_data="back_market")
                            ]])
                        )
                        
                        # Delete the loading message
                        await query.edit_message_text(
                            text=f"Chart for {instrument} generated successfully.",
                            reply_markup=None
                        )
                    else:
                        # Show error message
                        await query.edit_message_text(
                            text=f"❌ Could not generate chart for {instrument}. Please try again later.",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("⬅️ Back", callback_data="back_market")
                            ]])
                        )
                except Exception as chart_error:
                    logger.error(f"Error getting chart: {str(chart_error)}")
                    await query.edit_message_text(
                        text=f"❌ Could not generate chart for {instrument}. Please try again later.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Back", callback_data="back_market")
                        ]])
                    )
                
                return SHOW_RESULT
            
            elif analysis_type == 'sentiment':
                # Show loading message
                await query.edit_message_text(
                    text=f"Getting market sentiment for {instrument}...",
                    reply_markup=None
                )
                
                # Get sentiment analysis
                sentiment = await self.sentiment.get_market_sentiment(instrument)
                
                # Show sentiment analysis
                await query.edit_message_text(
                    text=sentiment,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_market")
                    ]]),
                    parse_mode=ParseMode.HTML
                )
                
                return SHOW_RESULT
            
            # Default: go to style selection for signals
            context.user_data['instrument'] = instrument
            
            await query.edit_message_text(
                text=f"Select your trading style for {instrument}:",
                reply_markup=InlineKeyboardMarkup(STYLE_KEYBOARD)
            )
            
            return CHOOSE_STYLE
            
        except Exception as e:
            logger.error(f"Error in instrument_callback: {str(e)}")
            await query.edit_message_text(
                text="An error occurred while retrieving the instrument data. Please try again later.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="back_market")
                ]])
            )
            return CHOOSE_MARKET

    async def instrument_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle instrument selection for signals"""
        query = update.callback_query
        await query.answer()
        
        # Get instrument from callback data
        parts = query.data.split('_')
        instrument = parts[1]  # instrument_EURUSD_signals -> EURUSD
        
        # Save instrument in user_data
        context.user_data['instrument'] = instrument
        
        # Show style selection
        await query.edit_message_text(
            text=f"Select your trading style for {instrument}:",
            reply_markup=InlineKeyboardMarkup(STYLE_KEYBOARD)
        )
        
        return CHOOSE_STYLE

    async def style_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle style selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back_instrument":
            # Back to instrument selection
            market = context.user_data.get('market', 'forex')
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
        context.user_data['style'] = style
        context.user_data['timeframe'] = STYLE_TIMEFRAME_MAP[style]
        
        try:
            # Save preferences
            user_id = update.effective_user.id
            market = context.user_data.get('market', 'forex')
            instrument = context.user_data.get('instrument', 'EURUSD')
            
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

    async def back_to_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to menu"""
        query = update.callback_query
        await query.answer()
        
        # Reset user_data
        context.user_data.clear()
        
        # Show main menu
        await query.edit_message_text(
            text=WELCOME_MESSAGE,
            reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
            parse_mode=ParseMode.HTML
        )
        
        return MENU

    async def back_to_analysis_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to analysis menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            logger.info("Handling back_to_analysis_callback - start")
            
            # Log message details for debugging
            message_id = query.message.message_id if query.message else "unknown"
            chat_id = query.message.chat.id if query.message and query.message.chat else "unknown"
            logger.info(f"Message ID: {message_id}, Chat ID: {chat_id}")
            
            # Show analysis menu with a completely new message to avoid any issues
            try:
                # First try to edit the existing message
                await query.edit_message_text(
                    text="Select your analysis type:",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
                logger.info("Successfully edited message")
            except Exception as edit_error:
                logger.error(f"Error editing message: {str(edit_error)}")
                # If editing fails, try to send a new message
                await query.message.reply_text(
                    text="Select your analysis type:",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
                logger.info("Sent new message as fallback")
            
            # Update state in user_data
            context.user_data['current_state'] = CHOOSE_ANALYSIS
            logger.info("Updated user_data state to CHOOSE_ANALYSIS")
            
            logger.info("Handling back_to_analysis_callback - end")
            return CHOOSE_ANALYSIS
        
        except Exception as e:
            logger.error(f"Error in back_to_analysis_callback: {str(e)}")
            # If there's an error, try to recover by showing the main menu
            try:
                await query.message.reply_text(
                    text=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
                context.user_data['current_state'] = MENU
                return MENU
            except Exception as inner_e:
                logger.error(f"Failed to recover from error: {str(inner_e)}")
                return ConversationHandler.END

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

    async def initialize(self, use_webhook=True):
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
            
            # Zorg ervoor dat we een market hebben
            if 'market' not in signal_data:
                # Detecteer de markt op basis van het instrument
                instrument = signal_data.get('instrument', '')
                if 'BTC' in instrument or 'ETH' in instrument:
                    signal_data['market'] = 'crypto'
                elif 'XAU' in instrument or 'XAG' in instrument:
                    signal_data['market'] = 'commodities'
                elif 'US30' in instrument or 'US500' in instrument:
                    signal_data['market'] = 'indices'
                else:
                    signal_data['market'] = 'forex'
                
                logger.info(f"Detected market: {signal_data['market']} for instrument {instrument}")
            
            # Haal de relevante informatie uit het signaal
            instrument = signal_data.get('instrument')
            timeframe = signal_data.get('timeframe', '1h')
            direction = signal_data.get('direction')
            price = signal_data.get('price')
            stop_loss = signal_data.get('stop_loss')
            take_profit = signal_data.get('take_profit')
            message = signal_data.get('message')
            market = signal_data.get('market', 'forex')
            strategy = signal_data.get('strategy', 'Test Strategy')
            risk_management = signal_data.get('risk_management', ["Position size: 1-2% max", "Use proper stop loss", "Follow your trading plan"])
            verdict = signal_data.get('verdict', '')
            
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
            
            # Als er geen matches zijn, log dit en stop de verwerking
            if not matched_subscribers:
                logger.info(f"No subscribers found for {instrument} {timeframe}. Signal will not be sent.")
                return False
            
            # Maak het signaal bericht
            signal_message = f"🎯 <b>New Trading Signal</b> 🎯\n\n"
            signal_message += f"Instrument: {instrument}\n"
            signal_message += f"Action: {direction.upper()} {'📈' if direction.lower() == 'buy' else '📉'}\n\n"
            
            signal_message += f"Entry Price: {price}\n"
            
            if stop_loss:
                signal_message += f"Stop Loss: {stop_loss} {'🔴' if stop_loss else ''}\n"
            
            if take_profit:
                signal_message += f"Take Profit: {take_profit} {'🎯' if take_profit else ''}\n\n"
            
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
            
            # Stuur het signaal naar alle geabonneerde gebruikers
            success_count = 0
            for subscriber in matched_subscribers:
                try:
                    user_id = subscriber['user_id']
                    logger.info(f"Sending signal to user {user_id}")
                    
                    # Stuur het signaal met de analyse-knop direct eronder
                    keyboard = [
                        [InlineKeyboardButton("🔍 Analyze Market", callback_data=f"analyze_market_{instrument}")]
                    ]
                    
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=signal_message,
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
            
                    logger.info(f"Successfully sent signal with analyze button to user {user_id}")
                    success_count += 1
                except Exception as user_error:
                    logger.error(f"Error sending signal to user {subscriber['user_id']}: {str(user_error)}")
                    logger.exception(user_error)
            
            return success_count > 0
        except Exception as e:
            logger.error(f"Error processing signal: {str(e)}")
            logger.exception(e)
            return False

    async def callback_query_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle callback queries that don't match other patterns"""
        query = update.callback_query
        await query.answer()
        
        # Log de callback data
        logger.info(f"Received callback: {query.data}")
        
        # Verwerk de callback data
        if query.data.startswith("analyze_market_"):
            # Extract instrument from callback data
            parts = query.data.split("_")
            instrument = parts[2]
            
            # Toon de analyse opties
            keyboard = [
                [InlineKeyboardButton("📊 Technical Analysis", callback_data=f"analysis_technical_{instrument}_signal")],
                [InlineKeyboardButton("🧠 Market Sentiment", callback_data=f"analysis_sentiment_{instrument}_signal")],
                [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"analysis_calendar_{instrument}_signal")],
                [InlineKeyboardButton("⬅️ Back to Signal", callback_data=f"back_to_signal")]
            ]
            
            await query.edit_message_text(
                text=f"Choose analysis type for {instrument}:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return MENU
        
        elif query.data == "back_to_signal":
            # We can't actually go back to the original signal message,
            # but we can inform the user to check their chat history
            try:
                # Try to extract the instrument from the current message text
                instrument = None
                message_text = query.message.text if query.message and hasattr(query.message, 'text') else ""
                
                # Extract instrument from message text like "Choose analysis type for XAUUSD:"
                instrument_match = re.search(r"for ([A-Z0-9]+):", message_text)
                if instrument_match:
                    instrument = instrument_match.group(1)
                
                # If not found in message text, try user_data
                if not instrument and context.user_data and 'instrument' in context.user_data:
                    instrument = context.user_data.get('instrument')
                
                # Prepare response message
                response_text = "You've returned to signal view. "
                response_text += "Please check your chat history for the original signal message."
                
                # Create keyboard with appropriate buttons
                keyboard = []
                if instrument:
                    keyboard.append([InlineKeyboardButton("🔍 Analyze Again", callback_data=f"analyze_market_{instrument}")])
                
                keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")])
                
                # Send the response
                await query.edit_message_text(
                    text=response_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Log success
                logger.info(f"Successfully handled back_to_signal with instrument: {instrument}")
                return MENU
            except Exception as e:
                logger.error(f"Error in back_to_signal handler: {str(e)}")
                logger.exception(e)  # Log full traceback
                
                # If there's an error, try to show a simple message
                try:
                    await query.edit_message_text(
                        text="Please check your chat history for the original signal.",
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
            
            return await self.show_technical_analysis(update, context, instrument, from_signal)
        
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

    async def show_technical_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE, instrument: str = None, from_signal: bool = False) -> int:
        """Show technical analysis for an instrument"""
        query = update.callback_query
        
        if not instrument:
            # Get instrument from user_data if not provided
            instrument = context.user_data.get('instrument', 'EURUSD')
        
        # Show loading message
        await query.edit_message_text(
            text=f"Generating technical analysis for {instrument}...",
            reply_markup=None
        )
        
        try:
            # Get chart image
            chart_image = await self.chart.get_chart(instrument)
            
            if not chart_image:
                # Create appropriate back button based on source
                back_button = InlineKeyboardButton("⬅️ Back to Analysis", callback_data=f"analyze_market_{instrument}") if from_signal else InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
                
                await query.edit_message_text(
                    text=f"❌ Could not generate chart for {instrument}. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[back_button]])
                )
                return MENU
            
            # Create appropriate back button based on source
            back_button = InlineKeyboardButton("⬅️ Back to Analysis", callback_data=f"analyze_market_{instrument}") if from_signal else InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
            
            # Send chart image
            await query.message.reply_photo(
                photo=chart_image,
                caption=f"Technical Analysis for {instrument}",
                reply_markup=InlineKeyboardMarkup([[back_button]])
            )
            
            # Delete the loading message
            await query.delete_message()
            
            return MENU
        
        except Exception as e:
            logger.error(f"Error showing technical analysis: {str(e)}")
            
            # Create appropriate back button based on source
            back_button = InlineKeyboardButton("⬅️ Back to Analysis", callback_data=f"analyze_market_{instrument}") if from_signal else InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
            
            await query.edit_message_text(
                text=f"❌ Error generating analysis for {instrument}. Please try again later.",
                reply_markup=InlineKeyboardMarkup([[back_button]])
            )
            return MENU

    async def show_sentiment_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE, instrument: str = None, from_signal: bool = False) -> int:
        """Show sentiment analysis for an instrument"""
        query = update.callback_query
        
        if not instrument:
            # Get instrument from user_data if not provided
            instrument = context.user_data.get('instrument', 'EURUSD')
        
        # Show loading message
        await query.edit_message_text(
            text=f"Getting market sentiment for {instrument}...",
            reply_markup=None
        )
        
        try:
            # Get sentiment analysis
            sentiment = await self.sentiment.get_market_sentiment(instrument)
            
            # Create appropriate back button based on source
            back_button = InlineKeyboardButton("⬅️ Back to Analysis", callback_data=f"analyze_market_{instrument}") if from_signal else InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
            
            # Show sentiment analysis
            await query.edit_message_text(
                text=sentiment,
                reply_markup=InlineKeyboardMarkup([[back_button]]),
                parse_mode=ParseMode.HTML
            )
            
            return MENU
        
        except Exception as e:
            logger.error(f"Error showing sentiment analysis: {str(e)}")
            
            # Create appropriate back button based on source
            back_button = InlineKeyboardButton("⬅️ Back to Analysis", callback_data=f"analyze_market_{instrument}") if from_signal else InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
            
            await query.edit_message_text(
                text=f"❌ Error getting sentiment for {instrument}. Please try again later.",
                reply_markup=InlineKeyboardMarkup([[back_button]])
            )
            return MENU

    async def show_economic_calendar(self, update: Update, context: ContextTypes.DEFAULT_TYPE, instrument: str = None, from_signal: bool = False) -> int:
        """Show economic calendar for an instrument"""
        query = update.callback_query
        
        if not instrument:
            # Get instrument from user_data if not provided
            instrument = context.user_data.get('instrument', 'EURUSD')
        
        # Show loading message
        await query.edit_message_text(
            text=f"Getting economic calendar for {instrument}...",
            reply_markup=None
        )
        
        try:
            # Get economic calendar
            calendar = await self.calendar.get_economic_calendar(instrument)
            
            # Create appropriate back button based on source
            back_button = InlineKeyboardButton("⬅️ Back to Analysis", callback_data=f"analyze_market_{instrument}") if from_signal else InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
            
            # Show economic calendar
            await query.edit_message_text(
                text=calendar,
                reply_markup=InlineKeyboardMarkup([[back_button]]),
                parse_mode=ParseMode.HTML
            )
            
            return MENU
        
        except Exception as e:
            logger.error(f"Error showing economic calendar: {str(e)}")
            
            # Create appropriate back button based on source
            back_button = InlineKeyboardButton("⬅️ Back to Analysis", callback_data=f"analyze_market_{instrument}") if from_signal else InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
            
            await query.edit_message_text(
                text=f"❌ Error getting economic calendar for {instrument}. Please try again later.",
                reply_markup=InlineKeyboardMarkup([[back_button]])
            )
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
            
            # Maak een Update object van de update data
            update = Update.de_json(data=update_data, bot=self.bot)
            
            # Stuur de update naar de application
            await self.application.process_update(update)
            
            return True
        except Exception as e:
            logger.error(f"Error processing update: {str(e)}")
            logger.exception(e)
            return False
