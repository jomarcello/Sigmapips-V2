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
from functools import lru_cache

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
            fast_mode: Whether to use faster, more efficient API calls (default: True)
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
        self._cache_loaded = False
        
        # Background task lock to prevent multiple saves at once
        self._cache_lock = threading.Lock()
        
        # Common request timeouts and concurrency control
        if self.fast_mode:
            # Faster timeouts for fast mode
            self.request_timeout = aiohttp.ClientTimeout(total=6, connect=2)
            # Semaphore for limiting concurrent requests in fast mode
            self.request_semaphore = asyncio.Semaphore(10)
            logger.info("Fast mode enabled: using optimized request parameters")
        else:
            # Standard timeouts
            self.request_timeout = aiohttp.ClientTimeout(total=12, connect=4)
            # In standard mode, limited semaphore
            self.request_semaphore = asyncio.Semaphore(5)
        
        # Load existing cache if available
        if self.use_persistent_cache:
            try:
                self._load_cache_from_file()
                logger.info(f"Loaded sentiment cache from {self.cache_file}")
            except Exception as e:
                logger.error(f"Error loading cache during initialization: {str(e)}")
        
        # Create a frequent instruments set for quick lookups
        self.frequent_instruments = {
            "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", 
            "USDCHF", "NZDUSD", "BTCUSD", "ETHUSD", "US30",
            "US500", "XAUUSD", "XAGUSD", "USOIL"
        }
        
        # Create a thread local cache for additional performance
        self._thread_local = threading.local()
        
        logger.info(f"Sentiment cache TTL set to {cache_ttl_minutes} minutes ({self.cache_ttl} seconds)")
        if self.use_persistent_cache:
            logger.info(f"Persistent caching enabled, cache file: {self.cache_file}")
        else:
            logger.info("Persistent caching disabled")
        
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
        
        # Memory optimization - add LRU cache to frequently called methods
        self._build_search_query = lru_cache(maxsize=100)(self._build_search_query)
        self._clean_deepseek_response = lru_cache(maxsize=20)(self._clean_deepseek_response)
        self._guess_market_from_instrument = lru_cache(maxsize=100)(self._guess_market_from_instrument)
        
        # NOTE: Don't call asyncio.create_task() here - it requires a running event loop
        # We'll initialize services later when the event loop is running

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
        
        # Use uppercase for consistent cache keys
        instrument = instrument.upper()
        
        # Check if in frequent instruments list for optimal routing
        is_frequent = instrument in self.frequent_instruments
        
        # For frequent instruments, try thread-local cached results first
        if is_frequent and hasattr(self._thread_local, 'recent_results'):
            if instrument in self._thread_local.recent_results:
                cached_item = self._thread_local.recent_results[instrument]
                if time.time() - cached_item['timestamp'] < 300:  # 5 minute TTL for thread local
                    # Ultra-fast in-memory response
                    logger.info(f"Using thread-local cached result for {instrument}")
                    self.metrics.record_cache_hit()
                    self.metrics.record_total_request(time.time() - start_time)
                    return cached_item['data']
        
        # Check if we have a valid cached result
        cached_data = self._get_from_cache(instrument)
        if cached_data:
            logger.info(f"Using cached result for {instrument} (elapsed: {time.time() - start_time:.2f}s)")
            self.metrics.record_cache_hit()
            
            # For frequently used instruments, optimize with thread local cache
            if is_frequent:
                if not hasattr(self._thread_local, 'recent_results'):
                    self._thread_local.recent_results = {}
                # Store in thread local cache with timestamp
                self._thread_local.recent_results[instrument] = {
                    'data': cached_data,
                    'timestamp': time.time()
                }
                
            # Convert API response format if needed
            if 'bullish_percentage' in cached_data and 'bullish' not in cached_data:
                cached_data['bullish'] = cached_data['bullish_percentage']
                cached_data['bearish'] = cached_data['bearish_percentage']
                cached_data['neutral'] = cached_data.get('neutral_percentage', 0)
            
            self.metrics.record_total_request(time.time() - start_time)
            return cached_data
            
        # No valid cache found - use fast mode with minimal API call
        if self.fast_mode:
            result = await self._get_fast_sentiment(instrument)
            
            # If data source is from API (not fallback), add to thread local cache for frequent instruments
            if is_frequent and result.get('source') == 'api':
                if not hasattr(self._thread_local, 'recent_results'):
                    self._thread_local.recent_results = {}
                # Store in thread local cache with timestamp
                self._thread_local.recent_results[instrument] = {
                    'data': result,
                    'timestamp': time.time()
                }
                
            # Record performance metrics
            self.metrics.record_cache_miss()
            self.metrics.record_total_request(time.time() - start_time)
            return result
            
        # For non-fast mode, use full sentiment analysis pipeline
        # Determine market type from instrument if not provided
        if market_type is None:
            market_type = self._guess_market_from_instrument(instrument)
        
        # Get sentiment using full analysis pipeline - this is slower but more comprehensive
        data = await self.get_market_sentiment(instrument, market_type)
        
        # Record performance metrics
        self.metrics.record_cache_miss()
        self.metrics.record_total_request(time.time() - start_time)
        return data

    # Add a new helper method to process sentiment text
    async def _process_sentiment_text(self, instrument: str, sentiment_text: str) -> Dict[str, Any]:
        """Process sentiment text and extract the necessary information"""
        if not sentiment_text or not isinstance(sentiment_text, str):
            return self._get_fallback_sentiment(instrument)
            
        # Extract sentiment values from the text if possible
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
            
            # Cache the result
            self._add_to_cache(instrument, result)
            return result
        else:
            # Use fallback sentiment if parsing fails
            return self._get_fallback_sentiment(instrument)

    def _add_to_cache(self, instrument: str, sentiment_data: Dict[str, Any]) -> None:
        """Add sentiment data to cache with TTL"""
        if not self.cache_enabled:
            return  # Cache is disabled
            
        try:
            # Check if this is fallback/mock data - if so, don't cache it
            source = sentiment_data.get('source', '')
            if source in ['fallback', 'mock', 'error_fallback', 'local_fallback']:
                logger.info(f"Not caching fallback data for {instrument} (source: {source})")
                return
                
            cache_key = instrument.upper()
            
            # Use shallow copy for better performance, deepcopy is slow
            cache_data = {**sentiment_data}
            # Add timestamp for TTL check
            cache_data['timestamp'] = time.time()
            
            # Store in memory cache
            self.sentiment_cache[cache_key] = cache_data
            
            # If persistent cache is enabled, save to file
            if self.use_persistent_cache and self.cache_file:
                try:
                    # Use a thread to save asynchronously for better performance 
                    threading.Thread(target=self._save_cache_to_file, daemon=True).start()
                    logger.info(f"Started async thread to save cache for {instrument}")
                except Exception as e:
                    logger.error(f"Error starting cache save thread: {str(e)}")
                    # Fallback to direct save if thread failed
                    self._save_cache_to_file()
                
        except Exception as e:
            logger.error(f"Error adding to sentiment cache: {str(e)}")
    
    async def _async_save_cache(self):
        """Save cache asynchronously for better performance"""
        try:
            # Use the lock to prevent multiple concurrent saves
            if not self._cache_lock.acquire(blocking=False):
                # Another task is already saving, skip this one
                return
                
            try:
                # Create directory if it doesn't exist
                os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
                
                # Filter for only frequent instruments to keep cache size manageable
                current_time = time.time()
                valid_cache = {}
                
                for key, data in self.sentiment_cache.items():
                    if key in self.frequent_instruments:
                        cache_time = data.get('timestamp', 0)
                        if current_time - cache_time < self.cache_ttl:
                            # Create a copy without the analysis field to reduce cache size
                            compact_data = {k: v for k, v in data.items() if k != 'analysis'}
                            valid_cache[key] = compact_data
                
                # Save to file
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(valid_cache, f)
            finally:
                self._cache_lock.release()
                
        except Exception as e:
            logger.error(f"Error in async cache save: {str(e)}")
    
    def _get_from_cache(self, instrument: str) -> Optional[Dict[str, Any]]:
        """Get sentiment data from cache if available and not expired"""
        if not self.cache_enabled:
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
                    # Use shallow copy for better performance
                    result = {**cache_data}
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
            
    async def load_cache(self):
        """Load the cache from persistent storage asynchronously"""
        if not self.use_persistent_cache or not self.cache_file or self._cache_loaded:
            return
            
        try:
            # Check if file exists
            if not os.path.exists(self.cache_file):
                return
                
            # Run load operation in a thread pool to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._load_cache_from_file)
            
            self._cache_loaded = True
            logger.info(f"Loaded sentiment cache from file asynchronously")
            
        except Exception as e:
            logger.error(f"Error loading sentiment cache from file: {str(e)}")

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
                # Don't cache local fallback data
                return result
                
            # Use semaphore to limit concurrent requests
            response_data = await self._process_fast_sentiment_request(instrument)
                
            if response_data:
                # Process the response to extract sentiment percentages
                bullish_pct = response_data.get('bullish', 50)  # Default in case it's missing
                bearish_pct = response_data.get('bearish', 50)
                neutral_pct = response_data.get('neutral', 0)
                
                # Make sure percentages add up to 100%
                total = bullish_pct + bearish_pct + neutral_pct
                if total != 100:
                    # Rescale to ensure total is 100%
                    if total > 0:
                        bullish_pct = int((bullish_pct / total) * 100)
                        bearish_pct = int((bearish_pct / total) * 100)
                        neutral_pct = 100 - bullish_pct - bearish_pct
                    else:
                        bullish_pct = 50
                        bearish_pct = 50
                        neutral_pct = 0
                
                # Calculate sentiment score
                sentiment_score = (bullish_pct - bearish_pct) / 100
                
                # Determine sentiment
                overall_sentiment = 'bullish' if bullish_pct > bearish_pct else 'bearish' if bearish_pct > bullish_pct else 'neutral'
                
                # Determine trend strength based on how far from neutral
                trend_strength = 'Strong' if abs(bullish_pct - 50) > 15 else 'Moderate' if abs(bullish_pct - 50) > 5 else 'Weak'
                
                # Format the sentiment text
                analysis_text = self._format_default_sentiment(
                    instrument=instrument,
                    bullish_pct=bullish_pct,
                    bearish_pct=bearish_pct,
                    neutral_pct=neutral_pct
                )
                
                # Create the result dictionary
                result = {
                    'bullish': bullish_pct,
                    'bearish': bearish_pct,
                    'neutral': neutral_pct,
                    'sentiment_score': sentiment_score,
                    'technical_score': 'Based on market analysis',
                    'news_score': f"{bullish_pct}% positive",
                    'social_score': f"{bearish_pct}% negative",
                    'trend_strength': trend_strength,
                    'volatility': 'Moderate',
                    'volume': 'Normal',
                    'news_headlines': [],
                    'overall_sentiment': overall_sentiment,
                    'analysis': analysis_text,
                    'source': 'api'  # Indicate this came from the API
                }
                
                # Add to cache
                self._add_to_cache(instrument, result)
                
                logger.info(f"Fast sentiment retrieved for {instrument} (elapsed: {time.time() - start_time:.2f}s)")
                return result
            else:
                # Fallback to local sentiment if API fails
                logger.warning(f"API request failed for {instrument}. Using local fallback.")
                result = self._get_quick_local_sentiment(instrument)
                # Don't cache local fallback data
                return result
                
        except Exception as e:
            logger.error(f"Error getting fast sentiment for {instrument}: {str(e)}")
            # Fallback to local sentiment estimation
            result = self._get_quick_local_sentiment(instrument)
            # Don't cache local fallback data
            return result
            
    def _format_default_sentiment(self, instrument: str, bullish_pct: int, bearish_pct: int, neutral_pct: int) -> str:
        """Format default sentiment text with provided percentages"""
        # Determine sentiment emoji
        sentiment_emoji = "📈" if bullish_pct > bearish_pct else "📉" if bearish_pct > bullish_pct else "➡️"
        overall = "Bullish" if bullish_pct > bearish_pct else "Bearish" if bearish_pct > bullish_pct else "Neutral"
        
        return f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> {overall} {sentiment_emoji}

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish_pct}%
🔴 Bearish: {bearish_pct}%
⚪️ Neutral: {neutral_pct}%

<b>📰 Key Sentiment Drivers:</b>
• Market sentiment driven by technical factors
• Current market positioning and sentiment
• Recent market developments

<b>📊 Market Sentiment Analysis:</b>
The {instrument} is currently showing {overall.lower()} sentiment with general market consensus.

<b>📅 Important Events & News:</b>
• Regular trading activity observed
• Standard market patterns in effect 
• Market sentiment data updated regularly
"""

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
                    'analysis': final_analysis,
                    'source': 'api'  # Mark as API data so it will be cached
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
                    'analysis': final_analysis,
                    'source': 'keyword_fallback'  # Mark as fallback so it won't be cached
                }
                
                # Don't cache keyword fallback results
                # self._add_to_cache(instrument, result)
                
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
                'news_headlines': [],  # We don't have actual headlines from the API
                'source': 'api'  # Mark as API data so it will be cached
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
""",
                    'source': 'error_fallback'  # Mark as fallback so it won't be cached
                }
                logger.info(f"Created fallback sentiment data with proper format for {instrument}")
                
                # Don't cache error fallback data
                # self._add_to_cache(instrument, sentiment_data)
            
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
    
    def _get_default_sentiment_text(self, instrument: str) -> str:
        """
        Get default sentiment text for an instrument
        
        Args:
            instrument: The instrument to analyze
            
        Returns:
            Formatted sentiment text
        """
        # Generate reasonable defaults
        instrument = instrument.upper()
        bullish = 50
        bearish = 50
        neutral = 0
        
        # Format using the same method as the other places
        return self._format_default_sentiment(
            instrument=instrument,
            bullish_pct=bullish,
            bearish_pct=bearish,
            neutral_pct=neutral
        )

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
        DISABLED: This functionality has been completely disabled to prevent unwanted API calls
        """
        # Do absolutely nothing - completely disabled
        logger.info("Prefetch functionality is permanently disabled")
        return

    async def start_background_prefetch(self, popular_instruments: List[str], interval_minutes: int = 60) -> None:
        """
        Start a background task to periodically prefetch sentiment data - DISABLED
        
        Args:
            popular_instruments: List of popular instruments to prefetch
            interval_minutes: How often to run the prefetch in minutes
        """
        # This function is disabled to prevent unnecessary API calls
        return  # Do nothing, completely disabled

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

    def _get_quick_local_sentiment(self, instrument: str) -> Dict[str, Any]:
        """
        Get a very quick local sentiment estimate without API calls
        
        Args:
            instrument: The instrument to analyze
            
        Returns:
            Dict with sentiment data
        """
        # Use deterministic but pseudo-random sentiment based on instrument name
        # This creates consistent results for same instrument but different across instruments
        instrument = instrument.upper()
        
        # Calculate hash value from instrument name
        hash_val = sum(ord(c) for c in instrument) % 100
        
        # Add a daily variation component that changes each day
        day_offset = int(time.time() / 86400) % 20 - 10  # Changes daily, range -10 to +10
        
        # Calculate sentiment percentages
        bullish = max(5, min(95, hash_val + day_offset))
        bearish = 100 - bullish
        neutral = 0
        
        # Format the sentiment text
        formatted_text = self._format_default_sentiment(
            instrument=instrument,
            bullish_pct=bullish,
            bearish_pct=bearish,
            neutral_pct=neutral
        )
        
        # Calculate sentiment score
        sentiment_score = (bullish - bearish) / 100
        
        # Determine overall sentiment
        if bullish > bearish:
            overall_sentiment = 'bullish'
        elif bearish > bullish:
            overall_sentiment = 'bearish'
        else:
            overall_sentiment = 'neutral'
            
        # Determine trend strength
        if abs(bullish - 50) > 15:
            trend_strength = 'Strong'
        elif abs(bullish - 50) > 5:
            trend_strength = 'Moderate'
        else:
            trend_strength = 'Weak'
        
        # Create the result dictionary with all required fields
        return {
            'bullish': bullish,
            'bearish': bearish,
            'neutral': neutral,
            'sentiment_score': sentiment_score,
            'technical_score': 'Based on market analysis',
            'news_score': f"{bullish}% positive",
            'social_score': f"{bearish}% negative",
            'overall_sentiment': overall_sentiment,
            'trend_strength': trend_strength,
            'volatility': 'Moderate',
            'volume': 'Normal',
            'news_headlines': [],
            'analysis': formatted_text,
            'source': 'local_fallback'  # Mark as local fallback data so it won't be cached
        }

    async def load_cache(self):
        """
        Asynchronously load cache from file
        This can be called after initialization to load the cache without blocking startup
        
        Returns:
            bool: True if cache was loaded successfully, False otherwise
        """
        if not self.use_persistent_cache or not self.cache_file or self._cache_loaded:
            return False
            
        try:
            # Run the load operation in a thread pool to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._load_cache_from_file)
            self._cache_loaded = True
            logger.info(f"Asynchronously loaded {len(self.sentiment_cache)} sentiment cache entries")
            return True
        except Exception as e:
            logger.error(f"Error loading sentiment cache asynchronously: {str(e)}")
            return False

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
                'model': "deepseek-chat",
                'messages': [
                    {'role': 'system', 'content': 'You are a financial market sentiment analyzer. Respond with valid JSON only.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.1,  # Lower temperature for more consistent results
                'response_format': {'type': 'json_object'}  # Request JSON format explicitly
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
                        error_text = await response.text()
                        logger.error(f"API error: {response.status}, {error_text[:200]}")
                        return None
                    
                    response_data = await response.json()
                    
            # Extract the content from the response
            content = response_data.get('choices', [{}])[0].get('message', {}).get('content', '{}')
            
            # Clean up any JSON formatting issues
            content = content.strip()
            if content.startswith("```json"):
                content = content.replace("```json", "", 1).strip()
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0].strip()
            
            try:
                # Try to parse as JSON first
                sentiment_data = json.loads(content)
                
                # Validate the expected fields are present
                required_fields = ['bullish_percentage', 'bearish_percentage', 'neutral_percentage']
                if all(field in sentiment_data for field in required_fields):
                    # Rename fields to match our expected format
                    return {
                        'bullish': sentiment_data['bullish_percentage'],
                        'bearish': sentiment_data['bearish_percentage'],
                        'neutral': sentiment_data['neutral_percentage']
                    }
                    
                # If we have sentiment fields in a different format, try to adapt
                if 'bullish' in sentiment_data:
                    return sentiment_data
                    
                # Otherwise, extract from text
                logger.warning(f"JSON response missing required fields: {content[:100]}")
                return self._extract_sentiment_from_text(content, instrument)
                
            except json.JSONDecodeError:
                # If not valid JSON, try to extract percentages from the text
                logger.warning(f"Failed to parse JSON response: {content[:100]}")
                return self._extract_sentiment_from_text(content, instrument)
                
        except asyncio.TimeoutError:
            logger.error(f"API request timed out for {instrument}")
            return None
        except Exception as e:
            logger.error(f"Error in API request for {instrument}: {str(e)}")
            return None
            
    def _extract_sentiment_from_text(self, text: str, instrument: str) -> Dict[str, Any]:
        """Extract sentiment percentages from text response"""
        try:
            # Look for percentage patterns
            bullish_match = re.search(r'(?:bullish|Bullish)[^\d]*(\d+)(?:\s*%|percent)', text)
            bearish_match = re.search(r'(?:bearish|Bearish)[^\d]*(\d+)(?:\s*%|percent)', text)
            neutral_match = re.search(r'(?:neutral|Neutral)[^\d]*(\d+)(?:\s*%|percent)', text)
            
            bullish = int(bullish_match.group(1)) if bullish_match else 50
            bearish = int(bearish_match.group(1)) if bearish_match else 50
            neutral = int(neutral_match.group(1)) if neutral_match else 0
            
            # Ensure percentages sum to 100%
            total = bullish + bearish + neutral
            if total != 100 and total > 0:
                bullish = int((bullish / total) * 100)
                bearish = int((bearish / total) * 100)
                neutral = 100 - bullish - bearish
            
            return {
                'bullish': bullish,
                'bearish': bearish,
                'neutral': neutral
            }
        except Exception as e:
            logger.error(f"Error extracting sentiment from text: {str(e)}")
            # Return default values
            return {
                'bullish': 50,
                'bearish': 50,
                'neutral': 0
            }

    def _prepare_fast_sentiment_prompt(self, instrument: str) -> str:
        """
        Prepare the prompt for fast sentiment analysis
        
        Args:
            instrument: The instrument to analyze
            
        Returns:
            Optimized prompt string
        """
        market_type = self._guess_market_from_instrument(instrument)
        
        prompt = f"""Analyze current market sentiment for {instrument} ({market_type}).

Provide ONLY this JSON format without any additional content:
{{
    "bullish_percentage": XX,
    "bearish_percentage": YY,
    "neutral_percentage": ZZ
}}

Your percentages must add up to 100. Return ONLY the JSON above. DO NOT include ANY explanations, reasoning or other text.
"""
        return prompt

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

    def _save_cache_to_file(self) -> None:
        """Save the sentiment cache to a persistent file with proper locking"""
        if not self.use_persistent_cache or not self.cache_file:
            return  # Nothing to do if persistent cache is disabled
            
        # Use a lock to prevent concurrent writes
        with self._cache_lock:
            try:
                # Filter out any items that shouldn't be cached persistently
                clean_cache = {}
                for key, data in self.sentiment_cache.items():
                    if data.get('source') not in ['fallback', 'mock', 'error_fallback', 'local_fallback']:
                        clean_cache[key] = data
                
                # Make directory if it doesn't exist
                os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
                
                # Write to a temporary file first, then rename to avoid corruption
                temp_file = f"{self.cache_file}.tmp"
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(clean_cache, f, ensure_ascii=False, indent=2)
                
                # Atomic rename to final file
                os.replace(temp_file, self.cache_file)
                logger.info(f"Successfully saved {len(clean_cache)} sentiment cache entries to {self.cache_file}")
                
            except Exception as e:
                logger.error(f"Error saving sentiment cache to file: {str(e)}")

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
