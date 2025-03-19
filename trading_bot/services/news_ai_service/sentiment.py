import logging
import random
import os
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class MarketSentimentService:
    """Service for analyzing market sentiment"""
    
    def __init__(self):
        """Initialize the market sentiment service"""
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.api_url = "https://api.deepseek.ai/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # If no API key is provided, we'll use mock data
        self.use_mock = not self.api_key
        if self.use_mock:
            logger.warning("No DeepSeek API key found, using mock data")
    
    async def get_market_sentiment(self, instrument):
        """Get market sentiment for a specific instrument"""
        try:
            logger.info(f"Getting market sentiment for {instrument}")
            
            if self.use_mock:
                # Generate sentiment based on instrument type
                if instrument.startswith(('BTC', 'ETH')):
                    sentiment_score = random.uniform(0.6, 0.8)  # Crypto tends to be bullish
                elif instrument.startswith(('XAU', 'GOLD')):
                    sentiment_score = random.uniform(0.4, 0.7)  # Commodities can be volatile
                else:
                    sentiment_score = random.uniform(0.3, 0.7)  # Forex and indices more balanced
                
                bullish_percentage = int(sentiment_score * 100)
                trend_strength = 'Strong' if abs(sentiment_score - 0.5) > 0.3 else 'Moderate' if abs(sentiment_score - 0.5) > 0.1 else 'Weak'
                
                return {
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
                
        except Exception as e:
            logger.error(f"Error getting market sentiment: {str(e)}")
            logger.exception(e)
            # Fallback naar neutraal sentiment
            return {
                'overall_sentiment': 'neutral',
                'sentiment_score': 0.5,
                'source': 'fallback'
            }

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
            
            # Hier zou je normaal gesproken een externe API aanroepen
            # Voor nu gebruiken we een mock implementatie
            
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
            sentiment_html = f"""
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
            
            logger.info(f"Sentiment analyse gegenereerd voor {instrument}")
            return sentiment_html
            
        except Exception as e:
            logger.error(f"Error in get_market_sentiment: {str(e)}")
            logger.exception(e)
            return f"<b>Error getting sentiment for {instrument}</b>\n\nSorry, we couldn't retrieve the market sentiment at this time. Please try again later."
