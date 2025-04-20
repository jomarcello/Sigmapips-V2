# Sentiment service initialization

# Define MarketSentimentService class directly in __init__.py to avoid circular imports
import logging
import random
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Simple cache for sentiment data
_sentiment_cache = {}

class MarketSentimentService:
    """Service for analyzing market sentiment (simplified version in __init__.py)"""
    
    def __init__(self):
        """Initialize the market sentiment service"""
        self.use_mock = True
        self.cache_ttl = 30 * 60
        logger.info("MarketSentimentService initialized with cache TTL: %s seconds", self.cache_ttl)
    
    async def get_market_sentiment(self, instrument):
        """Get market sentiment for a specific instrument"""
        logger.info(f"Getting market sentiment for {instrument}")
        return await self._generate_mock_data(instrument)
                
    async def _generate_mock_data(self, instrument):
        """Generate mock data for sentiment analysis"""
        logger.info(f"Generating mock data for {instrument}")
        
        # Generate basic mock data
        sentiment_score = random.uniform(0.3, 0.7)
        bullish_percentage = int(sentiment_score * 100)
        
        result = {
            'overall_sentiment': 'neutral',
            'sentiment_score': round(sentiment_score, 2),
            'bullish_percentage': bullish_percentage,
            'analysis': f"<b>🎯 {instrument} Market Analysis</b>\n\nMock data for testing purposes.",
            'source': 'mock_data'
        }
        
        # Save to cache
        _sentiment_cache[f"market_{instrument}"] = {
            'result': result,
            'timestamp': datetime.now()
        }
        
        return result
    
    async def get_sentiment(self, instrument, market_type=None):
        """Get sentiment for a given instrument"""
        return await self.get_market_sentiment(instrument)
        
    async def get_market_sentiment_html(self, instrument):
        """Get HTML-formatted sentiment analysis"""
        sentiment_data = await self.get_market_sentiment(instrument)
        return sentiment_data.get('analysis', f"<b>No sentiment data available for {instrument}</b>")

# Export the class
__all__ = ["MarketSentimentService"]
