import os
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from typing import Optional
from selenium.webdriver.chrome.options import Options
import asyncio
import time
import base64

logger = logging.getLogger(__name__)

class ChartService:
    def __init__(self):
        """Initialize chart service with Chromium"""
        self.chrome_options = Options()
        self.chrome_options.add_argument('--headless')
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument('--disable-gpu')
        self.chrome_options.add_argument('--window-size=1920,1080')
        
        # Voeg user data directory toe voor persistente login
        self.chrome_options.add_argument('--user-data-dir=/app/chrome-data')
        
        # Initialize een browser session bij startup
        self.browser = None
        self.initialize_browser()
        
        # Chart URL mapping
        self.chart_urls = {
            # Commodities
            'XAUUSD': 'https://www.tradingview.com/chart/bylCuCgc/',
            'XTIUSD': 'https://www.tradingview.com/chart/jxU29rbq/',
            
            # Forex
            'EURUSD': 'https://www.tradingview.com/chart/xknpxpcr/',
            'EURGBP': 'https://www.tradingview.com/chart/xt6LdUUi/',
            'EURCHF': 'https://www.tradingview.com/chart/4Jr8hVba/',
            'EURJPY': 'https://www.tradingview.com/chart/ume7H7lm/',
            'EURCAD': 'https://www.tradingview.com/chart/gbtrKFPk/',
            'EURAUD': 'https://www.tradingview.com/chart/WweOZl7z/',
            'EURNZD': 'https://www.tradingview.com/chart/bcrCHPsz/',
            'GBPUSD': 'https://www.tradingview.com/chart/jKph5b1W/',
            'GBPCHF': 'https://www.tradingview.com/chart/1qMsl4FS/',
            'GBPJPY': 'https://www.tradingview.com/chart/Zcmh5M2k/',
            'GBPCAD': 'https://www.tradingview.com/chart/CvwpPBpF/',
            'GBPAUD': 'https://www.tradingview.com/chart/neo3Fc3j/',
            'GBPNZD': 'https://www.tradingview.com/chart/egeCqr65/',
            'CHFJPY': 'https://www.tradingview.com/chart/g7qBPaqM/',
            'USDJPY': 'https://www.tradingview.com/chart/mcWuRDQv/',
            'USDCHF': 'https://www.tradingview.com/chart/e7xDgRyM/',
            'USDCAD': 'https://www.tradingview.com/chart/jjTOeBNM/',
            'CADJPY': 'https://www.tradingview.com/chart/KNsPbDME/',
            'CADCHF': 'https://www.tradingview.com/chart/XnHRKk5I/',
            'AUDUSD': 'https://www.tradingview.com/chart/h7CHetVW/',
            'AUDCHF': 'https://www.tradingview.com/chart/oooBW6HP/',
            'AUDJPY': 'https://www.tradingview.com/chart/sYiGgj7B/',
            'AUDNZD': 'https://www.tradingview.com/chart/AByyHLB4/',
            'AUDCAD': 'https://www.tradingview.com/chart/L4992qKp/',
            'NZDUSD': 'https://www.tradingview.com/chart/yab05IFU/',
            'NZDCHF': 'https://www.tradingview.com/chart/7epTugqA/',
            'NZDJPY': 'https://www.tradingview.com/chart/fdtQ7rx7/',
            'NZDCAD': 'https://www.tradingview.com/chart/mRVtXs19/',
            
            # Crypto
            'BTCUSD': 'https://www.tradingview.com/chart/Nroi4EqI/',
            'ETHUSD': 'https://www.tradingview.com/chart/rVh10RLj/',
            'XRPUSD': 'https://www.tradingview.com/chart/tQu9Ca4E/',
            'SOLUSD': 'https://www.tradingview.com/chart/oTTmSjzQ/',
            'BNBUSD': 'https://www.tradingview.com/chart/wNBWNh23/',
            'ADAUSD': 'https://www.tradingview.com/chart/WcBNFrdb/',
            'LTCUSD': 'https://www.tradingview.com/chart/AoDblBMt/',
            'DOGUSD': 'https://www.tradingview.com/chart/F6SPb52v/',
            'DOTUSD': 'https://www.tradingview.com/chart/nT9dwAx2/',
            'LNKUSD': 'https://www.tradingview.com/chart/FzOrtgYw/',
            'XLMUSD': 'https://www.tradingview.com/chart/SnvxOhDh/',
            'AVXUSD': 'https://www.tradingview.com/chart/LfTlCrdQ/',
            
            # Indices
            'AU200': 'https://www.tradingview.com/chart/U5CKagMM/',
            'EU50': 'https://www.tradingview.com/chart/tt5QejVd/',
            'FR40': 'https://www.tradingview.com/chart/RoPe3S1Q/',
            'HK50': 'https://www.tradingview.com/chart/Rllftdyl/',
            'JP225': 'https://www.tradingview.com/chart/i562Fk6X/',
            'UK100': 'https://www.tradingview.com/chart/0I4gguQa/',
            'US100': 'https://www.tradingview.com/chart/5d36Cany/',
            'US500': 'https://www.tradingview.com/chart/VsfYHrwP/',
            'US30': 'https://www.tradingview.com/chart/heV5Zitn/',
            'DE40': 'https://www.tradingview.com/chart/OWzg0XNw/'
        }

    def initialize_browser(self):
        """Initialize browser en log in op TradingView"""
        try:
            logger.info("Starting browser initialization...")
            
            # Voeg extra Chrome opties toe voor stabiliteit
            self.chrome_options.add_argument('--headless=new')
            self.chrome_options.add_argument('--no-sandbox')
            self.chrome_options.add_argument('--disable-dev-shm-usage')
            self.chrome_options.add_argument('--disable-gpu')
            self.chrome_options.add_argument('--disable-software-rasterizer')
            self.chrome_options.add_argument('--disable-extensions')
            self.chrome_options.add_argument('--single-process')
            self.chrome_options.add_argument('--ignore-certificate-errors')
            
            # Maak chrome-data directory als deze niet bestaat
            os.makedirs('/app/chrome-data', exist_ok=True)
            
            logger.info("Starting Chrome webdriver...")
            self.browser = webdriver.Chrome(options=self.chrome_options)
            
            # Haal credentials uit environment variables
            email = os.getenv("TRADINGVIEW_EMAIL")
            password = os.getenv("TRADINGVIEW_PASSWORD")
            
            if not email or not password:
                raise ValueError("Missing TradingView credentials in environment")
            
            logger.info("Navigating to TradingView login page...")
            self.browser.get('https://www.tradingview.com/accounts/signin/')
            
            # Wacht tot login form zichtbaar is
            logger.info("Waiting for login form...")
            try:
                email_input = WebDriverWait(self.browser, 20).until(
                    EC.presence_of_element_located((By.NAME, "username"))
                )
                logger.info("Login form found")
                
                # Vul login gegevens in
                email_input.send_keys(email)
                password_input = self.browser.find_element(By.NAME, "password")
                password_input.send_keys(password)
                
                # Klik login button
                logger.info("Submitting login form...")
                submit_button = self.browser.find_element(By.XPATH, "//button[@type='submit']")
                submit_button.click()
                
                # Wacht tot login compleet is
                logger.info("Waiting for login completion...")
                time.sleep(10)
                
                logger.info("Successfully logged in to TradingView")
                
            except Exception as e:
                logger.error(f"Error during login process: {str(e)}")
                if self.browser:
                    logger.info("Current page source:")
                    logger.info(self.browser.page_source[:1000])  # Log eerste 1000 chars
                    self.browser.quit()
                self.browser = None
                raise
                
        except Exception as e:
            logger.error(f"Error initializing browser: {str(e)}")
            if self.browser:
                self.browser.quit()
            self.browser = None
            raise

    async def generate_chart(self, symbol: str, timeframe: str = "1h") -> Optional[bytes]:
        """Generate chart using Chromium"""
        try:
            if not self.browser:
                self.initialize_browser()
            
            logger.info(f"Generating chart for {symbol}")
            
            # Get chart URL
            chart_url = self._get_chart_url(symbol)
            logger.info(f"Using chart URL: {chart_url}")
            
            # Extra Chrome options voor betere stabiliteit
            self.chrome_options.add_argument('--headless=new')  # Nieuwe headless mode
            self.chrome_options.add_argument('--no-sandbox')
            self.chrome_options.add_argument('--disable-dev-shm-usage')
            self.chrome_options.add_argument('--disable-gpu')
            self.chrome_options.add_argument('--window-size=1920,1080')
            self.chrome_options.add_argument('--start-maximized')
            self.chrome_options.add_argument('--force-device-scale-factor=1')
            
            # Initialize Chrome webdriver
            driver = webdriver.Chrome(options=self.chrome_options)
            driver.set_page_load_timeout(60)  # Langere timeout
            
            try:
                # Load page
                driver.get(chart_url)
                logger.info("Page loaded, waiting for elements...")
                
                # Langere initiële wachttijd
                await asyncio.sleep(10)
                
                # Probeer verschillende selectors met logging
                selectors = [
                    "div.chart-container",
                    "div.chart-markup-table",
                    "div.layout__area--center",
                    "div[data-name='chart-container']",
                    "div.chart-widget",
                    "div.chart-container-border"
                ]
                
                # Log de page source voor debugging
                logger.info(f"Page source: {driver.page_source[:500]}...")  # Eerste 500 chars
                
                chart_element = None
                for selector in selectors:
                    try:
                        logger.info(f"Trying selector: {selector}")
                        # Wacht op element
                        element = WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        chart_element = element
                        logger.info(f"Found chart element with selector: {selector}")
                        break
                    except Exception as e:
                        logger.warning(f"Selector {selector} failed: {str(e)}")
                        continue
                
                if chart_element is None:
                    # Probeer een volledige pagina screenshot als fallback
                    logger.info("No chart element found, taking full page screenshot")
                    screenshot = driver.get_screenshot_as_png()
                    return screenshot
                
                # Extra wachttijd voor chart rendering
                await asyncio.sleep(5)
                
                # Take screenshot
                screenshot = chart_element.screenshot_as_png
                logger.info("Successfully captured chart screenshot")
                
                return screenshot
                
            finally:
                driver.quit()
                
        except Exception as e:
            logger.error(f"Error generating chart: {str(e)}")
            logger.exception(e)
            return None

    def _get_chart_url(self, symbol: str) -> str:
        """Get chart URL for symbol"""
        return self.chart_urls.get(symbol, "https://www.tradingview.com/chart/")

    def _remove_ui_elements(self, driver):
        """Remove unnecessary UI elements from the chart"""
        try:
            elements_to_remove = [
                "header-chart-panel",
                "control-bar",
                "bottom-widgetbar-content",
                "chart-controls-bar"
            ]
            
            for class_name in elements_to_remove:
                elements = driver.find_elements(By.CLASS_NAME, class_name)
                for element in elements:
                    driver.execute_script("arguments[0].style.display = 'none';", element)
                    
        except Exception as e:
            logger.warning(f"Error removing UI elements: {str(e)}")
