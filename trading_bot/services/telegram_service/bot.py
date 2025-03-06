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
🚀 <b>Welkom bij SigmaPips Trading Bot!</b> 🚀

Ik ben je AI-gestuurde trading assistent, ontworpen om je te helpen betere trading beslissingen te nemen.

📊 <b>Mijn Diensten:</b>
• <b>Technische Analyse</b> - Krijg real-time chart analyse en key levels

• <b>Markt Sentiment</b> - Begrijp de markt stemming en trends

• <b>Economische Kalender</b> - Blijf op de hoogte van markt-bewegende gebeurtenissen

• <b>Trading Signalen</b> - Ontvang precieze entry/exit punten voor je favoriete paren

Selecteer een optie hieronder om te beginnen:
"""

MENU_MESSAGE = """
Welkom bij SigmaPips Trading Bot!

Kies een commando:

/start - Stel nieuwe trading paren in
Voeg nieuwe markt/instrument/timeframe combinaties toe om signalen te ontvangen

/manage - Beheer je voorkeuren
Bekijk, bewerk of verwijder je opgeslagen trading paren

Hulp nodig? Gebruik /help om alle beschikbare commando's te zien.
"""

HELP_MESSAGE = """
Beschikbare commando's:
/menu - Toon hoofdmenu
/start - Stel nieuwe trading paren in
/manage - Beheer je voorkeuren
/help - Toon dit help bericht
"""

# Start menu keyboard
START_KEYBOARD = [
    [InlineKeyboardButton("🔍 Analyseer Markt", callback_data="menu_analyse")],
    [InlineKeyboardButton("📊 Trading Signalen", callback_data="menu_signals")]
]

# Analysis menu keyboard
ANALYSIS_KEYBOARD = [
    [InlineKeyboardButton("📈 Technische Analyse", callback_data="analysis_technical")],
    [InlineKeyboardButton("🧠 Markt Sentiment", callback_data="analysis_sentiment")],
    [InlineKeyboardButton("📅 Economische Kalender", callback_data="analysis_calendar")],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_menu")]
]

# Signals menu keyboard
SIGNALS_KEYBOARD = [
    [InlineKeyboardButton("➕ Nieuwe Paren Toevoegen", callback_data="signals_add")],
    [InlineKeyboardButton("⚙️ Beheer Voorkeuren", callback_data="signals_manage")],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_menu")]
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

# Forex keyboard
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
    [InlineKeyboardButton("⬅️ Terug", callback_data="back")]
]

# Crypto keyboard
CRYPTO_KEYBOARD = [
    [
        InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD"),
        InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD"),
        InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back")]
]

# Indices keyboard
INDICES_KEYBOARD = [
    [
        InlineKeyboardButton("US30", callback_data="instrument_US30"),
        InlineKeyboardButton("US500", callback_data="instrument_US500"),
        InlineKeyboardButton("US100", callback_data="instrument_US100")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back")]
]

# Commodities keyboard
COMMODITIES_KEYBOARD = [
    [
        InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD"),
        InlineKeyboardButton("WTIUSD", callback_data="instrument_WTIUSD")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back")]
]

# Style keyboard
STYLE_KEYBOARD = [
    [InlineKeyboardButton("⚡ Test (1m)", callback_data="style_test")],
    [InlineKeyboardButton("🏃 Scalp (15m)", callback_data="style_scalp")],
    [InlineKeyboardButton("📊 Intraday (1h)", callback_data="style_intraday")],
    [InlineKeyboardButton("🌊 Swing (4h)", callback_data="style_swing")],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_instrument")]
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
                        CallbackQueryHandler(self.back_to_menu_callback, pattern="^back_menu$"),
                    ],
                    CHOOSE_SIGNALS: [
                        CallbackQueryHandler(self.signals_add_callback, pattern="^signals_add$"),
                        CallbackQueryHandler(self.signals_manage_callback, pattern="^signals_manage$"),
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
            
            logger.info("Telegram service initialized")
            
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            raise

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation."""
        try:
            # Stuur welkomstbericht met hoofdmenu
            await update.message.reply_text(
                text=WELCOME_MESSAGE,
                reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                parse_mode=ParseMode.HTML
            )
            return MENU
            
        except Exception as e:
            logger.error(f"Error in start command: {str(e)}")
            await update.message.reply_text(
                "Sorry, er is iets misgegaan. Probeer het later opnieuw."
            )
            return ConversationHandler.END

    async def menu_analyse_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle menu_analyse callback"""
        query = update.callback_query
        await query.answer()
        
        # Toon het analyse menu
        await query.edit_message_text(
            text="Selecteer je analyse type:",
            reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
        )
        
        return CHOOSE_ANALYSIS

    async def menu_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle menu_signals callback"""
        query = update.callback_query
        await query.answer()
        
        # Toon het signals menu
        await query.edit_message_text(
            text="Wat wil je doen met trading signalen?",
            reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
        )
        
        return CHOOSE_SIGNALS

    # Voeg hier de rest van de callback handlers toe...

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Toon help informatie"""
        try:
            await update.message.reply_text(
                HELP_MESSAGE,
                parse_mode=ParseMode.HTML
            )
            return MENU
        except Exception as e:
            logger.error(f"Error in help_command: {str(e)}")
            await update.message.reply_text(
                "Er is een fout opgetreden bij het tonen van de help informatie. Probeer het later opnieuw."
            )
            return MENU
