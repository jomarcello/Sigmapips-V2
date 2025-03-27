from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger(__name__)

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
