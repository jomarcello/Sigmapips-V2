from fastapi import FastAPI, Request
import asyncio
import logging
import os
import sys
import time
import traceback

# Configure logging to be more verbose
logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG for more detailed logs
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add the current directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Create a FastAPI app - don't try to import from trading_bot.main
app = FastAPI()

logger = logging.getLogger(__name__)

# Global telegram service reference
telegram_service = None
initialization_complete = False

# Basic health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for Railway's healthcheck."""
    global initialization_complete
    
    if initialization_complete:
        return {"status": "ok", "message": "Bot is running"}
    else:
        return {"status": "initializing", "message": "Bot is starting up"}

# Webhook endpoint - this is the critical part that was missing
@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle Telegram webhook requests."""
    global telegram_service, initialization_complete
    
    if not initialization_complete or not telegram_service or not telegram_service.application:
        logger.error("Telegram service not initialized, can't process webhook")
        return {"success": False, "error": "Telegram service not initialized"}
    
    try:
        # Get the update data from request
        update_data = await request.json()
        
        # Log the update
        update_id = update_data.get('update_id')
        logger.info(f"Received webhook update: {update_id}")
        
        # Check if signals need to be loaded
        if hasattr(telegram_service, '_signals_need_loading') and telegram_service._signals_need_loading:
            try:
                logger.info("Loading signals during first webhook request")
                await telegram_service._load_signals()
                telegram_service._signals_loaded = True
                telegram_service._signals_need_loading = False
                logger.info("Signals loaded successfully during webhook processing")
            except Exception as e:
                logger.error(f"Error loading signals during webhook processing: {str(e)}")
                logger.error(traceback.format_exc())
                # Continue anyway, as this might not be fatal
        
        # Process the update through telegram
        from telegram import Update
        update = Update.de_json(update_data, telegram_service.bot)
        await telegram_service.application.process_update(update)
        
        logger.info(f"Successfully processed update {update_id}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}

# Import the bot and run it
@app.on_event("startup")
async def startup_event():
    """Start the bot when the FastAPI app starts."""
    global telegram_service, initialization_complete
    
    try:
        # Direct implementation to start the bot without importing main
        logger.info("Starting bot directly within asgi.py")
        
        # Create and start services
        async def start_bot():
            global telegram_service, initialization_complete
            
            try:
                # Log Python version and environment information
                logger.info(f"Python version: {sys.version}")
                logger.info(f"Current working directory: {os.getcwd()}")
                logger.info(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'Not set')}")
                
                # Import required modules with detailed error logging
                try:
                    logger.info("Importing Database class")
                    from trading_bot.services.database.db import Database
                    logger.info("Database class imported successfully")
                    
                    logger.info("Importing StripeService class")
                    from trading_bot.services.payment_service.stripe_service import StripeService
                    logger.info("StripeService class imported successfully")
                    
                    logger.info("Importing TelegramService class")
                    from trading_bot.services.telegram_service.bot import TelegramService
                    logger.info("TelegramService class imported successfully")
                except ImportError as ie:
                    logger.error(f"Import error: {str(ie)}")
                    logger.error(traceback.format_exc())
                    initialization_complete = False
                    return
                
                # Initialize database
                logger.info("Initializing Database")
                db = Database()
                logger.info("Database initialized")
                
                # Initialize Stripe service
                logger.info("Initializing StripeService")
                stripe_service = StripeService(db)
                logger.info("Stripe service initialized")
                
                # Get the Telegram bot token from environment variables
                bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                if not bot_token:
                    logger.warning("No TELEGRAM_BOT_TOKEN found in environment, using default token")
                
                # Create the Telegram service with lazy initialization
                try:
                    logger.info("Creating TelegramService instance")
                    start_time = time.time()
                    telegram_service = TelegramService(db, stripe_service, bot_token=bot_token, lazy_init=True)
                    logger.info(f"Telegram service created in {time.time() - start_time:.2f} seconds")
                except Exception as e:
                    logger.error(f"Error creating TelegramService: {str(e)}")
                    logger.error(traceback.format_exc())
                    initialization_complete = False
                    return
                
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
                try:
                    logger.info("Initializing Telegram application")
                    await telegram_service.application.initialize()
                    logger.info("Telegram application initialized")
                    
                    logger.info("Starting Telegram application")
                    await telegram_service.application.start()
                    logger.info("Telegram application started")
                except Exception as e:
                    logger.error(f"Error initializing/starting Telegram application: {str(e)}")
                    logger.error(traceback.format_exc())
                    initialization_complete = False
                    return
                
                # Set the webhook
                try:
                    logger.info("Deleting existing webhook")
                    await telegram_service.bot.delete_webhook()
                    logger.info("Setting new webhook")
                    await telegram_service.bot.set_webhook(url=webhook_url)
                    logger.info("Webhook set successfully")
                except Exception as e:
                    logger.error(f"Error setting webhook: {str(e)}")
                    logger.error(traceback.format_exc())
                    # Continue anyway, as this might not be fatal
                
                # Set the commands
                try:
                    logger.info("Setting bot commands")
                    from telegram import BotCommand
                    commands = [
                        BotCommand("start", "Start the bot and get the welcome message"),
                        BotCommand("menu", "Show the main menu"),
                        BotCommand("help", "Show available commands and how to use the bot")
                    ]
                    await telegram_service.bot.set_my_commands(commands)
                    logger.info("Bot commands set")
                except Exception as e:
                    logger.error(f"Error setting bot commands: {str(e)}")
                    logger.error(traceback.format_exc())
                    # Continue anyway, as this might not be fatal
                
                # Verify webhook was set
                try:
                    logger.info("Verifying webhook")
                    webhook_info = await telegram_service.bot.get_webhook_info()
                    logger.info(f"Webhook set to: {webhook_info.url}")
                    logger.info(f"Pending updates: {webhook_info.pending_update_count}")
                except Exception as e:
                    logger.error(f"Error verifying webhook: {str(e)}")
                    logger.error(traceback.format_exc())
                    # Continue anyway, as this might not be fatal
                
                # Mark initialization as complete
                initialization_complete = True
                logger.info("Bot initialization complete, ready to handle webhook requests")
                
                # Bot is now ready to process updates
                logger.info("Bot started successfully")
                
                # Keep the task running to prevent garbage collection
                while True:
                    await asyncio.sleep(60)
                    
            except Exception as e:
                logger.error(f"Error in start_bot task: {str(e)}")
                logger.error(traceback.format_exc())
                
                # Clear telegram_service if initialization failed
                telegram_service = None
                initialization_complete = False
        
        # Start in background
        try:
            task = asyncio.create_task(start_bot())
            logger.info("Bot startup task created")
        except Exception as e:
            logger.error(f"Error creating startup task: {str(e)}")
            logger.error(traceback.format_exc())
            
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        logger.error(traceback.format_exc())
        # Clear telegram_service if initialization failed
        telegram_service = None
        initialization_complete = False 
