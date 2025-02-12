import os
import ssl
import asyncio
import logging
import aiohttp
import redis
import json
from typing import Dict, Any

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

logger = logging.getLogger(__name__)

# States
CHOOSE_MARKET, CHOOSE_INSTRUMENT, CHOOSE_TIMEFRAME, MANAGE_PREFERENCES = range(4)

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
    [InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD")],
    [InlineKeyboardButton("XAGUSD", callback_data="instrument_XAGUSD")],
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
    [InlineKeyboardButton("Add More", callback_data="add_more")],
    [InlineKeyboardButton("Manage Preferences", callback_data="manage_prefs")]
]

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
                decode_responses=True
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
                    CallbackQueryHandler(self._manage_preferences, pattern="^add_more|manage_prefs|delete_prefs|delete_\d+|start|manage$")
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
            
    async def send_signal(self, chat_id: str, signal: Dict[str, Any], sentiment: str = None, chart: bytes = None, events: list = None):
        """Send formatted signal message with inline buttons"""
        try:
            # Controleer of de gebruiker de bot heeft gestart
            try:
                chat_member = await self.bot.get_chat_member(chat_id, chat_id)
                if chat_member.status in ["left", "kicked"]:
                    logger.warning(f"User {chat_id} has left the chat or blocked the bot.")
                    return False
            except Exception as e:
                logger.warning(f"Failed to check chat member status: {str(e)}")
                return False

            message = (
                "<b>🚨 TRADING SIGNAL</b>\n\n"
                f"<b>Symbol:</b> {signal['symbol']}\n"
                f"<b>Action:</b> {signal['action']}\n"
                f"<b>Entry Price:</b> {signal['price']}\n"
                f"<b>Stop Loss:</b> {signal['stopLoss']}\n"
                f"<b>Take Profit:</b> {signal['takeProfit']}\n"
                f"<b>Timeframe:</b> {signal['timeframe']}\n\n"
                "<b>⚠️ Risk Management</b>\n"
                "• Use proper position sizing\n"
                "• Always use a stop loss\n"
                "• Maximum risk per trade: 1-2%"
            )

            keyboard = [
                [
                    InlineKeyboardButton("📊 Technical Analysis", callback_data=f"chart_{signal['symbol']}_{signal['timeframe']}"),
                    InlineKeyboardButton("🤖 Market Sentiment", callback_data=f"sentiment_{signal['symbol']}")
                ],
                [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"calendar_{signal['symbol']}")]
            ]
            
            # Convert keyboard to JSON-serializable format
            keyboard_data = [[{"text": btn.text, "callback_data": btn.callback_data} for btn in row] for row in keyboard]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            sent_message = await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            
            # Store in Redis with JSON-serializable keyboard
            message_key = f"signal:{sent_message.message_id}"
            cache_data = {
                'text': message,
                'keyboard': json.dumps(keyboard_data),
                'parse_mode': 'HTML'
            }
            
            try:
                self.redis.hmset(message_key, cache_data)
                self.redis.expire(message_key, 3600)
                logger.info(f"Stored signal in Redis: {message_key}")
            except Exception as e:
                logger.error(f"Redis storage error: {str(e)}")
            
            return True

        except Exception as e:
            logger.error(f"Failed to send signal to {chat_id}: {str(e)}")
            return False

    def _format_signal_message(self, signal: Dict[str, Any], sentiment: str = None, events: list = None) -> str:
        """Format signal data into a readable message"""
        message = f"New Signal Alert\n\n"
        message += f"Symbol: {signal['symbol']}\n"
        message += f"Action: {signal['action']}\n"
        message += f"Price: {signal['price']}\n"
        message += f"Stop Loss: {signal['stopLoss']}\n"
        message += f"Take Profit: {signal['takeProfit']}\n"
        message += f"Timeframe: {signal['timeframe']}\n"
        
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
        
        try:
            user_id = update.effective_user.id
            new_preferences = {
                'user_id': user_id,
                'market': context.user_data['market'],
                'instrument': context.user_data['instrument'],
                'timeframe': context.user_data['timeframe']
            }
            
            # Check voor dubbele combinaties
            existing = self.db.supabase.table('subscriber_preferences').select('*').eq('user_id', user_id).execute()
            
            for pref in existing.data:
                if (pref['market'] == new_preferences['market'] and 
                    pref['instrument'] == new_preferences['instrument'] and 
                    pref['timeframe'] == new_preferences['timeframe']):
                    
                    keyboard = [
                        [InlineKeyboardButton("Try Again", callback_data="add_more")],
                        [InlineKeyboardButton("Manage Preferences", callback_data="manage_prefs")]
                    ]
                    
                    await query.edit_message_text(
                        text="You already have this combination saved!\n\n"
                             f"Market: {new_preferences['market']}\n"
                             f"Instrument: {new_preferences['instrument']}\n"
                             f"Timeframe: {new_preferences['timeframe']}",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return MANAGE_PREFERENCES
            
            # Als er geen dubbele combinatie is, ga door met opslaan
            response = self.db.supabase.table('subscriber_preferences').insert(new_preferences).execute()
            logger.info(f"Added new preferences: {new_preferences}")
            
            logger.info(f"Database response: {response}")
            
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
                return MANAGE_PREFERENCES
            
            message = "Your current preferences:\n\n"
            for i, pref in enumerate(response.data, 1):
                message += f"{i}. {pref['market']} - {pref['instrument']} - {pref['timeframe']}\n"
            
            keyboard = [
                [InlineKeyboardButton("Add More", callback_data="add_more")],
                [DELETE_BUTTON]
            ]
            
            await update.message.reply_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return MANAGE_PREFERENCES
            
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
            return MANAGE_PREFERENCES
        except Exception as e:
            logger.error(f"Error handling menu command: {str(e)}")

    async def _manage_preferences(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle preference management"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "add_more" or query.data == "start":
            reply_markup = InlineKeyboardMarkup(MARKET_KEYBOARD)
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
                return MANAGE_PREFERENCES
            
            message = "Your current preferences:\n\n"
            for i, pref in enumerate(response.data, 1):
                message += f"{i}. {pref['market']} - {pref['instrument']} - {pref['timeframe']}\n"
            
            keyboard = [
                [InlineKeyboardButton("Add More", callback_data="add_more")],
                [DELETE_BUTTON]
            ]
            
            await query.edit_message_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return MANAGE_PREFERENCES
        
        elif query.data == "delete_prefs":
            user_id = query.from_user.id
            response = self.db.supabase.table('subscriber_preferences').select('*').eq('user_id', user_id).execute()
            
            message = "Select a preference to delete:\n\n"
            keyboard = []
            
            for i, pref in enumerate(response.data, 1):
                message += f"{i}. {pref['market']} - {pref['instrument']} - {pref['timeframe']}\n"
                keyboard.append([InlineKeyboardButton(f"Delete {i}", callback_data=f"delete_{pref['id']}")])
            
            keyboard.append([InlineKeyboardButton("Back", callback_data="manage_prefs")])
            
            await query.edit_message_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return MANAGE_PREFERENCES
        
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
                        message += f"{i}. {pref['market']} - {pref['instrument']} - {pref['timeframe']}\n"
                    
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
            
            return MANAGE_PREFERENCES
        
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
            
            if data.startswith("chart_"):
                _, symbol, timeframe = data.split('_')
                chart_image = await self.chart.generate_chart(symbol, timeframe)
                if chart_image:
                    # Store current message before showing chart
                    message_key = f"signal:{message_id}"
                    original_text = query.message.text or query.message.caption
                    
                    cache_data = {
                        'text': original_text,
                        'keyboard': json.dumps(query.message.reply_markup.to_dict()),
                        'parse_mode': 'HTML'
                    }
                    
                    try:
                        self.redis.hmset(message_key, cache_data)
                        self.redis.expire(message_key, 3600)
                        logger.info(f"Stored original message in Redis: {message_key}")
                    except Exception as e:
                        logger.error(f"Redis storage error: {str(e)}")
                    
                    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data=f"back_{message_id}")]]
                    await query.message.edit_media(
                        media=InputMediaPhoto(
                            media=chart_image,
                            caption=f"📊 Technical Analysis for {symbol} ({timeframe})"
                        ),
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
            
            elif data.startswith("back_"):
                original_id = data.split('_')[1]
                message_key = f"signal:{original_id}"
                logger.info(f"Fetching message from Redis with key: {message_key}")
                
                try:
                    cached_data = self.redis.hgetall(message_key)
                    logger.info(f"Found cached data: {cached_data}")
                    
                    if cached_data:
                        keyboard = InlineKeyboardMarkup.de_json(json.loads(cached_data['keyboard']), self.bot)
                        await query.message.edit_media(
                            media=InputMediaPhoto(
                                media="https://i.imgur.com/1HmqL5N.png",  # Placeholder afbeelding
                                caption=cached_data['text'],
                                parse_mode=cached_data['parse_mode']
                            ),
                            reply_markup=keyboard
                        )
                        logger.info("Restored original signal message")
                    else:
                        logger.error(f"No cached data found for message_id: {original_id}")
                except Exception as e:
                    logger.error(f"Error restoring message: {str(e)}")
                    logger.exception(e)
        
        except Exception as e:
            logger.error(f"Error handling button click: {str(e)}")
            logger.exception(e)
            await query.message.reply_text("Sorry, something went wrong.")

# ... rest van de code ...
