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

const { chromium } = require('playwright');
const fs = require('fs');

// Haal de argumenten op
const url = process.argv[2];
const outputPath = process.argv[3];
const sessionId = process.argv[4] || '';
const fullscreen = process.argv[5] === 'fullscreen';

// Log de argumenten voor debugging
console.log(`URL: ${url}`);
console.log(`Output path: ${outputPath}`);
console.log(`Session ID: ${sessionId ? 'Provided' : 'Not provided'}`);
console.log(`Fullscreen: ${fullscreen}`);

(async () => {
    try {
        console.log(`Taking screenshot of ${url} and saving to ${outputPath} (fullscreen: ${fullscreen})`);
        
        // Start een browser
        const browser = await chromium.launch({
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });
        
        // Maak een nieuwe context en pagina
        const context = await browser.newContext({
            viewport: { width: 1280, height: 800 },
            deviceScaleFactor: 1,
        });
        
        // Voeg cookies toe als er een session ID is
        if (sessionId) {
            await context.addCookies([
                {
                    name: 'sessionid',
                    value: sessionId,
                    domain: '.tradingview.com',
                    path: '/',
                }
            ]);
            console.log('Added TradingView session cookie');
        }
        
        const page = await context.newPage();
        
        // Navigeer naar de URL
        console.log(`Navigating to ${url}`);
        await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
        
        // Als het een TradingView URL is, wacht dan op de chart
        if (url.includes('tradingview.com')) {
            console.log('Waiting for TradingView chart to load...');
            
            // Wacht op de chart container
            await page.waitForSelector('.chart-container', { timeout: 30000 });
            
            // Wacht extra tijd voor de chart om volledig te laden
            await page.waitForTimeout(5000);
            
            // Als fullscreen is aangevraagd, simuleer Shift+F
            if (fullscreen || url.includes('fullscreen=true')) {
                console.log('Enabling fullscreen mode...');
                await page.keyboard.press('F11');
                await page.waitForTimeout(1000);
            }
            
            console.log('Chart loaded, taking screenshot...');
        } else {
            console.log('Not a TradingView URL, waiting for page load...');
            await page.waitForTimeout(3000);
        }
        
        // Neem een screenshot
        await page.screenshot({ path: outputPath });
        console.log(`Screenshot saved to ${outputPath}`);
        
        // Sluit de browser
        await browser.close();
        
        console.log('Done!');
        process.exit(0);
    } catch (error) {
        console.error('Error:', error);
        await browser.close();
        process.exit(1);
    }
})(); 
