# This package contains calendar services
# Explicitly export classes for external use

import logging
import traceback
import os
import sys
import socket
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

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
# Expliciet investing.com uitschakelen (investing is verwijderd)
os.environ["USE_INVESTING_CALENDAR"] = "false"
logger.info("⚠️ Investing.com calendar is verwijderd en niet meer beschikbaar")
print("⚠️ Investing.com calendar is verwijderd en niet meer beschikbaar")

# AGSI (gas storage index) is ook niet meer beschikbaar
logger.info("⚠️ AGSI (gas storage index) is verwijderd en niet meer beschikbaar")
print("⚠️ AGSI (gas storage index) is verwijderd en niet meer beschikbaar")

# Calendar fallback uitschakelen - we willen echte data
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

# Check of er iets expliciets in de omgeving is ingesteld voor fallback
USE_FALLBACK = os.environ.get("USE_CALENDAR_FALLBACK", "false").lower() in ("true", "1", "yes")

# Ingebouwde fallback EconomicCalendarService voor het geval de echte niet werkt
class InternalFallbackCalendarService:
    """Interne fallback implementatie van EconomicCalendarService"""
    def __init__(self, *args, **kwargs):
        self.logger = logging.getLogger(__name__)
        self.logger.warning("Internal fallback EconomicCalendarService is being used!")
        print("⚠️ INTERNAL FALLBACK CALENDAR SERVICE IS ACTIVE ⚠️")
        
    async def get_calendar(self, days_ahead: int = 0, min_impact: str = "Low", currency: str = None) -> List[Dict]:
        """Return empty calendar data"""
        self.logger.info(f"Internal fallback get_calendar called")
        return []
    
    async def get_economic_calendar(self, currencies: List[str] = None, days_ahead: int = 0, min_impact: str = "Low") -> str:
        """Return empty economic calendar message"""
        return "<b>📅 Economic Calendar</b>\n\nNo economic events available (using internal fallback)."
        
    async def get_events_for_instrument(self, instrument: str, *args, **kwargs) -> Dict[str, Any]:
        """Return empty events for an instrument"""
        return {
            "events": [], 
            "explanation": f"No calendar events available (using internal fallback)"
        }
        
    async def get_instrument_calendar(self, instrument: str, *args, **kwargs) -> str:
        """Return empty calendar for an instrument"""
        return "<b>📅 Economic Calendar</b>\n\nNo calendar events available (using internal fallback)."

# Log duidelijk naar de console of we fallback gebruiken of niet
if USE_FALLBACK:
    logger.info("⚠️ USE_CALENDAR_FALLBACK is set to True, using fallback implementation")
    print("⚠️ Calendar fallback mode is ENABLED via environment variable")
    print(f"⚠️ Check environment value: '{os.environ.get('USE_CALENDAR_FALLBACK', '')}'")
    # Gebruik interne fallback
    EconomicCalendarService = InternalFallbackCalendarService
    logger.info("Successfully initialized internal fallback EconomicCalendarService")
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
        # Als de import faalt, gebruiken we onze interne fallback implementatie
        logger.error(f"Could not import EconomicCalendarService from calendar.py: {str(e)}")
        logger.debug(traceback.format_exc())
        logger.warning("Using internal fallback implementation")
        print("⚠️ Could not import real calendar service, using internal fallback")
        
        # Gebruik interne fallback
        EconomicCalendarService = InternalFallbackCalendarService
        
        # Log dat we de fallback gebruiken
        logger.info("Successfully initialized internal fallback EconomicCalendarService")

# Exporteer TradingView debug functie als die beschikbaar is
try:

    # Create a global function to run the debug
    async def debug_tradingview_api():
        """Run a debug check on the TradingView API"""
        from trading_bot.services.calendar_service.tradingview_calendar import TradingViewCalendarService
        logger.info("Running TradingView API debug check")
        service = TradingViewCalendarService()
        return await service.debug_api_connection()

    # Add a function to get all calendar events without filtering
    async def get_all_calendar_events():
        """Get all calendar events without filtering"""
        from trading_bot.services.calendar_service.tradingview_calendar import TradingViewCalendarService
        logger.info("Getting all calendar events without filtering")
        service = TradingViewCalendarService()
        events = await service.get_calendar(days_ahead=0, min_impact="Low")
        logger.info(f"Retrieved {len(events)} total events")
        return events

    __all__ = ['EconomicCalendarService', 'debug_tradingview_api', 'get_all_calendar_events']
except Exception:
    # Als de import faalt, exporteren we alleen de EconomicCalendarService
    __all__ = ['EconomicCalendarService']
