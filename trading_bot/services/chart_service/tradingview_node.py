import os
import logging
import asyncio
import json
import base64
import subprocess
import time
import re
from typing import Optional, Dict, List, Any, Union
from io import BytesIO
from datetime import datetime, timedelta
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
        
        # Verbeterde scriptpad detectie
        project_root = self._detect_project_root()
        self.script_path = os.path.join(project_root, "tradingview_screenshot.js")
        
        # Cache voor recente screenshots
        self.screenshot_cache = {}
        self.cache_ttl = 60  # Hoeveel seconden een screenshot in de cache blijft
        
        # Chart links voor verschillende symbolen
        self.chart_links = {
            "EURUSD": "https://www.tradingview.com/chart/?symbol=EURUSD",
            "GBPUSD": "https://www.tradingview.com/chart/?symbol=GBPUSD",
            "BTCUSD": "https://www.tradingview.com/chart/?symbol=BTCUSD",
            "ETHUSD": "https://www.tradingview.com/chart/?symbol=ETHUSD"
        }
        
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"TradingView Node.js service initialized")
    
    def _detect_project_root(self):
        """Verbeterde detectie van het project root pad met fallbacks"""
        # Optie 1: Normaal pad met directory traversal 
        dir_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        
        # Controleer of script bestaat in deze directory
        if os.path.exists(os.path.join(dir_path, "tradingview_screenshot.js")):
            return dir_path
        
        # Optie 2: Gebruik het huidige werkdirectory
        cwd = os.getcwd()
        if os.path.exists(os.path.join(cwd, "tradingview_screenshot.js")):
            return cwd
        
        # Optie 3: Zoek in bovenliggende mappen
        current_dir = os.path.dirname(__file__)
        for _ in range(5):  # Zoek maximaal 5 levels omhoog
            if os.path.exists(os.path.join(current_dir, "tradingview_screenshot.js")):
                return current_dir
            current_dir = os.path.dirname(current_dir)
        
        # Fallback naar het originele pad
        return dir_path
    
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
            
            # Check if the screenshot.js file exists
            if not os.path.exists(self.script_path):
                # Probeer een alternatief pad
                alt_script_path = os.path.join(os.path.dirname(__file__), "screenshot.js")
                if os.path.exists(alt_script_path):
                    self.script_path = alt_script_path
                    logger.info(f"Using alternative screenshot.js found at {alt_script_path}")
                else:
                    logger.error(f"screenshot.js not found at {self.script_path} or {alt_script_path}")
                    return False
            
            logger.info(f"screenshot.js found at {self.script_path}")
            
            # Versneld - skip test bij initialisatie, dit bespaart significante tijd
            self.is_initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Error initializing TradingView Node.js service: {str(e)}")
            return False
    
    async def take_screenshot(self, symbol, timeframe=None, fullscreen=False):
        """Take a screenshot of a chart"""
        try:
            if not self.is_initialized:
                await self.initialize()
                
            # Normaliseer het symbool (verwijder / en converteer naar hoofdletters)
            normalized_symbol = symbol.replace("/", "").upper()
            
            # Bouw de cache key
            cache_key = f"{normalized_symbol}_{timeframe}_{fullscreen}"
            
            # Check cache first
            if cache_key in self.screenshot_cache:
                cache_entry = self.screenshot_cache[cache_key]
                age = time.time() - cache_entry['timestamp']
                if age < self.cache_ttl:
                    logger.info(f"Using cached screenshot for {symbol} ({timeframe})")
                    return cache_entry['data']
            
            # Bouw de chart URL
            chart_url = self.chart_links.get(normalized_symbol)
            if not chart_url:
                chart_url = f"https://www.tradingview.com/chart/?symbol={normalized_symbol}"
                if timeframe:
                    tv_interval = self.interval_map.get(timeframe, "D")
                    chart_url += f"&interval={tv_interval}"
            
            # Gebruik de take_screenshot_of_url methode om de screenshot te maken
            screenshot_bytes = await self.take_screenshot_of_url(chart_url, fullscreen=fullscreen)
            
            if screenshot_bytes:
                # Cache de screenshot
                self.screenshot_cache[cache_key] = {
                    'data': screenshot_bytes,
                    'timestamp': time.time()
                }
                
                # Verwijder oude cache items
                self._clean_cache()
                
                return screenshot_bytes
            else:
                logger.error(f"Failed to take screenshot for {symbol}")
                return None
            
        except Exception as e:
            logger.error(f"Error taking screenshot: {str(e)}")
            return None
    
    def _clean_cache(self):
        """Verwijder oude items uit de cache"""
        now = time.time()
        keys_to_remove = []
        
        for key, entry in self.screenshot_cache.items():
            if now - entry['timestamp'] > self.cache_ttl:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.screenshot_cache[key]
    
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
        self.screenshot_cache.clear()
    
    async def take_screenshot_of_url(self, url: str, fullscreen: bool = False) -> Optional[bytes]:
        """Take a screenshot of a URL using Node.js"""
        try:
            # Check cache first - URL-based cache
            cache_key = f"{url}_{fullscreen}"
            if cache_key in self.screenshot_cache:
                cache_entry = self.screenshot_cache[cache_key]
                age = time.time() - cache_entry['timestamp']
                if age < self.cache_ttl:
                    return cache_entry['data']
                    
            # Genereer een unieke bestandsnaam voor de screenshot
            timestamp = int(time.time())
            screenshot_path = os.path.join(os.path.dirname(self.script_path), f"screenshot_{timestamp}.png")
            
            # Zorg ervoor dat de URL geen aanhalingstekens bevat
            url = url.strip('"\'')
            
            # Schakel fullscreen in door de parameter direct aan de URL toe te voegen
            # Dit is efficiënter dan twee parameters doorgeven
            if fullscreen and "fullscreen=true" not in url:
                if "?" in url:
                    url += "&fullscreen=true"
                else:
                    url += "?fullscreen=true"
            
            # Bouw het commando
            cmd = f"node {self.script_path} \"{url}\" \"{screenshot_path}\" \"{self.session_id}\""
            
            # Beperkte logging voor snelheid
            logger.debug(f"Running command with url: {url}")
            
            # Start het proces met een timeout
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Gebruik een timeout om te voorkomen dat het proces te lang blijft hangen
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.error("Node.js process timed out after 30 seconds, killing it")
                process.kill()
                return None
            
            # Verminderde logging voor betere prestaties, alleen bij error niveaus
            if process.returncode != 0 and stderr:
                logger.error(f"Node.js stderr: {stderr.decode()}")
            
            # Controleer of het bestand bestaat
            if os.path.exists(screenshot_path):
                # Lees het bestand
                with open(screenshot_path, 'rb') as f:
                    screenshot_data = f.read()
                
                # Verwijder het bestand
                os.remove(screenshot_path)
                
                # Cache het resultaat
                self.screenshot_cache[cache_key] = {
                    'data': screenshot_data,
                    'timestamp': time.time()
                }
                
                return screenshot_data
            else:
                logger.error(f"Screenshot file not found: {screenshot_path}")
                return None
        
        except Exception as e:
            logger.error(f"Error taking screenshot with Node.js: {str(e)}")
            return None
