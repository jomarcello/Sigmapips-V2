import os
import logging
import asyncio
import json # Needed for localStorage init script
from typing import Optional, Dict
from io import BytesIO
from trading_bot.services.chart_service.tradingview import TradingViewService
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

logger = logging.getLogger(__name__)

# CSS selector to hide common popups and dialogs on TradingView
HIDE_DIALOGS_CSS = """
    [role="dialog"], 
    .tv-dialog, 
    .js-dialog,
    .tv-dialog-container,
    .tv-dialog__modal,
    .tv-dialog__modal-container,
    div[data-dialog-name*="chart-new-features"],
    div[data-dialog-name*="notice"],
    div[data-name*="dialog"],
    .tv-dialog--popup,
    .tv-alert-dialog,
    .tv-notification,
    .feature-no-touch .tv-dialog--popup,
    .tv-dialog--alert,
    div[class*="dialog"],
    div:has(button.close-B02UUUN3),
    div:has(button[data-name="close"]) {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
        z-index: -9999 !important;
        position: absolute !important;
        top: -9999px !important;
        left: -9999px !important;
        width: 0 !important;
        height: 0 !important;
        overflow: hidden !important;
    }
"""

# localStorage items to set to minimize popups
TV_LOCAL_STORAGE = {
    'tv_release_channel': 'stable',
    'tv_alert': 'dont_show',
    'feature_hint_shown': 'true',
    'screener_new_feature_notification': 'shown',
    'screener_deprecated': 'true',
    'tv_notification': 'dont_show',
    'screener_new_feature_already_shown': 'true',
    'stock_screener_banner_closed': 'true',
    'tv_screener_notification': 'dont_show',
    'hints_are_disabled': 'true',
    'tv.alerts-tour': 'true',
    'feature-hint-dialog-shown': 'true',
    'feature-hint-alerts-shown': 'true',
    'feature-hint-screener-shown': 'true',
    'feature-hint-shown': 'true',
    'popup.popup-handling-popups-shown': 'true',
    'tv.greeting-dialog-shown': 'true',
    'tv_notice_shown': 'true',
    'tv_chart_beta_notice': 'shown',
    'tv_chart_notice': 'shown',
    'tv_screener_notice': 'shown',
    'tv_watch_list_notice': 'shown',
    'tv_new_feature_notification': 'shown',
    'tv_notification_popup': 'dont_show',
    'notification_shown': 'true'
}


class TradingViewNodeService(TradingViewService):
    def __init__(self, session_id=None):
        """Initialize the TradingView service using Playwright for Python."""
        super().__init__()
        self.session_id = session_id or os.getenv("TRADINGVIEW_SESSION_ID", "z90l85p2anlgdwfppsrdnnfantz48z1o")
        # Remove username/password as session ID is primary login method here
        self.is_initialized = False
        self.playwright = None
        self.browser = None
        self.context = None

        # Mapping van timeframes naar TradingView interval waarden remains the same
        self.interval_map = {
            "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
            "1h": "60", "2h": "120", "4h": "240",
            "1d": "D", "1w": "W", "1M": "M"
        }

        # Chart links voor verschillende symbolen remains the same
        self.chart_links = {
             # Commodities
            "XAUUSD": "https://www.tradingview.com/chart/bylCuCgc/",
            "XTIUSD": "https://www.tradingview.com/chart/jxU29rbq/",
            
            # Currencies
            "EURUSD": "https://www.tradingview.com/chart/xknpxpcr/",
            "EURGBP": "https://www.tradingview.com/chart/xt6LdUUi/",
            "EURCHF": "https://www.tradingview.com/chart/4Jr8hVba/",
            "EURJPY": "https://www.tradingview.com/chart/ume7H7lm/",
            "EURCAD": "https://www.tradingview.com/chart/gbtrKFPk/",
            "EURAUD": "https://www.tradingview.com/chart/WweOZl7z/",
            "EURNZD": "https://www.tradingview.com/chart/bcrCHPsz/",
            "GBPUSD": "https://www.tradingview.com/chart/jKph5b1W/",
            "GBPCHF": "https://www.tradingview.com/chart/1qMsl4FS/",
            "GBPJPY": "https://www.tradingview.com/chart/Zcmh5M2k/",
            "GBPCAD": "https://www.tradingview.com/chart/CvwpPBpF/",
            "GBPAUD": "https://www.tradingview.com/chart/neo3Fc3j/",
            "GBPNZD": "https://www.tradingview.com/chart/egeCqr65/",
            "CHFJPY": "https://www.tradingview.com/chart/g7qBPaqM/",
            "USDJPY": "https://www.tradingview.com/chart/mcWuRDQv/",
            "USDCHF": "https://www.tradingview.com/chart/e7xDgRyM/",
            "USDCAD": "https://www.tradingview.com/chart/jjTOeBNM/",
            "CADJPY": "https://www.tradingview.com/chart/KNsPbDME/",
            "CADCHF": "https://www.tradingview.com/chart/XnHRKk5I/",
            "AUDUSD": "https://www.tradingview.com/chart/h7CHetVW/",
            "AUDCHF": "https://www.tradingview.com/chart/oooBW6HP/",
            "AUDJPY": "https://www.tradingview.com/chart/sYiGgj7B/",
            "AUDNZD": "https://www.tradingview.com/chart/AByyHLB4/",
            "AUDCAD": "https://www.tradingview.com/chart/L4992qKp/",
            "NDZUSD": "https://www.tradingview.com/chart/yab05IFU/",
            "NZDCHF": "https://www.tradingview.com/chart/7epTugqA/",
            "NZDJPY": "https://www.tradingview.com/chart/fdtQ7rx7/",
            "NZDCAD": "https://www.tradingview.com/chart/mRVtXs19/",
            
            # Cryptocurrencies
            "BTCUSD": "https://www.tradingview.com/chart/NWT8AI4a/",
            "ETHUSD": "https://www.tradingview.com/chart/rVh10RLj/",
            "XRPUSD": "https://www.tradingview.com/chart/tQu9Ca4E/",
            "SOLUSD": "https://www.tradingview.com/chart/oTTmSjzQ/",
            "BNBUSD": "https://www.tradingview.com/chart/wNBWNh23/",
            "ADAUSD": "https://www.tradingview.com/chart/WcBNFrdb/",
            "LTCUSD": "https://www.tradingview.com/chart/AoDblBMt/",
            "DOGUSD": "https://www.tradingview.com/chart/F6SPb52v/",
            "DOTUSD": "https://www.tradingview.com/chart/nT9dwAx2/",
            "LNKUSD": "https://www.tradingview.com/chart/FzOrtgYw/",
            "XLMUSD": "https://www.tradingview.com/chart/SnvxOhDh/",
            "AVXUSD": "https://www.tradingview.com/chart/LfTlCrdQ/",
            
            # Indices
            "AU200": "https://www.tradingview.com/chart/U5CKagMM/",
            "EU50": "https://www.tradingview.com/chart/tt5QejVd/",
            "FR40": "https://www.tradingview.com/chart/RoPe3S1Q/",
            "HK50": "https://www.tradingview.com/chart/Rllftdyl/",
            "JP225": "https://www.tradingview.com/chart/i562Fk6X/",
            "UK100": "https://www.tradingview.com/chart/0I4gguQa/",
            "US100": "https://www.tradingview.com/chart/5d36Cany/",
            "US500": "https://www.tradingview.com/chart/VsfYHrwP/",
            "US30": "https://www.tradingview.com/chart/heV5Zitn/",
            "DE40": "https://www.tradingview.com/chart/OWzg0XNw/",
        }
        logger.info("TradingView Python Playwright service initialized structure.")

    async def initialize(self):
        """Initialize the Playwright instance and browser."""
        if self.is_initialized:
            return True
        try:
            logger.info("Initializing Playwright for Python...")
            self.playwright = await async_playwright().start()
            
            # Check if Chromium browser is available, attempt install if not (might need user intervention)
            try:
                self.browser = await self.playwright.chromium.launch(headless=True)
                logger.info("Chromium browser launched successfully.")
            except PlaywrightError as e:
                logger.error(f"Failed to launch Chromium: {e}. Attempting to install...")
                # Try running the install command - this might fail depending on permissions
                try:
                    import sys
                    process = await asyncio.create_subprocess_exec(
                        sys.executable, '-m', 'playwright', 'install', 'chromium',
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    stdout, stderr = await process.communicate()
                    if process.returncode == 0:
                        logger.info("Playwright Chromium installed successfully.")
                        self.browser = await self.playwright.chromium.launch(headless=True)
                    else:
                        logger.error(f"Failed to automatically install Chromium. Stdout: {stdout.decode()}, Stderr: {stderr.decode()}")
                        raise RuntimeError("Chromium installation failed.") from e
                except Exception as install_e:
                     logger.error(f"Could not install Chromium automatically: {install_e}. Please run 'python -m playwright install chromium' manually.")
                     return False

            # Create a persistent context to reuse cookies/localStorage
            await self._create_browser_context()

            self.is_initialized = True
            logger.info("Playwright service initialized successfully.")
            return True
        except Exception as e:
            logger.error(f"Error initializing Playwright service: {e}", exc_info=True)
            await self.cleanup() # Attempt cleanup on failure
            return False

    async def _create_browser_context(self):
        """Creates a browser context with necessary settings and cookies."""
        if not self.browser:
             logger.error("Browser not available to create context.")
             return
             
        try:
            # Close existing context if any
            if self.context:
                await self.context.close()
                
            self.context = await self.browser.new_context(
                locale='en-US',
                timezone_id='Europe/Amsterdam',
                viewport={'width': 1920, 'height': 1080},
                bypass_csp=True,
                # user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
            )
            
            # Add session cookie if provided
            if self.session_id:
                logger.info(f"Adding TradingView session cookie (ID: {self.session_id[:5]}...).")
                await self.context.add_cookies([
                    {
                        'name': 'sessionid', 'value': self.session_id,
                        'domain': '.tradingview.com', 'path': '/',
                        'httpOnly': True, 'secure': True, 'sameSite': 'Lax'
                    },
                     {
                        'name': 'language', 'value': 'en',
                         'domain': '.tradingview.com', 'path': '/'
                    }
                ])
                
            # Add initial script to set localStorage and block popups
            await self.context.add_init_script(f"""
                // Set localStorage items
                const tvLocalStorage = {json.dumps(TV_LOCAL_STORAGE)};
                for (const [key, value] of Object.entries(tvLocalStorage)) {{
                    try {{ localStorage.setItem(key, value); }} catch (e) {{}}
                }}
                // Block popups
                window.open = () => null;
                window.confirm = () => true;
                window.alert = () => {{}};
            """)
            logger.info("Browser context created with cookies and init script.")
            
        except Exception as e:
            logger.error(f"Error creating browser context: {e}", exc_info=True)
            self.context = None


    async def take_screenshot(self, symbol, timeframe=None, fullscreen=False):
        """Take a screenshot of a chart using Playwright for Python."""
        if not self.is_initialized or not self.context:
             logger.error("Playwright service not initialized or context not available.")
             # Attempt to initialize if needed
             if not self.is_initialized:
                  await self.initialize()
                  if not self.is_initialized or not self.context:
                       return None
             elif not self.context:
                  await self._create_browser_context()
                  if not self.context:
                       return None

        logger.info(f"Taking screenshot for {symbol} on {timeframe} timeframe (fullscreen: {fullscreen})")

        # Build chart URL (same logic as before)
        normalized_symbol = symbol.replace("/", "").upper()
        chart_url = self.chart_links.get(normalized_symbol)
        if not chart_url:
            logger.warning(f"No specific chart layout URL found for {symbol}, using default chart page.")
            chart_url = f"https://www.tradingview.com/chart/?symbol={normalized_symbol}"
            if timeframe:
                tv_interval = self.interval_map.get(timeframe, "D")
                chart_url += f"&interval={tv_interval}"
        elif timeframe: # Append interval to existing layout URL
             tv_interval = self.interval_map.get(timeframe, "D")
             separator = '&' if '?' in chart_url else '?'
             chart_url += f"{separator}interval={tv_interval}"

        if not chart_url:
            logger.error(f"Invalid chart URL constructed for {symbol}")
            return None

        page = None
        try:
            page = await self.context.new_page()
            logger.info(f"Navigating to URL: {chart_url}")

            # Auto dismiss dialogs (though init script and CSS should handle most)
            page.on('dialog', lambda dialog: asyncio.ensure_future(dialog.dismiss()))

            # Add CSS to hide dialogs immediately
            await page.add_style_tag(content=HIDE_DIALOGS_CSS)

            await page.goto(chart_url, wait_until='domcontentloaded', timeout=30000) # 30s timeout

            # Apply localStorage settings again and try to close popups via JS
            await page.evaluate(f"""
                const tvLocalStorage = {json.dumps(TV_LOCAL_STORAGE)};
                for (const [key, value] of Object.entries(tvLocalStorage)) {{
                    try {{ localStorage.setItem(key, value); }} catch (e) {{}}
                }}
                document.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Escape', keyCode: 27 }}));
                document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"], .nav-button-znwuaSC1').forEach(btn => {{
                    try {{ btn.click(); }} catch (e) {{}}
                }});
                document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog, .tv-dialog--popup').forEach(dialog => {{
                    dialog.style.display = 'none';
                }});
            """)
            
            # Add CSS again for robustness
            await page.add_style_tag(content=HIDE_DIALOGS_CSS)

            # Wait briefly for the page to settle and scripts to run
            await page.wait_for_timeout(2000) # 2 seconds

            # Attempt to close common close buttons directly
            close_selectors = [
                'button.close-B02UUUN3',
                'button[data-name="close"]',
                'button.nav-button-znwuaSC1.size-medium-znwuaSC1.preserve-paddings-znwuaSC1.close-B02UUUN3',
                'button:has-text("Got it")', # Common confirmation button text
                 'button[aria-label*="Close"]' # Common aria labels
            ]
            for selector in close_selectors:
                try:
                    buttons = await page.query_selector_all(selector)
                    for button in buttons:
                         if await button.is_visible():
                              await button.click(timeout=500, force=True) # Short timeout, force click
                              logger.info(f"Clicked potential close button: {selector}")
                              await page.wait_for_timeout(100) # Small delay after click
                except PlaywrightTimeoutError:
                     pass # Ignore timeout errors when clicking close buttons
                except Exception as e:
                     logger.warning(f"Minor error clicking close button {selector}: {e}")


            # Wait for the main chart container to be present
            try:
                chart_container_selector = ".chart-gui-wrapper, .chart-container, .layout__area--center" # Common selectors
                await page.wait_for_selector(chart_container_selector, timeout=10000) # 10s timeout
                logger.info("Chart container found.")
            except PlaywrightTimeoutError:
                logger.warning("Chart container selector not found within timeout, proceeding anyway.")


            if fullscreen:
                logger.info("[FS] Fullscreen requested. Applying minimal CSS and simulating Shift+F...")
                # Hide only the most basic UI elements
                logger.info("[FS] Applying CSS to hide basic UI elements...")
                await page.add_style_tag(content="""
                    .tv-header, .tv-main-panel__toolbar, .tv-side-toolbar, 
                    footer, .tv-main-panel__statuses
                     { display: none !important; visibility: hidden !important; opacity: 0 !important; }
                    body { overflow: hidden !important; } /* Prevent scrollbars */
                """)
                await page.wait_for_timeout(500) # Short wait for basic CSS
                logger.info("[FS] Basic CSS applied and waited.")
                
                # Simulate Shift+F
                logger.info("[FS] Simulating Shift+F keyboard shortcut.")
                await page.keyboard.press('Shift+F')
                logger.info("[FS] Shift+F simulated.")
                
                # Wait specifically for the fullscreen transition
                logger.info("[FS] Waiting for potential fullscreen transition (3000ms)...")
                await page.wait_for_timeout(3000) # Increased wait time after Shift+F
                logger.info("[FS] Finished waiting for transition.")
                
                # Check fullscreen status via JS
                try:
                    fs_status = await page.evaluate("document.fullscreenElement !== null")
                    logger.info(f"[FS] Browser fullscreenElement status via JS: {fs_status}")
                except Exception as js_eval_err:
                    logger.warning(f"[FS] Could not evaluate fullscreenElement status: {js_eval_err}")
            
            # Log viewport and document size before final cleanup
            try:
                dims = await page.evaluate("() => ({ vp_w: window.innerWidth, vp_h: window.innerHeight, doc_w: document.documentElement.scrollWidth, doc_h: document.documentElement.scrollHeight })")
                logger.info(f"[PRE-CLEANUP] Viewport: {dims.get('vp_w')}x{dims.get('vp_h')}, Document: {dims.get('doc_w')}x{dims.get('doc_h')}")
            except Exception as js_eval_err:
                 logger.warning(f"Could not evaluate dimensions: {js_eval_err}")

            # Additional aggressive cleanup just before screenshot
            logger.info("Performing final JS cleanup before screenshot...")
            await page.evaluate("""
                () => {
                    document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog, .tv-dialog--popup, .tv-notification').forEach(el => {
                        el.style.display = 'none';
                        el.style.visibility = 'hidden';
                        el.style.opacity = '0';
                    });
                }
            """)
            await page.wait_for_timeout(500) # Short wait after final cleanup
            logger.info("Final JS cleanup finished.")

            # Log final dimensions before screenshot
            try:
                final_dims = await page.evaluate("() => ({ vp_w: window.innerWidth, vp_h: window.innerHeight, doc_w: document.documentElement.scrollWidth, doc_h: document.documentElement.scrollHeight })")
                logger.info(f"[PRE-SHOT] Viewport: {final_dims.get('vp_w')}x{final_dims.get('vp_h')}, Document: {final_dims.get('doc_w')}x{final_dims.get('doc_h')}")
            except Exception as js_eval_err:
                 logger.warning(f"Could not evaluate final dimensions: {js_eval_err}")

            logger.info("Taking screenshot with Playwright...")
            screenshot_bytes = await page.screenshot(type='png')

            logger.info(f"Screenshot taken successfully ({len(screenshot_bytes)} bytes).")
            return screenshot_bytes

        except PlaywrightTimeoutError as e:
             logger.error(f"Playwright timeout error during screenshot: {e}")
             return None
        except PlaywrightError as e:
             logger.error(f"Playwright general error during screenshot: {e}")
             return None
        except Exception as e:
            logger.error(f"Unexpected error taking screenshot: {e}", exc_info=True)
            return None
        finally:
            if page:
                await page.close()

    async def cleanup(self):
        """Clean up Playwright resources."""
        logger.info("Cleaning up Playwright service...")
        if self.context:
            try:
                await self.context.close()
                self.context = None
                logger.info("Playwright context closed.")
            except Exception as e:
                 logger.error(f"Error closing Playwright context: {e}")
        if self.browser:
            try:
                await self.browser.close()
                self.browser = None
                logger.info("Playwright browser closed.")
            except Exception as e:
                 logger.error(f"Error closing Playwright browser: {e}")
        if self.playwright:
            try:
                await self.playwright.stop()
                self.playwright = None
                logger.info("Playwright stopped.")
            except Exception as e:
                 logger.error(f"Error stopping Playwright: {e}")
        self.is_initialized = False
        logger.info("Playwright service cleanup complete.")

    # Remove batch_capture_charts as it wasn't fully implemented and complicates refactoring
    # async def batch_capture_charts(self, symbols=None, timeframes=None): ...

    # Remove take_screenshot_of_url as its logic is now integrated into take_screenshot
    # async def take_screenshot_of_url(self, url: str, fullscreen: bool = False) -> Optional[bytes]: ...

