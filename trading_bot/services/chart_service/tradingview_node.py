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
            
            # Controleer of Node.js is geïnstalleerd
            try:
                node_version = subprocess.check_output(["node", "--version"]).decode().strip()
                logger.info(f"Node.js version: {node_version}")
            except Exception as node_error:
                logger.error(f"Error checking Node.js version: {str(node_error)}")
                return False
            
            # Controleer of het screenshot.js bestand bestaat
            script_path = os.path.join(os.path.dirname(__file__), "screenshot.js")
            if not os.path.exists(script_path):
                logger.error(f"screenshot.js not found at {script_path}")
                return False
            
            logger.info(f"screenshot.js found at {script_path}")
            
            # Test de Node.js service met een eenvoudige URL
            try:
                logger.info("Testing Node.js service with a simple URL")
                test_result = await self.take_screenshot_of_url("https://www.google.com")
                if test_result:
                    logger.info("Node.js service test successful")
                    self.is_initialized = True
                    return True
                else:
                    logger.error("Node.js service test failed")
                    return False
            except Exception as test_error:
                logger.error(f"Error testing Node.js service: {str(test_error)}")
                return False
            
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
                # Gebruik een specifieke chart layout die beter werkt met fullscreen
                chart_url = f"https://www.tradingview.com/chart/xknpxpcr/?symbol={normalized_symbol}&fullscreen=true&hide_side_toolbar=true&hide_top_toolbar=true&scale=1.2"
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
    
    async def take_screenshot_of_url(self, url):
        """Take a screenshot of a URL"""
        try:
            logger.info(f"Taking screenshot of URL: {url}")
            
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
            command = ["node", script_path, url, screenshot_path]
            if self.session_id:
                command.append(self.session_id)
                logger.info(f"Using session ID: {self.session_id[:5]}...")
            
            # Voer het script uit
            logger.info(f"Running Node.js script: {script_path} with URL: {url} and output: {screenshot_path}")
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
            logger.error(f"Error taking screenshot of URL: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None 
