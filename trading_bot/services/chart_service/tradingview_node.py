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
        
        # Caching van playfound playwright check
        self.playwright_installed = None
        self.playwright_browsers_installed = None
        
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
            
            # Controleer of Node.js is geïnstalleerd (alleen indien nodig)
            try:
                node_version = subprocess.check_output(["node", "--version"]).decode().strip()
                logger.info(f"Node.js version: {node_version}")
            except Exception as node_error:
                logger.error(f"Error checking Node.js version: {str(node_error)}")
                return False
            
            # Check if the screenshot.js file exists
            if not os.path.exists(self.script_path):
                logger.error(f"screenshot.js not found at {self.script_path}")
                return False
            
            logger.info(f"screenshot.js found at {self.script_path}")
            
            # Controleer of Playwright al geïnstalleerd is om te vermijden dat het elke keer wordt gecontroleerd
            if self.playwright_installed is None:
                try:
                    # Test of Playwright al beschikbaar is
                    subprocess.run(["node", "-e", "require('playwright')"], 
                                  check=True, 
                                  stdout=subprocess.PIPE, 
                                  stderr=subprocess.PIPE)
                    logger.info("Playwright is already installed")
                    self.playwright_installed = True
                except Exception:
                    # Installeer Playwright als het niet beschikbaar is
                    logger.info("Installing Playwright directly...")
                    try:
                        subprocess.run(["npm", "install", "playwright", "--no-save"], 
                                      check=True, 
                                      stdout=subprocess.PIPE, 
                                      stderr=subprocess.PIPE)
                        logger.info("Playwright installed successfully")
                        self.playwright_installed = True
                    except Exception as e:
                        logger.error(f"Error installing Playwright: {str(e)}")
                        self.playwright_installed = False
            
            # Check if Playwright browsers are installed and install them if missing
            if self.playwright_browsers_installed is None and self.playwright_installed:
                try:
                    # First try to take a test screenshot, which will reveal if browsers are missing
                    logger.info("Testing Node.js service with TradingView URL")
                    test_url = "https://www.tradingview.com/chart/xknpxpcr/?symbol=EURUSD&interval=1h"
                    timestamp = int(time.time())
                    test_screenshot_path = os.path.join(os.path.dirname(self.script_path), f"screenshot_{timestamp}.png")
                    
                    cmd = f"node {self.script_path} \"{test_url}\" \"{test_screenshot_path}\" \"{self.session_id}\""
                    logger.info(f"Taking screenshot with fullscreen=False")
                    logger.info(f"Taking screenshot of TradingView URL: {test_url}")
                    logger.info(f"Running command: {cmd.replace(self.session_id, '****')}")
                    
                    process = await asyncio.create_subprocess_shell(
                        cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    
                    stdout, stderr = await process.communicate()
                    
                    if stdout:
                        logger.info(f"Node.js stdout: {stdout.decode()}")
                    if stderr:
                        stderr_output = stderr.decode()
                        logger.error(f"Node.js stderr: {stderr_output}")
                        
                        # Check if browsers are missing based on error message
                        if "Executable doesn't exist" in stderr_output or "Please run the following command to download new browsers" in stderr_output:
                            logger.info("Playwright browsers are missing, installing them now")
                            try:
                                # Install Playwright browsers
                                install_process = subprocess.run(
                                    ["npx", "playwright", "install", "chromium"],
                                    check=True,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    timeout=300  # 5 minutes timeout for browser installation
                                )
                                logger.info(f"Playwright browsers installed successfully: {install_process.stdout.decode()}")
                                self.playwright_browsers_installed = True
                            except subprocess.CalledProcessError as e:
                                logger.error(f"Error installing Playwright browsers: {e.stderr.decode()}")
                                self.playwright_browsers_installed = False
                            except Exception as e:
                                logger.error(f"Unexpected error installing Playwright browsers: {str(e)}")
                                self.playwright_browsers_installed = False
                        else:
                            # Some other error, but browsers might be installed
                            self.playwright_browsers_installed = True
                    
                    # Check if the test screenshot was created
                    if os.path.exists(test_screenshot_path):
                        logger.info("Node.js service test successful, browsers are installed")
                        self.playwright_browsers_installed = True
                        # Cleanup the test screenshot
                        try:
                            os.remove(test_screenshot_path)
                        except Exception:
                            pass
                    else:
                        logger.error("Screenshot file not found: {test_screenshot_path}")
                        logger.error("Node.js service test failed")
                        # We'll still try to continue, maybe browsers will be installed
                
                except Exception as e:
                    logger.error(f"Error testing Playwright browser installation: {str(e)}")
                    # We'll still continue with initialization
            
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
            
            # Gebruik session_id in plaats van tradingview_username
            # Voeg fullscreen parameter toe aan het commando
            cmd = f"node {self.script_path} \"{url}\" \"{screenshot_path}\" \"{self.session_id}\""
            
            # Voeg fullscreen parameter toe als dat nodig is
            if fullscreen or "fullscreen=true" in url:
                cmd += " fullscreen"
                logger.info("Adding fullscreen parameter to command")
            
            # Verwijder eventuele puntkomma's uit het commando
            cmd = cmd.replace(";", "")
            
            logger.info(f"Running command: {cmd.replace(self.session_id, '****')}")
            
            # Gebruik asyncio.create_subprocess_shell met een timeout om te voorkomen dat het script vastloopt
            try:
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                # Wacht op het proces met een kortere timeout (30 seconden max)
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
                except asyncio.TimeoutError:
                    logger.error("Timeout waiting for Node.js script, terminating process")
                    try:
                        process.kill()
                    except Exception as kill_error:
                        logger.error(f"Error killing process: {str(kill_error)}")
                    return None
                
                # Log de output
                if stdout:
                    logger.info(f"Node.js stdout: {stdout.decode()}")
                if stderr:
                    stderr_output = stderr.decode()
                    logger.error(f"Node.js stderr: {stderr_output}")
                    
                    # Check if browsers need to be installed
                    if "Executable doesn't exist" in stderr_output or "Please run the following command to download new browsers" in stderr_output:
                        logger.warning("Playwright browsers missing during screenshot attempt, trying to install them")
                        try:
                            # Install Playwright browsers
                            install_process = subprocess.run(
                                ["npx", "playwright", "install", "chromium"],
                                check=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                timeout=300  # 5 minutes timeout for browser installation
                            )
                            logger.info(f"Playwright browsers installed successfully during screenshot attempt: {install_process.stdout.decode()}")
                            
                            # Try the screenshot again after installing browsers
                            logger.info("Retrying screenshot after browser installation")
                            process = await asyncio.create_subprocess_shell(
                                cmd,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE
                            )
                            
                            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
                            if stdout:
                                logger.info(f"Node.js stdout (retry): {stdout.decode()}")
                            if stderr:
                                logger.error(f"Node.js stderr (retry): {stderr.decode()}")
                        except Exception as e:
                            logger.error(f"Error installing Playwright browsers during screenshot attempt: {str(e)}")
                
                # Controleer of het bestand bestaat
                if os.path.exists(screenshot_path):
                    # Lees het bestand
                    with open(screenshot_path, 'rb') as f:
                        screenshot_data = f.read()
                    
                    # Verwijder het bestand
                    try:
                        os.remove(screenshot_path)
                    except Exception as e:
                        logger.warning(f"Failed to remove temporary screenshot file: {str(e)}")
                    
                    # Return the screenshot data
                    return screenshot_data
                else:
                    logger.error(f"Screenshot file not found: {screenshot_path}")
                    return None
            except Exception as process_error:
                logger.error(f"Error running Node.js process: {str(process_error)}")
                return None
                
        except Exception as e:
            logger.error(f"Error taking screenshot: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
