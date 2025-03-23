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
import socket

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
            
            # First try Tavily
            self.logger.info(f"Searching for economic calendar data using Tavily")
            search_results = None
            
            try:
                # Check if Tavily is reachable with a simple socket test
                tavily_reachable = False
                try:
                    # Simple socket connection test to api.tavily.com on port 443
                    tavily_host = "api.tavily.com"
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3)  # Quick 3-second timeout
                    result = sock.connect_ex((tavily_host, 443))
                    sock.close()
                    
                    if result == 0:  # Port is open, connection successful
                        self.logger.info("Tavily API connectivity test successful")
                        tavily_reachable = True
                    else:
                        self.logger.warning(f"Tavily API connectivity test failed with result: {result}")
                except socket.error as e:
                    self.logger.warning(f"Tavily API socket connection failed: {str(e)}")
                
                if tavily_reachable:
                    search_results = await self.tavily_service.search(query)
            except Exception as e:
                self.logger.error(f"Error fetching data from Tavily: {str(e)}")
                self.logger.exception(e)
            
            if not search_results:
                self.logger.warning("Tavily search failed or returned no results. Using mock data.")
                # Generate mock search results for economic calendar
                search_results = [
                    {
                        "title": "Economic Calendar - Today's Economic Events",
                        "url": "https://www.example.com/calendar",
                        "content": f"Economic calendar for {today} shows several events for {', '.join(currencies)}. "
                                   f"Notable events include regular economic releases and central bank announcements."
                    }
                ]
                
            # Next, try to use DeepSeek to process the results
            calendar_json = None
            
            try:
                # Check DeepSeek API connectivity first
                deepseek_available = False
                try:
                    # Try to connect directly to DeepSeek API
                    deepseek_hosts = ["api.deepseek.com", "api.deepseek.ai"]
                    
                    for host in deepseek_hosts:
                        # Simple socket connection test
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(3)  # Quick 3-second timeout
                        result = sock.connect_ex((host, 443))
                        sock.close()
                        
                        if result == 0:  # Port is open, connection successful
                            self.logger.info(f"DeepSeek API connectivity test successful for {host}")
                            deepseek_available = True
                            break
                        else:
                            self.logger.warning(f"DeepSeek API connectivity test failed for {host}: {result}")
                except socket.error as e:
                    self.logger.warning(f"DeepSeek API socket connection failed: {str(e)}")
                
                if deepseek_available:
                    # Prepare the prompt for DeepSeek
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
                    
                    # Use SSL context that doesn't verify certificates if needed
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                    
                    # Set timeout to avoid long waits
                    timeout = aiohttp.ClientTimeout(total=10)
                    
                    # Get calendar data with SSL context
                    try:
                        # First try normal API call through DeepseekService
                        calendar_json = await self.deepseek_service.generate_completion(prompt)
                    except Exception as e:
                        self.logger.error(f"Error with DeepseekService API call: {str(e)}")
                        self.logger.exception(e)
                        
                        # If that fails, try direct HTTP call with custom SSL handling
                        deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "")
                        if deepseek_api_key:
                            try:
                                self.logger.info("Attempting direct DeepSeek API call with custom SSL handling")
                                connector = aiohttp.TCPConnector(ssl=ssl_context)
                                
                                deepseek_headers = {
                                    "Authorization": f"Bearer {deepseek_api_key.strip()}",
                                    "Content-Type": "application/json"
                                }
                                
                                deepseek_url = "https://api.deepseek.com/v1/chat/completions"
                                
                                payload = {
                                    "model": "deepseek-chat",
                                    "messages": [
                                        {"role": "user", "content": prompt}
                                    ],
                                    "temperature": 0.3,
                                    "max_tokens": 1024
                                }
                                
                                async with aiohttp.ClientSession(connector=connector) as session:
                                    async with session.post(
                                        deepseek_url, 
                                        headers=deepseek_headers, 
                                        json=payload, 
                                        timeout=timeout
                                    ) as response:
                                        response_text = await response.text()
                                        self.logger.info(f"DeepSeek direct API response status: {response.status}")
                                        
                                        if response.status == 200:
                                            data = json.loads(response_text)
                                            calendar_json = data['choices'][0]['message']['content']
                                        else:
                                            self.logger.error(f"DeepSeek direct API error: {response.status}, details: {response_text[:200]}...")
                            except Exception as e:
                                self.logger.error(f"Error with direct DeepSeek API call: {str(e)}")
                                self.logger.exception(e)
            except Exception as e:
                self.logger.error(f"Error processing with DeepSeek: {str(e)}")
                self.logger.exception(e)
            
            # If we got a response from DeepSeek, try to parse it
            if calendar_json:
                try:
                    # Extract JSON from potential markdown code blocks
                    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', calendar_json)
                    if json_match:
                        calendar_json = json_match.group(1)
                        
                    # Parse the JSON
                    calendar_data = json.loads(calendar_json)
                    self.logger.info(f"Successfully parsed economic calendar data with {len(calendar_data)} currencies")
                    return calendar_data
                except json.JSONDecodeError as e:
                    self.logger.error(f"Failed to parse JSON from response: {e}")
                    self.logger.error(f"Response content: {calendar_json[:200]}...")
            
            # If we reach here, both services failed or returned invalid data, generate mock data
            self.logger.warning("Using mock economic calendar data as fallback")
            return self._generate_mock_calendar_data(currencies)
                
        except Exception as e:
            self.logger.error(f"Error getting economic calendar data: {str(e)}")
            self.logger.exception(e)
            return self._generate_mock_calendar_data(currencies)
    
    def _generate_mock_calendar_data(self, currencies: List[str]) -> Dict:
        """Generate mock calendar data for testing or when APIs fail"""
        self.logger.info("Generating mock economic calendar data")
        
        # Create an empty dictionary with empty lists for all major currencies
        calendar_data = {currency: [] for currency in MAJOR_CURRENCIES}
        
        # Set random seed based on current date to make results consistent for a given day
        today = datetime.now()
        random.seed(today.day + today.month * 31 + today.year * 366)
        
        # Standard events by currency
        events_by_currency = {
            "USD": ["Initial Jobless Claims", "Non-Farm Payrolls", "CPI m/m", "Federal Reserve Interest Rate Decision", 
                    "FOMC Statement", "Fed Chair Speech", "Retail Sales m/m", "GDP q/q", "Trade Balance"],
            "EUR": ["ECB Interest Rate Decision", "ECB Press Conference", "CPI y/y", "German ZEW Economic Sentiment", 
                   "PMI Manufacturing", "German Ifo Business Climate"],
            "GBP": ["BoE Interest Rate Decision", "MPC Meeting Minutes", "CPI y/y", "Retail Sales m/m", 
                   "GDP q/q", "Manufacturing PMI"],
            "JPY": ["BoJ Interest Rate Decision", "Monetary Policy Statement", "Core CPI y/y", "GDP q/q", 
                   "Tankan Manufacturing Index", "Trade Balance"],
            "CHF": ["SNB Interest Rate Decision", "CPI m/m", "Trade Balance", "SNB Chairman Speech", 
                   "Retail Sales y/y"],
            "AUD": ["RBA Interest Rate Decision", "Employment Change", "CPI q/q", "Trade Balance", 
                   "Retail Sales m/m"],
            "NZD": ["RBNZ Interest Rate Decision", "GDP q/q", "CPI q/q", "Employment Change", 
                   "Trade Balance"],
            "CAD": ["BoC Interest Rate Decision", "Employment Change", "CPI m/m", "Retail Sales m/m", 
                   "Trade Balance"]
        }
        
        # Impact levels for events
        impact_by_event_type = {
            "Interest Rate Decision": "High",
            "Non-Farm Payrolls": "High",
            "CPI": "High",
            "GDP": "High",
            "Press Conference": "High",
            "Statement": "High",
            "Employment": "Medium",
            "Retail Sales": "Medium",
            "Trade Balance": "Medium",
            "PMI": "Medium",
            "Sentiment": "Low",
            "Business Climate": "Low",
            "Speech": "Medium",
        }
        
        # Add 0-3 events for each currency with 50% more likelihood for specified currencies
        for currency in MAJOR_CURRENCIES:
            # Skip some currencies randomly to make it more realistic
            if random.random() < 0.3 and currency not in currencies:
                continue
                
            # Determine number of events (more likely to have events for requested currencies)
            max_events = 3 if currency in currencies else 2
            num_events = random.randint(0, max_events)
            
            if num_events == 0:
                continue
                
            events = events_by_currency.get(currency, [])
            selected_events = random.sample(events, min(num_events, len(events)))
            
            for event in selected_events:
                # Generate a time between 7:00 and 17:00 EST
                hour = random.randint(7, 17)
                minute = random.choice([0, 15, 30, 45])
                time_str = f"{hour:02d}:{minute:02d} EST"
                
                # Determine impact level
                impact = "Medium"  # Default
                for event_type, impact_level in impact_by_event_type.items():
                    if event_type in event:
                        impact = impact_level
                        break
                
                calendar_data[currency].append({
                    "time": time_str,
                    "event": event,
                    "impact": impact
                })
        
        return calendar_data
            
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
