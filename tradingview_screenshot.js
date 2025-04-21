// Verbeterde foutafhandeling en module import
let playwright;
try {
    // Probeer eerst lokaal geïnstalleerde module
    playwright = require('playwright');
    console.log("Using locally installed playwright module");
} catch (e) {
    try {
        // Probeer globaal geïnstalleerde module
        const globalModulePath = require('child_process')
            .execSync('npm root -g')
            .toString()
            .trim();
        playwright = require(`${globalModulePath}/playwright`);
        console.log("Using globally installed playwright module");
    } catch (e2) {
        console.error('Geen Playwright module gevonden. Installeer met: npm install playwright');
        process.exit(1);
    }
}

// Verify if browsers are installed
async function checkBrowsersInstalled() {
    const { execSync } = require('child_process');
    try {
        // Check if the browser binary exists
        const checkCommand = "node -e \"const { chromium } = require('playwright'); chromium.executablePath();\"";
        execSync(checkCommand, { timeout: 10000 });
        return true;
    } catch (error) {
        console.log("Playwright browsers not installed. Attempting to install...");
        try {
            // Install only chromium for faster installation
            execSync("npx playwright install chromium", {
                stdio: 'inherit',
                timeout: 300000 // 5 minute timeout
            });
            console.log("Chromium browser installed successfully");
            return true;
        } catch (installError) {
            console.error("Failed to install Playwright browsers:", installError.message);
            return false;
        }
    }
}

// Haal de argumenten op
const url = process.argv[2];
const outputPath = process.argv[3];
const sessionId = process.argv[4]; // Voeg session ID toe als derde argument
const fullscreenArg = process.argv[5] || ''; // Get the full string value
const fullscreen = fullscreenArg === 'fullscreen' || fullscreenArg === 'true' || fullscreenArg === '1'; // Check various forms of true

if (!url || !outputPath) {
    console.error('Usage: node screenshot.js <url> <outputPath> [sessionId] [fullscreen]');
    process.exit(1);
}

const { chromium } = require('playwright');

// Voorgedefinieerde CSS om dialogen te verbergen - dit buiten de functie plaatsen voor snelheid
const hideDialogsCSS = `
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
`;

// Voorgedefinieerde localStorage items voor snelheid
const tvLocalStorage = {
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
};

(async () => {
    try {
        console.log(`Taking screenshot of ${url} and saving to ${outputPath} (fullscreen: ${fullscreen})`);
        
        // Check and install browsers if needed before launching
        const browsersReady = await checkBrowsersInstalled();
        if (!browsersReady) {
            console.error("Could not install browsers. Screenshot may fail.");
        }
        
        // Start een browser
        const browser = await chromium.launch({
            headless: true,
            args: [
                '--no-sandbox', 
                '--disable-setuid-sandbox', 
                '--disable-dev-shm-usage',
                '--disable-notifications',
                '--disable-popup-blocking',
                '--disable-extensions'
            ]
        });
        
        // Open een nieuwe pagina met grotere viewport voor fullscreen
        const context = await browser.newContext({
            locale: 'en-US', // Stel de locale in op Engels
            timezoneId: 'Europe/Amsterdam', // Stel de tijdzone in op Amsterdam
            viewport: { width: 1920, height: 1080 }, // Stel een grotere viewport in
            bypassCSP: true, // Bypass Content Security Policy
        });
        
        // Voeg cookies toe als er een session ID is
        if (sessionId) {
            console.log(`Using session ID: ${sessionId.substring(0, 5)}...`);
            
            // Voeg de session cookie direct toe zonder eerst naar TradingView te gaan
            await context.addCookies([
                {
                    name: 'sessionid',
                    value: sessionId,
                    domain: '.tradingview.com',
                    path: '/',
                    httpOnly: true,
                    secure: true,
                    sameSite: 'Lax'
                },
                {
                    name: 'language',
                    value: 'en',
                    domain: '.tradingview.com',
                    path: '/'
                },
                // Extra cookies om popups te blokkeren
                {
                    name: 'feature_hint_shown',
                    value: 'true',
                    domain: '.tradingview.com',
                    path: '/'
                },
                {
                    name: 'screener_new_feature_notification',
                    value: 'shown',
                    domain: '.tradingview.com',
                    path: '/'
                }
            ]);
        }
        
        // Stel localStorage waarden in voordat navigatie plaatsvindt
        await context.addInitScript(({ tvLocalStorage }) => {
            for (const [key, value] of Object.entries(tvLocalStorage)) {
                try {
                    localStorage.setItem(key, value);
                } catch (e) { }
            }
            
            // Blokkeer alle popups
            window.open = () => null;
            
            // Overschrijf confirm en alert om ze te negeren
            window.confirm = () => true;
            window.alert = () => {};
        }, { tvLocalStorage });
        
        // Open een nieuwe pagina voor de screenshot
        const page = await context.newPage();
        
        // Auto dismiss dialogs
        page.on('dialog', async dialog => {
            await dialog.dismiss().catch(() => {});
        });
        
        // Voeg CSS toe om dialogen te verbergen voordat navigatie begint
        await page.addStyleTag({ content: hideDialogsCSS }).catch(() => {});
        
        // Stel een maximale wachttijd in die past bij TradingView
        page.setDefaultTimeout(30000); // 30 seconden max timeout
        
        try {
            // Ga naar de URL
            console.log(`Navigating to ${url}...`);
            await page.goto(url, {
                waitUntil: 'domcontentloaded', // Sneller dan 'networkidle'
                timeout: 30000 // 30 seconden timeout voor navigatie
            });
            
            // Stel localStorage waarden in om meldingen uit te schakelen
            console.log('Setting localStorage values to disable notifications...');
            await page.evaluate(({ tvLocalStorage }) => {
                // Belangrijkste localStorage waarden instellen
                for (const [key, value] of Object.entries(tvLocalStorage)) {
                    try {
                        localStorage.setItem(key, value);
                    } catch (e) {}
                }
                
                // Escape toets simuleren om dialogen te sluiten
                document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
            }, { tvLocalStorage });
            
            // Voeg CSS toe om Stock Screener popup te verbergen (opnieuw voor zekerheid)
            await page.addStyleTag({ content: hideDialogsCSS });
            
            // In één stap alle dialogboxen sluiten
            await page.evaluate(() => {
                // Simuleer Escape toets om dialogen te sluiten
                document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
                
                // Vind en klik alle sluitingsknoppen
                document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"], .nav-button-znwuaSC1').forEach(btn => {
                    try {
                        btn.click();
                    } catch (e) {}
                });
                
                // Verwijder alle dialoogelementen
                document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog, .tv-dialog--popup').forEach(dialog => {
                    dialog.style.display = 'none';
                    if (dialog.parentNode) {
                        try {
                            dialog.parentNode.removeChild(dialog);
                        } catch (e) {}
                    }
                });
            });
            
            // Korter wachten om de pagina te laten laden (2000ms in plaats van 5000ms)
            console.log('Waiting for page to render...');
            await page.waitForTimeout(2000);
            
            // Direct aanpak om slechts één keer alle close buttons te klikken met Playwright
            const closeSelectors = [
                'button.close-B02UUUN3',
                'button[data-name="close"]',
                'button.nav-button-znwuaSC1.size-medium-znwuaSC1.preserve-paddings-znwuaSC1.close-B02UUUN3', 
                'button:has(svg path[d="m.58 1.42.82-.82 15 15-.82.82z"])',
                'button:has(svg path[d="m.58 15.58 15-15 .82.82-15 15z"])'
            ];
            
            for (const selector of closeSelectors) {
                try {
                    const buttons = await page.$$(selector);
                    console.log(`Found ${buttons.length} buttons with selector ${selector}`);
                    
                    for (const button of buttons) {
                        try {
                            await button.click({ force: true }).catch(() => {});
                        } catch (e) {}
                    }
                } catch (e) {}
            }
            
            // Controleer of we zijn ingelogd
            const isLoggedIn = await page.evaluate(() => {
                return document.body.innerText.includes('Log out') || 
                       document.body.innerText.includes('Account') ||
                       document.querySelector('.tv-header__user-menu-button') !== null;
            });
            
            console.log(`Logged in status: ${isLoggedIn}`);
            
            // Als fullscreen is ingeschakeld, verberg UI-elementen
            if (fullscreen) {
                console.log('Removing UI elements for fullscreen...');
                await page.evaluate(() => {
                    // Verberg de header
                    const header = document.querySelector('.tv-header');
                    if (header) header.style.display = 'none';
                    
                    // Verberg de toolbar
                    const toolbar = document.querySelector('.tv-main-panel__toolbar');
                    if (toolbar) toolbar.style.display = 'none';
                    
                    // Verberg de zijbalk
                    const sidebar = document.querySelector('.tv-side-toolbar');
                    if (sidebar) sidebar.style.display = 'none';
                    
                    // Verberg andere UI-elementen
                    const panels = document.querySelectorAll('.layout__area--left, .layout__area--right');
                    panels.forEach(panel => {
                        if (panel) panel.style.display = 'none';
                    });
                    
                    // Maximaliseer de chart
                    const chart = document.querySelector('.chart-container');
                    if (chart) {
                        chart.style.width = '100vw';
                        chart.style.height = '100vh';
                    }
                    
                    // Verberg de footer
                    const footer = document.querySelector('footer');
                    if (footer) footer.style.display = 'none';
                    
                    // Verberg de statusbalk
                    const statusBar = document.querySelector('.tv-main-panel__statuses');
                    if (statusBar) statusBar.style.display = 'none';
                });
            }
            
            // Eenvoudige en betrouwbare methode voor fullscreen
            console.log('Applying simple fullscreen method...');
            
            // Methode 1: Shift+F toetsencombinatie (meest betrouwbaar)
            await page.keyboard.down('Shift');
            await page.keyboard.press('F');
            await page.keyboard.up('Shift');
            
            // Korter wachten voor fullscreen (1000ms in plaats van 2000ms)
            await page.waitForTimeout(1000);
            
            // Methode 2: Maak de chart groter met CSS (werkt altijd)
            await page.addStyleTag({
                content: `
                    /* Verberg header en toolbar */
                    .tv-header, .tv-main-panel__toolbar, .tv-side-toolbar {
                        display: none !important;
                    }
                    
                    /* Maximaliseer chart container */
                    .chart-container, .chart-markup-table, .layout__area--center {
                        width: 100vw !important;
                        height: 100vh !important;
                        position: fixed !important;
                        top: 0 !important;
                        left: 0 !important;
                    }
                `
            });
            
            // Korter wachten voor indicators als we zijn ingelogd (3000ms ipv 5000ms)
            if (isLoggedIn) {
                console.log('Waiting for custom indicators to load...');
                await page.waitForTimeout(3000);
            }
            
            // Wacht op de chart met een kortere timeout (5000ms ipv 15000ms)
            console.log('Waiting for chart to be fully loaded...');
            try {
                // Controleer of de chart container aanwezig is
                const chartContainer = await page.$('.chart-container');
                if (chartContainer) {
                    console.log('Chart container found, continuing');
                } else {
                    // Als er geen chart container is, wacht dan iets langer
                    await page.waitForTimeout(2000);
                }
            } catch (e) {
                console.log('Timeout waiting for chart, continuing anyway:', e);
            }
            
            // Laatste dialoog cleanup - simpeler en sneller
            await page.evaluate(() => {
                // Escape key indrukken om eventuele dialogen te sluiten
                document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
                
                // Verwijder alleen zichtbare dialogen
                document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog').forEach(dialog => {
                    dialog.style.display = 'none';
                });
            });
            
            // Korter wachten voor stabiliteit (500ms ipv 2000ms)
            await page.waitForTimeout(500);
            
            // Neem screenshot
            console.log('Taking screenshot...');
            await page.screenshot({ path: outputPath });
            console.log('Screenshot taken successfully');
            
            // Sluit browser
            await browser.close();
        } catch (error) {
            console.error('Navigation error:', error);
            
            // Probeer toch een screenshot te maken in geval van een error
            try {
                console.log('Attempting to take screenshot despite error...');
                await page.screenshot({ path: outputPath });
                console.log('Screenshot taken despite error');
            } catch (screenshotError) {
                console.error('Failed to take screenshot after error:', screenshotError);
            }
            
            await browser.close();
            process.exit(1);
        }
    } catch (error) {
        console.error('Fatal error:', error);
        process.exit(1);
    }
})();
