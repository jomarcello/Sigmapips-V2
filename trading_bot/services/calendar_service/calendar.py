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
        self.openai = AsyncOpenAI()

    async def get_economic_calendar(self, symbol: str = None) -> str:
        """Get economic calendar data with fallback formatting"""
        try:
            # Basis kalender data (dit zou je kunnen vervangen met echte API data)
            calendar_data = self._get_mock_calendar_data(symbol)
            
            try:
                # Probeer AI formatting
                formatted_data = await self._format_with_ai(calendar_data, symbol)
                return formatted_data
            except Exception as e:
                logger.error(f"Error formatting calendar: {str(e)}")
                # Fallback naar basic formatting
                return self._format_basic(calendar_data, symbol)
                
        except Exception as e:
            logger.error(f"Error getting calendar data: {str(e)}")
            return "Error fetching economic calendar"

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
        return [
            {
                "time": "14:30 GMT",
                "event": "Non-Farm Payrolls",
                "country": "USD",
                "impact": 3
            },
            {
                "time": "12:00 GMT",
                "event": "ECB Interest Rate Decision",
                "country": "EUR",
                "impact": 3
            },
            # Voeg meer mock events toe indien nodig
        ]

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
