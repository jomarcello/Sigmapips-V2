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
                    "content": "You are a financial analyst focused on providing economic calendar data."
                }, {
                    "role": "user",
                    "content": """
                    Retrieve today's economic calendar for all major currencies (USD, EUR, GBP, JPY, AUD, CAD, CHF, and NZD). 
                    Include the event time (with time zone), event name, impact level (High, Medium, Low), 
                    previous value, forecasted value, and actual value (if available). 
                    The response should be structured and easy to process.
                    """
                }]
            }
            
            logger.info("Fetching economic calendar data")
            
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
            Format the following economic calendar data into a structured table where:
            • Convert ALL times to EST timezone
            • The time appears first
            • The event name appears second
            • The impact level follows as an emoji
                🔴 Red Circle for high-impact events
                🟡 Yellow Circle for medium-impact events
                ⚪ White Circle for low-impact events
            • Do NOT include Previous/Forecast/Actual values

            The format should look like this:

            📅 Economic Calendar for {today}

            🇺🇸 United States (USD):
            ⏰ [Time] EST – [Event Name] 🔴

            🇪🇺 Eurozone (EUR):
            ⏰ [Time] EST – [Event Name] 🟡

            [At the end of the calendar, add:]
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
                    "content": "You are a financial calendar specialist. Format economic calendar data in a clean, structured way. Convert all times to EST timezone, add one empty line between each country section, and do NOT include Previous/Forecast/Actual values."
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
