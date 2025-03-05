import os
import logging
import asyncio
import json
import base64
import subprocess
from io import BytesIO
from datetime import datetime
from trading_bot.services.chart_service.tradingview import TradingViewService

logger = logging.getLogger(__name__)

class TradingViewNodeService(TradingViewService):
    def __init__(self, session_id=None):
        """Initialize the TradingView Node.js service"""
        super().__init__()
        self.session_id = session_id or os.getenv("TRADINGVIEW_SESSION_ID", "")
        self.username = os.getenv("TRADINGVIEW_USERNAME", "")
        self.password = os.getenv("TRADINGVIEW_PASSWORD", "")
        self.is_initialized = False
        self.is_logged_in = False
        self.base_url = "https://www.tradingview.com"
        self.chart_url = "https://www.tradingview.com/chart"
        self.script_path = os.path.join(os.getcwd(), "tradingview_screenshot.js")
        
        # Chart links voor verschillende symbolen
        self.chart_links = {
            "EURUSD": "https://www.tradingview.com/chart/?symbol=EURUSD",
            "GBPUSD": "https://www.tradingview.com/chart/?symbol=GBPUSD",
            "BTCUSD": "https://www.tradingview.com/chart/?symbol=BTCUSD",
            "ETHUSD": "https://www.tradingview.com/chart/?symbol=ETHUSD"
        }
        
        logger.info(f"TradingView Node.js service initialized")
    
    async def initialize(self):
        """Initialize the Node.js service"""
        try:
            logger.info("Initializing TradingView Node.js service")
            
            # Controleer of het script bestaat
            if not os.path.exists(self.script_path):
                logger.error(f"Script not found at {self.script_path}")
                return False
            
            # Test of Node.js beschikbaar is
            try:
                process = await asyncio.create_subprocess_exec(
                    'node', '--version',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    logger.error(f"Node.js not available: {stderr.decode()}")
                    return False
                
                logger.info(f"Node.js version: {stdout.decode().strip()}")
            except Exception as e:
                logger.error(f"Error checking Node.js: {str(e)}")
                return False
            
            # Controleer of de benodigde npm packages zijn geïnstalleerd
            try:
                process = await asyncio.create_subprocess_exec(
                    'npm', 'list', 'playwright-extra',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    logger.warning(f"playwright-extra not installed: {stderr.decode()}")
                    logger.info("Installing required npm packages...")
                    
                    # Installeer de benodigde packages
                    install_process = await asyncio.create_subprocess_exec(
                        'npm', 'install', 'playwright-extra', 'puppeteer-extra-plugin-stealth', 
                        'puppeteer-extra-plugin-recaptcha', 'dotenv', '@playwright/test',
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    
                    install_stdout, install_stderr = await install_process.communicate()
                    
                    if install_process.returncode != 0:
                        logger.error(f"Failed to install npm packages: {install_stderr.decode()}")
                        return False
                    
                    logger.info("Successfully installed npm packages")
            except Exception as e:
                logger.error(f"Error checking npm packages: {str(e)}")
                return False
            
            self.is_initialized = True
            self.is_logged_in = True  # We gaan ervan uit dat het script de login afhandelt
            logger.info("TradingView Node.js service initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing TradingView Node.js service: {str(e)}")
            return False
    
    async def take_screenshot(self, symbol, timeframe=None):
        """Take a screenshot of a chart"""
        try:
            logger.info(f"Taking screenshot for {symbol} on {timeframe} timeframe")
            
            # Normaliseer het symbool (verwijder / en converteer naar hoofdletters)
            normalized_symbol = symbol.replace("/", "").upper()
            
            # Bouw de chart URL
            chart_url = self.chart_links.get(normalized_symbol)
            if not chart_url:
                logger.warning(f"No chart URL found for {symbol}, using default URL")
                # Gebruik een lichtere versie van de chart
                chart_url = f"https://www.tradingview.com/chart/xknpxpcr/?symbol={normalized_symbol}"
                if timeframe:
                    tv_interval = self.interval_map.get(timeframe, "D")
                    chart_url += f"&interval={tv_interval}"
            
            # Controleer of de URL geldig is
            if not chart_url:
                logger.error(f"Invalid chart URL for {symbol}")
                return None
            
            # Maak een tijdelijk bestand voor de screenshot
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                screenshot_path = temp_file.name
            
            # Voer het Node.js script uit om een screenshot te maken
            import subprocess
            
            # Controleer of het script bestaat
            script_path = os.path.join(os.path.dirname(__file__), "screenshot.js")
            if not os.path.exists(script_path):
                logger.error(f"Screenshot script not found at {script_path}")
                return None
            
            # Voeg de session ID toe aan de command line arguments
            command = ["node", script_path, chart_url, screenshot_path]
            if self.session_id:
                command.append(self.session_id)
                logger.info(f"Using session ID: {self.session_id[:5]}...")
            
            # Voer het script uit
            logger.info(f"Running Node.js script: {script_path} with URL: {chart_url} and output: {screenshot_path}")
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = process.communicate()
            
            # Log de output
            if stdout:
                logger.info(f"Node.js script output: {stdout.decode('utf-8')}")
            if stderr:
                logger.error(f"Node.js script error: {stderr.decode('utf-8')}")
            
            # Controleer of het script succesvol was
            if process.returncode != 0:
                logger.error(f"Node.js script failed with return code {process.returncode}")
                return None
            
            # Controleer of het bestand bestaat
            if not os.path.exists(screenshot_path):
                logger.error(f"Screenshot file not found at {screenshot_path}")
                return None
            
            # Lees het bestand
            with open(screenshot_path, "rb") as f:
                screenshot_bytes = f.read()
            
            # Verwijder het tijdelijke bestand
            os.unlink(screenshot_path)
            
            return screenshot_bytes
            
        except Exception as e:
            logger.error(f"Error taking screenshot: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    async def batch_capture_charts(self, symbols=None, timeframes=None):
        """Capture multiple charts"""
        if not self.is_initialized:
            logger.warning("TradingView Node.js service not initialized")
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
        # Geen resources om op te ruimen
        logger.info("TradingView Node.js service cleaned up") 
