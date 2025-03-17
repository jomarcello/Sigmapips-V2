// Verbeterde foutafhandeling en module import
const fs = require('fs');
const { execSync } = require('child_process');

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

// Controleer of Playwright is geïnstalleerd, zo niet, installeer het
try {
  // Probeer eerst of playwright al beschikbaar is
  require.resolve('playwright');
  console.log("Playwright module is already installed");
} catch (e) {
  console.log("Installing Playwright...");
  try {
    execSync('npm install playwright --no-save', { stdio: 'inherit' });
    console.log("Playwright installed successfully");
  } catch (installError) {
    console.error("Failed to install Playwright:", installError);
    process.exit(1);
  }
}

// Nu kunnen we playwright importeren
const { chromium } = require('playwright');

(async () => {
  let browser;
  try {
    console.log(`Taking screenshot of ${url} and saving to ${outputPath} (fullscreen: ${fullscreen})`);
    
    // Start een browser
    browser = await chromium.launch({
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
      await page.waitForSelector('.chart-container', { timeout: 30000 }).catch(e => {
        console.warn('Could not find chart container, continuing anyway:', e);
      });
      
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
    if (browser) {
      await browser.close().catch(e => console.error('Error closing browser:', e));
    }
    process.exit(1);
  }
})(); 
