// Verbeterde foutafhandeling en module import
const fs = require('fs');
const { execSync } = require('child_process');

// Haal de argumenten op
const url = process.argv[2];
const outputPath = process.argv[3];
const sessionId = process.argv[4] || '';
const fullscreen = process.argv[5] === 'fullscreen';

// Log de argumenten voor debugging (beperkt)
console.log(`Taking screenshot of ${url} and saving to ${outputPath} (fullscreen: ${fullscreen})`);
console.log(`Session ID: ${sessionId ? 'Using session ID: ' + sessionId.substring(0, 5) + '...' : 'Not provided'}`);

// Controleer of Playwright is geïnstalleerd, zo niet, installeer het
try {
  require.resolve('playwright');
  console.log("Using locally installed playwright module");
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

// Globale browser instantie voor hergebruik
let browserInstance = null;

(async () => {
  let browser;
  try {
    // Gebruik globale browser of maak nieuwe aan met minimale argumenten
    if (browserInstance) {
      browser = browserInstance;
      console.log("Reusing existing browser instance");
    } else {
      browser = await chromium.launch({
        headless: true,
        args: [
          '--no-sandbox',
          '--disable-setuid-sandbox',
          '--disable-web-security'
        ]
      });
      browserInstance = browser;
    }
    
    // Maak een nieuwe context met minimale configuratie (verlaagde deviceScaleFactor voor snelheid)
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      deviceScaleFactor: 1,
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
      bypassCSP: true,
    });
    
    // Eenvoudigere stealth configuratie - alleen essentiële instellingen
    await context.addInitScript(() => {
      // Blokkeer popups en alerts
      window.open = () => null;
      window.confirm = () => true;
      window.alert = () => {};
      
      // TradingView-specifieke localStorage waarden (alleen de belangrijkste)
      try {
        localStorage.setItem('tv_release_channel', 'stable');
        localStorage.setItem('feature_hint_shown', 'true');
        localStorage.setItem('hints_are_disabled', 'true');
      } catch (e) {}
      
      // Simuleer Escape om popups te sluiten
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
    });
    
    // Voeg cookies toe als er een session ID is (ongewijzigd)
    if (sessionId) {
      await context.addCookies([
        {
          name: 'sessionid',
          value: sessionId,
          domain: '.tradingview.com',
          path: '/',
        }
      ]);
    }
    
    const page = await context.newPage();
    
    // Dialogen automatisch sluiten
    page.on('dialog', async dialog => {
      await dialog.dismiss().catch(() => {});
    });
    
    // Voeg CSS toe om dialogen te blokkeren (verkorte versie)
    await page.addStyleTag({
      content: `
        /* Verberg alle dialogen en popups */
        [role="dialog"], .tv-dialog, .js-dialog, .tv-dialog-container, 
        .tv-dialog__modal, div[data-dialog-name*="chart-new-features"],
        div[data-dialog-name*="notice"], .tv-notification, .tv-alert-dialog {
          display: none !important;
          visibility: hidden !important;
          opacity: 0 !important;
        }
        /* Verberg de overlay/backdrop */
        .tv-dialog__modal-background {
          opacity: 0 !important;
          display: none !important;
        }
      `
    }).catch(() => {});
    
    // Navigeer met kortere timeout (10s in plaats van 15s)
    console.log('Navigating to page...');
    await page.goto(url, { 
      waitUntil: 'domcontentloaded', 
      timeout: 10000 
    });
    
    // Kortere wachttijd (500ms in plaats van 1000ms)
    await page.waitForTimeout(500);
    
    // Wacht beter op TradingView chart container met kortere timeout
    if (url.includes('tradingview.com')) {
      try {
        // Check alleen of chart container geladen is (3s in plaats van 5s)
        await page.waitForSelector('.chart-container', { timeout: 3000 });
      } catch (e) {
        console.warn('Chart container not found, continuing anyway');
      }
      
      // Als fullscreen is aangevraagd, simuleer Shift+F
      if (fullscreen || url.includes('fullscreen=true')) {
        await page.keyboard.down('Shift');
        await page.keyboard.press('F');
        await page.keyboard.up('Shift');
        // Kortere wachttijd (500ms in plaats van 1000ms)
        await page.waitForTimeout(500);
      }
    }
    
    // Neem screenshot zonder extra cleanup
    console.log('Taking screenshot...');
    const screenshot = await page.screenshot({ path: outputPath });
    console.log('Screenshot taken successfully');
    
    // Sluit de pagina en context, maar houd de browser open voor hergebruik
    await page.close();
    await context.close();
    
    process.exit(0);
    
  } catch (error) {
    console.error('Error:', error);
    
    // Probeer de browser te sluiten bij fatale fouten
    if (browser) {
      await browser.close();
      browserInstance = null;
    }
    
    process.exit(1);
  }
})(); 
