import os
import logging
from typing import Dict, Any
import aiohttp
from datetime import datetime, timezone
import pytz

logger = logging.getLogger(__name__)

class EconomicCalendarService:
    def __init__(self):
        """Initialize calendar service"""
        self.api_key = "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"
        self.api_url = "https://api.perplexity.ai/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def get_economic_calendar(self, instrument: str = None) -> str:
        """Get economic calendar data"""
        try:
            # Fetch calendar data
            calendar_data = await self._fetch_calendar_data()
            
            if not calendar_data:
                return "No economic calendar data available at this time."
            
            # Filter by instrument if provided
            if instrument:
                filtered_data = self._filter_by_instrument(calendar_data, instrument)
            else:
                filtered_data = calendar_data
            
            # Format the data
            formatted_data = self._format_calendar_data(filtered_data)
            
            # Verwijder de Investing.com vermelding
            formatted_data = formatted_data.replace("from Investing.com, formatted as requested:", "")
            
            return formatted_data
            
        except Exception as e:
            logger.error(f"Error getting economic calendar: {str(e)}")
            return "Error retrieving economic calendar data."

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

    async def _fetch_calendar_data(self) -> str:
        """Fetch economic calendar data from API"""
        try:
            # Krijg de huidige datum in EST timezone
            est = pytz.timezone('US/Eastern')
            current_date = datetime.now(est).strftime("%Y-%m-%d")
            
            prompt = f"""Zoek en analyseer de economische kalender events voor vandaag ({current_date}) van Investing.com.

            BELANGRIJK: 
            - Gebruik ALLEEN events van vandaag ({current_date})
            - Check de actuele tijden in EST timezone
            - Vermeld ALLEEN bevestigde events
            - Sorteer events chronologisch per valuta
            
            1. Check de volgende valuta's in deze volgorde:
            - EUR (Eurozone)
            - USD (Verenigde Staten) 
            - GBP (Verenigd Koninkrijk)
            - JPY (Japan)
            - CHF (Zwitserland)
            - AUD (Australië)
            - NZD (Nieuw-Zeeland)

            2. Formatteer elk event precies zo:
            🇪🇺 Eurozone (EUR):
            ⏰ [EXACTE TIJD] EST - [EVENT NAAM]
            [IMPACT EMOJI] [IMPACT LEVEL]
            Actueel: [ACTUAL als beschikbaar]
            Verwacht: [FORECAST als beschikbaar]
            Vorig: [PREVIOUS als beschikbaar]

            Gebruik deze impact levels:
            🔴 voor High Impact (Rentebeslissingen, NFP, GDP)
            🟡 voor Medium Impact (Handelsbalans, retail)
            ⚪ voor Low Impact (Kleine indicatoren)

            Voor valuta's zonder events vandaag, toon:
            "Geen bevestigde events gepland voor vandaag."

            Eindig met:
            -------------------
            🔴 High Impact
            🟡 Medium Impact
            ⚪ Low Impact"""

            payload = {
                "model": "sonar-pro",
                "messages": [{
                    "role": "system",
                    "content": f"""Je bent een real-time economische kalender analist. Je taak is:
                    1. Check Investing.com's Economic Calendar voor events op {current_date}
                    2. Gebruik ALLEEN bevestigde events voor vandaag
                    3. Sorteer events chronologisch per valuta
                    4. Gebruik exacte tijden in EST timezone
                    5. Voeg actuele/verwachte/vorige waarden toe indien beschikbaar
                    6. Markeer impact levels nauwkeurig op basis van event type
                    7. Verifieer dat alle data up-to-date is voor vandaag"""
                }, {
                    "role": "user",
                    "content": prompt
                }],
                "temperature": 0.1
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        calendar_data = data['choices'][0]['message']['content']
                        
                        # Voeg timestamp toe aan de data
                        current_time = datetime.now(est).strftime("%H:%M EST")
                        calendar_data = f"Laatste update: {current_time}\n\n{calendar_data}"
                        
                        return calendar_data
                    else:
                        logger.error(f"API error: {response.status}")
                        return self._get_fallback_calendar()

        except Exception as e:
            logger.error(f"Error fetching calendar data: {str(e)}")
            return self._get_fallback_calendar()

    def _filter_by_instrument(self, calendar_data: str, instrument: str) -> str:
        """Filter calendar data by instrument"""
        try:
            # Extract currency from instrument
            if len(instrument) >= 3:
                currency = instrument[:3]  # First 3 chars, e.g., "EUR" from "EURUSD"
            else:
                return calendar_data  # Can't filter, return all
            
            # Split by currency sections
            sections = calendar_data.split('\n\n')
            filtered_sections = []
            
            for section in sections:
                # Check if this section is for our currency
                if currency in section or currency.upper() in section:
                    filtered_sections.append(section)
            
            # If no matching sections, return all data
            if not filtered_sections:
                return calendar_data
            
            # Join filtered sections with headers
            result = '\n\n'.join(filtered_sections)
            
            # Add the legend at the end
            if "-------------------" in calendar_data:
                legend = calendar_data.split("-------------------")[1]
                result += "\n\n-------------------" + legend
                
            return result
            
        except Exception as e:
            logger.error(f"Error filtering calendar data: {str(e)}")
            return calendar_data  # Return original on error

    def _format_calendar_data(self, calendar_data: str) -> str:
        """Format calendar data for display"""
        try:
            # Add header
            formatted = "📅 <b>Economic Calendar</b>\n\n"
            formatted += calendar_data
            
            return formatted
            
        except Exception as e:
            logger.error(f"Error formatting calendar data: {str(e)}")
            return calendar_data
