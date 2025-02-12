from fastapi import FastAPI, HTTPException, Request
import logging
import os
from typing import Dict, Any
from telegram import Update

from trading_bot.services.telegram_service.bot import TelegramService
from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.database.db import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
port = int(os.getenv("PORT", 8080))

# Initialize services
db = Database()
telegram = TelegramService(db)
chart = ChartService()

@app.on_event("startup")
async def startup_event():
    """Initialize async services on startup"""
    await telegram.initialize()
    
    webhook_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if webhook_url:
        full_url = f"https://{webhook_url}"
        await telegram.set_webhook(full_url)
        logger.info(f"Webhook set to: {full_url}")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle Telegram webhook updates"""
    try:
        update = Update.de_json(await request.json(), telegram.bot)
        await telegram.app.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/signal")
async def process_signal(signal: Dict[str, Any]):
    """Process incoming trading signal"""
    try:
        logger.info(f"Received signal: {signal}")
        
        # 1. Validate signal
        required_fields = ["symbol", "action", "price", "stopLoss", "takeProfit", "timeframe", "market"]
        if not all(field in signal for field in required_fields):
            missing = [f for f in required_fields if f not in signal]
            logger.error(f"Missing fields in signal: {missing}")
            raise HTTPException(status_code=400, detail=f"Missing required fields: {missing}")
        
        # 2. Generate chart with market info
        try:
            chart_image = await chart.generate_chart(
                symbol=signal["symbol"],
                timeframe=signal["timeframe"],
                market=signal["market"]
            )
            logger.info("Chart generated successfully")
        except Exception as e:
            logger.error(f"Chart generation failed: {str(e)}")
            chart_image = None
        
        # 3. Find matching subscribers
        subscribers = await db.match_subscribers(signal)
        logger.info(f"Found {len(subscribers)} matching subscribers")
        
        # 4. Send signals to subscribers
        sent_count = 0
        for subscriber in subscribers:
            success = await telegram.send_signal(
                chat_id=subscriber["chat_id"],
                signal=signal,
                sentiment="Sentiment analysis coming soon",
                chart=chart_image,
                events=["Economic calendar coming soon"]
            )
            if success:
                sent_count += 1
            
        return {
            "status": "success", 
            "subscribers_found": len(subscribers),
            "signals_sent": sent_count
        }
        
    except Exception as e:
        logger.error(f"Error processing signal: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

