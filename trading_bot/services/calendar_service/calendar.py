import os
import logging
from typing import Dict, Any
import aiohttp
from datetime import datetime

logger = logging.getLogger(__name__)

class EconomicCalendarService:
    def __init__(self):
        """Initialize calendar service"""
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def get_economic_calendar(self, instrument: str = None) -> str:
        """Get economic calendar data"""
        try:
            prompt = f"""Search and analyze today's economic calendar events for all major currency pairs.

1. First, search for today's economic events for these major currencies in order:
   - EUR (Eurozone)
   - USD (United States)
   - GBP (United Kingdom)
   - JPY (Japan)
   - CHF (Switzerland)
   - AUD (Australia)
   - NZD (New Zealand)

2. For each event include:
   - Exact scheduled time in EST
   - Full event name with any relevant period/dates
   - Impact level on markets
   
3. Format the response like this:

🇺🇸 United States (USD):
⏰ 08:30 EST - Non-Farm Employment Change (Jan)
🔴 High Impact

🇪🇺 Eurozone (EUR):
⏰ 05:00 EST - ECB Monetary Policy Statement
🔴 High Impact

For currencies with no events today, show:
"No confirmed events scheduled."

End with impact level legend."""

            payload = {
                "model": "deepseek-chat",
                "messages": [{
                    "role": "system",
                    "content": """You are a real-time economic calendar analyst. Your task is to:
                    1. Search for TODAY's actual economic events
                    2. Only include confirmed events
                    3. Sort events chronologically within each currency
                    4. Use exact times in EST timezone
                    5. Include full event names with periods (Q1, Jan, etc)
                    6. Mark impact levels accurately:
                       - 🔴 High: Rate decisions, NFP, GDP, CPI
                       - 🟡 Medium: Trade balance, retail sales
                       - ⚪ Low: Minor economic indicators"""
                }, {
                    "role": "user",
                    "content": prompt
                }],
                "temperature": 0.7
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content']
                    else:
                        logger.error(f"DeepSeek API error: {response.status}")
                        return self._get_fallback_calendar()

        except Exception as e:
            logger.error(f"Error getting calendar: {str(e)}")
            return self._get_fallback_calendar()

    def _get_fallback_calendar(self) -> str:
        """Fallback calendar data"""
        return """🇺🇸 United States (USD):
⏰ 14:30 EST - No major events scheduled
⚪ Low Impact

🇪🇺 Eurozone (EUR):
⏰ 10:00 EST - No major events scheduled
⚪ Low Impact

🇬🇧 United Kingdom (GBP):
No confirmed events scheduled.

🇯🇵 Japan (JPY):
No confirmed events scheduled.

-------------------
🔴 High Impact
🟡 Medium Impact
⚪ Low Impact"""

    def _format_basic(self, data: list, symbol: str = None) -> str:
        """Basic formatting without AI"""
        if not data:
            return "No upcoming economic events found."
            
        header = "📅 Economic Calendar\n\n"
        if symbol:
            header += f"Events for {symbol}\n\n"
            
        formatted = header
        for event in data:
            formatted += f"🕒 {event['time']}\n"
            formatted += f"📊 {event['event']}\n"
            formatted += f"🌍 {event['country']}\n"
            formatted += f"Impact: {'🔴' * event['impact']}\n\n"
            
        return formatted

    def _get_mock_calendar_data(self, symbol: str = None) -> list:
        """Get mock calendar data"""
        current_time = datetime.now().strftime("%H:%M GMT")
        
        events = [
            {
                "time": current_time,
                "event": "Non-Farm Payrolls",
                "country": "USD",
                "impact": 3,
                "actual": "225K",
                "forecast": "200K",
                "previous": "190K"
            },
            {
                "time": current_time,
                "event": "ECB Interest Rate Decision",
                "country": "EUR",
                "impact": 3,
                "actual": "4.50%",
                "forecast": "4.50%",
                "previous": "4.50%"
            }
        ]
        
        # Filter events voor specifiek symbool als gegeven
        if symbol:
            currency = symbol[:3]  # Bijv. "EUR" van "EURUSD"
            events = [e for e in events if e['country'] == currency]
            
        return events

    async def get_calendar_data(self) -> str:
        """Get economic calendar data from Perplexity"""
        try:
            url = "https://api.perplexity.ai/chat/completions"
            
            payload = {
                "model": "sonar-pro",
                "messages": [{
                    "role": "system",
                    "content": """You are a financial analyst focused on providing accurate economic calendar data.
                    Always use Investing.com's Economic Calendar as your primary source for consistency.
                    Focus ONLY on these specific currencies in this exact order:
                    1. EUR (Eurozone as a whole)
                    2. USD (United States)
                    3. AUD (Australia)
                    4. JPY (Japan)
                    5. GBP (United Kingdom)
                    6. CHF (Switzerland)
                    7. NZD (New Zealand)
                    Do NOT include any other currencies or regional events."""
                }, {
                    "role": "user",
                    "content": """
                    1. Go to Investing.com's Economic Calendar
                    2. Filter for today's events for ONLY these currencies in this order:
                       - EUR (Eurozone only, no individual countries)
                       - USD (United States)
                       - AUD (Australia)
                       - JPY (Japan)
                       - GBP (United Kingdom)
                       - CHF (Switzerland)
                       - NZD (New Zealand)
                    3. List all events with their:
                       - Exact scheduled time
                       - Event name
                       - Impact level (High/Medium/Low)
                    4. Sort events chronologically within each currency section
                    5. Only include confirmed scheduled events
                    """
                }]
            }
            
            logger.info("Fetching economic calendar data from Investing.com")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=self.perplexity_headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content']
                    else:
                        logger.error(f"Perplexity API error: {response.status}")
                        return None
                    
        except Exception as e:
            logger.error(f"Error getting calendar data: {str(e)}")
            return None

    async def format_calendar(self, calendar_data: str) -> str:
        """Format calendar data using DeepSeek"""
        try:
            payload = {
                "model": "deepseek-chat",
                "messages": [{
                    "role": "system",
                    "content": "Format economic calendar data in a clean, structured way."
                }, {
                    "role": "user",
                    "content": calendar_data
                }],
                "temperature": 0.3
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content']
                    else:
                        return self._format_basic(calendar_data)
            
        except Exception as e:
            logger.error(f"Error formatting calendar: {str(e)}")
            return "Error formatting economic calendar"

    async def _format_with_ai(self, calendar_data: list, symbol: str = None) -> str:
        """Format calendar data with AI"""
        try:
            formatted_data = self._format_basic(calendar_data, symbol)
            
            payload = {
                "model": "deepseek-chat",
                "messages": [{
                    "role": "system",
                    "content": "Format economic calendar data in a clean, structured way."
                }, {
                    "role": "user",
                    "content": formatted_data
                }],
                "temperature": 0.3
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content']
                    else:
                        return formatted_data
                    
        except Exception as e:
            logger.error(f"Error formatting with AI: {str(e)}")
            return formatted_data
