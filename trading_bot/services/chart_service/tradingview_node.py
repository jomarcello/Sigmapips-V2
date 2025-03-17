import os
import logging
import asyncio
import json
import base64
import subprocess
import time
from typing import Optional, Dict, List, Any, Union
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
            
            # Controleer of de benodigde Node.js modules zijn geïnstalleerd
            try:
                # Controleer of playwright is geïnstalleerd
                playwright_check = subprocess.run(["npm", "list", "-g", "playwright"], 
                                                 stdout=subprocess.PIPE, 
                                                 stderr=subprocess.PIPE)
                
                if playwright_check.returncode != 0:
                    logger.info("Installing Playwright...")
                    subprocess.run(["npm", "install", "-g", "playwright"], check=True)
                
                # Controleer of @playwright/test is geïnstalleerd
                test_check = subprocess.run(["npm", "list", "-g", "@playwright/test"], 
                                           stdout=subprocess.PIPE, 
                                           stderr=subprocess.PIPE)
                
                if test_check.returncode != 0:
                    logger.info("Installing @playwright/test...")
                    subprocess.run(["npm", "install", "-g", "@playwright/test"], check=True)
                
                # Controleer of playwright-core is geïnstalleerd
                core_check = subprocess.run(["npm", "list", "-g", "playwright-core"], 
                                           stdout=subprocess.PIPE, 
                                           stderr=subprocess.PIPE)
                
                if core_check.returncode != 0:
                    logger.info("Installing playwright-core...")
                    subprocess.run(["npm", "install", "-g", "playwright-core"], check=True)
                
                logger.info("Playwright modules are installed")
            except Exception as e:
                logger.error(f"Error checking/installing Playwright modules: {str(e)}")
                # Ga door, want we kunnen nog steeds proberen om de service te gebruiken
            
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
    
    async def take_screenshot(self, symbol, timeframe=None, fullscreen=False):
        """Take a screenshot of a chart"""
        try:
            logger.info(f"Taking screenshot for {symbol} on {timeframe} timeframe (fullscreen: {fullscreen})")
            
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
            
            # Voeg fullscreen parameter toe indien nodig
            if fullscreen:
                command.append("fullscreen")
            
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
    
    async def take_screenshot_of_url(self, url: str, fullscreen: bool = False):
        """Take a screenshot of a TradingView chart URL using Node.js"""
        try:
            # Bepaal het pad naar de screenshot.js
            js_path = os.path.join(os.path.dirname(__file__), 'screenshot.js')
            output_path = os.path.join(os.path.dirname(__file__), f'screenshot_{int(time.time())}.png')
            
            # Haal de sessie ID op
            session_id = os.getenv("TRADINGVIEW_SESSION_ID", "")
            
            # Bepaal de fullscreen parameter
            fullscreen_arg = "fullscreen" if fullscreen else ""
            
            # Voer het Node.js script uit
            cmd = f"node {js_path} \"{url}\" \"{output_path}\" \"{session_id}\" {fullscreen_arg}"
            
            # Log de command (zonder de session ID om privacy te waarborgen)
            safe_cmd = cmd.replace(session_id, "****") if session_id else cmd
            logger.info(f"Running command: {safe_cmd}")
            
            # Voer het commando uit
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Wacht op resultaten
            stdout, stderr = await process.communicate()
            
            # Log de output
            logger.info(f"Node.js output: {stdout.decode()}")
            if stderr:
                logger.warning(f"Node.js error: {stderr.decode()}")
            
            # Controleer of het proces succesvol was
            if process.returncode != 0:
                logger.error(f"Node.js process returned non-zero exit code: {process.returncode}")
                return None
            
            # Controleer of het bestand bestaat
            if not os.path.exists(output_path):
                logger.error(f"Screenshot file not found: {output_path}")
                return None
            
            # Lees het bestand
            with open(output_path, 'rb') as f:
                screenshot_data = f.read()
            
            # Verwijder het bestand
            try:
                os.remove(output_path)
            except Exception as e:
                logger.warning(f"Failed to remove temporary screenshot file: {str(e)}")
            
            return screenshot_data
            
        except Exception as e:
            logger.error(f"Error taking screenshot with Node.js: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None 
