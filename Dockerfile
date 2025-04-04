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

# Gebruik Chromium in plaats van Chrome (werkt op ARM en x86)
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Installeer de nieuwste beschikbare ChromeDriver versie (voor Chrome 123)
# Chrome 134 is te nieuw, dus we gebruiken de laatste beschikbare versie
RUN echo "Using chromedriver from Chromium package" \
    && ln -sf /usr/bin/chromedriver /usr/local/bin/chromedriver

# Set up Chrome environment variables
ENV CHROME_BIN=/usr/bin/chromium
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
RUN pip install --no-cache-dir webdriver-manager==3.8.6

# Installeer Playwright browsers voor Python
RUN playwright install chromium

# Installeer Playwright voor Node.js en de browsers
RUN npm install -g playwright @playwright/test
RUN npm install -g playwright-core
RUN npx playwright install chromium

# Maak directories voor data opslag
RUN mkdir -p /app/selenium_data
RUN mkdir -p /app/playwright_data
RUN chmod -R 777 /app/selenium_data
RUN chmod -R 777 /app/playwright_data

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
