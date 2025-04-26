import asyncio
import os
import logging
import json
from datetime import datetime
from trading_bot.services.calendar_service.tradingview_calendar import TradingViewCalendarService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Zorg ervoor dat ScrapingAnt is ingeschakeld en er een API key is geconfigureerd
os.environ["USE_SCRAPINGANT"] = "true"
os.environ["SCRAPINGANT_API_KEY"] = "e63e79e708d247c798885c0c320f9f30"  # Default key uit __init__.py
os.environ["USE_CALENDAR_FALLBACK"] = "false"

async def test_api_health():
    """Test de gezondheid van de API"""
    service = TradingViewCalendarService()
    is_healthy = await service._check_api_health()
    logger.info(f"API health: {is_healthy}")
    return is_healthy

async def test_get_calendar():
    """Test het ophalen van kalender gegevens"""
    service = TradingViewCalendarService()
    events = await service.get_calendar(days_ahead=0)
    logger.info(f"Retrieved {len(events)} events")
    # Geef de eerste 3 events weer voor debug doeleinden
    for i, event in enumerate(events[:3]):
        logger.info(f"Event {i+1}: {json.dumps(event)}")
    return events

async def test_scrapingant_request():
    """Test een directe ScrapingAnt request"""
    service = TradingViewCalendarService()
    
    # Bereid parameters voor
    start_date = datetime.now()
    params = {
        'from': service._format_date(start_date),
        'to': service._format_date(start_date.replace(hour=23, minute=59, second=59)),
        'countries': 'US,EU,GB',
        'limit': 10
    }
    
    # Maak de ScrapingAnt request
    response_text = await service._make_scrapingant_request(service.base_url, params)
    if response_text:
        logger.info(f"ScrapingAnt response: {response_text[:200]}...")
        if response_text.strip().startswith('[') or response_text.strip().startswith('{'):
            # Probeer het te verwerken als JSON
            logger.info("Response lijkt op geldige JSON, proberen te verwerken...")
            events = await service._process_response_text(response_text, "Low", None)
            logger.info(f"Verwerkt tot {len(events)} events")
            # Toon eerste 3 events
            for i, event in enumerate(events[:3]):
                logger.info(f"Event {i+1}: {json.dumps(event)}")
            return events
    
    logger.error("ScrapingAnt request mislukt of ongeldige response")
    return None

async def main():
    """Voer alle tests uit"""
    logger.info("Starting TradingView Calendar API tests")
    
    # Log environment variables
    logger.info(f"USE_SCRAPINGANT: {os.environ.get('USE_SCRAPINGANT', 'not set')}")
    logger.info(f"SCRAPINGANT_API_KEY: (masked)")
    logger.info(f"USE_CALENDAR_FALLBACK: {os.environ.get('USE_CALENDAR_FALLBACK', 'not set')}")
    
    # Test API gezondheid
    logger.info("=== Testing API Health ===")
    is_healthy = await test_api_health()
    
    # Test kalender gegevens ophalen
    logger.info("=== Testing Get Calendar ===")
    events = await test_get_calendar()
    
    # Test ScrapingAnt request
    logger.info("=== Testing ScrapingAnt Request ===")
    scrapingant_events = await test_scrapingant_request()
    
    # Log resultaten
    logger.info("=== Test Results ===")
    logger.info(f"API Health: {is_healthy}")
    logger.info(f"Direct API Events: {len(events) if events else 0}")
    logger.info(f"ScrapingAnt Events: {len(scrapingant_events) if scrapingant_events else 0}")
    
    logger.info("All tests completed")

if __name__ == "__main__":
    asyncio.run(main()) 
