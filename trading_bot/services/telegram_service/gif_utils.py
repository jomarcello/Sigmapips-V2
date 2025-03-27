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
    return "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExaDlteTY3dHl2bjdlN3RlMDRwMTV4bjV6c3dlczQzMmQ1NHlncHUzNiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/zqKzzCRDhMsvGuxhfS/giphy.gif"

async def get_analyse_gif():
    """Get the analysis GIF URL."""
    # Gebruik de nieuwe Giphy URL
    return "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExaDlteTY3dHl2bjdlN3RlMDRwMTV4bjV6c3dlczQzMmQ1NHlncHUzNiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/zqKzzCRDhMsvGuxhfS/giphy.gif"

async def get_signals_gif():
    """Get the signals GIF URL."""
    # Gebruik de nieuwe Giphy URL
    return "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExaDlteTY3dHl2bjdlN3RlMDRwMTV4bjV6c3dlczQzMmQ1NHlncHUzNiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/zqKzzCRDhMsvGuxhfS/giphy.gif"

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
        # GIF URL voor bovenaan het welkomstbericht
        gif_url = "https://i.imgur.com/bSwVALm.gif"
        
        # Stuur de GIF animatie
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
        # GIF URL voor bovenaan het menubericht
        gif_url = "https://i.imgur.com/bSwVALm.gif"
        
        # Stuur de GIF animatie
        await bot.send_animation(
            chat_id=chat_id,
            animation=gif_url,
            caption=caption or "📊 <b>SigmaPips AI Menu</b>",
            parse_mode=ParseMode.HTML
        )
        return True
    except Exception as e:
        logger.error(f"Error sending menu GIF: {str(e)}")
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
        gif_url = "https://i.imgur.com/bSwVALm.gif"
        
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
