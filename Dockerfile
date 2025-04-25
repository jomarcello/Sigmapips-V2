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

# Kopieer alleen de dependency bestanden
COPY requirements.txt .
COPY docker_setup.sh .

# Maak het setup-script uitvoerbaar
RUN chmod +x docker_setup.sh

# Draai het setup-script om alle dependencies te installeren
RUN ./docker_setup.sh

# Kopieer de rest van de app
COPY . .

# Poort voor FastAPI
EXPOSE 8000

# Start de applicatie
CMD ["python", "-m", "trading_bot.main"]
