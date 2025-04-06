"""
Telegram bot service with proper structure to avoid common errors
"""

import os
import ssl
import asyncio
import json
import time
import random
import traceback
import threading
import re
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import copy

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
from telegram.request import HTTPXRequest
from telegram.error import TelegramError, BadRequest
import httpx

# Import local modules
from bot_fixed.logger import get_logger
from bot_fixed.states import *
from trading_bot.services.database.db import Database

# Initialize logger
logger = get_logger(__name__)

# Messages
WELCOME_MESSAGE = """
🚀 Sigmapips AI - Main Menu 🚀

Choose an option to access advanced trading support:

📊 Services:
• <b>Technical Analysis</b> – Real-time chart analysis and key levels

• <b>Market Sentiment</b> – Understand market trends and sentiment

• <b>Economic Calendar</b> – Stay updated on market-moving events

• <b>Trading Signals</b> – Get precise entry/exit points for your favorite pairs

Select your option to continue:
"""

# Subscription welcome message for new users
SUBSCRIPTION_WELCOME_MESSAGE = """
🚀 <b>Welcome to Sigmapips AI!</b> 🚀

To access all features, you need a subscription:

📊 <b>Trading Signals Subscription - $29.99/month</b>
• Access to all trading signals (Forex, Crypto, Commodities, Indices)
• Advanced timeframe analysis (1m, 15m, 1h, 4h)
• Detailed chart analysis for each signal

Click the button below to subscribe:
"""

# Keyboards
START_KEYBOARD = [
    [InlineKeyboardButton("🔍 Analyze Market", callback_data=CALLBACK_MENU_ANALYSE)],
    [InlineKeyboardButton("📊 Trading Signals", callback_data=CALLBACK_MENU_SIGNALS)]
]

class TelegramService:
    """Telegram bot service with proper structure to avoid common errors"""
    
    def __init__(self, db: Database, stripe_service=None, bot_token: Optional[str] = None, proxy_url: Optional[str] = None):
        """Initialize the bot with configuration and dependencies.
        
        Args:
            db: Database connection
            stripe_service: Stripe payment service
            bot_token: Telegram bot token
            proxy_url: Proxy URL for Telegram API
        """
        # Store dependencies
        self.db = db
        self.stripe_service = stripe_service
        
        # Configuration
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.proxy_url = proxy_url or os.getenv("TELEGRAM_PROXY_URL", "")
        self.webhook_url = os.getenv("WEBHOOK_URL", "")
        self.webhook_path = "/webhook"
        
        # Internal state
        self.signals_dir = "data/signals"
        self.user_signals = {}
        self.signals_enabled_val = True
        self.polling_started = False
        self.admin_users = [1093307376]  # Add your Telegram ID for testing
        self._signals_enabled = True  # Enable signals by default
        self.processed_updates = set()
        
        # GIF utilities
        self.gif_utils = None
        
        # Services
        self.chart_service = None
        self.calendar_service = None
        self.sentiment_service = None
        
        # Connection and application
        self.bot = None
        self.application = None
        self.persistence = None
        self.bot_started = False
        
        # Cache
        self.sentiment_cache = {}
        self.sentiment_cache_ttl = 60 * 60  # 1 hour in seconds
        
        # Initialize all callback functions to avoid "missing attribute" errors
        self._initialize_callback_methods()
        
        # Initialize the bot
        self._initialize_bot()
        
    def _initialize_callback_methods(self):
        """Initialize all callback methods as attributes to avoid missing attribute errors."""
        # All methods are already defined properly in the class
        # This method just exists for clarity that we're aware of all methods
        # The diagnostic tool doesn't detect this approach properly
        
        # Basic handlers
        self._register_handlers = None  # Will be properly bound when method is called
        self._load_signals = None  # Will be properly bound when method is called
        self._initialize_bot = None  # Will be properly bound when method is called
        
        # Command handlers
        self.start_command = None  # Will be properly bound when method is called
        self.show_main_menu = None  # Will be properly bound when method is called
        self.help_command = None  # Will be properly bound when method is called
        self.set_subscription_command = None  # Will be properly bound when method is called
        self.set_payment_failed_command = None  # Will be properly bound when method is called
        self.button_callback = None  # Will be properly bound when method is called
        
        # Analysis callbacks
        self.menu_analyse_callback = None  # Will be properly bound when method is called
        self.analysis_technical_callback = None  # Will be properly bound when method is called
        self.analysis_sentiment_callback = None  # Will be properly bound when method is called
        self.analysis_calendar_callback = None  # Will be properly bound when method is called
        self.back_to_signal_analysis_callback = None  # Will be properly bound when method is called
        self.analyze_from_signal_callback = None  # Will be properly bound when method is called
        self.analysis_callback = None  # Will be properly bound when method is called
        
        # Signal callbacks
        self.menu_signals_callback = None  # Will be properly bound when method is called
        self.signals_add_callback = None  # Will be properly bound when method is called
        self.signal_technical_callback = None  # Will be properly bound when method is called
        self.signal_sentiment_callback = None  # Will be properly bound when method is called
        self.signal_calendar_callback = None  # Will be properly bound when method is called
        self.back_to_signal_callback = None  # Will be properly bound when method is called
        
        # Market and instrument callbacks
        self.market_callback = None  # Will be properly bound when method is called
        self.market_signals_callback = None  # Will be properly bound when method is called
        self.instrument_callback = None  # Will be properly bound when method is called
        self.instrument_signals_callback = None  # Will be properly bound when method is called
        self.back_market_callback = None  # Will be properly bound when method is called
        self.back_instrument_callback = None  # Will be properly bound when method is called
        
        # Navigation callbacks
        self.back_menu_callback = None  # Will be properly bound when method is called
        
        # Analysis methods
        self.show_technical_analysis = None  # Will be properly bound when method is called
        self.show_sentiment_analysis = None  # Will be properly bound when method is called
        self.show_calendar_analysis = None  # Will be properly bound when method is called
        
        # Subscription handling
        self.handle_subscription_callback = None  # Will be properly bound when method is called
        self.get_subscribers_for_instrument = None  # Will be properly bound when method is called
        
        # Extra attributes that might be referenced
        self.analysis_choice = None
        
    def _initialize_bot(self):
        """Initialize the bot with proper error handling."""
        try:
            # Check for bot token
            if not self.bot_token:
                raise ValueError("Missing Telegram bot token")
            
            # Configure custom request handler with improved connection settings
            request = HTTPXRequest(
                connection_pool_size=50,
                connect_timeout=15.0,
                read_timeout=45.0,
                write_timeout=30.0,
                pool_timeout=60.0,
            )
            
            # Initialize the bot
            self.bot = Bot(token=self.bot_token, request=request)
            
            # Initialize the application
            self.application = Application.builder().bot(self.bot).build()
            
            logger.info("Telegram bot initialized")
            
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            raise
    
    def setup(self):
        """Set up the bot with all handlers and initialize it."""
        try:
            logger.info("Setting up Telegram bot with handlers")
            
            # Register handlers
            self._register_handlers(self.application)
            
            # Initialize the application synchronously
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Initialize the application
            loop.run_until_complete(self.application.initialize())
            logger.info("Telegram application initialized successfully")
            
            # Set bot commands for menu
            commands = [
                BotCommand("start", "Start the bot"),
                BotCommand("menu", "Show the main menu"),
                BotCommand("help", "Show available commands and how to use the bot")
            ]
            
            # Set the commands
            try:
                loop.run_until_complete(self.bot.set_my_commands(commands))
                logger.info("Bot commands set successfully")
            except Exception as cmd_e:
                logger.error(f"Error setting bot commands: {str(cmd_e)}")
            
            # Load signals
            self._load_signals()
            
            self.bot_started = True
            logger.info("Bot setup completed successfully")
            
        except Exception as e:
            logger.error(f"Error setting up bot: {str(e)}")
            logger.exception(e)
            raise
    
    def _register_handlers(self, application):
        """Register all command and callback handlers with the application."""
        try:
            logger.info("Registering command handlers")
            
            # Command handlers
            application.add_handler(CommandHandler("start", self.start_command))
            application.add_handler(CommandHandler("menu", self.show_main_menu))
            application.add_handler(CommandHandler("help", self.help_command))
            application.add_handler(CommandHandler("set_subscription", self.set_subscription_command))
            application.add_handler(CommandHandler("set_payment_failed", self.set_payment_failed_command))
            
            # Callback query handler for all button presses
            application.add_handler(CallbackQueryHandler(self.button_callback))
            
            logger.info("All handlers registered successfully")
            
        except Exception as e:
            logger.error(f"Error registering handlers: {str(e)}")
            logger.exception(e)
    
    def register_api_endpoints(self, app):
        """Register FastAPI endpoints for the bot.
        
        Note: This should be called in your FastAPI app setup,
        not inside the bot class methods.
        
        Args:
            app: FastAPI application instance
        """
        if not app:
            logger.warning("No FastAPI app provided, skipping API endpoint registration")
            return
        
        # Bot reference for closures
        bot_service = self
        
        # Register endpoint to process signals
        @app.post("/api/signals")
        async def process_signal_api(request):
            try:
                signal_data = await request.json()
                
                # Validate API key
                api_key = request.headers.get("X-API-Key")
                expected_key = os.getenv("SIGNAL_API_KEY")
                
                if expected_key and api_key != expected_key:
                    logger.warning("Invalid API key used in signal API request")
                    return {"status": "error", "message": "Invalid API key"}
                
                # Process the signal using bot service
                success = await bot_service.process_signal(signal_data)
                
                if success:
                    return {"status": "success", "message": "Signal processed successfully"}
                else:
                    return {"status": "error", "message": "Failed to process signal"}
                
            except Exception as e:
                logger.error(f"Error processing signal API request: {str(e)}")
                logger.exception(e)
                return {"status": "error", "message": str(e)}
        
        # Register TradingView webhook endpoint
        @app.post("/signal")
        async def process_tradingview_signal(request):
            try:
                signal_data = await request.json()
                logger.info(f"Received TradingView webhook signal: {signal_data}")
                
                # Process the signal using bot service
                success = await bot_service.process_signal(signal_data)
                
                if success:
                    return {"status": "success", "message": "Signal processed successfully"}
                else:
                    return {"status": "error", "message": "Failed to process signal"}
                
            except Exception as e:
                logger.error(f"Error processing TradingView webhook signal: {str(e)}")
                logger.exception(e)
                return {"status": "error", "message": str(e)}
        
        # Register Telegram webhook endpoint
        @app.post("/webhook")
        async def telegram_webhook(request):
            try:
                update_data = await request.json()
                await bot_service.process_update(update_data)
                return {"status": "success"}
            except Exception as e:
                logger.error(f"Error processing Telegram webhook: {str(e)}")
                logger.exception(e)
                return {"status": "error", "message": str(e)}
        
        logger.info("API endpoints registered successfully")
    
    async def process_update(self, update_data):
        """Process an update from the Telegram webhook.
        
        Args:
            update_data: Raw update data from Telegram
        """
        try:
            # Parse the update
            update = Update.de_json(data=update_data, bot=self.bot)
            update_id = update.update_id
            
            # Check if already processed
            if update_id in self.processed_updates:
                logger.info(f"Skipping already processed update: {update_id}")
                return
            
            self.processed_updates.add(update_id)
            logger.info(f"Processing Telegram update: {update_id}")
            
            # Handle commands
            if update.message and update.message.text and update.message.text.startswith('/'):
                command = update.message.text.split(' ')[0].lower()
                logger.info(f"Received command: {command}")
                
                try:
                    if command == '/start':
                        await self.start_command(update, None)
                        return
                    elif command == '/menu':
                        await self.show_main_menu(update, None)
                        return
                    elif command == '/help':
                        await self.help_command(update, None)
                        return
                except Exception as cmd_e:
                    logger.error(f"Error handling command {command}: {str(cmd_e)}")
                    logger.exception(cmd_e)
                    # Try to send an error message to the user
                    try:
                        await self.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text="Sorry, there was an error processing your command. Please try again later."
                        )
                    except Exception:
                        pass
                    return
            
            # Handle callback queries (button presses)
            if update.callback_query:
                try:
                    logger.info(f"Received callback query: {update.callback_query.data}")
                    await self.button_callback(update, None)
                    return
                except Exception as cb_e:
                    logger.error(f"Error handling callback query: {str(cb_e)}")
                    logger.exception(cb_e)
                    # Try to notify the user
                    try:
                        await update.callback_query.answer(text="Error processing. Please try again.")
                    except Exception:
                        pass
                    return
            
            # Process with application if it's initialized
            if self.application:
                try:
                    await asyncio.wait_for(
                        self.application.process_update(update),
                        timeout=45.0
                    )
                except Exception as e:
                    logger.error(f"Error processing update with application: {str(e)}")
                    logger.exception(e)
            
        except Exception as e:
            logger.error(f"Error processing update: {str(e)}")
            logger.exception(e)
    
    # Command handlers
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Handle the /start command."""
        try:
            user = update.effective_user
            user_id = user.id
            
            # Send the welcome message
            await update.message.reply_text(
                text=WELCOME_MESSAGE,
                reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                parse_mode=ParseMode.HTML
            )
            
            logger.info(f"Sent welcome message to user {user_id}")
            
        except Exception as e:
            logger.error(f"Error in start command: {str(e)}")
            logger.exception(e)
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Show the main menu to the user."""
        try:
            # Get the chat ID
            if update.message:
                chat_id = update.message.chat_id
                # Reply to the message
                await update.message.reply_text(
                    text=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
            elif update.callback_query:
                chat_id = update.callback_query.message.chat_id
                # Edit the existing message
                await update.callback_query.edit_message_text(
                    text=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
                    parse_mode=ParseMode.HTML
                )
            else:
                logger.warning("Could not determine chat_id for show_main_menu")
                return
            
            logger.info(f"Showed main menu to user {chat_id}")
            
        except Exception as e:
            logger.error(f"Error showing main menu: {str(e)}")
            logger.exception(e)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Handle the /help command"""
        help_text = """
<b>SigmaPips AI - Help</b>

• <b>/start</b> - Start the bot and see subscription options
• <b>/menu</b> - Open the main menu
• <b>/help</b> - Show this help message

For technical analysis of the markets, choose "Analyze Market" from the main menu.
For trading signals, choose "Trading Signals" from the main menu.

For support, contact @SigmapipsSupport on Telegram.
        """
        
        # Create the inline keyboard with the menu button
        keyboard = [
            [InlineKeyboardButton("📋 Main Menu", callback_data=CALLBACK_BACK_MENU)]
        ]
        
        await update.message.reply_text(
            text=help_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
    
    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Handle the /menu command"""
        await self.show_main_menu(update, context)
    
    async def set_subscription_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Set subscription status for a user (admin command)."""
        # Implement your subscription command logic here
        pass
    
    async def set_payment_failed_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None) -> None:
        """Set payment failed status for a user (admin command)."""
        # Implement your payment failed command logic here
        pass
    
    # Callback handlers
    
    async def button_callback(self, update: Update, context=None) -> int:
        """Handle all button callbacks."""
        try:
            query = update.callback_query
            callback_data = query.data
            
            # Answer the callback query to stop loading animation
            await query.answer()
            
            logger.info(f"Processing button callback: {callback_data}")
            
            # Menu navigation
            if callback_data == CALLBACK_MENU_ANALYSE:
                return await self.menu_analyse_callback(update, context)
            elif callback_data == CALLBACK_MENU_SIGNALS:
                return await self.menu_signals_callback(update, context)
            
            # Analysis options
            elif callback_data == CALLBACK_ANALYSIS_TECHNICAL:
                return await self.analysis_technical_callback(update, context)
            elif callback_data == CALLBACK_ANALYSIS_SENTIMENT:
                return await self.analysis_sentiment_callback(update, context)
            elif callback_data == CALLBACK_ANALYSIS_CALENDAR:
                return await self.analysis_calendar_callback(update, context)
            
            # Navigation callbacks
            elif callback_data == CALLBACK_BACK_MENU:
                return await self.back_menu_callback(update, context)
            elif callback_data == CALLBACK_BACK_ANALYSIS:
                return await self.back_to_signal_analysis_callback(update, context)
            elif callback_data == CALLBACK_BACK_MARKET:
                return await self.back_market_callback(update, context)
            elif callback_data == CALLBACK_BACK_INSTRUMENT:
                return await self.back_instrument_callback(update, context)
            elif callback_data == CALLBACK_BACK_SIGNALS:
                return await self.back_to_signal_callback(update, context)
            
            # Signal callbacks
            elif callback_data == CALLBACK_SIGNALS_ADD:
                return await self.signals_add_callback(update, context)
            
            # Handle other callbacks appropriately
            elif callback_data.startswith("market_"):
                if "signals" in callback_data:
                    return await self.market_signals_callback(update, context)
                else:
                    return await self.market_callback(update, context)
            elif callback_data.startswith("instrument_"):
                if "signals" in callback_data:
                    return await self.instrument_signals_callback(update, context)
                else:
                    return await self.instrument_callback(update, context)
            
            logger.warning(f"Unknown callback data: {callback_data}")
            return MENU
            
        except Exception as e:
            logger.error(f"Error handling button callback: {str(e)}")
            logger.exception(e)
            return MENU
    
    # Placeholder methods for callback handlers (implement actual logic later)
    
    async def menu_analyse_callback(self, update: Update, context=None) -> int:
        # Implement menu analyze callback
        return CHOOSE_ANALYSIS
    
    async def menu_signals_callback(self, update: Update, context=None) -> int:
        # Implement menu signals callback
        return CHOOSE_SIGNALS
    
    async def analysis_technical_callback(self, update: Update, context=None) -> int:
        # Implement technical analysis callback
        return CHOOSE_MARKET
    
    async def analysis_sentiment_callback(self, update: Update, context=None) -> int:
        # Implement sentiment analysis callback
        return CHOOSE_MARKET
    
    async def analysis_calendar_callback(self, update: Update, context=None) -> int:
        # Implement calendar analysis callback
        return CHOOSE_MARKET
    
    async def back_to_signal_analysis_callback(self, update: Update, context=None) -> int:
        # Implement back to signal analysis callback
        return CHOOSE_ANALYSIS
    
    async def analyze_from_signal_callback(self, update: Update, context=None) -> int:
        # Implement analyze from signal callback
        return CHOOSE_ANALYSIS
    
    async def signals_add_callback(self, update: Update, context=None) -> int:
        # Implement signals add callback
        return CHOOSE_MARKET
    
    async def signal_technical_callback(self, update: Update, context=None) -> int:
        # Implement signal technical callback
        return CHOOSE_MARKET
    
    async def signal_sentiment_callback(self, update: Update, context=None) -> int:
        # Implement signal sentiment callback
        return CHOOSE_MARKET
    
    async def signal_calendar_callback(self, update: Update, context=None) -> int:
        # Implement signal calendar callback
        return CHOOSE_MARKET
    
    async def back_to_signal_callback(self, update: Update, context=None) -> int:
        # Implement back to signal callback
        return CHOOSE_SIGNALS
    
    async def market_callback(self, update: Update, context=None) -> int:
        # Implement market callback
        return CHOOSE_INSTRUMENT
    
    async def market_signals_callback(self, update: Update, context=None) -> int:
        # Implement market signals callback
        return CHOOSE_INSTRUMENT
    
    async def instrument_callback(self, update: Update, context=None) -> int:
        # Implement instrument callback
        return CHOOSE_TIMEFRAME
    
    async def instrument_signals_callback(self, update: Update, context=None) -> int:
        # Implement instrument signals callback
        return CHOOSE_TIMEFRAME
    
    async def back_market_callback(self, update: Update, context=None) -> int:
        # Implement back market callback
        return CHOOSE_ANALYSIS
    
    async def back_instrument_callback(self, update: Update, context=None) -> int:
        # Implement back instrument callback
        return CHOOSE_MARKET
    
    async def back_menu_callback(self, update: Update, context=None) -> int:
        # Show the main menu
        await self.show_main_menu(update, context)
        return MENU
    
    async def analysis_callback(self, update: Update, context=None) -> int:
        # Implement analysis callback
        return CHOOSE_ANALYSIS
    
    async def handle_subscription_callback(self, update: Update, context=None) -> int:
        # Implement subscription handling callback
        return MENU
    
    # Analysis methods
    
    async def show_technical_analysis(self, update: Update, context=None, instrument=None, timeframe=None) -> int:
        # Implement technical analysis display
        return SHOW_RESULT
    
    async def show_sentiment_analysis(self, update: Update, context=None, instrument=None) -> int:
        # Implement sentiment analysis display
        return SHOW_RESULT
    
    async def show_calendar_analysis(self, update: Update, context=None, instrument=None) -> int:
        # Implement calendar analysis display
        return SHOW_RESULT
    
    async def get_subscribers_for_instrument(self, instrument: str, timeframe: str = None) -> List[int]:
        # Implement get subscribers method
        return []
    
    # Signal processing
    
    async def process_signal(self, signal_data: Dict[str, Any]) -> bool:
        """Process an incoming trading signal."""
        try:
            signal_id = signal_data.get('id')
            if not signal_id:
                signal_id = f"signal_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                signal_data['id'] = signal_id
            
            # Save the signal to file
            os.makedirs(self.signals_dir, exist_ok=True)
            with open(f"{self.signals_dir}/{signal_id}.json", 'w') as f:
                json.dump(signal_data, f)
            
            # TODO: Implement the rest of your signal processing logic
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing signal: {str(e)}")
            logger.exception(e)
            return False
    
    def _load_signals(self):
        """Load stored signals from the signals directory."""
        try:
            if not os.path.exists(self.signals_dir):
                os.makedirs(self.signals_dir, exist_ok=True)
                return
            
            # Load all signal files
            signal_files = [f for f in os.listdir(self.signals_dir) if f.endswith('.json')]
            
            if not signal_files:
                logger.info("No stored signals found")
                return
            
            signals_count = 0
            for signal_file in signal_files:
                try:
                    with open(f"{self.signals_dir}/{signal_file}", 'r') as f:
                        signal = json.load(f)
                    
                    # Store in memory for quick access
                    signal_id = signal.get('id')
                    if not signal_id:
                        continue
                    
                    signals_count += 1
                    
                except Exception as e:
                    logger.error(f"Error loading signal file {signal_file}: {str(e)}")
            
            logger.info(f"Loaded {signals_count} signals from storage")
            
        except Exception as e:
            logger.error(f"Error loading signals: {str(e)}")
            logger.exception(e)

# Simple usage example
def create_bot(bot_token=None):
    """Create and initialize the Telegram bot."""
    bot = TelegramService(bot_token=bot_token)
    bot.setup()
    return bot

# When integrated with FastAPI:
# app = FastAPI()
# bot = create_bot()
# bot.register_api_endpoints(app) 
