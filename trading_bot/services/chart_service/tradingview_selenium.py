import os
import time
import logging
import asyncio
import base64
from io import BytesIO
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.utils import ChromeType

logger = logging.getLogger(__name__)

class TradingViewSeleniumService:
    def __init__(self, session_id=None):
        """Initialize the TradingView Selenium service"""
        self.session_id = session_id or os.getenv("TRADINGVIEW_SESSION_ID", "z90l85p2anlgdwfppsrdnnfantz48z1o")
        self.driver = None
        self.is_initialized = False
        self.base_url = "https://www.tradingview.com"
        self.chart_url = "https://www.tradingview.com/chart"
        
        # Chart links voor verschillende symbolen
        self.chart_links = {
            "EURUSD": "https://www.tradingview.com/chart/?symbol=EURUSD",
            "GBPUSD": "https://www.tradingview.com/chart/?symbol=GBPUSD",
            "BTCUSD": "https://www.tradingview.com/chart/?symbol=BTCUSD",
            "ETHUSD": "https://www.tradingview.com/chart/?symbol=ETHUSD"
        }
        
        logger.info(f"TradingView Selenium service initialized with session ID: {self.session_id[:5]}...")
    
    async def initialize(self):
        """Initialize the Selenium WebDriver"""
        try:
            logger.info("Initializing TradingView Selenium service")
            
            # Configureer Chrome opties
            chrome_options = Options()
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-infobars")
            chrome_options.add_argument("--disable-notifications")
            chrome_options.add_argument("--force-dark-mode")
            
            # Gebruik WebDriverManager om ChromeDriver te beheren
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install()),
                options=chrome_options
            )
            
            # Ga naar TradingView en voeg session cookie toe
            self.driver.get(self.base_url)
            
            # Voeg session ID cookie toe
            self.driver.add_cookie({
                'name': 'sessionid',
                'value': self.session_id,
                'domain': '.tradingview.com'
            })
            
            # Vernieuw de pagina om de cookie te activeren
            self.driver.refresh()
            
            # Wacht even om de pagina te laden
            await asyncio.sleep(5)
            
            # Controleer of we ingelogd zijn
            if self._is_logged_in():
                logger.info("Successfully logged in to TradingView using session ID")
                self.is_initialized = True
                return True
            else:
                logger.warning("Failed to log in with session ID")
                return False
                
        except Exception as e:
            logger.error(f"Error initializing TradingView Selenium service: {str(e)}")
            return False
    
    def _is_logged_in(self):
        """Check if we are logged in to TradingView"""
        try:
            # Controleer of er een gebruikersmenu element aanwezig is
            user_menu = self.driver.find_elements(By.CSS_SELECTOR, ".tv-header__user-menu-button")
            return len(user_menu) > 0
        except Exception as e:
            logger.error(f"Error checking login status: {str(e)}")
            return False
    
    async def take_screenshot(self, symbol, timeframe=None, adjustment=100):
        """Take a screenshot of a chart"""
        if not self.is_initialized:
            logger.warning("TradingView Selenium service not initialized")
            return None
        
        try:
            # Bepaal de chart URL
            chart_url = self.chart_links.get(symbol, f"{self.chart_url}/?symbol={symbol}")
            logger.info(f"Taking screenshot of {symbol} at {timeframe}, URL: {chart_url}")
            
            # Navigeer naar de chart
            self.driver.get(chart_url)
            
            # Wacht tot de chart is geladen
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".chart-container"))
            )
            
            # Wacht nog wat extra tijd voor volledige rendering
            time.sleep(10)
            
            # Stel timeframe in als opgegeven
            if timeframe:
                self._set_timeframe(timeframe)
            
            # Pas de positie aan (scroll naar rechts)
            actions = ActionChains(self.driver)
            actions.send_keys(Keys.ESCAPE).perform()  # Sluit eventuele dialogen
            actions.send_keys(Keys.RIGHT * adjustment).perform()
            time.sleep(3)
            
            # Verberg UI elementen voor een schone screenshot
            self._hide_ui_elements()
            
            # Neem screenshot
            screenshot = self.driver.get_screenshot_as_png()
            
            # Converteer naar PIL Image voor eventuele bewerking
            img = Image.open(BytesIO(screenshot))
            
            # Converteer terug naar bytes
            img_byte_arr = BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            
            logger.info(f"Successfully took screenshot of {symbol} at {timeframe}")
            return img_byte_arr.getvalue()
            
        except Exception as e:
            logger.error(f"Error taking screenshot: {str(e)}")
            return None
    
    def _set_timeframe(self, timeframe):
        """Set the chart timeframe"""
        try:
            # Zoek de timeframe knop
            timeframe_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".chart-toolbar-timeframes button"))
            )
            timeframe_button.click()
            
            # Wacht op het dropdown menu
            time.sleep(1)
            
            # Zoek en klik op de juiste timeframe optie
            timeframe_options = self.driver.find_elements(By.CSS_SELECTOR, ".menu-item")
            for option in timeframe_options:
                if timeframe.lower() in option.text.lower():
                    option.click()
                    break
            
            # Wacht tot de chart is bijgewerkt
            time.sleep(3)
            
        except Exception as e:
            logger.error(f"Error setting timeframe: {str(e)}")
    
    def _hide_ui_elements(self):
        """Hide UI elements for a clean screenshot"""
        try:
            # JavaScript om UI elementen te verbergen
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
            
            self.driver.execute_script(js_hide_elements)
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"Error hiding UI elements: {str(e)}")
    
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
