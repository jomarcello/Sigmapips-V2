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
        const browser = await chromium.launch({
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        });
        
        // Open een nieuwe pagina met grotere viewport voor fullscreen
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
        
        // Stel een langere timeout in
        page.setDefaultTimeout(180000); // 3 minuten timeout
        
        try {
            // Ga naar de URL
            console.log(`Navigating to ${url}...`);
            await page.goto(url, {
                waitUntil: 'domcontentloaded',
                timeout: 120000 // 2 minuten timeout voor navigatie
            });
            
            // Wacht een langere tijd om de pagina en indicators te laten laden
            console.log('Waiting for page and indicators to render...');
            await page.waitForTimeout(20000); // 20 seconden wachten
            
            // Controleer of we zijn ingelogd
            const isLoggedIn = await page.evaluate(() => {
                return document.body.innerText.includes('Log out') || 
                       document.body.innerText.includes('Account') ||
                       document.querySelector('.tv-header__user-menu-button') !== null;
            });
            
            console.log(`Logged in status: ${isLoggedIn}`);
            
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
                await page.waitForTimeout(3000);
            }
            
            // Wacht nog wat langer als we zijn ingelogd om custom indicators te laden
            if (isLoggedIn) {
                console.log('Waiting for custom indicators to load...');
                await page.waitForTimeout(10000); // Extra 10 seconden voor custom indicators
            }
            
            // Wacht tot de chart volledig is geladen
            console.log('Waiting for chart to be fully loaded...');
            await page.waitForFunction(() => {
                // Controleer of de loading indicator verdwenen is
                const loadingIndicator = document.querySelector('.loading-indicator');
                if (loadingIndicator && window.getComputedStyle(loadingIndicator).display !== 'none') {
                    return false;
                }
                
                // Controleer of de chart container zichtbaar is
                const chartContainer = document.querySelector('.chart-container');
                return chartContainer && window.getComputedStyle(chartContainer).visibility !== 'hidden';
            }, { timeout: 30000 }).catch(e => {
                console.warn('Timeout waiting for chart to load, taking screenshot anyway:', e);
            });
            
            // Wacht nog een laatste moment voor stabiliteit
            await page.waitForTimeout(5000);
            
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
