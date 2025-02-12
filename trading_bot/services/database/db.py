from supabase import create_client, Client
import redis
import logging
import os
from typing import Dict, List

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        """Initialize database connection"""
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        
        if not supabase_url or not supabase_key:
            raise ValueError("Missing Supabase credentials")
            
        try:
            # Direct initialisatie zonder options
            self.supabase = create_client(supabase_url, supabase_key)
            logger.info("Successfully connected to Supabase")
        except Exception as e:
            logger.error(f"Failed to connect to Supabase: {str(e)}")
            raise
            
        # Setup Redis
        try:
            self.redis = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                decode_responses=True
            )
            logger.info("Successfully connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")
            raise
        
        self.CACHE_TIMEOUT = 300  # 5 minuten in seconden
        
    async def match_subscribers(self, signal: Dict) -> List[Dict]:
        """Match signal with subscriber preferences"""
        try:
            logger.info(f"Attempting to connect to Supabase with URL: {self.supabase.supabase_url}")
            logger.info(f"Incoming signal: {signal}")
            
            response = self.supabase.table("subscribers").select("*").execute()
            logger.info(f"Supabase response: {response}")
            
            # Transform subscriber data to include chat_id
            subscribers = []
            for s in response.data:
                s['chat_id'] = str(s['user_id'])  # Use user_id as chat_id
                subscribers.append(s)
            
            matches = [s for s in subscribers if self._matches_preferences(signal, s)]
            logger.info(f"Matched subscribers: {matches}")
            return matches
            
        except Exception as e:
            logger.error(f"Error matching subscribers: {str(e)}", exc_info=True)
            return []
            
    async def get_cached_sentiment(self, symbol: str) -> str:
        """Get cached sentiment analysis"""
        return self.redis.get(f"sentiment:{symbol}")
        
    async def cache_sentiment(self, symbol: str, sentiment: str) -> None:
        """Cache sentiment analysis"""
        try:
            self.redis.set(f"sentiment:{symbol}", sentiment, ex=self.CACHE_TIMEOUT)
        except Exception as e:
            logger.error(f"Error caching sentiment: {str(e)}")
            
    def _matches_preferences(self, signal: Dict, subscriber: Dict) -> bool:
        """Check if signal matches subscriber preferences"""
        logger.info(f"Checking preferences for subscriber: {subscriber}")
        
        # Check if subscriber is active
        if not subscriber.get("is_active", False):
            return False
        
        # Check symbol
        if subscriber.get("symbols"):
            if signal["symbol"] not in subscriber["symbols"]:
                return False
        
        # Check timeframe
        if subscriber.get("timeframes"):
            if signal["timeframe"] not in subscriber["timeframes"]:
                return False
        
        return True
