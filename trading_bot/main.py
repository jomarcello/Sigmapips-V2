import logging
import os
import json
from fastapi import FastAPI, Request, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import stripe

# Configureer logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Laad omgevingsvariabelen
load_dotenv()

# Importeer de benodigde services
from trading_bot.services.database.db import Database
from trading_bot.services.telegram_service.bot import TelegramService
from trading_bot.services.payment_service.stripe_service import StripeService
from trading_bot.services.payment_service.stripe_config import STRIPE_WEBHOOK_SECRET

# Initialiseer de FastAPI app
app = FastAPI()

# Initialiseer de database
db = Database()

# Initialiseer de Stripe service
stripe_service = StripeService(db)

# Initialiseer de Telegram service
telegram_service = TelegramService(
    db=db, 
    stripe_service=stripe_service,
    signal_service=None,
    news_service=None,
    chart_service=None
)

# Voeg deze functie toe bovenaan het bestand, na de imports
def convert_interval_to_timeframe(interval):
    """Convert TradingView interval value to readable timeframe format"""
    if not interval:
        return "1h"  # Default timeframe
    
    # Converteer naar string voor het geval het als getal binnenkomt
    interval_str = str(interval).lower()
    
    # Controleer of het al een formaat heeft zoals "1m", "5m", etc.
    if interval_str.endswith('m') or interval_str.endswith('h') or interval_str.endswith('d') or interval_str.endswith('w'):
        return interval_str
    
    # Vertaal numerieke waarden naar timeframe formaat
    interval_map = {
        "1": "1m",
        "3": "3m",
        "5": "5m",
        "15": "15m",
        "30": "30m",
        "60": "1h",
        "120": "2h",
        "240": "4h",
        "360": "6h",
        "480": "8h",
        "720": "12h",
        "1440": "1d",
        "10080": "1w",
        "43200": "1M"
    }
    
    # Speciale gevallen voor 1
    if interval_str == "1":
        return "1m"  # Standaard 1 = 1 minuut
    
    # Controleer of we een directe mapping hebben
    if interval_str in interval_map:
        return interval_map[interval_str]
    
    # Als het een getal is zonder mapping, probeer te raden
    try:
        interval_num = int(interval_str)
        if interval_num < 60:
            return f"{interval_num}m"  # Minuten
        elif interval_num < 1440:
            hours = interval_num // 60
            return f"{hours}h"  # Uren
        elif interval_num < 10080:
            days = interval_num // 1440
            return f"{days}d"  # Dagen
        else:
            weeks = interval_num // 10080
            return f"{weeks}w"  # Weken
    except ValueError:
        # Als het geen getal is, geef het terug zoals het is
        return interval_str

@app.on_event("startup")
async def startup_event():
    try:
        await telegram_service.initialize(use_webhook=True)
        logger.info("Telegram service initialized")
    except Exception as e:
        logger.error(f"Error initializing services: {str(e)}")
        raise

@app.post("/webhook")
async def webhook(request: Request):
    try:
        # Log de binnenkomende request
        body = await request.body()
        logger.info(f"Received webhook: {body.decode('utf-8')}")
        
        # Parse de JSON data
        data = await request.json()
        
        # Controleer of het een Telegram update is (heeft 'update_id')
        if 'update_id' in data:
            # Verwerk als Telegram update
            if telegram_service:
                success = await telegram_service.process_update(data)
                if success:
                    return JSONResponse(content={"status": "success", "message": "Telegram update processed"})
                else:
                    raise HTTPException(status_code=500, detail="Failed to process Telegram update")
        else:
            # Verwerk als TradingView signaal
            if telegram_service:
                success = await telegram_service.process_signal(data)
                if success:
                    return JSONResponse(content={"status": "success", "message": "Signal processed"})
                else:
                    raise HTTPException(status_code=500, detail="Failed to process signal")
        
        # Als we hier komen, konden we het verzoek niet verwerken
        raise HTTPException(status_code=400, detail="Unknown webhook format")
    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/signal")
async def handle_signal(request: Request):
    """Handle incoming trading signals"""
    try:
        # Log raw data
        raw_data = await request.body()
        logger.info(f"Received raw signal data: {raw_data}")
        
        # Parse JSON data
        signal_data = await request.json()
        logger.info(f"Parsed signal data: {signal_data}")
        
        # Controleer en corrigeer template strings
        for key, value in signal_data.items():
            if isinstance(value, str) and '{{' in value and '}}' in value:
                logger.warning(f"Template string detected in {key}: {value}, replacing with default value")
                
                # Vervang template strings met standaardwaarden
                if key == 'signal':
                    signal_data[key] = 'buy'  # Standaard naar 'buy' omdat we alleen met buy signalen werken
                    logger.info(f"Replaced template string in 'signal' with 'buy'")
                # Voeg hier andere template vervangingen toe indien nodig
        
        # Converteer interval naar leesbaar timeframe formaat
        if 'interval' in signal_data:
            original_interval = signal_data['interval']
            signal_data['interval'] = convert_interval_to_timeframe(original_interval)
            logger.info(f"Converted interval from {original_interval} to {signal_data['interval']}")
        
        # Zorg ervoor dat 'symbol' wordt gekopieerd naar 'instrument' als het ontbreekt
        if 'symbol' in signal_data and not signal_data.get('instrument'):
            signal_data['instrument'] = signal_data['symbol']
            logger.info(f"Copied symbol to instrument: {signal_data['instrument']}")
        
        # Validate required fields
        required_fields = ['instrument', 'signal', 'price']
        if not all(field in signal_data for field in required_fields):
            logger.error(f"Missing required fields in signal: {signal_data}")
            return {"status": "error", "message": "Missing required fields"}
            
        # Converteer waardes naar float en rond af op 2 decimalen
        try:
            price = float(signal_data.get('price', 0))
            
            # SL en TP waarden ophalen en valideren
            if 'sl' in signal_data and signal_data['sl'] is not None:
                sl = float(signal_data['sl'])
                
                # Validatie voor Buy/Sell signalen
                if signal_data['signal'].lower() == 'buy' and sl > price:
                    logger.warning(f"Correcting invalid stop loss for BUY signal: SL ({sl}) > Entry ({price})")
                    # Correctie: bereken een SL 1.5% onder de entry prijs
                    sl = round(price * 0.985, 2)  # 1.5% onder entry prijs
                    signal_data['sl'] = sl
                
                elif signal_data['signal'].lower() == 'sell' and sl < price:
                    logger.warning(f"Correcting invalid stop loss for SELL signal: SL ({sl}) < Entry ({price})")
                    # Correctie: bereken een SL 1.5% boven de entry prijs
                    sl = round(price * 1.015, 2)  # 1.5% boven entry prijs
                    signal_data['sl'] = sl
            else:
                # Als SL ontbreekt, bereken deze automatisch
                if signal_data['signal'].lower() == 'buy':
                    signal_data['sl'] = round(price * 0.985, 2)  # 1.5% onder entry prijs
                else:
                    signal_data['sl'] = round(price * 1.015, 2)  # 1.5% boven entry prijs
            
            # Zorg dat TP waarden correct zijn
            if signal_data['signal'].lower() == 'buy':
                # Voor BUY: Entry < TP1 < TP2 < TP3
                if 'tp1' in signal_data and signal_data['tp1'] is not None:
                    if float(signal_data['tp1']) <= price:
                        logger.warning(f"Correcting invalid TP1 for BUY signal: TP1 <= Entry")
                        signal_data['tp1'] = round(price * 1.01, 2)  # 1% boven entry
                else:
                    signal_data['tp1'] = round(price * 1.01, 2)  # 1% boven entry
                
                if 'tp2' in signal_data and signal_data['tp2'] is not None:
                    if float(signal_data['tp2']) <= price:
                        logger.warning(f"Correcting invalid TP2 for BUY signal: TP2 <= Entry")
                        signal_data['tp2'] = round(price * 1.02, 2)  # 2% boven entry
                else:
                    signal_data['tp2'] = round(price * 1.02, 2)  # 2% boven entry
                
                if 'tp3' in signal_data and signal_data['tp3'] is not None:
                    if float(signal_data['tp3']) <= price:
                        logger.warning(f"Correcting invalid TP3 for BUY signal: TP3 <= Entry")
                        signal_data['tp3'] = round(price * 1.03, 2)  # 3% boven entry
                else:
                    signal_data['tp3'] = round(price * 1.03, 2)  # 3% boven entry
            
            elif signal_data['signal'].lower() == 'sell':
                # Voor SELL: Entry > TP1 > TP2 > TP3
                if 'tp1' in signal_data and signal_data['tp1'] is not None:
                    if float(signal_data['tp1']) >= price:
                        logger.warning(f"Correcting invalid TP1 for SELL signal: TP1 >= Entry")
                        signal_data['tp1'] = round(price * 0.99, 2)  # 1% onder entry
                else:
                    signal_data['tp1'] = round(price * 0.99, 2)  # 1% onder entry
                
                if 'tp2' in signal_data and signal_data['tp2'] is not None:
                    if float(signal_data['tp2']) >= price:
                        logger.warning(f"Correcting invalid TP2 for SELL signal: TP2 >= Entry")
                        signal_data['tp2'] = round(price * 0.98, 2)  # 2% onder entry
                else:
                    signal_data['tp2'] = round(price * 0.98, 2)  # 2% onder entry
                
                if 'tp3' in signal_data and signal_data['tp3'] is not None:
                    if float(signal_data['tp3']) >= price:
                        logger.warning(f"Correcting invalid TP3 for SELL signal: TP3 >= Entry")
                        signal_data['tp3'] = round(price * 0.97, 2)  # 3% onder entry
                else:
                    signal_data['tp3'] = round(price * 0.97, 2)  # 3% onder entry
            
            # Rond alle prijswaarden af op 2 decimalen
            for key in ['price', 'sl', 'tp1', 'tp2', 'tp3']:
                if key in signal_data and signal_data[key] is not None:
                    signal_data[key] = round(float(signal_data[key]), 2)
                    
        except ValueError as e:
            logger.error(f"Invalid price values in signal: {str(e)}")
            return {"status": "error", "message": "Invalid price values"}
        
        # Process the signal
        success = await telegram_service.process_signal(signal_data)
        
        if success:
            return {"status": "success", "message": "Signal processed successfully"}
        else:
            return {"status": "error", "message": "Failed to process signal"}
            
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in webhook: {str(e)}")
        return {"status": "error", "message": "Invalid JSON format"}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        logger.exception(e)
        return {"status": "error", "message": str(e)}

@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature")
    stripe_webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    
    try:
        # Verify the webhook event came from Stripe
        event = stripe.Webhook.construct_event(
            payload, sig_header, stripe_webhook_secret
        )
        
        # Process the event according to its type
        await stripe_service.handle_webhook_event(event)
        
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/create-subscription-link/{user_id}/{plan_type}")
async def create_subscription_link(user_id: int, plan_type: str = 'basic'):
    """Maak een Stripe Checkout URL voor een gebruiker"""
    try:
        checkout_url = await stripe_service.create_checkout_session(user_id, plan_type)
        
        if checkout_url:
            return {"status": "success", "checkout_url": checkout_url}
        else:
            raise HTTPException(status_code=500, detail="Failed to create checkout session")
    except Exception as e:
        logger.error(f"Error creating subscription link: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("trading_bot.main:app", host="0.0.0.0", port=8080)

# Expliciet de app exporteren
__all__ = ['app']

app = app  # Expliciete herbevestiging van de app variabele
