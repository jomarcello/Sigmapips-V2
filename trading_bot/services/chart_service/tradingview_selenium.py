import os
import time
import logging
import asyncio
from typing import Dict, Optional, List, Any
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

# Probeer eerst de nieuwe import methode (voor nieuwere versies)
try:
    from webdriver_manager.chrome import ChromeDriverManager
    # In nieuwere versies is ChromeType verplaatst of niet meer nodig
    CHROME_TYPE_IMPORT = False
except ImportError:
    from webdriver_manager.chrome import ChromeDriverManager
    try:
        # Voor oudere versies
        from webdriver_manager.core.utils import ChromeType
        CHROME_TYPE_IMPORT = True
    except ImportError:
        # Als ChromeType niet beschikbaar is, gebruik dan een fallback
        CHROME_TYPE_IMPORT = False

# Importeer de base class
from trading_bot.services.chart_service.base import TradingViewService

logger = logging.getLogger(__name__)

class TradingViewSeleniumService(TradingViewService):
    """TradingView service using Selenium"""
    
    def __init__(self, chart_links=None, session_id=None):
        """Initialize the service"""
        super().__init__(chart_links)
        self.session_id = session_id
        self.driver = None
        self.is_initialized = False
        self.is_logged_in = False
        
        # Interval mapping
        self.interval_map = {
            "1m": "1",
            "5m": "5",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "4h": "240",
            "1d": "D",
            "1w": "W",
            "1M": "M"
        }
        
        # Chart links voor verschillende symbolen
        self.chart_links = chart_links or {
            "EURUSD": "https://www.tradingview.com/chart/?symbol=EURUSD",
            "GBPUSD": "https://www.tradingview.com/chart/?symbol=GBPUSD",
            "BTCUSD": "https://www.tradingview.com/chart/?symbol=BTCUSD",
            "ETHUSD": "https://www.tradingview.com/chart/?symbol=ETHUSD"
        }
        
        # Controleer of we in een Docker container draaien
        self.in_docker = os.path.exists("/.dockerenv")
        
        logger.info(f"TradingView Selenium service initialized (in Docker: {self.in_docker})")
    
    async def initialize(self):
        """Initialize the Selenium driver"""
        try:
            logger.info("Initializing TradingView Selenium service")
            
            # Gebruik webdriver-manager om automatisch de juiste ChromeDriver te downloaden
            service = Service(ChromeDriverManager().install())
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info("Chrome driver created successfully with webdriver-manager")
            
            try:
                self.driver.set_window_size(1920, 1080)
                logger.info("Window size set successfully")
            except Exception as window_error:
                logger.error(f"Error setting window size: {str(window_error)}")
                # Dit is niet kritiek, dus we gaan door
            
            # Test of de driver werkt door naar een eenvoudige URL te navigeren
            try:
                logger.info("Testing driver with a simple URL")
                self.driver.get("https://www.google.com")
                logger.info("Driver test successful")
            except Exception as test_error:
                logger.error(f"Driver test failed: {str(test_error)}")
                return False
            
            self.is_initialized = True
            logger.info("Selenium driver initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Error initializing Selenium driver: {str(e)}")
            return False
    
    async def take_screenshot(self, symbol, timeframe=None):
        """Take a screenshot of a chart"""
        if not self.is_initialized:
            logger.warning("TradingView Selenium service not initialized")
            return None
        
        try:
            logger.info(f"Taking screenshot for {symbol}")
            
            # Normaliseer het symbool (verwijder / en converteer naar hoofdletters)
            normalized_symbol = symbol.replace("/", "").upper()
            
            # Bouw de chart URL
            if self.is_logged_in:
                # Als we zijn ingelogd, gebruik de chart links uit de dictionary
                chart_url = self.chart_links.get(normalized_symbol)
                if not chart_url:
                    logger.warning(f"No chart URL found for {symbol}, using default URL")
                    chart_url = f"https://www.tradingview.com/chart/?symbol={normalized_symbol}"
                    if timeframe:
                        tv_interval = self.interval_map.get(timeframe, "D")
                        chart_url += f"&interval={tv_interval}"
            else:
                # Anders gebruik een publieke chart URL
                chart_url = f"https://www.tradingview.com/chart/?symbol={normalized_symbol}"
                if timeframe:
                    tv_interval = self.interval_map.get(timeframe, "D")
                    chart_url += f"&interval={tv_interval}"
            
            # Ga naar de chart URL
            logger.info(f"Navigating to chart URL: {chart_url}")
            self.driver.get(chart_url)
            
            # Wacht tot de pagina is geladen
            try:
                WebDriverWait(self.driver, 30).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                # Wacht nog wat extra tijd voor de chart om te laden
                time.sleep(10)
                
                # Controleer of we een 404 pagina hebben
                if "This isn't the page you're looking for" in self.driver.page_source or "404" in self.driver.page_source:
                    logger.warning("Detected 404 page, trying alternative approach")
                    
                    # Probeer een publieke chart als fallback
                    public_chart_url = f"https://www.tradingview.com/chart/?symbol={normalized_symbol}"
                    if timeframe:
                        tv_interval = self.interval_map.get(timeframe, "D")
                        public_chart_url += f"&interval={tv_interval}"
                    
                    logger.info(f"Using public chart URL as fallback: {public_chart_url}")
                    self.driver.get(public_chart_url)
                    
                    # Wacht tot de pagina is geladen
                    WebDriverWait(self.driver, 30).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                    
                    # Wacht nog wat extra tijd voor de chart om te laden
                    time.sleep(10)
                
                # Neem een screenshot
                logger.info("Taking screenshot")
                screenshot_bytes = self.driver.get_screenshot_as_png()
                
                # Log de huidige URL voor debugging
                logger.info(f"Current URL after screenshot: {self.driver.current_url}")
                
                return screenshot_bytes
            
            except TimeoutException:
                logger.error("Timeout waiting for chart to load")
                return None
            
        except Exception as e:
            logger.error(f"Error taking screenshot: {str(e)}")
            return None
    
    async def close(self):
        """Close the Selenium driver"""
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
            self.is_initialized = False
            self.is_logged_in = False
            logger.info("TradingView Selenium service closed")
        except Exception as e:
            logger.error(f"Error closing TradingView Selenium service: {str(e)}")
    
    async def batch_capture_charts(self, symbols=None, timeframes=None):
        """Capture multiple charts"""
        if not self.is_initialized:
            logger.warning("TradingView Selenium service not initialized")
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
                        # Neem screenshot
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
            if self.driver:
                self.driver.quit()
                logger.info("TradingView Selenium service cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up TradingView Selenium service: {str(e)}")
    
    async def take_screenshot_of_url(self, url):
        """Take a screenshot of a URL"""
        try:
            logger.info(f"Taking screenshot of URL: {url}")
            
            # Controleer of de driver is geïnitialiseerd
            if not self.driver:
                logger.error("Selenium driver not initialized")
                return None
            
            # Ga naar de URL
            try:
                logger.info(f"Navigating to URL: {url}")
                self.driver.get(url)
                
                # Wacht tot de pagina is geladen
                logger.info("Waiting for page to load")
                WebDriverWait(self.driver, 30).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                # Wacht nog wat langer om de pagina volledig te laden
                logger.info("Waiting for page to render")
                time.sleep(10)
                
                # Neem een screenshot
                logger.info("Taking screenshot")
                screenshot_bytes = self.driver.get_screenshot_as_png()
                
                # Log de huidige URL voor debugging
                logger.info(f"Current URL after screenshot: {self.driver.current_url}")
                
                return screenshot_bytes
            
            except TimeoutException:
                logger.error("Timeout waiting for page to load")
                return None
            
        except Exception as e:
            logger.error(f"Error taking screenshot of URL: {str(e)}")
            return None
    
    async def get_screenshot(self, url: str) -> bytes:
        """Get a screenshot of a URL using Selenium"""
        try:
            logger.info(f"Getting screenshot of {url}")
            
            # Controleer of Selenium is geïnitialiseerd
            if not self.is_initialized:
                logger.error("Selenium is not initialized, attempting to initialize")
                initialized = await self.initialize()
                if not initialized:
                    logger.error("Failed to initialize Selenium")
                    return None
            
            if not self.driver:
                logger.error("Selenium driver is None")
                return None
            
            # Navigeer naar de URL
            logger.info(f"Navigating to URL: {url}")
            try:
                self.driver.get(url)
                logger.info("Successfully navigated to URL")
            except Exception as nav_error:
                logger.error(f"Error navigating to URL: {str(nav_error)}")
                return None
            
            # Wacht tot de pagina is geladen
            logger.info("Waiting for page to load")
            try:
                await asyncio.sleep(10)  # Wacht 10 seconden (verhoogd van 5)
                logger.info("Wait completed")
            except Exception as wait_error:
                logger.error(f"Error during wait: {str(wait_error)}")
                return None
            
            # Maak een screenshot
            logger.info("Taking screenshot")
            try:
                screenshot = self.driver.get_screenshot_as_png()
                if screenshot:
                    logger.info("Screenshot taken successfully")
                    return screenshot
                else:
                    logger.error("Screenshot is None")
                    return None
            except Exception as ss_error:
                logger.error(f"Error taking screenshot: {str(ss_error)}")
                return None
            
        except Exception as e:
            logger.error(f"Error getting screenshot: {str(e)}")
            return None 
