# This package contains calendar services
# Explicitly export classes for external use

# Leave this file empty to prevent circular imports
# Import directly from calendar.py where needed:
# from trading_bot.services.calendar_service.calendar import EconomicCalendarService

# Import hack om circulaire dependencies te voorkomen
# Importeer alleen als ze al beschikbaar zijn, anders valt het terug op alternatieven

try:
    from trading_bot.services.calendar_service.calendar import EconomicCalendarService
    HAS_CALENDAR_SERVICE = True
except ImportError:
    HAS_CALENDAR_SERVICE = False
    
    # Fallback definitie als de import mislukt
    class EconomicCalendarService:
        """Fallback implementation van EconomicCalendarService"""
        def __init__(self, *args, **kwargs):
            import logging
            self.logger = logging.getLogger(__name__)
            self.logger.warning("Fallback EconomicCalendarService is being used!")
            
        async def get_calendar(self, *args, **kwargs):
            """Return empty calendar data"""
            return []
            
        async def get_events_for_instrument(self, *args, **kwargs):
            """Return empty events"""
            return {"events": [], "explanation": "No calendar service available"}
            
        async def get_instrument_calendar(self, instrument: str, *args, **kwargs):
            """Return empty formatted response"""
            return "<b>📅 Economic Calendar</b>\n\nCalendar service unavailable."

# Exporteer de service zodat deze kan worden geïmporteerd
__all__ = ['EconomicCalendarService']
