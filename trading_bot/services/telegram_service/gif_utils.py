from telegram import Bot, Update, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger(__name__)

# Functions for retrieving GIF URLs
async def get_welcome_gif():
    """Get the welcome GIF URL."""
    # Use the Giphy URL
    return "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExaDlteTY3dHl2bjdlN3RlMDRwMTV4bjV6c3dlczQzMmQ1NHlncHUzNiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/zqKzzCRDhMsvGuxhfS/giphy.gif"

async def get_menu_gif():
    """Get the menu GIF URL."""
    # Use the Giphy URL
    return "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExaDlteTY3dHl2bjdlN3RlMDRwMTV4bjV6c3dlczQzMmQ1NHlncHUzNiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/zqKzzCRDhMsvGuxhfS/giphy.gif"

async def get_analyse_gif():
    """Get the analysis GIF URL."""
    # Use the Giphy URL
    return "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExaDlteTY3dHl2bjdlN3RlMDRwMTV4bjV6c3dlczQzMmQ1NHlncHUzNiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/zqKzzCRDhMsvGuxhfS/giphy.gif"

async def get_signals_gif():
    """Get the signals GIF URL."""
    # Use the Giphy URL
    return "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExaDlteTY3dHl2bjdlN3RlMDRwMTV4bjV6c3dlczQzMmQ1NHlncHUzNiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/zqKzzCRDhMsvGuxhfS/giphy.gif"

# Function for sending a GIF with caption and keyboard
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
        # Send the GIF with caption and keyboard
        await update.message.reply_animation(
            animation=gif_url,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
        return True
    except Exception as e:
        logger.error(f"Error sending GIF with caption: {str(e)}")
        
        # Fallback: only send text if GIF fails
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

# Old functions for backward compatibility
async def send_welcome_gif(bot, chat_id, caption=None):
    """Send a welcome GIF to the user."""
    try:
        # GIF URL for welcome message
        gif_url = "https://i.imgur.com/bSwVALm.gif"
        
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
        # GIF URL for menu message
        gif_url = "https://i.imgur.com/bSwVALm.gif"
        
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
        return False

async def send_analyse_gif(bot, chat_id, caption=None):
    """Send an analysis GIF to the user."""
    try:
        # GIF URL for analysis message
        gif_url = "https://i.imgur.com/bSwVALm.gif"
        
        # Send the GIF animation
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
        # GIF URL for signals message
        gif_url = "https://i.imgur.com/bSwVALm.gif"
        
        # Send the GIF animation
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
