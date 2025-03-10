import logging
import os
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# Configureer logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Laad omgevingsvariabelen
load_dotenv()

# Importeer de benodigde services
from trading_bot.services.database.db import Database
from trading_bot.services.telegram_service.bot import TelegramService

# Initialiseer de FastAPI app
app = FastAPI()

# Initialiseer de database
db = Database()

# Initialiseer de Telegram service
telegram_service = None

@app.on_event("startup")
async def startup_event():
    global telegram_service
    try:
        # Initialiseer de Telegram service
        telegram_service = TelegramService(db)
        await telegram_service.initialize(use_webhook=True)
        logger.info("Telegram service initialized")
    except Exception as e:
        logger.error(f"Error initializing Telegram service: {str(e)}")
        raise

@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):
    try:
        # Log de binnenkomende request
        body = await request.body()
        logger.info(f"Received TradingView webhook: {body.decode('utf-8')}")
        
        # Parse de JSON data
        data = await request.json()
        logger.info(f"Parsed TradingView data: {data}")
        
        # Verwerk het signaal
        if telegram_service:
            success = await telegram_service.process_signal(data)
            if success:
                return JSONResponse(content={"status": "success", "message": "Signal processed"})
            else:
                raise HTTPException(status_code=500, detail="Failed to process signal")
        else:
            raise HTTPException(status_code=503, detail="Telegram service not initialized")
    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        logger.error(f"Error processing TradingView webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        # Log de binnenkomende request
        body = await request.body()
        logger.debug(f"Received Telegram webhook: {body.decode('utf-8')}")
        
        # Parse de JSON data
        data = await request.json()
        
        # Verwerk de update
        if telegram_service:
            success = await telegram_service.process_update(data)
            if success:
                return JSONResponse(content={"status": "success", "message": "Update processed"})
            else:
                raise HTTPException(status_code=500, detail="Failed to process update")
        else:
            raise HTTPException(status_code=503, detail="Telegram service not initialized")
    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        logger.error(f"Error processing Telegram webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("trading_bot.main:app", host="0.0.0.0", port=port, reload=True)
