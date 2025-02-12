FROM python:3.11-slim

# Kritieke instellingen voor imports
ENV PYTHONPATH="/app:/app/trading_bot"
ENV PORT=8080

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Create logs directory
RUN mkdir -p logs

# Start de main applicatie met module flag
CMD python -m uvicorn trading_bot.main:app --host 0.0.0.0 --port $PORT
