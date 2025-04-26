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

# Zorg ervoor dat HAS_CUSTOM_MOCK_DATA False is, aangezien we geen mock data gebruiken
HAS_CUSTOM_MOCK_DATA = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

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
        """Check if the TradingView API endpoint is working"""
        try:
            await self._ensure_session()
            
            # Simple health check request with minimal parameters
            params = {
                'from': self._format_date(datetime.now()),
                'to': self._format_date(datetime.now() + timedelta(days=1)),
                'limit': 1
            }
            
            # Add headers for better API compatibility
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
                "Accept": "application/json",
                "Origin": "https://www.tradingview.com",
                "Referer": "https://www.tradingview.com/economic-calendar/"
            }
            
            # Make request to TradingView
            full_url = f"{self.base_url}"
            logger.info(f"Checking API health: {full_url}")
            
            async with self.session.get(full_url, params=params, headers=headers) as response:
                logger.info(f"Health check response status: {response.status}")
                return response.status == 200
                
        except Exception as e:
            logger.error(f"API health check failed: {str(e)}")
            return False
        
    async def get_calendar(self, days_ahead: int = 0, min_impact: str = "Low", currency: str = None) -> List[Dict[str, Any]]:
        """
        Fetch calendar events from TradingView
        
        Args:
            days_ahead: Number of days to look ahead
            min_impact: Minimum impact level to include (Low, Medium, High)
            currency: Optional currency to filter events by
            
        Returns:
            List of calendar events
        """
        try:
            logger.info(f"Starting calendar fetch from TradingView (days_ahead={days_ahead}, min_impact={min_impact}, currency={currency})")
            await self._ensure_session()
            
            # First check if the API is healthy
            is_healthy = await self._check_api_health()
            if not is_healthy:
                logger.error("TradingView API is not healthy, using fallback or returning empty list")
                if HAS_CUSTOM_MOCK_DATA:
                    logger.info("Falling back to mock calendar data due to unhealthy API")
                    return generate_mock_calendar_data(days_ahead, min_impact)
                return []
            
            # Calculate date range
            start_date = datetime.now()
            # Always make sure end_date is at least 1 day after start_date
            end_date = start_date + timedelta(days=max(1, days_ahead))
            
            # Prepare request parameters with correct format
            params = {
                'from': self._format_date(start_date),
                'to': self._format_date(end_date),
                'countries': 'US,EU,GB,JP,CH,AU,NZ,CA',  # Include all major countries
                'limit': 1000
            }
            
            # Filter by country if currency is specified
            if currency:
                logger.info(f"Filtering by currency: {currency}")
                # Map currency code to country code
                currency_to_country = {
                    'USD': 'US',
                    'EUR': 'EU',
                    'GBP': 'GB',
                    'JPY': 'JP',
                    'CHF': 'CH',
                    'AUD': 'AU',
                    'NZD': 'NZ',
                    'CAD': 'CA'
                }
                country_code = currency_to_country.get(currency)
                if country_code:
                    params['countries'] = country_code
                    logger.info(f"Set country filter to {country_code}")
            
            logger.info(f"Requesting calendar with params: {params}")
            
            # Add headers for better API compatibility
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
                "Accept": "application/json",
                "Origin": "https://www.tradingview.com",
                "Referer": "https://www.tradingview.com/economic-calendar/"
            }
            
            # Make request to TradingView
            full_url = f"{self.base_url}"
            logger.info(f"Making request to: {full_url}")
            
            # Use a custom timeout to prevent hanging forever
            timeout = aiohttp.ClientTimeout(total=15)
            async with self.session.get(full_url, params=params, headers=headers, timeout=timeout) as response:
                logger.info(f"Got response with status: {response.status}")
                
                if response.status != 200:
                    response_text = await response.text()
                    logger.error(f"Error response from TradingView (status {response.status}): {response_text[:200]}")
                    
                    # Log more detailed error information for debugging
                    if response.status == 404:
                        logger.error(f"404 Not Found error for URL: {full_url}?{urllib.parse.urlencode(params)}")
                    
                    # Fallback naar mock data als de API faalt
                    if HAS_CUSTOM_MOCK_DATA:
                        logger.info("Falling back to mock calendar data")
                        return generate_mock_calendar_data(days_ahead, min_impact)
                    return []
                    
                # Update the last successful call timestamp
                self.last_successful_call = datetime.now()
                
                try:
                    response_text = await response.text()
                    
                    # Check if we received HTML instead of JSON
                    if "<html" in response_text.lower():
                        logger.error("Received HTML response instead of JSON data")
                        logger.error(f"HTML content (first 200 chars): {response_text[:200]}...")
                        
                        # TradingView might load data through JavaScript
                            # For now, fall back to mock data
                            if HAS_CUSTOM_MOCK_DATA:
                                logger.info("Falling back to mock calendar data due to HTML response")
                                return generate_mock_calendar_data(days_ahead, min_impact)
                            return []
                        try:
                        return events_to_return
                    # COMMENT: except block removed due to indentation error
                    logger.error("Error processing response")
                            logger.error(f"Failed to extract data from HTML: {str(e)}")
                            if HAS_CUSTOM_MOCK_DATA:
                                logger.info("Falling back to mock calendar data")
                                return generate_mock_calendar_data(days_ahead, min_impact)
                            return []
                    
                    # Clean up invalid JSON - fix common issues like semicolons after URLs
                    # This pattern fixes the issue with semicolons after URLs in source_url fields
                    response_text = response_text.replace('";,', '",')
                    response_text = response_text.replace('";', '"')
                    
                    # Fix specifically for the pattern observed in logs
                    # Handle "http://www.api.org";, pattern
                    response_text = re.sub(r'"(http://www\.api\.org)";,', r'"\1",', response_text)
                    # Handle "http://www.federalreserve.gov/";, pattern
                    response_text = re.sub(r'"(http://www\.federalreserve\.gov/)";,', r'"\1",', response_text)
                    # Handle other API URLs with trailing semicolons
                    response_text = re.sub(r'"(https?://[^"]+\.gov[^"]*)";,', r'"\1",', response_text)
                    response_text = re.sub(r'"(https?://[^"]+\.org[^"]*)";,', r'"\1",', response_text)
                    response_text = re.sub(r'"(https?://[^"]+\.com[^"]*)";,', r'"\1",', response_text)
                    
                    # Additional cleanup for invalid JSON patterns found in the logs
                    # Fix patterns like: "source_url": "http://www.site.com";,
                    response_text = re.sub(r'"source_url"\s*:\s*"(https?://[^"]+)";,', r'"source_url": "\1",', response_text)
                    # Fix patterns like: "source_url": "http://www.site.com";
                    response_text = re.sub(r'"source_url"\s*:\s*"(https?://[^"]+)";', r'"source_url": "\1"', response_text)
                    
                    # More general pattern to catch any stray semicolons after quoted strings in the JSON
                    response_text = re.sub(r'";(\s*[,}])', r'"\1', response_text)
                    
                    # Check for any remaining problematic URL patterns
                    url_patterns = [
                        r'"source_url"\s*:\s*"[^"]+";',
                        r'"https?://[^"]+";',
                        r'";,'
                    ]
                    
                    for pattern in url_patterns:
                        matches = re.findall(pattern, response_text)
                        if matches:
                            logger.warning(f"Found {len(matches)} instances of problematic pattern: {pattern}")
                            for i, match in enumerate(matches[:3]):  # Show first 3 examples
                                logger.warning(f"  Match {i+1}: {match}")
                    
                    # Log cleaned response for debugging if there were issues
                    if '";' in response_text or '";,' in response_text:
                        logger.warning("Potential JSON issues still exist after cleaning, showing first 200 chars:")
                        logger.warning(f"Cleaned response: {response_text[:200]}...")
                    
                    # Final, extreme measure - replace all remaining semicolons after quotes with proper JSON
                    if '";' in response_text:
                        logger.warning("Applying extreme JSON fixing measures")
                        # This is a last resort - it might cause data loss but it's better than failing
                        final_fixed = re.sub(r'";([^,])', r'"\1', response_text)
                        # Only use this if it looks like it didn't break the JSON structure
                        if final_fixed.count('{') == response_text.count('{') and final_fixed.count('}') == response_text.count('}'):
                            logger.info("Applied extreme measures without changing JSON structure")
                            response_text = final_fixed
                    
                    # Last resort - try to fix malformed JSON with a more comprehensive approach
                    def fix_json_urls(json_str):
                        # This function systematically finds all URL patterns and ensures they're properly formatted
                        # Pattern to find URL fields in JSON: "field_name": "http://...";
                        url_pattern = re.compile(r'"([^"]+)"\s*:\s*"(https?://[^"]+)";([\s,}])')
                        
                        # Keep replacing until no more matches
                        last_str = ""
                        current_str = json_str
                        iteration = 0
                        max_iterations = 10  # Avoid infinite loops
                        
                        while last_str != current_str and iteration < max_iterations:
                            last_str = current_str
                            current_str = url_pattern.sub(r'"\1": "\2"\3', current_str)
                            iteration += 1
                        
                        if iteration > 0 and iteration < max_iterations:
                            logger.info(f"Fixed JSON URLs with {iteration} replacements")
                        elif iteration == max_iterations:
                            logger.warning("Reached maximum iterations while fixing JSON URLs")
                        
                        return current_str
                    
                    # Apply the comprehensive URL fix
                    response_text = fix_json_urls(response_text)
                    
                    try:
                        data = json.loads(response_text)
                        # Log response structure for debugging
                        logger.info(f"Response type: {type(data)}")
                        if isinstance(data, dict):
                            logger.info(f"Dictionary keys: {list(data.keys())}")
                            # Log a sample of the first few keys and values
                            sample = {k: data[k] for k in list(data.keys())[:3]}
                            logger.info(f"Sample data: {json.dumps(sample, indent=2)[:500]}...")
                    except json.JSONDecodeError as je:
                        logger.error(f"Failed to parse JSON response: {str(je)}")
                        logger.error(f"Raw response content (first 200 chars): {response_text[:200]}...")
                        
                        # Enhanced error logging with position information
                        error_pos = je.pos
                        start_pos = max(0, error_pos - 50)
                        end_pos = min(len(response_text), error_pos + 50)
                        context = response_text[start_pos:end_pos]
                        pointer = ' ' * (min(50, error_pos - start_pos)) + '^'
                        logger.error(f"Error context: {context}")
                        logger.error(f"Error position: {pointer}")
                        
                        # Last desperate attempt - try to manually fix the JSON around the error point
                        try:
                            # Calculate a safer region around the error
                            safe_start = max(0, error_pos - 200)
                            safe_end = min(len(response_text), error_pos + 200)
                            error_region = response_text[safe_start:safe_end]
                            
                            # Common patterns at error locations
                            fixes = [
                                (r'";,', '",'),     # Fix semicolon before comma
                                (r'";(\s*})', '"\1'),  # Fix semicolon before closing brace
                                (r'";(\s*$)', '"'),   # Fix trailing semicolon
                                (r'"([^"]*);([^"]*)"', r'"\1;\2"')  # Fix semicolons within quotes
                            ]
                            
                            # Apply fixes around the error location
                            fixed_region = error_region
                            for pattern, replacement in fixes:
                                fixed_region = re.sub(pattern, replacement, fixed_region)
                            
                            # Replace the region in the full text
                            patched_text = response_text[:safe_start] + fixed_region + response_text[safe_end:]
                            
                            # Try parsing again
                            logger.info("Attempting to parse with emergency fixes")
                            data = json.loads(patched_text)
                            logger.info("Emergency JSON fix successful!")
                        except Exception as e2:
                            logger.error(f"Emergency JSON fix failed: {str(e2)}")
                            if HAS_CUSTOM_MOCK_DATA:
                                logger.info("Falling back to mock calendar data")
                                return generate_mock_calendar_data(days_ahead, min_impact)
                            return []
                    
                    try:
                        if not isinstance(data, list):
                            logger.info(f"Response format is: {type(data)}")
                        
                            # Handle dictionary format with 'result' key (TradingView API format)
                            if isinstance(data, dict) and "result" in data:
                                status = data.get("status", "unknown")
                                if status != "ok":
                                    logger.error(f"TradingView API returned non-OK status: {status}")
                                    if HAS_CUSTOM_MOCK_DATA:
                                        logger.info("Falling back to mock calendar data due to API status")
                                        return generate_mock_calendar_data(days_ahead, min_impact)
                                    return []
                                
                                if isinstance(data["result"], list):
                                    data = data["result"]
                                    logger.info(f"Extracted result list from response, found {len(data)} items")
                                else:
                                    logger.error(f"Result field is not a list: {type(data['result'])}")
                                    if HAS_CUSTOM_MOCK_DATA:
                                        logger.info("Falling back to mock calendar data")
                                        return generate_mock_calendar_data(days_ahead, min_impact)
                                    return []
                            # Try old format with 'data' key as fallback
                            elif isinstance(data, dict) and "data" in data:
                                if isinstance(data["data"], list):
                                    data = data["data"]
                                    logger.info(f"Extracted data list from dictionary response, found {len(data)} items")
                                else:
                                    logger.error(f"Data field is not a list: {type(data['data'])}")
                                    if HAS_CUSTOM_MOCK_DATA:
                                        logger.info("Falling back to mock calendar data")
                                        return generate_mock_calendar_data(days_ahead, min_impact)
                                    return []
                            else:
                                logger.error("Response is not a list and does not contain expected fields")
                                if HAS_CUSTOM_MOCK_DATA:
                                    logger.info("Falling back to mock calendar data")
                                    return generate_mock_calendar_data(days_ahead, min_impact)
                                return []
                        
                        logger.info(f"Received {len(data)} items from API")
                        
                        # Log de eerste paar events voor debugging
                        for i, event in enumerate(data[:5]):
                            logger.info(f"Raw event {i+1}: {json.dumps(event)}")
                        
                        # Transform TradingView data to our format
                        events = []
                        skipped_events = 0
                        unknown_countries = set()
                        non_major_events = 0
                        
                        for event in data:
                            try:
                                # Gebruik de omgekeerde van CURRENCY_COUNTRY_MAP voor volledige dekking
                                # Bouw een country-to-currency mapping op basis van de CURRENCY_COUNTRY_MAP
                                country_to_currency = {country: currency for currency, country in CURRENCY_COUNTRY_MAP.items()}
                                
                                # Map importance levels from numeric to text
                                # Based on TradingView's numeric representation (1=low, 2=medium, 3=high)
                                importance_map = {
                                    3: "High",
                                    2: "Medium",
                                    1: "Low"
                                }
                                
                                # Gebruik direct het currency veld uit het event als het aanwezig is
                                if "currency" in event and event["currency"]:
                                    currency_code = event["currency"]
                                else:
                                    # Fallback naar country-to-currency mapping
                                    country = event.get("country", "")
                                    currency_code = country_to_currency.get(country, "")
                                
                                # Als de valuta onbekend is, log en sla over
                                if not currency_code:
                                    logger.info(f"Skipping event with unknown country code: '{country}' for event: '{event.get('title', 'Unknown')}'")
                                    skipped_events += 1
                                    unknown_countries.add(country)
                                    continue
                                
                                # Only skip non-major currencies if a specific currency is requested
                                # When no currency is specified, show all events for all major currencies
                                if currency and currency_code not in MAJOR_CURRENCIES:
                                    logger.debug(f"Skipping non-major currency: {currency_code}")
                                    non_major_events += 1
                                    continue
                                
                                # Extract the time from the date field
                                date_str = event.get("date", "")
                                if not date_str:
                                    logger.debug(f"Skipping event without date: {event.get('title', 'Unknown')}")
                                    continue
                                
                                # Convert ISO date string to datetime and format just the time
                                try:
                                    event_time = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                                    time_str = event_time.strftime("%H:%M")
                                except (ValueError, TypeError) as e:
                                    logger.error(f"Error parsing date '{date_str}': {str(e)}")
                                    time_str = "00:00"  # Default time if parsing fails
                                
                                # Get importance level - handle both numeric and string values
                                importance_value = event.get("importance", 1)  # Default to low if not specified
                                if isinstance(importance_value, int):
                                    impact = importance_map.get(importance_value, "Low")
                                else:
                                    # Handle string values for backward compatibility
                                    impact = importance_value.capitalize() if isinstance(importance_value, str) else "Low"
                                
                                # Create event object
                                event_obj = {
                                    "country": currency_code,
                                    "time": time_str,
                                    "event": event.get("title", ""),
                                    "impact": impact
                                }
                                
                                # Add additional information if available
                                if "actual" in event and event["actual"]:
                                    event_obj["actual"] = event["actual"]
                                if "previous" in event and event["previous"]:
                                    event_obj["previous"] = event["previous"]
                                if "forecast" in event and event["forecast"]:
                                    event_obj["forecast"] = event["forecast"]
                                
                                events.append(event_obj)
                                logger.debug(f"Added event: {event_obj}")
                                
                                # Log volledige events voor de eerste 3 items (debug)
                                if len(events) <= 3:
                                    logger.info(f"Processed event {len(events)}: From '{event.get('title', '')}' ({event.get('country', '')}) to {json.dumps(event_obj)}")
                                
                            try:
                        return events_to_return
                    # COMMENT: except block removed due to indentation error
                    logger.error("Error processing response")
                                logger.error(f"Error processing event {event}: {str(e)}")
                                continue
                        
                        logger.info(f"Processed {len(events)} valid events")
                        
                        # Filter by minimum impact if specified
                        if min_impact != "Low":
                            impact_levels = ["High", "Medium", "Low"]
                            min_impact_idx = impact_levels.index(min_impact)
                            events = [e for e in events if impact_levels.index(e["impact"]) <= min_impact_idx]
                            logger.info(f"After impact filtering: {len(events)} events")
                        
                        # Sort events by time
                        events.sort(key=lambda x: x["time"])
                        
                        # Log summary with filter statistics
                        logger.info(f"Calendar processing summary:")
                        logger.info(f"- Total events from API: {len(data)}")
                        logger.info(f"- Events with unknown country codes: {skipped_events} ({', '.join(unknown_countries) if unknown_countries else 'none'})")
                        logger.info(f"- Events with non-major currencies: {non_major_events}")
                        logger.info(f"- Final events after filtering: {len(events)}")
                        
                        # Log success with useful information
                        logger.info(f"Successfully processed calendar data with {len(events)} events from TradingView API")
                        if self.last_successful_call:
                            logger.info(f"Last successful API call was at {self.last_successful_call.isoformat()}")
                        
                        # After getting events, highlight the events for the specified currency without filtering out others
                        if currency and len(events) > 0:
                            logger.info(f"Highlighting events for currency: {currency}")
                            # Add highlighted flag to events matching the requested currency
                            for event in events:
                                event["highlighted"] = event.get('country') == currency
                            
                            # Log that we're showing all events with highlighted currency
                            highlighted_count = sum(1 for e in events if e.get("highlighted", False))
                            logger.info(f"Showing all {len(events)} events with {highlighted_count} {currency} events highlighted")
                        
                    return events
                    
                except Exception as e:
                        logger.error(f"Error processing response: {str(e)}")
                    return []
                
        except Exception as e:
            logger.error(f"Error fetching calendar data: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []
            
        finally:
            await self._close_session()

    async def debug_api_connection(self):
        """Perform detailed API connection debugging"""
        logger.info("Starting TradingView API connection debug")
        debug_info = {
            "api_health": False,
            "connection_error": None,
            "events_retrieved": 0,
            "sample_events": [],
            "last_successful_call": None,
            "test_time": datetime.now().isoformat()
        }
        
        try:
            # Check API health
            await self._ensure_session()
            is_healthy = await self._check_api_health()
            debug_info["api_health"] = is_healthy
            
            if is_healthy:
                # Try to retrieve events
                events = await self.get_calendar(days_ahead=0)
                debug_info["events_retrieved"] = len(events)
                if events:
                    # Include a sample of first 3 events
                    debug_info["sample_events"] = events[:3]
                
                # Record last successful call
                debug_info["last_successful_call"] = self.last_successful_call.isoformat() if self.last_successful_call else None
            
            logger.info(f"API debug completed: health={debug_info['api_health']}, events={debug_info['events_retrieved']}")
            return debug_info
            
        except Exception as e:
            logger.error(f"Error during API debug: {str(e)}")
            debug_info["connection_error"] = str(e)
            return debug_info
        
        finally:
            await self._close_session()

    async def get_economic_calendar(self, currencies: List[str] = None, days_ahead: int = 0, min_impact: str = "Low") -> str:
        """
        Fetch and format economic calendar events for multiple currencies
        
        Args:
            currencies: List of currency codes to filter events by (e.g. ["EUR", "USD"])
            days_ahead: Number of days to look ahead
            min_impact: Minimum impact level to include (Low, Medium, High)
            
        Returns:
            Formatted HTML string with calendar data
        """
        try:
            logger.info(f"Getting economic calendar for currencies: {currencies}, days_ahead: {days_ahead}")
            
            # Get all events from TradingView (we'll filter by currency ourselves)
            all_events = await self.get_calendar(days_ahead=days_ahead, min_impact=min_impact)
            logger.info(f"Got {len(all_events)} events from TradingView")
            
            # Filter by currencies if provided
            filtered_events = all_events
            if currencies:
                filtered_events = [
                    event for event in all_events 
                    if event.get('country') in currencies
                ]
                logger.info(f"Filtered to {len(filtered_events)} events for currencies: {currencies}")
                
                # If no events found after filtering, try to get events for all major currencies
                if not filtered_events:
                    logger.info(f"No events found for {currencies}, fetching for all major currencies")
                    filtered_events = all_events
            
            # Format the events
            formatted_calendar = await format_calendar_for_telegram(filtered_events)
            
            return formatted_calendar
            
        except Exception as e:
            logger.error(f"Error in get_economic_calendar: {str(e)}")
            logger.exception(e)
            
            # Return a minimal calendar with error message
            return "<b>📅 Economic Calendar</b>\n\nSorry, there was an error retrieving the economic calendar data."

async def format_calendar_for_telegram(events: List[Dict]) -> str:
    """Format the calendar data for Telegram display"""
    if not events:
        logger.warning("No events provided to format_calendar_for_telegram")
        return "<b>📅 Economic Calendar</b>\n\nNo economic events found for today."
    
    # Count events per type
    logger.info(f"Formatting {len(events)} events for Telegram")
    event_counts = {"total": len(events), "valid": 0, "missing_fields": 0, "highlighted": 0}
    
    # Log all events to help diagnose issues
    logger.info(f"Events to format: {json.dumps(events[:5], indent=2)}")
    
    # Sort events by time if not already sorted
    try:
        # Verbeterde sortering met datetime objecten
        def parse_time_for_sorting(event):
            time_str = event.get("time", "00:00")
            try:
                if ":" in time_str:
                    hours, minutes = time_str.split(":")
                    # Strip any AM/PM/timezone indicators
                    hours = hours.strip()
                    if " " in minutes:
                        minutes = minutes.split(" ")[0]
                    return int(hours) * 60 + int(minutes)
                return 0
            except Exception as e:
                logger.error(f"Error parsing time for sorting: {str(e)} for time: {time_str}")
                return 0
        
        sorted_events = sorted(events, key=parse_time_for_sorting)
        logger.info(f"Sorted {len(sorted_events)} events by time")
    except Exception as e:
        logger.error(f"Error sorting calendar events: {str(e)}")
        sorted_events = events
    
    # Format the message
    message = "<b>📅 Economic Calendar</b>\n\n"
    
    # Add impact legend
    message += "<b>Impact:</b> 🔴 High   🟠 Medium   🟢 Low\n\n"
    
    # Display events in chronological order without grouping by country
    for i, event in enumerate(sorted_events):
        try:
            country = event.get("country", "")
            time = event.get("time", "")
            title = event.get("event", "")
            impact = event.get("impact", "Low")
            impact_emoji = IMPACT_EMOJI.get(impact, "🟢")
            
            # Check if this event is highlighted (specific to the requested currency)
            is_highlighted = event.get("highlighted", False)
            if is_highlighted:
                event_counts["highlighted"] += 1
            
            # Log each event being processed for debugging
            logger.debug(f"Processing event {i+1}: {json.dumps(event)}")
            
            # Controleer of alle benodigde velden aanwezig zijn
            if not country or not time or not title:
                missing = []
                if not country: missing.append("country")
                if not time: missing.append("time") 
                if not title: missing.append("event")
                
                logger.warning(f"Event {i+1} missing fields: {', '.join(missing)}: {json.dumps(event)}")
                event_counts["missing_fields"] += 1
                continue
            
            # Format the line with enhanced visibility for country - bold if highlighted
            country_text = f"<b>{country}</b>" if is_highlighted else country
            # Add a special marker for highlighted events to make them more visible
            prefix = "➤ " if is_highlighted else ""
            event_line = f"{time} - 「{country_text}」 - {prefix}{title} {impact_emoji}"
            
            # Add previous/forecast/actual values if available
            values = []
            if "previous" in event and event["previous"] is not None:
                values.append(f"{event['previous']}")
            if "forecast" in event and event["forecast"] is not None:
                values.append(f"Fcst: {event['forecast']}")
            if "actual" in event and event["actual"] is not None:
                values.append(f"Act: {event['actual']}")
                
            if values:
                event_line += f" ({', '.join(values)})"
                
            message += event_line + "\n"
            event_counts["valid"] += 1
            
            # Log first few formatted events for debugging
            if i < 5:
                logger.info(f"Formatted event {i+1}: {event_line}")
        except Exception as e:
            logger.error(f"Error formatting event {i+1}: {str(e)}")
            logger.error(f"Problematic event: {json.dumps(event)}")
            continue
    
    if event_counts["valid"] == 0:
        logger.warning("No valid events to display in calendar")
        message += "No valid economic events found for today.\n"
    
    # Add legend with explanation of formatting
    message += "\n-------------------\n"
    message += "🔴 High Impact\n"
    message += "🟠 Medium Impact\n"
    message += "🟢 Low Impact\n"
    # Add note about highlighted events
    message += "➤ Primary currency events are in <b>bold</b>\n"
    
    # Log event counts
    logger.info(f"Telegram formatting: {event_counts['valid']} valid events, {event_counts['highlighted']} highlighted events, {event_counts['missing_fields']} skipped due to missing fields")
    logger.info(f"Final message length: {len(message)} characters")
    
    return message

async def main():
    """Test the TradingView calendar service"""
    # Create the service
    service = TradingViewCalendarService()
    
    # Get calendar data
    calendar_data = await service.get_calendar(days_ahead=3)
    
    # Print the results
    logger.info(f"Got {len(calendar_data)} events from TradingView")
    print(json.dumps(calendar_data, indent=2))
    
    # Format the events for Telegram
    telegram_message = await format_calendar_for_telegram(calendar_data)
    print("\nTelegram Message Format:")
    print(telegram_message)

if __name__ == "__main__":
    asyncio.run(main()) 
