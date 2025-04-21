from fastapi import FastAPI
import asyncio
import logging
import os
import sys

# Add the current directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Create a FastAPI app - don't try to import from trading_bot.main
app = FastAPI()

logger = logging.getLogger(__name__)

# Basic health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for Railway's healthcheck."""
    return {"status": "ok", "message": "Bot is running"}

# Import the bot and run it
@app.on_event("startup")
async def startup_event():
    """Start the bot when the FastAPI app starts."""
    try:
        # Import main app's main function directly
        from main import main
        
        # Start the bot in the background
        asyncio.create_task(main())
        logger.info("Bot started via FastAPI app")
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        logger.exception(e) 
