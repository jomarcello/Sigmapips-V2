// Verbeterde foutafhandeling en module import
const fs = require('fs');
const { execSync } = require('child_process');
const os = require('os');
const path = require('path');

// Haal de argumenten op
const url = process.argv[2];
const outputPath = process.argv[3];
const sessionId = process.argv[4] || '';
const fullscreen = process.argv[5] === 'fullscreen';

// Configuratie voor betrouwbare screenshots
const VIEWPORT_WIDTH = 1280;
const VIEWPORT_HEIGHT = 800;
const DEFAULT_TIMEOUT = 30000;
const CHART_WAIT_TIMEOUT = 20000;

// Log de argumenten voor debugging
console.log(`URL: ${url}`);
console.log(`Output path: ${outputPath}`);
console.log(`Session ID: ${sessionId ? 'Using session ID: ' + sessionId.substring(0, 5) + '...' : 'Not provided'}`);
console.log(`Fullscreen: ${fullscreen}`);

// Controleer of Playwright is geïnstalleerd, zo niet, installeer het
try {
  // Probeer eerst of playwright al beschikbaar is
  require.resolve('playwright');
  console.log("Using locally installed playwright module");
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

// Globale browser instantie voor hergebruik
let browserInstance = null;

(async () => {
  let browser;
  let context;
  let page;
  
  try {
    console.log(`Taking screenshot of ${url} and saving to ${outputPath} (fullscreen: ${fullscreen})`);
    
    // Zorg ervoor dat de output directory bestaat
    const outputDir = path.dirname(outputPath);
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }
    
    // Gebruik globale browser of maak nieuwe aan met minimale argumenten
    if (browserInstance) {
      browser = browserInstance;
      console.log("Reusing existing browser instance");
    } else {
      // Maak een tijdelijke directory voor browser data
      const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pw-chrome-'));
      
      browser = await chromium.launch({
        headless: true,
        args: [
          '--no-sandbox',
          '--disable-setuid-sandbox',
          '--disable-web-security',
          '--disable-features=IsolateOrigins,site-per-process',
          '--disable-site-isolation-trials',
          '--disable-dev-shm-usage',
          '--disable-gpu',
          '--disable-extensions',
          '--disable-notifications',
          '--disable-popup-blocking'
        ],
        downloadsPath: tmpDir
      });
      browserInstance = browser;
      console.log("New browser instance created");
    }
    
    // Maak een nieuwe context met verbeterde configuratie
    context = await browser.newContext({
      viewport: { width: VIEWPORT_WIDTH, height: VIEWPORT_HEIGHT },
      deviceScaleFactor: 1,
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
      bypassCSP: true,
      ignoreHTTPSErrors: true,
      javaScriptEnabled: true
    });
    
    // Verbeterde stealth configuratie
    await context.addInitScript(() => {
      // TradingView-specifieke localStorage waarden om popups te voorkomen
      const tvLocalStorage = {
        'tv_release_channel': 'stable',
        'feature_hint_shown': 'true',
        'screener_new_feature_notification': 'shown',
        'hints_are_disabled': 'true',
        'tv_notification': 'dont_show',
        'has_visited_chart': 'true',
        'LoginDialog.isSignUpFormOpened': 'false',
        'LoginDialog.isLoginFormOpened': 'false',
        'sign_in_from': 'link',
        'login_dialog_closed': 'true',
        'chart_watchlist': '{"watchlists":[],"activeListId":null}',
        'recent_tickers': 'EURUSD',
        'chart.lastUsedStyle': '{"name":"Candles","lb":"candle"}',
        'UI.TradingView.DrawingToolbar.toolbarState': 'off'
      };
      
      // Stel belangrijkste localStorage waarden in
      Object.entries(tvLocalStorage).forEach(([key, value]) => {
        try {
          localStorage.setItem(key, value);
        } catch (e) {}
      });
      
      // Blokkeer popups en alerts
      window.open = () => null;
      window.confirm = () => true;
      window.alert = () => {};
      window.onbeforeunload = null;
      
      // Verwijder modal blokkades
      Object.defineProperty(window, 'TVDialogs', {
        value: { modal: () => ({ close: () => {} }) },
        writable: false
      });
    });
    
    // Voeg cookies toe voor authenticatie
    if (sessionId) {
      await context.addCookies([
        {
          name: 'sessionid',
          value: sessionId,
          domain: '.tradingview.com',
          path: '/',
        },
        {
          name: 'tv_authed',
          value: '1',
          domain: '.tradingview.com',
          path: '/',
        }
      ]);
      console.log('Using session ID:', sessionId.substring(0, 5) + '...');
    }
    
    page = await context.newPage();
    
    // Configureer netwerk interception
    await setupNetworkInterception(page);
    
    // Navigeer naar de URL
    console.log(`Navigating to ${url}...`);
    try {
      // Setup event handler voor dialogs
      page.on('dialog', async dialog => {
        console.log(`Dismissing dialog: ${dialog.type()}, message: ${dialog.message().substring(0, 50)}...`);
        await dialog.dismiss().catch(() => {});
      });

      // Voeg CSS toe om dialogen te blokkeren
      await page.addStyleTag({
        content: `
          /* Verberg alle dialogen en popups */
          [role="dialog"], 
          .tv-dialog, 
          .js-dialog,
          .tv-dialog-container,
          .tv-dialog__modal,
          div[data-dialog-name*="chart-new-features"],
          div[data-dialog-name*="notice"],
          div[data-name*="dialog"],
          .tv-dialog--popup,
          .tv-alert-dialog,
          .tv-notification,
          #overlap-manager-root,
          div[data-role="toast-container"],
          div[data-name="popup-dialog"] {
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;
          }
          
          /* Verberg de overlay/backdrop */
          .tv-dialog__modal-background {
            opacity: 0 !important;
            display: none !important;
          }

          /* Maximale chart weergave */
          body.chart-page {
            overflow: hidden !important;
          }
          .chart-container, .chart-gui-wrapper, .chart-markup-table.pane {
            width: 100% !important;
            height: 100% !important;
          }
          .full-height, .layout__area--center {
            height: 100% !important;
          }
        `
      }).catch(e => console.warn('Warning: Failed to add style tag', e.message));
      
      // Navigeer met verbeterde opties
      await page.goto(url, { 
        waitUntil: 'domcontentloaded', 
        timeout: DEFAULT_TIMEOUT 
      });
      console.log('Page loaded, waiting for chart to render...');
      
      // Stel localStorage in en sluit popups
      await page.evaluate(() => {
        // Simuleer Escape om popups te sluiten
        for (let i = 0; i < 5; i++) {
          document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
        }
        
        // Force TradingView initialisatie
        if (window.TradingView && window.TradingView.onready) {
          try {
            window.TradingView.onready();
          } catch (e) {}
        }
        
        // Trigger een resize event om ervoor te zorgen dat de chart correct wordt weergegeven
        window.dispatchEvent(new Event('resize'));
      });

      // Wacht extra tijd voor de pagina om te laden
      await page.waitForTimeout(3000);
      
      // Sluit popups en modals
      await closePopups(page);
      
      // Wacht beter op TradingView chart container
      if (url.includes('tradingview.com')) {
        console.log('Waiting for chart indicators to render...');
        
        try {
          // Wacht tot prijsbalken of elementen geladen zijn
          const chartSelector = await waitForAnyChartElement(page);
          if (chartSelector) {
            console.log(`Found chart element: ${chartSelector}`);
          } else {
            console.warn('Could not find specific chart element, continuing anyway');
          }
        } catch (e) {
          console.warn('Error waiting for chart elements:', e.message);
        }
        
        // Check of de chart technische indicatoren bevat
        const hasIndicators = await page.evaluate(() => {
          const priceAxis = document.querySelector('.price-axis');
          const chartElements = document.querySelectorAll('path[stroke], .chart-markup-table rect');
          const loadingElement = document.querySelector('.loading-indicator, .tv-spinner');
          
          // Als er nog een loading indicator is, is de chart waarschijnlijk niet volledig geladen
          if (loadingElement && window.getComputedStyle(loadingElement).display !== 'none') {
            return false;
          }
          
          return priceAxis && chartElements.length > 10;
        });
        
        if (!hasIndicators) {
          console.log('Chart indicators not found, waiting longer...');
          await page.waitForTimeout(5000);
        }
        
        // Als fullscreen is aangevraagd, pas toe met meerdere methoden
        if (fullscreen || url.includes('fullscreen=true')) {
          console.log('Applying fullscreen mode...');
          await applyFullscreenMode(page);
        }
      }
      
      // Verwijder storende elementen voor de screenshot
      await page.evaluate(() => {
        // Verwijder alle dialogen
        document.querySelectorAll('[role="dialog"], .tv-dialog, .js-dialog, .toast-container').forEach(el => {
          if (el && el.parentNode) {
            el.parentNode.removeChild(el);
          }
        });
        
        // Verwijder header-elementen
        document.querySelectorAll('.header-chart-panel, .tv-side-toolbar').forEach(el => {
          if (el) el.style.display = 'none';
        });
        
        // Trigger resize event voor betere rendering
        window.dispatchEvent(new Event('resize'));
      });
      
      // Wacht kort zodat veranderingen effect hebben
      await page.waitForTimeout(2000);
      
      // Neem screenshot
      console.log('Taking screenshot...');
      const screenshot = await page.screenshot({ 
        path: outputPath,
        timeout: DEFAULT_TIMEOUT
      });
      console.log('Screenshot taken successfully');
      
      // Controleer of het bestand succesvol is opgeslagen
      if (fs.existsSync(outputPath) && fs.statSync(outputPath).size > 1000) {
        console.log(`Screenshot saved to ${outputPath} (${fs.statSync(outputPath).size} bytes)`);
      } else {
        console.error('Screenshot file is too small or not created properly');
      }
      
      // Sluit de pagina en context, maar houd de browser open voor hergebruik
      await page.close();
      await context.close();
      
      console.log('Done!');
      process.exit(0);
      
    } catch (navError) {
      console.error('Navigation error:', navError);
      
      // Probeer toch screenshot te maken
      try {
        console.log('Attempting to take screenshot despite navigation error...');
        await page.waitForTimeout(1000);
        const screenshot = await page.screenshot({ path: outputPath });
        console.log(`Screenshot saved despite errors`);
        await page.close();
        await context.close();
        process.exit(0);
      } catch (e) {
        console.error('Failed to take screenshot after navigation error:', e);
        cleanup(browser, page, context);
        process.exit(1);
      }
    }
  } catch (error) {
    console.error('Error:', error);
    cleanup(browser, page, context);
    process.exit(1);
  }
})();

// Helper functie: wacht tot een van de chart elementen zichtbaar is
async function waitForAnyChartElement(page) {
  const selectors = [
    '.chart-container',
    '.chart-markup-table',
    '.tv-chart-container',
    '.layout__area--center',
    '.chart-container-border',
    '.js-chart-container',
    '.chart-gui-wrapper',
    '.price-axis'
  ];
  
  for (const selector of selectors) {
    try {
      const element = await page.waitForSelector(selector, { 
        state: 'visible', 
        timeout: CHART_WAIT_TIMEOUT / selectors.length
      });
      
      if (element) {
        return selector;
      }
    } catch (e) {
      // Ga door naar de volgende selector
    }
  }
  
  return null;
}

// Helper functie: sluit popups
async function closePopups(page) {
  try {
    // Druk meerdere keren op Escape
    for (let i = 0; i < 3; i++) {
      await page.keyboard.press('Escape');
      await page.waitForTimeout(100);
    }
    
    // Lijst van mogelijke popup selectors
    const popupSelectors = [
      'button[data-name="accept-cookies-button"]',
      'button:has-text("Accept all cookies")',
      'div[data-role="toast-container"] button',
      'div[data-name="popup-dialog"] button[data-name="dialog-close"]',
      '.tv-dialog__close',
      '.tv-dialog button.close',
      'button[data-dialog-action="cancel"]',
      'button[data-dialog-action="close"]',
      'button.js-dialog__close',
      '[data-name="header-toolbar-close"]',
      '[data-name="close-button"]',
      '.tv-notification__close'
    ];
    
    // Klik op alle popup knoppen die we kunnen vinden
    for (const selector of popupSelectors) {
      const buttons = await page.$$(selector);
      if (buttons.length > 0) {
        console.log(`Found ${buttons.length} popup buttons matching ${selector}, clicking...`);
        for (const button of buttons) {
          await button.click().catch(() => {});
        }
      }
    }
  } catch (error) {
    console.log('Error closing popups:', error.message);
  }
}

// Helper functie: pas fullscreen modus toe
async function applyFullscreenMode(page) {
  try {
    // Methode 1: Verberg interface elementen met CSS
    await page.addStyleTag({
      content: `
        .header-chart-panel, .tv-side-toolbar, .bottom-widgetbar-content.backtesting, 
        .chart-controls-bar, .control-bar, .drawing-toolbar {
          display: none !important;
        }
        .chart-container, .chart-markup-table, .chart-container-border {
          height: 100vh !important;
          width: 100vw !important;
        }
      `
    });
    
    // Methode 2: Toetsenbordsnelkoppeling
    await page.keyboard.press('F11');
    
    // Methode 3: Programmisch via DOM
    await page.evaluate(() => {
      // Zoek fullscreen knop
      const fullscreenButton = document.querySelector('button[data-name="full-screen-button"], [data-tooltip-title*="fullscreen"]');
      if (fullscreenButton) {
        fullscreenButton.click();
      }
      
      // Maximaliseer container
      document.querySelectorAll('.chart-container, .chart-markup-table').forEach(el => {
        if (el) {
          el.style.width = '100vw';
          el.style.height = '100vh';
          el.style.position = 'fixed';
          el.style.top = '0';
          el.style.left = '0';
        }
      });
      
      // Trigger resize
      window.dispatchEvent(new Event('resize'));
    });
  } catch (error) {
    console.log('Error applying fullscreen:', error.message);
  }
}

// Helper functie: configureer netwerk interceptie
async function setupNetworkInterception(page) {
  // Log failed requests
  page.on('requestfailed', request => {
    const url = request.url();
    if (url.includes('tradingview.com') && !url.includes('.css') && !url.includes('.png')) {
      console.log(`Request failed: ${url.substring(0, 100)}... - ${request.failure().errorText}`);
    }
  });
  
  // Log belangrijke netwerk responses
  page.on('response', response => {
    const url = response.url();
    if (url.includes('/tradingview/') && url.includes('data') && response.status() === 200) {
      console.log(`✓ Data loaded: ${url.substring(0, 80)}...`);
    }
  });
  
  // Log belangrijke console error berichten
  page.on('console', msg => {
    if (msg.type() === 'error' || msg.text().includes('error') || msg.text().includes('Error')) {
      console.log(`Page error: ${msg.text().substring(0, 100)}...`);
    }
  });
  
  // Blokkeer niet-essentiële resources voor betere performance
  await page.route('**/*.{gif,svg,ttf,woff2,mp4,webm,mp3,ogg,pdf,map}', route => {
    route.abort();
  });
}

// Helper functie: cleanup resources
function cleanup(browser, page, context) {
  (async () => {
    try {
      if (page) await page.close().catch(() => {});
      if (context) await context.close().catch(() => {});
      if (browser === browserInstance) {
        browserInstance = null;
        await browser.close().catch(() => {});
      }
    } catch (e) {
      console.error('Error during cleanup:', e);
    }
  })();
}
