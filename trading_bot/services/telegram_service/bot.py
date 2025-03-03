import os
from telegram import Bot, Application, ConversationHandler, CommandHandler, CallbackQueryHandler, Update, InlineKeyboardMarkup
from trading_bot.services.telegram_service.bot import CHOOSE_MENU, CHOOSE_ANALYSIS, CHOOSE_MARKET, CHOOSE_INSTRUMENT, CHOOSE_SIGNALS
from trading_bot.services.database.database import Database
from trading_bot.services.chart_service import ChartService
from trading_bot.services.market_sentiment_service import MarketSentimentService
from trading_bot.services.economic_calendar_service import EconomicCalendarService
from trading_bot.utils.logger import logger
from telegram.ext import ContextTypes

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
                    CHOOSE_MARKET: [
                        CallbackQueryHandler(self.market_choice, pattern="^market_"),
                        CallbackQueryHandler(self.back_to_analysis, pattern="^back$")
                    ],
                    CHOOSE_INSTRUMENT: [
                        CallbackQueryHandler(self.instrument_choice, pattern="^instrument_"),
                        CallbackQueryHandler(self.back_to_market, pattern="^back$")
                    ]
                },
                fallbacks=[CallbackQueryHandler(self.cancel, pattern="^cancel$")]
            )
            
            # Add handlers in deze volgorde
            self.application.add_handler(conv_handler)
            self.application.add_handler(CommandHandler("help", self.help))
            self.application.add_handler(CallbackQueryHandler(self._button_click))  # Belangrijk!
            
            logger.info("Telegram service initialized")
            
        except Exception as e:
            logger.error(f"Error initializing Telegram service: {str(e)}")
            raise

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
                return CHOOSE_ANALYSIS
            
            elif choice == 'signals':
                await query.edit_message_text(
                    text="What would you like to do with trading signals?",
                    reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                )
                return CHOOSE_SIGNALS
            
            return CHOOSE_MENU
            
        except Exception as e:
            logger.error(f"Error in menu choice: {str(e)}")
            await query.edit_message_text(
                text="Sorry, something went wrong. Please use /start to begin again.",
                reply_markup=None
            )
            return ConversationHandler.END
