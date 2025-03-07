const playwright = require('playwright');

const url = process.argv[2];
const outputPath = process.argv[3];
const sessionId = process.argv[4];

if (!url || !outputPath) {
    console.error('Usage: node screenshot.js <url> <outputPath> [sessionId]');
    process.exit(1);
}

(async () => {
    try {
        console.log(`Taking screenshot of ${url} and saving to ${outputPath}`);

        const browser = await playwright.chromium.launch({
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        });

        const context = await browser.newContext({
            locale: 'en-US',
            timezoneId: 'Europe/Amsterdam',
            viewport: { width: 1920, height: 1080 }
        });

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
        console.log(`Navigating to ${url}...`);
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });

        console.log('Waiting for page to render...');
        await page.waitForTimeout(10000);

        console.log('Hiding UI elements...');
        await page.evaluate(() => {
            const selectors = [
                'header', 'footer', '.chart-controls-bar', '.layout__area--top',
                '.layout__area--right', '.layout__area--left', '.layout__area--bottom',
                '.chart-bottom-toolbar', '.js-rootresizer__contents'
            ];
            selectors.forEach(selector => {
                document.querySelectorAll(selector).forEach(el => el.remove());
            });
        });

        console.log('Taking fullscreen screenshot...');
        await page.screenshot({
            path: outputPath,
            fullPage: true,
            omitBackground: true
        });

        await browser.close();
        console.log('Screenshot taken successfully');
        process.exit(0);
    } catch (error) {
        console.error('Error taking screenshot:', error);
        process.exit(1);
    }
})();
