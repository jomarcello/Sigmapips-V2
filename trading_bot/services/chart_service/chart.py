import os
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from typing import Optional
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver import Firefox

logger = logging.getLogger(__name__)

class ChartService:
    def __init__(self):
        """Initialize chart service with Selenium"""
        self.chrome_options = Options()
        self.chrome_options.add_argument('--headless')
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument('--window-size=1920,1080')
        
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

    async def generate_chart(self, symbol: str, timeframe: str = "1h") -> Optional[bytes]:
        """Generate chart using Firefox"""
        try:
            logger.info(f"Generating chart for {symbol}")
            
            # Get chart URL
            chart_url = self._get_chart_url(symbol)
            logger.info(f"Using chart URL: {chart_url}")
            
            # Setup Firefox options
            firefox_options = FirefoxOptions()
            firefox_options.add_argument('--headless')
            firefox_options.add_argument('--width=1920')
            firefox_options.add_argument('--height=1080')
            
            # Initialize driver
            driver = Firefox(options=firefox_options)
            
            try:
                # Load page
                driver.get(chart_url)
                
                # Wait for chart to load
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "chart-container"))
                )
                
                # Take screenshot
                chart_element = driver.find_element(By.CLASS_NAME, "chart-container")
                screenshot = chart_element.screenshot_as_png
                
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
