import os
import time
import pickle
import logging
from typing import Optional
import asyncio
from playwright.async_api import async_playwright
import json

logger = logging.getLogger(__name__)

class TradingViewService:
    """Service voor interactie met TradingView"""
    
    def __init__(self):
        """Initialize TradingView service"""
        self.username = os.getenv("TRADINGVIEW_USERNAME")
        self.password = os.getenv("TRADINGVIEW_PASSWORD")
        self.debug = os.getenv("TRADINGVIEW_DEBUG", "false").lower() == "true"
        self.browser = None
        self.context = None
        self.page = None
        self.cookies_file = "tradingview_cookies.pkl"
        self.is_logged_in = False
        logger.info("TradingView service initialized")
        if self.debug:
            logger.info(f"Debug mode enabled. Username: {self.username}")
        
    async def initialize(self):
        """Initialize the browser"""
        try:
            logger.info("Initializing TradingView service browser")
            self.playwright = await async_playwright().start()
            
            # Gebruik een persistente browser context
            user_data_dir = os.path.join(os.getcwd(), "browser_data")
            os.makedirs(user_data_dir, exist_ok=True)
            
            self.browser = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--disable-gpu',
                    '--display=' + os.getenv('DISPLAY', ':99'),
                    '--window-size=1920,1080'
                ]
            )
            
            self.page = await self.browser.new_page()
            
            # Probeer eerst hardcoded cookies te laden
            if await self._load_hardcoded_cookies():
                return True
            
            # Als dat niet werkt, probeer cookies uit bestand te laden
            if await self._load_cookies_from_json():
                return True
            
            # Als dat niet werkt, controleer of we al ingelogd zijn
            await self.page.goto("https://www.tradingview.com/chart/", wait_until="networkidle")
            
            if await self._is_logged_in():
                logger.info("Already logged in to TradingView")
                self.is_logged_in = True
                return True
            
            # Als we niet ingelogd zijn, probeer in te loggen
            if self.username and self.password:
                logger.info("Not logged in, trying to log in")
                return await self.login()
            else:
                logger.warning("No TradingView credentials provided")
                return False
                
        except Exception as e:
            logger.error(f"Error initializing TradingView service: {str(e)}")
            return False
            
    async def login(self) -> bool:
        """Login to TradingView using direct navigation"""
        try:
            logger.info("Logging in to TradingView using direct navigation")
            
            # Ga direct naar de chart pagina
            await self.page.goto("https://www.tradingview.com/chart/", wait_until="networkidle")
            
            # Wacht even om de pagina te laten laden
            await self.page.wait_for_timeout(5000)
            
            # Gebruik JavaScript om direct in te loggen
            login_success = await self.page.evaluate(f"""
                async () => {{
                    try {{
                        // Probeer de TradingView API te gebruiken om in te loggen
                        if (window.TradingView && window.TradingView.User) {{
                            // Als de TradingView API beschikbaar is
                            const loginResult = await window.TradingView.User.login({{
                                username: "{self.username}",
                                password: "{self.password}"
                            }});
                            return loginResult && loginResult.success;
                        }}
                        
                        // Als de API niet beschikbaar is, probeer de login knop te vinden
                        const userMenuButton = document.querySelector('.tv-header__user-menu-button--anonymous');
                        if (userMenuButton) {{
                            userMenuButton.click();
                            await new Promise(resolve => setTimeout(resolve, 1000));
                            
                            // Zoek naar de sign in knop in het menu
                            const signInButton = Array.from(document.querySelectorAll('a')).find(
                                a => a.href && a.href.includes('/signin/')
                            );
                            if (signInButton) {{
                                signInButton.click();
                                await new Promise(resolve => setTimeout(resolve, 3000));
                                
                                // Vul het email veld in
                                const emailInput = document.querySelector('input[name="username"], input[type="email"]');
                                if (emailInput) {{
                                    emailInput.value = "{self.username}";
                                    emailInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    await new Promise(resolve => setTimeout(resolve, 1000));
                                    
                                    // Klik op de continue knop
                                    const continueButton = document.querySelector('button[type="submit"]');
                                    if (continueButton) {{
                                        continueButton.click();
                                        await new Promise(resolve => setTimeout(resolve, 3000));
                                        
                                        // Vul het wachtwoord veld in
                                        const passwordInput = document.querySelector('input[name="password"], input[type="password"]');
                                        if (passwordInput) {{
                                            passwordInput.value = "{self.password}";
                                            passwordInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                            await new Promise(resolve => setTimeout(resolve, 1000));
                                            
                                            // Klik op de sign in knop
                                            const signInButton = document.querySelector('button[type="submit"]');
                                            if (signInButton) {{
                                                signInButton.click();
                                                return true;
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                        }}
                        
                        return false;
                    }} catch (e) {{
                        console.error("Error in login script:", e);
                        return false;
                    }}
                }}
            """)
            
            logger.info(f"JavaScript login result: {login_success}")
            
            # Wacht even om de login te laten verwerken
            await self.page.wait_for_timeout(5000)
            
            # Controleer of we zijn ingelogd
            if await self._is_logged_in():
                logger.info("Successfully logged in to TradingView")
                self.is_logged_in = True
                return True
            else:
                logger.error("Failed to log in to TradingView")
                return False
            
        except Exception as e:
            logger.error(f"Error logging in to TradingView: {str(e)}")
            return False
            
    async def _is_logged_in(self) -> bool:
        """Check if we are logged in to TradingView"""
        try:
            # Controleer of de user menu zichtbaar is
            try:
                # Gebruik een meer specifieke selector
                user_menu = self.page.locator('.tv-header__user-menu-button--logged')
                is_visible = await user_menu.is_visible()
                logger.info(f"Logged in user menu visible: {is_visible}")
                return is_visible
            except Exception:
                # Probeer een alternatieve methode
                is_logged_in = await self.page.evaluate("""
                    () => {
                        // Controleer of er elementen zijn die alleen zichtbaar zijn voor ingelogde gebruikers
                        const userMenuLogged = document.querySelector('.tv-header__user-menu-button--logged');
                        const userAvatar = document.querySelector('.tv-header__user-avatar');
                        const userMenu = document.querySelector('.js-header-user-menu-button');
                        
                        // Controleer of er elementen zijn die alleen zichtbaar zijn voor niet-ingelogde gebruikers
                        const signInButton = document.querySelector('a[href="/signin/"]');
                        const anonymousButton = document.querySelector('.tv-header__user-menu-button--anonymous');
                        
                        // Als er elementen zijn voor ingelogde gebruikers en geen elementen voor niet-ingelogde gebruikers
                        return (userMenuLogged || userAvatar) && !signInButton && !anonymousButton;
                    }
                """)
                logger.info(f"JavaScript check for logged in: {is_logged_in}")
                return is_logged_in
        except Exception as e:
            logger.error(f"Error checking if logged in: {str(e)}")
            return False
            
    async def _save_cookies(self) -> bool:
        """Save cookies for future sessions"""
        try:
            cookies = await self.context.cookies()
            with open(self.cookies_file, "wb") as f:
                pickle.dump(cookies, f)
            logger.info("Saved TradingView cookies")
            return True
        except Exception as e:
            logger.error(f"Error saving cookies: {str(e)}")
            return False
            
    async def _load_cookies(self) -> bool:
        """Load cookies from file"""
        try:
            if os.path.exists(self.cookies_file):
                with open(self.cookies_file, "rb") as f:
                    cookies = pickle.load(f)
                await self.context.add_cookies(cookies)
                logger.info("Loaded TradingView cookies")
                return True
            return False
        except Exception as e:
            logger.error(f"Error loading cookies: {str(e)}")
            return False
            
    async def _load_cookies_from_json(self) -> bool:
        """Load cookies from JSON file"""
        try:
            cookies_file = os.path.join(os.getcwd(), "tradingview_cookies.json")
            if os.path.exists(cookies_file):
                logger.info(f"Loading cookies from {cookies_file}")
                with open(cookies_file, "r") as f:
                    cookies = json.load(f)
                
                # Voeg cookies toe aan de browser context
                await self.browser.add_cookies(cookies)
                logger.info("Loaded TradingView cookies from JSON file")
                
                # Controleer of we zijn ingelogd
                await self.page.goto("https://www.tradingview.com/chart/", wait_until="networkidle")
                if await self._is_logged_in():
                    logger.info("Successfully logged in with cookies")
                    self.is_logged_in = True
                    return True
                else:
                    logger.warning("Cookies loaded but not logged in")
                    return False
            else:
                logger.warning(f"No cookies file found at {cookies_file}")
                return False
        except Exception as e:
            logger.error(f"Error loading cookies from file: {str(e)}")
            return False
            
    async def _load_hardcoded_cookies(self) -> bool:
        """Load hardcoded cookies"""
        try:
            # Hardcoded cookies
            cookies = [
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1741083604,
                    "hostOnly": False,
                    "httpOnly": False,
                    "name": "_sp_ses.cf1a",
                    "path": "/",
                    "sameSite": "no_restriction",
                    "secure": True,
                    "session": False,
                    "storeId": None,
                    "value": "*"
                },
                # ... rest van je cookies ...
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1749046958.319093,
                    "hostOnly": False,
                    "httpOnly": True,
                    "name": "sessionid_sign",
                    "path": "/",
                    "sameSite": "lax",
                    "secure": True,
                    "session": False,
                    "storeId": None,
                    "value": "v3:KfkuD+pEvQ4AjbHnN29dcdxeG7URIo4ZviOTuhFvJrY="
                }
            ]
            
            # Verwijder onnodige velden die Playwright niet accepteert
            for cookie in cookies:
                if "storeId" in cookie:
                    del cookie["storeId"]
                if "hostOnly" in cookie:
                    del cookie["hostOnly"]
                if "session" in cookie:
                    del cookie["session"]
            
            # Voeg cookies toe aan de browser context
            await self.browser.add_cookies(cookies)
            logger.info("Loaded hardcoded TradingView cookies")
            
            # Controleer of we zijn ingelogd
            await self.page.goto("https://www.tradingview.com/chart/", wait_until="networkidle")
            if await self._is_logged_in():
                logger.info("Successfully logged in with hardcoded cookies")
                self.is_logged_in = True
                return True
            else:
                logger.warning("Hardcoded cookies loaded but not logged in")
                return False
        except Exception as e:
            logger.error(f"Error loading hardcoded cookies: {str(e)}")
            return False
            
    async def get_chart_screenshot(self, chart_url: str) -> Optional[bytes]:
        """Get a screenshot of a TradingView chart with indicators"""
        try:
            if not self.is_logged_in:
                logger.warning("Not logged in to TradingView, trying to log in")
                if not await self.login():
                    logger.error("Failed to log in to TradingView")
                    return None
            
            logger.info(f"Getting screenshot of chart: {chart_url}")
            
            # Ga naar de chart pagina
            await self.page.goto(chart_url, wait_until="networkidle")
            await self.page.wait_for_timeout(5000)  # Wacht extra tijd voor het laden van de chart
            
            # Debug informatie
            logger.info(f"Page title: {await self.page.title()}")
            logger.info(f"Page URL: {self.page.url}")
            
            # Wacht tot de chart is geladen
            try:
                await self.page.wait_for_selector(".chart-markup-table", timeout=30000)
                logger.info("Chart markup table found")
                
                # Wacht extra tijd voor het laden van indicators
                await self.page.wait_for_timeout(10000)
                
                # Verberg UI elementen voor een schonere screenshot
                await self.page.evaluate("""
                    () => {
                        // Verberg header
                        const header = document.querySelector('.header-chart-panel');
                        if (header) header.style.display = 'none';
                        
                        // Verberg toolbar
                        const toolbar = document.querySelector('.chart-toolbar');
                        if (toolbar) toolbar.style.display = 'none';
                        
                        // Verberg andere UI elementen
                        const elements = document.querySelectorAll('.tv-side-toolbar, .tv-floating-toolbar, .tv-dialog, .tv-toast');
                        elements.forEach(el => {
                            if (el) el.style.display = 'none';
                        });
                        
                        // Verberg de drawing tools
                        const drawingTools = document.querySelector('.drawing-toolbar');
                        if (drawingTools) drawingTools.style.display = 'none';
                        
                        // Verberg de watchlist
                        const watchlist = document.querySelector('.tv-watchlist');
                        if (watchlist) watchlist.style.display = 'none';
                    }
                """)
                
                # Maak een screenshot van alleen de chart
                chart_element = await self.page.query_selector(".chart-container")
                if chart_element:
                    screenshot = await chart_element.screenshot(type="png")
                    logger.info("Successfully took screenshot of chart element")
                    return screenshot
                else:
                    logger.warning("Chart container element not found, taking full page screenshot")
                    screenshot = await self.page.screenshot(full_page=False, type="png")
                    return screenshot
                
            except Exception as e:
                logger.error(f"Error waiting for chart to load: {str(e)}")
                
                # Maak een screenshot van de pagina voor debugging
                screenshot = await self.page.screenshot()
                with open("chart_load_failed.png", "wb") as f:
                    f.write(screenshot)
                logger.info("Saved chart load failed screenshot to chart_load_failed.png")
                
                return None
            
        except Exception as e:
            logger.error(f"Error getting chart screenshot: {str(e)}")
            return None
            
    async def cleanup(self):
        """Clean up resources"""
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("TradingView service resources cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up TradingView service: {str(e)}") 
