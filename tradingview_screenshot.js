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

// Voeg een parameter toe voor test modus
const testMode = process.argv[6] === 'test';

// Stel minimale wachttijd in (in milliseconden)
const MIN_WAIT_TIME = testMode ? 300 : 3000; // 0.3 seconde voor tests, 3 seconden normaal

// Stel navigatie timeout in
const NAVIGATION_TIMEOUT = testMode ? 2000 : 8000; // 2 seconden voor tests, 8 seconden normaal

// Stel viewport grootte in
const VIEWPORT_WIDTH = 1920;
const VIEWPORT_HEIGHT = 1080;

if (!url || !outputPath) {
    console.error('Usage: node screenshot.js <url> <outputPath> [sessionId] [fullscreen] [testMode]');
    process.exit(1);
}

const { chromium } = require('playwright');

(async () => {
    try {
        console.log(`Taking screenshot of ${url} and saving to ${outputPath} (fullscreen: ${fullscreen})`);
        
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
                'tv_notice_shown': 'true',
                'tv_chart_beta_notice': 'shown',
                'tv_chart_notice': 'shown',
                'tv_screener_notice': 'shown',
                'tv_watch_list_notice': 'shown',
                'tv_new_feature_notification': 'shown',
                'tv_notification_popup': 'dont_show',
                'notification_shown': 'true'
            };
            
            for (const [key, value] of Object.entries(storageItems)) {
                try {
                    localStorage.setItem(key, value);
                } catch (e) { }
            }
        });
        
        // Ook testMode aan context toevoegen om te gebruiken in evaluatie-scripts
        await context.addInitScript(testModeValue => {
            window.testMode = testModeValue;
        }, testMode);
        
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
                    position: absolute !important;
                    top: -9999px !important;
                    left: -9999px !important;
                    width: 0 !important;
                    height: 0 !important;
                    overflow: hidden !important;
                }
            `
        }).catch(() => {});
        
        // Stel een langere timeout in
        page.setDefaultTimeout(60000); // 1 minuut timeout
        
        try {
            // Ga naar de URL
            console.log(`Navigating to ${url}...`);
            await page.goto(url, {
                waitUntil: 'domcontentloaded',
                timeout: NAVIGATION_TIMEOUT
            });
            
            // Direct Shift+F versturen voor fullscreen modus
            console.log('Pressing Shift+F for fullscreen mode...');
            await page.keyboard.press('Shift+F');
            
            // Wacht precies de minimale tijd
            console.log(`Waiting exactly ${MIN_WAIT_TIME/1000} seconds for chart to render...`);
            await page.waitForTimeout(MIN_WAIT_TIME);
            
            // Stel localStorage waarden in om meldingen uit te schakelen
            console.log('Setting localStorage values to disable notifications...');
            await page.evaluate((testModeValue) => {
                // Define testMode in this scope to make it available
                const testMode = testModeValue;
                
                // Stel release channel in op stable
                localStorage.setItem('tv_release_channel', 'stable');
                
                // Schakel versie meldingen uit
                localStorage.setItem('tv_alert', 'dont_show');
                
                // Schakel nieuwe functie hints uit
                localStorage.setItem('feature_hint_shown', 'true');
                
                // Stel in dat de nieuwe versie al is weergegeven
                localStorage.setItem('tv_twitter_notification', 'true');
                localStorage.setItem('tv_changelog_notification', 'true');
                
                // Schakel privacy meldingen uit
                localStorage.setItem('TVPrivacySettingsAccepted', 'true');
                
                // Onthoud gebruikersvoorkeuren
                localStorage.setItem('UserPreferences', '{"hiddenMarketBanners":{}}');
                
                // Schakel update meldingen uit
                localStorage.setItem('tv_alert_dialog_chart_v5', 'true');
                
                // Schakel specifiek de Stock Screener popup uit
                localStorage.setItem('screener_new_feature_notification', 'shown');
                localStorage.setItem('screener_deprecated', 'true');
                localStorage.setItem('tv_screener_notification', 'dont_show');
                localStorage.setItem('screener_new_feature_already_shown', 'true');
                localStorage.setItem('stock_screener_banner_closed', 'true');
                
                console.log('LocalStorage settings applied successfully');
            }, testMode);
            
            // Voeg CSS toe om Stock Screener popup te verbergen
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
                        position: absolute !important;
                        top: -9999px !important;
                        left: -9999px !important;
                        width: 0 !important;
                        height: 0 !important;
                        overflow: hidden !important;
                    }
                `
            });
            
            // Geef een constant interval om popups te detecteren en te sluiten (nieuwe aanpak)
            await page.evaluate((testModeValue) => {
                // Define testMode in this scope to make it available
                const testMode = testModeValue;
                
                // Functie om regelmatig alle dialogen te verwijderen
                function removeAllDialogs() {
                    console.log('Checking for dialogs to remove...');
                    
                    // Gebruik Escape key om dialogen te sluiten
                    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
                    
                    // 1. Zoek en klik op alle sluitingsknoppen
                    document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"], .nav-button-znwuaSC1').forEach(btn => {
                        try {
                            console.log('Found close button, clicking it');
                            btn.click();
                        } catch (e) {}
                    });
                    
                    // 2. Zoek speciek op SVG paden (X-pictogrammen in sluitknoppen)
                    document.querySelectorAll('svg path[d="m.58 1.42.82-.82 15 15-.82.82z"], svg path[d="m.58 15.58 15-15 .82.82-15 15z"]').forEach(path => {
                        try {
                            let button = path;
                            // Loop omhoog tot we een button vinden
                            while (button && button.tagName !== 'BUTTON') {
                                button = button.parentElement;
                                if (!button) break;
                            }
                            
                            if (button) {
                                console.log('Found button with SVG path, clicking it');
                                button.click();
                            }
                        } catch (e) {}
                    });
                    
                    // 3. Vind en klik op "Got it, thanks" knoppen
                    document.querySelectorAll('button').forEach(btn => {
                        if (btn.textContent.includes('Got it') || 
                            btn.textContent.includes('thanks') || 
                            btn.textContent.includes('OK') ||
                            btn.textContent.includes('Dismiss')) {
                            try {
                                console.log('Found "Got it" button, clicking it');
                                btn.click();
                            } catch (e) {}
                        }
                    });
                    
                    // 4. DIRECTE VERWIJDERING: Detecteer en verwijder alle dialoogelementen
                    const dialogs = document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog, .tv-dialog--popup');
                    console.log(`Found ${dialogs.length} dialogs to remove`);
                    
                    dialogs.forEach(dialog => {
                        try {
                            console.log('Removing dialog element');
                            dialog.style.display = 'none';
                            dialog.style.visibility = 'hidden';
                            dialog.style.opacity = '0';
                            if (dialog.parentNode) {
                                dialog.parentNode.removeChild(dialog);
                            }
                        } catch (e) {}
                    });
                    
                    // 5. Specifieke aanpak voor Stock Screener popup
                    const stockScreenerTexts = [
                        "Stock Screener is disappearing",
                        "Got it, thanks",
                        "Stock Screener", 
                        "notification"
                    ];
                    
                    // Zoek alle tekst nodes
                    const allTextElements = document.querySelectorAll('div, p, span, h1, h2, h3, h4, h5, button');
                    
                    allTextElements.forEach(el => {
                        const text = el.textContent.trim();
                        if (stockScreenerTexts.some(screenText => text.includes(screenText))) {
                            try {
                                console.log('Found element with Stock Screener text:', text);
                                
                                // Zoek de parent dialog
                                let dialog = el;
                                while (dialog && !dialog.matches('[role="dialog"], .tv-dialog, .js-dialog')) {
                                    dialog = dialog.parentElement;
                                    if (!dialog) break;
                                }
                                
                                if (dialog) {
                                    console.log('Found parent dialog of Stock Screener element, removing');
                                    dialog.style.display = 'none';
                                    if (dialog.parentNode) {
                                        dialog.parentNode.removeChild(dialog);
                                    }
                                    
                                    // Zoek en klik op de Got it knop
                                    const gotItBtn = dialog.querySelector('button');
                                    if (gotItBtn) {
                                        console.log('Clicking Got it button');
                                        gotItBtn.click();
                                    }
                                }
                            } catch (e) {}
                        }
                    });
                }
                
                // Roep de functie direct aan
                removeAllDialogs();
                
                // Stel een interval in om regelmatig te controleren op popups - minder frequent in testmodus
                window._popupRemovalInterval = setInterval(removeAllDialogs, testMode ? 100 : 500);
                
                // Stel ook een MutationObserver in om nieuwe elementen direct te detecteren
                const observer = new MutationObserver(mutations => {
                    // Controleer of er dialogen zijn toegevoegd
                    for (const mutation of mutations) {
                        if (mutation.addedNodes && mutation.addedNodes.length) {
                            for (const node of mutation.addedNodes) {
                                if (node.nodeType === 1) { // ELEMENT_NODE
                                    // Als het een dialoog is, verwijder het
                                    if (node.matches && (
                                        node.matches('[role="dialog"], .tv-dialog, .js-dialog') ||
                                        node.querySelector('[role="dialog"], .tv-dialog, .js-dialog, button.close-B02UUUN3')
                                    )) {
                                        console.log('MutationObserver: Found dialog, removing it');
                                        node.style.display = 'none';
                                        if (node.parentNode) {
                                            node.parentNode.removeChild(node);
                                        }
                                    }
                                    
                                    // Zoek close buttons en klik erop
                                    if (node.matches && node.matches('button.close-B02UUUN3, button[data-name="close"]')) {
                                        console.log('MutationObserver: Found close button, clicking it');
                                        node.click();
                                    }
                                }
                            }
                        }
                    }
                });
                
                // Start de observer
                observer.observe(document.body, { childList: true, subtree: true });
            }, testMode);
            
            // Wacht een langere tijd om de pagina en indicators te laten laden
            console.log('Waiting for page and indicators to render...');
            await page.waitForTimeout(testMode ? 1000 : 5000); // 1 of 5 seconden wachten voor dialogen
            
            // Direct aanpak om alle close buttons te klikken met Playwright
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
                            console.log(`Clicked button with selector ${selector}`);
                            await page.waitForTimeout(testMode ? 50 : 100); // Minimaal wachten na elke klik in testmodus
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
            
            // Als fullscreen is aangevraagd, geen extra stappen meer
            console.log('Additional fullscreen mode already applied via Shift+F');
            
            // Verberg UI elementen voor fullscreen
            console.log('Removing UI elements for fullscreen...');
            await page.evaluate((testModeValue) => {
                // Define testMode in this scope to make it available
                const testMode = testModeValue;
                
                try {
                    // Verberg alle UI elementen die de chart verbergen
                    const elementsToHide = [
                        '.chart-toolbar-container', // Chart toolbar
                        '.header-chart-panel', // Header panel
                        '.tv-side-toolbar', // Side toolbar
                        '#tv-chat-dialog', // Chat dialoog
                        '#tv-chart-dom-dialog', // DOM dialoog
                        '#footer-chart-panel', // Footer panel
                        '.bottom-widgetbar-content.widgetbar-content-floating', // Bottom widget bar
                        '.legend-Uu7k8Nav', // Legend
                        '.status-3LGcAzCN.statusWrap-3LGcAzCN', // Status bar
                        '.date-range-wrapper', // Date range wrapper
                        '.toolbar-2yU8ifXU', // Toolbar
                        '.chart-controls-bar', // Chart controls bar
                        '[data-role="toast-container"]', // Toast container
                        '.widgetbar-footer'  // Widget bar footer
                    ];
                    
                    elementsToHide.forEach(selector => {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            if (el) el.style.display = 'none';
                        });
                    });
                    
                    // Verwijder margins en paddings van de chart container
                    const chartContainer = document.querySelector('.chart-container');
                    if (chartContainer) {
                        chartContainer.style.margin = '0';
                        chartContainer.style.padding = '0';
                        chartContainer.style.width = '100vw';
                        chartContainer.style.height = '100vh';
                    }
                    
                    return true;
                } catch (e) {
                    return false;
                }
            }, testMode);
            
            // Skip de vertraging en knoppen zoeken - we hebben al Shift+F gebruikt
            console.log('Chart loaded or timeout reached');
            
            // Laatste kans om alle popups te sluiten
            await page.evaluate((testModeValue) => {
                // Define testMode in this scope to make it available
                const testMode = testModeValue;
                
                // Verwijder alle dialogen
                document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog, .tv-dialog--popup').forEach(dialog => {
                    dialog.style.display = 'none';
                    if (dialog.parentNode) {
                        dialog.parentNode.removeChild(dialog);
                    }
                });
                
                // Escape key indrukken om eventuele dialogen te sluiten
                document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
                
                // Klik alle close buttons
                document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"], button.nav-button-znwuaSC1').forEach(btn => {
                    try {
                        btn.click();
                    } catch (e) {}
                });
            }, testMode);
            
            // Wacht nog een laatste moment voor stabiliteit
            await page.waitForTimeout(testMode ? 200 : 2000); // 0.2 of 2 seconden voor volledige stabiliteit
            
            // Neem screenshot
            console.log('Taking screenshot...');
            await page.screenshot({
                path: outputPath,
                fullPage: false,
                clip: {
                    x: 0,
                    y: 0, 
                    width: Math.min(VIEWPORT_WIDTH, page.viewportSize().width),
                    height: Math.min(VIEWPORT_HEIGHT, page.viewportSize().height),
                }
            });
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
        process.exit(1);
    }
})();
