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
from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
from trading_bot.services.calendar_service.calendar import EconomicCalendarService

logger = logging.getLogger(__name__)

# States
CHOOSE_MENU = 0      # Eerste state - hoofdmenu
CHOOSE_ANALYSIS = 1  # Analyse submenu
CHOOSE_SIGNALS = 2   # Signals submenu
CHOOSE_MARKET = 3    # Market keuze
CHOOSE_INSTRUMENT = 4
CHOOSE_STYLE = 5     # Vierde state - kies trading stijl (alleen voor signals)
SHOW_RESULT = 6      # Laatste state - toon resultaat

# Messages
WELCOME_MESSAGE = """
🚀 <b>Welcome to SigmaPips Trading Bot!</b> 🚀

I'm your AI-powered trading assistant, designed to help you make better trading decisions.

📊 <b>My Services:</b>
• <b>Technical Analysis</b> - Get real-time chart analysis and key levels

• <b>Market Sentiment</b> - Understand market mood and trends

• <b>Economic Calendar</b> - Stay informed about market-moving events

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

# Back button
BACK_BUTTON = InlineKeyboardButton("Back", callback_data="back")

# Delete button
DELETE_BUTTON = InlineKeyboardButton("Delete", callback_data="delete_prefs")

# Start menu keyboard
START_KEYBOARD = [
    [InlineKeyboardButton("🔍 Analyse Market", callback_data="menu_analyse")],
    [InlineKeyboardButton("📊 Trading Signals", callback_data="menu_signals")]
]

# Analysis menu keyboard
ANALYSIS_KEYBOARD = [
    [InlineKeyboardButton("📈 Technical Analysis", callback_data="analysis_technical")],
    [InlineKeyboardButton("🧠 Market Sentiment", callback_data="analysis_sentiment")],
    [InlineKeyboardButton("📅 Economic Calendar", callback_data="analysis_calendar")],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
]

# Market keyboard (geen emoji's)
MARKET_KEYBOARD = [
    [InlineKeyboardButton("Forex", callback_data="market_forex")],
    [InlineKeyboardButton("Crypto", callback_data="market_crypto")],
    [InlineKeyboardButton("Commodities", callback_data="market_commodities")],
    [InlineKeyboardButton("Indices", callback_data="market_indices")],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
]

# Signals menu keyboard
SIGNALS_KEYBOARD = [
    [InlineKeyboardButton("➕ Add New Pairs", callback_data="signals_add")],
    [InlineKeyboardButton("⚙️ Manage Preferences", callback_data="signals_manage")],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
]

# Style keyboard
STYLE_KEYBOARD = [
    [InlineKeyboardButton("⚡ Test (1m)", callback_data="style_test")],
    [InlineKeyboardButton("🏃 Scalp (15m)", callback_data="style_scalp")],
    [InlineKeyboardButton("📊 Intraday (1h)", callback_data="style_intraday")],
    [InlineKeyboardButton("🌊 Swing (4h)", callback_data="style_swing")],
    [InlineKeyboardButton("⬅️ Back", callback_data="back")]
]

# After setup keyboard
AFTER_SETUP_KEYBOARD = [
    [InlineKeyboardButton("➕ Add More", callback_data="add_more")],
    [InlineKeyboardButton("⚙️ Manage Preferences", callback_data="manage_prefs")],
    [InlineKeyboardButton("🏠 Back to Start", callback_data="back_to_menu")]
]

# Forex keyboard (geen emoji's)
FOREX_KEYBOARD = [
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
    [
        InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD"),
        InlineKeyboardButton("GBPJPY", callback_data="instrument_GBPJPY"),
        InlineKeyboardButton("GBPCHF", callback_data="instrument_GBPCHF")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back")]
]

# Crypto keyboard
CRYPTO_KEYBOARD = [
    [
        InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD"),
        InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD"),
        InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back")]
]

# Indices keyboard
INDICES_KEYBOARD = [
    [
        InlineKeyboardButton("US30", callback_data="instrument_US30"),
        InlineKeyboardButton("US500", callback_data="instrument_US500"),
        InlineKeyboardButton("US100", callback_data="instrument_US100")
    ],
    [
        InlineKeyboardButton("UK100", callback_data="instrument_UK100"),
        InlineKeyboardButton("DE40", callback_data="instrument_DE40"),
        InlineKeyboardButton("FR40", callback_data="instrument_FR40")
    ],
    [
        InlineKeyboardButton("JP225", callback_data="instrument_JP225"),
        InlineKeyboardButton("AU200", callback_data="instrument_AU200"),
        InlineKeyboardButton("HK50", callback_data="instrument_HK50")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back")]
]

# Commodities keyboard
COMMODITIES_KEYBOARD = [
    [
        InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD"),
        InlineKeyboardButton("XAGUSD", callback_data="instrument_XAGUSD"),
        InlineKeyboardButton("USOIL", callback_data="instrument_USOIL")
    ],
    [InlineKeyboardButton("⬅️ Back", callback_data="back")]
]

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
            self.redis = db.redis
            
            # Setup services
            self.chart = ChartService()
            self.sentiment = MarketSentimentService()
            self.calendar = EconomicCalendarService()
            
            # Setup conversation handler
            conv_handler = ConversationHandler(
                entry_points=[CommandHandler("start", self.start)],
                states={
                    CHOOSE_MENU: [
                        CallbackQueryHandler(self.menu_choice, pattern="^menu_")
                    ],
                    CHOOSE_ANALYSIS: [
                        CallbackQueryHandler(self.analysis_choice, pattern="^analysis_"),
                        CallbackQueryHandler(self.back_to_menu, pattern="^back_menu$")
                    ],
                    CHOOSE_SIGNALS: [
                        CallbackQueryHandler(self.signals_choice, pattern="^signals_"),
                        CallbackQueryHandler(self.back_to_menu, pattern="^back_menu$")
                    ],
                    CHOOSE_MARKET: [
                        CallbackQueryHandler(self.market_choice, pattern="^market_"),
                        CallbackQueryHandler(self.back_to_analysis, pattern="^back$")
                    ],
                    CHOOSE_INSTRUMENT: [
                        CallbackQueryHandler(self.instrument_choice, pattern="^instrument_"),
                        CallbackQueryHandler(self.back_to_market, pattern="^back$")
                    ],
                    CHOOSE_STYLE: [
                        CallbackQueryHandler(self.style_choice, pattern="^style_"),
                        CallbackQueryHandler(self.back_to_instrument, pattern="^back$")
                    ],
                    SHOW_RESULT: [
                        CallbackQueryHandler(self.add_more, pattern="^add_more$"),
                        CallbackQueryHandler(self.manage_preferences, pattern="^manage_prefs$"),
                        CallbackQueryHandler(self.back_to_menu, pattern="^back_menu$"),
                        CallbackQueryHandler(self.back_to_instruments, pattern="^back_to_instruments$")
                    ]
                },
                fallbacks=[CallbackQueryHandler(self.cancel, pattern="^cancel$")],
                per_message=True
            )
            
            # Add handlers
            self.application.add_handler(conv_handler)
            self.application.add_handler(CommandHandler("help", self.help))
            self.application.add_handler(CallbackQueryHandler(self._button_click))
            
            logger.info("Telegram service initialized")
            
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            raise

    async def initialize(self):
        """Async initialization"""
        try:
            info = await self.bot.get_me()
            logger.info(f"Successfully connected to Telegram API. Bot info: {info}")
            
            # Set bot commands - alleen /start en /help
            commands = [
                ("start", "Start the bot and see available options"),
                ("help", "Show help message")
            ]
            await self.bot.set_my_commands(commands)
            
            # Initialize the application
            await self.application.initialize()
            await self.application.start()
            
            # Log webhook info
            webhook_info = await self.bot.get_webhook_info()
            logger.info(f"Current webhook info: {webhook_info}")
            
        except Exception as e:
            logger.error(f"Failed to connect to Telegram API: {str(e)}")
            raise
            
    async def format_signal_with_ai(self, signal: Dict[str, Any]) -> str:
        """Format trading signal using DeepSeek AI"""
        try:
            prompt = self._create_signal_prompt(signal)
            
            payload = {
                "model": "deepseek-chat",
                "messages": [{
                    "role": "system",
                    "content": "Format trading signals in a clear and professional way."
                }, {
                    "role": "user",
                    "content": prompt
                }],
                "temperature": 0.5
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info("Successfully formatted signal with DeepSeek")
                        return data['choices'][0]['message']['content']
                    else:
                        logger.error(f"DeepSeek API error: {response.status}")
                        return self._format_basic_signal(signal)

        except Exception as e:
            logger.error(f"Error formatting signal with AI: {str(e)}")
            return self._format_basic_signal(signal)

    def _format_basic_signal(self, signal: Dict[str, Any]) -> str:
        """Basic signal formatting without AI"""
        return f"""🚨 NEW TRADING SIGNAL 🚨

Instrument: {signal['instrument']}
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

    async def send_signal(self, chat_id: str, signal: Dict[str, Any]):
        """Send AI-formatted signal message"""
        try:
            # Format met AI
            message = await self.format_signal_with_ai(signal)
            
            # Maak keyboard
            keyboard = [
                [
                    InlineKeyboardButton("📊 Technical Analysis", callback_data=f"chart_{signal['instrument']}_{signal['timeframe']}"),
                    InlineKeyboardButton("🤖 Market Sentiment", callback_data=f"sentiment_{signal['instrument']}")
                ],
                [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"calendar_{signal['instrument']}")]
            ]
            
            # Verstuur bericht
            sent_message = await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # Sla originele data op in Redis
            message_key = f"signal:{sent_message.message_id}"
            cache_data = {
                'text': message,
                'keyboard': json.dumps(keyboard, default=lambda x: x.__dict__),
                'parse_mode': 'HTML'
            }
            
            # Gebruik hmset voor Redis opslag
            self.redis.hmset(message_key, cache_data)
            self.redis.expire(message_key, 3600)  # 1 uur expiry
            
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

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation."""
        try:
            user = update.effective_user
            logger.info(f"Starting conversation with user {user.id}")
            
            # Reset user data
            if context:
                context.user_data.clear()
            
            # Stuur welkomstbericht met START_KEYBOARD
            await update.message.reply_text(
                text=WELCOME_MESSAGE,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
            )
            return CHOOSE_MENU
            
        except Exception as e:
            logger.error(f"Error in start command: {str(e)}")
            await update.message.reply_text(
                "Sorry, something went wrong. Please try again with /start"
            )
            return ConversationHandler.END

    async def menu_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle main menu selection"""
        try:
            query = update.callback_query
            await query.answer()
            
            choice = query.data.replace('menu_', '')
            
            if choice == 'analyse':
                await query.edit_message_text(
                    text="Select your analysis type:",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
            elif choice == 'signals':
                await query.edit_message_text(
                    text="What would you like to do with trading signals?",
                    reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                )
            
            return CHOOSE_MENU
            
        except Exception as e:
            logger.error(f"Error in menu choice: {str(e)}")
            await query.edit_message_text(
                text="Sorry, something went wrong. Please use /start to begin again.",
                reply_markup=None
            )
            return ConversationHandler.END

    async def signals_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle signals menu selection"""
        query = update.callback_query
        await query.answer()
        
        choice = query.data.replace('signals_', '')
        
        if choice == 'add':
            await query.edit_message_text(
                text="Please select your preferred market:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
            )
            return CHOOSE_MARKET
        elif choice == 'manage':
            # Haal voorkeuren op
            user_id = update.effective_user.id
            preferences = self.db.supabase.table('subscriber_preferences').select('*').eq('user_id', user_id).execute()
            
            if not preferences.data:
                await query.edit_message_text(
                    text="You don't have any saved preferences yet.\n\nUse 'Add New Pairs' to set up your first trading pair.",
                    reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                )
                return CHOOSE_SIGNALS
            
            # Format preferences text
            prefs_text = "Your current preferences:\n\n"
            for i, pref in enumerate(preferences.data, 1):
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
            return CHOOSE_SIGNALS

    async def market_choice(self, callback_query: CallbackQuery, analysis_type: str):
        """Handle market selection after analysis type"""
        try:
            # Sla analysis type op in reply markup data
            keyboard = MARKET_KEYBOARD.copy()
            for row in keyboard:
                for button in row:
                    button.callback_data = f"{button.callback_data}_{analysis_type}"
            
            await callback_query.edit_message_text(
                text="Please select your preferred market:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error in market choice: {str(e)}")

    async def handle_market_selection(self, callback_query: CallbackQuery, market: str):
        """Handle market selection and show instruments"""
        try:
            # Bepaal welke keyboard te tonen op basis van market
            keyboard_map = {
                'forex': FOREX_KEYBOARD,
                'crypto': CRYPTO_KEYBOARD,
                'commodities': COMMODITIES_KEYBOARD,
                'indices': INDICES_KEYBOARD
            }
            
            keyboard = keyboard_map.get(market, FOREX_KEYBOARD)
            
            # Voeg analysis type toe aan callback data
            analysis_type = callback_query.data.split('_')[-1]
            for row in keyboard:
                for button in row:
                    button.callback_data = f"{button.callback_data}_{analysis_type}"
            
            await callback_query.edit_message_text(
                text=f"Please select an instrument from {market.title()}:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error in handle market selection: {str(e)}")

    async def instrument_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle instrument selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back":
            # Terug naar market selectie
            reply_markup = InlineKeyboardMarkup(MARKET_KEYBOARD)
            await query.edit_message_text(
                text=f"Please select a market for {context.user_data['analysis_type'].replace('_', ' ').title()}:",
                reply_markup=reply_markup
            )
            return CHOOSE_MARKET
        
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

    async def style_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle style selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back":
            # Terug naar instrument keuze
            await query.edit_message_text(
                text=f"Please select an instrument:",
                reply_markup=InlineKeyboardMarkup(FOREX_KEYBOARD)
            )
            return CHOOSE_INSTRUMENT
        
        style = query.data.replace('style_', '')
        context.user_data['style'] = style
        context.user_data['timeframe'] = STYLE_TIMEFRAME_MAP[style]
        
        try:
            # Save preferences
            await self.db.save_preferences(
                user_id=update.effective_user.id,
                market=context.user_data['market'],
                instrument=context.user_data['instrument'],
                style=style
            )
            
            # Show success message with options
            await query.edit_message_text(
                text=f"✅ Successfully saved your preferences!\n\n"
                     f"Market: {context.user_data['market']}\n"
                     f"Instrument: {context.user_data['instrument']}\n"
                     f"Style: {style} ({STYLE_TIMEFRAME_MAP[style]})",
                reply_markup=InlineKeyboardMarkup(AFTER_SETUP_KEYBOARD)
            )
            logger.info(f"Saved preferences for user {update.effective_user.id}")
            return SHOW_RESULT
            
        except Exception as e:
            logger.error(f"Error saving preferences: {str(e)}")
            await query.edit_message_text(
                text="❌ Error saving preferences. Please try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Try Again", callback_data="back_to_market")]])
            )
            return CHOOSE_MARKET

    async def _show_result(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle result selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back":
            # Ga terug naar style keuze gebaseerd op market
            keyboard_map = {
                'forex': FOREX_KEYBOARD,
                'indices': FOREX_KEYBOARD,
                'commodities': FOREX_KEYBOARD,
                'crypto': FOREX_KEYBOARD
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

    async def add_more(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle add more button"""
        query = update.callback_query
        await query.answer()
        
        # Reset user_data voor nieuwe sessie
        context.user_data.clear()
        
        # Start nieuwe setup flow
        await query.edit_message_text(
            text="Welcome! What would you like to analyze?",
            reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
        )
        return CHOOSE_ANALYSIS

    async def manage_preferences(self, callback_query: CallbackQuery) -> None:
        """Show user preferences"""
        try:
            user_id = callback_query.from_user.id
            
            # Haal voorkeuren op uit database
            preferences = await self.db.get_user_preferences(user_id)
            
            if not preferences:
                await callback_query.edit_message_text(
                    text="You don't have any saved preferences yet.\n\nUse 'Add New Pairs' to set up your first trading pair.",
                    reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                )
                return
            
            # Format preferences message
            message = "Your current trading preferences:\n\n"
            for pref in preferences:
                message += f"• {pref['instrument']} ({pref['timeframe']})\n"
                message += f"  Style: {pref['style']}\n\n"
            
            # Add management options
            keyboard = [
                [InlineKeyboardButton("➕ Add More", callback_data="signals_add")],
                [InlineKeyboardButton("🗑 Delete Preferences", callback_data="delete_prefs")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_signals")]
            ]
            
            await callback_query.edit_message_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logger.error(f"Error managing preferences: {str(e)}")
            await callback_query.edit_message_text(
                text="Sorry, something went wrong while fetching your preferences.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="back_signals")
                ]])
            )

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

    async def help(self, update: Update, context):
        """Handle help command"""
        try:
            await update.message.reply_text(HELP_MESSAGE)
        except Exception as e:
            logger.error(f"Error handling help command: {str(e)}")

    async def _button_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button clicks"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Parse button data
            data = query.data
            
            if data == "back":
                # Bepaal waar we naartoe moeten gaan op basis van context
                if 'analysis_type' in context.user_data:
                    if context.user_data['analysis_type'] in ['technical', 'sentiment']:
                        # Terug naar instrument selectie
                        await query.edit_message_text(
                            text="Please select an instrument:",
                            reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
                        )
                        return CHOOSE_MARKET
                
                # Default: terug naar hoofdmenu
                await query.edit_message_text(
                    text="Welcome! Please select what you would like to do:",
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
                return CHOOSE_MENU
            
            elif data.startswith('chart_'):
                instrument = data.split('_')[1]
                await self.handle_chart_button(query, instrument)
            elif data.startswith('sentiment_'):
                instrument = data.split('_')[1]
                await self.show_sentiment_analysis(query, instrument)
            elif data.startswith('calendar_'):
                instrument = data.split('_')[1]
                await self.handle_calendar_button(query, instrument)
            
        except Exception as e:
            logger.error(f"Error handling button click: {str(e)}")
            # Stuur gebruiker terug naar hoofdmenu bij error
            await query.edit_message_text(
                text="Sorry, something went wrong. Please start over:",
                reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
            )
            return CHOOSE_MENU

    async def broadcast_signal(self, signal: Dict[str, Any]):
        """Broadcast signal to subscribers"""
        try:
            logger.info(f"Starting broadcast for signal: {signal}")
            
            # Eerst market data voorbereiden
            market_data = await self.prepare_market_data(signal['instrument'])
            
            # Get subscribers met timeframe filter
            subscribers = await self.db.get_subscribers(
                instrument=signal['instrument'],
                timeframe=signal.get('timeframe')
            )
            
            if not subscribers.data:
                logger.warning(f"No subscribers found for {signal['instrument']}")
                return
            
            # Format signal met vooraf geladen verdict
            message = f"""🚨 NEW TRADING SIGNAL 🚨

Instrument: {signal['instrument']}
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
{market_data['verdict']}"""

            # Send to each subscriber
            for subscriber in subscribers.data:
                try:
                    keyboard = [
                        [
                            InlineKeyboardButton("📊 Technical Analysis", callback_data=f"chart_{signal['instrument']}"),
                            InlineKeyboardButton("🤖 Market Sentiment", callback_data=f"sentiment_{signal['instrument']}")
                        ],
                        [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"calendar_{signal['instrument']}")]
                    ]
                    
                    await self.bot.send_message(
                        chat_id=subscriber['user_id'],
                        text=message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    logger.info(f"Signal sent to {subscriber['user_id']}")
                    
                except Exception as e:
                    logger.error(f"Failed to send signal to {subscriber['user_id']}: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error broadcasting signal: {str(e)}")

    async def analysis_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle analysis type selection"""
        query = update.callback_query
        await query.answer()
        
        analysis_type = query.data.replace('analysis_', '')
        context.user_data['analysis_type'] = analysis_type
        
        if analysis_type == 'calendar':
            # Direct calendar tonen zonder market/instrument selectie
            await self._show_analysis(query, context)
            return SHOW_RESULT
        else:
            # Voor technical, sentiment en signals naar market selectie
            await query.edit_message_text(
                text="Please select your preferred market:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
            )
            return CHOOSE_MARKET

    async def _show_analysis(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
        """Toon analyse gebaseerd op type"""
        analysis_type = context.user_data['analysis_type']
        instrument = context.user_data['instrument']
        
        try:
            if analysis_type == 'technical':
                # Toon loading message
                loading_message = await query.edit_message_text(
                    text=f"⏳ Generating technical analysis for {instrument}...\n\n"
                         f"Please wait while I prepare your chart 📊"
                )
                
                # Genereer chart
                chart_image = await self.chart.generate_chart(instrument, "1h")
                
                if chart_image:
                    # Maak keyboard met back button
                    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_instruments")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # Verwijder loading message
                    await loading_message.delete()
                    
                    # Stuur nieuwe message met chart
                    new_message = await query.message.reply_photo(
                        photo=chart_image,
                        caption=f"📊 Technical Analysis for {instrument}",
                        reply_markup=reply_markup
                    )
                    
                    # Sla message ID op voor later gebruik
                    context.user_data['last_chart_message'] = new_message.message_id
                    
                else:
                    await loading_message.edit_text(
                        "Sorry, couldn't generate the chart. Please try again.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_instruments")]])
                    )

            elif analysis_type == 'sentiment':
                # Sentiment Analysis
                loading_message = await query.edit_message_text(
                    text=f"⏳ Analyzing market sentiment for {instrument}...\n\n"
                         f"Please wait while I gather the data 📊"
                )
                
                sentiment_data = await self.sentiment.get_market_sentiment(instrument)
                
                keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_instruments")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await loading_message.delete()
                
                new_message = await query.message.reply_text(
                    text=f"🤖 Market Sentiment Analysis for {instrument}\n\n{sentiment_data}",
                    reply_markup=reply_markup
                )
                
                context.user_data['last_message'] = new_message.message_id
                
        except Exception as e:
            logger.error(f"Error showing analysis: {str(e)}")
            await query.edit_message_text(
                "Sorry, an error occurred. Please try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_instruments")]])
            )

    async def back_to_instruments(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to instruments button"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Verwijder de huidige message (chart/sentiment/calendar)
            await query.message.delete()
            
            # Bepaal welke keyboard te tonen op basis van market
            market = context.user_data.get('market', 'forex')
            keyboard_map = {
                'forex': FOREX_KEYBOARD,
                'crypto': CRYPTO_KEYBOARD,
                'commodities': COMMODITIES_KEYBOARD,
                'indices': INDICES_KEYBOARD
            }
            
            # Stuur nieuwe message met instrument keuze
            await query.message.reply_text(
                text="Please select an instrument:",
                reply_markup=InlineKeyboardMarkup(keyboard_map[market])
            )
            return CHOOSE_INSTRUMENT
            
        except Exception as e:
            logger.error(f"Error handling back to instruments: {str(e)}")
            # Bij error terug naar hoofdmenu
            await query.message.reply_text(
                text="Sorry, something went wrong. Please select what you would like to do:",
                reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
            )
            return CHOOSE_MENU

    async def back_to_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Ga terug naar analyse type keuze"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            text="Welcome! What would you like to analyze?",
            reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
        )
        return CHOOSE_ANALYSIS

    async def back_to_market(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Ga terug naar market keuze"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            text="Please select your preferred market:",
            reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
        )
        return CHOOSE_MARKET

    async def back_to_instrument(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Ga terug naar instrument keuze"""
        query = update.callback_query
        await query.answer()
        
        market = context.user_data.get('market', 'forex')
        await query.edit_message_text(
            text="Please select an instrument:",
            reply_markup=InlineKeyboardMarkup(FOREX_KEYBOARD)  # Later kunnen we dit per market maken
        )
        return CHOOSE_INSTRUMENT

    async def back_to_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle back to menu button"""
        query = update.callback_query
        await query.answer()
        
        # Reset user_data
        context.user_data.clear()
        
        # Terug naar hoofdmenu met START_KEYBOARD
        await query.edit_message_text(
            text="Welcome! Please select what you would like to do:",
            reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
        )
        return CHOOSE_MENU  # Belangrijk: we gaan terug naar CHOOSE_MENU state

    def _create_signal_prompt(self, signal: Dict[str, Any]) -> str:
        """Create prompt for signal formatting"""
        return f"""Format this trading signal using EXACTLY this template:

🚨 NEW TRADING SIGNAL 🚨

Instrument: {signal['instrument']}
Action: {signal['action']} {'📈' if signal['action'] == 'BUY' else '📉'}

Entry Price: {signal['price']}
Take Profit 1: {signal['takeProfit1']} 🎯
Take Profit 2: {signal['takeProfit2']} 🎯
Take Profit 3: {signal['takeProfit3']} 🎯
Stop Loss: {signal['stopLoss']} 🔴

Timeframe: {signal['timeframe']}
Strategy: Test Strategy"""

    async def handle_chart_button(self, callback_query: CallbackQuery, instrument: str):
        """Handle chart button click"""
        try:
            # Toon loading message
            await callback_query.edit_message_text(
                text=f"⏳ Generating chart for {instrument}...\n\nThis may take a moment."
            )
            
            # Get chart image
            chart_image = await self.chart.get_chart(instrument, timeframe="1h")
            
            if not chart_image:
                await callback_query.edit_message_text(
                    text=f"Sorry, could not generate chart for {instrument}. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data=f"back_to_signal_{instrument}")
                    ]])
                )
                return
            
            # Cache the chart in Redis for future use
            try:
                signal_key = f"signal:{callback_query.message.message_id}"
                self.redis.hset(signal_key, "chart", base64.b64encode(chart_image).decode('utf-8'))
                self.redis.expire(signal_key, 3600)  # 1 hour expiry
            except Exception as redis_error:
                logger.error(f"Redis caching error: {str(redis_error)}")
            
            # Determine back button callback data
            if 'signal' in callback_query.message.text.lower():
                back_callback = f"back_to_signal_{instrument}"
            else:
                back_callback = f"back_to_instruments_{instrument}"
            
            # Update message with chart image
            await callback_query.edit_message_media(
                media=InputMediaPhoto(
                    media=chart_image,
                    caption=f"📊 Technical Analysis for {instrument}"
                ),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data=back_callback)
                ]])
            )
        except Exception as e:
            logger.error(f"Error handling chart button: {str(e)}")
            await callback_query.edit_message_text(
                text=f"Sorry, an error occurred while generating the chart for {instrument}.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")
                ]])
            )

    async def show_sentiment_analysis(self, callback_query: CallbackQuery, instrument: str):
        """Toon sentiment analyse voor een instrument"""
        try:
            # Toon loading message
            await callback_query.edit_message_text(
                text=f"⏳ Analyzing market sentiment for {instrument}...\n\nThis may take a moment."
            )
            
            # Get sentiment data
            market = 'crypto' if any(crypto in instrument for crypto in ['BTC', 'ETH', 'XRP']) else 'forex'
            sentiment_data = await self.sentiment.get_market_sentiment({
                'instrument': instrument,
                'market': market
            })
            
            # Bepaal de juiste back callback data
            # Controleer of dit vanuit een trading signal komt of vanuit analyse
            if 'signal' in callback_query.message.text.lower():
                # Het komt van een trading signal
                back_callback = f"back_to_signal_{instrument}"
            else:
                # Het komt van analyse
                back_callback = f"back_to_instruments_{instrument}"
            
            # Update message with sentiment data
            await callback_query.edit_message_text(
                text=f"🧠 <b>Market Sentiment Analysis for {instrument}</b>\n\n{sentiment_data}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data=back_callback)
                ]])
            )
        except Exception as e:
            logger.error(f"Error showing sentiment analysis: {str(e)}")
            await callback_query.edit_message_text(
                text=f"Sorry, er is een fout opgetreden bij het ophalen van sentiment data voor {instrument}. Probeer het later opnieuw.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")
                ]])
            )

    async def handle_calendar_button(self, callback_query: CallbackQuery, instrument: str):
        """Handle calendar button click"""
        try:
            # Toon loading message zonder back button
            await callback_query.edit_message_text(
                text="⏳ Loading Economic Calendar...\n\nFetching latest economic events..."
            )

            # Get calendar data
            calendar_data = await self.calendar.get_economic_calendar(instrument)
            
            # Bepaal de juiste back callback data
            back_callback = "back_to_signal" if instrument else "back_analysis"
            
            # Update message with calendar data and back button
            await callback_query.edit_message_text(
                text=calendar_data,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data=back_callback)
                ]])
            )
        except Exception as e:
            logger.error(f"Error handling calendar button: {str(e)}")
            await callback_query.edit_message_text(
                text="Sorry, er is een fout opgetreden bij het ophalen van de economische kalender. Probeer het later opnieuw.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")
                ]])
            )

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel and end the conversation."""
        try:
            logger.info(f"User {update.effective_user.id} canceled the conversation")
            await update.message.reply_text(
                "Operation cancelled. Use /menu to see available commands."
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error in cancel command: {str(e)}")
            logger.exception(e)
            return ConversationHandler.END

    async def send_test_signal(self):
        """Stuur een test trading signal"""
        test_signal = {
            "instrument": "EURUSD",
            "market": "forex",
            "timeframe": "1h",
            "action": "BUY",
            "price": "1.0950",
            "takeProfit1": "1.0965",
            "takeProfit2": "1.0980",
            "takeProfit3": "1.0995",
            "stopLoss": "1.0935",
            "strategy": "Test Strategy"
        }
        
        try:
            # Format en verstuur het signaal
            await self.broadcast_signal(test_signal)
            logger.info("Test signal sent successfully")
        except Exception as e:
            logger.error(f"Error sending test signal: {str(e)}")

    async def show_market_selection(self, callback_query: CallbackQuery, analysis_type: str):
        """Toon market selectie"""
        try:
            logger.info(f"Showing market selection for analysis_type: {analysis_type}")
            
            # Maak een nieuwe keyboard met aangepaste callback data
            keyboard = []
            for row in MARKET_KEYBOARD:
                new_row = []
                for button in row:
                    if "Back" in button.text:
                        # Bepaal de juiste back callback data
                        if analysis_type in ['technical', 'sentiment', 'calendar']:
                            back_callback = "back_analysis"
                        else:
                            back_callback = "back_signals"
                        
                        new_button = InlineKeyboardButton(
                            text="⬅️ Back",
                            callback_data=back_callback
                        )
                    else:
                        # Voor market buttons, voeg analysis_type toe aan callback data
                        market = button.text.lower()
                        new_button = InlineKeyboardButton(
                            text=button.text,
                            callback_data=f"market_{market}_{analysis_type}"
                        )
                    new_row.append(new_button)
                keyboard.append(new_row)
            
            await callback_query.edit_message_text(
                text="Please select a market:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error showing market selection: {str(e)}")
            await callback_query.edit_message_text(
                text="Sorry, something went wrong. Please use /start to begin again.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Back to Start", callback_data="start")
                ]])
            )

    async def show_instruments(self, callback_query: CallbackQuery, market: str, analysis_type: str):
        """Toon instrumenten voor gekozen market"""
        try:
            logger.info(f"Showing instruments for market: {market}, analysis_type: {analysis_type}")
            
            # Bepaal welke keyboard te gebruiken
            keyboard_map = {
                'forex': FOREX_KEYBOARD,
                'crypto': CRYPTO_KEYBOARD,
                'commodities': COMMODITIES_KEYBOARD,
                'indices': INDICES_KEYBOARD
            }
            base_keyboard = keyboard_map.get(market, FOREX_KEYBOARD)
            
            # Maak een nieuwe keyboard met aangepaste callback data
            keyboard = []
            for row in base_keyboard:
                new_row = []
                for button in row:
                    if "Back" in button.text:
                        # Bepaal de juiste back callback data
                        if analysis_type in ['technical', 'sentiment', 'calendar']:
                            back_callback = "back_analysis"
                        else:
                            back_callback = "back_signals"
                        
                        new_button = InlineKeyboardButton(
                            text="⬅️ Back",
                            callback_data=back_callback
                        )
                    else:
                        # Voor instrument buttons, voeg analysis_type toe aan callback data
                        instrument = button.text
                        new_button = InlineKeyboardButton(
                            text=instrument,
                            callback_data=f"instrument_{instrument}_{analysis_type}"
                        )
                    new_row.append(new_button)
                keyboard.append(new_row)
            
            await callback_query.edit_message_text(
                text=f"Select an instrument from {market.title()}:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error showing instruments: {str(e)}")
            await callback_query.edit_message_text(
                text="Sorry, something went wrong. Please use /start to begin again.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Back to Start", callback_data="start")
                ]])
            )

    async def handle_back(self, callback_query: CallbackQuery, back_type: str):
        """Handle back button clicks"""
        try:
            logger.info(f"Handling back button with type: {back_type}")
            
            if back_type == 'menu':
                await callback_query.edit_message_text(
                    text=WELCOME_MESSAGE,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
            elif back_type == 'analysis':
                # Terug naar analyse menu
                await callback_query.edit_message_text(
                    text="Select your analysis type:",
                    reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                )
            elif back_type == 'signals':
                # Terug naar signals menu
                await callback_query.edit_message_text(
                    text="What would you like to do with trading signals?",
                    reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                )
            elif back_type == 'to':
                # Dit is een back_to_instruments of back_to_signal callback
                # Laat main.py dit afhandelen
                logger.info("Letting main.py handle back_to callback")
                pass
            elif back_type == 'market':
                # Probeer de analysis_type te bepalen uit de callback data
                try:
                    # Probeer eerst uit de callback data
                    if callback_query.data and len(callback_query.data.split('_')) > 2:
                        parts = callback_query.data.split('_')
                        analysis_type = parts[2] if len(parts) > 2 else 'analysis'
                    else:
                        # Anders probeer uit de keyboard data
                        keyboard_data = callback_query.message.reply_markup.inline_keyboard[0][0].callback_data
                        if 'technical' in keyboard_data:
                            analysis_type = 'technical'
                        elif 'sentiment' in keyboard_data:
                            analysis_type = 'sentiment'
                        elif 'calendar' in keyboard_data:
                            analysis_type = 'calendar'
                        else:
                            analysis_type = 'analysis'
                    
                    # Als het technical, sentiment of calendar is, ga terug naar analyse menu
                    if analysis_type in ['technical', 'sentiment', 'calendar']:
                        await callback_query.edit_message_text(
                            text="Select your analysis type:",
                            reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                        )
                    else:
                        # Anders ga terug naar market selectie voor signals
                        await self.show_market_selection(callback_query, 'signals')
                except Exception as inner_e:
                    logger.error(f"Error determining analysis type: {str(inner_e)}")
                    # Fallback naar analyse menu
                    await callback_query.edit_message_text(
                        text="Select your analysis type:",
                        reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
                    )
            else:
                # Onbekend back type, fallback naar start menu
                logger.warning(f"Unknown back type: {back_type}")
                await callback_query.edit_message_text(
                    text=WELCOME_MESSAGE,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
                )
        except Exception as e:
            logger.error(f"Error handling back button: {str(e)}")
            await callback_query.edit_message_text(
                text="Sorry, something went wrong. Please use /start to begin again.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Back to Start", callback_data="start")
                ]])
            )

    async def handle_delete_preferences(self, callback_query: CallbackQuery) -> None:
        """Handle delete preferences button"""
        try:
            user_id = callback_query.from_user.id
            
            # Get current preferences
            preferences = await self.db.get_user_preferences(user_id)
            
            if not preferences:
                await callback_query.edit_message_text(
                    text="You don't have any preferences to delete.",
                    reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                )
                return
            
            # Create keyboard with delete buttons for each preference
            keyboard = []
            for pref in preferences:
                button_text = f"❌ {pref['instrument']} ({pref['timeframe']} - {pref['style']})"
                callback_data = f"delete_pref_{pref['instrument']}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
            
            # Add back button
            keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_manage")])
            
            await callback_query.edit_message_text(
                text="Select preferences to delete:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logger.error(f"Error handling delete preferences: {str(e)}")
            await callback_query.edit_message_text(
                text="Sorry, something went wrong while deleting preferences.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="back_signals")
                ]])
            )

    async def delete_single_preference(self, callback_query: CallbackQuery) -> None:
        """Delete a single preference"""
        try:
            user_id = callback_query.from_user.id
            instrument = callback_query.data.split('_')[2]  # delete_pref_EURUSD -> EURUSD
            
            # Delete from database
            await self.db.delete_preference(user_id, instrument)
            
            # Show updated preferences
            await self.manage_preferences(callback_query)
            
        except Exception as e:
            logger.error(f"Error deleting preference: {str(e)}")
            await callback_query.edit_message_text(
                text="Sorry, something went wrong while deleting the preference.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="back_signals")
                ]])
            )

    async def back_to_signals(self, callback_query: CallbackQuery) -> None:
        """Handle back to signals menu"""
        try:
            await callback_query.edit_message_text(
                text="What would you like to do with trading signals?",
                reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
            )
        except Exception as e:
            logger.error(f"Error handling back to signals: {str(e)}")

    def _extract_instrument(self, callback_query: CallbackQuery) -> str:
        """Extract instrument from callback query data or message"""
        try:
            # Probeer eerst uit callback data
            if callback_query.data:
                # Voor calendar_EURUSD of sentiment_BTCUSD etc.
                parts = callback_query.data.split('_')
                if len(parts) >= 2:
                    return parts[1]
            
            # Als dat niet lukt, probeer uit het originele bericht
            if callback_query.message and callback_query.message.text:
                # Zoek naar "Instrument: XXX" in het bericht
                lines = callback_query.message.text.split('\n')
                for line in lines:
                    if line.startswith('Instrument:'):
                        return line.split(':')[1].strip()
            
            # Fallback naar default instrument
            logger.warning("Could not extract instrument, using default")
            return "EURUSD"
            
        except Exception as e:
            logger.error(f"Error extracting instrument: {str(e)}")
            return "EURUSD"

    async def show_original_signal(self, callback_query: CallbackQuery) -> None:
        """Toon het originele signaal bericht"""
        try:
            # Extract instrument
            instrument = self._extract_instrument(callback_query)
            
            # Probeer opgeslagen market data op te halen, met fallback
            market_data = {}
            try:
                signal_key = f"market_data:{instrument}"
                market_data = self.redis.hgetall(signal_key)
            except Exception as redis_error:
                logger.error(f"Redis error: {str(redis_error)}")
                # Ga door met lege market_data
            
            if not market_data:
                # Als er geen opgeslagen data is of Redis niet werkt, gebruik default verdict
                market_data = {'verdict': "✅ Trade aligns with market analysis"}
            
            # Maak keyboard
            keyboard = [
                [
                    InlineKeyboardButton("📊 Technical Analysis", callback_data=f"chart_{instrument}"),
                    InlineKeyboardButton("🤖 Market Sentiment", callback_data=f"sentiment_{instrument}")
                ],
                [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"calendar_{instrument}")]
            ]

            # Format signal met opgeslagen verdict
            original_signal = f"""🚨 NEW TRADING SIGNAL 🚨

Instrument: {instrument}
Action: BUY 📈

Entry Price: 2.300
Take Profit 1: 2.350 🎯
Take Profit 2: 2.400 🎯
Take Profit 3: 2.450 🎯
Stop Loss: 2.250 🔴

Timeframe: 1h
Strategy: Test Strategy

---------------

Risk Management:
• Position size: 1-2% max
• Use proper stop loss
• Follow your trading plan

---------------

🤖 SigmaPips AI Verdict:
{market_data.get('verdict', '✅ Trade aligns with market analysis')}"""

            # Update het bericht
            await callback_query.edit_message_text(
                text=original_signal,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logger.error(f"Error showing original signal: {str(e)}")
            try:
                # Fallback bericht bij error
                await callback_query.edit_message_text(
                    text="Sorry, something went wrong. Please use /start to begin again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🏠 Back to Start", callback_data="start")
                    ]])
                )
            except Exception as answer_error:
                logger.error(f"Error sending error message: {str(answer_error)}")

    def _analyze_sentiment_for_verdict(self, sentiment_data: str) -> str:
        """Analyseer sentiment data en genereer een verdict"""
        try:
            sentiment_lower = sentiment_data.lower()
            
            # Positieve indicatoren
            bullish_indicators = [
                "bullish", "positive", "upward", "support", "buying pressure",
                "higher", "strength", "momentum", "rally"
            ]
            
            # Negatieve indicatoren
            bearish_indicators = [
                "bearish", "negative", "downward", "resistance", "selling pressure",
                "lower", "weakness", "decline", "pullback"
            ]
            
            # Tel indicatoren
            bullish_count = sum(1 for indicator in bullish_indicators if indicator in sentiment_lower)
            bearish_count = sum(1 for indicator in bearish_indicators if indicator in sentiment_lower)
            
            # Vereenvoudigde verdicts met één emoji en één zin
            if bullish_count > bearish_count:
                return "✅ Bullish market sentiment supports this trade"
            elif bearish_count > bullish_count:
                return "⚠️ Bearish market sentiment detected"
            else:
                return "⚖️ Mixed market sentiment signals"
            
        except Exception as e:
            logger.error(f"Error analyzing sentiment: {str(e)}")
            return "⚠️ Unable to analyze market sentiment"

    async def prepare_market_data(self, instrument: str) -> Dict[str, str]:
        """Bereid market data voor en sla op voor later gebruik"""
        try:
            # Market type detecteren
            market = 'crypto' if any(crypto in instrument for crypto in ['BTC', 'ETH', 'XRP']) else 'forex'
            
            # Sentiment ophalen
            sentiment_data = await self.sentiment.get_market_sentiment({
                'instrument': instrument,
                'market': market
            })
            
            # Genereer verdict
            verdict = self._analyze_sentiment_for_verdict(sentiment_data)
            
            # Sla op in Redis voor later gebruik
            data = {
                'sentiment': sentiment_data,
                'verdict': verdict
            }
            
            signal_key = f"market_data:{instrument}"
            self.redis.hmset(signal_key, data)
            self.redis.expire(signal_key, 3600)  # 1 uur geldig
            
            return data
            
        except Exception as e:
            logger.error(f"Error preparing market data: {str(e)}")
            return {
                'sentiment': "Market sentiment data unavailable",
                'verdict': "⚠️ Market data unavailable"
            }

    async def start_from_callback(self, update: Update) -> int:
        """Start the conversation from a callback query."""
        try:
            user = update.effective_user
            logger.info(f"Starting conversation with user {user.id} from callback")
            
            # Het is een callback query
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                text=WELCOME_MESSAGE,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(START_KEYBOARD)
            )
            
            return CHOOSE_MENU
            
        except Exception as e:
            logger.error(f"Error in start_from_callback: {str(e)}")
            try:
                await update.callback_query.edit_message_text(
                    text="Sorry, something went wrong. Please try again with /start",
                    reply_markup=None
                )
            except Exception as inner_e:
                logger.error(f"Error sending error message: {str(inner_e)}")
            return ConversationHandler.END
