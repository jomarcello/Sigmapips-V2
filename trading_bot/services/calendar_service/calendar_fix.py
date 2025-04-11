"""
Calendar service fallback implementation
"""
import logging
import random
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

# Create a fallback class for the EconomicCalendarService
class EconomicCalendarService:
    """Fallback implementation of EconomicCalendarService"""
    def __init__(self, *args, **kwargs):
        self.logger = logging.getLogger(__name__)
        self.logger.warning("Fallback EconomicCalendarService is being used!")
        print("⚠️ FALLBACK CALENDAR SERVICE IS ACTIVE - Using mock calendar data ⚠️")
        
    async def get_calendar(self, days_ahead: int = 0, min_impact: str = "Low") -> List[Dict]:
        """Return mock calendar data"""
        self.logger.info(f"Fallback get_calendar called with days_ahead={days_ahead}, min_impact={min_impact}")
        print(f"⚠️ FALLBACK: Generating calendar data (days_ahead={days_ahead}, min_impact={min_impact}) ⚠️")
        
        mock_data = self._generate_mock_calendar_data(["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"], 
                                                     datetime.now().strftime("%Y-%m-%d"))
        self.logger.info(f"Generated {len(mock_data)} mock calendar events")
        
        # Filter by impact level
        impact_levels = {"High": 3, "Medium": 2, "Low": 1}
        min_level = impact_levels.get(min_impact, 1)
        
        filtered_data = [
            event for event in mock_data 
            if impact_levels.get(event.get("impact", "Low"), 1) >= min_level
        ]
        
        self.logger.info(f"Filtered to {len(filtered_data)} events based on minimum impact level: {min_impact}")
        return filtered_data
        
    async def get_events_for_instrument(self, instrument: str, *args, **kwargs) -> Dict[str, Any]:
        """Return mock events for an instrument"""
        self.logger.info(f"Fallback get_events_for_instrument called for {instrument}")
        
        # Map of instruments to their currencies
        currency_map = {
            "EURUSD": ["EUR", "USD"],
            "GBPUSD": ["GBP", "USD"],
            "USDJPY": ["USD", "JPY"],
            "USDCHF": ["USD", "CHF"],
            "AUDUSD": ["AUD", "USD"],
            "NZDUSD": ["NZD", "USD"],
            "USDCAD": ["USD", "CAD"],
            # Default to USD if instrument not found
            "default": ["USD"]
        }
        
        # Get relevant currencies for this instrument
        relevant_currencies = currency_map.get(instrument, currency_map["default"])
        
        # Generate mock data for all currencies
        all_mock_data = self._generate_mock_calendar_data(["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"], 
                                                        datetime.now().strftime("%Y-%m-%d"))
        
        # Filter for relevant currencies
        instrument_events = [
            event for event in all_mock_data
            if event.get("country") in relevant_currencies
        ]
        
        self.logger.info(f"Generated {len(instrument_events)} mock events for {instrument} ({', '.join(relevant_currencies)})")
        
        return {
            "events": instrument_events, 
            "explanation": f"Calendar events for {instrument} (mock data)"
        }
        
    async def get_instrument_calendar(self, instrument: str, *args, **kwargs) -> str:
        """Return formatted mock calendar for an instrument"""
        self.logger.info(f"Fallback get_instrument_calendar called for {instrument}")
        
        events_data = await self.get_events_for_instrument(instrument)
        events = events_data["events"]
        
        if not events:
            return "<b>📅 Economic Calendar</b>\n\nNo calendar events found for this instrument."
        
        # Format the events into a nice message
        formatted = "<b>📅 Economic Calendar</b>\n\n"
        
        # Impact emoji mapping
        impact_emoji = {
            "High": "🔴",
            "Medium": "🟠",
            "Low": "🟢"
        }
        
        # Sort events by time
        events.sort(key=lambda x: x.get("time", "00:00"))
        
        # Format each event
        for event in events:
            time = event.get("time", "")
            country_flag = event.get("country_flag", "")
            country = event.get("country", "")
            title = event.get("title", "")
            impact = event.get("impact", "Low")
            forecast = event.get("forecast", "")
            previous = event.get("previous", "")
            
            # Format forecast and previous if available
            forecast_text = f"F: {forecast}, " if forecast else ""
            previous_text = f"P: {previous}" if previous else ""
            data_text = f"({forecast_text}{previous_text})" if forecast_text or previous_text else ""
            
            # Add impact emoji
            impact_icon = impact_emoji.get(impact, "🟢")
            
            # Format the line with special characters for country visibility
            line = f"{time} - 「{country}」 - {title} {data_text} {impact_icon}\n"
            formatted += line
        
        # Add legend
        formatted += "\n-------------------\n"
        formatted += "🔴 High Impact\n"
        formatted += "🟠 Medium Impact\n"
        formatted += "🟢 Low Impact\n"
        formatted += "F: Forecast, P: Previous"
        
        return formatted
    
    def get_loading_gif(self) -> str:
        """Get the URL for the loading GIF"""
        return "https://media.giphy.com/media/dpjUltnOPye7azvAhH/giphy.gif" 
        
    def _generate_mock_calendar_data(self, currencies, date):
        """Generate a comprehensive set of mock calendar data for today
        
        This method provides realistic economic calendar data when the real service is not available.
        """
        self.logger.info(f"Generating mock calendar data for {date}")
        
        # Convert date string to datetime
        try:
            current_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            self.logger.warning(f"Invalid date format: {date}, using current date")
            current_date = datetime.now()
        
        # Basic currency to flag mapping
        currency_flags = {
            "USD": "🇺🇸",
            "EUR": "🇪🇺",
            "GBP": "🇬🇧",
            "JPY": "🇯🇵",
            "CHF": "🇨🇭",
            "AUD": "🇦🇺",
            "NZD": "🇳🇿",
            "CAD": "🇨🇦"
        }
        
        # Use current day of week/month to generate semi-deterministic events
        # This way we get different events on different days but consistent for a given day
        day_of_week = current_date.weekday()  # 0-6, 0 is Monday
        day_of_month = current_date.day       # 1-31
        
        # Set random seed for semi-deterministic generation
        random.seed(day_of_month + day_of_week * 31)
        
        # Template events for each currency - these will be randomized
        templates = {
            "USD": [
                {"title": "Initial Jobless Claims", "impact": "Medium", "time_range": ("08:30", "09:30")},
                {"title": "Fed Chair Speech", "impact": "High", "time_range": ("10:00", "15:00")},
                {"title": "CPI MoM", "impact": "High", "time_range": ("08:30", "09:30")},
                {"title": "CPI YoY", "impact": "High", "time_range": ("08:30", "09:30")},
                {"title": "Retail Sales MoM", "impact": "Medium", "time_range": ("08:30", "09:30")},
                {"title": "GDP Growth Rate QoQ", "impact": "High", "time_range": ("08:30", "09:30")},
                {"title": "Nonfarm Payrolls", "impact": "High", "time_range": ("08:30", "09:30")},
                {"title": "Unemployment Rate", "impact": "High", "time_range": ("08:30", "09:30")},
                {"title": "30-Year Bond Auction", "impact": "Low", "time_range": ("13:00", "17:00")},
                {"title": "Treasury Bill Auction", "impact": "Low", "time_range": ("11:30", "15:30")}
            ],
            "EUR": [
                {"title": "ECB Interest Rate Decision", "impact": "High", "time_range": ("07:45", "08:45")},
                {"title": "ECB Press Conference", "impact": "High", "time_range": ("08:30", "09:30")},
                {"title": "CPI YoY", "impact": "High", "time_range": ("07:00", "10:00")},
                {"title": "GDP Growth Rate QoQ", "impact": "High", "time_range": ("07:00", "10:00")},
                {"title": "Retail Sales MoM", "impact": "Medium", "time_range": ("07:00", "10:00")},
                {"title": "Manufacturing PMI", "impact": "Medium", "time_range": ("07:00", "10:00")},
                {"title": "Services PMI", "impact": "Medium", "time_range": ("07:00", "10:00")},
                {"title": "Unemployment Rate", "impact": "Medium", "time_range": ("07:00", "10:00")}
            ],
            "GBP": [
                {"title": "BoE Interest Rate Decision", "impact": "High", "time_range": ("07:00", "12:00")},
                {"title": "Manufacturing PMI", "impact": "Medium", "time_range": ("09:00", "11:00")},
                {"title": "GDP Growth Rate QoQ", "impact": "High", "time_range": ("07:00", "09:00")},
                {"title": "CPI YoY", "impact": "High", "time_range": ("07:00", "09:00")},
                {"title": "Halifax House Price Index MoM", "impact": "Low", "time_range": ("09:00", "10:00")},
                {"title": "Unemployment Rate", "impact": "Medium", "time_range": ("07:00", "09:00")}
            ],
            "JPY": [
                {"title": "Tokyo CPI", "impact": "Medium", "time_range": ("00:30", "01:30")},
                {"title": "GDP Growth Rate QoQ", "impact": "High", "time_range": ("00:30", "01:30")},
                {"title": "BoJ Interest Rate Decision", "impact": "High", "time_range": ("03:00", "06:00")},
                {"title": "Industrial Production MoM", "impact": "Medium", "time_range": ("00:30", "01:30")},
                {"title": "Tankan Large Manufacturers Index", "impact": "High", "time_range": ("00:30", "01:30")}
            ],
            "CHF": [
                {"title": "CPI MoM", "impact": "High", "time_range": ("03:30", "05:30")},
                {"title": "CPI YoY", "impact": "High", "time_range": ("03:30", "05:30")},
                {"title": "SNB Interest Rate Decision", "impact": "High", "time_range": ("03:30", "05:30")},
                {"title": "Retail Sales YoY", "impact": "Medium", "time_range": ("07:15", "09:15")},
                {"title": "Unemployment Rate", "impact": "Medium", "time_range": ("05:45", "07:45")}
            ],
            "AUD": [
                {"title": "Employment Change", "impact": "High", "time_range": ("21:30", "23:30")},
                {"title": "RBA Interest Rate Decision", "impact": "High", "time_range": ("03:30", "05:30")},
                {"title": "CPI QoQ", "impact": "High", "time_range": ("00:30", "02:30")},
                {"title": "Trade Balance", "impact": "Medium", "time_range": ("00:30", "02:30")},
                {"title": "Retail Sales MoM", "impact": "Medium", "time_range": ("00:30", "02:30")}
            ],
            "NZD": [
                {"title": "RBNZ Interest Rate Decision", "impact": "High", "time_range": ("02:00", "04:00")},
                {"title": "Trade Balance", "impact": "Medium", "time_range": ("22:45", "23:45")},
                {"title": "CPI QoQ", "impact": "High", "time_range": ("22:45", "23:45")},
                {"title": "Employment Change QoQ", "impact": "High", "time_range": ("22:45", "23:45")},
                {"title": "GDP Growth Rate QoQ", "impact": "High", "time_range": ("22:45", "23:45")}
            ],
            "CAD": [
                {"title": "Employment Change", "impact": "High", "time_range": ("13:30", "15:30")},
                {"title": "Unemployment Rate", "impact": "High", "time_range": ("13:30", "15:30")},
                {"title": "BoC Interest Rate Decision", "impact": "High", "time_range": ("14:00", "16:00")},
                {"title": "Trade Balance", "impact": "Medium", "time_range": ("13:30", "15:30")},
                {"title": "CPI MoM", "impact": "High", "time_range": ("13:30", "15:30")}
            ]
        }
        
        # Generate events based on day of week
        # Monday = few events, Friday = many events
        num_events_multi = {
            0: 0.8,   # Monday: fewer events
            1: 1.0,   # Tuesday: normal
            2: 1.2,   # Wednesday: more events
            3: 1.0,   # Thursday: normal
            4: 0.9,   # Friday: slightly fewer events
            5: 0.4,   # Saturday: very few events
            6: 0.4    # Sunday: very few events
        }
        
        # More random numbers for forecast/previous
        def random_pct():
            """Generate random percentage value"""
            return f"{(random.random() * 5 - 1):.1f}%"
            
        def random_number():
            """Generate random numeric value"""
            return f"{random.randint(1, 400)}.{random.randint(0, 9)}"
            
        def random_time(time_range):
            """Generate random time within range"""
            start_h, start_m = map(int, time_range[0].split(':'))
            end_h, end_m = map(int, time_range[1].split(':'))
            
            total_start_mins = start_h * 60 + start_m
            total_end_mins = end_h * 60 + end_m
            
            if total_end_mins <= total_start_mins:
                total_end_mins = total_start_mins + 60
                
            total_mins = random.randint(total_start_mins, total_end_mins)
            hours = total_mins // 60
            mins = total_mins % 60
            
            return f"{hours:02d}:{mins:02d}"
        
        # Mock data list
        mock_data = []
        
        # For each currency, generate some events
        for currency in currencies:
            if currency not in templates:
                continue
                
            # Determine how many events to generate based on day of week
            max_events = len(templates[currency])
            num_events = min(max(1, int(max_events * num_events_multi[day_of_week])), max_events)
            
            # Randomly select events
            selected_templates = random.sample(templates[currency], num_events)
            
            for template in selected_templates:
                # Randomize values
                is_pct = "%" in template["title"]
                has_forecast = random.random() > 0.3  # 70% chance of having forecast
                
                forecast = random_pct() if is_pct else random_number() if has_forecast else ""
                previous = random_pct() if is_pct else random_number()
                
                # Create event
                event = {
                    "time": random_time(template["time_range"]),
                    "country": currency,
                    "country_flag": currency_flags[currency],
                    "title": template["title"],
                    "impact": template["impact"],
                    "forecast": forecast,
                    "previous": previous
                }
                
                mock_data.append(event)
        
        # Sort by time
        mock_data.sort(key=lambda x: x["time"])
        
        return mock_data 
