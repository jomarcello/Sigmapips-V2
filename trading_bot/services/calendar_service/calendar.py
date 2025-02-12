import os
import logging
from typing import Dict, Any
from openai import AsyncOpenAI
import aiohttp
from datetime import datetime

logger = logging.getLogger(__name__)

class EconomicCalendarService:
    def __init__(self):
        """Initialize calendar service"""
        self.openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.perplexity_key = os.getenv("PERPLEXITY_API_KEY")
        if not self.perplexity_key:
            raise ValueError("Missing PERPLEXITY_API_KEY")
        
        # Perplexity API setup
        self.perplexity_headers = {
            "Authorization": f"Bearer {self.perplexity_key}",
            "Content-Type": "application/json"
        }
        
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
        """Format calendar data using OpenAI"""
        try:
            today = datetime.now().strftime("%B %d, %Y")
            prompt = f"""
            Format the following economic calendar data into a structured table.
            
            Rules:
            1. Convert ALL times to EST timezone
            2. The time appears first
            3. The event name appears second
            4. The impact level follows as an emoji
            5. Add TWO empty lines between each country section
            6. Only include these currencies in this exact order:
               - 🇪🇺 Eurozone (EUR)
               - 🇺🇸 United States (USD)
               - 🇦🇺 Australia (AUD)
               - 🇯🇵 Japan (JPY)
               - 🇬🇧 United Kingdom (GBP)
               - 🇨🇭 Switzerland (CHF)
               - 🇳🇿 New Zealand (NZD)

            Format example:
            📅 Economic Calendar for {today}


            🇪🇺 Eurozone (EUR):
            ⏰ [Time] EST – [Event Name] 🔴
            ⏰ [Time] EST – [Event Name] 🟡
            ⏰ [Time] EST – [Event Name] ⚪


            🇺🇸 United States (USD):
            ⏰ [Time] EST – [Event Name] 🔴
            ⏰ [Time] EST – [Event Name] 🟡


            [Continue with other countries, with TWO empty lines between them]

            ---------------
            🔴 High Impact
            🟡 Medium Impact
            ⚪ Low Impact

            Raw calendar data:
            {calendar_data}
            """

            response = await self.openai.chat.completions.create(
                model="gpt-4",
                messages=[{
                    "role": "system",
                    "content": "You are a financial calendar specialist. Format economic calendar data in a clean, structured way. Convert all times to EST timezone, add TWO empty lines between countries, and do NOT include Previous/Forecast/Actual values."
                }, {
                    "role": "user",
                    "content": prompt
                }],
                temperature=0
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Error formatting calendar: {str(e)}")
            return "Error formatting economic calendar"

    async def get_economic_calendar(self) -> str:
        """Get complete economic calendar"""
        try:
            # Get raw calendar data
            calendar_data = await self.get_calendar_data()
            if not calendar_data:
                return "Could not fetch economic calendar"
                
            # Format with OpenAI
            formatted_calendar = await self.format_calendar(calendar_data)
            return formatted_calendar
            
        except Exception as e:
            logger.error(f"Error in economic calendar: {str(e)}")
            return "Error retrieving economic calendar"
