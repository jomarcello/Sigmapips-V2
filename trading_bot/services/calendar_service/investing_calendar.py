import urllib
import urllib.request
from urllib.error import HTTPError
import logging
import asyncio

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
        return await self.get_calendar_events()

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
            return "❌ Error fetching economic calendar events"

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
        output.append(f"📅 *Economische Kalender - {datetime.datetime.now().strftime('%d-%m-%Y')}*")
        output.append("=" * 30)
        
        for result in events:
            # Convert to Malaysian time (UTC+8)
            event_time = datetime.datetime.fromtimestamp(result['timestamp'])
            malaysian_time = event_time + datetime.timedelta(hours=8)
            
            impact_stars = "⭐" * result['impact']
            country_emoji = {
                'United States': '🇺🇸',
                'Euro Zone': '🇪🇺',
                'United Kingdom': '🇬🇧',
                'Japan': '🇯🇵',
                'Switzerland': '🇨🇭',
                'Canada': '🇨🇦',
                'Australia': '🇦🇺',
                'New Zealand': '🇳🇿'
            }.get(result['country'], '🌍')
            
            output.append(f"\n*{malaysian_time.strftime('%H:%M')}* {country_emoji} {result['country']}")
            output.append(f"📊 {result['name']}")
            output.append(f"Impact: {impact_stars}")
            
            if result['fore']:
                output.append(f"Voorspelling: {result['fore']}")
            if result['prev']:
                output.append(f"Vorige: {result['prev']}")
            if result['bold']:
                output.append(f"Actueel: {result['bold']}")
            
            output.append(f"Signaal: {result['signal'].value}")
            output.append("-" * 20)
        
        return "\n".join(output)

# Export the class with the name that is imported in __init__.py
InvestingCalendarService = InvestingCalendarServiceImpl 
