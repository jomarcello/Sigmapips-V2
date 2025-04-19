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

// CSS om dialoogvensters te verbergen (gebruik één gemeenschappelijke definitie)
const hideDialogsCSS = `
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
  
  /* Verberg de overlay/backdrop */
  .tv-dialog__modal-background {
    opacity: 0 !important;
    display: none !important;
    visibility: hidden !important;
  }
`;

// Fullscreen CSS (apart van dialogen)
const fullscreenCSS = `
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
`;

// Anti-popup script
const removePopupsScript = `
  function removeAllDialogs() {
    // Escape key om dialogen te sluiten
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
    
    // Zoek en klik op alle sluitingsknoppen
    document.querySelectorAll('button.close-B02UUUN3, button[data-name="close"], .nav-button-znwuaSC1').forEach(btn => {
      try { btn.click(); } catch (e) {}
    });
    
    // Zoek speciek op SVG paden (X-pictogrammen in sluitknoppen)
    document.querySelectorAll('svg path[d="m.58 1.42.82-.82 15 15-.82.82z"], svg path[d="m.58 15.58 15-15 .82.82-15 15z"]').forEach(path => {
      try {
        let button = path;
        while (button && button.tagName !== 'BUTTON') {
          button = button.parentElement;
          if (!button) break;
        }
        if (button) button.click();
      } catch (e) {}
    });
    
    // Klik op "Got it, thanks" knoppen
    document.querySelectorAll('button').forEach(btn => {
      const text = btn.textContent || '';
      if (text.includes('Got it') || text.includes('thanks') || text.includes('OK') || text.includes('Dismiss')) {
        try { btn.click(); } catch (e) {}
      }
    });
    
    // Verwijder alle dialoogelementen direct
    document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog, .tv-dialog--popup').forEach(dialog => {
      try {
        dialog.style.display = 'none';
        dialog.style.visibility = 'hidden';
        dialog.style.opacity = '0';
        if (dialog.parentNode) dialog.parentNode.removeChild(dialog);
      } catch (e) {}
    });
  }
  
  // Blokker voor window.open om nieuwe popups te voorkomen
  window.open = () => null;
  window.confirm = () => true;
  window.alert = () => {};
  
  // Loop alle localStorage sleutels door om alles uit te schakelen
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && (
      key.endsWith("_do_not_show_again") || 
      key.includes("notification") || 
      key.includes("popup") || 
      key.includes("alert") ||
      key.includes("hint")
    )) {
      localStorage.setItem(key, key.includes("notification") ? 'shown' : 'true');
    }
  }
  
  // Voer direct uit en stel interval in
  removeAllDialogs();
  setInterval(removeAllDialogs, 250);
`;

(async () => {
  let browser;
  try {
    console.log(`Taking screenshot of ${url} and saving to ${outputPath} (fullscreen: ${fullscreen})`);
    
    // Start een browser met minimale argumenten
    browser = await chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    // Maak een nieuwe context en pagina met basisinstellingen
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
      bypassCSP: true,
      javaScriptEnabled: true,
      locale: 'en-US',
      timezoneId: 'Europe/Amsterdam',
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
    
    // Dialogs automatisch sluiten
    page.on('dialog', async dialog => {
      console.log(`Auto-dismissing dialog: ${dialog.type()}`);
      await dialog.dismiss().catch(() => {});
    });
    
    // Stel een kortere timeout in
    page.setDefaultTimeout(30000);
    
    // Voeg CSS toe om dialogen bij page load direct te blokkeren
    await page.addStyleTag({ content: hideDialogsCSS }).catch(e => {});
    
    // Navigeer naar de URL
    console.log(`Navigating to ${url}`);
    try {
      // Navigeer met kortere timeout en domcontentloaded is sneller
      await page.goto(url, { 
        waitUntil: 'domcontentloaded', 
        timeout: 15000 
      });
      console.log('Page loaded (domcontentloaded)');
      
      // Voeg CSS voor dialogen opnieuw toe en voer anti-popup script uit
      await page.addStyleTag({ content: hideDialogsCSS });
      await page.evaluate(removePopupsScript);
      
      // Wacht kort om de pagina basisonderdelen te laten laden
      await page.waitForTimeout(500);
      
      // Direct verwijder popups via Playwright
      const closeSelectors = [
        'button.close-B02UUUN3', 
        'button[data-name="close"]'
      ];
      
      for (const selector of closeSelectors) {
        const buttons = await page.$$(selector);
        console.log(`Found ${buttons.length} buttons with selector ${selector}`);
        for (const button of buttons) {
          try {
            await button.click({ force: true }).catch(() => {});
          } catch (e) {}
        }
      }
      
      // Als fullscreen is aangevraagd, voeg CSS toe en gebruik Shift+F
      if (fullscreen) {
        console.log('Applying fullscreen CSS');
        await page.addStyleTag({ content: fullscreenCSS });
        
        console.log('Enabling fullscreen mode with Shift+F...');
        await page.keyboard.down('Shift');
        await page.keyboard.press('F');
        await page.keyboard.up('Shift');
      }

      // Wacht op de chart container (maar niet te lang)
      console.log('Waiting for chart to be fully loaded...');
      try {
        const waitPromise = page.waitForFunction(() => {
          return document.querySelector('.chart-container') !== null;
        }, { timeout: 5000 });
        
        await Promise.race([
          waitPromise,
          new Promise(resolve => setTimeout(resolve, 5000))
        ]);
        console.log('Chart loaded or timeout reached');
      } catch (e) {
        console.log('Timeout waiting for chart, continuing anyway');
      }
      
      // Laatste popup cleanup
      await page.evaluate('removeAllDialogs && removeAllDialogs()');
      
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
      // Probeer toch de screenshot te maken
      try {
        const screenshot = await page.screenshot({ path: outputPath });
        console.log(`Screenshot saved despite errors to ${outputPath}`);
      } catch (e) {
        console.error('Failed to take screenshot after navigation error:', e);
        if (browser) await browser.close().catch(e => {});
        process.exit(1);
      }
      
      if (browser) await browser.close().catch(e => {});
      process.exit(0);
    }
  } catch (error) {
    console.error('Error:', error);
    if (browser) await browser.close().catch(e => {});
    process.exit(1);
  }
})(); 
