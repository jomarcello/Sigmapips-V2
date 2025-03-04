async def login(self) -> bool:
    """Login to TradingView"""
    try:
        logger.info("Logging in to TradingView")
        
        # Ga direct naar de login pagina in plaats van de chart pagina
        await self.page.goto("https://www.tradingview.com/signin/", wait_until="networkidle")
        
        # Debug informatie
        logger.info(f"Page title: {await self.page.title()}")
        logger.info(f"Page URL: {self.page.url}")
        
        # Maak een screenshot voor debugging
        screenshot = await self.page.screenshot()
        with open("login_page.png", "wb") as f:
            f.write(screenshot)
        logger.info("Saved login page screenshot to login_page.png")
        
        # Wacht op het email input veld
        try:
            await self.page.wait_for_selector('input[name="username"]', timeout=10000)
            logger.info("Username input found")
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
        # ... rest van de code ... 
