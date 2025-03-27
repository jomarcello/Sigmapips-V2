from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger(__name__)

# Nieuwe functies voor het ophalen van GIF URLs
async def get_welcome_gif():
    """Get the welcome GIF URL."""
    # Gebruik een constante URL voor de welkomst GIF
    return "https://i.ibb.co/bzhvz2v/welcome.gif"

async def get_menu_gif():
    """Get the menu GIF URL."""
    # Gebruik een constante URL voor de menu GIF
    return "https://i.ibb.co/bzhvz2v/welcome.gif"

async def get_analyse_gif():
    """Get the analysis GIF URL."""
    # Gebruik een constante URL voor de analyse GIF
    return "https://i.ibb.co/bzhvz2v/welcome.gif"

async def get_signals_gif():
    """Get the signals GIF URL."""
    # Gebruik een constante URL voor de signalen GIF
    return "https://i.ibb.co/bzhvz2v/welcome.gif"

# Oude functies voor backward compatibility
async def send_welcome_gif(bot, chat_id, caption=None):
    """Send a welcome GIF to the user."""
    try:
        # GIF URL voor bovenaan het welkomstbericht
        gif_url = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExdW40bzUzanIzeXJka3Fxc2U0eGtrenhwOGY3ajA4Z2pxZXRndjZleiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/JtBZm3Getg3dqxK0zP/giphy.gif"
        
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
        gif_url = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExcXZuZWx0ZXc5Zjlvb2t3cXJjbWR2bHR6OHdsMHBzaHozaGY5emU3cyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/qgQUggAC3Pfv687qPC/giphy.gif"
        
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
        gif_url = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExeTRnM3QzNHJxbzk0dHVudzh5MjZlenh6MHYwZ2Z5aGRibGhvNmo0biZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/JWuBH9rCO2uZuHBFpm/giphy.gif"
        
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
        gif_url = "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExb2gyN2huY2txNnh5OXBuYzlhcHVjdHFiOWU0MWx0MmlxbWthZnBibiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/l4FGr7tRgmSJFiQFO/giphy.gif"
        
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
