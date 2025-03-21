import os
import ssl
import asyncio
import logging
import aiohttp
import redis
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from decimal import Decimal
from functools import wraps

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from telegram.constants import ParseMode
from telegram import Bot

# Import de Trading Bot services
from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
from trading_bot.services.calendar_service.calendar import EconomicCalendarService
from trading_bot.services.database.db import Database

# States for ConversationHandler
(MENU, ANALYZE_MARKET, TRADING_SIGNALS, SELECT_MARKET, 
 SELECT_INSTRUMENT, SELECT_TIMEFRAME, CONFIRM_SIGNAL) = range(7)

# Market Types
FOREX = "forex"
CRYPTO = "crypto"
INDICES = "indices"
COMMODITIES = "commodities"

# Timeframes
TIMEFRAMES = {
    "1m": "⚡ Test (1m)",       # Lightning bolt
    "15m": "🏃 Scalp (15m)",   # Runner
    "30m": "⏱ Scalp (30m)",    # Timer
    "1h": "📊 Intraday (1h)",  # Chart
    "4h": "🌊 Intraday (4h)"   # Wave
}

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class MessageTemplates:
    WELCOME_ACTIVE = """
✅ <b>Welcome to SigmaPips Trading Bot!</b> ✅

Your subscription is <b>ACTIVE</b>. You have full access to all features.

<b>🚀 HOW TO USE:</b>

<b>1. Start with /menu</b>
   - This will show you the main options:
   - <b>Analyze Market</b> - For all market analysis tools
   - <b>Trading Signals</b> - To manage your trading signals

<b>2. Analyze Market options:</b>
   - <b>Technical Analysis</b> - Charts and price levels
   - <b>Market Sentiment</b> - Indicators and market mood
   - <b>Economic Calendar</b> - Upcoming economic events

<b>3. Trading Signals:</b>
   - Set up which signals you want to receive
   - Signals will be sent automatically
   - Each includes entry, stop loss, and take profit levels

Type /menu to start using the bot.
"""

    SUBSCRIPTION_INACTIVE = """
❌ <b>Subscription Inactive</b> ❌

Your SigmaPips Trading Bot subscription is currently inactive. 

To regain access to all features and trading signals, please reactivate your subscription:
"""

    TRIAL_WELCOME = """
🚀 <b>Welcome to SigmaPips Trading Bot!</b> 🚀

<b>Discover powerful trading signals for various markets:</b>
- <b>Forex</b> - Major and minor currency pairs
- <b>Crypto</b> - Bitcoin, Ethereum and other top cryptocurrencies
- <b>Indices</b> - Global market indices
- <b>Commodities</b> - Gold, silver and oil

<b>Features:</b>
✅ Real-time trading signals
✅ Multi-timeframe analysis (1m, 15m, 1h, 4h)
✅ Advanced chart analysis
✅ Sentiment indicators
✅ Economic calendar integration

<b>Start today with a FREE 14-day trial!</b>
Price: $29.99/month after trial
"""

    SUBSCRIPTION_REQUIRED = """
⚠️ <b>Subscription Required</b>

This feature requires an active subscription.
Start your 14-day FREE trial or subscribe now to access all features.

Price: $29.99/month
"""

    @staticmethod
    def get_signal_message(interval: str, instrument: str, direction: str, price: float, sl: float) -> str:
        return f"""Timeframe: {interval}
Strategy: TradingView Signal

------------------------------------------------

Risk Management:
- Position size: 1-2% max
- Use proper stop loss
- Follow your trading plan

------------------------------------------------

🤖 SigmaPips AI Verdict:
The {instrument} {direction.lower()} signal shows a promising setup with defined entry at {price:.2f} and stop loss at {sl:.2f}. Multiple take profit levels provide opportunities for partial profit taking.

If you need any assistance, simply type /help to see available commands.

Happy Trading! 📈
"""

class KeyboardFactory:
    @staticmethod
    def get_main_menu_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton("🔍 Analyze Market", callback_data="menu_analyse"),
                InlineKeyboardButton("📊 Trading Signals", callback_data="menu_signals")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def get_analysis_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton("📈 Technical Analysis", callback_data="analysis_technical"),
                InlineKeyboardButton("🧠 Market Sentiment", callback_data="analysis_sentiment")
            ],
            [
                InlineKeyboardButton("📅 Economic Calendar", callback_data="analysis_calendar")
            ],
            [
                InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def get_market_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton("💱 Forex", callback_data=f"market_{FOREX}"),
                InlineKeyboardButton("💰 Crypto", callback_data=f"market_{CRYPTO}")
            ],
            [
                InlineKeyboardButton("📊 Indices", callback_data=f"market_{INDICES}"),
                InlineKeyboardButton("🛢️ Commodities", callback_data=f"market_{COMMODITIES}")
            ],
            [
                InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def get_timeframe_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton(text, callback_data=f"timeframe_{tf}")]
            for tf, text in TIMEFRAMES.items()
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_instrument")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def get_subscription_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton("Start FREE Trial", callback_data="start_trial"),
                InlineKeyboardButton("Subscribe $29.99/m", callback_data="subscribe")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

class TelegramService:
    def __init__(self, db: Database, stripe_service=None):
        """Initialize telegram service"""
        try:
            # Sla de database op
            self.db = db
            
            # Initialiseer de bot
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
            if not bot_token:
                raise ValueError("Missing Telegram bot token")
            
            # Initialiseer de bot
            self.bot = Bot(token=bot_token)
            
            # Initialiseer de application
            self.application = Application.builder().bot(self.bot).build()
            
            # Initialiseer de services
            self.chart = ChartService()
            self.sentiment = MarketSentimentService()
            self.calendar = EconomicCalendarService()
            
            # Initialiseer message templates en keyboards
            self.messages = MessageTemplates()
            self.keyboards = KeyboardFactory()
            
            # Test de sentiment service
            logger.info("Testing sentiment service...")
            
            # Initialiseer de dictionary voor gebruikerssignalen
            self.user_signals = {}
            
            # Maak de data directory als die niet bestaat
            os.makedirs('data', exist_ok=True)
            
            # Laad bestaande signalen
            self._load_signals()
            
            # Registreer de handlers
            self._register_handlers()
            
            logger.info("Telegram service initialized")
            
            # Houd bij welke updates al zijn verwerkt
            self.processed_updates = set()
            
            self.stripe_service = stripe_service  # Stripe service toevoegen
            
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            raise

    def _register_handlers(self):
        """Register message handlers"""
        try:
            # Create conversation handler with the states
            conv_handler = ConversationHandler(
                entry_points=[
                    CommandHandler("start", self.start_command),
                    CommandHandler("menu", self.menu_command)
                ],
                states={
                    MENU: [
                        CallbackQueryHandler(self.analyze_market_callback, pattern="^menu_analyse$"),
                        CallbackQueryHandler(self.menu_signals_callback, pattern="^menu_signals$")
                    ],
                    ANALYZE_MARKET: [
                        CallbackQueryHandler(self.technical_analysis_callback, pattern="^analysis_technical$"),
                        CallbackQueryHandler(self.sentiment_analysis_callback, pattern="^analysis_sentiment$"),
                        CallbackQueryHandler(self.calendar_analysis_callback, pattern="^analysis_calendar$"),
                        CallbackQueryHandler(self.back_to_menu_callback, pattern="^back_menu$")
                    ],
                    SELECT_MARKET: [
                        CallbackQueryHandler(
                            self.market_selected_callback,
                            pattern=f"^market_({FOREX}|{CRYPTO}|{INDICES}|{COMMODITIES})$"
                        ),
                        CallbackQueryHandler(self.back_to_menu_callback, pattern="^back_menu$")
                    ],
                    SELECT_INSTRUMENT: [
                        CallbackQueryHandler(self.instrument_selected_callback, pattern="^instrument_"),
                        CallbackQueryHandler(self.back_to_market_callback, pattern="^back_market$")
                    ],
                    SELECT_TIMEFRAME: [
                        CallbackQueryHandler(self.timeframe_selected_callback, pattern="^timeframe_"),
                        CallbackQueryHandler(self.back_to_instrument_callback, pattern="^back_instrument$")
                    ],
                    TRADING_SIGNALS: [
                        CallbackQueryHandler(self.signals_add_callback, pattern="^signals_add$"),
                        CallbackQueryHandler(self.signals_manage_callback, pattern="^signals_manage$"),
                        CallbackQueryHandler(self.back_to_menu_callback, pattern="^back_menu$")
                    ]
                },
                fallbacks=[CommandHandler("help", self.help_command)]
            )
            
            # Add handlers
            self.application.add_handler(conv_handler)
            self.application.add_handler(CommandHandler("help", self.help_command))
            
            # Add error handler
            self.application.add_error_handler(self.error_handler)
            
            logger.info("Handlers registered successfully")
        except Exception as e:
            logger.error(f"Error registering handlers: {str(e)}")
            raise

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle /start command"""
        if not update.message or not update.effective_user:
            return ConversationHandler.END
            
        user_id = update.effective_user.id
        is_subscribed = await self.check_subscription(user_id)
        
        if is_subscribed:
            keyboard = self.keyboards.get_main_menu_keyboard()
            await update.message.reply_text(
                self.messages.WELCOME_ACTIVE,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        else:
            keyboard = self.keyboards.get_subscription_keyboard()
            await update.message.reply_text(
                self.messages.TRIAL_WELCOME,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        return MENU

    async def check_subscription(self, user_id: int) -> bool:
        """Check if user has active subscription"""
        # For testing purposes, we'll return True for everyone
        # In production, check with the database
        return True
        
        # In real implementation, you would do something like:
        # return await self.db.is_user_subscribed(user_id)

    # Add all the other handler methods for the bot
    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle /menu command"""
        if not update.message:
            return ConversationHandler.END
            
        keyboard = self.keyboards.get_main_menu_keyboard()
        await update.message.reply_text(
            "Please select an option:",
            reply_markup=keyboard
        )
        return MENU

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command"""
        if not update.message:
            return
            
        help_text = """
Available commands:
/start - Setup and welcome
/menu - Main menu
/help - Show this help message
/manage - Manage preferences

For support, contact @SigmaPipsSupport
"""
        await update.message.reply_text(help_text)

    async def analyze_market_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle analyze market button"""
        query = update.callback_query
        if not query:
            return ConversationHandler.END
            
        await query.answer()
        keyboard = self.keyboards.get_analysis_keyboard()
        await query.edit_message_text(
            text="Choose analysis type:",
            reply_markup=keyboard
        )
        return ANALYZE_MARKET

    async def technical_analysis_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle technical analysis selection"""
        query = update.callback_query
        if not query:
            return ConversationHandler.END
            
        await query.answer()
        keyboard = self.keyboards.get_market_keyboard()
        await query.edit_message_text(
            text="Select market type:",
            reply_markup=keyboard
        )
        return SELECT_MARKET
        
    async def sentiment_analysis_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle sentiment analysis selection"""
        query = update.callback_query
        if not query:
            return ConversationHandler.END
            
        await query.answer()
        keyboard = self.keyboards.get_market_keyboard()
        await query.edit_message_text(
            text="Select market for sentiment analysis:",
            reply_markup=keyboard
        )
        return SELECT_MARKET
        
    async def calendar_analysis_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle calendar analysis selection"""
        query = update.callback_query
        if not query:
            return ConversationHandler.END
            
        await query.answer()
        # Get calendar data
        calendar_text = "Economic Calendar:\n\nLoading economic events..."
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Back", callback_data="back_menu")
        ]])
        
        await query.edit_message_text(
            text=calendar_text,
            reply_markup=keyboard
        )
        return ANALYZE_MARKET
        
    async def back_to_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to menu button"""
        query = update.callback_query
        if not query:
            return ConversationHandler.END
            
        await query.answer()
        keyboard = self.keyboards.get_main_menu_keyboard()
        await query.edit_message_text(
            text="Please select an option:",
            reply_markup=keyboard
        )
        return MENU
        
    async def back_to_market_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to market selection button"""
        query = update.callback_query
        if not query:
            return ConversationHandler.END
            
        await query.answer()
        keyboard = self.keyboards.get_market_keyboard()
        await query.edit_message_text(
            text="Select market type:",
            reply_markup=keyboard
        )
        return SELECT_MARKET
        
    async def back_to_instrument_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to instrument selection button"""
        query = update.callback_query
        if not query:
            return ConversationHandler.END
            
        await query.answer()
        if "market_type" not in context.user_data:
            return await self.back_to_market_callback(update, context)
            
        market_type = context.user_data["market_type"]
        instruments = self.get_instruments_for_market(market_type)
        
        # Create dynamic keyboard based on market type
        keyboard = []
        
        # Create rows with 2 buttons each
        for i in range(0, len(instruments), 2):
            row = []
            for j in range(2):
                if i + j < len(instruments):
                    instrument = instruments[i + j]
                    row.append(InlineKeyboardButton(
                        instrument, 
                        callback_data=f"instrument_{instrument}"
                    ))
            keyboard.append(row)
            
        # Add back button
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_market")])
        
        await query.edit_message_text(
            text=f"Select {market_type} instrument:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELECT_INSTRUMENT
        
    async def menu_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle trading signals menu button"""
        query = update.callback_query
        if not query:
            return ConversationHandler.END
            
        await query.answer()
        # Create a signals keyboard here
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Add Signals", callback_data="signals_add")],
            [InlineKeyboardButton("Manage Signals", callback_data="signals_manage")],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
        ])
        await query.edit_message_text(
            text="Trading Signals Menu:",
            reply_markup=keyboard
        )
        return TRADING_SIGNALS
        
    async def signals_add_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle add signals button"""
        query = update.callback_query
        if not query:
            return ConversationHandler.END
            
        await query.answer()
        keyboard = self.keyboards.get_market_keyboard()
        await query.edit_message_text(
            text="Select market type for signals:",
            reply_markup=keyboard
        )
        return SELECT_MARKET
        
    async def signals_manage_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle manage signals button"""
        query = update.callback_query
        if not query:
            return ConversationHandler.END
            
        await query.answer()
        
        # Here you would show the user's current signal subscriptions
        # For now, we'll just show a simple message
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
        ])
        
        await query.edit_message_text(
            text="You don't have any active signal subscriptions yet.",
            reply_markup=keyboard
        )
        return TRADING_SIGNALS

    async def market_selected_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle market selection"""
        query = update.callback_query
        if not query or not query.data:
            return ConversationHandler.END
            
        await query.answer()
        market_type = query.data.split("_")[1]
        
        # Store the selected market type
        context.user_data["market_type"] = market_type
        
        # Create dynamic keyboard based on market type
        instruments = self.get_instruments_for_market(market_type)
        keyboard = []
        
        # Create rows with 2 buttons each
        for i in range(0, len(instruments), 2):
            row = []
            for j in range(2):
                if i + j < len(instruments):
                    instrument = instruments[i + j]
                    row.append(InlineKeyboardButton(
                        instrument, 
                        callback_data=f"instrument_{instrument}"
                    ))
            keyboard.append(row)
            
        # Add back button
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_market")])
        
        await query.edit_message_text(
            text=f"Select {market_type} instrument:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELECT_INSTRUMENT
        
    async def instrument_selected_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle instrument selection"""
        query = update.callback_query
        if not query or not query.data:
            return ConversationHandler.END
            
        await query.answer()
        instrument = query.data.split("_")[1]
        
        # Store the selected instrument
        context.user_data["instrument"] = instrument
        
        # Show timeframe selection
        keyboard = self.keyboards.get_timeframe_keyboard()
        
        await query.edit_message_text(
            text=f"Select timeframe for {instrument}:",
            reply_markup=keyboard
        )
        return SELECT_TIMEFRAME
        
    async def timeframe_selected_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle timeframe selection"""
        query = update.callback_query
        if not query or not query.data:
            return ConversationHandler.END
            
        await query.answer()
        timeframe = query.data.split("_")[1]
        
        # Store the selected timeframe
        context.user_data["timeframe"] = timeframe
        
        # Get the instrument
        instrument = context.user_data.get("instrument")
        if not instrument:
            return await self.back_to_menu_callback(update, context)
        
        # Here you would get the actual chart, sentiment, or other data
        # For now we'll just show a message
        
        await query.edit_message_text(
            text=f"Loading {timeframe} data for {instrument}...",
            reply_markup=None
        )
        
        # Implement analysis logic here based on context.user_data
        # This is where you would call your services
        
        # For demonstration, we'll just show a dummy message
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Back", callback_data="back_instrument")
        ]])
        
        await query.edit_message_text(
            text=f"Analysis for {instrument} on {timeframe} timeframe:\n\nData not available. This is a placeholder.",
            reply_markup=keyboard
        )
        
        return SELECT_TIMEFRAME

    def get_instruments_for_market(self, market_type: str) -> List[str]:
        """Get available instruments for a market type"""
        if market_type == FOREX:
            return ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
        elif market_type == CRYPTO:
            return ["BTCUSD", "ETHUSD", "XRPUSD", "SOLUSD"] 
        elif market_type == INDICES:
            return ["US500", "US30", "US100", "UK100"]
        elif market_type == COMMODITIES:
            return ["XAUUSD", "XTIUSD"]
        return []

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors"""
        logger.error(f"Error: {context.error}")
        
    def _load_signals(self):
        """Load existing user signals from disk"""
        try:
            signals_file = 'data/user_signals.json'
            if os.path.exists(signals_file):
                with open(signals_file, 'r') as f:
                    self.user_signals = json.load(f)
                logger.info(f"Loaded {len(self.user_signals)} user signals")
            else:
                logger.info("No existing signals file found")
        except Exception as e:
            logger.error(f"Error loading signals: {str(e)}")
            self.user_signals = {}
            
    async def run(self):
        """Start the Telegram bot"""
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        logger.info("Bot started polling")
        
        try:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
        except Exception as e:
            logger.error(f"Error stopping bot: {str(e)}")
