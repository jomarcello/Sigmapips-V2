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
        self.chart_links = {
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
            
            # Configureer Chrome opties
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-infobars")
            
            # Voeg user-agent toe
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
            
            # Start de Chrome driver
            self.driver = webdriver.Chrome(options=chrome_options)
            
            # Als er een session ID is, gebruik deze
            if self.session_id:
                logger.info(f"Using session ID for authentication: {self.session_id[:5]}...")
                
                # Ga eerst naar TradingView om cookies te kunnen instellen
                self.driver.get("https://www.tradingview.com/")
                
                # Wacht even om de pagina te laden
                time.sleep(5)
                
                # Log alle huidige cookies
                logger.info(f"Current cookies before setting: {self.driver.get_cookies()}")
                
                # Verwijder alle bestaande cookies
                self.driver.delete_all_cookies()
                logger.info("Deleted all existing cookies")
                
                # Voeg cookies toe
                cookies_to_add = [
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
                ]
                
                for cookie in cookies_to_add:
                    try:
                        self.driver.add_cookie(cookie)
                        logger.info(f"Added cookie: {cookie['name']}")
                    except Exception as cookie_error:
                        logger.error(f"Error adding cookie {cookie['name']}: {str(cookie_error)}")
                
                # Log alle cookies na het instellen
                logger.info(f"Cookies after setting: {self.driver.get_cookies()}")
                
                # Ververs de pagina om de cookies te activeren
                self.driver.refresh()
                time.sleep(5)
                
                # Controleer of we zijn ingelogd
                try:
                    # Ga naar de chart pagina
                    self.driver.get("https://www.tradingview.com/chart/")
                    
                    # Wacht maximaal 15 seconden
                    WebDriverWait(self.driver, 15).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                    
                    # Wacht nog wat extra tijd voor de pagina om te laden
                    time.sleep(5)
                    
                    # Neem een screenshot voor debugging
                    debug_screenshot_path = "/tmp/tradingview_login_check.png"
                    self.driver.save_screenshot(debug_screenshot_path)
                    logger.info(f"Saved login check screenshot to {debug_screenshot_path}")
                    
                    # Controleer of we zijn ingelogd door te zoeken naar elementen die alleen zichtbaar zijn als je bent ingelogd
                    page_source = self.driver.page_source
                    
                    # Zoek naar tekenen van ingelogd zijn
                    logged_in_indicators = [
                        "Sign Out",
                        "Account",
                        "Profile",
                        "My Profile",
                        "user-menu-button"
                    ]
                    
                    is_logged_in = any(indicator in page_source for indicator in logged_in_indicators)
                    
                    if is_logged_in:
                        logger.info("Successfully authenticated with session ID")
                        self.is_logged_in = True
                    else:
                        logger.warning("Session ID authentication failed, but continuing anyway")
                        self.is_logged_in = False
                except Exception as page_error:
                    logger.error(f"Error testing session: {str(page_error)}")
                    self.is_logged_in = False
            else:
                logger.warning("No session ID provided")
                self.is_logged_in = False
            
            self.is_initialized = True
            return True
        
        except Exception as e:
            logger.error(f"Error initializing TradingView Selenium service: {str(e)}")
            self.is_initialized = False
            self.is_logged_in = False
            
            # Probeer de driver te sluiten als er een fout optreedt
            try:
                if self.driver:
                    self.driver.quit()
                    self.driver = None
            except:
                pass
                
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
