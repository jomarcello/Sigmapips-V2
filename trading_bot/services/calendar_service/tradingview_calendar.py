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
        """Check if the TradingView API endpoint is working"""
        try:
            await self._ensure_session()
            params = {
                'from': self._format_date(datetime.now()),
                'to': self._format_date(datetime.now() + timedelta(days=1)),
                'limit': 1
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
                "Accept": "application/json",
                "Origin": "https://www.tradingview.com",
                "Referer": "https://www.tradingview.com/economic-calendar/"
            }
            full_url = f"{self.base_url}"
            logger.info(f"Checking API health: {full_url}")
            async with self.session.get(full_url, params=params, headers=headers) as response:
                logger.info(f"Health check response status: {response.status}")
                return response.status == 200
        except Exception as e:
            logger.error(f"API health check failed: {str(e)}")
            return False
            
    def _map_importance(self, importance_value: int) -> str:
        """Map TradingView importance values to impact levels"""
        return IMPORTANCE_MAP.get(importance_value, "Low")  # Default to Low if unknown value

    async def get_calendar(self, days_ahead: int = 0, min_impact: str = "Low", currency: str = None) -> List[Dict[str, Any]]:
        """Fetch calendar events from TradingView"""
        try:
            logger.info(f"Starting calendar fetch from TradingView (days_ahead={days_ahead}, min_impact={min_impact}, currency={currency})")
            await self._ensure_session()
            
            # First check if the API is healthy
            is_healthy = await self._check_api_health()
            if not is_healthy:
                logger.error("TradingView API is not healthy, using fallback or returning empty list")
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
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
                "Accept": "application/json",
                "Origin": "https://www.tradingview.com",
                "Referer": "https://www.tradingview.com/economic-calendar/"
            }
            
            async with self.session.get(
                self.base_url, 
                params=params, 
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status != 200:
                    logger.error(f"Error response from TradingView: {response.status}")
                    if HAS_CUSTOM_MOCK_DATA:
                        return generate_mock_calendar_data(days_ahead, min_impact)
                    return []
                
                self.last_successful_call = datetime.now()
                response_text = await response.text()
                
                # Clean up response text (fix JSON issues)
                response_text = re.sub(r'";,', '",', response_text)
                response_text = re.sub(r'";(\s*[,}])', r'"\1', response_text)
                
                data = json.loads(response_text)
                if isinstance(data, dict):
                    data = data.get("result", []) if "result" in data else data.get("data", [])
                
                # Process events
                events = []
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
                        
                        # Create event object
                        event_obj = {
                            "country": currency_code,
                            "time": time_str,
                            "event": event.get("title", ""),
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
            events = await self.get_calendar(days_ahead=days_ahead, min_impact=min_impact)
            if currencies:
                events = [e for e in events if e["country"] in currencies]
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
    
    for event in sorted(events, key=lambda x: x["time"]):
        impact_emoji = IMPACT_EMOJI[event["impact"]]
        
        # Format event line
        event_line = f"{event['time']} - 「{event['country']}」 - {event['event']} {impact_emoji}"
        
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
