# Start met Python als basis
FROM python:3.11-slim

# Installeer Node.js
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    && curl -sL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Installeer Chrome en benodigde dependencies
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    xvfb \
    libxi6 \
    libgconf-2-4 \
    default-jdk \
    libglib2.0-0 \
    libnss3 \
    libgdk-pixbuf2.0-0 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxss1 \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libfontconfig1 \
    fonts-liberation \
    libappindicator3-1 \
    xdg-utils \
    python3-tk \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Installeer Chrome
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Installeer een specifieke versie van ChromeDriver die compatibel is met Chrome
RUN wget -q "https://chromedriver.storage.googleapis.com/114.0.5735.90/chromedriver_linux64.zip" \
    && unzip chromedriver_linux64.zip \
    && mv chromedriver /usr/bin/chromedriver \
    && chmod +x /usr/bin/chromedriver \
    && rm chromedriver_linux64.zip

# Set up Chrome environment variables
ENV CHROME_BIN=/usr/bin/google-chrome
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV DISPLAY=:99

# Werkdirectory instellen
WORKDIR /app

# Maak een virtuele omgeving en activeer deze
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Kopieer requirements.txt en installeer dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Installeer Playwright browsers
RUN playwright install chromium

# Maak directories voor data opslag
RUN mkdir -p /app/selenium_data
RUN mkdir -p /app/playwright_data
RUN chmod -R 777 /app/selenium_data
RUN chmod -R 777 /app/playwright_data

# Installeer Puppeteer lokaal in plaats van globaal
WORKDIR /app/puppeteer
RUN npm init -y && \
    npm install puppeteer@19.7.0 --save && \
    npm install

# Maak het Puppeteer setup script
RUN echo 'console.log("Testing Puppeteer installation...");' > test_puppeteer.js && \
    echo 'const puppeteer = require("puppeteer");' >> test_puppeteer.js && \
    echo '(async () => {' >> test_puppeteer.js && \
    echo '  try {' >> test_puppeteer.js && \
    echo '    const browser = await puppeteer.launch({' >> test_puppeteer.js && \
    echo '      headless: true,' >> test_puppeteer.js && \
    echo '      args: ["--no-sandbox", "--disable-dev-shm-usage"]' >> test_puppeteer.js && \
    echo '    });' >> test_puppeteer.js && \
    echo '    console.log("Puppeteer is working correctly!");' >> test_puppeteer.js && \
    echo '    await browser.close();' >> test_puppeteer.js && \
    echo '  } catch (error) {' >> test_puppeteer.js && \
    echo '    console.error("Error testing Puppeteer:", error);' >> test_puppeteer.js && \
    echo '    process.exit(1);' >> test_puppeteer.js && \
    echo '  }' >> test_puppeteer.js && \
    echo '})();' >> test_puppeteer.js

# Test Puppeteer installatie
RUN node test_puppeteer.js

# Ga terug naar de hoofddirectory
WORKDIR /app

# Kopieer de rest van de code
COPY . .

# Stel environment variables in
ENV PYTHONPATH=/app
ENV PORT=8080

# Stel debug mode in
ENV TRADINGVIEW_DEBUG=true

# Start Xvfb en de applicatie
CMD Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 & \
    uvicorn trading_bot.main:app --host 0.0.0.0 --port 8080
