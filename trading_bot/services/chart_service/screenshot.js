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
    
    // Navigeer naar de URL met een minder strenge wachttoestand
    console.log(`Navigating to ${url}`);
    try {
      // Gebruik domcontentloaded in plaats van networkidle
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      console.log('Page loaded (domcontentloaded)');
      
      // Direct zoeken naar de stock screener dialoog en deze actief verwijderen
      console.log('Actively searching for Stock Screener notification...');
      await page.evaluate(() => {
        // Functie om alle tekst te vinden die voorkomt in de pagina
        function findElementsWithText(searchText) {
          const result = [];
          const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            { acceptNode: node => node.nodeValue.includes(searchText) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT }
          );
          
          let node;
          while (node = walker.nextNode()) {
            result.push(node.parentElement);
          }
          
          return result;
        }
        
        // Lijst van teksten die in de Stock Screener dialoog voorkomen
        const screenerTexts = [
          'Stock Screener is disappearing',
          'The old Stock Screener',
          'streamline your experience',
          'Got it, thanks',
          'Screener',
          'removing the old'
        ];
        
        // Zoek naar de tekst en vervolgens de dialoog container
        screenerTexts.forEach(text => {
          const elements = findElementsWithText(text);
          console.log(`Found ${elements.length} elements containing: ${text}`);
          
          elements.forEach(element => {
            // Zoek omhoog naar de dialoog container
            let current = element;
            let foundDialog = false;
            
            // Loop maximaal 10 niveaus omhoog
            for (let i = 0; i < 10; i++) {
              if (!current || current === document.body) break;
              
              // Check of dit een dialoog is
              if (
                current.classList && (
                  current.classList.contains('tv-dialog') ||
                  current.classList.contains('js-dialog')
                ) ||
                current.getAttribute && current.getAttribute('role') === 'dialog' ||
                current.querySelectorAll && (
                  current.querySelectorAll('button').length > 0 ||
                  current.querySelectorAll('[role="dialog"]').length > 0
                )
              ) {
                foundDialog = true;
                console.log('Found dialog containing text:', text);
                
                // Zoek en klik op Got it knoppen
                const buttons = current.querySelectorAll('button');
                let clicked = false;
                
                Array.from(buttons).forEach(button => {
                  if (
                    button.textContent && (
                      button.textContent.includes('Got it') ||
                      button.textContent.includes('thanks') ||
                      button.textContent.includes('OK')
                    )
                  ) {
                    console.log('Clicking button with text:', button.textContent);
                    button.click();
                    clicked = true;
                  }
                });
                
                // Als geen knop gevonden, verberg de dialoog
                current.style.display = 'none';
                current.style.visibility = 'hidden';
                current.style.opacity = '0';
                current.style.pointerEvents = 'none';
                
                // Probeer het element te verwijderen
                try {
                  if (current.parentNode) {
                    current.parentNode.removeChild(current);
                    console.log('Successfully removed dialog');
                  }
                } catch(e) {
                  console.error('Failed to remove dialog:', e);
                }
                
                break;
              }
              
              current = current.parentNode;
            }
          });
        });
      });
      
      // Voeg onmiddellijk krachtige CSS toe om popups en dialogen te blokkeren
      await page.addStyleTag({
        content: `
          /* Zeer agressieve CSS om alle mogelijke popups te verbergen */
          .tv-dialog, 
          .tv-dialog-container,
          .js-dialog, 
          .tv-dialog__modal,
          .tv-dialog__modal-container,
          [role="dialog"], 
          .tv-notification, 
          .feature-notification,
          .tv-toast,
          .tv-alert-dialog,
          div[data-dialog-name*="chart-new-features"],
          div[data-dialog-name*="notice"],
          div[data-name*="dialog"] {
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;
            z-index: -9999 !important;
          }

          /* Zeer specifiek voor de Stock Screener popup */
          body > div > div > div > div > div > div > div > div:has(button:has-text("Got it, thanks")),
          div:has(> div > span:contains("Stock Screener")),
          div:has(> div:contains("streamline your experience")) {
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
          }
        `
      });
      
      // Stel localStorage waarden in om meldingen uit te schakelen
      console.log('Setting localStorage values to disable notifications...');
      await page.evaluate(() => {
        // Volledige lijst van alle mogelijke localStorage instellingen om notificaties te deactiveren
        const settings = {
          // TradingView algemene instellingen
          'tv_release_channel': 'stable',
          'tv_alert': 'dont_show',
          'tv_alert_dialog_chart_v5': 'true',
          'feature_hint_shown': 'true',
          'tv_twitter_notification': 'true',
          'tv_changelog_notification': 'true',
          'TVPrivacySettingsAccepted': 'true',
          
          // Stock Screener specifieke instellingen
          'screener_new_feature_notification': 'shown',
          'tv_notification': 'dont_show',
          'screener_shown': 'true',
          'screener.warning-message': 'shown',
          'screener.notification-message': 'shown',
          'ScreenerNotification_Viewed': 'true',
          'screener_deprecated': 'true',
          'tv_screener_notification': 'dont_show',
          'screener_new_feature_already_shown': 'true',
          
          // Algemene feature hints en notification dialogs
          'tv_notifications_dialog': 'dont_show',
          'notificationsDialogShown': 'true',
          'tv_notification_dialog': 'dont_show',
          'notificationcenter_dialog_shown': 'true',
          'dont-show-notification-hints': 'true',
          'tv_popup': 'dont_show',
          'has_seen_tv_dialog': 'true',
          'DialogNotification_Viewed': 'true',
          'ChartWarning_Viewed': 'true'
        };
        
        // Alle instellingen toepassen
        for (const [key, value] of Object.entries(settings)) {
          try {
            localStorage.setItem(key, value);
          } catch (e) {
            console.log(`Error setting localStorage item: ${key}`, e);
          }
        }
        
        // Sla gebruikersvoorkeuren op voor dialogen
        try {
          // Huidige voorkeuren ophalen en bijwerken
          let prefs = {};
          try {
            prefs = JSON.parse(localStorage.getItem('UserPreferences') || '{}');
          } catch (e) {}
          
          // Update met alle dialogen gesloten
          prefs.hideAllDialogs = true;
          prefs.dontShowHints = true;
          prefs.hiddenMarketBanners = prefs.hiddenMarketBanners || {};
          prefs.hiddenScreenerNotifications = true;
          
          localStorage.setItem('UserPreferences', JSON.stringify(prefs));
        } catch (e) {
          console.log('Error setting user preferences', e);
        }
      });
      
      // Wacht extra tijd voor de pagina om te laden
      console.log('Waiting additional time for page to render...');
      await page.waitForTimeout(5000);
      
      // Voeg direct vangnet toe: MutationObserver om nieuwe dialogen onmiddellijk te verwijderen
      await page.evaluate(() => {
        try {
          // MutationObserver voor het verwijderen van nieuwe dialogen
          const observer = new MutationObserver((mutations) => {
            // Zoek naar nieuwe dialogen in de gemuteerde elementen
            mutations.forEach(mutation => {
              if (mutation.addedNodes && mutation.addedNodes.length > 0) {
                for (let i = 0; i < mutation.addedNodes.length; i++) {
                  const node = mutation.addedNodes[i];
                  
                  // Als het een element node is (type 1)
                  if (node.nodeType === 1) {
                    // Check of het een dialoog is
                    if (
                      node.classList && (
                        node.classList.contains('tv-dialog') ||
                        node.classList.contains('js-dialog') ||
                        node.getAttribute('role') === 'dialog'
                      ) ||
                      node.querySelector && (
                        node.querySelector('.tv-dialog') || 
                        node.querySelector('.js-dialog') ||
                        node.querySelector('[role="dialog"]')
                      )
                    ) {
                      console.log('Found dialog via MutationObserver, removing:', node);
                      
                      // Zoek eerst naar "Got it" knoppen en klik erop
                      const gotItButtons = node.querySelectorAll('button');
                      gotItButtons.forEach(btn => {
                        if (
                          btn.textContent && (
                            btn.textContent.includes('Got it') || 
                            btn.textContent.includes('thanks') ||
                            btn.textContent.includes('OK')
                          )
                        ) {
                          console.log('Clicking button in dialog:', btn.textContent);
                          btn.click();
                        }
                      });
                      
                      // Verberg en verwijderen de dialoog
                      node.style.display = 'none';
                      node.style.visibility = 'hidden';
                      node.style.opacity = '0';
                      node.style.pointerEvents = 'none';
                      
                      // Probeer te verwijderen indien mogelijk
                      try {
                        if (node.parentNode) {
                          node.parentNode.removeChild(node);
                        }
                      } catch(e) {}
                    }
                  }
                }
              }
            });
          });
          
          // Start observing the document
          observer.observe(document.body, { 
            childList: true, 
            subtree: true 
          });
          
          // Keep observer reference in window object
          window._dialogObserver = observer;
          
          console.log('Added MutationObserver to automatically remove dialogs');
        } catch (e) {
          console.error('Error setting up MutationObserver:', e);
        }
      });
    } catch (navError) {
      console.error('Navigation error:', navError);
      // Probeer toch door te gaan, misschien is de pagina gedeeltelijk geladen
      console.log('Continuing despite navigation error...');
    }
    
    // Als het een TradingView URL is, wacht dan op de chart
    if (url.includes('tradingview.com')) {
      console.log('Waiting for TradingView chart to load...');
      
      // Extra code om de specifieke stock screener notificatie te verbergen
      console.log('Hiding all notifications and dialogs via JavaScript...');
      await page.evaluate(() => {
        // Functie om alle elementen met bepaalde tekst te vinden en te verbergen
        function findAndHideElementsWithText(text) {
          const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            {
              acceptNode: function(node) {
                return node.nodeValue.includes(text) ? 
                  NodeFilter.FILTER_ACCEPT : 
                  NodeFilter.FILTER_REJECT;
              }
            }
          );
          
          const matchingNodes = [];
          let node;
          while(node = walker.nextNode()) {
            matchingNodes.push(node);
          }
          
          // Voor elk gevonden knooppunt, zoek het parent dialoog element en verberg het
          matchingNodes.forEach(textNode => {
            let parent = textNode.parentNode;
            while (parent && parent !== document.body) {
              // Als dit een dialoog of popup container is, verberg het
              if (
                parent.classList && (
                  parent.classList.contains('tv-dialog') ||
                  parent.classList.contains('js-dialog') ||
                  parent.getAttribute('role') === 'dialog'
                )
              ) {
                console.log('Hiding dialog with text:', text);
                parent.style.display = 'none';
                parent.style.visibility = 'hidden';
                parent.style.opacity = '0';
                break;
              }
              
              // Zoek buttons in dialoog en klik erop
              if (
                parent.querySelectorAll && 
                (parent.querySelectorAll('button').length > 0)
              ) {
                const buttons = parent.querySelectorAll('button');
                buttons.forEach(button => {
                  if (
                    button.textContent && (
                      button.textContent.includes('Got it') ||
                      button.textContent.includes('thanks') ||
                      button.textContent.includes('OK')
                    )
                  ) {
                    console.log('Clicking button:', button.textContent);
                    button.click();
                  }
                });
              }
              
              parent = parent.parentNode;
            }
          });
        }
        
        // Specifieke tekstfragmenten uit de Stock Screener popup
        const textsToHide = [
          'Stock Screener is disappearing',
          'The old Stock Screener',
          'streamline your experience',
          'Got it, thanks',
          'Try new screener',
          'new, more powerful',
          'removing the old'
        ];
        
        textsToHide.forEach(findAndHideElementsWithText);
      });
      
      // Klik op alle mogelijke "Got it, thanks" knoppen (directe aanpak)
      try {
        console.log('Trying direct approach to dismiss Stock Screener dialog...');
        
        // Opzettelijke vertraging om popup te laten verschijnen
        await page.waitForTimeout(3000);
        
        // Automatisch klikken op alle dialoogvensters met "Got it, thanks" knoppen
        const result = await page.evaluate(() => {
          console.log('Searching for dialogs in the page...');
          
          // Helper functie om een element te klikken als het zichtbaar is
          function clickVisible(element) {
            if (!element) return false;
            
            // Check of element zichtbaar is
            const style = window.getComputedStyle(element);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
              return false;
            }
            
            console.log('Clicking element:', element.tagName, element.textContent);
            element.click();
            return true;
          }
          
          // Specifiek voor de Stock Screener dialog (exacte match)
          const stockScreenerTexts = [
            'The old Stock Screener is disappearing very soon',
            'Stock Screener is disappearing',
            'Stock Screener',
            'streamline your experience',
            'Got it, thanks'
          ];
          
          // Check alle dialog/popup containers
          let clicked = false;
          document.querySelectorAll('.tv-dialog, .tv-dialog__modal-container, [role="dialog"], .js-dialog').forEach(dialog => {
            // Check of dialoog zichtbaar is en de juiste tekst bevat
            if (dialog.style.display !== 'none') {
              let containsText = false;
              stockScreenerTexts.forEach(text => {
                if (dialog.textContent && dialog.textContent.includes(text)) {
                  containsText = true;
                }
              });
              
              if (containsText) {
                // Vind de button met "Got it, thanks"
                const buttons = dialog.querySelectorAll('button');
                buttons.forEach(btn => {
                  if (btn.textContent && (
                    btn.textContent.includes('Got it') || 
                    btn.textContent.includes('thanks') ||
                    btn.textContent.includes('OK') ||
                    btn.textContent.includes('Thanks'))
                  ) {
                    console.log('Found dialog button with text:', btn.textContent);
                    btn.click();
                    clicked = true;
                  }
                });
                
                // Als geen buttons gevonden, probeer close buttons
                if (!clicked) {
                  const closeButtons = dialog.querySelectorAll('.tv-dialog__close-button, .close-button, .close-icon');
                  closeButtons.forEach(btn => {
                    console.log('Found close button');
                    btn.click();
                    clicked = true;
                  });
                }
              }
            }
          });
          
          // Tweede poging: zoek simpelweg alle buttons met "Got it, thanks" tekst
          if (!clicked) {
            document.querySelectorAll('button').forEach(btn => {
              if (btn.textContent && (
                btn.textContent.includes('Got it, thanks') || 
                btn.textContent.includes('Got it') ||
                btn.textContent.includes('OK'))
              ) {
                console.log('Found button with text:', btn.textContent);
                btn.click();
                clicked = true;
              }
            });
          }
          
          return clicked ? 'Clicked something' : 'Nothing clicked';
        });
        
        console.log('Dialog dismissal result:', result);
        
        // Wacht even om de popup te laten verdwijnen
        await page.waitForTimeout(2000);
      } catch (e) {
        console.error('Error in direct dialog dismissal:', e);
      }
      
      // Zoek en verwijder de update meldingen
      console.log('Checking for update notifications...');
      try {
        // Specifieke behandeling voor de Stock Screener melding
        console.log('Checking for Stock Screener notification...');
        const hasScreenerDialog = await page.evaluate(() => {
          // Check specifiek voor de screener melding tekst
          const screeningTexts = [
            'Stock Screener is disappearing',
            'old Stock Screener', 
            'streamline your experience',
            'saved screens'
          ];
          
          // Zoek in alle elementen naar tekst die hiermee overeenkomt
          const allElements = document.querySelectorAll('div');
          for (const element of allElements) {
            if (element.innerText) {
              for (const text of screeningTexts) {
                if (element.innerText.includes(text)) {
                  console.log('Found Stock Screener dialog text:', text);
                  
                  // Zoek de "Got it, thanks" knop
                  const gotItButton = Array.from(document.querySelectorAll('button')).find(
                    button => button.innerText.includes('Got it, thanks')
                  );
                  
                  if (gotItButton) {
                    console.log('Clicking "Got it, thanks" button');
                    gotItButton.click();
                    return true;
                  }
                  
                  // Als we de knop niet direct kunnen vinden, zoek in de omgeving
                  const parentDialog = element.closest('.tv-dialog, [role="dialog"], .js-dialog');
                  if (parentDialog) {
                    const buttons = parentDialog.querySelectorAll('button');
                    for (const button of buttons) {
                      if (
                        button.innerText.includes('Got it') || 
                        button.innerText.includes('Thanks') || 
                        button.innerText.includes('OK')
                      ) {
                        console.log('Clicking button in Stock Screener dialog:', button.innerText);
                        button.click();
                        return true;
                      }
                    }
                  }
                }
              }
            }
          }
          return false;
        });
        
        if (hasScreenerDialog) {
          console.log('Successfully handled Stock Screener notification');
          // Wacht even om de dialoog te laten verdwijnen
          await page.waitForTimeout(1000);
        } else {
          console.log('No Stock Screener notification found');
        }
        
        // Gebruik ook een directe selector-benadering
        try {
          // Zoek direct naar de "Got it, thanks" knop met een selector
          const gotItButton = await page.$('button:has-text("Got it, thanks")');
          if (gotItButton) {
            console.log('Found "Got it, thanks" button directly, clicking it');
            await gotItButton.click();
            await page.waitForTimeout(1000);
          }
        } catch (err) {
          console.log('Error finding direct button:', err);
        }
        
        // Specifieke behandeling voor TradingView v5 update melding
        console.log('Checking for TradingView v5 update dialog...');
        const hasV5Dialog = await page.evaluate(() => {
          // Zoek naar de v5 dialog op verschillende manieren
          const dialogSelectors = [
            '.tv-dialog__modal-container',
            '.js-dialog',
            '[data-dialog-name="chart-new-features"]',
            '.tv-dialog'
          ];
          
          for (const selector of dialogSelectors) {
            const dialogs = document.querySelectorAll(selector);
            for (const dialog of dialogs) {
              // Controleer of deze dialog de v5 update melding is
              if (
                dialog.innerText.includes('TradingView has been updated') ||
                dialog.innerText.includes('Got it, thanks') ||
                dialog.innerText.includes('Chart V5') ||
                dialog.innerText.includes('New version') ||
                dialog.innerText.includes('Got it')
              ) {
                // Zoek naar knoppen in de dialog
                const buttons = dialog.querySelectorAll('button');
                for (const button of buttons) {
                  if (
                    button.innerText.includes('Got it') ||
                    button.innerText.includes('OK') ||
                    button.innerText.includes('Thanks')
                  ) {
                    console.log('Clicking v5 update dialog button:', button.innerText);
                    button.click();
                    return true;
                  }
                }
                
                // Als er geen specifieke knop is gevonden, probeer de dialog te sluiten
                const closeButton = dialog.querySelector('.tv-dialog__close-button, .close-button');
                if (closeButton) {
                  console.log('Clicking close button on dialog');
                  closeButton.click();
                  return true;
                }
              }
            }
          }
          
          return false;
        });
        
        if (hasV5Dialog) {
          console.log('Successfully handled TradingView v5 update dialog');
          // Wacht even om de dialoog te laten verdwijnen
          await page.waitForTimeout(1000);
        } else {
          console.log('No TradingView v5 update dialog found');
        }
        
        // Zoek en klik op alle "Got it" of "Thanks" knoppen
        await page.evaluate(() => {
          // Zoek elementen met tekst "Got it" of "Thanks"
          const elements = Array.from(document.querySelectorAll('button, a, div'));
          const gotItElements = elements.filter(el => 
            el.innerText && (
              el.innerText.includes('Got it') || 
              el.innerText.includes('Thanks') || 
              el.innerText.includes('OK')
            )
          );
          
          // Klik op alle gevonden elementen
          gotItElements.forEach(el => {
            console.log('Clicking on element with text:', el.innerText);
            el.click();
          });
          
          // Zoek ook naar close buttons zonder specifieke tekst
          const closeButtons = Array.from(document.querySelectorAll('.tv-dialog__close-button, .close-button, .close-icon'));
          closeButtons.forEach(btn => btn.click());
        });
      } catch (e) {
        console.log('Error trying to close notifications:', e);
        // Doorgaan met screenshot ook als dit faalt
      }
      
      // Wacht op de chart container met een kortere timeout
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
        // Gebruik Shift+F in plaats van F11
        await page.keyboard.down('Shift');
        await page.keyboard.press('F');
        await page.keyboard.up('Shift');
        await page.waitForTimeout(2000); // Wacht iets langer voor fullscreen effect
        console.log('Fullscreen mode activated');
      }
      
      console.log('Chart loaded, taking screenshot...');
    } else {
      console.log('Not a TradingView URL, waiting for page load...');
      await page.waitForTimeout(3000);
    }
    
    // Laatste poging om alle dialogen weg te klikken voordat screenshot wordt genomen
    console.log('Final attempt to dismiss all dialogs...');
    
    // Probeer direct op de "Got it, thanks" knop te klikken met Playwright
    try {
      console.log('Trying to click directly on "Got it, thanks" button...');
      
      // Zoek elke knop met "Got it"
      const gotItButtons = await page.$$('button');
      let clicked = false;
      
      for (const button of gotItButtons) {
        const text = await button.textContent();
        if (text && (text.includes('Got it') || text.includes('thanks') || text.includes('OK'))) {
          console.log('Found button with text:', text);
          await button.click();
          clicked = true;
          await page.waitForTimeout(500);
        }
      }
      
      if (clicked) {
        console.log('Successfully clicked button directly');
        await page.waitForTimeout(1000);
      } else {
        console.log('No buttons found to click directly');
      }
    } catch (e) {
      console.error('Error in direct button click:', e);
    }
    
    // Brute force method: injecteer CSS om alle dialogen te verbergen
    console.log('Injecting CSS to hide all dialogs...');
    await page.addStyleTag({
      content: `
        /* Hide all dialogs and pop-ups */
        .tv-dialog, 
        .js-dialog, 
        [role="dialog"], 
        .tv-notification, 
        .feature-notification,
        .tv-toast,
        .tv-alert-dialog,
        .tv-dialog__modal,
        .tv-dialog__modal-container,
        div[data-name*="dialog"],
        div[data-dialog-name*="chart-new-features"],
        div[data-dialog-name*="notice"],
        .tv-dialog-container {
          display: none !important;
          visibility: hidden !important;
          opacity: 0 !important;
          pointer-events: none !important;
          z-index: -9999 !important;
        }
      `
    });
    
    await page.evaluate(() => {
      // Functie om een element te klikken als het bestaat
      const clickIfExists = (selector) => {
        const elements = document.querySelectorAll(selector);
        elements.forEach(el => {
          console.log('Clicking element:', selector);
          el.click();
        });
        return elements.length > 0;
      };
      
      // Lijst van selectors voor verschillende soorten dialogen en knoppen
      const dismissSelectors = [
        'button:has-text("Got it, thanks")',
        'button:has-text("Got it")',
        'button:has-text("OK")',
        'button:has-text("Thanks")',
        'button:has-text("Try new screener")',
        '.tv-dialog__close-button',
        '.close-button',
        '.close-icon',
        '[data-dialog-name="chart-new-features"] button',
        '.tv-dialog button',
        '.feature-notification__close',
        '.tv-notification__close'
      ];
      
      // Probeer alle selectors
      dismissSelectors.forEach(clickIfExists);
      
      // Zoek ook naar specifieke dialoogteksten en klik op de bijbehorende knoppen
      const allDialogs = document.querySelectorAll('.tv-dialog, [role="dialog"], .js-dialog, .tv-notification');
      allDialogs.forEach(dialog => {
        if (dialog && dialog.style.display !== 'none') {
          const buttons = dialog.querySelectorAll('button');
          buttons.forEach(btn => btn.click());
        }
      });
      
      // Verberg eventueel resterende dialogen met CSS
      const styleEl = document.createElement('style');
      styleEl.textContent = `
        .tv-dialog, .js-dialog, [role="dialog"], .tv-notification, .feature-notification { 
          display: none !important; 
          visibility: hidden !important;
          opacity: 0 !important;
        }
      `;
      document.head.appendChild(styleEl);
    });
    
    // Wacht een laatste moment om zeker te zijn
    await page.waitForTimeout(1000);
    
    // Extra wachttijd voor stabiliteit (indien nodig)
    await page.waitForTimeout(2000);
    
    // Laatste handleiding check en klik actie voor alle Got it knoppen
    console.log('Final check for Got it buttons...');
    await page.evaluate(() => {
      // Zoek alle knoppen met "Got it" tekst en klik erop
      const buttons = Array.from(document.querySelectorAll('button'));
      buttons.forEach(button => {
        if (button.textContent && (
            button.textContent.includes('Got it') || 
            button.textContent.includes('thanks') || 
            button.textContent.includes('OK') ||
            button.textContent.includes('Close')
          )) {
          console.log('Clicking button with text:', button.textContent);
          button.click();
        }
      });
      
      // Forceer alle dialogen te verdwijnen
      const dialogs = Array.from(document.querySelectorAll('.tv-dialog, .js-dialog, [role="dialog"], .tv-notification, .feature-notification, .tv-toast, .tv-alert-dialog'));
      dialogs.forEach(dialog => {
        dialog.style.display = 'none';
        dialog.style.visibility = 'hidden';
        dialog.style.opacity = '0';
        dialog.style.pointerEvents = 'none';
        dialog.style.zIndex = '-9999';
        
        // Probeer te verwijderen indien mogelijk
        try {
          if (dialog.parentNode) {
            dialog.parentNode.removeChild(dialog);
          }
        } catch(e) {}
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
  } catch (error) {
    console.error('Error:', error);
    if (browser) {
      await browser.close().catch(e => console.error('Error closing browser:', e));
    }
    process.exit(1);
  }
})(); 
