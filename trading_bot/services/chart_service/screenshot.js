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
        
        // Wacht tot de pagina volledig is geladen
        console.log('Waiting for the chart to fully load...');
        await page.waitForTimeout(15000); // Wacht 15 seconden
        await page.waitForSelector('.chart-container', { state: 'attached', timeout: 30000 });
        await page.waitForSelector('.chart-container .candlestick', { state: 'visible', timeout: 30000 });

        // Maak de chart fullscreen en verwijder UI-elementen
        console.log('Making chart fullscreen and removing UI elements...');
        await page.evaluate(() => {
            // Probeer de volledige schermmodus te forceren
            document.documentElement.requestFullscreen().catch(err => {
                console.error(`Error attempting fullscreen: ${err.message}`);
            });

            // Verberg de header
            const header = document.querySelector('header');
            if (header) header.style.display = 'none';

            // Verberg de footer
            const footer = document.querySelector('footer');
            if (footer) footer.style.display = 'none';

            // Verberg de sidebar
            const sidebar = document.querySelector('.sidebar');
            if (sidebar) sidebar.style.display = 'none';

            // Verberg de toolbar
            const toolbar = document.querySelector('.chart-toolbar');
            if (toolbar) toolbar.style.display = 'none';

            // Verberg andere ongewenste elementen
            const unwantedElements = document.querySelectorAll('.unwanted-class');
            unwantedElements.forEach(element => element.style.display = 'none');

            // Maak de chart-container fullscreen
            const chart = document.querySelector('.chart-container');
            if (chart) {
                chart.style.position = 'fixed';
                chart.style.top = '0';
                chart.style.left = '0';
                chart.style.width = '100vw';
                chart.style.height = '100vh';
                chart.style.zIndex = '1000';
            }

            // Maak de achtergrond transparant
            document.body.style.backgroundColor = 'transparent';
        });

        // Neem een fullscreen screenshot
        console.log('Taking fullscreen screenshot...');
        await page.screenshot({
            path: outputPath,
            fullPage: true, // Maak een volledige pagina-screenshot
            omitBackground: true // Verwijder de achtergrond voor een transparante screenshot
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
