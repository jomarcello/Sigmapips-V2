import os
import logging
import asyncio
import json
from typing import Optional
from pyppeteer import launch
from urllib.parse import quote

logger = logging.getLogger(__name__)

class TradingViewPuppeteerService:
    """Service voor interactie met TradingView via Puppeteer"""
    
    def __init__(self):
        """Initialize TradingView service"""
        self.username = os.getenv("TRADINGVIEW_USERNAME")
        self.password = os.getenv("TRADINGVIEW_PASSWORD")
        self.debug = os.getenv("TRADINGVIEW_DEBUG", "false").lower() == "true"
        self.browser = None
        self.page = None
        self.cookies_file = "tradingview_cookies.json"
        self.is_logged_in = False
        logger.info("TradingView Puppeteer service initialized")
        if self.debug:
            logger.info(f"Debug mode enabled. Username: {self.username}")
        
    async def initialize(self):
        """Initialize the browser with stealth mode"""
        try:
            logger.info("Initializing TradingView Puppeteer service browser")
            
            # Verbeterde browser launch opties om detectie te vermijden
            self.browser = await launch({
                'headless': False,
                'args': [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--disable-gpu',
                    f'--display={os.getenv("DISPLAY", ":99")}',
                    '--window-size=1920,1080',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--disable-site-isolation-trials'
                ],
                'ignoreHTTPSErrors': True,
                'userDataDir': os.path.join(os.getcwd(), "puppeteer_data")
            })
            
            # Maak een nieuwe pagina aan
            self.page = await self.browser.newPage()
            
            # Stel viewport in
            await self.page.setViewport({'width': 1920, 'height': 1080})
            
            # Stel user agent in
            await self.page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
            
            # Voeg stealth mode toe
            await self._add_stealth_mode()
            
            # Probeer eerst cookies uit bestand te laden
            if await self._load_cookies_from_json():
                return True
            
            # Als dat niet werkt, probeer direct naar de chart pagina te gaan
            # Dit kan werken voor publieke charts zonder login
            await self.page.goto("https://www.tradingview.com/chart/", {
                'waitUntil': 'networkidle0',
                'timeout': 60000
            })
            await asyncio.sleep(5)
            
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
            logger.error(f"Error initializing TradingView Puppeteer service: {str(e)}")
            return False
            
    async def _add_stealth_mode(self):
        """Add stealth mode to avoid detection"""
        try:
            # Verberg WebDriver
            await self.page.evaluateOnNewDocument("""
                () => {
                    // Verberg dat we Puppeteer gebruiken
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
                    
                    // Voeg WebGL toe
                    const getParameter = WebGLRenderingContext.getParameter;
                    WebGLRenderingContext.prototype.getParameter = function(parameter) {
                        // UNMASKED_VENDOR_WEBGL
                        if (parameter === 37445) {
                            return 'Intel Inc.';
                        }
                        // UNMASKED_RENDERER_WEBGL
                        if (parameter === 37446) {
                            return 'Intel Iris OpenGL Engine';
                        }
                        return getParameter.apply(this, arguments);
                    };
                }
            """)
            
            logger.info("Added stealth mode to browser")
            return True
        except Exception as e:
            logger.error(f"Error adding stealth mode: {str(e)}")
            return False
            
    async def _load_cookies_from_json(self) -> bool:
        """Load cookies from JSON file"""
        try:
            if os.path.exists(self.cookies_file):
                logger.info(f"Loading cookies from {self.cookies_file}")
                with open(self.cookies_file, 'r') as f:
                    cookies = json.load(f)
                
                # Voeg cookies toe aan de browser
                for cookie in cookies:
                    await self.page.setCookie(cookie)
                
                # Ga naar TradingView om te controleren of we zijn ingelogd
                await self.page.goto("https://www.tradingview.com/chart/", {
                    'waitUntil': 'networkidle0',
                    'timeout': 60000
                })
                
                # Controleer of we zijn ingelogd
                if await self._is_logged_in():
                    logger.info("Successfully logged in with cookies")
                    self.is_logged_in = True
                    return True
                else:
                    logger.warning("Cookies loaded but not logged in")
                    return False
            else:
                logger.warning(f"Cookies file {self.cookies_file} not found")
                return False
        except Exception as e:
            logger.error(f"Error loading cookies: {str(e)}")
            return False
            
    async def _save_cookies(self) -> bool:
        """Save cookies to JSON file"""
        try:
            cookies = await self.page.cookies()
            with open(self.cookies_file, 'w') as f:
                json.dump(cookies, f)
            logger.info(f"Saved cookies to {self.cookies_file}")
            return True
        except Exception as e:
            logger.error(f"Error saving cookies: {str(e)}")
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
            
    async def _can_access_charts(self) -> bool:
        """Check if we can access charts without login"""
        try:
            # Controleer of we de chart container kunnen zien
            chart_container = await self.page.querySelector(".chart-container")
            if chart_container:
                logger.info("Chart container found, can access charts")
                return True
            
            # Controleer of we de chart markup table kunnen zien
            chart_markup = await self.page.querySelector(".chart-markup-table")
            if chart_markup:
                logger.info("Chart markup found, can access charts")
                return True
            
            # Controleer of we de layout area kunnen zien
            layout_area = await self.page.querySelector(".layout__area--center")
            if layout_area:
                logger.info("Layout area found, can access charts")
                return True
            
            logger.warning("Cannot access charts without login")
            return False
        except Exception as e:
            logger.error(f"Error checking chart access: {str(e)}")
            return False
            
    async def login(self) -> bool:
        """Login to TradingView using direct navigation"""
        try:
            logger.info("Logging in to TradingView using direct navigation")
            
            # Ga direct naar de login pagina
            await self.page.goto("https://www.tradingview.com/signin/", {
                'waitUntil': 'networkidle0',
                'timeout': 60000
            })
            await asyncio.sleep(5)
            
            # Debug informatie
            logger.info(f"Page title: {await self.page.title()}")
            logger.info(f"Page URL: {self.page.url}")
            
            # Maak een screenshot voor debugging
            await self.page.screenshot({'path': 'login_page.png'})
            
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
            await self.page.screenshot({'path': 'after_login.png'})
            
            # Controleer of we zijn ingelogd
            await self.page.goto("https://www.tradingview.com/chart/", {
                'waitUntil': 'networkidle0',
                'timeout': 60000
            })
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
                await self.page.screenshot({'path': 'login_failed.png'})
                
                return False
        except Exception as e:
            logger.error(f"Error logging in to TradingView: {str(e)}")
            return False
            
    async def get_chart_screenshot(self, chart_url: str) -> Optional[bytes]:
        """Get a screenshot of a TradingView chart with indicators"""
        try:
            logger.info(f"Getting screenshot of chart: {chart_url}")
            
            # Ga naar de chart pagina
            await self.page.goto(chart_url, {
                'waitUntil': 'networkidle0',
                'timeout': 60000
            })
            await asyncio.sleep(10)  # Wacht extra tijd voor het laden van de chart
            
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
                            await self.page.waitForSelector(selector, {'timeout': 5000})
                            logger.info(f"Chart element found with selector: {selector}")
                            break
                        except:
                            continue
                    
                    # Wacht extra tijd voor het laden van indicators
                    await asyncio.sleep(15)
                    
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
                    await asyncio.sleep(1)
                    
                    # Probeer verschillende selectors voor de chart container
                    for selector in [".chart-container", ".layout__area--center", ".chart-markup-table"]:
                        try:
                            chart_element = await self.page.querySelector(selector)
                            if chart_element:
                                logger.info(f"Taking screenshot of chart element with selector: {selector}")
                                screenshot = await chart_element.screenshot()
                                logger.info("Successfully took screenshot of chart element")
                                return screenshot
                        except Exception as e:
                            logger.warning(f"Error taking screenshot with selector {selector}: {str(e)}")
                    
                    # Als geen van de selectors werkt, maak een screenshot van de hele pagina
                    logger.warning("Chart container element not found, taking full page screenshot")
                    screenshot = await self.page.screenshot()
                    return screenshot
                    
                except Exception as e:
                    logger.error(f"Error waiting for chart to load: {str(e)}")
                    
                    # Maak een screenshot van de pagina voor debugging
                    screenshot = await self.page.screenshot()
                    with open("chart_load_failed.png", "wb") as f:
                        f.write(screenshot)
                    logger.info("Saved chart load failed screenshot to chart_load_failed.png")
                    
                    # Probeer een screenshot van de hele pagina
                    return await self.page.screenshot()
            else:
                # We zijn niet op een chart pagina, probeer naar de chart pagina te navigeren
                logger.warning(f"Not on chart page, current URL: {self.page.url}")
                
                # Probeer naar de chart pagina te navigeren via de URL
                chart_id = chart_url.split("/")[-2]
                public_url = f"https://www.tradingview.com/x/{chart_id}/"
                
                logger.info(f"Trying public chart URL: {public_url}")
                await self.page.goto(public_url, {
                    'waitUntil': 'networkidle0',
                    'timeout': 60000
                })
                await asyncio.sleep(10)
                
                # Maak een screenshot van de pagina
                return await self.page.screenshot()
            
        except Exception as e:
            logger.error(f"Error getting chart screenshot: {str(e)}")
            
            # Probeer een screenshot van de huidige pagina als fallback
            try:
                return await self.page.screenshot()
            except:
                return None
                
    async def cleanup(self):
        """Clean up resources"""
        try:
            if self.browser:
                await self.browser.close()
            logger.info("TradingView Puppeteer service resources cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up TradingView Puppeteer service: {str(e)}") 
