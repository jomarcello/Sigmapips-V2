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
        self.session_id = session_id or os.getenv("TRADINGVIEW_SESSION_ID", "z90l85p2anlgdwfppsrdnnfantz48z1o")
        self.username = os.getenv("TRADINGVIEW_USERNAME", "")
        self.password = os.getenv("TRADINGVIEW_PASSWORD", "")
        self.is_initialized = False
        self.is_logged_in = False
        self.base_url = "https://www.tradingview.com"
        self.chart_url = "https://www.tradingview.com/chart"
        
        # Get the project root directory and set the correct script path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        self.script_path = os.path.join(project_root, "tradingview_screenshot.js")
        
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
                process = await asyncio.create_subprocess_exec(
                    "node", "--version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
                node_version = stdout.decode().strip()
                logger.info(f"Node.js version: {node_version}")
            except Exception as node_error:
                logger.error(f"Node.js not found: {str(node_error)}")
                return False
            
            # Controleer of het script bestaat
            if not os.path.exists(self.script_path):
                logger.error(f"Script niet gevonden: {self.script_path}")
                return False
            
            # Test een snelle screenshot om te controleren of de service werkt
            logger.info("Testing Node.js service with a quick screenshot")
            test_url = "https://www.example.com"
            
            # Voer een snelle test uit
            try:
                # Gebruik een korte timeout voor de test
                test_cmd = ["node", self.script_path, test_url, "/tmp/test_screenshot.png", "", ""]
                test_process = await asyncio.create_subprocess_exec(
                    *test_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                test_stdout, test_stderr = await asyncio.wait_for(test_process.communicate(), timeout=15)
                
                if test_process.returncode == 0:
                    logger.info("Node.js service test successful")
                    self.is_initialized = True
                    return True
                else:
                    logger.error(f"Node.js test failed with exit code {test_process.returncode}")
                    logger.error(f"Error: {test_stderr.decode()}")
                    return False
                
            except asyncio.TimeoutError:
                logger.error("Node.js service test timed out after 15 seconds")
                return False
            except Exception as e:
                logger.error(f"Node.js service test failed: {str(e)}")
                return False
                
        except Exception as e:
            logger.error(f"Error initializing Node.js service: {str(e)}")
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
            
            # Gebruik de take_screenshot_of_url methode om de screenshot te maken
            logger.info(f"Taking screenshot of URL: {chart_url}")
            screenshot_bytes = await self.take_screenshot_of_url(chart_url, fullscreen=fullscreen)
            
            if screenshot_bytes:
                logger.info(f"Screenshot taken successfully for {symbol}")
                return screenshot_bytes
            else:
                logger.error(f"Failed to take screenshot for {symbol}")
                return None
            
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
    
    async def take_screenshot_of_url(self, url: str, fullscreen: bool = False) -> Optional[bytes]:
        """Take a screenshot of a URL using Node.js and Playwright"""
        try:
            # Genereer een unieke bestandsnaam voor de screenshot
            timestamp = int(time.time())
            if hasattr(self, 'screenshot_dir') and self.screenshot_dir:
                os.makedirs(self.screenshot_dir, exist_ok=True)
                screenshot_path = os.path.join(self.screenshot_dir, f"screenshot_{timestamp}.png")
            else:
                # Docker container pad als we in Docker draaien, anders tijdelijk bestand
                if os.path.exists('/app'):
                    screenshot_path = f"/app/screenshot_{timestamp}.png"
                else:
                    screenshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"screenshot_{timestamp}.png")
            
            # Bereid de Node.js opdracht voor
            js_path = self.script_path if hasattr(self, 'script_path') and self.script_path else "tradingview_screenshot.js"
            
            # Controleer of het pad bestaat
            if not os.path.exists(js_path) and js_path == "tradingview_screenshot.js":
                # Probeer het bestand in de root van het project te vinden
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
                js_path = os.path.join(project_root, "tradingview_screenshot.js")
                if not os.path.exists(js_path):
                    logger.error(f"JavaScript bestand niet gevonden: {js_path}")
                    return None
            
            # Fullscreen parameter toevoegen aan opdracht
            fullscreen_param = "fullscreen" if fullscreen else ""
            if fullscreen:
                logger.info("Adding fullscreen parameter to command")
            
            # Stel je session ID in
            session_id = self.session_id if hasattr(self, 'session_id') and self.session_id else ""
            
            # Voer de Node.js opdracht uit met een kortere timeout
            logger.info(f"Running command: node {js_path} \"{url}\" \"{screenshot_path}\" \"****\" {fullscreen_param}")
            
            cmd = ["node", js_path, url, screenshot_path, session_id, fullscreen_param]
            
            # Voer het proces uit met een kortere timeout (was 60 seconden)
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Wacht maximaal 30 seconden op het proces om te voltooien (was 15 seconden)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
                stdout_str = stdout.decode('utf-8', errors='ignore')
                stderr_str = stderr.decode('utf-8', errors='ignore')
                
                logger.info(f"Node.js stdout: {stdout_str[:200]}...")
                if stderr_str:
                    logger.error(f"Node.js stderr: {stderr_str[:200]}...")
                
                if process.returncode != 0:
                    logger.error(f"Node.js process returned non-zero exit code: {process.returncode}")
                    return None
                
            except asyncio.TimeoutError:
                logger.error("Node.js process timed out after 30 seconds")
                process.kill()
                return None
            
            # Controleer of het bestand bestaat
            if os.path.exists(screenshot_path):
                # Lees het bestand
                with open(screenshot_path, 'rb') as f:
                    screenshot_data = f.read()
                
                # Verwijder het bestand
                os.remove(screenshot_path)
                
                return screenshot_data
            else:
                logger.error(f"Screenshot file not found: {screenshot_path}")
                return None
        
        except Exception as e:
            logger.error(f"Error taking screenshot with Node.js: {str(e)}")
            return None
