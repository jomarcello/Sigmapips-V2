import os
import logging
import asyncio
import json
import base64
import subprocess
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
            
            # Controleer of het script bestaat
            if not os.path.exists(self.script_path):
                logger.error(f"Script not found at {self.script_path}")
                return False
            
            # Test of Node.js beschikbaar is
            try:
                process = await asyncio.create_subprocess_exec(
                    'node', '--version',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    logger.error(f"Node.js not available: {stderr.decode()}")
                    return False
                
                logger.info(f"Node.js version: {stdout.decode().strip()}")
            except Exception as e:
                logger.error(f"Error checking Node.js: {str(e)}")
                return False
            
            # Controleer of de benodigde npm packages zijn geïnstalleerd
            try:
                process = await asyncio.create_subprocess_exec(
                    'npm', 'list', 'playwright-extra',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    logger.warning(f"playwright-extra not installed: {stderr.decode()}")
                    logger.info("Installing required npm packages...")
                    
                    # Installeer de benodigde packages
                    install_process = await asyncio.create_subprocess_exec(
                        'npm', 'install', 'playwright-extra', 'puppeteer-extra-plugin-stealth', 
                        'puppeteer-extra-plugin-recaptcha', 'dotenv', '@playwright/test',
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    
                    install_stdout, install_stderr = await install_process.communicate()
                    
                    if install_process.returncode != 0:
                        logger.error(f"Failed to install npm packages: {install_stderr.decode()}")
                        return False
                    
                    logger.info("Successfully installed npm packages")
            except Exception as e:
                logger.error(f"Error checking npm packages: {str(e)}")
                return False
            
            self.is_initialized = True
            self.is_logged_in = True  # We gaan ervan uit dat het script de login afhandelt
            logger.info("TradingView Node.js service initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing TradingView Node.js service: {str(e)}")
            return False
    
    async def take_screenshot(self, symbol, timeframe):
        """Take a screenshot of a chart using Node.js script"""
        if not self.is_initialized:
            logger.warning("TradingView Node.js service not initialized")
            return None
        
        try:
            logger.info(f"Taking screenshot for {symbol} on {timeframe} timeframe")
            
            # Voer het Node.js script uit
            process = await asyncio.create_subprocess_exec(
                'node', self.script_path, symbol, timeframe,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error(f"Screenshot failed: {stderr.decode()}")
                return None
            
            # Lees het screenshot bestand
            screenshot_path = os.path.join(os.getcwd(), 'screenshots', f"{symbol}_{timeframe}.png")
            
            if not os.path.exists(screenshot_path):
                logger.error(f"Screenshot file not found at {screenshot_path}")
                return None
            
            with open(screenshot_path, 'rb') as f:
                screenshot = f.read()
            
            logger.info(f"Successfully took screenshot of {symbol} {timeframe}")
            return screenshot
            
        except Exception as e:
            logger.error(f"Error taking screenshot: {str(e)}")
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
