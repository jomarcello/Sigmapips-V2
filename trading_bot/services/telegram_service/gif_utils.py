"""
Test module om te demonstreren hoe je GIFs kunt sturen in Telegram.
Dit is een standalone module die je kunt gebruiken om te testen.
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

# URL van de GIF die we willen gebruiken
GIF_URL = "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExaDlteTY3dHl2bjdlN3RlMDRwMTV4bjV6c3dlczQzMmQ1NHlncHUzNiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/zqKzzCRDhMsvGuxhfS/giphy.gif"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler voor het /start commando.
    Dit stuurt een GIF met een bijschrift naar de gebruiker.
    """
    # Tekst voor het bijschrift
    caption = """
🚀 <b>Welcome to Sigmapips AI!</b> 🚀

<b>Discover powerful trading signals for various markets:</b>
• <b>Forex</b> - Major and minor currency pairs
• <b>Crypto</b> - Bitcoin, Ethereum and other top cryptocurrencies

<b>Features:</b>
✅ Real-time trading signals
✅ Advanced chart analysis
    """
    
    # Knoppen toevoegen
    keyboard = [
        [InlineKeyboardButton("🔥 Start Trial", callback_data="trial")]
    ]
    
    # GIF verzenden met bijschrift en knoppen
    await update.message.reply_animation(
        animation=GIF_URL,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def main() -> None:
    """Start de bot."""
    # Vul hier je bot token in
    application = Application.builder().token("YOUR_BOT_TOKEN").build()

    # Commando handlers toevoegen
    application.add_handler(CommandHandler("start", start))

    # Start de bot
    application.run_polling()

if __name__ == "__main__":
    main() 
