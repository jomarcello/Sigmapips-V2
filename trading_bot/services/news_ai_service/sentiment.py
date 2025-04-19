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
    
    def __init__(self, cache_ttl_minutes: int = 30, persistent_cache: bool = True, cache_file: str = None, fast_mode: bool = False):
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
        
        # Initialize cache settings
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
        
        # Defer cache loading to async method
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
            # In standard mode, we still need a semaphore
            self.request_semaphore = asyncio.Semaphore(3)
        
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
            # Use fast mode for all sentiment requests
            result = await self._get_fast_sentiment(instrument)
            # Record total request time
            self.metrics.record_total_request(time.time() - start_time)
            return result
            
        except Exception as e:
            logger.error(f"Error in get_sentiment: {str(e)}")
            logger.exception(e)
            # Return a basic sentiment result compatible with fast_mode
            logger.error(f"Returning error result for {instrument} due to exception")
            try:
                # Try to get a local sentiment result
                return self._get_quick_local_sentiment(instrument)
            except Exception as inner_e:
                logger.error(f"Error in fallback local sentiment: {str(inner_e)}")
                # Final fallback with hardcoded values if everything fails
                return {
                    'instrument': instrument,
                    'bullish_percentage': 50,
                    'bearish_percentage': 50,
                    'neutral_percentage': 0,
                    'sentiment_text': f"Neutraal sentiment voor {instrument} (50% bullish, 50% bearish)",
                    'source': 'error_fallback',
                    'overall_sentiment': 'neutral',
                    'analysis': f"<b>🎯 {instrument} Marktanalyse</b>\n\n<b>Overall Sentiment:</b> Neutral ⚖️\n\n<b>Market Sentiment Breakdown:</b>\n🟢 Bullish: 50%\n🔴 Bearish: 50%\n⚪️ Neutral: 0%\n\n<b>📰 Key Sentiment Drivers:</b>\nAlgemene markttrends zonder duidelijke richting\n\n<b>📊 Market Mood:</b>\nNeutrale marktomstandigheden"
                }
    
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
            return final_analysis
        except Exception as e:
            logger.error(f"Error in market sentiment analysis: {str(e)}")
            logger.exception(e)
            return None
    
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
            try:
                async with self.request_semaphore:
                    response_data = await self._process_fast_sentiment_request(instrument)
            except Exception as e:
                logger.error(f"Error during API request for {instrument}: {str(e)}")
                response_data = None
                
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
            try:
                result = self._get_quick_local_sentiment(instrument)
                return result
            except Exception as inner_e:
                logger.error(f"Error in fallback local sentiment: {str(inner_e)}")
                # Final hardcoded fallback
                return {
                    'instrument': instrument,
                    'bullish_percentage': 50,
                    'bearish_percentage': 50,
                    'neutral_percentage': 0,
                    'sentiment_text': f"Neutraal sentiment voor {instrument} (50% bullish, 50% bearish)",
                    'source': 'error_fallback',
                    'overall_sentiment': 'neutral',
                    'analysis': f"<b>🎯 {instrument} Marktanalyse</b>\n\n<b>Overall Sentiment:</b> Neutral ⚖️\n\n<b>Market Sentiment Breakdown:</b>\n🟢 Bullish: 50%\n🔴 Bearish: 50%\n⚪️ Neutral: 0%\n\n<b>📰 Key Sentiment Drivers:</b>\nAlgemene markttrends zonder duidelijke richting\n\n<b>📊 Market Mood:</b>\nNeutrale marktomstandigheden"
                }
    
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
                'Authorization': f'Bearer {self.deepseek_api_key}'
            }
            
            payload = {
                'model': 'deepseek-chat',
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
                    self.deepseek_url,
                    headers=headers,
                    json=payload,
                    timeout=self.request_timeout
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
        
        bullish_pct = max(5, min(95, hash_val + day_offset))
        bearish_pct = max(5, min(95, 100 - bullish_pct - 10))  # Add some neutral sentiment
        neutral_pct = 100 - bullish_pct - bearish_pct
        
        # Format the sentiment text
        formatted_text = self._format_fast_sentiment_text(
            instrument=instrument,
            bullish_pct=bullish_pct,
            bearish_pct=bearish_pct,
            neutral_pct=neutral_pct
        )
        
        return {
            'instrument': instrument,
            'bullish_percentage': bullish_pct,
            'bearish_percentage': bearish_pct,
            'neutral_percentage': neutral_pct,
            'sentiment_text': formatted_text,
            'source': 'local',
            'overall_sentiment': 'bullish' if bullish_pct > bearish_pct else 'bearish' if bearish_pct > bullish_pct else 'neutral',
            'trend_strength': 'Strong' if abs(bullish_pct - bearish_pct) > 15 else 'Moderate' if abs(bullish_pct - bearish_pct) > 5 else 'Weak',
            'volatility': 'Moderate',
            'volume': 'Normal',
            'analysis': f"<b>🎯 {instrument} Marktanalyse</b>\n\n<b>Overall Sentiment:</b> {'Bullish 📈' if bullish_pct > bearish_pct else 'Bearish 📉' if bearish_pct > bullish_pct else 'Neutral ⚖️'}\n\n<b>Market Sentiment Breakdown:</b>\n🟢 Bullish: {bullish_pct}%\n🔴 Bearish: {bearish_pct}%\n⚪️ Neutral: {neutral_pct}%\n\n<b>📰 Key Sentiment Drivers:</b>\nAlgemene markttrends en economische factoren\n\n<b>📊 Market Mood:</b>\nHuidige marktstemming toont {'positieve' if bullish_pct > bearish_pct else 'negatieve' if bearish_pct > bullish_pct else 'neutrale'} signalen"
        }

    def _load_cache_from_file(self) -> None:
        """
        Load sentiment cache from disk file
        """
        if not self.use_persistent_cache or not self.cache_file:
            logger.warning("Cannot load cache: persistent caching is disabled or no cache file specified")
            return
            
        try:
            # Check if file exists
            if not self.cache_file.exists():
                logger.info(f"Cache file not found at {self.cache_file}")
                return
                
            # Load cache data
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
                
            # Process and filter cached data
            now = time.time()
            count_total = 0
            count_loaded = 0
            count_expired = 0
            
            if data and isinstance(data, dict):
                for instrument, cache_entry in data.items():
                    count_total += 1
                    
                    # Skip if entry is malformed
                    if not isinstance(cache_entry, dict) or 'timestamp' not in cache_entry or 'data' not in cache_entry:
                        continue
                        
                    # Check if entry is expired
                    timestamp = cache_entry.get('timestamp', 0)
                    if now - timestamp > self.cache_ttl:
                        count_expired += 1
                        continue
                        
                    # Add valid entry to cache
                    self.sentiment_cache[instrument] = cache_entry
                    count_loaded += 1
                    
            logger.info(f"Loaded {count_loaded} sentiment cache entries from {self.cache_file}")
            if count_expired > 0:
                logger.info(f"Skipped {count_expired} expired cache entries")
                
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading sentiment cache from {self.cache_file}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error loading sentiment cache: {str(e)}")
    
    def _get_from_cache(self, instrument: str) -> Optional[Dict[str, Any]]:
        """
        Get sentiment data from cache if available and not expired
        
        Args:
            instrument: The instrument to get data for
            
        Returns:
            Dict with sentiment data or None if not available/expired
        """
        if not instrument or not isinstance(instrument, str):
            return None
            
        instrument = instrument.upper()
        
        # Check if we have this instrument in cache
        if instrument not in self.sentiment_cache:
            return None
            
        cache_entry = self.sentiment_cache[instrument]
        
        # Check if entry is valid
        if not isinstance(cache_entry, dict) or 'data' not in cache_entry or 'timestamp' not in cache_entry:
            # Invalid entry, remove it
            del self.sentiment_cache[instrument]
            return None
            
        # Check if entry is expired
        timestamp = cache_entry.get('timestamp', 0)
        if time.time() - timestamp > self.cache_ttl:
            # Expired entry, remove it
            del self.sentiment_cache[instrument]
            return None
            
        # Return the cached data
        return cache_entry.get('data')
    
    def _add_to_cache(self, instrument: str, data: Dict[str, Any]) -> None:
        """
        Add sentiment data to cache
        
        Args:
            instrument: The instrument to cache data for
            data: The sentiment data to cache
        """
        if not instrument or not isinstance(instrument, str) or not data:
            return
            
        instrument = instrument.upper()
        
        # Create cache entry
        cache_entry = {
            'data': data,
            'timestamp': time.time()
        }
        
        # Add to cache
        self.sentiment_cache[instrument] = cache_entry
        
        # Save cache to disk if persistent caching is enabled
        if self.use_persistent_cache and self.cache_file:
            # Use background thread to avoid blocking
            threading.Thread(
                target=self._save_cache_to_file,
                name=f"cache_save_{instrument}",
                daemon=True
            ).start()
    
    def _save_cache_to_file(self) -> None:
        """
        Save the current cache to disk file
        This is called in a background thread to avoid blocking
        """
        if not self.use_persistent_cache or not self.cache_file:
            return
            
        # Use lock to prevent multiple saves at once
        if not self._cache_lock.acquire(blocking=False):
            logger.debug("Cache save already in progress, skipping")
            return
            
        try:
            # Create directory if needed
            os.makedirs(self.cache_file.parent, exist_ok=True)
            
            # Write cache to file
            with open(self.cache_file, 'w') as f:
                json.dump(self.sentiment_cache, f)
                
            logger.debug(f"Saved {len(self.sentiment_cache)} sentiment cache entries to {self.cache_file}")
        except Exception as e:
            logger.error(f"Error saving sentiment cache to file: {str(e)}")
        finally:
            self._cache_lock.release()
    
    def _guess_market_from_instrument(self, instrument: str) -> str:
        """
        Try to determine the market type from the instrument name
        
        Args:
            instrument: The instrument name (e.g., 'EURUSD')
            
        Returns:
            str: Market type (forex, crypto, indices, commodities)
        """
        instrument = instrument.upper() if instrument else ""
        
        # Check for common forex pairs
        forex_pairs = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD']
        if len(instrument) == 6 and any(instrument.startswith(pair) for pair in forex_pairs) and any(instrument.endswith(pair) for pair in forex_pairs):
            return 'forex'
            
        # Check for crypto
        crypto_currencies = ['BTC', 'ETH', 'SOL', 'DOT', 'ADA', 'DOGE', 'XRP']
        if any(crypto in instrument for crypto in crypto_currencies) or instrument.endswith('USD') and not instrument.startswith('X'):
            return 'crypto'
            
        # Check for commodities
        commodities = {
            'XAUUSD': 'commodities',  # Gold
            'XAGUSD': 'commodities',  # Silver
            'USOIL': 'commodities',   # US Oil
            'BRENT': 'commodities',   # Brent Oil
            'NGAS': 'commodities'     # Natural Gas
        }
        if instrument in commodities:
            return commodities[instrument]
            
        # Check for indices
        indices = {
            'US30': 'indices',     # Dow Jones
            'US500': 'indices',    # S&P 500
            'US100': 'indices',    # Nasdaq
            'GER30': 'indices',    # DAX
            'UK100': 'indices',    # FTSE 100
            'JPN225': 'indices',   # Nikkei
            'AUS200': 'indices',   # ASX 200
            'STOXX50': 'indices',  # Euro Stoxx 50
            'HK50': 'indices'      # Hang Seng
        }
        if instrument in indices:
            return indices[instrument]
            
        # Default to forex if we can't determine
        logger.info(f"Could not determine market type for {instrument}, defaulting to forex")
        return 'forex'
    
    async def _get_tavily_news(self, query: str) -> str:
        """
        Get news content from Tavily API for a given search query
        
        Args:
            query: The search query to use
            
        Returns:
            str: Formatted news content or empty string if failed
        """
        start_time = time.time()
        
        if not self.tavily_client or not self.tavily_api_key:
            logger.warning("No Tavily API client available")
            return ""
            
        try:
            # Make the API request
            response = await self.tavily_client.search(
                query=query,
                search_depth="advanced",
                include_answer=True,
                include_images=False,
                max_results=8
            )
            
            # Record API call duration
            self.metrics.record_api_call('tavily', time.time() - start_time)
            
            if not response:
                logger.error(f"No response from Tavily API for query: {query}")
                return ""
                
            # Extract content from response
            content = response.get('answer', '')
            
            # Add sources if available
            sources = response.get('results', [])
            if sources:
                content += "\n\nSources:\n"
                for idx, source in enumerate(sources[:3], 1):
                    title = source.get('title', 'No title')
                    url = source.get('url', '')
                    content += f"{idx}. {title} - {url}\n"
                    
            return content
            
        except Exception as e:
            logger.error(f"Error in Tavily news retrieval: {str(e)}")
            return ""
    
    def _format_data_manually(self, content: str, instrument: str) -> str:
        """
        Format the raw news content into a more structured format
        
        Args:
            content: The raw news content
            instrument: The instrument being analyzed
            
        Returns:
            str: Formatted content
        """
        if not content:
            return f"No data available for {instrument}."
            
        # Simple formatting to ensure consistent structure
        formatted = f"Market Analysis for {instrument}:\n\n"
        
        # Split content into paragraphs and keep only the first few
        paragraphs = content.split('\n\n')
        main_content = '\n\n'.join(paragraphs[:min(5, len(paragraphs))])
        
        formatted += main_content
        
        # Add sources if present
        if "Sources:" in content:
            sources_part = content.split("Sources:")[1] if len(content.split("Sources:")) > 1 else ""
            if sources_part:
                formatted += f"\n\nSources: {sources_part}"
                
        return formatted
    
    async def _format_with_deepseek(self, instrument: str, market_type: str, content: str) -> str:
        """
        Format content with DeepSeek API to extract sentiment
        
        Args:
            instrument: The trading instrument
            market_type: Type of market (forex, crypto, etc.)
            content: The content to analyze
            
        Returns:
            str: HTML-formatted sentiment analysis
        """
        start_time = time.time()
        
        if not self.deepseek_api_key:
            logger.warning(f"No DeepSeek API key available for sentiment analysis of {instrument}")
            # Return a basic formatted version of the content
            return self._create_fallback_sentiment(instrument, content)
            
        try:
            # Prepare prompt for DeepSeek
            system_prompt = """You are a financial market analyzer. Analyze market sentiment and generate a concise, 
            well-structured analysis with the following sections:
            1. Overall Sentiment (bullish, bearish, or neutral with emoji)
            2. Market Sentiment Breakdown (percentages for bullish, bearish, neutral)
            3. Key Sentiment Drivers (bullet points)
            4. Market Mood (concise description)
            Format the response in HTML with appropriate bold tags and emojis."""
            
            user_prompt = f"""Analyze the market sentiment for {instrument} ({market_type} market) based on the following information:

{content}

Determine if the overall sentiment is bullish, bearish, or neutral. 
Provide percentages for bullish, bearish, and neutral sentiment that add up to 100%.
Give specific reasons for the sentiment in the Key Sentiment Drivers section.
Keep the analysis concise but informative and format as HTML with <b></b> tags for headers.
"""
            
            # Prepare API request
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.deepseek_api_key}'
            }
            
            payload = {
                'model': 'deepseek-chat',
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                'temperature': 0.3,
                'max_tokens': 500
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.deepseek_url,
                    headers=headers,
                    json=payload,
                    timeout=self.request_timeout
                ) as response:
                    if response.status != 200:
                        logger.error(f"DeepSeek API error: {response.status}, {await response.text()}")
                        return self._create_fallback_sentiment(instrument, content)
                    
                    data = await response.json()
            
            # Record API call duration
            self.metrics.record_api_call('deepseek', time.time() - start_time)
            
            # Extract the formatted content
            formatted_content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
            
            if not formatted_content:
                return self._create_fallback_sentiment(instrument, content)
                
            # Ensure we have the key sections in the result
            if '<b>Overall Sentiment:</b>' not in formatted_content:
                # Add a proper header if missing
                formatted_content = f"<b>🎯 {instrument} Market Analysis</b>\n\n" + formatted_content
                
            return formatted_content
            
        except Exception as e:
            logger.error(f"Error in DeepSeek formatting: {str(e)}")
            return self._create_fallback_sentiment(instrument, content)
    
    def _create_fallback_sentiment(self, instrument: str, content: str) -> str:
        """
        Create a fallback sentiment analysis when DeepSeek API fails
        
        Args:
            instrument: The trading instrument
            content: The raw content
            
        Returns:
            str: Basic formatted sentiment analysis
        """
        # Use a simple keyword-based approach for fallback
        bullish_keywords = ['up', 'rise', 'bull', 'growth', 'positive', 'gain', 'increase', 'higher']
        bearish_keywords = ['down', 'fall', 'bear', 'decline', 'negative', 'loss', 'decrease', 'lower']
        
        # Count occurrences of keywords
        bullish_count = sum(content.lower().count(keyword) for keyword in bullish_keywords)
        bearish_count = sum(content.lower().count(keyword) for keyword in bearish_keywords)
        
        total_count = bullish_count + bearish_count
        if total_count == 0:
            # No clear sentiment, default to neutral
            bullish_pct = 50
            bearish_pct = 30
            neutral_pct = 20
            sentiment = "Neutral ⚖️"
        else:
            # Calculate percentages
            bullish_pct = int(min(100, max(0, (bullish_count / total_count) * 100)))
            bearish_pct = int(min(100, max(0, (bearish_count / total_count) * 100)))
            neutral_pct = 100 - bullish_pct - bearish_pct
            
            # Determine overall sentiment
            if bullish_pct > bearish_pct + 20:
                sentiment = "Bullish 📈"
            elif bearish_pct > bullish_pct + 20:
                sentiment = "Bearish 📉"
            else:
                sentiment = "Neutral ⚖️"
                
        # Create the formatted content
        summary = content[:200] + "..." if len(content) > 200 else content
        
        formatted = f"""<b>🎯 {instrument} Market Analysis</b>

<b>Overall Sentiment:</b> {sentiment}

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish_pct}%
🔴 Bearish: {bearish_pct}%
⚪️ Neutral: {neutral_pct}%

<b>📰 Key Sentiment Drivers:</b>
{summary}

<b>📊 Market Mood:</b>
Market appears to be showing {sentiment.lower().split()[0]} signals based on available information.
"""
        return formatted
        
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
            
    async def start_background_prefetch(self, instruments: List[str], interval_minutes: int = 30):
        """
        Start a background task to prefetch sentiment data for popular instruments
        
        Args:
            instruments: List of instrument names to prefetch
            interval_minutes: How often to refresh the data (in minutes)
        """
        logger.info(f"Starting background prefetch for {len(instruments)} instruments")
        
        while True:
            try:
                for instrument in instruments:
                    try:
                        # Check if we already have fresh cached data
                        cached_data = self._get_from_cache(instrument)
                        if cached_data:
                            logger.info(f"Using cached data for {instrument} in prefetch")
                            continue
                            
                        # Get fresh data
                        logger.info(f"Prefetching sentiment data for {instrument}")
                        result = await self._get_fast_sentiment(instrument)
                        logger.info(f"Successfully prefetched sentiment for {instrument}")
                        
                        # Small delay between requests to avoid API rate limits
                        await asyncio.sleep(2)
                    except Exception as e:
                        logger.error(f"Error prefetching sentiment for {instrument}: {str(e)}")
                        # Continue with next instrument
                        continue
                
                # Wait for the specified interval before refreshing
                logger.info(f"Completed prefetch cycle, waiting {interval_minutes} minutes for next cycle")
                await asyncio.sleep(interval_minutes * 60)
            except Exception as e:
                logger.error(f"Error in background prefetch task: {str(e)}")
                # Wait a bit before retrying
                await asyncio.sleep(60)

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
