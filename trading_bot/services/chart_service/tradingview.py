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
                    '--disable-gpu'
                ]
            )
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
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
            
            # Ga naar de hoofdpagina in plaats van de signin pagina
            await self.page.goto("https://www.tradingview.com/", wait_until="networkidle")
            
            # Debug informatie
            logger.info(f"Page title: {await self.page.title()}")
            logger.info(f"Page URL: {self.page.url}")
            
            # Maak een screenshot voor debugging
            screenshot = await self.page.screenshot()
            with open("login_page.png", "wb") as f:
                f.write(screenshot)
            logger.info("Saved login page screenshot to login_page.png")
            
            # Klik op de Sign In knop op de hoofdpagina
            try:
                sign_in_button = self.page.locator('button:has-text("Sign in"), a:has-text("Sign in")')
                if await sign_in_button.is_visible():
                    logger.info("Sign in button found, clicking...")
                    await sign_in_button.click()
                    await self.page.wait_for_timeout(3000)
                else:
                    logger.warning("Sign in button not visible")
                    
                    # Probeer JavaScript om de login knop te vinden en te klikken
                    await self.page.evaluate("""
                        () => {
                            // Zoek naar elementen met "Sign in" tekst
                            const elements = Array.from(document.querySelectorAll('button, a'));
                            const signInElement = elements.find(el => 
                                el.textContent.includes('Sign in') || 
                                el.textContent.includes('Log in')
                            );
                            
                            if (signInElement) {
                                signInElement.click();
                                console.log("Clicked sign in button via JavaScript");
                            }
                        }
                    """)
                    await self.page.wait_for_timeout(3000)
            except Exception as e:
                logger.warning(f"Error finding sign in button: {str(e)}")
            
            # Maak een screenshot na het klikken op de Sign In knop
            screenshot = await self.page.screenshot()
            with open("after_signin_click.png", "wb") as f:
                f.write(screenshot)
            logger.info("Saved screenshot after clicking sign in button")
            
            # Wacht op het email input veld
            try:
                await self.page.wait_for_selector('input[name="username"]', timeout=10000)
                logger.info("Username input found")
                await self.page.fill('input[name="username"]', self.username)
            except Exception as e:
                logger.warning(f"Username input not found: {str(e)}")
                
                # Probeer alternatieve selectors
                selectors = [
                    'input[type="text"][autocomplete="username"]',
                    'input[type="email"]',
                    'input.tv-control-material-input__control',
                    'form input[type="text"]:first-child'
                ]
                
                for selector in selectors:
                    try:
                        username_input = self.page.locator(selector)
                        if await username_input.is_visible():
                            logger.info(f"Found username input with selector: {selector}")
                            await username_input.fill(self.username)
                            await self.page.wait_for_timeout(1000)
                            break
                    except Exception as e:
                        logger.warning(f"Error with selector {selector}: {str(e)}")
                
                # Als we nog steeds geen username input hebben gevonden, probeer JavaScript
                await self.page.evaluate(f"""
                    () => {{
                        // Probeer alle zichtbare input velden
                        const inputs = Array.from(document.querySelectorAll('input[type="text"], input[type="email"]'));
                        const visibleInputs = inputs.filter(input => {{
                            const style = window.getComputedStyle(input);
                            return style.display !== 'none' && style.visibility !== 'hidden';
                        }});
                        
                        if (visibleInputs.length > 0) {{
                            visibleInputs[0].value = "{self.username}";
                            console.log("Set username via JavaScript");
                        }}
                    }}
                """)
            
            # Klik op de "Continue" of "Next" knop als die er is
            try:
                continue_button = self.page.locator('button:has-text("Continue"), button:has-text("Next"), button[type="submit"]')
                if await continue_button.is_visible():
                    logger.info("Continue button found, clicking...")
                    await continue_button.click()
                    await self.page.wait_for_timeout(3000)
                else:
                    logger.warning("Continue button not visible")
            except Exception as e:
                logger.warning(f"Continue button not found: {str(e)}")
            
            # Wacht op het password input veld
            try:
                await self.page.wait_for_selector('input[name="password"]', timeout=10000)
                logger.info("Password input found")
                await self.page.fill('input[name="password"]', self.password)
            except Exception as e:
                logger.warning(f"Password input not found: {str(e)}")
                
                # Probeer alternatieve selectors
                selectors = [
                    'input[type="password"]',
                    'input.tv-control-material-input__control[type="password"]',
                    'form input[type="password"]'
                ]
                
                for selector in selectors:
                    try:
                        password_input = self.page.locator(selector)
                        if await password_input.is_visible():
                            logger.info(f"Found password input with selector: {selector}")
                            await password_input.fill(self.password)
                            await self.page.wait_for_timeout(1000)
                            break
                    except Exception as e:
                        logger.warning(f"Error with selector {selector}: {str(e)}")
                
                # Als we nog steeds geen password input hebben gevonden, probeer JavaScript
                await self.page.evaluate(f"""
                    () => {{
                        // Probeer alle zichtbare password velden
                        const inputs = Array.from(document.querySelectorAll('input[type="password"]'));
                        const visibleInputs = inputs.filter(input => {{
                            const style = window.getComputedStyle(input);
                            return style.display !== 'none' && style.visibility !== 'hidden';
                        }});
                        
                        if (visibleInputs.length > 0) {{
                            visibleInputs[0].value = "{self.password}";
                            console.log("Set password via JavaScript");
                        }}
                    }}
                """)
            
            # Klik op de "Sign In" knop
            try:
                selectors = [
                    'button[type="submit"]',
                    'button:has-text("Sign in")',
                    'button:has-text("Log in")',
                    'button.tv-button--primary'
                ]
                
                for selector in selectors:
                    try:
                        submit_button = self.page.locator(selector)
                        if await submit_button.is_visible():
                            logger.info(f"Found submit button with selector: {selector}")
                            await submit_button.click()
                            await self.page.wait_for_timeout(5000)
                            break
                    except Exception as e:
                        logger.warning(f"Error with selector {selector}: {str(e)}")
                
                # Als we nog steeds geen submit button hebben gevonden, probeer JavaScript
                await self.page.evaluate("""
                    () => {
                        // Probeer alle zichtbare buttons
                        const buttons = Array.from(document.querySelectorAll('button'));
                        const visibleButtons = buttons.filter(button => {
                            const style = window.getComputedStyle(button);
                            return style.display !== 'none' && style.visibility !== 'hidden';
                        });
                        
                        // Zoek naar een submit button of een button met "Sign in" of "Log in" tekst
                        const submitButton = visibleButtons.find(button => 
                            button.type === 'submit' || 
                            button.textContent.includes('Sign in') || 
                            button.textContent.includes('Log in')
                        );
                        
                        if (submitButton) {
                            submitButton.click();
                            console.log("Clicked submit button via JavaScript");
                        }
                    }
                """)
            except Exception as e:
                logger.warning(f"Error finding submit button: {str(e)}")
            
            # Wacht tot de pagina is geladen
            await self.page.wait_for_timeout(5000)
            
            # Maak een screenshot na login poging
            screenshot = await self.page.screenshot()
            with open("after_login.png", "wb") as f:
                f.write(screenshot)
            logger.info("Saved after login screenshot to after_login.png")
            
            # Debug informatie
            logger.info(f"After login, URL: {self.page.url}")
            
            # Controleer of we zijn ingelogd
            if await self._is_logged_in():
                logger.info("Successfully logged in to TradingView")
                self.is_logged_in = True
                
                # Sla cookies op voor toekomstige sessies
                await self._save_cookies()
                
                return True
            else:
                logger.error("Failed to log in to TradingView")
                
                # Maak een screenshot van de pagina voor debugging
                try:
                    screenshot = await self.page.screenshot()
                    with open("login_failed.png", "wb") as f:
                        f.write(screenshot)
                    logger.info("Saved login failed screenshot to login_failed.png")
                except Exception as e:
                    logger.error(f"Error saving login failed screenshot: {str(e)}")
                
                return False
                
        except Exception as e:
            logger.error(f"Error logging in to TradingView: {str(e)}")
            return False
            
    async def _is_logged_in(self) -> bool:
        """Check if we are logged in to TradingView"""
        try:
            # Controleer of de user menu zichtbaar is
            user_menu = self.page.locator('.tv-header__user-menu-button')
            is_visible = await user_menu.is_visible()
            logger.info(f"User menu visible: {is_visible}")
            return is_visible
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
        """Get a screenshot of a TradingView chart"""
        try:
            if not self.is_logged_in:
                logger.warning("Not logged in to TradingView, trying to log in")
                if not await self.login():
                    logger.error("Failed to log in to TradingView")
                    return None
            
            logger.info(f"Getting screenshot of chart: {chart_url}")
            
            # Ga naar de chart pagina
            await self.page.goto(chart_url, wait_until="networkidle")
            
            # Debug informatie
            logger.info(f"Page title: {await self.page.title()}")
            logger.info(f"Page URL: {self.page.url}")
            
            # Wacht tot de chart is geladen
            try:
                await self.page.wait_for_selector(".chart-markup-table", timeout=30000)
                logger.info("Chart markup table found")
            except Exception as e:
                logger.error(f"Error waiting for chart markup table: {str(e)}")
                
                # Maak een screenshot van de pagina voor debugging
                try:
                    screenshot = await self.page.screenshot()
                    with open("chart_load_failed.png", "wb") as f:
                        f.write(screenshot)
                    logger.info("Saved chart load failed screenshot to chart_load_failed.png")
                except Exception as screenshot_error:
                    logger.error(f"Error saving chart load failed screenshot: {str(screenshot_error)}")
                
                return None
            
            # Wacht nog wat extra tijd voor alle indicators
            await self.page.wait_for_timeout(5000)
            
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
                    const elements = document.querySelectorAll('.tv-side-toolbar, .tv-floating-toolbar');
                    elements.forEach(el => {
                        if (el) el.style.display = 'none';
                    });
                }
            """)
            
            # Maak een screenshot
            screenshot = await self.page.screenshot(
                full_page=False,
                type="png",
                clip={"x": 0, "y": 0, "width": 1280, "height": 800}
            )
            
            logger.info(f"Successfully got screenshot of chart: {chart_url}")
            return screenshot
            
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
