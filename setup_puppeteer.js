console.log("Installing Puppeteer...");
const puppeteer = require("puppeteer");

(async () => {
  try {
    // Test of Puppeteer werkt
    const browser = await puppeteer.launch({
      headless: true,
      args: ["--no-sandbox", "--disable-dev-shm-usage"]
    });
    console.log("Puppeteer installed and working correctly");
    await browser.close();
  } catch (error) {
    console.error("Error testing Puppeteer:", error);
    process.exit(1);
  }
})();
