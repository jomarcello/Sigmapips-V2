import logging
import random
import os
import time
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
            
        # Cache voor sentiment analyses (instrument -> (timestamp, data))
        self.sentiment_cache = {}
        # Cache geldigheid in seconden (30 minuten)
        self.cache_ttl = 30 * 60
    
    async def get_market_sentiment(self, instrument):
        """Get market sentiment for a specific instrument"""
        try:
            logger.info(f"Getting market sentiment for {instrument}")
            
            # Controleer of we een geldige cache entry hebben
            current_time = time.time()
            if instrument in self.sentiment_cache:
                timestamp, cached_data = self.sentiment_cache[instrument]
                # Check of de cache nog geldig is (minder dan 30 minuten oud)
                if current_time - timestamp < self.cache_ttl:
                    logger.info(f"Using cached sentiment data for {instrument}")
                    return cached_data
                    
            # Geen geldige cache, genereer nieuwe data
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
                
                # Sla het resultaat op in de cache met huidige timestamp
                self.sentiment_cache[instrument] = (current_time, result)
                return result
                
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
            
            # Controleer of we een geldige cache entry hebben
            current_time = time.time()
            cache_key = f"html_{instrument}"
            if cache_key in self.sentiment_cache:
                timestamp, cached_html = self.sentiment_cache[cache_key]
                # Check of de cache nog geldig is (minder dan 30 minuten oud)
                if current_time - timestamp < self.cache_ttl:
                    logger.info(f"Using cached HTML sentiment data for {instrument}")
                    return cached_html
            
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
            
            # Sla het resultaat op in de cache met huidige timestamp
            self.sentiment_cache[cache_key] = (current_time, sentiment_html)
            
            logger.info(f"Sentiment analyse gegenereerd voor {instrument}")
            return sentiment_html
            
        except Exception as e:
            logger.error(f"Error in get_market_sentiment: {str(e)}")
            logger.exception(e)
            return f"<b>Error getting sentiment for {instrument}</b>\n\nSorry, we couldn't retrieve the market sentiment at this time. Please try again later."
            
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
        
        # Generate a mock analysis
        return f"""<b>🎯 {instrument} Market Analysis</b>

<b>Market Sentiment:</b>
Bullish: {bullish_percentage}%
Bearish: {bearish_percentage}%
Neutral: 0%

<b>📈 Market Direction:</b>
The {instrument} is currently showing a {"bullish" if is_bullish else "bearish"} trend. Technical indicators suggest {"upward momentum" if is_bullish else "downward pressure"} in the near term.

<b>📰 Latest News & Events:</b>
• {"Positive economic data supporting price" if is_bullish else "Recent economic indicators adding pressure"}
• {"Increased buying interest from institutional investors" if is_bullish else "Technical resistance levels limiting upside potential"}
• Regular market fluctuations in line with broader market conditions

<b>⚠️ Risk Factors:</b>
• Market Volatility: {random.choice(['High', 'Moderate', 'Low'])}
• Watch for unexpected news events
• Monitor broader market conditions

<b>💡 Conclusion:</b>
Based on current market conditions, the outlook for {instrument} appears {"positive" if is_bullish else "cautious"}. Traders should consider {"buy opportunities on dips" if is_bullish else "sell positions on rallies"} while maintaining proper risk management.

<i>Note: This is mock data for demonstration purposes only. Real trading decisions should be based on comprehensive analysis.</i>"""

    async def debug_api_keys(self):
        """
        Debug functie om te controleren of API keys geladen zijn en correct werken.
        Geeft een string terug met debug informatie.
        """
        logger.info("Debugging API keys")
        debug_info = []
        
        # Controleer of API keys zijn ingesteld in omgevingsvariabelen
        debug_info.append(f"DeepSeek API key in environment: {'Yes' if os.getenv('DEEPSEEK_API_KEY') else 'No'}")
        
        # Controleer of API keys zijn ingesteld in class variabelen
        debug_info.append(f"DeepSeek API key in instance: {'Yes' if self.api_key else 'No'}")
        
        # Test connectiviteit
        debug_info.append(f"Using mock data: {self.use_mock}")
        
        # Cache status
        cache_size = len(self.sentiment_cache)
        debug_info.append(f"Cache size: {cache_size} items")
        
        return "\n".join(debug_info)
        
    async def get_sentiment(self, instrument: str, market_type: str = None) -> Dict[str, Any]:
        """
        Get sentiment for a given instrument. This function is used by the TelegramService.
        Returns a dictionary with sentiment data or formatted text.
        """
        logger.info(f"get_sentiment called for {instrument}")
        
        try:
            # Controleer of we een geldige cache entry hebben
            current_time = time.time()
            cache_key = f"sentiment_{instrument}"
            if cache_key in self.sentiment_cache:
                timestamp, cached_data = self.sentiment_cache[cache_key]
                # Check of de cache nog geldig is (minder dan 30 minuten oud)
                if current_time - timestamp < self.cache_ttl:
                    logger.info(f"Using cached sentiment analysis for {instrument}")
                    return cached_data
            
            # Get market sentiment
            sentiment_data = await self.get_market_sentiment(instrument)
            
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
            
            # Sla het resultaat op in de cache met huidige timestamp
            self.sentiment_cache[cache_key] = (current_time, result)
            return result
                
        except Exception as e:
            logger.error(f"Error in get_sentiment: {str(e)}")
            logger.exception(e)
            # Return a basic analysis message
            return {
                'analysis': f"<b>🎯 {instrument} Market Analysis</b>\n\nSorry, there was an error analyzing the market sentiment. Please try again later.",
                'sentiment_score': 0,
                'technical_score': 'N/A',
                'news_score': 'N/A',
                'social_score': 'N/A',
                'trend_strength': 'Moderate',
                'volatility': 'Normal',
                'volume': 'Normal',
                'news_headlines': []
            }
            
    def clear_cache(self, instrument=None):
        """
        Wis de cache voor een specifiek instrument of de gehele cache
        
        Args:
            instrument: Optioneel, specifiek instrument om te wissen uit cache
        """
        if instrument:
            # Verwijder alle keys die met dit instrument te maken hebben
            keys_to_remove = []
            for key in self.sentiment_cache.keys():
                if key == instrument or key.endswith(f"_{instrument}"):
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self.sentiment_cache[key]
            
            logger.info(f"Cache gewist voor instrument: {instrument}")
        else:
            # Wis de gehele cache
            self.sentiment_cache.clear()
            logger.info("Volledige cache gewist")
