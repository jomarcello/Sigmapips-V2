# Core packages
python-telegram-bot>=20.0
aiohttp==3.9.5
python-dotenv>=1.0.0
httpx==0.24.1
stripe>=5.4.0
tenacity>=8.2.3  # For robust retry mechanisms
fastapi>=0.95.0
uvicorn[standard]>=0.21.1

# Database
supabase==1.1.1
redis==5.0.1

# Chart generation
matplotlib>=3.7.1
pandas>=2.0.0
mplfinance>=0.12.9b0
numpy>=1.24.2
tradingview-ta>=3.3.0
yahoo_fin>=0.8.9  # Yahoo Finance data provider
requests_html>=0.10.0  # Required by yahoo_fin
yfinance==0.2.56  # Specific version to ensure compatibility (proven to work locally)

# API integrations
# python-binance>=1.0.17  # Optionele Binance API client (uncomment indien nodig)

# For logging and debugging
python-json-logger==2.0.7

# Browser automation
selenium==4.10.0
pillow
webdriver-manager==3.8.6
playwright==1.40.0

# OCR processing
# Using OCR.space API instead of local Tesseract
# pytesseract>=0.3.13
google-cloud-vision==3.4.4  # For Google Cloud Vision API

# Data fetching
lxml
beautifulsoup4==4.12.2  # Voor Investing Calendar
arrow==1.3.0  # Voor Investing Calendar

# Vector database
pinecone-client
requests>=2.31.0
urllib3>=2.0.7

# AI Services
# Required dependencies for natural language processing and sentiment analysis
tavily-python==0.2.2  # for web search via Tavily API - REQUIRED for sentiment analysis

# Added from the code block
twelvedata>=1.2.10

# Added for Telegram bot functionality
aiogram==2.25.2
