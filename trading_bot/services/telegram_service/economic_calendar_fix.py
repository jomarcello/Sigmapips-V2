async def show_economic_calendar(self, update: Update, context=None, instrument: str = None) -> int:
    """Show economic calendar for a specific instrument"""
    query = update.callback_query
    
    try:
        # Show loading message with GIF
        from trading_bot.services.telegram_service.gif_utils import send_loading_gif
        await send_loading_gif(
            self.bot,
            update.effective_chat.id,
            caption=f"⏳ <b>Loading economic calendar for {instrument}...</b>"
        )
        
        # Check if we're coming from a signal
        is_from_signal = False
        if context and hasattr(context, 'user_data'):
            # We need to check ALL signal-related flags
            is_really_from_signal = all([
                context.user_data.get('from_signal', False) or context.user_data.get('previous_state') == 'SIGNAL',
                context.user_data.get('in_signal_flow', False)
            ])
            # Only if we're REALLY from a signal, use the signal back button
            is_from_signal = is_really_from_signal
            
            # Debug log
            logger.info(f"show_economic_calendar - is_from_signal: {is_from_signal}")
        
        # Show loading message
        await query.edit_message_text(
            text=f"Fetching economic calendar for {instrument}. Please wait..."
        )
        
        try:
            # Get calendar by currency/instrument
            calendar_data = None
            
            # First, try to get currency-specific calendar if we have an instrument
            if instrument:
                # Extract currency code from the instrument
                currencies = self._extract_currency_codes(instrument)
                
                if currencies:
                    # Get calendar data with currency filter
                    logger.info(f"Getting calendar for currencies: {currencies}")
                    calendar_data = await self.calendar.get_economic_calendar(currencies=currencies)
            
            # If no data found or no instrument specified, get the general calendar
            if not calendar_data:
                logger.info("Getting general economic calendar")
                calendar_data = await self.calendar.get_economic_calendar()
                
            # Make sure we have calendar data
            if not calendar_data or calendar_data.strip() == "":
                calendar_data = "No economic events found for the selected period."
                
            # Show calendar with back button - dynamic based on where we came from
            back_button = "back_to_signal" if is_from_signal else "back_to_signal_analysis"
            
            await query.edit_message_text(
                text=calendar_data,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data=back_button)
                ]]),
                parse_mode=ParseMode.HTML
            )
            
            return SHOW_RESULT
                
        except Exception as calendar_error:
            logger.error(f"Error getting calendar: {str(calendar_error)}")
            logger.exception(calendar_error)
            
            # Show error message with back button
            await query.edit_message_text(
                text="Sorry, there was a problem retrieving the economic calendar. Please try again later.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal" if is_from_signal else "back_to_signal_analysis")
                ]])
            )
            
            return MENU
                
    except Exception as e:
        logger.error(f"Error in show_economic_calendar: {str(e)}")
        logger.exception(e)
        
        # Attempt to recover
        try:
            await query.edit_message_text(
                text="An error occurred. Please try again.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="back_to_signal_analysis")
                ]])
            )
        except Exception:
            pass
            
        return MENU 
