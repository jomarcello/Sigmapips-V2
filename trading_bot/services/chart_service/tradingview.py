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
        """Initialize the browser with stealth mode"""
        try:
            logger.info("Initializing TradingView service browser")
            self.playwright = await async_playwright().start()
            
            # Gebruik een persistente browser context met stealth mode
            user_data_dir = os.path.join(os.getcwd(), "browser_data")
            os.makedirs(user_data_dir, exist_ok=True)
            
            # Verbeterde browser launch opties om detectie te vermijden
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
                    '--window-size=1920,1080',
                    '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                ],
                viewport={"width": 1920, "height": 1080},
                ignore_https_errors=True
            )
            
            # Maak een nieuwe pagina aan
            self.page = await self.browser.new_page()
            
            # Voeg stealth mode toe
            await self._add_stealth_mode()
            
            # Probeer eerst hardcoded cookies te laden
            if await self._load_hardcoded_cookies():
                return True
            
            # Als dat niet werkt, probeer cookies uit bestand te laden
            if await self._load_cookies_from_json():
                return True
            
            # Als dat niet werkt, probeer direct naar de chart pagina te gaan
            # Dit kan werken voor publieke charts zonder login
            await self.page.goto("https://www.tradingview.com/chart/", wait_until="networkidle")
            await self.page.wait_for_timeout(5000)
            
            # Controleer of we toegang hebben tot de chart
            if await self._can_access_charts():
                logger.info("Can access charts without login")
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
            
            # Ga direct naar de login pagina
            await self.page.goto("https://www.tradingview.com/signin/", wait_until="networkidle")
            await self.page.wait_for_timeout(5000)
            
            # Debug informatie
            logger.info(f"Page title: {await self.page.title()}")
            logger.info(f"Page URL: {self.page.url}")
            
            # Maak een screenshot voor debugging
            screenshot = await self.page.screenshot()
            with open("login_page.png", "wb") as f:
                f.write(screenshot)
            
            # Gebruik JavaScript om direct in te loggen
            login_success = await self.page.evaluate(f"""
                async () => {{
                    try {{
                        // Wacht tot de pagina volledig is geladen
                        await new Promise(resolve => setTimeout(resolve, 3000));
                        
                        // Zoek het email input veld
                        const emailInput = document.querySelector('input[name="username"], input[type="email"]');
                        if (!emailInput) {{
                            console.error('Email input not found');
                            return false;
                        }}
                        
                        // Vul het email veld in
                        emailInput.value = "{self.username}";
                        emailInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        
                        // Zoek de continue knop
                        const continueButton = Array.from(document.querySelectorAll('button')).find(
                            button => button.textContent.includes('Continue') || button.textContent.includes('Sign in')
                        );
                        
                        if (!continueButton) {{
                            console.error('Continue button not found');
                            return false;
                        }}
                        
                        // Klik op de continue knop
                        continueButton.click();
                        
                        // Wacht op het password veld
                        await new Promise(resolve => setTimeout(resolve, 3000));
                        
                        // Zoek het password input veld
                        const passwordInput = document.querySelector('input[name="password"], input[type="password"]');
                        if (!passwordInput) {{
                            console.error('Password input not found');
                            return false;
                        }}
                        
                        // Vul het password veld in
                        passwordInput.value = "{self.password}";
                        passwordInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        
                        // Zoek de sign in knop
                        const signInButton = Array.from(document.querySelectorAll('button')).find(
                            button => button.textContent.includes('Sign in')
                        );
                        
                        if (!signInButton) {{
                            console.error('Sign in button not found');
                            return false;
                        }}
                        
                        // Klik op de sign in knop
                        signInButton.click();
                        
                        // Wacht tot we zijn ingelogd
                        await new Promise(resolve => setTimeout(resolve, 5000));
                        
                        return true;
                    }} catch (error) {{
                        console.error('Error during login:', error);
                        return false;
                    }}
                }}
            """)
            
            logger.info(f"JavaScript login result: {login_success}")
            
            # Maak een screenshot na het inloggen
            screenshot = await self.page.screenshot()
            with open("after_login.png", "wb") as f:
                f.write(screenshot)
            
            # Controleer of we zijn ingelogd
            await self.page.goto("https://www.tradingview.com/chart/", wait_until="networkidle")
            logger.info(f"After login, URL: {self.page.url}")
            
            if await self._is_logged_in():
                logger.info("Successfully logged in to TradingView")
                self.is_logged_in = True
                
                # Sla cookies op voor toekomstige sessies
                await self._save_cookies()
                
                return True
            else:
                logger.error("Failed to log in to TradingView")
                
                # Maak een screenshot van de mislukte login
                screenshot = await self.page.screenshot()
                with open("login_failed.png", "wb") as f:
                    f.write(screenshot)
                
                return False
        except Exception as e:
            logger.error(f"Error logging in to TradingView: {str(e)}")
            return False
            
    async def _is_logged_in(self) -> bool:
        """Check if we are logged in to TradingView using JavaScript"""
        try:
            # Gebruik JavaScript om te controleren of we zijn ingelogd
            is_logged_in = await self.page.evaluate("""
                () => {
                    try {
                        // Methode 1: Controleer op de logged-in user menu button
                        const userMenuLogged = document.querySelector('.tv-header__user-menu-button--logged');
                        if (userMenuLogged) return true;
                        
                        // Methode 2: Controleer op de aanwezigheid van de username in de DOM
                        const usernameElement = document.querySelector('.tv-header__dropdown-text');
                        if (usernameElement) return true;
                        
                        // Methode 3: Controleer of de anonymous user menu button afwezig is
                        const anonymousButton = document.querySelector('.tv-header__user-menu-button--anonymous');
                        if (!anonymousButton) return true;
                        
                        // Methode 4: Controleer op de aanwezigheid van bepaalde elementen die alleen zichtbaar zijn voor ingelogde gebruikers
                        const userSpecificElements = document.querySelector('.js-user-menu-button');
                        if (userSpecificElements) return true;
                        
                        // Methode 5: Controleer of we toegang hebben tot bepaalde functies
                        const premiumElements = document.querySelector('.js-upgrade-link');
                        if (premiumElements) return true;
                        
                        return false;
                    } catch (error) {
                        console.error('Error checking if logged in:', error);
                        return false;
                    }
                }
            """)
            
            logger.info(f"JavaScript login check result: {is_logged_in}")
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
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1774268901.267212,
                    "hostOnly": False,
                    "httpOnly": False,
                    "name": "cookiesSettings",
                    "path": "/",
                    "sameSite": None,
                    "secure": False,
                    "session": False,
                    "storeId": None,
                    "value": "{\"analytics\":true,\"advertising\":true}"
                },
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1775641803.552845,
                    "hostOnly": False,
                    "httpOnly": False,
                    "name": "_ga",
                    "path": "/",
                    "sameSite": None,
                    "secure": False,
                    "session": False,
                    "storeId": None,
                    "value": "GA1.1.1638786280.1739708898"
                },
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1774268901.269229,
                    "hostOnly": False,
                    "httpOnly": False,
                    "name": "cookiePrivacyPreferenceBannerProduction",
                    "path": "/",
                    "sameSite": None,
                    "secure": False,
                    "session": False,
                    "storeId": None,
                    "value": "accepted"
                },
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1754298365,
                    "hostOnly": False,
                    "httpOnly": False,
                    "name": "__eoi",
                    "path": "/",
                    "sameSite": "no_restriction",
                    "secure": True,
                    "session": False,
                    "storeId": None,
                    "value": "ID=8d75d90be25efe42:T=1738746365:RT=1741081804:S=AA-AfjYn18duLyZaIYcUb54Akz0p"
                },
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1772115758.316634,
                    "hostOnly": False,
                    "httpOnly": True,
                    "name": "device_t",
                    "path": "/",
                    "sameSite": "no_restriction",
                    "secure": True,
                    "session": False,
                    "storeId": None,
                    "value": "d2J3Zzoy.iSC9qEryjAHVQuFl3gYq0aWdSm_jh9N2PtxifF84_n0"
                },
                {
                    "domain": "www.tradingview.com",
                    "expirationDate": 1755634814,
                    "hostOnly": True,
                    "httpOnly": False,
                    "name": "g_state",
                    "path": "/",
                    "sameSite": None,
                    "secure": False,
                    "session": False,
                    "storeId": None,
                    "value": "{\"i_l\":0}"
                },
                {
                    "domain": "www.tradingview.com",
                    "expirationDate": 1741082933,
                    "hostOnly": True,
                    "httpOnly": False,
                    "name": "_dd_s",
                    "path": "/",
                    "sameSite": "strict",
                    "secure": False,
                    "session": False,
                    "storeId": None,
                    "value": "rum=0&expire=1741082882897"
                },
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1774707569,
                    "hostOnly": False,
                    "httpOnly": False,
                    "name": "__gads",
                    "path": "/",
                    "sameSite": "no_restriction",
                    "secure": True,
                    "session": False,
                    "storeId": None,
                    "value": "ID=1803660b410ec0f9:T=1741011569:RT=1741081804:S=ALNI_Mb1QtiHTWes_s1oAM6CKjKxqRomWw"
                },
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1774707569,
                    "hostOnly": False,
                    "httpOnly": False,
                    "name": "__gpi",
                    "path": "/",
                    "sameSite": "no_restriction",
                    "secure": True,
                    "session": False,
                    "storeId": None,
                    "value": "UID=00001053d14ca0b5:T=1741011569:RT=1741081804:S=ALNI_MYOLPfDFZDFjgXFvIpB1ZPhF8FkQw"
                },
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1775641979.545086,
                    "hostOnly": False,
                    "httpOnly": False,
                    "name": "_ga_YVVRYGL0E0",
                    "path": "/",
                    "sameSite": None,
                    "secure": False,
                    "session": False,
                    "storeId": None,
                    "value": "GS1.1.1741081803.12.1.1741081979.60.0.0"
                },
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1775641804.606804,
                    "hostOnly": False,
                    "httpOnly": False,
                    "name": "_sp_id.cf1a",
                    "path": "/",
                    "sameSite": "no_restriction",
                    "secure": True,
                    "session": False,
                    "storeId": None,
                    "value": "6e54c09e-b492-4e55-8c18-928eaf060eff.1738746363.10.1741081805.1741011575.b03a5bf1-224d-4b34-88c3-246f147de90b.c45aa8b5-1d3d-49fc-bae1-4e626acfc937.ccd5fee3-941b-43f0-af4a-6d7e6a9e10a0.1741081802448.8"
                },
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1775571538.003148,
                    "hostOnly": False,
                    "httpOnly": False,
                    "name": "cachec",
                    "path": "/",
                    "sameSite": None,
                    "secure": False,
                    "session": False,
                    "storeId": None,
                    "value": "undefined"
                },
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1775571537.913522,
                    "hostOnly": False,
                    "httpOnly": False,
                    "name": "etg",
                    "path": "/",
                    "sameSite": None,
                    "secure": False,
                    "session": False,
                    "storeId": None,
                    "value": "undefined"
                },
                {
                    "domain": ".tradingview.com",
                    "expirationDate": 1749046958.318503,
                    "hostOnly": False,
                    "httpOnly": True,
                    "name": "sessionid",
                    "path": "/",
                    "sameSite": "lax",
                    "secure": True,
                    "session": False,
                    "storeId": None,
                    "value": "z90l85p2anlgdwfppsrdnnfantz48z1o"
                },
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
            
    async def _add_stealth_mode(self):
        """Add stealth mode to avoid detection"""
        try:
            # Verberg WebDriver
            await self.page.evaluate("""
                () => {
                    // Verberg dat we Playwright/Selenium gebruiken
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => false,
                    });
                    
                    // Verberg automation flags
                    window.navigator.chrome = {
                        runtime: {},
                    };
                    
                    // Voeg plugins toe
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [
                            {
                                0: {type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format"},
                                description: "Portable Document Format",
                                filename: "internal-pdf-viewer",
                                length: 1,
                                name: "Chrome PDF Plugin"
                            },
                            {
                                0: {type: "application/pdf", suffixes: "pdf", description: "Portable Document Format"},
                                description: "Portable Document Format",
                                filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai",
                                length: 1,
                                name: "Chrome PDF Viewer"
                            },
                            {
                                0: {type: "application/x-nacl", suffixes: "", description: "Native Client Executable"},
                                1: {type: "application/x-pnacl", suffixes: "", description: "Portable Native Client Executable"},
                                description: "Native Client",
                                filename: "internal-nacl-plugin",
                                length: 2,
                                name: "Native Client"
                            }
                        ],
                    });
                    
                    // Voeg languages toe
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['nl-NL', 'nl', 'en-US', 'en'],
                    });
                    
                    // Verberg automation-specifieke functies
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                }
            """)
            
            logger.info("Added stealth mode to browser")
            return True
        except Exception as e:
            logger.error(f"Error adding stealth mode: {str(e)}")
            return False
            
    async def _can_access_charts(self) -> bool:
        """Check if we can access charts without login"""
        try:
            # Controleer of we de chart container kunnen zien
            chart_container = await self.page.query_selector(".chart-container")
            if chart_container:
                logger.info("Chart container found, can access charts")
                return True
            
            # Controleer of we de chart markup table kunnen zien
            chart_markup = await self.page.query_selector(".chart-markup-table")
            if chart_markup:
                logger.info("Chart markup found, can access charts")
                return True
            
            # Controleer of we de layout area kunnen zien
            layout_area = await self.page.query_selector(".layout__area--center")
            if layout_area:
                logger.info("Layout area found, can access charts")
                return True
            
            logger.warning("Cannot access charts without login")
            return False
        except Exception as e:
            logger.error(f"Error checking chart access: {str(e)}")
            return False
            
    async def get_chart_screenshot(self, chart_url: str) -> Optional[bytes]:
        """Get a screenshot of a TradingView chart with indicators"""
        try:
            logger.info(f"Getting screenshot of chart: {chart_url}")
            
            # Ga naar de chart pagina
            await self.page.goto(chart_url, wait_until="networkidle")
            await self.page.wait_for_timeout(10000)  # Wacht extra tijd voor het laden van de chart
            
            # Debug informatie
            logger.info(f"Page title: {await self.page.title()}")
            logger.info(f"Page URL: {self.page.url}")
            
            # Controleer of we op een publieke chart pagina zijn
            if "tradingview.com/chart/" in self.page.url or "tradingview.com/x/" in self.page.url:
                logger.info("On chart page, taking screenshot")
                
                # Wacht tot de chart is geladen
                try:
                    # Wacht op verschillende mogelijke selectors voor de chart
                    for selector in [".chart-markup-table", ".chart-container", ".layout__area--center"]:
                        try:
                            await self.page.wait_for_selector(selector, timeout=5000)
                            logger.info(f"Chart element found with selector: {selector}")
                            break
                        except:
                            continue
                    
                    # Wacht extra tijd voor het laden van indicators
                    await self.page.wait_for_timeout(15000)
                    
                    # Verberg UI elementen voor een schonere screenshot
                    await self.page.evaluate("""
                        () => {
                            try {
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
                                
                                // Verberg andere UI elementen
                                const otherElements = document.querySelectorAll('.chart-controls-bar');
                                otherElements.forEach(el => {
                                    if (el) el.style.display = 'none';
                                });
                                
                                // Verberg popup dialogs
                                const dialogs = document.querySelectorAll('.tv-dialog, .tv-dialog__modal-wrap');
                                dialogs.forEach(el => {
                                    if (el) el.style.display = 'none';
                                });
                                
                                // Verberg login prompts
                                const loginPrompts = document.querySelectorAll('.tv-dialog--login, .tv-dialog--sign-in');
                                loginPrompts.forEach(el => {
                                    if (el) el.style.display = 'none';
                                });
                            } catch (e) {
                                console.error("Error hiding UI elements:", e);
                            }
                        }
                    """)
                    
                    # Wacht even na het verbergen van UI elementen
                    await self.page.wait_for_timeout(1000)
                    
                    # Probeer verschillende selectors voor de chart container
                    for selector in [".chart-container", ".layout__area--center", ".chart-markup-table"]:
                        try:
                            chart_element = await self.page.query_selector(selector)
                            if chart_element:
                                logger.info(f"Taking screenshot of chart element with selector: {selector}")
                                screenshot = await chart_element.screenshot(type="png")
                                logger.info("Successfully took screenshot of chart element")
                                return screenshot
                        except Exception as e:
                            logger.warning(f"Error taking screenshot with selector {selector}: {str(e)}")
                    
                    # Als geen van de selectors werkt, maak een screenshot van de hele pagina
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
                    
                    # Probeer een screenshot van de hele pagina
                    return await self.page.screenshot(full_page=False, type="png")
            else:
                # We zijn niet op een chart pagina, probeer naar de chart pagina te navigeren
                logger.warning(f"Not on chart page, current URL: {self.page.url}")
                
                # Probeer naar de chart pagina te navigeren via de URL
                chart_id = chart_url.split("/")[-2]
                public_url = f"https://www.tradingview.com/x/{chart_id}/"
                
                logger.info(f"Trying public chart URL: {public_url}")
                await self.page.goto(public_url, wait_until="networkidle")
                await self.page.wait_for_timeout(10000)
                
                # Maak een screenshot van de pagina
                return await self.page.screenshot(full_page=False, type="png")
            
        except Exception as e:
            logger.error(f"Error getting chart screenshot: {str(e)}")
            
            # Probeer een screenshot van de huidige pagina als fallback
            try:
                return await self.page.screenshot(full_page=False, type="png")
            except:
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
