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
    
    // Start een browser met stealth modus en extra argumenten
    browser = await chromium.launch({
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-web-security',
        '--disable-notifications',
        '--disable-popup-blocking',
        '--disable-extensions',
        '--disable-component-extensions-with-background-pages',
        '--disable-background-networking',
        '--disable-sync'
      ]
    });
    
    // Maak een nieuwe context en pagina met uitgebreide stealth configuratie
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      deviceScaleFactor: 1,
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
      bypassCSP: true, // Bypass Content Security Policy
      javaScriptEnabled: true,
      hasTouch: false,
      permissions: ['notifications'],
      locale: 'en-US',
      timezoneId: 'Europe/Amsterdam',
    });
    
    // Configureer extra instellingen om detectie te voorkomen
    await context.addInitScript(() => {
      // OverrideWebgl Fingerprinting
      const getParameter = WebGLRenderingContext.prototype.getParameter;
      WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) {
          return 'Intel Inc.';
        }
        if (parameter === 37446) {
          return 'Intel Iris Pro Graphics';
        }
        return getParameter.apply(this, arguments);
      };
      
      // Override canvas fingerprinting
      const toDataURL = HTMLCanvasElement.prototype.toDataURL;
      HTMLCanvasElement.prototype.toDataURL = function(type) {
        if (type === 'image/png' && this.width === 16 && this.height === 16) {
          return 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAAXNSR0IArs4c6QAAACNJREFUOBFjYBgFwygI/P//nw3KZ4CSUHoUDKPAMBYCAAAtNQdem4JsWwAAAABJRU5ErkJggg==';
        }
        return toDataURL.apply(this, arguments);
      };
      
      // Nep navigator properties om detectie te voorkomen
      Object.defineProperty(navigator, 'webdriver', {
        get: () => false
      });

      // TradingView-specifieke localStorage waarden (uitgebreid)
      // Voegt alle mogelijke localStorage waarden toe die popups blokkeren
      const tvLocalStorage = {
        'tv_release_channel': 'stable',
        'tv_alert': 'dont_show',
        'feature_hint_shown': 'true',
        'screener_new_feature_notification': 'shown',
        'screener_deprecated': 'true',
        'tv_notification': 'dont_show',
        'screener_new_feature_already_shown': 'true',
        'stock_screener_banner_closed': 'true',
        'tv_screener_notification': 'dont_show',
        'hints_are_disabled': 'true',
        'tv.alerts-tour': 'true',
        'feature-hint-dialog-shown': 'true',
        'feature-hint-alerts-shown': 'true',
        'feature-hint-screener-shown': 'true',
        'feature-hint-shown': 'true',
        'popup.popup-handling-popups-shown': 'true',
        'tv.greeting-dialog-shown': 'true',
        'tv_notice_shown': 'true'
      };
      
      // Stel alle localStorage waarden in
      Object.entries(tvLocalStorage).forEach(([key, value]) => {
        try {
          localStorage.setItem(key, value);
        } catch (e) {
          console.error(`Failed to set localStorage for ${key}:`, e);
        }
      });
      
      // Blokkeer alle popups
      window.open = () => null;
      
      // Overschrijf confirm en alert om ze te negeren
      window.confirm = () => true;
      window.alert = () => {};
    });
    
    // Voeg cookies toe als er een session ID is
    if (sessionId) {
      await context.addCookies([
        {
          name: 'sessionid',
          value: sessionId,
          domain: '.tradingview.com',
          path: '/',
        },
        // Extra cookies om te laten zien dat je alle popups hebt gezien
        {
          name: 'feature_hint_shown',
          value: 'true',
          domain: '.tradingview.com',
          path: '/',
        },
        {
          name: 'screener_new_feature_notification',
          value: 'shown',
          domain: '.tradingview.com',
          path: '/',
        }
      ]);
      console.log('Added TradingView session cookies');
    }
    
    const page = await context.newPage();
    
    // Auto-dismiss dialogs
    page.on('dialog', async dialog => {
      await dialog.dismiss().catch(() => {});
    });
    
    // Voeg CSS toe om dialogen te verbergen
    await page.addStyleTag({
      content: `
        [role="dialog"], 
        .tv-dialog, 
        .js-dialog,
        .tv-dialog-container,
        .tv-dialog__modal,
        .tv-dialog__modal-container,
        div[data-dialog-name*="chart-new-features"],
        div[data-dialog-name*="notice"],
        div[data-name*="dialog"],
        .tv-dialog--popup,
        .tv-alert-dialog,
        .tv-notification,
        .feature-no-touch .tv-dialog--popup,
        .tv-dialog--alert,
        div[class*="dialog"],
        div:has(button.close-B02UUUN3),
        div:has(button[data-name="close"]) {
          display: none !important;
          visibility: hidden !important;
          opacity: 0 !important;
          pointer-events: none !important;
          z-index: -9999 !important;
        }
        
        .tv-dialog__modal-background {
          opacity: 0 !important;
          display: none !important;
          visibility: hidden !important;
        }
      `
    }).catch(e => console.log('Error adding stylesheet:', e));
    
    // Navigeer met kortere timeout - GEOPTIMALISEERD
    try {
      await page.goto(url, { 
        waitUntil: 'domcontentloaded', 
        timeout: 20000 // GEOPTIMALISEERD: 20s in plaats van 30s
      });
      console.log('Page loaded (domcontentloaded)');
      
      // Script om popups te verwijderen
      await page.evaluate(() => {
        function closePopups() {
          // Escape key indrukken om dialogen te sluiten
          document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27 }));
          
          // Klik op sluitknoppen
          document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"]').forEach(btn => {
            try { btn.click(); } catch (e) {}
          });
          
          // Verwijder dialoogelementen
          document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog').forEach(dialog => {
            try {
              dialog.style.display = 'none';
              if (dialog.parentNode) {
                dialog.parentNode.removeChild(dialog);
              }
            } catch (e) {}
          });
        }
        
        // Direct uitvoeren
        closePopups();
        
        // MutationObserver om nieuwe dialogen te verwijderen
        const observer = new MutationObserver(mutations => {
          for (const mutation of mutations) {
            if (mutation.addedNodes && mutation.addedNodes.length) {
              closePopups();
            }
          }
        });
        
        observer.observe(document.body, { childList: true, subtree: true });
      });
      
      // Wacht op TradingView chart - GEOPTIMALISEERD
      if (url.includes('tradingview.com')) {
        console.log('Waiting for TradingView chart...');
        
        try {
          // Kortere wachttijd voor chart - GEOPTIMALISEERD
          await Promise.race([
            page.waitForSelector('.chart-container', { timeout: 8000 }), // was 10000ms
            new Promise(resolve => setTimeout(resolve, 8000))
          ]);
          
          // Als fullscreen is aangevraagd
          if (fullscreen) {
            console.log('Enabling fullscreen mode...');
            
            // Methode 1: Shift+F toetsencombinatie
            await page.keyboard.down('Shift');
            await page.keyboard.press('F');
            await page.keyboard.up('Shift');
            await page.waitForTimeout(500); // GEOPTIMALISEERD: Kortere wachttijd (was 2000ms)
            
            // Methode 2: CSS fullscreen
            await page.addStyleTag({
              content: `
                /* Verberg header en toolbar */
                .tv-header, .tv-main-panel__toolbar, .tv-side-toolbar {
                  display: none !important;
                }
                
                /* Maximaliseer chart container */
                .chart-container, .chart-markup-table, .layout__area--center {
                  width: 100vw !important;
                  height: 100vh !important;
                  position: fixed !important;
                  top: 0 !important;
                  left: 0 !important;
                }
              `
            });
          }
        } catch (e) {
          console.warn('Could not wait for chart container:', e);
        }
      }
      
      // Kortere wachttijd voor stabiliteit - GEOPTIMALISEERD
      await page.waitForTimeout(1000); // was 1500ms
      
      // Neem screenshot
      console.log('Taking screenshot...');
      await page.screenshot({ path: outputPath });
      console.log(`Screenshot saved to ${outputPath}`);
      
    } catch (navError) {
      console.error('Navigation error:', navError);
      
      // Probeer toch een screenshot te maken
      try {
        await page.screenshot({ path: outputPath });
        console.log(`Screenshot saved despite errors to ${outputPath}`);
      } catch (e) {
        console.error('Failed to take screenshot after navigation error:', e);
      }
    }
  } catch (error) {
    console.error('Error:', error);
  } finally {
    // Altijd browser netjes afsluiten
    if (browser) {
      await browser.close().catch(e => console.error('Error closing browser:', e));
    }
    process.exit(0);
  }
})(); 
