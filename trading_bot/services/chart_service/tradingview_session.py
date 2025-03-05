import os
import logging
import asyncio
from playwright.async_api import async_playwright
from io import BytesIO
from datetime import datetime
from trading_bot.services.chart_service.tradingview import TradingViewService

logger = logging.getLogger(__name__)

class TradingViewSessionService(TradingViewService):
    def __init__(self, session_id=None, chart_links=None):
        """Initialize the TradingView Session service"""
        super().__init__()
        self.session_id = session_id or os.getenv("TRADINGVIEW_SESSION_ID", "")
        self.username = os.getenv("TRADINGVIEW_USERNAME", "")
        self.password = os.getenv("TRADINGVIEW_PASSWORD", "")
        self.is_initialized = False
        self.is_logged_in = False
        self.browser = None
        self.context = None
        self.playwright = None
        
        # Gebruik de meegegeven chart links of de standaard links
        self.chart_links = chart_links or {
            "EURUSD": "https://www.tradingview.com/chart/?symbol=EURUSD",
            "GBPUSD": "https://www.tradingview.com/chart/?symbol=GBPUSD",
            "BTCUSD": "https://www.tradingview.com/chart/?symbol=BTCUSD",
            "ETHUSD": "https://www.tradingview.com/chart/?symbol=ETHUSD"
        }
        
        logger.info(f"TradingView Session service initialized with {len(self.chart_links)} chart links")
    
    async def initialize(self):
        """Initialize the Playwright browser"""
        try:
            logger.info("Initializing TradingView Session service")
            
            # Start Playwright
            self.playwright = await async_playwright().start()
            
            # Launch browser
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                ]
            )
            
            # Create a new browser context
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
            
            # Als er een session ID is, gebruik deze
            if self.session_id:
                logger.info("Using session ID for authentication")
                await self.context.add_cookies([
                    {
                        "name": "sessionid",
                        "value": self.session_id,
                        "domain": ".tradingview.com",
                        "path": "/"
                    }
                ])
                
                # Test of de sessie werkt
                page = await self.context.new_page()
                await page.goto("https://www.tradingview.com/", timeout=30000)
                
                # Controleer of we zijn ingelogd
                is_logged_in = await page.evaluate("""() => {
                    return document.querySelector('.tv-header__user-menu-button') !== null;
                }""")
                
                if is_logged_in:
                    logger.info("Successfully authenticated with session ID")
                    self.is_logged_in = True
                else:
                    logger.warning("Session ID authentication failed, falling back to login")
                    await self.login(page)
                
                await page.close()
            else:
                # Als er geen session ID is, log in met gebruikersnaam en wachtwoord
                logger.info("No session ID provided, using username/password")
                page = await self.context.new_page()
                await self.login(page)
                await page.close()
            
            self.is_initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Error initializing TradingView Session service: {str(e)}")
            await self.cleanup()
            return False
    
    async def login(self, page):
        """Login to TradingView"""
        try:
            logger.info("Logging in to TradingView")
            
            # Navigeer naar de login pagina
            await page.goto("https://www.tradingview.com/#signin", timeout=30000)
            
            # Klik op de email login optie
            await page.click('span.js-show-email')
            
            # Vul inloggegevens in
            await page.fill('[name="username"]', self.username)
            await page.fill('[name="password"]', self.password)
            
            # Klik op de login knop
            await page.click('[type="submit"]')
            
            # Wacht tot we zijn ingelogd
            try:
                await page.wait_for_navigation(timeout=30000)
                logger.info("Successfully logged in")
                self.is_logged_in = True
                
                # Haal de nieuwe session ID op
                cookies = await self.context.cookies()
                for cookie in cookies:
                    if cookie["name"] == "sessionid":
                        self.session_id = cookie["value"]
                        logger.info(f"New session ID: {self.session_id[:10]}...")
                        break
                
                return True
            except Exception as e:
                logger.error(f"Error during login: {str(e)}")
                
                # Controleer op CAPTCHA
                if await page.query_selector('iframe[src*="recaptcha"]'):
                    logger.warning("CAPTCHA detected, manual intervention required")
                    # Wacht op handmatige interventie
                    await page.wait_for_timeout(30000)
                    
                    # Controleer of we nu zijn ingelogd
                    is_logged_in = await page.evaluate("""() => {
                        return document.querySelector('.tv-header__user-menu-button') !== null;
                    }""")
                    
                    if is_logged_in:
                        logger.info("Successfully logged in after CAPTCHA")
                        self.is_logged_in = True
                        
                        # Haal de nieuwe session ID op
                        cookies = await self.context.cookies()
                        for cookie in cookies:
                            if cookie["name"] == "sessionid":
                                self.session_id = cookie["value"]
                                logger.info(f"New session ID: {self.session_id[:10]}...")
                                break
                        
                        return True
                
                return False
                
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            return False
    
    async def take_screenshot(self, symbol, timeframe):
        """Take a screenshot of a chart"""
        if not self.is_initialized or not self.is_logged_in:
            logger.warning("TradingView Session service not initialized or not logged in")
            return None
        
        try:
            logger.info(f"Taking screenshot for {symbol} on {timeframe} timeframe")
            
            # Maak een nieuwe pagina
            page = await self.context.new_page()
            
            # Navigeer naar de chart pagina
            chart_url = self.chart_links.get(symbol)
            if not chart_url:
                logger.warning(f"No chart URL found for {symbol}, using default URL")
                chart_url = f"https://www.tradingview.com/chart/?symbol={symbol}"
            
            logger.info(f"Navigating to chart URL: {chart_url}")
            await page.goto(chart_url, timeout=30000)
            
            # Wacht tot de chart is geladen
            await page.wait_for_selector('.chart-markup-table', timeout=30000)
            
            # Verander de timeframe indien nodig
            if timeframe != '1d':  # Standaard is 1d
                logger.info(f"Changing timeframe to {timeframe}")
                
                # Klik op de timeframe selector
                await page.click('.chart-toolbar-timeframes button')
                
                # Wacht op het dropdown menu
                await page.wait_for_selector('.menu-T1RzLuj3 .item-RhC5uhZw', timeout=10000)
                
                # Zoek en klik op de juiste timeframe
                timeframe_items = await page.query_selector_all('.menu-T1RzLuj3 .item-RhC5uhZw')
                timeframe_found = False
                
                for item in timeframe_items:
                    text = await item.text_content()
                    if timeframe.upper() in text:
                        await item.click()
                        timeframe_found = True
                        break
                
                if not timeframe_found:
                    logger.warning(f"Timeframe {timeframe} not found, using default")
                
                # Wacht tot de chart is bijgewerkt
                await page.wait_for_timeout(3000)
            
            # Verberg UI elementen voor een schonere screenshot
            await page.evaluate("""() => {
                // Verberg header, footer, sidebar, etc.
                const elementsToHide = [
                    '.header-KN-Kpxs-',
                    '.drawingToolbar-2_so5tMw',
                    '.chart-controls-bar',
                    '.bottom-widgetbar-content.backtesting',
                    '.control-bar',
                    '.tv-side-toolbar'
                ];
                
                elementsToHide.forEach(selector => {
                    const elements = document.querySelectorAll(selector);
                    elements.forEach(el => {
                        if (el) el.style.display = 'none';
                    });
                });
            }""")
            
            # Wacht even om zeker te zijn dat alles is bijgewerkt
            await page.wait_for_timeout(1000)
            
            # Neem de screenshot
            screenshot = await page.screenshot()
            
            # Sluit de pagina
            await page.close()
            
            logger.info(f"Successfully took screenshot of {symbol} {timeframe}")
            return screenshot
            
        except Exception as e:
            logger.error(f"Error taking screenshot: {str(e)}")
            return None
    
    async def batch_capture_charts(self, symbols=None, timeframes=None):
        """Capture multiple charts"""
        if not self.is_initialized or not self.is_logged_in:
            logger.warning("TradingView Session service not initialized or not logged in")
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
                        # Take screenshot
                        screenshot = await self.take_screenshot(symbol, timeframe)
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
                self.browser = None
            
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            
            self.is_initialized = False
            self.is_logged_in = False
            
            logger.info("TradingView Session service cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up TradingView Session service: {str(e)}") 
