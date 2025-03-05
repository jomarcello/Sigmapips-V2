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

# Installeer system dependencies voor zowel Chromium, Playwright als Selenium
# Voeg curl toe aan de lijst met dependencies
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

# Installeer Google Chrome (nieuwere versie dan Chromium)
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Installeer de juiste ChromeDriver versie die overeenkomt met Chrome
RUN CHROME_VERSION=$(google-chrome --version | awk '{print $3}' | cut -d. -f1) \
    && CHROMEDRIVER_VERSION=$(curl -s "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_$CHROME_VERSION") \
    && wget -q "https://chromedriver.storage.googleapis.com/$CHROMEDRIVER_VERSION/chromedriver_linux64.zip" \
    && unzip chromedriver_linux64.zip \
    && mv chromedriver /usr/local/bin/chromedriver \
    && chmod +x /usr/local/bin/chromedriver \
    && rm chromedriver_linux64.zip

# Set up Chrome environment variables
ENV CHROME_BIN=/usr/bin/google-chrome
ENV CHROMEDRIVER_PATH=/usr/local/bin/chromedriver
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

# Installeer Puppeteer globaal
RUN npm install -g puppeteer@19.7.0 --unsafe-perm=true

# Stel Puppeteer cache directory in
ENV PUPPETEER_CACHE_DIR=/app/.cache/puppeteer

# Maak directories voor data opslag
RUN mkdir -p /app/puppeteer_data
RUN mkdir -p /app/selenium_data
RUN chmod -R 777 /app/puppeteer_data /app/selenium_data

# Kopieer de rest van de code
COPY . .

# Stel environment variables in
ENV PYTHONPATH=/app
ENV PORT=8080

# Stel TradingView session ID in
ENV TRADINGVIEW_SESSION_ID=z90l85p2anlgdwfppsrdnnfantz48z1o

# Stel debug mode in
ENV TRADINGVIEW_DEBUG=true

# Start Xvfb en de applicatie
CMD Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 & \
    uvicorn trading_bot.main:app --host 0.0.0.0 --port 8080
