FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    firefox-esr \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install geckodriver
RUN wget https://github.com/mozilla/geckodriver/releases/download/v0.32.0/geckodriver-v0.32.0-linux64.tar.gz \
    && tar -xvzf geckodriver-v0.32.0-linux64.tar.gz \
    && chmod +x geckodriver \
    && mv geckodriver /usr/local/bin/ \
    && rm geckodriver-v0.32.0-linux64.tar.gz

# Set up app directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Set environment variables
ENV PYTHONPATH=/app
ENV PORT=8080
ENV MOZ_HEADLESS=1

# Run the app
CMD ["uvicorn", "trading_bot.main:app", "--host", "0.0.0.0", "--port", "8080"]
