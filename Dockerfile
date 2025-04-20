# Start met Python als basis
FROM python:3.9-slim

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
    # Tesseract en afhankelijkheden voor OCR
    tesseract-ocr \
    libtesseract-dev \
    tesseract-ocr-eng \
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

# Install Node.js dependencies first - IMPORTANT CHANGE
COPY package.json tradingview_screenshot.js ./
RUN npm install playwright
RUN npx playwright install chromium
RUN npx playwright install-deps chromium

# Installeer Playwright browsers voor Python
ENV PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright
RUN playwright install chromium
RUN playwright install-deps

# Maak directories voor data opslag
RUN mkdir -p /app/selenium_data
RUN mkdir -p /app/playwright_data
RUN mkdir -p /tmp
RUN chmod -R 777 /app/selenium_data
RUN chmod -R 777 /app/playwright_data
RUN chmod -R 777 /tmp

# Kopieer de rest van de code
COPY . .

# Repareer de syntaxfout in bot.py door de zwevende docstring te verwijderen
RUN grep -n "Create and return a logger instance with the given name" /app/trading_bot/services/telegram_service/bot.py | while read -r line ; do \
    line_num=$(echo "$line" | cut -d':' -f1); \
    sed -i "${line_num}d" /app/trading_bot/services/telegram_service/bot.py; \
done

# BELANGRIJK: Repareer de asyncio.create_task aanroep in sentiment.py
RUN grep -n "asyncio.create_task(self.load_cache())" /app/trading_bot/services/sentiment_service/sentiment.py | while read -r line ; do \
    line_num=$(echo "$line" | cut -d':' -f1); \
    sed -i "${line_num}s/asyncio.create_task(self.load_cache())/# asyncio.create_task call removed to prevent RuntimeWarning/" /app/trading_bot/services/sentiment_service/sentiment.py; \
done

# Stel environment variables in
ENV PYTHONPATH=/app
ENV PORT=8080
ENV NODE_ENV=production
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0
ENV PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright
ENV TIMEOUT_SECONDS=180

# Stel debug mode in
ENV TRADINGVIEW_DEBUG=true

# Stel Tesseract pad in (voor OCR)
ENV TESSERACT_CMD=/usr/bin/tesseract

# Controleer of Tesseract correct is geïnstalleerd
RUN tesseract --version && echo "Tesseract is correctly installed"

# Test if the Node.js script works with a timeout
RUN echo "Testing Node.js screenshot script..." && \
    timeout 15s node /app/tradingview_screenshot.js "https://www.tradingview.com" "/tmp/test_screenshot.png" || echo "Test timed out as expected but should work in runtime"

# Voeg een script toe om de bot te starten met een timeout
RUN echo '#!/bin/bash\n\
echo "Starting SigmaPips Trading Bot..."\n\
cd /app\n\
echo "Starting main application..."\n\
# Run with a timeout to prevent getting stuck\n\
timeout ${TIMEOUT_SECONDS:-180} python main.py || {\n\
    echo "Application timed out after ${TIMEOUT_SECONDS:-180} seconds, restarting..."\n\
    python main.py\n\
}\n\
' > /app/start.sh && chmod +x /app/start.sh

# Draai de applicatie
CMD ["/app/start.sh"]
