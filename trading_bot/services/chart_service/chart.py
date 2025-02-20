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
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService

logger = logging.getLogger(__name__)

class ChartService:
    def __init__(self):
        """Initialize chart service with Chrome"""
        self.chrome_options = Options()
        self.chrome_options.add_argument('--headless=new')
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument('--window-size=1920,1080')
        
        # Chart URL mapping met exacte URLs
        self.chart_urls = {
            # Commodities
            'XAUUSD': 'https://www.tradingview.com/chart/bylCuCgc/',
            'XTIUSD': 'https://www.tradingview.com/chart/jxU29rbq/',
            
            # Currencies
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
            
            # Cryptocurrencies
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

    async def generate_chart(self, symbol: str, timeframe: str = "1h") -> Optional[bytes]:
        """Generate chart using saved layout"""
        try:
            logger.info(f"Generating chart for {symbol}")
            
            # Get base URL for symbol
            base_url = self.chart_urls.get(symbol)
            if not base_url:
                logger.error(f"No chart URL found for symbol: {symbol}")
                return None
            
            # Voeg timeframe toe aan bestaande URL
            chart_url = f"{base_url}&interval={timeframe}"
            logger.info(f"Using chart URL: {chart_url}")
            
            service = Service()
            driver = webdriver.Chrome(service=service, options=self.chrome_options)
            driver.set_page_load_timeout(30)
            
            try:
                # Load chart
                logger.info("Opening URL in Chrome...")
                driver.get(chart_url)
                
                # Wacht tot pagina geladen is
                logger.info("Waiting for initial page load...")
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                # Check of er een error pagina is
                if "Error" in driver.title:
                    logger.error(f"TradingView error page: {driver.title}")
                    return None
                
                logger.info("Waiting for chart container...")
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.CLASS_NAME, "chart-container"))
                    )
                except Exception as e:
                    logger.error(f"Chart container not found: {str(e)}")
                    logger.info(f"Current page source: {driver.page_source[:500]}")
                    return None
                
                logger.info("Chart container found, waiting for indicators...")
                await asyncio.sleep(8)
                
                # Verwijder UI elementen
                logger.info("Removing UI elements...")
                self._remove_ui_elements(driver)
                
                # Screenshot maken
                logger.info("Taking screenshot...")
                screenshot = driver.get_screenshot_as_png()
                logger.info("Chart captured successfully")
                
                return screenshot
                
            except Exception as e:
                logger.error(f"Error in Chrome: {str(e)}")
                if driver:
                    logger.error(f"Page source: {driver.page_source[:500]}")
                return None
                
            finally:
                if driver:
                    driver.quit()
                
        except Exception as e:
            logger.error(f"Error in generate_chart: {str(e)}")
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
