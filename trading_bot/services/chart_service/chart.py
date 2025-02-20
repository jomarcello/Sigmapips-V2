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
        
        # Chrome opties voor persistente sessie
        self.chrome_options.add_argument('--headless=new')
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument('--window-size=1920,1080')
        
        # Belangrijk: User data directory voor persistente login
        user_data_dir = "/app/chrome-data"
        os.makedirs(user_data_dir, exist_ok=True)
        self.chrome_options.add_argument(f'--user-data-dir={user_data_dir}')
        
        # Eerst inloggen en sessie opslaan
        self.login_tradingview()
        
    def login_tradingview(self):
        """Log in to TradingView and save session"""
        try:
            service = Service()
            driver = webdriver.Chrome(service=service, options=self.chrome_options)
            
            # Ga naar login pagina
            driver.get('https://www.tradingview.com/accounts/signin/')
            time.sleep(5)
            
            # Klik eerst op de "Email" login optie
            email_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Email')]"))
            )
            email_button.click()
            time.sleep(2)  # Wacht tot email form verschijnt
            
            # Login gegevens invullen
            email = os.getenv("TRADINGVIEW_EMAIL")
            password = os.getenv("TRADINGVIEW_PASSWORD")
            
            # Nu pas het email veld invullen
            email_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "username"))
            )
            email_input.send_keys(email)
            time.sleep(1)
            
            password_input = driver.find_element(By.NAME, "password")
            password_input.send_keys(password)
            time.sleep(1)
            
            # Submit button klikken
            submit_button = driver.find_element(By.XPATH, "//button[@type='submit']")
            submit_button.click()
            
            # Wacht tot login compleet is
            time.sleep(10)
            
            logger.info("Successfully logged in and saved session")
            
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            logger.error(f"Current page source: {driver.page_source[:1000]}")  # Log page source voor debugging
        finally:
            driver.quit()

    async def generate_chart(self, symbol: str, timeframe: str = "1h") -> Optional[bytes]:
        """Generate chart using saved session"""
        try:
            service = Service()
            driver = webdriver.Chrome(service=service, options=self.chrome_options)
            
            # Gebruik je chart layout met indicators
            chart_url = f"https://www.tradingview.com/chart/YOUR_CHART_ID/?symbol={symbol}"
            driver.get(chart_url)
            
            # Wacht tot chart en indicators geladen zijn
            time.sleep(10)
            
            # Screenshot
            screenshot = driver.get_screenshot_as_png()
            return screenshot
            
        except Exception as e:
            logger.error(f"Error generating chart: {str(e)}")
            return None
        finally:
            driver.quit()

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
