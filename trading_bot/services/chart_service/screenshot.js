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
        const context = await browser.newContext();
        
        // Voeg cookies toe als er een session ID is
        if (sessionId) {
            console.log(`Using session ID: ${sessionId.substring(0, 5)}...`);
            
            // Ga eerst naar TradingView om de cookies te kunnen instellen
            const page = await context.newPage();
            await page.goto('https://www.tradingview.com', {
                waitUntil: 'networkidle',
                timeout: 60000
            });
            
            // Voeg de session cookie toe
            await context.addCookies([
                {
                    name: 'sessionid',
                    value: sessionId,
                    domain: '.tradingview.com',
                    path: '/',
                    httpOnly: true,
                    secure: true,
                    sameSite: 'Lax'
                }
            ]);
            
            // Sluit deze pagina
            await page.close();
        }
        
        // Open een nieuwe pagina voor de screenshot
        const page = await context.newPage();
        
        // Ga naar de URL
        await page.goto(url, {
            waitUntil: 'networkidle',
            timeout: 60000
        });
        
        // Wacht even om de chart te laden
        await page.waitForTimeout(5000);
        
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
        }
        
        // Neem een screenshot
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
