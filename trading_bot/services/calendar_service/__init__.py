# This package contains calendar services
# Explicitly export classes for external use

# Try to import from calendar.py, but fall back to calendar_fix.py if necessary
try:
    from trading_bot.services.calendar_service.calendar import EconomicCalendarService
    import logging
    logging.getLogger(__name__).info("Successfully imported EconomicCalendarService from calendar.py")
except ImportError:
    # If the import fails, use our fallback implementation
    import logging
    logging.getLogger(__name__).warning("Could not import EconomicCalendarService from calendar.py, using fallback")
    from trading_bot.services.calendar_service.calendar_fix import EconomicCalendarService

# Export the service so it can be imported
__all__ = ['EconomicCalendarService']
