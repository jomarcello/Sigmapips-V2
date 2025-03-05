const { chromium } = require('playwright-extra');
const stealth = require('puppeteer-extra-plugin-stealth')();
const RecaptchaPlugin = require('puppeteer-extra-plugin-recaptcha');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

// Voeg de stealth plugin toe
chromium.use(stealth);

// Voeg de recaptcha plugin toe
chromium.use(
  RecaptchaPlugin({
    provider: {
      id: '2captcha',
      token: process.env.TWOCAPTCHA_API_KEY || '442b77082098300c2d00291e4a99372f'
    },
    visualFeedback: true
  })
);

// Configuratie
const config = {
  username: process.env.TRADINGVIEW_USERNAME || 'JovanniMT',
  password: process.env.TRADINGVIEW_PASSWORD || 'JmT!102710!!',
  outputDir: path.join(__dirname, 'screenshots'),
  symbols: process.argv[2] ? [process.argv[2]] : ['EURUSD', 'GBPUSD', 'BTCUSD'],
  timeframes: process.argv[3] ? [process.argv[3]] : ['1h', '4h', '1d']
};

// Zorg ervoor dat de output directory bestaat
if (!fs.existsSync(config.outputDir)) {
  fs.mkdirSync(config.outputDir, { recursive: true });
}

async function takeScreenshot(page, symbol, timeframe) {
  console.log(`Taking screenshot for ${symbol} on ${timeframe} timeframe`);
  
  // Navigeer naar de chart pagina
  await page.goto(`https://www.tradingview.com/chart/?symbol=${symbol}`, { waitUntil: 'networkidle' });
  
  // Wacht tot de chart is geladen
  await page.waitForSelector('.chart-markup-table', { timeout: 30000 });
  
  // Verander de timeframe indien nodig
  if (timeframe !== '1d') { // Standaard is 1d
    console.log(`Changing timeframe to ${timeframe}`);
    
    // Klik op de timeframe selector
    await page.click('.chart-toolbar-timeframes button');
    
    // Wacht op het dropdown menu
    await page.waitForSelector('.menu-T1RzLuj3 .item-RhC5uhZw', { timeout: 10000 });
    
    // Zoek en klik op de juiste timeframe
    const timeframeItems = await page.$$('.menu-T1RzLuj3 .item-RhC5uhZw');
    let timeframeFound = false;
    
    for (const item of timeframeItems) {
      const text = await item.textContent();
      if (text.includes(timeframe.toUpperCase())) {
        await item.click();
        timeframeFound = true;
        break;
      }
    }
    
    if (!timeframeFound) {
      console.warn(`Timeframe ${timeframe} not found, using default`);
    }
    
    // Wacht tot de chart is bijgewerkt
    await page.waitForTimeout(3000);
  }
  
  // Verberg UI elementen voor een schonere screenshot
  await page.evaluate(() => {
    // Verberg header, footer, sidebar, etc.
    const elementsToHide = [
      '.header-KN-Kpxs-',
      '.drawingToolbar-2_so5tMw',
      '.chart-controls-bar',
      '.bottom-widgetbar-content.backtesting',
      '.control-bar',
      '.tv-side-toolbar'
    ];
    
    elementsToHide.forEach(selector => {
      const elements = document.querySelectorAll(selector);
      elements.forEach(el => {
        if (el) el.style.display = 'none';
      });
    });
  });
  
  // Wacht even om zeker te zijn dat alles is bijgewerkt
  await page.waitForTimeout(1000);
  
  // Neem de screenshot
  const screenshotPath = path.join(config.outputDir, `${symbol}_${timeframe}.png`);
  const screenshot = await page.screenshot({ path: screenshotPath, fullPage: false });
  
  console.log(`Screenshot saved to ${screenshotPath}`);
  return screenshot;
}

async function run() {
  console.log('Starting TradingView automation');
  
  const browser = await chromium.launch({
    headless: false, // Zet op true voor productie
    args: [
      '--no-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--window-size=1920,1080'
    ]
  });
  
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
  });
  
  const page = await context.newPage();
  
  try {
    // Login op TradingView
    console.log('Navigating to TradingView login page');
    await page.goto('https://www.tradingview.com/#signin', { waitUntil: 'networkidle' });
    
    // Klik op de email login optie
    console.log('Clicking email login option');
    await page.click('span.js-show-email');
    
    // Vul inloggegevens in
    console.log('Filling login credentials');
    await page.fill('[name="username"]', config.username);
    await page.fill('[name="password"]', config.password);
    
    // Klik op de login knop
    console.log('Submitting login form');
    await page.click('[type="submit"]');
    
    // Wacht tot we zijn ingelogd
    try {
      await page.waitForNavigation({ timeout: 30000 });
      console.log('Successfully logged in');
    } catch (error) {
      console.log('Navigation timeout, checking for CAPTCHA');
      
      // Controleer op CAPTCHA
      const captchaExists = await page.$$eval('iframe[src*="recaptcha"]', frames => frames.length > 0);
      
      if (captchaExists) {
        console.log('CAPTCHA detected, solving...');
        await page.solveRecaptchas();
        
        // Probeer opnieuw in te loggen na CAPTCHA
        await page.click('[type="submit"]');
        await page.waitForNavigation({ timeout: 30000 });
      }
    }
    
    // Neem screenshots voor elke combinatie van symbool en timeframe
    const results = {};
    
    for (const symbol of config.symbols) {
      results[symbol] = {};
      
      for (const timeframe of config.timeframes) {
        try {
          const screenshot = await takeScreenshot(page, symbol, timeframe);
          results[symbol][timeframe] = screenshot;
        } catch (error) {
          console.error(`Error taking screenshot for ${symbol} ${timeframe}:`, error);
          results[symbol][timeframe] = null;
        }
      }
    }
    
    console.log('All screenshots completed');
    return results;
    
  } catch (error) {
    console.error('Error during automation:', error);
    throw error;
  } finally {
    // Sluit de browser
    await browser.close();
    console.log('Browser closed');
  }
}

// Voer het script uit als het direct wordt aangeroepen
if (require.main === module) {
  run()
    .then(() => {
      console.log('Script completed successfully');
      process.exit(0);
    })
    .catch(error => {
      console.error('Script failed:', error);
      process.exit(1);
    });
} else {
  // Exporteer de functie voor gebruik in andere scripts
  module.exports = { run, takeScreenshot }; 
