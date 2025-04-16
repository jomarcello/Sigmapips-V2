import asyncio
import logging
import re
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock necessary components
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

def _format_telegram_message(events):
    """Format events for Telegram message"""
    output = []
    output.append(f"📅 *Economic Calendar*")
    
    # Get the current date in different formats
    today = datetime.now()
    today_formatted = today.strftime("%B %d, %Y")
    
    output.append(f"\nDate: {today_formatted}")
    output.append("\nImpact: 🔴 High   🟠 Medium   🟢 Low")
    output.append("")
    
    if not events:
        output.append("No economic events scheduled for today.")
        return "\n".join(output)
    
    # Map countries to currency codes
    country_to_currency = {
        'United States': 'USD',
        'Euro Zone': 'EUR',
        'United Kingdom': 'GBP',
        'Japan': 'JPY',
        'Switzerland': 'CHF',
        'Canada': 'CAD',
        'Australia': 'AUD',
        'New Zealand': 'NZD'
    }
    
    # Group events by currency
    events_by_currency = {}
    for result in events:
        country = result['country']
        currency_code = country_to_currency.get(country, country)
        
        if currency_code not in events_by_currency:
            events_by_currency[currency_code] = []
        
        events_by_currency[currency_code].append(result)
    
    # Process each currency group
    for currency_code, currency_events in sorted(events_by_currency.items()):
        # Get the flag emoji
        country = next((c for c, code in country_to_currency.items() if code == currency_code), None)
        country_emoji = {
            'United States': '🇺🇸',
            'Euro Zone': '🇪🇺',
            'United Kingdom': '🇬🇧',
            'Japan': '🇯🇵',
            'Switzerland': '🇨🇭',
            'Canada': '🇨🇦',
            'Australia': '🇦🇺',
            'New Zealand': '🇳🇿'
        }.get(country, '🌍')
        
        # Add currency header
        output.append(f"{country_emoji} {currency_code}")
        
        # Sort events by time
        currency_events.sort(key=lambda x: x['timestamp'])
        
        # Add each event
        for result in currency_events:
            # Convert to local time
            event_time = datetime.fromtimestamp(result['timestamp'])
            
            # Format impact level
            impact_emoji = "🟢"  # Default Low
            if result['impact'] == 3:
                impact_emoji = "🔴"
            elif result['impact'] == 2:
                impact_emoji = "🟠"
            
            # Simplify event name by removing parentheses details where possible
            event_name = result['name']
            # Try to remove the date part in parentheses
            event_name = re.sub(r'\s*\([A-Za-z]+/\d+\)\s*', ' ', event_name)
            event_name = re.sub(r'\s*\([A-Za-z]+\)\s*', ' ', event_name)
            # Remove trailing spaces
            event_name = event_name.strip()
            
            # Format time and event name
            output.append(f"{event_time.strftime('%H:%M')} - {impact_emoji} {event_name}")
        
        # Add empty line between currency groups
        output.append("")
    
    output.append("Note: Only showing events scheduled for today.")
    
    return "\n".join(output)

async def test_calendar_format():
    # Create sample data
    now = datetime.now()
    events = [
        {
            'timestamp': (now + timedelta(hours=2)).timestamp(),
            'country': 'Japan',
            'impact': 1,
            'name': 'Capacity Utilization (MoM) (Feb)',
            'fore': '',
            'prev': '4.5%',
            'bold': '-1.1%',
            'signal': None,
            'type': 'release'
        },
        {
            'timestamp': (now + timedelta(hours=2)).timestamp(),
            'country': 'Japan',
            'impact': 2,
            'name': 'Industrial Production (MoM) (Feb)',
            'fore': '2.5%',
            'prev': '-1.1%',
            'bold': '2.3%',
            'signal': None,
            'type': 'release'
        },
        {
            'timestamp': (now + timedelta(hours=4)).timestamp(),
            'country': 'Switzerland',
            'impact': 2,
            'name': 'PPI (MoM) (Mar)',
            'fore': '0.2%',
            'prev': '0.3%',
            'bold': '0.1%',
            'signal': None,
            'type': 'release'
        },
        {
            'timestamp': (now + timedelta(hours=4)).timestamp(),
            'country': 'Switzerland',
            'impact': 1,
            'name': 'PPI (YoY) (Mar)',
            'fore': '',
            'prev': '-0.1%',
            'bold': '-0.1%',
            'signal': None,
            'type': 'release'
        },
        {
            'timestamp': (now + timedelta(hours=7, minutes=30)).timestamp(),
            'country': 'Euro Zone',
            'impact': 1,
            'name': 'ECOFIN Meetings',
            'fore': '',
            'prev': '',
            'bold': '',
            'signal': None,
            'type': 'speech'
        },
        {
            'timestamp': (now + timedelta(hours=8, minutes=30)).timestamp(),
            'country': 'United States',
            'impact': 2,
            'name': 'OPEC Monthly Report',
            'fore': '',
            'prev': '',
            'bold': '',
            'signal': None,
            'type': 'report'
        },
        {
            'timestamp': (now + timedelta(hours=10, minutes=0)).timestamp(),
            'country': 'Canada',
            'impact': 1,
            'name': 'New Motor Vehicle Sales (MoM) (Feb)',
            'fore': '',
            'prev': '121.6K',
            'bold': '',
            'signal': None,
            'type': 'release'
        }
    ]
    
    # Format the message
    formatted_message = _format_telegram_message(events)
    
    # Print the formatted message
    print(formatted_message)
    
    # Print the target format example
    print("\n\nTarget format example:")
    print("📅 Economic Calendar\n\nDate: April 14, 2025\n\nImpact: 🔴 High   🟠 Medium   🟢 Low\n")
    print("🇯🇵 JPY\n08:30 - 🟢 Tokyo CPI\n08:30 - 🔴 GDP Growth Rate QoQ\n08:37 - 🟠 Industrial Production MoM\n")
    print("🇺🇸 USD\n08:39 - 🔴 CPI MoM\n08:40 - 🔴 GDP Growth Rate QoQ\n08:55 - 🟠 Retail Sales MoM\n")

if __name__ == "__main__":
    asyncio.run(test_calendar_format()) 