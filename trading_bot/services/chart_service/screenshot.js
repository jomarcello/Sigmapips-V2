const puppeteer = require('puppeteer');

// Haal de argumenten op
const url = process.argv[2];
const outputPath = process.argv[3];

if (!url || !outputPath) {
    console.error('Usage: node screenshot.js <url> <outputPath>');
    process.exit(1);
}

(async () => {
    try {
        console.log(`Taking screenshot of ${url} and saving to ${outputPath}`);
        
        // Start een browser
        const browser = await puppeteer.launch({
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        });
        
        // Open een nieuwe pagina
        const page = await browser.newPage();
        
        // Stel de viewport in
        await page.setViewport({
            width: 1280,
            height: 800
        });
        
        // Ga naar de URL
        await page.goto(url, {
            waitUntil: 'networkidle2',
            timeout: 60000
        });
        
        // Wacht even om de chart te laden
        await page.waitForTimeout(5000);
        
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
