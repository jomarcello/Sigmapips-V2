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
Welcome to SigmaPips Trading Bot!

I will help you set up your trading preferences.
Please answer a few questions to get started.
"""

HELP_MESSAGE = """
Available commands:
start - Start the bot and set preferences
help - Show this help message
"""

# Back button
BACK_BUTTON = InlineKeyboardButton("Back", callback_data="back")

# Keyboard layouts - alle buttons onder elkaar
MARKET_KEYBOARD = [
    [InlineKeyboardButton("Forex", callback_data="market_forex")],
    [InlineKeyboardButton("Indices", callback_data="market_indices")],
    [InlineKeyboardButton("Commodities", callback_data="market_commodities")],
    [InlineKeyboardButton("Crypto", callback_data="market_crypto")]
]

# Instrument keyboards per markt
FOREX_KEYBOARD = [
    [InlineKeyboardButton("EUR/USD", callback_data="instrument_EURUSD")],
    [InlineKeyboardButton("GBP/USD", callback_data="instrument_GBPUSD")],
    [InlineKeyboardButton("USD/JPY", callback_data="instrument_USDJPY")],
    [InlineKeyboardButton("USD/CHF", callback_data="instrument_USDCHF")],
    [InlineKeyboardButton("AUD/USD", callback_data="instrument_AUDUSD")],
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
    [InlineKeyboardButton("Gold (XAU/USD)", callback_data="instrument_XAUUSD")],
    [InlineKeyboardButton("Silver (XAG/USD)", callback_data="instrument_XAGUSD")],
    [InlineKeyboardButton("Oil (WTI)", callback_data="instrument_WTI")],
    [InlineKeyboardButton("Oil (Brent)", callback_data="instrument_Brent")],
    [InlineKeyboardButton("Natural Gas", callback_data="instrument_NGAS")],
    [BACK_BUTTON]
]

CRYPTO_KEYBOARD = [
    [InlineKeyboardButton("Bitcoin (BTC/USD)", callback_data="instrument_BTCUSD")],
    [InlineKeyboardButton("Ethereum (ETH/USD)", callback_data="instrument_ETHUSD")],
    [InlineKeyboardButton("Ripple (XRP/USD)", callback_data="instrument_XRPUSD")],
    [InlineKeyboardButton("Solana (SOL/USD)", callback_data="instrument_SOLUSD")],
    [InlineKeyboardButton("Litecoin (LTC/USD)", callback_data="instrument_LTCUSD")],
    [BACK_BUTTON]
]

TIMEFRAME_KEYBOARD = [
    [InlineKeyboardButton("1m", callback_data="timeframe_1m")],
    [InlineKeyboardButton("15m", callback_data="timeframe_15m")],
    [InlineKeyboardButton("1h", callback_data="timeframe_1h")],
    [InlineKeyboardButton("4h", callback_data="timeframe_4h")],
    [BACK_BUTTON]
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
            fallbacks=[CommandHandler("start", self._start_command)],
            per_message=True
        )
        
        # Add handlers
        self.app.add_handler(conv_handler)
        
        # Add webhook handler
        self.app.add_handler(CommandHandler("webhook", self._webhook_handler))
        
        logger.info("Telegram service initialized")
            
    async def initialize(self):
        """Async initialization"""
        try:
            info = await self.bot.get_me()
            logger.info(f"Successfully connected to Telegram API. Bot info: {info}")
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
                text="Please select a market:",
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
                text="Please select a market:",
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
            # TODO: Add database save logic here
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

    async def _webhook_handler(self, update: Update, context):
        """Handle webhook updates"""
        try:
            logger.info(f"Received webhook update: {update}")
            # Process the update
            await self.app.process_update(update)
        except Exception as e:
            logger.error(f"Error processing webhook: {str(e)}")

# ... rest van de code ...
