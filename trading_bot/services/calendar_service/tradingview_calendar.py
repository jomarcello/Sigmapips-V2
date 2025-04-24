import os
import sys
import logging
import asyncio
import json
import pandas as pd
import aiohttp
import http.client
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union
from pathlib import Path
import re

# Import onze custom mock data generator
try:
    from trading_bot.services.calendar_service._generate_mock_calendar_data import generate_mock_calendar_data
    HAS_CUSTOM_MOCK_DATA = True
except ImportError:
    HAS_CUSTOM_MOCK_DATA = False
    logging.getLogger(__name__).warning("Custom mock calendar data not available, using default mock data")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Currency to flag emoji mapping
CURRENCY_FLAG_MAP = {
    "USD": "🇺🇸",
    "EUR": "🇪🇺",
    "GBP": "🇬🇧",
    "JPY": "🇯🇵",
    "CHF": "🇨🇭",
    "AUD": "🇦🇺",
    "NZD": "🇳🇿",
    "CAD": "🇨🇦",
}

# Map of major currencies to country codes for TradingView API
CURRENCY_COUNTRY_MAP = {
    "USD": "US",
    "EUR": "EU",
    "GBP": "GB",
    "JPY": "JP",
    "CHF": "CH",
    "AUD": "AU",
    "NZD": "NZ",
    "CAD": "CA",
    # Extra landen toevoegen die op TradingView worden getoond
    "CNY": "CN",  # China
    "HKD": "HK",  # Hong Kong
    "SGD": "SG",  # Singapore
    "INR": "IN",  # India
    "BRL": "BR",  # Brazilië
    "MXN": "MX",  # Mexico
    "ZAR": "ZA",  # Zuid-Afrika
    "SEK": "SE",  # Zweden
    "NOK": "NO",  # Noorwegen
    "DKK": "DK",  # Denemarken
    "PLN": "PL",  # Polen
    "TRY": "TR",  # Turkije
    "RUB": "RU",  # Rusland
    "KRW": "KR",  # Zuid-Korea
    "ILS": "IL",  # Israël
    # Ontbrekende landen die op TradingView worden getoond
    "IDR": "ID",  # Indonesië
    "SAR": "SA",  # Saudi Arabië
    "THB": "TH",  # Thailand
    "MYR": "MY",  # Maleisië
    "PHP": "PH",  # Filipijnen
    "VND": "VN",  # Vietnam
    "UAH": "UA",  # Oekraïne
    "AED": "AE",  # Verenigde Arabische Emiraten
    "QAR": "QA",  # Qatar
    "CZK": "CZ",  # Tsjechië
    "HUF": "HU",  # Hongarije
    "RON": "RO",  # Roemenië
    "CLP": "CL",  # Chili
    "COP": "CO",  # Colombia
    "PEN": "PE",  # Peru
    "ARS": "AR"   # Argentinië
}

# Impact levels and their emoji representations
IMPACT_EMOJI = {
    "High": "🔴",
    "Medium": "🟠",
    "Low": "🟢"
}

# Definieer de major currencies die we altijd willen tonen
MAJOR_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"]

# Updated importance level mapping
IMPORTANCE_MAP = {
    3: "High",    # High importance
    2: "Medium",  # Medium importance
    1: "Medium",  # Also Medium importance in TradingView
    0: "Low",     # Low importance
    -1: "Low"     # Also Low importance in TradingView
}

class TradingViewCalendarService:
    """Service for retrieving calendar data directly from TradingView"""
    
    def __init__(self):
        # TradingView calendar API endpoint - ensure this is the current working endpoint
        self.base_url = "https://economic-calendar.tradingview.com/events"
        self.session = None
        # Keep track of last successful API call
        self.last_successful_call = None
        
    async def _ensure_session(self):
        """Ensure we have an active aiohttp session"""
        if self.session is None:
            self.session = aiohttp.ClientSession()
            
    async def _close_session(self):
        """Close the aiohttp session"""
        if self.session:
            await self.session.close()
            self.session = None
            
    def _format_date(self, date: datetime) -> str:
        """Format date for TradingView API"""
        # Remove microseconds and format as expected by the API
        date = date.replace(microsecond=0)
        return date.isoformat() + '.000Z'
        
    async def _check_api_health(self) -> bool:
        """Check if the TradingView API endpoint is working with retry mechanism"""
        max_retries = 3
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                await self._ensure_session()
                params = {
                    'from': self._format_date(datetime.now()),
                    'to': self._format_date(datetime.now() + timedelta(days=1)),
                    'limit': 1
                }
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Origin": "https://www.tradingview.com",
                    "Referer": "https://www.tradingview.com/economic-calendar/",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache"
                }
                
                full_url = f"{self.base_url}"
                logger.info(f"API health check attempt {attempt + 1}/{max_retries}: {full_url}")
                
                async with self.session.get(
                    full_url, 
                    params=params, 
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    logger.info(f"Health check response status: {response.status}")
                    if response.status == 200:
                        # Try to parse response to verify it's valid JSON
                        data = await response.json()
                        if isinstance(data, (list, dict)):
                            logger.info("API health check successful: received valid JSON response")
                            return True
                        else:
                            logger.warning(f"API returned unexpected data type: {type(data)}")
                    else:
                        logger.warning(f"API returned non-200 status: {response.status}")
                        
            except aiohttp.ClientError as e:
                logger.error(f"API connection error on attempt {attempt + 1}: {str(e)}")
            except json.JSONDecodeError as e:
                logger.error(f"API returned invalid JSON on attempt {attempt + 1}: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error during API health check on attempt {attempt + 1}: {str(e)}")
            
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
        
        logger.error("API health check failed after all retry attempts")
        return False
            
    def _map_importance(self, importance_value: int) -> str:
        """Map TradingView importance values to impact levels"""
        return IMPORTANCE_MAP.get(importance_value, "Low")  # Default to Low if unknown value

    async def get_calendar(self, days_ahead: int = 0, min_impact: str = "Low", currency: str = None) -> List[Dict[str, Any]]:
        """Fetch calendar events from TradingView with retry mechanism"""
        max_retries = 3
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Calendar fetch attempt {attempt + 1}/{max_retries} from TradingView")
                logger.info(f"Parameters: days_ahead={days_ahead}, min_impact={min_impact}, currency={currency}")
                
                await self._ensure_session()
                
                # First check if the API is healthy
                is_healthy = await self._check_api_health()
                if not is_healthy:
                    if attempt < max_retries - 1:
                        logger.warning(f"API health check failed, retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        logger.error("API health check failed after all attempts, falling back to mock data")
                        if HAS_CUSTOM_MOCK_DATA:
                            return generate_mock_calendar_data(days_ahead, min_impact)
                        return []
                
                # Calculate date range
                start_date = datetime.now()
                end_date = start_date + timedelta(days=max(1, days_ahead))
                
                # Prepare request parameters
                params = {
                    'from': self._format_date(start_date),
                    'to': self._format_date(end_date),
                    'countries': 'US,EU,GB,JP,CH,AU,NZ,CA',
                    'limit': 1000
                }
            
                # Filter by currency if specified
                if currency:
                    logger.info(f"Filtering by currency: {currency}")
                    country_code = CURRENCY_COUNTRY_MAP.get(currency)
                    if country_code:
                        params['countries'] = country_code
                
                # Make request to TradingView
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Origin": "https://www.tradingview.com",
                    "Referer": "https://www.tradingview.com/economic-calendar/",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "Connection": "keep-alive"
                }
            
                full_url = f"{self.base_url}"
                logger.info(f"Making request to: {full_url}")
                logger.info(f"Request params: {params}")
                logger.info(f"Request headers: {headers}")
                
                async with self.session.get(
                    full_url, 
                    params=params, 
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    logger.info(f"Response status: {response.status}")
                    logger.info(f"Response headers: {dict(response.headers)}")
                    if response.status != 200:
                        response_text = await response.text()
                        logger.error(f"Error response from TradingView: {response.status}")
                        logger.error(f"Response body: {response_text}")
                        if attempt < max_retries - 1:
                            logger.warning(f"Request failed, retrying in {retry_delay} seconds...")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                        logger.error("Request failed after all retries, falling back to mock data")
                        if HAS_CUSTOM_MOCK_DATA:
                            return generate_mock_calendar_data(days_ahead, min_impact)
                        return []

                    # Process the successful response
                    response_text = await response.text()
                    try:
                        response_data = json.loads(response_text)
                        logger.info(f"Successfully parsed response JSON, data type: {type(response_data)}")
                        return response_data
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse response JSON: {str(e)}")
                        logger.error(f"Raw response: {response_text}")
                        return []
                
                self.last_successful_call = datetime.now()
                response_text = await response.text()
                
                # Clean up response text (fix JSON issues)
                response_text = re.sub(r'";,', '",', response_text)
                response_text = re.sub(r'";(\s*[,}])', r'"\1', response_text)
                
                data = json.loads(response_text)
                logger.info(f"Raw API response type: {type(data)}")
                logger.info(f"Raw API response sample: {json.dumps(data[:2] if isinstance(data, list) else data, indent=2)}")

                if isinstance(data, dict):
                    logger.info(f"Response is a dictionary with keys: {list(data.keys())}")
                    data = data.get("result", []) if "result" in data else data.get("data", [])
                
                if not isinstance(data, list):
                    logger.error(f"Unexpected data format: {type(data)}")
                    return []
                
                logger.info(f"Processing {len(data)} events from API")
                
                # Process events
                logger.info("Converting TradingView events to our format")
                events = []
                
                # Log first few raw events for debugging
                for idx, raw_event in enumerate(data[:5]):
                    logger.info(f"Raw event {idx + 1}: {json.dumps(raw_event)}")
                
                # Start processing events
                skipped = 0
                for event in data:
                    try:
                        # Get currency code
                        currency_code = event.get("currency") or CURRENCY_COUNTRY_MAP.get(event.get("country", ""))
                        if not currency_code:
                            continue
                        
                        # Get and map importance level
                        importance_value = event.get("importance", 0)  # Default to 0 (Low) if not specified
                        impact = self._map_importance(importance_value)
                        
                        # Parse time
                        date_str = event.get("date", "")
                        if not date_str:
                            continue
                            
                        event_time = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        time_str = event_time.strftime("%H:%M")
                        
                        # Extract event title - try different possible field names
                        event_title = event.get('title') or event.get('event') or event.get('description') or event.get('name')
                        if not event_title:
                            logger.warning(f"Missing title in event: {json.dumps(event)}")
                            continue
                        
                        # Log the found title and where it came from
                        for field in ['title', 'event', 'description', 'name']:
                            if field in event:
                                logger.info(f"Found event name in field '{field}': {event[field]}")

                        # Log raw event data for debugging
                        logger.info(f"Processing event: title='{event_title}', country='{currency_code}', importance={importance_value}, impact='{impact}'")

                        # Create event object
                        event_obj = {
                            "country": currency_code,
                            "time": time_str,
                            "event": event_title,  # Use the extracted title
                            "impact": impact,
                        }
                        
                        # Add optional fields
                        for field in ["actual", "previous", "forecast"]:
                            if event.get(field) is not None:
                                event_obj[field] = event[field]
                        
                        events.append(event_obj)
                        
                    except Exception as e:
                        logger.error(f"Error processing event: {str(e)}")
                        continue
                
                # Filter by minimum impact
                if min_impact != "Low":
                    impact_levels = ["High", "Medium", "Low"]
                    min_impact_idx = impact_levels.index(min_impact)
                    events = [e for e in events if impact_levels.index(e["impact"]) <= min_impact_idx]
                
                # Sort events by time
                events.sort(key=lambda x: x["time"])
                
                logger.info(f"Successfully processed {len(events)} events")
                return events
                
        except Exception as e:
            logger.error(f"Error fetching calendar data: {str(e)}")
            return []
            
        finally:
            await self._close_session()

    async def get_economic_calendar(self, currencies: List[str] = None, days_ahead: int = 0, min_impact: str = "Low") -> str:
        """Format calendar data for display"""
        try:
            # Get events
            events = await self.get_calendar(days_ahead=days_ahead, min_impact=min_impact)
            
            # Filter by currencies if specified
            if currencies:
                logger.info(f"Filtering events by currencies: {currencies}")
                # Create mapping of currency codes to their respective country codes
                currency_countries = {currency: CURRENCY_COUNTRY_MAP.get(currency, currency) for currency in currencies}
                logger.info(f"Currency to country mapping: {currency_countries}")
                
                filtered_events = []
                for event in events:
                    country = event["country"]
                    if country in currency_countries.values():
                        logger.info(f"Including event with country {country}: {event.get('event', '')}")
                        filtered_events.append(event)
                    else:
                        logger.info(f"Excluding event with country {country}: {event.get('event', '')}")
                events = filtered_events
                
            return await format_calendar_for_telegram(events)
        except Exception as e:
            logger.error(f"Error getting economic calendar: {str(e)}")
            return "<b>📅 Economic Calendar</b>\n\nError retrieving calendar data."

async def format_calendar_for_telegram(events: List[Dict]) -> str:
    """Format calendar events for Telegram display"""
    if not events:
        return "<b>📅 Economic Calendar</b>\n\nNo economic events found."
    
    message = "<b>📅 Economic Calendar</b>\n\n"
    message += "<b>Impact:</b> 🔴 High   🟠 Medium   🟢 Low\n\n"
    
    # Create reverse mapping from country to currency
    COUNTRY_CURRENCY_MAP = {country: currency for currency, country in CURRENCY_COUNTRY_MAP.items()}
    
    # Group events by currency
    currency_events = {}
    for event in sorted(events, key=lambda x: x["time"]):
        country = event["country"]
        # Convert country code back to currency code
        currency = COUNTRY_CURRENCY_MAP.get(country, country)
        if currency not in currency_events:
            currency_events[currency] = []
        currency_events[currency].append(event)
    
    # Format events by currency
    for currency in sorted(currency_events.keys()):
        # Get the appropriate flag emoji for the currency
        flag_emoji = CURRENCY_FLAG_MAP.get(currency, "🏴‍☠️")
        message += f"{flag_emoji} {currency}\n"
        
        for event in currency_events[currency]:
            event_time = event["time"]
            impact_emoji = IMPACT_EMOJI[event["impact"]]
            
            # Try all possible title fields
            event_title = event["event"]
            logger.info(f"Processing event for {currency} at {event_time}: {event_title}")
            
            # Format event line with time, impact emoji, and event title
            event_line = f"{event_time} - {impact_emoji} {event_title}"
            message += event_line + "\n"
    
    return message
        
        # Add values if available
        values = []
        if "previous" in event:
            values.append(f"{event['previous']}")
        if "forecast" in event:
            values.append(f"Fcst: {event['forecast']}")
        if "actual" in event:
            values.append(f"Act: {event['actual']}")
            
        if values:
            event_line += f" ({', '.join(values)})"
            
        message += event_line + "\n"
    
    return message

async def main():
    """Test the calendar service"""
    service = TradingViewCalendarService()
    events = await service.get_calendar(days_ahead=1)
    print(json.dumps(events, indent=2))
    print("\nFormatted for Telegram:")
    print(await format_calendar_for_telegram(events))

if __name__ == "__main__":
    asyncio.run(main())
