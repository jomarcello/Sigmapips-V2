import os
import time
import pickle
import logging
from typing import Optional
import asyncio
from playwright.async_api import async_playwright

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
            
            # Gebruik een niet-headless browser met Xvfb
            self.browser = await self.playwright.chromium.launch(
                headless=False,  # Gebruik een niet-headless browser
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--single-process',
                    '--disable-gpu',
                    '--display=' + os.getenv('DISPLAY', ':99'),  # Gebruik Xvfb display
                    '--window-size=1920,1080'  # Grotere window size
                ]
            )
            
            # Gebruik een context met meer realistische browser eigenschappen
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
                locale="en-US",
                timezone_id="Europe/Amsterdam",
                permissions=["geolocation"],
                color_scheme="light"
            )
            
            # Voeg extra headers toe om meer op een echte browser te lijken
            await self.context.set_extra_http_headers({
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br"
            })
            
            self.page = await self.context.new_page()
            
            # Probeer in te loggen met cookies
            if await self._load_cookies():
                logger.info("Loaded cookies, checking if logged in")
                await self.page.goto("https://www.tradingview.com/chart/", wait_until="networkidle")
                if await self._is_logged_in():
                    logger.info("Successfully logged in with cookies")
                    self.is_logged_in = True
                    return True
            
            # Als cookies niet werken, log in met gebruikersnaam en wachtwoord
            if self.username and self.password:
                logger.info("Logging in with username and password")
                return await self.login()
            else:
                logger.warning("No TradingView credentials provided")
                return False
                
        except Exception as e:
            logger.error(f"Error initializing TradingView service: {str(e)}")
            return False
            
    async def login(self) -> bool:
        """Login to TradingView"""
        try:
            logger.info("Logging in to TradingView")
            
            # Ga direct naar de login pagina
            await self.page.goto("https://www.tradingview.com/chart/", wait_until="networkidle")
            await self.page.wait_for_timeout(3000)
            
            # Debug informatie
            logger.info(f"Page title: {await self.page.title()}")
            logger.info(f"Page URL: {self.page.url}")
            
            # Maak een screenshot voor debugging
            screenshot = await self.page.screenshot()
            with open("chart_page.png", "wb") as f:
                f.write(screenshot)
            
            # Klik op de Sign In knop (deze is altijd aanwezig op de chart pagina)
            try:
                # Zoek de user menu knop
                user_menu = await self.page.query_selector('.tv-header__user-menu-button--anonymous')
                if user_menu:
                    logger.info("Found anonymous user menu button, clicking...")
                    await user_menu.click()
                    await self.page.wait_for_timeout(1000)
                    
                    # Zoek de Sign In knop in het menu
                    sign_in_button = await self.page.query_selector('a[href="/signin/"]')
                    if sign_in_button:
                        logger.info("Found sign in button, clicking...")
                        await sign_in_button.click()
                        await self.page.wait_for_timeout(3000)
                    else:
                        logger.warning("Sign in button not found in menu")
                else:
                    logger.warning("Anonymous user menu button not found")
                    
                    # Probeer direct naar de signin pagina te gaan
                    await self.page.goto("https://www.tradingview.com/signin/", wait_until="networkidle")
            except Exception as e:
                logger.warning(f"Error finding sign in button: {str(e)}")
            
            # Wacht op het email input veld
            try:
                email_input = await self.page.wait_for_selector('input[name="username"], input[type="email"]', timeout=10000)
                if email_input:
                    logger.info("Found email input, filling...")
                    await email_input.fill(self.username)
                    await self.page.wait_for_timeout(1000)
                    
                    # Zoek de continue knop
                    continue_button = await self.page.query_selector('button[type="submit"]')
                    if continue_button:
                        logger.info("Found continue button, clicking...")
                        await continue_button.click()
                        await self.page.wait_for_timeout(3000)
                    else:
                        logger.warning("Continue button not found")
                else:
                    logger.warning("Email input not found")
            except Exception as e:
                logger.warning(f"Error with email input: {str(e)}")
            
            # Wacht op het password input veld
            try:
                password_input = await self.page.wait_for_selector('input[name="password"], input[type="password"]', timeout=10000)
                if password_input:
                    logger.info("Found password input, filling...")
                    await password_input.fill(self.password)
                    await self.page.wait_for_timeout(1000)
                    
                    # Zoek de sign in knop
                    sign_in_button = await self.page.query_selector('button[type="submit"]')
                    if sign_in_button:
                        logger.info("Found sign in button, clicking...")
                        await sign_in_button.click()
                        await self.page.wait_for_timeout(5000)
                    else:
                        logger.warning("Sign in button not found")
                else:
                    logger.warning("Password input not found")
            except Exception as e:
                logger.warning(f"Error with password input: {str(e)}")
            
            # Controleer of we zijn ingelogd
            await self.page.goto("https://www.tradingview.com/chart/", wait_until="networkidle")
            
            if await self._is_logged_in():
                logger.info("Successfully logged in to TradingView")
                self.is_logged_in = True
                
                # Sla cookies op voor toekomstige sessies
                await self._save_cookies()
                
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
