import os
import time
import json
import asyncio
import logging
import copy
import pathlib
from typing import Dict, Any, Optional
import threading

logger = logging.getLogger(__name__)

class SentimentCacheManager:
    """
    Manages caching of sentiment data for market instruments
    with a 30-minute Time-To-Live (TTL) for cached entries.
    
    This class provides thread-safe and async-safe operations for
    storing and retrieving sentiment data in a shared cache.
    """
    
    def __init__(self, ttl_minutes: int = 30, persistent_cache: bool = True, cache_file: str = None):
        """
        Initialize the sentiment cache manager
        
        Args:
            ttl_minutes: Cache TTL in minutes (default: 30)
            persistent_cache: Whether to save/load cache to/from disk
            cache_file: Path to cache file, if None uses default in user's home directory
        """
        self.cache_ttl = ttl_minutes * 60  # Convert minutes to seconds
        self.use_persistent_cache = persistent_cache
        
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
        
        # Cache stats
        self.cache_hits = 0
        self.cache_misses = 0
        
        # Thread lock for thread safety
        self._cache_lock = threading.Lock()
        
        # Async lock for async safety
        self._async_lock = asyncio.Lock()
        
        # Load cache if persistent
        if self.use_persistent_cache:
            self._load_cache_from_file()
        
        logger.info(f"Sentiment cache initialized with TTL: {ttl_minutes} minutes")
        logger.info(f"Persistent cache: {'enabled' if self.use_persistent_cache else 'disabled'}")
    
    async def get(self, instrument: str) -> Optional[Dict[str, Any]]:
        """
        Get sentiment data from cache if available and not expired (async version)
        
        Args:
            instrument: The instrument to get cached data for
            
        Returns:
            Dict or None: The cached sentiment data or None if not found/expired
        """
        async with self._async_lock:
            result = self._get_from_cache(instrument)
            if result:
                self.cache_hits += 1
                logger.info(f"Cache HIT for {instrument}")
            else:
                self.cache_misses += 1
                logger.info(f"Cache MISS for {instrument}")
            return result
    
    async def set(self, instrument: str, sentiment_data: Dict[str, Any]) -> None:
        """
        Add sentiment data to cache with TTL (async version)
        
        Args:
            instrument: The instrument to cache data for
            sentiment_data: The sentiment data to cache
        """
        async with self._async_lock:
            self._add_to_cache(instrument, sentiment_data)
    
    def _add_to_cache(self, instrument: str, sentiment_data: Dict[str, Any]) -> None:
        """Add sentiment data to cache with TTL (synchronous implementation)"""
        try:
            with self._cache_lock:
                cache_key = instrument.upper()
                
                # Make a copy to avoid reference issues
                cache_data = copy.deepcopy(sentiment_data)
                # Add timestamp for TTL check
                cache_data['timestamp'] = time.time()
                
                # Store in memory cache
                self.sentiment_cache[cache_key] = cache_data
                
                # If persistent cache is enabled, save to file
                if self.use_persistent_cache:
                    self._save_cache_to_file()
                    
        except Exception as e:
            logger.error(f"Error adding to sentiment cache: {str(e)}")
    
    def _get_from_cache(self, instrument: str) -> Optional[Dict[str, Any]]:
        """Get sentiment data from cache if available and not expired (synchronous implementation)"""
        try:
            with self._cache_lock:
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
        if not self.use_persistent_cache:
            return  # No persistent cache
            
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
        if not self.use_persistent_cache:
            return  # No persistent cache
            
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
    
    def clear(self, instrument: Optional[str] = None) -> None:
        """
        Clear cache entries for a specific instrument or all instruments
        
        Args:
            instrument: Optional instrument to clear from cache. If None, clears all cache.
        """
        with self._cache_lock:
            if instrument:
                cache_key = instrument.upper()
                removed = self.sentiment_cache.pop(cache_key, None)
                if removed:
                    logger.info(f"Cleared cache for {instrument}")
                    # Update cache file if persistent
                    if self.use_persistent_cache:
                        self._save_cache_to_file()
                else:
                    logger.info(f"No cache found for {instrument}")
            else:
                cache_size = len(self.sentiment_cache)
                self.sentiment_cache.clear()
                logger.info(f"Cleared complete sentiment cache ({cache_size} entries)")
                # Update cache file if persistent
                if self.use_persistent_cache and cache_size > 0:
                    self._save_cache_to_file()
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired entries from the cache
        
        Returns:
            int: Number of entries removed
        """
        removed_count = 0
        with self._cache_lock:
            current_time = time.time()
            keys_to_remove = []
            
            for key, data in self.sentiment_cache.items():
                cache_time = data.get('timestamp', 0)
                if current_time - cache_time >= self.cache_ttl:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self.sentiment_cache[key]
                removed_count += 1
            
            if removed_count > 0 and self.use_persistent_cache:
                self._save_cache_to_file()
                
        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} expired cache entries")
            
        return removed_count
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics
        
        Returns:
            Dict: Statistics about the cache
        """
        with self._cache_lock:
            # Count unexpired items
            current_time = time.time()
            valid_count = 0
            expired_count = 0
            
            for data in self.sentiment_cache.values():
                cache_time = data.get('timestamp', 0)
                if current_time - cache_time < self.cache_ttl:
                    valid_count += 1
                else:
                    expired_count += 1
            
            total_requests = self.cache_hits + self.cache_misses
            hit_rate = (self.cache_hits / total_requests * 100) if total_requests > 0 else 0
            
            return {
                'total_items': len(self.sentiment_cache),
                'valid_items': valid_count,
                'expired_items': expired_count,
                'cache_hits': self.cache_hits,
                'cache_misses': self.cache_misses,
                'hit_rate_percent': hit_rate,
                'ttl_seconds': self.cache_ttl,
                'persistent': self.use_persistent_cache
            } 
