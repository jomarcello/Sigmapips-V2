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

(async () => {
    let browser;
    try {
        console.log(`Taking screenshot of ${url} and saving to ${outputPath} (fullscreen: ${fullscreen})`);
        
        // Start een browser met gereduceerde wachttijden
        browser = await chromium.launch({
            headless: true,
            args: [
                '--no-sandbox', 
                '--disable-setuid-sandbox', 
                '--disable-dev-shm-usage',
                '--disable-notifications',
                '--disable-popup-blocking',
                '--disable-extensions',
                '--disable-web-security',
                '--disable-background-networking',
                '--disable-sync'
            ]
        });
        
        // Open een nieuwe pagina met grotere viewport voor fullscreen
        const context = await browser.newContext({
            locale: 'en-US', 
            timezoneId: 'Europe/Amsterdam',
            viewport: { width: 1920, height: 1080 },
            bypassCSP: true,
            userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
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
        await context.addInitScript(() => {
            const storageItems = {
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
                'tv_notice_shown': 'true'
            };
            
            for (const [key, value] of Object.entries(storageItems)) {
                try { localStorage.setItem(key, value); } catch (e) { }
            }
            
            // Block popups and dialogs
            window.open = () => null;
            window.confirm = () => true;
            window.alert = () => {};
        });
        
        // Open een nieuwe pagina voor de screenshot
        const page = await context.newPage();
        
        // Auto dismiss dialogs
        page.on('dialog', async dialog => {
            await dialog.dismiss().catch(() => {});
        });
        
        // Voeg CSS toe om dialogen te verbergen voordat navigatie begint
        await page.addStyleTag({
            content: `
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
                }
            `
        }).catch(() => {});
        
        // Stel een lagere timeout in (30s in plaats van 60s)
        page.setDefaultTimeout(30000);
        
        try {
            // Ga naar de URL met geoptimaliseerde timeout
            console.log(`Navigating to ${url}...`);
            await page.goto(url, {
                waitUntil: 'domcontentloaded',
                timeout: 30000 // 30 seconden timeout voor navigatie
            });
            
            // Stel localStorage waarden in om meldingen uit te schakelen
            console.log('Setting localStorage values to disable notifications...');
            await page.evaluate(() => {
                localStorage.setItem('tv_release_channel', 'stable');
                localStorage.setItem('tv_alert', 'dont_show');
                localStorage.setItem('feature_hint_shown', 'true');
                localStorage.setItem('TVPrivacySettingsAccepted', 'true');
                localStorage.setItem('screener_new_feature_notification', 'shown');
                
                // Functie om dialogen te verwijderen
                function removeAllDialogs() {
                    // Escape toets om dialogen te sluiten
                    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
                    
                    // Klik op sluitingsknoppen
                    document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"]').forEach(btn => {
                        try { btn.click(); } catch (e) {}
                    });
                    
                    // Verwijder dialoog elementen
                    document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog').forEach(dialog => {
                        try {
                            dialog.style.display = 'none';
                            if (dialog.parentNode) {
                                dialog.parentNode.removeChild(dialog);
                            }
                        } catch (e) {}
                    });
                }
                
                // Roep de functie direct aan
                removeAllDialogs();
                
                // Observer om nieuwe dialogen te verwijderen
                const observer = new MutationObserver(mutations => {
                    for (const mutation of mutations) {
                        if (mutation.addedNodes && mutation.addedNodes.length) {
                            removeAllDialogs();
                        }
                    }
                });
                
                // Start de observer
                observer.observe(document.body, { childList: true, subtree: true });
            });
            
            // Kortere wachttijd voor het laden van de pagina
            console.log('Waiting for page to render...');
            await page.waitForTimeout(2500); // 2.5 seconden wachten (voorheen 5s)
            
            // Als fullscreen is ingeschakeld, verberg UI-elementen
            if (fullscreen) {
                console.log('Removing UI elements for fullscreen...');
                await page.evaluate(() => {
                    // Verberg de header
                    const header = document.querySelector('.tv-header');
                    if (header) header.style.display = 'none';
                    
                    // Verberg andere UI-elementen
                    const elementsToHide = [
                        '.tv-main-panel__toolbar',
                        '.tv-side-toolbar',
                        '.layout__area--left', 
                        '.layout__area--right',
                        'footer',
                        '.tv-main-panel__statuses'
                    ];
                    
                    elementsToHide.forEach(selector => {
                        const element = document.querySelector(selector);
                        if (element) element.style.display = 'none';
                    });
                    
                    // Maximaliseer de chart
                    const chart = document.querySelector('.chart-container');
                    if (chart) {
                        chart.style.width = '100vw';
                        chart.style.height = '100vh';
                    }
                });
            }
            
            // Eenvoudige en betrouwbare methode voor fullscreen
            console.log('Applying simple fullscreen method...');
            
            // Methode 1: Shift+F toetsencombinatie (meest betrouwbaar)
            await page.keyboard.down('Shift');
            await page.keyboard.press('F');
            await page.keyboard.up('Shift');
            
            // Methode 2: CSS fullscreen (backup)
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
            
            // Wacht tot de chart volledig is geladen (kortere timeout)
            console.log('Waiting for chart to be fully loaded...');
            try {
                const waitPromise = page.waitForFunction(() => {
                    const chartContainer = document.querySelector('.chart-container');
                    return chartContainer !== null;
                }, { timeout: 10000 }); // 10s in plaats van 15s
                
                const timeoutPromise = new Promise((resolve) => setTimeout(resolve, 10000));
                await Promise.race([waitPromise, timeoutPromise]);
                console.log('Chart loaded or timeout reached');
            } catch (e) {
                console.log('Timeout waiting for chart, continuing anyway:', e);
            }
            
            // Kortere stabiliteitswachttijd
            await page.waitForTimeout(1000); // 1s in plaats van 2s
            
            // Neem screenshot
            console.log('Taking screenshot...');
            await page.screenshot({ path: outputPath });
            console.log('Screenshot taken successfully');
            
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
        }
    } catch (error) {
        console.error('Fatal error:', error);
        process.exit(1);
    } finally {
        if (browser) {
            await browser.close().catch(e => console.error('Error closing browser:', e));
        }
    }
})();
