// Verbeterde foutafhandeling en module import
const fs = require('fs');
const { execSync } = require('child_process');

// Haal de argumenten op
const url = process.argv[2];
const outputPath = process.argv[3];
const sessionId = process.argv[4] || '';
const fullscreen = process.argv[5] === 'fullscreen';

// Log alleen de essentiële argumenten
console.log(`URL: ${url}`);
console.log(`Output path: ${outputPath}`);
console.log(`Session ID: ${sessionId ? 'Provided' : 'Not provided'}`);
console.log(`Fullscreen: ${fullscreen}`);

// Voorgedefinieerde CSS voor blockers - dit versnelt de code execution
const blockerCSS = `
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

// Voorgedefinieerde localStorage items
const storageItems = {
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
    
    // Start een browser met stealth modus en extra argumenten - minder argumenten voor snelheid
    browser = await chromium.launch({
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-web-security',
        '--disable-notifications',
        '--disable-popup-blocking'
      ]
    });
    
    // Maak een nieuwe context met basis stealth configuratie - minimale instellingen voor snelheid
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      deviceScaleFactor: 1,
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
      bypassCSP: true,
      javaScriptEnabled: true,
      locale: 'en-US',
      timezoneId: 'Europe/Amsterdam',
    });
    
    // Configureer minimale detectie-preventie
    await context.addInitScript(() => {
      // Blokkeer detectie van webdriver
      Object.defineProperty(navigator, 'webdriver', {
        get: () => false
      });

      // TradingView-specifieke localStorage waarden instellen
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
        'tv.alerts-tour': 'true'
      };
      
      // Stel alle localStorage waarden in
      Object.entries(tvLocalStorage).forEach(([key, value]) => {
        try {
          localStorage.setItem(key, value);
        } catch (e) {
          // Stille catch
        }
      });
      
      // Blokkeer alle popups en dialogen
      window.open = () => null;
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
    
    // Voeg vooraf onze CSS toe om dialogen te blokkeren
    await page.addStyleTag({
      content: blockerCSS
    }).catch(e => console.log('Error adding pre-navigation stylesheet:', e));
    
    // Navigeer naar de pagina met kortere timeout
    console.log(`Navigating to ${url}`);
    try {
      // Navigeer met kortere timeout
      await page.goto(url, { 
        waitUntil: 'domcontentloaded', 
        timeout: 20000  // Verkort naar 20 seconden
      });
      console.log('Page loaded (domcontentloaded)');
      
      // Voeg CSS toe om alle popups en dialogen te blokkeren
      await page.addStyleTag({
        content: blockerCSS
      });

      // Wacht kort zodat de pagina kan laden (500ms in plaats van 1000ms)
      await page.waitForTimeout(500);
      
      // Escape toets simuleren om eventuele dialogen direct te sluiten
      await page.keyboard.press('Escape');
      
      // Verwijder dialogen en klik op sluitknoppen in één keer
      await page.evaluate(() => {
        // Escape toets simuleren
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
        
        // Zoek en klik op alle sluitknoppen
        document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"]').forEach(btn => {
          try {
            btn.click();
          } catch (e) {}
        });
        
        // Verwijder alle dialogen direct
        document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog').forEach(dialog => {
          dialog.style.display = 'none';
          if (dialog.parentNode) {
            try {
              dialog.parentNode.removeChild(dialog);
            } catch (e) {}
          }
        });
      });
      
      // Wacht op het chart element met kortere timeout (5 sec in plaats van 10 sec)
      if (url.includes('tradingview.com')) {
        console.log('Waiting for TradingView chart to load...');
        
        try {
          // Gebruik een kort wachten in plaats van lange selector-wachttijd
          await page.waitForTimeout(1000);
          
          // Controleer dan of de chart container er is
          const chartContainer = await page.$('.chart-container');
          if (chartContainer) {
            console.log('Chart container found');
          } else {
            // Als we nog geen chart container hebben, wacht wat langer
            await page.waitForTimeout(3000);
          }
        } catch (e) {
          console.warn('Could not find chart container, continuing anyway');
        }
      } else {
        // Verkort de wachttijd voor niet-TradingView URLs
        await page.waitForTimeout(1000);
      }
      
      // Als fullscreen is aangevraagd, simuleer Shift+F
      if (fullscreen || url.includes('fullscreen=true')) {
        console.log('Enabling fullscreen mode with Shift+F...');
        await page.keyboard.down('Shift');
        await page.keyboard.press('F');
        await page.keyboard.up('Shift');
        
        // Verkort wachttijd na fullscreen activatie (1 sec in plaats van 2 sec)
        await page.waitForTimeout(1000);
        
        // Voeg CSS toe om fullscreen te forceren
        await page.addStyleTag({
          content: `
            .tv-header, .tv-main-panel__toolbar, .tv-side-toolbar {
              display: none !important;
            }
            
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
      
      // Final cleanup before screenshot - verwijder alles wat nog zichtbaar zou kunnen zijn
      await page.evaluate(() => {
        document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog, .tv-dialog--popup, .tv-notification').forEach(el => {
          el.style.display = 'none';
          el.style.visibility = 'hidden';
          el.style.opacity = '0';
        });
      });
      
      // Verkorte laatste stabilisatie wachttijd (500ms in plaats van meerdere seconden)
      await page.waitForTimeout(500);
      
      // Neem screenshot
      console.log('Taking screenshot...');
      const screenshot = await page.screenshot({ path: outputPath });
      console.log(`Screenshot saved to ${outputPath}`);
      
      // Sluit de browser
      await browser.close();
      
      console.log('Done!');
      process.exit(0);
      
    } catch (navError) {
      console.error('Navigation error:', navError);
      
      // Try to take the screenshot regardless
      try {
        const screenshot = await page.screenshot({ path: outputPath });
        console.log(`Screenshot saved despite errors to ${outputPath}`);
      } catch (e) {
        console.error('Failed to take screenshot after navigation error:', e);
        if (browser) {
          await browser.close().catch(e => console.error('Error closing browser:', e));
        }
        process.exit(1);
      }
      
      // Close the browser and exit
      if (browser) {
        await browser.close().catch(e => console.error('Error closing browser:', e));
      }
      process.exit(0);
    }
  } catch (error) {
    console.error('Error:', error);
    if (browser) {
      await browser.close().catch(e => console.error('Error closing browser:', e));
    }
    process.exit(1);
  }
})(); 
