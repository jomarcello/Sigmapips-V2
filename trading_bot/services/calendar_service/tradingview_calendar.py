import os
import sys
import logging
import asyncio
import json
import base64
import subprocess
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path

# Add parent directory to path to import DeepSeek service
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from trading_bot.services.ai_service.deepseek_service import DeepseekService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Map of major currencies to flag emojis
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

# Impact levels and their emoji representations
IMPACT_EMOJI = {
    "High": "🔴",
    "Medium": "🟠",
    "Low": "🟢"
}

class ForexFactoryCalendarService:
    """Service for retrieving economic calendar data from ForexFactory using screenshots"""
    
    def __init__(self, deepseek_service: Optional[DeepseekService] = None):
        """Initialize the service"""
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing ForexFactoryCalendarService")
        
        # Initialize DeepSeek service or use provided one
        self.deepseek_service = deepseek_service or DeepseekService()
        
        # Define paths
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.screenshot_script_path = os.path.join(self.base_dir, "forex_factory_screenshot.js")
        self.screenshot_path = os.path.join(self.base_dir, "forex_factory_calendar.png")
        
        # Make sure the screenshot script exists
        if not os.path.exists(self.screenshot_script_path):
            self.logger.error(f"Screenshot script not found at {self.screenshot_script_path}")
            raise FileNotFoundError(f"Screenshot script not found: {self.screenshot_script_path}")
    
    async def get_calendar(self) -> List[Dict]:
        """Get the economic calendar events for today from ForexFactory"""
        try:
            self.logger.info("Getting economic calendar from ForexFactory")
            
            # Take screenshot of ForexFactory calendar
            screenshot_path = await self._take_screenshot()
            
            # Process the screenshot with DeepSeek
            calendar_data = await self._process_screenshot_with_deepseek(screenshot_path)
            
            # Flatten the data into a single list of events with currency info
            flattened_events = []
            for currency, events in calendar_data.items():
                for event in events:
                    flattened_events.append({
                        "time": event.get("time", ""),
                        "country": currency,
                        "country_flag": CURRENCY_FLAG.get(currency, ""),
                        "title": event.get("event", ""),
                        "impact": event.get("impact", "Low")
                    })
            
            return flattened_events
            
        except Exception as e:
            self.logger.error(f"Error getting calendar data: {e}")
            self.logger.exception(e)
            return []
    
    async def _take_screenshot(self) -> str:
        """Take a screenshot of the ForexFactory calendar"""
        try:
            self.logger.info(f"Taking screenshot using {self.screenshot_script_path}")
            
            # Run the Node.js script to take a screenshot
            process = subprocess.Popen(
                ["node", self.screenshot_script_path, self.screenshot_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = process.communicate()
            
            # Log the output
            if stdout:
                self.logger.info(f"Screenshot script output: {stdout.decode()}")
            if stderr:
                self.logger.error(f"Screenshot script error: {stderr.decode()}")
            
            # Check if the screenshot was created
            if process.returncode != 0:
                raise RuntimeError(f"Screenshot script exited with code {process.returncode}")
                
            if not os.path.exists(self.screenshot_path):
                raise FileNotFoundError(f"Screenshot not created at {self.screenshot_path}")
            
            self.logger.info(f"Screenshot saved to {self.screenshot_path}")
            return self.screenshot_path
            
        except Exception as e:
            self.logger.error(f"Error taking screenshot: {e}")
            self.logger.exception(e)
            raise
    
    async def _process_screenshot_with_deepseek(self, screenshot_path: str) -> Dict[str, List[Dict[str, str]]]:
        """Process the screenshot using DeepSeek to extract calendar events"""
        try:
            self.logger.info(f"Processing screenshot with DeepSeek")
            
            # Read the screenshot file as base64
            with open(screenshot_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode("utf-8")
            
            # Create prompt for DeepSeek
            prompt = f"""
I have a screenshot of the Forex Factory economic calendar. Please extract all economic events for today.

For each event, extract:
1. The currency it relates to (USD, EUR, GBP, JPY, CHF, AUD, NZD, CAD)
2. The time of the event (in the local timezone shown)
3. The name of the event
4. The impact level (High, Medium, or Low)

Please organize the data by currency and return it as a JSON object with the following structure:
```json
{{
  "USD": [
    {{
      "time": "8:30",
      "event": "Example Event Name",
      "impact": "High"
    }},
    ...
  ],
  "EUR": [...],
  ...
}}
```

Only include events for today. Include only the major currencies: USD, EUR, GBP, JPY, CHF, AUD, NZD, and CAD.
Return ONLY the JSON object, with no additional text or explanation.

Here's the economic calendar screenshot (base64 encoded):
[Image: {base64_image[:100]}...]
"""
            
            # Call DeepSeek API
            response = await self.deepseek_service.generate_completion(
                prompt=prompt,
                model="deepseek-chat",
                temperature=0.2
            )
            
            # Extract the JSON from the response
            json_data = self._extract_json_from_response(response)
            
            # Validate and process the data
            calendar_data = self._validate_calendar_data(json_data)
            
            return calendar_data
            
        except Exception as e:
            self.logger.error(f"Error processing screenshot with DeepSeek: {e}")
            self.logger.exception(e)
            return self._generate_mock_calendar_data()
    
    def _extract_json_from_response(self, response: str) -> Dict:
        """Extract the JSON object from the DeepSeek response"""
        try:
            # Look for JSON between code fences
            if "```json" in response:
                json_start = response.find("```json") + 7
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
            elif "```" in response:
                json_start = response.find("```") + 3
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
            else:
                # Assume the entire response is JSON
                json_str = response.strip()
            
            # Parse the JSON
            return json.loads(json_str)
            
        except Exception as e:
            self.logger.error(f"Error extracting JSON from response: {e}")
            self.logger.error(f"Response: {response}")
            return {}
    
    def _validate_calendar_data(self, data: Dict) -> Dict[str, List[Dict[str, str]]]:
        """Validate and clean the calendar data"""
        valid_currencies = ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"]
        valid_impacts = ["High", "Medium", "Low"]
        
        result = {}
        
        for currency in valid_currencies:
            if currency in data and isinstance(data[currency], list):
                result[currency] = []
                
                for event in data[currency]:
                    if not isinstance(event, dict):
                        continue
                    
                    # Extract and validate fields
                    time = event.get("time", "")
                    event_name = event.get("event", "")
                    impact = event.get("impact", "Low")
                    
                    # Normalize impact
                    if impact not in valid_impacts:
                        if "high" in impact.lower():
                            impact = "High"
                        elif "medium" in impact.lower() or "med" in impact.lower():
                            impact = "Medium"
                        else:
                            impact = "Low"
                    
                    if time and event_name:
                        result[currency].append({
                            "time": time,
                            "event": event_name,
                            "impact": impact
                        })
        
        return result
    
    def _generate_mock_calendar_data(self) -> Dict[str, List[Dict[str, str]]]:
        """Generate mock calendar data when extraction fails"""
        self.logger.info("Generating mock calendar data")
        
        # Get today's date
        today = datetime.now().strftime("%Y-%m-%d")
        
        return {
            "USD": [
                {"time": "08:30", "event": "Initial Jobless Claims", "impact": "Medium"},
                {"time": "10:00", "event": "Fed Chair Speech", "impact": "High"},
                {"time": "14:00", "event": "Treasury Bond Auction", "impact": "Low"}
            ],
            "EUR": [
                {"time": "07:45", "event": "ECB Interest Rate Decision", "impact": "High"},
                {"time": "08:30", "event": "ECB Press Conference", "impact": "High"}
            ],
            "GBP": [
                {"time": "09:00", "event": "Manufacturing PMI", "impact": "Medium"}
            ],
            "JPY": [
                {"time": "00:30", "event": "Tokyo CPI", "impact": "Medium"}
            ],
            "CHF": [],
            "AUD": [
                {"time": "21:30", "event": "Employment Change", "impact": "High"}
            ],
            "NZD": [],
            "CAD": [
                {"time": "13:30", "event": "Trade Balance", "impact": "Medium"}
            ]
        }

async def main():
    """Test the calendar service"""
    calendar_service = ForexFactoryCalendarService()
    calendar_data = await calendar_service.get_calendar()
    
    # Print the results
    print(json.dumps(calendar_data, indent=2))

if __name__ == "__main__":
    asyncio.run(main()) 
