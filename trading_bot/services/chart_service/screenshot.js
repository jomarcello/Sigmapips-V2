// Geoptimaliseerde versie voor snellere screenshots
const fs = require('fs');
const { execSync } = require('child_process');

// Haal de argumenten op
const url = process.argv[2];
const outputPath = process.argv[3];
const sessionId = process.argv[4] || '';
const fullscreen = process.argv[5] === 'fullscreen';

// Minimale logging
console.log(`Taking screenshot of ${url}`);
if (sessionId) console.log(`Using session ID: ${sessionId.substring(0, 5)}...`);

// Globale browser instantie voor hergebruik
let browserInstance = null;

// Laad Playwright
let chromium;
try {
  const playwright = require('playwright');
  chromium = playwright.chromium;
  console.log("Using locally installed playwright module");
} catch (e) {
  try {
    execSync('npm install playwright --no-save', { stdio: 'inherit' });
    const playwright = require('playwright');
    chromium = playwright.chromium;
  } catch (installError) {
    console.error("Failed to install Playwright:", installError);
    process.exit(1);
  }
}

(async () => {
  let browser;
  let startTime = Date.now();
  try {
    // Gebruik bestaande browser of start nieuwe met hardwareversnelling
    if (browserInstance) {
      browser = browserInstance;
    } else {
      browser = await chromium.launch({
        headless: true,
        args: [
          '--no-sandbox',
          '--disable-setuid-sandbox',
          '--disable-web-security',
          '--disable-gpu',
          '--use-gl=desktop', // Hardwareversnelling
          '--ignore-certificate-errors',
          '--disable-features=IsolateOrigins,site-per-process',
          '--disable-site-isolation-trials'
        ]
      });
      browserInstance = browser;
    }
    
    // Context met optimale instellingen voor snelheid
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      deviceScaleFactor: 1,
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
      bypassCSP: true,
      ignoreHTTPSErrors: true, // Voorkom ssl vertragingen
      javaScriptEnabled: true
    });
    
    // Injecteer minimale scripts om de pagina te versnellen
    await context.addInitScript(() => {
      // Alle alerts, prompts en dialogs uitschakelen
      window.alert = () => {};
      window.confirm = () => true;
      window.prompt = () => '';
      window.open = () => null;
      
      // TradingView specifieke settings (alleen essentiële)
      try {
        localStorage.setItem('tv_release_channel', 'stable');
        localStorage.setItem('feature_hint_shown', 'true');
        localStorage.setItem('hints_are_disabled', 'true');
      } catch (e) {}
      
      // Escape key event voor popups sluiten
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
    });
    
    // Voeg cookies toe voor authenticatie
    if (sessionId) {
      await context.addCookies([{
        name: 'sessionid',
        value: sessionId,
        domain: '.tradingview.com',
        path: '/',
      }]);
    }
    
    // Maak pagina aan en stel handlers in
    const page = await context.newPage();
    
    // Automatisch alle dialogs afwijzen
    page.on('dialog', async dialog => await dialog.dismiss().catch(() => {}));
    
    // Inject CSS om alle dialogen en popups te verbergen
    await page.addStyleTag({
      content: `
        [role="dialog"], .tv-dialog, .js-dialog, .tv-dialog-container, 
        .tv-dialog__modal, div[data-dialog-name*="chart"], div[data-name*="dialog"],
        div[data-dialog-name*="notice"], .tv-notification, .tv-alert-dialog {
          display: none !important; visibility: hidden !important; opacity: 0 !important;
        }
        .tv-dialog__modal-background { opacity: 0 !important; display: none !important; }
      `
    }).catch(() => {});
    
    // Navigeer met optimale instellingen
    console.log('Navigating to page...');
    
    // Route resources efficiënter
    await page.route('**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,otf}', route => {
      if (route.request().resourceType() === 'image' || route.request().resourceType() === 'font') {
        // Blokkeer niet-essentiële resources
        route.abort();
      } else {
        route.continue();
      }
    }).catch(() => {});
    
    // Navigeer naar de pagina met optimale instellingen
    await page.goto(url, { 
      waitUntil: 'networkidle', // Wacht tot netwerk 500ms rustig is
      timeout: 10000 // 10s max wachttijd
    });
    
    // Minimale wachttijd
    await page.waitForTimeout(300);
    
    // Voor TradingView pagina's, wacht alleen op essentiële elementen
    if (url.includes('tradingview.com')) {
      try {
        // Wacht op chart container element (essentiëel voor screenshots)
        await page.waitForSelector('.chart-container, .chart-markup-table', { 
          timeout: 3000,
          state: 'attached'
        });
      } catch (e) {
        console.warn('Chart container not found, continuing anyway');
      }
      
      // Voer fullscreen actie uit indien gevraagd
      if (fullscreen || url.includes('fullscreen=true')) {
        await page.keyboard.press('Escape'); // Eerst eventuele popups sluiten
        await page.keyboard.down('Shift');
        await page.keyboard.press('F');
        await page.keyboard.up('Shift');
        await page.waitForTimeout(200); // Wacht kort tot fullscreen effect zichtbaar is
      }
    }
    
    // Neem screenshot direct zonder extra cleaning
    console.log('Taking screenshot...');
    await page.screenshot({ path: outputPath });
    console.log(`Screenshot taken successfully (${Date.now() - startTime}ms)`);
    
    // Sluit pagina en context, maar houd browser voor hergebruik
    await page.close();
    await context.close();
    
    process.exit(0);
    
  } catch (error) {
    console.error('Error:', error);
    
    // Probeer browser te sluiten alleen bij fatale fouten
    if (browser) {
      try {
        await browser.close();
        browserInstance = null;
      } catch (e) {}
    }
    
    process.exit(1);
  }
})(); 
