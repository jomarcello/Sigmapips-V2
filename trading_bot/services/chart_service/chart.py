import os
import logging
import asyncio
import base64
from io import BytesIO
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
import aiofiles
import json
import time
import random
import aiohttp
from twocaptcha import TwoCaptcha

logger = logging.getLogger(__name__)

class ChartService:
    def __init__(self):
        """Initialize chart service"""
        self.browser = None
        self.context = None
        self.page = None
        self.is_initialized = False
        self.is_logged_in = False
        self.cookies_path = os.path.join(os.path.dirname(__file__), "tradingview_cookies.json")
        self.username = os.getenv("TRADINGVIEW_USERNAME")
        self.password = os.getenv("TRADINGVIEW_PASSWORD")
        
        # 2Captcha API key
        self.captcha_api_key = os.getenv("TWOCAPTCHA_API_KEY", "442b77082098300c2d00291e4a99372f")
        self.solver = TwoCaptcha(self.captcha_api_key) if self.captcha_api_key else None
        
        # Redis voor cookie opslag
        redis_host = os.getenv("REDIS_HOST", "redis")
        redis_port = int(os.getenv("REDIS_PORT", 6379))
        try:
            import redis
            self.redis = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=0,
                decode_responses=True,
                socket_connect_timeout=2,
                retry_on_timeout=True
            )
            # Test de verbinding
            self.redis.ping()
            logger.info("Redis connection established")
        except Exception as redis_error:
            logger.error(f"Redis connection failed: {str(redis_error)}")
            self.redis = None
        
        # Configuratie voor charts
        self.base_url = "https://www.tradingview.com/chart/"
        self.timeframe_map = {
            "1m": "1",
            "5m": "5",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "4h": "240",
            "1d": "D",
            "1w": "W"
        }
        
        self.session_pool = []
        self.max_sessions = 2  # Aantal parallelle sessies
        
    async def initialize(self):
        """Initialize browser sessions"""
        if self.session_pool:
            return
            
        for i in range(self.max_sessions):
            try:
                session = await self._create_session()
                self.session_pool.append(session)
                logger.info(f"Initialized session {i+1}/{self.max_sessions}")
            except Exception as e:
                logger.error(f"Error initializing session {i+1}: {str(e)}")
                
    async def _create_session(self):
        """Create a new browser session"""
        browser = None
        context = None
        page = None
        
        try:
            logger.info("Creating new browser session")
            playwright = await async_playwright().start()
            
            # Gebruik een echte browser (chromium) met stealth modus
            browser = await playwright.chromium.launch(
                headless=True,  # True voor productie, False voor debugging
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-site-isolation-trials"
                ]
            )
            
            # Maak een context met menselijke eigenschappen
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                locale="en-US",
                timezone_id="Europe/Amsterdam",
                has_touch=False,
                is_mobile=False,
                color_scheme="light"
            )
            
            # Voeg stealth scripts toe
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false,
                });
                
                // Overwrite the 'plugins' property to use a custom getter
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
                
                // Overwrite the 'languages' property to use a custom getter
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                });
            """)
            
            # Laad cookies als ze bestaan
            self.context = context  # Tijdelijk instellen voor load_cookies
            cookies_loaded = await self.load_cookies()
            
            # Open een nieuwe pagina
            page = await context.new_page()
            
            # Voeg extra headers toe
            await page.set_extra_http_headers({
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
            })
            
            # Controleer of we ingelogd zijn
            self.page = page  # Tijdelijk instellen voor check_login_status
            is_logged_in = False
            
            if cookies_loaded:
                # Controleer login status
                await page.goto("https://www.tradingview.com/chart/", timeout=30000)
                await asyncio.sleep(2)
                user_menu = await page.query_selector('button[data-name="user-menu"]')
                is_logged_in = user_menu is not None
            
            if not is_logged_in and self.username and self.password:
                # Log in
                self.browser = browser
                self.context = context
                self.page = page
                is_logged_in = await self.login()
            
            # Maak een sessie-object
            session = {
                'playwright': playwright,
                'browser': browser,
                'context': context,
                'page': page,
                'is_logged_in': is_logged_in,
                'last_session_check': time.time()
            }
            
            logger.info(f"Browser session created successfully, logged in: {is_logged_in}")
            return session
            
        except Exception as e:
            logger.error(f"Error creating browser session: {str(e)}")
            
            # Cleanup bij fout
            try:
                if page:
                    await page.close()
                if context:
                    await context.close()
                if browser:
                    await browser.close()
                if 'playwright' in locals() and playwright:
                    await playwright.stop()
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {str(cleanup_error)}")
            
            return None
    
    async def load_cookies(self):
        """Load cookies from Redis or file"""
        try:
            # Probeer eerst uit Redis
            if hasattr(self, 'redis') and self.redis:
                cookies_data = self.redis.get("tradingview_cookies")
                if cookies_data:
                    cookies = json.loads(cookies_data)
                    await self.context.add_cookies(cookies)
                    logger.info("Cookies loaded from Redis successfully")
                    return True
            
            # Fallback naar bestand
            if os.path.exists(self.cookies_path):
                async with aiofiles.open(self.cookies_path, "r") as f:
                    cookies = json.loads(await f.read())
                await self.context.add_cookies(cookies)
                logger.info("Cookies loaded from file successfully")
                return True
            
            logger.info("No cookies found")
            return False
        except Exception as e:
            logger.error(f"Error loading cookies: {str(e)}")
            return False
    
    async def save_cookies(self):
        """Save cookies to Redis and file"""
        try:
            cookies = await self.context.cookies()
            
            # Sla op in Redis
            if hasattr(self, 'redis') and self.redis:
                self.redis.set("tradingview_cookies", json.dumps(cookies))
                self.redis.expire("tradingview_cookies", 604800)  # 7 dagen
            
            # Sla ook op in bestand als backup
            async with aiofiles.open(self.cookies_path, "w") as f:
                await f.write(json.dumps(cookies))
            
            logger.info("Cookies saved successfully")
            return True
        except Exception as e:
            logger.error(f"Error saving cookies: {str(e)}")
            return False
    
    async def check_login_status(self):
        """Check if we're logged in to TradingView"""
        try:
            await self.page.goto("https://www.tradingview.com/chart/", timeout=60000)
            
            # Wacht even om de pagina te laden
            await asyncio.sleep(3)
            
            # Controleer of we ingelogd zijn door te zoeken naar elementen die alleen zichtbaar zijn als je ingelogd bent
            user_menu = await self.page.query_selector('button[data-name="user-menu"]')
            
            if user_menu:
                logger.info("Already logged in to TradingView")
                self.is_logged_in = True
                return True
            else:
                logger.info("Not logged in to TradingView")
                self.is_logged_in = False
                
                # Probeer in te loggen als we credentials hebben
                if self.username and self.password:
                    return await self.login()
                return False
                
        except Exception as e:
            logger.error(f"Error checking login status: {str(e)}")
            self.is_logged_in = False
            return False
    
    async def login(self):
        """Login to TradingView"""
        try:
            if self.is_logged_in:
                return True
                
            logger.info("Logging in to TradingView")
            
            # Ga naar de login pagina
            await self.page.goto("https://www.tradingview.com/signin/", timeout=60000)
            
            # Wacht op de email input en vul deze in
            await self.page.wait_for_selector('input[name="username"]', timeout=10000)
            
            # Voeg menselijke vertraging toe
            await self.human_type(self.page, 'input[name="username"]', self.username)
            
            # Klik op de "Email" tab als die er is
            email_tab = await self.page.query_selector('button:has-text("Email")')
            if email_tab:
                await email_tab.click()
                await asyncio.sleep(1)
            
            # Vul het wachtwoord in
            await self.human_type(self.page, 'input[name="password"]', self.password)
            
            # Klik op de inlogknop
            await self.page.click('button[type="submit"]')
            
            # Wacht tot we ingelogd zijn of een captcha tegenkomen (max 20 seconden)
            try:
                # Wacht op ofwel de user menu button (succes) of een captcha
                result = await self.page.wait_for_selector('button[data-name="user-menu"], div[class*="captcha"], iframe[title*="recaptcha"]', timeout=20000)
                
                # Controleer of het een captcha is
                is_captcha = await result.get_attribute('class')
                is_iframe = await result.get_attribute('title')
                
                if (is_captcha and 'captcha' in is_captcha) or (is_iframe and 'recaptcha' in is_iframe):
                    logger.info("CAPTCHA detected, attempting to solve...")
                    
                    # Los de captcha op
                    captcha_solved = await self.solve_captcha()
                    if not captcha_solved:
                        logger.error("Failed to solve CAPTCHA")
                        self.is_logged_in = False
                        return False
                    
                    # Wacht opnieuw op de user menu button na het oplossen van de captcha
                    await self.page.wait_for_selector('button[data-name="user-menu"]', timeout=20000)
                
                logger.info("Successfully logged in to TradingView")
                self.is_logged_in = True
                
                # Sla cookies op
                await self.save_cookies()
                
                return True
                
            except Exception as timeout_error:
                logger.error(f"Login timeout: {str(timeout_error)}")
                
                # Controleer op foutmeldingen
                error = await self.page.query_selector('div[class*="error"]')
                if error:
                    error_text = await error.text_content()
                    logger.error(f"Login error: {error_text}")
                
                self.is_logged_in = False
                return False
                
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            self.is_logged_in = False
            return False
    
    async def human_type(self, page: Page, selector: str, text: str):
        """Type like a human with random delays between keystrokes"""
        await page.click(selector)
        await asyncio.sleep(random.uniform(0.1, 0.3))
        
        for char in text:
            await page.type(selector, char, delay=random.uniform(50, 150))
            await asyncio.sleep(random.uniform(0.01, 0.05))
        
        await asyncio.sleep(random.uniform(0.2, 0.5))
    
    async def get_chart(self, instrument: str, timeframe: str = "1h") -> Optional[bytes]:
        """Get chart image for instrument and timeframe using session pool"""
        try:
            # Initialiseer sessies indien nodig
            if not self.session_pool:
                await self.initialize()
            
            # Als er geen sessies beschikbaar zijn, gebruik fallback
            if not self.session_pool:
                logger.error("No browser sessions available, using fallback")
                return await self.get_fallback_chart(instrument)
            
            # Kies een willekeurige sessie uit de pool
            session_index = random.randint(0, len(self.session_pool) - 1)
            
            # Haal sessie attributen op
            self.browser = self.session_pool[session_index].get('browser')
            self.context = self.session_pool[session_index].get('context')
            self.page = self.session_pool[session_index].get('page')
            self.is_logged_in = self.session_pool[session_index].get('is_logged_in', False)
            
            # Vernieuw de sessie indien nodig
            current_time = time.time()
            last_check = self.session_pool[session_index].get('last_session_check', 0)
            
            if current_time - last_check > 1800:  # 30 minuten
                await self.refresh_session_if_needed()
                self.session_pool[session_index]['last_session_check'] = current_time
            
            # Als we niet ingelogd zijn, probeer in te loggen
            if not self.is_logged_in:
                success = await self.login()
                if not success:
                    logger.error("Failed to login, using fallback chart")
                    return await self.get_fallback_chart(instrument)
                self.session_pool[session_index]['is_logged_in'] = True
            
            # Normaliseer instrument en timeframe
            instrument = instrument.upper()
            tf = self.timeframe_map.get(timeframe, "60")  # Default to 1h
            
            # Bepaal het juiste symbool formaat
            if "USD" in instrument and len(instrument) == 6:
                # Forex pair
                symbol = f"FX:{instrument}"
            elif instrument in ["XAUUSD", "XAGUSD"]:
                # Gold/Silver
                metal_map = {"XAUUSD": "GOLD", "XAGUSD": "SILVER"}
                symbol = f"TVC:{metal_map.get(instrument, instrument)}"
            elif instrument in ["USOIL", "UKOIL"]:
                # Oil
                symbol = f"TVC:{instrument}"
            elif any(index in instrument for index in ["30", "500", "100"]):
                # US indices
                indices_map = {"US30": "DJ30", "US500": "SPX500", "US100": "NASDAQ100"}
                symbol = f"TVC:{indices_map.get(instrument, instrument)}"
            elif any(crypto in instrument for crypto in ["BTC", "ETH", "XRP"]):
                # Crypto
                base = instrument[:3]
                quote = instrument[3:] if len(instrument) > 3 else "USD"
                symbol = f"BINANCE:{base}{quote}"
            else:
                # Default
                symbol = f"FX:{instrument}"
            
            # Navigeer naar de chart pagina met het juiste symbool en timeframe
            chart_url = f"https://www.tradingview.com/chart/?symbol={symbol}&interval={tf}"
            logger.info(f"Navigating to chart URL: {chart_url}")
            
            await self.page.goto(chart_url, timeout=60000)
            
            # Wacht tot de chart geladen is
            await self.page.wait_for_selector('.chart-markup-table', timeout=30000)
            
            # Geef de chart tijd om volledig te renderen
            await asyncio.sleep(5)
            
            # Verwijder UI elementen die we niet willen in de screenshot
            await self.page.evaluate("""
                () => {
                    // Verberg header, footer, sidebar, etc.
                    const elementsToHide = [
                        '.header-chart-panel',
                        '.footer-chart-panel',
                        '.left-toolbar',
                        '.right-toolbar',
                        '.chart-controls-bar',
                        '.drawing-toolbar',
                        '.tv-side-toolbar'
                    ];
                    
                    elementsToHide.forEach(selector => {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            if (el) el.style.display = 'none';
                        });
                    });
                }
            """)
            
            # Wacht even om de UI aanpassingen te laten verwerken
            await asyncio.sleep(1)
            
            # Neem een screenshot van alleen de chart
            chart_element = await self.page.query_selector('.chart-markup-table')
            if not chart_element:
                logger.error("Chart element not found")
                return await self.get_fallback_chart(instrument)
            
            screenshot = await chart_element.screenshot()
            
            # Sla cookies op na elke succesvolle chart generatie om de sessie te verlengen
            await self.save_cookies()
            
            return screenshot
            
        except Exception as e:
            logger.error(f"Error getting chart: {str(e)}")
            # Probeer fallback bij fout
            return await self.get_fallback_chart(instrument)
    
    async def get_fallback_chart(self, instrument: str) -> Optional[bytes]:
        """Get a fallback chart when TradingView is not available"""
        try:
            # Use a public API for a basic chart
            url = f"https://api.chart-img.com/v1/tradingview/advanced-chart?symbol={instrument}&interval=1h&studies=RSI&key=demo"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.error(f"Fallback chart API error: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error getting fallback chart: {str(e)}")
            return None
    
    async def cleanup(self):
        """Clean up all browser resources"""
        try:
            # Ruim alle sessies op
            for session in self.session_pool:
                try:
                    if 'page' in session and session['page']:
                        await session['page'].close()
                    
                    if 'context' in session and session['context']:
                        await session['context'].close()
                    
                    if 'browser' in session and session['browser']:
                        await session['browser'].close()
                    
                    if 'playwright' in session and session['playwright']:
                        await session['playwright'].stop()
                        
                except Exception as session_error:
                    logger.error(f"Error cleaning up session: {str(session_error)}")
            
            # Leeg de sessiepool
            self.session_pool = []
            
            # Reset eigen attributen
            self.browser = None
            self.context = None
            self.page = None
            self.is_initialized = False
            self.is_logged_in = False
            
            logger.info("All browser resources cleaned up")
            
        except Exception as e:
            logger.error(f"Error cleaning up browser resources: {str(e)}")
    
    async def solve_captcha(self) -> bool:
        """Solve CAPTCHA using 2Captcha service"""
        try:
            if not self.solver:
                logger.error("No 2Captcha API key provided, cannot solve CAPTCHA")
                return False
            
            # Detecteer het type captcha
            recaptcha_iframe = await self.page.query_selector('iframe[title*="recaptcha"]')
            
            if recaptcha_iframe:
                # Het is een reCAPTCHA
                logger.info("Detected reCAPTCHA")
                
                # Haal de sitekey op
                src = await recaptcha_iframe.get_attribute('src')
                sitekey = None
                if 'k=' in src:
                    sitekey = src.split('k=')[1].split('&')[0]
                
                if not sitekey:
                    logger.error("Could not extract reCAPTCHA sitekey")
                    return False
                
                logger.info(f"Found reCAPTCHA sitekey: {sitekey}")
                
                # Haal de huidige URL op
                url = self.page.url
                
                # Los de reCAPTCHA op met 2Captcha
                try:
                    # Dit is een blokkerende operatie, dus we gebruiken een executor
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None, 
                        lambda: self.solver.recaptcha(
                            sitekey=sitekey,
                            url=url
                        )
                    )
                    
                    g_response = result.get('code')
                    logger.info("Successfully solved reCAPTCHA")
                    
                    # Vul de captcha response in
                    await self.page.evaluate(f"""
                        document.querySelector('textarea#g-recaptcha-response').innerHTML = '{g_response}';
                        
                        // Trigger de callback
                        ___grecaptcha_cfg.clients[0].L.L.callback('{g_response}');
                    """)
                    
                    # Wacht even om de captcha te verwerken
                    await asyncio.sleep(2)
                    
                    # Klik op de inlogknop opnieuw als die er is
                    submit_button = await self.page.query_selector('button[type="submit"]')
                    if submit_button:
                        await submit_button.click()
                    
                    return True
                    
                except Exception as captcha_error:
                    logger.error(f"Error solving reCAPTCHA: {str(captcha_error)}")
                    return False
            
            # Andere soorten captcha's
            else:
                # Het kan een afbeelding captcha zijn
                captcha_img = await self.page.query_selector('img[class*="captcha"]')
                
                if captcha_img:
                    logger.info("Detected image CAPTCHA")
                    
                    # Neem een screenshot van de captcha
                    captcha_screenshot = await captcha_img.screenshot()
                    
                    # Los de afbeelding captcha op met 2Captcha
                    try:
                        # Dit is een blokkerende operatie, dus we gebruiken een executor
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(
                            None, 
                            lambda: self.solver.normal(
                                captcha_screenshot,
                                caseSensitive=1
                            )
                        )
                        
                        captcha_text = result.get('code')
                        logger.info(f"Successfully solved image CAPTCHA: {captcha_text}")
                        
                        # Vul de captcha text in
                        captcha_input = await self.page.query_selector('input[name="captcha"]')
                        if captcha_input:
                            await captcha_input.fill(captcha_text)
                            
                            # Klik op de inlogknop opnieuw
                            submit_button = await self.page.query_selector('button[type="submit"]')
                            if submit_button:
                                await submit_button.click()
                            
                            return True
                        else:
                            logger.error("Could not find captcha input field")
                            return False
                        
                    except Exception as captcha_error:
                        logger.error(f"Error solving image CAPTCHA: {str(captcha_error)}")
                        return False
                
                else:
                    logger.error("Unknown CAPTCHA type")
                    return False
            
        except Exception as e:
            logger.error(f"Error in solve_captcha: {str(e)}")
            return False
    
    async def refresh_session_if_needed(self):
        """Check if session is still valid and refresh if needed"""
        try:
            if not self.is_initialized or not self.is_logged_in:
                await self.initialize()
                return
            
            # Controleer of we nog steeds ingelogd zijn door naar een beveiligde pagina te gaan
            await self.page.goto("https://www.tradingview.com/chart/", timeout=30000)
            
            # Wacht even om de pagina te laden
            await asyncio.sleep(2)
            
            # Controleer of we nog steeds ingelogd zijn
            user_menu = await self.page.query_selector('button[data-name="user-menu"]')
            
            if not user_menu:
                logger.info("Session expired, logging in again")
                self.is_logged_in = False
                
                # Probeer opnieuw in te loggen
                if self.username and self.password:
                    await self.login()
                
        except Exception as e:
            logger.error(f"Error refreshing session: {str(e)}")
            self.is_logged_in = False
