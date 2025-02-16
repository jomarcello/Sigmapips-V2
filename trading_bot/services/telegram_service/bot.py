import os
import ssl
import asyncio
import logging
import aiohttp
import redis
import json
from typing import Dict, Any
import base64
import time

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes
)
from telegram.constants import ParseMode

from trading_bot.services.database.db import Database
from ..chart_service.chart import ChartService
from openai import AsyncOpenAI
from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
from trading_bot.services.calendar_service.calendar import EconomicCalendarService

logger = logging.getLogger(__name__)

# States
CHOOSE_ANALYSIS = 0  # Eerste state - kies analyse type
CHOOSE_MARKET = 1    # Tweede state - kies market
CHOOSE_INSTRUMENT = 2  # Derde state - kies instrument
CHOOSE_STYLE = 3     # Vierde state - kies trading stijl
SHOW_RESULT = 4      # Laatste state - toon resultaat

# Messages
WELCOME_MESSAGE = """
🤖 Welcome to SigmaPips Trading Bot!

I will help you set up your trading preferences.
Please answer a few questions to get started.
"""

MENU_MESSAGE = """
Welcome to SigmaPips Trading Bot! 📊

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

# Back button
BACK_BUTTON = InlineKeyboardButton("⬅️ Back", callback_data="back")

# Delete button
DELETE_BUTTON = InlineKeyboardButton("🗑️ Delete", callback_data="delete_prefs")

# Keyboard layouts met meerdere instrumenten per rij
FOREX_KEYBOARD = [
    # EUR pairs
    [
        InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD"),
        InlineKeyboardButton("EURGBP", callback_data="instrument_EURGBP"),
        InlineKeyboardButton("EURCHF", callback_data="instrument_EURCHF")
    ],
    [
        InlineKeyboardButton("EURJPY", callback_data="instrument_EURJPY"),
        InlineKeyboardButton("EURCAD", callback_data="instrument_EURCAD"),
        InlineKeyboardButton("EURAUD", callback_data="instrument_EURAUD")
    ],
    # GBP pairs
    [
        InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD"),
        InlineKeyboardButton("GBPJPY", callback_data="instrument_GBPJPY"),
        InlineKeyboardButton("GBPCHF", callback_data="instrument_GBPCHF")
    ],
    # USD pairs
    [
        InlineKeyboardButton("USDJPY", callback_data="instrument_USDJPY"),
        InlineKeyboardButton("USDCHF", callback_data="instrument_USDCHF"),
        InlineKeyboardButton("USDCAD", callback_data="instrument_USDCAD")
    ],
    # Cross rates
    [
        InlineKeyboardButton("AUDUSD", callback_data="instrument_AUDUSD"),
        InlineKeyboardButton("NZDUSD", callback_data="instrument_NZDUSD"),
        InlineKeyboardButton("AUDNZD", callback_data="instrument_AUDNZD")
    ],
    [BACK_BUTTON]
]

INDICES_KEYBOARD = [
    [
        InlineKeyboardButton("US500", callback_data="instrument_US500"),
        InlineKeyboardButton("US100", callback_data="instrument_US100"),
        InlineKeyboardButton("US30", callback_data="instrument_US30")
    ],
    [
        InlineKeyboardButton("DE40", callback_data="instrument_DE40"),
        InlineKeyboardButton("UK100", callback_data="instrument_UK100"),
        InlineKeyboardButton("EU50", callback_data="instrument_EU50")
    ],
    [
        InlineKeyboardButton("JP225", callback_data="instrument_JP225"),
        InlineKeyboardButton("AU200", callback_data="instrument_AU200"),
        InlineKeyboardButton("HK50", callback_data="instrument_HK50")
    ],
    [BACK_BUTTON]
]

COMMODITIES_KEYBOARD = [
    [InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD")],
    [InlineKeyboardButton("XTIUSD", callback_data="instrument_XTIUSD")],
    [BACK_BUTTON]
]

CRYPTO_KEYBOARD = [
    [
        InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD"),
        InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD"),
        InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD")
    ],
    [
        InlineKeyboardButton("SOLUSD", callback_data="instrument_SOLUSD"),
        InlineKeyboardButton("BNBUSD", callback_data="instrument_BNBUSD"),
        InlineKeyboardButton("ADAUSD", callback_data="instrument_ADAUSD")
    ],
    [
        InlineKeyboardButton("DOGUSD", callback_data="instrument_DOGUSD"),
        InlineKeyboardButton("DOTUSD", callback_data="instrument_DOTUSD"),
        InlineKeyboardButton("LTCUSD", callback_data="instrument_LTCUSD")
    ],
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
    [InlineKeyboardButton("Add More", callback_data="add_more")],
    [InlineKeyboardButton("Manage Preferences", callback_data="manage_prefs")]
]

# Market keyboard
MARKET_KEYBOARD = [
    [InlineKeyboardButton("Forex", callback_data="market_forex")],
    [InlineKeyboardButton("Indices", callback_data="market_indices")],
    [InlineKeyboardButton("Commodities", callback_data="market_commodities")],
    [InlineKeyboardButton("Crypto", callback_data="market_crypto")]
]

# Analysis Type Keyboard
ANALYSIS_KEYBOARD = [
    [InlineKeyboardButton("📊 Technical Analysis", callback_data="analysis_technical")],
    [InlineKeyboardButton("🤖 Sentiment Analysis", callback_data="analysis_sentiment")],
    [InlineKeyboardButton("📅 Economic Calendar", callback_data="analysis_calendar")],
    [InlineKeyboardButton("🎯 Trading Signals", callback_data="analysis_signals")]
]

# Trading Style Keyboard
STYLE_KEYBOARD = [
    [InlineKeyboardButton("⚡ Scalp", callback_data="style_scalp")],
    [InlineKeyboardButton("⏳ Intraday", callback_data="style_intraday")],
    [InlineKeyboardButton("🏆 Swing", callback_data="style_swing")],
    [BACK_BUTTON]
]

# Timeframe mapping based on style
STYLE_TIMEFRAME_MAP = {
    'scalp': ['1m', '5m', '15m'],
    'intraday': ['15m', '1h', '4h'],
    'swing': ['4h', '1d', '1w']
}

class TelegramService:
    def __init__(self, db: Database):
        """Initialize telegram service"""
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError("Missing TELEGRAM_BOT_TOKEN")
            
        self.db = db
        self.chart = ChartService()
        
        # Redis setup met Railway credentials
        redis_url = os.getenv("REDIS_URL", "redis://default:kcXeNDIt~!Pg6onj9B4t9IcudGehM1Ed@autorack.proxy.rlwy.net:42803")
        try:
            self.redis = redis.from_url(
                redis_url,
                decode_responses=True,
                encoding='utf-8'
            )
            # Test Redis connectie
            self.redis.ping()
            logger.info("Successfully connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")
            raise
        
        # SSL setup zonder verificatie voor ontwikkeling
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Gebruik Application builder voor bot setup
        self.app = Application.builder().token(self.token).build()
        self.bot = self.app.bot
        
        # Conversation handler setup
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("start", self._start_command),
                CommandHandler("manage", self._manage_command),
                CommandHandler("menu", self._menu_command)
            ],
            states={
                CHOOSE_ANALYSIS: [
                    CallbackQueryHandler(self._analysis_choice, pattern="^analysis_")
                ],
                CHOOSE_MARKET: [
                    CallbackQueryHandler(self._market_choice, pattern="^market_|back$")
                ],
                CHOOSE_INSTRUMENT: [
                    CallbackQueryHandler(self._instrument_choice, pattern="^instrument_|back$")
                ],
                CHOOSE_STYLE: [
                    CallbackQueryHandler(self._style_choice, pattern="^style_")
                ],
                SHOW_RESULT: [
                    CallbackQueryHandler(self._show_result, pattern="^result_")
                ]
            },
            fallbacks=[
                CommandHandler("start", self._start_command),
                CommandHandler("manage", self._manage_command),
                CommandHandler("menu", self._menu_command)
            ]
        )
        
        # Add handlers
        self.app.add_handler(conv_handler)
        
        # Voeg losse command handlers toe
        self.app.add_handler(CommandHandler("start", self._start_command))
        self.app.add_handler(CommandHandler("manage", self._manage_command))
        self.app.add_handler(CommandHandler("menu", self._menu_command))
        self.app.add_handler(CommandHandler("help", self._help_command))
        
        # Voeg button click handler toe
        self.app.add_handler(CallbackQueryHandler(self._button_click, pattern="^(chart|back_to_signal|sentiment|calendar)_"))
        
        self.message_cache = {}  # Dict om originele berichten op te slaan
        
        # OpenAI setup
        self.openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Sentiment service setup
        self.sentiment = MarketSentimentService()
        
        # Calendar service setup
        self.calendar = EconomicCalendarService()
        
        logger.info("Telegram service initialized")
            
    async def initialize(self):
        """Async initialization"""
        try:
            info = await self.bot.get_me()
            logger.info(f"Successfully connected to Telegram API. Bot info: {info}")
            
            # Set bot commands
            commands = [
                ("start", "Set up new trading pairs"),
                ("manage", "Manage your preferences"),
                ("menu", "Show main menu"),
                ("help", "Show help message")
            ]
            await self.bot.set_my_commands(commands)
            
            # Initialize the application
            await self.app.initialize()
            await self.app.start()
            
            # Log webhook info
            webhook_info = await self.bot.get_webhook_info()
            logger.info(f"Current webhook info: {webhook_info}")
            
        except Exception as e:
            logger.error(f"Failed to connect to Telegram API: {str(e)}")
            raise
            
    async def format_signal_with_ai(self, signal: Dict[str, Any]) -> str:
        """Format signal with AI"""
        try:
            prompt = f"""Format this trading signal using EXACTLY this template:

🚨 NEW TRADING SIGNAL 🚨

Instrument: {signal['symbol']}
Action: {signal['action']} {'📈' if signal['action'] == 'BUY' else '📉'}

Entry Price: {signal['price']}
Take Profit 1: {signal['takeProfit1']} 🎯
Take Profit 2: {signal['takeProfit2']} 🎯
Take Profit 3: {signal['takeProfit3']} 🎯
Stop Loss: {signal['stopLoss']} 🔴

Timeframe: {signal['timeframe']}
Strategy: Test Strategy

---------------

Risk Management:
• Position size: 1-2% max
• Use proper stop loss
• Follow your trading plan

---------------

🤖 SigmaPips AI Verdict:
✅ Trade aligns with market analysis"""

            response = await self.openai.chat.completions.create(
                model="gpt-4",
                messages=[{
                    "role": "system",
                    "content": "You are a trading signal formatter. Format signals EXACTLY according to the template, maintaining all emojis and sections."
                }, {
                    "role": "user",
                    "content": prompt
                }],
                temperature=0  # Exact output
            )

            formatted_signal = response.choices[0].message.content
            logger.info("Signal successfully formatted with AI")
            return formatted_signal

        except Exception as e:
            logger.error(f"Error formatting signal with AI: {str(e)}")
            # Fallback naar basic formatting
            return self._format_signal_message(signal)

    async def send_signal(self, chat_id: str, signal: Dict[str, Any]):
        """Send AI-formatted signal message"""
        try:
            # Format met AI
            message = await self.format_signal_with_ai(signal)
            
            keyboard = [
                [
                    InlineKeyboardButton("📊 Technical Analysis", callback_data=f"chart_{signal['symbol']}_{signal['timeframe']}"),
                    InlineKeyboardButton("🤖 Market Sentiment", callback_data=f"sentiment_{signal['symbol']}")
                ],
                [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"calendar_{signal['symbol']}")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            sent_message = await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            
            # Cache voor back button
            message_key = f"signal:{sent_message.message_id}"
            cache_data = {
                'text': message,
                'keyboard': json.dumps([[{"text": btn.text, "callback_data": btn.callback_data} for btn in row] for row in keyboard]),
                'parse_mode': 'HTML'
            }
            
            self.redis.hmset(message_key, cache_data)
            self.redis.expire(message_key, 3600)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to send signal to {chat_id}: {str(e)}")
            return False

    def _format_signal_message(self, signal: Dict[str, Any], sentiment: str = None, events: list = None) -> str:
        """Basic signal formatting fallback"""
        message = f"""🚨 <b>Trading Signal Alert</b>

📊 <b>Signal Details</b>
• Symbol: {signal['symbol']}
• Action: {signal['action']}
• Entry Price: {signal['price']}

🎯 <b>Take Profit Targets</b>
• TP1: {signal['takeProfit1']}
• TP2: {signal['takeProfit2']}
• TP3: {signal['takeProfit3']}

⚠️ <b>Risk Management</b>
• Stop Loss: {signal['stopLoss']}
• Timeframe: {signal['timeframe']}
"""

        if sentiment:
            message += f"\n📈 <b>Market Sentiment</b>\n{sentiment}"
            
        if events and len(events) > 0:
            message += "\n\n📅 <b>Economic Events</b>"
            for event in events[:3]:
                message += f"\n• {event}"
            
        return message

    async def _start_command(self, update: Update, context):
        """Handle start command"""
        try:
            # Start met analyse type keuze
            reply_markup = InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            await update.message.reply_text(
                "Welcome! What would you like to analyze?",
                reply_markup=reply_markup
            )
            logger.info(f"Start command handled for user {update.effective_user.id}")
            return CHOOSE_ANALYSIS
        except Exception as e:
            logger.error(f"Error handling start command: {str(e)}")

    async def _market_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle market selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back":
            # Terug naar analyse type keuze
            reply_markup = InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            await query.edit_message_text(
                text="Welcome! What would you like to analyze?",
                reply_markup=reply_markup
            )
            return CHOOSE_ANALYSIS
        
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
            text=f"Please select an instrument for {context.user_data['analysis_type'].replace('_', ' ').title()}:",
            reply_markup=reply_markup
        )
        return CHOOSE_INSTRUMENT

    async def _instrument_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle instrument selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back":
            reply_markup = InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            await query.edit_message_text(
                text="Welcome! What would you like to do?",
                reply_markup=reply_markup
            )
            return CHOOSE_ANALYSIS
        
        # Store the chosen instrument
        context.user_data['instrument'] = query.data.replace('instrument_', '')
        
        if context.user_data['analysis_type'] == 'signals':
            # Alleen voor signals naar style selectie
            reply_markup = InlineKeyboardMarkup(STYLE_KEYBOARD)
            await query.edit_message_text(
                text="Please select your trading style:",
                reply_markup=reply_markup
            )
            return CHOOSE_STYLE
        else:
            # Voor andere analyses direct resultaat tonen
            await self._show_analysis(query, context)
            return SHOW_RESULT

    async def _style_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle style selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back":
            # Ga terug naar instrument keuze gebaseerd op market
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
        
        # Store the chosen style
        context.user_data['style'] = query.data.replace('style_', '')
        
        # Get corresponding timeframes
        timeframes = STYLE_TIMEFRAME_MAP.get(context.user_data['style'], ['1m', '15m', '1h', '4h'])
        
        reply_markup = InlineKeyboardMarkup(TIMEFRAME_KEYBOARD)
        await query.edit_message_text(
            text="Please select a timeframe:",
            reply_markup=reply_markup
        )
        return SHOW_RESULT

    async def _show_result(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle result selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back":
            # Ga terug naar style keuze gebaseerd op market
            keyboard_map = {
                'forex': FOREX_KEYBOARD,
                'indices': INDICES_KEYBOARD,
                'commodities': COMMODITIES_KEYBOARD,
                'crypto': CRYPTO_KEYBOARD
            }
            
            reply_markup = InlineKeyboardMarkup(keyboard_map[context.user_data['market']])
            await query.edit_message_text(
                text="Please select a style:",
                reply_markup=reply_markup
            )
            return CHOOSE_STYLE
        
        # Store the chosen timeframe
        context.user_data['timeframe'] = query.data.replace('timeframe_', '')
        
        try:
            user_id = update.effective_user.id
            new_preferences = {
                'user_id': user_id,
                'market': context.user_data['market'],
                'instrument': context.user_data['instrument'],
                'style': context.user_data['style'],
                'timeframe': context.user_data['timeframe']
            }
            
            # Check voor dubbele combinaties
            existing = self.db.supabase.table('subscriber_preferences').select('*').eq('user_id', user_id).execute()
            
            for pref in existing.data:
                if (pref['market'] == new_preferences['market'] and 
                    pref['instrument'] == new_preferences['instrument'] and 
                    pref['style'] == new_preferences['style'] and 
                    pref['timeframe'] == new_preferences['timeframe']):
                    
                    keyboard = [
                        [InlineKeyboardButton("Try Again", callback_data="add_more")],
                        [InlineKeyboardButton("Manage Preferences", callback_data="manage_prefs")]
                    ]
                    
                    await query.edit_message_text(
                        text="You already have this combination saved!\n\n"
                             f"Market: {new_preferences['market']}\n"
                             f"Instrument: {new_preferences['instrument']}\n"
                             f"Style: {new_preferences['style']}\n"
                             f"Timeframe: {new_preferences['timeframe']}",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return SHOW_RESULT
            
            # Als er geen dubbele combinatie is, ga door met opslaan
            response = self.db.supabase.table('subscriber_preferences').insert(new_preferences).execute()
            logger.info(f"Added new preferences: {new_preferences}")
            
            logger.info(f"Database response: {response}")
            
            reply_markup = InlineKeyboardMarkup(AFTER_SETUP_KEYBOARD)
            await query.edit_message_text(
                text=f"Preferences saved!\n\n"
                     f"Market: {context.user_data['market']}\n"
                     f"Instrument: {context.user_data['instrument']}\n"
                     f"Style: {context.user_data['style']}\n"
                     f"Timeframe: {context.user_data['timeframe']}",
                reply_markup=reply_markup
            )
            return SHOW_RESULT
        
        except Exception as e:
            logger.error(f"Error saving preferences: {str(e)}")
            await query.edit_message_text(
                text="Error saving preferences. Please try again."
            )
            return ConversationHandler.END

    async def _manage_command(self, update: Update, context):
        """Handle manage command"""
        try:
            user_id = update.effective_user.id
            response = self.db.supabase.table('subscriber_preferences').select('*').eq('user_id', user_id).execute()
            
            if not response.data:
                await update.message.reply_text(
                    text="You don't have any saved preferences yet.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Add Preferences", callback_data="add_more")]])
                )
                return SHOW_RESULT
            
            message = "Your current preferences:\n\n"
            for i, pref in enumerate(response.data, 1):
                message += f"{i}. {pref['market']} - {pref['instrument']} - {pref['style']} - {pref['timeframe']}\n"
            
            keyboard = [
                [InlineKeyboardButton("Add More", callback_data="add_more")],
                [DELETE_BUTTON]
            ]
            
            await update.message.reply_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SHOW_RESULT
            
        except Exception as e:
            logger.error(f"Error handling manage command: {str(e)}")
            await update.message.reply_text(
                "Error loading preferences. Please try again."
            )
            return ConversationHandler.END

    async def _menu_command(self, update: Update, context):
        """Handle menu command"""
        try:
            keyboard = [
                [InlineKeyboardButton("➕ Add New Pairs", callback_data="start")],
                [InlineKeyboardButton("⚙️ Manage Preferences", callback_data="manage")]
            ]
            await update.message.reply_text(
                MENU_MESSAGE,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SHOW_RESULT
        except Exception as e:
            logger.error(f"Error handling menu command: {str(e)}")

    async def _manage_preferences(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle preference management"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "add_more" or query.data == "start":
            reply_markup = InlineKeyboardMarkup(FOREX_KEYBOARD)
            await query.edit_message_text(
                text=WELCOME_MESSAGE,
                reply_markup=reply_markup
            )
            return CHOOSE_MARKET
        
        elif query.data == "manage_prefs" or query.data == "manage":
            user_id = query.from_user.id
            response = self.db.supabase.table('subscriber_preferences').select('*').eq('user_id', user_id).execute()
            
            if not response.data:
                await query.edit_message_text(
                    text="You don't have any saved preferences yet.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Add Preferences", callback_data="add_more")]])
                )
                return SHOW_RESULT
            
            message = "Your current preferences:\n\n"
            for i, pref in enumerate(response.data, 1):
                message += f"{i}. {pref['market']} - {pref['instrument']} - {pref['style']} - {pref['timeframe']}\n"
            
            keyboard = [
                [InlineKeyboardButton("Add More", callback_data="add_more")],
                [DELETE_BUTTON]
            ]
            
            await query.edit_message_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SHOW_RESULT
        
        elif query.data == "delete_prefs":
            user_id = query.from_user.id
            response = self.db.supabase.table('subscriber_preferences').select('*').eq('user_id', user_id).execute()
            
            message = "Select a preference to delete:\n\n"
            keyboard = []
            
            for i, pref in enumerate(response.data, 1):
                message += f"{i}. {pref['market']} - {pref['instrument']} - {pref['style']} - {pref['timeframe']}\n"
                keyboard.append([InlineKeyboardButton(f"Delete {i}", callback_data=f"delete_{pref['id']}")])
            
            keyboard.append([InlineKeyboardButton("Back", callback_data="manage_prefs")])
            
            await query.edit_message_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SHOW_RESULT
        
        elif query.data.startswith("delete_"):
            pref_id = int(query.data.replace("delete_", ""))
            try:
                self.db.supabase.table('subscriber_preferences').delete().eq('id', pref_id).execute()
                await query.answer("Preference deleted successfully!")
                
                # Show updated preferences
                user_id = query.from_user.id
                response = self.db.supabase.table('subscriber_preferences').select('*').eq('user_id', user_id).execute()
                
                if not response.data:
                    await query.edit_message_text(
                        text="You don't have any saved preferences yet.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Add Preferences", callback_data="add_more")]])
                    )
                else:
                    message = "Your current preferences:\n\n"
                    for i, pref in enumerate(response.data, 1):
                        message += f"{i}. {pref['market']} - {pref['instrument']} - {pref['style']} - {pref['timeframe']}\n"
                    
                    keyboard = [
                        [InlineKeyboardButton("Add More", callback_data="add_more")],
                        [DELETE_BUTTON]
                    ]
                    
                    await query.edit_message_text(
                        text=message,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
            
            except Exception as e:
                logger.error(f"Error deleting preference: {str(e)}")
                await query.answer("Error deleting preference")
            
            return SHOW_RESULT
        
        return SHOW_RESULT

    async def set_webhook(self, webhook_url: str):
        """Set webhook for telegram bot"""
        try:
            # Verwijder oude webhook
            await self.bot.delete_webhook()
            
            # Controleer huidige webhook
            webhook_info = await self.bot.get_webhook_info()
            logger.info(f"Current webhook info: {webhook_info}")
            
            # Zet nieuwe webhook
            webhook_url = webhook_url.strip(';').strip()  # Verwijder trailing karakters
            await self.bot.set_webhook(
                url=webhook_url,
                allowed_updates=['message', 'callback_query']
            )
            
            # Verifieer nieuwe webhook
            webhook_info = await self.bot.get_webhook_info()
            logger.info(f"Webhook verification: {webhook_info}")
            
        except Exception as e:
            logger.error(f"Failed to set webhook: {str(e)}")
            raise

    async def _help_command(self, update: Update, context):
        """Handle help command"""
        try:
            await update.message.reply_text(HELP_MESSAGE)
        except Exception as e:
            logger.error(f"Error handling help command: {str(e)}")

    async def _button_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        try:
            data = query.data
            message_id = query.message.message_id
            logger.info(f"Button clicked: {data}, message_id: {message_id}")
            
            # Haal de signal key op uit de message cache
            signal_key = f"signal:{message_id}"
            signal_cache = self.redis.hgetall(signal_key)
            
            if not signal_cache:
                logger.error(f"No cached signal data found for message_id: {message_id}")
                return
            
            # Haal de preloaded data op
            preload_key = signal_cache.get('preload_key')
            if not preload_key:
                logger.error("No preload key found in signal cache")
                return
            
            preloaded_data = self.redis.hgetall(preload_key)
            if not preloaded_data:
                logger.error(f"No preloaded data found for key: {preload_key}")
                return
            
            logger.info(f"Found preloaded data with keys: {list(preloaded_data.keys())}")
            
            if data.startswith("chart_"):
                try:
                    # Gebruik gecachede chart data
                    if preloaded_data.get('chart_image'):
                        chart_image = base64.b64decode(preloaded_data['chart_image'].encode('utf-8'))
                        
                        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data=f"back_to_signal_{message_id}")]]
                        await query.message.edit_media(
                            media=InputMediaPhoto(
                                media=chart_image,
                                caption=f"📊 Technical Analysis"
                            ),
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        logger.info("Displayed cached chart")
                    else:
                        logger.error("No chart data in cache")
                        
                except Exception as e:
                    logger.error(f"Error displaying chart: {str(e)}")
                    logger.exception(e)
                
            elif data.startswith("sentiment_"):
                try:
                    # Gebruik gecachede sentiment data
                    if preloaded_data.get('sentiment'):
                        sentiment = preloaded_data['sentiment']
                        
                        # Sla eerst de huidige message_id op
                        old_message_id = query.message.message_id
                        
                        # Verwijder het oude bericht
                        await query.message.delete()
                        
                        # Stuur een nieuw bericht
                        new_message = await self.bot.send_message(
                            chat_id=query.message.chat_id,
                            text=sentiment,
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("⬅️ Back", callback_data=f"back_to_signal_{old_message_id}")
                            ]])
                        )
                        
                        # Kopieer de cache data
                        new_signal_key = f"signal:{new_message.message_id}"
                        cache_data = {
                            'text': sentiment,
                            'parse_mode': 'HTML',
                            'preload_key': preload_key,
                            'symbol': preloaded_data['symbol'],
                            'timeframe': preloaded_data['timeframe']
                        }
                        
                        self.redis.hmset(new_signal_key, cache_data)
                        self.redis.expire(new_signal_key, 3600)
                        
                        logger.info("Displayed cached sentiment")
                    else:
                        logger.error("No sentiment data in cache")
                        
                except Exception as e:
                    logger.error(f"Error displaying sentiment: {str(e)}")
                    logger.exception(e)
                
            elif data.startswith("calendar_"):
                try:
                    # Gebruik gecachede calendar data
                    if preloaded_data.get('calendar'):
                        calendar = preloaded_data['calendar']
                        
                        # Sla eerst de huidige message_id op
                        old_message_id = query.message.message_id
                        
                        # Verwijder het oude bericht
                        await query.message.delete()
                        
                        # Stuur een nieuw bericht
                        new_message = await self.bot.send_message(
                            chat_id=query.message.chat_id,
                            text=calendar,
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("⬅️ Back", callback_data=f"back_to_signal_{old_message_id}")
                            ]])
                        )
                        
                        # Kopieer de cache data
                        new_signal_key = f"signal:{new_message.message_id}"
                        cache_data = {
                            'text': calendar,
                            'parse_mode': 'HTML',
                            'preload_key': preload_key,
                            'symbol': preloaded_data['symbol'],
                            'timeframe': preloaded_data['timeframe']
                        }
                        
                        self.redis.hmset(new_signal_key, cache_data)
                        self.redis.expire(new_signal_key, 3600)
                        
                        logger.info("Displayed cached calendar")
                    else:
                        logger.error("No calendar data in cache")
                        
                except Exception as e:
                    logger.error(f"Error displaying calendar: {str(e)}")
                    logger.exception(e)
                
            elif data.startswith("back_to_signal_"):
                try:
                    # Gebruik preloaded data voor het originele bericht
                    formatted_signal = preloaded_data['formatted_signal']
                    
                    keyboard = [
                        [
                            InlineKeyboardButton(
                                "📊 Technical Analysis", 
                                callback_data=f"chart_{preloaded_data['symbol']}_{preloaded_data['timeframe']}"
                            ),
                            InlineKeyboardButton(
                                "🤖 Market Sentiment", 
                                callback_data=f"sentiment_{preloaded_data['symbol']}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "📅 Economic Calendar", 
                                callback_data=f"calendar_{preloaded_data['symbol']}"
                            )
                        ]
                    ]
                    
                    # Check of het huidige bericht een foto is
                    is_photo = bool(query.message.photo)
                    
                    if is_photo:
                        # Als het een foto is, stuur een nieuw text bericht
                        await query.message.delete()
                        new_message = await self.bot.send_message(
                            chat_id=query.message.chat_id,
                            text=formatted_signal,
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        
                        # Kopieer de cache data naar het nieuwe message_id
                        new_signal_key = f"signal:{new_message.message_id}"
                        cache_data = {
                            'text': formatted_signal,
                            'parse_mode': 'HTML',
                            'preload_key': preload_key,
                            'symbol': preloaded_data['symbol'],
                            'timeframe': preloaded_data['timeframe']
                        }
                        
                        self.redis.hmset(new_signal_key, cache_data)
                        self.redis.expire(new_signal_key, 3600)
                        
                    else:
                        # Anders gebruik edit_text
                        await query.message.edit_text(
                            text=formatted_signal,
                            parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    logger.info("Restored original signal")
                    
                except Exception as e:
                    logger.error(f"Error restoring signal: {str(e)}")
                    logger.exception(e)
            
        except Exception as e:
            logger.error(f"Error handling button click: {str(e)}")
            logger.exception(e)

    async def broadcast_signal(self, signal: Dict[str, Any], message_key: str):
        """Broadcast signal to all matching subscribers using pre-loaded data"""
        try:
            # Get matching subscribers
            subscribers = await self.db.match_subscribers(signal)
            logger.info(f"Found {len(subscribers)} matching subscribers")
            
            # Get cached data
            logger.info(f"Retrieving cached data for key: {message_key}")
            cached_data = self.redis.hgetall(message_key)
            
            if not cached_data:
                logger.error(f"No cached data found for message_key: {message_key}")
                logger.info("Available Redis keys:", self.redis.keys("preload:*"))
                return
            
            logger.info(f"Found cached data with keys: {list(cached_data.keys())}")
            
            formatted_signal = cached_data['formatted_signal']
            logger.info("Successfully retrieved formatted signal from cache")
            
            # Create keyboard
            keyboard = [
                [
                    {"text": "📊 Technical Analysis", "callback_data": f"chart_{signal['symbol']}_{signal['timeframe']}"},
                    {"text": "🤖 Market Sentiment", "callback_data": f"sentiment_{signal['symbol']}"}
                ],
                [{"text": "📅 Economic Calendar", "callback_data": f"calendar_{signal['symbol']}"}]
            ]
            
            # Create InlineKeyboardMarkup from the keyboard dict
            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(**btn) for btn in row
                ] for row in keyboard
            ])
            
            # Send to each subscriber
            for subscriber in subscribers:
                try:
                    sent_message = await self.bot.send_message(
                        chat_id=subscriber['chat_id'],
                        text=formatted_signal,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
                    
                    # Cache voor back button
                    signal_key = f"signal:{sent_message.message_id}"
                    cache_data = {
                        'text': formatted_signal,
                        'parse_mode': 'HTML',
                        'preload_key': message_key,
                        'symbol': signal['symbol'],
                        'timeframe': signal['timeframe']
                    }
                    
                    self.redis.hmset(signal_key, cache_data)
                    self.redis.expire(signal_key, 3600)
                    
                except Exception as e:
                    logger.error(f"Failed to send signal to {subscriber['chat_id']}: {str(e)}")
                    continue
                
        except Exception as e:
            logger.error(f"Error broadcasting signal: {str(e)}")
            logger.exception(e)

    async def _analysis_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle analysis type selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back":
            reply_markup = InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            await query.edit_message_text(
                text="Welcome! What would you like to do?",
                reply_markup=reply_markup
            )
            return CHOOSE_ANALYSIS
        
        analysis_type = query.data.replace('analysis_', '')
        context.user_data['analysis_type'] = analysis_type
        
        if analysis_type == 'signals':
            # Alleen voor signals naar market selectie
            reply_markup = InlineKeyboardMarkup(MARKET_KEYBOARD)
            await query.edit_message_text(
                text="Please select a market for your signals:",
                reply_markup=reply_markup
            )
            return CHOOSE_MARKET
        else:
            # Voor andere analyses direct naar instrument selectie
            keyboard_map = {
                'technical': FOREX_KEYBOARD,
                'sentiment': FOREX_KEYBOARD,
                'calendar': FOREX_KEYBOARD
            }
            reply_markup = InlineKeyboardMarkup(keyboard_map[analysis_type])
            await query.edit_message_text(
                text=f"Please select an instrument for {analysis_type.replace('_', ' ').title()} Analysis:",
                reply_markup=reply_markup
            )
            return CHOOSE_INSTRUMENT

# ... rest van de code ...
