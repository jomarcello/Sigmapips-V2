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
            
            # Initialiseer de user_states dictionary
            self.user_states = {}
            
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
        
        # Determine which keyboard to show based on market
        keyboard_map = {
            'forex': FOREX_KEYBOARD,
            'crypto': CRYPTO_KEYBOARD,
            'commodities': COMMODITIES_KEYBOARD,
            'indices': INDICES_KEYBOARD
        }
        
        keyboard = keyboard_map.get(market, FOREX_KEYBOARD)
        
        # Adjust callback data for signals
        for row in keyboard:
            for button in row:
                if "Back" not in button.text:
                    button.callback_data = f"instrument_{button.text}_signals"
        
        # Add back button
        for row in keyboard:
            for button in row:
                if "Back" in button.text:
                    button.callback_data = "back_signals"
        
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
            
            # Adjust callback data for signals
            for row in keyboard:
                for button in row:
                    if "Back" not in button.text:
                        button.callback_data = f"instrument_{button.text}_signals"
            
            # Add back button
            for row in keyboard:
                for button in row:
                    if "Back" in button.text:
                        button.callback_data = "back_signals"
            
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
        """Handle back to market callback"""
        try:
            query = update.callback_query
            chat_id = query.message.chat_id
            message_id = query.message.message_id
            
            # Log de huidige staat
            current_state = self.user_states.get(chat_id, {}).get('state', 0)
            analysis_type = self.user_states.get(chat_id, {}).get('analysis_type', 'technical')
            logger.info(f"Back to market: current_state={current_state}, analysis_type={analysis_type}")
            
            # Bevestig de callback query
            await query.answer()
            
            # Controleer of het bericht een foto bevat
            if query.message.photo:
                # Als het een foto is, verwijder het huidige bericht en stuur een nieuw bericht
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                except Exception as delete_error:
                    logger.error(f"Error deleting message: {str(delete_error)}")
                
                # Stuur een nieuw bericht met de instrumenten
                await self.show_instruments(update, context)
            else:
                # Als het een tekstbericht is, bewerk het bericht
                keyboard = self.get_instruments_keyboard()
                
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="🔍 Selecteer een instrument om te analyseren:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            # Reset de staat
            self.user_states[chat_id] = {'state': 1, 'analysis_type': analysis_type}
            
        except Exception as e:
            logger.error(f"Error in back_to_market_callback: {str(e)}")
            
            # Probeer te herstellen door een nieuw bericht te sturen
            try:
                chat_id = update.callback_query.message.chat_id
                await update.callback_query.answer()
                
                # Stuur een nieuw bericht met de instrumenten
                keyboard = self.get_instruments_keyboard()
                await update.callback_query.message.reply_text(
                    "🔍 Selecteer een instrument om te analyseren:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Reset de staat
                self.user_states[chat_id] = {'state': 1, 'analysis_type': 'technical'}
                
            except Exception as recovery_error:
                logger.error(f"Failed to recover from error: {str(recovery_error)}")

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

    async def process_update(self, update_data):
        """Process an update from the webhook."""
        try:
            # Converteer de update data naar een Update object
            update = Update.de_json(update_data, self.bot)
            
            # Log de update voor debugging
            if isinstance(update, Update):
                if update.callback_query:
                    logger.info(f"Processing callback: {update.callback_query.data}")
                elif update.message and update.message.text:
                    logger.info(f"Processing message: {update.message.text}")
            
            # Verwerk de update via de application
            await self.application.process_update(update)
            
            return True
        except Exception as e:
            logger.error(f"Error processing update: {str(e)}")
            return False

    async def show_chart(self, update: Update, context: CallbackContext, instrument: str, timeframe: str = "1h", fullscreen: bool = False):
        """Show chart for instrument"""
        try:
            # Haal de chat ID op
            chat_id = update.effective_chat.id
            
            # Stuur een "loading" bericht
            loading_message = await context.bot.send_message(
                chat_id=chat_id,
                text=f"⏳ Genereren van chart voor {instrument} ({timeframe})..."
            )
            
            # Haal de chart op
            chart_service = ChartService()
            chart_bytes = await chart_service.get_chart(instrument, timeframe, fullscreen)
            
            if not chart_bytes:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=loading_message.message_id,
                    text=f"❌ Kon geen chart genereren voor {instrument}. Probeer het later opnieuw."
                )
                return
            
            # Maak een caption voor de chart
            caption = f"📊 {instrument} Technical Analysis"
            
            # Maak een keyboard met een "Back" knop
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data="back_market")]
            ]
            
            # Verwijder het loading bericht
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=loading_message.message_id
            )
            
            # Stuur de chart als foto
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=chart_bytes,
                caption=caption,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # Update de gebruikersstaat
            self.user_states[chat_id] = {'state': 6, 'instrument': instrument, 'timeframe': timeframe, 'analysis_type': 'technical'}
            
        except Exception as e:
            logger.error(f"Error showing chart: {str(e)}")
            
            # Probeer het loading bericht te updaten als er een fout optreedt
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=loading_message.message_id,
                    text=f"❌ Er is een fout opgetreden bij het genereren van de chart: {str(e)}"
                )
            except Exception as update_error:
                logger.error(f"Error updating loading message: {str(update_error)}")

    async def show_instruments(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show instruments keyboard"""
        try:
            chat_id = update.effective_chat.id
            
            # Bepaal welke markt we moeten tonen
            market = self.user_states.get(chat_id, {}).get('market', 'forex')
            
            # Bepaal welk keyboard we moeten tonen op basis van de markt
            keyboard_map = {
                'forex': self.get_forex_keyboard(),
                'crypto': self.get_crypto_keyboard(),
                'indices': self.get_indices_keyboard(),
                'commodities': self.get_commodities_keyboard()
            }
            
            keyboard = keyboard_map.get(market, self.get_forex_keyboard())
            
            # Stuur het bericht met de instrumenten
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔍 Selecteer een instrument uit {market.capitalize()}:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # Update de gebruikersstaat
            self.user_states[chat_id] = {'state': 2, 'market': market, 'analysis_type': 'technical'}
            
        except Exception as e:
            logger.error(f"Error showing instruments: {str(e)}")
            
            # Probeer te herstellen door een generiek bericht te sturen
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Er is een fout opgetreden. Probeer het opnieuw met /start."
                )
            except Exception as recovery_error:
                logger.error(f"Failed to recover from error: {str(recovery_error)}")

    def get_instruments_keyboard(self):
        """Get the instruments keyboard based on the current market"""
        # Standaard forex keyboard
        return [
            [
                InlineKeyboardButton("EUR/USD", callback_data="instrument_EURUSD"),
                InlineKeyboardButton("GBP/USD", callback_data="instrument_GBPUSD"),
                InlineKeyboardButton("USD/JPY", callback_data="instrument_USDJPY")
            ],
            [
                InlineKeyboardButton("EUR/GBP", callback_data="instrument_EURGBP"),
                InlineKeyboardButton("AUD/USD", callback_data="instrument_AUDUSD"),
                InlineKeyboardButton("USD/CAD", callback_data="instrument_USDCAD")
            ],
            [
                InlineKeyboardButton("EUR/JPY", callback_data="instrument_EURJPY"),
                InlineKeyboardButton("GBP/JPY", callback_data="instrument_GBPJPY"),
                InlineKeyboardButton("CHF/JPY", callback_data="instrument_CHFJPY")
            ],
            [
                InlineKeyboardButton("⬅️ Back to Markets", callback_data="back_to_markets")
            ]
        ]

    def get_forex_keyboard(self):
        """Get the forex instruments keyboard"""
        return [
            [
                InlineKeyboardButton("EUR/USD", callback_data="instrument_EURUSD"),
                InlineKeyboardButton("GBP/USD", callback_data="instrument_GBPUSD"),
                InlineKeyboardButton("USD/JPY", callback_data="instrument_USDJPY")
            ],
            [
                InlineKeyboardButton("EUR/GBP", callback_data="instrument_EURGBP"),
                InlineKeyboardButton("AUD/USD", callback_data="instrument_AUDUSD"),
                InlineKeyboardButton("USD/CAD", callback_data="instrument_USDCAD")
            ],
            [
                InlineKeyboardButton("EUR/JPY", callback_data="instrument_EURJPY"),
                InlineKeyboardButton("GBP/JPY", callback_data="instrument_GBPJPY"),
                InlineKeyboardButton("CHF/JPY", callback_data="instrument_CHFJPY")
            ],
            [
                InlineKeyboardButton("⬅️ Back to Markets", callback_data="back_to_markets")
            ]
        ]

    def get_crypto_keyboard(self):
        """Get the crypto instruments keyboard"""
        return [
            [
                InlineKeyboardButton("BTC/USD", callback_data="instrument_BTCUSD"),
                InlineKeyboardButton("ETH/USD", callback_data="instrument_ETHUSD")
            ],
            [
                InlineKeyboardButton("XRP/USD", callback_data="instrument_XRPUSD"),
                InlineKeyboardButton("LTC/USD", callback_data="instrument_LTCUSD")
            ],
            [
                InlineKeyboardButton("SOL/USD", callback_data="instrument_SOLUSD"),
                InlineKeyboardButton("BNB/USD", callback_data="instrument_BNBUSD")
            ],
            [
                InlineKeyboardButton("⬅️ Back to Markets", callback_data="back_to_markets")
            ]
        ]

    def get_indices_keyboard(self):
        """Get the indices instruments keyboard"""
        return [
            [
                InlineKeyboardButton("US500", callback_data="instrument_US500"),
                InlineKeyboardButton("US100", callback_data="instrument_US100")
            ],
            [
                InlineKeyboardButton("US30", callback_data="instrument_US30"),
                InlineKeyboardButton("UK100", callback_data="instrument_UK100")
            ],
            [
                InlineKeyboardButton("DE40", callback_data="instrument_DE40"),
                InlineKeyboardButton("JP225", callback_data="instrument_JP225")
            ],
            [
                InlineKeyboardButton("⬅️ Back to Markets", callback_data="back_to_markets")
            ]
        ]

    def get_commodities_keyboard(self):
        """Get the commodities instruments keyboard"""
        return [
            [
                InlineKeyboardButton("GOLD", callback_data="instrument_XAUUSD"),
                InlineKeyboardButton("SILVER", callback_data="instrument_XAGUSD")
            ],
            [
                InlineKeyboardButton("OIL", callback_data="instrument_XTIUSD"),
                InlineKeyboardButton("NATURAL GAS", callback_data="instrument_NATGAS")
            ],
            [
                InlineKeyboardButton("⬅️ Back to Markets", callback_data="back_to_markets")
            ]
        ]
