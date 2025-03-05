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
            timezoneId: 'Europe/Amsterdam' // Stel de tijdzone in op Amsterdam
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
            
            // Controleer of we zijn ingelogd
            const isLoggedIn = await page.evaluate(() => {
                return document.body.innerText.includes('Log out') || 
                       document.body.innerText.includes('Account') ||
                       document.querySelector('.tv-header__user-menu-button') !== null;
            });
            
            console.log(`Logged in status: ${isLoggedIn}`);
            
            // Wacht nog wat langer als we zijn ingelogd om custom indicators te laden
            if (isLoggedIn) {
                console.log('Waiting for custom indicators to load...');
                await page.waitForTimeout(5000);
                
                // Verberg de zijbalk en maak fullscreen
                console.log('Making chart fullscreen...');
                
                // Probeer eerst de TradingView shortcut voor fullscreen
                await page.keyboard.press('F');
                await page.waitForTimeout(1000);
                
                // Verberg UI elementen via JavaScript
                await page.evaluate(() => {
                    // Verberg de header
                    const header = document.querySelector('.tv-header');
                    if (header) header.style.display = 'none';
                    
                    // Verberg andere UI elementen
                    const elements = document.querySelectorAll('.chart-toolbar, .tv-side-toolbar, .tv-floating-toolbar, .layout__area--left, .layout__area--right');
                    elements.forEach(el => {
                        if (el) el.style.display = 'none';
                    });
                    
                    // Verberg de "Open in TradingView" link
                    const tvLink = document.querySelector('.tv-watermark');
                    if (tvLink) tvLink.style.display = 'none';
                    
                    // Maximaliseer de chart
                    const chartContainer = document.querySelector('.chart-container');
                    if (chartContainer) {
                        chartContainer.style.width = '100vw';
                        chartContainer.style.height = '100vh';
                    }
                });
                
                console.log('Hid UI elements and maximized chart');
                
                // Wacht nog even om de UI aanpassingen te verwerken
                await page.waitForTimeout(2000);
            }
            
        } catch (error) {
            console.error('Error loading page, trying to take screenshot anyway:', error);
        }
        
        // Neem een screenshot
        console.log('Taking screenshot...');
        await page.screenshot({
            path: outputPath,
            fullPage: false
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
