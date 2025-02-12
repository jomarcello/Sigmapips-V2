import os
import ssl
import asyncio
import logging
import aiohttp
from typing import Dict, Any

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes
)
from telegram.constants import ParseMode

from trading_bot.services.database.db import Database

logger = logging.getLogger(__name__)

# States
CHOOSE_MARKET, CHOOSE_INSTRUMENT, CHOOSE_TIMEFRAME, MANAGE_PREFERENCES = range(4)

# Messages
WELCOME_MESSAGE = """
🤖 Welcome to SigmaPips Trading Bot!

I will help you set up your trading preferences.
Please answer a few questions to get started.
"""

HELP_MESSAGE = """
Available commands:
start - Start the bot and set preferences
help - Show this help message
"""

# Back button
BACK_BUTTON = InlineKeyboardButton("⬅️ Back", callback_data="back")

# Keyboard layouts - alle buttons onder elkaar
MARKET_KEYBOARD = [
    [InlineKeyboardButton("Forex", callback_data="market_forex")],
    [InlineKeyboardButton("Indices", callback_data="market_indices")],
    [InlineKeyboardButton("Commodities", callback_data="market_commodities")],
    [InlineKeyboardButton("Crypto", callback_data="market_crypto")]
]

# Instrument keyboards per markt
FOREX_KEYBOARD = [
    [InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD")],
    [InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD")],
    [InlineKeyboardButton("USDJPY", callback_data="instrument_USDJPY")],
    [InlineKeyboardButton("USDCHF", callback_data="instrument_USDCHF")],
    [InlineKeyboardButton("AUDUSD", callback_data="instrument_AUDUSD")],
    [BACK_BUTTON]
]

INDICES_KEYBOARD = [
    [InlineKeyboardButton("S&P 500", callback_data="instrument_SP500")],
    [InlineKeyboardButton("NASDAQ 100", callback_data="instrument_NAS100")],
    [InlineKeyboardButton("Dow Jones", callback_data="instrument_DJI")],
    [InlineKeyboardButton("DAX 40", callback_data="instrument_DAX40")],
    [InlineKeyboardButton("FTSE 100", callback_data="instrument_FTSE100")],
    [BACK_BUTTON]
]

COMMODITIES_KEYBOARD = [
    [InlineKeyboardButton("Gold (XAUUSD)", callback_data="instrument_XAUUSD")],
    [InlineKeyboardButton("Silver (XAGUSD)", callback_data="instrument_XAGUSD")],
    [InlineKeyboardButton("Oil (WTI)", callback_data="instrument_WTI")],
    [InlineKeyboardButton("Oil (Brent)", callback_data="instrument_Brent")],
    [InlineKeyboardButton("Natural Gas", callback_data="instrument_NGAS")],
    [BACK_BUTTON]
]

CRYPTO_KEYBOARD = [
    [InlineKeyboardButton("Bitcoin (BTCUSD)", callback_data="instrument_BTCUSD")],
    [InlineKeyboardButton("Ethereum (ETHUSD)", callback_data="instrument_ETHUSD")],
    [InlineKeyboardButton("Ripple (XRPUSD)", callback_data="instrument_XRPUSD")],
    [InlineKeyboardButton("Solana (SOLUSD)", callback_data="instrument_SOLUSD")],
    [InlineKeyboardButton("Litecoin (LTCUSD)", callback_data="instrument_LTCUSD")],
    [BACK_BUTTON]
]

TIMEFRAME_KEYBOARD = [
    [InlineKeyboardButton("1m", callback_data="timeframe_1m")],
    [InlineKeyboardButton("15m", callback_data="timeframe_15m")],
    [InlineKeyboardButton("1h", callback_data="timeframe_1h")],
    [InlineKeyboardButton("4h", callback_data="timeframe_4h")],
    [BACK_BUTTON]
]

AFTER_SETUP_KEYBOARD = [
    [InlineKeyboardButton("Add More Combinations", callback_data="add_more")],
    [InlineKeyboardButton("View Preferences", callback_data="view_prefs")],
    [InlineKeyboardButton("Manage Preferences", callback_data="manage_prefs")]
]

class TelegramService:
    def __init__(self, db: Database):
        """Initialize telegram service"""
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError("Missing TELEGRAM_BOT_TOKEN")
            
        self.db = db
        
        # SSL setup zonder verificatie voor ontwikkeling
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Gebruik Application builder voor bot setup
        self.app = Application.builder().token(self.token).build()
        self.bot = self.app.bot
        
        # Conversation handler setup
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self._start_command)],
            states={
                CHOOSE_MARKET: [
                    CallbackQueryHandler(self._market_choice, pattern="^market_|back$")
                ],
                CHOOSE_INSTRUMENT: [
                    CallbackQueryHandler(self._instrument_choice, pattern="^instrument_|back$")
                ],
                CHOOSE_TIMEFRAME: [
                    CallbackQueryHandler(self._timeframe_choice, pattern="^timeframe_|back$")
                ],
                MANAGE_PREFERENCES: [
                    CallbackQueryHandler(self._manage_preferences, pattern="^add_more|view_prefs|manage_prefs$")
                ]
            },
            fallbacks=[CommandHandler("start", self._start_command)]
        )
        
        # Add handlers
        self.app.add_handler(conv_handler)
        
        logger.info("Telegram service initialized")
            
    async def initialize(self):
        """Async initialization"""
        try:
            info = await self.bot.get_me()
            logger.info(f"Successfully connected to Telegram API. Bot info: {info}")
            
            # Initialize the application
            await self.app.initialize()
            
            # Start the application without polling
            await self.app.start()
            
            # Log webhook info
            webhook_info = await self.bot.get_webhook_info()
            logger.info(f"Current webhook info: {webhook_info}")
            
        except Exception as e:
            logger.error(f"Failed to connect to Telegram API: {str(e)}")
            raise
            
    async def send_signal(self, chat_id: str, signal: Dict[str, Any], sentiment: str = None, chart: str = None, events: list = None):
        try:
            message = self._format_signal_message(signal, sentiment, events)
            logger.info(f"Attempting to send message to chat_id: {chat_id}")
            await self.bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
            if chart:
                await self.bot.send_photo(chat_id=chat_id, photo=chart)
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {str(e)}", exc_info=True)
            return False
            
    def _format_signal_message(self, signal: Dict[str, Any], sentiment: str = None, events: list = None) -> str:
        """Format signal data into a readable message"""
        message = f"New Signal Alert\n\n"
        message += f"Symbol: {signal['symbol']}\n"
        message += f"Action: {signal['action']}\n"
        message += f"Price: {signal['price']}\n"
        message += f"Stop Loss: {signal['stopLoss']}\n"
        message += f"Take Profit: {signal['takeProfit']}\n"
        message += f"Timeframe: {signal.get('timeframe', 'Not specified')}\n"
        
        if sentiment:
            message += f"\nSentiment Analysis\n{sentiment}\n"
            
        if events and len(events) > 0:
            message += f"\nUpcoming Events\n"
            for event in events[:3]:
                message += f"• {event}\n"
                
        return message

    async def _start_command(self, update: Update, context):
        """Handle start command"""
        try:
            reply_markup = InlineKeyboardMarkup(MARKET_KEYBOARD)
            await update.message.reply_text(
                WELCOME_MESSAGE,
                reply_markup=reply_markup
            )
            logger.info(f"Start command handled for user {update.effective_user.id}")
            return CHOOSE_MARKET
        except Exception as e:
            logger.error(f"Error handling start command: {str(e)}")

    async def _market_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle market selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back":
            reply_markup = InlineKeyboardMarkup(MARKET_KEYBOARD)
            await query.edit_message_text(
                text=WELCOME_MESSAGE,
                reply_markup=reply_markup
            )
            return CHOOSE_MARKET
        
        # Store the chosen market
        context.user_data['market'] = query.data.replace('market_', '')
        
        # Show instruments based on market choice
        keyboard_map = {
            'forex': FOREX_KEYBOARD,
            'indices': INDICES_KEYBOARD,
            'commodities': COMMODITIES_KEYBOARD,
            'crypto': CRYPTO_KEYBOARD
        }
        
        reply_markup = InlineKeyboardMarkup(keyboard_map[context.user_data['market']])
        await query.edit_message_text(
            text="Please select an instrument:",
            reply_markup=reply_markup
        )
        return CHOOSE_INSTRUMENT

    async def _instrument_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle instrument selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back":
            reply_markup = InlineKeyboardMarkup(MARKET_KEYBOARD)
            await query.edit_message_text(
                text=WELCOME_MESSAGE,
                reply_markup=reply_markup
            )
            return CHOOSE_MARKET
        
        # Store the chosen instrument
        context.user_data['instrument'] = query.data.replace('instrument_', '')
        
        reply_markup = InlineKeyboardMarkup(TIMEFRAME_KEYBOARD)
        await query.edit_message_text(
            text="Please select a timeframe:",
            reply_markup=reply_markup
        )
        return CHOOSE_TIMEFRAME

    async def _timeframe_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle timeframe selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back":
            keyboard_map = {
                'forex': FOREX_KEYBOARD,
                'indices': INDICES_KEYBOARD,
                'commodities': COMMODITIES_KEYBOARD,
                'crypto': CRYPTO_KEYBOARD
            }
            reply_markup = InlineKeyboardMarkup(keyboard_map[context.user_data['market']])
            await query.edit_message_text(
                text="Please select an instrument:",
                reply_markup=reply_markup
            )
            return CHOOSE_INSTRUMENT
        
        # Store the chosen timeframe
        context.user_data['timeframe'] = query.data.replace('timeframe_', '')
        
        # Save preferences to database
        try:
            # Prepare data for database
            user_id = update.effective_user.id
            preferences = {
                'market': context.user_data['market'],
                'instrument': context.user_data['instrument'],
                'timeframe': context.user_data['timeframe'],
                'is_active': True
            }
            
            # Check if user already exists
            existing = self.db.supabase.table('subscribers').select('*').eq('user_id', user_id).execute()
            
            if existing.data:
                # Update existing preferences
                response = self.db.supabase.table('subscribers').update(preferences).eq('user_id', user_id).execute()
            else:
                # Insert new preferences
                preferences['user_id'] = user_id
                response = self.db.supabase.table('subscribers').insert(preferences).execute()
            
            logger.info(f"Saved preferences to database: {response}")
            
            reply_markup = InlineKeyboardMarkup(AFTER_SETUP_KEYBOARD)
            await query.edit_message_text(
                text=f"Preferences saved!\n\n"
                     f"Market: {context.user_data['market']}\n"
                     f"Instrument: {context.user_data['instrument']}\n"
                     f"Timeframe: {context.user_data['timeframe']}",
                reply_markup=reply_markup
            )
            return MANAGE_PREFERENCES
        
        except Exception as e:
            logger.error(f"Error saving preferences: {str(e)}")
            await query.edit_message_text(
                text="Error saving preferences. Please try again."
            )
            return ConversationHandler.END

    async def _manage_preferences(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle preference management"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "add_more":
            reply_markup = InlineKeyboardMarkup(MARKET_KEYBOARD)
            await query.edit_message_text(
                text="Please select a market:",
                reply_markup=reply_markup
            )
            return CHOOSE_MARKET
        elif query.data == "view_prefs":
            # TODO: Add view preferences logic
            pass
        elif query.data == "manage_prefs":
            # TODO: Add manage preferences logic
            pass
        
        return MANAGE_PREFERENCES

    async def set_webhook(self, webhook_url: str):
        """Set webhook for the bot"""
        try:
            # Verwijder bestaande webhook
            await self.bot.delete_webhook()
            
            # Stel nieuwe webhook in met de juiste path
            webhook_url = f"{webhook_url}/webhook"
            await self.bot.set_webhook(
                url=webhook_url,
                allowed_updates=['message', 'callback_query']
            )
            logger.info(f"Webhook set to: {webhook_url}")
            
            # Verify webhook is set
            webhook_info = await self.bot.get_webhook_info()
            logger.info(f"Webhook verification: {webhook_info}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {str(e)}")
            raise

# ... rest van de code ...
