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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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
        self.executor = ThreadPoolExecutor(max_workers=2)  # Beperk het aantal parallelle processen
        
        # Get the project root directory and set the correct script path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        self.script_dir = os.path.dirname(__file__)
        self.screenshot_js_path = os.path.join(self.script_dir, "screenshot.js")
        
        # Controleer de Node.js installatie en maak al een cache-map aan
        self._ensure_cache_dir()
        
        # Chart links voor verschillende symbolen
        self.chart_links = {
            "EURUSD": "https://www.tradingview.com/chart/?symbol=OANDA:EURUSD",
            "GBPUSD": "https://www.tradingview.com/chart/?symbol=OANDA:GBPUSD",
            "USDJPY": "https://www.tradingview.com/chart/?symbol=OANDA:USDJPY",
            "BTCUSD": "https://www.tradingview.com/chart/?symbol=BITSTAMP:BTCUSD",
            "ETHUSD": "https://www.tradingview.com/chart/?symbol=BITSTAMP:ETHUSD"
        }
        
        logger.info(f"TradingView Node.js service initialized")
    
    def _ensure_cache_dir(self):
        """Zorg ervoor dat de cache-map bestaat"""
        self.cache_dir = os.path.join(self.script_dir, "screenshot_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        return self.cache_dir
    
    async def initialize(self):
        """Initialize the Node.js service"""
        try:
            logger.info("Initializing TradingView Node.js service")
            
            # Controleer of Node.js is geïnstalleerd
            try:
                # Gebruik asyncio voor de subprocess om blokkering te voorkomen
                proc = await asyncio.create_subprocess_exec(
                    "node", "--version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                node_version = stdout.decode().strip()
                logger.info(f"Node.js version: {node_version}")
            except Exception as node_error:
                logger.error(f"Error checking Node.js version: {str(node_error)}")
                return False
            
            # Controleer of screenshot.js bestaat, zo niet maak het aan
            if not os.path.exists(self.screenshot_js_path):
                logger.warning(f"screenshot.js not found at {self.screenshot_js_path}, creating from tradingview_screenshot.js")
                # Kopieer de tradingview_screenshot.js naar screenshot.js
                try:
                    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
                    source_js = os.path.join(project_root, "tradingview_screenshot.js")
                    if os.path.exists(source_js):
                        with open(source_js, 'r') as src:
                            with open(self.screenshot_js_path, 'w') as dst:
                                dst.write(src.read())
                        logger.info(f"Created screenshot.js from tradingview_screenshot.js")
                    else:
                        logger.error(f"tradingview_screenshot.js not found at {source_js}")
                        return False
                except Exception as e:
                    logger.error(f"Error creating screenshot.js: {str(e)}")
                    return False
            
            # Voer een snelle test uit voor playwright module
            try:
                node_cmd = f"node -e \"try {{ require.resolve('playwright'); console.log('installed'); }} catch(e) {{ console.log('not-installed'); }}\""
                result = subprocess.run(node_cmd, shell=True, capture_output=True, text=True)
                if 'not-installed' in result.stdout:
                    logger.info("Playwright not found, installation will be triggered when needed")
                else:
                    logger.info("Playwright already installed")
            except Exception as e:
                logger.warning(f"Could not check Playwright installation: {str(e)}")
            
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
            
            # Bouw de chart URL
            chart_url = self.chart_links.get(normalized_symbol)
            if not chart_url:
                # Gebruik een vooraf ingestelde correcte TradingView URL-structuur met broker
                if "USD" in normalized_symbol:
                    # Voor forex paren, gebruik OANDA als broker
                    chart_url = f"https://www.tradingview.com/chart/?symbol=OANDA:{normalized_symbol}"
                elif normalized_symbol.startswith("BTC") or normalized_symbol.startswith("ETH"):
                    # Voor crypto, gebruik Bitstamp als broker
                    chart_url = f"https://www.tradingview.com/chart/?symbol=BITSTAMP:{normalized_symbol}"
                else:
                    # Voor andere instrumenten
                    chart_url = f"https://www.tradingview.com/chart/?symbol={normalized_symbol}"
            
            # Voeg timeframe toe indien gespecificeerd
            if timeframe:
                tv_interval = self.interval_map.get(timeframe, "D")
                if "?" in chart_url:
                    chart_url += f"&interval={tv_interval}"
                else:
                    chart_url += f"?interval={tv_interval}"
            
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
        """Capture multiple charts in parallel"""
        if not self.is_initialized:
            await self.initialize()
        
        if not symbols:
            symbols = ["EURUSD", "GBPUSD", "BTCUSD", "ETHUSD"]
        
        if not timeframes:
            timeframes = ["1h", "4h", "1d"]
        
        results = {}
        tasks = []
        
        try:
            # Maak taken voor asyncio.gather
            for symbol in symbols:
                results[symbol] = {}
                for timeframe in timeframes:
                    task = asyncio.create_task(self._capture_chart(symbol, timeframe))
                    tasks.append((symbol, timeframe, task))
            
            # Wacht tot alle taken zijn voltooid
            await asyncio.sleep(0.1)  # Korte pauze om taken te laten starten
            
            # Verzamel resultaten
            for symbol, timeframe, task in tasks:
                try:
                    results[symbol][timeframe] = await task
                except Exception as e:
                    logger.error(f"Error in task for {symbol} at {timeframe}: {str(e)}")
                    results[symbol][timeframe] = None
            
            return results
            
        except Exception as e:
            logger.error(f"Error in batch capture: {str(e)}")
            return None
    
    async def _capture_chart(self, symbol, timeframe):
        """Helper method voor batch_capture_charts"""
        try:
            return await self.take_screenshot(symbol, timeframe)
        except Exception as e:
            logger.error(f"Error capturing {symbol} at {timeframe}: {str(e)}")
            return None
    
    async def cleanup(self):
        """Clean up resources"""
        try:
            # Sluit de thread pool executor
            self.executor.shutdown(wait=False)
            
            # Ruim tijdelijke bestanden op
            cache_files = os.listdir(self.cache_dir)
            for file in cache_files:
                if file.startswith("screenshot_") and file.endswith(".png"):
                    try:
                        os.remove(os.path.join(self.cache_dir, file))
                    except:
                        pass
            
            logger.info("TradingView Node.js service cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up: {str(e)}")
    
    async def take_screenshot_of_url(self, url: str, fullscreen: bool = False) -> Optional[bytes]:
        """Take a screenshot of a URL using Node.js"""
        try:
            # Controleer of we in een Docker-omgeving draaien en stel de NODE_OPTIONS-variabele in
            is_docker = self._check_if_running_in_docker()
            if is_docker:
                logger.info("Running in Docker environment, setting NODE_OPTIONS")
                os.environ["NODE_OPTIONS"] = "--no-sandbox --max-old-space-size=2048"
            
            # Genereer een unieke bestandsnaam voor de screenshot in de cache-map
            timestamp = int(time.time())
            random_suffix = os.urandom(4).hex()  # Extra randomness om conflicten te voorkomen
            screenshot_path = os.path.join(self.cache_dir, f"screenshot_{timestamp}_{random_suffix}.png")
            
            # Zorg ervoor dat de URL geen aanhalingstekens bevat
            url = url.strip('"\'')
            
            # Debug logging
            logger.info(f"Taking screenshot with fullscreen={fullscreen}")
            
            # Bouw het commando efficiënter
            cmd_args = [
                "node", 
                self.screenshot_js_path, 
                url, 
                screenshot_path,
                self.session_id
            ]
            
            # Voeg fullscreen parameter toe als dat nodig is
            if fullscreen:
                cmd_args.append("fullscreen")
            
            logger.info(f"Running command: node screenshot.js [url] [output] [session] {fullscreen}")
            
            # Gebruik aangepaste omgevingsvariabelen voor Docker-compatibiliteit
            env = os.environ.copy()
            if is_docker:
                env["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] = "1"
                env["PLAYWRIGHT_BROWSERS_PATH"] = "/ms-playwright"
                env["DISPLAY"] = ":99"
            
            # Gebruik asyncio subprocess voor non-blocking operatie
            start_time = time.time()
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            
            # Stel een timeout in van 60 seconden (verhoogd voor betere UI-laadtijd verificatie)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
            except asyncio.TimeoutError:
                logger.error("Node.js process timed out after 60 seconds, terminating")
                try:
                    process.terminate()
                    await asyncio.sleep(0.5)
                    if process.returncode is None:
                        process.kill()
                except:
                    pass
                return None
            
            end_time = time.time()
            logger.info(f"Screenshot process took {end_time - start_time:.2f} seconds")
            
            # Log de output alleen bij fouten of als debug niveau
            if stdout:
                logger.debug(f"Node.js stdout: {stdout.decode()}")
            if stderr:
                logger.error(f"Node.js stderr: {stderr.decode()}")
                # Als er foutmeldingen zijn over display problemen, gebruik een fallback
                stderr_text = stderr.decode()
                if "Failed to connect to the bus" in stderr_text or "xcb_connect() failed" in stderr_text:
                    logger.warning("Display connection issues detected, using fallback")
                    return await self._generate_fallback_chart(url)
            
            # Controleer of het bestand bestaat en heeft een redelijke grootte
            if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
                # Lees het bestand
                with open(screenshot_path, 'rb') as f:
                    screenshot_data = f.read()
                
                # Verwijder het bestand
                try:
                    os.remove(screenshot_path)
                except:
                    # Negeer fouten bij het verwijderen, dit is niet kritiek
                    pass
                
                return screenshot_data
            else:
                if os.path.exists(screenshot_path):
                    file_size = os.path.getsize(screenshot_path)
                    logger.error(f"Screenshot file too small: {file_size} bytes, might be an error")
                    try:
                        os.remove(screenshot_path)
                    except:
                        pass
                    # Gebruik fallback
                    return await self._generate_fallback_chart(url)
                else:
                    logger.error(f"Screenshot file not found: {screenshot_path}")
                    # Gebruik fallback
                    return await self._generate_fallback_chart(url)
        
        except Exception as e:
            logger.error(f"Error taking screenshot with Node.js: {str(e)}")
            # Gebruik fallback
            return await self._generate_fallback_chart(url)
    
    def _check_if_running_in_docker(self) -> bool:
        """Controleer of de service in een Docker-container draait"""
        try:
            # Methode 1: controleer /.dockerenv bestand
            if os.path.exists('/.dockerenv'):
                return True
            
            # Methode 2: controleer cgroup
            with open('/proc/1/cgroup', 'r') as f:
                return 'docker' in f.read() or 'kubepods' in f.read()
        except:
            # Bij twijfel/fout, ga ervan uit dat we niet in Docker zitten
            return False
    
    async def _generate_fallback_chart(self, url: str) -> bytes:
        """Genereer een fallback chart wanneer screenshots niet werken"""
        try:
            logger.warning(f"Generating fallback chart for URL: {url}")
            
            # Identificeer het instrument uit de URL
            import re
            instrument = "EURUSD"  # Default
            
            # Probeer instrument te halen uit de URL
            match = re.search(r'symbol=([A-Za-z0-9:]+)', url)
            if match:
                symbol_part = match.group(1)
                # Strip broker prefixes als OANDA: of BITSTAMP:
                if ':' in symbol_part:
                    instrument = symbol_part.split(':')[1]
                else:
                    instrument = symbol_part
            
            # Identificeer timeframe
            timeframe = "1h"  # Default
            match = re.search(r'interval=([0-9A-Za-z]+)', url)
            if match:
                interval = match.group(1)
                # Map TradingView intervals naar onze timeframes
                interval_map_reverse = {
                    "1": "1m", "5": "5m", "15": "15m", "30": "30m", 
                    "60": "1h", "240": "4h", "D": "1d", "W": "1W"
                }
                timeframe = interval_map_reverse.get(interval, "1h")
            
            # Roep de ChartService aan om een matplotlib chart te genereren
            try:
                from trading_bot.services.chart_service.chart import ChartService
                chart_service = ChartService()
                return await chart_service._generate_random_chart(instrument, timeframe)
            except ImportError:
                # Als we de ChartService niet kunnen importeren, genereer een eenvoudige afbeelding
                import io
                from PIL import Image, ImageDraw, ImageFont
                
                # Maak een eenvoudige afbeelding met tekst
                img = Image.new('RGB', (1280, 800), color=(20, 24, 35))
                d = ImageDraw.Draw(img)
                
                # Probeer een font te laden, gebruik default als het niet lukt
                try:
                    font = ImageFont.truetype("Arial", 36)
                except:
                    font = ImageFont.load_default()
                
                # Teken de tekst
                d.text((640, 400), f"{instrument} {timeframe}", fill=(255, 255, 255), anchor="mm", font=font)
                
                # Converteer naar bytes
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                return buffer.getvalue()
        
        except Exception as e:
            logger.error(f"Error generating fallback chart: {str(e)}")
            # Als alles mislukt, gebruik een hardcoded fallback afbeelding
            import base64
            fallback_img = "iVBORw0KGgoAAAANSUhEUgAABQAAAALQAQMAAAD1s08VAAAAA1BMVEUUHy8OksuVAAAASElEQVR4AezBMQEAAADCIPuntsYOYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAXA8ZQAAGpnV+kAAAAAElFTkSuQmCC"
            return base64.b64decode(fallback_img)
