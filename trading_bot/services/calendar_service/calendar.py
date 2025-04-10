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
import traceback

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
    try:
        from trading_bot.services.calendar_service.forexfactory_screenshot import ForexFactoryScreenshotService
        HAS_SCREENSHOT_SERVICE = True
    except ImportError:
        HAS_SCREENSHOT_SERVICE = False
    try:
        from trading_bot.services.calendar_service.tradingview_calendar import TradingViewCalendarService
        HAS_TRADINGVIEW_SERVICE = True
    except ImportError:
        HAS_TRADINGVIEW_SERVICE = False
    HAS_AI_SERVICES = True
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("AI services not available. Using fallback implementations.")
    HAS_AI_SERVICES = False
    HAS_SCREENSHOT_SERVICE = False
    HAS_TRADINGVIEW_SERVICE = False
    
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
        self.logger.info("Initializing EconomicCalendarService - Using TradingView as source")
        print("📅 Initializing Economic Calendar Service - Using TradingView API with ScrapingAnt")
        
        # Expliciete configuratie voor ScrapingAnt
        use_scrapingant = os.environ.get("USE_SCRAPINGANT", "").lower() in ("true", "1", "yes")
        api_key = os.environ.get("SCRAPINGANT_API_KEY", "")
        is_railway = os.environ.get("RAILWAY_ENVIRONMENT") is not None
        
        # Log configuratie
        if is_railway:
            self.logger.info("✨ Running in Railway environment")
            print("✨ Running in Railway environment")
        
        if use_scrapingant:
            masked_key = f"{api_key[:5]}...{api_key[-3:]}" if api_key else "Not set"
            self.logger.info(f"🔑 ScrapingAnt is ENABLED with key: {masked_key}")
            print(f"🔑 ScrapingAnt is ENABLED with key: {masked_key}")
        else:
            self.logger.info("⚠️ ScrapingAnt is DISABLED")
            print("⚠️ ScrapingAnt is DISABLED")
        
        # Create the TradingView calendar service
        self.calendar_service = TradingViewCalendarService()
        self.logger.info("Successfully created TradingViewCalendarService instance")
        
        self.tavily_service = tavily_service or TavilyService()
        self.deepseek_service = deepseek_service or DeepseekService()
        
        # Try to load API keys from environment on initialization
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if api_key:
            masked_key = api_key[:5] + "..." if len(api_key) > 5 else "[masked]"
            self.logger.info(f"Found Tavily API key in environment: {masked_key}")
            # Refresh the Tavily service with the key
            self.tavily_service = TavilyService(api_key=api_key)
        
        # Always disable ForexFactory screenshot service
        use_calendar_fallback = True  # Force to True to disable ForexFactory screenshot method
        self.logger.warning("❌ Calendar fallback mode is ENABLED - ForexFactory screenshot service disabled permanently")
        print("❌ Calendar fallback mode is ENABLED - ForexFactory screenshot service disabled permanently")
        self.use_screenshot_method = False
        
        self.cache = {}
        self.cache_time = {}
        self.cache_expiry = 3600  # 1 hour in seconds
        
        # Define loading GIF URLs
        self.loading_gif = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"  # Update loading GIF
        
    def get_loading_gif(self) -> str:
        """Get the URL for the loading GIF"""
        return self.loading_gif
        
    async def get_calendar(self, days_ahead: int = 0, min_impact: str = "Low") -> List[Dict]:
        """Get the economic calendar for the specified number of days ahead
        
        Args:
            days_ahead: Number of days to look ahead
            min_impact: Minimum impact level to include (Low, Medium, High)
            
        Returns:
            List of calendar events
        """
        try:
            self.logger.info(f"MAIN: Getting economic calendar data (days_ahead={days_ahead}, min_impact={min_impact})")
            print(f"📅 Getting economic calendar data for {days_ahead} days ahead with min impact {min_impact}")
            
            # Gebruik de TradingView kalender service om events op te halen
            events = await self.calendar_service.get_calendar(days_ahead=days_ahead, min_impact=min_impact)
            
            self.logger.info(f"MAIN: Received {len(events)} calendar events")
            print(f"📅 Successfully retrieved {len(events)} calendar events")
            
            return events
        
        except Exception as e:
            self.logger.error(f"Error getting calendar: {e}")
            # Probeer eens extra informatie te loggen bij een fout
            try:
                from inspect import getframeinfo, stack
                caller = getframeinfo(stack()[1][0])
                self.logger.error(f"Error location: {caller.filename}:{caller.lineno}")
            except Exception:
                # Ignore errors in debugging code
                pass
            
            # Return empty list on error
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
            calendar_data = await self._get_economic_calendar_data(currencies, datetime.now().strftime("%B %d, %Y"), datetime.now().strftime("%B %d, %Y"))
            
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
            calendar_data = await self._get_economic_calendar_data(currencies, datetime.now().strftime("%B %d, %Y"), datetime.now().strftime("%B %d, %Y"))
            
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
            
    async def _get_economic_calendar_data(self, currency_list, start_date, end_date, lookback_hours = 8):
        """
        Retrieve economic calendar data for select currencies within a date range
        """
        try:
            # Initialize calendar_json to an empty dict to avoid reference before assignment
            calendar_json = {}
            
            # Get Tavily API key from environment - expliciete refresh
            env_tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
            
            # Zorg ervoor dat de API key het tvly- prefix heeft voor Bearer authenticatie
            if env_tavily_key:
                # Voeg 'tvly-' prefix toe als dat niet aanwezig is, voor Bearer authenticatie
                if not env_tavily_key.startswith("tvly-"):
                    env_tavily_key = f"tvly-{env_tavily_key}"
                    logger.info(f"Added 'tvly-' prefix to API key for Bearer authentication")
                
                # Update environment variable met het correcte formaat
                os.environ["TAVILY_API_KEY"] = env_tavily_key
                masked_key = f"{env_tavily_key[:8]}...{env_tavily_key[-4:]}" if len(env_tavily_key) > 12 else f"{env_tavily_key[:4]}..."
                logger.info(f"Set TAVILY_API_KEY in environment: {masked_key}")
            else:
                # Gebruik de default API key als geen API key is ingesteld
                default_key = "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"
                env_tavily_key = default_key
                os.environ["TAVILY_API_KEY"] = default_key
                logger.info(f"Using default Tavily API key: {default_key[:8]}...{default_key[-4:]}")
                
            # Voeg debug info toe
            logger.info(f"Tavily API key from env_tavily_key: {env_tavily_key[:8]}...{env_tavily_key[-4:] if len(env_tavily_key) > 12 else ''}")
            logger.info(f"Tavily API key from os.environ: {os.environ.get('TAVILY_API_KEY', 'Not set')[:8]}...{os.environ.get('TAVILY_API_KEY', '')[-4:] if len(os.environ.get('TAVILY_API_KEY', '')) > 12 else ''}")
            
            # Form search query
            query = f"Economic calendar for {', '.join(currency_list)} from {start_date} to {end_date}"
            logger.info(f"Searching Tavily with query: {query}")
            
            # First attempt - general search
            try:
                # Initialize with explicit key
                tavily_service = TavilyService(api_key=env_tavily_key)
                logger.info("Created new TavilyService instance with explicit API key")
                
                # Test tavily_service API key
                if hasattr(tavily_service, 'api_key') and tavily_service.api_key:
                    logger.info(f"TavilyService.api_key: {tavily_service.api_key[:5]}...{tavily_service.api_key[-4:] if len(tavily_service.api_key) > 9 else ''}")
                else:
                    logger.error("TavilyService API key not set after initialization!")
                
                # Perform search
                logger.info("Starting Tavily search...")
                search_results = await tavily_service.search(query)
                
                if search_results and isinstance(search_results, list):
                    logger.info(f"Retrieved {len(search_results)} search results from Tavily")
                    content = "\n".join([result.get('content', '') for result in search_results])
                    
                    # Extract calendar data from the content using DeepSeek
                    calendar_json = await self._extract_calendar_data_with_deepseek(content, currency_list)
                    logger.info(f"Extracted calendar data: {len(calendar_json)} currencies")
                elif search_results and isinstance(search_results, dict) and search_results.get('results'):
                    logger.info(f"Retrieved {len(search_results.get('results', []))} search results from Tavily (dict format)")
                    content = "\n".join([result.get('content', '') for result in search_results.get('results', [])])
                    
                    # Extract calendar data from the content using DeepSeek
                    calendar_json = await self._extract_calendar_data_with_deepseek(content, currency_list)
                    logger.info(f"Extracted calendar data: {len(calendar_json)} currencies")
                else:
                    logger.warning("No search results from Tavily, trying search_internet instead")
                    # Second attempt - internet search
                    logger.info("Starting Tavily internet search...")
                    search_results = await tavily_service.search_internet(query)
                    
                    if search_results and isinstance(search_results, dict) and search_results.get('results'):
                        logger.info(f"Retrieved {len(search_results.get('results', []))} internet search results from Tavily")
                        content = "\n".join([result.get('content', '') for result in search_results.get('results', [])])
                        
                        # Extract calendar data from the content using DeepSeek
                        calendar_json = await self._extract_calendar_data_with_deepseek(content, currency_list)
                        logger.info(f"Extracted calendar data: {len(calendar_json)} currencies")
                    else:
                        logger.error("Both Tavily search and search_internet failed, using mock data")
                        logger.error(f"Search result type: {type(search_results)}")
                        logger.error(f"Search result preview: {str(search_results)[:200]}...")
                        return self._generate_mock_calendar_data(currency_list, start_date)
                        
            except Exception as e:
                logger.error(f"Error retrieving economic calendar data from Tavily: {str(e)}")
                logger.error(traceback.format_exc())
                return self._generate_mock_calendar_data(currency_list, start_date)
                
            # Return the calendar data
            return calendar_json
            
        except Exception as e:
            logger.error(f"Unexpected error in _get_economic_calendar_data: {str(e)}")
            logger.error(traceback.format_exc())
            return self._generate_mock_calendar_data(currency_list, start_date)
    
    async def _extract_calendar_data_with_deepseek(self, text: str, currencies: List[str]) -> Dict[str, List[Dict[str, str]]]:
        """Extract economic calendar data from text content using DeepSeek AI"""
        self.logger.info("Extracting calendar data using DeepSeek AI")
        
        try:
            # Initialize result dictionary with empty lists for all currencies
            result = {currency: [] for currency in currencies}
            
            # Check if DeepSeek service is available
            if not self.deepseek_service:
                self.logger.warning("DeepSeek service not available, falling back to regex extraction")
                return self._extract_calendar_data_from_text(text, currencies)
            
            # Create prompt for DeepSeek
            # Add current date to the prompt
            today = datetime.now()
            today_date = today.strftime("%Y-%m-%d")
            today_formatted = today.strftime("%B %d, %Y")
            current_month = today.strftime("%b").lower()
            current_day = today.strftime("%d").lstrip("0")  # 5, 10, etc. (zonder voorloopnul)
            
            prompt = f"""Extract economic calendar events from the following text. 
Format the response as JSON with the following structure:

```json
{{
  "USD": [
    {{
      "time": "08:30 EST",
      "event": "Initial Jobless Claims",
      "impact": "Medium",
      "date": "{today_date}"
    }}
  ],
  "EUR": [
    {{
      "time": "07:45 EST",
      "event": "ECB Interest Rate Decision",
      "impact": "High",
      "date": "{today_date}"
    }}
  ],
  // ... other currencies ...
}}
```

CRITICAL FILTERING INSTRUCTIONS:
1. ONLY include events scheduled for TODAY ({today_formatted}). Filter out ALL events from other days.
2. EXCLUDE events with date references that are not today, such as:
   - Events with date formats like (Mar/29), (Feb/10) - unless it's ({current_month}/{current_day})
   - Events that mention months other than the current month
   - Events with quarterly references (Q1, Q2, etc.)
   - Events with specific years mentioned (2022, 2023)
3. Pay close attention to text in parentheses, often containing dates like "Initial Jobless Claims (Apr/05)"
4. DO NOT include ANY events from future dates or past dates.
5. EVENTS MUST BE HAPPENING TODAY, not tomorrow, not yesterday.

Only include events for these currencies: {', '.join(currencies)}
For times, include timezone (EST if not specified).
For impact, use "High", "Medium", or "Low".

Text to extract from:
{text}

Only return the JSON, nothing else. DO NOT include events from any date other than TODAY ({today_formatted}).
"""

            # Make the DeepSeek API call
            self.logger.info("Calling DeepSeek API to extract calendar data")
            response = await self.deepseek_service.generate_completion(prompt)
            
            if not response:
                self.logger.warning("Empty response from DeepSeek, falling back to regex extraction")
                return self._extract_calendar_data_from_text(text, currencies)
            
            # Extract JSON from response (it might be wrapped in ```json blocks)
            json_match = re.search(r'```(?:json)?(.*?)```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                json_str = response.strip()
            
            # Parse the JSON
            try:
                parsed_data = json.loads(json_str)
                
                # Validate the structure
                if not isinstance(parsed_data, dict):
                    self.logger.warning("DeepSeek response is not a dictionary, falling back to regex extraction")
                    return self._extract_calendar_data_from_text(text, currencies)
                
                # Process the data to ensure it matches our expected structure
                for currency in currencies:
                    if currency in parsed_data and isinstance(parsed_data[currency], list):
                        for event in parsed_data[currency]:
                            if isinstance(event, dict) and "time" in event and "event" in event:
                                # Ensure impact is one of High, Medium, Low
                                if "impact" not in event or event["impact"] not in ["High", "Medium", "Low"]:
                                    event["impact"] = "Medium"  # Default to Medium if missing or invalid
                                
                                # Ensure time format includes timezone
                                if "time" in event and not any(tz in event["time"] for tz in ['AM', 'PM', 'EST', 'GMT', 'UTC', 'EDT']):
                                    event["time"] += " EST"
                                
                                # Add to result
                                result[currency].append({
                                    "time": event.get("time", ""),
                                    "event": event.get("event", ""),
                                    "impact": event.get("impact", "Medium")
                                })
                
                # Check if we found any events
                total_events = sum(len(events) for events in result.values())
                self.logger.info(f"DeepSeek extracted {total_events} events from calendar data")
                
                if total_events > 0:
                    return result
                else:
                    self.logger.warning("No events found in DeepSeek response, falling back to regex extraction")
                    return self._extract_calendar_data_from_text(text, currencies)
                    
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to parse DeepSeek JSON: {str(e)}")
                self.logger.error(f"Raw response: {response[:200]}...")
                return self._extract_calendar_data_from_text(text, currencies)
                
        except Exception as e:
            self.logger.error(f"Error using DeepSeek to extract calendar data: {str(e)}")
            self.logger.exception(e)
            return self._extract_calendar_data_from_text(text, currencies)
    
    def _extract_calendar_data_from_text(self, text: str, currencies: List[str]) -> Dict[str, List[Dict[str, str]]]:
        """Extract economic calendar data from text content"""
        self.logger.info("Extracting calendar data from text content")
        
        result = {currency: [] for currency in currencies}
        
        try:
            # Check for common time formats
            time_pattern = r'(\d{1,2}:\d{2}(?:\s*(?:AM|PM|EST|GMT|UTC|EDT))?)'
            currency_pattern = r'\b(' + '|'.join(currencies) + r')\b'
            impact_pattern = r'\b(High|Medium|Low|high|medium|low)\b'
            
            # Find potential event blocks - lines containing both a time and a currency
            lines = text.split('\n')
            for line in lines:
                # Skip empty lines
                if not line.strip():
                    continue
                    
                # Extract time
                time_match = re.search(time_pattern, line)
                if not time_match:
                    continue
                    
                time_str = time_match.group(1)
                
                # Ensure time has EST suffix if no timezone specified
                if not any(tz in time_str for tz in ['AM', 'PM', 'EST', 'GMT', 'UTC', 'EDT']):
                    time_str += ' EST'
                
                # Extract currency
                currency_match = re.search(currency_pattern, line, re.IGNORECASE)
                if not currency_match:
                    continue
                    
                currency = currency_match.group(1).upper()
                
                # Extract impact if present
                impact = "Low"  # Default
                impact_match = re.search(impact_pattern, line)
                if impact_match:
                    impact = impact_match.group(1).capitalize()
                    
                # Determine event name by removing time, currency and impact
                event_name = line
                event_name = re.sub(time_pattern, '', event_name)
                event_name = re.sub(r'\b' + currency + r'\b', '', event_name, flags=re.IGNORECASE)
                event_name = re.sub(impact_pattern, '', event_name, flags=re.IGNORECASE)
                
                # Clean up event name
                event_name = re.sub(r'[^\w\s\-]', '', event_name)  # Remove special chars except dash
                event_name = re.sub(r'\s+', ' ', event_name).strip()  # Remove extra whitespace
                
                # Skip if event name is too short or empty
                if len(event_name) < 3:
                    continue
                
                # Create event entry
                event = {
                    "time": time_str,
                    "event": event_name,
                    "impact": impact
                }
                
                # Add to correct currency
                if currency in result:
                    result[currency].append(event)
            
            # If we found any events, return the result
            if any(len(events) > 0 for currency, events in result.items()):
                self.logger.info(f"Successfully extracted {sum(len(events) for events in result.values())} events")
                return result
                
            # Otherwise return empty
            self.logger.warning("No calendar events found in text content")
            return {currency: [] for currency in currencies}
            
        except Exception as e:
            self.logger.error(f"Error extracting calendar data from text: {str(e)}")
            self.logger.exception(e)
            return {currency: [] for currency in currencies}
    
    def _generate_mock_calendar_data(self, currencies: List[str], start_date: str) -> Dict:
        """Generate mock calendar data for testing or when APIs fail"""
        self.logger.info("Generating mock economic calendar data")
        
        # Create an empty dictionary with empty lists for all major currencies
        calendar_data = {currency: [] for currency in MAJOR_CURRENCIES}
        
        # Set random seed based on current date to make results consistent for a given day
        # For testing, we can override with a specific date
        use_test_date = os.environ.get("CALENDAR_TEST_DATE", "")
        if use_test_date:
            try:
                test_date = datetime.strptime(use_test_date, "%Y-%m-%d")
                self.logger.info(f"Using test date for calendar: {test_date.strftime('%B %d, %Y')}")
                random.seed(test_date.day + test_date.month * 31 + test_date.year * 366)
            except Exception as e:
                self.logger.error(f"Error parsing test date: {str(e)}")
                today = datetime.now()
                random.seed(today.day + today.month * 31 + today.year * 366)
        else:
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
        # NIEUWE IMPLEMENTATIE met strikte filtering en een vaste datumkop
        
        # Altijd de huidige datum gebruiken, niet wat mogelijk in de data staat
        today = datetime.now()
        today_date = today.strftime("%Y-%m-%d")
        today_formatted = today.strftime("%B %d, %Y")
        current_month = today.strftime("%b").lower()
        current_month_full = today.strftime("%B").lower()
        current_day = today.strftime("%d").lstrip("0")
        
        # Begin met de standaard kop
        response = "<b>📅 Economic Calendar</b>\n\n"
        response += f"Date: {today_formatted}\n\n"
        response += "Impact: 🔴 High   🟠 Medium   🟢 Low\n\n"
        
        # Checken of we überhaupt data hebben
        if not calendar_data:
            return response + "No major economic events scheduled for today.\n\n<i>Check back later for updates.</i>"
        
        # Maanden voor detectie
        months_abbr = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
        months_full = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
        
        # Verzamel alle events voor vandaag
        today_events_by_currency = {}
        filtered_out_count = 0
        
        # Eerste stap: verzamel alleen events van vandaag
        for currency, events in calendar_data.items():
            if currency not in MAJOR_CURRENCIES:
                continue
                
            currency_events = []
            for event in events:
                # Haal event info op
                event_date = event.get("date", "")
                event_name = event.get("event", "").lower()
                event_time = event.get("time", "").strip()
                
                # Sla events over die duidelijk niet van vandaag zijn
                should_exclude = False
                
                # 1. Check op datum veld
                if event_date and event_date != today_date:
                    should_exclude = True
                
                # 2. Check op datums in naam tussen haakjes
                if "(" in event_name and ")" in event_name:
                    # Zoek naar datum indicaties tussen haakjes
                    bracket_content = re.findall(r'\((.*?)\)', event_name)
                    for content in bracket_content:
                        content_lower = content.lower()
                        
                        # A. Controleer op maandafkortingen die niet de huidige maand zijn
                        for month in months_abbr:
                            if month != current_month and month in content_lower:
                                should_exclude = True
                                
                        # B. Controleer op volledige maandnamen die niet de huidige maand zijn
                        for month in months_full:
                            if month != current_month_full and month in content_lower:
                                should_exclude = True
                                break
                                
                        # C. Controleer op datum notaties zoals Mar/29
                        month_day_match = re.search(r'([a-zA-Z]{3})/(\d{1,2})', content_lower)
                        if month_day_match:
                            matched_month = month_day_match.group(1).lower()
                            matched_day = month_day_match.group(2).lstrip("0")
                            
                            # Als het niet de huidige maand EN dag is, filter uit
                            if matched_month != current_month or matched_day != current_day:
                                should_exclude = True
                                
                        # D. Check op kwartalen/jaren tussen haakjes
                        if re.search(r'q[1-4]', content_lower) or re.search(r'\b\d{4}\b', content_lower):
                            should_exclude = True
                            
                # 3. Check op namen met "yesterday" of "tomorrow"
                if "yesterday" in event_name or "tomorrow" in event_name:
                    should_exclude = True
                
                # 4. Check op maandnamen in de titel (buiten haakjes) die niet de huidige maand zijn
                for month in months_abbr:
                    if month != current_month and month in event_name:
                        # Skip als het in een naam is zoals "Nonfarm" (bevat 'mar')
                        if month == "mar" and "mar" in event_name:
                            # Controleer of het echt de maand maart is en niet deel van een woord
                            if re.search(r'\bmar\b', event_name) or "(mar" in event_name or "mar/" in event_name:
                                should_exclude = True
                        else:
                            should_exclude = True
                
                # 5. Check op maand-specifieke woorden die naar andere maanden verwijzen
                month_keywords = {
                    "january": ["jan"],
                    "february": ["feb"],
                    "march": ["mar"],
                    "april": ["apr"],
                    "may": ["may"],
                    "june": ["jun"],
                    "july": ["jul"],
                    "august": ["aug"],
                    "september": ["sep"],
                    "october": ["oct"],
                    "november": ["nov"],
                    "december": ["dec"]
                }
                
                # Zoek naar de maand-gerelateerde keywords
                current_month_name = [k for k, v in month_keywords.items() if current_month in v]
                if current_month_name:
                    current_month_name = current_month_name[0]
                    # Filter alle maanden behalve de huidige
                    for month_name, abbrs in month_keywords.items():
                        if month_name != current_month_name:
                            if month_name in event_name or any(abbr in event_name and re.search(r'\b' + abbr + r'\b', event_name) for abbr in abbrs):
                                should_exclude = True
                
                # 6. Extra check voor bv. "Building Permits MoM (Feb)"
                # Controleer op veelvoorkomende indicatoren die maandelijks gepubliceerd worden
                monthly_indicators = ["mom", "yoy", "retail sales", "cpi", "inflation", "production", "unemployment", "interest rate", "payrolls", "non-farm"]
                if any(indicator in event_name for indicator in monthly_indicators):
                    # Controleer of er parentheses zijn met een andere maand dan de huidige
                    if "(" in event_name and ")" in event_name:
                        for month in months_abbr:
                            # Als er een maandafkorting in haakjes staat die niet de huidige maand is
                            if month != current_month and f"({month}" in event_name.lower():
                                should_exclude = True
                
                # Voeg alleen toe als we het niet moeten uitsluiten
                if not should_exclude:
                    if event_time:  # Alleen toevoegen als er een tijd is
                        # Voeg toe aan de currency lijst
                        currency_events.append(event)
                else:
                    filtered_out_count += 1
            
            # Als er events zijn voor deze currency, voeg ze toe
            if currency_events:
                # Sorteer op tijd
                currency_events = sorted(currency_events, key=lambda x: self._parse_time_for_sorting(x.get("time", "00:00")))
                today_events_by_currency[currency] = currency_events
        
        # Log resultaten
        total_events = sum(len(events) for events in today_events_by_currency.values())
        self.logger.info(f"CALENDAR: Showing {total_events} events for today (filtered out {filtered_out_count})")
        
        # Check of we events hebben na filtering
        if not today_events_by_currency:
            return response + "No major economic events scheduled for today.\n\n<i>Check back later for updates.</i>"
        
        # Sorteer currencies alfabetisch voor consistente weergave
        sorted_currencies = sorted(today_events_by_currency.keys())
        
        # Toon events per currency
        for currency in sorted_currencies:
            # Toon currency header met vlag
            response += f"{CURRENCY_FLAG.get(currency, '')} {currency}\n"
            
            # Toon alle events voor deze currency
            for event in today_events_by_currency[currency]:
                time = event.get("time", "").strip()
                event_name = event.get("event", "").strip()
                impact = event.get("impact", "Low")
                impact_emoji = IMPACT_EMOJI.get(impact, "🟢")
                
                # Verwijder dubbele spaties
                event_name = re.sub(r'\s+', ' ', event_name)
                
                # Toon tijd - impact emoji - event naam
                response += f"{time} - {impact_emoji} {event_name}\n"
            
            # Voeg lege regel toe tussen currencies
            response += "\n"
        
        return response
        
    def _parse_time_for_sorting(self, time_str: str) -> int:
        """Parse time string to minutes for sorting"""
        # Default value
        minutes = 0
        
        try:
            # Extract only time part if it contains timezone
            if " " in time_str:
                time_parts = time_str.split(" ")
                time_str = time_parts[0]
                
            # Handle AM/PM format
            if "AM" in time_str.upper() or "PM" in time_str.upper():
                # Parse 12h format
                time_only = time_str.upper().replace("AM", "").replace("PM", "").strip()
                parts = time_only.split(":")
                hours = int(parts[0])
                minutes_part = int(parts[1]) if len(parts) > 1 else 0
                
                # Add 12 hours for PM times (except 12 PM)
                if "PM" in time_str.upper() and hours < 12:
                    hours += 12
                # 12 AM should be 0
                if "AM" in time_str.upper() and hours == 12:
                    hours = 0
                
                minutes = hours * 60 + minutes_part
            else:
                # Handle 24h format
                parts = time_str.split(":")
                if len(parts) >= 2:
                    hours = int(parts[0])
                    minutes_part = int(parts[1])
                    minutes = hours * 60 + minutes_part
        except Exception:
            # In case of parsing error, default to 0
            minutes = 0
            
        return minutes
        
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

    # Nieuwe testfunctie om kalender voor een specifieke datum te genereren
    async def generate_calendar_for_date(self, target_date_str: str) -> str:
        """Generate calendar data for a specific date (format: YYYY-MM-DD)"""
        try:
            # Parse de datum
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
            formatted_date = target_date.strftime("%B %d, %Y")
            
            # Tijdelijk de testdatum instellen in de omgevingsvariabele
            os.environ["CALENDAR_TEST_DATE"] = target_date_str
            
            # Generate calendar data voor alle major currencies
            calendar_data = self._generate_mock_calendar_data(MAJOR_CURRENCIES, formatted_date)
            
            # Formateer het resultaat
            formatted_result = await self._format_calendar_response(calendar_data, "TEST")
            
            # Reset de omgevingsvariabele
            if "CALENDAR_TEST_DATE" in os.environ:
                del os.environ["CALENDAR_TEST_DATE"]
                
            return f"Economic Calendar for {formatted_date}:\n\n{formatted_result}"
            
        except Exception as e:
            logger.error(f"Error generating test calendar: {str(e)}")
            return f"Error generating calendar: {str(e)}"

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
