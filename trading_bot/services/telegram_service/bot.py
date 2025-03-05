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
from trading_bot.services.chart_service.tradingview_selenium import TradingViewSeleniumService

logger = logging.getLogger(__name__)

# States
CHOOSE_MENU = 0      # Eerste state - hoofdmenu
CHOOSE_ANALYSIS = 1  # Analyse submenu
CHOOSE_SIGNALS = 2   # Signals submenu
CHOOSE_MARKET = 3    # Market keuze
CHOOSE_INSTRUMENT = 4
CHOOSE_STYLE = 5     # Vierde state - kies trading stijl (alleen voor signals)
SHOW_RESULT = 6      # Laatste state - toon resultaat

# Definieer de states als constanten voor de ConversationHandler
MENU = CHOOSE_MENU
ANALYSIS = CHOOSE_ANALYSIS
MARKET = CHOOSE_MARKET
INSTRUMENT = CHOOSE_INSTRUMENT
STYLE = CHOOSE_STYLE
RESULT = SHOW_RESULT

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

# Hulpfuncties als globale functies
async def log_user_state(update: Update, context: CallbackContext):
    """Log de huidige state van de gebruiker"""
    user_id = update.effective_user.id
    
    # Probeer de huidige conversatie state te krijgen
    current_state = None
    if hasattr(context, 'conversation_states') and context.conversation_states:
        conversation_states = context.conversation_states.get('conversation', {})
        current_state = conversation_states.get((user_id, user_id), None)
    
    # Log de state en user_data
    logger.info(f"User {user_id} - Current state: {current_state}")
    logger.info(f"User {user_id} - User data: {context.user_data}")

async def check_redis_connection(update: Update, context: CallbackContext):
    """Controleer de Redis verbinding"""
    try:
        if hasattr(context.application, 'persistence') and hasattr(context.application.persistence, 'redis'):
            redis_client = context.application.persistence.redis
            if redis_client:
                redis_ping = redis_client.ping()
                logger.info(f"Redis ping: {redis_ping}")
            else:
                logger.warning("Redis client is None")
        else:
            logger.warning("No Redis persistence found")
    except Exception as e:
        logger.error(f"Error checking Redis connection: {str(e)}")

async def error_handler(update: Update, context: CallbackContext):
    """Handle errors in the conversation"""
    logger.error(f"Error handling update: {update}")
    logger.error(f"Error context: {context.error}")
    
    # Stuur een bericht naar de gebruiker
    if update and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Sorry, er is een fout opgetreden. Probeer het opnieuw met /start."
        )
    
    # Reset de conversatie
    return ConversationHandler.END

# Start keyboard
START_KEYBOARD = [
    [InlineKeyboardButton("🔍 Analyse Market", callback_data="menu_analyse")],
    [InlineKeyboardButton("📊 Trading Signals", callback_data="menu_signals")]
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
            
            # Setup services
            self.chart = ChartService()
            self.sentiment = MarketSentimentService()
            self.calendar = EconomicCalendarService()
            
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
                BotCommand("start", "Start de bot en toon het hoofdmenu"),
                BotCommand("help", "Toon help informatie")
            ]
            await self.bot.set_my_commands(commands)
            
            # Maak een persistence handler voor de bot
            import os
            persistence_dir = os.path.join(os.path.dirname(__file__), "persistence")
            os.makedirs(persistence_dir, exist_ok=True)
            
            persistence_path = os.path.join(persistence_dir, "bot_persistence")
            
            # Maak een persistence handler
            persistence = PicklePersistence(
                filepath=persistence_path,
                store_data={"user_data", "chat_data", "bot_data", "callback_data", "conversations"}
            )
            
            # Voeg persistence toe aan de application
            self.application.persistence = persistence
            
            # Definieer de ConversationHandler
            conv_handler = ConversationHandler(
                entry_points=[CommandHandler("start", self.start_command)],
                states={
                    MENU: [
                        CallbackQueryHandler(self.menu_analyse_callback, pattern="^menu_analyse$"),
                        CallbackQueryHandler(self.menu_signals_callback, pattern="^menu_signals$"),
                    ],
                    ANALYSIS: [
                        CallbackQueryHandler(self.analysis_technical_callback, pattern="^analysis_technical$"),
                        CallbackQueryHandler(self.analysis_sentiment_callback, pattern="^analysis_sentiment$"),
                        CallbackQueryHandler(self.analysis_calendar_callback, pattern="^analysis_calendar$"),
                        CallbackQueryHandler(self.back_to_menu_callback, pattern="^back_menu$"),
                    ],
                    MARKET: [
                        CallbackQueryHandler(self.market_callback, pattern="^market_"),
                        CallbackQueryHandler(self.back_to_analysis_callback, pattern="^back_analysis$"),
                    ],
                    INSTRUMENT: [
                        CallbackQueryHandler(self.instrument_callback, pattern="^instrument_"),
                        CallbackQueryHandler(self.back_to_market_callback, pattern="^back_market$"),
                    ],
                    STYLE: [
                        CallbackQueryHandler(self.style_choice, pattern="^style_"),
                        CallbackQueryHandler(self.back_to_instrument, pattern="^back$")
                    ],
                    RESULT: [
                        CallbackQueryHandler(self.add_more, pattern="^add_more$"),
                        CallbackQueryHandler(self.manage_preferences, pattern="^manage_prefs$"),
                        CallbackQueryHandler(self.back_to_menu, pattern="^back_menu$"),
                        CallbackQueryHandler(self.back_to_instruments, pattern="^back_to_instruments$")
                    ]
                },
                fallbacks=[CommandHandler("help", self.help_command)],
                name="my_conversation",
                persistent=False,  # Zet dit op False om persistence uit te schakelen
                per_message=False,
            )
            
            # Voeg handlers toe
            self.application.add_handler(conv_handler)
            
            # Voeg andere handlers toe
            self.application.add_handler(CommandHandler("help", self.help_command))
            
            # Start de application
            await self.application.initialize()
            await self.application.start()
            
            # Log webhook info
            webhook_info = await self.bot.get_webhook_info()
            logger.info(f"Current webhook info: {webhook_info}")
            
            logger.info("Telegram service initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            return False

    # Nieuwe methode voor /start commando
    async def start_command(self, update: Update, context: CallbackContext) -> None:
        """Handle /start command outside of conversation"""
        logger.info(f"Start command received from user {update.effective_user.id}")
        
        try:
            # Stuur het welkomstbericht met de hoofdmenu knoppen
            await update.message.reply_text(
                WELCOME_MESSAGE,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Analyse Market", callback_data="menu_analyse")],
                    [InlineKeyboardButton("📊 Trading Signals", callback_data="menu_signals")]
                ]),
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Welcome message sent to user {update.effective_user.id}")
        except Exception as e:
            logger.error(f"Error in start_command: {str(e)}")
            # Probeer een eenvoudiger bericht te sturen bij een fout
            await update.message.reply_text(
                "Welkom bij de SigmaPips Trading Bot! Er is een fout opgetreden bij het laden van het menu. Probeer het later opnieuw."
            )

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

    async def start(self, update: Update, context: CallbackContext) -> int:
        """Start command handler"""
        logger.info(f"Starting conversation with user {update.effective_user.id}")
        
        # Stuur het welkomstbericht met de hoofdmenu knoppen
        await update.message.reply_text(
            WELCOME_MESSAGE,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Analyse Market", callback_data="menu_analyse")],
                [InlineKeyboardButton("📊 Trading Signals", callback_data="menu_signals")]
            ]),
            parse_mode=ParseMode.HTML
        )
        
        return MENU

    async def menu_analyse_callback(self, update: Update, context: CallbackContext) -> int:
        """Handle analyse menu selection"""
        query = update.callback_query
        try:
            await query.answer()
            
            # Definieer de keyboard direct in de methode
            analysis_keyboard = [
                [InlineKeyboardButton("📈 Technical Analysis", callback_data="analysis_technical")],
                [InlineKeyboardButton("🧠 Market Sentiment", callback_data="analysis_sentiment")],
                [InlineKeyboardButton("📅 Economic Calendar", callback_data="analysis_calendar")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
            ]
            
            # Toon de analyse opties met inline keyboard
            await query.edit_message_text(
                text="Select your analysis type:",
                reply_markup=InlineKeyboardMarkup(analysis_keyboard)
            )
            
            return ANALYSIS
        except Exception as e:
            logger.error(f"Error in menu choice: {str(e)}")
            # Stuur een foutmelding
            await query.edit_message_text(
                text=f"Sorry, er is een fout opgetreden: {str(e)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
                ])
            )
            return MENU

    async def menu_signals_callback(self, update: Update, context: CallbackContext) -> int:
        """Handle signals menu selection"""
        query = update.callback_query
        await query.answer()
        
        # Toon de signalen opties
        await query.edit_message_text(
            text="Trading signals are coming soon!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
            ])
        )
        
        return MENU

    async def analysis_technical_callback(self, update: Update, context: CallbackContext) -> int:
        """Handle technical analysis selection"""
        query = update.callback_query
        await query.answer()
        
        # Log voor debugging
        logger.info("Technical analysis callback triggered")
        
        try:
            # Sla de analyse type op in user_data
            context.user_data['analysis_type'] = 'technical'
            
            # Haal de markten op uit de database of gebruik standaard markten
            markets = ["forex", "crypto", "indices", "commodities"]
            
            # Maak keyboard met markten
            keyboard = []
            for market in markets:
                keyboard.append([InlineKeyboardButton(f"{market.capitalize()}", callback_data=f"market_{market}")])
            
            # Voeg terug knop toe
            keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Update het bericht
            await query.edit_message_text(
                text="Select a market:",
                reply_markup=reply_markup
            )
            
            # Log voor debugging
            logger.info("Moving to MARKET state")
            
            # Ga naar de MARKET state
            return MARKET
        except Exception as e:
            logger.error(f"Error in analysis_technical_callback: {str(e)}")
            
            # Stuur een foutmelding
            await query.edit_message_text(
                text=f"Sorry, er is een fout opgetreden: {str(e)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
                ])
            )
            
            return MENU

    async def analysis_sentiment_callback(self, update: Update, context: CallbackContext) -> int:
        """Handle sentiment analysis selection"""
        query = update.callback_query
        await query.answer()
        
        # Toon een bericht dat deze functie nog niet beschikbaar is
        await query.edit_message_text(
            text="Market sentiment analysis is coming soon!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
            ])
        )
        
        return ANALYSIS

    async def analysis_calendar_callback(self, update: Update, context: CallbackContext) -> int:
        """Handle economic calendar selection"""
        query = update.callback_query
        await query.answer()
        
        # Toon een bericht dat deze functie nog niet beschikbaar is
        await query.edit_message_text(
            text="Economic calendar is coming soon!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
            ])
        )
        
        return ANALYSIS

    async def back_to_menu_callback(self, update: Update, context: CallbackContext) -> int:
        """Handle back to menu selection"""
        query = update.callback_query
        await query.answer()
        
        # Ga terug naar het hoofdmenu
        await query.edit_message_text(
            WELCOME_MESSAGE,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Analyse Market", callback_data="menu_analyse")],
                [InlineKeyboardButton("📊 Trading Signals", callback_data="menu_signals")]
            ]),
            parse_mode=ParseMode.HTML
        )
        
        return MENU

    async def back_to_analysis_callback(self, update: Update, context: CallbackContext) -> int:
        """Handle back to analysis selection"""
        query = update.callback_query
        await query.answer()
        
        # Ga terug naar het analyse menu
        await query.edit_message_text(
            text="Select your analysis type:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 Technical Analysis", callback_data="analysis_technical")],
                [InlineKeyboardButton("🧠 Market Sentiment", callback_data="analysis_sentiment")],
                [InlineKeyboardButton("📅 Economic Calendar", callback_data="analysis_calendar")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
            ])
        )
        
        return ANALYSIS

    async def market_callback(self, update: Update, context: CallbackContext) -> int:
        """Handle market selection"""
        query = update.callback_query
        await query.answer()
        
        # Haal de gekozen markt op
        market = query.data.split("_")[1]
        
        # Sla de markt op in user_data
        context.user_data['market'] = market
        
        # Haal de instrumenten op voor de gekozen markt
        instruments = []
        if market == "forex":
            instruments = [
                ["EURUSD", "GBPUSD", "USDJPY"],
                ["AUDUSD", "USDCAD", "NZDUSD"],
                ["EURGBP", "EURJPY", "GBPJPY"],
                ["USDCHF", "EURAUD", "EURCHF"]
            ]
        elif market == "crypto":
            instruments = [
                ["BTCUSD", "ETHUSD", "XRPUSD"],
                ["SOLUSD", "BNBUSD", "ADAUSD"],
                ["LTCUSD", "DOGUSD", "DOTUSD"],
                ["LNKUSD", "XLMUSD", "AVXUSD"]
            ]
        elif market == "indices":
            instruments = [
                ["US30", "US500", "US100"],
                ["UK100", "DE40", "FR40"],
                ["JP225", "AU200", "HK50"],
                ["EU50"]
            ]
        elif market == "commodities":
            instruments = [
                ["XAUUSD", "WTIUSD"]
            ]
        
        # Maak keyboard met instrumenten
        keyboard = []
        for row in instruments:
            buttons = []
            for instrument in row:
                buttons.append(InlineKeyboardButton(instrument, callback_data=f"instrument_{instrument}"))
            keyboard.append(buttons)
        
        # Voeg terug knop toe
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Update het bericht
        await query.edit_message_text(
            text=f"Select an instrument from {market.capitalize()}:",
            reply_markup=reply_markup
        )
        
        return INSTRUMENT

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel and end the conversation"""
        await update.message.reply_text("Conversation cancelled.")
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
                     f"Timeframe: {context.user_data['timeframe']}",
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

    async def handle_callback_query(self, update: Update, context: CallbackContext) -> None:
        """Handle callback queries"""
        query = update.callback_query
        data = query.data
        
        try:
            # Verwerk de callback query
            if data == "menu_analyse":
                await self.menu_analyse_callback(update, context)
            elif data == "menu_signals":
                await self.menu_signals_callback(update, context)
            elif data.startswith("analysis_"):
                if data == "analysis_technical":
                    await self.analysis_technical_callback(update, context)
                elif data == "analysis_sentiment":
                    await self.analysis_sentiment_callback(update, context)
                elif data == "analysis_calendar":
                    await self.analysis_calendar_callback(update, context)
            elif data == "back_menu":
                await self.back_to_menu_callback(update, context)
            elif data == "back_analysis":
                await self.back_to_analysis_callback(update, context)
            elif data.startswith("market_"):
                await self.market_callback(update, context)
            else:
                await query.answer("Unknown action")
        except Exception as e:
            logger.error(f"Error handling callback query: {str(e)}")
            await query.answer(f"Error: {str(e)}")

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
                    text=f"🧠 <b>Market Sentiment Analysis for {instrument}</b>\n\n{sentiment_data}",
                    parse_mode=ParseMode.HTML,
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
            
            # Log voor debugging
            logger.info(f"Handling chart button for instrument: {instrument}")
            
            # Normaliseer instrument (verwijder /)
            instrument = instrument.upper().replace("/", "")
            
            # Get chart image
            logger.info(f"Getting chart for instrument: {instrument}")
            chart_image = await self.chart.get_chart(instrument)
            
            if not chart_image:
                logger.error(f"Failed to get chart for {instrument}")
                await callback_query.edit_message_text(
                    text=f"Sorry, could not generate chart for {instrument}. Please try again later.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data=f"back_to_signal_{instrument}")
                    ]])
                )
                return
            
            logger.info(f"Successfully got chart for {instrument}, size: {len(chart_image)} bytes")
            
            # Determine back button callback data
            if 'signal' in callback_query.message.text.lower():
                back_callback = f"back_to_signal_{instrument}"
            else:
                back_callback = f"back_to_instruments_{instrument}"
            
            # Update message with chart image
            logger.info(f"Sending chart for {instrument} to user")
            await callback_query.edit_message_media(
                media=InputMediaPhoto(
                    media=chart_image,
                    caption=f"📊 Technical Analysis for {instrument}"
                ),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data=back_callback)
                ]])
            )
            logger.info(f"Chart for {instrument} sent successfully")
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

    async def process_update(self, update_data: Dict[str, Any]) -> None:
        """Process update from webhook"""
        try:
            logger.info(f"Processing update: {update_data}")
            
            # Controleer direct op /start commando
            if 'message' in update_data and 'text' in update_data['message'] and update_data['message']['text'] == '/start':
                logger.info("Detected /start command, handling directly")
                
                # Haal chat_id op
                chat_id = update_data['message']['chat']['id']
                
                # Stuur welkomstbericht direct via de bot
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=WELCOME_MESSAGE,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔍 Analyse Market", callback_data="menu_analyse")],
                        [InlineKeyboardButton("📊 Trading Signals", callback_data="menu_signals")]
                    ]),
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Direct welcome message sent to chat {chat_id}")
                return
            
            # Controleer direct op callback query's
            if 'callback_query' in update_data:
                logger.info("Detected callback query, handling directly")
                callback_data = update_data['callback_query']['data']
                chat_id = update_data['callback_query']['message']['chat']['id']
                message_id = update_data['callback_query']['message']['message_id']
                
                # Bevestig de callback query
                await self.bot.answer_callback_query(update_data['callback_query']['id'])
                
                # Verwerk de verschillende callback data types
                if callback_data == "menu_analyse":
                    logger.info("Handling menu_analyse callback")
                    # Definieer de keyboard direct in de methode
                    analysis_keyboard = [
                        [InlineKeyboardButton("📈 Technical Analysis", callback_data="analysis_technical")],
                        [InlineKeyboardButton("🧠 Market Sentiment", callback_data="analysis_sentiment")],
                        [InlineKeyboardButton("📅 Economic Calendar", callback_data="analysis_calendar")],
                        [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
                    ]
                    
                    # Toon de analyse opties met inline keyboard
                    await self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="Selecteer je analyse type:",
                        reply_markup=InlineKeyboardMarkup(analysis_keyboard)
                    )
                    logger.info("Sent analysis options")
                    return
                
                elif callback_data == "menu_signals":
                    logger.info("Handling menu_signals callback")
                    # Toon de signalen opties
                    await self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="Trading signalen komen binnenkort!",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
                        ])
                    )
                    logger.info("Sent signals message")
                    return
                
                elif callback_data == "back_menu":
                    logger.info("Handling back_menu callback")
                    # Ga terug naar het hoofdmenu
                    await self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=WELCOME_MESSAGE,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔍 Analyse Market", callback_data="menu_analyse")],
                            [InlineKeyboardButton("📊 Trading Signals", callback_data="menu_signals")]
                        ]),
                        parse_mode=ParseMode.HTML
                    )
                    logger.info("Sent welcome message (back to menu)")
                    return
                
                # Technical Analysis callback
                elif callback_data == "analysis_technical":
                    logger.info("Handling analysis_technical callback")
                    # Toon de markt selectie
                    market_keyboard = [
                        [InlineKeyboardButton("Forex", callback_data="market_forex")],
                        [InlineKeyboardButton("Crypto", callback_data="market_crypto")],
                        [InlineKeyboardButton("Indices", callback_data="market_indices")],
                        [InlineKeyboardButton("Commodities", callback_data="market_commodities")],
                        [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
                    ]
                    
                    await self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="Selecteer een markt:",
                        reply_markup=InlineKeyboardMarkup(market_keyboard)
                    )
                    logger.info("Sent market selection")
                    return
                
                # Market Sentiment callback
                elif callback_data == "analysis_sentiment":
                    logger.info("Handling analysis_sentiment callback")
                    await self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="Market sentiment analyse komt binnenkort!",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
                        ])
                    )
                    logger.info("Sent sentiment message")
                    return
                
                # Economic Calendar callback
                elif callback_data == "analysis_calendar":
                    logger.info("Handling analysis_calendar callback")
                    await self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="Economische kalender komt binnenkort!",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
                        ])
                    )
                    logger.info("Sent calendar message")
                    return
                
                # Back to analysis menu
                elif callback_data == "back_analysis":
                    logger.info("Handling back_analysis callback")
                    analysis_keyboard = [
                        [InlineKeyboardButton("📈 Technical Analysis", callback_data="analysis_technical")],
                        [InlineKeyboardButton("🧠 Market Sentiment", callback_data="analysis_sentiment")],
                        [InlineKeyboardButton("📅 Economic Calendar", callback_data="analysis_calendar")],
                        [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
                    ]
                    
                    await self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="Selecteer je analyse type:",
                        reply_markup=InlineKeyboardMarkup(analysis_keyboard)
                    )
                    logger.info("Sent analysis options (back)")
                    return
                
                # Market selection callbacks
                elif callback_data.startswith("market_"):
                    logger.info(f"Handling market selection: {callback_data}")
                    market = callback_data.split("_")[1]
                    
                    # Bepaal de instrumenten op basis van de gekozen markt
                    instruments = []
                    if market == "forex":
                        instruments = [
                            ["EURUSD", "GBPUSD", "USDJPY"],
                            ["AUDUSD", "USDCAD", "NZDUSD"],
                            ["EURGBP", "EURJPY", "GBPJPY"],
                            ["USDCHF", "EURAUD", "EURCHF"]
                        ]
                    elif market == "crypto":
                        instruments = [
                            ["BTCUSD", "ETHUSD", "XRPUSD"],
                            ["SOLUSD", "BNBUSD", "ADAUSD"],
                            ["LTCUSD", "DOGUSD", "DOTUSD"],
                            ["LNKUSD", "XLMUSD", "AVXUSD"]
                        ]
                    elif market == "indices":
                        instruments = [
                            ["US30", "US500", "US100"],
                            ["UK100", "DE40", "FR40"],
                            ["JP225", "AU200", "HK50"],
                            ["EU50"]
                        ]
                    elif market == "commodities":
                        instruments = [
                            ["XAUUSD", "WTIUSD"]
                        ]
                    
                    # Maak keyboard met instrumenten
                    keyboard = []
                    for row in instruments:
                        buttons = []
                        for instrument in row:
                            buttons.append(InlineKeyboardButton(instrument, callback_data=f"instrument_{instrument}"))
                        keyboard.append(buttons)
                    
                    # Voeg terug knop toe
                    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")])
                    
                    await self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"Selecteer een instrument uit {market.capitalize()}:",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    logger.info(f"Sent instrument selection for {market}")
                    return
                
                # Instrument selection callbacks
                elif callback_data.startswith("instrument_"):
                    logger.info(f"Handling instrument selection: {callback_data}")
                    instrument = callback_data.split("_")[1]
                    
                    # Toon een "loading" bericht
                    await self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"⏳ Bezig met het genereren van de chart voor {instrument}..."
                    )
                    
                    try:
                        # Probeer de chart te genereren
                        if hasattr(self, 'chart') and self.chart:
                            # Gebruik de directe TradingView link zonder timeframes
                            chart_url = self.chart.chart_links.get(instrument)
                            
                            if chart_url:
                                logger.info(f"Using TradingView link for {instrument}: {chart_url}")
                                
                                # Probeer een screenshot te maken
                                chart_image = await self.chart.get_chart(instrument)
                                
                                if chart_image:
                                    # Stuur de screenshot
                                    await self.bot.send_photo(
                                        chat_id=chat_id,
                                        photo=chart_image,
                                        caption=f"📊 {instrument} Chart",
                                        reply_markup=InlineKeyboardMarkup([
                                            [InlineKeyboardButton("🔗 Open in TradingView", url=chart_url)],
                                            [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
                                        ])
                                    )
                                    
                                    # Update het oorspronkelijke bericht
                                    await self.bot.edit_message_text(
                                        chat_id=chat_id,
                                        message_id=message_id,
                                        text=f"✅ Chart voor {instrument} is gegenereerd."
                                    )
                                else:
                                    # Geen screenshot beschikbaar, stuur alleen de link
                                    await self.bot.edit_message_text(
                                        chat_id=chat_id,
                                        message_id=message_id,
                                        text=f"📊 Chart voor {instrument}:\n\nKon geen screenshot maken, maar je kunt de chart bekijken op TradingView:",
                                        reply_markup=InlineKeyboardMarkup([
                                            [InlineKeyboardButton("🔗 Open in TradingView", url=chart_url)],
                                            [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
                                        ])
                                    )
                            else:
                                # Geen directe link beschikbaar
                                await self.bot.edit_message_text(
                                    chat_id=chat_id,
                                    message_id=message_id,
                                    text=f"❌ Geen TradingView link beschikbaar voor {instrument}",
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
                                    ])
                                )
                        else:
                            # Geen chart service beschikbaar
                            await self.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=message_id,
                                text="❌ Chart service is niet beschikbaar. Probeer het later opnieuw.",
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
                                ])
                            )
                    except Exception as e:
                        logger.error(f"Error handling instrument selection: {str(e)}")
                        await self.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=f"❌ Er is een fout opgetreden: {str(e)}",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
                            ])
                        )
                    return
                
                # Back to market selection
                elif callback_data == "back_market":
                    logger.info("Handling back_market callback")
                    market_keyboard = [
                        [InlineKeyboardButton("Forex", callback_data="market_forex")],
                        [InlineKeyboardButton("Crypto", callback_data="market_crypto")],
                        [InlineKeyboardButton("Indices", callback_data="market_indices")],
                        [InlineKeyboardButton("Commodities", callback_data="market_commodities")],
                        [InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")]
                    ]
                    
                    await self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="Selecteer een markt:",
                        reply_markup=InlineKeyboardMarkup(market_keyboard)
                    )
                    logger.info("Sent market selection (back)")
                    return
            
            # Converteer de update naar een Update object
            update = Update.de_json(update_data, self.bot)
            
            # Verwerk de update
            await self.application.process_update(update)
            
            logger.info("Update successfully processed")
        except Exception as e:
            logger.error(f"Error processing update: {str(e)}")

    async def cmd_batch_charts(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Verbeterde command handler voor het maken van meerdere chart screenshots"""
        try:
            # Stuur een bericht dat we bezig zijn
            message = await update.message.reply_text(
                "🔄 Bezig met het maken van chart screenshots. Dit kan even duren..."
            )
            
            # Haal symbolen en timeframes uit het bericht als die zijn opgegeven
            message_text = update.message.text.strip()
            parts = message_text.split()
            
            symbols = None
            timeframes = None
            
            # Controleer of er parameters zijn opgegeven
            if len(parts) > 1:
                # Format: /charts EURUSD,GBPUSD 1h,4h
                if len(parts) >= 2:
                    symbols_arg = parts[1].strip()
                    if symbols_arg and symbols_arg != "default":
                        symbols = symbols_arg.split(",")
                
                if len(parts) >= 3:
                    timeframes_arg = parts[2].strip()
                    if timeframes_arg and timeframes_arg != "default":
                        timeframes = timeframes_arg.split(",")
            
            # Log de parameters
            logger.info(f"Batch charts command with symbols={symbols}, timeframes={timeframes}")
            
            # Update het bericht
            await message.edit_text(
                f"🔄 Bezig met het maken van screenshots voor "
                f"{', '.join(symbols) if symbols else 'standaard symbolen'} op "
                f"{', '.join(timeframes) if timeframes else 'standaard timeframes'}..."
            )
            
            # Roep de batch capture functie aan
            results = await self.chart.tradingview.batch_capture_charts(
                symbols=symbols,
                timeframes=timeframes
            )
            
            if not results:
                await message.edit_text("❌ Er is een fout opgetreden bij het maken van screenshots.")
                return
            
            # Stuur de screenshots één voor één
            await message.edit_text(f"✅ Screenshots gemaakt voor {len(results)} symbolen!")
            
            for symbol, timeframe_data in results.items():
                for timeframe, screenshot in timeframe_data.items():
                    if screenshot is None:
                        continue
                        
                    # Maak een caption
                    caption = f"📊 {symbol} - {timeframe} Timeframe"
                    
                    try:
                        # Stuur de afbeelding
                        await update.message.reply_photo(
                            photo=screenshot,
                            caption=caption
                        )
                        
                        # Korte pauze om rate limiting te voorkomen
                        await asyncio.sleep(1)
                    except Exception as photo_error:
                        logger.error(f"Error sending photo: {str(photo_error)}")
                        await update.message.reply_text(
                            f"❌ Kon screenshot voor {symbol} - {timeframe} niet versturen: {str(photo_error)}"
                        )
            
        except Exception as e:
            logger.error(f"Error in batch charts command: {str(e)}")
            await update.message.reply_text(f"❌ Er is een fout opgetreden: {str(e)}")

    async def cmd_selenium_charts(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Command handler voor het maken van chart screenshots met Selenium"""
        try:
            # Stuur een bericht dat we bezig zijn
            message = await update.message.reply_text(
                "🔄 Bezig met het maken van chart screenshots via Selenium. Dit kan even duren..."
            )
            
            # Haal symbolen en timeframes uit het bericht als die zijn opgegeven
            message_text = update.message.text.strip()
            parts = message_text.split()
            
            symbols = None
            timeframes = None
            
            # Controleer of er parameters zijn opgegeven
            if len(parts) > 1:
                # Format: /selenium EURUSD,GBPUSD 1h,4h
                if len(parts) >= 2:
                    symbols_arg = parts[1].strip()
                    if symbols_arg and symbols_arg != "default":
                        symbols = symbols_arg.split(",")
                
                if len(parts) >= 3:
                    timeframes_arg = parts[2].strip()
                    if timeframes_arg and timeframes_arg != "default":
                        timeframes = timeframes_arg.split(",")
            
            # Log de parameters
            logger.info(f"Selenium charts command with symbols={symbols}, timeframes={timeframes}")
            
            # Update het bericht
            await message.edit_text(
                f"🔄 Bezig met het maken van screenshots voor "
                f"{', '.join(symbols) if symbols else 'standaard symbolen'} op "
                f"{', '.join(timeframes) if timeframes else 'standaard timeframes'}..."
            )
            
            # Controleer of de Selenium service is geïnitialiseerd
            if not self.chart.tradingview_selenium or not self.chart.tradingview_selenium.is_initialized:
                await message.edit_text("❌ Selenium service is niet geïnitialiseerd. Probeer het later opnieuw.")
                return
            
            # Roep de batch capture functie aan
            results = await self.chart.tradingview_selenium.batch_capture_charts(
                symbols=symbols,
                timeframes=timeframes
            )
            
            if not results:
                await message.edit_text("❌ Er is een fout opgetreden bij het maken van screenshots.")
                return
            
            # Stuur de screenshots één voor één
            await message.edit_text(f"✅ Screenshots gemaakt voor {len(results)} symbolen!")
            
            for symbol, timeframe_data in results.items():
                for timeframe, screenshot in timeframe_data.items():
                    if screenshot is None:
                        continue
                        
                    # Maak een caption
                    caption = f"📊 {symbol} - {timeframe} Timeframe (Selenium)"
                    
                    try:
                        # Stuur de afbeelding
                        await update.message.reply_photo(
                            photo=screenshot,
                            caption=caption
                        )
                        
                        # Korte pauze om rate limiting te voorkomen
                        await asyncio.sleep(1)
                    except Exception as photo_error:
                        logger.error(f"Error sending photo: {str(photo_error)}")
                        await update.message.reply_text(
                            f"❌ Kon screenshot voor {symbol} - {timeframe} niet versturen: {str(photo_error)}"
                        )
            
        except Exception as e:
            logger.error(f"Error in selenium charts command: {str(e)}")
            await update.message.reply_text(f"❌ Er is een fout opgetreden: {str(e)}")

    async def selenium_charts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /selenium_charts command"""
        try:
            logger.info("Selenium charts command received")
            
            # Stuur een bericht dat we bezig zijn
            message = await update.message.reply_text("🔄 Bezig met het maken van charts...")
            
            # Parse de argumenten (symbolen en timeframes)
            symbols = ["EURUSD", "GBPUSD", "BTCUSD", "ETHUSD"]  # Standaard symbolen
            timeframes = ["1h", "4h", "1d"]  # Standaard timeframes
            
            if context.args:
                # Controleer of er argumenten zijn meegegeven
                text = " ".join(context.args)
                parts = text.split("|")
                
                if len(parts) >= 1:
                    symbols_arg = parts[0].strip()
                    if symbols_arg and symbols_arg != "default":
                        symbols = symbols_arg.split(",")
                
                if len(parts) >= 2:
                    timeframes_arg = parts[1].strip()
                    if timeframes_arg and timeframes_arg != "default":
                        timeframes = timeframes_arg.split(",")
            
            # Log de parameters
            logger.info(f"Charts command with symbols={symbols}, timeframes={timeframes}")
            
            # Update het bericht
            await message.edit_text(
                f"🔄 Bezig met het maken van charts voor "
                f"{', '.join(symbols) if symbols else 'standaard symbolen'} op "
                f"{', '.join(timeframes) if timeframes else 'standaard timeframes'}..."
            )
            
            # Gebruik de fallback methode
            results = {}
            for symbol in symbols:
                results[symbol] = {}
                for timeframe in timeframes:
                    try:
                        # Gebruik de fallback methode
                        chart_image = await self.chart.get_chart(symbol, timeframe)
                        if chart_image:
                            results[symbol][timeframe] = chart_image
                        else:
                            results[symbol][timeframe] = None
                    except Exception as chart_error:
                        logger.error(f"Error generating chart for {symbol} {timeframe}: {str(chart_error)}")
                        results[symbol][timeframe] = None
            
            if not any(any(timeframe_data.values()) for timeframe_data in results.values()):
                await message.edit_text("❌ Er is een fout opgetreden bij het maken van charts.")
                return
            
            # Stuur de charts één voor één
            await message.edit_text(f"✅ Charts gemaakt voor {len(results)} symbolen!")
            
            for symbol, timeframe_data in results.items():
                for timeframe, chart_image in timeframe_data.items():
                    if chart_image is None:
                        continue
                        
                    # Maak een caption
                    caption = f"📊 {symbol} - {timeframe} Timeframe (Fallback)"
                    
                    try:
                        # Stuur de afbeelding
                        await update.message.reply_photo(
                            photo=chart_image,
                            caption=caption
                        )
                        
                        # Korte pauze om rate limiting te voorkomen
                        await asyncio.sleep(1)
                    except Exception as photo_error:
                        logger.error(f"Error sending photo: {str(photo_error)}")
                        await update.message.reply_text(
                            f"❌ Kon chart voor {symbol} - {timeframe} niet versturen: {str(photo_error)}"
                        )
            
        except Exception as e:
            logger.error(f"Error in charts command: {str(e)}")
            await update.message.reply_text(f"❌ Er is een fout opgetreden: {str(e)}")

    async def handle_technical_analysis_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle technical analysis callback"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Haal de callback data op
            data = query.data
            parts = data.split(":")
            
            if len(parts) < 3:
                await query.message.reply_text("❌ Ongeldige callback data")
                return
            
            # Haal het instrument en de markt op
            market = parts[1]
            instrument = parts[2]
            
            # Log de aanvraag
            logger.info(f"Technical analysis requested for {market}:{instrument}")
            
            # Stuur een bericht dat we bezig zijn
            message = await query.message.reply_text(
                f"🔄 Bezig met het maken van technische analyse voor {instrument}..."
            )
            
            # Probeer eerst de TradingView service als die beschikbaar is
            if hasattr(self.chart, 'tradingview') and self.chart.tradingview and self.chart.tradingview.is_initialized:
                logger.info(f"Using TradingView service for {instrument}")
                
                # Gebruik de TradingView service voor alle timeframes
                timeframes = ["1h", "4h", "1d"]
                results = {}
                
                for timeframe in timeframes:
                    try:
                        # Bepaal de chart URL
                        chart_url = self.chart.chart_links.get(instrument, f"https://www.tradingview.com/chart/?symbol={instrument}")
                        
                        # Neem screenshot
                        screenshot = await self.chart.tradingview.take_screenshot(chart_url, timeframe)
                        if screenshot:
                            results[timeframe] = screenshot
                    except Exception as chart_error:
                        logger.error(f"Error generating TradingView chart for {instrument} {timeframe}: {str(chart_error)}")
                        results[timeframe] = None
                
                if any(results.values()):
                    # Stuur de charts één voor één
                    await message.edit_text(f"✅ Technische analyse voor {instrument} gereed!")
                    
                    for timeframe, chart_image in results.items():
                        if chart_image is None:
                            continue
                        
                        # Maak een caption
                        caption = f"📊 {instrument} - {timeframe} Timeframe (TradingView)"
                        
                        try:
                            # Stuur de afbeelding
                            await query.message.reply_photo(
                                photo=chart_image,
                                caption=caption
                            )
                            
                            # Korte pauze om rate limiting te voorkomen
                            await asyncio.sleep(1)
                        except Exception as photo_error:
                            logger.error(f"Error sending photo: {str(photo_error)}")
                            await query.message.reply_text(
                                f"❌ Kon chart voor {instrument} - {timeframe} niet versturen: {str(photo_error)}"
                            )
                    
                    return
            
            # Als TradingView niet werkt of geen resultaten geeft, gebruik de fallback methode
            logger.info(f"Using fallback method for {instrument}")
            
            # Gebruik de fallback methode voor alle timeframes
            timeframes = ["1h", "4h", "1d"]
            results = {}
            
            for timeframe in timeframes:
                try:
                    chart_image = await self.chart.get_chart(instrument, timeframe)
                    if chart_image:
                        results[timeframe] = chart_image
                except Exception as chart_error:
                    logger.error(f"Error generating chart for {instrument} {timeframe}: {str(chart_error)}")
                    results[timeframe] = None
            
            if not any(results.values()):
                await message.edit_text(f"❌ Kon geen charts genereren voor {instrument}")
                return
            
            # Stuur de charts één voor één
            await message.edit_text(f"✅ Technische analyse voor {instrument} gereed!")
            
            for timeframe, chart_image in results.items():
                if chart_image is None:
                    continue
                
                # Maak een caption
                caption = f"📊 {instrument} - {timeframe} Timeframe (Fallback)"
                
                try:
                    # Stuur de afbeelding
                    await query.message.reply_photo(
                        photo=chart_image,
                        caption=caption
                    )
                    
                    # Korte pauze om rate limiting te voorkomen
                    await asyncio.sleep(1)
                except Exception as photo_error:
                    logger.error(f"Error sending photo: {str(photo_error)}")
                    await query.message.reply_text(
                        f"❌ Kon chart voor {instrument} - {timeframe} niet versturen: {str(photo_error)}"
                    )
            
        except Exception as e:
            logger.error(f"Error in technical analysis callback: {str(e)}")
            await update.callback_query.message.reply_text(f"❌ Er is een fout opgetreden: {str(e)}")

    async def handle_market_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle market selection callback"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Haal de callback data op
            data = query.data
            parts = data.split(":")
            
            if len(parts) < 2:
                await query.message.reply_text("❌ Ongeldige callback data")
                return
            
            # Haal de markt op
            market = parts[1]
            
            # Maak een keyboard op basis van de geselecteerde markt
            if market == "forex":
                keyboard = [
                    [
                        InlineKeyboardButton("EUR/USD", callback_data=f"technical_analysis:forex:EURUSD"),
                        InlineKeyboardButton("GBP/USD", callback_data=f"technical_analysis:forex:GBPUSD"),
                        InlineKeyboardButton("USD/JPY", callback_data=f"technical_analysis:forex:USDJPY")
                    ],
                    [
                        InlineKeyboardButton("AUD/USD", callback_data=f"technical_analysis:forex:AUDUSD"),
                        InlineKeyboardButton("USD/CAD", callback_data=f"technical_analysis:forex:USDCAD"),
                        InlineKeyboardButton("EUR/GBP", callback_data=f"technical_analysis:forex:EURGBP")
                    ],
                    [
                        InlineKeyboardButton("Terug", callback_data="analysis_menu")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.edit_text("Selecteer een Forex paar voor technische analyse:", reply_markup=reply_markup)
                
            elif market == "crypto":
                keyboard = [
                    [
                        InlineKeyboardButton("BTC/USD", callback_data=f"technical_analysis:crypto:BTCUSD"),
                        InlineKeyboardButton("ETH/USD", callback_data=f"technical_analysis:crypto:ETHUSD"),
                        InlineKeyboardButton("XRP/USD", callback_data=f"technical_analysis:crypto:XRPUSD")
                    ],
                    [
                        InlineKeyboardButton("SOL/USD", callback_data=f"technical_analysis:crypto:SOLUSD"),
                        InlineKeyboardButton("BNB/USD", callback_data=f"technical_analysis:crypto:BNBUSD"),
                        InlineKeyboardButton("ADA/USD", callback_data=f"technical_analysis:crypto:ADAUSD")
                    ],
                    [
                        InlineKeyboardButton("Terug", callback_data="analysis_menu")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.edit_text("Selecteer een Crypto paar voor technische analyse:", reply_markup=reply_markup)
                
            # Voeg andere markten toe zoals indices, commodities, etc.
            
            else:
                await query.message.edit_text(f"❌ Onbekende markt: {market}")
                
        except Exception as e:
            logger.error(f"Error in market callback: {str(e)}")
            await update.callback_query.message.reply_text(f"❌ Er is een fout opgetreden: {str(e)}")

    async def cmd_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /analysis command"""
        try:
            keyboard = [
                [
                    InlineKeyboardButton("Technical Analysis", callback_data="analysis_type:technical")
                ],
                [
                    InlineKeyboardButton("Fundamental Analysis", callback_data="analysis_type:fundamental")
                ],
                [
                    InlineKeyboardButton("Sentiment Analysis", callback_data="analysis_type:sentiment")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Selecteer het type analyse:", reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in analysis command: {str(e)}")
            await update.message.reply_text(f"❌ Er is een fout opgetreden: {str(e)}")

    async def handle_analysis_type_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle analysis type selection callback"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Haal de callback data op
            data = query.data
            parts = data.split(":")
            
            if len(parts) < 2:
                await query.message.reply_text("❌ Ongeldige callback data")
                return
            
            # Haal het type analyse op
            analysis_type = parts[1]
            
            if analysis_type == "technical":
                keyboard = [
                    [
                        InlineKeyboardButton("Forex", callback_data="market:forex"),
                        InlineKeyboardButton("Crypto", callback_data="market:crypto")
                    ],
                    [
                        InlineKeyboardButton("Indices", callback_data="market:indices"),
                        InlineKeyboardButton("Commodities", callback_data="market:commodities")
                    ],
                    [
                        InlineKeyboardButton("Terug", callback_data="main_menu")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.edit_text("Selecteer een markt voor technische analyse:", reply_markup=reply_markup)
                
            # Voeg andere analyse types toe zoals fundamental, sentiment, etc.
            
            else:
                await query.message.edit_text(f"❌ Onbekend analyse type: {analysis_type}")
                
        except Exception as e:
            logger.error(f"Error in analysis type callback: {str(e)}")
            await update.callback_query.message.reply_text(f"❌ Er is een fout opgetreden: {str(e)}")

    async def handle_technical_analysis(self, update: Update, context: CallbackContext):
        """Handle technical analysis command"""
        query = update.callback_query
        data = query.data
        
        # Parse de callback data
        parts = data.split('_')
        if len(parts) < 3:
            await query.answer("Invalid command")
            return
        
        action = parts[1]
        
        if action == "market":
            # Toon de beschikbare markten
            market_keyboard = [
                [InlineKeyboardButton("Forex", callback_data="ta_instrument_forex")],
                [InlineKeyboardButton("Crypto", callback_data="ta_instrument_crypto")],
                [InlineKeyboardButton("Indices", callback_data="ta_instrument_indices")],
                [InlineKeyboardButton("Commodities", callback_data="ta_instrument_commodities")],
                [InlineKeyboardButton("Back", callback_data="ta_main")]
            ]
            
            await query.edit_message_text(
                "Kies een markt:",
                reply_markup=InlineKeyboardMarkup(market_keyboard)
            )
        elif action == "instrument":
            # Toon de beschikbare instrumenten voor de gekozen markt
            market = parts[2]
            
            instruments = []
            if market == "forex":
                instruments = [
                    ["EURUSD", "GBPUSD", "USDJPY"],
                    ["AUDUSD", "USDCAD", "NZDUSD"],
                    ["EURGBP", "EURJPY", "GBPJPY"],
                    ["USDCHF", "EURAUD", "EURCHF"],
                    ["Back"]
                ]
            elif market == "crypto":
                instruments = [
                    ["BTCUSD", "ETHUSD", "XRPUSD"],
                    ["SOLUSD", "BNBUSD", "ADAUSD"],
                    ["LTCUSD", "DOGUSD", "DOTUSD"],
                    ["LNKUSD", "XLMUSD", "AVXUSD"],
                    ["Back"]
                ]
            elif market == "indices":
                instruments = [
                    ["US30", "US500", "US100"],
                    ["UK100", "DE40", "FR40"],
                    ["JP225", "AU200", "HK50"],
                    ["EU50", "Back"]
                ]
            elif market == "commodities":
                instruments = [
                    ["XAUUSD", "WTIUSD", "Back"]
                ]
            
            instrument_keyboard = []
            for row in instruments:
                if row == ["Back"]:
                    instrument_keyboard.append([InlineKeyboardButton("Back", callback_data="ta_market")])
                else:
                    buttons = []
                    for instrument in row:
                        buttons.append(InlineKeyboardButton(instrument, callback_data=f"ta_chart_{instrument}"))
                    instrument_keyboard.append(buttons)
            
            await query.edit_message_text(
                f"Kies een instrument uit {market.capitalize()}:",
                reply_markup=InlineKeyboardMarkup(instrument_keyboard)
            )
        elif action == "chart":
            # Toon de chart voor het gekozen instrument
            instrument = parts[2]
            
            # Toon een "loading" bericht
            await query.edit_message_text(f"Bezig met het genereren van de chart voor {instrument}...")
            
            # Haal de chart op
            try:
                # Haal de chart op met de chart service
                chart_service = self.bot.chart
                
                if chart_service and chart_service.tradingview:
                    # Neem screenshots voor verschillende timeframes
                    timeframes = ["1h", "4h", "1d"]
                    screenshots = {}
                    
                    for timeframe in timeframes:
                        # Bepaal de chart URL met de juiste timeframe
                        chart_url = chart_service.chart_links.get(instrument)
                        if not chart_url:
                            chart_url = f"https://www.tradingview.com/chart/?symbol={instrument}"
                        
                        # Voeg timeframe toe aan de URL als deze er nog niet in zit
                        if "interval=" not in chart_url:
                            # Converteer timeframe naar TradingView formaat
                            interval_map = {
                                "1m": "1", "5m": "5", "15m": "15", "30m": "30",
                                "1h": "60", "2h": "120", "4h": "240",
                                "1d": "D", "1w": "W", "1M": "M"
                            }
                            tv_interval = interval_map.get(timeframe, "D")
                            
                            # Voeg interval parameter toe aan URL
                            if "?" in chart_url:
                                chart_url += f"&interval={tv_interval}"
                            else:
                                chart_url += f"?interval={tv_interval}"
                        
                        # Neem screenshot met de volledige URL
                        screenshot = await chart_service.tradingview.take_screenshot(chart_url)
                        if screenshot:
                            screenshots[timeframe] = screenshot
                    
                    if screenshots:
                        # Stuur de screenshots
                        for timeframe, screenshot in screenshots.items():
                            # Stuur de screenshot
                            await query.message.reply_photo(
                                photo=screenshot,
                                caption=f"{instrument} - {timeframe} timeframe"
                            )
                        
                        # Stuur een bericht met een knop om terug te gaan
                        back_keyboard = [[InlineKeyboardButton("Back", callback_data="ta_market")]]
                        await query.message.reply_text(
                            f"Charts voor {instrument}",
                            reply_markup=InlineKeyboardMarkup(back_keyboard)
                        )
                    else:
                        # Geen screenshots beschikbaar
                        await query.edit_message_text(
                            f"Kon geen chart genereren voor {instrument}. Probeer het later opnieuw.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ta_market")]])
                        )
                else:
                    # Geen chart service beschikbaar
                    await query.edit_message_text(
                        f"Chart service is niet beschikbaar. Probeer het later opnieuw.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ta_market")]])
                    )
            except Exception as e:
                logger.error(f"Error generating chart: {str(e)}")
                await query.edit_message_text(
                    f"Fout bij het genereren van de chart: {str(e)}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="ta_market")]])
                )
        else:
            # Onbekende actie
            await query.answer("Unknown action")

    async def log_user_state(self, update: Update, context: CallbackContext):
        """Log de huidige state van de gebruiker"""
        user_id = update.effective_user.id
        
        # Probeer de huidige conversatie state te krijgen
        current_state = None
        if hasattr(context, 'conversation_states') and context.conversation_states:
            conversation_states = context.conversation_states.get('conversation', {})
            current_state = conversation_states.get((user_id, user_id), None)
        
        # Log de state en user_data
        logger.info(f"User {user_id} - Current state: {current_state}")
        logger.info(f"User {user_id} - User data: {context.user_data}")

    async def check_redis_connection(self, update: Update, context: CallbackContext):
        """Controleer de Redis verbinding"""
        try:
            if hasattr(context.application, 'persistence') and hasattr(context.application.persistence, 'redis'):
                redis_client = context.application.persistence.redis
                if redis_client:
                    redis_ping = redis_client.ping()
                    logger.info(f"Redis ping: {redis_ping}")
                else:
                    logger.warning("Redis client is None")
            else:
                logger.warning("No Redis persistence found")
        except Exception as e:
            logger.error(f"Error checking Redis connection: {str(e)}")

    async def error_handler(self, update: Update, context: CallbackContext):
        """Handle errors in the conversation"""
        logger.error(f"Error handling update: {update}")
        logger.error(f"Error context: {context.error}")
        
        # Stuur een bericht naar de gebruiker
        if update and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Sorry, er is een fout opgetreden. Probeer het opnieuw met /start."
            )
        
        # Reset de conversatie
        return ConversationHandler.END

    async def instrument_callback(self, update: Update, context: CallbackContext) -> int:
        """Handle instrument selection"""
        query = update.callback_query
        await query.answer()
        
        # Haal het gekozen instrument op
        instrument = query.data.split("_")[1]
        
        # Sla het instrument op in user_data
        context.user_data['instrument'] = instrument
        
        # Toon de timeframe opties
        timeframe_keyboard = [
            [InlineKeyboardButton("5 min", callback_data="timeframe_5m")],
            [InlineKeyboardButton("15 min", callback_data="timeframe_15m")],
            [InlineKeyboardButton("1 uur", callback_data="timeframe_1h")],
            [InlineKeyboardButton("4 uur", callback_data="timeframe_4h")],
            [InlineKeyboardButton("1 dag", callback_data="timeframe_1d")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_instrument")]
        ]
        
        await query.edit_message_text(
            text=f"Select a timeframe for {instrument}:",
            reply_markup=InlineKeyboardMarkup(timeframe_keyboard)
        )
        
        return TIMEFRAME

    async def back_to_market_callback(self, update: Update, context: CallbackContext) -> int:
        """Handle back to market selection"""
        query = update.callback_query
        await query.answer()
        
        # Haal de markt op uit user_data
        market = context.user_data.get('market', 'forex')
        
        # Maak keyboard met markten
        keyboard = []
        for m in ["forex", "crypto", "indices", "commodities"]:
            keyboard.append([InlineKeyboardButton(f"{m.capitalize()}", callback_data=f"market_{m}")])
        
        # Voeg terug knop toe
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")])
        
        await query.edit_message_text(
            text="Select a market:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return MARKET

    async def timeframe_callback(self, update: Update, context: CallbackContext) -> int:
        """Handle timeframe selection"""
        query = update.callback_query
        await query.answer()
        
        # Haal de gekozen timeframe op
        timeframe = query.data.split("_")[1]
        
        # Sla de timeframe op in user_data
        context.user_data['timeframe'] = timeframe
        
        # Haal de andere gegevens op uit user_data
        analysis_type = context.user_data.get('analysis_type', 'technical')
        market = context.user_data.get('market', 'forex')
        instrument = context.user_data.get('instrument', 'EURUSD')
        
        # Toon een "loading" bericht
        await query.edit_message_text(f"Bezig met het genereren van de analyse voor {instrument} ({timeframe})...")
        
        try:
            # Genereer de analyse
            if analysis_type == 'technical':
                # Technische analyse
                # Hier zou je de chart service aanroepen om een chart te genereren
                if hasattr(self, 'chart') and self.chart:
                    # Bepaal de chart URL
                    chart_url = self.chart.get_chart_url(instrument, timeframe)
                    
                    # Neem een screenshot
                    screenshot = await self.chart.take_screenshot(chart_url)
                    
                    if screenshot:
                        # Stuur de screenshot
                        await query.message.reply_photo(
                            photo=screenshot,
                            caption=f"Technical analysis for {instrument} ({timeframe})"
                        )
                        
                        # Stuur een bericht met opties
                        keyboard = [
                            [InlineKeyboardButton("➕ Add More", callback_data="add_more")],
                            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
                        ]
                        
                        await query.message.reply_text(
                            "What would you like to do next?",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        
                        return RESULT
                    else:
                        # Geen screenshot beschikbaar
                        await query.edit_message_text(
                            f"Could not generate chart for {instrument} ({timeframe}). Please try again later.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("⬅️ Back", callback_data="back_instrument")]
                            ])
                        )
                        
                        return INSTRUMENT
                else:
                    # Geen chart service beschikbaar
                    await query.edit_message_text(
                        "Chart service is not available. Please try again later.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⬅️ Back", callback_data="back_instrument")]
                        ])
                    )
                    
                    return INSTRUMENT
            else:
                # Andere analyse types
                await query.edit_message_text(
                    f"Analysis type '{analysis_type}' is not implemented yet.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Back", callback_data="back_instrument")]
                    ])
                )
                
                return INSTRUMENT
        except Exception as e:
            logger.error(f"Error generating analysis: {str(e)}")
            
            # Stuur een foutmelding
            await query.edit_message_text(
                f"Error generating analysis: {str(e)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_instrument")]
                ])
            )
            
            return INSTRUMENT

    async def back_to_instrument_callback(self, update: Update, context: CallbackContext) -> int:
        """Handle back to instrument selection"""
        query = update.callback_query
        await query.answer()
        
        # Haal de markt op uit user_data
        market = context.user_data.get('market', 'forex')
        
        # Haal de instrumenten op voor de gekozen markt
        instruments = []
        if market == "forex":
            instruments = [
                ["EURUSD", "GBPUSD", "USDJPY"],
                ["AUDUSD", "USDCAD", "NZDUSD"],
                ["EURGBP", "EURJPY", "GBPJPY"],
                ["USDCHF", "EURAUD", "EURCHF"]
            ]
        elif market == "crypto":
            instruments = [
                ["BTCUSD", "ETHUSD", "XRPUSD"],
                ["SOLUSD", "BNBUSD", "ADAUSD"],
                ["LTCUSD", "DOGUSD", "DOTUSD"],
                ["LNKUSD", "XLMUSD", "AVXUSD"]
            ]
        elif market == "indices":
            instruments = [
                ["US30", "US500", "US100"],
                ["UK100", "DE40", "FR40"],
                ["JP225", "AU200", "HK50"],
                ["EU50"]
            ]
        elif market == "commodities":
            instruments = [
                ["XAUUSD", "WTIUSD"]
            ]
        
        # Maak keyboard met instrumenten
        keyboard = []
        for row in instruments:
            buttons = []
            for instrument in row:
                buttons.append(InlineKeyboardButton(instrument, callback_data=f"instrument_{instrument}"))
            keyboard.append(buttons)
        
        # Voeg terug knop toe
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_market")])
        
        await query.edit_message_text(
            text=f"Select an instrument from {market.capitalize()}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return INSTRUMENT

    async def add_more_callback(self, update: Update, context: CallbackContext) -> int:
        """Handle add more selection"""
        query = update.callback_query
        await query.answer()
        
        # Ga terug naar het analyse menu
        await query.edit_message_text(
            text="Select your analysis type:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 Technical Analysis", callback_data="analysis_technical")],
                [InlineKeyboardButton("🧠 Market Sentiment", callback_data="analysis_sentiment")],
                [InlineKeyboardButton("📅 Economic Calendar", callback_data="analysis_calendar")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_menu")]
            ])
        )
        
        return ANALYSIS
