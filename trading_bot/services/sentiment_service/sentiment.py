import logging
import random
import os
import time
import asyncio
from typing import Dict, Any, List
import httpx

logger = logging.getLogger(__name__)
# Verhoog log level voor sentiment service
logger.setLevel(logging.DEBUG)

class MarketSentimentService:
    """Service for analyzing market sentiment"""
    
    def __init__(self):
        """Initialize the market sentiment service"""
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
        
        # Debug logging voor API key
        if self.api_key:
            logger.info(f"DeepSeek API key found: {self.api_key[:4]}...{self.api_key[-4:] if len(self.api_key) > 8 else ''}")
        else:
            logger.warning("DeepSeek API key not found in environment variables")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # If no API key is provided, we'll use mock data
        self.use_mock = not self.api_key or self.api_key.strip() == ""
        if self.use_mock:
            logger.warning("No DeepSeek API key found, using mock data")
            
        # Cache voor sentiment analyses (instrument -> (timestamp, data))
        self.sentiment_cache = {}
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
            
            logger.debug(f"Cache check voor {cache_key}. Cache bevat keys: {list(self.sentiment_cache.keys())}")
            logger.debug(f"Current cache state: {self.get_cache_status()}")
            
            if cache_key in self.sentiment_cache:
                timestamp, cached_data = self.sentiment_cache[cache_key]
                cache_age = current_time - timestamp
                logger.debug(f"Cache entry found - Timestamp: {timestamp}, Current time: {current_time}, Age: {cache_age}s, TTL: {self.cache_ttl}s")
                
                # Check of de cache nog geldig is (minder dan 30 minuten oud)
                if cache_age < self.cache_ttl:
                    logger.info(f"Cache HIT for {instrument} (age: {cache_age:.1f}s)")
                    return cached_data
                else:
                    logger.info(f"Cache EXPIRED for {instrument} (age: {cache_age:.1f}s)")
                    del self.sentiment_cache[cache_key]  # Remove expired entry
            else:
                logger.info(f"Cache MISS for {instrument}")
                    
            # Geen geldige cache, genereer nieuwe data
            logger.debug(f"Genereren van nieuwe sentiment data voor {instrument}")
            if self.use_mock:
                logger.info(f"Using mock data for {instrument} (api_key available: {bool(self.api_key)})")
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
                self.sentiment_cache[cache_key] = (current_time, result)
                logger.debug(f"Nieuwe data in cache opgeslagen voor {cache_key}")
                return result
            else:
                # Gebruik de DeepSeek API om sentiment data te genereren
                logger.info(f"Calling DeepSeek API for {instrument} sentiment analysis")
                
                try:
                    # Opstellen van het prompt voor de DeepSeek API
                    prompt = f"""You are a professional financial analyst with expertise in market sentiment analysis.
                    Provide a detailed market sentiment analysis for {instrument}.
                    
                    Format your response as JSON with the following structure:
                    {{
                        "overall_sentiment": "bullish|bearish|neutral",
                        "sentiment_score": 0.1-0.9 (where 0.1 is very bearish and 0.9 is very bullish),
                        "bullish_percentage": 0-100,
                        "trend_strength": "Strong|Moderate|Weak",
                        "volatility": "High|Moderate|Low",
                        "analysis": "HTML formatted analysis with the EXACT format below (including all emojis and section titles)"
                    }}
                    
                    For the "analysis" field, use EXACTLY this format (with HTML tags):
                    
                    <b>🎯 {instrument} Market Analysis</b>

                    <b>Overall Sentiment:</b> [Bullish|Bearish|Neutral] [📈|📉|⚖️]

                    <b>Market Sentiment Breakdown:</b>
                    🟢 Bullish: [percentage]%
                    🔴 Bearish: [percentage]%
                    ⚪️ Neutral: 0%

                    <b>📰 Key Sentiment Drivers:</b>
                    • [First key market driver]
                    • [Second key market driver]
                    • [Third key market driver]

                    <b>📊 Market Sentiment Analysis:</b>
                    [One paragraph analysis of current market sentiment]

                    <b>📅 Important Events & News:</b>
                    • [Important event 1]
                    • [Important event 2] 
                    • [Important event 3]
                    
                    <b>🔮 Sentiment Outlook:</b>
                    [Brief outlook based on sentiment]
                    """
                    
                    # Maak het request body
                    payload = {
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": "You are a professional financial analyst."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 1000
                    }
                    
                    # Maak de API call
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.post(
                            self.api_url,
                            headers=self.headers,
                            json=payload
                        )
                        
                        if response.status_code == 200:
                            response_data = response.json()
                            # Extract the assistant's response
                            assistant_response = response_data.get('choices', [{}])[0].get('message', {}).get('content', '')
                            
                            # Parse the JSON response
                            import json
                            try:
                                # Extract JSON from the response (it might be wrapped in markdown)
                                import re
                                json_match = re.search(r'```json\n(.*?)\n```', assistant_response, re.DOTALL)
                                if json_match:
                                    json_str = json_match.group(1)
                                else:
                                    json_str = assistant_response
                                
                                sentiment_data = json.loads(json_str)
                                
                                # Ensure all required fields are present
                                required_fields = ['overall_sentiment', 'sentiment_score', 'bullish_percentage', 'trend_strength', 'volatility', 'analysis']
                                for field in required_fields:
                                    if field not in sentiment_data:
                                        logger.warning(f"Missing required field '{field}' in API response")
                                        sentiment_data[field] = "N/A" if field != 'sentiment_score' else 0.5
                                
                                # Sla het resultaat op in de cache
                                self.sentiment_cache[cache_key] = (current_time, sentiment_data)
                                logger.info(f"DeepSeek API data successfully saved to cache for {instrument}")
                                return sentiment_data
                            except json.JSONDecodeError as json_err:
                                logger.error(f"Failed to parse JSON from DeepSeek API: {str(json_err)}")
                                logger.error(f"Response content: {assistant_response[:200]}...")
                        else:
                            logger.error(f"DeepSeek API request failed with status {response.status_code}: {response.text}")
                except Exception as api_err:
                    logger.error(f"Error calling DeepSeek API: {str(api_err)}")
                    logger.exception(api_err)
                
                # Fallback to mock data if API call fails
                logger.warning(f"Falling back to mock data for {instrument} after API failure")
                return await self._generate_mock_data(instrument, current_time, cache_key)
            
            # Als we hier komen, was er geen mock data en geen API key
            # Genereer een standaard fallback resultaat
            logger.warning(f"No data source available for {instrument}. Using fallback data.")
            return await self._generate_mock_data(instrument, current_time, cache_key)
                
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

    async def _generate_mock_data(self, instrument, current_time, cache_key):
        """Generate mock data for sentiment analysis"""
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
        self.sentiment_cache[cache_key] = (current_time, result)
        logger.debug(f"Nieuwe mock data in cache opgeslagen voor {cache_key}")
        return result

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
            
            logger.debug(f"Cache check voor {cache_key}. Cache bevat keys: {list(self.sentiment_cache.keys())}")
            
            if cache_key in self.sentiment_cache:
                timestamp, cached_html = self.sentiment_cache[cache_key]
                cache_age = current_time - timestamp
                # Check of de cache nog geldig is (minder dan 30 minuten oud)
                if cache_age < self.cache_ttl:
                    logger.debug(f"Cache hit voor {cache_key}! Leeftijd: {cache_age:.1f} seconden")
                    return cached_html
                else:
                    logger.debug(f"Cache verouderd voor {cache_key}. Leeftijd: {cache_age:.1f} seconden")
            else:
                logger.debug(f"Cache miss voor {cache_key}")
            
            logger.debug(f"Genereren van nieuwe HTML sentiment data voor {instrument}")
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
            logger.debug(f"Nieuwe HTML data in cache opgeslagen voor {cache_key}")
            
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
        
        # Determine sentiment emoji and text
        sentiment_text = "Bullish" if is_bullish else "Bearish"
        sentiment_emoji = "📈" if is_bullish else "📉"
        
        # Determine if we're using mock data because of a missing API key or API failure
        if not self.api_key or self.api_key.strip() == "":
            mock_reason = "<i>Note: Using mock data because no DeepSeek API key is configured.</i>"
        else:
            mock_reason = "<i>Note: Using mock data because the DeepSeek API could not be reached. Check your internet connection or API key.</i>"
        
        # Generate a mock analysis with the requested format
        return f"""<b>🎯 {instrument} Market Analysis</b>

<b>Overall Sentiment:</b> {sentiment_text} {sentiment_emoji}

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish_percentage}%
🔴 Bearish: {bearish_percentage}%
⚪️ Neutral: 0%

<b>📰 Key Sentiment Drivers:</b>
• {"Positive economic data supporting price" if is_bullish else "Recent economic indicators adding pressure"}
• {"Increased buying interest from institutional investors" if is_bullish else "Technical resistance levels limiting upside potential"}
• Regular market fluctuations in line with broader market conditions

<b>📊 Market Sentiment Analysis:</b>
The {instrument} is currently showing {sentiment_text.lower()} sentiment with general market consensus.

<b>📅 Important Events & News:</b>
• Regular trading activity observed
• Standard market patterns in effect 
• Market sentiment data updated regularly

<b>🔮 Sentiment Outlook:</b>
Based on current data, the outlook appears {"favorable" if is_bullish else "cautious"} for this instrument.

{mock_reason}"""

    async def debug_api_keys(self):
        """
        Debug functie om te controleren of API keys geladen zijn en correct werken.
        Geeft een string terug met debug informatie.
        """
        logger.info("Debugging API keys and cache")
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
        debug_info.append(f"Cache contents: {list(self.sentiment_cache.keys())}")
        debug_info.append(f"Cache TTL: {self.cache_ttl} seconds ({self.cache_ttl/60} minutes)")
        
        # Run cache test
        debug_info.append("\n=== Running Cache Test ===")
        await self.test_caching()
        debug_info.append(self.get_cache_status())
        
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
            
            logger.debug(f"Cache check voor {cache_key}. Cache bevat keys: {list(self.sentiment_cache.keys())}")
            
            if cache_key in self.sentiment_cache:
                timestamp, cached_data = self.sentiment_cache[cache_key]
                cache_age = current_time - timestamp
                # Check of de cache nog geldig is (minder dan 30 minuten oud)
                if cache_age < self.cache_ttl:
                    logger.debug(f"Cache hit voor {cache_key}! Leeftijd: {cache_age:.1f} seconden")
                    return cached_data
                else:
                    logger.debug(f"Cache verouderd voor {cache_key}. Leeftijd: {cache_age:.1f} seconden")
            else:
                logger.debug(f"Cache miss voor {cache_key}")
            
            logger.debug(f"Genereren van nieuwe sentiment data voor {instrument}")
            # Get market sentiment
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
            
            # Sla het resultaat op in de cache met huidige timestamp
            self.sentiment_cache[cache_key] = (current_time, result)
            logger.debug(f"Nieuwe sentiment data in cache opgeslagen voor {cache_key}")
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
            
    # Een helper functie om cache status te tonen
    def get_cache_status(self):
        """
        Geeft informatie over de huidige status van de cache
        
        Returns:
            str: Debug informatie over cache
        """
        output = []
        output.append(f"Aantal items in cache: {len(self.sentiment_cache)}")
        
        current_time = time.time()
        
        for key, (timestamp, _) in self.sentiment_cache.items():
            cache_age = current_time - timestamp
            expired = cache_age > self.cache_ttl
            output.append(f"Key: {key}, Leeftijd: {cache_age:.1f}s, Verlopen: {expired}")
            
        return "\n".join(output)

    async def test_caching(self, instrument="BTCUSD"):
        """
        Test the caching behavior by making consecutive requests
        and logging the results
        
        Args:
            instrument: Instrument to test with (default BTCUSD)
        """
        logger.info(f"\n=== Starting cache test for {instrument} ===")
        
        # First request - should be a miss
        logger.info("\nFirst request (should be MISS)")
        result1 = await self.get_market_sentiment(instrument)
        
        # Immediate second request - should be HIT
        logger.info("\nSecond request (should be HIT)")
        result2 = await self.get_market_sentiment(instrument)
        
        # Wait 30s then request again - should still be HIT
        logger.info("\nWaiting 30 seconds...")
        await asyncio.sleep(30)
        logger.info("\nThird request after 30s (should be HIT)")
        result3 = await self.get_market_sentiment(instrument)
        
        # Wait until cache expires then request again - should be MISS
        logger.info(f"\nWaiting {self.cache_ttl+1} seconds for cache to expire...")
        await asyncio.sleep(self.cache_ttl+1)
        logger.info("\nFourth request after TTL (should be MISS)")
        result4 = await self.get_market_sentiment(instrument)
        
        logger.info("\n=== Cache test complete ===")
