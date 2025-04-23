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

# Verwijderen van de vlag-valuta koppeling - we gebruiken geen vlaggen meer maar dikgedrukte tekst
# In plaats daarvan definiëren we alleen MAJOR_CURRENCIES om consistentie te garanderen
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
        try:
            # Importeer de TradingView kalender service als deze beschikbaar is
            from trading_bot.services.calendar_service.tradingview_calendar import TradingViewCalendarService
            self.calendar_service = TradingViewCalendarService()
            self.logger.info("Successfully created TradingViewCalendarService instance")
        except (ImportError, NameError) as e:
            # Als de import mislukt, gebruik dan een mock fallback
            self.logger.error(f"Failed to create TradingViewCalendarService: {str(e)}")
            self.logger.warning("Using mock calendar service instead")
            self.calendar_service = self._create_mock_calendar_service()
        
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
        use_calendar_fallback = False  # Set to False to properly enable TradingView calendar
        self.logger.info("✅ Calendar fallback mode is DISABLED - Using TradingView for economic calendar data")
        print("✅ Calendar fallback mode is DISABLED - Using TradingView for economic calendar data")
        self.use_screenshot_method = False
        
        self.cache = {}
        self.cache_time = {}
        self.cache_expiry = 3600  # 1 hour in seconds
        
        # Define loading GIF URLs
        self.loading_gif = "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif"  # Update loading GIF
        
    def get_loading_gif(self) -> str:
        """Get the URL for the loading GIF"""
        return self.loading_gif
        
    async def get_calendar(self, days_ahead: int = 0, min_impact: str = "Low", currency: str = None) -> List[Dict]:
        """Get the economic calendar for the specified number of days ahead
        
        Args:
            days_ahead: Number of days to look ahead
            min_impact: Minimum impact level to include (Low, Medium, High)
            currency: Optional currency to filter events by
            
        Returns:
            List of calendar events
        """
        try:
            self.logger.info(f"MAIN: Getting economic calendar data (days_ahead={days_ahead}, min_impact={min_impact}, currency={currency})")
            print(f"📅 Getting economic calendar data for {days_ahead} days ahead with min impact {min_impact}")
            
            # Gebruik de TradingView kalender service om events op te halen
            # Instead of filtering after, we pass the currency to the service which will tag events as "highlighted"
            events = await self.calendar_service.get_calendar(days_ahead=days_ahead, min_impact=min_impact, currency=currency)
            
            # Log the number of events found
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
            
    async def get_events_for_instrument(self, instrument: str) -> Dict[str, Any]:
        """Get economic events for a specific instrument"""
        self.logger.info(f"Getting events for instrument: {instrument}")
        
        # Get the relevant currencies for this instrument
        currencies = INSTRUMENT_CURRENCY_MAP.get(instrument, ["USD"])
        self.logger.info(f"Relevant currencies for {instrument}: {currencies}")
        
        # Use primary currency for highlighting
        primary_currency = currencies[0] if currencies else "USD"
        self.logger.info(f"Using primary currency {primary_currency} for highlighting")
        
        try:
            # Get all events with the primary currency highlighted
            calendar_data = await self.get_calendar(currency=primary_currency)
            self.logger.info(f"Retrieved {len(calendar_data)} calendar events with {primary_currency} highlighted")
            
            return {
                "events": calendar_data, 
                "explanation": f"Calendar events for {instrument} ({', '.join(currencies)})"
            }
            
        except Exception as e:
            self.logger.error(f"Error getting calendar data for {instrument}: {str(e)}")
            self.logger.error(traceback.format_exc())
            return {"events": [], "explanation": f"Could not retrieve calendar data: {str(e)}"}
            
    async def get_instrument_calendar(self, instrument: str) -> str:
        """Get a formatted calendar for a specific instrument"""
        self.logger.info(f"Getting calendar for instrument: {instrument}")
        
        try:
            # Get relevant currencies for clearer display
            currencies = INSTRUMENT_CURRENCY_MAP.get(instrument, ["USD"])
            primary_currency = currencies[0] if currencies else "USD"
            self.logger.info(f"Primary currency for {instrument}: {primary_currency}")
            
            # Get the events with highlighting for primary currency
            events_data = await self.get_events_for_instrument(instrument)
            events = events_data["events"]
            
            if not events:
                self.logger.warning(f"No calendar events found for {instrument}")
                return "<b>📅 Economic Calendar</b>\n\nNo calendar events found for this instrument."
            
            # Use the tradingview formatting function with our highlighted events
            from trading_bot.services.calendar_service.tradingview_calendar import format_calendar_for_telegram
            calendar_message = await format_calendar_for_telegram(events)
            
            # Add instrument-specific header
            calendar_message = calendar_message.replace("<b>📅 Economic Calendar</b>", 
                                                       f"<b>📅 Economic Calendar for {instrument}</b>\n" +
                                                       f"<i>Primary currency: {primary_currency} (in bold)</i>")
            
            return calendar_message
            
        except Exception as e:
            self.logger.error(f"Error getting calendar for {instrument}: {str(e)}")
            self.logger.error(traceback.format_exc())
            return f"<b>📅 Economic Calendar</b>\n\nCould not retrieve calendar data: {str(e)}"
            
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
            
            # Create prompt for DeepSeek with explicit today's date
            today = datetime.now()
            today_date = today.strftime("%Y-%m-%d")
            today_formatted = today.strftime("%B %d, %Y")
            current_month = today.strftime("%B")  # Full month name
            current_month_abbr = today.strftime("%b")  # Abbreviated month name
            current_day = today.strftime("%d").lstrip("0")  # 5, 10, etc. (zonder voorloopnul)
            
            prompt = f"""TASK: Extract economic calendar events ONLY for TODAY ({today_formatted}) from the text.

TODAY'S DATE: {today_formatted}
TODAY'S DAY: {current_day}
TODAY'S MONTH: {current_month} ({current_month_abbr})

Format the response as JSON with this structure:
```json
{{
  "USD": [
    {{
      "time": "08:30",
      "event": "Initial Jobless Claims",
      "impact": "Medium"
    }}
  ],
  "EUR": [ /* events for EUR */ ]
}}
```

STRICT DATE FILTERING RULES:
1. ONLY extract events specifically happening TODAY ({today_formatted})
2. EXCLUDE ALL events that:
   - Mention future dates like "tomorrow", "next week"
   - Mention past dates like "yesterday", "last week"
   - Contain date formats that don't match today (e.g., Apr/11 when today is {current_month_abbr}/{current_day})
   - Reference months other than {current_month}
3. If event has date in format ({current_month_abbr}/{current_day}), it's VALID for today
4. If a date reference isn't clearly today, EXCLUDE the event

FORMATTING RULES:
- Include events ONLY for these currencies: {', '.join(currencies)}
- Remove any timezone (EST, GMT, etc.) from time fields - just use 24-hour format like "08:30"
- For impact levels, ONLY use: "High", "Medium", or "Low"

Text to extract from:
{text}

IMPORTANT: ONLY return the JSON with TODAY's events. No explanation text.
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
                
                # Maak een nieuw resultaat zonder vlaggen
                validated_result = {}
                
                # Process the data to ensure it matches our expected structure
                for currency in currencies:
                    if currency in parsed_data and isinstance(parsed_data[currency], list):
                        validated_result[currency] = []
                        
                        for event in parsed_data[currency]:
                            if isinstance(event, dict) and "time" in event and "event" in event:
                                # Ensure impact is one of High, Medium, Low
                                if "impact" not in event or event["impact"] not in ["High", "Medium", "Low"]:
                                    event["impact"] = "Medium"  # Default to Medium if missing or invalid
                                
                                # Remove timezone if present and format time
                                if "time" in event:
                                    # Strip any timezone identifiers
                                    time_str = event["time"]
                                    time_str = re.sub(r'\s+(?:EST|GMT|UTC|EDT|AM|PM).*$', '', time_str)
                                    event["time"] = time_str
                                
                                # Add to result
                                validated_result[currency].append({
                                    "time": event.get("time", ""),
                                    "event": event.get("event", ""),
                                    "impact": event.get("impact", "Medium")
                                })
                
                # Check if we found any events
                total_events = sum(len(events) for events in validated_result.values())
                self.logger.info(f"DeepSeek extracted {total_events} events from calendar data")
                
                if total_events > 0:
                    return validated_result
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
        self.logger.info(f"Generating mock calendar data for {start_date}")
        
        # Create an empty dictionary with empty lists for all major currencies
        calendar_data = {currency: [] for currency in MAJOR_CURRENCIES}
        
        # Parse the start date
        try:
            today_date = datetime.strptime(start_date, "%Y-%m-%d")
        except:
            today_date = datetime.now()
            
        # Format for display
        today_formatted = today_date.strftime("%B %d, %Y")
        month_abbr = today_date.strftime("%b")
        
        self.logger.info(f"Using date: {today_formatted}")
        
        # Set fixed seed for consistent results based on date
        random.seed(today_date.day + today_date.month * 31 + today_date.year * 366)
        
        # Real world economic events based on the screenshot
        real_events = {
            "USD": [
                {"time": "15:00", "event": "Consumer Inflation Expectations (Mar)", "impact": "High"},
                {"time": "15:30", "event": "3-Month Bill Auction", "impact": "Low"},
                {"time": "15:30", "event": "6-Month Bill Auction", "impact": "Low"},
                {"time": "16:00", "event": "Fed Barkin Speech", "impact": "High"},
                {"time": "17:00", "event": "Fed Waller Speech", "impact": "High"},
                {"time": "22:00", "event": "Fed Harker Speech", "impact": "High"},
                {"time": "23:40", "event": "Fed Bostic Speech", "impact": "High"}
            ],
            "CAD": [
                {"time": "12:30", "event": "Wholesale Sales MoM Final (Feb)", "impact": "Low"},
                {"time": "12:30", "event": "New Motor Vehicle Sales (Feb)", "impact": "Low"}
            ],
            "CHF": [
                {"time": "06:30", "event": "Producer & Import Prices MoM (Mar)", "impact": "Low"},
                {"time": "06:30", "event": "Producer & Import Prices YoY (Mar)", "impact": "Low"}
            ],
            "GBP": [
                {"time": "23:01", "event": "BRC Retail Sales Monitor YoY (Mar)", "impact": "Medium"}
            ],
            "JPY": [
                {"time": "04:30", "event": "Industrial Production MoM Final (Feb)", "impact": "Medium"},
                {"time": "04:30", "event": "Industrial Production YoY Final (Feb)", "impact": "Medium"},
                {"time": "04:30", "event": "Capacity Utilization MoM (Feb)", "impact": "Low"}
            ],
            "NZD": [
                {"time": "22:45", "event": "Food Inflation YoY (Mar)", "impact": "High"}
            ],
            "EUR": [],
            "AUD": []
        }
        
        # Extra events voor valuta's die niet in het screenshot staan, 
        # om wat variatie te hebben als die valuta's worden gevraagd
        extra_events = {
            "AUD": [
                {"time": "01:30", "event": "Home Loans MoM", "impact": "Medium"},
                {"time": "02:30", "event": "Consumer Inflation Expectations", "impact": "Medium"}
            ],
            "NZD": [
                {"time": "22:45", "event": "Electronic Card Retail Sales MoM", "impact": "Medium"},
                {"time": "23:00", "event": "Business NZ PMI", "impact": "Medium"}
            ],
            "CAD": [
                {"time": "12:30", "event": "New Housing Price Index MoM", "impact": "Low"},
                {"time": "14:30", "event": "BoC Senior Loan Officer Survey", "impact": "Medium"}
            ]
        }
        
        # Voeg de extra events toe aan de real_events dictionary
        for currency, events in extra_events.items():
            if currency in real_events:
                real_events[currency].extend(events)
            else:
                real_events[currency] = events
                
        # Gebruik de echte events voor de kalender
        for currency, events in real_events.items():
            for event in events:
                # Voeg toe aan de kalender data
                calendar_data[currency].append({
                    "time": event["time"],
                    "event": event["event"],
                    "impact": event["impact"]
                })
        
        # Log het aantal gegenereerde events
        total_events = sum(len(events) for events in calendar_data.values())
        self.logger.info(f"Generated {total_events} mock calendar events")
        
        return calendar_data
            
    def _get_fallback_calendar(self, instrument: str) -> str:
        """Generate a fallback response if getting the calendar fails"""
        response = "<b>📅 Economic Calendar</b>\n\n"
        
        # Get current date
        today = datetime.now()
        today_readable = today.strftime("%B %d, %Y")
        
        # Add date header to the response
        response += f"<b>Date: {today_readable}</b>\n\n"
        
        # Add the impact legend immediately after the date
        response += "Impact: 🔴 High   🟠 Medium   🟢 Low\n\n"
        
        currencies = INSTRUMENT_CURRENCY_MAP.get(instrument, ["USD"])
        currencies = [c for c in currencies if c in MAJOR_CURRENCIES]
        
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
        
        # Group events by currency
        events_by_currency = {}
        for event in all_events:
            currency = event.get("currency", "")
            if currency not in events_by_currency:
                events_by_currency[currency] = []
            events_by_currency[currency].append(event)
        
        # Nu de output genereren volgens MAJOR_CURRENCIES volgorde
        for currency in MAJOR_CURRENCIES:
            # Skip valuta die niet in onze events voorkomen
            if currency not in events_by_currency:
                continue
                
            # Gebruik speciale tekens om valuta te markeren voor betere zichtbaarheid
            response += f"<b>⟪{currency}⟫</b>:\n"
            
            # Voeg events toe
            sorted_events = sorted(events_by_currency[currency], key=lambda x: x.get("time", "00:00"))
            
            for event in sorted_events:
                time = event.get("time", "")
                event_name = event.get("event", "")
                impact = event.get("impact", "Low")
                impact_emoji = IMPACT_EMOJI.get(impact, "🟢")
                
                # Format with time first, then impact emoji and event name
                response += f"{time} - {impact_emoji} {event_name}\n"
            
            # Lege regel na elke valuta sectie
            response += "\n"
        
        # Add empty line before legend
        response += "-------------------\n"
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

    def _create_mock_calendar_service(self):
        """Een mock calendar service maken als fallback"""
        self.logger.info("Creating mock calendar service")
        
        # Maak een eenvoudig object met dezelfde interface als TradingViewCalendarService
        class MockCalendarService:
            async def get_calendar(self, days_ahead=0, min_impact="Low"):
                """Return mock calendar data"""
                from datetime import datetime, timedelta
                
                # Gebruik de huidige tijd als basis
                now = datetime.now()
                mock_date = now + timedelta(days=days_ahead)
                date_str = mock_date.strftime("%B %d, %Y")
                
                # Genereer wat standaard evenementen voor vandaag
                mock_events = [
                    {
                        "time": "08:30",
                        "currency": "USD",
                        "impact": "High",
                        "event": "Non-Farm Payrolls",
                        "actual": "202K",
                        "forecast": "200K",
                        "previous": "195K"
                    },
                    {
                        "time": "10:00",
                        "currency": "EUR",
                        "impact": "Medium",
                        "event": "Consumer Price Index",
                        "actual": "2.1%",
                        "forecast": "2.0%",
                        "previous": "1.9%"
                    },
                    {
                        "time": "14:00",
                        "currency": "GBP",
                        "impact": "Low",
                        "event": "BOE Governor Bailey Speech",
                        "actual": "",
                        "forecast": "",
                        "previous": ""
                    }
                ]
                
                # Filter op impact level
                impact_levels = {"Low": 0, "Medium": 1, "High": 2}
                min_impact_level = impact_levels.get(min_impact, 0)
                
                filtered_events = [
                    event for event in mock_events
                    if impact_levels.get(event["impact"], 0) >= min_impact_level
                ]
                
                return filtered_events
                
            # Voeg andere methodes toe indien nodig
        
        return MockCalendarService()

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
            
            # Initialiseer de TradingView kalender service
            if HAS_TRADINGVIEW_SERVICE:
                self.calendar = TradingViewCalendarService()
                logger.info("Successfully initialized TradingView Calendar Service")
            else:
                logger.warning("TradingView Calendar Service not available, using fallback")
                self.calendar = EconomicCalendarService()
            
            # Rest van de initialisatie
            # ...
        except Exception as e:
            # Voeg een except block toe
            logging.error(f"Error initializing TelegramService: {str(e)}")
            raise  # Optioneel: re-raise de exceptie na het loggen
