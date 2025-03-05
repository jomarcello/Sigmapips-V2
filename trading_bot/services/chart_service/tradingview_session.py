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
        
        # Standaard chart links
        self.default_chart_links = {
            # Commodities
            "XAUUSD": "https://www.tradingview.com/chart/bylCuCgc/",
            "WTIUSD": "https://www.tradingview.com/chart/jxU29rbq/",
            
            # Currencies
            "EURUSD": "https://www.tradingview.com/chart/xknpxpcr/",
            "EURGBP": "https://www.tradingview.com/chart/xt6LdUUi/",
            "EURCHF": "https://www.tradingview.com/chart/4Jr8hVba/",
            "EURJPY": "https://www.tradingview.com/chart/ume7H7lm/",
            "EURCAD": "https://www.tradingview.com/chart/gbtrKFPk/",
            "EURAUD": "https://www.tradingview.com/chart/WweOZl7z/",
            "EURNZD": "https://www.tradingview.com/chart/bcrCHPsz/",
            "GBPUSD": "https://www.tradingview.com/chart/jKph5b1W/",
            "GBPCHF": "https://www.tradingview.com/chart/1qMsl4FS/",
            "GBPJPY": "https://www.tradingview.com/chart/Zcmh5M2k/",
            "GBPCAD": "https://www.tradingview.com/chart/CvwpPBpF/",
            "GBPAUD": "https://www.tradingview.com/chart/neo3Fc3j/",
            "GBPNZD": "https://www.tradingview.com/chart/egeCqr65/",
            "CHFJPY": "https://www.tradingview.com/chart/g7qBPaqM/",
            "USDJPY": "https://www.tradingview.com/chart/mcWuRDQv/",
            "USDCHF": "https://www.tradingview.com/chart/e7xDgRyM/",
            "USDCAD": "https://www.tradingview.com/chart/jjTOeBNM/",
            "CADJPY": "https://www.tradingview.com/chart/KNsPbDME/",
            "CADCHF": "https://www.tradingview.com/chart/XnHRKk5I/",
            "AUDUSD": "https://www.tradingview.com/chart/h7CHetVW/",
            "AUDCHF": "https://www.tradingview.com/chart/oooBW6HP/",
            "AUDJPY": "https://www.tradingview.com/chart/sYiGgj7B/",
            "AUDNZD": "https://www.tradingview.com/chart/AByyHLB4/",
            "AUDCAD": "https://www.tradingview.com/chart/L4992qKp/",
            "NZDUSD": "https://www.tradingview.com/chart/yab05IFU/",
            "NZDCHF": "https://www.tradingview.com/chart/7epTugqA/",
            "NZDJPY": "https://www.tradingview.com/chart/fdtQ7rx7/",
            "NZDCAD": "https://www.tradingview.com/chart/mRVtXs19/",
            
            # Cryptocurrencies
            "BTCUSD": "https://www.tradingview.com/chart/Nroi4EqI/",
            "ETHUSD": "https://www.tradingview.com/chart/rVh10RLj/",
            "XRPUSD": "https://www.tradingview.com/chart/tQu9Ca4E/",
            "SOLUSD": "https://www.tradingview.com/chart/oTTmSjzQ/",
            "BNBUSD": "https://www.tradingview.com/chart/wNBWNh23/",
            "ADAUSD": "https://www.tradingview.com/chart/WcBNFrdb/",
            "LTCUSD": "https://www.tradingview.com/chart/AoDblBMt/",
            "DOGUSD": "https://www.tradingview.com/chart/F6SPb52v/",
            "DOTUSD": "https://www.tradingview.com/chart/nT9dwAx2/",
            "LNKUSD": "https://www.tradingview.com/chart/FzOrtgYw/",
            "XLMUSD": "https://www.tradingview.com/chart/SnvxOhDh/",
            "AVXUSD": "https://www.tradingview.com/chart/LfTlCrdQ/",
            
            # Indices
            "AU200": "https://www.tradingview.com/chart/U5CKagMM/",
            "EU50": "https://www.tradingview.com/chart/tt5QejVd/",
            "FR40": "https://www.tradingview.com/chart/RoPe3S1Q/",
            "HK50": "https://www.tradingview.com/chart/Rllftdyl/",
            "JP225": "https://www.tradingview.com/chart/i562Fk6X/",
            "UK100": "https://www.tradingview.com/chart/0I4gguQa/",
            "US100": "https://www.tradingview.com/chart/5d36Cany/",
            "US500": "https://www.tradingview.com/chart/VsfYHrwP/",
            "US30": "https://www.tradingview.com/chart/heV5Zitn/",
            "DE40": "https://www.tradingview.com/chart/OWzg0XNw/"
        }
        
        # Gebruik de meegegeven chart links of de standaard links
        self.chart_links = chart_links or self.default_chart_links
        
        # Converteer timeframe naar TradingView formaat
        self.interval_map = {
            "1m": "1",
            "5m": "5",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "2h": "120",
            "4h": "240",
            "1d": "D",
            "1w": "W",
            "1M": "M"
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
                headless=True,  # Altijd headless in productie
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
                logger.info(f"Using session ID for authentication: {self.session_id[:5]}...")
                
                # Voeg alle mogelijke cookies toe die nodig zijn voor authenticatie
                await self.context.add_cookies([
                    {
                        "name": "sessionid",
                        "value": self.session_id,
                        "domain": ".tradingview.com",
                        "path": "/"
                    },
                    {
                        "name": "device_t",
                        "value": "web",
                        "domain": ".tradingview.com",
                        "path": "/"
                    },
                    {
                        "name": "logged_in",
                        "value": "1",
                        "domain": ".tradingview.com",
                        "path": "/"
                    },
                    {
                        "name": "tv_ecuid",
                        "value": self.session_id[:16],  # Gebruik een deel van de session ID
                        "domain": ".tradingview.com",
                        "path": "/"
                    }
                ])
                
                try:
                    # Test of de sessie werkt met een langere timeout
                    page = await self.context.new_page()
                    await page.goto("https://www.tradingview.com/chart/", timeout=120000)  # 2 minuten timeout
                    await page.wait_for_load_state("networkidle", timeout=60000)  # 1 minuut timeout
                    
                    # Controleer of we zijn ingelogd
                    is_logged_in = await page.evaluate("""() => {
                        // Verschillende mogelijke selectors voor de gebruikersmenu-knop
                        const selectors = [
                            '.tv-header__user-menu-button',
                            '.js-username',
                            '.tv-header__user-menu',
                            '.tv-header__user',
                            '[data-name="user-menu"]'
                        ];
                        
                        // Controleer of een van de selectors bestaat
                        for (const selector of selectors) {
                            if (document.querySelector(selector)) {
                                return true;
                            }
                        }
                        
                        // Controleer of er een uitlog-link is
                        if (document.querySelector('a[href="/logout/"]')) {
                            return true;
                        }
                        
                        return false;
                    }""")
                    
                    # Neem een screenshot van de login pagina voor debugging
                    debug_screenshot = await page.screenshot()
                    logger.info(f"Login page screenshot size: {len(debug_screenshot)} bytes")
                    
                    if is_logged_in:
                        logger.info("Successfully authenticated with session ID")
                        self.is_logged_in = True
                    else:
                        logger.warning("Session ID authentication failed, but continuing anyway")
                        self.is_logged_in = False
                    
                    await page.close()
                except Exception as page_error:
                    logger.error(f"Error testing session: {str(page_error)}")
                    # Sluit de pagina als deze nog open is
                    try:
                        await page.close()
                    except:
                        pass
                    self.is_logged_in = False
            else:
                logger.warning("No session ID provided")
                self.is_logged_in = False
            
            self.is_initialized = True
            return True  # Altijd true retourneren, zelfs als login mislukt
            
        except Exception as e:
            logger.error(f"Error initializing TradingView Session service: {str(e)}")
            self.is_initialized = False
            self.is_logged_in = False
            return False
    
    async def login(self, page=None):
        """Login to TradingView (not used with session ID)"""
        logger.warning("Login with username/password is not implemented for session ID service")
        return False
    
    async def take_screenshot(self, symbol, timeframe=None):
        """Take a screenshot of a chart"""
        if not self.is_initialized:
            logger.warning("TradingView Session service not initialized")
            return None
        
        try:
            logger.info(f"Taking screenshot for {symbol}")
            
            # Maak een nieuwe pagina
            page = await self.context.new_page()
            
            try:
                # Bepaal de chart URL
                chart_url = None
                
                # Als het symbool een volledige URL is, gebruik deze direct
                if symbol.startswith("http"):
                    chart_url = symbol
                    logger.info(f"Using provided URL: {chart_url}")
                else:
                    # Anders zoek de URL op in de chart_links dictionary
                    # Normaliseer het symbool (verwijder / en converteer naar hoofdletters)
                    normalized_symbol = symbol.replace("/", "").upper()
                    
                    chart_url = self.chart_links.get(normalized_symbol)
                    if not chart_url:
                        logger.warning(f"No chart URL found for {symbol}, using default URL")
                        chart_url = f"https://www.tradingview.com/chart/?symbol={symbol}"
                
                # Gebruik de directe chart URL met de session ID
                logger.info(f"Navigating to chart URL with session ID: {chart_url}")
                
                # Ga direct naar de chart URL met de session ID
                await page.goto(chart_url, timeout=60000)
                
                # Wacht tot de pagina is geladen
                await page.wait_for_load_state("networkidle", timeout=30000)
                
                # Wacht nog wat extra tijd voor de chart om te laden
                await page.wait_for_timeout(15000)
                
                # Neem een screenshot
                logger.info("Taking screenshot")
                screenshot_bytes = await page.screenshot()
                
                return screenshot_bytes
            
            except Exception as e:
                logger.error(f"Error taking screenshot: {str(e)}")
                
                # Probeer een publieke chart als fallback
                try:
                    # Normaliseer het symbool
                    normalized_symbol = symbol.replace("/", "").upper()
                    
                    # Bouw een publieke chart URL
                    public_chart_url = f"https://www.tradingview.com/chart/?symbol={normalized_symbol}"
                    if timeframe:
                        tv_interval = self.interval_map.get(timeframe, "D")
                        public_chart_url += f"&interval={tv_interval}"
                    
                    logger.info(f"Using public chart URL as fallback: {public_chart_url}")
                    await page.goto(public_chart_url, timeout=60000)
                    await page.wait_for_load_state("networkidle", timeout=30000)
                    await page.wait_for_timeout(10000)
                    
                    # Neem een screenshot
                    logger.info("Taking screenshot of public chart")
                    screenshot_bytes = await page.screenshot()
                    
                    return screenshot_bytes
                except Exception as fallback_error:
                    logger.error(f"Error taking screenshot of public chart: {str(fallback_error)}")
                    return None
            
            finally:
                # Sluit de pagina
                try:
                    await page.close()
                except:
                    pass
        
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
