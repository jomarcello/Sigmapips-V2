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

# BELANGRIJK: Force instellingen voor TradingView calendar
# Expliciet investing.com uitschakelen
os.environ["USE_INVESTING_CALENDAR"] = "false"
logger.info("⚠️ Forcing USE_INVESTING_CALENDAR=false to use TradingView calendar")
print("⚠️ Forcing USE_INVESTING_CALENDAR=false to use TradingView calendar")

# Calendfaer fallback uitschakelen - we willen echte data
os.environ["USE_CALENDAR_FALLBACK"] = "false"
logger.info("⚠️ Forcing USE_CALENDAR_FALLBACK=false to use real data")
print("⚠️ Forcing USE_CALENDAR_FALLBACK=false to use real data")

# ScrapingAnt inschakelen voor betere data
os.environ["USE_SCRAPINGANT"] = "true"
logger.info("⚠️ Forcing USE_SCRAPINGANT=true for better data retrieval")
print("⚠️ Forcing USE_SCRAPINGANT=true for better data retrieval")

# ScrapingAnt API key configureren indien niet al gedaan
if os.environ.get("SCRAPINGANT_API_KEY") is None:
    os.environ["SCRAPINGANT_API_KEY"] = "e63e79e708d247c798885c0c320f9f30"
    logger.info("Setting default ScrapingAnt API key")

# Flag om te bepalen welke implementatie we moeten gebruiken
USE_INVESTING = os.environ.get("USE_INVESTING_CALENDAR", "").lower() in ("true", "1", "yes")

if USE_INVESTING:
    logger.info("✅ Using Investing.com calendar implementation")
    from trading_bot.services.calendar_service.investing_calendar import InvestingCalendarService as EconomicCalendarService
    logger.info("Successfully imported InvestingCalendarService")
else:
    # Check of er iets expliciets in de omgeving is ingesteld voor fallback
    USE_FALLBACK = os.environ.get("USE_CALENDAR_FALLBACK", "").lower() in ("true", "1", "yes")

    # Log duidelijk naar de console of we fallback gebruiken of niet
    if USE_FALLBACK:
        logger.info("⚠️ USE_CALENDAR_FALLBACK is set to True, using fallback implementation")
        print("⚠️ Calendar fallback mode is ENABLED via environment variable")
        print(f"⚠️ Check environment value: '{os.environ.get('USE_CALENDAR_FALLBACK', '')}'")
        from trading_bot.services.calendar_service.calendar_fix import EconomicCalendarService
        logger.info("Successfully imported fallback EconomicCalendarService from calendar_fix.py")
    else:
        # Probeer eerst de volledige implementatie
        logger.info("✅ USE_CALENDAR_FALLBACK is set to False, will use real implementation")
        print("✅ Calendar fallback mode is DISABLED")
        print(f"✅ Environment value: '{os.environ.get('USE_CALENDAR_FALLBACK', '')}'")
        
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
