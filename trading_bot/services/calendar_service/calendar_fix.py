"""
Calendar service fallback implementation
"""
import logging
from typing import Dict, List, Any, Optional

# Create a fallback class for the EconomicCalendarService
class EconomicCalendarService:
    """Fallback implementation of EconomicCalendarService"""
    def __init__(self, *args, **kwargs):
        self.logger = logging.getLogger(__name__)
        self.logger.warning("Fallback EconomicCalendarService is being used!")
        
    async def get_calendar(self, days_ahead: int = 0, min_impact: str = "Low") -> List[Dict]:
        """Return empty calendar data"""
        self.logger.info(f"Fallback get_calendar called with days_ahead={days_ahead}, min_impact={min_impact}")
        return []
        
    async def get_events_for_instrument(self, instrument: str, *args, **kwargs) -> Dict[str, Any]:
        """Return empty events"""
        self.logger.info(f"Fallback get_events_for_instrument called for {instrument}")
        return {"events": [], "explanation": "No calendar service available"}
        
    async def get_instrument_calendar(self, instrument: str, *args, **kwargs) -> str:
        """Return empty formatted response"""
        self.logger.info(f"Fallback get_instrument_calendar called for {instrument}")
        return "<b>📅 Economic Calendar</b>\n\nCalendar service unavailable."
    
    def get_loading_gif(self) -> str:
        """Get the URL for the loading GIF"""
        return "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif" 
