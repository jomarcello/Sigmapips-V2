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

# ... rest van de code ...
