from telegram import Bot, Update, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger(__name__)

# Nieuwe functies voor het ophalen van GIF URLs
async def get_welcome_gif():
    """Get the welcome GIF URL."""
    # Use the new Giphy URL
    return "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExaWVkdzcxZHMydm8ybnBjYW9rNjd3b2gzeng2b3BhMjA0d3p5dDV1ZSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/gSzIKNrqtotEYrZv7i/giphy.gif"

async def get_menu_gif():
    """Get the menu GIF URL."""
    # Gebruik de nieuwe Giphy URL
    return "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExaWVkdzcxZHMydm8ybnBjYW9rNjd3b2gzeng2b3BhMjA0d3p5dDV1ZSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/gSzIKNrqtotEYrZv7i/giphy.gif"

async def get_analyse_gif():
    """Get the analysis GIF URL."""
    # Gebruik de nieuwe Giphy URL
    return "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExaWVkdzcxZHMydm8ybnBjYW9rNjd3b2gzeng2b3BhMjA0d3p5dDV1ZSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/gSzIKNrqtotEYrZv7i/giphy.gif"

async def get_signals_gif():
    """Get the signals GIF URL."""
    # Gebruik de nieuwe Giphy URL
    return "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExaWVkdzcxZHMydm8ybnBjYW9rNjd3b2gzeng2b3BhMjA0d3p5dDV1ZSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/gSzIKNrqtotEYrZv7i/giphy.gif"

# Nieuwe functie voor het verzenden van een GIF met caption en keyboard
async def send_gif_with_caption(update: Update, gif_url: str, caption: str, reply_markup=None, parse_mode=ParseMode.HTML):
    """
    Send a GIF with caption and optional keyboard.
    
    Args:
        update: Telegram Update object
        gif_url: URL of the GIF to send
        caption: Text caption to show with the GIF
        reply_markup: Optional keyboard markup
        parse_mode: Parse mode for the caption text
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Verzend de GIF met caption en keyboard
        await update.message.reply_animation(
            animation=gif_url,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
        return True
    except Exception as e:
        logger.error(f"Error sending GIF with caption: {str(e)}")
        
        # Fallback: stuur alleen text als GIF faalt
        try:
            await update.message.reply_text(
                text=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
            return True
        except Exception as e2:
            logger.error(f"Fallback failed too: {str(e2)}")
            return False

# Oude functies voor backward compatibility
async def send_welcome_gif(bot, chat_id, caption=None):
    """Send a welcome GIF to the user."""
    try:
        # Use the new welcome GIF URL
        gif_url = "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExaWVkdzcxZHMydm8ybnBjYW9rNjd3b2gzeng2b3BhMjA0d3p5dDV1ZSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/gSzIKNrqtotEYrZv7i/giphy.gif"
        
        # Send the GIF animation
        await bot.send_animation(
            chat_id=chat_id,
            animation=gif_url,
            caption=caption or "🤖 <b>SigmaPips AI is Ready!</b>",
            parse_mode=ParseMode.HTML
        )
        return True
    except Exception as e:
        logger.error(f"Error sending welcome GIF: {str(e)}")
        return False

async def send_menu_gif(bot, chat_id, caption=None):
    """Send a menu message to the user (without GIF)."""
    try:
        # Send only the text without GIF
        await bot.send_message(
            chat_id=chat_id,
            text=caption or "📊 <b>SigmaPips AI Menu</b>",
            parse_mode=ParseMode.HTML
        )
        return True
    except Exception as e:
        logger.error(f"Error sending menu message: {str(e)}")
        return False

async def send_analyse_gif(bot, chat_id, caption=None):
    """Send an analysis GIF to the user."""
    try:
        # GIF URL voor bovenaan het analysebericht
        gif_url = "https://i.imgur.com/bSwVALm.gif"
        
        # Stuur de GIF animatie
        await bot.send_animation(
            chat_id=chat_id,
            animation=gif_url,
            caption=caption or "📈 <b>SigmaPips AI Analysis</b>",
            parse_mode=ParseMode.HTML
        )
        return True
    except Exception as e:
        logger.error(f"Error sending analyse GIF: {str(e)}")
        return False

async def send_signals_gif(bot, chat_id, caption=None):
    """Send a signals GIF to the user."""
    try:
        # GIF URL voor bovenaan het signalenbericht
        gif_url = "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExaWVkdzcxZHMydm8ybnBjYW9rNjd3b2gzeng2b3BhMjA0d3p5dDV1ZSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/gSzIKNrqtotEYrZv7i/giphy.gif"
        
        # Stuur de GIF animatie
        await bot.send_animation(
            chat_id=chat_id,
            animation=gif_url,
            caption=caption or "🎯 <b>SigmaPips AI Signals</b>",
            parse_mode=ParseMode.HTML
        )
        return True
    except Exception as e:
        logger.error(f"Error sending signals GIF: {str(e)}")
        return False

async def send_loading_gif(bot, chat_id, caption=None):
    """Send a loading GIF to the user."""
    try:
        # Loading GIF URL
        gif_url = "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExZDlnaXk2NnNtc2toOHhvc3IzNXJvbWQ1YWR3and3aHJoeWF6dDE2dSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/dpjUltnOPye7azvAhH/giphy.gif"
        
        # Send the loading GIF animation
        await bot.send_animation(
            chat_id=chat_id,
            animation=gif_url,
            caption=caption or "⏳ <b>Analyzing...</b>",
            parse_mode=ParseMode.HTML
        )
        return True
    except Exception as e:
        logger.error(f"Error sending loading GIF: {str(e)}")
        return False

async def get_loading_gif():
    """Get the loading GIF URL."""
    return "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExZDlnaXk2NnNtc2toOHhvc3IzNXJvbWQ1YWR3and3aHJoeWF6dDE2dSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/dpjUltnOPye7azvAhH/giphy.gif"

async def embed_gif_in_text(gif_url: str, text: str) -> str:
    """
    Embed a GIF URL in text using the HTML invisible character trick.
    This allows GIFs to be displayed in edit_message_text calls.
    
    Args:
        gif_url: URL of the GIF to embed
        text: Text to display below the GIF
        
    Returns:
        Formatted text with embedded GIF URL
    """
    return f'<a href="{gif_url}">&#8205;</a>\n{text}'

async def update_message_with_gif(query: 'CallbackQuery', gif_url: str, text: str, 
                              reply_markup=None, parse_mode=ParseMode.HTML) -> bool:
    """
    Update an existing message with a GIF and new text.
    Uses the invisible character HTML trick to embed the GIF.
    
    Args:
        query: The callback query containing the message to update
        gif_url: URL of the GIF to embed
        text: Text to display below the GIF
        reply_markup: Optional keyboard markup
        parse_mode: Parse mode for the text
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create the message with the GIF using inline HTML
        formatted_text = await embed_gif_in_text(gif_url, text)
        
        # First try to update the message text
        try:
            await query.edit_message_text(
                text=formatted_text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
            return True
        except Exception as text_error:
            # Check if the error is about no text to edit
            if "There is no text in the message to edit" in str(text_error):
                # Message likely has a caption instead - try to edit the caption
                logger.info("Message has no text, trying to edit caption instead")
                await query.edit_message_caption(
                    caption=text,  # Use plain text for caption, not the formatted text with GIF
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                return True
            else:
                # Re-raise if it's some other error
                raise
    except Exception as e:
        logger.error(f"Failed to update message with GIF: {str(e)}")
        
        # Fallback: try both caption and text approaches
        try:
            # First try caption
            try:
                await query.edit_message_caption(
                    caption=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                return True
            except Exception as caption_error:
                # If caption fails, try text
                await query.edit_message_text(
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                return True
        except Exception as e2:
            logger.error(f"Fallback update failed too: {str(e2)}")
            return False
