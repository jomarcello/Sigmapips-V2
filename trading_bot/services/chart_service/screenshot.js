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
      // Gebruik domcontentloaded in plaats van networkidle
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      console.log('Page loaded (domcontentloaded)');
      
      // =============================================
      // VERBERG EN SLUIT DE STOCK SCREENER POPUP
      // =============================================
      
      // 1. Direct via Playwright selectors
      console.log('Trying to find and close Stock Screener popup...');
      
      // Wacht kort zodat popups kunnen verschijnen
      await page.waitForTimeout(2000);
      
      // Directe aanpak met Playwright selectors
      try {
        console.log('Looking for close button with exact selectors...');
        const selectors = [
          'button.nav-button-znwuaSC1.size-medium-znwuaSC1.preserve-paddings-znwuaSC1.close-B02UUUN3',
          'button[data-name="close"]',
          '.close-B02UUUN3'
        ];
        
        for (const selector of selectors) {
          try {
            const buttons = await page.$$(selector);
            console.log(`Found ${buttons.length} buttons with selector ${selector}`);
            
            for (const button of buttons) {
              try {
                console.log(`Clicking button with selector ${selector}`);
                await button.click({ force: true }).catch(e => console.log('Click error:', e));
                await page.waitForTimeout(500);
              } catch (clickError) {
                console.log('Error clicking button:', clickError);
              }
            }
          } catch (selectorError) {
            console.log(`Error with selector ${selector}:`, selectorError);
          }
        }
      } catch (e) {
        console.log('Error in direct selector approach:', e);
      }
      
      // 2. CSS Approach - injecteer CSS om popups te verbergen
      console.log('Injecting CSS to hide popups...');
      
      await page.addStyleTag({
        content: `
          /* Hide all popups and dialogs */
          [role="dialog"], 
          .tv-dialog, 
          .js-dialog,
          .tv-dialog-container,
          .tv-dialog__modal,
          .tv-dialog__modal-container,
          div[data-dialog-name*="chart-new-features"],
          div[data-dialog-name*="notice"],
          div[data-name*="dialog"],
          div:has(> button.nav-button-znwuaSC1) {
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;
            z-index: -9999 !important;
          }
        `
      });
      
      // 3. JavaScript aanpak
      console.log('Using JavaScript to find and remove popups...');
      
      await page.evaluate(() => {
        // Locale functies om popups te verwijderen
        function setupPopupRemover() {
          function removePopups() {
            // Zoek en verwijder specifieke close buttons
            const closeSelectors = [
              'button.nav-button-znwuaSC1.size-medium-znwuaSC1.preserve-paddings-znwuaSC1.close-B02UUUN3',
              'button[data-name="close"]',
              '.close-B02UUUN3'
            ];
            
            closeSelectors.forEach(selector => {
              document.querySelectorAll(selector).forEach(button => {
                try {
                  // Klik de button
                  button.click();
                  
                  // Zoek de parent dialog
                  let parent = button.closest('[role="dialog"]') || 
                               button.closest('.tv-dialog') || 
                               button.closest('.js-dialog');
                  
                  if (parent) {
                    parent.style.display = 'none';
                    if (parent.parentNode) {
                      parent.parentNode.removeChild(parent);
                    }
                  }
                } catch (e) {}
              });
            });
            
            // Zoek direct naar SVG paden (speciaal voor TradingView close button)
            document.querySelectorAll('svg path[d="m.58 1.42.82-.82 15 15-.82.82z"], svg path[d="m.58 15.58 15-15 .82.82-15 15z"]').forEach(path => {
              try {
                // Zoek de parent button
                let button = path;
                while (button && button.tagName !== 'BUTTON') {
                  button = button.parentElement;
                }
                
                if (button) {
                  // Klik de button
                  button.click();
                  
                  // Vind en verwijder de parent dialoog
                  let dialog = button.closest('[role="dialog"]') || 
                               button.closest('.tv-dialog') || 
                               button.closest('.js-dialog');
                  
                  if (dialog) {
                    dialog.style.display = 'none';
                    if (dialog.parentNode) {
                      dialog.parentNode.removeChild(dialog);
                    }
                  }
                }
              } catch (e) {}
            });
            
            // Verwijder alle dialogs
            document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog').forEach(dialog => {
              try {
                dialog.style.display = 'none';
                if (dialog.parentNode) {
                  dialog.parentNode.removeChild(dialog);
                }
              } catch (e) {}
            });
          }
          
          // Stel localStorage waarden in
          try {
            // Universele "don't show" flags voor dialogs
            localStorage.setItem('tv_release_channel', 'stable');
            localStorage.setItem('tv_alert', 'dont_show');
            localStorage.setItem('feature_hint_shown', 'true');
            localStorage.setItem('screener_new_feature_notification', 'shown');
            localStorage.setItem('screener_deprecated', 'true');
            localStorage.setItem('tv_notification', 'dont_show');
          } catch (e) {}
          
          // Run direct
          removePopups();
          
          // Set interval voor continu verwijderen
          return setInterval(removePopups, 100);
        }
        
        // Observer om nieuwe dialogen te detecteren en verwijderen
        function setupMutationObserver() {
          const observer = new MutationObserver(mutations => {
            mutations.forEach(mutation => {
              if (mutation.addedNodes && mutation.addedNodes.length > 0) {
                for (const node of mutation.addedNodes) {
                  if (node.nodeType === 1) {  // ELEMENT_NODE
                    // Als het een dialog is
                    if (
                      node.getAttribute && node.getAttribute('role') === 'dialog' ||
                      node.classList && (
                        node.classList.contains('tv-dialog') ||
                        node.classList.contains('js-dialog')
                      )
                    ) {
                      console.log('MutationObserver: found and removing dialog');
                      node.style.display = 'none';
                      if (node.parentNode) {
                        node.parentNode.removeChild(node);
                      }
                    }
                    
                    // Als het een close button bevat
                    const buttons = node.querySelectorAll('button.nav-button-znwuaSC1, button[data-name="close"]');
                    if (buttons.length > 0) {
                      console.log('MutationObserver: found button, clicking and removing parent');
                      buttons.forEach(button => {
                        button.click();
                        
                        const dialog = button.closest('[role="dialog"]') || 
                                     button.closest('.tv-dialog') || 
                                     button.closest('.js-dialog');
                        
                        if (dialog) {
                          dialog.style.display = 'none';
                          if (dialog.parentNode) {
                            dialog.parentNode.removeChild(dialog);
                          }
                        }
                      });
                    }
                  }
                }
              }
            });
          });
          
          observer.observe(document.body, { childList: true, subtree: true });
          return observer;
        }
        
        // Start beide mechanismen
        window._popupRemoverInterval = setupPopupRemover();
        window._mutationObserver = setupMutationObserver();
      });
      
      // Wacht nog wat tijd voor verdere verwerking
      await page.waitForTimeout(3000);
      
      // 4. Laatste poging direct voor screenshot
      console.log('Final attempt to close dialogs before screenshot...');
      
      await page.evaluate(() => {
        // Laatste zoekpoging naar exact de close button
        const closeButton = document.querySelector('button.nav-button-znwuaSC1.size-medium-znwuaSC1.preserve-paddings-znwuaSC1.close-B02UUUN3');
        if (closeButton) {
          console.log('Found exact close button in final attempt, clicking...');
          try { 
            closeButton.click();
            
            // Zoek parent dialoog
            const dialog = closeButton.closest('[role="dialog"]') || 
                         closeButton.closest('.tv-dialog') ||
                         closeButton.closest('.js-dialog');
                         
            if (dialog) {
              console.log('Found parent dialog, removing completely');
              dialog.style.display = 'none';
              if (dialog.parentNode) {
                dialog.parentNode.removeChild(dialog);
              }
            }
          } catch (e) {}
        }
        
        // Verwijder ook alle dialogen direct
        document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog').forEach(dialog => {
          try {
            console.log('Removing dialog element');
            dialog.style.display = 'none';
            if (dialog.parentNode) {
              dialog.parentNode.removeChild(dialog);
            }
          } catch (e) {}
        });
        
        // Gebruik Escape toets om eventuele dialogen te sluiten
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27 }));
        document.dispatchEvent(new KeyboardEvent('keyup', { key: 'Escape', code: 'Escape', keyCode: 27 }));
      });
      
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
