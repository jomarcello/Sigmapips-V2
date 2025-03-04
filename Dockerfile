# Gebruik een specifieke Python versie
FROM node:18-slim

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
    python3-tk \
    python3-dev \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Set up Chrome environment variables
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV DISPLAY=:99

# Maak app directory
WORKDIR /app

# Kopieer requirements eerst (voor betere caching)
COPY requirements.txt .

# Installeer dependencies in kleinere groepen om problemen te voorkomen
RUN pip install --no-cache-dir fastapi==0.109.0 python-telegram-bot==20.3 uvicorn==0.27.0 python-dotenv==1.0.0
RUN pip install --no-cache-dir aiohttp==3.9.3 twocaptcha==0.0.1 aiofiles==23.2.1
RUN pip install --no-cache-dir supabase==1.2.0 redis==5.0.1
RUN pip install --no-cache-dir selenium==4.10.0 pillow==10.2.0 webdriver-manager==3.8.6
RUN pip install --no-cache-dir matplotlib==3.7.1 pandas==2.0.1 numpy==1.24.3 mplfinance==0.12.9b0 yfinance==0.2.35
RUN pip install --no-cache-dir python-multipart==0.0.6 pinecone-client requests
RUN pip install --no-cache-dir pyppeteer==1.0.2

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

# Installeer Puppeteer globaal
RUN npm install -g puppeteer@19.7.0 --unsafe-perm=true

# Stel Puppeteer cache directory in
ENV PUPPETEER_CACHE_DIR=/app/.cache/puppeteer

# Start Xvfb en de applicatie
CMD Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 & \
    uvicorn trading_bot.main:app --host 0.0.0.0 --port 8080

# Installeer Python
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    && ln -s /usr/bin/python3 /usr/bin/python \
    && ln -s /usr/bin/pip3 /usr/bin/pip

# Maak pip.conf om playwright te blokkeren
RUN mkdir -p /root/.config/pip
RUN echo "[global]" > /root/.config/pip/pip.conf
RUN echo "no-dependencies = yes" >> /root/.config/pip/pip.conf
