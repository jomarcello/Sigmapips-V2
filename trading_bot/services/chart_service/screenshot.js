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
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-web-security']
    });
    
    // Maak een nieuwe context en pagina
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      deviceScaleFactor: 1,
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
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
    try {
      // Voeg localStorage waarden in vóór de pagina wordt geladen om notificaties uit te schakelen
      await page.addInitScript(() => {
        // Zet alle mogelijke keys om notificaties en popups te blokkeren
        window.localStorage.setItem('screener_new_feature_notification', 'shown');
        window.localStorage.setItem('tv_notification', 'dont_show');
        window.localStorage.setItem('screener_deprecated', 'true');
        window.localStorage.setItem('tv_screener_notification', 'dont_show');
        window.localStorage.setItem('screener_new_feature_already_shown', 'true');
        window.localStorage.setItem('stock_screener_banner_closed', 'true');
        window.localStorage.setItem('tv_release_channel', 'stable');
        window.localStorage.setItem('tv_alert', 'dont_show');
        window.localStorage.setItem('feature_hint_shown', 'true');
        window.localStorage.setItem('hints_are_disabled', 'true');
        window.localStorage.setItem('tv.alerts-tour', 'true');
        window.localStorage.setItem('popup.popup-handling-popups-shown', 'true');

        // Voor alle keys die eindigen met "_do_not_show_again", zet ze op true
        for (let i = 0; i < localStorage.length; i++) {
          const key = localStorage.key(i);
          if (key && key.endsWith("_do_not_show_again")) {
            localStorage.setItem(key, 'true');
          }
        }
      });
      
      // Gebruik domcontentloaded in plaats van networkidle
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      console.log('Page loaded (domcontentloaded)');
      
      // Wacht kort zodat popups kunnen verschijnen
      await page.waitForTimeout(2000);
      
      // Injecteer CSS om alle dialogen te verbergen, nog agressiever
      console.log('Injecting CSS to forcefully hide all dialogs and popups...');
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
          div:has(button[data-name="close"]) {
            display: none !important;
            visibility: hidden !important;
          }
        `
      });
      
      // Direct aanroepen van de nieuwe functie voor het specifiek zoeken naar het Stock Screener element
      console.log('Executing direct Stock Screener popup removal...');
      
      // Specifiek gericht op de Stock Screener popup
      await page.evaluate(() => {
        // Functie die alle Stock Screener popups opzoekt en verwijdert
        function findAndRemoveStockScreenerPopup() {
          console.log('Searching for Stock Screener popup...');
          
          // Specifiek gericht op de SVG X-icon in de close button
          const svgPaths = document.querySelectorAll('svg path[d="m.58 1.42.82-.82 15 15-.82.82z"], svg path[d="m.58 15.58 15-15 .82.82-15 15z"]');
          console.log(`Found ${svgPaths.length} SVG paths that match close icon`);
          
          svgPaths.forEach(path => {
            try {
              // Zoek de parent button
              let button = path;
              let foundButton = false;
              
              // Loop naar boven tot we een button vinden
              while (button && !foundButton) {
                if (button.tagName === 'BUTTON') {
                  foundButton = true;
                  break;
                }
                button = button.parentElement;
                if (!button) break;
              }
              
              if (foundButton && button) {
                console.log('Found a close button with X icon, clicking it...');
                button.click();
                
                // Zoek de parent dialoog en verwijder deze
                let dialog = button;
                let foundDialog = false;
                
                // Loop naar boven tot we een dialoog vinden
                while (dialog && !foundDialog) {
                  if (
                    dialog.getAttribute && dialog.getAttribute('role') === 'dialog' ||
                    dialog.classList && (
                      dialog.classList.contains('tv-dialog') ||
                      dialog.classList.contains('js-dialog')
                    )
                  ) {
                    foundDialog = true;
                    break;
                  }
                  dialog = dialog.parentElement;
                  if (!dialog) break;
                }
                
                if (foundDialog && dialog) {
                  console.log('Found parent dialog, forcefully removing...');
                  dialog.style.display = 'none';
                  dialog.style.visibility = 'hidden';
                  dialog.style.opacity = '0';
                  
                  // Verwijder de dialoog volledig uit de DOM
                  if (dialog.parentNode) {
                    try {
                      dialog.parentNode.removeChild(dialog);
                      console.log('Successfully removed dialog from DOM');
                    } catch (e) {
                      console.log('Error removing dialog:', e);
                    }
                  }
                }
              }
            } catch (e) {
              console.log('Error processing SVG path:', e);
            }
          });
          
          // Zoek ook specifiek naar buttons met de klasse 'close-B02UUUN3'
          const closeButtons = document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"]');
          console.log(`Found ${closeButtons.length} close buttons`);
          
          closeButtons.forEach(button => {
            try {
              console.log('Clicking close button...');
              button.click();
              
              // Zoek de parent dialoog en verwijder deze
              let dialog = button.closest('[role="dialog"]') || 
                          button.closest('.tv-dialog') || 
                          button.closest('.js-dialog');
              
              if (dialog) {
                console.log('Found parent dialog via close button, removing...');
                dialog.style.display = 'none';
                if (dialog.parentNode) {
                  try {
                    dialog.parentNode.removeChild(dialog);
                    console.log('Successfully removed dialog from DOM');
                  } catch (e) {
                    console.log('Error removing dialog:', e);
                  }
                }
              }
            } catch (e) {
              console.log('Error clicking close button:', e);
            }
          });
          
          // Laatste methode: zoek tekstelementen die wijzen op de Stock Screener popup
          const stockScreenerTexts = [
            "Stock Screener is disappearing",
            "Got it, thanks",
            "Stock Screener", 
            "notification"
          ];
          
          // Loop door alle text nodes in de DOM
          const textNodes = [];
          const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            null,
            false
          );
          
          let node;
          while (node = walker.nextNode()) {
            const text = node.textContent.trim();
            if (text && stockScreenerTexts.some(searchText => text.includes(searchText))) {
              textNodes.push(node);
            }
          }
          
          console.log(`Found ${textNodes.length} text nodes that might be in Stock Screener popup`);
          
          // Verwerk de gevonden nodes
          textNodes.forEach(node => {
            try {
              // Zoek de parent dialoog van deze text node
              let dialog = node.parentElement;
              let found = false;
              
              // Loop naar boven tot we een dialoog vinden
              while (dialog && !found) {
                if (
                  dialog.getAttribute && dialog.getAttribute('role') === 'dialog' ||
                  dialog.classList && (
                    dialog.classList.contains('tv-dialog') ||
                    dialog.classList.contains('js-dialog')
                  )
                ) {
                  found = true;
                  break;
                }
                dialog = dialog.parentElement;
                if (!dialog) break;
              }
              
              if (found && dialog) {
                console.log('Found dialog via text content, removing...');
                
                // Zoek eerst naar een "Got it" button en klik deze
                const gotItButton = Array.from(dialog.querySelectorAll('button')).find(
                  btn => btn.textContent.trim().toLowerCase().includes('got it')
                );
                
                if (gotItButton) {
                  console.log('Found "Got it" button, clicking it...');
                  gotItButton.click();
                }
                
                // Forceer verwijdering van de dialoog
                dialog.style.display = 'none';
                if (dialog.parentNode) {
                  try {
                    dialog.parentNode.removeChild(dialog);
                    console.log('Successfully removed dialog from DOM');
                  } catch (e) {
                    console.log('Error removing dialog:', e);
                  }
                }
              }
            } catch (e) {
              console.log('Error processing text node:', e);
            }
          });
        }
        
        // Stel ook de MutationObserver in om nieuwe dialogen op te vangen
        const observer = new MutationObserver(mutations => {
          // Roep onze functie aan bij elke DOM wijziging
          findAndRemoveStockScreenerPopup();
        });
        
        // Observer voor het hele document
        observer.observe(document.body, { 
          childList: true, 
          subtree: true, 
          attributes: true,
          characterData: true
        });
        
        // Voer direct ook de functie uit
        findAndRemoveStockScreenerPopup();
        
        // Maak een interval om regelmatig te controleren op popups
        setInterval(findAndRemoveStockScreenerPopup, 500);
        
        // Gebruik ook Escape toets om eventuele dialogen te sluiten
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27 }));
      });
      
      // Wacht extra tijd voor de acties om effect te hebben
      await page.waitForTimeout(3000);
      
      // Al het bestaande code om in te blijven staan...
      // Gebruik Playwright selectors
      try {
        console.log('Attempting direct Playwright click on close buttons...');
        const selectors = [
          'button.nav-button-znwuaSC1.size-medium-znwuaSC1.preserve-paddings-znwuaSC1.close-B02UUUN3',
          'button[data-name="close"]',
          '.close-B02UUUN3'
        ];
        
        for (const selector of selectors) {
          const buttons = await page.$$(selector);
          console.log(`Found ${buttons.length} buttons with selector ${selector}`);
          
          for (const button of buttons) {
            await button.click({ force: true }).catch(e => console.log('Click error:', e));
            await page.waitForTimeout(500);
          }
        }
      } catch (e) {
        console.log('Error in Playwright click attempt:', e);
      }
      
      // NIEUWE METHODE: Directe screenshot methode
      // Als alle andere methoden falen, blijf toch doorgaan en neem schermafbeelding
      
      // Als het een TradingView URL is, wacht dan op de chart
      if (url.includes('tradingview.com')) {
        console.log('Waiting for TradingView chart to load...');
        
        // Probeer te wachten op de chart container
        try {
          await page.waitForSelector('.chart-container', { timeout: 10000 });
          console.log('Chart container found');
        } catch (e) {
          console.warn('Could not find chart container, continuing anyway:', e);
        }
        
        // Wacht extra tijd voor de chart om volledig te laden
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
      
      // Laatste DOM-manipulatie voor de screenshot om er zeker van te zijn dat popups verborgen zijn
      await page.evaluate(() => {
        // Verberg alle dialogen direct voor screenshot
        document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog').forEach(dialog => {
          dialog.style.display = 'none';
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
