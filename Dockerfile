# Gebruik een specifieke Python versie die beter werkt met Supabase
FROM python:3.11-slim

WORKDIR /app

# Installeer system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Kopieer requirements eerst (voor betere caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopieer de rest van de code
COPY . .

# Maak logs directory
RUN mkdir -p logs

# Start de applicatie
CMD ["python", "-m", "trading_bot.test_services"] 