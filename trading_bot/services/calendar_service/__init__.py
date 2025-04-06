# This package contains calendar services
# Explicitly export classes for external use

# Import and re-export the EconomicCalendarService
from trading_bot.services.calendar_service.calendar import EconomicCalendarService

# Export the service so it can be imported
__all__ = ['EconomicCalendarService']
