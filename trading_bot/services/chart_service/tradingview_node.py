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
        
        # Corrigeer het pad naar het script
        self.script_path = os.path.join(os.path.dirname(__file__), "screenshot.js")
        
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
            
            # Installeer Playwright direct via npm
            try:
                logger.info("Installing Playwright directly...")
                subprocess.run(["npm", "install", "playwright", "--no-save"], 
                              check=True, 
                              stdout=subprocess.PIPE, 
                              stderr=subprocess.PIPE)
                logger.info("Playwright installed successfully")
            except Exception as e:
                logger.error(f"Error installing Playwright: {str(e)}")
                # Ga door, want het script zal proberen Playwright te installeren indien nodig
            
            # Test de Node.js service met een TradingView URL
            try:
                logger.info("Testing Node.js service with TradingView URL")
                test_url = "https://www.tradingview.com/chart/xknpxpcr/?symbol=EURUSD&interval=1h"
                test_result = await self.take_screenshot_of_url(test_url)
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
            
            # Gebruik de take_screenshot_of_url methode om de screenshot te maken
            logger.info(f"Taking screenshot of URL: {chart_url}")
            screenshot_bytes = await self.take_screenshot_of_url(chart_url)
            
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
    
    async def take_screenshot_of_url(self, url: str) -> Optional[bytes]:
        """Take a screenshot of a URL using Node.js"""
        try:
            # Genereer een unieke bestandsnaam voor de screenshot
            timestamp = int(time.time())
            screenshot_path = os.path.join(os.path.dirname(self.script_path), f"screenshot_{timestamp}.png")
            
            # Zorg ervoor dat de URL geen aanhalingstekens bevat
            url = url.strip('"\'')
            
            # Controleer of de URL naar TradingView verwijst
            if "tradingview.com" in url:
                logger.info(f"Taking screenshot of TradingView URL: {url}")
                
                # Verwijder eventuele extra parameters als het een specifieke chart URL is
                if "/chart/" in url and "?" in url:
                    # Haal de basis-URL eruit (alles voor het vraagteken)
                    url = url.split("?")[0]
                    logger.info(f"Cleaned URL to: {url}")
            else:
                logger.warning(f"URL is not a TradingView URL: {url}")
            
            # Gebruik session_id in plaats van tradingview_username
            # Zorg ervoor dat de URL correct wordt doorgegeven zonder extra aanhalingstekens
            cmd = f"node {self.script_path} \"{url}\" \"{screenshot_path}\" \"{self.session_id}\""
            logger.info(f"Running command: {cmd.replace(self.session_id, '****')}")
            
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            # Log de output
            if stdout:
                logger.info(f"Node.js stdout: {stdout.decode()}")
            if stderr:
                logger.error(f"Node.js stderr: {stderr.decode()}")
            
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
