from fastapi import FastAPI, Request
import asyncio
import logging
import os
import sys

# Add the current directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Create a FastAPI app - don't try to import from trading_bot.main
app = FastAPI()

logger = logging.getLogger(__name__)

# Global telegram service reference
telegram_service = None

# Basic health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for Railway's healthcheck."""
    return {"status": "ok", "message": "Bot is running"}

# Webhook endpoint - this is the critical part that was missing
@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle Telegram webhook requests."""
    global telegram_service
    
    if not telegram_service or not telegram_service.application:
        logger.error("Telegram service not initialized, can't process webhook")
        return {"success": False, "error": "Telegram service not initialized"}
    
    try:
        # Get the update data from request
        update_data = await request.json()
        
        # Log the update
        update_id = update_data.get('update_id')
        logger.info(f"Received webhook update: {update_id}")
        
        # Process the update through telegram
        from telegram import Update
        update = Update.de_json(update_data, telegram_service.bot)
        await telegram_service.application.process_update(update)
        
        logger.info(f"Successfully processed update {update_id}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}

# Import the bot and run it
@app.on_event("startup")
async def startup_event():
    """Start the bot when the FastAPI app starts."""
    global telegram_service
    
    try:
        # Direct implementation to start the bot without importing main
        logger.info("Starting bot directly within asgi.py")
        
        # Import required modules
        from trading_bot.services.telegram_service.bot import TelegramService
        from trading_bot.services.database.db import Database
        from trading_bot.services.payment_service.stripe_service import StripeService
        
        # Create and start services
        async def start_bot():
            global telegram_service
            
            # Initialize database
            db = Database()
            logger.info("Database initialized")
            
            # Initialize Stripe service
            stripe_service = StripeService(db)
            logger.info("Stripe service initialized")
            
            # Initialize Telegram service with database and Stripe service
            telegram_service = TelegramService(db, stripe_service, lazy_init=True)
            logger.info("Telegram service initialized")
            
            # Controleer of we in Railway draaien en stel webhook in indien nodig
            railway_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
            if railway_url:
                webhook_url = f"https://{railway_url}"
                logger.info(f"Detected Railway environment, setting webhook URL to: {webhook_url}")
                # In Railway omgeving, webhook instellingen overschrijven voor betere compatibiliteit
                telegram_service.webhook_url = webhook_url
            
            # Initialize bot - but don't use telegram_service.run() as it creates its own app
            # Instead, set up the webhook explicitly
            webhook_url = f"{telegram_service.webhook_url}/webhook"
            logger.info(f"Setting webhook URL to: {webhook_url}")
            
            # Initialize the application
            await telegram_service.application.initialize()
            await telegram_service.application.start()
            
            # Set the webhook
            await telegram_service.bot.delete_webhook()  # Delete existing webhook
            await telegram_service.bot.set_webhook(url=webhook_url)
            
            # Set the commands
            from telegram import BotCommand
            commands = [
                BotCommand("start", "Start the bot and get the welcome message"),
                BotCommand("menu", "Show the main menu"),
                BotCommand("help", "Show available commands and how to use the bot")
            ]
            await telegram_service.bot.set_my_commands(commands)
            logger.info("Bot commands set")
            
            # Verify webhook was set
            webhook_info = await telegram_service.bot.get_webhook_info()
            logger.info(f"Webhook set to: {webhook_info.url}")
            logger.info(f"Pending updates: {webhook_info.pending_update_count}")
            
            # Bot is now ready to process updates
            logger.info("Bot started successfully")
            
            # Keep the task running to prevent garbage collection
            while True:
                await asyncio.sleep(60)
        
        # Start in background
        asyncio.create_task(start_bot())
        logger.info("Bot startup task created")
        
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        logger.exception(e) 
