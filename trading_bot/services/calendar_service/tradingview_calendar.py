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
from typing import Dict, List, Any, Optional
from pathlib import Path

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

# Map of major currencies to flag emojis
CURRENCY_FLAG = {
    "USD": "🇺🇸",
    "EUR": "🇪🇺",
    "GBP": "🇬🇧",
    "JPY": "🇯🇵",
    "CHF": "🇨🇭",
    "AUD": "🇦🇺",
    "NZD": "🇳🇿",
    "CAD": "🇨🇦",
    # Extra vlaggen toevoegen
    "CNY": "🇨🇳",
    "HKD": "🇭🇰",
    "SGD": "🇸🇬",
    "INR": "🇮🇳",
    "BRL": "🇧🇷",
    "MXN": "🇲🇽",
    "ZAR": "🇿🇦", 
    "SEK": "🇸��",
    "NOK": "🇳🇴",
    "DKK": "🇩🇰",
    "PLN": "🇵🇱",
    "TRY": "🇹🇷",
    "RUB": "🇷🇺",
    "KRW": "🇰🇷",
    "ILS": "🇮🇱",
    # Ontbrekende vlaggen toevoegen
    "IDR": "🇮🇩",  # Indonesië
    "SAR": "🇸🇦",  # Saudi Arabië
    "THB": "🇹🇭",  # Thailand
    "MYR": "🇲🇾",  # Maleisië
    "PHP": "🇵🇭",  # Filipijnen
    "VND": "🇻🇳",  # Vietnam
    "UAH": "🇺🇦",  # Oekraïne  
    "AED": "🇦🇪",  # Verenigde Arabische Emiraten
    "QAR": "🇶🇦",  # Qatar
    "CZK": "🇨🇿",  # Tsjechië
    "HUF": "🇭🇺",  # Hongarije
    "RON": "🇷🇴",  # Roemenië
    "CLP": "🇨🇱",  # Chili
    "COP": "🇨🇴",  # Colombia
    "PEN": "🇵🇪",  # Peru
    "ARS": "🇦🇷"   # Argentinië
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
    """Service for retrieving economic calendar data from TradingView's API using ScrapingAnt as a proxy"""
    
    def __init__(self, use_mock_data: bool = False):
        """Initialize the service"""
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing TradingViewCalendarService - Using real API data by default")
        
        # Flag to use mock data if needed
        self.use_mock_data = use_mock_data
        
        # URL for TradingView calendar API
        self.calendar_api_url = "https://economic-calendar.tradingview.com/events"
        
        # ScrapingAnt API token
        self.scrapingant_api_key = os.environ.get("SCRAPINGANT_API_KEY", "e63e79e708d247c798885c0c320f9f30")
        
        # Use ScrapingAnt or direct connection
        self.use_scrapingant = os.environ.get("USE_SCRAPINGANT", "true").lower() in ["true", "1", "yes"]
        
        # Default headers for TradingView API
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
            'Origin': 'https://in.tradingview.com',
            'Referer': 'https://in.tradingview.com/'
        }
        
        # Enhanced headers for better API connectivity
        self.enhanced_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': 'https://www.tradingview.com',
            'Referer': 'https://www.tradingview.com/economic-calendar/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
        
        # Important economic indicators for better filtering
        self.important_indicators = [
            # High importance keywords (case insensitive)
            "interest rate", "rate decision", "fomc", "fed chair", "gdp", "nonfarm payroll",
            "employment change", "unemployment", "cpi", "inflation", "retail sales", "pmi",
            "manufacturing", "trade balance", "central bank", "ecb", "boe", "rba", "boc", "snb",
            "monetary policy", "press conference"
        ]
        
        # Log configuration
        self.logger.info(f"Using ScrapingAnt: {self.use_scrapingant}")
        self.logger.info(f"ScrapingAnt API Key: {self.scrapingant_api_key[:5]}..." if self.scrapingant_api_key else "No ScrapingAnt API Key")
        
        # Run debug connection test if needed
        if os.environ.get("DEBUG_TRADINGVIEW_API", "").lower() in ["true", "1", "yes"]:
            try:
                asyncio.create_task(self.debug_api_connection())
            except Exception as e:
                self.logger.error(f"Could not start debug task: {e}")
    
    async def fetch_via_scrapingant(self, url: str, params: Dict) -> Dict:
        """Fetch data via ScrapingAnt proxy service"""
        self.logger.info(f"Fetching via ScrapingAnt: {url}")
        
        # Build the full URL with parameters
        query_string = "&".join([f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items()])
        full_url = f"{url}?{query_string}"
        self.logger.info(f"Full URL: {full_url}")
        
        # Create connection to ScrapingAnt
        try:
            # Use aiohttp for async HTTP requests
            api_url = "https://api.scrapingant.com/v2/general"
            scraping_params = {
                'url': full_url,
                'x-api-key': self.scrapingant_api_key,
                'browser': 'false',  # API request, no need for browser rendering
                'return_text': 'true'
            }
            
            query_string = "&".join([f"{k}={urllib.parse.quote(str(v))}" for k, v in scraping_params.items()])
            scrapingant_url = f"{api_url}?{query_string}"
            
            self.logger.info(f"ScrapingAnt request URL: {api_url} (params omitted)")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(scrapingant_url, timeout=60) as response:
                    status = response.status
                    self.logger.info(f"ScrapingAnt response status: {status}")
                    
                    if status != 200:
                        error_text = await response.text()
                        self.logger.error(f"ScrapingAnt error: {error_text[:500]}")
                        return {}
                    
                    response_text = await response.text()
                    self.logger.info(f"ScrapingAnt response length: {len(response_text)} bytes")
                    
                    # Log the first part of the response
                    if len(response_text) > 0:
                        self.logger.info(f"First 200 chars: {response_text[:200]}")
                    
                    # Parse as JSON
                    try:
                        data = json.loads(response_text)
                        return data
                    except json.JSONDecodeError as e:
                        self.logger.error(f"JSON parse error: {e}")
                        return {}
            
        except Exception as e:
            self.logger.error(f"Error using ScrapingAnt: {e}")
            return {}
    
    async def debug_api_connection(self):
        """Test the TradingView API connection and log detailed results"""
        self.logger.info("DEBUG: Testing TradingView API connection...")
        
        # Standard parameters
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        params = {
            'from': today.isoformat() + '.000Z',
            'to': tomorrow.isoformat() + '.000Z'
        }
        
        # Try different variations of headers and parameters
        header_variations = [
            {"name": "Enhanced Browser", "headers": self.enhanced_headers},
            {"name": "Simple Browser", "headers": {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
                'Origin': 'https://www.tradingview.com',
                'Referer': 'https://www.tradingview.com/economic-calendar/'
            }},
            {"name": "Minimal", "headers": {
                'User-Agent': 'Mozilla/5.0'
            }}
        ]
        
        param_variations = [
            {"name": "All countries", "params": params},
            {"name": "With USD only", "params": {**params, "countries": "US"}},
            {"name": "With major countries", "params": {**params, "countries": "US,EU,GB,JP"}}
        ]
        
        # Log environment info
        self.logger.info(f"DEBUG: Running in environment: {os.environ.get('RAILWAY_ENVIRONMENT', 'local')}")
        
        # Test ScrapingAnt if enabled
        if self.use_scrapingant:
            self.logger.info("DEBUG: Testing ScrapingAnt connection")
            
            # Test params
            test_params = {
                'from': today.isoformat() + '.000Z',
                'to': tomorrow.isoformat() + '.000Z'
            }
            
            try:
                data = await self.fetch_via_scrapingant(self.calendar_api_url, test_params)
                if data and 'result' in data:
                    events = data.get('result', [])
                    self.logger.info(f"DEBUG: ScrapingAnt SUCCESS! Found {len(events)} events in response")
                else:
                    self.logger.warning("DEBUG: ScrapingAnt returned invalid data structure")
            except Exception as e:
                self.logger.error(f"DEBUG: ScrapingAnt test failed: {e}")
        
        # Test each combination for direct API access
        for header_var in header_variations:
            for param_var in param_variations:
                try:
                    self.logger.info(f"DEBUG: Testing with {header_var['name']} headers and {param_var['name']} params")
                    
                    async with aiohttp.ClientSession() as session:
                        start_time = datetime.now()
                        async with session.get(
                            self.calendar_api_url,
                            headers=header_var["headers"],
                            params=param_var["params"],
                            timeout=30
                        ) as response:
                            elapsed = (datetime.now() - start_time).total_seconds()
                            status = response.status
                            self.logger.info(f"DEBUG: API response status: {status} (time: {elapsed:.2f}s)")
                            
                            response_text = await response.text()
                            self.logger.info(f"DEBUG: Response length: {len(response_text)} bytes")
                            
                            if len(response_text) < 500:
                                self.logger.info(f"DEBUG: Full response: {response_text}")
                            else:
                                self.logger.info(f"DEBUG: First 200 chars: {response_text[:200]}")
                            
                            # Check if we got a valid response with events
                            try:
                                data = json.loads(response_text)
                                events = data.get('result', [])
                                self.logger.info(f"DEBUG: Found {len(events)} events in response")
                                
                                if events:
                                    self.logger.info(f"DEBUG: SUCCESS with {header_var['name']} headers and {param_var['name']} params")
                                    
                                    # Remember successful config for future use
                                    self.best_headers = header_var["headers"]
                                    self.best_params_template = param_var["params"]
                                    
                            except Exception as e:
                                self.logger.error(f"DEBUG: Error parsing response JSON: {e}")
                            
                except Exception as e:
                    self.logger.error(f"DEBUG: Connection error with {header_var['name']} and {param_var['name']}: {e}")
        
        self.logger.info("DEBUG: API connection test completed")
    
    async def get_calendar(self, days_ahead: int = 2, min_impact: str = "Low") -> List[Dict]:
        """Get the economic calendar events from TradingView
        
        Args:
            days_ahead: Number of days to look ahead (default: 2)
            min_impact: Minimum impact level to include (Low, Medium, High)
            
        Returns:
            List of calendar events
        """
        try:
            self.logger.info(f"Getting economic calendar from TradingView (days_ahead={days_ahead}, min_impact={min_impact})")
            
            # If mock data is requested, return it directly
            if self.use_mock_data:
                self.logger.info("Using mock data as requested")
                calendar_data = self._generate_mock_calendar_data()
                return self._filter_by_impact(calendar_data, min_impact)
            
            # First try with ScrapingAnt if enabled
            if self.use_scrapingant:
                self.logger.info("Trying to fetch calendar data using ScrapingAnt")
                events = await self._fetch_tradingview_calendar_via_scrapingant(days_ahead=days_ahead)
                
                if events and len(events) > 0:
                    self.logger.info(f"SUCCESS: Got {len(events)} events from TradingView API via ScrapingAnt")
                    filtered_events = self._filter_by_impact(events, min_impact)
                    return filtered_events
                else:
                    self.logger.warning("No events from TradingView API via ScrapingAnt, trying direct connection")
            
            # If ScrapingAnt failed or is disabled, try direct connection
            events = await self._fetch_tradingview_calendar(days_ahead=days_ahead)
            
            if events and len(events) > 0:
                self.logger.info(f"SUCCESS: Got {len(events)} events from TradingView API via direct connection")
                filtered_events = self._filter_by_impact(events, min_impact)
                return filtered_events
            else:
                self.logger.warning("No events from TradingView API, using fallback data")
            
            # If we reached this point, the API call failed or returned empty
            self.logger.info("Using fallback calendar implementation")
            try:
                from trading_bot.services.calendar_service.calendar_fix import EconomicCalendarService
                fallback = EconomicCalendarService()
                mock_data = await fallback.get_calendar(days_ahead, min_impact)
                self.logger.info(f"Successfully got {len(mock_data)} events from fallback implementation")
                return mock_data
            except Exception as fallback_error:
                self.logger.error(f"Error using fallback implementation: {fallback_error}")
                # Last resort: use our internal mock data
                calendar_data = self._generate_mock_calendar_data()
                return self._filter_by_impact(calendar_data, min_impact)
            
        except Exception as e:
            self.logger.error(f"Error getting calendar data: {e}")
            self.logger.exception(e)
            
            # Use fallback on any error
            try:
                from trading_bot.services.calendar_service.calendar_fix import EconomicCalendarService
                fallback = EconomicCalendarService()
                return await fallback.get_calendar(days_ahead, min_impact)
            except Exception:
                # If anything fails, use our internal mock data
                calendar_data = self._generate_mock_calendar_data()
                return self._filter_by_impact(calendar_data, min_impact)
    
    async def _fetch_tradingview_calendar_via_scrapingant(self, days_ahead: int = 1) -> List[Dict]:
        """Fetch calendar data via ScrapingAnt proxy"""
        try:
            self.logger.info(f"Fetching calendar data via ScrapingAnt, days ahead: {days_ahead}")
            
            # Calculate date range
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            start_date = today
            days_to_add = max(1, days_ahead)
            end_date = today + timedelta(days=days_to_add)
            
            # Prepare parameters
            params = {
                'from': start_date.isoformat() + '.000Z',
                'to': end_date.isoformat() + '.000Z'
            }
            
            # Fetch data via ScrapingAnt
            data = await self.fetch_via_scrapingant(self.calendar_api_url, params)
            
            if not data or 'result' not in data:
                self.logger.error(f"Invalid API response structure from ScrapingAnt")
                return []
            
            # Process API response
            events_data = data.get('result', [])
            self.logger.info(f"Received {len(events_data)} events from TradingView API via ScrapingAnt")
            
            # Save raw data for debugging
            try:
                with open("tradingview_debug_scrapingant.json", "w") as f:
                    json.dump(events_data, f, indent=2)
                self.logger.info("Saved API response data to tradingview_debug_scrapingant.json")
            except Exception as e:
                self.logger.warning(f"Could not save debug file: {e}")
            
            # Extract and format events
            events = self._extract_events_from_tradingview(events_data)
            
            return events
            
        except Exception as e:
            self.logger.error(f"Error fetching TradingView calendar data via ScrapingAnt: {e}")
            self.logger.exception(e)
            return []
    
    async def _fetch_tradingview_calendar(self, days_ahead: int = 1) -> List[Dict]:
        """Fetch economic calendar data from TradingView API directly"""
        try:
            self.logger.info(f"Fetching calendar data from TradingView API directly, days ahead: {days_ahead}")
            
            # Calculate date range
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Start date is today at midnight
            start_date = today
            
            # End date is start_date + days_ahead (at least 1 day to get a full day)
            days_to_add = max(1, days_ahead)
            end_date = today + timedelta(days=days_to_add)
            
            # Prepare parameters for API call
            # Try without specific countries to get all events
            params = {
                'from': start_date.isoformat() + '.000Z',
                'to': end_date.isoformat() + '.000Z',
                # Not specifying countries to get all available events
            }
            
            # Use headers that were successful in the debug test if available
            headers_to_use = getattr(self, 'best_headers', self.enhanced_headers)
            
            self.logger.info(f"API parameters: {params}")
            self.logger.info(f"Using headers: {headers_to_use.get('User-Agent', 'Not specified')}")
            
            # Log the full URL being called
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            full_url = f"{self.calendar_api_url}?{query_string}"
            self.logger.info(f"Calling API URL: {full_url}")
            
            # Make API call
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(
                        self.calendar_api_url,
                        headers=headers_to_use,
                        params=params,
                        timeout=30  # Add explicit timeout
                    ) as response:
                        status = response.status
                        self.logger.info(f"API response status: {status}")
                        
                        if status != 200:
                            self.logger.error(f"API request failed with status {status}")
                            # Try to get response text for better debugging
                            try:
                                error_text = await response.text()
                                self.logger.error(f"Error response: {error_text[:500]}")
                            except Exception as text_error:
                                self.logger.error(f"Could not read error response: {text_error}")
                            return []
                        
                        # Log response headers for debugging
                        self.logger.info(f"Response headers: {dict(response.headers)}")
                        
                        # Read response as text first for debugging
                        response_text = await response.text()
                        self.logger.info(f"Response length: {len(response_text)} bytes")
                        
                        # Save raw response for debugging
                        try:
                            with open("tradingview_response.txt", "w") as f:
                                f.write(response_text)
                            self.logger.info("Saved raw API response to tradingview_response.txt")
                        except Exception as e:
                            self.logger.warning(f"Could not save response text file: {e}")
                        
                        # Parse as JSON
                        try:
                            data = json.loads(response_text)
                        except json.JSONDecodeError as e:
                            self.logger.error(f"JSON parse error: {e}")
                            self.logger.error(f"First 200 chars of response: {response_text[:200]}")
                            return []
                        
                        if not data or 'result' not in data:
                            self.logger.error(f"Invalid API response structure: {data}")
                            return []
                
                except aiohttp.ClientError as e:
                    self.logger.error(f"HTTP request error: {e}")
                    return []
                except asyncio.TimeoutError:
                    self.logger.error("API request timed out")
                    return []
            
            # Process API response
            events_data = data.get('result', [])
            self.logger.info(f"Received {len(events_data)} events from TradingView API")
            
            # Test if return data is empty, try alternative approach
            if not events_data:
                self.logger.warning("Received empty events list, trying alternative approach")
                
                # Try with specific countries
                alt_params = params.copy()
                alt_params['countries'] = 'US,EU,GB,JP'
                
                self.logger.info(f"Trying alternative API parameters: {alt_params}")
                
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.get(
                            self.calendar_api_url,
                            headers=headers_to_use,
                            params=alt_params,
                            timeout=30
                        ) as alt_response:
                            if alt_response.status != 200:
                                self.logger.error(f"Alternative API request failed with status {alt_response.status}")
                                return []
                            
                            alt_data = await alt_response.json()
                            
                            if not alt_data or 'result' not in alt_data:
                                self.logger.error(f"Invalid alternative API response: {alt_data}")
                                return []
                            
                            events_data = alt_data.get('result', [])
                            self.logger.info(f"Received {len(events_data)} events from alternative TradingView API call")
                    
                    except Exception as alt_error:
                        self.logger.error(f"Alternative approach error: {alt_error}")
            
            # Save raw data for debugging
            try:
                with open("tradingview_debug.json", "w") as f:
                    json.dump(events_data, f, indent=2)
                self.logger.info("Saved API response data to tradingview_debug.json")
            except Exception as e:
                self.logger.warning(f"Could not save debug file: {e}")
            
            # Extract and format events
            events = self._extract_events_from_tradingview(events_data)
            
            return events
            
        except Exception as e:
            self.logger.error(f"Error fetching TradingView calendar data: {e}")
            self.logger.exception(e)
            return []
    
    def _extract_events_from_tradingview(self, events_data: List[Dict]) -> List[Dict]:
        """Extract and format economic events from TradingView API response"""
        formatted_events = []
        
        # Create reverse mapping from country code to currency
        country_to_currency = {v: k for k, v in CURRENCY_COUNTRY_MAP.items()}
        
        # Map TradingView impact levels to our format
        # Belangrijk: TradingView API gebruikt een andere waarde voor importance
        # In de API kan importance -1 zijn voor normale events
        impact_map = {
            3: "High",
            2: "Medium",
            1: "Low",
            0: "Low",
            -1: "Low"  # Veel events hebben -1 als importance maar kunnen toch belangrijk zijn
        }
        
        # Lijst met woorden die duiden op een High impact event
        high_impact_keywords = [
            "interest rate", "rate decision", "fomc", "fed chair", "gdp", 
            "nonfarm payroll", "employment change", "unemployment", "cpi", "inflation",
            "monetary policy", "central bank", "economic sentiment", "monetary policy statement"
        ]
        
        # Lijst met woorden die duiden op een Medium impact event
        medium_impact_keywords = [
            "retail sales", "pmi", "manufacturing", "trade balance", "central bank", 
            "ecb", "boe", "rba", "boc", "snb", "monetary policy", "press conference",
            "consumer confidence", "business confidence", "industrial production", "factory orders",
            "durable goods", "housing", "building permits", "construction"
        ]
        
        # Opslaan van event_time objecten voor betere sortering
        event_times = {}
        
        for event in events_data:
            try:
                # Get country code
                country_code = event.get('country')
                
                # Map country code to currency
                currency = country_to_currency.get(country_code, "")
                
                # Skip events without a known currency or not in major currencies
                if not currency or currency not in MAJOR_CURRENCIES:
                    continue
                
                # Extract time (convert to local time)
                event_time_str = event.get('date', "")
                if not event_time_str:
                    self.logger.warning(f"Missing date for event: {event.get('title', 'Unknown')}")
                    continue  # Skip events without a date
                
                try:
                    event_time = datetime.fromisoformat(event_time_str.replace('Z', '+00:00'))
                    time_str = event_time.strftime("%H:%M")
                    
                    # Sla het originele datetime object op voor betere sortering
                    event_id = f"{currency}_{event.get('id', '')}"
                    event_times[event_id] = event_time
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Invalid date format: {event_time_str} - {e}")
                    time_str = ""
                
                # Extract impact level - TradingView gebruikt verschillende manieren
                importance_value = event.get('importance')
                
                # Standaard is Low impact
                impact_level = "Low"
                
                # Probeer de importance value te bepalen
                if importance_value is not None:
                    try:
                        importance = int(importance_value)
                        impact_level = impact_map.get(importance, "Low")
                    except (ValueError, TypeError):
                        self.logger.warning(f"Invalid importance value: {importance_value}")
                        impact_level = "Low"
                
                # Haal de titel op voor keyword matching
                event_title = event.get('title', event.get('indicator', "Unknown Event")).lower()
                
                # Check voor High impact keywords
                if any(keyword in event_title for keyword in high_impact_keywords):
                    impact_level = "High"
                # Als het niet High is, check voor Medium impact
                elif any(keyword in event_title for keyword in medium_impact_keywords):
                    impact_level = "Medium"
                
                # Speciale gevallen op basis van ervaring met TradingView
                if "fomc" in event_title or "fed" in event_title:
                    impact_level = "High"
                elif "pmi" in event_title:
                    impact_level = "Medium"
                elif "gdp" in event_title:
                    impact_level = "High"
                elif "cpi" in event_title or "inflation" in event_title:
                    impact_level = "High"
                
                # Format title with period
                if event.get('period'):
                    event_title = f"{event.get('title', event.get('indicator', 'Unknown Event'))} ({event.get('period')})"
                else:
                    event_title = event.get('title', event.get('indicator', 'Unknown Event'))
                
                # Get values, handling None and formatting
                forecast = event.get('forecast')
                previous = event.get('previous')
                actual = event.get('actual')
                
                # Create formatted event
                formatted_event = {
                    "time": time_str,
                    "country": currency,
                    "country_flag": CURRENCY_FLAG.get(currency, ""),
                    "title": event_title,
                    "impact": impact_level,
                    # Additional fields that might be useful
                    "forecast": forecast if forecast is not None else "",
                    "previous": previous if previous is not None else "",
                    "actual": actual if actual is not None else "",
                    # ID voor chronologische sortering
                    "event_id": event_id
                }
                
                formatted_events.append(formatted_event)
                
            except Exception as e:
                self.logger.error(f"Error processing event: {e}")
                self.logger.error(f"Event data: {event}")
                continue
        
        # Sort events chronologically using the stored datetime objects
        try:
            formatted_events = sorted(formatted_events, key=lambda x: event_times.get(x.get('event_id'), datetime.min))
        except Exception as e:
            self.logger.error(f"Error sorting events: {e}")
            # Fallback naar string-based sortering als datetime sortering faalt
            formatted_events = sorted(formatted_events, key=lambda x: x.get('time', '00:00'))
        
        self.logger.info(f"Extracted {len(formatted_events)} formatted events")
        return formatted_events
    
    def _generate_mock_calendar_data(self) -> List[Dict]:
        """Generate mock calendar data when extraction fails"""
        self.logger.info("Generating mock calendar data")
        
        # Gebruik de custom mock data als deze beschikbaar is
        if HAS_CUSTOM_MOCK_DATA:
            self.logger.info("Using custom mock calendar data")
            return generate_mock_calendar_data()
        
        # Als de custom mock data niet beschikbaar is, gebruik de standaard mock data
        self.logger.info("Using default mock calendar data")
        
        # Get today's date
        today = datetime.now().strftime("%Y-%m-%d")
        
        mock_data = [
            {
                "time": "08:30",
                "country": "USD",
                "country_flag": "🇺🇸",
                "title": "Initial Jobless Claims",
                "impact": "Medium",
                "forecast": "225K",
                "previous": "230K"
            },
            {
                "time": "10:00",
                "country": "USD",
                "country_flag": "🇺🇸",
                "title": "Fed Chair Speech",
                "impact": "High",
                "forecast": "",
                "previous": ""
            },
            {
                "time": "07:45",
                "country": "EUR",
                "country_flag": "🇪🇺",
                "title": "ECB Interest Rate Decision",
                "impact": "High",
                "forecast": "4.50%",
                "previous": "4.50%"
            },
            {
                "time": "08:30",
                "country": "EUR",
                "country_flag": "🇪🇺",
                "title": "ECB Press Conference",
                "impact": "High",
                "forecast": "",
                "previous": ""
            },
            {
                "time": "09:00",
                "country": "GBP",
                "country_flag": "🇬🇧",
                "title": "Manufacturing PMI",
                "impact": "Medium",
                "forecast": "49.5",
                "previous": "49.2"
            },
            {
                "time": "00:30",
                "country": "JPY",
                "country_flag": "🇯🇵",
                "title": "Tokyo CPI",
                "impact": "Medium",
                "forecast": "2.6%",
                "previous": "2.5%"
            },
            {
                "time": "21:30",
                "country": "AUD",
                "country_flag": "🇦🇺",
                "title": "Employment Change",
                "impact": "High",
                "forecast": "25.3K",
                "previous": "20.2K"
            },
            {
                "time": "13:30",
                "country": "CAD",
                "country_flag": "🇨🇦",
                "title": "Trade Balance",
                "impact": "Medium",
                "forecast": "1.2B",
                "previous": "0.9B"
            }
        ]
        
        return mock_data
    
    def _filter_by_impact(self, events: List[Dict], min_impact: str) -> List[Dict]:
        """Filter events by impact level"""
        impact_levels = {
            "Low": 1,
            "Medium": 2,
            "High": 3
        }
        
        min_level = impact_levels.get(min_impact, 1)
        
        filtered = [
            event for event in events 
            if impact_levels.get(event.get("impact", "Low"), 1) >= min_level
        ]
        
        self.logger.info(f"Filtered events by impact level {min_impact}: {len(filtered)} of {len(events)} events")
        return filtered

async def format_calendar_for_telegram(events: List[Dict]) -> str:
    """Format the calendar data for Telegram display"""
    if not events:
        return "<b>📅 Economic Calendar</b>\n\nNo economic events found for today."
    
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
                logger.error(f"Error parsing time for sorting: {str(e)}")
                return 0
        
        sorted_events = sorted(events, key=parse_time_for_sorting)
    except Exception as e:
        logger.error(f"Error sorting calendar events: {str(e)}")
        sorted_events = events
    
    # Format the message
    message = "<b>📅 Economic Calendar</b>\n\n"
    
    for event in sorted_events:
        country = event.get("country", "")
        country_flag = event.get("country_flag", "")
        time = event.get("time", "")
        title = event.get("title", "")
        impact = event.get("impact", "Low")
        impact_emoji = IMPACT_EMOJI.get(impact, "🟢")
        
        # Include forecast and previous data if available
        forecast = event.get("forecast", "")
        previous = event.get("previous", "")
        actual = event.get("actual", "")
        
        details = ""
        if forecast or previous or actual:
            details_parts = []
            if actual:
                details_parts.append(f"A: {actual}")
            if forecast:
                details_parts.append(f"F: {forecast}")
            if previous:
                details_parts.append(f"P: {previous}")
            
            if details_parts:
                details = f" ({', '.join(details_parts)})"
        
        message += f"{time} {country_flag} <b>{country}</b> - {title}{details} {impact_emoji}\n"
    
    # Add legend
    message += "\n-------------------\n"
    message += "🔴 High Impact\n"
    message += "🟠 Medium Impact\n"
    message += "🟢 Low Impact\n"
    message += "A: Actual, F: Forecast, P: Previous"
    
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
