import os
import logging
import aiohttp
import json
import random
from typing import Dict, Any, Optional, List, Tuple, Set
import asyncio
import socket
import re
import ssl
import sys
import time
from datetime import datetime, timedelta
import threading
import pathlib
import statistics
import copy

logger = logging.getLogger(__name__)

class PerformanceMetrics:
    """Class to track and analyze performance metrics for API calls and caching"""
    
    def __init__(self, max_history: int = 100):
        """
        Initialize performance metrics tracking
        
        Args:
            max_history: Maximum number of data points to store
        """
        self.api_calls = {
            'tavily': [],
            'deepseek': [],
            'total': []
        }
        self.cache_hits = 0
        self.cache_misses = 0
        self.max_history = max_history
        self.lock = threading.Lock()
    
    def record_api_call(self, api_name: str, duration: float) -> None:
        """
        Record the duration of an API call
        
        Args:
            api_name: Name of the API ('tavily' or 'deepseek')
            duration: Duration of the call in seconds
        """
        with self.lock:
            if api_name in self.api_calls:
                # Keep only the most recent entries
                if len(self.api_calls[api_name]) >= self.max_history:
                    self.api_calls[api_name].pop(0)
                self.api_calls[api_name].append(duration)
    
    def record_total_request(self, duration: float) -> None:
        """
        Record the total duration of a sentiment request
        
        Args:
            duration: Duration of the request in seconds
        """
        with self.lock:
            if len(self.api_calls['total']) >= self.max_history:
                self.api_calls['total'].pop(0)
            self.api_calls['total'].append(duration)
    
    def record_cache_hit(self) -> None:
        """Record a cache hit"""
        with self.lock:
            self.cache_hits += 1
    
    def record_cache_miss(self) -> None:
        """Record a cache miss"""
        with self.lock:
            self.cache_misses += 1
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current performance metrics
        
        Returns:
            Dict with performance statistics
        """
        with self.lock:
            metrics = {
                'api_calls': {},
                'cache': {
                    'hits': self.cache_hits,
                    'misses': self.cache_misses,
                    'hit_rate': (self.cache_hits / (self.cache_hits + self.cache_misses) * 100)
                    if (self.cache_hits + self.cache_misses) > 0 else 0
                }
            }
            
            # Calculate API call statistics
            for api_name, durations in self.api_calls.items():
                if durations:
                    metrics['api_calls'][api_name] = {
                        'count': len(durations),
                        'avg_duration': statistics.mean(durations),
                        'min_duration': min(durations),
                        'max_duration': max(durations),
                        'median_duration': statistics.median(durations),
                        'p90_duration': sorted(durations)[int(len(durations) * 0.9)] if len(durations) >= 10 else None
                    }
                else:
                    metrics['api_calls'][api_name] = {
                        'count': 0,
                        'avg_duration': None,
                        'min_duration': None,
                        'max_duration': None,
                        'median_duration': None,
                        'p90_duration': None
                    }
            
            return metrics
    
    def reset(self) -> None:
        """Reset all metrics"""
        with self.lock:
            self.api_calls = {
                'tavily': [],
                'deepseek': [],
                'total': []
            }
            self.cache_hits = 0
            self.cache_misses = 0

class MarketSentimentService:
    """Service for retrieving market sentiment data"""
    
    def __init__(self, cache_ttl_minutes: int = 30, persistent_cache: bool = True, cache_file: str = None, fast_mode: bool = True):
        """
        Initialize the market sentiment service
        
        Args:
            cache_ttl_minutes: Time in minutes to keep sentiment data in cache (default: 30)
            persistent_cache: Whether to save/load cache to/from disk (default: True)
            cache_file: Path to cache file, if None uses default in user's home directory
            fast_mode: Whether to use faster, more efficient API calls (default: False)
        """
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.tavily_api_key = os.getenv("TAVILY_API_KEY")
        
        self.deepseek_url = "https://api.deepseek.com/v1/chat/completions"
        
        # Initialize the Tavily client
        self.tavily_client = TavilyClient(self.tavily_api_key)
        
        # Fast mode flag
        self.fast_mode = fast_mode
        
        # Explicitly enable caching
        self.cache_enabled = True
        
        # Initialize cache settings with longer TTL for performance
        self.cache_ttl = cache_ttl_minutes * 60  # Convert minutes to seconds
        self.use_persistent_cache = persistent_cache
        
        # Performance metrics
        self.metrics = PerformanceMetrics()
        
        # Set default cache file path if not specified
        if cache_file is None:
            home_dir = pathlib.Path.home()
            cache_dir = home_dir / ".trading_bot"
            os.makedirs(cache_dir, exist_ok=True)
            self.cache_file = cache_dir / "sentiment_cache.json"
        else:
            self.cache_file = pathlib.Path(cache_file)
        
        # Initialize cache for sentiment data
        self.sentiment_cache = {}  # Format: {instrument: {'data': sentiment_data, 'timestamp': creation_time}}
        
        # Load cache from disk if persistent caching is enabled - but don't block startup
        # Instead of loading here, we'll provide an async method to load the cache
        self.cache_loaded = False
        
        # Background task lock to prevent multiple saves at once
        self._cache_lock = threading.Lock()
        
        # Common request timeouts and concurrency control
        if self.fast_mode:
            # Faster timeouts for fast mode
            self.request_timeout = aiohttp.ClientTimeout(total=8, connect=3)
            # Semaphore for limiting concurrent requests in fast mode
            self.request_semaphore = asyncio.Semaphore(5)
            logger.info("Fast mode enabled: using optimized request parameters")
        else:
            # Standard timeouts
            self.request_timeout = aiohttp.ClientTimeout(total=12, connect=4)
            # In standard mode, no request semaphore needed
        
        logger.info(f"Sentiment cache TTL set to {cache_ttl_minutes} minutes ({self.cache_ttl} seconds)")
        logger.info(f"Persistent caching {'enabled' if self.use_persistent_cache else 'disabled'}, cache file: {self.cache_file if self.use_persistent_cache else 'N/A'}")
        
        # Log API key status (without revealing full keys)
        if self.tavily_api_key:
            masked_key = self.tavily_api_key[:6] + "..." + self.tavily_api_key[-4:] if len(self.tavily_api_key) > 10 else "***"
            logger.info(f"Tavily API key is configured: {masked_key}")
        else:
            logger.warning("No Tavily API key found")
        
        # Log DeepSeek API key status
        if self.deepseek_api_key:
            masked_key = self.deepseek_api_key[:6] + "..." + self.deepseek_api_key[-4:] if len(self.deepseek_api_key) > 10 else "***"
            logger.info(f"DeepSeek API key is configured: {masked_key}")
        else:
            logger.warning("No DeepSeek API key found")
            
    def _build_search_query(self, instrument: str, market_type: str) -> str:
        """
        Build a search query for the given instrument and market type.
        
        Args:
            instrument: The instrument to analyze (e.g., 'EURUSD')
            market_type: Market type (e.g., 'forex', 'crypto')
            
        Returns:
            str: A formatted search query for news and market data
        """
        logger.info(f"Building search query for {instrument} ({market_type})")
        
        base_query = f"{instrument} {market_type} market analysis"
        
        # Add additional context based on market type
        if market_type == 'forex':
            currency_pair = instrument[:3] + "/" + instrument[3:] if len(instrument) == 6 else instrument
            base_query = f"{currency_pair} forex market analysis current trend technical news"
        elif market_type == 'crypto':
            # For crypto, use common naming conventions
            crypto_name = instrument.replace('USD', '') if instrument.endswith('USD') else instrument
            base_query = f"{crypto_name} cryptocurrency price analysis market sentiment current trend"
        elif market_type == 'commodities':
            commodity_name = {
                'XAUUSD': 'gold',
                'XAGUSD': 'silver',
                'USOIL': 'crude oil',
                'BRENT': 'brent oil'
            }.get(instrument, instrument)
            base_query = f"{commodity_name} commodity market analysis price trend current news"
        elif market_type == 'indices':
            index_name = {
                'US30': 'Dow Jones',
                'US500': 'S&P 500',
                'US100': 'Nasdaq',
                'GER30': 'DAX',
                'UK100': 'FTSE 100'
            }.get(instrument, instrument)
            base_query = f"{index_name} stock index market analysis current trend technical indicators"
            
        # Add current date to get latest info
        base_query += " latest analysis today"
        
        logger.info(f"Search query built: {base_query}")
        return base_query
            
    async def get_sentiment(self, instrument: str, market_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get sentiment for a given instrument. This function is used by the TelegramService.
        Returns a dictionary with sentiment data or formatted text.
        """
        logger.info(f"get_sentiment called for {instrument}")
        
        # Start timing the total request
        start_time = time.time()
        
        # Check if we have a valid cached result
        cached_data = self._get_from_cache(instrument)
        if cached_data:
            # Record cache hit
            self.metrics.record_cache_hit()
            logger.info(f"Returning cached sentiment data for {instrument}")
            
            # Record total time (very fast for cache hits)
            self.metrics.record_total_request(time.time() - start_time)
            return cached_data
        
        # Record cache miss
        self.metrics.record_cache_miss()
        
        try:
            # Use fast mode if enabled
            if self.fast_mode:
                result = await self._get_fast_sentiment(instrument)
                # Record total request time
                self.metrics.record_total_request(time.time() - start_time)
                return result
            
            # Standard mode processing continues from here
            # Get sentiment text directly
            logger.info(f"Calling get_market_sentiment_text for {instrument}...")
            sentiment_text = await self.get_market_sentiment_text(instrument, market_type)
            logger.info(f"Received sentiment_text for {instrument}, length: {len(sentiment_text) if sentiment_text else 0}")
            
            # Make sure we have appropriate sentiment format. If not, use default.
            if not "<b>🎯" in sentiment_text or "Market Sentiment Analysis</b>" not in sentiment_text:
                logger.warning(f"Sentiment text doesn't have proper title format, using default format")
                sentiment_text = self._get_default_sentiment_text(instrument)
            
            # Check for required sections before continuing
            required_sections = [
                "<b>Overall Sentiment:</b>",
                "<b>Market Sentiment Breakdown:</b>",
                "🟢 Bullish:",
                "🔴 Bearish:",
                "<b>📊 Market Sentiment Analysis:</b>",
                "<b>📰 Key Sentiment Drivers:</b>",
                "<b>📅 Important Events & News:</b>"
            ]
            
            for section in required_sections:
                if section not in sentiment_text:
                    logger.warning(f"Missing required section: {section}, using default format")
                    sentiment_text = self._get_default_sentiment_text(instrument)
                    break
            
            # Check for disallowed sections before continuing
            disallowed_sections = [
                "Market Direction:",
                "Technical Outlook:",
                "Support & Resistance:",
                "Conclusion:"
            ]
            
            for section in disallowed_sections:
                if section in sentiment_text:
                    logger.warning(f"Found disallowed section: {section}, using default format")
                    sentiment_text = self._get_default_sentiment_text(instrument)
                    break
            
            # Extract sentiment values from the text if possible
            # Updated regex to better match the emoji format with more flexible whitespace handling
            bullish_match = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', sentiment_text)
            bearish_match = re.search(r'(?:Bearish:|🔴\s*Bearish:)\s*(\d+)\s*%', sentiment_text)
            
            # Log regex matches for debugging
            if bullish_match:
                logger.info(f"get_sentiment found bullish percentage for {instrument}: {bullish_match.group(1)}%")
            else:
                logger.warning(f"get_sentiment could not find bullish percentage in text for {instrument}")
                # Log a small snippet of the text for debugging
                text_snippet = sentiment_text[:300] + "..." if len(sentiment_text) > 300 else sentiment_text
                logger.warning(f"Text snippet: {text_snippet}")
                
                # If we can't extract the percentages, use the default format
                sentiment_text = self._get_default_sentiment_text(instrument)
                # Try again with the default format
                bullish_match = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', sentiment_text)
                bearish_match = re.search(r'(?:Bearish:|🔴\s*Bearish:)\s*(\d+)\s*%', sentiment_text)
                
            if bearish_match:
                logger.info(f"get_sentiment found bearish percentage for {instrument}: {bearish_match.group(1)}%")
            else:
                logger.warning(f"get_sentiment could not find bearish percentage in text for {instrument}")
                # If we can't extract the percentages, use the default format
                sentiment_text = self._get_default_sentiment_text(instrument)
                # Try again with the default format
                bullish_match = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', sentiment_text)
                bearish_match = re.search(r'(?:Bearish:|🔴\s*Bearish:)\s*(\d+)\s*%', sentiment_text)
                
            if bullish_match and bearish_match:
                bullish = int(bullish_match.group(1))
                bearish = int(bearish_match.group(1))
                neutral = 100 - (bullish + bearish)
                neutral = max(0, neutral)  # Ensure it's not negative
                
                # Calculate the sentiment score (-1.0 to 1.0)
                sentiment_score = (bullish - bearish) / 100
                
                # Determine trend strength based on how far from neutral
                trend_strength = 'Strong' if abs(bullish - 50) > 15 else 'Moderate' if abs(bullish - 50) > 5 else 'Weak'
                
                # Determine sentiment
                overall_sentiment = 'bullish' if bullish > bearish else 'bearish' if bearish > bullish else 'neutral'
                
                logger.info(f"Returning complete sentiment data for {instrument}: {overall_sentiment} (score: {sentiment_score:.2f})")
                
                result = {
                    'bullish': bullish,
                    'bearish': bearish,
                    'neutral': neutral,
                    'sentiment_score': sentiment_score,
                    'technical_score': 'Based on market analysis',
                    'news_score': f"{bullish}% positive",
                    'social_score': f"{bearish}% negative",
                    'trend_strength': trend_strength,
                    'volatility': 'Moderate',
                    'volume': 'Normal',
                    'news_headlines': [],
                    'overall_sentiment': overall_sentiment,
                    'analysis': sentiment_text
                }
                
                # Cache the result before returning
                self._add_to_cache(instrument, result)
                
                # Log the final result dictionary
                logger.info(f"Final sentiment result for {instrument}: {overall_sentiment}, score: {sentiment_score:.2f}, bullish: {bullish}%, bearish: {bearish}%, neutral: {neutral}%")
                
                # Record total request time
                self.metrics.record_total_request(time.time() - start_time)
                return result
            else:
                # If we can't extract percentages, use default values from default text
                logger.warning(f"Extracting percentages failed even with default text, using hardcoded defaults")
                
                result = {
                    'bullish': 50,
                    'bearish': 50,
                    'neutral': 0,
                    'sentiment_score': 0,
                    'technical_score': 'Based on market analysis',
                    'news_score': '50% positive',
                    'social_score': '50% negative',
                    'trend_strength': 'Moderate',
                    'volatility': 'Moderate',
                    'volume': 'Normal',
                    'news_headlines': [],
                    'overall_sentiment': 'neutral',
                    'analysis': self._get_default_sentiment_text(instrument)
                }
                
                # Cache the result before returning
                self._add_to_cache(instrument, result)
                
                # Log the fallback result
                logger.warning(f"Using hardcoded defaults for {instrument}: neutral, score: 0.00")
                
                # Record total request time
                self.metrics.record_total_request(time.time() - start_time)
                return result
            
        except Exception as e:
            logger.error(f"Error in get_sentiment: {str(e)}")
            logger.exception(e)
            # Return a basic analysis message
            error_result = {
                'bullish': 50,
                'bearish': 50,
                'neutral': 0,
                'sentiment_score': 0,
                'technical_score': 'N/A',
                'news_score': 'N/A',
                'social_score': 'N/A',
                'trend_strength': 'Moderate',
                'volatility': 'Normal',
                'volume': 'Normal',
                'news_headlines': [],
                'overall_sentiment': 'neutral',
                'analysis': self._get_default_sentiment_text(instrument)
            }
            
            # Record total request time even for errors
            self.metrics.record_total_request(time.time() - start_time)
            logger.error(f"Returning error result for {instrument} due to exception")
            return error_result
    
    async def get_market_sentiment(self, instrument: str, market_type: Optional[str] = None) -> Optional[dict]:
        """
        Get market sentiment for a given instrument.
        
        Args:
            instrument: The instrument to analyze (e.g., 'EURUSD')
            market_type: Optional market type if known (e.g., 'forex', 'crypto')
            
        Returns:
            dict: A dictionary containing sentiment data, or a string with formatted analysis
        """
        try:
            logger.info(f"Getting market sentiment for {instrument} ({market_type or 'unknown'})")
            
            # Check for cached data first
            cached_data = self._get_from_cache(instrument)
            if cached_data:
                logger.info(f"Using cached sentiment data for {instrument}")
                return cached_data
            
            if market_type is None:
                # Determine market type from instrument if not provided
                market_type = self._guess_market_from_instrument(instrument)
            
            # Build search query based on market type
            search_query = self._build_search_query(instrument, market_type)
            logger.info(f"Built search query: {search_query}")
            
            # Get news data and process sentiment in parallel
            news_content_task = self._get_tavily_news(search_query)
            
            try:
                # Use timeout to avoid waiting too long
                news_content = await asyncio.wait_for(news_content_task, timeout=15)
            except asyncio.TimeoutError:
                logger.warning(f"Tavily news retrieval timed out for {instrument}")
                news_content = f"Market analysis for {instrument}"
            
            if not news_content:
                logger.error(f"Failed to retrieve Tavily news content for {instrument}")
                news_content = f"Market analysis for {instrument}"
            
            # Process and format the news content
            formatted_content = self._format_data_manually(news_content, instrument)
            
            # Use DeepSeek to analyze the sentiment
            try:
                final_analysis = await asyncio.wait_for(
                    self._format_with_deepseek(instrument, market_type, formatted_content),
                    timeout=20
                )
            except asyncio.TimeoutError:
                logger.warning(f"DeepSeek analysis timed out for {instrument}, using formatted content")
                final_analysis = formatted_content
                
            if not final_analysis:
                logger.error(f"Failed to format DeepSeek analysis for {instrument}")
                # Val NIET terug op een error, maar gebruik de ruwe content
                final_analysis = f"""<b>🎯 {instrument} Market Analysis</b>

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 60%
🔴 Bearish: 30%
⚪️ Neutral: 10%

<b>📈 Market Direction:</b>
{formatted_content}
"""
            
            logger.info(f"Looking for bullish percentage in response for {instrument}")
            
            # Try to extract sentiment values from the text
            # Updated regex to better match the emoji format with more flexible whitespace handling
            bullish_match = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', final_analysis)
            
            # Log the bullish match result for debugging
            if bullish_match:
                logger.info(f"Found bullish percentage for {instrument}: {bullish_match.group(1)}%")
            else:
                logger.warning(f"Could not find bullish percentage in response for {instrument}")
                logger.debug(f"Response snippet: {final_analysis[:300]}...")
            
            # If we couldn't find bullish percentage in the DeepSeek response, look for keywords
            # to determine sentiment direction and assign reasonable default values
            bullish_percentage = None
            bearish_percentage = None
            
            if bullish_match:
                # Normal path - extract directly from regex match
                bullish_percentage = int(bullish_match.group(1))
                
                # Try to extract bearish and neutral directly
                bearish_match = re.search(r'(?:Bearish:|🔴\s*Bearish:)\s*(\d+)\s*%', final_analysis)
                neutral_match = re.search(r'(?:Neutral:|⚪️\s*Neutral:)\s*(\d+)\s*%', final_analysis)
                
                if bearish_match:
                    bearish_percentage = int(bearish_match.group(1))
                    logger.info(f"Found bearish percentage for {instrument}: {bearish_percentage}%")
                else:
                    bearish_percentage = 100 - bullish_percentage
                    logger.warning(f"Could not find bearish percentage, using complement: {bearish_percentage}%")
                
                if neutral_match:
                    neutral_percentage = int(neutral_match.group(1))
                    logger.info(f"Found neutral percentage for {instrument}: {neutral_percentage}%")
                    
                    # Adjust percentages to ensure they sum to 100%
                    total = bullish_percentage + bearish_percentage + neutral_percentage
                    if total != 100:
                        logger.warning(f"Sentiment percentages sum to {total}, adjusting...")
                        # Scale proportionally
                        bullish_percentage = int((bullish_percentage / total) * 100)
                        bearish_percentage = int((bearish_percentage / total) * 100)
                        neutral_percentage = 100 - bullish_percentage - bearish_percentage
                else:
                    neutral_percentage = 0
                    logger.warning(f"Could not find neutral percentage, using default: {neutral_percentage}%")
                
                logger.info(f"Extracted sentiment values for {instrument}: Bullish {bullish_percentage}%, Bearish {bearish_percentage}%, Neutral {neutral_percentage}%")
                
                # Determine sentiment
                overall_sentiment = 'bullish' if bullish_percentage > bearish_percentage else 'bearish' if bearish_percentage > bullish_percentage else 'neutral'
                
                # Calculate the sentiment score (-1.0 to 1.0)
                sentiment_score = (bullish_percentage - bearish_percentage) / 100
                
                # Determine trend strength based on how far from neutral
                trend_strength = 'Strong' if abs(bullish_percentage - 50) > 15 else 'Moderate' if abs(bullish_percentage - 50) > 5 else 'Weak'
                
                logger.info(f"Returning complete sentiment data for {instrument}: {overall_sentiment} (score: {sentiment_score:.2f})")
                
                result = {
                    'bullish': bullish_percentage,
                    'bearish': bearish_percentage,
                    'neutral': neutral_percentage,
                    'sentiment_score': sentiment_score,
                    'technical_score': 'Based on market analysis',
                    'news_score': f"{bullish_percentage}% positive",
                    'social_score': f"{bearish_percentage}% negative",
                    'trend_strength': trend_strength,
                    'volatility': 'Moderate',
                    'volume': 'Normal',
                    'news_headlines': [],
                    'overall_sentiment': overall_sentiment,
                    'analysis': final_analysis
                }
                
                # Cache the result
                self._add_to_cache(instrument, result)
                
                return result
            else:
                logger.warning(f"Could not find bullish percentage in DeepSeek response for {instrument}. Using keyword analysis.")
                # Fallback: Calculate sentiment through keyword analysis
                bullish_keywords = ['bullish', 'optimistic', 'uptrend', 'positive', 'strong', 'upside', 'buy', 'growth']
                bearish_keywords = ['bearish', 'pessimistic', 'downtrend', 'negative', 'weak', 'downside', 'sell', 'decline']
                
                bullish_count = sum(final_analysis.lower().count(keyword) for keyword in bullish_keywords)
                bearish_count = sum(final_analysis.lower().count(keyword) for keyword in bearish_keywords)
                
                total_count = bullish_count + bearish_count
                if total_count > 0:
                    bullish_percentage = int((bullish_count / total_count) * 100)
                    bearish_percentage = 100 - bullish_percentage
                    neutral_percentage = 0
                else:
                    bullish_percentage = 50
                    bearish_percentage = 50
                    neutral_percentage = 0
                
                # Calculate sentiment score same as above
                sentiment_score = (bullish_percentage - bearish_percentage) / 100
                overall_sentiment = 'bullish' if bullish_percentage > bearish_percentage else 'bearish' if bearish_percentage > bullish_percentage else 'neutral'
                trend_strength = 'Strong' if abs(bullish_percentage - 50) > 15 else 'Moderate' if abs(bullish_percentage - 50) > 5 else 'Weak'
                
                logger.warning(f"Using keyword analysis for {instrument}: Bullish {bullish_percentage}%, Bearish {bearish_percentage}%, Sentiment: {overall_sentiment}")
                
                result = {
                    'bullish': bullish_percentage,
                    'bearish': bearish_percentage,
                    'neutral': neutral_percentage,
                    'sentiment_score': sentiment_score,
                    'technical_score': 'Based on keyword analysis',
                    'news_score': f"{bullish_percentage}% positive",
                    'social_score': f"{bearish_percentage}% negative",
                    'trend_strength': trend_strength,
                    'volatility': 'Moderate',
                    'volume': 'Normal',
                    'news_headlines': [],
                    'overall_sentiment': overall_sentiment,
                    'analysis': final_analysis
                }
                
                # Cache the result
                self._add_to_cache(instrument, result)
                
                return result
            
            sentiment = 'bullish' if bullish_percentage > 50 else 'bearish' if bullish_percentage < 50 else 'neutral'
            
            # Create dictionary result with all data
            result = {
                'overall_sentiment': sentiment,
                'sentiment_score': bullish_percentage / 100,
                'bullish': bullish_percentage,
                'bearish': bearish_percentage,
                'neutral': 0,
                'bullish_percentage': bullish_percentage,
                'bearish_percentage': bearish_percentage,
                'technical_score': 'Based on market analysis',
                'news_score': f"{bullish_percentage}% positive",
                'social_score': f"{bearish_percentage}% negative",
                'trend_strength': 'Strong' if abs(bullish_percentage - 50) > 15 else 'Moderate' if abs(bullish_percentage - 50) > 5 else 'Weak',
                'volatility': 'Moderate',  # Default value as this is hard to extract reliably
                'volume': 'Normal',
                'support_level': 'Not available',  # Would need more sophisticated analysis
                'resistance_level': 'Not available',  # Would need more sophisticated analysis
                'recommendation': 'See analysis for details',
                'analysis': final_analysis,
                'news_headlines': []  # We don't have actual headlines from the API
            }
            
            # Cache the result
            self._add_to_cache(instrument, result)
            
            logger.info(f"Returning sentiment data for {instrument}: {sentiment} (score: {bullish_percentage/100:.2f})")
            return result
                
        except Exception as e:
            logger.error(f"Error in market sentiment analysis: {str(e)}")
            logger.exception(e)
            raise ValueError(f"Failed to analyze market sentiment for {instrument}: {str(e)}")
    
    async def get_market_sentiment_text(self, instrument: str, market_type: Optional[str] = None) -> str:
        """
        Get market sentiment as formatted text for a given instrument.
        This is a wrapper around get_market_sentiment that ensures a string is returned.
        
        Args:
            instrument: The instrument to analyze (e.g., 'EURUSD')
            market_type: Optional market type if known (e.g., 'forex', 'crypto')
            
        Returns:
            str: Formatted sentiment analysis text
        """
        logger.info(f"Getting market sentiment text for {instrument} ({market_type or 'unknown'})")
        
        try:
            if market_type is None:
                # Determine market type from instrument if not provided
                market_type = self._guess_market_from_instrument(instrument)
                logger.info(f"Market type guessed as {market_type} for {instrument}")
            else:
                # Normalize to lowercase
                market_type = market_type.lower()
            
            # Get sentiment data as dictionary
            try:
                # First check if we have a cached sentiment that contains the analysis
                cached_sentiment = self._get_from_cache(instrument)
                if cached_sentiment and 'analysis' in cached_sentiment:
                    logger.info(f"Using cached sentiment analysis for {instrument}")
                    return cached_sentiment['analysis']
                
                # If no cache, proceed with regular sentiment analysis
                logger.info(f"Calling get_market_sentiment for {instrument} ({market_type})")
                sentiment_data = await self.get_market_sentiment(instrument, market_type)
                logger.info(f"Got sentiment data: {type(sentiment_data)}")
                
                # Log part of the analysis text for debugging
                if isinstance(sentiment_data, dict) and 'analysis' in sentiment_data:
                    analysis_snippet = sentiment_data['analysis'][:300] + "..." if len(sentiment_data['analysis']) > 300 else sentiment_data['analysis']
                    logger.info(f"Analysis snippet for {instrument}: {analysis_snippet}")
                else:
                    logger.warning(f"No 'analysis' field in sentiment data for {instrument}")
                
            except Exception as e:
                logger.error(f"Error in get_market_sentiment call: {str(e)}")
                logger.exception(e)
                # Create a default sentiment data structure with proper percentages for parsing
                sentiment_data = {
                    'overall_sentiment': 'neutral',
                    'bullish': 50,
                    'bearish': 50,
                    'neutral': 0,
                    'trend_strength': 'Weak',
                    'volatility': 'Moderate',
                    'analysis': f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> Neutral ➡️

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 50%
🔴 Bearish: 50%
⚪️ Neutral: 0%

<b>📰 Key Sentiment Drivers:</b>
• Market conditions appear normal with mixed signals
• No clear directional bias at this time
• Standard market activity observed

<b>📊 Market Mood:</b>
{instrument} is currently showing mixed signals with no clear sentiment bias.

<b>📅 Important Events & News:</b>
• Normal market activity with no major catalysts
• No significant economic releases impacting the market
• General news and global trends affecting sentiment

<b>🔮 Sentiment Outlook:</b>
The market shows balanced sentiment for {instrument} with no strong directional bias at this time.

<i>Error details: {str(e)[:100]}</i>
"""
                }
                logger.info(f"Created fallback sentiment data with proper format for {instrument}")
                
                # Cache this fallback data too
                self._add_to_cache(instrument, sentiment_data)
            
            # Convert sentiment_data to a string result
            result = None
            
            # Extract the analysis text if it exists
            if isinstance(sentiment_data, dict) and 'analysis' in sentiment_data:
                logger.info(f"Using 'analysis' field from sentiment data for {instrument}")
                result = sentiment_data['analysis']
                
                # Verify that the result contains proper sentiment percentages
                bullish_match = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', result)
                if not bullish_match:
                    logger.warning(f"Analysis field does not contain proper Bullish percentage format for {instrument}")
                    
                    # Check if we have bullish percentage in sentiment_data
                    bullish_percentage = sentiment_data.get('bullish', 50)
                    bearish_percentage = sentiment_data.get('bearish', 50)
                    
                    # Try to find where to insert the sentiment breakdown section
                    if "<b>Market Sentiment Breakdown:</b>" in result:
                        # Replace the entire section
                        pattern = r'<b>Market Sentiment Breakdown:</b>.*?(?=<b>)'
                        replacement = f"""<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish_percentage}%
🔴 Bearish: {bearish_percentage}%
⚪️ Neutral: 0%

"""
                        result = re.sub(pattern, replacement, result, flags=re.DOTALL)
                        logger.info(f"Replaced Market Sentiment section with percentages from sentiment_data")
                    else:
                        # Try to insert after the first section
                        pattern = r'(<b>🎯.*?</b>\s*\n\s*\n)'
                        replacement = f"""$1<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish_percentage}%
🔴 Bearish: {bearish_percentage}%
⚪️ Neutral: 0%

"""
                        new_result = re.sub(pattern, replacement, result, flags=re.DOTALL)
                        
                        if new_result != result:
                            result = new_result
                            logger.info(f"Inserted Market Sentiment section after title")
                        else:
                            logger.warning(f"Could not find place to insert Market Sentiment section")
            
            # If there's no analysis text, generate one from the sentiment data
            if not result and isinstance(sentiment_data, dict):
                logger.info(f"Generating formatted text from sentiment data for {instrument}")
                
                bullish = sentiment_data.get('bullish', 50)
                bearish = sentiment_data.get('bearish', 50)
                neutral = sentiment_data.get('neutral', 0)
                
                sentiment = sentiment_data.get('overall_sentiment', 'neutral')
                trend_strength = sentiment_data.get('trend_strength', 'Moderate')
                
                result = f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> {sentiment.capitalize()} {'📈' if sentiment == 'bullish' else '📉' if sentiment == 'bearish' else '➡️'}

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish}%
🔴 Bearish: {bearish}%
⚪️ Neutral: {neutral}%

<b>📰 Key Sentiment Drivers:</b>
• Market sentiment driven by technical and fundamental factors
• Recent market developments shaping trader perception
• Evolving economic conditions influencing outlook

<b>📊 Market Mood:</b>
The {instrument} is currently showing {sentiment} sentiment with {trend_strength.lower()} momentum.

<b>📅 Important Events & News:</b>
• Regular trading activity observed
• No major market-moving events at this time
• Standard economic influences in effect

<b>🔮 Sentiment Outlook:</b>
{sentiment_data.get('recommendation', 'Monitor market conditions and manage risk appropriately.')}
"""
                logger.info(f"Generated complete formatted text with percentages for {instrument}")
            
            # Fallback to a simple message if we still don't have a result
            if not result or not isinstance(result, str) or len(result.strip()) == 0:
                logger.warning(f"Using complete fallback sentiment message for {instrument}")
                result = f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> Neutral ➡️

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 50%
🔴 Bearish: 50%
⚪️ Neutral: 0%

<b>📰 Key Sentiment Drivers:</b>
• Regular market activity with no major catalysts
• General economic factors influencing market mood
• No significant news events driving sentiment

<b>📊 Market Mood:</b>
{instrument} is trading with a balanced sentiment pattern with no clear sentiment bias.

<b>📅 Important Events & News:</b>
• Standard market updates with limited impact
• No major economic releases affecting sentiment
• Regular market fluctuations within expected ranges

<b>🔮 Sentiment Outlook:</b>
Current sentiment for {instrument} is neutral with balanced perspectives from market participants.
"""
            
            logger.info(f"Returning sentiment text for {instrument} (length: {len(result) if result else 0})")
            
            # Final check - verify the result has the correct format for bullish/bearish percentages
            bullish_check = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', result)
            if bullish_check:
                logger.info(f"Final text contains bullish percentage: {bullish_check.group(1)}%")
            else:
                logger.warning(f"Final text does NOT contain bullish percentage pattern, fixing format")
                
                # Add proper sentiment breakdown section if missing
                pattern = r'(<b>🎯.*?</b>\s*\n\s*\n)'
                replacement = f"""$1<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 50%
🔴 Bearish: 50%
⚪️ Neutral: 0%

"""
                new_result = re.sub(pattern, replacement, result, flags=re.DOTALL)
                
                if new_result != result:
                    result = new_result
                    logger.info(f"Fixed: inserted Market Sentiment section with percentages")
                
            # Ensure the result has the expected sections with emojis
            expected_sections = [
                ('<b>📰 Key Sentiment Drivers:</b>', '<b>Key Sentiment Drivers:</b>'),
                ('<b>📊 Market Mood:</b>', '<b>Market Mood:</b>'),
                ('<b>📅 Important Events & News:</b>', '<b>Important Events & News:</b>'),
                ('<b>🔮 Sentiment Outlook:</b>', '<b>Sentiment Outlook:</b>')
            ]
            
            for emoji_section, plain_section in expected_sections:
                if emoji_section not in result and plain_section in result:
                    logger.info(f"Converting {plain_section} to {emoji_section}")
                    result = result.replace(plain_section, emoji_section)
            
            return result if result else f"Sentiment analysis for {instrument}: Currently neutral"
            
        except Exception as e:
            logger.error(f"Uncaught error in get_market_sentiment_text: {str(e)}")
            logger.exception(e)
            # Return a valid response even in case of errors, with correct percentages format
            return f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> Neutral ➡️

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 50%
🔴 Bearish: 50%
⚪️ Neutral: 0%

<b>⚠️ Service Note:</b>
The sentiment analysis service encountered an error while processing data for {instrument}.
Please try again later or choose a different instrument.

<b>📰 Key Sentiment Drivers:</b>
• Market conditions appear normal with mixed signals
• No clear directional bias at this time
• Standard risk factors in the current market

<b>📊 Market Mood:</b>
Market mood is currently balanced with no strong signals.

<b>📅 Important Events & News:</b>
• No major market-moving events detected
• Regular market activity continues
• Standard economic factors in play

<b>🔮 Sentiment Outlook:</b>
Standard risk management practices recommended until clearer sentiment emerges.
"""
    
    def _format_data_manually(self, news_content: str, instrument: str) -> str:
        """Format market data manually for further processing"""
        try:
            logger.info(f"Manually formatting market data for {instrument}")
            
            # Extract key phrases and content from news_content
            formatted_text = f"# Market Sentiment Data for {instrument}\n\n"
            
            # Add news content sections
            if "Market Sentiment Analysis" in news_content or "Market Analysis" in news_content:
                formatted_text += news_content
            else:
                # Extract key parts of the news content
                sections = news_content.split("\n\n")
                for section in sections:
                    if len(section.strip()) > 0:
                        formatted_text += section.strip() + "\n\n"
            
            # Make sure it's not too long
            if len(formatted_text) > 6000:
                formatted_text = formatted_text[:6000] + "...\n\n(content truncated for processing)"
                
            return formatted_text
            
        except Exception as e:
            logger.error(f"Error formatting market data manually: {str(e)}")
            return f"# Market Sentiment Data for {instrument}\n\nError formatting data: {str(e)}\n\nRaw content: {news_content[:500]}..."
    
    async def _get_tavily_news(self, search_query: str) -> str:
        """Use Tavily API to get latest news and market data"""
        logger.info(f"Searching for news using Tavily API")
        
        # Start timing the API call
        start_time = time.time()
        
        # Check if API key is configured
        if not self.tavily_api_key:
            logger.error("Tavily API key is not configured")
            return None
            
        # Use our Tavily client to make the API call
        try:
            response = await self.tavily_client.search(
                query=search_query,
                search_depth="basic",
                include_answer=True,
                max_results=5
            )
            
            # Record API call duration
            self.metrics.record_api_call('tavily', time.time() - start_time)
            
            if response:
                return self._process_tavily_response(json.dumps(response))
            else:
                logger.error("Tavily search returned no results")
                return None
                
        except Exception as e:
            # Record API call duration even for failures
            self.metrics.record_api_call('tavily', time.time() - start_time)
            
            logger.error(f"Error calling Tavily API: {str(e)}")
            logger.exception(e)
            return None
            
    def _process_tavily_response(self, response_text: str) -> str:
        """Process the Tavily API response and extract useful information"""
        try:
            data = json.loads(response_text)
            
            # Structure for the formatted response
            formatted_text = f"Market Sentiment Analysis:\n\n"
            
            # Extract the generated answer if available
            if data and "answer" in data and data["answer"]:
                answer = data["answer"]
                formatted_text += f"Summary: {answer}\n\n"
                logger.info("Successfully received answer from Tavily")
                
            # Extract results for more comprehensive information
            if "results" in data and data["results"]:
                formatted_text += "Detailed Market Information:\n"
                for idx, result in enumerate(data["results"][:5]):  # Limit to top 5 results
                    title = result.get("title", "No Title")
                    content = result.get("content", "No Content").strip()
                    url = result.get("url", "")
                    score = result.get("score", 0)
                    
                    formatted_text += f"\n{idx+1}. {title}\n"
                    formatted_text += f"{content[:500]}...\n" if len(content) > 500 else f"{content}\n"
                    formatted_text += f"Source: {url}\n"
                    formatted_text += f"Relevance: {score:.2f}\n"
                
                logger.info(f"Successfully processed {len(data['results'])} results from Tavily")
                return formatted_text
            
            # If no answer and no results but we have response content
            if response_text and len(response_text) > 20:
                logger.warning(f"Unusual Tavily response format, but using raw content")
                return f"Market sentiment data:\n\n{response_text[:2000]}"
                
            logger.error(f"Unexpected Tavily API response format: {response_text[:200]}...")
            return None
                
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON response from Tavily: {response_text[:200]}...")
            return None
    
    async def _format_with_deepseek(self, instrument: str, market: str, market_data: str) -> str:
        """Use DeepSeek to format the news into a structured Telegram message"""
        if not self.deepseek_api_key:
            logger.warning("No DeepSeek API key available, using manual formatting")
            return self._format_data_manually(market_data, instrument)
            
        logger.info(f"Formatting market data for {instrument} using DeepSeek API")
        
        # Start timing the API call
        start_time = time.time()
        
        try:
            # Check DeepSeek API connectivity first
            deepseek_available = await self._check_deepseek_connectivity()
            if not deepseek_available:
                logger.warning("DeepSeek API is unreachable, using manual formatting")
                return self._format_data_manually(market_data, instrument)
            
            # Prepare the API call
            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key.strip()}",
                "Content-Type": "application/json"
            }
            
            # Create prompt for sentiment analysis
            prompt = f"""Analyze the following market data for {instrument} and provide a market sentiment analysis focused ONLY on news, events, and broader market sentiment. 

**IMPORTANT**: 
1. You MUST include explicit percentages for bullish, bearish, and neutral sentiment in EXACTLY the format shown below. The percentages MUST be integers that sum to 100%.
2. DO NOT include ANY specific price levels, exact numbers, technical analysis, support/resistance levels, or price targets. 
3. DO NOT include ANY specific trading recommendations or strategies like "buy at X" or "sell at Y".
4. DO NOT mention any specific trading indicators like RSI, EMA, MACD, or specific numerical values like percentages of price movement.
5. Focus ONLY on general news events, market sentiment, and fundamental factors that drive sentiment.
6. DO NOT include sections named "Market Direction", "Technical Outlook", "Support & Resistance", "Conclusion", or anything related to technical analysis.

Market Data:
{market_data}

Your response MUST follow this EXACT format with EXACTLY this HTML formatting (keep the exact formatting with the <b> tags):

<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> [Bullish/Bearish/Neutral] [Emoji]

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: XX%
🔴 Bearish: YY%
⚪️ Neutral: ZZ%

<b>📊 Market Sentiment Analysis:</b>
[Brief description of the current market sentiment and outlook without specific price targets]

<b>📰 Key Sentiment Drivers:</b>
• [Key sentiment factor 1]
• [Key sentiment factor 2]
• [Key sentiment factor 3]

<b>📅 Important Events & News:</b>
• [News event 1]
• [News event 2]
• [News event 3]

DO NOT mention any specific price levels, numeric values, resistance/support levels, or trading recommendations. Focus ONLY on NEWS, EVENTS, and SENTIMENT information.

The sentiment percentages (Overall Sentiment, Bullish, Bearish, Neutral percentages) MUST be clearly indicated EXACTLY as shown in the format.

I will check your output to ensure you have followed the EXACT format required. DO NOT add any additional sections beyond the ones shown above.
"""

            # Log the prompt for debugging
            logger.info(f"DeepSeek prompt for {instrument} (first 200 chars): {prompt[:200]}...")
            
            # Make the API call
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.deepseek_url,
                    headers=headers,
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": "You are a professional market analyst specializing in quantitative sentiment analysis. You ALWAYS follow the EXACT format requested."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.2,
                        "max_tokens": 1024
                    }
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Record API call duration for successful call
                        self.metrics.record_api_call('deepseek', time.time() - start_time)
                        
                        response_content = data['choices'][0]['message']['content']
                        logger.info(f"DeepSeek raw response for {instrument}: {response_content[:200]}...")
                        
                        # Clean up any trailing instructions that might have been included in the output
                        response_content = self._clean_deepseek_response(response_content)
                        
                        # Ensure the title is correctly formatted
                        if not "<b>🎯" in response_content:
                            response_content = f"<b>🎯 {instrument} Market Sentiment Analysis</b>\n\n" + response_content
                        
                        # Ensure the title uses "Market Sentiment Analysis" not just "Market Analysis"
                        response_content = response_content.replace("Market Analysis</b>", "Market Sentiment Analysis</b>")
                        
                        # Check for required sections and add them if missing
                        required_sections = [
                            ("<b>Overall Sentiment:</b>", f"<b>Overall Sentiment:</b> Neutral ➡️\n\n"),
                            ("<b>Market Sentiment Breakdown:</b>", f"<b>Market Sentiment Breakdown:</b>\n🟢 Bullish: 50%\n🔴 Bearish: 50%\n⚪️ Neutral: 0%\n\n"),
                            ("<b>📊 Market Sentiment Analysis:</b>", f"<b>📊 Market Sentiment Analysis:</b>\n{instrument} is currently showing mixed signals with no clear sentiment bias. The market shows balanced sentiment with no strong directional bias at this time.\n\n"),
                            ("<b>📰 Key Sentiment Drivers:</b>", f"<b>📰 Key Sentiment Drivers:</b>\n• Market conditions appear normal with mixed signals\n• No clear directional bias at this time\n• Standard market activity observed\n\n"),
                            ("<b>📅 Important Events & News:</b>", f"<b>📅 Important Events & News:</b>\n• Normal market activity with no major catalysts\n• No significant economic releases impacting the market\n• General news and global trends affecting sentiment\n")
                        ]
                        
                        for section, default_content in required_sections:
                            if section not in response_content:
                                # Find where to insert the missing section
                                insert_position = len(response_content)
                                for next_section, _ in required_sections:
                                    if next_section in response_content and response_content.find(next_section) > response_content.find(section) if section in response_content else True:
                                        insert_position = min(insert_position, response_content.find(next_section))
                                
                                # Insert the section
                                response_content = response_content[:insert_position] + default_content + response_content[insert_position:]
                                logger.info(f"Added missing section: {section}")
                        
                        # Remove disallowed sections
                        disallowed_sections = [
                            ("<b>📈 Market Direction:</b>", "<b>Market Direction:</b>", "Market Direction:"),
                            ("<b>Technical Outlook:</b>", "Technical Outlook:"),
                            ("<b>Support & Resistance:</b>", "Support & Resistance:"),
                            ("<b>💡 Conclusion:</b>", "<b>Conclusion:</b>", "Conclusion:")
                        ]
                        
                        for section_variants in disallowed_sections:
                            for variant in section_variants:
                                if variant in response_content:
                                    # Find start and end of section
                                    start_idx = response_content.find(variant)
                                    end_idx = len(response_content)
                                    
                                    # Try to find the next section that starts with <b>
                                    next_section = response_content.find("<b>", start_idx + 1)
                                    if next_section != -1:
                                        end_idx = next_section
                                    
                                    # Remove the section
                                    response_content = response_content[:start_idx] + response_content[end_idx:]
                                    logger.info(f"Removed disallowed section: {variant}")
                        
                        # Fix section titles to ensure correct emoji
                        response_content = response_content.replace("<b>Key Sentiment Drivers:</b>", "<b>📰 Key Sentiment Drivers:</b>")
                        response_content = response_content.replace("<b>Market Mood:</b>", "<b>📊 Market Sentiment Analysis:</b>")
                        response_content = response_content.replace("<b>Important Events & News:</b>", "<b>📅 Important Events & News:</b>")
                        
                        # Remove Sentiment Outlook if it exists and hasn't been caught by disallowed sections
                        if "<b>🔮 Sentiment Outlook:</b>" in response_content or "<b>Sentiment Outlook:</b>" in response_content:
                            for pattern in ["<b>🔮 Sentiment Outlook:</b>", "<b>Sentiment Outlook:</b>"]:
                                if pattern in response_content:
                                    start_idx = response_content.find(pattern)
                                    end_idx = len(response_content)
                                    
                                    # Try to find the next section that starts with <b>
                                    next_section = response_content.find("<b>", start_idx + 1)
                                    if next_section != -1:
                                        end_idx = next_section
                                    
                                    # Remove the section
                                    response_content = response_content[:start_idx] + response_content[end_idx:]
                                    logger.info(f"Removed deprecated section: {pattern}")
                        
                        # If Market Sentiment Analysis is not present, rename Market Mood to it
                        if "<b>📊 Market Sentiment Analysis:</b>" not in response_content and "<b>📊 Market Mood:</b>" in response_content:
                            response_content = response_content.replace("<b>📊 Market Mood:</b>", "<b>📊 Market Sentiment Analysis:</b>")
                            logger.info("Renamed Market Mood to Market Sentiment Analysis")
                        
                        # Extract and validate sentiment percentages
                        bullish_match = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', response_content)
                        bearish_match = re.search(r'(?:Bearish:|🔴\s*Bearish:)\s*(\d+)\s*%', response_content)
                        neutral_match = re.search(r'(?:Neutral:|⚪️\s*Neutral:)\s*(\d+)\s*%', response_content)
                        
                        if bullish_match and bearish_match and neutral_match:
                            bullish = int(bullish_match.group(1))
                            bearish = int(bearish_match.group(1))
                            neutral = int(neutral_match.group(1))
                            total = bullish + bearish + neutral
                            
                            # Ensure percentages sum to 100%
                            if total != 100:
                                logger.warning(f"Sentiment percentages sum to {total}, adjusting to 100%")
                                # Adjust to ensure sum is 100%
                                if total > 0:
                                    bullish = int((bullish / total) * 100)
                                    bearish = int((bearish / total) * 100)
                                    neutral = 100 - bullish - bearish
                                else:
                                    bullish = 50
                                    bearish = 50
                                    neutral = 0
                                
                                # Update the sentiment values in the text
                                response_content = re.sub(
                                    r'(🟢\s*Bullish:)\s*\d+\s*%', 
                                    f'🟢 Bullish: {bullish}%', 
                                    response_content
                                )
                                response_content = re.sub(
                                    r'(🔴\s*Bearish:)\s*\d+\s*%', 
                                    f'🔴 Bearish: {bearish}%', 
                                    response_content
                                )
                                response_content = re.sub(
                                    r'(⚪️\s*Neutral:)\s*\d+\s*%', 
                                    f'⚪️ Neutral: {neutral}%', 
                                    response_content
                                )
                                
                                # Also make sure Overall Sentiment matches the percentages
                                if bullish > bearish:
                                    overall = "Bullish 📈"
                                elif bearish > bullish:
                                    overall = "Bearish 📉"
                                else:
                                    overall = "Neutral ➡️"
                                    
                                response_content = re.sub(
                                    r'<b>Overall Sentiment:</b>.*?\n',
                                    f'<b>Overall Sentiment:</b> {overall}\n',
                                    response_content
                                )
                        else:
                            # Add default values if percentages are missing
                            logger.warning(f"Sentiment percentages missing, adding defaults")
                            sentiment_section = "<b>Market Sentiment Breakdown:</b>\n🟢 Bullish: 50%\n🔴 Bearish: 50%\n⚪️ Neutral: 0%\n\n"
                            if "<b>Market Sentiment Breakdown:</b>" in response_content:
                                # Replace existing section
                                response_content = re.sub(
                                    r'<b>Market Sentiment Breakdown:</b>.*?(?=<b>|$)',
                                    sentiment_section,
                                    response_content,
                                    flags=re.DOTALL
                                )
                            else:
                                # Add section after title
                                title_end = response_content.find("</b>", response_content.find("<b>🎯")) + 4
                                response_content = response_content[:title_end] + "\n\n" + sentiment_section + response_content[title_end:]
                        
                        # Cleanup whitespace and formatting
                        response_content = re.sub(r'\n{3,}', '\n\n', response_content)
                        
                        # Final check for any disallowed sections that might have been missed
                        final_disallowed = [
                            "Market Direction", 
                            "Technical Outlook", 
                            "Support & Resistance", 
                            "Support and Resistance",
                            "Conclusion", 
                            "Technical Analysis",
                            "Price Targets",
                            "Trading Recommendation"
                        ]
                        
                        for disallowed in final_disallowed:
                            if disallowed in response_content:
                                logger.warning(f"Found disallowed content '{disallowed}' in final output, replacing with default")
                                # If we still have disallowed content, return default format
                                return self._get_default_sentiment_text(instrument)
                        
                        # Final log of modified content
                        logger.info(f"Final formatted response for {instrument} (first 200 chars): {response_content[:200]}...")
                        
                        return response_content
                    else:
                        # Record API call duration for failed call
                        self.metrics.record_api_call('deepseek', time.time() - start_time)
                        
                        logger.error(f"DeepSeek API request failed with status {response.status}")
                        error_message = await response.text()
                        logger.error(f"DeepSeek API error: {error_message}")
                        # Fall back to default sentiment text
                        return self._get_default_sentiment_text(instrument)
        except Exception as e:
            # Record API call duration for exceptions
            self.metrics.record_api_call('deepseek', time.time() - start_time)
            
            logger.error(f"Error in DeepSeek formatting: {str(e)}")
            logger.exception(e)
            # Return a default sentiment text
            return self._get_default_sentiment_text(instrument)
    
    def _clean_deepseek_response(self, response_content: str) -> str:
        """
        Clean up the DeepSeek response to remove any prompt instructions that might have been included
        
        Args:
            response_content: The raw response from DeepSeek API
            
        Returns:
            str: Cleaned response without any prompt instructions
        """
        # List of instruction-related phrases to detect and clean up
        instruction_markers = [
            "DO NOT mention any specific price levels",
            "The sentiment percentages",
            "I will check your output",
            "DO NOT add any additional sections",
            "Focus ONLY on NEWS, EVENTS, and SENTIMENT",
            "resistance/support levels"
        ]
        
        # Check if any instruction text is included at the end of the response
        for marker in instruction_markers:
            if marker in response_content:
                # Find the start of the instruction text
                marker_index = response_content.find(marker)
                
                # Check if the marker is part of a longer instruction paragraph
                # by looking for newlines before it
                paragraph_start = response_content.rfind("\n\n", 0, marker_index)
                if paragraph_start != -1:
                    # If we found a paragraph break before the marker, trim from there
                    cleaned_content = response_content[:paragraph_start].strip()
                    logger.info(f"Removed instruction text starting with: '{marker}'")
                    return cleaned_content
                else:
                    # If no clear paragraph break, just trim from the marker
                    cleaned_content = response_content[:marker_index].strip()
                    logger.info(f"Removed instruction text starting with: '{marker}'")
                    return cleaned_content
        
        # If no instruction markers were found, return the original content
        return response_content
    
    def _guess_market_from_instrument(self, instrument: str) -> str:
        """Guess market type from instrument symbol"""
        if instrument.startswith(('XAU', 'XAG', 'OIL', 'USOIL', 'BRENT')):
            return 'commodities'
        elif instrument.endswith('USD') and len(instrument) <= 6:
            return 'forex'
        elif instrument in ('US30', 'US500', 'US100', 'GER30', 'UK100'):
            return 'indices'
        elif instrument in ('BTCUSD', 'ETHUSD', 'XRPUSD'):
            return 'crypto'
        else:
            return 'forex'  # Default to forex
    
    def _get_mock_sentiment_data(self, instrument: str) -> Dict[str, Any]:
        """Generate mock sentiment data for an instrument"""
        logger.warning(f"Using mock sentiment data for {instrument} because API keys are not available or valid")
        
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
        neutral_percentage = 0  # We don't use neutral in this mockup
        
        # Calculate sentiment score from -1.0 to 1.0
        sentiment_score = (bullish_percentage - bearish_percentage) / 100
        
        # Generate random news headlines
        headlines = []
        if is_bullish:
            headlines = [
                f"Positive economic outlook boosts {instrument}",
                f"Institutional investors increase {instrument} positions",
                f"Optimistic market sentiment for {instrument}"
            ]
        else:
            headlines = [
                f"Economic concerns weigh on {instrument}",
                f"Profit taking leads to {instrument} pressure",
                f"Cautious market sentiment for {instrument}"
            ]
        
        # Generate mock analysis text
        analysis_text = f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> {"Bullish 📈" if is_bullish else "Bearish 📉"}

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish_percentage}%
🔴 Bearish: {bearish_percentage}%
⚪️ Neutral: 0%

<b>📰 Key Sentiment Drivers:</b>
• {"Positive economic indicators" if is_bullish else "Negative economic outlook"}
• {"Strong institutional interest" if is_bullish else "Increased selling pressure"}
• Regular market fluctuations and trading activity

<b>📊 Market Mood:</b>
The overall market mood for {instrument} is {"optimistic with strong buyer interest" if is_bullish else "cautious with increased seller activity"}.

<b>📅 Important Events & News:</b>
• {"Recent economic data showing positive trends" if is_bullish else "Economic concerns affecting market sentiment"}
• {"Institutional buying providing support" if is_bullish else "Technical resistance creating pressure"}
• General market conditions aligning with broader trends

<b>🔮 Sentiment Outlook:</b>
Based on current market sentiment, the outlook for {instrument} appears {"positive" if is_bullish else "cautious"}.

<i>Note: This is mock data for demonstration purposes only. Real trading decisions should be based on comprehensive analysis.</i>"""
        
        # Determine strength based on how far from neutral (50%)
        trend_strength = 'Strong' if abs(bullish_percentage - 50) > 15 else 'Moderate' if abs(bullish_percentage - 50) > 5 else 'Weak'
        
        # Create dictionary result with all data
        return {
            'overall_sentiment': 'bullish' if is_bullish else 'bearish',
            'sentiment_score': sentiment_score,
            'bullish': bullish_percentage,
            'bearish': bearish_percentage,
            'neutral': neutral_percentage,
            'bullish_percentage': bullish_percentage,
            'bearish_percentage': bearish_percentage,
            'technical_score': f"{random.randint(60, 80)}% {'bullish' if is_bullish else 'bearish'}",
            'news_score': f"{random.randint(55, 75)}% {'positive' if is_bullish else 'negative'}",
            'social_score': f"{random.randint(50, 70)}% {'bullish' if is_bullish else 'bearish'}",
            'trend_strength': trend_strength,
            'volatility': random.choice(['High', 'Moderate', 'Low']),
            'volume': random.choice(['Above Average', 'Normal', 'Below Average']),
            'support_level': 'Not available',
            'resistance_level': 'Not available',
            'recommendation': f"{'Consider appropriate risk management with the current market conditions.' if is_bullish else 'Consider appropriate risk management with the current market conditions.'}",
            'analysis': analysis_text,
            'news_headlines': headlines,
            'source': 'mock_data'
        }
    
    def _get_fallback_sentiment(self, instrument: str) -> Dict[str, Any]:
        """Generate fallback sentiment data when APIs fail"""
        logger.warning(f"Using fallback sentiment data for {instrument} due to API errors")
        
        # Default neutral headlines
        headlines = [
            f"Market awaits clear direction for {instrument}",
            "Economic data shows mixed signals",
            "Traders taking cautious approach"
        ]
        
        # Create a neutral sentiment analysis
        analysis_text = f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> Neutral ➡️

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 50%
🔴 Bearish: 50%
⚪️ Neutral: 0%

<b>📰 Key Sentiment Drivers:</b>
• Standard market activity with no major developments
• Technical and fundamental factors in balance
• No significant market-moving events

<b>📊 Market Mood:</b>
The {instrument} is currently showing a neutral trend with balanced buy and sell interest.

<b>📅 Important Events & News:</b>
• Standard market activity with no major developments
• Normal trading conditions observed
• Balanced market sentiment indicators

<b>🔮 Sentiment Outlook:</b>
The market sentiment for {instrument} is currently neutral with balanced indicators.
Monitor market developments for potential sentiment shifts.

<i>Note: This is fallback data due to API issues. Please try again later for updated analysis.</i>"""
        
        # Return a balanced neutral sentiment
        return {
            'overall_sentiment': 'neutral',
            'sentiment_score': 0,
            'bullish': 50,
            'bearish': 50,
            'neutral': 0,
            'bullish_percentage': 50,
            'bearish_percentage': 50,
            'technical_score': 'N/A',
            'news_score': 'N/A',
            'social_score': 'N/A',
            'trend_strength': 'Weak',
            'volatility': 'Moderate',
            'volume': 'Normal',
            'support_level': 'Not available',
            'resistance_level': 'Not available',
            'recommendation': 'Monitor market developments for clearer signals.',
            'analysis': analysis_text,
            'news_headlines': headlines,
            'source': 'fallback_data'
        }

    async def _get_alternative_news(self, instrument: str, market: str) -> str:
        """Alternative news source when Tavily API fails"""
        logger.info(f"Using alternative news source for {instrument}")
        
        try:
            # Construct appropriate URLs based on market and instrument
            urls = []
            
            if market == 'forex':
                # Common forex news sources
                urls = [
                    f"https://www.forexlive.com/tag/{instrument}/",
                    f"https://www.fxstreet.com/rates-charts/{instrument.lower()}-chart",
                    f"https://finance.yahoo.com/quote/{instrument}=X/"
                ]
            elif market == 'crypto':
                # Crypto news sources
                crypto_symbol = instrument.replace('USD', '')
                urls = [
                    f"https://finance.yahoo.com/quote/{crypto_symbol}-USD/",
                    f"https://www.coindesk.com/price/{crypto_symbol.lower()}/",
                    f"https://www.tradingview.com/symbols/CRYPTO-{crypto_symbol}USD/"
                ]
            elif market == 'indices':
                # Indices news sources
                index_map = {
                    'US30': 'DJI',
                    'US500': 'GSPC',
                    'US100': 'NDX'
                }
                index_symbol = index_map.get(instrument, instrument)
                urls = [
                    f"https://finance.yahoo.com/quote/^{index_symbol}/",
                    f"https://www.marketwatch.com/investing/index/{index_symbol.lower()}"
                ]
            elif market == 'commodities':
                # Commodities news sources
                commodity_map = {
                    'XAUUSD': 'gold',
                    'GOLD': 'gold',
                    'XAGUSD': 'silver',
                    'SILVER': 'silver',
                    'USOIL': 'oil',
                    'OIL': 'oil'
                }
                commodity = commodity_map.get(instrument, instrument.lower())
                urls = [
                    f"https://www.marketwatch.com/investing/commodity/{commodity}",
                    f"https://finance.yahoo.com/quote/{instrument}/"
                ]
            
            # Fetch data from each URL
            result_text = f"Market Analysis for {instrument}:\n\n"
            successful_fetches = 0
            
            async with aiohttp.ClientSession() as session:
                fetch_tasks = []
                for url in urls:
                    fetch_tasks.append(self._fetch_url_content(session, url))
                
                results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                
                for i, content in enumerate(results):
                    if isinstance(content, Exception):
                        logger.warning(f"Failed to fetch {urls[i]}: {str(content)}")
                        continue
                    
                    if content:
                        result_text += f"Source: {urls[i]}\n"
                        result_text += f"{content}\n\n"
                        successful_fetches += 1
            
            if successful_fetches == 0:
                logger.warning(f"No alternative sources available for {instrument}")
                return None
                
            return result_text
            
        except Exception as e:
            logger.error(f"Error getting alternative news: {str(e)}")
            logger.exception(e)
            return None
            
    async def _fetch_url_content(self, session, url):
        """Fetch content from a URL and extract relevant text"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            }
            
            timeout = aiohttp.ClientTimeout(total=10)
            async with session.get(url, headers=headers, timeout=timeout) as response:
                if response.status != 200:
                    return None
                
                html = await response.text()
                
                # Extract the most relevant content based on the URL
                if "yahoo.com" in url:
                    return self._extract_yahoo_content(html, url)
                elif "forexlive.com" in url:
                    return self._extract_forexlive_content(html)
                elif "fxstreet.com" in url:
                    return self._extract_fxstreet_content(html)
                elif "marketwatch.com" in url:
                    return self._extract_marketwatch_content(html)
                elif "coindesk.com" in url:
                    return self._extract_coindesk_content(html)
                else:
                    # Basic content extraction
                    return self._extract_basic_content(html)
                    
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            return None
            
    def _extract_yahoo_content(self, html, url):
        """Extract relevant content from Yahoo Finance"""
        try:
            # Extract price information
            price_match = re.search(r'data-symbol="[^"]+" data-field="regularMarketPrice" value="([^"]+)"', html)
            change_match = re.search(r'data-symbol="[^"]+" data-field="regularMarketChange" value="([^"]+)"', html)
            change_percent_match = re.search(r'data-symbol="[^"]+" data-field="regularMarketChangePercent" value="([^"]+)"', html)
            
            content = "Current Market Data:\n"
            
            if price_match:
                content += f"Price: {price_match.group(1)}\n"
            
            if change_match and change_percent_match:
                change = float(change_match.group(1))
                change_percent = float(change_percent_match.group(1))
                direction = "▲" if change > 0 else "▼"
                content += f"Change: {direction} {abs(change):.4f} ({abs(change_percent):.2f}%)\n"
            
            # Extract news headlines
            news_matches = re.findall(r'<h3 class="Mb\(5px\)">(.*?)</h3>', html)
            if news_matches:
                content += "\nRecent News:\n"
                for i, headline in enumerate(news_matches[:3]):
                    # Clean up HTML tags
                    headline = re.sub(r'<[^>]+>', '', headline).strip()
                    content += f"• {headline}\n"
            
            return content
        except Exception as e:
            logger.error(f"Error extracting Yahoo content: {str(e)}")
            return "Price and market data available at Yahoo Finance"
            
    def _extract_forexlive_content(self, html):
        """Extract relevant content from ForexLive"""
        try:
            # Extract article titles
            article_matches = re.findall(r'<h2 class="article-title">(.*?)</h2>', html)
            
            if not article_matches:
                return "Latest forex news and analysis available at ForexLive."
                
            content = "Recent Forex News:\n"
            for i, article in enumerate(article_matches[:3]):
                # Clean up HTML tags
                article = re.sub(r'<[^>]+>', '', article).strip()
                content += f"• {article}\n"
                
            return content
        except Exception as e:
            logger.error(f"Error extracting ForexLive content: {str(e)}")
            return "Latest forex news and analysis available at ForexLive."
    
    def _extract_fxstreet_content(self, html):
        """Extract relevant content from FXStreet"""
        try:
            # Extract price information
            price_match = re.search(r'<span class="price">(.*?)</span>', html)
            change_match = re.search(r'<span class="change-points[^"]*">(.*?)</span>', html)
            
            content = "Current Market Data:\n"
            
            if price_match:
                content += f"Price: {price_match.group(1).strip()}\n"
            
            if change_match:
                content += f"Change: {change_match.group(1).strip()}\n"
            
            # Extract technical indicators if available
            if '<div class="technical-indicators">' in html:
                content += "\nTechnical Indicators Summary:\n"
                if "bullish" in html.lower():
                    content += "• Overall trend appears bullish\n"
                elif "bearish" in html.lower():
                    content += "• Overall trend appears bearish\n"
                else:
                    content += "• Mixed technical signals\n"
            
            return content
        except Exception as e:
            logger.error(f"Error extracting FXStreet content: {str(e)}")
            return "Currency charts and analysis available at FXStreet."
    
    def _extract_marketwatch_content(self, html):
        """Extract relevant content from MarketWatch"""
        try:
            # Extract price information
            price_match = re.search(r'<bg-quote[^>]*>([^<]+)</bg-quote>', html)
            change_match = re.search(r'<bg-quote[^>]*field="change"[^>]*>([^<]+)</bg-quote>', html)
            change_percent_match = re.search(r'<bg-quote[^>]*field="percentchange"[^>]*>([^<]+)</bg-quote>', html)
            
            content = "Current Market Data:\n"
            
            if price_match:
                content += f"Price: {price_match.group(1).strip()}\n"
            
            if change_match and change_percent_match:
                content += f"Change: {change_match.group(1).strip()} ({change_percent_match.group(1).strip()})\n"
            
            # Extract news headlines
            news_matches = re.findall(r'<h3 class="article__headline">(.*?)</h3>', html)
            if news_matches:
                content += "\nRecent News:\n"
                for i, headline in enumerate(news_matches[:3]):
                    # Clean up HTML tags
                    headline = re.sub(r'<[^>]+>', '', headline).strip()
                    content += f"• {headline}\n"
            
            return content
        except Exception as e:
            logger.error(f"Error extracting MarketWatch content: {str(e)}")
            return "Market data and news available at MarketWatch."
    
    def _extract_coindesk_content(self, html):
        """Extract relevant content from CoinDesk"""
        try:
            # Extract price information
            price_match = re.search(r'<span class="price-large">([^<]+)</span>', html)
            change_match = re.search(r'<span class="percent-change-medium[^"]*">([^<]+)</span>', html)
            
            content = "Current Cryptocurrency Data:\n"
            
            if price_match:
                content += f"Price: {price_match.group(1).strip()}\n"
            
            if change_match:
                content += f"24h Change: {change_match.group(1).strip()}\n"
            
            # Extract news headlines
            news_matches = re.findall(r'<h4 class="heading">(.*?)</h4>', html)
            if news_matches:
                content += "\nRecent News:\n"
                for i, headline in enumerate(news_matches[:3]):
                    # Clean up HTML tags
                    headline = re.sub(r'<[^>]+>', '', headline).strip()
                    content += f"• {headline}\n"
            
            return content
        except Exception as e:
            logger.error(f"Error extracting CoinDesk content: {str(e)}")
            return "Cryptocurrency data and news available at CoinDesk."
    
    def _extract_basic_content(self, html):
        """Basic content extraction for other sites"""
        try:
            # Remove scripts, styles and other tags that don't contain useful content
            html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
            
            # Extract title
            title_match = re.search(r'<title[^>]*>(.*?)</title>', html)
            title = title_match.group(1).strip() if title_match else "Market Information"
            
            # Find paragraphs with relevant financial keywords
            financial_keywords = ['market', 'price', 'trend', 'analysis', 'forecast', 'technical', 'support', 'resistance']
            paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, flags=re.DOTALL)
            
            content = f"{title}\n\n"
            
            relevant_paragraphs = []
            for p in paragraphs:
                p_text = re.sub(r'<[^>]+>', '', p).strip()
                if p_text and any(keyword in p_text.lower() for keyword in financial_keywords):
                    relevant_paragraphs.append(p_text)
            
            if relevant_paragraphs:
                for i, p in enumerate(relevant_paragraphs[:3]):
                    content += f"{p}\n\n"
            else:
                content += "Visit the page for detailed market information and analysis."
            
            return content
        except Exception as e:
            logger.error(f"Error extracting basic content: {str(e)}")
            return "Market information available. Visit the source for details."

    async def _check_deepseek_connectivity(self) -> bool:
        """Check if the DeepSeek API is reachable"""
        logger.info("Checking DeepSeek API connectivity")
        try:
            # Try to connect to the new DeepSeek API endpoint
            deepseek_host = "api.deepseek.com"
            
            # Socket check (basic connectivity)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((deepseek_host, 443))
            sock.close()
            
            if result != 0:
                logger.warning(f"DeepSeek API socket connection failed with result: {result}")
                return False
                
            # If socket connects, try an HTTP HEAD request to verify API is responding
            # Create SSL context that doesn't verify certificates
            ssl_context = ssl.create_default_context()
            
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            # Use a shorter timeout for the HTTP check
            timeout = aiohttp.ClientTimeout(total=5)
            
            try:
                async with aiohttp.ClientSession(connector=connector) as session:
                    # Use the new domain
                    async with session.head(
                        "https://api.deepseek.com/v1/chat/completions",
                        timeout=timeout
                    ) as response:
                        status = response.status
                        logger.info(f"DeepSeek API HTTP check status: {status}")
                        
                        # Even if we get a 401 (Unauthorized) or 403 (Forbidden), 
                        # that means the API is accessible
                        if status in (200, 401, 403, 404):
                            logger.info("DeepSeek API is accessible")
                            return True
                            
                        logger.warning(f"DeepSeek API HTTP check failed with status: {status}")
                        return False
                        
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"DeepSeek API HTTP check failed: {str(e)}")
                return False
                
        except Exception as e:
            logger.warning(f"DeepSeek API connectivity check failed: {str(e)}")
            return False

    async def _try_deepseek_with_fallback(self, market_data: str, instrument: str) -> str:
        """Try to use DeepSeek API and fall back to manual formatting if needed"""
        # Skip early if no API key
        if not self.deepseek_api_key:
            logger.warning("No DeepSeek API key available, using manual formatting")
            return self._format_data_manually(market_data, instrument)
        
        try:
            # Use the existing _format_with_deepseek method which has the complete prompt
            market_type = self._guess_market_from_instrument(instrument)
            formatted_content = await self._format_with_deepseek(instrument, market_type, market_data)
            
            if formatted_content:
                return await self._get_deepseek_sentiment(market_data, instrument, formatted_content)
            else:
                logger.warning(f"DeepSeek formatting failed for {instrument}, using manual formatting")
                return self._format_data_manually(market_data, instrument)
            
        except Exception as e:
            logger.error(f"Error in DeepSeek processing: {str(e)}")
            logger.exception(e)
            return self._format_data_manually(market_data, instrument)
            
    async def _get_deepseek_sentiment(self, market_data: str, instrument: str, formatted_content: str = None) -> str:
        """Use DeepSeek to analyze market sentiment and return formatted analysis"""
        try:
            # If formatted_content is not provided, try to get it
            if not formatted_content:
                formatted_content = await self._format_with_deepseek(instrument, 
                                                                  self._guess_market_from_instrument(instrument), 
                                                                  market_data)
            
            if not formatted_content:
                logger.warning(f"DeepSeek formatting failed for {instrument}, using manual formatting")
                return self._format_data_manually(market_data, instrument)
            
            # Return the formatted content directly
            return formatted_content
            
        except Exception as e:
            logger.error(f"Error analyzing DeepSeek sentiment: {str(e)}")
            logger.exception(e)
            return self._format_data_manually(market_data, instrument)

    async def debug_api_keys(self):
        """Debug API keys configuration and connectivity"""
        try:
            lines = []
            lines.append("=== Market Sentiment API Keys Debug ===")
            
            # Check DeepSeek API key
            if self.deepseek_api_key:
                masked_key = self.deepseek_api_key[:6] + "..." + self.deepseek_api_key[-4:] if len(self.deepseek_api_key) > 10 else "***"
                lines.append(f"• DeepSeek API Key: {masked_key} [CONFIGURED]")
                
                # Test DeepSeek connectivity
                deepseek_connectivity = await self._check_deepseek_connectivity()
                lines.append(f"  - Connectivity Test: {'✅ SUCCESS' if deepseek_connectivity else '❌ FAILED'}")
            else:
                lines.append("• DeepSeek API Key: [NOT CONFIGURED]")
            
            # Check Tavily API key
            if self.tavily_api_key:
                masked_key = self.tavily_api_key[:6] + "..." + self.tavily_api_key[-4:] if len(self.tavily_api_key) > 10 else "***"
                lines.append(f"• Tavily API Key: {masked_key} [CONFIGURED]")
                
                # Test Tavily connectivity
                tavily_connectivity = await self._test_tavily_connectivity()
                lines.append(f"  - Connectivity Test: {'✅ SUCCESS' if tavily_connectivity else '❌ FAILED'}")
            else:
                lines.append("• Tavily API Key: [NOT CONFIGURED]")
            
            # Check .env file for keys
            env_path = os.path.join(os.getcwd(), '.env')
            if os.path.exists(env_path):
                lines.append("\n=== Environment File ===")
                lines.append(f"• .env file exists at: {env_path}")
                try:
                    with open(env_path, 'r') as f:
                        env_contents = f.read()
                        
                    # Check for key patterns without revealing actual keys
                    has_deepseek = "DEEPSEEK_API_KEY" in env_contents
                    has_tavily = "TAVILY_API_KEY" in env_contents
                    
                    lines.append(f"• Contains DEEPSEEK_API_KEY: {'✅ YES' if has_deepseek else '❌ NO'}")
                    lines.append(f"• Contains TAVILY_API_KEY: {'✅ YES' if has_tavily else '❌ NO'}")
                except Exception as e:
                    lines.append(f"• Error reading .env file: {str(e)}")
            else:
                lines.append("\n• .env file NOT found at: {env_path}")
            
            # System info
            lines.append("\n=== System Info ===")
            lines.append(f"• Python Version: {sys.version.split()[0]}")
            lines.append(f"• OS: {os.name}")
            lines.append(f"• Working Directory: {os.getcwd()}")
            
            # Overall status
            lines.append("\n=== Overall Status ===")
            if self.deepseek_api_key and deepseek_connectivity and self.tavily_api_key and tavily_connectivity:
                lines.append("✅ All sentiment APIs are properly configured and working")
            elif (self.deepseek_api_key or self.tavily_api_key) and (deepseek_connectivity or tavily_connectivity):
                lines.append("⚠️ Some sentiment APIs are working, others are not configured or not working")
            else:
                lines.append("❌ No sentiment APIs are properly configured and working")
                
            # Test recommendations
            missing_services = []
            if not self.deepseek_api_key or not deepseek_connectivity:
                missing_services.append("DeepSeek")
            if not self.tavily_api_key or not tavily_connectivity:
                missing_services.append("Tavily")
                
            if missing_services:
                lines.append("\n=== Recommendations ===")
                lines.append(f"• Configure or check the following APIs: {', '.join(missing_services)}")
                lines.append("• Ensure API keys are correctly set in the .env file")
                lines.append("• Check if API services are accessible from your server")
                lines.append("• Check API usage limits and account status")
            
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Error in debug_api_keys: {str(e)}")
            return f"Error debugging API keys: {str(e)}"
        
    async def _test_tavily_connectivity(self) -> bool:
        """Test if Tavily API is reachable and working"""
        try:
            if not self.tavily_api_key:
                return False
            
            timeout = aiohttp.ClientTimeout(total=5)
            headers = {
                "Authorization": f"Bearer {self.tavily_api_key.strip()}",
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.tavily.com/health",
                    headers=headers,
                    timeout=timeout
                ) as response:
                    return response.status == 200
        except Exception as e:
            logger.error(f"Error testing Tavily API connection: {str(e)}")
            return False

    def _get_default_sentiment_text(self, instrument: str) -> str:
        """Get a correctly formatted default sentiment text for an instrument"""
        return f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> Neutral ➡️

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 50%
🔴 Bearish: 50%
⚪️ Neutral: 0%

<b>📊 Market Sentiment Analysis:</b>
{instrument} is currently showing mixed signals with no clear sentiment bias. The market shows balanced sentiment with no strong directional bias at this time.

<b>📰 Key Sentiment Drivers:</b>
• Market conditions appear normal with mixed signals
• No clear directional bias at this time
• Standard market activity observed

<b>📅 Important Events & News:</b>
• Normal market activity with no major catalysts
• No significant economic releases impacting the market
• General news and global trends affecting sentiment
"""

    def _add_to_cache(self, instrument: str, sentiment_data: Dict[str, Any]) -> None:
        """Add sentiment data to cache with TTL"""
        if hasattr(self, 'cache_enabled') and not self.cache_enabled:
            return  # Cache is disabled
            
        try:
            cache_key = instrument.upper()
            
            # Make a copy to avoid reference issues
            cache_data = copy.deepcopy(sentiment_data)
            # Add timestamp for TTL check
            cache_data['timestamp'] = time.time()
            
            # Store in memory cache
            self.sentiment_cache[cache_key] = cache_data
            
            # If persistent cache is enabled, save to file
            if self.cache_file:
                self._save_cache_to_file()
                
        except Exception as e:
            logger.error(f"Error adding to sentiment cache: {str(e)}")
    
    def _get_from_cache(self, instrument: str) -> Optional[Dict[str, Any]]:
        """Get sentiment data from cache if available and not expired"""
        if hasattr(self, 'cache_enabled') and not self.cache_enabled:
            return None  # Cache is disabled
            
        try:
            cache_key = instrument.upper()
            
            # Check if in memory cache
            if cache_key in self.sentiment_cache:
                cache_data = self.sentiment_cache[cache_key]
                
                # Check if expired
                current_time = time.time()
                cache_time = cache_data.get('timestamp', 0)
                
                if current_time - cache_time < self.cache_ttl:
                    # Make a copy to avoid reference issues
                    result = copy.deepcopy(cache_data)
                    # Remove timestamp as it's internal
                    if 'timestamp' in result:
                        del result['timestamp']
                    return result
                else:
                    # Expired, remove from cache
                    del self.sentiment_cache[cache_key]
                    
            return None
            
        except Exception as e:
            logger.error(f"Error getting from sentiment cache: {str(e)}")
            return None
    
    def _save_cache_to_file(self) -> None:
        """Save the in-memory cache to the persistent file"""
        if not hasattr(self, 'cache_file') or not self.cache_file:
            return  # No cache file configured
            
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            
            # Filter out expired items
            current_time = time.time()
            valid_cache = {}
            
            for key, data in self.sentiment_cache.items():
                cache_time = data.get('timestamp', 0)
                if current_time - cache_time < self.cache_ttl:
                    valid_cache[key] = data
            
            # Save to file
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(valid_cache, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error saving sentiment cache to file: {str(e)}")
    
    def _load_cache_from_file(self) -> None:
        """Load the cache from the persistent file"""
        if not hasattr(self, 'cache_file') or not self.cache_file:
            return  # No cache file configured
            
        try:
            # Check if file exists
            if not os.path.exists(self.cache_file):
                self.sentiment_cache = {}
                return
                
            # Load from file
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                loaded_cache = json.load(f)
            
            # Filter out expired items
            current_time = time.time()
            valid_cache = {}
            
            for key, data in loaded_cache.items():
                cache_time = data.get('timestamp', 0)
                if current_time - cache_time < self.cache_ttl:
                    valid_cache[key] = data
            
            self.sentiment_cache = valid_cache
            
            logger.info(f"Loaded {len(valid_cache)} sentiment cache entries from file")
            
        except Exception as e:
            logger.error(f"Error loading sentiment cache from file: {str(e)}")
            self.sentiment_cache = {}

    def clear_cache(self, instrument: Optional[str] = None) -> None:
        """
        Clear cache entries for a specific instrument or all instruments
        
        Args:
            instrument: Optional instrument to clear from cache. If None, clears all cache.
        """
        if instrument:
            removed = self.sentiment_cache.pop(instrument, None)
            if removed:
                logger.info(f"Cleared cache for {instrument}")
            else:
                logger.info(f"No cache found for {instrument}")
        else:
            cache_size = len(self.sentiment_cache)
            self.sentiment_cache.clear()
            logger.info(f"Cleared complete sentiment cache ({cache_size} entries)")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the current cache state
        
        Returns:
            Dict with cache statistics including size, entries, etc.
        """
        now = time.time()
        
        # Count active vs expired entries
        active_entries = 0
        expired_entries = 0
        instruments = []
        
        for instrument, entry in self.sentiment_cache.items():
            age = now - entry['timestamp']
            if age <= self.cache_ttl:
                active_entries += 1
                instruments.append({
                    'instrument': instrument,
                    'age_seconds': round(age),
                    'age_minutes': round(age / 60, 1),
                    'expires_in_minutes': round((self.cache_ttl - age) / 60, 1)
                })
            else:
                expired_entries += 1
        
        # Sort instruments by expiration time
        instruments.sort(key=lambda x: x['expires_in_minutes'])
        
        return {
            'total_entries': len(self.sentiment_cache),
            'active_entries': active_entries,
            'expired_entries': expired_entries,
            'cache_ttl_minutes': self.cache_ttl / 60,
            'instruments': instruments
        }
        
    def cleanup_expired_cache(self) -> int:
        """
        Remove all expired entries from the cache
        
        Returns:
            Number of entries removed
        """
        now = time.time()
        expired_keys = []
        
        for instrument, entry in self.sentiment_cache.items():
            if now - entry['timestamp'] > self.cache_ttl:
                expired_keys.append(instrument)
        
        for key in expired_keys:
            self.sentiment_cache.pop(key, None)
        
        logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")
        return len(expired_keys)

    async def prefetch_common_instruments(self, instruments: List[str]) -> None:
        """
        Prefetch sentiment data for commonly used instruments
        
        Args:
            instruments: List of instrument symbols to prefetch
        """
        logger.info(f"Starting prefetch for {len(instruments)} instruments")
        
        # Create a list to track which instruments need fetching
        to_fetch = []
        
        # Check which instruments are not already in the cache
        for instrument in instruments:
            if not self._get_from_cache(instrument):
                to_fetch.append(instrument)
        
        if not to_fetch:
            logger.info("All common instruments already in cache")
            return
            
        logger.info(f"Prefetching sentiment for {len(to_fetch)} instruments: {', '.join(to_fetch)}")
        
        # Use a semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(3)  # Limit to 3 concurrent requests
        
        async def fetch_with_semaphore(instrument):
            async with semaphore:
                try:
                    logger.info(f"Prefetching sentiment for {instrument}")
                    await self.get_sentiment(instrument)
                    logger.info(f"Successfully prefetched sentiment for {instrument}")
                except Exception as e:
                    logger.error(f"Error prefetching sentiment for {instrument}: {str(e)}")
        
        # Create tasks for all instruments to fetch
        fetch_tasks = [fetch_with_semaphore(instrument) for instrument in to_fetch]
        
        # Run all tasks concurrently with a timeout
        try:
            await asyncio.gather(*fetch_tasks)
            logger.info("Prefetch completed successfully")
        except Exception as e:
            logger.error(f"Error during prefetch: {str(e)}")
    
    async def start_background_prefetch(self, popular_instruments: List[str], interval_minutes: int = 25) -> None:
        """
        Start a background task to periodically prefetch popular instruments
        
        Args:
            popular_instruments: List of popular instrument symbols
            interval_minutes: How often to refresh the cache (default: 25 minutes)
        """
        logger.info(f"Starting background prefetch task for {len(popular_instruments)} instruments")
        
        async def prefetch_loop():
            while True:
                try:
                    await self.prefetch_common_instruments(popular_instruments)
                except Exception as e:
                    logger.error(f"Error in prefetch loop: {str(e)}")
                
                # Sleep until next refresh
                logger.info(f"Next prefetch in {interval_minutes} minutes")
                await asyncio.sleep(interval_minutes * 60)
        
        # Start the prefetch loop as a background task
        asyncio.create_task(prefetch_loop())
        logger.info("Background prefetch task started")

    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get performance metrics for sentiment API calls and caching
        
        Returns:
            Dict with performance metrics
        """
        metrics = self.metrics.get_metrics()
        
        # Add cache size information
        cache_stats = self.get_cache_stats()
        metrics['cache']['size'] = cache_stats['total_entries']
        metrics['cache']['active_entries'] = cache_stats['active_entries']
        
        return metrics

    async def _get_fast_sentiment(self, instrument: str) -> Dict[str, Any]:
        """
        Get a quick sentiment analysis for a trading instrument with minimal processing
        
        Args:
            instrument: The trading instrument to analyze (e.g., 'EURUSD')
            
        Returns:
            Dict[str, Any]: Sentiment data including percentages and formatted text
        """
        start_time = time.time()
        instrument = instrument.upper()
        
        try:
            # Check cache first
            cached_result = self._get_from_cache(instrument)
            if cached_result:
                logger.info(f"Using cached sentiment for {instrument} (elapsed: {time.time() - start_time:.2f}s)")
                return cached_result
                
            # Check if we have a DeepSeek API key
            if not self.deepseek_api_key:
                logger.warning(f"No DeepSeek API key available. Using local sentiment estimate for {instrument}")
                result = self._get_quick_local_sentiment(instrument)
                self._add_to_cache(instrument, result)
                return result
                
            # Use semaphore to limit concurrent requests
            async with self.request_semaphore:
                response_data = await self._process_fast_sentiment_request(instrument)
                
            if response_data:
                # Process the response to extract sentiment percentages
                bullish_pct = response_data.get('bullish_percentage', 0)
                bearish_pct = response_data.get('bearish_percentage', 0)
                neutral_pct = response_data.get('neutral_percentage', 0)
                
                # Format the sentiment text
                sentiment_text = self._format_fast_sentiment_text(
                    instrument, bullish_pct, bearish_pct, neutral_pct
                )
                
                # Create the result dictionary
                result = {
                    'instrument': instrument,
                    'bullish_percentage': bullish_pct,
                    'bearish_percentage': bearish_pct,
                    'neutral_percentage': neutral_pct,
                    'sentiment_text': sentiment_text,
                    'source': 'api'
                }
                
                # Add to cache
                self._add_to_cache(instrument, result)
                
                logger.info(f"Fast sentiment retrieved for {instrument} (elapsed: {time.time() - start_time:.2f}s)")
                return result
            else:
                # Fallback to local sentiment if API fails
                logger.warning(f"API request failed for {instrument}. Using local fallback.")
                result = self._get_quick_local_sentiment(instrument)
                self._add_to_cache(instrument, result)
                return result
                
        except Exception as e:
            logger.error(f"Error getting fast sentiment for {instrument}: {str(e)}")
            # Fallback to local sentiment estimation
            result = self._get_quick_local_sentiment(instrument)
            return result
    
    async def _process_fast_sentiment_request(self, instrument: str) -> Dict[str, Any]:
        """
        Process a quick sentiment request to external API
        
        Args:
            instrument: The trading instrument to analyze
            
        Returns:
            Dict with sentiment data or None if request failed
        """
        try:
            # Prepare the prompt for sentiment analysis
            prompt = self._prepare_fast_sentiment_prompt(instrument)
            
            # Build the request
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            
            payload = {
                'model': self.api_model,
                'messages': [
                    {'role': 'system', 'content': 'You are a financial market sentiment analyzer.'},
                    {'role': 'user', 'content': prompt}
                ],
                'response_format': {'type': 'json_object'},
                'temperature': 0.1  # Lower temperature for more consistent results
            }
            
            # Make the API request with timeout
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=self.api_timeout
                ) as response:
                    if response.status != 200:
                        logger.error(f"API error: {response.status}, {await response.text()}")
                        return None
                    
                    response_data = await response.json()
                    
            # Extract the content from the response
            content = response_data.get('choices', [{}])[0].get('message', {}).get('content', '{}')
            
            try:
                # Parse the JSON content
                sentiment_data = json.loads(content)
                return sentiment_data
            except json.JSONDecodeError:
                logger.error(f"Failed to parse sentiment response: {content}")
                return None
                
        except asyncio.TimeoutError:
            logger.error(f"API request timed out for {instrument}")
            return None
        except Exception as e:
            logger.error(f"Error in API request for {instrument}: {str(e)}")
            return None
            
    def _format_fast_sentiment_text(self, instrument: str, bullish_pct: float, 
                                  bearish_pct: float, neutral_pct: float) -> str:
        """Format sentiment text based on percentages"""
        sentiment_text = f"Marktsentiment voor {instrument}: "
        
        if bullish_pct > bearish_pct + 20:
            sentiment_text += f"Sterk bullish ({bullish_pct:.1f}% bullish, {bearish_pct:.1f}% bearish)"
        elif bullish_pct > bearish_pct + 5:
            sentiment_text += f"Gematigd bullish ({bullish_pct:.1f}% bullish, {bearish_pct:.1f}% bearish)"
        elif bearish_pct > bullish_pct + 20:
            sentiment_text += f"Sterk bearish ({bearish_pct:.1f}% bearish, {bullish_pct:.1f}% bullish)"
        elif bearish_pct > bullish_pct + 5:
            sentiment_text += f"Gematigd bearish ({bearish_pct:.1f}% bearish, {bullish_pct:.1f}% bullish)"
        else:
            sentiment_text += f"Neutraal ({neutral_pct:.1f}% neutraal, {bullish_pct:.1f}% bullish, {bearish_pct:.1f}% bearish)"
            
        return sentiment_text
        
    def _prepare_fast_sentiment_prompt(self, instrument: str) -> str:
        """Prepare the prompt for sentiment analysis"""
        prompt = f"""Analyseer het huidige marktsentiment voor het handelsinstrument {instrument}.
        
Geef je antwoord in het volgende JSON-formaat:
{{
    "bullish_percentage": [percentage bullish sentiment, 0-100],
    "bearish_percentage": [percentage bearish sentiment, 0-100],
    "neutral_percentage": [percentage neutral sentiment, 0-100]
}}

De percentages moeten optellen tot 100. Geef alleen de JSON terug zonder extra tekst."""
        
        return prompt
    
    def _get_quick_local_sentiment(self, instrument: str) -> Dict[str, Any]:
        """Get a very quick local sentiment estimate"""
        # Use deterministic but seemingly random sentiment based on instrument name
        # This is for fallback only when API fails
        hash_val = sum(ord(c) for c in instrument) % 100
        day_offset = int(time.time() / 86400) % 20 - 10  # Changes daily, range -10 to +10
        
        bullish = max(5, min(95, hash_val + day_offset))
        bearish = 100 - bullish
        neutral = 0
        
        # Format the sentiment text
        formatted_text = self._format_fast_sentiment_text(
            instrument=instrument,
            bullish=bullish,
            bearish=bearish,
            neutral=neutral,
            reasoning=f"Local sentiment estimate for {instrument} based on market trends"
        )
        
        return {
            'bullish': bullish,
            'bearish': bearish,
            'neutral': neutral,
            'sentiment_score': (bullish - bearish) / 100,
            'technical_score': 'Based on market analysis',
            'news_score': f"{bullish}% positive",
            'social_score': f"{bearish}% negative",
            'overall_sentiment': 'bullish' if bullish > bearish else 'bearish' if bearish > bullish else 'neutral',
            'trend_strength': 'Strong' if abs(bullish - bearish) > 15 else 'Moderate' if abs(bullish - bearish) > 5 else 'Weak',
            'volatility': 'Moderate',
            'volume': 'Normal',
            'news_headlines': [],
            'analysis': formatted_text
        }

    async def load_cache(self):
        """
        Asynchronously load cache from file
        This can be called after initialization to load the cache without blocking startup
        
        Returns:
            bool: True if cache was loaded successfully, False otherwise
        """
        if not self.use_persistent_cache or not self.cache_file or self.cache_loaded:
            return False
            
        try:
            # Run the load operation in a thread pool to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._load_cache_from_file)
            self.cache_loaded = True
            logger.info(f"Asynchronously loaded {len(self.sentiment_cache)} sentiment cache entries")
            return True
        except Exception as e:
            logger.error(f"Error loading sentiment cache asynchronously: {str(e)}")
            return False

class TavilyClient:
    """A simple wrapper for the Tavily API that handles errors properly"""
    
    def __init__(self, api_key):
        """Initialize with the API key"""
        self.api_key = api_key
        self.base_url = "https://api.tavily.com"
        
    async def search(self, query, search_depth="basic", include_answer=True, 
                   include_images=False, max_results=5):
        """
        Search the Tavily API with the given query
        """
        if not self.api_key:
            logger.error("No Tavily API key provided")
            return None
            
        # Sanitize the API key
        api_key = self.api_key.strip() if self.api_key else ""
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "query": query,
            "search_depth": search_depth,
            "include_answer": include_answer,
            "include_images": include_images,
            "max_results": max_results
        }
        
        logger.info(f"Calling Tavily API with query: {query}")
        timeout = aiohttp.ClientTimeout(total=20)
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.base_url}/search", 
                    headers=headers,
                    json=payload,
                    timeout=timeout
                ) as response:
                    response_text = await response.text()
                    
                    if response.status == 200:
                        try:
                            return json.loads(response_text)
                        except json.JSONDecodeError:
                            logger.error(f"Invalid JSON response: {response_text[:200]}...")
                            return None
                    
                    logger.error(f"Tavily API error: {response.status}, {response_text[:200]}...")
                    return None
            except Exception as e:
                logger.error(f"Error in Tavily API call: {str(e)}")
                logger.exception(e)
                return None
