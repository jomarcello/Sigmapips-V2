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
        
        # Voeg caching toe om herhaald screenshot van dezelfde URL te vermijden
        self.screenshot_cache = {}
        self.cache_expiry = 60  # 60 seconden cache tijd
        
        logger.info(f"TradingView Node.js service initialized")
    
    async def initialize(self):
        """Initialize the Node.js service"""
        try:
            logger.info("Initializing TradingView Node.js service")
            
            # Controleer of het screenshot.js bestand bestaat
            if not os.path.exists(self.script_path):
                logger.error(f"screenshot.js not found at {self.script_path}")
                return False
            
            logger.info(f"screenshot.js found at {self.script_path}")
            
            # We slaan de Node.js en Playwright controle over om tijd te besparen
            # Die wordt automatisch geïnstalleerd indien nodig door het script
            
            # Markeer als geïnitialiseerd
            self.is_initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Error initializing TradingView Node.js service: {str(e)}")
            return False
    
    async def take_screenshot(self, symbol, timeframe=None, fullscreen=False):
        """Take a screenshot of a chart"""
        try:
            logger.info(f"Taking screenshot for {symbol} on {timeframe} timeframe (fullscreen: {fullscreen})")
            
            # Normaliseer het symbool (verwijder / en converteer naar hoofdletters)
            normalized_symbol = symbol.replace("/", "").upper()
            
            # Bouw de cache key
            cache_key = f"{normalized_symbol}_{timeframe}_{fullscreen}"
            
            # Controleer of we een recente screenshot in cache hebben
            current_time = time.time()
            if cache_key in self.screenshot_cache:
                cache_time, screenshot_data = self.screenshot_cache[cache_key]
                if current_time - cache_time < self.cache_expiry:
                    logger.info(f"Using cached screenshot for {symbol} (age: {int(current_time - cache_time)}s)")
                    return screenshot_data
            
            # Bouw de chart URL
            chart_url = self.chart_links.get(normalized_symbol)
            if not chart_url:
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
                # Cache het resultaat
                self.screenshot_cache[cache_key] = (current_time, screenshot_bytes)
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
        try:
            # Genereer een unieke bestandsnaam voor de screenshot
            timestamp = int(time.time())
            screenshot_path = os.path.join(os.path.dirname(self.script_path), f"screenshot_{timestamp}.png")
            
            # Zorg ervoor dat de URL geen aanhalingstekens bevat
            url = url.strip('"\'')
            
            # Debug logging
            logger.info(f"Taking screenshot with fullscreen={fullscreen}")
            
            # Controleer of de URL naar TradingView verwijst
            if "tradingview.com" in url:
                logger.info(f"Taking screenshot of TradingView URL: {url}")
            else:
                logger.warning(f"URL is not a TradingView URL: {url}")
            
            # Bouw het commando
            cmd = f"node {self.script_path} \"{url}\" \"{screenshot_path}\" \"{self.session_id}\""
            
            # Voeg fullscreen parameter toe als dat nodig is
            if fullscreen:
                cmd += " fullscreen"
                logger.info("Adding fullscreen parameter to command")
            
            # Verwijder eventuele puntkomma's uit het commando
            cmd = cmd.replace(";", "")
            
            # Log het commando zonder de session ID te tonen
            masked_cmd = cmd.replace(self.session_id, '****')
            logger.info(f"Running command: {masked_cmd}")
            
            # Gebruik een kortere timeout
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Wacht maximaal 30 seconden op voltooiing (was voorheen onbeperkt)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
                
                # Log de output
                if stdout:
                    logger.info(f"Node.js stdout: {stdout.decode()}")
                if stderr:
                    stderr_text = stderr.decode()
                    # Alleen echte fouten loggen, niet de waarschuwingen
                    if "error:" in stderr_text.lower():
                        logger.error(f"Node.js stderr: {stderr_text}")
                    else:
                        logger.info(f"Node.js stderr: {stderr_text}")
                
                # Controleer of het bestand bestaat
                if os.path.exists(screenshot_path):
                    # Lees het bestand
                    with open(screenshot_path, 'rb') as f:
                        screenshot_data = f.read()
                    
                    # Verwijder het bestand
                    os.remove(screenshot_path)
                    
                    # Log de grootte van de screenshot
                    logger.info(f"Screenshot size: {len(screenshot_data) / 1024:.1f} KB")
                    
                    return screenshot_data
                else:
                    logger.error(f"Screenshot file not found: {screenshot_path}")
                    return None
                    
            except asyncio.TimeoutError:
                # Kill het proces als het te lang duurt
                logger.error("Screenshot process timed out after 30 seconds, killing it")
                try:
                    process.kill()
                except:
                    pass
                
                # Controleer of we toch een screenshot hebben
                if os.path.exists(screenshot_path):
                    with open(screenshot_path, 'rb') as f:
                        screenshot_data = f.read()
                    os.remove(screenshot_path)
                    return screenshot_data
                return None
        
        except Exception as e:
            logger.error(f"Error taking screenshot with Node.js: {str(e)}")
            return None
