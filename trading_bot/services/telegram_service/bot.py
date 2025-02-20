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
CHOOSE_ANALYSIS = 0  # Eerste state - kies analyse type
CHOOSE_MARKET = 1    # Tweede state - kies market
CHOOSE_INSTRUMENT = 2  # Derde state - kies instrument
CHOOSE_STYLE = 3     # Vierde state - kies trading stijl (alleen voor signals)
SHOW_RESULT = 4      # Laatste state - toon resultaat

# Messages
WELCOME_MESSAGE = """
Welcome to SigmaPips Trading Bot!

I will help you set up your trading preferences.
Please select your preferred market:
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

# Keyboard layouts
MARKET_KEYBOARD = [
    [InlineKeyboardButton("Forex", callback_data="market_forex")],
    [InlineKeyboardButton("Crypto", callback_data="market_crypto")],
    [InlineKeyboardButton("Commodities", callback_data="market_commodities")],
    [InlineKeyboardButton("Indices", callback_data="market_indices")]
]

FOREX_KEYBOARD = [
    [InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD")],
    [InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD")],
    [InlineKeyboardButton("USDJPY", callback_data="instrument_USDJPY")],
    [InlineKeyboardButton("Back", callback_data="back")]
]

STYLE_KEYBOARD = [
    [InlineKeyboardButton("Test (1m)", callback_data="style_test")],
    [InlineKeyboardButton("Scalp (15m)", callback_data="style_scalp")],
    [InlineKeyboardButton("Intraday (1h)", callback_data="style_intraday")],
    [InlineKeyboardButton("Swing (4h)", callback_data="style_swing")],
    [InlineKeyboardButton("Back", callback_data="back")]
]

# Update AFTER_SETUP_KEYBOARD
AFTER_SETUP_KEYBOARD = [
    [InlineKeyboardButton("Add More", callback_data="add_more")],
    [InlineKeyboardButton("Manage Preferences", callback_data="manage_prefs")],
    [InlineKeyboardButton("Back to Start", callback_data="back_to_menu")]
]

# Analysis Type Keyboard
ANALYSIS_KEYBOARD = [
    [InlineKeyboardButton("Technical Analysis", callback_data="analysis_technical")],
    [InlineKeyboardButton("Market Sentiment", callback_data="analysis_sentiment")],
    [InlineKeyboardButton("Economic Calendar", callback_data="analysis_calendar")],
    [InlineKeyboardButton("Trading Signals", callback_data="analysis_signals")]
]

# Timeframe mapping based on style
STYLE_TIMEFRAME_MAP = {
    'test': '1m',
    'scalp': '15m',
    'intraday': '1h',
    'swing': '4h'
}

# Voeg deze mapping toe aan het begin van de file
TIMEFRAME_STYLE_MAP = {
    '1m': 'test',
    '15m': 'scalp',
    '1h': 'intraday',
    '4h': 'swing'
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
            self.redis = db.redis
            
            # Setup services
            self.chart = ChartService()
            self.sentiment = MarketSentimentService()
            self.calendar = EconomicCalendarService()
            
            # Setup conversation handler
            conv_handler = ConversationHandler(
                entry_points=[CommandHandler("start", self.start)],
                states={
                    CHOOSE_ANALYSIS: [
                        CallbackQueryHandler(self.analysis_choice, pattern="^analysis_")
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
                        CallbackQueryHandler(self.manage_preferences, pattern="^manage_prefs$")
                    ]
                },
                fallbacks=[CommandHandler("cancel", self.cancel)]
            )
            
            # Add handlers
            self.application.add_handler(conv_handler)
            self.application.add_handler(CommandHandler("menu", self.menu))
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
            
            # Set bot commands
            commands = [
                ("start", "Set up new trading pairs"),
                ("manage", "Manage your preferences"),
                ("menu", "Show main menu"),
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

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation and ask for analysis type"""
        try:
            user_id = update.effective_user.id
            logger.info(f"Starting conversation with user {user_id}")
            
            await update.message.reply_text(
                "Welcome! What would you like to analyze?",
                reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            )
            return CHOOSE_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error in start command: {str(e)}")
            return ConversationHandler.END

    async def market_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle market selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "back":
            # Terug naar analyse type keuze
            reply_markup = InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
            await query.edit_message_text(
                text="Welcome! What would you like to do?",
                reply_markup=reply_markup
            )
            return CHOOSE_ANALYSIS
        
        # Store the chosen market
        context.user_data['market'] = query.data.replace('market_', '')
        
        # Show instruments based on market choice
        keyboard_map = {
            'forex': FOREX_KEYBOARD,
            'indices': FOREX_KEYBOARD,
            'commodities': FOREX_KEYBOARD,
            'crypto': FOREX_KEYBOARD
        }
        
        reply_markup = InlineKeyboardMarkup(keyboard_map[context.user_data['market']])
        await query.edit_message_text(
            text=f"Please select an instrument for {context.user_data['analysis_type'].replace('_', ' ').title()}:",
            reply_markup=reply_markup
        )
        return CHOOSE_INSTRUMENT

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

    async def menu(self, update: Update, context):
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

    async def add_more(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle add more button"""
        query = update.callback_query
        await query.answer()
        
        # Ga terug naar market selectie voor nieuwe toevoeging
        reply_markup = InlineKeyboardMarkup(MARKET_KEYBOARD)
        await query.edit_message_text(
            text="Please select a market for Trading Signals:",
            reply_markup=reply_markup
        )
        return CHOOSE_MARKET

    async def manage_preferences(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle manage preferences button"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Haal user preferences op
            user_id = update.effective_user.id
            preferences = self.db.supabase.table('subscriber_preferences').select('*').eq('user_id', user_id).execute()
            
            if not preferences.data:
                await query.edit_message_text(
                    text="You don't have any saved preferences yet.\n\nUse /start to set up your first trading pair.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
                )
                return SHOW_RESULT
            
            # Format preferences text
            prefs_text = "Your current preferences:\n\n"
            keyboard = []
            
            for i, pref in enumerate(preferences.data, 1):
                prefs_text += f"{i}. {pref['market']} - {pref['instrument']}\n"
                prefs_text += f"   Style: {pref['style']}, Timeframe: {pref['timeframe']}\n\n"
            
            keyboard.append([InlineKeyboardButton("🗑️ Delete Preferences", callback_data="delete_prefs")])
            keyboard.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")])
            
            await query.edit_message_text(
                text=prefs_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SHOW_RESULT
            
        except Exception as e:
            logger.error(f"Error managing preferences: {str(e)}")
            await query.edit_message_text(
                text="Error retrieving preferences. Please try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
            )
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
            data = query.data  # bijv. 'chart_BTCUSD_1m' of 'back_to_signal_BTCUSD'
            action, *params = data.split('_')
            
            if action == 'back':
                # Haal originele signal op uit Redis
                signal_key = f"signal:{query.message.message_id}"
                cached_data = self.redis.hgetall(signal_key)
                
                if cached_data:
                    # Herstel originele keyboard
                    keyboard = [
                        [
                            InlineKeyboardButton("📊 Technical Analysis", callback_data=f"chart_{cached_data['symbol']}_{cached_data['timeframe']}"),
                            InlineKeyboardButton("🤖 Market Sentiment", callback_data=f"sentiment_{cached_data['symbol']}")
                        ],
                        [InlineKeyboardButton("📅 Economic Calendar", callback_data=f"calendar_{cached_data['symbol']}")]
                    ]
                    
                    # Update message terug naar originele signal
                    await query.message.edit_text(
                        text=cached_data['text'],
                        parse_mode=cached_data['parse_mode'],
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    logger.info("Restored original signal")
                    
            elif action == 'chart':
                await self.handle_chart_button(query, params[0], params[1])
            elif action == 'sentiment':
                await self.handle_sentiment_button(query, params[0])
            elif action == 'calendar':
                await self.handle_calendar_button(query, params[0])
            
        except Exception as e:
            logger.error(f"Error handling button click: {str(e)}")
            logger.exception(e)

    async def broadcast_signal(self, signal: Dict[str, Any]):
        """Broadcast signal to subscribers"""
        try:
            logger.info(f"Starting broadcast for signal: {signal}")
            
            # Get subscribers met timeframe filter
            subscribers = await self.db.get_subscribers(
                instrument=signal['instrument'],
                timeframe=signal.get('timeframe')
            )
            logger.info(f"Found {len(subscribers.data)} subscribers for {signal['instrument']} ({signal.get('timeframe')})")
            
            if not subscribers.data:
                logger.warning(f"No subscribers found for {signal['instrument']} with timeframe {signal.get('timeframe')}")
                return
            
            # Generate chart
            chart_image = await self.chart.generate_chart(signal['instrument'])
            
            # Get sentiment met correcte market type
            sentiment_data = await self.sentiment.get_market_sentiment({
                'symbol': signal['instrument'],
                'market': signal['market']  # Nu gebruiken we de correcte market type
            })
            
            # Format signal
            message = await self._format_signal(signal, sentiment_data)
            
            # Send to each subscriber
            for subscriber in subscribers.data:
                try:
                    await self.bot.send_message(
                        chat_id=subscriber['user_id'],
                        text=message,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    logger.info(f"Signal sent to {subscriber['user_id']}")
                except Exception as e:
                    logger.error(f"Failed to send signal to {subscriber['user_id']}: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error broadcasting signal: {str(e)}")
            logger.exception(e)

    async def analysis_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle analysis type selection"""
        query = update.callback_query
        await query.answer()
        
        analysis_type = query.data.replace('analysis_', '')
        context.user_data['analysis_type'] = analysis_type
        
        if analysis_type == 'signals':
            await query.edit_message_text(
                text="Please select your preferred market:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
            )
            logger.info(f"User {update.effective_user.id} selected Trading Signals")
            return CHOOSE_MARKET
        else:
            # Handle andere analyse types (technical, sentiment, calendar)
            await self._show_analysis(query, context)
            return SHOW_RESULT

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
                         f"Please wait while I gather the data ��"
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
                
            elif analysis_type == 'calendar':
                # Economic Calendar
                loading_message = await query.edit_message_text(
                    text=f"⏳ Fetching economic events for {instrument}...\n\n"
                         f"Please wait while I check the calendar 📅"
                )
                
                calendar_data = await self.calendar.get_economic_calendar(instrument)
                
                keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_instruments")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await loading_message.delete()
                
                new_message = await query.message.reply_text(
                    text=f"📅 Economic Calendar for {instrument}\n\n{calendar_data}",
                    reply_markup=reply_markup
                )
                
                context.user_data['last_message'] = new_message.message_id
                
        except Exception as e:
            logger.error(f"Error showing analysis: {str(e)}")
            await query.edit_message_text(
                "Sorry, an error occurred. Please try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_instruments")]])
            )

    async def _back_to_instruments(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle back to instruments button"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Verwijder de chart message
            await query.message.delete()
            
            # Stuur nieuwe message met instrument keuze
            keyboard_map = {
                'technical': FOREX_KEYBOARD,
                'sentiment': FOREX_KEYBOARD,
                'calendar': FOREX_KEYBOARD
            }
            
            analysis_type = context.user_data['analysis_type']
            reply_markup = InlineKeyboardMarkup(keyboard_map[analysis_type])
            
            await query.message.reply_text(
                text=f"Please select an instrument for {analysis_type.replace('_', ' ').title()} Analysis:",
                reply_markup=reply_markup
            )
            return CHOOSE_INSTRUMENT
            
        except Exception as e:
            logger.error(f"Error handling back button: {str(e)}")
            return CHOOSE_INSTRUMENT

    async def _back_to_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle back to menu button"""
        query = update.callback_query
        await query.answer()
        
        # Terug naar hoofdmenu
        reply_markup = InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
        await query.edit_message_text(
            text="Welcome! What would you like to do?",
            reply_markup=reply_markup
        )
        return CHOOSE_ANALYSIS

    def _create_signal_prompt(self, signal: Dict[str, Any]) -> str:
        """Create prompt for signal formatting"""
        return f"""Format this trading signal using EXACTLY this template:

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

    async def handle_chart_button(self, callback_query: Dict[str, Any], instrument: str, timeframe: str):
        """Handle chart button click"""
        try:
            # Get cached chart
            signal_key = f"signal:{callback_query['message']['message_id']}"
            cached_data = self.redis.hgetall(signal_key)
            
            if cached_data and cached_data.get('chart'):
                chart_image = base64.b64decode(cached_data['chart'])
                
                # Update message with cached chart
                await self.bot.edit_message_media(
                    chat_id=callback_query['message']['chat']['id'],
                    message_id=callback_query['message']['message_id'],
                    media=InputMediaPhoto(
                        media=chart_image,
                        caption=f"📊 Technical Analysis for {instrument}"
                    ),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data=f"back_to_signal_{instrument}")
                    ]])
                )
        except Exception as e:
            logger.error(f"Error handling chart button: {str(e)}")

    async def handle_sentiment_button(self, callback_query: Dict[str, Any], instrument: str):
        """Handle sentiment button click"""
        try:
            # Get sentiment
            sentiment_data = await self.sentiment.get_market_sentiment({
                'symbol': instrument,
                'market': 'crypto' if 'USD' in instrument else 'forex'
            })
            
            # Update existing message with sentiment
            await self.bot.edit_message_text(
                chat_id=callback_query['message']['chat']['id'],
                message_id=callback_query['message']['message_id'],
                text=f"🤖 Market Sentiment for {instrument}\n\n{sentiment_data}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data=f"back_to_signal_{instrument}")
                ]])
            )
        except Exception as e:
            logger.error(f"Error handling sentiment button: {str(e)}")

    async def handle_calendar_button(self, callback_query: Dict[str, Any], instrument: str):
        """Handle calendar button click"""
        try:
            # Get calendar
            calendar_data = await self.calendar.get_economic_calendar()
            
            # Update existing message with calendar
            await self.bot.edit_message_text(
                chat_id=callback_query['message']['chat']['id'],
                message_id=callback_query['message']['message_id'],
                text=f"📅 Economic Calendar for {instrument}\n\n{calendar_data}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data=f"back_to_signal_{instrument}")
                ]])
            )
        except Exception as e:
            logger.error(f"Error handling calendar button: {str(e)}")

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
