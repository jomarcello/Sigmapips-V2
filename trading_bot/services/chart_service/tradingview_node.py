// Probeer verschillende manieren om Playwright te importeren
let playwright;
let chromium;

try {
    // Probeer eerst @playwright/test
    playwright = require('@playwright/test');
    chromium = playwright.chromium;
    console.log("Using @playwright/test module");
} catch (e) {
    try {
        // Als dat niet lukt, probeer playwright
        playwright = require('playwright');
        chromium = playwright.chromium;
        console.log("Using playwright module");
    } catch (e2) {
        console.error('Geen Playwright module gevonden. Installeer met: npm install playwright of npm install @playwright/test');
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

(async () => {
    try {
        console.log(`Taking screenshot of ${url} and saving to ${outputPath} (fullscreen: ${fullscreen})`);
        
        // Start een browser
        const browser = await playwright.chromium.launch({
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
        
        // Ga naar de URL
        console.log(`Navigating to ${url}...`);
        await page.goto(url, {
            waitUntil: 'domcontentloaded',
            timeout: 90000
        });
        
        // Wacht een vaste tijd om de pagina te laten renderen
        console.log('Waiting for page to render...');
        await page.waitForTimeout(10000);

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
            await page.waitForTimeout(2000);
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
