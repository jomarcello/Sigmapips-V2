# This package contains calendar services
# Explicitly export classes for external use

# Import de echte EconomicCalendarService, niet de fallback
from trading_bot.services.calendar_service.calendar import EconomicCalendarService
import logging
logging.getLogger(__name__).info("Successfully imported EconomicCalendarService from calendar.py")

# Export the service so it can be imported
__all__ = ['EconomicCalendarService']
