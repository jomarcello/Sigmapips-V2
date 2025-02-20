# Gebruik een specifieke Python versie
FROM python:3.11-slim

# Installeer system dependencies
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    xvfb \
    libgconf-2-4 \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

# Maak app directory
WORKDIR /app

# Kopieer requirements eerst (voor betere caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopieer de rest van de code
COPY . .

# Stel environment variables in
ENV PYTHONPATH=/app
ENV PORT=8080

# Start command
CMD ["uvicorn", "trading_bot.main:app", "--host", "0.0.0.0", "--port", "808"]
