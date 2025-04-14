import urllib
import urllib.request
from urllib.error import HTTPError
import logging
import asyncio
import re

from bs4 import BeautifulSoup
import datetime
import arrow

logger = logging.getLogger(__name__)

class Good():
    def __init__(self):
        self.value = "+"
        self.name = "good"

    def __repr__(self):
        return "<Good(value='%s')>" % (self.value)


class Bad():
    def __init__(self):
        self.value = "-"
        self.name = "bad"

    def __repr__(self):
        return "<Bad(value='%s')>" % (self.value)


class Unknow():
    def __init__(self):
        self.value = "?"
        self.name = "unknow"

    def __repr__(self):
        return "<Unknow(value='%s')>" % (self.value)        


# Calendar data result class to ensure compatibility with bot
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
    
    def __str__(self):
        if self.error:
            return f"Error: {self.message}"
        return f"Calendar with {len(self.events)} events"


# Rename class to be very explicit
class InvestingCalendarServiceImpl():
    def __init__(self, uri='https://www.investing.com/economic-calendar/'):
        self.uri = uri
        self.req = urllib.request.Request(uri)
        self.req.add_header('User-Agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/51.0.2704.103 Safari/537.36')
        self.result = []
        self.major_countries = [
            'United States',
            'Euro Zone', 
            'United Kingdom',
            'Japan',
            'Switzerland',
            'Canada',
            'Australia',
            'New Zealand'
        ]
    
    # Add compatibility method for existing bot interface
    async def get_calendar(self, currency_pair=None):
        """Compatibility method for the existing bot interface that calls get_calendar"""
        logger.info("get_calendar called with currency_pair: %s", currency_pair)
        try:
            # Get raw formatted message
            formatted_message = await self.get_calendar_events()
            
            # Return in expected format with events and message
            return CalendarResult(
                events=[],  # Bot might not use actual events if we provide a formatted message
                message=formatted_message,
                error=False
            )
        except Exception as e:
            logger.error(f"Error in get_calendar: {str(e)}")
            return CalendarResult(
                events=[],
                message=f"❌ Fout bij ophalen economische kalender: {str(e)}",
                error=True
            )

    async def get_calendar_events(self):
        """
        Fetch economic calendar events asynchronously
        Returns formatted events for Telegram
        """
        try:
            # Run blocking HTTP request in thread pool
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, self._fetch_news)
            
            # Get today's date
            today = datetime.datetime.now().date()
            
            # Filter and sort events
            today_events = []
            for result in results:
                event_date = datetime.datetime.fromtimestamp(result['timestamp']).date()
                if event_date == today:
                    today_events.append(result)
            
            # Sort by timestamp
            today_events.sort(key=lambda x: x['timestamp'])
            
            # Format for Telegram
            return self._format_telegram_message(today_events)
            
        except Exception as e:
            logger.error(f"Error fetching calendar events: {str(e)}")
            raise

    def _fetch_news(self):
        """Internal method to fetch news from Investing.com"""
        try:
            response = urllib.request.urlopen(self.req)
            
            html = response.read()
            
            soup = BeautifulSoup(html, "html.parser")

            # Find event item fields
            table = soup.find('table', {"id": "economicCalendarData"})
            tbody = table.find('tbody')
            rows = tbody.find_all('tr', {"class": "js-event-item"})

            self.result = []
            for tr in rows:
                news = {'timestamp': None,
                        'country': None,
                        'impact': None,
                        'url': None,
                        'name': None,
                        'bold': None,
                        'fore': None,
                        'prev': None,
                        'signal': None,
                        'type': None}
                
                _datetime = tr.attrs['data-event-datetime']
                news['timestamp'] = arrow.get(_datetime, "YYYY/MM/DD HH:mm:ss").timestamp()

                cols = tr.find('td', {"class": "flagCur"})
                flag = cols.find('span')

                news['country'] = flag.get('title')

                # Skip if not a major currency country
                if news['country'] not in self.major_countries:
                    continue

                impact = tr.find('td', {"class": "sentiment"})
                bull = impact.find_all('i', {"class": "grayFullBullishIcon"})

                news['impact'] = len(bull)

                event = tr.find('td', {"class": "event"})
                a = event.find('a')

                news['url'] = "https://www.investing.com{}".format(a['href'])
                news['name'] = a.text.strip()

                # Determite type of event
                legend = event.find('span', {"class": "smallGrayReport"})
                if legend:
                    news['type'] = "report"

                legend = event.find('span', {"class": "audioIconNew"})
                if legend:
                    news['type'] = "speech"

                legend = event.find('span', {"class": "smallGrayP"})
                if legend:
                    news['type'] = "release"
                
                legend = event.find('span', {"class": "sandClock"})
                if legend:
                    news['type'] = "retrieving data"                    

                bold = tr.find('td', {"class": "bold"})

                if bold.text != '':
                    news['bold'] = bold.text.strip()
                else:
                    news['bold'] = ''

                fore = tr.find('td', {"class": "fore"})
                news['fore'] = fore.text.strip()

                prev = tr.find('td', {"class": "prev"})
                news['prev'] = prev.text.strip()

                if "blackFont" in bold['class']:
                    news['signal'] = Unknow()

                elif "redFont" in bold['class']:
                    news['signal'] = Bad()

                elif "greenFont" in bold['class']:
                    news['signal'] = Good()

                else:
                    news['signal'] = Unknow()

                self.result.append(news)
        
        except HTTPError as error:
            logger.error(f"HTTP Error fetching calendar: {error.code}")
            raise

        return self.result

    def _format_telegram_message(self, events):
        """Format events for Telegram message"""
        output = []
        # Use HTML formatting for the title and ensure correct emoji
        output.append("<b>📅 Economic Calendar</b>")
        
        # Get the current date in different formats
        today = datetime.datetime.now()
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
                event_time = datetime.datetime.fromtimestamp(result['timestamp'])
                
                # Format impact level
                impact_emoji = "🟢"  # Default Low
                if result['impact'] == 3:
                    impact_emoji = "🔴"
                elif result['impact'] == 2:
                    impact_emoji = "🟠"
                
                # Simplify event name by removing parentheses details where possible
                event_name = result['name']
                # Remove quarter indicators (Q1), (Q2) etc.
                event_name = re.sub(r'\s*\(Q[1-4]\)\s*', ' ', event_name)
                # Remove month/year indicators like (Mar), (Apr), etc.
                event_name = re.sub(r'\s*\([A-Za-z]{3}\)\s*', ' ', event_name)
                # Remove change period indicators like (MoM), (YoY), (QoQ)
                event_name = re.sub(r'\s*\((?:MoM|YoY|QoQ)\)\s*', ' ', event_name)
                # Remove date patterns like (Jan/2024)
                event_name = re.sub(r'\s*\([A-Za-z]{3}/\d{4}\)\s*', ' ', event_name)
                # Remove trailing spaces
                event_name = event_name.strip()
                
                # Format time and event name
                output.append(f"{event_time.strftime('%H:%M')} - {impact_emoji} {event_name}")
            
            # Add empty line between currency groups
            output.append("")
        
        # Only add the note once
        # Note: Verwijder deze notitie omdat het anders dubbel kan verschijnen als bot.py dit ook toevoegt
        # output.append("Note: Only showing events scheduled for today.")
        
        return "\n".join(output)

# Export the class with the name that is imported in __init__.py
InvestingCalendarService = InvestingCalendarServiceImpl 
