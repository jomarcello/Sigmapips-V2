import os
import logging
import aiohttp
import pytz
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)

class EconomicCalendarService:
    def __init__(self):
        """Initialize calendar service"""
        # Get API key from environment variable or use fallback
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "your-deepseek-api-key")
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def get_economic_calendar(self, instrument: str = None) -> str:
        """Get economic calendar data"""
        try:
            # Fetch calendar data using DeepSeek
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

    async def _fetch_calendar_data(self) -> str:
        """Fetch economic calendar data using DeepSeek API"""
        try:
            # Get current date in EST timezone
            est = pytz.timezone('US/Eastern')
            current_date = datetime.now(est).strftime("%Y-%m-%d")
            
            # Use DeepSeek API to get calendar data
            prompt = f"""Search and analyze ALL economic calendar events for today ({current_date}) from Investing.com.

            IMPORTANT: 
            - Include ALL events listed for today ({current_date}) regardless of confirmation status
            - Maintain the exact order as shown on Investing.com
            - Include ALL events for the specified currencies, even low impact ones
            - Use the exact time format as displayed on Investing.com

            1. Check the following currencies in this exact order:
            - EUR (Eurozone)
            - USD (United States) 
            - GBP (United Kingdom)
            - JPY (Japan)
            - CHF (Switzerland)
            - AUD (Australia)
            - NZD (New Zealand)
            - Include other currencies if they have high impact events

            2. Format each event exactly like this:
            🇪🇺 Eurozone (EUR):
            ⏰ [EXACT TIME] EST - [EVENT NAME]
            [IMPACT EMOJI] [IMPACT LEVEL]
            Actual: [ACTUAL if available]
            Forecast: [FORECAST if available]
            Previous: [PREVIOUS if available]

            Use these impact levels:
            🔴 for High Impact (Interest Rate Decisions, NFP, GDP)
            🟡 for Medium Impact (Trade Balance, Retail)
            ⚪ for Low Impact (Minor indicators)

            For currencies with no events today, show:
            "No confirmed events scheduled for today."

            End with:
            -------------------
            🔴 High Impact
            🟡 Medium Impact
            ⚪ Low Impact"""

            # Prepare payload for DeepSeek API
            payload = {
                "model": "deepseek-chat",
                "messages": [{
                    "role": "system",
                    "content": f"""You are a real-time economic calendar analyst. Your task is:
                    1. Go to Investing.com's Economic Calendar and extract ALL events listed for {current_date}
                    2. Include ALL events regardless of confirmation status
                    3. Maintain the exact same order as shown on the website
                    4. Convert times to EST timezone if needed
                    5. Include ALL actual/forecast/previous values exactly as shown
                    6. Do not filter out any events for the specified currencies
                    7. If you're unsure about an event's impact level, default to Medium Impact"""
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
                        
                        # Add timestamp to the data
                        current_time = datetime.now(est).strftime("%H:%M EST")
                        calendar_data = f"Last update: {current_time}\n\n{calendar_data}"
                        
                        return calendar_data
                    else:
                        error_text = await response.text()
                        logger.error(f"DeepSeek API error: {response.status}, {error_text}")
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
