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
        'tv_notice_shown': 'true',
        'tv_chart_beta_notice': 'shown',
        'tv_chart_notice': 'shown',
        'tv_screener_notice': 'shown',
        'tv_watch_list_notice': 'shown',
        'tv_new_feature_notification': 'shown',
        'tv_notification_popup': 'dont_show',
        'notification_shown': 'true'
      };
      
      // Stel alle localStorage waarden in
      Object.entries(tvLocalStorage).forEach(([key, value]) => {
        try {
          localStorage.setItem(key, value);
        } catch (e) {
          console.error(`Failed to set localStorage for ${key}:`, e);
        }
      });
      
      // Zoek naar alle localStorage sleutels die eindigen met "_do_not_show_again" of "notification" en zet ze op true/shown
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && (key.endsWith("_do_not_show_again") || key.includes("notification"))) {
          localStorage.setItem(key, key.includes("notification") ? 'shown' : 'true');
        }
      }
      
      // Blokkeer alle popups
      window.open = () => null;
      
      // Overschrijf confirm en alert om ze te negeren
      window.confirm = () => true;
      window.alert = () => {};
      
      // Voeg code toe om alle dialogen automatisch te verwerpen zodra ze verschijnen
      const originalCreateElement = document.createElement;
      document.createElement = function() {
        const element = originalCreateElement.apply(this, arguments);
        if (arguments[0].toLowerCase() === 'dialog') {
          // Verberg dialogs direct bij creatie
          setTimeout(() => {
            element.style.display = 'none';
            element.style.visibility = 'hidden';
            element.style.opacity = '0';
          }, 0);
        }
        return element;
      };
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
    
    // Navigeer naar de URL
    console.log(`Navigating to ${url}`);
    try {
      // Setup event handlers voor dialogs om ze automatisch te sluiten
      page.on('dialog', async dialog => {
        console.log(`Auto-dismissing dialog: ${dialog.type()} with message: ${dialog.message()}`);
        await dialog.dismiss().catch(() => {});
      });
      
      // Voeg CSS toe om dialogen bij page load direct te blokkeren - dit gebeurt nog voor page.goto
      await page.addStyleTag({
        content: `
          @keyframes dialogfade {
            from { opacity: 1; }
            to { opacity: 0; display: none; visibility: hidden; }
          }
          
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
            animation: dialogfade 0.01s forwards !important;
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
        `
      }).catch(e => console.log('Error adding pre-navigation stylesheet:', e));
      
      // Navigeer met kortere timeout
      await page.goto(url, { 
        waitUntil: 'domcontentloaded', 
        timeout: 30000 
      });
      console.log('Page loaded (domcontentloaded)');
      
      // Voeg CSS toe om alle popups en dialogen te blokkeren
      console.log('Adding CSS to block all popups and dialogs...');
      await page.addStyleTag({
        content: `
          /* Agressief verbergen van alle dialogen en popups */
          [role="dialog"], 
          .tv-dialog, 
          .js-dialog,
          .tv-dialog-container,
          .tv-dialog__modal,
          .tv-dialog__modal-container,
          div[data-dialog-name*="chart-new-features"],
          div[data-dialog-name*="notice"],
          div[data-name*="dialog"],
          div:has(> button.nav-button-znwuaSC1),
          .tv-dialog--popup,
          .tv-alert-dialog,
          .tv-notification,
          .feature-no-touch .tv-dialog--popup,
          .tv-dialog--alert,
          div[class*="dialog"] {
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
          
          /* Specifiek voor de Stock Screener popup */
          div:has(button.close-B02UUUN3),
          div:has(button[data-name="close"]),
          [data-role="dialog"],
          [data-name*="popup"] {
            display: none !important;
            visibility: hidden !important;
          }
          
          /* Verberg de overlay/backdrop */
          .tv-dialog__modal-background {
            opacity: 0 !important;
            display: none !important;
            visibility: hidden !important;
          }
        `
      });

      // Wacht kort zodat de pagina kan laden
      await page.waitForTimeout(1000);
      
      // Direct specifieke acties uitvoeren gericht op het sluiten van de Stock Screener popup
      await page.evaluate(() => {
        // Functie om Stock Screener popups te vinden en te sluiten
        function closeAllStockScreenerPopups() {
          console.log("Attempting to close all Stock Screener popups...");
          
          // Methode 1: Escape toets simuleren
          document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27 }));
          
          // Methode 2: Direct de close buttons zoeken en klikken
          const closeSelectors = [
            'button.nav-button-znwuaSC1.size-medium-znwuaSC1.preserve-paddings-znwuaSC1.close-B02UUUN3',
            'button[data-name="close"]',
            '.close-B02UUUN3',
            'button.close-B02UUUN3'
          ];
          
          closeSelectors.forEach(selector => {
            const buttons = document.querySelectorAll(selector);
            console.log(`Found ${buttons.length} buttons with selector: ${selector}`);
            
            buttons.forEach(button => {
              try {
                // Log button info
                console.log(`Clicking button: ${button.outerHTML}`);
                button.click();
                
                // Find parent dialog
                let dialog = button.closest('[role="dialog"]') || 
                             button.closest('.tv-dialog') || 
                             button.closest('.js-dialog');
                
                if (dialog) {
                  console.log('Found parent dialog, removing...');
                  dialog.style.display = 'none';
                  dialog.remove();
                }
              } catch (e) {
                console.log(`Error clicking button: ${e}`);
              }
            });
          });
          
          // Methode 3: Zoek specifiek op SVG paths (sluitknoppen)
          const svgPaths = document.querySelectorAll('svg path[d="m.58 1.42.82-.82 15 15-.82.82z"], svg path[d="m.58 15.58 15-15 .82.82-15 15z"]');
          console.log(`Found ${svgPaths.length} SVG paths matching close button`);
          
          svgPaths.forEach(path => {
            try {
              // Find parent button
              let button = path;
              while (button && button.tagName !== 'BUTTON') {
                button = button.parentElement;
              }
              
              if (button) {
                console.log('Found button containing SVG path, clicking...');
                button.click();
                
                // Find parent dialog
                let dialog = button;
                while (dialog && 
                      !(dialog.getAttribute('role') === 'dialog' ||
                        dialog.classList && dialog.classList.contains('tv-dialog'))) {
                  dialog = dialog.parentElement;
                }
                
                if (dialog) {
                  console.log('Found parent dialog via SVG path, removing...');
                  dialog.style.display = 'none';
                  dialog.remove();
                }
              }
            } catch (e) {
              console.log(`Error handling SVG path: ${e}`);
            }
          });
        }
        
        // Voer de functie direct uit
        closeAllStockScreenerPopups();
        
        // Stel een interval in om te blijven controleren op nieuwe popups
        setInterval(closeAllStockScreenerPopups, 500);
      });
      
      // Wacht beter op TradingView chart container
      if (url.includes('tradingview.com')) {
        console.log('Waiting for TradingView chart to load...');
        
        // Probeer te wachten op de chart container
        try {
          // Wacht op het chart element
          await page.waitForSelector('.chart-container', { timeout: 10000 });
          console.log('Chart container found');
          
          // Probeer nogmaals de close button te klikken na chart loaded
          await page.evaluate(() => {
            // Direct specifieke Stock Screener sluitknoppen proberen
            const closeButtons = document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"]');
            console.log(`Found ${closeButtons.length} direct close buttons`);
            closeButtons.forEach(btn => {
              try {
                btn.click();
                console.log('Clicked close button');
              } catch (e) {
                console.log('Error clicking button:', e);
              }
            });
            
            // Verwijder alle dialogen
            document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog').forEach(dialog => {
              dialog.style.display = 'none';
              dialog.style.visibility = 'hidden';
              if (dialog.parentNode) {
                try {
                  dialog.parentNode.removeChild(dialog);
                } catch (e) {}
              }
            });
          });
          
          // Probeer nogmaals met Playwright direct
          const closeButtons = await page.$$('button.close-B02UUUN3, button[data-name="close"]');
          console.log(`Found ${closeButtons.length} close buttons with Playwright`);
          
          for (const button of closeButtons) {
            try {
              await button.click();
              console.log('Clicked button with Playwright');
            } catch (e) {
              console.log('Error clicking with Playwright:', e);
            }
          }
          
        } catch (e) {
          console.warn('Could not find chart container, continuing anyway:', e);
        }
        
        // Wacht op de chart om te laden
        await page.waitForTimeout(5000);
        
        // Als fullscreen is aangevraagd, simuleer Shift+F
        if (fullscreen || url.includes('fullscreen=true')) {
          console.log('Enabling fullscreen mode with Shift+F...');
          await page.keyboard.down('Shift');
          await page.keyboard.press('F');
          await page.keyboard.up('Shift');
          await page.waitForTimeout(2000);
          console.log('Fullscreen mode activated');
        }
      } else {
        console.log('Not a TradingView URL, waiting for page load...');
        await page.waitForTimeout(3000);
      }
      
      // Final cleanup before screenshot
      await page.evaluate(() => {
        // Verberg alles wat nog zichtbaar zou kunnen zijn
        const elementsToHide = document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog, .tv-dialog--popup, .tv-notification');
        console.log(`Hiding ${elementsToHide.length} elements before screenshot`);
        
        elementsToHide.forEach(el => {
          el.style.display = 'none';
          el.style.visibility = 'hidden';
          el.style.opacity = '0';
        });
      });
      
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
      // Try to continue anyway, maybe page is partially loaded
      console.log('Continuing despite navigation error...');
      
      // Try to take the screenshot regardless
      try {
        const screenshot = await page.screenshot({ path: outputPath });
        console.log(`Screenshot saved despite errors to ${outputPath}`);
      } catch (e) {
        console.error('Failed to take screenshot after navigation error:', e);
        // If we can't take the screenshot, exit with error
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
