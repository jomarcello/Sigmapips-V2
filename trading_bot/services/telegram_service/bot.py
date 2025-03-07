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
/manage - Manage your preferences
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
            # Initialize bot
            self.token = os.getenv("TELEGRAM_BOT_TOKEN")
            if not self.token:
                raise ValueError("Missing Telegram bot token")
            
            self.bot = Bot(self.token)
            self.application = Application.builder().token(self.token).build()
            
            # Store database instance
            self.db = db
            
            # Setup services
            self.chart = ChartService()
            self.sentiment = MarketSentimentService()
            self.calendar = EconomicCalendarService()
            
            # Setup conversation handler
            conv_handler = ConversationHandler(
                entry_points=[CommandHandler("start", self.start_command)],
                states={
                    MENU: [
                        CallbackQueryHandler(self.menu_analyse_callback, pattern="^menu_analyse$"),
                        CallbackQueryHandler(self.menu_signals_callback, pattern="^menu_signals$"),
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
                fallbacks=[CommandHandler("help", self.help_command)],
                name="my_conversation",
                persistent=False,
                per_message=False,
            )
            
            # Add handlers
            self.application.add_handler(conv_handler)
            self.application.add_handler(CommandHandler("help", self.help_command))
            
            # Add reset conversation handler
            self.application.add_handler(CommandHandler("reset", self.reset_conversation))
            
            logger.info("Telegram service initialized")
            
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
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
            #
