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
const fullscreen = fullscreenArg === 'fullscreen' || fullscreenArg === 'true' || fullscreenArg === '1' || url.includes('fullscreen=true'); // Check various forms of true

if (!url || !outputPath) {
    console.error('Usage: node screenshot.js <url> <outputPath> [sessionId] [fullscreen]');
    process.exit(1);
}

const { chromium } = require('playwright');

// CSS om popups en dialogen te blokkeren - gedefinieerd op één plek voor efficiëntie
const blockPopupCSS = `
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

// CSS for fullscreen mode
const fullscreenCSS = `
    /* Verberg UI-elementen */
    .tv-header, .tv-main-panel__toolbar, .tv-side-toolbar, 
    .layout__area--left, .layout__area--right, 
    footer, .tv-main-panel__statuses, 
    .header-chart-panel, .control-bar, .chart-controls-bar {
        display: none !important;
    }
    
    /* Maximaliseer chart */
    .chart-container, .chart-markup-table, .layout__area--center {
        width: 100vw !important;
        height: 100vh !important;
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
    }
    
    /* Extra stijlen om zeker te zijn dat de chart volledig zichtbaar is */
    body, html {
        overflow: hidden !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    
    /* Verberg alle andere elementen die fullscreen zouden kunnen storen */
    .tv-floating-toolbar, .chart-page, .layout__area--top, .layout__area--bottom {
        display: none !important;
    }
`;

// LocalStorage waarden om popups te blokkeren - gedefinieerd op één plek
const disablePopupLocalStorage = {
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
    let browser = null;
    try {
        console.log(`Taking screenshot of ${url} and saving to ${outputPath} (fullscreen: ${fullscreen})`);
        
        // Start een browser
        browser = await chromium.launch({
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', 
                  '--disable-notifications', '--disable-popup-blocking', '--disable-extensions']
        });
        
        // Open een nieuwe pagina met grotere viewport
        const context = await browser.newContext({
            locale: 'en-US',
            timezoneId: 'Europe/Amsterdam',
            viewport: { width: 1920, height: 1080 },
            bypassCSS: true, // Bypass Content Security Policy
        });
        
        // Voeg cookies toe als er een session ID is
        if (sessionId) {
            console.log(`Using session ID: ${sessionId.substring(0, 5)}...`);
            
            // Voeg cookies direct toe
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
        
        // Stel localStorage waarden in voordat navigatie plaatsvindt
        await context.addInitScript(() => {
            // Voeg alle localStorage waarden toe om popups te blokkeren
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
                'tv_notice_shown': 'true',
                'tv_chart_beta_notice': 'shown',
                'tv_chart_notice': 'shown',
                'tv_screener_notice': 'shown',
                'tv_watch_list_notice': 'shown',
                'tv_new_feature_notification': 'shown',
                'tv_notification_popup': 'dont_show',
                'notification_shown': 'true'
            };
            
            // Stel alle localStorage waarden in
            for (const [key, value] of Object.entries(storageItems)) {
                try {
                    localStorage.setItem(key, value);
                } catch (e) { }
            }
            
            // Zoek naar alle localStorage sleutels die eindigen met "_do_not_show_again" of "notification" en zet ze op true/shown
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && (key.endsWith("_do_not_show_again") || key.includes("notification"))) {
                    localStorage.setItem(key, key.includes("notification") ? 'shown' : 'true');
                }
            }
            
            // Verberg alle popups
            window.alert = () => {};
            window.confirm = () => true;
            window.prompt = () => null;
            window.open = () => null;
        });
        
        // Open een nieuwe pagina voor de screenshot
        const page = await context.newPage();
        
        // Auto dismiss dialogs
        page.on('dialog', async dialog => {
            await dialog.dismiss().catch(() => {});
        });
        
        // Voeg CSS toe aan de context om dialogen te verbergen voordat navigatie begint
        await context.addInitScript(`
            (function() {
                const style = document.createElement('style');
                style.textContent = \`${blockPopupCSS}\`;
                document.head.appendChild(style);
                
                // Overschrijf window.open
                window.open = function() { return null; };
                
                // Voeg event listener toe voor Escape toets
                document.addEventListener('keydown', function(e) {
                    if (e.key === 'Escape' || e.keyCode === 27) {
                        console.log('Escape key pressed');
                    }
                });
                
                // Functie om popups te sluiten direct na het laden
                function closeAllPopups() {
                    document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"]').forEach(btn => {
                        try { btn.click(); } catch (e) {}
                    });
                    
                    document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog').forEach(dialog => {
                        try {
                            dialog.style.display = 'none';
                            if (dialog.parentNode) {
                                dialog.parentNode.removeChild(dialog);
                            }
                        } catch (e) {}
                    });
                }
                
                // Voer direct uit en dan nog een keer na DOMContentLoaded
                if (document.readyState === 'complete' || document.readyState === 'interactive') {
                    closeAllPopups();
                } else {
                    document.addEventListener('DOMContentLoaded', closeAllPopups);
                }
                
                // Voer ook uit bij load event
                window.addEventListener('load', closeAllPopups);
                
                // Voer periodiek uit
                setInterval(closeAllPopups, 200);
            })();
        `);
        
        // Verminderde timeout voor betere prestaties
        page.setDefaultTimeout(30000); // 30 seconden timeout
        
        // Ga naar de URL met aangepaste navigatie strategie
        console.log(`Navigating to ${url}...`);
        try {
            await page.goto(url, {
                waitUntil: 'domcontentloaded', // Gebruik domcontentloaded voor sneller laden
                timeout: 30000 // 30 seconden timeout
            });
        } catch (err) {
            // Als de normale navigatie mislukt, probeer dan alleen domcontentloaded
            console.error(`Navigation error: ${err}. Trying alternative approach...`);
        }
        
        // Voeg CSS direct toe om popups te blokkeren - dit gebeurt sneller dan evaluate
        await page.addStyleTag({ content: blockPopupCSS });
        
        // Snelle popup cleaner uitvoeren
        await page.evaluate(() => {
            // Reset localStorage voor alle popup-gerelateerde keys
            for (const [key, value] of Object.entries({
                'tv_release_channel': 'stable',
                'tv_alert': 'dont_show',
                'feature_hint_shown': 'true',
                'screener_new_feature_notification': 'shown',
                'screener_deprecated': 'true',
                'tv_notification': 'dont_show',
                'screener_new_feature_already_shown': 'true',
                'stock_screener_banner_closed': 'true',
                'tv_screener_notification': 'dont_show'
            })) {
                try {
                    localStorage.setItem(key, value);
                } catch (e) {}
            }
            
            // Sluit alle popups
            document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"]').forEach(btn => {
                try { btn.click(); } catch (e) {}
            });
            
            // Verwijder alle dialogen
            document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog').forEach(dialog => {
                try {
                    dialog.style.display = 'none';
                    if (dialog.parentNode) dialog.parentNode.removeChild(dialog);
                } catch (e) {}
            });
            
            // Stuur Escape key om dialogen te sluiten
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
        });
        
        // Kortere wachttijd voor chart rendering
        await page.waitForTimeout(2000);
        
        // ALTIJD FULLSCREEN METHODES GEBRUIKEN - ook wanneer fullscreen niet expliciet is opgegeven
        // Dit zorgt voor consistente screenshots en voorkomt problemen
        console.log('Enabling fullscreen mode (ALWAYS)...');
        
        // ALTIJD Shift+F als eerste uitvoeren - dit is het meest betrouwbaar
        try {
            // Zorg ervoor dat de pagina focus heeft
            await page.focus('body');
            await page.keyboard.down('Shift');
            await page.keyboard.press('F');
            await page.keyboard.up('Shift');
            console.log('Successfully pressed Shift+F to toggle fullscreen');
            
            // Wacht zodat fullscreen kan worden toegepast (belangrijk)
            await page.waitForTimeout(2000);
        } catch (e) {
            console.log('Shift+F shortcut failed:', e);
        }
        
        // Methode 2: CSS om UI te verbergen (als backup, altijd toepassen)
        await page.addStyleTag({ content: fullscreenCSS });
        console.log('Applied fullscreen CSS');
        
        // Methode 3: Verberg UI-elementen direct (als extra backup)
        await page.evaluate(() => {
            // Verberg header en toolbars
            const elementsToHide = [
                '.tv-header', 
                '.tv-main-panel__toolbar', 
                '.tv-side-toolbar',
                '.layout__area--left', 
                '.layout__area--right', 
                'footer', 
                '.tv-main-panel__statuses',
                '.header-chart-panel',
                '.control-bar',
                '.chart-controls-bar'
            ];
            
            elementsToHide.forEach(selector => {
                const elements = document.querySelectorAll(selector);
                elements.forEach(el => {
                    if (el) el.style.display = 'none';
                });
            });
            
            // Vergroot chart container
            const chartContainer = document.querySelector('.chart-container');
            if (chartContainer) {
                chartContainer.style.width = '100vw';
                chartContainer.style.height = '100vh';
                chartContainer.style.position = 'fixed';
                chartContainer.style.top = '0';
                chartContainer.style.left = '0';
            }
            
            // Vergroot layout center element
            const layoutCenter = document.querySelector('.layout__area--center');
            if (layoutCenter) {
                layoutCenter.style.width = '100vw';
                layoutCenter.style.height = '100vh';
                layoutCenter.style.position = 'fixed';
                layoutCenter.style.top = '0';
                layoutCenter.style.left = '0';
            }
        });
        
        // Wacht nog even voor betere stabiliteit na fullscreen acties
        await page.waitForTimeout(2000);
        
        // Laatste cleanup voor screenshot
        await page.evaluate(() => {
            // Verwijder nogmaals alle dialogen
            document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog, .tv-dialog--popup').forEach(el => {
                el.style.display = 'none';
                el.style.visibility = 'hidden';
            });
            
            // Stuur Escape key om alle resterende dialogen te sluiten
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
        });
        
        // Neem screenshot
        console.log('Taking screenshot...');
        await page.screenshot({ path: outputPath });
        console.log('Screenshot taken successfully');
        
        // Sluit browser
        await browser.close();
        browser = null;
        
    } catch (error) {
        console.error('Error:', error);
        
        // Probeer toch een screenshot te maken in geval van een error
        if (browser) {
            try {
                const page = await browser.newPage();
                await page.setContent(`<html><body><h1>Error loading TradingView</h1><p>${error.message}</p></body></html>`);
                await page.screenshot({ path: outputPath });
                console.log('Created error screenshot as fallback');
            } catch (screenshotError) {
                console.error('Failed to create error screenshot:', screenshotError);
            }
            
            await browser.close();
        }
        
        process.exit(1);
    } finally {
        // Zorg ervoor dat de browser altijd wordt gesloten
        if (browser) {
            await browser.close().catch(e => console.error('Error closing browser:', e));
        }
    }
})();
