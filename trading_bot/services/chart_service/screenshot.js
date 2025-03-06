let playwright;
try {
    playwright = require('@playwright/test');
} catch (e) {
    try {
        playwright = require('playwright');
    } catch (e2) {
        console.error('Geen Playwright module gevonden. Installeer met: npm install playwright');
        process.exit(1);
    }
}

const { chromium } = playwright;

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
                    // Verberg alleen de belangrijkste UI elementen
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
                        '.chart-controls-bar'          // Controls bar
                    ];
                    
                    // Verberg alleen de specifieke UI elementen
                    elementsToHide.forEach(selector => {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            if (el) {
                                el.style.display = 'none';
                            }
                        });
                    });
                    
                    // Maximaliseer de chart container zonder andere stijlen aan te passen
                    const chartContainer = document.querySelector('.chart-container');
                    if (chartContainer) {
                        chartContainer.style.width = '100vw';
                        chartContainer.style.height = '100vh';
                        chartContainer.style.position = 'fixed';
                        chartContainer.style.top = '0';
                        chartContainer.style.left = '0';
                        chartContainer.style.zIndex = '9999';
                    }
                    
                    // Zorg ervoor dat de chart zichtbaar blijft
                    const chartArea = document.querySelector('.chart-markup-table');
                    if (chartArea) {
                        chartArea.style.display = 'block';
                        chartArea.style.visibility = 'visible';
                        chartArea.style.opacity = '1';
                    }
                    
                    console.log('Applied fullscreen optimizations while keeping chart visible');
                });
                
                console.log('Applied fullscreen optimizations');
            } catch (error) {
                console.error('Error applying fullscreen:', error);
            }
            
            // Wacht langer om de UI aanpassingen te verwerken
            console.log('Waiting longer for UI changes to take effect...');
            await page.waitForTimeout(10000); // Verhoog naar 10 seconden
            
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
                
                // Zorg ervoor dat de chart zichtbaar blijft
                const chartArea = document.querySelector('.chart-markup-table');
                if (chartArea) {
                    chartArea.style.display = 'block';
                    chartArea.style.visibility = 'visible';
                    chartArea.style.opacity = '1';
                }
                
                console.log('Double-checked UI elements are hidden and chart is visible');
            });
            
            // Wacht nog een keer voor de zekerheid
            await page.waitForTimeout(3000);
            
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
