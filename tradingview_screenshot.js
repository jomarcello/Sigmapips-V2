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
const fullscreen = process.argv[5] === 'fullscreen'; // Controleer of fullscreen is ingeschakeld

if (!url || !outputPath) {
    console.error('Usage: node screenshot.js <url> <outputPath> [sessionId] [fullscreen]');
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
        page.setDefaultTimeout(180000); // 3 minuten timeout
        
        try {
            // Ga naar de URL
            console.log(`Navigating to ${url}...`);
            await page.goto(url, {
                waitUntil: 'domcontentloaded',
                timeout: 120000 // 2 minuten timeout voor navigatie
            });
            
            // Stel localStorage waarden in om meldingen uit te schakelen
            console.log('Setting localStorage values to disable notifications...');
            await page.evaluate(() => {
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
            });
            
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
            await page.evaluate(() => {
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
                
                // Stel een interval in om regelmatig te controleren op popups
                window._popupRemovalInterval = setInterval(removeAllDialogs, 500);
                
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
            });
            
            // Wacht een langere tijd om de pagina en indicators te laten laden
            console.log('Waiting for page and indicators to render...');
            await page.waitForTimeout(5000); // 5 seconden wachten voor dialogen
            
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
                            await page.waitForTimeout(100); // Kort wachten na elke klik
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
                
                // Wacht even om de wijzigingen toe te passen
                await page.waitForTimeout(1000);
            }
            
            // Altijd Shift+F indrukken om fullscreen te activeren, ongeacht de fullscreen parameter
            console.log('Activating fullscreen mode with Shift+F keyboard shortcut...');
            
            // Zorg ervoor dat de chart eerst gefocust is voordat we de toetscombinatie gebruiken
            await page.evaluate(() => {
                // Focus op de chart container om toetsaanslagen te laten werken
                const chartContainer = document.querySelector('.chart-container');
                if (chartContainer) {
                    chartContainer.focus();
                    console.log('Focused on chart container');
                }
                
                // Als alternatief, simuleer ook de toggle fullscreen functie direct
                try {
                    // Probeer eventuele TradingView fullscreen functie aan te roepen als deze bestaat
                    if (window.TradingView && window.TradingView.ChartAPI) {
                        const chartInstance = Object.values(window.TradingView.ChartAPI._instances)[0];
                        if (chartInstance && typeof chartInstance.toggleFullscreen === 'function') {
                            chartInstance.toggleFullscreen();
                            console.log('Called TradingView fullscreen toggle directly');
                            return true;
                        }
                    }
                } catch (e) {
                    console.log('Error trying to call toggleFullscreen directly:', e);
                }
                
                return false;
            });
            
            // Probeer de toetscombinatie
            await page.keyboard.down('Shift');
            await page.keyboard.press('F');
            await page.keyboard.up('Shift');
            
            // Alternatief probeer ook F11 als backup
            await page.keyboard.press('F11');
            
            await page.waitForTimeout(2000); // Wacht even zodat fullscreen kan worden toegepast
            
            // Probeer ook de fullscreen button te vinden en te klikken
            console.log('Trying to find and click the fullscreen button...');
            try {
                // Zoek naar de fullscreen knop in de UI
                const fullscreenButtonSelectors = [
                    'button[data-name="full-screen"]',
                    'button[data-tooltip="Toggle Fullscreen Mode (Shift+F)"]',
                    'button.fullscreen-button',
                    'button.button-Wgfb_fN3:has(svg)', // TradingView's icon button format
                    'button:has(svg[data-name="maximize"])',
                ];
                
                for (const selector of fullscreenButtonSelectors) {
                    const buttons = await page.$$(selector);
                    console.log(`Found ${buttons.length} buttons with selector ${selector}`);
                    
                    for (const button of buttons) {
                        try {
                            await button.click({ force: true }).catch(() => {});
                            console.log(`Clicked fullscreen button with selector ${selector}`);
                            break;
                        } catch (e) {
                            console.log(`Error clicking button with selector ${selector}:`, e);
                        }
                    }
                }
                
                // Als directe methode, probeer op de maximaliseerknop in de JS-API te klikken
                await page.evaluate(() => {
                    try {
                        // Zoek naar alle knoppen en probeer degene met maximalisatie/fullscreen attributen te vinden
                        const allButtons = document.querySelectorAll('button');
                        for (const btn of allButtons) {
                            const btnText = btn.innerText.toLowerCase();
                            const btnTitle = (btn.getAttribute('title') || '').toLowerCase();
                            const btnTooltip = (btn.getAttribute('data-tooltip') || '').toLowerCase();
                            
                            if (btnText.includes('fullscreen') || 
                                btnTitle.includes('fullscreen') || 
                                btnTooltip.includes('fullscreen') ||
                                btnText.includes('maximize') || 
                                btnTitle.includes('maximize') ||
                                btnTooltip.includes('maximize') ||
                                btnTooltip.includes('shift+f')) {
                                console.log('Found fullscreen button via text/attributes');
                                btn.click();
                                return true;
                            }
                        }
                        
                        // Als we het nog niet hebben gevonden, zoek naar svg-iconen
                        const svgMaximizeIcons = document.querySelectorAll('svg[data-name="maximize"]');
                        if (svgMaximizeIcons.length > 0) {
                            for (const icon of svgMaximizeIcons) {
                                let button = icon;
                                // Zoek naar de bovenliggende knop
                                while (button && button.tagName !== 'BUTTON') {
                                    button = button.parentElement;
                                    if (!button) break;
                                }
                                
                                if (button) {
                                    console.log('Found fullscreen button via SVG icon');
                                    button.click();
                                    return true;
                                }
                            }
                        }
                    } catch (e) {
                        console.log('Error trying to find and click fullscreen button:', e);
                    }
                    return false;
                });
            } catch (e) {
                console.log('Error attempting to click fullscreen button:', e);
            }
            
            // Wacht nog een moment zodat fullscreen kan worden toegepast
            await page.waitForTimeout(2000);
            
            // Forceer maximale chart weergave met CSS (werk altijd, ongeacht fullscreen parameter)
            console.log('Applying CSS to maximize chart view...');
            await page.addStyleTag({
                content: `
                    /* Verberg alle UI elementen die niet nodig zijn voor de chart */
                    .tv-header, 
                    .js-rootresizer__contents,
                    .tv-side-toolbar,
                    .layout__area--left,
                    .layout__area--right,
                    .layout__area--top,
                    .layout__area--bottom,
                    .tv-floating-toolbar,
                    .tv-dialog-wrapper,
                    .tv-main-panel__toolbar,
                    .tv-main-panel__statuses,
                    .header-chart-panel,
                    footer,
                    .tv-dialog,
                    .tv-insert-study-dialog,
                    .tv-objects-tree-dialog {
                        display: none !important;
                        visibility: hidden !important;
                        opacity: 0 !important;
                        width: 0 !important;
                        height: 0 !important;
                        overflow: hidden !important;
                    }
                    
                    /* Maximaliseer de chart container */
                    .chart-container,
                    .chart-markup-table,
                    .chart-page,
                    .layout__area--center,
                    .trading-layout,
                    .layout-with-border-container,
                    .layout__area {
                        width: 100vw !important;
                        height: 100vh !important;
                        max-width: 100vw !important;
                        max-height: 100vh !important;
                        position: fixed !important;
                        top: 0 !important;
                        left: 0 !important;
                        margin: 0 !important;
                        padding: 0 !important;
                        border: none !important;
                        z-index: 999 !important;
                        overflow: hidden !important;
                    }
                    
                    /* Forceer de chart om de volledige grootte te gebruiken */
                    .chart-container [data-name="legend"],
                    .chart-container [data-name="labels"] {
                        display: none !important;
                    }
                    
                    /* Set chart content to take full space */
                    body, html {
                        overflow: hidden !important;
                        margin: 0 !important;
                        padding: 0 !important;
                    }
                `
            });
            
            // Probeer de chart maximaal te maken met JavaScript
            await page.evaluate(() => {
                try {
                    // Forceer maximale afmetingen op alle chart gerelateerde elementen
                    const chartElements = document.querySelectorAll('.chart-container, .chart-markup-table, .chart-page, .layout__area--center, .trading-layout');
                    chartElements.forEach(el => {
                        el.style.width = '100vw';
                        el.style.height = '100vh';
                        el.style.maxWidth = '100vw';
                        el.style.maxHeight = '100vh';
                        el.style.position = 'fixed';
                        el.style.top = '0';
                        el.style.left = '0';
                        el.style.margin = '0';
                        el.style.padding = '0';
                        el.style.zIndex = '999';
                    });
                    
                    // Verberg alle UI elementen
                    const uiElements = document.querySelectorAll('.tv-header, .tv-side-toolbar, .layout__area--left, .layout__area--right, .tv-main-panel__toolbar');
                    uiElements.forEach(el => {
                        el.style.display = 'none';
                    });
                    
                    // Roep viewport resize events aan om de chart te forceren om opnieuw te tekenen
                    window.dispatchEvent(new Event('resize'));
                } catch (e) {
                    console.log('Error maximizing chart:', e);
                }
            });
            
            // Wacht nog wat langer als we zijn ingelogd om custom indicators te laden
            if (isLoggedIn) {
                console.log('Waiting for custom indicators to load...');
                await page.waitForTimeout(5000); // 5 seconden voor custom indicators
            }
            
            // Wacht tot de chart volledig is geladen
            console.log('Waiting for chart to be fully loaded...');
            await page.waitForFunction(() => {
                // Controleer of de loading indicator verdwenen is
                const loadingIndicator = document.querySelector('.loading-indicator');
                if (loadingIndicator && window.getComputedStyle(loadingIndicator).display !== 'none') {
                    console.log('Loading indicator still visible');
                    return false;
                }
                
                // Controleer of de chart container zichtbaar is
                const chartContainer = document.querySelector('.chart-container');
                if (!chartContainer) {
                    console.log('Chart container not found');
                    return false;
                }
                
                // Controleer of de chart container zichtbaar is
                const isVisible = window.getComputedStyle(chartContainer).visibility !== 'hidden';
                if (!isVisible) {
                    console.log('Chart container is hidden');
                    return false;
                }
                
                // Controleer of er een error message zichtbaar is
                const errorMessage = document.querySelector('.tv-error-card');
                if (errorMessage && window.getComputedStyle(errorMessage).display !== 'none') {
                    console.log('Error message is visible:', errorMessage.textContent);
                    return false;
                }
                
                return true;
            }, { timeout: 30000 }).catch(e => {
                console.error('Error waiting for chart to load:', e);
                // We gaan door, ook al is er een timeout
            });
            
            // Laatste kans om alle popups te sluiten
            await page.evaluate(() => {
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
            });
            
            // Wacht nog een laatste moment voor stabiliteit
            await page.waitForTimeout(2000); // 2 seconden voor volledige stabiliteit
            
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
        process.exit(1);
    }
})();
