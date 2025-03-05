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

# Kopieer requirements eerst (voor betere caching)
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

# Installeer Puppeteer globaal
RUN npm install -g puppeteer@19.7.0 --unsafe-perm=true

# Stel Puppeteer cache directory in
ENV PUPPETEER_CACHE_DIR=/app/.cache/puppeteer

# Kopieer het Puppeteer setup script
COPY setup_puppeteer.js /app/setup_puppeteer.js

# Voer het script uit om te controleren of Puppeteer werkt
RUN node /app/setup_puppeteer.js

# Kopieer de rest van de code
COPY . .

# Stel environment variables in
ENV PYTHONPATH=/app
ENV PORT=8080

# Stel TradingView en 2Captcha credentials in
ENV TRADINGVIEW_USERNAME=JovanniMT
ENV TRADINGVIEW_PASSWORD=JmT!102710!!
ENV TWOCAPTCHA_API_KEY=442b77082098300c2d00291e4a99372f

# Stel debug mode in
ENV TRADINGVIEW_DEBUG=true

# Start Xvfb en de applicatie
CMD Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 & \
    uvicorn trading_bot.main:app --host 0.0.0.0 --port 8080
