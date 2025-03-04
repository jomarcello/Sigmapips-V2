# Gebruik een specifieke Python versie
FROM python:3.11-slim

# Installeer system dependencies voor zowel Chromium als Playwright
RUN apt-get update && apt-get install -y \
    wget \
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
    && rm -rf /var/lib/apt/lists/*

# Set up Chrome environment variables
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV DISPLAY=:99

# Maak app directory
WORKDIR /app

# Kopieer requirements eerst (voor betere caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Installeer Playwright en browsers
RUN pip install playwright && playwright install chromium

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
