import os
import logging
import asyncio
import base64
from io import BytesIO
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
import aiofiles
import json
import time
import random
import aiohttp

logger = logging.getLogger(__name__)

class ChartService:
    def __init__(self):
        """Initialize chart service"""
        self.browser = None
        self.context = None
        self.page = None
        self.is_initialized = False
        self.is_logged_in = False
        self.cookies_path = os.path.join(os.path.dirname(__file__), "tradingview_cookies.json")
        self.username = os.getenv("TRADINGVIEW_USERNAME")
        self.password = os.getenv("TRADINGVIEW_PASSWORD")
        
        # Configuratie voor charts
        self.base_url = "https://www.tradingview.com/chart/"
        self.timeframe_map = {
            "1m": "1",
            "5m": "5",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "4h": "240",
            "1d": "D",
            "1w": "W"
        }
        
    async def initialize(self):
        """Initialize browser and context"""
        if self.is_initialized:
            return
            
        try:
            logger.info("Initializing Playwright browser")
            self.playwright = await async_playwright().start()
            
            # Gebruik een echte browser (chromium) met stealth modus
            self.browser = await self.playwright.chromium.launch(
                headless=True,  # True voor productie, False voor debugging
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-site-isolation-trials"
                ]
            )
            
            # Maak een context met menselijke eigenschappen
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                locale="en-US",
                timezone_id="Europe/Amsterdam",
                has_touch=False,
                is_mobile=False,
                color_scheme="light"
            )
            
            # Voeg stealth scripts toe
            await self.context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false,
                });
                
                // Overwrite the 'plugins' property to use a custom getter
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
                
                // Overwrite the 'languages' property to use a custom getter
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                });
            """)
            
            # Laad cookies als ze bestaan
            await self.load_cookies()
            
            # Open een nieuwe pagina
            self.page = await self.context.new_page()
            
            # Voeg extra headers toe
            await self.page.set_extra_http_headers({
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
            })
            
            # Controleer of we ingelogd zijn
            await self.check_login_status()
            
            self.is_initialized = True
            logger.info("Playwright browser initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing browser: {str(e)}")
            await self.cleanup()
            raise
    
    async def load_cookies(self):
        """Load cookies from file"""
        try:
            if os.path.exists(self.cookies_path):
                async with aiofiles.open(self.cookies_path, "r") as f:
                    cookies = json.loads(await f.read())
                await self.context.add_cookies(cookies)
                logger.info("Cookies loaded successfully")
                return True
            else:
                logger.info("No cookies file found")
                return False
        except Exception as e:
            logger.error(f"Error loading cookies: {str(e)}")
            return False
    
    async def save_cookies(self):
        """Save cookies to file"""
        try:
            cookies = await self.context.cookies()
            async with aiofiles.open(self.cookies_path, "w") as f:
                await f.write(json.dumps(cookies))
            logger.info("Cookies saved successfully")
            return True
        except Exception as e:
            logger.error(f"Error saving cookies: {str(e)}")
            return False
    
    async def check_login_status(self):
        """Check if we're logged in to TradingView"""
        try:
            await self.page.goto("https://www.tradingview.com/chart/", timeout=60000)
            
            # Wacht even om de pagina te laden
            await asyncio.sleep(3)
            
            # Controleer of we ingelogd zijn door te zoeken naar elementen die alleen zichtbaar zijn als je ingelogd bent
            user_menu = await self.page.query_selector('button[data-name="user-menu"]')
            
            if user_menu:
                logger.info("Already logged in to TradingView")
                self.is_logged_in = True
                return True
            else:
                logger.info("Not logged in to TradingView")
                self.is_logged_in = False
                
                # Probeer in te loggen als we credentials hebben
                if self.username and self.password:
                    return await self.login()
                return False
                
        except Exception as e:
            logger.error(f"Error checking login status: {str(e)}")
            self.is_logged_in = False
            return False
    
    async def login(self):
        """Login to TradingView"""
        try:
            if self.is_logged_in:
                return True
                
            logger.info("Logging in to TradingView")
            
            # Ga naar de login pagina
            await self.page.goto("https://www.tradingview.com/signin/", timeout=60000)
            
            # Wacht op de email input en vul deze in
            await self.page.wait_for_selector('input[name="username"]', timeout=10000)
            
            # Voeg menselijke vertraging toe
            await self.human_type(self.page, 'input[name="username"]', self.username)
            
            # Klik op de "Email" tab als die er is
            email_tab = await self.page.query_selector('button:has-text("Email")')
            if email_tab:
                await email_tab.click()
                await asyncio.sleep(1)
            
            # Vul het wachtwoord in
            await self.human_type(self.page, 'input[name="password"]', self.password)
            
            # Klik op de inlogknop
            await self.page.click('button[type="submit"]')
            
            # Wacht tot we ingelogd zijn (max 20 seconden)
            try:
                await self.page.wait_for_selector('button[data-name="user-menu"]', timeout=20000)
                logger.info("Successfully logged in to TradingView")
                self.is_logged_in = True
                
                # Sla cookies op
                await self.save_cookies()
                
                return True
            except Exception as timeout_error:
                logger.error(f"Login timeout: {str(timeout_error)}")
                
                # Controleer op captcha
                captcha = await self.page.query_selector('div[class*="captcha"]')
                if captcha:
                    logger.error("CAPTCHA detected during login")
                
                # Controleer op foutmeldingen
                error = await self.page.query_selector('div[class*="error"]')
                if error:
                    error_text = await error.text_content()
                    logger.error(f"Login error: {error_text}")
                
                self.is_logged_in = False
                return False
                
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            self.is_logged_in = False
            return False
    
    async def human_type(self, page: Page, selector: str, text: str):
        """Type like a human with random delays between keystrokes"""
        await page.click(selector)
        await asyncio.sleep(random.uniform(0.1, 0.3))
        
        for char in text:
            await page.type(selector, char, delay=random.uniform(50, 150))
            await asyncio.sleep(random.uniform(0.01, 0.05))
        
        await asyncio.sleep(random.uniform(0.2, 0.5))
    
    async def get_chart(self, instrument: str, timeframe: str = "1h") -> Optional[bytes]:
        """Get chart image for instrument and timeframe"""
        try:
            if not self.is_initialized:
                await self.initialize()
                
            if not self.is_logged_in:
                success = await self.check_login_status()
                if not success:
                    logger.error("Failed to login, cannot get chart")
                    return None
            
            # Normaliseer instrument en timeframe
            instrument = instrument.upper()
            tf = self.timeframe_map.get(timeframe, "60")  # Default to 1h
            
            # Bepaal het juiste symbool formaat
            if "USD" in instrument and len(instrument) == 6:
                # Forex pair
                symbol = f"FX:{instrument}"
            elif instrument in ["XAUUSD", "XAGUSD"]:
                # Gold/Silver
                metal_map = {"XAUUSD": "GOLD", "XAGUSD": "SILVER"}
                symbol = f"TVC:{metal_map.get(instrument, instrument)}"
            elif instrument in ["USOIL", "UKOIL"]:
                # Oil
                symbol = f"TVC:{instrument}"
            elif any(index in instrument for index in ["30", "500", "100"]):
                # US indices
                indices_map = {"US30": "DJ30", "US500": "SPX500", "US100": "NASDAQ100"}
                symbol = f"TVC:{indices_map.get(instrument, instrument)}"
            elif any(crypto in instrument for crypto in ["BTC", "ETH", "XRP"]):
                # Crypto
                base = instrument[:3]
                quote = instrument[3:] if len(instrument) > 3 else "USD"
                symbol = f"BINANCE:{base}{quote}"
            else:
                # Default
                symbol = f"FX:{instrument}"
            
            # Navigeer naar de chart pagina met het juiste symbool en timeframe
            chart_url = f"https://www.tradingview.com/chart/?symbol={symbol}&interval={tf}"
            logger.info(f"Navigating to chart URL: {chart_url}")
            
            await self.page.goto(chart_url, timeout=60000)
            
            # Wacht tot de chart geladen is
            await self.page.wait_for_selector('.chart-markup-table', timeout=30000)
            
            # Geef de chart tijd om volledig te renderen
            await asyncio.sleep(5)
            
            # Verwijder UI elementen die we niet willen in de screenshot
            await self.page.evaluate("""
                () => {
                    // Verberg header, footer, sidebar, etc.
                    const elementsToHide = [
                        '.header-chart-panel',
                        '.footer-chart-panel',
                        '.left-toolbar',
                        '.right-toolbar',
                        '.chart-controls-bar',
                        '.drawing-toolbar',
                        '.tv-side-toolbar'
                    ];
                    
                    elementsToHide.forEach(selector => {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            if (el) el.style.display = 'none';
                        });
                    });
                }
            """)
            
            # Wacht even om de UI aanpassingen te laten verwerken
            await asyncio.sleep(1)
            
            # Neem een screenshot van alleen de chart
            chart_element = await self.page.query_selector('.chart-markup-table')
            if not chart_element:
                logger.error("Chart element not found")
                return None
                
            screenshot = await chart_element.screenshot()
            
            return screenshot
            
        except Exception as e:
            logger.error(f"Error getting chart: {str(e)}")
            return None
    
    async def get_fallback_chart(self, instrument: str) -> Optional[bytes]:
        """Get a fallback chart when TradingView is not available"""
        try:
            # Use a public API for a basic chart
            url = f"https://api.chart-img.com/v1/tradingview/advanced-chart?symbol={instrument}&interval=1h&studies=RSI&key=demo"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.error(f"Fallback chart API error: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error getting fallback chart: {str(e)}")
            return None
    
    async def cleanup(self):
        """Clean up resources"""
        try:
            if self.page:
                await self.page.close()
                self.page = None
                
            if self.context:
                await self.context.close()
                self.context = None
                
            if self.browser:
                await self.browser.close()
                self.browser = None
                
            if hasattr(self, 'playwright') and self.playwright:
                await self.playwright.stop()
                
            self.is_initialized = False
            self.is_logged_in = False
            
            logger.info("Browser resources cleaned up")
            
        except Exception as e:
            logger.error(f"Error cleaning up browser resources: {str(e)}")
