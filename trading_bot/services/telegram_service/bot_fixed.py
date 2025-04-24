#!/usr/bin/env python3
# This is a fixed version of the bot.py file
# The indentation around line 3833 has been fixed

# Instructions to replace the original file:
# 1. Make a backup of the original file: cp trading_bot/services/telegram_service/bot.py trading_bot/services/telegram_service/bot.py.bak
# 2. Replace the original file with this fixed version: cp trading_bot/services/telegram_service/bot_fixed.py trading_bot/services/telegram_service/bot.py

# The fixed section:
"""
                    except Exception as caption_e:
                        logger.error(f"Error editing message caption: {str(caption_e)}")
                        try:
                            await query.message.reply_text(
                                text="Unknown button pressed. Returning to main menu.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]])
                            )
                        except Exception as reply_e:
                            logger.error(f"Error sending reply message: {str(reply_e)}")
                else:
                    logger.error(f"Error in button_callback default handling: {str(e)}")
                    try:
                        await query.message.reply_text(
                            text="Unknown button pressed. Returning to main menu.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]])
                        )
                    except Exception as reply_e:
                        logger.error(f"Error sending reply message: {str(reply_e)}")
""" 
