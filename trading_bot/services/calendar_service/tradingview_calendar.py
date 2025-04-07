import os
import sys
import logging
import asyncio
import json
import pandas as pd
import aiohttp
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
    "SEK": "🇸🇪",
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
    """Service for retrieving economic calendar data from TradingView's API"""
    
    def __init__(self, use_mock_data: bool = False):
        """Initialize the service"""
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing TradingViewCalendarService - Using real API data by default")
        
        # Flag to use mock data if needed
        self.use_mock_data = use_mock_data
        
        # URL for TradingView calendar API
        self.calendar_api_url = "https://economic-calendar.tradingview.com/events"
        
        # Default headers for TradingView API
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
            'Origin': 'https://in.tradingview.com',
            'Referer': 'https://in.tradingview.com/'
        }
        
        # Important economic indicators for better filtering
        self.important_indicators = [
            # High importance keywords (case insensitive)
            "interest rate", "rate decision", "fomc", "fed chair", "gdp", "nonfarm payroll",
            "employment change", "unemployment", "cpi", "inflation", "retail sales", "pmi",
            "manufacturing", "trade balance", "central bank", "ecb", "boe", "rba", "boc", "snb",
            "monetary policy", "press conference"
        ]
    
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
            
            # Fetch the calendar data from TradingView API
            events = await self._fetch_tradingview_calendar(days_ahead=days_ahead)
            
            if not events:
                self.logger.warning("No events returned from TradingView API, using mock data")
                return self._filter_by_impact(self._generate_mock_calendar_data(), min_impact)
            
            # Filter events by minimum impact level
            filtered_events = self._filter_by_impact(events, min_impact)
            
            return filtered_events
            
        except Exception as e:
            self.logger.error(f"Error getting calendar data: {e}")
            self.logger.exception(e)
            # If anything fails, use mock data
            calendar_data = self._generate_mock_calendar_data()
            return self._filter_by_impact(calendar_data, min_impact)
    
    async def _fetch_tradingview_calendar(self, days_ahead: int = 1) -> List[Dict]:
        """Fetch economic calendar data from TradingView API"""
        try:
            self.logger.info(f"Fetching calendar data from TradingView API, days ahead: {days_ahead}")
            
            # Calculate date range
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Start date is today at midnight
            start_date = today
            
            # End date is start_date + days_ahead (at least 1 day to get a full day)
            days_to_add = max(1, days_ahead)
            end_date = today + timedelta(days=days_to_add)
            
            # Prepare parameters for API call
            # We use all available countries instead of only major currencies
            params = {
                'from': start_date.isoformat() + '.000Z',
                'to': end_date.isoformat() + '.000Z',
                'countries': ','.join([CURRENCY_COUNTRY_MAP.get(curr, "") for curr in MAJOR_CURRENCIES if curr in CURRENCY_COUNTRY_MAP])
            }
            
            self.logger.info(f"API parameters: {params}")
            
            # Make API call
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(
                        self.calendar_api_url,
                        headers=self.headers,
                        params=params,
                        timeout=30  # Add explicit timeout
                    ) as response:
                        if response.status != 200:
                            self.logger.error(f"API request failed with status {response.status}")
                            # Try to get response text for better debugging
                            try:
                                error_text = await response.text()
                                self.logger.error(f"Error response: {error_text[:500]}")
                            except:
                                pass
                            return []
                        
                        data = await response.json()
                        
                        if not data or 'result' not in data:
                            self.logger.error(f"Invalid API response: {data}")
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
            
            # Save raw data for debugging
            try:
                with open("tradingview_debug.json", "w") as f:
                    json.dump(events_data, f, indent=2)
                self.logger.info("Saved raw API response to tradingview_debug.json")
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
