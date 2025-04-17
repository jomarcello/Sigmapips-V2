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
        """Initialize the Node.js service met directe initialisatie zonder test"""
        try:
            logger.info("Initializing TradingView Node.js service")
            
            # Controleer of Node.js is geïnstalleerd
            try:
                process = await asyncio.create_subprocess_exec(
                    "node", "--version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=3)
                node_version = stdout.decode().strip()
                logger.info(f"Node.js version: {node_version}")
            except Exception as node_error:
                logger.error(f"Node.js not found: {str(node_error)}")
                return False
            
            # Controleer of het script bestaat
            if not os.path.exists(self.script_path):
                logger.error(f"Script niet gevonden: {self.script_path}")
                return False
            
            # DIRECTE INITIALISATIE: sla testen over
            logger.info("DIRECT INITIALIZATION: Skipping tests completely")
            self.is_initialized = True
            self.node_initialized = True 
            return True
                
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
    
    async def take_screenshot_of_url(self, url: str, fullscreen: bool = False, test_mode: bool = False) -> Optional[bytes]:
        """Take a screenshot of a URL using Node.js with optimized timeout"""
        try:
            # Als we nog niet eerder geinitialiseerd zijn, doen we dat nu
            if not self.is_initialized:
                logger.warning("Node.js service not initialized, initializing now")
                await self.initialize()
            
            # Genereer een unieke bestandsnaam voor de screenshot
            timestamp = int(time.time())
            
            # Controleer of de Docker container draait
            in_docker = os.path.exists('/app')
            
            if in_docker:
                # We zijn in Docker
                screenshot_path = f"/app/screenshot_{timestamp}.png"
                logger.info(f"Running in Docker, setting screenshot path to {screenshot_path}")
            else:
                # We zijn lokaal
                # Gebruik een pad in dezelfde directory als het script
                script_dir = os.path.dirname(os.path.abspath(__file__))
                screenshot_dir = os.path.join(script_dir, "temp_screenshots")
                os.makedirs(screenshot_dir, exist_ok=True)
                screenshot_path = os.path.join(screenshot_dir, f"screenshot_{timestamp}.png")
                logger.info(f"Running locally, setting screenshot path to {screenshot_path}")
            
            # Bereid de Node.js opdracht voor
            js_path = os.path.abspath(self.script_path)
            
            # Controleer of het pad bestaat
            if not os.path.exists(js_path):
                logger.error(f"JavaScript bestand niet gevonden op pad: {js_path}")
                # Probeer het bestand in de root van het project te vinden
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
                js_path = os.path.join(project_root, "tradingview_screenshot.js")
                if not os.path.exists(js_path):
                    logger.error(f"JavaScript bestand niet gevonden: {js_path}")
                    return None
            
            # Log het absolute pad voor debugging
            logger.info(f"Using Node.js script at: {js_path}")
            
            # Fullscreen parameter toevoegen aan opdracht
            fullscreen_param = "fullscreen" if fullscreen else ""
            if fullscreen:
                logger.info("Adding fullscreen parameter to command")
            
            # Test mode parameter toevoegen
            test_param = "test" if test_mode else ""
            
            # Stel je session ID in
            session_id = self.session_id if hasattr(self, 'session_id') and self.session_id else ""
            
            # Voer de Node.js opdracht uit met een kortere timeout
            cmd = ["node", js_path, url, screenshot_path, session_id, fullscreen_param, test_param]
            
            logger.info(f"Running command: {' '.join(cmd)}")
            
            # Voer het proces uit met een kortere timeout (15 seconden)
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Haal timeout uit class of gebruik default
            timeout = getattr(self, 'timeout', 15)
            
            # Wacht maximaal op het gespecifieerde aantal seconden
            try:
                logger.info(f"Waiting for process to complete with timeout {timeout} seconds...")
                start_time = time.time()
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                elapsed_time = time.time() - start_time
                logger.info(f"Process completed in {elapsed_time:.2f} seconds")
                
                stdout_str = stdout.decode('utf-8', errors='ignore')
                stderr_str = stderr.decode('utf-8', errors='ignore')
                
                logger.info(f"Node.js stdout: {stdout_str[:200]}...")
                if stderr_str:
                    logger.error(f"Node.js stderr: {stderr_str[:200]}...")
                
                if process.returncode != 0:
                    logger.error(f"Node.js process returned non-zero exit code: {process.returncode}")
                    return None
                
            except asyncio.TimeoutError:
                logger.error(f"Node.js process timed out after {timeout} seconds")
                process.kill()
                return None
            
            # Controleer of het bestand bestaat
            if os.path.exists(screenshot_path):
                logger.info(f"Screenshot file exists: {screenshot_path}")
                
                # Lees het bestand
                with open(screenshot_path, 'rb') as f:
                    screenshot_data = f.read()
                
                # Controleer of er data is
                if not screenshot_data or len(screenshot_data) < 1000:
                    logger.error(f"Screenshot file exists but contains no data: {screenshot_path}")
                    return None
                
                # Log de bestandsgrootte
                logger.info(f"Screenshot size: {len(screenshot_data)} bytes")
                
                # Verwijder het bestand na het lezen
                try:
                    os.remove(screenshot_path)
                    logger.info(f"Removed screenshot file after reading")
                except Exception as e:
                    logger.warning(f"Could not remove screenshot file: {str(e)}")
                
                return screenshot_data
            else:
                logger.error(f"Screenshot file not found: {screenshot_path}")
                return None
        
        except Exception as e:
            logger.error(f"Error taking screenshot with Node.js: {str(e)}")
            return None
