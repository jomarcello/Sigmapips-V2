// Geoptimaliseerde versie voor betrouwbare screenshots
const fs = require('fs');
const { execSync } = require('child_process');
const { chromium } = require('playwright');
const path = require('path');
const os = require('os');

// Configuratie
const VIEWPORT_WIDTH = 1280;
const VIEWPORT_HEIGHT = 720;
const DEFAULT_TIMEOUT = 30000;
const ELEMENT_TIMEOUT = 15000;
const MAX_WAIT_FOR_CHART = 30000;
const BROWSER_ARGS = [
  '--disable-dev-shm-usage',
  '--disable-setuid-sandbox',
  '--no-sandbox',
  '--disable-web-security',
  '--disable-features=IsolateOrigins,site-per-process',
  '--disable-site-isolation-trials',
  '--disable-gpu',
  '--disable-accelerated-2d-canvas',
  '--disable-accelerated-video-decode',
  '--disable-infobars',
  '--disable-extensions'
];

// Globale browser instance voor hergebruik
let globalBrowser = null;
let browserLastUsed = Date.now();
const BROWSER_MAX_LIFETIME = 15 * 60 * 1000; // 15 minuten

// Haal de argumenten op
const url = process.argv[2];
const outputPath = process.argv[3];
const sessionId = process.argv[4] || '';
const fullscreen = process.argv[5] === 'fullscreen';

// Start performance meting
const startTime = Date.now();
console.log(`🚀 Starting screenshot process for ${url}`);
if (sessionId) console.log(`🔑 Session ID: ${sessionId.substring(0, 5)}...`);

// Verbeterde lijst van mogelijke chart selectors, in volgorde van prioriteit
const CHART_SELECTORS = [
  '.chart-container',
  '.chart-markup-table',
  '.tv-chart-container',
  '.layout__area--center',
  '.chart-container-border',
  '.js-chart-container',
  '.chart-gui-wrapper',
  '.chart-markup-table.pane'
];

// Helper functie: wacht tot een van de selectors zichtbaar is
async function waitForAnySelector(page, selectors, timeout = 15000) {
  console.log(`👀 Waiting for chart elements (max ${timeout}ms)...`);
  const startWaitTime = Date.now();
  
  try {
    for (const selector of selectors) {
      try {
        // Gebruik een korte timeout per selector
        const element = await page.waitForSelector(selector, {
          state: 'attached',
          timeout: timeout / selectors.length
        });
        
        if (element) {
          console.log(`✓ Found chart element "${selector}" in ${Date.now() - startWaitTime}ms`);
          return selector;
        }
      } catch (e) {
        // Skip naar de volgende selector
      }
    }
    
    console.log(`⚠️ No chart elements found in ${Date.now() - startWaitTime}ms, continuing...`);
    return null;
  } catch (e) {
    console.log(`⚠️ Error waiting for selectors: ${e.message}`);
    return null;
  }
}

// Functie om meerdere Escape-toetsen te simuleren voor hardnekkige popups
async function dismissPopups(page, count = 5) {
  for (let i = 0; i < count; i++) {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(100);
  }
}

/**
 * Hoofdfunctie voor het nemen van een screenshot
 */
async function takeScreenshot() {
  // Controleer command line parameters
  const args = process.argv.slice(2);
  if (args.length < 2) {
    console.error('Gebruik: node screenshot.js <url> <output_path> [session_id] [fullscreen]');
    process.exit(1);
  }
  
  const url = args[0];
  const outputPath = args[1];
  const sessionId = args[2] || '';
  const fullscreen = args.includes('fullscreen');
  
  // Maak de output directory indien nodig
  const outputDir = path.dirname(outputPath);
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }
  
  let browser = null;
  let context = null;
  let page = null;
  
  try {
    // Gebruik globale browser of maak nieuwe aan
    browser = await getBrowserInstance();
    browserLastUsed = Date.now();
    
    // Maak context en pagina
    context = await createBrowserContext(browser, sessionId);
    page = await context.newPage();
    
    // Configureer viewport
    await page.setViewportSize({ 
      width: VIEWPORT_WIDTH, 
      height: VIEWPORT_HEIGHT 
    });
    
    // Verbeterde foutafhandeling en logging voor netwerkrequests
    setupNetworkLogging(page);
    
    // TradingView-specifieke cookie indien sessie ID opgegeven
    if (sessionId && sessionId.length > 0) {
      await setupTradingViewSession(page, sessionId);
    }
    
    // Ga naar de URL met timeout
    console.log(`Navigeren naar ${url}...`);
    await page.goto(url, { 
      timeout: DEFAULT_TIMEOUT,
      waitUntil: 'networkidle'
    });
    
    // Sluit dialoogvensters (cookies, updates, etc.)
    await closePopups(page);
    
    // Wacht tot de chart geladen is
    await waitForChart(page);
    
    // Wacht extra tijd voor TradingView chart om data te laden
    console.log('Wachten op dataverwerking...');
    await page.waitForTimeout(5000);
    
    // Pas mogelijk fullscreen toe
    if (fullscreen) {
      await enterFullscreenMode(page);
    }
    
    // Wacht kort voor stabilisatie
    await page.waitForTimeout(2000);
    
    // Controleer of chart daadwerkelijk data bevat
    const hasChartData = await page.evaluate(() => {
      // Controleer aanwezigheid van prijsbalken of andere grafiek-elementen
      const priceElements = document.querySelectorAll('.price-axis');
      const chartLines = document.querySelectorAll('path[stroke]');
      const candlesticks = document.querySelectorAll('.chart-markup-table rect');
      
      return priceElements.length > 0 && (chartLines.length > 10 || candlesticks.length > 10);
    });
    
    if (!hasChartData) {
      console.log('⚠️ Chart lijkt geen data te bevatten, wacht langer...');
      await page.waitForTimeout(10000);
    }
    
    // Verwijder overlays die de chart kunnen blokkeren
    await page.evaluate(() => {
      // Verwijder alle popups, dialogen en advertisements die de chart kunnen bedekken
      const elementsToRemove = document.querySelectorAll('.tv-dialog, .tv-alert, .tv-notification, .banner-container');
      elementsToRemove.forEach(el => el.remove());
    });
    
    // Neem de screenshot
    console.log('Screenshot nemen...');
    await page.screenshot({ 
      path: outputPath,
      fullPage: false,
      timeout: DEFAULT_TIMEOUT
    });
    
    console.log(`Screenshot gemaakt: ${outputPath}`);
    
  } catch (error) {
    console.error(`Error bij maken screenshot: ${error.message}`);
    process.exitCode = 1;
    
    // Sluit de browser bij ernstige fouten
    if (error.message.includes('timeout') || 
        error.message.includes('net::ERR') ||
        error.message.includes('Navigation')) {
      console.error('Ernstige fout: Browser wordt afgesloten');
      await closeBrowser(browser);
      globalBrowser = null;
    }
    
  } finally {
    // Sluit pagina en context, maar houd browser open voor hergebruik
    try {
      if (page) await page.close();
      if (context) await context.close();
    } catch (err) {
      console.error(`Error bij opruimen resources: ${err.message}`);
    }
    
    // Controleer of we browser moeten sluiten bij inactiviteit
    checkBrowserLifetime();
  }
}

/**
 * Hergebruik bestaande browser of maak een nieuwe aan
 */
async function getBrowserInstance() {
  // Controleer of bestaande browser geldig is en niet te oud
  if (globalBrowser) {
    try {
      // Test of browser nog steeds bruikbaar is
      await globalBrowser.contexts();
      
      const browserAge = Date.now() - browserLastUsed;
      if (browserAge > BROWSER_MAX_LIFETIME) {
        console.log(`Browser te oud (${Math.round(browserAge/1000)}s), nieuwe starten...`);
        await closeBrowser(globalBrowser);
        globalBrowser = null;
      } else {
        console.log('Bestaande browser hergebruiken...');
        return globalBrowser;
      }
    } catch (err) {
      console.log('Bestaande browser niet bruikbaar, nieuwe starten...');
      globalBrowser = null;
    }
  }
  
  // Start nieuwe browser
  console.log('Nieuwe browser starten...');
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pw-chrome-'));
  
  globalBrowser = await chromium.launch({
    headless: true,
    args: BROWSER_ARGS,
    userDataDir: tmpDir,
    downloadsPath: tmpDir,
    timeout: DEFAULT_TIMEOUT,
    ignoreDefaultArgs: ['--enable-automation'],
    ignoreHTTPSErrors: true
  });
  
  return globalBrowser;
}

/**
 * Maak browser context met juiste instellingen
 */
async function createBrowserContext(browser, sessionId) {
  return await browser.newContext({
    viewport: { width: VIEWPORT_WIDTH, height: VIEWPORT_HEIGHT },
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.71 Safari/537.36',
    locale: 'en-US',
    timezoneId: 'Europe/Amsterdam',
    acceptDownloads: false,
  });
}

/**
 * Controleer en sluit browser indien inactief
 */
function checkBrowserLifetime() {
  if (globalBrowser) {
    const browserAge = Date.now() - browserLastUsed;
    if (browserAge > 60 * 1000) { // 1 minuut
      console.log(`Browser inactief voor ${Math.round(browserAge/1000)}s, sluiten...`);
      closeBrowser(globalBrowser).catch(console.error);
      globalBrowser = null;
    }
  }
}

/**
 * Sluit browser op betrouwbare manier
 */
async function closeBrowser(browser) {
  if (!browser) return;
  
  try {
    await browser.close();
  } catch (err) {
    console.error(`Error bij sluiten browser: ${err.message}`);
    // Als normaal sluiten faalt, forceer afsluiten
    process.exit(1);
  }
}

/**
 * Configureer TradingView sessie met cookies
 */
async function setupTradingViewSession(page, sessionId) {
  if (sessionId && sessionId.length > 0) {
    await page.context().addCookies([
      {
        name: 'sessionid',
        value: sessionId,
        domain: '.tradingview.com',
        path: '/',
      }
    ]);
    // Voeg extra cookie toe voor TradingView authenticatie
    await page.context().addCookies([
      {
        name: 'tv_authed',
        value: '1',
        domain: '.tradingview.com',
        path: '/',
      }
    ]);
  }
}

/**
 * Configureer netwerk logging voor debugging
 */
function setupNetworkLogging(page) {
  // Log navigatie-events
  page.on('requestfailed', request => {
    const url = request.url();
    if (url.includes('tradingview.com') && !url.includes('.css') && !url.includes('.png')) {
      console.error(`Request mislukt: ${url} - ${request.failure().errorText}`);
    }
  });
  
  // Blokkeer niet-essentiële requests voor snellere laadtijd
  page.route('**/*.{png,jpg,jpeg,gif,svg,woff,woff2,mp4,webm,mp3,pdf}', route => {
    // Sta afbeeldingen toe maar blokkeer andere grote media bestanden
    if (route.request().resourceType() === 'image') {
      route.continue();
    } else {
      route.abort();
    }
  });
  
  // Log succesvolle data requests
  page.on('response', response => {
    const url = response.url();
    if (url.includes('tradingview.com/tradingview/') && url.includes('data')) {
      console.log(`✓ Data request: ${url.substring(0, 100)}...`);
    }
  });
  
  // Log console berichten van de pagina
  page.on('console', msg => {
    const text = msg.text();
    if (text.includes('error') || text.includes('Error') || text.includes('Exception')) {
      console.error(`Pagina console: ${text}`);
    }
  });
}

/**
 * Sluit bekende TradingView popups
 */
async function closePopups(page) {
  try {
    // Gebruik eerst keyboard methode
    await dismissPopups(page, 5);
    
    // Lijst met mogelijke popups
    const popupSelectors = [
      'div[data-role="toast-container"] button',
      'div[data-name="popup-dialog"] button[data-name="dialog-close"]',
      'div.toast-wrapper button',
      'div.tv-dialog button.close',
      'div.tv-dialog__close',
      'button[data-dialog-action="cancel"]',
      'button[data-dialog-action="close"]',
      'button.js-dialog__close',
      // Extra selectors voor nieuwere TradingView popups
      '[data-name="header-toolbar-close"]',
      '[data-name="close-button"]',
      '.close-button',
      '.tv-dialog__close-button',
      '.tv-alert__close-button'
    ];
    
    for (const selector of popupSelectors) {
      // Zoek en klik op alle matching popup knoppen
      await page.$$eval(selector, buttons => {
        buttons.forEach(button => button.click());
      }).catch(() => {});
    }
    
    // Accept cookies popup (TradingView specifiek)
    await page.locator('button[data-name="accept-cookies-button"]')
      .click({ timeout: 2000 })
      .catch(() => {});
      
    // Alternatieve cookie popup sluiten
    await page.locator('button:has-text("Accept all cookies")')
      .click({ timeout: 2000 })
      .catch(() => {});
      
    // Sluit ads en marketing popups
    await page.evaluate(() => {
      // Verwijder banner containers
      document.querySelectorAll('.banner-container').forEach(el => el.remove());
      document.querySelectorAll('[class*="popup"], [class*="modal"], [class*="toast"]').forEach(el => {
        if (el.style) el.style.display = 'none';
      });
    });
      
  } catch (error) {
    console.log('Geen popups gevonden of error bij sluiten popups');
  }
}

/**
 * Wacht tot de TradingView chart volledig geladen is
 */
async function waitForChart(page) {
  try {
    // Detecteer wanneer de chart zichtbaar is
    console.log('Wachten op chart...');
    
    // Gebruik Promise.race voor timeout
    const chartSelector = await waitForAnySelector(page, CHART_SELECTORS, MAX_WAIT_FOR_CHART);
    
    if (!chartSelector) {
      console.log('Geen specifieke chart-element gevonden, doorgaan...');
    }
    
    // Wacht tot prijsdata zichtbaar is
    await Promise.race([
      page.waitForSelector('.price-axis', { 
        state: 'visible',
        timeout: ELEMENT_TIMEOUT
      }),
      page.waitForSelector('path[stroke]', {
        state: 'visible',
        timeout: ELEMENT_TIMEOUT
      })
    ]).catch(() => console.log('Geen prijsdata gevonden, doorgaan...'));
    
    // Wacht extra tijd voor data om te laden
    await page.waitForTimeout(5000);
    
    // Controleer of er een laadspinner is en wacht tot deze verdwijnt
    const loadingSpinner = await page.$('div.loading-indicator, .tv-spinner');
    if (loadingSpinner) {
      console.log('Wachten tot spinner verdwijnt...');
      await loadingSpinner.waitForElementState('hidden', { timeout: ELEMENT_TIMEOUT });
    }
    
    // Uitvoeren van extra acties om ervoor te zorgen dat grafieken correct worden weergegeven
    await page.evaluate(() => {
      // Dispatchen van een resize event kan helpen bij het laden van grafiek-elementen
      window.dispatchEvent(new Event('resize'));
      
      // Schakel automatisch bijwerken in
      const autoUpdateButton = document.querySelector('button[data-name="toggle-auto-update"]');
      if (autoUpdateButton) autoUpdateButton.click();
    });
    
    console.log('Chart geladen!');
  } catch (error) {
    console.error(`Error bij wachten op chart: ${error.message}`);
    // Doe toch een poging om screenshot te maken
  }
}

/**
 * Zet TradingView in fullscreen mode
 */
async function enterFullscreenMode(page) {
  try {
    console.log('Activeren fullscreen modus...');
    
    // Methode 1: Verberg onnodige UI elementen via CSS
    await page.evaluate(() => {
      // Verberg dialogen, toolbars, etc.
      const style = document.createElement('style');
      style.textContent = `
        .header-chart-panel, .tv-side-toolbar, .bottom-widgetbar-content.backtesting {
          display: none !important;
        }
        .chart-container, .chart-markup-table, .chart-container-border {
          height: 100% !important;
          width: 100% !important;
        }
      `;
      document.head.appendChild(style);
    });
    
    // Methode 2: Via element selectie en klik
    await page.evaluate(() => {
      // Zoek naar fullscreen knop of probeer programmatisch fullscreen
      const fullscreenButton = document.querySelector('button[data-name="full-screen-button"]');
      if (fullscreenButton) {
        fullscreenButton.click();
      } else if (document.documentElement.requestFullscreen) {
        document.documentElement.requestFullscreen().catch(() => {});
      }
      
      // Zorg ervoor dat de grafiek op maximale grootte wordt weergegeven
      const chartContainer = document.querySelector('.chart-container, .chart-markup-table');
      if (chartContainer) {
        chartContainer.style.width = '100vw';
        chartContainer.style.height = '100vh';
      }
    });
    
    await page.waitForTimeout(2000);
  } catch (error) {
    console.log('Kon fullscreen modus niet activeren, doorgaan met normale screenshot');
  }
}

// Start het script
takeScreenshot().catch(error => {
  console.error(`Fatale fout: ${error.message}`);
  process.exit(1);
}); 
