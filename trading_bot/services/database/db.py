from supabase import create_client, Client
import redis
import logging
import os
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        """Initialize database connections"""
        try:
            # Supabase setup
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_KEY")
            
            if not supabase_url or not supabase_key:
                raise ValueError("Missing Supabase credentials")
                
            self.supabase = create_client(supabase_url, supabase_key)
            
            # Test de connectie
            test_query = self.supabase.table('subscriber_preferences').select('*').limit(1).execute()
            logger.info(f"Supabase connection test successful: {test_query}")
            
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
        
    async def match_subscribers(self, signal: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Match signal with subscribers based on market, instrument and timeframe"""
        try:
            # Log het inkomende signaal
            logger.info(f"Incoming signal: market={signal['market']}, symbol={signal['symbol']}, timeframe={signal['timeframe']}")
            
            # Haal alle actieve subscribers op (zonder await)
            subscribers = self.supabase.table('subscriber_preferences').select('*').execute()
            total_subscribers = len(subscribers.data)
            logger.info(f"Found {total_subscribers} total subscribers in database")

            # Filter subscribers die matchen met het signaal
            matched_subscribers = []
            for subscriber in subscribers.data:
                # Converteer alles naar lowercase voor case-insensitive vergelijking
                subscriber_market = subscriber['market'].lower()
                subscriber_instrument = subscriber['instrument'].lower()
                signal_market = signal['market'].lower()
                signal_symbol = signal['symbol'].lower()
                
                # Log elke vergelijking
                logger.info(f"Checking subscriber {subscriber['id']}: "
                           f"market={subscriber_market}=={signal_market}, "
                           f"instrument={subscriber_instrument}=={signal_symbol}, "
                           f"timeframe={subscriber['timeframe']}=={signal['timeframe']}")

                # Check of market, instrument en timeframe matchen
                if (subscriber_market == signal_market and
                    subscriber_instrument == signal_symbol and
                    subscriber['timeframe'] == signal['timeframe'] and
                    subscriber.get('is_active', True)):
                    
                    # Voeg chat_id toe aan subscriber data
                    subscriber['chat_id'] = str(subscriber['user_id'])
                    matched_subscribers.append(subscriber)
                    logger.info(f"✅ Matched subscriber {subscriber['id']}: user_id={subscriber['user_id']}")
                else:
                    logger.info(f"❌ No match for subscriber {subscriber['id']}")

            # Log samenvattende statistieken
            logger.info(f"Matching Summary:")
            logger.info(f"- Total subscribers: {total_subscribers}")
            logger.info(f"- Matched subscribers: {len(matched_subscribers)}")
            logger.info(f"- Match rate: {(len(matched_subscribers)/total_subscribers)*100:.1f}%")
            if matched_subscribers:
                logger.info(f"- Matched user_ids: {[sub['user_id'] for sub in matched_subscribers]}")

            return matched_subscribers

        except Exception as e:
            logger.error(f"Error matching subscribers: {str(e)}")
            logger.exception(e)
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
