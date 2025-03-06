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

# Forex keyboard voor analyse
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
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
]

# Forex keyboard voor signals
FOREX_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("EURUSD", callback_data="instrument_EURUSD_signals"),
        InlineKeyboardButton("GBPUSD", callback_data="instrument_GBPUSD_signals"),
        InlineKeyboardButton("USDJPY", callback_data="instrument_USDJPY_signals")
    ],
    [
        InlineKeyboardButton("AUDUSD", callback_data="instrument_AUDUSD_signals"),
        InlineKeyboardButton("USDCAD", callback_data="instrument_USDCAD_signals"),
        InlineKeyboardButton("EURGBP", callback_data="instrument_EURGBP_signals")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
]

# Crypto keyboard voor analyse
CRYPTO_KEYBOARD = [
    [
        InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD"),
        InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD"),
        InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
]

# Crypto keyboard voor signals
CRYPTO_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("BTCUSD", callback_data="instrument_BTCUSD_signals"),
        InlineKeyboardButton("ETHUSD", callback_data="instrument_ETHUSD_signals"),
        InlineKeyboardButton("XRPUSD", callback_data="instrument_XRPUSD_signals")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
]

# Indices keyboard voor analyse
INDICES_KEYBOARD = [
    [
        InlineKeyboardButton("US30", callback_data="instrument_US30"),
        InlineKeyboardButton("US500", callback_data="instrument_US500"),
        InlineKeyboardButton("US100", callback_data="instrument_US100")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
]

# Indices keyboard voor signals
INDICES_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("US30", callback_data="instrument_US30_signals"),
        InlineKeyboardButton("US500", callback_data="instrument_US500_signals"),
        InlineKeyboardButton("US100", callback_data="instrument_US100_signals")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
]

# Commodities keyboard voor analyse
COMMODITIES_KEYBOARD = [
    [
        InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD"),
        InlineKeyboardButton("XAGUSD", callback_data="instrument_XAGUSD"),
        InlineKeyboardButton("USOIL", callback_data="instrument_USOIL")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
]

# Commodities keyboard voor signals
COMMODITIES_KEYBOARD_SIGNALS = [
    [
        InlineKeyboardButton("XAUUSD", callback_data="instrument_XAUUSD_signals"),
        InlineKeyboardButton("XAGUSD", callback_data="instrument_XAGUSD_signals"),
        InlineKeyboardButton("USOIL", callback_data="instrument_USOIL_signals")
    ],
    [InlineKeyboardButton("⬅️ Terug", callback_data="back_market")]
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

    async def analysis_technical_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle analysis_technical callback"""
        query = update.callback_query
        await query.answer()
        
        # Toon de markt selectie voor technische analyse
        await query.edit_message_text(
            text="Selecteer een markt voor technische analyse:",
            reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
        )
        
        # Sla het analyse type op in user_data
        context.user_data['analysis_type'] = 'technical'
        
        return CHOOSE_MARKET

    async def analysis_sentiment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle analysis_sentiment callback"""
        query = update.callback_query
        await query.answer()
        
        # Toon de markt selectie voor sentiment analyse
        await query.edit_message_text(
            text="Selecteer een markt voor sentiment analyse:",
            reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
        )
        
        # Sla het analyse type op in user_data
        context.user_data['analysis_type'] = 'sentiment'
        
        return CHOOSE_MARKET

    async def analysis_calendar_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle analysis_calendar callback"""
        query = update.callback_query
        await query.answer()
        
        # Toon loading message
        await query.edit_message_text(
            text="⏳ Bezig met het laden van de economische kalender...",
        )
        
        try:
            # Haal kalender data op
            calendar_data = await self.calendar.get_economic_calendar()
            
            # Toon de kalender
            await query.edit_message_text(
                text=calendar_data,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Terug", callback_data="back_analysis")
                ]])
            )
            
            return CHOOSE_ANALYSIS
            
        except Exception as e:
            logger.error(f"Error getting economic calendar: {str(e)}")
            
            # Toon foutmelding
            await query.edit_message_text(
                text="❌ Er is een fout opgetreden bij het ophalen van de economische kalender. Probeer het later opnieuw.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Terug", callback_data="back_analysis")
                ]])
            )
            
            return CHOOSE_ANALYSIS

    async def signals_add_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle signals_add callback"""
        query = update.callback_query
        await query.answer()
        
        # Toon de markt selectie voor signals
        await query.edit_message_text(
            text="Selecteer een markt voor je trading signalen:",
            reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
        )
        
        return CHOOSE_MARKET

    async def signals_manage_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle signals_manage callback"""
        query = update.callback_query
        await query.answer()
        
        # Haal voorkeuren op uit de database
        user_id = update.effective_user.id
        
        try:
            preferences = await self.db.get_user_preferences(user_id)
            
            if not preferences or len(preferences) == 0:
                await query.edit_message_text(
                    text="Je hebt nog geen voorkeuren ingesteld.\n\nGebruik 'Nieuwe Paren Toevoegen' om je eerste trading paar in te stellen.",
                    reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
                )
                return CHOOSE_SIGNALS
            
            # Format preferences text
            prefs_text = "Je huidige voorkeuren:\n\n"
            for i, pref in enumerate(preferences, 1):
                prefs_text += f"{i}. {pref['market']} - {pref['instrument']}\n"
                prefs_text += f"   Stijl: {pref['style']}, Timeframe: {pref['timeframe']}\n\n"
            
            keyboard = [
                [InlineKeyboardButton("➕ Meer Toevoegen", callback_data="signals_add")],
                [InlineKeyboardButton("🗑 Voorkeuren Verwijderen", callback_data="delete_prefs")],
                [InlineKeyboardButton("⬅️ Terug", callback_data="back_signals")]
            ]
            
            await query.edit_message_text(
                text=prefs_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logger.error(f"Error getting preferences: {str(e)}")
            await query.edit_message_text(
                text="Er is een fout opgetreden bij het ophalen van je voorkeuren. Probeer het later opnieuw.",
                reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
            )
        
        return CHOOSE_SIGNALS

    async def market_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle market selection for analysis"""
        query = update.callback_query
        await query.answer()
        
        # Haal de markt op uit de callback data
        market = query.data.replace('market_', '')
        
        # Sla de markt op in user_data
        context.user_data['market'] = market
        
        # Bepaal welke keyboard te tonen op basis van de markt
        keyboard_map = {
            'forex': FOREX_KEYBOARD,
            'crypto': CRYPTO_KEYBOARD,
            'indices': INDICES_KEYBOARD,
            'commodities': COMMODITIES_KEYBOARD
        }
        
        keyboard = keyboard_map.get(market, FOREX_KEYBOARD)
        
        # Toon de instrumenten voor de gekozen markt
        await query.edit_message_text(
            text=f"Selecteer een instrument uit {market.capitalize()}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CHOOSE_INSTRUMENT

    async def market_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle market selection for signals"""
        query = update.callback_query
        await query.answer()
        
        # Haal de markt op uit de callback data
        market = query.data.replace('market_', '').replace('_signals', '')
        
        # Sla de markt op in user_data
        context.user_data['market'] = market
        
        # Bepaal welke keyboard te tonen op basis van de markt
        keyboard_map = {
            'forex': FOREX_KEYBOARD_SIGNALS,
            'crypto': CRYPTO_KEYBOARD_SIGNALS,
            'indices': INDICES_KEYBOARD_SIGNALS,
            'commodities': COMMODITIES_KEYBOARD_SIGNALS
        }
        
        keyboard = keyboard_map.get(market, FOREX_KEYBOARD_SIGNALS)
        
        # Toon de instrumenten voor de gekozen markt
        await query.edit_message_text(
            text=f"Selecteer een instrument uit {market.capitalize()}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CHOOSE_INSTRUMENT

    async def instrument_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle instrument selection for analysis"""
        query = update.callback_query
        await query.answer()
        
        # Haal het instrument op uit de callback data
        instrument = query.data.replace('instrument_', '')
        
        # Sla het instrument op in user_data
        context.user_data['instrument'] = instrument
        
        # Haal het analyse type op uit user_data
        analysis_type = context.user_data.get('analysis_type', 'technical')
        
        if analysis_type == 'technical':
            # Toon loading message
            await query.edit_message_text(
                text=f"⏳ Bezig met het genereren van technische analyse voor {instrument}..."
            )
            
            try:
                # Genereer chart voor verschillende timeframes
                timeframes = ["1h", "4h", "1d"]
                charts = {}
                
                for timeframe in timeframes:
                    chart = await self.chart.get_chart(instrument, timeframe)
                    if chart:
                        charts[timeframe] = chart
                
                if charts:
                    # Stuur de charts één voor één
                    await query.edit_message_text(
                        text=f"✅ Technische analyse voor {instrument} gereed!",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Terug", callback_data="back_market")
                        ]])
                    )
                    
                    for timeframe, chart in charts.items():
                        caption = f"📊 {instrument} - {timeframe} Timeframe"
                        await query.message.reply_photo(
                            photo=chart,
                            caption=caption
                        )
                    
                    return CHOOSE_MARKET
                else:
                    # Geen charts beschikbaar
                    await query.edit_message_text(
                        text=f"❌ Kon geen charts genereren voor {instrument}. Probeer het later opnieuw.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Terug", callback_data="back_market")
                        ]])
                    )
                    return CHOOSE_MARKET
                    
            except Exception as e:
                logger.error(f"Error generating technical analysis: {str(e)}")
                await query.edit_message_text(
                    text=f"❌ Er is een fout opgetreden bij het genereren van technische analyse voor {instrument}. Probeer het later opnieuw.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Terug", callback_data="back_market")
                    ]])
                )
                return CHOOSE_MARKET
                
        elif analysis_type == 'sentiment':
            # Toon loading message
            await query.edit_message_text(
                text=f"⏳ Bezig met het ophalen van sentiment data voor {instrument}..."
            )
            
            try:
                # Haal sentiment data op
                sentiment_data = await self.sentiment.get_market_sentiment(instrument)
                
                # Toon de sentiment data
                await query.edit_message_text(
                    text=sentiment_data,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Terug", callback_data="back_market")
                    ]])
                )
                
                return CHOOSE_MARKET
                
            except Exception as e:
                logger.error(f"Error getting sentiment data: {str(e)}")
                await query.edit_message_text(
                    text=f"❌ Er is een fout opgetreden bij het ophalen van sentiment data voor {instrument}. Probeer het later opnieuw.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Terug", callback_data="back_market")
                    ]])
                )
                return CHOOSE_MARKET
        
        # Default: ga naar style selectie voor signals
        await query.edit_message_text(
            text="Selecteer je trading stijl:",
            reply_markup=InlineKeyboardMarkup(STYLE_KEYBOARD)
        )
        
        return CHOOSE_STYLE

    async def instrument_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle instrument selection for signals"""
        query = update.callback_query
        await query.answer()
        
        # Haal het instrument op uit de callback data
        instrument = query.data.replace('instrument_', '').replace('_signals', '')
        
        # Sla het instrument op in user_data
        context.user_data['instrument'] = instrument
        
        # Toon de style selectie
        await query.edit_message_text(
            text="Selecteer je trading stijl:",
            reply_markup=InlineKeyboardMarkup(STYLE_KEYBOARD)
        )
        
        return CHOOSE_STYLE

    async def style_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle style selection"""
        query = update.callback_query
        await query.answer()
        
        # Haal de stijl op uit de callback data
        style = query.data.split('_')[1]  # style_test -> test
        
        # Sla de stijl op in user_data
        context.user_data['style'] = style
        context.user_data['timeframe'] = STYLE_TIMEFRAME_MAP[style]
        
        # Sla de voorkeur op in de database
        user_id = update.effective_user.id
        
        try:
            # Haal de markt en het instrument op uit user_data
            market = context.user_data.get('market', 'forex')
            instrument = context.user_data.get('instrument', 'EURUSD')
            
            # Controleer of deze combinatie al bestaat
            preferences = await self.db.get_user_preferences(user_id)
            
            for pref in preferences:
                if (pref['market'] == market and 
                    pref['instrument'] == instrument and 
                    pref['style'] == style):
                    
                    # Deze combinatie bestaat al
                    await query.edit_message_text(
                        text=f"Je hebt deze combinatie al opgeslagen!\n\n"
                             f"Markt: {market}\n"
                             f"Instrument: {instrument}\n"
                             f"Stijl: {style} ({STYLE_TIMEFRAME_MAP[style]})",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("➕ Meer Toevoegen", callback_data="signals_add")],
                            [InlineKeyboardButton("⚙️ Beheer Voorkeuren", callback_data="signals_manage")],
                            [InlineKeyboardButton("🏠 Terug naar Start", callback_data="back_menu")]
                        ])
                    )
                    return SHOW_RESULT
            
            # Sla de nieuwe voorkeur op
            await self.db.save_preference(
                user_id=user_id,
                market=market,
                instrument=instrument,
                style=style,
                timeframe=STYLE_TIMEFRAME_MAP[style]
            )
            
            # Show success message with options
            await query.edit_message_text(
                text=f"✅ Je voorkeuren zijn succesvol opgeslagen!\n\n"
                     f"Markt: {market}\n"
                     f"Instrument: {instrument}\n"
                     f"Stijl: {style} ({STYLE_TIMEFRAME_MAP[style]})",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Meer Toevoegen", callback_data="signals_add")],
                    [InlineKeyboardButton("⚙️ Beheer Voorkeuren", callback_data="signals_manage")],
                    [InlineKeyboardButton("🏠 Terug naar Start", callback_data="back_menu")]
                ])
            )
            logger.info(f"Saved preferences for user {user_id}")
            return SHOW_RESULT
            
        except Exception as e:
            logger.error(f"Error saving preferences: {str(e)}")
            await query.edit_message_text(
                text="❌ Fout bij het opslaan van voorkeuren. Probeer het opnieuw.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Probeer Opnieuw", callback_data="back_signals")]
                ])
            )
            return CHOOSE_SIGNALS

    async def back_to_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to menu"""
        query = update.callback_query
        await query.answer()
        
        # Reset user_data
        context.user_data.clear()
        
        # Toon het hoofdmenu
        await query.edit_message_text(
            text=WELCOME_MESSAGE,
            reply_markup=InlineKeyboardMarkup(START_KEYBOARD),
            parse_mode=ParseMode.HTML
        )
        
        return MENU

    async def back_to_analysis_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to analysis menu"""
        query = update.callback_query
        await query.answer()
        
        # Toon het analyse menu
        await query.edit_message_text(
            text="Selecteer je analyse type:",
            reply_markup=InlineKeyboardMarkup(ANALYSIS_KEYBOARD)
        )
        
        return CHOOSE_ANALYSIS

    async def back_to_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to signals menu"""
        query = update.callback_query
        await query.answer()
        
        # Toon het signals menu
        await query.edit_message_text(
            text="Wat wil je doen met trading signalen?",
            reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
        )
        
        return CHOOSE_SIGNALS

    async def back_to_market_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to market selection"""
        query = update.callback_query
        await query.answer()
        
        # Haal het analyse type op uit user_data
        analysis_type = context.user_data.get('analysis_type', 'technical')
        
        if analysis_type in ['technical', 'sentiment']:
            # Toon de markt selectie voor analyse
            await query.edit_message_text(
                text=f"Selecteer een markt voor {analysis_type} analyse:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD)
            )
        else:
            # Toon de markt selectie voor signals
            await query.edit_message_text(
                text="Selecteer een markt voor je trading signalen:",
                reply_markup=InlineKeyboardMarkup(MARKET_KEYBOARD_SIGNALS)
            )
        
        return CHOOSE_MARKET

    async def back_to_instrument(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle back to instrument selection"""
        query = update.callback_query
        await query.answer()
        
        # Haal de markt op uit user_data
        market = context.user_data.get('market', 'forex')
        
        # Bepaal welke keyboard te tonen op basis van de markt
        keyboard_map = {
            'forex': FOREX_KEYBOARD,
            'crypto': CRYPTO_KEYBOARD,
            'indices': INDICES_KEYBOARD,
            'commodities': COMMODITIES_KEYBOARD
        }
        
        keyboard = keyboard_map.get(market, FOREX_KEYBOARD)
        
        # Voeg _signals toe aan de callback data als we in signals flow zitten
        if context.user_data.get('analysis_type') != 'technical':
            for row in keyboard:
                for button in row:
                    if button.callback_data.startswith('instrument_'):
                        button.callback_data = f"{button.callback_data}_signals"
        
        # Toon de instrumenten voor de gekozen markt
        await query.edit_message_text(
            text=f"Selecteer een instrument uit {market.capitalize()}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CHOOSE_INSTRUMENT

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

    async def initialize(self):
        """Initialize the Telegram bot asynchronously."""
        try:
            # Get bot info
            info = await self.bot.get_me()
            logger.info(f"Successfully connected to Telegram API. Bot info: {info}")
            
            # Set bot commands
            commands = [
                ("start", "Start de bot en toon hoofdmenu"),
                ("help", "Toon help bericht")
            ]
            await self.bot.set_my_commands(commands)
            
            # Start the bot
            await self.application.initialize()
            await self.application.start()
            
            # Start polling
            await self.application.updater.start_polling()
            logger.info("Telegram bot initialized and started polling.")
        except Exception as e:
            logger.error(f"Error during Telegram bot initialization: {str(e)}")
            raise

    async def set_webhook(self, webhook_url: str):
        """Set the Telegram bot webhook URL."""
        try:
            # Verwijder eerst eventuele bestaande webhook
            await self.bot.delete_webhook()
            
            # Stel de nieuwe webhook in
            await self.bot.set_webhook(url=webhook_url)
            
            # Haal webhook info op om te controleren
            webhook_info = await self.bot.get_webhook_info()
            
            logger.info(f"Webhook succesvol ingesteld op: {webhook_url}")
            logger.info(f"Webhook info: {webhook_info}")
        except Exception as e:
            logger.error(f"Fout bij het instellen van de webhook: {str(e)}")
            raise
