const playwright = require('playwright');

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
        const browser = await playwright.chromium.launch({
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        });
        
        // Open een nieuwe pagina
        const context = await browser.newContext({
            locale: 'en-US',
            timezoneId: 'Europe/Amsterdam',
            viewport: { width: 1920, height: 1080 }
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
                }
            ]);
        }
        
        const page = await context.newPage();
        
        // Ga naar de URL
        console.log(`Navigating to ${url}...`);
        await page.goto(url, {
            waitUntil: 'domcontentloaded',
            timeout: 90000
        });

        // Wacht totdat de TradingView-grafiek geladen is
        console.log('Waiting for the chart to fully load...');
        await page.waitForTimeout(15000);
        await page.waitForSelector('.chart-container', { state: 'attached', timeout: 30000 });

        // Forceer de TradingView grafiek in fullscreen modus
        console.log('Forcing TradingView into fullscreen mode...');
        await page.evaluate(() => {
            const chart = document.querySelector('.chart-container');
            if (chart) {
                chart.style.position = 'fixed';
                chart.style.top = '0';
                chart.style.left = '0';
                chart.style.width = '100vw';
                chart.style.height = '100vh';
                chart.style.zIndex = '1000';
            }

            // Verberg ongewenste UI-elementen
            const elementsToHide = [
                'header', 'footer', '.sidebar', '.chart-toolbar', '.tv-side-toolbar', 
                '.tv-header', '.tv-footer', '.chart-panel'
            ];
            elementsToHide.forEach(selector => {
                const el = document.querySelector(selector);
                if (el) el.style.display = 'none';
            });

            // Simuleer de "Fullscreen" toets (F11) in TradingView
            const fullscreenButton = document.querySelector('[data-name="fullscreen-button"]');
            if (fullscreenButton) fullscreenButton.click();
        });

        // Extra wachttijd om ervoor te zorgen dat fullscreen correct wordt toegepast
        await page.waitForTimeout(5000);

        // Neem een fullscreen screenshot
        console.log('Taking fullscreen screenshot...');
        await page.screenshot({
            path: outputPath,
            fullPage: false, // Zet op false om alleen het zichtbare deel vast te leggen
            omitBackground: true
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
