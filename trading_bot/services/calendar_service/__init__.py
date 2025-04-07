# This package contains calendar services
# Explicitly export classes for external use

import logging
import traceback
import os
import sys
import socket

logger = logging.getLogger(__name__)
logger.info("Initializing calendar service module...")

# Configureer een extra handlertje voor kalender gerelateerde logs
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

# Detecteer of we in Railway draaien
RUNNING_IN_RAILWAY = os.environ.get("RAILWAY_ENVIRONMENT") is not None
HOSTNAME = socket.gethostname()

logger.info(f"Running on host: {HOSTNAME}")
logger.info(f"Running in Railway: {RUNNING_IN_RAILWAY}")

# Als we in Railway draaien, gebruik dan ScrapingAnt als default
if RUNNING_IN_RAILWAY and os.environ.get("USE_SCRAPINGANT") is None:
    os.environ["USE_SCRAPINGANT"] = "true"
    logger.info("Running in Railway, setting USE_SCRAPINGANT=true by default")

# ScrapingAnt API key configureren indien niet al gedaan
if os.environ.get("SCRAPINGANT_API_KEY") is None:
    os.environ["SCRAPINGANT_API_KEY"] = "e63e79e708d247c798885c0c320f9f30"
    logger.info("Setting default ScrapingAnt API key")

# Flag om te bepalen welke implementatie we moeten gebruiken
USE_FALLBACK = os.environ.get("USE_CALENDAR_FALLBACK", "").lower() in ("true", "1", "yes")

if USE_FALLBACK:
    logger.info("USE_CALENDAR_FALLBACK is set to True, using fallback implementation")
    print("⚠️ Calendar fallback mode is ENABLED via environment variable")
    from trading_bot.services.calendar_service.calendar_fix import EconomicCalendarService
    logger.info("Successfully imported fallback EconomicCalendarService from calendar_fix.py")
else:
    # Probeer eerst de volledige implementatie
    try:
        logger.info("Attempting to import EconomicCalendarService from calendar.py...")
        from trading_bot.services.calendar_service.calendar import EconomicCalendarService
        logger.info("Successfully imported EconomicCalendarService from calendar.py")
        
        # Test importeren van TradingView kalender
        try:
            from trading_bot.services.calendar_service.tradingview_calendar import TradingViewCalendarService
            logger.info("Successfully imported TradingViewCalendarService")
            
            # Check if using ScrapingAnt
            use_scrapingant = os.environ.get("USE_SCRAPINGANT", "").lower() in ("true", "1", "yes")
            logger.info(f"Using ScrapingAnt for calendar API: {use_scrapingant}")
            
            if use_scrapingant:
                print("✅ Using ScrapingAnt proxy for TradingView calendar API")
            else:
                print("✅ Using direct connection for TradingView calendar API")
            
        except Exception as e:
            logger.warning(f"TradingViewCalendarService import failed: {e}")
            logger.debug(traceback.format_exc())
            print("⚠️ TradingView calendar service could not be imported")

    except Exception as e:
        # Als de import faalt, gebruiken we onze fallback implementatie
        logger.error(f"Could not import EconomicCalendarService from calendar.py: {str(e)}")
        logger.debug(traceback.format_exc())
        logger.warning("Using fallback implementation from calendar_fix.py")
        print("⚠️ Could not import real calendar service, using fallback")
        
        # Importeer de fallback implementatie
        from trading_bot.services.calendar_service.calendar_fix import EconomicCalendarService
        
        # Log dat we de fallback gebruiken
        logger.info("Successfully imported fallback EconomicCalendarService from calendar_fix.py")

# Exporteer TradingView debug functie als die beschikbaar is
try:
    from trading_bot.services.calendar_service.tradingview_calendar import TradingViewCalendarService
    
    # Create a global function to run the debug
    async def debug_tradingview_api():
        """Run a debug check on the TradingView API"""
        logger.info("Running TradingView API debug check")
        service = TradingViewCalendarService()
        return await service.debug_api_connection()

    __all__ = ['EconomicCalendarService', 'debug_tradingview_api']
except Exception:
    # Als de import faalt, exporteren we alleen de EconomicCalendarService
    __all__ = ['EconomicCalendarService']
