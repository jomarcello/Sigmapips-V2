import os
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
import io

logger = logging.getLogger(__name__)

class ChartService:
    def __init__(self):
        """Initialize chart service with Selenium"""
        self.chrome_options = Options()
        self.chrome_options.add_argument('--headless')
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument('--window-size=1920,1080')
        
        # TradingView base URL
        self.base_url = "https://www.tradingview.com/chart/"
        
    def _get_symbol_with_broker(self, symbol: str, market: str) -> str:
        """Get symbol with correct broker prefix"""
        if market.lower() == 'forex':
            return f"OANDA:{symbol}"  # Gebruik OANDA voor forex pairs
        
        prefixes = {
            'crypto': 'BINANCE:',
            'indices': '',
            'commodities': ''
        }
        return f"{prefixes.get(market.lower(), '')}{symbol}"

    async def generate_chart(self, symbol: str, timeframe: str, market: str = 'forex') -> bytes:
        """Generate chart image for given symbol and timeframe"""
        try:
            logger.info(f"Generating chart for {symbol} on {timeframe} timeframe")
            
            # Get symbol with correct broker
            full_symbol = self._get_symbol_with_broker(symbol, market)
            
            # Initialize driver
            driver = webdriver.Chrome(options=self.chrome_options)
            
            try:
                # Construct URL met @ aan het begin
                url = f"@{self.base_url}?symbol={full_symbol}&interval={timeframe}"
                logger.info(f"Chart URL: {url}")
                driver.get(url)
                
                # Wait for chart to load
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "chart-container"))
                )
                
                # Remove unnecessary UI elements
                self._remove_ui_elements(driver)
                
                # Take screenshot
                chart_element = driver.find_element(By.CLASS_NAME, "chart-container")
                screenshot = chart_element.screenshot_as_png
                
                # Process image
                img = Image.open(io.BytesIO(screenshot))
                img = img.convert('RGB')
                
                # Save to bytes
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG', quality=85)
                img_byte_arr = img_byte_arr.getvalue()
                
                logger.info(f"Successfully generated chart for {symbol}")
                return img_byte_arr
                
            finally:
                driver.quit()
                
        except Exception as e:
            logger.error(f"Error generating chart: {str(e)}")
            raise
            
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

