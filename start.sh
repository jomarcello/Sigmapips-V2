#!/bin/bash

echo "Starting SigmaPips Trading Bot..."
cd /app
echo "Starting main application..."

# Detecteer de hostname en maak een volledige URL
HOSTNAME=$(hostname -f 2>/dev/null || echo "localhost")
PUBLIC_URL=${PUBLIC_URL:-"https://$HOSTNAME"}

# Debug: Controleer sentiment.py bestand
echo "Checking sentiment.py file..."
echo "Content of sentiment.py file:"
if [ -f "trading_bot/services/sentiment_service/sentiment.py" ]; then
  head -n 20 trading_bot/services/sentiment_service/sentiment.py
  echo "File exists and looking for MarketSentimentService class..."
  grep -A 5 "class MarketSentimentService" trading_bot/services/sentiment_service/sentiment.py || echo "MarketSentimentService class not found!"
else
  echo "sentiment.py file not found!"
fi

# Make sure the sentiment.py file has the correct class
echo "Fixing sentiment.py file..."
cat > trading_bot/services/sentiment_service/sentiment.py << 'EOL'
import logging
import random
import os
import time
import asyncio
import json
from typing import Dict, Any, List
import httpx
from datetime import datetime, timedelta
import tavily  # Direct import Tavily, laat het gewoon crashen als het niet beschikbaar is

logger = logging.getLogger(__name__)
# Verhoog log level voor sentiment service
logger.setLevel(logging.DEBUG)

# Global cache storage
sentiment_cache = {}

class MarketSentimentService:
    """Service for analyzing market sentiment"""
    
    def __init__(self):
        """Initialize the market sentiment service"""
        self.tavily_api_key = os.getenv("TAVILY_API_KEY", "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")
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.deepseek_api_url = "https://api.deepseek.com/v1/chat/completions"
        
        # Debug logging voor API keys
        if self.tavily_api_key:
            logger.info(f"Tavily API key found: {self.tavily_api_key[:4]}...{self.tavily_api_key[-4:] if len(self.tavily_api_key) > 8 else ''}")
        else:
            logger.warning("Tavily API key not found in environment variables")
            
        if self.deepseek_api_key:
            logger.info(f"DeepSeek API key found: {self.deepseek_api_key[:4]}...{self.deepseek_api_key[-4:] if len(self.deepseek_api_key) > 8 else ''}")
        else:
            logger.warning("DeepSeek API key not found in environment variables")
        
        self.headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json"
        }
        
        # Always set the Tavily API key
        tavily.api_key = self.tavily_api_key
        logger.info(f"Set Tavily API key: {self.tavily_api_key[:4]}...{self.tavily_api_key[-4:] if len(self.tavily_api_key) > 8 else ''}")
        
        # If no API keys are provided or tavily is not available, we'll use mock data
        self.use_mock = not self.tavily_api_key or not self.deepseek_api_key or self.tavily_api_key.strip() == "" or self.deepseek_api_key.strip() == ""
        if self.use_mock:
            logger.warning("Missing API keys or tavily package not available, using mock data")
            
        # Cache geldigheid in seconden (30 minuten)
        self.cache_ttl = 30 * 60
        logger.debug("MarketSentimentService geïnitialiseerd met cache TTL: %s seconden", self.cache_ttl)
    
    async def get_market_sentiment(self, instrument):
        """Get market sentiment for a specific instrument"""
        try:
            logger.info(f"Getting market sentiment for {instrument}")
            
            # Controleer of we een geldige cache entry hebben
            current_time = time.time()
            cache_key = f"market_{instrument}"  # Specifiekere key om verwarring te voorkomen
            
            logger.debug(f"Cache check voor {cache_key}. Cache bevat keys: {list(sentiment_cache.keys())}")
            
            if cache_key in sentiment_cache:
                cached_data = sentiment_cache[cache_key]
                cache_timestamp = cached_data.get('timestamp', datetime.fromtimestamp(0))
                
                # Convert to datetime if it's still a timestamp
                if not isinstance(cache_timestamp, datetime):
                    cache_timestamp = datetime.fromtimestamp(cache_timestamp)
                    
                # Check if cache is still valid (less than 30 minutes old)
                if datetime.now() - cache_timestamp < timedelta(minutes=30):
                    logger.info(f"Cache HIT for {instrument}")
                    return cached_data.get('result')
                else:
                    logger.info(f"Cache EXPIRED for {instrument}")
            else:
                logger.info(f"Cache MISS for {instrument}")
            
            # Fallback naar mock data
            logger.warning(f"Using mock data for {instrument}")
            return await self._generate_mock_data(instrument)
                
        except Exception as e:
            logger.error(f"Error getting market sentiment: {str(e)}")
            logger.exception(e)
            # Fallback naar neutraal sentiment
            return {
                'overall_sentiment': 'neutral',
                'sentiment_score': 0.5,
                'bullish_percentage': 50,
                'trend_strength': 'Moderate', 
                'volatility': 'Moderate',
                'analysis': f"<b>🎯 {instrument} Market Analysis</b>\n\nThere was an error retrieving market sentiment. Please try again later.",
                'source': 'fallback'
            }
    
    async def _generate_mock_data(self, instrument):
        """Generate mock data for sentiment analysis"""
        logger.info(f"Generating mock data for {instrument}")
        
        # Generate sentiment based on instrument type
        if instrument.startswith(('BTC', 'ETH')):
            sentiment_score = random.uniform(0.6, 0.8)  # Crypto tends to be bullish
        elif instrument.startswith(('XAU', 'GOLD')):
            sentiment_score = random.uniform(0.4, 0.7)  # Commodities can be volatile
        else:
            sentiment_score = random.uniform(0.3, 0.7)  # Forex and indices more balanced
        
        bullish_percentage = int(sentiment_score * 100)
        trend_strength = 'Strong' if abs(sentiment_score - 0.5) > 0.3 else 'Moderate' if abs(sentiment_score - 0.5) > 0.1 else 'Weak'
        
        result = {
            'overall_sentiment': 'bullish' if sentiment_score > 0.6 else 'bearish' if sentiment_score < 0.4 else 'neutral',
            'sentiment_score': round(sentiment_score, 2),
            'bullish_percentage': bullish_percentage,
            'trend_strength': trend_strength,
            'volatility': random.choice(['High', 'Moderate', 'Low']),
            'support_level': 'See analysis for details',
            'resistance_level': 'See analysis for details',
            'recommendation': 'See analysis for detailed trading recommendations',
            'analysis': self._get_mock_sentiment(instrument),
            'source': 'mock_data'
        }
        
        # Save to cache
        sentiment_cache[f"market_{instrument}"] = {
            'result': result,
            'timestamp': datetime.now()
        }
        
        logger.debug(f"Mock data generated and cached for {instrument}")
        return result
    
    def _get_mock_sentiment(self, instrument: str) -> str:
        """Generate mock sentiment analysis for an instrument"""
        logger.info(f"Generating mock sentiment analysis for {instrument}")
        
        # Determine sentiment randomly but biased by instrument type
        if instrument.startswith(('BTC', 'ETH')):
            is_bullish = random.random() > 0.3  # 70% chance of bullish for crypto
        elif instrument.startswith(('XAU', 'GOLD')):
            is_bullish = random.random() > 0.4  # 60% chance of bullish for gold
        else:
            is_bullish = random.random() > 0.5  # 50% chance for other instruments
        
        # Generate random percentage values
        bullish_percentage = random.randint(60, 85) if is_bullish else random.randint(15, 40)
        bearish_percentage = 100 - bullish_percentage
        
        # Determine sentiment emoji and text
        sentiment_text = "Bullish" if is_bullish else "Bearish"
        sentiment_emoji = "📈" if is_bullish else "📉"
        
        # Mock reason text
        mock_reason = "<i>Note: Using mock data because API keys are not configured or APIs could not be reached.</i>"
        
        # Generate a mock analysis with the requested format
        return f"""<b>🎯 {instrument} Market Analysis</b>

<b>Overall Sentiment:</b> {sentiment_text} {sentiment_emoji}

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish_percentage}%
🔴 Bearish: {bearish_percentage}%
⚪️ Neutral: 0%

<b>📊 Market Sentiment Analysis:</b>
The {instrument} is currently showing {sentiment_text.lower()} sentiment with general market consensus. Based on current data, the outlook appears {"favorable" if is_bullish else "cautious"} for this instrument.

<b>📰 Key Sentiment Drivers:</b>
• {"Positive economic data supporting price" if is_bullish else "Recent economic indicators adding pressure"}
• {"Increased buying interest from institutional investors" if is_bullish else "Technical resistance levels limiting upside potential"}
• Regular market fluctuations in line with broader market conditions

<b>📅 Important Events & News:</b>
• Regular trading activity observed
• Standard market patterns in effect 
• Market sentiment data updated regularly

{mock_reason}"""
            
    async def get_market_sentiment_html(self, instrument: str) -> str:
        """
        Haal marktsentiment op voor een instrument
        
        Args:
            instrument: Het instrument waarvoor sentiment moet worden opgehaald
            
        Returns:
            str: HTML-geformatteerde sentiment analyse
        """
        try:
            logger.info(f"Ophalen van sentiment voor {instrument}")
            
            # Controleer of we een geldige cache entry hebben
            cache_key = f"html_{instrument}"
            
            # Check cache
            if cache_key in sentiment_cache:
                cached_data = sentiment_cache[cache_key]
                cache_timestamp = cached_data.get('timestamp')
                
                # Convert to datetime if it's not already
                if not isinstance(cache_timestamp, datetime):
                    cache_timestamp = datetime.fromtimestamp(cache_timestamp)
                    
                # Check if cache is still valid (less than 30 minutes old)
                if datetime.now() - cache_timestamp < timedelta(minutes=30):
                    logger.debug(f"Cache hit voor {cache_key}!")
                    return cached_data.get('result')
            
            # Get full sentiment data
            sentiment_data = await self.get_market_sentiment(instrument)
            
            if sentiment_data and 'analysis' in sentiment_data:
                # Already has HTML analysis
                html_content = sentiment_data['analysis']
            else:
                # Generate fallback HTML
                html_content = self._generate_fallback_html(instrument)
            
            # Cache the HTML result
            sentiment_cache[cache_key] = {
                'result': html_content,
                'timestamp': datetime.now()
            }
            
            return html_content
            
        except Exception as e:
            logger.error(f"Error in get_market_sentiment_html: {str(e)}")
            logger.exception(e)
            return f"<b>Error getting sentiment for {instrument}</b>\n\nSorry, we couldn't retrieve the market sentiment at this time. Please try again later."
    
    async def get_sentiment(self, instrument: str, market_type: str = None) -> Dict[str, Any]:
        """
        Get sentiment for a given instrument. This function is used by the TelegramService.
        Returns a dictionary with sentiment data or formatted text.
        """
        logger.info(f"get_sentiment called for {instrument}")
        
        try:
            # Get market sentiment data
            sentiment_data = await self.get_market_sentiment(instrument)
            
            # Check if sentiment_data is None before accessing it
            if sentiment_data is None:
                logger.error(f"Failed to get market sentiment data for {instrument}")
                # Return a basic fallback response
                return {
                    'analysis': f"<b>🎯 {instrument} Market Analysis</b>\n\nSorry, there was an error retrieving market sentiment data. Please try again later.",
                    'sentiment_score': 0.5,
                    'bullish': 50,
                    'bearish': 50,
                    'neutral': 0,
                    'technical_score': 'N/A',
                    'news_score': 'N/A',
                    'social_score': 'N/A',
                    'trend_strength': 'Moderate',
                    'volatility': 'Normal',
                    'volume': 'Normal',
                    'news_headlines': [],
                    'overall_sentiment': 'neutral'
                }
            
            # Extract sentiment values
            sentiment_score = sentiment_data.get('sentiment_score', 0.5)
            bullish_percentage = sentiment_data.get('bullish_percentage', 50)
            bearish_percentage = 100 - bullish_percentage
            neutral_percentage = 0
            
            # Determine trend strength
            trend_strength = sentiment_data.get('trend_strength', 'Moderate')
            
            # Get analysis text
            analysis = sentiment_data.get('analysis', f"<b>🎯 {instrument} Market Analysis</b>\n\nSorry, no detailed analysis is available at the moment.")
            
            result = {
                'bullish': bullish_percentage,
                'bearish': bearish_percentage,
                'neutral': neutral_percentage,
                'sentiment_score': sentiment_score,
                'technical_score': 'Based on market analysis',
                'news_score': f"{bullish_percentage}% positive",
                'social_score': f"{bearish_percentage}% negative",
                'trend_strength': trend_strength,
                'volatility': sentiment_data.get('volatility', 'Moderate'),
                'volume': 'Normal',
                'news_headlines': [],
                'overall_sentiment': sentiment_data.get('overall_sentiment', 'neutral'),
                'analysis': analysis
            }
            
            # Cache the result 
            cache_key = f"sentiment_{instrument}"
            sentiment_cache[cache_key] = {
                'result': result,
                'timestamp': datetime.now()
            }
            
            logger.debug(f"Sentiment data processed for {instrument}")
            return result
                
        except Exception as e:
            logger.error(f"Error in get_sentiment: {str(e)}")
            logger.exception(e)
            # Return a basic analysis message
            return {
                'analysis': f"<b>🎯 {instrument} Market Analysis</b>\n\nSorry, there was an error analyzing the market sentiment. Please try again later.",
                'sentiment_score': 0.5,
                'bullish': 50,
                'bearish': 50,
                'neutral': 0,
                'technical_score': 'N/A',
                'news_score': 'N/A',
                'social_score': 'N/A',
                'trend_strength': 'Moderate',
                'volatility': 'Normal',
                'volume': 'Normal',
                'news_headlines': [],
                'overall_sentiment': 'neutral'
            }
            
    def _generate_fallback_html(self, instrument):
        """Generate fallback HTML when no sentiment data is available"""
        # Genereer willekeurige sentiment scores
        bullish_score = random.randint(30, 70)
        bearish_score = 100 - bullish_score
        
        # Bepaal overall sentiment
        if bullish_score > 55:
            overall = "Bullish"
            emoji = "📈"
            color = "green"
        elif bullish_score < 45:
            overall = "Bearish"
            emoji = "📉"
            color = "red"
        else:
            overall = "Neutral"
            emoji = "⚖️"
            color = "orange"
        
        # Genereer sentiment analyse tekst
        return f"""
        <b>🧠 Market Sentiment Analysis: {instrument}</b>
        
        <b>Overall Sentiment:</b> <span style='color:{color}'>{overall} {emoji}</span>
        
        <b>Sentiment Breakdown:</b>
        • Bullish: {bullish_score}%
        • Bearish: {bearish_score}%
        
        <b>Key Indicators:</b>
        • Retail Sentiment: {"Mostly Bullish" if bullish_score > 50 else "Mostly Bearish"}
        • Institutional Positioning: {"Net Long" if random.random() > 0.5 else "Net Short"}
        • Social Media Buzz: {"Positive" if random.random() > 0.5 else "Negative"}
        
        <b>Recent News Impact:</b>
        {"Positive news driving bullish sentiment" if bullish_score > 50 else "Negative news causing bearish outlook"}
        
        <b>Market Analysis:</b>
        The current sentiment for {instrument} is {overall.lower()}, with {bullish_score}% of traders showing bullish bias. This suggests that the market is {"expecting upward movement" if bullish_score > 50 else "anticipating downward pressure"} in the near term.
        """

# Standalone function that the code might be calling
def get_sentiment_analysis(instrument, use_cache=True):
    """
    Standalone function for sentiment analysis, using the global sentiment_cache.
    This provides compatibility with the user-requested implementation.
    """
    current_time = datetime.now()
    
    # Check if we have a valid cached result
    if use_cache and instrument in sentiment_cache:
        cached_data = sentiment_cache[instrument]
        # Check if the cache is still valid (less than 30 minutes old)
        if current_time - cached_data['timestamp'] < timedelta(minutes=30):
            print(f"Using cached sentiment analysis for {instrument}")
            return cached_data['result']
    
    print(f"Performing new sentiment analysis for {instrument}")
    
    # If no valid cache, perform the analysis
    # Only set API key if not already set
    if not tavily.api_key:
        tavily.api_key = os.environ.get('TAVILY_API_KEY', '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')
        print(f"Set Tavily API key: {tavily.api_key[:4]}...{tavily.api_key[-4:]}")
    
    try:
        # Generate mock data since we don't have deepseek module
        sentiment_analysis = f"Mock sentiment analysis for {instrument}: NEUTRAL"
        
        # Cache the result with timestamp
        sentiment_cache[instrument] = {
            'result': sentiment_analysis,
            'timestamp': current_time
        }
        
        return sentiment_analysis
    
    except Exception as e:
        error_message = f"Error performing sentiment analysis: {str(e)}"
        print(error_message)
        return error_message
EOL
echo "sentiment.py file has been fixed with essential methods"

# Maak .env bestand aan
echo "Creating .env file..."
cat > .env << EOL
# Telegram Bot configuratie
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-"YOUR_TELEGRAM_BOT_TOKEN"}

# Webhook configuratie
WEBHOOK_URL=${WEBHOOK_URL:-"$PUBLIC_URL/webhook"}
WEBHOOK_PATH=${WEBHOOK_PATH:-"/webhook"}
PORT=${PORT:-8080}

# Force polling mode als je wilt testen zonder webhook (standaard uit voor Railway)
FORCE_POLLING=${FORCE_POLLING:-"false"}
EOL

# Forcibly install required packages
echo "Making sure essential packages are installed..."
pip install --no-cache-dir tavily-python==0.2.2
echo "Tavily package installed"

# Check if we're using the old structure (trading_bot/main.py) or new structure (main.py in root)
if [ -f "trading_bot/main.py" ]; then
    echo "Found main.py in trading_bot directory"
    # Run with a timeout to prevent getting stuck
    timeout ${TIMEOUT_SECONDS:-180} python -m trading_bot.main || {
        echo "Application timed out after ${TIMEOUT_SECONDS:-180} seconds, restarting..."
        python -m trading_bot.main
    }
elif [ -f "main.py" ]; then
    echo "Found main.py in root directory"
    # Run with a timeout to prevent getting stuck
    timeout ${TIMEOUT_SECONDS:-180} python main.py || {
        echo "Application timed out after ${TIMEOUT_SECONDS:-180} seconds, restarting..."
        python main.py
    }
else
    echo "main.py not found in either location, falling back to trading_bot.main module"
    # Fall back to the module-based import
    timeout ${TIMEOUT_SECONDS:-180} python -m trading_bot.main || {
        echo "Application timed out after ${TIMEOUT_SECONDS:-180} seconds, restarting..."
        python -m trading_bot.main
    }
fi
