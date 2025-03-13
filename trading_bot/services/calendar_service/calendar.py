import os
import logging
import aiohttp
import asyncio
import pytz
import base64
from datetime import datetime
from typing import Dict, Any
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

class EconomicCalendarService:
    def __init__(self):
        """Initialize calendar service"""
        # Get API key from environment variable or use fallback
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "your-deepseek-api-key")
        self.api_url = "https://api.deepseek.com/v1/chat/completions"  # Update with correct endpoint
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Investing.com URL
        self.calendar_url = "https://www.investing.com/economic-calendar/"
        
        # Create screenshots directory if it doesn't exist
        os.makedirs("screenshots", exist_ok=True)

    async def get_economic_calendar(self, instrument: str = None) -> str:
        """Get economic calendar data"""
        try:
            # Take screenshot and extract data
            calendar_data = await self._screenshot_and_extract()
            
            if not calendar_data:
                return "No economic calendar data available at this time."
            
            # Filter by instrument if provided
            if instrument:
                filtered_data = self._filter_by_instrument(calendar_data, instrument)
            else:
                filtered_data = calendar_data
            
            # Format the data
            formatted_data = self._format_calendar_data(filtered_data)
            
            return formatted_data
            
        except Exception as e:
            logger.error(f"Error getting economic calendar: {str(e)}")
            return "Error retrieving economic calendar data."

    def _get_fallback_calendar(self) -> str:
        """Fallback calendar data"""
        return """🇺🇸 United States (USD):
⏰ 14:30 EST - No major events scheduled
⚪ Low Impact

🇪🇺 Eurozone (EUR):
⏰ 10:00 EST - No major events scheduled
⚪ Low Impact

🇬🇧 United Kingdom (GBP):
No confirmed events scheduled.

🇯🇵 Japan (JPY):
No confirmed events scheduled.

-------------------
🔴 High Impact
🟡 Medium Impact
⚪ Low Impact"""

    async def _screenshot_and_extract(self) -> str:
        """Take screenshot of Investing.com economic calendar and extract data"""
        try:
            # Get current date for filename
            current_date = datetime.now().strftime("%Y-%m-%d")
            screenshot_path = f"screenshots/economic_calendar_{current_date}.png"
            
            # Check if we already have a recent screenshot (less than 1 hour old)
            if os.path.exists(screenshot_path):
                file_time = os.path.getmtime(screenshot_path)
                current_time = datetime.now().timestamp()
                # If screenshot is less than 1 hour old, use it
                if current_time - file_time < 3600:  # 3600 seconds = 1 hour
                    logger.info(f"Using existing screenshot from {screenshot_path}")
                    with open(screenshot_path, "rb") as img_file:
                        screenshot_base64 = base64.b64encode(img_file.read()).decode('utf-8')
                    return await self._extract_data_from_image(screenshot_base64)
            
            # Take a new screenshot
            logger.info("Taking new screenshot of Investing.com economic calendar")
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                
                # Set viewport size to capture more content
                await page.set_viewport_size({"width": 1280, "height": 8000})
                
                # Navigate to the page
                await page.goto(self.calendar_url, wait_until="networkidle")
                
                # Wait for the calendar to load
                await page.wait_for_selector("#economicCalendarData", timeout=30000)
                
                # Accept cookies if the dialog appears
                try:
                    await page.click("button#onetrust-accept-btn-handler", timeout=5000)
                    logger.info("Accepted cookies")
                except:
                    logger.info("No cookie dialog found or already accepted")
                
                # Scroll to load all content
                await self._scroll_page(page)
                
                # Take screenshot
                await page.screenshot(path=screenshot_path, full_page=True)
                logger.info(f"Screenshot saved to {screenshot_path}")
                
                # Close browser
                await browser.close()
            
            # Read the screenshot and convert to base64
            with open(screenshot_path, "rb") as img_file:
                screenshot_base64 = base64.b64encode(img_file.read()).decode('utf-8')
            
            # Extract data from the image
            return await self._extract_data_from_image(screenshot_base64)
            
        except Exception as e:
            logger.error(f"Error taking screenshot: {str(e)}")
            return self._get_fallback_calendar()

    async def _scroll_page(self, page):
        """Scroll the page to load all content"""
        try:
            # Get scroll height
            scroll_height = await page.evaluate("document.body.scrollHeight")
            
            # Scroll down in increments
            for i in range(0, scroll_height, 500):
                await page.evaluate(f"window.scrollTo(0, {i})")
                await asyncio.sleep(0.1)  # Small delay to let content load
            
            # Scroll back to top
            await page.evaluate("window.scrollTo(0, 0)")
            
        except Exception as e:
            logger.error(f"Error scrolling page: {str(e)}")

    async def _extract_data_from_image(self, image_base64: str) -> str:
        """Extract economic calendar data from image using DeepSeek AI"""
        try:
            # Get current date in EST timezone
            est = pytz.timezone('US/Eastern')
            current_date = datetime.now(est).strftime("%Y-%m-%d")
            
            # Prepare the prompt for DeepSeek
            prompt = f"""This is a screenshot of the Investing.com Economic Calendar for {current_date}.

            Please extract ALL economic events visible in this image and format them as follows:

            1. Group events by currency in this exact order:
            - EUR (Eurozone)
            - USD (United States) 
            - GBP (United Kingdom)
            - JPY (Japan)
            - CHF (Switzerland)
            - AUD (Australia)
            - NZD (New Zealand)
            - Include other currencies if they have high impact events

            2. Format each event exactly like this:
            🇪🇺 Eurozone (EUR):
            ⏰ [EXACT TIME] EST - [EVENT NAME]
            [IMPACT EMOJI] [IMPACT LEVEL]
            Actual: [ACTUAL if available]
            Forecast: [FORECAST if available]
            Previous: [PREVIOUS if available]

            Use these impact levels:
            🔴 for High Impact (Interest Rate Decisions, NFP, GDP)
            🟡 for Medium Impact (Trade Balance, Retail)
            ⚪ for Low Impact (Minor indicators)

            For currencies with no events today, show:
            "No confirmed events scheduled for today."

            End with:
            -------------------
            🔴 High Impact
            🟡 Medium Impact
            ⚪ Low Impact"""

            # Prepare the payload for DeepSeek API
            payload = {
                "model": "deepseek-vision",  # Use vision model that can process images
                "messages": [
                    {
                        "role": "system",
                        "content": f"You are an economic calendar data extraction specialist. Extract all economic events from the provided screenshot of Investing.com's Economic Calendar for {current_date}."
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                "temperature": 0.1
            }

            # Make request to DeepSeek API
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        calendar_data = data['choices'][0]['message']['content']
                        
                        # Add timestamp to the data
                        current_time = datetime.now(est).strftime("%H:%M EST")
                        calendar_data = f"Last update: {current_time}\n\n{calendar_data}"
                        
                        return calendar_data
                    else:
                        error_text = await response.text()
                        logger.error(f"DeepSeek API error: {response.status}, {error_text}")
                        return self._get_fallback_calendar()

        except Exception as e:
            logger.error(f"Error extracting data from image: {str(e)}")
            return self._get_fallback_calendar()

    def _filter_by_instrument(self, calendar_data: str, instrument: str) -> str:
        """Filter calendar data by instrument"""
        try:
            # Extract currency from instrument
            if len(instrument) >= 3:
                currency = instrument[:3]  # First 3 chars, e.g., "EUR" from "EURUSD"
            else:
                return calendar_data  # Can't filter, return all
            
            # Split by currency sections
            sections = calendar_data.split('\n\n')
            filtered_sections = []
            
            for section in sections:
                # Check if this section is for our currency
                if currency in section or currency.upper() in section:
                    filtered_sections.append(section)
            
            # If no matching sections, return all data
            if not filtered_sections:
                return calendar_data
            
            # Join filtered sections with headers
            result = '\n\n'.join(filtered_sections)
            
            # Add the legend at the end
            if "-------------------" in calendar_data:
                legend = calendar_data.split("-------------------")[1]
                result += "\n\n-------------------" + legend
                
            return result
            
        except Exception as e:
            logger.error(f"Error filtering calendar data: {str(e)}")
            return calendar_data  # Return original on error

    def _format_calendar_data(self, calendar_data: str) -> str:
        """Format calendar data for display"""
        try:
            # Add header
            formatted = "📅 <b>Economic Calendar</b>\n\n"
            formatted += calendar_data
            
            return formatted
            
        except Exception as e:
            logger.error(f"Error formatting calendar data: {str(e)}")
            return calendar_data
