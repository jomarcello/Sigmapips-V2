import os
import logging
import asyncio
import json
import base64
import subprocess
import time
import hashlib
from typing import Optional, Dict, List, Any, Union
from io import BytesIO
from datetime import datetime
from trading_bot.services.chart_service.tradingview import TradingViewService

logger = logging.getLogger(__name__)

# Voeg globale browser context toe voor hergebruik
BROWSER_PROCESS = None
BROWSER_LAST_USED = 0

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
        
        # Chart links met specifieke chart IDs om sneller te laden
        self.chart_links = {
            "EURUSD": "https://www.tradingview.com/chart/xknpxpcr/",  # Snelle voorgeladen chart
            "GBPUSD": "https://www.tradingview.com/chart/jKph5b1W/",
            "USDJPY": "https://www.tradingview.com/chart/mcWuRDQv/",
            "BTCUSD": "https://www.tradingview.com/chart/NWT8AI4a/",
            "ETHUSD": "https://www.tradingview.com/chart/rVh10RLj/"
        }
        
        # Maak cache directory als deze niet bestaat
        os.makedirs('data/charts', exist_ok=True)
        
        # Voorkom onnodige node installaties door checks toe te voegen
        self._node_checked = False
        
        logger.info(f"TradingView Node.js service initialized")
    
    async def initialize(self):
        """Initialize the Node.js service"""
        try:
            logger.info("Initializing TradingView Node.js service")
            
            # Voorkom dubbel controleren
            if self._node_checked:
                logger.info("Node.js already verified, skipping checks")
                self.is_initialized = True
                return True
            
            # Controleer of Node.js is geïnstalleerd
            try:
                node_version = subprocess.check_output(["node", "--version"]).decode().strip()
                logger.info(f"Node.js version: {node_version}")
                self._node_checked = True
            except Exception as node_error:
                logger.error(f"Error checking Node.js version: {str(node_error)}")
                return False
            
            # Check if the screenshot.js file exists
            if not os.path.exists(self.script_path):
                logger.error(f"screenshot.js not found at {self.script_path}")
                return False
            
            # Gebruik minder logging
            logger.debug(f"screenshot.js found at {self.script_path}")
            
            # Playwright installatie voorbijgaan als script zelf dit doet
            # Test de Node.js service met een TradingView URL (gebruik een kort timeout)
            try:
                test_url = "https://www.tradingview.com/chart/xknpxpcr/?symbol=EURUSD&interval=1h"
                test_result = await asyncio.wait_for(
                    self.take_screenshot_of_url(test_url), 
                    timeout=15  # Maximum van 15 seconden voor de test
                )
                
                if test_result:
                    logger.info("Node.js service test successful")
                    self.is_initialized = True
                    return True
                else:
                    logger.error("Node.js service test failed")
                    return False
            except asyncio.TimeoutError:
                logger.error("Node.js service test timed out")
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
        """Take a screenshot of a URL using Node.js"""
        global BROWSER_PROCESS, BROWSER_LAST_USED
        
        try:
            # Gebruik agressieve caching voor veelvoorkomende URLs
            cache_key = f"{url}_{fullscreen}"
            url_hash = hashlib.md5(cache_key.encode()).hexdigest()
            
            cache_path = os.path.join('data/charts', f"cached_{url_hash}.png")
            
            # Zeer kort TTL voor debug, normaal gebruiken we een hogere waarde
            cache_ttl = 300  # 5 minuten in seconden (standaard)
            
            # Check voor instrument-specifieke TTLs
            if "EURUSD" in url:
                cache_ttl = 600  # 10 minuten voor EURUSD
            elif "BTCUSD" in url:
                cache_ttl = 180  # 3 minuten voor crypto (meer volatiel)
            
            # Check of we een recente cache-hit hebben
            if os.path.exists(cache_path):
                file_age = time.time() - os.path.getmtime(cache_path)
                if file_age < cache_ttl:
                    logger.info(f"Using cached screenshot ({int(file_age)}s old) for {url}")
                    with open(cache_path, 'rb') as f:
                        return f.read()
                else:
                    logger.info(f"Cached screenshot expired for {url}")
            
            # Genereer een unieke bestandsnaam voor de screenshot
            timestamp = int(time.time())
            screenshot_path = os.path.join(os.path.dirname(self.script_path), f"screenshot_{timestamp}.png")
            
            # Zorg ervoor dat de URL geen aanhalingstekens bevat
            url = url.strip('"\'')
            
            # Voeg fullscreen en andere parameters toe aan URL
            if "tradingview.com" in url:
                # Alle parameters op één plaats toevoegen
                if "?" in url:
                    # URL heeft al parameters
                    if "fullscreen=true" not in url:
                        url += "&fullscreen=true&hide_side_toolbar=true&hide_top_toolbar=true"
                else:
                    # URL heeft nog geen parameters
                    url += "?fullscreen=true&hide_side_toolbar=true&hide_top_toolbar=true"
                
                # Voeg nog meer parameters toe om de pagina sneller te laden
                if "&theme=" not in url and "?theme=" not in url:
                    url += "&theme=dark&toolbar_bg=dark"
                
                # Voorkom hotlist en andere vertragende elementen
                url += "&hotlist=false&calendar=false"
            
            # Loggen voor debug
            logger.info(f"Taking screenshot with Node.js service: {url}")
            
            # Kill eerder browser proces als het te lang inactief is geweest (2 minuten)
            if BROWSER_PROCESS and (time.time() - BROWSER_LAST_USED) > 120:
                try:
                    logger.info("Killing stale browser process")
                    BROWSER_PROCESS.kill()
                    BROWSER_PROCESS = None
                except:
                    pass
            
            # Bouw het Node.js commando met browser hergebruik
            cmd = f"node {self.script_path} \"{url}\" \"{screenshot_path}\" \"{self.session_id}\""
            
            # Voeg fullscreen parameter toe indien nodig
            if fullscreen:
                cmd += " fullscreen"
                logger.info("Taking screenshot with fullscreen=True")
            
            # Verwijder eventuele puntkomma's uit het commando
            cmd = cmd.replace(";", "")
            
            # Start tijd meting
            start_time = time.time()
            
            # Voer het commando uit
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            BROWSER_PROCESS = process
            BROWSER_LAST_USED = time.time()
            
            try:
                # Wacht maximaal 20 seconden (korter dan voorheen)
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
            except asyncio.TimeoutError:
                logger.error("Screenshot process timed out after 20 seconds")
                process.kill()
                BROWSER_PROCESS = None
                return None
            
            # Update last usage time
            BROWSER_LAST_USED = time.time()
            
            # Controleer of het bestand bestaat
            if os.path.exists(screenshot_path):
                # Lees het bestand
                with open(screenshot_path, 'rb') as f:
                    screenshot_bytes = f.read()
                
                # Cache het resultaat voor later
                try:
                    with open(cache_path, 'wb') as f:
                        f.write(screenshot_bytes)
                except Exception as cache_error:
                    logger.error(f"Error caching screenshot: {str(cache_error)}")
                
                # Probeer het originele screenshot bestand te verwijderen
                try:
                    os.remove(screenshot_path)
                except:
                    pass
                
                # Log de tijd die het nam
                duration = time.time() - start_time
                logger.info(f"Screenshot taken successfully with Node.js in {duration:.2f}s")
                
                return screenshot_bytes
            else:
                logger.error(f"Screenshot file not found at {screenshot_path}")
                
                # Controleer stderr voor errors
                if stderr:
                    stderr_text = stderr.decode()
                    logger.error(f"Node.js stderr: {stderr_text}")
                
                return None
                
        except Exception as e:
            logger.error(f"Error taking screenshot with Node.js: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
