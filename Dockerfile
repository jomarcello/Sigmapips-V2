# Gebruik een specifieke Node.js versie
FROM node:18-slim

# Installeer Python eerst
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    python3-venv \
    && if [ ! -e /usr/bin/python ]; then ln -s /usr/bin/python3 /usr/bin/python; fi \
    && if [ ! -e /usr/bin/pip ]; then ln -s /usr/bin/pip3 /usr/bin/pip; fi

# Installeer system dependencies voor Selenium
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
    chromium \
    chromium-driver \
    xvfb \
    libgconf-2-4 \
    libnss3 \
    libnspr4 \
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
    libgcc-s1 \
    libstdc++6 \
    libx11-6 \
    libxcb1 \
    libxext6 \
    libxcursor1 \
    libxi6 \
    libxtst6 \
    libgtk-3-0 \
    python3-tk \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Set up Chromium environment variables
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV DISPLAY=:99

# Maak app directory
WORKDIR /app

# Maak een virtuele omgeving en activeer deze
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Maak een requirements.txt bestand
COPY requirements.txt .

# Installeer dependencies in de virtuele omgeving
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
