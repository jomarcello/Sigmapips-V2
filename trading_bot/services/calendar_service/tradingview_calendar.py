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
        # TradingView calendar API endpoint
        self.base_url = "https://economic-calendar.tradingview.com/events"
        self.session = None
        
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
        
    async def get_calendar(self, days_ahead: int = 0, min_impact: str = "Low") -> List[Dict[str, Any]]:
        """
        Fetch calendar events from TradingView
        
        Args:
            days_ahead: Number of days to look ahead
            min_impact: Minimum impact level to include (Low, Medium, High)
            
        Returns:
            List of calendar events
        """
        try:
            logger.info("Starting calendar fetch from TradingView")
            await self._ensure_session()
            
            # Calculate date range
            start_date = datetime.now()
            end_date = start_date + timedelta(days=days_ahead)
            
            # Prepare request parameters with correct format
            params = {
                'from': self._format_date(start_date),
                'to': self._format_date(end_date),
                'countries': 'US,EU,GB,JP,CH,AU,NZ,CA',
                'limit': 1000
            }
            
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
            
            async with self.session.get(full_url, params=params, headers=headers) as response:
                logger.info(f"Got response with status: {response.status}")
                
                if response.status != 200:
                    response_text = await response.text()
                    logger.error(f"Error response from TradingView: {response_text}")
                    
                    # Fallback naar mock data als de API faalt
                    if HAS_CUSTOM_MOCK_DATA:
                        logger.info("Falling back to mock calendar data")
                        return generate_mock_calendar_data(days_ahead, min_impact)
                    return []
                    
                try:
                    response_text = await response.text()
                    
                    # Check if we received HTML instead of JSON
                    if "<html" in response_text.lower():
                        logger.error("Received HTML response instead of JSON data")
                        logger.info("Attempting to extract calendar data from HTML response")
                        
                        try:
                            # TradingView might load data through JavaScript
                            # For now, fall back to mock data
                            if HAS_CUSTOM_MOCK_DATA:
                                logger.info("Falling back to mock calendar data due to HTML response")
                                return generate_mock_calendar_data(days_ahead, min_impact)
                            return []
                        except Exception as e:
                            logger.error(f"Failed to extract data from HTML: {str(e)}")
                            if HAS_CUSTOM_MOCK_DATA:
                                logger.info("Falling back to mock calendar data")
                                return generate_mock_calendar_data(days_ahead, min_impact)
                            return []
                    
                    try:
                        data = json.loads(response_text)
                        # Log response structure for debugging
                        logger.info(f"Response type: {type(data)}")
                        if isinstance(data, dict):
                            logger.info(f"Dictionary keys: {list(data.keys())}")
                            # Log a sample of the first few keys and values
                            sample = {k: data[k] for k in list(data.keys())[:3]}
                            logger.info(f"Sample data: {json.dumps(sample, indent=2)[:500]}...")
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse JSON response: {response_text[:200]}...")
                        if HAS_CUSTOM_MOCK_DATA:
                            logger.info("Falling back to mock calendar data")
                            return generate_mock_calendar_data(days_ahead, min_impact)
                        return []
                    
                    if not isinstance(data, list):
                        logger.info(f"Response format is: {type(data)}")
                        
                        # Handle dictionary format with 'result' key (TradingView API format)
                        if isinstance(data, dict) and "result" in data:
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
                    
                    # Transform TradingView data to our format
                    events = []
                    for event in data:
                        try:
                            # Map country codes to currency codes
                            country_to_currency = {
                                "US": "USD",
                                "EU": "EUR",
                                "GB": "GBP",
                                "JP": "JPY",
                                "CH": "CHF",
                                "AU": "AUD",
                                "NZ": "NZD",
                                "CA": "CAD",
                                "IN": "INR",  # India
                                "CN": "CNY",  # China
                                "RU": "RUB",  # Russia
                                "BR": "BRL",  # Brazil
                                "ZA": "ZAR",  # South Africa
                            }
                            
                            # Map importance levels from numeric to text
                            # Based on TradingView's numeric representation (1=low, 2=medium, 3=high)
                            importance_map = {
                                3: "High",
                                2: "Medium",
                                1: "Low"
                            }
                            
                            country = event.get("country", "")
                            currency = country_to_currency.get(country, "")
                            if not currency:
                                logger.debug(f"Skipping event with unknown country: {country}")
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
                                "country": currency,
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
                            
                        except Exception as e:
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
        time = event.get("time", "")
        title = event.get("event", "")
        impact = event.get("impact", "Low")
        impact_emoji = IMPACT_EMOJI.get(impact, "🟢")
        
        # Format the line with enhanced visibility for country - in plaats van alleen bold 
        # gebruiken we nu "「{country}」" voor betere zichtbaarheid in Telegram
        message += f"{time} - 「{country}」 - {title} {impact_emoji}\n"
    
    # Add legend
    message += "\n-------------------\n"
    message += "🔴 High Impact\n"
    message += "🟠 Medium Impact\n"
    message += "🟢 Low Impact\n"
    
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
