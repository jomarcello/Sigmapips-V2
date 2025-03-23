# Calendar service package
# This file should be kept minimal to avoid import cycles

import os
import ssl
import asyncio
import logging
import aiohttp
import redis
import json
from typing import Dict, Any, List, Optional
import base64
import time
import re
import random
from datetime import datetime, timedelta

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    CallbackContext,
    MessageHandler,
    filters,
    PicklePersistence
)
from telegram.constants import ParseMode

from trading_bot.services.database.db import Database
from trading_bot.services.chart_service.chart import ChartService
from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
from trading_bot.services.payment_service.stripe_service import StripeService
from trading_bot.services.payment_service.stripe_config import get_subscription_features

# Try to import AI services, but provide fallbacks if they don't exist
try:
    from trading_bot.services.ai_service.tavily_service import TavilyService
    from trading_bot.services.ai_service.deepseek_service import DeepseekService
    HAS_AI_SERVICES = True
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("AI services not available. Using fallback implementations.")
    HAS_AI_SERVICES = False
    
    # Define fallback classes if imports fail
    class TavilyService:
        """Fallback Tavily service implementation"""
        async def search(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
            """Return mock search results"""
            return [
                {
                    "title": "Economic Calendar - Today's Economic Events",
                    "url": "https://www.forexfactory.com/calendar",
                    "content": f"Economic calendar showing major events for today. The calendar includes data for USD, EUR, GBP, JPY, AUD, CAD, CHF, and NZD currencies. Upcoming events include interest rate decisions, employment reports, and inflation data. Each event is marked with an impact level (high, medium, or low)."
                }
            ]
            
    class DeepseekService:
        """Fallback DeepSeek service implementation"""
        async def generate_completion(self, prompt: str, model: str = "deepseek-chat", temperature: float = 0.2) -> str:
            """Return mock completion"""
            if "economic calendar" in prompt.lower():
                # Mock economic calendar JSON
                return """```json
{
  "USD": [
    {
      "time": "08:30 EST",
      "event": "Initial Jobless Claims",
      "impact": "Medium"
    },
    {
      "time": "08:30 EST",
      "event": "Trade Balance",
      "impact": "Medium"
    },
    {
      "time": "15:30 EST",
      "event": "Fed Chair Speech",
      "impact": "High"
    }
  ],
  "EUR": [
    {
      "time": "07:45 EST",
      "event": "ECB Interest Rate Decision",
      "impact": "High"
    },
    {
      "time": "08:30 EST",
      "event": "ECB Press Conference",
      "impact": "High"
    }
  ],
  "GBP": [],
  "JPY": [],
  "CHF": [],
  "AUD": [],
  "NZD": [],
  "CAD": []
}```"""
            else:
                return "Fallback completion: DeepSeek API not available"

logger = logging.getLogger(__name__)

# Callback data constants
CALLBACK_ANALYSIS_TECHNICAL = "analysis_technical"
CALLBACK_ANALYSIS_SENTIMENT = "analysis_sentiment"
CALLBACK_ANALYSIS_CALENDAR = "analysis_calendar"
# ... rest of constants

# Major currencies to focus on
MAJOR_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"]

# Map of instruments to their corresponding currencies
INSTRUMENT_CURRENCY_MAP = {
    # Special case for global view
    "GLOBAL": MAJOR_CURRENCIES,
    
    # Forex
    "EURUSD": ["EUR", "USD"],
    "GBPUSD": ["GBP", "USD"],
    "USDJPY": ["USD", "JPY"],
    "USDCHF": ["USD", "CHF"],
    "AUDUSD": ["AUD", "USD"],
    "NZDUSD": ["NZD", "USD"],
    "USDCAD": ["USD", "CAD"],
    "EURGBP": ["EUR", "GBP"],
    "EURJPY": ["EUR", "JPY"],
    "GBPJPY": ["GBP", "JPY"],
    
    # Indices (mapped to their related currencies)
    "US30": ["USD"],
    "US100": ["USD"],
    "US500": ["USD"],
    "UK100": ["GBP"],
    "GER40": ["EUR"],
    "FRA40": ["EUR"],
    "ESP35": ["EUR"],
    "JP225": ["JPY"],
    "AUS200": ["AUD"],
    
    # Commodities (mapped to USD primarily)
    "XAUUSD": ["USD", "XAU"],  # Gold
    "XAGUSD": ["USD", "XAG"],  # Silver
    "USOIL": ["USD"],          # Oil (WTI)
    "UKOIL": ["USD", "GBP"],   # Oil (Brent)
    
    # Crypto
    "BTCUSD": ["USD", "BTC"],
    "ETHUSD": ["USD", "ETH"],
    "LTCUSD": ["USD", "LTC"],
    "XRPUSD": ["USD", "XRP"]
}

# Impact levels and their emoji representations
IMPACT_EMOJI = {
    "High": "🔴",
    "Medium": "🟡",
    "Low": "⚪"
}

# Currency to flag emoji mapping
CURRENCY_FLAG = {
    "USD": "🇺🇸",
    "EUR": "🇪🇺",
    "GBP": "🇬🇧",
    "JPY": "🇯🇵",
    "CHF": "🇨🇭",
    "AUD": "🇦🇺",
    "NZD": "🇳🇿",
    "CAD": "🇨🇦"
}

# De hoofdklasse voor de calendar service
class EconomicCalendarService:
    """Service for retrieving economic calendar data"""
    
    def __init__(self, tavily_service: Optional[TavilyService] = None, deepseek_service: Optional[DeepseekService] = None):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing EconomicCalendarService")
        self.tavily_service = tavily_service or TavilyService()
        self.deepseek_service = deepseek_service or DeepseekService()
        self.cache = {}
        self.cache_time = {}
        self.cache_expiry = 3600  # 1 hour in seconds
        
    async def get_instrument_calendar(self, instrument: str) -> str:
        """Get economic calendar events relevant to an instrument"""
        try:
            self.logger.info(f"Getting economic calendar for {instrument}")
            
            # Check cache first
            now = time.time()
            if instrument in self.cache and (now - self.cache_time.get(instrument, 0)) < self.cache_expiry:
                self.logger.info(f"Using cached calendar data for {instrument}")
                return self.cache[instrument]
            
            # Get currencies related to this instrument
            currencies = INSTRUMENT_CURRENCY_MAP.get(instrument, [])
            
            # If no currencies found, use USD as default
            if not currencies:
                currencies = ["USD"]
                
            # Filter to only include major currencies
            currencies = [c for c in currencies if c in MAJOR_CURRENCIES]
            
            # Get calendar data for these currencies
            calendar_data = await self._get_economic_calendar_data(currencies)
            
            # Format the response
            formatted_response = self._format_calendar_response(calendar_data, instrument)
            
            # Cache the result
            self.cache[instrument] = formatted_response
            self.cache_time[instrument] = now
            
            return formatted_response
            
        except Exception as e:
            self.logger.error(f"Error getting economic calendar: {str(e)}")
            self.logger.exception(e)
            return self._get_fallback_calendar(instrument)
            
    async def _get_economic_calendar_data(self, currencies: List[str]) -> Dict:
        """Use Tavily to get economic calendar data and Deepseek to parse it"""
        try:
            # Form the search query for Tavily
            today = datetime.now().strftime("%B %d, %Y")
            query = f"economic calendar events today {today} for {', '.join(currencies)} currencies"
            
            # Search using Tavily
            search_results = await self.tavily_service.search(query)
            
            if not search_results:
                self.logger.warning("No search results from Tavily")
                return {}
                
            # Parse the results with DeepSeek
            prompt = f"""
Extract today's ({today}) economic calendar events for the following major currencies: {', '.join(MAJOR_CURRENCIES)}.
Format the data as a structured JSON with the following format:
{{
    "EUR": [
        {{
            "time": "07:45 EST",
            "event": "ECB Interest Rate Decision",
            "impact": "High"
        }},
        ...
    ],
    "USD": [
        {{
            "time": "08:30 EST",
            "event": "Initial Jobless Claims",
            "impact": "Medium"
        }},
        ...
    ],
    ...
}}

For each currency, include the time (in EST timezone), event name, and impact level (High, Medium, or Low).
If there are no events for a currency, include an empty array.
Only include confirmed events for today.

Here is the search data from economic calendar sources:
{json.dumps(search_results, indent=2)}
"""
            
            # Get calendar data from DeepSeek
            calendar_json = await self.deepseek_service.generate_completion(prompt)
            
            # Try to parse the JSON
            try:
                # Extract JSON from potential markdown code blocks
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', calendar_json)
                if json_match:
                    calendar_json = json_match.group(1)
                    
                # Parse the JSON
                calendar_data = json.loads(calendar_json)
                return calendar_data
            except json.JSONDecodeError:
                self.logger.error(f"Failed to parse JSON from DeepSeek response: {calendar_json}")
                return {}
                
        except Exception as e:
            self.logger.error(f"Error getting economic calendar data: {str(e)}")
            self.logger.exception(e)
            return {}
            
    def _format_calendar_response(self, calendar_data: Dict, instrument: str) -> str:
        """Format the calendar data into a nice HTML response"""
        response = "<b>📅 Economic Calendar</b>\n\n"
        
        # If the calendar data is empty, return a simple message
        if not calendar_data:
            return response + "No major economic events scheduled for today.\n\n<i>Check back later for updates.</i>"
            
        # Sort currencies to always show in same order
        currencies = sorted(calendar_data.keys(), 
                          key=lambda x: (0 if x in MAJOR_CURRENCIES else 1, MAJOR_CURRENCIES.index(x) if x in MAJOR_CURRENCIES else 999))
        
        # Add calendar events for each currency
        for currency in currencies:
            if currency not in MAJOR_CURRENCIES:
                continue
                
            events = calendar_data.get(currency, [])
            
            # Skip if no events
            if not events:
                response += f"{CURRENCY_FLAG.get(currency, '')} {currency}:\n"
                response += "No confirmed events scheduled.\n\n"
                continue
                
            # Add currency header
            currency_name = {
                "USD": "United States",
                "EUR": "Eurozone",
                "GBP": "United Kingdom",
                "JPY": "Japan",
                "CHF": "Switzerland",
                "AUD": "Australia",
                "NZD": "New Zealand",
                "CAD": "Canada"
            }.get(currency, currency)
            
            response += f"{CURRENCY_FLAG.get(currency, '')} {currency_name} ({currency}):\n"
            
            # Sort events by time
            events = sorted(events, key=lambda x: x.get("time", "00:00"))
            
            # Add events
            for event in events:
                time = event.get("time", "")
                event_name = event.get("event", "")
                impact = event.get("impact", "Low")
                impact_emoji = IMPACT_EMOJI.get(impact, "⚪")
                
                response += f"⏰ {time} - {event_name}\n"
                response += f"{impact_emoji} {impact} Impact\n"
            
            response += "\n"
            
        # Add legend at the bottom
        response += "-------------------\n"
        response += "🔴 High Impact\n"
        response += "🟡 Medium Impact\n"
        response += "⚪ Low Impact"
        
        return response
        
    def _get_fallback_calendar(self, instrument: str) -> str:
        """Generate a fallback response if getting the calendar fails"""
        response = "<b>📅 Economic Calendar</b>\n\n"
        
        currencies = INSTRUMENT_CURRENCY_MAP.get(instrument, ["USD"])
        currencies = [c for c in currencies if c in MAJOR_CURRENCIES]
        
        # Generate some mock data based on the instrument
        today = datetime.now()
        
        # Check if it's a weekend
        if today.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
            return response + "No major economic events scheduled for today (weekend).\n\n<i>Check back on Monday for updates.</i>"
            
        # Simple simulation using day of week to determine which currencies have events
        active_currencies = []
        if today.weekday() == 0:  # Monday
            active_currencies = ["USD", "EUR"]
        elif today.weekday() == 1:  # Tuesday
            active_currencies = ["GBP", "USD", "AUD"]
        elif today.weekday() == 2:  # Wednesday
            active_currencies = ["JPY", "EUR", "USD"]
        elif today.weekday() == 3:  # Thursday
            active_currencies = ["USD", "GBP", "CHF"]
        elif today.weekday() == 4:  # Friday
            active_currencies = ["USD", "CAD", "JPY"]
            
        for currency in MAJOR_CURRENCIES:
            # Add currency header with flag
            currency_name = {
                "USD": "United States",
                "EUR": "Eurozone",
                "GBP": "United Kingdom",
                "JPY": "Japan",
                "CHF": "Switzerland",
                "AUD": "Australia",
                "NZD": "New Zealand",
                "CAD": "Canada"
            }.get(currency, currency)
            
            response += f"{CURRENCY_FLAG.get(currency, '')} {currency_name} ({currency}):\n"
            
            # Add mock events if this is an active currency
            if currency in active_currencies:
                if currency == "USD":
                    response += f"⏰ {(today.hour % 12 + 1):02d}:30 EST - Retail Sales\n"
                    response += f"{IMPACT_EMOJI['Medium']} Medium Impact\n"
                    response += f"⏰ {(today.hour % 12 + 3):02d}:00 EST - Fed Chair Speech\n"
                    response += f"{IMPACT_EMOJI['High']} High Impact\n"
                elif currency == "EUR":
                    response += f"⏰ {(today.hour % 12):02d}:45 EST - Inflation Data\n"
                    response += f"{IMPACT_EMOJI['High']} High Impact\n"
                elif currency == "GBP":
                    response += f"⏰ {(today.hour % 12 + 2):02d}:00 EST - Employment Change\n"
                    response += f"{IMPACT_EMOJI['Medium']} Medium Impact\n"
                else:
                    response += f"⏰ {(today.hour % 12 + 1):02d}:15 EST - GDP Data\n"
                    response += f"{IMPACT_EMOJI['Medium']} Medium Impact\n"
            else:
                response += "No confirmed events scheduled.\n"
                
            response += "\n"
            
        # Add legend at the bottom
        response += "-------------------\n"
        response += "🔴 High Impact\n"
        response += "🟡 Medium Impact\n"
        response += "⚪ Low Impact"
        
        return response

# Telegram service class die de calendar service gebruikt
class TelegramService:
    def __init__(self, db: Database, stripe_service=None):
        """Initialize telegram service"""
        try:
            # Sla de database op
            self.db = db
            
            # Initialiseer de services
            self.chart = ChartService()
            self.sentiment = MarketSentimentService()
            self.calendar = EconomicCalendarService()  # Direct instantiëren, geen import nodig
            
            # Rest van de initialisatie
            # ...
        except Exception as e:
            # Voeg een except block toe
            logging.error(f"Error initializing TelegramService: {str(e)}")
            raise  # Optioneel: re-raise de exceptie na het loggen
