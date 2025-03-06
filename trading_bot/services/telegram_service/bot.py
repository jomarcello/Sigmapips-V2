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

async def market_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle market selection for signals"""
    query = update.callback_query
    await query.answer()
    
    # Haal de markt op uit de callback data
    market = query.data.split('_')[1]  # market_forex_signals -> forex
    
    # Sla de markt op in user_data
    context.user_data['market'] = market
    context.user_data['analysis_type'] = 'signals'
    
    # Bepaal welke keyboard te tonen op basis van market
    keyboard_map = {
        'forex': FOREX_KEYBOARD,
        'crypto': CRYPTO_KEYBOARD,
        'commodities': COMMODITIES_KEYBOARD,
        'indices': INDICES_KEYBOARD
    }
    
    keyboard = keyboard_map.get(market, FOREX_KEYBOARD)
    
    # Pas de callback data aan voor signals
    for row in keyboard:
        for button in row:
            if "Back" not in button.text:
                button.callback_data = f"instrument_{button.text}_signals"
    
    # Voeg terug knop toe
    for row in keyboard:
        for button in row:
            if "Back" in button.text:
                button.callback_data = "back_signals"
    
    await query.edit_message_text(
        text=f"Selecteer een instrument uit {market.capitalize()}:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return CHOOSE_INSTRUMENT

async def instrument_signals_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle instrument selection for signals"""
    query = update.callback_query
    await query.answer()
    
    # Haal het instrument op uit de callback data
    parts = query.data.split('_')
    instrument = parts[1]  # instrument_EURUSD_signals -> EURUSD
    
    # Sla het instrument op in user_data
    context.user_data['instrument'] = instrument
    
    # Toon de stijl selectie
    await query.edit_message_text(
        text=f"Selecteer je trading stijl voor {instrument}:",
        reply_markup=InlineKeyboardMarkup(STYLE_KEYBOARD)
    )
    
    return CHOOSE_STYLE

async def style_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle style selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_instrument":
        # Terug naar instrument keuze
        market = context.user_data.get('market', 'forex')
        keyboard_map = {
            'forex': FOREX_KEYBOARD,
            'crypto': CRYPTO_KEYBOARD,
            'commodities': COMMODITIES_KEYBOARD,
            'indices': INDICES_KEYBOARD
        }
        keyboard = keyboard_map.get(market, FOREX_KEYBOARD)
        
        # Pas de callback data aan voor signals
        for row in keyboard:
            for button in row:
                if "Back" not in button.text:
                    button.callback_data = f"instrument_{button.text}_signals"
        
        # Voeg terug knop toe
        for row in keyboard:
            for button in row:
                if "Back" in button.text:
                    button.callback_data = "back_signals"
        
        await query.edit_message_text(
            text=f"Selecteer een instrument uit {market.capitalize()}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSE_INSTRUMENT
    
    style = query.data.replace('style_', '')
    context.user_data['style'] = style
    context.user_data['timeframe'] = STYLE_TIMEFRAME_MAP[style]
    
    try:
        # Save preferences
        user_id = update.effective_user.id
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

async def back_to_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle back to signals menu"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        text="Wat wil je doen met trading signalen?",
        reply_markup=InlineKeyboardMarkup(SIGNALS_KEYBOARD)
    )
    
    return CHOOSE_SIGNALS

# Update de ConversationHandler om de nieuwe handlers toe te voegen
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", self.start_command)],
    states={
        MENU: [
            CallbackQueryHandler(self.menu_analyse_callback, pattern="^menu_analyse$"),
            CallbackQueryHandler(self.menu_signals_callback, pattern="^menu_signals$"),
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
            CallbackQueryHandler(self.back_to_signals, pattern="^back_signals$"),
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
        # ... andere states ...
    },
    fallbacks=[CommandHandler("help", self.help_command)],
    name="my_conversation",
    persistent=False,
    per_message=False,
) 
