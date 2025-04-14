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
        return date.strftime("%Y-%m-%d")
        
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
            await self._ensure_session()
            
            # Calculate date range
            start_date = datetime.now()
            end_date = start_date + timedelta(days=days_ahead)
            
            # Prepare request parameters
            params = {
                "from": self._format_date(start_date),
                "to": self._format_date(end_date),
                "countries": ["US", "EU", "GB", "JP", "CH", "AU", "NZ", "CA"],  # Major currency countries
                "importance": ["high", "medium", "low"],
                "limit": 1000
            }
            
            # Make request to TradingView
            async with self.session.get(self.base_url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Error fetching calendar data: {response.status}")
                    return []
                    
                data = await response.json()
                
                # Transform TradingView data to our format
                events = []
                for event in data:
                    # Map country codes to currency codes
                    country_to_currency = {
                        "US": "USD",
                        "EU": "EUR",
                        "GB": "GBP",
                        "JP": "JPY",
                        "CH": "CHF",
                        "AU": "AUD",
                        "NZ": "NZD",
                        "CA": "CAD"
                    }
                    
                    # Map impact levels
                    impact_map = {
                        "high": "High",
                        "medium": "Medium",
                        "low": "Low"
                    }
                    
                    currency = country_to_currency.get(event.get("country", ""), "")
                    if not currency:
                        continue
                        
                    # Convert event time to local time
                    event_time = datetime.fromisoformat(event.get("date", "")).strftime("%H:%M")
                    
                    events.append({
                        "country": currency,  # Use currency code instead of country
                        "time": event_time,
                        "event": event.get("title", ""),
                        "impact": impact_map.get(event.get("importance", "low"), "Low")
                    })
                
                # Filter by minimum impact if specified
                if min_impact != "Low":
                    impact_levels = ["High", "Medium", "Low"]
                    min_impact_idx = impact_levels.index(min_impact)
                    events = [e for e in events if impact_levels.index(e["impact"]) <= min_impact_idx]
                
                return events
                
        except Exception as e:
            logger.error(f"Error fetching calendar data: {str(e)}")
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
