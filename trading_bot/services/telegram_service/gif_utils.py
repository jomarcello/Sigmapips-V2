from telegram import Bot, Update, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger(__name__)

# Nieuwe functies voor het ophalen van GIF URLs
async def get_welcome_gif():
    """Get the welcome GIF URL."""
    # SigmaPips welcome GIF in zwart met logo
    return "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"

async def get_menu_gif():
    """Get the menu GIF URL."""
    # SigmaPips welcome GIF in zwart met logo
    return "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"

async def get_analyse_gif():
    """Get the analysis GIF URL."""
    # SigmaPips analyse GIF in zwart met logo
    return "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"

async def get_signals_gif():
    """Get the signals GIF URL."""
    # SigmaPips signals GIF in zwart met logo
    return "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"

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
        gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
        
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
    """Send a menu GIF to the user."""
    try:
        # Use the welcome GIF URL for menu as well
        gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
        
        # Send the GIF animation
        await bot.send_animation(
            chat_id=chat_id,
            animation=gif_url,
            caption=caption or "📊 <b>SigmaPips AI Menu</b>",
            parse_mode=ParseMode.HTML
        )
        return True
    except Exception as e:
        logger.error(f"Error sending menu GIF: {str(e)}")
        # Fallback to text
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=caption or "📊 <b>SigmaPips AI Menu</b>",
                parse_mode=ParseMode.HTML
            )
            return True
        except Exception:
            return False

async def send_analyse_gif(bot, chat_id, caption=None):
    """Send an analysis GIF to the user."""
    try:
        # Use the analyse GIF URL 
        gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
        
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
        # Use the signals GIF URL
        gif_url = "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif"
        
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
        # Get the loading GIF URL from the dedicated function to ensure consistency
        gif_url = await get_loading_gif()
        
        # Explicitly use send_animation to ensure it's treated as a GIF
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
    # Using a specialized loading animation GIF - clean spinning loader with subtle animation
    return "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"

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
        # Check if the message already has the exact content we're trying to set
        # to avoid "Message is not modified" errors
        current_text = query.message.text or ""
        current_caption = query.message.caption or ""
        
        # Create the message with the GIF using inline HTML
        formatted_text = await embed_gif_in_text(gif_url, text)
        
        # If current content matches what we're setting, no need to update
        if (current_text == formatted_text or current_caption == text) and query.message.reply_markup == reply_markup:
            logger.info("Message content already matches the desired content, skipping update")
            return True
            
        # First try to update the message text if the message has text
        if query.message.text is not None:
            try:
                await query.edit_message_text(
                    text=formatted_text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                return True
            except Exception as text_error:
                # If the error is "Message is not modified", just return success
                if "Message is not modified" in str(text_error):
                    logger.info("Message is already in the desired state")
                    return True
                elif "There is no text in the message to edit" in str(text_error):
                    # Message likely has a caption instead - try to edit the caption
                    logger.info("Message has no text, trying to edit caption instead")
                else:
                    # For other errors, log and try fallback
                    logger.warning(f"Text update error: {str(text_error)}")
                
                # Try to edit the caption
                try:
                    await query.edit_message_caption(
                        caption=text,  # Use plain text for caption
                        parse_mode=parse_mode,
                        reply_markup=reply_markup
                    )
                    return True
                except Exception as caption_error:
                    if "Message is not modified" in str(caption_error):
                        logger.info("Caption is already in the desired state")
                        return True
                    else:
                        # Re-raise if it's some other error
                        raise caption_error
        else:
            # Message has no text, try caption
            try:
                await query.edit_message_caption(
                    caption=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                return True
            except Exception as caption_error:
                if "Message is not modified" in str(caption_error):
                    logger.info("Caption is already in the desired state")
                    return True
                elif "Bad Request: Message caption is empty" in str(caption_error):
                    # Try to use the text approach as fallback
                    await query.edit_message_text(
                        text=formatted_text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup
                    )
                    return True
                else:
                    raise caption_error
    except Exception as e:
        logger.error(f"Failed to update message with GIF: {str(e)}")
        
        # Fallback: try to use InputMediaAnimation to edit the media itself
        try:
            from telegram import InputMediaAnimation
            # Try to update the media directly
            await query.edit_message_media(
                media=InputMediaAnimation(
                    media=gif_url,
                    caption=text,
                    parse_mode=parse_mode
                ),
                reply_markup=reply_markup
            )
            return True
        except Exception as media_error:
            if "Message is not modified" in str(media_error):
                logger.info("Media is already in the desired state")
                return True
            
            logger.error(f"Media update fallback failed: {str(media_error)}")
            
            # As a last resort, try to send a new message if everything else fails
            try:
                await query.message.reply_text(
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                logger.warning("Sent a new message instead of updating the existing one")
                return True
            except Exception as final_error:
                logger.error(f"Final fallback failed: {str(final_error)}")
                return False

# List of GIF URLs for use in various parts of the app
ANALYSIS_GIFS = [
    "https://media.giphy.com/media/gSzIKNrqtotEYrZv7i/giphy.gif",
    "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"
]
