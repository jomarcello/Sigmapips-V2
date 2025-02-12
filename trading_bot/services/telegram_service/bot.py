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
        
        # Voeg command handlers toe zonder / in de logging
        self.app.add_handler(CommandHandler("start", self._start_command))
        
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

# ... rest van de code ...
