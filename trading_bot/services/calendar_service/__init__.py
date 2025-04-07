# This package contains calendar services
# Explicitly export classes for external use

import logging
import traceback
import os
import sys

logger = logging.getLogger(__name__)
logger.info("Initializing calendar service module...")

# Configureer een extra handlertje voor kalender gerelateerde logs
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

# Flag om te bepalen welke implementatie we moeten gebruiken
USE_FALLBACK = os.environ.get("USE_CALENDAR_FALLBACK", "").lower() in ("true", "1", "yes")

if USE_FALLBACK:
    logger.info("USE_CALENDAR_FALLBACK is set to True, using fallback implementation")
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
        except Exception as e:
            logger.warning(f"TradingViewCalendarService import failed: {e}")
            logger.debug(traceback.format_exc())

    except Exception as e:
        # Als de import faalt, gebruiken we onze fallback implementatie
        logger.error(f"Could not import EconomicCalendarService from calendar.py: {str(e)}")
        logger.debug(traceback.format_exc())
        logger.warning("Using fallback implementation from calendar_fix.py")
        
        # Importeer de fallback implementatie
        from trading_bot.services.calendar_service.calendar_fix import EconomicCalendarService
        
        # Log dat we de fallback gebruiken
        logger.info("Successfully imported fallback EconomicCalendarService from calendar_fix.py")

# Export the service so it can be imported
__all__ = ['EconomicCalendarService']
