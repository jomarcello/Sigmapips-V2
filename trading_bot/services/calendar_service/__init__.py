# This package contains calendar services
# Explicitly export classes for external use

import logging
logger = logging.getLogger(__name__)

# Try to import from calendar.py, but fall back to calendar_fix.py if necessary
try:
    # Eerst proberen we te importeren uit calendar.py
    from trading_bot.services.calendar_service.calendar import EconomicCalendarService
    logger.info("Successfully imported EconomicCalendarService from calendar.py")
except ImportError as e:
    # Als de import faalt, gebruiken we onze fallback implementatie
    logger.warning(f"Could not import EconomicCalendarService from calendar.py: {str(e)}")
    logger.warning("Using fallback implementation from calendar_fix.py")
    
    # Importeer de fallback implementatie
    from trading_bot.services.calendar_service.calendar_fix import EconomicCalendarService
    
    # Log dat we de fallback gebruiken
    logger.info("Successfully imported fallback EconomicCalendarService from calendar_fix.py")

# Export the service so it can be imported
__all__ = ['EconomicCalendarService']
