import os
import logging
import asyncio
import json
import base64
import subprocess
import time
import hashlib
import tempfile
import shutil
import select
import threading
import multiprocessing
from typing import Optional, Dict, List, Any, Union
from io import BytesIO
from datetime import datetime, timedelta
from trading_bot.services.chart_service.tradingview import TradingViewService
import aiofiles
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger(__name__)

# Configuratie instellingen
MAX_SCREENSHOT_RETRIES = 3  # Aantal keer dat we een screenshot opnieuw proberen
SCREENSHOT_TIMEOUT = 30      # Timeout voor elke screenshot poging (seconden)
CACHE_DIR = os.path.join(tempfile.gettempdir(), "tradingview_cache")
CACHE_TTL = 600              # Standaard cache tijd (seconden)
USE_BROWSER_REUSE = True     # Browser hergebruik inschakelen
BROWSER_LIFETIME = 300       # Maximum levensduur van een hergebruikte browser (seconden)
BROWSER_THROTTLE_DELAY = 0.2  # seconden
MAX_CONCURRENT_SCREENSHOTS = 3  # maximum parallel screenshot processes
MAX_RETRIES = 3  # maximum number of retries for failed screenshots

# Globale variabelen voor browserhergebruik
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
        
        # Gebruik het absolute pad naar het script in de hoofdmap
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        self.script_path = os.path.join(root_dir, "tradingview_screenshot.js")
        
        # Log het pad voor debugging
        logger.info(f"Using script path: {self.script_path}")
        
        # Controleer of het script bestaat
        if not os.path.exists(self.script_path):
            logger.error(f"Script niet gevonden op {self.script_path}")
            # Zoek het script in de huidige directory als fallback
            current_dir = os.getcwd()
            fallback_path = os.path.join(current_dir, "tradingview_screenshot.js")
            if os.path.exists(fallback_path):
                logger.info(f"Script gevonden op fallback locatie: {fallback_path}")
                self.script_path = fallback_path
            else:
                logger.error(f"Script ook niet gevonden op fallback locatie: {fallback_path}")
                # Laatste poging - zoek in alle subdirectories
                possible_paths = []
                for root, dirs, files in os.walk(current_dir):
                    if "tradingview_screenshot.js" in files:
                        possible_path = os.path.join(root, "tradingview_screenshot.js")
                        possible_paths.append(possible_path)
                        logger.info(f"Script gevonden in: {possible_path}")
                
                if possible_paths:
                    self.script_path = possible_paths[0]
                    logger.info(f"Using script at: {self.script_path}")
        
        # Chart links met specifieke chart IDs om sneller te laden
        self.chart_links = {
            "EURUSD": "https://www.tradingview.com/chart/xknpxpcr/",  # Specifieke chart ID
            "GBPUSD": "https://www.tradingview.com/chart/jKph5b1W/",
            "USDJPY": "https://www.tradingview.com/chart/mcWuRDQv/",
            "BTCUSD": "https://www.tradingview.com/chart/NWT8AI4a/",
            "ETHUSD": "https://www.tradingview.com/chart/rVh10RLj/"
        }
        
        # Maak cache directories
        os.makedirs('data/charts', exist_ok=True)
        os.makedirs('data/cache', exist_ok=True)
        
        # Zorg ervoor dat de cache directories absoluut zijn
        self.cache_dir = os.path.join(os.getcwd(), 'data/charts')
        
        # Voorkom onnodige Node.js checks
        self._node_checked = False
        
        # Cache voor snel hergebruik
        self._charts_cache = {}
        
        # Executor voor parallelle verwerking
        self._executor = ThreadPoolExecutor(max_workers=os.cpu_count())
        
        # Semaphore voor het beperken van gelijktijdige processen
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_SCREENSHOTS)
        
        # In-memory cache voor veelgebruikte screenshots  
        self._memory_cache = {}
        
        # Clean up old cache files
        asyncio.create_task(self._cleanup_cache())
        
        logger.info(f"TradingView Node.js service initialized")
    
    async def initialize(self):
        """Initialize the Node.js service with retry logic"""
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
            
            # Implementeer retry mechanisme voor testen
            max_retries = 2
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    logger.info(f"Testing Node.js service (attempt {retry_count + 1}/{max_retries})")
                    
                    # Gebruik een zeer eenvoudige test URL
                    test_url = "https://www.tradingview.com/chart/xknpxpcr/?symbol=EURUSD&interval=1h"
                    
                    # Kortere timeout voor test (maar niet te kort)
                    test_result = await asyncio.wait_for(
                        self.take_screenshot_of_url(test_url), 
                        timeout=15  # 15 seconden voor de test
                    )
                    
                    if test_result:
                        logger.info("Node.js service test successful")
                        self.is_initialized = True
                        return True
                    else:
                        logger.warning(f"Node.js test returned no data (attempt {retry_count + 1})")
                        retry_count += 1
                
                except asyncio.TimeoutError:
                    logger.warning(f"Node.js service test timed out (attempt {retry_count + 1})")
                    retry_count += 1
                except Exception as test_error:
                    logger.error(f"Error testing Node.js service: {str(test_error)}")
                    retry_count += 1
            
            logger.error(f"Node.js service failed after {max_retries} attempts")
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
        global BROWSER_PROCESS
        
        # Kill openstaand browser proces
        if BROWSER_PROCESS:
            try:
                logger.info("Cleaning up browser process")
                BROWSER_PROCESS.kill()
                BROWSER_PROCESS = None
            except:
                pass
        
        # Sluit executor
        self._executor.shutdown(wait=False)
        
        # Verwijder oude cache bestanden
        try:
            now = time.time()
            for filename in os.listdir(CACHE_DIR):
                filepath = os.path.join(CACHE_DIR, filename)
                if os.path.isfile(filepath):
                    file_age = now - os.path.getmtime(filepath)
                    if file_age > (CACHE_TTL * 2):  # Verwijder bestanden die 2x ouder zijn dan TTL
                        os.remove(filepath)
        except Exception as e:
            logger.warning(f"Error cleaning up cache: {str(e)}")
        
        logger.info("TradingView Node.js service cleaned up")
    
    async def take_screenshot_of_url(self, url: str, fullscreen: bool = False) -> Optional[bytes]:
        """Take a screenshot of a URL using Node.js with improved reliability"""
        global BROWSER_PROCESS, BROWSER_LAST_USED
        
        start_time = time.time()
        logger.info(f"Taking screenshot with Node.js: {url[:80]}...")
        
        try:
            # Debug: Controleer of het script bestaat
            if not os.path.exists(self.script_path):
                logger.error(f"CRITICAL ERROR: Script not found at path: {self.script_path}")
                return None
            else:
                logger.info(f"Using script at: {self.script_path} (file exists)")
            
            # Debug: Controleer cache directory
            if not os.path.exists(self.cache_dir):
                logger.error(f"CRITICAL ERROR: Cache directory does not exist: {self.cache_dir}")
                try:
                    os.makedirs(self.cache_dir, exist_ok=True)
                    logger.info(f"Created cache directory: {self.cache_dir}")
                except Exception as e:
                    logger.error(f"Failed to create cache directory: {str(e)}")
                    return None
            else:
                logger.info(f"Cache directory exists: {self.cache_dir}")
            
            # Voeg force-refresh parameter toe voor frisse charts
            if '?' in url:
                url += '&forceRefresh=' + str(int(time.time()))
            else:
                url += '?forceRefresh=' + str(int(time.time()))
            
            # Gebruik agressieve caching voor veelvoorkomende URLs
            cache_key = f"{url}_{fullscreen}"
            url_hash = hashlib.md5(cache_key.encode()).hexdigest()
            
            # Zorg ervoor dat de cache directory absoluut is
            cache_path = os.path.join(self.cache_dir, f"cached_{url_hash}.png")
            logger.info(f"Cache path: {cache_path}")
            
            # Bepaal cache TTL afhankelijk van het instrument
            cache_ttl = CACHE_TTL  # Default 5 minuten
            
            # Check instrument-specifieke TTLs
            if "EURUSD" in url:
                cache_ttl = 600  # 10 minuten voor EURUSD
            elif "BTCUSD" in url:
                cache_ttl = 180  # 3 minuten voor crypto (meer volatiel)
            
            # Check of we een recente cache-hit hebben
            if os.path.exists(cache_path):
                file_age = time.time() - os.path.getmtime(cache_path)
                if file_age < cache_ttl:
                    logger.info(f"Using cached screenshot ({int(file_age)}s old) for {url[:50]}...")
                    with open(cache_path, 'rb') as f:
                        # Wacht kort om overbelasting te voorkomen (simuleer netwerkvertraging)
                        await asyncio.sleep(BROWSER_THROTTLE_DELAY)
                        return f.read()
                else:
                    logger.info(f"Cached screenshot expired ({int(file_age)}s old)")
            
            # Implementeer retry logic
            max_retries = MAX_RETRIES
            retry_count = 0
            last_error = None
            
            while retry_count < max_retries:
                try:
                    # Genereer een unieke bestandsnaam in de temp directory
                    fd, screenshot_path = tempfile.mkstemp(suffix='.png')
                    os.close(fd)  # We need only the path
                    logger.info(f"Temporary screenshot path: {screenshot_path}")
                    
                    # Voorbereid URL, verwijder aanhalingstekens
                    url = url.strip('"\'')
                    
                    # Voeg TradingView specifieke parameters toe
                    if "tradingview.com" in url:
                        # Voeg alle parameters toe op één plaats
                        query_params = [
                            "fullscreen=true",
                            "hide_side_toolbar=true",
                            "hide_top_toolbar=true",
                            "hide_legend=true",
                            "theme=dark",
                            "toolbar_bg=dark",
                            "hotlist=false",
                            "calendar=false"
                        ]
                        
                        if "?" in url:
                            # URL heeft al parameters
                            for param in query_params:
                                if param.split('=')[0] not in url:
                                    url += f"&{param}"
                        else:
                            # URL heeft nog geen parameters
                            url += "?" + "&".join(query_params)
                    
                    # Debug: Toon de volledige URL
                    logger.info(f"Final URL for screenshot: {url}")
                    
                    # Kill eerder browser proces als het te lang inactief is geweest
                    if BROWSER_PROCESS and USE_BROWSER_REUSE:
                        if (time.time() - BROWSER_LAST_USED) > BROWSER_LIFETIME:
                            try:
                                logger.info("Killing stale browser process")
                                BROWSER_PROCESS.kill()
                                BROWSER_PROCESS = None
                            except:
                                pass
                    
                    # Bouw het Node.js commando
                    cmd = f"node {self.script_path} \"{url}\" \"{screenshot_path}\" \"{self.session_id}\""
                    
                    # Voeg fullscreen parameter toe indien nodig
                    if fullscreen:
                        cmd += " fullscreen"
                    
                    logger.info(f"Running command: {cmd}")
                    
                    # Spawn het Node.js proces met timeout
                    process = await asyncio.create_subprocess_shell(
                        cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    
                    # Sla process op voor hergebruik
                    if USE_BROWSER_REUSE:
                        BROWSER_PROCESS = process
                        BROWSER_LAST_USED = time.time()
                    
                    try:
                        # Wacht op proces met timeout
                        stdout, stderr = await asyncio.wait_for(
                            process.communicate(), 
                            timeout=SCREENSHOT_TIMEOUT
                        )
                        
                        # Debug: Log stdout en stderr
                        if stdout:
                            logger.info(f"Process stdout: {stdout.decode()[:500]}")
                        if stderr:
                            logger.error(f"Process stderr: {stderr.decode()[:500]}")
                        
                        # Update last usage time
                        if USE_BROWSER_REUSE:
                            BROWSER_LAST_USED = time.time()
                        
                        # Debug: Controleer bestandsgrootte
                        if os.path.exists(screenshot_path):
                            file_size = os.path.getsize(screenshot_path)
                            logger.info(f"Screenshot file size: {file_size} bytes")
                        else:
                            logger.error(f"Screenshot file does not exist: {screenshot_path}")
                        
                        # Als het bestand bestaat en niet leeg is, gebruik het
                        if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 100:
                            with open(screenshot_path, 'rb') as f:
                                screenshot_bytes = f.read()
                            
                            # Sla het resultaat op in cache voor hergebruik
                            try:
                                with open(cache_path, 'wb') as f:
                                    f.write(screenshot_bytes)
                                logger.info(f"Saved screenshot to cache: {cache_path}")
                            except Exception as cache_error:
                                logger.warning(f"Error caching screenshot: {str(cache_error)}")
                            
                            # Verwijder tijdelijk bestand
                            try:
                                os.remove(screenshot_path)
                            except:
                                pass
                            
                            # Log succes
                            duration = time.time() - start_time
                            logger.info(f"Screenshot taken successfully in {duration:.1f}s")
                            
                            return screenshot_bytes
                        else:
                            # Bestand bestaat niet of is leeg
                            logger.warning(f"Screenshot file empty or missing: {screenshot_path}")
                            
                            # Controleer stderr voor errors
                            if stderr:
                                stderr_text = stderr.decode()
                                if any(error in stderr_text for error in ['Error:', 'ECONNREFUSED', 'failed', 'timeout']):
                                    logger.error(f"Node.js error: {stderr_text[:200]}")
                                    last_error = stderr_text
                            
                            retry_count += 1
                            continue
                            
                    except asyncio.TimeoutError:
                        logger.warning(f"Screenshot process timed out after {SCREENSHOT_TIMEOUT}s (attempt {retry_count + 1})")
                        
                        # Opruimen van processen bij timeout
                        try:
                            if process and process.returncode is None:
                                logger.warning("Force terminating stuck Node.js process")
                                process.kill()
                                
                                if USE_BROWSER_REUSE:
                                    BROWSER_PROCESS = None
                        except:
                            pass
                        
                        last_error = f"Timeout after {SCREENSHOT_TIMEOUT}s"
                        retry_count += 1
                        continue
                
                except Exception as e:
                    logger.error(f"Error in screenshot process: {str(e)}")
                    last_error = str(e)
                    retry_count += 1
                
                finally:
                    # Zorg altijd voor opruimen van temp bestand indien aanwezig
                    if 'screenshot_path' in locals() and os.path.exists(screenshot_path):
                        try:
                            os.remove(screenshot_path)
                        except:
                            pass
                
                # Wacht kort voor volgende poging (exponential backoff)
                if retry_count < max_retries:
                    wait_time = 0.5 * (2 ** retry_count)  # 1s, 2s, 4s
                    logger.info(f"Retrying screenshot in {wait_time:.1f}s...")
                    await asyncio.sleep(wait_time)
            
            # Na alle pogingen, check of we een cachekopie hebben als fallback
            if os.path.exists(cache_path):
                logger.warning("Using outdated cache as fallback after failed attempts")
                with open(cache_path, 'rb') as f:
                    return f.read()
            
            # Als hier, alle pogingen mislukt
            logger.error(f"Failed to take screenshot after {max_retries} attempts: {last_error}")
            return None
            
        except Exception as e:
            logger.error(f"Fatal error taking screenshot: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    @lru_cache(maxsize=100)
    def _get_cache_path(self, url: str, fullscreen: bool = False) -> str:
        """
        Generate a unique cache path for a URL and fullscreen setting
        
        Args:
            url: TradingView chart URL
            fullscreen: Whether the screenshot is in fullscreen mode
        
        Returns:
            Path to the cached screenshot file
        """
        # Create a unique hash based on URL and fullscreen setting
        url_hash = hashlib.md5(f"{url}_{fullscreen}_{self.session_id}".encode()).hexdigest()
        return os.path.join('data/charts', f"{url_hash}.png")

    async def _is_cache_valid(self, cache_path: str) -> bool:
        """
        Check if a cached screenshot is still valid (not expired)
        
        Args:
            cache_path: Path to the cached screenshot
            
        Returns:
            True if the cache is valid, False otherwise
        """
        try:
            if not os.path.exists(cache_path):
                return False
                
            # Check file modification time
            mtime = os.path.getmtime(cache_path)
            age = datetime.now().timestamp() - mtime
            return age < CACHE_TTL
        except Exception as e:
            logger.warning(f"Error checking cache validity: {e}")
            return False

    async def batch_take_screenshots(self, urls: List[str], output_dir: str = None, 
                                     fullscreen: bool = False, force_refresh: bool = False) -> Dict[str, str]:
        """
        Take multiple screenshots in parallel
        
        Args:
            urls: List of TradingView chart URLs
            output_dir: Directory to save the screenshots (optional)
            fullscreen: Whether to take fullscreen screenshots
            force_refresh: Force refresh the cache
            
        Returns:
            Dictionary mapping URLs to screenshot paths
        """
        tasks = []
        results = {}
        
        for url in urls:
            output_path = None
            if output_dir:
                # Generate a filename based on the URL
                url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
                output_path = os.path.join(output_dir, f"{url_hash}.png")
                
            # Create task for each URL
            task = asyncio.create_task(
                self.take_screenshot(
                    url=url,
                    output_path=output_path,
                    fullscreen=fullscreen,
                    force_refresh=force_refresh
                )
            )
            tasks.append((url, task))
        
        # Wait for all tasks to complete
        for url, task in tasks:
            try:
                screenshot_path = await task
                results[url] = screenshot_path
            except Exception as e:
                logger.error(f"Error taking screenshot for {url}: {e}")
                results[url] = None
        
        return results

    async def _cleanup_cache(self) -> None:
        """Clean up old cache files that exceed twice the cache TTL"""
        try:
            now = datetime.now().timestamp()
            for filename in os.listdir('data/charts'):
                file_path = os.path.join('data/charts', filename)
                if os.path.isfile(file_path) and filename.endswith('.png'):
                    mtime = os.path.getmtime(file_path)
                    age = now - mtime
                    # Remove files older than 2x cache TTL
                    if age > (CACHE_TTL * 2):
                        try:
                            os.remove(file_path)
                            logger.debug(f"Removed old cache file: {file_path}")
                        except Exception as e:
                            logger.warning(f"Failed to remove old cache file {file_path}: {e}")
        except Exception as e:
            logger.warning(f"Error during cache cleanup: {e}")

    async def __aenter__(self):
        """Context manager support"""
        await self.initialize()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup"""
        self.cleanup()
