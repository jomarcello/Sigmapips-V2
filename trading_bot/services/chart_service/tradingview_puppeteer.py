# Tijdelijke stub voor backward compatibility
# Dit bestand zal worden verwijderd in toekomstige versies

import logging
logger = logging.getLogger(__name__)

import os
import asyncio
import json
import base64
from io import BytesIO
from datetime import datetime
from trading_bot.services.chart_service.tradingview import TradingViewService

class TradingViewPuppeteerService(TradingViewService):
    """Stub class for backward compatibility"""
    
    def __init__(self, session_id=None):
        """Initialize the TradingView Puppeteer service"""
        super().__init__()
        self.session_id = session_id or os.getenv("TRADINGVIEW_SESSION_ID", "")
        self.username = os.getenv("TRADINGVIEW_USERNAME", "")
        self.password = os.getenv("TRADINGVIEW_PASSWORD", "")
        self.is_initialized = False
        self.is_logged_in = False
        self.base_url = "https://www.tradingview.com"
        self.chart_url = "https://www.tradingview.com/chart"
        
        # Chart links voor verschillende symbolen
        self.chart_links = {
            "EURUSD": "https://www.tradingview.com/chart/?symbol=EURUSD",
            "GBPUSD": "https://www.tradingview.com/chart/?symbol=GBPUSD",
            "BTCUSD": "https://www.tradingview.com/chart/?symbol=BTCUSD",
            "ETHUSD": "https://www.tradingview.com/chart/?symbol=ETHUSD"
        }
        
        logger.info(f"TradingView Puppeteer service initialized")
    
    async def initialize(self):
        """Initialize the Puppeteer browser"""
        try:
            logger.info("Initializing TradingView Puppeteer service")
            
            # Gebruik Node.js om Puppeteer aan te roepen
            import subprocess
            import tempfile
            
            # Maak een tijdelijk JavaScript bestand
            with tempfile.NamedTemporaryFile(suffix='.js', delete=False, mode='w') as f:
                js_code = """
                const puppeteer = require('puppeteer');

                (async () => {
                    try {
                        console.log('Starting Puppeteer');
                        const browser = await puppeteer.launch({
                            headless: true,
                            args: [
                                "--no-sandbox",
                                "--disable-dev-shm-usage",
                                "--disable-gpu",
                                "--window-size=1366,768",
                            ],
                        });
                        
                        console.log('Browser launched');
                        const page = (await browser.pages())[0];
                        
                        // Ga naar TradingView
                        await page.goto('https://www.tradingview.com/#signin');
                        console.log('Navigated to TradingView');
                        
                        // Login
                        await page.click('span.js-show-email');
                        await page.type('[name="username"]', process.env.TRADINGVIEW_USERNAME);
                        await page.type('[name="password"]', process.env.TRADINGVIEW_PASSWORD);
                        await page.click('[type="submit"]');
                        
                        console.log('Login form submitted');
                        
                        try {
                            const loginResponse = await page.waitForResponse(
                                (response) =>
                                    response.url().includes('accounts/signin/') &&
                                    response.status() === 200,
                                { timeout: 30000 }
                            );
                            
                            const responseText = await loginResponse.text();
                            const loginSuccess = responseText.includes('user');
                            
                            if (loginSuccess) {
                                console.log('Login successful');
                                
                                // Wacht tot de pagina volledig is geladen
                                await page.waitForSelector('.tv-header__user-menu-button', { timeout: 30000 });
                                
                                // Sla cookies op
                                const cookies = await page.cookies();
                                console.log(JSON.stringify(cookies));
                                
                                // Sluit de browser
                                await browser.close();
                                process.exit(0);
                            } else {
                                console.error('Login failed: Invalid credentials');
                                await browser.close();
                                process.exit(1);
                            }
                        } catch (error) {
                            console.error('Login failed:', error.message);
                            await browser.close();
                            process.exit(1);
                        }
                    } catch (error) {
                        console.error('Error:', error.message);
                        process.exit(1);
                    }
                })();
                """
                f.write(js_code)
                js_file = f.name
            
            # Voer het JavaScript bestand uit
            env = os.environ.copy()
            env['TRADINGVIEW_USERNAME'] = self.username
            env['TRADINGVIEW_PASSWORD'] = self.password
            
            logger.info(f"Running Puppeteer with username: {self.username}")
            
            process = await asyncio.create_subprocess_exec(
                'node', js_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            
            stdout, stderr = await process.communicate()
            
            # Verwijder het tijdelijke bestand
            os.unlink(js_file)
            
            if process.returncode != 0:
                logger.error(f"Puppeteer login failed: {stderr.decode()}")
                return False
            
            # Parse de cookies uit de stdout
            output = stdout.decode()
            logger.info(f"Puppeteer output: {output}")
            
            # Zoek naar de JSON cookies in de output
            import re
            cookies_match = re.search(r'\[(.*)\]', output, re.DOTALL)
            
            if cookies_match:
                cookies_json = cookies_match.group(0)
                cookies = json.loads(cookies_json)
                
                # Zoek naar de sessionid cookie
                for cookie in cookies:
                    if cookie['name'] == 'sessionid':
                        self.session_id = cookie['value']
                        logger.info(f"Found sessionid: {self.session_id[:5]}...")
                        break
                
                if self.session_id:
                    self.is_initialized = True
                    self.is_logged_in = True
                    logger.info("Successfully logged in to TradingView using Puppeteer")
                    return True
            
            logger.warning("Could not find sessionid in cookies")
            return False
                
        except Exception as e:
            logger.error(f"Error initializing TradingView Puppeteer service: {str(e)}")
            return False
    
    async def login(self):
        """Login to TradingView using Puppeteer"""
        return await self.initialize()
    
    async def take_screenshot(self, chart_url, timeframe=None, adjustment=5):
        """Take a screenshot of a chart using Puppeteer"""
        try:
            if not self.is_initialized:
                logger.warning("TradingView Puppeteer service not initialized")
                return None
            
            # If chart_url is a symbol instead of a URL, convert it
            if not chart_url.startswith("http"):
                symbol = chart_url
                chart_url = self.chart_links.get(symbol, f"{self.chart_url}/?symbol={symbol}")
            
            logger.info(f"Taking screenshot of chart at URL: {chart_url}")
            
            # Gebruik Node.js om Puppeteer aan te roepen
            import subprocess
            import tempfile
            
            # Maak een tijdelijk JavaScript bestand
            with tempfile.NamedTemporaryFile(suffix='.js', delete=False, mode='w') as f:
                js_code = f"""
                const puppeteer = require('puppeteer');

                (async () => {{
                    try {{
                        console.log('Starting Puppeteer for screenshot');
                        const browser = await puppeteer.launch({{
                            headless: true,
                            args: [
                                "--no-sandbox",
                                "--disable-dev-shm-usage",
                                "--disable-gpu",
                                "--window-size=1920,1080",
                            ],
                        }});
                        
                        console.log('Browser launched');
                        const page = (await browser.pages())[0];
                        
                        // Stel viewport in
                        await page.setViewport({{ width: 1920, height: 1080 }});
                        
                        // Voeg session cookie toe
                        await page.setCookie({{
                            name: 'sessionid',
                            value: '{self.session_id}',
                            domain: '.tradingview.com',
                            path: '/'
                        }});
                        
                        // Ga naar de chart
                        await page.goto('{chart_url}', {{ waitUntil: 'networkidle2', timeout: 60000 }});
                        console.log('Navigated to chart URL');
                        
                        // Wacht tot de chart is geladen
                        await page.waitForSelector('.chart-container', {{ timeout: 60000 }});
                        console.log('Chart container found');
                        
                        // Wacht extra tijd voor volledige rendering
                        await new Promise(resolve => setTimeout(resolve, 10000));
                        
                        // Stel timeframe in als opgegeven
                        if ('{timeframe}') {{
                            try {{
                                // Klik op de timeframe knop
                                await page.click('.chart-toolbar-timeframes button');
                                
                                // Wacht op het dropdown menu
                                await new Promise(resolve => setTimeout(resolve, 1000));
                                
                                // Zoek en klik op de juiste timeframe optie
                                const timeframeOptions = await page.$$('.menu-item');
                                for (const option of timeframeOptions) {{
                                    const text = await page.evaluate(el => el.textContent, option);
                                    if (text.toLowerCase().includes('{timeframe}'.toLowerCase())) {{
                                        await option.click();
                                        break;
                                    }}
                                }}
                                
                                // Wacht tot de chart is bijgewerkt
                                await new Promise(resolve => setTimeout(resolve, 3000));
                            }} catch (error) {{
                                console.error('Error setting timeframe:', error.message);
                            }}
                        }}
                        
                        // Pas de positie aan (scroll naar rechts)
                        try {{
                            // Druk op Escape om eventuele dialogen te sluiten
                            await page.keyboard.press('Escape');
                            
                            // Druk op pijltje rechts meerdere keren
                            for (let i = 0; i < {adjustment}; i++) {{
                                await page.keyboard.press('ArrowRight');
                                await new Promise(resolve => setTimeout(resolve, 10));
                            }}
                            
                            await new Promise(resolve => setTimeout(resolve, 3000));
                        }} catch (error) {{
                            console.error('Error performing keyboard actions:', error.message);
                        }}
                        
                        // Verberg UI elementen voor een schone screenshot
                        await page.evaluate(() => {{
                            const elementsToHide = [
                                '.chart-toolbar',
                                '.tv-side-toolbar',
                                '.header-chart-panel',
                                '.drawing-toolbar',
                                '.chart-controls-bar',
                                '.layout__area--left',
                                '.layout__area--top',
                                '.layout__area--right'
                            ];
                            
                            elementsToHide.forEach(selector => {{
                                const elements = document.querySelectorAll(selector);
                                elements.forEach(el => {{
                                    if (el) el.style.display = 'none';
                                }});
                            }});
                        }});
                        
                        await new Promise(resolve => setTimeout(resolve, 1000));
                        
                        // Neem screenshot
                        const screenshot = await page.screenshot({{ fullPage: false }});
                        console.log(screenshot.toString('base64'));
                        
                        // Sluit de browser
                        await browser.close();
                        process.exit(0);
                    }} catch (error) {{
                        console.error('Error taking screenshot:', error.message);
                        process.exit(1);
                    }}
                }})();
                """
                f.write(js_code)
                js_file = f.name
            
            # Voer het JavaScript bestand uit
            process = await asyncio.create_subprocess_exec(
                'node', js_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            # Verwijder het tijdelijke bestand
            os.unlink(js_file)
            
            if process.returncode != 0:
                logger.error(f"Puppeteer screenshot failed: {stderr.decode()}")
                return None
            
            # Parse de base64 screenshot uit de stdout
            output = stdout.decode()
            
            # Zoek naar de base64 string in de output
            import re
            base64_match = re.search(r'([A-Za-z0-9+/=]{100,})', output)
            
            if base64_match:
                base64_str = base64_match.group(0)
                screenshot = base64.b64decode(base64_str)
                logger.info(f"Successfully took screenshot of chart")
                return screenshot
            
            logger.warning("Could not find base64 screenshot in output")
            return None
            
        except Exception as e:
            logger.error(f"Error taking screenshot: {str(e)}")
            return None
    
    async def batch_capture_charts(self, symbols=None, timeframes=None):
        """Capture multiple charts"""
        if not self.is_initialized:
            logger.warning("TradingView Puppeteer service not initialized")
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
                        # Determine chart URL
                        chart_url = self.chart_links.get(symbol, f"{self.chart_url}/?symbol={symbol}")
                        
                        # Take screenshot
                        screenshot = await self.take_screenshot(chart_url, timeframe)
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
        logger.info("TradingView Puppeteer service cleaned up") 
