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
    "Medium": "🟠",
    "Low": "🟢"
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
        
        # Define loading GIF URLs
        self.loading_gif = "https://media.giphy.com/media/3oEjI6SIIHBdRxXI40/giphy.gif"  # Default loading GIF
        
        # Try to load API keys from environment on initialization
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if api_key:
            masked_key = api_key[:5] + "..." if len(api_key) > 5 else "[masked]"
            self.logger.info(f"Found Tavily API key in environment: {masked_key}")
            # Refresh the Tavily service with the key
            self.tavily_service = TavilyService(api_key=api_key)
        
    def get_loading_gif(self) -> str:
        """Get the URL for the loading GIF"""
        return self.loading_gif
        
    async def get_calendar(self) -> List[Dict]:
        """Get economic calendar events for all major currencies"""
        try:
            self.logger.info(f"Getting economic calendar for all major currencies")
            
            # Check for API key again in case it was added after initialization
            api_key = os.environ.get("TAVILY_API_KEY", "")
            if api_key and (not hasattr(self.tavily_service, 'api_key') or self.tavily_service.api_key != api_key):
                self.logger.info("Updating Tavily service with new API key")
                self.tavily_service = TavilyService(api_key=api_key)
                # Invalidate cache when API key changes
                self.cache = {}
                self.cache_time = {}
            
            # Check cache first for "all" key
            now = time.time()
            if "all" in self.cache and (now - self.cache_time.get("all", 0)) < self.cache_expiry:
                self.logger.info(f"Using cached calendar data for all currencies")
                return self.cache["all"]
            
            # Get calendar data for all major currencies
            calendar_data = await self._get_economic_calendar_data(MAJOR_CURRENCIES)
            
            # Flatten the data into a single list of events with currency info
            flattened_events = []
            for currency, events in calendar_data.items():
                for event in events:
                    flattened_events.append({
                        "time": event.get("time", ""),
                        "country": currency,
                        "country_flag": CURRENCY_FLAG.get(currency, ""),
                        "title": event.get("event", ""),
                        "impact": event.get("impact", "Low")
                    })
            
            # Cache the result
            self.cache["all"] = flattened_events
            self.cache_time["all"] = now
            
            return flattened_events
            
        except Exception as e:
            self.logger.error(f"Error getting global economic calendar: {str(e)}")
            self.logger.exception(e)
            return []
            
    async def get_events(self, instrument: str) -> Dict:
        """Get economic calendar events and explanations for a specific instrument"""
        try:
            self.logger.info(f"Getting economic calendar events for {instrument}")
            
            # Get currencies related to this instrument
            currencies = INSTRUMENT_CURRENCY_MAP.get(instrument, [])
            
            # If no currencies found, use USD as default
            if not currencies:
                currencies = ["USD"]
                
            # Filter to only include major currencies
            currencies = [c for c in currencies if c in MAJOR_CURRENCIES]
            
            # Get calendar data for these currencies
            calendar_data = await self._get_economic_calendar_data(currencies)
            
            # Flatten the data into a list of events with the event information
            events = []
            for currency, currency_events in calendar_data.items():
                for event in currency_events:
                    events.append({
                        "date": f"{event.get('time', 'TBD')} - {CURRENCY_FLAG.get(currency, '')} {currency}",
                        "title": event.get("event", "Unknown Event"),
                        "impact": event.get("impact", "low").lower(),
                        "forecast": "",  # Could be expanded in the future
                        "previous": ""   # Could be expanded in the future
                    })
            
            # Sort events by time
            events = sorted(events, key=lambda x: x.get("date", ""))
            
            # Create a simple explanation of the impact
            explanation = f"These economic events may impact {instrument} as they affect "
            explanation += ", ".join([f"{CURRENCY_FLAG.get(c, '')} {c}" for c in currencies])
            explanation += " which are the base currencies for this instrument."
            
            return {
                "events": events,
                "explanation": explanation
            }
            
        except Exception as e:
            self.logger.error(f"Error getting events for {instrument}: {str(e)}")
            self.logger.exception(e)
            # Return empty data structure
            return {
                "events": [],
                "explanation": f"No economic events found for {instrument}."
            }
            
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
            # Check environment for API key again 
            env_tavily_key = os.environ.get("TAVILY_API_KEY", "")
            if env_tavily_key and (not hasattr(self.tavily_service, 'api_key') or 
                                  self.tavily_service.api_key != env_tavily_key):
                self.logger.info("Refreshing Tavily service with API key from environment")
                self.tavily_service = TavilyService(api_key=env_tavily_key)
            
            # Form the search query for Tavily
            today = datetime.now().strftime("%B %d, %Y")
            query = f"economic calendar events today {today} for {', '.join(currencies)} currencies with EST time format event times impact level high medium low"
            
            # First try Tavily
            self.logger.info(f"Searching for economic calendar data using Tavily")
            search_results = None
            
            try:
                # Check if Tavily API key is available
                if hasattr(self.tavily_service, 'api_key') and self.tavily_service.api_key:
                    self.logger.info("Tavily API key is available, proceeding with search")
                    search_results = await self.tavily_service.search(query)
                    
                    # Check if we got meaningful results
                    if search_results:
                        self.logger.info(f"Received {len(search_results)} search results from Tavily")
                        
                        # Extract relevant content from search results for better processing
                        calendar_data_content = ""
                        for result in search_results:
                            if result.get("content"):
                                calendar_data_content += result.get("content") + "\n\n"
                                
                        # If we have content, try to extract event data directly
                        if calendar_data_content:
                            calendar_data = self._extract_calendar_data_from_text(calendar_data_content, currencies)
                            if calendar_data and any(len(events) > 0 for _, events in calendar_data.items()):
                                self.logger.info("Successfully extracted calendar data from Tavily results")
                                return calendar_data
                else:
                    self.logger.warning("No Tavily API key available")
            except Exception as e:
                self.logger.error(f"Error fetching data from Tavily: {str(e)}")
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
        
        # Collect all events across currencies to sort by time
        all_events = []
        for currency in currencies:
            if currency not in MAJOR_CURRENCIES:
                continue
                
            events = calendar_data.get(currency, [])
            for event in events:
                # Add currency to event for display
                event_with_currency = event.copy()
                event_with_currency['currency'] = currency
                all_events.append(event_with_currency)
        
        # Sort all events by time
        all_events = sorted(all_events, key=lambda x: x.get("time", "00:00"))
        
        # Display events in chronological order
        for event in all_events:
            time = event.get("time", "")
            currency = event.get("currency", "")
            event_name = event.get("event", "")
            impact = event.get("impact", "Low")
            impact_emoji = IMPACT_EMOJI.get(impact, "🟢")
            
            # Format with currency flag - no extra newline after each event
            response += f"{time} - {CURRENCY_FLAG.get(currency, '')} {currency} - {event_name} {impact_emoji}\n"
        
        # Add empty line before legend
        response += "\n-------------------\n"
        response += "🔴 High Impact\n"
        response += "🟠 Medium Impact\n"
        response += "🟢 Low Impact"
        
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
            
        # Collect all events
        all_events = []
            
        for currency in MAJOR_CURRENCIES:
            # Add mock events if this is an active currency
            if currency in active_currencies:
                if currency == "USD":
                    all_events.append({
                        "time": f"{(today.hour % 12 + 1):02d}:30 EST",
                        "currency": currency,
                        "event": "Retail Sales",
                        "impact": "Medium"
                    })
                    all_events.append({
                        "time": f"{(today.hour % 12 + 3):02d}:00 EST",
                        "currency": currency,
                        "event": "Fed Chair Speech",
                        "impact": "High"
                    })
                elif currency == "EUR":
                    all_events.append({
                        "time": f"{(today.hour % 12):02d}:45 EST",
                        "currency": currency,
                        "event": "Inflation Data",
                        "impact": "High"
                    })
                elif currency == "GBP":
                    all_events.append({
                        "time": f"{(today.hour % 12 + 2):02d}:00 EST",
                        "currency": currency,
                        "event": "Employment Change",
                        "impact": "Medium"
                    })
                else:
                    all_events.append({
                        "time": f"{(today.hour % 12 + 1):02d}:15 EST",
                        "currency": currency,
                        "event": "GDP Data",
                        "impact": "Medium"
                    })
        
        # Sort events by time
        all_events = sorted(all_events, key=lambda x: x.get("time", "00:00"))
        
        # Display events in chronological order
        for event in all_events:
            time = event.get("time", "")
            currency = event.get("currency", "")
            event_name = event.get("event", "")
            impact = event.get("impact", "Low")
            impact_emoji = IMPACT_EMOJI.get(impact, "🟢")
            
            # Format with currency flag - no extra newline after each event
            response += f"{time} - {CURRENCY_FLAG.get(currency, '')} {currency} - {event_name} {impact_emoji}\n"
        
        # Add empty line before legend
        response += "\n-------------------\n"
        response += "🔴 High Impact\n"
        response += "🟠 Medium Impact\n"
        response += "🟢 Low Impact"
        
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
