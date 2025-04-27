bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher(bot)

# Initialize services
# ... existing code ...

# Function to show market selection
async def show_market_selection(chat_id: int, instrument: str, message_id: int = None):
    logger.debug(f"Showing market selection for {instrument} in chat {chat_id}")
    keyboard = InlineKeyboardMarkup(row_width=2)
    markets = get_markets_for_instrument(instrument)

    if not markets:
        await bot.send_message(chat_id, f"No supported markets found for {instrument}. Please choose another instrument.")
        # Optionally, resend the instrument selection menu
        await show_instrument_selection(chat_id)
        return

    buttons = [InlineKeyboardButton(market.upper(), callback_data=f"select_market_{instrument}_{market}") for market in markets]
    keyboard.add(*buttons)
    keyboard.add(InlineKeyboardButton("🔙 Back to Instruments", callback_data="back_to_instruments"))

    text = f"Please select the market for <b>{instrument}</b>:"
    if message_id:
        await bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    else:
        await bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

# Function to show actions after market selection (No Timeframe anymore)
async def show_actions_menu(chat_id: int, instrument: str, market: str, message_id: int = None):
    logger.debug(f"Showing actions for {instrument} ({market}) in chat {chat_id} - Timeframe is fixed H1")
    keyboard = InlineKeyboardMarkup(row_width=2)
    # Removed timeframe button
    buttons = [
        InlineKeyboardButton("📈 Analyze Market (H1)", callback_data=f"analyze_{instrument}_{market}"),
        InlineKeyboardButton("📰 Latest News", callback_data=f"news_{instrument}_{market}"),
        InlineKeyboardButton("💡 Trading Idea", callback_data=f"idea_{instrument}"),
        # InlineKeyboardButton("🔔 Set Alert", callback_data=f"alert_{instrument}_{market}") # Alert functionality placeholder
    ]
    keyboard.add(*buttons)
    # Back button now goes to market selection for this instrument
    keyboard.add(InlineKeyboardButton(f"🔙 Back to Markets ({instrument})", callback_data=f"back_to_markets_{instrument}"))

    text = f"""Selected: <b>{instrument}</b> on <b>{market.upper()}</b> market.
Timeframe is fixed to <b>H1</b>.

What would you like to do?"""

    if message_id:
        await bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    else:
        await bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


# --- Callback Query Handlers ---

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('select_instrument_'))
async def handle_instrument_selection(callback_query: CallbackQuery):
    instrument = callback_query.data.split('_')[2]
    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id
    logger.info(f"User {chat_id} selected instrument: {instrument}")
    await bot.answer_callback_query(callback_query.id)
    # Directly show market selection, skipping timeframe
    await show_market_selection(chat_id, instrument, message_id)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('select_market_'))
async def handle_market_selection(callback_query: CallbackQuery):
    parts = callback_query.data.split('_')
    instrument = parts[2]
    market = parts[3]
    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id
    logger.info(f"User {chat_id} selected market: {market} for instrument: {instrument}")
    await bot.answer_callback_query(callback_query.id)
    # Show actions directly, no timeframe selection needed
    await show_actions_menu(chat_id, instrument, market, message_id)

# Timeframe selection is removed
# @dp.callback_query_handler(lambda c: c.data and c.data.startswith('select_timeframe_'))
# async def handle_timeframe_selection(callback_query: CallbackQuery):
#    parts = callback_query.data.split('_')
#    instrument = parts[2]
#    market = parts[3]
#    timeframe = parts[4]
#    chat_id = callback_query.message.chat.id
#    message_id = callback_query.message.message_id
#    logger.info(f"User {chat_id} selected timeframe: {timeframe} for {instrument} ({market})")
#    await bot.answer_callback_query(callback_query.id)
#    # Now show the final actions menu
#    await show_actions_menu(chat_id, instrument, market, timeframe, message_id)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('analyze_'))
async def handle_analyze_market(callback_query: CallbackQuery):
    parts = callback_query.data.split('_')
    instrument = parts[1]
    market = parts[2]
    # Timeframe is removed, always H1
    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id
    logger.info(f"User {chat_id} requested analysis for {instrument} ({market}) - Fixed Timeframe: H1")
    await bot.answer_callback_query(callback_query.id, text=f"📊 Analyzing {instrument} (H1)...")

    # Delete the previous message (menu)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.warning(f"Could not delete previous message {message_id} in chat {chat_id}: {e}")

    # Send placeholder message
    placeholder_message = await bot.send_message(chat_id, f"⏳ Generating H1 analysis for {instrument}...", parse_mode=ParseMode.HTML)

    try:
        # 1. Get Technical Analysis (no timeframe needed)
        analysis_text = await chart_service.get_technical_analysis(instrument)

        # 2. Get Chart (no timeframe needed)
        chart_image = await chart_service.get_chart(instrument)

        # Prepare back button specific to the MENU flow
        keyboard_menu_flow = InlineKeyboardMarkup().add(
            InlineKeyboardButton("🔙 Back to Actions", callback_data=f"back_to_actions_{instrument}_{market}")
        )

        if chart_image:
            caption = analysis_text
            # Send chart with analysis as caption
            await bot.send_photo(
                chat_id,
                photo=InputFile(BytesIO(chart_image), filename=f'{instrument}_H1_chart.png'),
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard_menu_flow # Back button for menu flow
            )
            logger.info(f"Sent chart and analysis for {instrument} (H1) to chat {chat_id}")
        else:
            # Send only analysis text if chart failed
            await bot.send_message(
                chat_id,
                analysis_text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard_menu_flow # Back button for menu flow
            )
            logger.warning(f"Sent only analysis for {instrument} (H1) to chat {chat_id} as chart generation failed.")

        # Delete the placeholder message
        await bot.delete_message(chat_id, placeholder_message.message_id)

    except Exception as e:
        logger.error(f"Error during analysis for {instrument} (H1): {e}", exc_info=True)
        await bot.edit_message_text(f"❌ Error generating analysis for {instrument} (H1). Please try again later.", chat_id, placeholder_message.message_id)
        # Also add a back button here in case of error
        keyboard_error = InlineKeyboardMarkup().add(
            InlineKeyboardButton("🔙 Back to Actions", callback_data=f"back_to_actions_{instrument}_{market}")
        )
        await bot.edit_message_reply_markup(chat_id, placeholder_message.message_id, reply_markup=keyboard_error)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith('signal_analyze_'))
async def handle_analyze_market_from_signal(callback_query: CallbackQuery):
    """Handles the 'Analyze Market' button press coming directly from a signal alert."""
    parts = callback_query.data.split('_')
    instrument = parts[2]
    # Market and timeframe are determined by the signal context (market might not be needed if instrument is unique like EURUSD, timeframe fixed H1)
    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id
    logger.info(f"[Signal Flow] User {chat_id} requested analysis for signal instrument: {instrument} - Fixed Timeframe: H1")

    # Answer callback quickly
    await bot.answer_callback_query(callback_query.id, text=f"📊 Analyzing {instrument} (H1) from signal...")

    # Edit the original signal message to show loading state
    try:
        original_message_text = callback_query.message.text or callback_query.message.caption
        await bot.edit_message_text(f"{original_message_text}\n\n⏳ _Generating H1 analysis..._",
                                    chat_id, message_id, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning(f"[Signal Flow] Could not edit original signal message {message_id} in chat {chat_id}: {e}")
        # If editing fails, send a new placeholder message
        placeholder_message = await bot.send_message(chat_id, f"⏳ Generating H1 analysis for {instrument}...", parse_mode=ParseMode.HTML)
        message_id_to_delete = placeholder_message.message_id # Need to delete this new message later
    else:
        message_id_to_delete = None # Will edit the original message further

    try:
        # 1. Get Technical Analysis (no timeframe needed)
        # Instrument might need normalization depending on the signal source format
        normalized_instrument = instrument.upper().replace("/", "") # Basic normalization
        analysis_text = await chart_service.get_technical_analysis(normalized_instrument)

        # 2. Get Chart (no timeframe needed)
        chart_image = await chart_service.get_chart(normalized_instrument)

        # IMPORTANT: NO back button for the signal flow analysis result
        # The user is not in the menu flow here.
        keyboard_signal_flow = None # No keyboard markup

        if chart_image:
            caption = analysis_text
            # Send a NEW message with the chart and analysis
            # We don't edit the original signal message with the image, send as new.
            await bot.send_photo(
                chat_id,
                photo=InputFile(BytesIO(chart_image), filename=f'{normalized_instrument}_H1_chart.png'),
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard_signal_flow # No back button for signal flow
            )
            logger.info(f"[Signal Flow] Sent chart and analysis for {normalized_instrument} (H1) to chat {chat_id}")
        else:
            # Send analysis text as a NEW message if chart failed
            await bot.send_message(
                chat_id,
                analysis_text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard_signal_flow # No back button for signal flow
            )
            logger.warning(f"[Signal Flow] Sent only analysis for {normalized_instrument} (H1) to chat {chat_id} as chart generation failed.")

        # Clean up placeholder/loading state
        if message_id_to_delete:
            await bot.delete_message(chat_id, message_id_to_delete)
        else:
            # Edit the original message back (remove loading state, keep original text/buttons)
            # Or maybe just delete the loading part? Or leave it?
            # Let's try removing the loading text added earlier.
             await bot.edit_message_text(original_message_text, chat_id, message_id, reply_markup=callback_query.message.reply_markup) # Restore original markup

    except Exception as e:
        logger.error(f"[Signal Flow] Error during analysis for {normalized_instrument} (H1): {e}", exc_info=True)
        error_text = f"❌ Error generating H1 analysis for {normalized_instrument} from signal."
        if message_id_to_delete:
             await bot.edit_message_text(error_text, chat_id, message_id_to_delete)
        else:
             # Edit original message to show error, keep original markup
             await bot.edit_message_text(f"{original_message_text}\n\n{error_text}",
                                     chat_id, message_id, reply_markup=callback_query.message.reply_markup)
        # Alternatively, send a new error message:
        # await bot.send_message(chat_id, error_text)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith('news_'))
# ... existing code ...

@dp.callback_query_handler(lambda c: c.data == 'back_to_instruments')
async def handle_back_to_instruments(callback_query: CallbackQuery):
    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id
    logger.debug(f"User {chat_id} going back to instrument selection")
    await bot.answer_callback_query(callback_query.id)
    await show_instrument_selection(chat_id, message_id)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('back_to_markets_'))
async def handle_back_to_markets(callback_query: CallbackQuery):
    instrument = callback_query.data.split('_')[3]
    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id
    logger.debug(f"User {chat_id} going back to market selection for {instrument}")
    await bot.answer_callback_query(callback_query.id)
    await show_market_selection(chat_id, instrument, message_id)

# Removed back_to_timeframes handler

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('back_to_actions_'))
async def handle_back_to_actions(callback_query: CallbackQuery):
    parts = callback_query.data.split('_')
    instrument = parts[3]
    market = parts[4]
    # Timeframe is removed
    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id
    logger.debug(f"User {chat_id} going back to actions for {instrument} ({market})")
    await bot.answer_callback_query(callback_query.id)
    # Delete the analysis/chart message before showing the menu again
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.warning(f"Could not delete analysis message {message_id} in chat {chat_id} when going back: {e}")
    # Show the actions menu again (no timeframe needed)
    await show_actions_menu(chat_id, instrument, market) # Send as new message

# --- Signal Handling --- (Example of how a signal might trigger analysis)
async def send_signal_alert(chat_id: int, instrument: str, signal_type: str, price: float, source: str):
    """Sends a signal alert message with an 'Analyze Market' button."""
    logger.info(f"Sending signal alert for {instrument} ({signal_type} at {price}) from {source} to chat {chat_id}")
    # Timeframe is implicitly H1 now
    text = (
        f"🚨 **Signal Alert** 🚨\n\n"
        f"**Instrument:** {instrument}\n"
        f"**Type:** {signal_type}\n"
        f"**Price:** {price}\n"
        f"**Timeframe:** H1 (Fixed)\n"
        f"**Source:** {source}\n\n"
        f"Click below to analyze the H1 chart and technicals."
    )
    # Button specifically for the signal flow
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("📊 Analyze Market (H1)", callback_data=f"signal_analyze_{instrument}")
    )
    try:
        await bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        logger.info(f"Successfully sent signal alert for {instrument} to {chat_id}")
    except Exception as e:
        logger.error(f"Failed to send signal alert to {chat_id} for {instrument}: {e}")

# --- Main Execution ---
# ... existing code ... 
