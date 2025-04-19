// CSS om altijd fullscreen modus af te dwingen
const fullscreenCSS = `
  /* Verberg alle UI elementen */
  .tv-header, 
  .tv-main-panel__toolbar, 
  .tv-side-toolbar,
  .layout__area--left, 
  .layout__area--right, 
  footer,
  .tv-main-panel__statuses,
  .header-chart-panel,
  .control-bar,
  .chart-controls-bar,
  .tv-floating-toolbar,
  .chart-page,
  .layout__area--top,
  .layout__area--bottom {
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
  }
  
  /* Maximaliseer chart container */
  .chart-container, 
  .chart-markup-table, 
  .layout__area--center {
    width: 100vw !important;
    height: 100vh !important;
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
  }
  
  /* Volledige pagina vullen */
  body, html {
    overflow: hidden !important;
    margin: 0 !important;
    padding: 0 !important;
  }
`;

// Voeg functie toe om fullscreen modus af te dwingen
async function applyFullscreenMode(page) {
  console.log('Applying fullscreen mode - multiple methods');
  
  // Methode 1: Shift+F toetsencombinatie (meest direct)
  try {
    await page.focus('body'); // Zorg ervoor dat de pagina focus heeft
    await page.keyboard.down('Shift');
    await page.keyboard.press('F');
    await page.keyboard.up('Shift');
    console.log('Applied Shift+F fullscreen keyboard shortcut');
    
    // Geef tijd om de fullscreen modus te activeren
    await page.waitForTimeout(2000);
  } catch (e) {
    console.log('Shift+F failed, using alternative methods', e);
  }
  
  // Methode 2: CSS injectie
  try {
    await page.addStyleTag({ content: fullscreenCSS });
    console.log('Applied fullscreen CSS');
  } catch (e) {
    console.log('Fullscreen CSS injection failed', e);
  }
  
  // Methode 3: JavaScript directe manipulatie
  try {
    await page.evaluate(() => {
      // Verberg alle UI elementen
      const selectors = [
        '.tv-header', 
        '.tv-main-panel__toolbar', 
        '.tv-side-toolbar',
        '.layout__area--left', 
        '.layout__area--right', 
        'footer',
        '.tv-main-panel__statuses',
        '.header-chart-panel',
        '.control-bar',
        '.chart-controls-bar'
      ];
      
      selectors.forEach(selector => {
        document.querySelectorAll(selector).forEach(el => {
          if (el) {
            el.style.display = 'none';
            el.style.visibility = 'hidden';
          }
        });
      });
      
      // Maximaliseer chart container
      const chartContainer = document.querySelector('.chart-container');
      if (chartContainer) {
        chartContainer.style.width = '100vw';
        chartContainer.style.height = '100vh';
        chartContainer.style.position = 'fixed';
        chartContainer.style.top = '0';
        chartContainer.style.left = '0';
        chartContainer.style.right = '0';
        chartContainer.style.bottom = '0';
      }
      
      // Maximaliseer ook layout center
      const layoutCenter = document.querySelector('.layout__area--center');
      if (layoutCenter) {
        layoutCenter.style.width = '100vw';
        layoutCenter.style.height = '100vh';
        layoutCenter.style.position = 'fixed';
        layoutCenter.style.top = '0';
        layoutCenter.style.left = '0';
        layoutCenter.style.right = '0';
        layoutCenter.style.bottom = '0';
      }
    });
    console.log('Applied JS direct DOM manipulation for fullscreen');
  } catch (e) {
    console.log('JS fullscreen manipulation failed', e);
  }
  
  // Wacht na alle fullscreen methodes om de wijzigingen toe te passen
  await page.waitForTimeout(1000);
}

// Verbeterde foutafhandeling en module import
const fs = require('fs');
const { execSync } = require('child_process');

// Haal de argumenten op
const url = process.argv[2];
const outputPath = process.argv[3];
const sessionId = process.argv[4] || '';
const fullscreen = process.argv[5] === 'fullscreen' || url.includes('fullscreen=true');

// Log de argumenten voor debugging
console.log(`URL: ${url}`);
console.log(`Output path: ${outputPath}`);
console.log(`Session ID: ${sessionId ? 'Provided' : 'Not provided'}`);
console.log(`Fullscreen: ${fullscreen}`);

// Voorgedefinieerde CSS om dialogen te blokkeren (voorkomt duplicatie)
const blockDialogCSS = `
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
    position: absolute !important;
    top: -9999px !important;
    left: -9999px !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
  }
`;

// Voorgedefinieerde localStorage instellingen (meer gestructureerd en centraal)
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
  'tv_notice_shown': 'true',
  'tv_chart_beta_notice': 'shown',
  'tv_chart_notice': 'shown',
  'tv_screener_notice': 'shown',
  'tv_watch_list_notice': 'shown',
  'tv_new_feature_notification': 'shown',
  'tv_notification_popup': 'dont_show',
  'notification_shown': 'true'
};

// Snellere en meer directe manier om Playwright te laden
let playwright;
try {
  // Probeer eerst of playwright al beschikbaar is
  playwright = require('playwright');
  console.log("Playwright is already installed");
} catch (e) {
  console.log("Installing Playwright...");
  try {
    // Installeer met --no-save flag voor snellere installatie
    execSync('npm install playwright --no-save --no-fund --no-audit', { stdio: 'inherit' });
    playwright = require('playwright');
    console.log("Playwright installed successfully");
  } catch (installError) {
    console.error("Failed to install Playwright:", installError);
    process.exit(1);
  }
}

// Gebruik chromium uit playwright
const { chromium } = playwright;

(async () => {
  let browser;
  try {
    console.log(`Taking screenshot of ${url} and saving to ${outputPath} (fullscreen: ${fullscreen})`);
    
    // Start een browser met geoptimaliseerde argumenten voor prestaties
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
        '--disable-sync',
        '--disable-default-apps',
        '--disable-translate',
        '--disable-features=NetworkService,RendererCodeIntegrity',
        '--disable-web-resources',
        '--no-first-run'
      ]
    });
    
    // Maak een nieuwe context met geoptimaliseerde instellingen
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      deviceScaleFactor: 1,
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
      bypassCSP: true,
      javaScriptEnabled: true,
      permissions: ['notifications'],
      locale: 'en-US',
      timezoneId: 'Europe/Amsterdam',
    });
    
    // Voeg een init script toe om fingerpriniting te voorkomen
    // en direct CSS en localStorage instellingen doen zonder extra evaluate calls
    await context.addInitScript(`
      // Voeg CSS toe vanaf het begin
      (function() {
        const style = document.createElement('style');
        style.textContent = \`${blockDialogCSS}\`;
        document.head.appendChild(style);
      })();
      
      // Override WebGL fingerprinting
      const getParameter = WebGLRenderingContext.prototype.getParameter;
      WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris Pro Graphics';
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
      
      // Nep navigator properties
      Object.defineProperty(navigator, 'webdriver', { get: () => false });
      
      // Stel localStorage in (direct aan begin)
      const tvStorage = ${JSON.stringify(tvLocalStorage)};
      for (const [key, value] of Object.entries(tvStorage)) {
        try { localStorage.setItem(key, value); } catch(e) {}
      }
      
      // Zoek en zet alle localStorage sleutels met notification
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && (key.endsWith("_do_not_show_again") || key.includes("notification"))) {
          localStorage.setItem(key, key.includes("notification") ? 'shown' : 'true');
        }
      }
      
      // Blokkeer alle popup mechanismes
      window.open = () => null;
      window.confirm = () => true;
      window.alert = () => {};
      window.prompt = () => null;
      
      // Automatisch alle dialogen sluiten functie
      window.closeAllDialogs = function() {
        // Druk op Escape
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
        
        // Klik op alle close buttons
        document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"]').forEach(btn => {
          try { btn.click(); } catch(e) {}
        });
        
        // Verwijder alle dialogen
        document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog').forEach(dialog => {
          try {
            dialog.style.display = 'none';
            if (dialog.parentNode) dialog.parentNode.removeChild(dialog);
          } catch(e) {}
        });
      };
      
      // Voer direct uit
      if (document.readyState === 'complete' || document.readyState === 'interactive') {
        window.closeAllDialogs();
      }
      
      // Bij page load events
      document.addEventListener('DOMContentLoaded', window.closeAllDialogs);
      window.addEventListener('load', window.closeAllDialogs);
      
      // Periodiek uitvoeren
      setInterval(window.closeAllDialogs, 300);
      
      // Element creation override
      const originalCreateElement = document.createElement;
      document.createElement = function() {
        const element = originalCreateElement.apply(this, arguments);
        if (arguments[0].toLowerCase() === 'dialog') {
          setTimeout(() => {
            element.style.display = 'none';
            element.style.visibility = 'hidden';
            element.style.opacity = '0';
          }, 0);
        }
        return element;
      };
    `);
    
    // Voeg cookies toe als er een session ID is
    if (sessionId) {
      await context.addCookies([
        {
          name: 'sessionid',
          value: sessionId,
          domain: '.tradingview.com',
          path: '/',
        },
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
    
    // Stel een handler in om dialogs automatisch te sluiten
    page.on('dialog', async dialog => {
      await dialog.dismiss().catch(() => {});
    });
    
    // Stel een korte timeout in voor betere prestaties
    page.setDefaultTimeout(15000);
    
    // Optimaliseer URL als fullscreen nodig is
    if (fullscreen && !url.includes('fullscreen=true')) {
      if (url.includes('?')) {
        url += '&fullscreen=true';
      } else {
        url += '?fullscreen=true';
      }
    }
    
    // Navigeer naar de URL
    console.log(`Navigating to ${url}`);
    try {
      await page.goto(url, { 
        waitUntil: 'domcontentloaded', 
        timeout: 15000
      });
      console.log('Page loaded (domcontentloaded)');
    } catch (navError) {
      console.error('Navigation timeout or error, but continuing with screenshot attempt');
    }
    
    // Direct aanpak voor popup handling - voert uit ongeacht navigatieresultaat
    await page.addStyleTag({ content: blockDialogCSS });
    
    // Snelle popup cleanup actie
    await page.evaluate(() => {
      // Escape toets
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
      
      // Klik alle close buttons
      document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"]').forEach(btn => {
        try { btn.click(); } catch(e) {}
      });
      
      // Verwijder alle dialogen
      document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog, .tv-dialog--popup').forEach(dialog => {
        try {
          dialog.style.display = 'none';
          if (dialog.parentNode) dialog.parentNode.removeChild(dialog);
        } catch(e) {}
      });
    });
    
    // Wacht kort voordat we fullscreen toepassen
    await page.waitForTimeout(1500);
    
    // ALTIJD fullscreen toepassen, ongeacht de parameter
    await applyFullscreenMode(page);
    
    // Korte wachttijd voor stabiliteit
    await page.waitForTimeout(1500);
    
    // Neem screenshot
    console.log('Taking screenshot...');
    try {
      await page.screenshot({ path: outputPath });
      console.log(`Screenshot saved to ${outputPath}`);
    } catch (e) {
      console.error('Screenshot error:', e);
      // Laatste poging met content
      try {
        await page.setContent('<html><body><h1>Error with TradingView</h1></body></html>');
        await page.screenshot({ path: outputPath });
        console.log('Created fallback screenshot');
      } catch (finalError) {
        console.error('Fatal screenshot error:', finalError);
      }
    }
    
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
