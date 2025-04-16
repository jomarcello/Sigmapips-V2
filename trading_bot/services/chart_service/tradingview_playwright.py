import os
import time
import logging
import asyncio
import base64
from io import BytesIO
from datetime import datetime
from PIL import Image
from playwright.async_api import async_playwright
from trading_bot.services.chart_service.tradingview import TradingViewService

logger = logging.getLogger(__name__)

class TradingViewPlaywrightService(TradingViewService):
    def __init__(self, session_id=None):
        """Initialize the TradingView Playwright service"""
        super().__init__()
        self.session_id = session_id or os.getenv("TRADINGVIEW_SESSION_ID", "")
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.is_initialized = False
        self.is_logged_in = False
        self.base_url = "https://www.tradingview.com"
        self.chart_url = "https://www.tradingview.com/chart"
        
        # Chart links voor verschillende symbolen
        self.chart_links = {
            "EURUSD": "https://www.tradingview.com/chart/?symbol=EURUSD",
            "GBPUSD": "https://www.tradingview.com/chart/?symbol=GBPUSD",
            "BTCUSD": "https://www.tradingview.com/chart/?symbol=BTCUSD",
            "ETHUSD": "https://www.tradingview.com/chart/?symbol=ETHUSD"
        }
        
        logger.info(f"TradingView Playwright service initialized with session ID: {self.session_id[:5] if self.session_id else 'None'}...")
    
    async def initialize(self):
        """Initialize the Playwright browser"""
        try:
            logger.info("Initializing TradingView Playwright service")
            
            # Log system info
            import platform
            logger.info(f"System: {platform.system()} {platform.release()}")
            logger.info(f"Python: {platform.python_version()}")
            
            # Start Playwright with detailed logging
            logger.info("Starting Playwright")
            self.playwright = await async_playwright().start()
            logger.info("Playwright started successfully")
            
            # Launch browser with detailed logging
            logger.info("Launching browser with args")
            browser_args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080"
            ]
            logger.info(f"Browser args: {browser_args}")
            
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=browser_args
            )
            logger.info("Browser launched successfully")
            
            # Create a new context
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )
            
            # Create a new page
            self.page = await self.context.new_page()
            
            # Go to TradingView
            await self.page.goto(self.base_url)
            
            # Add session cookie if available
            if self.session_id:
                await self.context.add_cookies([{
                    'name': 'sessionid',
                    'value': self.session_id,
                    'domain': '.tradingview.com',
                    'path': '/'
                }])
                
                # Refresh the page
                await self.page.reload()
                
                # Wait for page to load
                await self.page.wait_for_load_state("networkidle")
                
                # Check if logged in
                if await self._is_logged_in():
                    logger.info("Successfully logged in to TradingView using session ID")
                    self.is_initialized = True
                    self.is_logged_in = True
                    return True
                else:
                    logger.warning("Failed to log in with session ID")
                    # Continue with initialization even if not logged in
            
            # Initialize without login
            self.is_initialized = True
            return True
                
        except Exception as e:
            logger.error(f"Error initializing TradingView Playwright service: {str(e)}")
            return False
    
    async def _is_logged_in(self):
        """Check if we are logged in to TradingView"""
        try:
            # Check if user menu button is present
            user_menu = await self.page.query_selector(".tv-header__user-menu-button")
            return user_menu is not None
        except Exception as e:
            logger.error(f"Error checking login status: {str(e)}")
            return False
    
    async def login(self):
        """Login to TradingView using session ID"""
        try:
            if not self.is_initialized:
                logger.warning("Playwright not initialized, cannot login")
                return False
                
            # Go to TradingView
            await self.page.goto(self.base_url)
            
            # Add session cookie
            if self.session_id:
                await self.context.add_cookies([{
                    'name': 'sessionid',
                    'value': self.session_id,
                    'domain': '.tradingview.com',
                    'path': '/'
                }])
                
                # Refresh the page
                await self.page.reload()
                
                # Wait for page to load
                await self.page.wait_for_load_state("networkidle")
                
                # Check if logged in
                if await self._is_logged_in():
                    logger.info("Successfully logged in to TradingView using session ID")
                    self.is_logged_in = True
                    return True
                else:
                    logger.warning("Failed to log in with session ID")
                    return False
            else:
                logger.warning("No session ID provided")
                return False
                
        except Exception as e:
            logger.error(f"Error logging in to TradingView: {str(e)}")
            return False
    
    async def get_chart_screenshot(self, chart_url):
        """Get a screenshot of a chart"""
        return await self.take_screenshot(chart_url)
    
    async def take_screenshot(self, chart_url, timeframe=None, adjustment=100):
        """Take a screenshot of a chart"""
        if not self.is_initialized:
            logger.warning("TradingView Playwright service not initialized")
            return None
        
        try:
            # If chart_url is a symbol instead of a URL, convert it
            if not chart_url.startswith("http"):
                symbol = chart_url
                chart_url = self.chart_links.get(symbol, f"{self.chart_url}/?symbol={symbol}")
            
            logger.info(f"Taking screenshot of chart at URL: {chart_url}")
            
            # Navigate to the chart
            await self.page.goto(chart_url)
            
            # Wait for chart to load
            try:
                await self.page.wait_for_selector(".chart-container", timeout=30000)
            except Exception as wait_error:
                logger.warning(f"Timeout waiting for chart container: {str(wait_error)}")
                # Continue, maybe the chart is loaded anyway
            
            # Wait extra time for full rendering
            await asyncio.sleep(10)
            
            # Set timeframe if specified
            if timeframe:
                await self._set_timeframe(timeframe)
            
            # Adjust position (scroll right)
            try:
                # Press Escape to close any dialogs
                await self.page.keyboard.press("Escape")
                
                # Press right arrow multiple times
                for _ in range(adjustment):
                    await self.page.keyboard.press("ArrowRight")
                    await asyncio.sleep(0.01)
                
                await asyncio.sleep(3)
            except Exception as action_error:
                logger.warning(f"Error performing keyboard actions: {str(action_error)}")
            
            # Hide UI elements for a clean screenshot
            await self._hide_ui_elements()
            
            # Take screenshot
            screenshot = await self.page.screenshot(full_page=False)
            
            logger.info(f"Successfully took screenshot of chart")
            return screenshot
            
        except Exception as e:
            logger.error(f"Error taking screenshot: {str(e)}")
            return None
    
    async def _set_timeframe(self, timeframe):
        """Set the chart timeframe"""
        try:
            # Click the timeframe button
            timeframe_button = await self.page.query_selector(".chart-toolbar-timeframes button")
            if timeframe_button:
                await timeframe_button.click()
                
                # Wait for dropdown menu
                await asyncio.sleep(1)
                
                # Find and click the correct timeframe option
                timeframe_options = await self.page.query_selector_all(".menu-item")
                for option in timeframe_options:
                    option_text = await option.text_content()
                    if timeframe.lower() in option_text.lower():
                        await option.click()
                        break
                
                # Wait for chart to update
                await asyncio.sleep(3)
            
        except Exception as e:
            logger.error(f"Error setting timeframe: {str(e)}")
    
    async def _hide_ui_elements(self):
        """Hide UI elements for a clean screenshot"""
        try:
            # JavaScript to hide UI elements
            js_hide_elements = """
                const elementsToHide = [
                    '.chart-toolbar',
                    '.tv-side-toolbar',
                    '.header-chart-panel',
                    '.drawing-toolbar',
                    '.chart-controls-bar',
                    '.layout__area--left',
                    '.layout__area--top',
                    '.layout__area--right'
                ];
                
                elementsToHide.forEach(selector => {
                    const elements = document.querySelectorAll(selector);
                    elements.forEach(el => {
                        if (el) el.style.display = 'none';
                    });
                });
            """
            
            await self.page.evaluate(js_hide_elements)
            await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"Error hiding UI elements: {str(e)}")
    
    async def batch_capture_charts(self, symbols=None, timeframes=None):
        """Capture multiple charts"""
        if not self.is_initialized:
            logger.warning("TradingView Playwright service not initialized")
            return None
        
        if not symbols:
            symbols = ["EURUSD", "GBPUSD", "BTCUSD", "ETHUSD"]
        
        if not timeframes:
            timeframes = ["1h", "4h", "1d"]
        
        results = {}
        
        try:
            for symbol in symbols:
                results[symbol] = {}
                
                for timeframe in timeframes:
                    try:
                        # Determine chart URL
                        chart_url = self.chart_links.get(symbol, f"{self.chart_url}/?symbol={symbol}")
                        
                        # Take screenshot
                        screenshot = await self.take_screenshot(chart_url, timeframe)
                        results[symbol][timeframe] = screenshot
                    except Exception as e:
                        logger.error(f"Error capturing {symbol} at {timeframe}: {str(e)}")
                        results[symbol][timeframe] = None
            
            return results
            
        except Exception as e:
            logger.error(f"Error in batch capture: {str(e)}")
            return None
    
    async def cleanup(self):
        """Clean up resources"""
        try:
            if self.browser:
                await self.browser.close()
            
            if self.playwright:
                await self.playwright.stop()
                
            logger.info("TradingView Playwright service cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up TradingView Playwright service: {str(e)}") 
