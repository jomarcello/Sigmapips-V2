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
      
      // Stel localStorage waarden in om meldingen uit te schakelen
      console.log('Setting localStorage values to disable notifications...');
      await page.evaluate(() => {
        // Stel release channel in op stable
        localStorage.setItem('tv_release_channel', 'stable');
        
        // Schakel versie meldingen uit
        localStorage.setItem('tv_alert', 'dont_show');
        
        // Schakel nieuwe functie hints uit
        localStorage.setItem('feature_hint_shown', 'true');
        
        // Stel in dat de nieuwe versie al is weergegeven
        localStorage.setItem('tv_twitter_notification', 'true');
        localStorage.setItem('tv_changelog_notification', 'true');
        
        // Schakel privacy meldingen uit
        localStorage.setItem('TVPrivacySettingsAccepted', 'true');
        
        // Onthoud gebruikersvoorkeuren
        localStorage.setItem('UserPreferences', '{"hiddenMarketBanners":{}}');
        
        // Schakel update meldingen uit
        localStorage.setItem('tv_alert_dialog_chart_v5', 'true');
      });
      
      // Wacht extra tijd voor de pagina om te laden
      console.log('Waiting additional time for page to render...');
      await page.waitForTimeout(10000);
    } catch (navError) {
      console.error('Navigation error:', navError);
      // Probeer toch door te gaan, misschien is de pagina gedeeltelijk geladen
      console.log('Continuing despite navigation error...');
    }
    
    // Als het een TradingView URL is, wacht dan op de chart
    if (url.includes('tradingview.com')) {
      console.log('Waiting for TradingView chart to load...');
      
      // Zoek en verwijder de update meldingen
      console.log('Checking for update notifications...');
      try {
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
