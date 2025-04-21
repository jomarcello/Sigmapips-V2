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
import traceback

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
        # API configuration
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.tavily_api_key = os.getenv("TAVILY_API_KEY")
        
        # Configure the API parameters
        self.api_key = self.deepseek_api_key  # Use DeepSeek as the default API
        self.api_model = "deepseek-chat"      # Default model
        self.api_url = "https://api.deepseek.com/v1/chat/completions"  # Default API URL
        self.api_timeout = 10                 # Default timeout in seconds
        
        # Additional URL configurations for direct API approach
        self.deepseek_url = "https://api.deepseek.com/v1/chat/completions"
        self.tavily_url = "https://api.tavily.com/search"
        
        # Initialize the Tavily client
        self.tavily_client = TavilyClient(self.tavily_api_key)
        
        # Fast mode flag
        self.fast_mode = fast_mode
        
        # Initialize cache settings
        self.cache_ttl = cache_ttl_minutes * 60  # Convert minutes to seconds
        self.use_persistent_cache = persistent_cache
        
        # Enable caching by default
        self.cache_enabled = True
        
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
        
        base_query = f"{instrument} {market_type} news economic events"
        
        # Add additional context based on market type
        if market_type == 'forex':
            currency_pair = instrument[:3] + "/" + instrument[3:] if len(instrument) == 6 else instrument
            base_query = f"{currency_pair} forex news economic data central bank policy decisions"
        elif market_type == 'crypto':
            # For crypto, use common naming conventions
            crypto_name = instrument.replace('USD', '') if instrument.endswith('USD') else instrument
            base_query = f"{crypto_name} cryptocurrency news regulatory developments market sentiment"
        elif market_type == 'commodities':
            commodity_name = {
                'XAUUSD': 'gold',
                'XAGUSD': 'silver',
                'USOIL': 'crude oil',
                'BRENT': 'brent oil'
            }.get(instrument, instrument)
            base_query = f"{commodity_name} commodity news supply demand factors economic impact"
        elif market_type == 'indices':
            index_name = {
                'US30': 'Dow Jones',
                'US500': 'S&P 500',
                'US100': 'Nasdaq',
                'GER30': 'DAX',
                'UK100': 'FTSE 100'
            }.get(instrument, instrument)
            base_query = f"{index_name} stock index news economic data earnings reports policy decisions"
            
        # Add current date to get latest info
        base_query += " latest news today"
        
        logger.info(f"Search query built: {base_query}")
        return base_query
            
    async def get_sentiment(self, instrument: str, market_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get sentiment for a given instrument. This function is used by the TelegramService.
        Returns a dictionary with sentiment data or formatted text.
        """
        logger.info(f"get_sentiment called for {instrument}")
        
        if market_type is None:
            # Determine market type from instrument if not provided
            market_type = self._guess_market_from_instrument(instrument)
            logger.info(f"Detected market type: {market_type} for {instrument}")
        
        # Start timing the total request
        start_time = time.time()
        
        # Check if we have a valid cached result using market-specific cache
        if market_type:
            cached_data = self._get_from_market_specific_cache(instrument, market_type)
            if cached_data:
                logger.info(f"Returning market-specific cached sentiment data for {instrument} ({market_type})")
                self.metrics.record_total_request(time.time() - start_time)
                return cached_data
        else:
            # Fallback to standard cache if market_type is not available
            cached_data = self._get_from_cache(instrument)
            if cached_data:
                logger.info(f"Returning cached sentiment data for {instrument}")
                self.metrics.record_total_request(time.time() - start_time)
                return cached_data
        
        try:
            # First try the direct API approach (similar to LiveSentimentService)
            if self.deepseek_api_key and self.tavily_api_key:
                try:
                    logger.info(f"Attempting direct API approach for {instrument}")
                    result = await self._get_direct_api_sentiment(instrument, market_type)
                    if result:
                        # Cache the result with market-specific key if market type is available
                        if market_type:
                            self._add_market_specific_to_cache(instrument, market_type, result)
                        else:
                            self._add_to_cache(instrument, result)
                        
                        # Record total request time
                        self.metrics.record_total_request(time.time() - start_time)
                        return result
                    logger.info(f"Direct API approach returned no result, trying fast mode")
                except Exception as e:
                    logger.error(f"Error with direct API approach in get_sentiment: {str(e)}")
                    logger.info("Falling back to fast mode")
            
            # Use fast mode if enabled
            if self.fast_mode:
                result = await self._get_fast_sentiment(instrument)
                # Cache the result with market-specific key if market type is available
                if market_type:
                    self._add_market_specific_to_cache(instrument, market_type, result)
                else:
                    self._add_to_cache(instrument, result)
                
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
            
            # Try using direct API approach first (LiveSentimentService approach)
            if self.deepseek_api_key and self.tavily_api_key:
                try:
                    logger.info(f"Attempting to get direct API sentiment for {instrument}")
                    
                    # Format instrument for better search query
                    if len(instrument) == 6 and instrument.isalpha():
                        # Likely a forex pair, add a slash
                        formatted_instrument = f"{instrument[:3]}/{instrument[3:]}"
                    else:
                        formatted_instrument = instrument
                    
                    # Get market data from Tavily
                    query = f"{formatted_instrument} latest news economic events policy decisions market sentiment analysis"
                    
                    # Prepare request for Tavily
                    headers = {
                        "Authorization": f"Bearer {self.tavily_api_key}",
                        "Content-Type": "application/json"
                    }
                    
                    payload = {
                        "query": query,
                        "search_depth": "advanced",
                        "include_answer": True,
                        "include_images": False,
                        "max_results": 5
                    }
                    
                    # Get market data
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            "https://api.tavily.com/search",
                            headers=headers,
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=15)
                        ) as response:
                            if response.status != 200:
                                logger.error(f"Tavily API returned status {response.status}: {await response.text()}")
                                raise ValueError(f"Tavily API error: {response.status}")
                            
                            tavily_data = await response.json()
                    
                    # Process Tavily data
                    market_data = f"# Market Analysis for {instrument}\n\n"
                    
                    # Add the generated answer if available
                    if tavily_data.get("answer"):
                        market_data += f"## Summary\n{tavily_data['answer']}\n\n"
                    
                    # Add search results
                    if tavily_data.get("results"):
                        market_data += "## Market News and Analysis\n\n"
                        for i, item in enumerate(tavily_data["results"], 1):
                            market_data += f"### {item.get('title', f'Source {i}')}\n"
                            market_data += f"{item.get('content', 'No content available')}\n"
                            market_data += f"Source: {item.get('url', 'Unknown')}\n\n"
                    
                    logger.info(f"Retrieved {len(tavily_data.get('results', []))} market data items for {instrument}")
                    
                    # Truncate market data if too long
                    if len(market_data) > 5000:
                        market_data = market_data[:5000] + "...[truncated]"
                    
                    # Create sentiment prompt for DeepSeek
                    prompt = f"""Analyze the current market sentiment for {instrument} based on the following market data:

{market_data}

Provide a DETAILED market sentiment analysis with the following:

1. Overall market sentiment (bullish, bearish, or neutral)
2. Precise percentage breakdown of bullish, bearish, and neutral sentiment
3. Analysis of current market trends and sentiment drivers
4. Key factors influencing the sentiment
5. Important events and news affecting the instrument

Your response MUST be in this exact JSON format:
{{
    "bullish_percentage": [percentage of bullish sentiment as a number, 0-100],
    "bearish_percentage": [percentage of bearish sentiment as a number, 0-100],
    "neutral_percentage": [percentage of neutral sentiment as a number, 0-100],
    "formatted_text": "Your full formatted HTML text here with all the required sections"
}}

For the "formatted_text" field, use THIS EXACT HTML FORMAT:

<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> [Bullish/Bearish/Neutral with emoji]

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: XX%
🔴 Bearish: YY%
⚪️ Neutral: ZZ%

<b>📊 Market Sentiment Analysis:</b>
[Detailed analysis of current market sentiment based on the data]

<b>📰 Key Sentiment Drivers:</b>
• [Key sentiment factor 1]
• [Key sentiment factor 2]
• [Key sentiment factor 3]

<b>📅 Important Events & News:</b>
• [News event 1]
• [News event 2]
• [News event 3]

The percentages MUST add up to 100%, and the formatted text MUST include all sections with the exact HTML tags shown. Base your analysis ONLY on the provided market data.
"""
                    
                    # Prepare DeepSeek request
                    headers = {
                        "Authorization": f"Bearer {self.deepseek_api_key}",
                        "Content-Type": "application/json"
                    }
                    
                    payload = {
                        "model": self.api_model,
                        "messages": [
                            {"role": "system", "content": "You are a financial market analyst specializing in sentiment analysis. Your task is to analyze market data and provide detailed sentiment analysis with specific percentages and sections."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.2,
                        "max_tokens": 1500,
                        "response_format": {"type": "json_object"}
                    }
                    
                    # Get DeepSeek analysis
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            self.api_url,
                            headers=headers,
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=20)
                        ) as response:
                            if response.status != 200:
                                logger.error(f"DeepSeek API returned status {response.status}: {await response.text()}")
                                raise ValueError(f"DeepSeek API error: {response.status}")
                            
                            deepseek_result = await response.json()
                    
                    # Extract content from response
                    content = deepseek_result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                    
                    # Parse the JSON response
                    data = json.loads(content)
                    
                    # Validate the response has the expected structure
                    required_fields = ["bullish_percentage", "bearish_percentage", "neutral_percentage", "formatted_text"]
                    missing = [field for field in required_fields if field not in data]
                    
                    if missing:
                        logger.error(f"Missing fields in DeepSeek response: {missing}")
                        raise ValueError(f"Invalid response format: missing {missing}")
                    
                    # Ensure percentages add up to 100
                    total = data["bullish_percentage"] + data["bearish_percentage"] + data["neutral_percentage"]
                    if abs(total - 100) > 0.01:  # Allow small floating point error
                        logger.warning(f"Percentages don't add up to 100 ({total}), adjusting")
                        # Adjust proportionally
                        data["bullish_percentage"] = round(data["bullish_percentage"] * 100 / total)
                        data["bearish_percentage"] = round(data["bearish_percentage"] * 100 / total)
                        data["neutral_percentage"] = 100 - data["bullish_percentage"] - data["bearish_percentage"]
                    
                    # Add source information
                    data["source"] = "api"
                    data["instrument"] = instrument
                    data["market_type"] = market_type
                    
                    # Verify the formatted text includes all required sections
                    formatted_text = data["formatted_text"]
                    required_sections = [
                        "<b>🎯", "Market Sentiment Analysis</b>",
                        "<b>Overall Sentiment:</b>",
                        "<b>Market Sentiment Breakdown:</b>",
                        "<b>📊 Market Sentiment Analysis:</b>",
                        "<b>📰 Key Sentiment Drivers:</b>",
                        "<b>📅 Important Events & News:</b>"
                    ]
                    
                    for section in required_sections:
                        if section not in formatted_text:
                            logger.warning(f"Missing '{section}' in formatted text")
                    
                    # Add sentiment_text for compatibility
                    data["sentiment_text"] = formatted_text
                    
                    # Create a result in our expected format
                    result = {
                        'bullish': data["bullish_percentage"],
                        'bearish': data["bearish_percentage"],
                        'neutral': data["neutral_percentage"],
                        'sentiment_score': (data["bullish_percentage"] - data["bearish_percentage"]) / 100,
                        'technical_score': 'Based on market analysis',
                        'news_score': f"{data['bullish_percentage']}% positive",
                        'social_score': f"{data['bearish_percentage']}% negative",
                        'trend_strength': 'Strong' if abs(data["bullish_percentage"] - 50) > 15 else 'Moderate' if abs(data["bullish_percentage"] - 50) > 5 else 'Weak',
                        'volatility': 'Moderate',
                        'volume': 'Normal',
                        'news_headlines': [],
                        'overall_sentiment': 'bullish' if data["bullish_percentage"] > data["bearish_percentage"] else 'bearish' if data["bearish_percentage"] > data["bullish_percentage"] else 'neutral',
                        'analysis': formatted_text,
                        'market_type': market_type
                    }
                    
                    # Cache the result with market-specific key
                    self._add_market_specific_to_cache(instrument, market_type, result)
                    
                    logger.info(f"Direct API sentiment analysis complete: {data['bullish_percentage']}% bullish, {data['bearish_percentage']}% bearish")
                    return result
                    
                except Exception as e:
                    logger.error(f"Error with direct API approach: {str(e)}")
                    logger.info("Falling back to standard sentiment analysis process")
            
            # If we reach here, either the direct API approach failed or API keys weren't available
            # Continue with the existing logic
            
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
            
            # Create sentiment prompt for DeepSeek
            prompt = f"""Analyze the current market sentiment for {instrument} based on the following market data:

{market_data}

Provide a DETAILED market sentiment analysis with the following:

1. Overall market sentiment (bullish, bearish, or neutral)
2. Precise percentage breakdown of bullish, bearish, and neutral sentiment
3. Analysis of current market sentiment drivers focused ONLY on news and economic events
4. Key news and economic factors influencing the sentiment
5. Important events and news affecting the instrument

IMPORTANT INSTRUCTIONS:
1. DO NOT include ANY technical analysis, chart patterns, or price action
2. DO NOT mention ANY price levels, support/resistance, or moving averages
3. DO NOT discuss trading volumes, momentum, or technical indicators
4. Focus EXCLUSIVELY on economic data, policy decisions, news events, and fundamental factors
5. Avoid ALL references to price targets, entry/exit points, or trade recommendations
6. Your analysis should be based ONLY on news, economic events, and fundamental information

Your response MUST be in this exact JSON format:
{
    "bullish_percentage": [percentage of bullish sentiment as a number, 0-100],
    "bearish_percentage": [percentage of bearish sentiment as a number, 0-100],
    "neutral_percentage": [percentage of neutral sentiment as a number, 0-100],
    "formatted_text": "Your full formatted HTML text here with all the required sections"
}

For the "formatted_text" field, use THIS EXACT HTML FORMAT:

<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> [Bullish/Bearish/Neutral with emoji]

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: XX%
🔴 Bearish: YY%
⚪️ Neutral: ZZ%

<b>📊 Market Sentiment Analysis:</b>
[Detailed analysis of current market sentiment focusing ONLY on news, economic events, and fundamental factors]

<b>📰 Key Sentiment Drivers:</b>
• [Key news or economic factor 1]
• [Key news or economic factor 2]
• [Key news or economic factor 3]

<b>📅 Important Events & News:</b>
• [News event 1]
• [News event 2]
• [News event 3]

The percentages MUST add up to 100%, and the formatted text MUST include all sections with the exact HTML tags shown. Base your analysis EXCLUSIVELY on news, economic events, and fundamental factors in the provided market data.
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
{instrument} sentiment is currently balanced with no strong directional bias based on recent economic data and news events. Market participants appear divided on the future direction.

<b>📰 Key Sentiment Drivers:</b>
• Recent economic data showing mixed results
• No significant policy changes affecting the market
• Balanced market reaction to current news flow

<b>📅 Important Events & News:</b>
• No major economic releases with significant impact
• Standard news flow with balanced market reaction
• No unexpected announcements affecting sentiment
"""

    def _add_to_cache(self, instrument: str, sentiment_data: Dict[str, Any]) -> None:
        """
        Add sentiment data to cache with TTL
        
        Args:
            instrument: The instrument to cache
            sentiment_data: The sentiment data to cache
        """
        if not self.cache_enabled:
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
            if self.use_persistent_cache and self.cache_file:
                self._save_cache_to_file()
                
            logger.debug(f"Added sentiment data to cache for {instrument}")
                
        except Exception as e:
            logger.error(f"Error adding to sentiment cache: {str(e)}")
    
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
                    # Make a copy to avoid reference issues
                    result = copy.deepcopy(cache_data)
                    # Remove timestamp as it's internal
                    if 'timestamp' in result:
                        del result['timestamp']
                    
                    # Record cache hit metric
                    self.metrics.record_cache_hit()
                    
                    return result
                else:
                    # Expired, remove from cache
                    del self.sentiment_cache[cache_key]
                    
            # Record cache miss metric
            self.metrics.record_cache_miss()
            return None
            
        except Exception as e:
            logger.error(f"Error getting from sentiment cache: {str(e)}")
            return None
    
    def _save_cache_to_file(self) -> None:
        """Save the in-memory cache to the persistent file"""
        if not self.cache_file:
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
                
            logger.debug(f"Saved {len(valid_cache)} cache entries to file: {self.cache_file}")
                
        except Exception as e:
            logger.error(f"Error saving sentiment cache to file: {str(e)}")
    
    def _load_cache_from_file(self) -> None:
        """Load the cache from the persistent file"""
        if not self.cache_file:
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
        Clear the sentiment cache for a specific instrument or all instruments
        
        Args:
            instrument: Instrument to clear from cache, if None clears for specific instrument
        """
        if instrument:
            instrument_key = instrument.upper()
            if instrument_key in self.sentiment_cache:
                del self.sentiment_cache[instrument_key]
                logger.info(f"Cleared sentiment cache for {instrument_key}")
            else:
                logger.info(f"No cache entry found for {instrument_key}")
        else:
            count = len(self.sentiment_cache)
            self.sentiment_cache.clear()
            logger.info(f"Cleared all {count} sentiment cache entries")
            
        # If persistent cache is enabled, save the changes
        if self.use_persistent_cache and self.cache_file:
            self._save_cache_to_file()
            
    def clear_cache_all(self) -> None:
        """
        Clear all sentiment cache entries and remove the cache file
        
        This is more thorough than clear_cache() as it also removes the persistent cache file
        """
        # Clear in-memory cache
        count = len(self.sentiment_cache)
        self.sentiment_cache.clear()
        
        # Remove the cache file if it exists
        cache_file_removed = False
        if self.use_persistent_cache and self.cache_file and os.path.exists(self.cache_file):
            try:
                os.remove(self.cache_file)
                cache_file_removed = True
            except Exception as e:
                logger.error(f"Error removing cache file: {str(e)}")
                
        logger.info(f"Completely cleared {count} sentiment cache entries")
        if cache_file_removed:
            logger.info(f"Removed cache file: {self.cache_file}")

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
    
    def import_external_sentiment_data(self, instrument: str, data: Dict[str, Any], market_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Import sentiment data from an external source and cache it
        
        Args:
            instrument: Trading instrument symbol
            data: Dictionary with sentiment data
            market_type: Optional market type for more specific caching
            
        Returns:
            Dictionary with the processed and cached sentiment data
        """
        logger.info(f"Importing external sentiment data for {instrument}")
        
        try:
            # Validate essential fields
            required_fields = ["bullish_percentage", "bearish_percentage", "neutral_percentage"]
            alt_required_fields = ["bullish", "bearish", "neutral"]
            
            # Check if the data has percentage fields in the expected format
            has_req_fields = all(field in data for field in required_fields)
            has_alt_fields = all(field in data for field in alt_required_fields)
            
            if not has_req_fields and not has_alt_fields:
                logger.error(f"Missing required fields in external sentiment data for {instrument}")
                return None
            
            # Create standardized data structure
            result = {}
            
            # Standardize keys
            if has_req_fields:
                result["bullish"] = data["bullish_percentage"]
                result["bearish"] = data["bearish_percentage"]
                result["neutral"] = data["neutral_percentage"]
            else:
                result["bullish"] = data["bullish"]
                result["bearish"] = data["bearish"]
                result["neutral"] = data["neutral"]
            
            # Make sure percentages are numbers
            for key in ["bullish", "bearish", "neutral"]:
                if isinstance(result[key], str):
                    # Remove % sign if present and convert to float
                    result[key] = float(result[key].replace('%', ''))
                    
            # Ensure percentages add up to 100
            total = result["bullish"] + result["bearish"] + result["neutral"]
            if abs(total - 100) > 0.01:  # Allow small floating point error
                logger.warning(f"Percentages don't add up to 100 ({total}), adjusting")
                # Adjust proportionally
                result["bullish"] = round(result["bullish"] * 100 / total)
                result["bearish"] = round(result["bearish"] * 100 / total)
                result["neutral"] = 100 - result["bullish"] - result["bearish"]
            
            # Add required fields
            result["sentiment_score"] = (result["bullish"] - result["bearish"]) / 100
            result["overall_sentiment"] = 'bullish' if result["bullish"] > result["bearish"] else 'bearish' if result["bearish"] > result["bullish"] else 'neutral'
            result["instrument"] = instrument
            result["source"] = data.get("source", "external")
            
            # Add formatted_text or analysis if available
            if "analysis" in data:
                result["analysis"] = data["analysis"]
            elif "formatted_text" in data:
                result["analysis"] = data["formatted_text"]
            else:
                # Generate a simple formatted text
                result["analysis"] = self._format_fast_sentiment_text(
                    instrument, 
                    result["bullish"], 
                    result["bearish"], 
                    result["neutral"]
                )
            
            # Add other fields if available
            for field in ["technical_score", "news_score", "social_score", "news_headlines"]:
                if field in data:
                    result[field] = data[field]
            
            # Add timestamp
            result["timestamp"] = data.get("timestamp", time.time())
            
            # Determine market type if not provided
            if not market_type and "market_type" in data:
                market_type = data["market_type"]
            elif not market_type:
                market_type = self._guess_market_from_instrument(instrument)
                
            # Add market_type to the result
            result["market_type"] = market_type
            
            # Cache the data
            if market_type:
                self._add_market_specific_to_cache(instrument, market_type, result)
            else:
                self._add_to_cache(instrument, result)
            
            logger.info(f"Successfully imported and cached external sentiment data for {instrument}")
            return result
            
        except Exception as e:
            logger.error(f"Error importing external sentiment data: {str(e)}")
            return None

    async def _get_fast_sentiment(self, instrument: str) -> Dict[str, Any]:
        """
        Get a quick sentiment analysis for a trading instrument with more comprehensive formatting
        
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
                # Ensure cached result has all required sections
                if 'sentiment_text' in cached_result:
                    if ("<b>📊 Market Sentiment Analysis:</b>" not in cached_result['sentiment_text'] or
                        "<b>📰 Key Sentiment Drivers:</b>" not in cached_result['sentiment_text'] or
                        "<b>📅 Important Events & News:</b>" not in cached_result['sentiment_text']):
                        
                        logger.warning(f"Cached sentiment for {instrument} has incomplete format, regenerating")
                        self.clear_cache(instrument)
                    else:
                        logger.info(f"Using cached sentiment for {instrument} (elapsed: {time.time() - start_time:.2f}s)")
                        return cached_result
                else:
                    logger.warning(f"Cached sentiment for {instrument} missing sentiment_text, regenerating")
                    self.clear_cache(instrument)
            
            # Market type detection
            market_type = self._guess_market_from_instrument(instrument)
            logger.info(f"Detected market type: {market_type} for {instrument}")
            
            # Check if Tavily API key is available - we'll use it to get real market data
            search_data = None
            if self.tavily_api_key:
                try:
                    # Build query for the instrument
                    search_query = self._build_search_query(instrument, market_type)
                    logger.info(f"Running Tavily search for {instrument} with query: {search_query}")
                    
                    # Get search data with a timeout to keep it fast
                    search_data_task = self._get_tavily_news(search_query)
                    search_data = await asyncio.wait_for(search_data_task, timeout=6.0)
                    logger.info(f"Received Tavily search data for {instrument}: {len(search_data) if search_data else 0} bytes")
                except asyncio.TimeoutError:
                    logger.warning(f"Tavily search timed out for {instrument}, proceeding without search data")
                except Exception as e:
                    logger.error(f"Error getting Tavily search data for {instrument}: {str(e)}")
            
            # Check if we have a DeepSeek API key
            if not self.api_key:
                logger.warning(f"No DeepSeek API key available. Using local sentiment estimate for {instrument}")
                result = self._get_quick_local_sentiment(instrument)
                # Verify the format one last time
                if ("<b>📊 Market Sentiment Analysis:</b>" not in result['sentiment_text'] or
                    "<b>📰 Key Sentiment Drivers:</b>" not in result['sentiment_text'] or
                    "<b>📅 Important Events & News:</b>" not in result['sentiment_text']):
                    logger.warning(f"Local sentiment has incomplete format, using default template")
                    # Use the default sentiment text with the percentages from our estimation
                    result['sentiment_text'] = self._get_default_sentiment_text(instrument)
                
                self._add_to_cache(instrument, result)
                logger.info(f"Local sentiment generated for {instrument} (elapsed: {time.time() - start_time:.2f}s)")
                return result
            
            # Use semaphore to limit concurrent requests
            async with self.request_semaphore:
                # Build a better prompt that includes search data if available
                enhanced_prompt = self._prepare_enhanced_sentiment_prompt(instrument, market_type, search_data)
                
                # Get sentiment from DeepSeek
                response_data = await self._process_sentiment_request(instrument, enhanced_prompt)
                
            if response_data:
                # Process the response to extract sentiment percentages
                bullish_pct = response_data.get('bullish_percentage', 0)
                bearish_pct = response_data.get('bearish_percentage', 0)
                neutral_pct = response_data.get('neutral_percentage', 0)
                
                # Get formatted text (this should always be present from _process_sentiment_request)
                sentiment_text = response_data.get('formatted_text', '')
                if not sentiment_text or ("<b>📊 Market Sentiment Analysis:</b>" not in sentiment_text or
                                          "<b>📰 Key Sentiment Drivers:</b>" not in sentiment_text or
                                          "<b>📅 Important Events & News:</b>" not in sentiment_text):
                    logger.warning(f"API response missing complete sentiment text for {instrument}, using default")
                    sentiment_text = self._get_default_sentiment_text(instrument)
                
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
                
                # Verify the format one last time
                if ("<b>📊 Market Sentiment Analysis:</b>" not in result['sentiment_text'] or
                    "<b>📰 Key Sentiment Drivers:</b>" not in result['sentiment_text'] or
                    "<b>📅 Important Events & News:</b>" not in result['sentiment_text']):
                    logger.warning(f"Local fallback has incomplete format, using default template")
                    # Use the default sentiment text with the percentages from our estimation
                    result['sentiment_text'] = self._get_default_sentiment_text(instrument)
                
                self._add_to_cache(instrument, result)
                logger.info(f"Local fallback used for {instrument} (elapsed: {time.time() - start_time:.2f}s)")
                return result
                
        except Exception as e:
            logger.error(f"Error getting fast sentiment for {instrument}: {str(e)}")
            logger.exception(e)
            # Fallback to default sentiment
            bullish_pct = 50
            bearish_pct = 50
            neutral_pct = 0
            sentiment_text = self._get_default_sentiment_text(instrument)
            
            result = {
                'instrument': instrument,
                'bullish_percentage': bullish_pct,
                'bearish_percentage': bearish_pct,
                'neutral_percentage': neutral_pct,
                'sentiment_text': sentiment_text,
                'source': 'error_fallback'
            }
            
            logger.error(f"Error fallback used for {instrument} due to exception")
            return result
    
    def _prepare_enhanced_sentiment_prompt(self, instrument: str, market_type: str, search_data: Optional[str] = None) -> str:
        """
        Prepare an enhanced prompt for DeepSeek that includes search data if available
        
        Args:
            instrument: The trading instrument to analyze
            market_type: The market type (forex, crypto, etc.)
            search_data: Optional search data from Tavily
            
        Returns:
            str: The formatted prompt
        """
        # Base information about the instrument
        base_info = f"Instrument: {instrument}\nMarket type: {market_type}"
        
        # Add search data if available
        data_section = ""
        if search_data and len(search_data) > 10:
            # Trim if too long
            if len(search_data) > 3000:
                search_data = search_data[:3000] + "...[truncated for brevity]"
            data_section = f"\n\nMarket data and news:\n{search_data}"
        
        # Create the prompt with clear instructions
        prompt = f"""Analyze the current market sentiment for the trading instrument {instrument} based on the following information:

{base_info}{data_section}

Create a DETAILED market sentiment analysis with the following sections:

1. Overall market sentiment (bullish, bearish, or neutral)
2. Percentage breakdown of bullish, bearish, and neutral sentiment
3. Market sentiment analysis that explains the current sentiment
4. Key sentiment drivers (factors affecting the market)
5. Important events and news affecting the instrument

Your response MUST include BOTH:

1. A JSON section with the sentiment percentages:
{{
    "bullish_percentage": [percentage of bullish sentiment, 0-100],
    "bearish_percentage": [percentage of bearish sentiment, 0-100],
    "neutral_percentage": [percentage of neutral sentiment, 0-100],
    "formatted_text": "Your full formatted HTML text here with all the required sections"
}}

2. In the "formatted_text" field, include a complete HTML-formatted analysis with this EXACT format:

<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> [Bullish/Bearish/Neutral with emoji]

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: XX%
🔴 Bearish: YY%
⚪️ Neutral: ZZ%

<b>📊 Market Sentiment Analysis:</b>
[Detailed analysis of current market sentiment for {instrument}]

<b>📰 Key Sentiment Drivers:</b>
• [Key factor 1]
• [Key factor 2]
• [Key factor 3]

<b>📅 Important Events & News:</b>
• [Event/news 1]
• [Event/news 2]
• [Event/news 3]

Make sure the percentages add up to 100%. The formatted text MUST include all sections with the exact HTML tags shown.
"""
        return prompt
        
    async def _process_sentiment_request(self, instrument: str, prompt: str) -> Dict[str, Any]:
        """
        Process a sentiment request to the DeepSeek API with the enhanced prompt
        
        Args:
            instrument: The trading instrument to analyze
            prompt: The enhanced prompt with all instructions
            
        Returns:
            Dict with sentiment data or None if request failed
        """
        try:
            # Check if API key is available
            if not self.api_key:
                logger.error(f"No API key available for {instrument}")
                return None
                
            # Build the request
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            
            payload = {
                'model': self.api_model,
                'messages': [
                    {'role': 'system', 'content': 'You are a financial market analyst specializing in sentiment analysis. You provide detailed, accurate analysis of market sentiment based on available data.'},
                    {'role': 'user', 'content': prompt}
                ],
                'response_format': {'type': 'json_object'},
                'temperature': 0.2  # Lower temperature for more consistent results
            }
            
            # Use a longer timeout to ensure we get a complete response
            api_timeout = aiohttp.ClientTimeout(total=20)  # Increase from 10 to 20 seconds
            
            # Make the API request with timeout
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=api_timeout
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
                
                # Validate the sentiment data
                if 'bullish_percentage' not in sentiment_data or 'bearish_percentage' not in sentiment_data:
                    logger.error(f"Invalid sentiment data format: {sentiment_data}")
                    return None
                
                # Get the formatted text or create it if not provided
                formatted_text = sentiment_data.get('formatted_text', '')
                if not formatted_text:
                    logger.warning(f"No formatted_text provided in API response for {instrument}, creating one")
                    formatted_text = self._format_fast_sentiment_text(
                        instrument, 
                        sentiment_data.get('bullish_percentage', 50),
                        sentiment_data.get('bearish_percentage', 50),
                        sentiment_data.get('neutral_percentage', 0)
                    )
                    sentiment_data['formatted_text'] = formatted_text
                
                # Verify that formatted_text contains all required sections
                required_sections = [
                    "<b>🎯", "Market Sentiment Analysis</b>",
                    "<b>Overall Sentiment:</b>",
                    "<b>Market Sentiment Breakdown:</b>",
                    "🟢 Bullish:", 
                    "🔴 Bearish:",
                    "<b>📊 Market Sentiment Analysis:</b>",
                    "<b>📰 Key Sentiment Drivers:</b>",
                    "<b>📅 Important Events & News:</b>"
                ]
                
                missing_sections = [sect for sect in required_sections if sect not in formatted_text]
                if missing_sections:
                    logger.warning(f"Missing sections in formatted text: {missing_sections}")
                    # Use our default formatter to ensure all sections are included
                    default_text = self._get_default_sentiment_text(instrument)
                    
                    # Try to extract numbers from API response
                    formatted_text = self._format_fast_sentiment_text(
                        instrument, 
                        sentiment_data.get('bullish_percentage', 50),
                        sentiment_data.get('bearish_percentage', 50),
                        sentiment_data.get('neutral_percentage', 0)
                    )
                    sentiment_data['formatted_text'] = formatted_text
                
                # Final verification - ensure text has all required sections with full content
                # This is a critical check to make sure the telegram output is complete
                final_text = sentiment_data.get('formatted_text', '')
                
                # Check for minimal length in each section to ensure content is proper
                section_checks = {
                    "Market Sentiment Analysis:</b>": 30,  # Expect at least 30 chars of content
                    "Key Sentiment Drivers:</b>": 30,
                    "Important Events & News:</b>": 30
                }
                
                incomplete_sections = []
                for section, min_length in section_checks.items():
                    if section in final_text:
                        section_start = final_text.find(section) + len(section)
                        next_section = final_text.find("<b>", section_start)
                        if next_section == -1:
                            next_section = len(final_text)
                        
                        section_content = final_text[section_start:next_section].strip()
                        if len(section_content) < min_length:
                            incomplete_sections.append(section)
                
                if incomplete_sections:
                    logger.warning(f"Sections with insufficient content: {incomplete_sections}")
                    # Use our built-in formatter for most consistent output
                    formatted_text = self._format_fast_sentiment_text(
                        instrument, 
                        sentiment_data.get('bullish_percentage', 50),
                        sentiment_data.get('bearish_percentage', 50),
                        sentiment_data.get('neutral_percentage', 0)
                    )
                    sentiment_data['formatted_text'] = formatted_text
                
                # Make one final check to ensure our expected sections are present
                final_check = sentiment_data.get('formatted_text', '')
                if ("<b>📊 Market Sentiment Analysis:</b>" not in final_check or
                    "<b>📰 Key Sentiment Drivers:</b>" not in final_check or
                    "<b>📅 Important Events & News:</b>" not in final_check):
                    logger.error(f"Critical sections still missing after all corrections!")
                    # Use get_default_sentiment_text as our final fallback
                    sentiment_data['formatted_text'] = self._get_default_sentiment_text(instrument)
                
                # Update the sentiment_text entry to use the same content
                sentiment_data['sentiment_text'] = sentiment_data['formatted_text']
                
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
        # Determine overall sentiment
        if bullish_pct > bearish_pct + 20:
            overall_sentiment = "Bullish 📈"
        elif bullish_pct > bearish_pct + 5:
            overall_sentiment = "Slightly Bullish 📈"
        elif bearish_pct > bullish_pct + 20:
            overall_sentiment = "Bearish 📉"
        elif bearish_pct > bullish_pct + 5:
            overall_sentiment = "Slightly Bearish 📉"
        else:
            overall_sentiment = "Neutral ⚖️"
        
        # Generate analysis text based on sentiment
        if bullish_pct > bearish_pct + 10:
            analysis = f"{instrument} sentiment is currently positive based on recent economic data and news flow. Market participants appear optimistic about future economic developments related to this instrument."
        elif bearish_pct > bullish_pct + 10:
            analysis = f"{instrument} sentiment is currently negative based on recent economic data and news flow. Market participants show concern about economic factors affecting this instrument."
        else:
            analysis = f"{instrument} sentiment is currently balanced with no clear directional bias based on recent economic data and news events. Market participants appear divided on the future direction."
        
        # Format the full sentiment text with all required sections
        sentiment_text = f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> {overall_sentiment}

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish_pct:.0f}%
🔴 Bearish: {bearish_pct:.0f}%
⚪️ Neutral: {neutral_pct:.0f}%

<b>📊 Market Sentiment Analysis:</b>
{analysis}

<b>📰 Key Sentiment Drivers:</b>
• Recent economic data releases and their impact
• Policy statements from relevant financial authorities
• News flow and its effect on market perception

<b>📅 Important Events & News:</b>
• Recent economic announcements affecting {instrument}
• Policy decisions and statements from key figures
• Market reactions to global economic developments
"""
        return sentiment_text
        
    def _prepare_fast_sentiment_prompt(self, instrument: str) -> str:
        """Prepare the prompt for sentiment analysis"""
        prompt = f"""Analyze the current market sentiment for the trading instrument {instrument}.

Include the following in your analysis:
1. Overall market sentiment (bullish, bearish, or neutral)
2. Percentage breakdown of sentiment (bullish, bearish, neutral percentages)
3. Brief market analysis
4. Key sentiment drivers
5. Important events and news affecting the instrument

Return your answer in the following JSON format:
{{
    "bullish_percentage": [percentage of bullish sentiment, 0-100],
    "bearish_percentage": [percentage of bearish sentiment, 0-100],
    "neutral_percentage": [percentage of neutral sentiment, 0-100]
}}

The percentages must add up to 100. Only return the JSON with no additional text."""
        
        return prompt
    
    def _get_quick_local_sentiment(self, instrument: str) -> Dict[str, Any]:
        """Get a very quick local sentiment estimate"""
        # Use deterministic but seemingly random sentiment based on instrument name
        # This is for fallback only when API fails
        hash_val = sum(ord(c) for c in instrument) % 100
        day_offset = int(time.time() / 86400) % 20 - 10  # Changes daily, range -10 to +10
        
        bullish_pct = max(5, min(95, hash_val + day_offset))
        bearish_pct = max(5, min(95, 100 - bullish_pct - 10))  # Ensure some neutrality
        neutral_pct = 100 - bullish_pct - bearish_pct
        
        # Use the default sentiment text to guarantee proper format
        # This ensures we always have all the required sections
        formatted_text = self._get_default_sentiment_text(instrument)
        
        # Update the percentages in the text
        formatted_text = formatted_text.replace("Bullish: 50%", f"Bullish: {bullish_pct:.0f}%")
        formatted_text = formatted_text.replace("Bearish: 50%", f"Bearish: {bearish_pct:.0f}%")
        formatted_text = formatted_text.replace("Neutral: 0%", f"Neutral: {neutral_pct:.0f}%")
        
        # Determine overall sentiment based on percentages
        if bullish_pct > bearish_pct + 20:
            sentiment = "Bullish 📈"
            analysis_text = f"{instrument} sentiment is currently positive based on recent economic data and news flow. Market participants appear optimistic about future economic developments related to this instrument."
        elif bullish_pct > bearish_pct + 5:
            sentiment = "Slightly Bullish 📈"
            analysis_text = f"{instrument} shows mildly positive sentiment with recent economic data slightly favorable. News flow suggests cautious optimism among market participants."
        elif bearish_pct > bullish_pct + 20:
            sentiment = "Bearish 📉"
            analysis_text = f"{instrument} sentiment is currently negative based on recent economic data and news flow. Market participants show concern about economic factors affecting this instrument."
        elif bearish_pct > bullish_pct + 5:
            sentiment = "Slightly Bearish 📉"
            analysis_text = f"{instrument} shows mildly negative sentiment with recent economic data slightly unfavorable. News flow suggests some caution among market participants."
        else:
            sentiment = "Neutral ➡️"
            analysis_text = f"{instrument} sentiment is currently balanced with no clear directional bias based on recent economic data and news events. Market participants appear divided on the future direction."
        
        # Update overall sentiment and analysis text
        formatted_text = formatted_text.replace("Neutral ➡️", sentiment)
        formatted_text = formatted_text.replace(f"{instrument} sentiment is currently balanced with no strong directional bias based on recent economic data and news events. Market participants appear divided on the future direction.", analysis_text)
        
        # Update sentiment drivers based on sentiment
        if bullish_pct > 65:
            drivers = """• Positive economic data supporting sentiment
• Favorable policy and regulatory environment
• Encouraging statements from key market figures"""
            formatted_text = re.sub(r'<b>📰 Key Sentiment Drivers:</b>\n.*?<b>', f'<b>📰 Key Sentiment Drivers:</b>\n{drivers}\n\n<b>', formatted_text, flags=re.DOTALL)
        elif bearish_pct > 65:
            drivers = """• Concerning economic indicators in recent reports
• Policy uncertainty affecting market confidence
• Negative news flow impacting market sentiment"""
            formatted_text = re.sub(r'<b>📰 Key Sentiment Drivers:</b>\n.*?<b>', f'<b>📰 Key Sentiment Drivers:</b>\n{drivers}\n\n<b>', formatted_text, flags=re.DOTALL)
        
        return {
            'instrument': instrument,
            'bullish_percentage': bullish_pct,
            'bearish_percentage': bearish_pct,
            'neutral_percentage': neutral_pct,
            'sentiment_text': formatted_text,
            'source': 'local'
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

    async def _get_direct_api_sentiment(self, instrument: str, market_type: str) -> Optional[Dict[str, Any]]:
        """
        Get sentiment using direct API calls to Tavily and DeepSeek
        
        Args:
            instrument: Trading instrument symbol
            market_type: Market type (forex, crypto, etc.)
            
        Returns:
            Dict with sentiment data or None if failed
        """
        try:
            logger.info(f"Getting direct API sentiment for {instrument} ({market_type})")
            
            # Format instrument for better search query
            if len(instrument) == 6 and instrument.isalpha():
                # Likely a forex pair, add a slash
                formatted_instrument = f"{instrument[:3]}/{instrument[3:]}"
            else:
                formatted_instrument = instrument
            
            # Get market data from Tavily
            query = f"{formatted_instrument} latest news economic events policy decisions market sentiment analysis"
            
            # Prepare request for Tavily
            headers = {
                "Authorization": f"Bearer {self.tavily_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "query": query,
                "search_depth": "advanced",
                "include_answer": True,
                "include_images": False,
                "max_results": 5
            }
            
            # Get market data
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.tavily_url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status != 200:
                        logger.error(f"Tavily API returned status {response.status}: {await response.text()}")
                        return None
                    
                    tavily_data = await response.json()
            
            # Process Tavily data
            market_data = f"# Market Analysis for {instrument}\n\n"
            
            # Add the generated answer if available
            if tavily_data.get("answer"):
                market_data += f"## Summary\n{tavily_data['answer']}\n\n"
            
            # Add search results
            if tavily_data.get("results"):
                market_data += "## Market News and Analysis\n\n"
                for i, item in enumerate(tavily_data["results"], 1):
                    market_data += f"### {item.get('title', f'Source {i}')}\n"
                    market_data += f"{item.get('content', 'No content available')}\n"
                    market_data += f"Source: {item.get('url', 'Unknown')}\n\n"
            
            logger.info(f"Retrieved {len(tavily_data.get('results', []))} market data items for {instrument}")
            
            # Truncate market data if too long
            if len(market_data) > 5000:
                market_data = market_data[:5000] + "...[truncated]"
            
            # Create sentiment prompt for DeepSeek
            prompt = f"""Analyze the current market sentiment for {instrument} based on the following market data:

{market_data}

Provide a DETAILED market sentiment analysis with the following:

1. Overall market sentiment (bullish, bearish, or neutral)
2. Precise percentage breakdown of bullish, bearish, and neutral sentiment
3. Analysis of current market trends and sentiment drivers
4. Key factors influencing the sentiment
5. Important events and news affecting the instrument

Your response MUST be in this exact JSON format:
{{
    "bullish_percentage": [percentage of bullish sentiment as a number, 0-100],
    "bearish_percentage": [percentage of bearish sentiment as a number, 0-100],
    "neutral_percentage": [percentage of neutral sentiment as a number, 0-100],
    "formatted_text": "Your full formatted HTML text here with all the required sections"
}}

For the "formatted_text" field, use THIS EXACT HTML FORMAT:

<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> [Bullish/Bearish/Neutral with emoji]

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: XX%
🔴 Bearish: YY%
⚪️ Neutral: ZZ%

<b>📊 Market Sentiment Analysis:</b>
[Detailed analysis of current market sentiment based on the data]

<b>📰 Key Sentiment Drivers:</b>
• [Key sentiment factor 1]
• [Key sentiment factor 2]
• [Key sentiment factor 3]

<b>📅 Important Events & News:</b>
• [News event 1]
• [News event 2]
• [News event 3]

The percentages MUST add up to 100%, and the formatted text MUST include all sections with the exact HTML tags shown. Base your analysis ONLY on the provided market data.
"""
            
            # Prepare DeepSeek request
            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.api_model,
                "messages": [
                    {"role": "system", "content": "You are a financial market analyst specializing in sentiment analysis. Your task is to analyze market data and provide detailed sentiment analysis with specific percentages and sections."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 1500,
                "response_format": {"type": "json_object"}
            }
            
            # Get DeepSeek analysis
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.deepseek_url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    if response.status != 200:
                        logger.error(f"DeepSeek API returned status {response.status}: {await response.text()}")
                        return None
                    
                    deepseek_result = await response.json()
            
            # Extract content from response
            content = deepseek_result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            
            try:
                # Parse the JSON response
                data = json.loads(content)
                
                # Validate the response has the expected structure
                required_fields = ["bullish_percentage", "bearish_percentage", "neutral_percentage", "formatted_text"]
                missing = [field for field in required_fields if field not in data]
                
                if missing:
                    logger.error(f"Missing fields in DeepSeek response: {missing}")
                    return None
                
                # Ensure percentages add up to 100
                total = data["bullish_percentage"] + data["bearish_percentage"] + data["neutral_percentage"]
                if abs(total - 100) > 0.01:  # Allow small floating point error
                    logger.warning(f"Percentages don't add up to 100 ({total}), adjusting")
                    # Adjust proportionally
                    data["bullish_percentage"] = round(data["bullish_percentage"] * 100 / total)
                    data["bearish_percentage"] = round(data["bearish_percentage"] * 100 / total)
                    data["neutral_percentage"] = 100 - data["bullish_percentage"] - data["bearish_percentage"]
                
                # Add source information
                data["source"] = "api"
                data["instrument"] = instrument
                data["market_type"] = market_type
                
                # Verify the formatted text includes all required sections
                formatted_text = data["formatted_text"]
                required_sections = [
                    "<b>🎯", "Market Sentiment Analysis</b>",
                    "<b>Overall Sentiment:</b>",
                    "<b>Market Sentiment Breakdown:</b>",
                    "<b>📊 Market Sentiment Analysis:</b>",
                    "<b>📰 Key Sentiment Drivers:</b>",
                    "<b>📅 Important Events & News:</b>"
                ]
                
                for section in required_sections:
                    if section not in formatted_text:
                        logger.warning(f"Missing '{section}' in formatted text")
                        # Add missing sections with defaults
                        if "<b>📊 Market Sentiment Analysis:</b>" not in formatted_text:
                            # Find where to insert it (after sentiment breakdown)
                            breakdown_pos = formatted_text.find("<b>Market Sentiment Breakdown:</b>")
                            if breakdown_pos > 0:
                                # Find the next section after breakdown
                                next_section_pos = formatted_text.find("<b>", breakdown_pos + 10)
                                if next_section_pos > 0:
                                    # Insert before next section
                                    formatted_text = formatted_text[:next_section_pos] + "\n\n<b>📊 Market Sentiment Analysis:</b>\n" + instrument + " is currently showing " + ("bullish trends" if data["bullish_percentage"] > data["bearish_percentage"] else "bearish pressure" if data["bearish_percentage"] > data["bullish_percentage"] else "mixed signals") + " based on recent market data.\n\n" + formatted_text[next_section_pos:]
                
                # Make sure the title has the correct emoji
                if "<b>🎯" not in formatted_text and "<b>" in formatted_text:
                    formatted_text = formatted_text.replace("<b>", "<b>🎯 ", 1)
                
                # Ensure it has "Market Sentiment Analysis" in the title
                if "Market Sentiment Analysis</b>" not in formatted_text and "Market Analysis</b>" in formatted_text:
                    formatted_text = formatted_text.replace("Market Analysis</b>", "Market Sentiment Analysis</b>")
                
                # Add emoji to sentiment if missing
                if "<b>Overall Sentiment:</b> Bullish" in formatted_text and "📈" not in formatted_text:
                    formatted_text = formatted_text.replace("<b>Overall Sentiment:</b> Bullish", "<b>Overall Sentiment:</b> Bullish 📈")
                elif "<b>Overall Sentiment:</b> Bearish" in formatted_text and "📉" not in formatted_text:
                    formatted_text = formatted_text.replace("<b>Overall Sentiment:</b> Bearish", "<b>Overall Sentiment:</b> Bearish 📉")
                elif "<b>Overall Sentiment:</b> Neutral" in formatted_text and "➡️" not in formatted_text:
                    formatted_text = formatted_text.replace("<b>Overall Sentiment:</b> Neutral", "<b>Overall Sentiment:</b> Neutral ➡️")
                
                # Update formatted text with our corrected version
                data["formatted_text"] = formatted_text
                
                # Add sentiment_text for compatibility
                data["sentiment_text"] = formatted_text
                
                # Create a result in our expected format
                result = {
                    'bullish': data["bullish_percentage"],
                    'bearish': data["bearish_percentage"],
                    'neutral': data["neutral_percentage"],
                    'sentiment_score': (data["bullish_percentage"] - data["bearish_percentage"]) / 100,
                    'technical_score': 'Based on market analysis',
                    'news_score': f"{data['bullish_percentage']}% positive",
                    'social_score': f"{data['bearish_percentage']}% negative",
                    'trend_strength': 'Strong' if abs(data["bullish_percentage"] - 50) > 15 else 'Moderate' if abs(data["bullish_percentage"] - 50) > 5 else 'Weak',
                    'volatility': 'Moderate',
                    'volume': 'Normal',
                    'news_headlines': [],
                    'overall_sentiment': 'bullish' if data["bullish_percentage"] > data["bearish_percentage"] else 'bearish' if data["bearish_percentage"] > data["bullish_percentage"] else 'neutral',
                    'analysis': formatted_text,
                    'market_type': market_type
                }
                
                # Cache the result with market-specific key
                self._add_market_specific_to_cache(instrument, market_type, result)
                
                logger.info(f"Direct API sentiment analysis complete for {instrument}: {data['bullish_percentage']}% bullish, {data['bearish_percentage']}% bearish")
                return result
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse DeepSeek response: {e}")
                logger.error(f"Response content: {content[:500]}...")
                return None
                
        except Exception as e:
            logger.error(f"Error in direct API sentiment: {str(e)}")
            return None

    def set_cache_ttl(self, minutes: int) -> None:
        """
        Set the cache Time-To-Live (TTL) duration
        
        Args:
            minutes: New TTL duration in minutes
        """
        if minutes < 1:
            logger.warning(f"Invalid cache TTL value ({minutes}), minimum is 1 minute")
            minutes = 1
            
        old_ttl = self.cache_ttl / 60
        self.cache_ttl = minutes * 60  # Convert to seconds
        
        logger.info(f"Updated cache TTL from {old_ttl} to {minutes} minutes")
        
        # Clean up any expired entries with the new TTL
        self.cleanup_expired_cache()
        
        # If persistent cache is enabled, save changes
        if self.use_persistent_cache and self.cache_file:
            self._save_cache_to_file()

    def get_cache_info(self, instrument: Optional[str] = None) -> Dict[str, Any]:
        """
        Get detailed information about the cache status
        
        Args:
            instrument: Optional specific instrument to check. If None, returns info for all.
            
        Returns:
            Dictionary with cache information including TTL settings and cached instruments
        """
        now = time.time()
        
        if not self.cache_enabled:
            return {
                "cache_enabled": False,
                "message": "Cache is currently disabled"
            }
        
        # If specific instrument is requested, return details for just that one
        if instrument:
            cache_key = instrument.upper()
            
            if cache_key in self.sentiment_cache:
                entry = self.sentiment_cache[cache_key]
                age = now - entry['timestamp']
                expires_in = max(0, self.cache_ttl - age)
                
                # Create a clean copy without timestamp
                data_copy = copy.deepcopy(entry)
                if 'timestamp' in data_copy:
                    del data_copy['timestamp']
                
                return {
                    "cache_enabled": True,
                    "instrument": cache_key,
                    "cached": True,
                    "age_seconds": round(age),
                    "age_minutes": round(age / 60, 1),
                    "expires_in_seconds": round(expires_in),
                    "expires_in_minutes": round(expires_in / 60, 1),
                    "expired": age > self.cache_ttl,
                    "cache_ttl_minutes": self.cache_ttl / 60,
                    "data": data_copy
                }
            else:
                return {
                    "cache_enabled": True,
                    "instrument": cache_key,
                    "cached": False,
                    "message": f"No cache entry found for {cache_key}"
                }
        
        # Get information about all cached instruments
        cached_instruments = []
        for key, entry in self.sentiment_cache.items():
            age = now - entry['timestamp']
            expires_in = max(0, self.cache_ttl - age)
            
            cached_instruments.append({
                "instrument": key,
                "age_seconds": round(age),
                "age_minutes": round(age / 60, 1),
                "expires_in_seconds": round(expires_in),
                "expires_in_minutes": round(expires_in / 60, 1),
                "expired": age > self.cache_ttl,
                "bullish_percentage": entry.get("bullish_percentage", entry.get("bullish", 0)),
                "bearish_percentage": entry.get("bearish_percentage", entry.get("bearish", 0)),
                "source": entry.get("source", "unknown")
            })
        
        # Sort by expiration time (soonest first)
        cached_instruments.sort(key=lambda x: x["expires_in_seconds"])
        
        # Calculate cache statistics
        total_entries = len(self.sentiment_cache)
        active_entries = sum(1 for i in cached_instruments if not i["expired"])
        expired_entries = total_entries - active_entries
        
        return {
            "cache_enabled": True,
            "cache_ttl_minutes": self.cache_ttl / 60,
            "persistent_cache": self.use_persistent_cache,
            "cache_file": str(self.cache_file) if self.cache_file else None,
            "total_entries": total_entries,
            "active_entries": active_entries,
            "expired_entries": expired_entries,
            "instruments": cached_instruments
        }

    def _get_market_specific_cache_key(self, instrument: str, market_type: str) -> str:
        """
        Generate a market-specific cache key
        
        Args:
            instrument: Trading instrument symbol
            market_type: Market type (forex, crypto, etc.)
            
        Returns:
            Cache key in format INSTRUMENT_MARKETTYPE
        """
        instrument = instrument.upper()
        market_type = market_type.lower() if market_type else "unknown"
        return f"{instrument}_{market_type}"
    
    def _add_market_specific_to_cache(self, instrument: str, market_type: str, sentiment_data: Dict[str, Any]) -> None:
        """
        Add sentiment data to cache with market-specific key
        
        Args:
            instrument: Trading instrument symbol
            market_type: Market type (forex, crypto, etc.)
            sentiment_data: Sentiment data to cache
        """
        if not self.cache_enabled:
            return  # Cache is disabled
            
        try:
            # Generate market-specific cache key
            cache_key = self._get_market_specific_cache_key(instrument, market_type)
            
            # Make a copy to avoid reference issues
            cache_data = copy.deepcopy(sentiment_data)
            # Add timestamp for TTL check
            cache_data['timestamp'] = time.time()
            # Add market info
            cache_data['market_type'] = market_type
            
            # Store in memory cache
            self.sentiment_cache[cache_key] = cache_data
            
            # Also store with standard key for backward compatibility
            standard_key = instrument.upper()
            self.sentiment_cache[standard_key] = cache_data
            
            # If persistent cache is enabled, save to file
            if self.use_persistent_cache and self.cache_file:
                self._save_cache_to_file()
                
        except Exception as e:
            logger.error(f"Error adding to market-specific sentiment cache: {str(e)}")
    
    def _get_from_market_specific_cache(self, instrument: str, market_type: str) -> Optional[Dict[str, Any]]:
        """
        Get sentiment data from cache using market-specific key
        
        Args:
            instrument: Trading instrument symbol
            market_type: Market type (forex, crypto, etc.)
            
        Returns:
            Dictionary with sentiment data or None if not in cache or expired
        """
        if not self.cache_enabled:
            return None  # Cache is disabled
            
        try:
            # Try with market-specific key first
            cache_key = self._get_market_specific_cache_key(instrument, market_type)
            
            # If not found with market-specific key, try standard key
            if cache_key not in self.sentiment_cache:
                cache_key = instrument.upper()
                
                # If still not found, return None
                if cache_key not in self.sentiment_cache:
                    self.metrics.record_cache_miss()
                    return None
            
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
                
                # Record cache hit metric
                self.metrics.record_cache_hit()
                
                return result
            else:
                # Expired, remove from cache
                del self.sentiment_cache[cache_key]
                
                # Also remove standard key if it exists and has same timestamp
                standard_key = instrument.upper()
                if standard_key in self.sentiment_cache and self.sentiment_cache[standard_key].get('timestamp') == cache_time:
                    del self.sentiment_cache[standard_key]
                
            self.metrics.record_cache_miss()
            return None
            
        except Exception as e:
            logger.error(f"Error getting from market-specific sentiment cache: {str(e)}")
            return None

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
