const { chromium } = require('@playwright/test');

// Haal de argumenten op
const url = process.argv[2];
const outputPath = process.argv[3];
const sessionId = process.argv[4]; // Voeg session ID toe als derde argument

if (!url || !outputPath) {
    console.error('Usage: node screenshot.js <url> <outputPath> [sessionId]');
    process.exit(1);
}

(async () => {
    try {
        console.log(`Taking screenshot of ${url} and saving to ${outputPath}`);
        
        // Start een browser
        const browser = await chromium.launch({
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        });
        
        // Open een nieuwe pagina
        const context = await browser.newContext({
            locale: 'en-US', // Stel de locale in op Engels
            timezoneId: 'Europe/Amsterdam', // Stel de tijdzone in op Amsterdam
            viewport: { width: 1920, height: 1080 } // Stel een grotere viewport in
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
                }
            ]);
        }
        
        // Open een nieuwe pagina voor de screenshot
        const page = await context.newPage();
        
        // Stel headers in voor Engelse taal
        await page.setExtraHTTPHeaders({
            'Accept-Language': 'en-US,en;q=0.9'
        });
        
        // Stel een langere timeout in
        page.setDefaultTimeout(120000);
        
        try {
            // Ga naar de URL met minder strenge wachttijd
            console.log(`Navigating to ${url}...`);
            await page.goto(url, {
                waitUntil: 'domcontentloaded', // Minder streng dan 'networkidle'
                timeout: 90000
            });
            
            // Wacht een vaste tijd
            console.log('Waiting for page to render...');
            await page.waitForTimeout(15000);
            
            // Controleer of we zijn ingelogd (alleen voor logging)
            const isLoggedIn = await page.evaluate(() => {
                // Verschillende manieren om te controleren of we zijn ingelogd
                const hasLogoutButton = document.body.innerText.includes('Log out');
                const hasAccountButton = document.body.innerText.includes('Account');
                const hasUserMenuButton = document.querySelector('.tv-header__user-menu-button') !== null;
                const hasUserAvatar = document.querySelector('.tv-header__user-avatar') !== null;
                
                console.log('Login checks:', {
                    hasLogoutButton,
                    hasAccountButton,
                    hasUserMenuButton,
                    hasUserAvatar
                });
                
                return hasLogoutButton || hasAccountButton || hasUserMenuButton || hasUserAvatar;
            });
            
            console.log(`Logged in status: ${isLoggedIn}`);
            
            // Wacht nog wat langer als we zijn ingelogd om custom indicators te laden
            if (isLoggedIn) {
                console.log('Waiting for custom indicators to load...');
                await page.waitForTimeout(5000);
            }
            
            // Verberg de zijbalk en maak fullscreen (altijd, ongeacht login status)
            console.log('Making chart fullscreen...');
            
            // Probeer verschillende methoden voor fullscreen
            try {
                // Methode 1: Gebruik de TradingView shortcut 'F'
                await page.keyboard.press('F');
                await page.waitForTimeout(1000);
                
                // Methode 2: Klik op de fullscreen knop als deze bestaat
                const fullscreenButton = await page.$('.js-chart-actions-fullscreen');
                if (fullscreenButton) {
                    await fullscreenButton.click();
                    console.log('Clicked fullscreen button');
                    await page.waitForTimeout(1000);
                }
                
                // Methode 3: Gebruik JavaScript om de chart te maximaliseren
                await page.evaluate(() => {
                    // Verberg alle UI elementen
                    const elementsToHide = [
                        '.tv-header',                  // Header
                        '.chart-toolbar',              // Chart toolbar
                        '.tv-side-toolbar',            // Side toolbar
                        '.tv-floating-toolbar',        // Floating toolbar
                        '.layout__area--left',         // Left sidebar
                        '.layout__area--right',        // Right sidebar
                        '.tv-watermark',               // TradingView watermark
                        '.tv-chart-toolbar',           // Chart toolbar
                        '.tv-main-panel--top-toolbar', // Top toolbar
                        '.tv-main-panel--bottom-toolbar', // Bottom toolbar
                        '.tv-chart-studies',           // Studies panel
                        '.tv-dialog',                  // Any open dialogs
                        '.tv-insert-study-dialog',     // Study dialog
                        '.tv-insert-indicator-dialog', // Indicator dialog
                        '.tv-linetool-properties-toolbar', // Line tool properties
                        '.chart-controls-bar',         // Controls bar
                        '.layout__area'                // Alle layout areas (inclusief zwarte balken)
                    ];
                    
                    // Verberg alle elementen
                    elementsToHide.forEach(selector => {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            if (el) el.style.display = 'none';
                        });
                    });
                    
                    // Verwijder alle marges en padding van alle elementen
                    document.querySelectorAll('*').forEach(el => {
                        el.style.margin = '0';
                        el.style.padding = '0';
                    });
                    
                    // Maximaliseer de chart container
                    const chartContainer = document.querySelector('.chart-container');
                    if (chartContainer) {
                        chartContainer.style.width = '100vw';
                        chartContainer.style.height = '100vh';
                        chartContainer.style.position = 'fixed';
                        chartContainer.style.top = '0';
                        chartContainer.style.left = '0';
                        chartContainer.style.zIndex = '9999';
                        chartContainer.style.margin = '0';
                        chartContainer.style.padding = '0';
                        chartContainer.style.border = 'none';
                        chartContainer.style.backgroundColor = '#131722'; // TradingView achtergrondkleur
                    }
                    
                    // Maximaliseer de chart zelf
                    const chartElement = document.querySelector('.chart-markup-table');
                    if (chartElement) {
                        chartElement.style.width = '100vw';
                        chartElement.style.height = '100vh';
                        chartElement.style.margin = '0';
                        chartElement.style.padding = '0';
                        chartElement.style.border = 'none';
                    }
                    
                    // Maximaliseer de canvas
                    const canvas = document.querySelector('canvas');
                    if (canvas) {
                        canvas.style.width = '100vw';
                        canvas.style.height = '100vh';
                    }
                    
                    // Verwijder marges en padding van body en html
                    document.body.style.margin = '0';
                    document.body.style.padding = '0';
                    document.body.style.overflow = 'hidden';
                    document.body.style.backgroundColor = '#131722'; // TradingView achtergrondkleur
                    
                    document.documentElement.style.margin = '0';
                    document.documentElement.style.padding = '0';
                    document.documentElement.style.overflow = 'hidden';
                    document.documentElement.style.backgroundColor = '#131722'; // TradingView achtergrondkleur
                    
                    // Verwijder alle zwarte balken
                    document.querySelectorAll('.layout__area').forEach(el => {
                        if (el) el.style.display = 'none';
                    });
                    
                    // Maximaliseer de main pane
                    const mainPane = document.querySelector('.chart-container .layout__area--center, .chart-container .layout__area--main');
                    if (mainPane) {
                        mainPane.style.width = '100vw';
                        mainPane.style.height = '100vh';
                        mainPane.style.position = 'fixed';
                        mainPane.style.top = '0';
                        mainPane.style.left = '0';
                        mainPane.style.margin = '0';
                        mainPane.style.padding = '0';
                        mainPane.style.border = 'none';
                    }
                    
                    // Zoom in op de chart
                    try {
                        // Methode 1: Gebruik de TradingView zoom functie
                        const zoomInButton = document.querySelector('.control-bar__btn--zoom-in');
                        if (zoomInButton) {
                            // Klik meerdere keren op de zoom-in knop
                            for (let i = 0; i < 3; i++) {
                                zoomInButton.click();
                            }
                            console.log('Zoomed in using zoom button');
                        }
                        
                        // Methode 2: Pas de schaal van de chart aan
                        const chartScaleElement = document.querySelector('.chart-markup-table');
                        if (chartScaleElement) {
                            chartScaleElement.style.transform = 'scale(1.2)';
                            chartScaleElement.style.transformOrigin = 'center center';
                            console.log('Applied scale transform to chart');
                        }
                        
                        // Methode 3: Pas de viewport aan
                        const panes = document.querySelectorAll('.chart-markup-table pane');
                        if (panes.length > 0) {
                            panes.forEach(pane => {
                                if (pane) {
                                    pane.style.transform = 'scale(1.2)';
                                    pane.style.transformOrigin = 'center center';
                                }
                            });
                            console.log('Applied scale transform to panes');
                        }
                    } catch (error) {
                        console.error('Error applying zoom:', error);
                    }
                });
                
                console.log('Applied fullscreen optimizations');
            } catch (error) {
                console.error('Error applying fullscreen:', error);
            }
            
            // Wacht langer om de UI aanpassingen te verwerken
            console.log('Waiting longer for UI changes to take effect...');
            await page.waitForTimeout(5000); // Verhoog naar 5 seconden
            
            // Controleer of alle UI elementen echt weg zijn
            await page.evaluate(() => {
                // Nog een keer alle UI elementen verbergen voor de zekerheid
                const elementsToHide = [
                    '.tv-header',                  // Header
                    '.chart-toolbar',              // Chart toolbar
                    '.tv-side-toolbar',            // Side toolbar
                    '.tv-floating-toolbar',        // Floating toolbar
                    '.layout__area--left',         // Left sidebar
                    '.layout__area--right',        // Right sidebar
                    '.tv-watermark',               // TradingView watermark
                    '.tv-chart-toolbar',           // Chart toolbar
                    '.tv-main-panel--top-toolbar', // Top toolbar
                    '.tv-main-panel--bottom-toolbar', // Bottom toolbar
                    '.tv-chart-studies',           // Studies panel
                    '.tv-dialog',                  // Any open dialogs
                    '.tv-insert-study-dialog',     // Study dialog
                    '.tv-insert-indicator-dialog', // Indicator dialog
                    '.tv-linetool-properties-toolbar', // Line tool properties
                    '.chart-controls-bar',         // Controls bar
                    '.layout__area'                // Alle layout areas (inclusief zwarte balken)
                ];
                
                // Verberg alle elementen
                elementsToHide.forEach(selector => {
                    const elements = document.querySelectorAll(selector);
                    elements.forEach(el => {
                        if (el) el.style.display = 'none';
                    });
                });
                
                // Zorg ervoor dat de chart container de volledige viewport vult
                const chartContainer = document.querySelector('.chart-container');
                if (chartContainer) {
                    chartContainer.style.width = '100vw';
                    chartContainer.style.height = '100vh';
                    chartContainer.style.position = 'fixed';
                    chartContainer.style.top = '0';
                    chartContainer.style.left = '0';
                }
                
                console.log('Double-checked UI elements are hidden');
            });
            
            // Wacht nog een keer voor de zekerheid
            await page.waitForTimeout(2000);
            
            // Probeer ook in te zoomen met toetsenbord
            try {
                // Druk op de '+' toets om in te zoomen
                for (let i = 0; i < 3; i++) {
                    await page.keyboard.press('+');
                    await page.waitForTimeout(300);
                }
                console.log('Pressed + key to zoom in');
            } catch (error) {
                console.error('Error pressing + key:', error);
            }
            
            // Wacht nog even om de zoom aanpassingen te verwerken
            await page.waitForTimeout(1000);
            
        } catch (error) {
            console.error('Error loading page, trying to take screenshot anyway:', error);
        }
        
        // Neem een screenshot
        console.log('Taking screenshot...');
        await page.screenshot({
            path: outputPath,
            fullPage: false,
            clip: {
                x: 0,
                y: 0,
                width: 1920,
                height: 1080
            }
        });
        
        // Sluit de browser
        await browser.close();
        
        console.log('Screenshot taken successfully');
        process.exit(0);
    } catch (error) {
        console.error('Error taking screenshot:', error);
        process.exit(1);
    }
})(); 
