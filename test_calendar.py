import asyncio
import logging
from datetime import datetime
from collections import namedtuple

# Configuratie logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock CalendarResult class
class CalendarResult:
    def __init__(self, events=None, message=None, error=False):
        self.events = events or []
        self.message = message
        self.error = error
    
    def get(self, key, default=None):
        """Compatibility with dictionary-like interface"""
        if key == 'events':
            return self.events
        elif key == 'message':
            return self.message
        elif key == 'error':
            return self.error
        return default

# De te testen methode, gekopieerd uit bot.py maar vereenvoudigd
async def _format_calendar_events(calendar_data):
    """Format the calendar data in chronological order - TEST IMPLEMENTATION"""
    try:
        # Check if calendar_data is a CalendarResult object
        if hasattr(calendar_data, 'get'):
            # Als calendar_data een CalendarResult object is, haal de message op
            if calendar_data.get('message'):
                return calendar_data.get('message')
            # Als er een error is, geef een foutmelding terug
            if calendar_data.get('error'):
                return f"📅 Economic Calendar\n\nError: {calendar_data.get('message', 'Unknown error')}"
            # Haal events op als array
            events = calendar_data.get('events', [])
        else:
            # Fallback voor het geval calendar_data een lijst is (zoals eerder verwacht)
            events = calendar_data or []
        
        # Genereer dummy bericht voor de test
        message = "📅 Economic Calendar\n\n"
        message += f"Date: {datetime.now().strftime('%B %d, %Y')}\n\n"
        
        # Leeg resultaat als er geen data is
        if not events or len(events) == 0:
            return message + "No economic events scheduled for today."
            
        # Als er events zijn, voeg demo event toe
        return message + "Test events: " + str(len(events))
        
    except Exception as e:
        logger.error(f"Error formatting calendar events: {str(e)}")
        
        # Eenvoudige fallback bij een error
        return "📅 Economic Calendar\n\nUnable to format calendar data correctly. Please try again later."

async def test_calendar_integration():
    # Test met een CalendarResult object
    calendar_result = CalendarResult(
        events=[],
        message="Dit is een testbericht uit de kalender",
        error=False
    )
    
    # Probeer het kalenderbericht te formatteren
    formatted_message = await _format_calendar_events(calendar_result)
    logger.info(f"Geformatteerd bericht met message: {formatted_message}")
    
    # Test met een error response
    error_result = CalendarResult(
        events=[],
        message="Er is een fout opgetreden",
        error=True
    )
    formatted_error = await _format_calendar_events(error_result)
    logger.info(f"Geformatteerde fout: {formatted_error}")
    
    # Test met events
    events_result = CalendarResult(
        events=[{"name": "Test Event"}],
        message=None,
        error=False
    )
    formatted_events = await _format_calendar_events(events_result)
    logger.info(f"Geformatteerd met events: {formatted_events}")
    
    # Test met een lijst in plaats van CalendarResult (oude manier)
    old_style_data = [{"name": "Old Event 1"}, {"name": "Old Event 2"}]
    formatted_old = await _format_calendar_events(old_style_data)
    logger.info(f"Geformatteerd met oude stijl data: {formatted_old}")

# Run de test
if __name__ == "__main__":
    asyncio.run(test_calendar_integration()) 