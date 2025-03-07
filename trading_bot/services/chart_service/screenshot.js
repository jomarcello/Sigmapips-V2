const playwright = require('playwright');

const url = process.argv[2];
const outputPath = process.argv[3];

(async () => {
    const browser = await playwright.chromium.launch({
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });

    const context = await browser.newContext({
        viewport: { width: 2560, height: 1440 }
    });

    const page = await context.newPage();
    await page.goto(url, { waitUntil: 'domcontentloaded' });

    // Wacht totdat TradingView geladen is
    await page.waitForTimeout(5000);
    
    // Verberg UI-elementen die de afbeelding kunnen beïnvloeden
    await page.evaluate(() => {
        document.body.style.overflow = 'hidden'; // Voorkom scrollbars
        const elementsToHide = [
            '.tv-header', '.tv-footer', '.sidebar', 
            '.chart-toolbar', '.tv-side-toolbar', '.chart-panel'
        ];
        elementsToHide.forEach(selector => {
            const el = document.querySelector(selector);
            if (el) el.style.display = 'none';
        });

        // Forceer de grafiek-container om 100% van het scherm te vullen
        const chartContainer = document.querySelector('.chart-container');
        if (chartContainer) {
            chartContainer.style.position = 'fixed';
            chartContainer.style.top = '0';
            chartContainer.style.left = '0';
            chartContainer.style.width = '100vw';
            chartContainer.style.height = '100vh';
        }
    });

    // Extra wachttijd om wijzigingen te laten verwerken
    await page.waitForTimeout(3000);

    // Maak screenshot
    await page.screenshot({ path: outputPath, fullPage: false });

    await browser.close();
    console.log('Screenshot succesvol opgeslagen:', outputPath);
})();
