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

// De TradingView-specifieke localStorage waarden die popups blokkeren
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

// CSS om dialoogvensters te verbergen
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
    
    /* Verberg de overlay/backdrop */
    .tv-dialog__modal-background {
        opacity: 0 !important;
        display: none !important;
        visibility: hidden !important;
    }
`;

// Functie om alle dialogen te verwijderen
const removeAllDialogsScript = `
    function removeAllDialogs() {
        // Gebruik Escape key om dialogen te sluiten
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
        
        // Klik op alle sluitingsknoppen
        document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"], .nav-button-znwuaSC1').forEach(btn => {
            try { btn.click(); } catch (e) {}
        });
        
        // Zoek op SVG paden (X-pictogrammen in sluitknoppen)
        document.querySelectorAll('svg path[d="m.58 1.42.82-.82 15 15-.82.82z"], svg path[d="m.58 15.58 15-15 .82.82-15 15z"]').forEach(path => {
            try {
                let button = path;
                while (button && button.tagName !== 'BUTTON') {
                    button = button.parentElement;
                    if (!button) break;
                }
                if (button) button.click();
            } catch (e) {}
        });
        
        // Klik op "Got it, thanks" knoppen
        document.querySelectorAll('button').forEach(btn => {
            if (btn.textContent.includes('Got it') || 
                btn.textContent.includes('thanks') || 
                btn.textContent.includes('OK') ||
                btn.textContent.includes('Dismiss')) {
                try { btn.click(); } catch (e) {}
            }
        });
        
        // Verwijder alle dialoogelementen
        document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog, .tv-dialog--popup').forEach(dialog => {
            try {
                dialog.style.display = 'none';
                dialog.style.visibility = 'hidden';
                dialog.style.opacity = '0';
                if (dialog.parentNode) {
                    dialog.parentNode.removeChild(dialog);
                }
            } catch (e) {}
        });
    }
    
    // Roep de functie direct aan en stel ook interval in
    removeAllDialogs();
    window._popupRemovalInterval = setInterval(removeAllDialogs, 300);
`;

// CSS voor fullscreen modus
const fullscreenCSS = `
    /* Verberg header en toolbar */
    .tv-header, .tv-side-toolbar, .layout__area--top, .layout__area--left, .layout__area--right {
        display: none !important;
    }
    
    /* Maximaliseer chart container */
    .chart-container, .chart-markup-table, .layout__area--center {
        width: 100vw !important;
        height: 100vh !important;
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    
    /* Verberg extra UI elementen */
    .tv-floating-toolbar, .ui-draggable, .floating-toolbar-react-widget, .bottom-widgetbar-content {
        display: none !important;
    }
    
    /* Verberg statusbar */
    .tv-main-panel__statuses {
        display: none !important;
    }
`;

(async () => {
    let browser;
    try {
        console.log(`Taking screenshot of ${url} and saving to ${outputPath} (fullscreen: ${fullscreen})`);
        
        // Start een browser met minder argumenten voor snellere opstart
        browser = await chromium.launch({
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });
        
        // Maak een context met een wat kleinere viewport voor snellere rendering
        const context = await browser.newContext({
            locale: 'en-US',
            timezoneId: 'Europe/Amsterdam',
            viewport: { width: 1920, height: 1080 },
            bypassCSP: true,
        });
        
        // Voeg cookies toe als er een session ID is
        if (sessionId) {
            console.log(`Using session ID: ${sessionId.substring(0, 5)}...`);
            
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
        
        // Stel localStorage waarden in om meldingen uit te schakelen
        await context.addInitScript(`(() => {
            const storageItems = ${JSON.stringify(tvLocalStorage)};
            for (const [key, value] of Object.entries(storageItems)) {
                try { localStorage.setItem(key, value); } catch (e) { }
            }
        })()`);
        
        // Open een nieuwe pagina
        const page = await context.newPage();
        
        // Auto dismiss dialogs
        page.on('dialog', async dialog => {
            await dialog.dismiss().catch(() => {});
        });
        
        // Stel een kortere timeout in (30 seconden in plaats van 60)
        page.setDefaultTimeout(30000);
        
        try {
            // Voeg direct CSS toe om dialogen te verbergen
            await page.addStyleTag({ content: hideDialogsCSS }).catch(() => {});
            
            // Ga naar de URL met kortere timeout
            console.log(`Navigating to ${url}...`);
            await page.goto(url, {
                waitUntil: 'domcontentloaded', // Sneller dan 'networkidle'
                timeout: 20000 // Kortere timeout voor navigatie
            });
            
            // Voeg nog een keer de CSS toe en voer JavaScript uit om dialogen te verbergen
            await page.addStyleTag({ content: hideDialogsCSS });
            await page.evaluate(removeAllDialogsScript);
            
            // Verwijder popup buttons direct met Playwright
            const closeSelectors = [
                'button.close-B02UUUN3',
                'button[data-name="close"]',
                'button.nav-button-znwuaSC1.size-medium-znwuaSC1.preserve-paddings-znwuaSC1.close-B02UUUN3'
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
            
            // Controleer of we zijn ingelogd (voor debugging)
            const isLoggedIn = await page.evaluate(() => {
                return document.body.innerText.includes('Log out') || 
                       document.body.innerText.includes('Account') ||
                       document.querySelector('.tv-header__user-menu-button') !== null;
            });
            console.log(`Logged in status: ${isLoggedIn}`);
            
            // Als fullscreen is aangevraagd, activeer dit en wacht kort
            if (fullscreen) {
                console.log('Removing UI elements for fullscreen...');
                await page.addStyleTag({ content: fullscreenCSS });
                
                // Gebruik JavaScript om fullscreen-modus beter te activeren
                await page.evaluate(() => {
                    // Verberg header en toolbar elementen
                    const elementsToHide = [
                        '.tv-header',
                        '.tv-side-toolbar',
                        '.layout__area--top',
                        '.layout__area--left',
                        '.layout__area--right',
                        '.tv-floating-toolbar',
                        '.tv-main-panel__statuses',
                        '.bottom-widgetbar-content'
                    ];
                    
                    elementsToHide.forEach(selector => {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            if (el) el.style.display = 'none';
                        });
                    });
                    
                    // Maximaliseer chart container
                    const chartContainer = document.querySelector('.chart-container');
                    if (chartContainer) {
                        chartContainer.style.width = '100vw';
                        chartContainer.style.height = '100vh';
                        chartContainer.style.position = 'fixed';
                        chartContainer.style.top = '0';
                        chartContainer.style.left = '0';
                    }
                    
                    // Zoek en klik op de fullscreen knop indien aanwezig
                    const fullscreenButton = document.querySelector('[data-name="full-screen"]');
                    if (fullscreenButton) {
                        console.log('Found fullscreen button, clicking it');
                        fullscreenButton.click();
                    }
                });
                
                // Wacht langer om de CSS goed toe te passen
                await page.waitForTimeout(2000);
            }
            
            // Eenvoudige en betrouwbare methode voor fullscreen
            console.log('Applying simple fullscreen method...');
            
            // Methode 1: Shift+F toetsencombinatie
            await page.keyboard.down('Shift');
            await page.keyboard.press('F');
            await page.keyboard.up('Shift');
            
            // Wacht extra tijd na de Shift+F combinatie
            await page.waitForTimeout(2000);
            
            // Laatste popup verwijdering
            await page.evaluate('removeAllDialogs()');
            
            // Neem screenshot
            console.log('Taking screenshot...');
            await page.screenshot({ path: outputPath });
            console.log('Screenshot taken successfully');
            
            // Sluit browser
            await browser.close();
        } catch (error) {
            console.error('Error:', error);
            
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
        if (browser) await browser.close();
        process.exit(1);
    }
})();
