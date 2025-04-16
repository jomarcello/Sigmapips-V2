// Geoptimaliseerde versie voor betere performance
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
let playwrightInstalled = false;
try {
  require.resolve('playwright');
  console.log("Playwright module is already installed");
  playwrightInstalled = true;
} catch (e) {
  console.log("Installing Playwright...");
  try {
    // Snellere installatie met minimal flag
    execSync('npm install playwright-core --no-save', { stdio: 'inherit' });
    execSync('npx playwright install chromium --with-deps', { stdio: 'inherit' });
    console.log("Playwright installed successfully");
    playwrightInstalled = true;
  } catch (installError) {
    console.error("Failed to install Playwright:", installError);
    process.exit(1);
  }
}

// Nu kunnen we playwright importeren
const { chromium } = playwrightInstalled ? require('playwright') : require('playwright-core');

(async () => {
  let browser;
  try {
    console.log(`Taking screenshot of ${url} and saving to ${outputPath} (fullscreen: ${fullscreen})`);
    
    // Start een browser met minimale opties voor betere prestaties
    browser = await chromium.launch({
      headless: true,
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-gpu',
        '--disable-features=site-per-process',
        '--disable-web-security',
        '--disable-dev-shm-usage',
        '--disable-notifications',
        '--disable-popup-blocking',
        '--disable-extensions',
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-breakpad',
        '--disable-component-extensions-with-background-pages',
        '--disable-ipc-flooding-protection',
        '--disable-renderer-backgrounding',
        '--no-first-run',
        '--no-startup-window',
        '--no-zygote',
        '--mute-audio',
        '--ignore-gpu-blocklist',
        '--use-gl=swiftshader',
        '--disable-software-rasterizer',
        '--font-render-hinting=none'
      ],
      handleSIGINT: false,
      handleSIGTERM: false,
      handleSIGHUP: false,
      env: {
        ...process.env,
        DISPLAY: process.env.DISPLAY || ':99',
        XAUTHORITY: process.env.XAUTHORITY || ''
      }
    });
    
    // Optimaliseer context-instellingen voor snelheid
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      deviceScaleFactor: 1,
      bypassCSP: true,
      javaScriptEnabled: true,
      permissions: ['notifications'],
      locale: 'en-US',
      timezoneId: 'Europe/Amsterdam',
      acceptDownloads: false, // Schakel downloads uit voor snelheid
    });
    
    // Voeg de essentiële scripts toe om popup-dialogen te blokkeren (minimaal gehouden)
    await context.addInitScript(() => {
      // Blokkeer popups en dialogen
      window.open = () => null;
      window.confirm = () => true;
      window.alert = () => {};
      
      // TradingView-specifieke localStorage-essentials
      const essentialSettings = {
        'tv_release_channel': 'stable',
        'tv_alert': 'dont_show',
        'feature_hint_shown': 'true',
        'screener_new_feature_notification': 'shown',
        'hints_are_disabled': 'true',
        'tv_notification': 'dont_show',
        'tv_notification_popup': 'dont_show'
      };
      
      // Stel alleen de essentiële localStorage-waarden in
      Object.entries(essentialSettings).forEach(([key, value]) => {
        try {
          localStorage.setItem(key, value);
        } catch (e) {}
      });
    });
    
    // Voeg alleen essentiële cookies toe als er een session ID is
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
    
    // Auto-dismiss dialogs
    page.on('dialog', async dialog => {
      await dialog.dismiss().catch(() => {});
    });
    
    // Voeg essentiële CSS toe om dialogen direct te blokkeren
    await page.addStyleTag({
      content: `
        [role="dialog"], 
        .tv-dialog, 
        .js-dialog,
        .tv-dialog-container,
        .tv-dialog__modal,
        .tv-dialog__modal-container,
        div[data-dialog-name*="chart-new-features"],
        div[data-name*="dialog"],
        .tv-dialog--popup,
        .tv-alert-dialog,
        .tv-notification {
          display: none !important;
          visibility: hidden !important;
          opacity: 0 !important;
        }
      `
    }).catch(() => {});
    
    // Navigeer met aangepaste opties voor snelheid
    console.log(`Navigating to ${url}`);
    try {
      await page.goto(url, { 
        waitUntil: 'load', // Gebruik 'load' in plaats van 'networkidle'
        timeout: 20000 // Langere timeout voor volledig laden
      });
      console.log('Page loaded (load event fired)');
      
      // Wacht kort op initiële JavaScript executie
      await page.waitForTimeout(2000);
      
      // Toets ESC indrukken om dialogs te sluiten
      await page.keyboard.press('Escape').catch(() => {});
      
      // Verbeterde wachtfunctie voor TradingView charts
      if (url.includes('tradingview.com')) {
        console.log('Waiting for TradingView chart to load completely...');
        
        // 1. Wacht eerst op de chart container
        try {
          await page.waitForSelector('.chart-container', { timeout: 10000 });
          console.log('Chart container found');
        } catch (e) {
          console.warn('Could not find chart container, continuing anyway');
        }
        
        // 2. Wacht tot er candles zichtbaar zijn (deze selector is specifiek voor TradingView)
        try {
          await page.waitForSelector('.price-axis', { timeout: 10000 });
          console.log('Price axis found, chart has data');
        } catch (e) {
          console.warn('Could not find price axis, chart might not have loaded data');
        }
        
        // 3. Probeer te wachten tot JavaScript animaties zijn voltooid
        await page.evaluate(() => {
          return new Promise(resolve => {
            // Controleer of er candles zijn
            const hasPriceData = document.querySelector('.price-axis') !== null;
            
            if (hasPriceData) {
              console.log('Chart has price data, waiting for animations to complete');
              // Geef voldoende tijd voor UI animaties
              setTimeout(resolve, 2000);
            } else {
              // Als er geen prijsdata is, wacht korter
              setTimeout(resolve, 1000);
            }
          });
        });
        
        // 4. Controleer of het chart gebied gevuld is met data door middel van pixeldetectie
        const hasData = await page.evaluate(() => {
          try {
            // Probeer de canvas te vinden waarop de chart is getekend
            const canvas = document.querySelector('.chart-markup-table canvas');
            if (!canvas) return false;
            
            // Controleer of de canvas niet leeg is door te kijken naar niet-transparante pixels
            const ctx = canvas.getContext('2d');
            const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
            
            // Als er genoeg niet-transparante pixels zijn, heeft de chart waarschijnlijk gerenderd
            let nonTransparentPixels = 0;
            for (let i = 3; i < data.length; i += 4) {
              if (data[i] > 0) nonTransparentPixels++;
            }
            
            console.log(`Canvas has ${nonTransparentPixels} non-transparent pixels`);
            return nonTransparentPixels > 1000; // Voldoende data gerenderd
          } catch (e) {
            console.error('Error checking chart data:', e);
            return true; // Bij fout gaan we door met screenshot
          }
        });
        
        if (hasData) {
          console.log('Chart has rendered data');
        } else {
          console.warn('Chart might not have rendered data, waiting additional time');
          // Extra wachttijd indien er geen data lijkt te zijn
          await page.waitForTimeout(3000);
        }
        
        // 5. Fulllscreen modus toepassen
        if (fullscreen || url.includes('fullscreen=true')) {
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
          console.log('Fullscreen CSS applied');
        }
        
        // 6. Wacht een finale periode voor stabiliteit
        console.log('Waiting final stabilization period...');
        await page.waitForTimeout(2000);
      } else {
        // Voor niet-TradingView pagina's
        await page.waitForTimeout(2000);
      }
      
      // 7. Neem screenshot en sluit af
      console.log('Taking screenshot...');
      await page.screenshot({ path: outputPath });
      console.log(`Screenshot saved to ${outputPath}`);
      
      await browser.close();
      process.exit(0);
    } catch (navError) {
      console.error('Navigation error:', navError);
      
      // Probeer toch een screenshot te maken
      try {
        console.log('Attempting screenshot despite error...');
        await page.screenshot({ path: outputPath });
        console.log(`Screenshot saved despite errors to ${outputPath}`);
      } catch (e) {
        console.error('Failed to take screenshot after navigation error:', e);
        await browser.close().catch(() => {});
        process.exit(1);
      }
      
      await browser.close().catch(() => {});
      process.exit(0);
    }
  } catch (error) {
    console.error('Error:', error);
    if (browser) {
      await browser.close().catch(() => {});
    }
    process.exit(1);
  }
})(); 
