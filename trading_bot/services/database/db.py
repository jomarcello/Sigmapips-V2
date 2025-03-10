from supabase import create_client, Client
import redis
import logging
import os
from typing import Dict, List, Any
import re

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
            redis_host = os.getenv("REDIS_HOST", "redis")
            redis_port = int(os.getenv("REDIS_PORT", 6379))
            redis_password = os.getenv("REDIS_PASSWORD", None)
            
            self.redis = redis.Redis(
                host=redis_host,
                port=redis_port,
                password=redis_password,
                db=0,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                retry_on_timeout=True,
                health_check_interval=30
            )
            
            # Test de verbinding
            self.redis.ping()
            logger.info(f"Redis connection established to {redis_host}:{redis_port}")
        except Exception as redis_error:
            logger.warning(f"Redis connection failed: {str(redis_error)}. Using local caching.")
            self.redis = None
        
        self.CACHE_TIMEOUT = 300  # 5 minuten in seconden
        
        # Validatie constanten
        self.VALID_STYLES = ['test', 'scalp', 'intraday', 'swing']
        self.STYLE_TIMEFRAME_MAP = {
            'test': '1m',
            'scalp': '15m',
            'intraday': '1h',
            'swing': '4h'
        }
        
    async def match_subscribers(self, signal):
        """Match subscribers to a signal"""
        try:
            market = signal.get('market', 'forex')
            instrument = signal.get('symbol', '')
            timeframe = signal.get('timeframe', '1h')
            
            logger.info(f"Matching subscribers for: market={market}, instrument={instrument}, timeframe={timeframe}")
            
            # Haal alle abonnees op
            all_preferences = await self.get_all_preferences()
            
            # Filter handmatig op basis van de signaalgegevens
            matched_subscribers = []
            for pref in all_preferences:
                # Controleer of de voorkeuren overeenkomen met het signaal
                if (pref.get('market') == market and 
                    pref.get('instrument') == instrument and 
                    pref.get('timeframe') == timeframe):
                    
                    # Voeg de gebruiker toe aan de lijst met matches
                    matched_subscribers.append(pref)
                    logger.info(f"Matched subscriber: user_id={pref.get('user_id')}, market={pref.get('market')}, instrument={pref.get('instrument')}, timeframe={pref.get('timeframe')}")
            
            # Log het resultaat
            logger.info(f"Found {len(matched_subscribers)} matching subscribers")
            
            return matched_subscribers
        except Exception as e:
            logger.error(f"Error matching subscribers: {str(e)}")
            logger.exception(e)
            return []

    async def get_all_preferences(self):
        """Get all subscriber preferences"""
        try:
            # Haal alle voorkeuren op uit de database
            response = self.supabase.table('subscriber_preferences').select('*').execute()
            
            if response.data:
                return response.data
            else:
                return []
        except Exception as e:
            logger.error(f"Error getting all preferences: {str(e)}")
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

    async def save_preferences(self, user_id: int, market: str, instrument: str, style: str):
        """Save user preferences with validation"""
        try:
            if style not in self.VALID_STYLES:
                raise ValueError(f"Invalid style: {style}")
                
            timeframe = self.STYLE_TIMEFRAME_MAP[style]
            
            data = {
                'user_id': user_id,
                'market': market,
                'instrument': instrument,
                'style': style,
                'timeframe': timeframe
            }
            
            response = self.supabase.table('subscriber_preferences').insert(data).execute()
            return response
            
        except Exception as e:
            logger.error(f"Error saving preferences: {str(e)}")
            raise 

    async def get_subscribers(self, instrument: str, timeframe: str = None):
        """Get all subscribers for an instrument and timeframe"""
        query = self.supabase.table('subscriber_preferences')\
            .select('*')\
            .eq('instrument', instrument)
        
        # Als timeframe '1m' is, voeg style='test' toe
        if timeframe == '1m':
            query = query.eq('style', 'test')
        elif timeframe:
            # Map timeframe naar style
            style_map = {
                '15m': 'scalp',
                '1h': 'intraday',
                '4h': 'swing'
            }
            if timeframe in style_map:
                query = query.eq('style', style_map[timeframe])
        
        return query.execute() 

    async def get_user_preferences(self, user_id: int) -> List[Dict[str, Any]]:
        """Get user preferences from database"""
        try:
            # Haal voorkeuren op uit de database
            response = self.supabase.table('subscriber_preferences').select('*').eq('user_id', user_id).execute()
            
            if response.data:
                return response.data
            else:
                return []
        except Exception as e:
            logger.error(f"Error getting user preferences: {str(e)}")
            return []

    async def save_preference(self, user_id: int, market: str, instrument: str, style: str, timeframe: str) -> bool:
        """Save user preference to database"""
        try:
            # Maak een nieuwe voorkeur
            new_preference = {
                'user_id': user_id,
                'market': market,
                'instrument': instrument,
                'style': style,
                'timeframe': timeframe
            }
            
            # Sla op in de database
            response = self.supabase.table('subscriber_preferences').insert(new_preference).execute()
            
            if response.data:
                logger.info(f"Saved preference for user {user_id}: {instrument} ({timeframe})")
                return True
            else:
                logger.error(f"Failed to save preference: {response}")
                return False
        except Exception as e:
            logger.error(f"Error saving preference: {str(e)}")
            return False

    async def delete_preference(self, user_id: int, instrument: str) -> bool:
        """Delete user preference from database"""
        try:
            # Verwijder de voorkeur
            response = self.supabase.table('subscriber_preferences').delete().eq('user_id', user_id).eq('instrument', instrument).execute()
            
            if response.data:
                logger.info(f"Deleted preference for user {user_id}: {instrument}")
                return True
            else:
                logger.error(f"Failed to delete preference: {response}")
                return False
        except Exception as e:
            logger.error(f"Error deleting preference: {str(e)}")
            return False

    async def delete_all_preferences(self, user_id: int) -> bool:
        """Delete all preferences for a user"""
        try:
            # Delete all preferences for this user using Supabase
            response = self.supabase.table('subscriber_preferences').delete().eq('user_id', user_id).execute()
            
            if response.data:
                logger.info(f"Deleted all preferences for user {user_id}")
                return True
            else:
                logger.error(f"Failed to delete all preferences: {response}")
                return False
        except Exception as e:
            logger.error(f"Error deleting preferences: {str(e)}")
            return False

    async def delete_preference_by_id(self, preference_id: int) -> bool:
        """Delete a preference by its ID"""
        try:
            # Delete the preference
            response = self.supabase.table('subscriber_preferences').delete().eq('id', preference_id).execute()
            
            if response.data:
                logger.info(f"Deleted preference with ID {preference_id}")
                return True
            else:
                logger.error(f"Failed to delete preference: {response}")
                return False
        except Exception as e:
            logger.error(f"Error deleting preference: {str(e)}")
            return False

    async def execute_query(self, query: str) -> List[Dict[str, Any]]:
        """Execute a query on Supabase (simplified version)"""
        try:
            logger.info(f"Executing query: {query}")
            
            # Eenvoudige implementatie: haal alle subscriber_preferences op en filter handmatig
            result = self.supabase.table('subscriber_preferences').select('*').execute()
            
            # Log het resultaat
            logger.info(f"Raw query result: {result.data}")
            
            # Als de query een filter op market, instrument en timeframe bevat, filter dan handmatig
            if 'market' in query and 'instrument' in query and 'timeframe' in query:
                # Extraheer de waarden (eenvoudige implementatie)
                market_match = re.search(r"market\s*=\s*'([^']*)'", query)
                instrument_match = re.search(r"instrument\s*=\s*'([^']*)'", query)
                timeframe_match = re.search(r"timeframe\s*=\s*'([^']*)'", query)
                
                if market_match and instrument_match and timeframe_match:
                    market = market_match.group(1)
                    instrument = instrument_match.group(1)
                    timeframe = timeframe_match.group(1)
                    
                    # Filter handmatig
                    filtered_result = [
                        item for item in result.data
                        if item.get('market') == market and 
                           item.get('instrument') == instrument and 
                           item.get('timeframe') == timeframe
                    ]
                    
                    logger.info(f"Filtered result: {filtered_result}")
                    return filtered_result
            
            return result.data
        except Exception as e:
            logger.error(f"Error executing query: {str(e)}")
            logger.exception(e)
            return []

    async def get_all_users(self):
        """Get all users from the database"""
        try:
            # Probeer eerst de users tabel
            try:
                users = await self.execute_query("SELECT * FROM users")
            except Exception as e:
                # Als users tabel niet bestaat, probeer subscriber_preferences
                logger.warning(f"Could not query users table: {str(e)}")
                users = await self.execute_query("SELECT DISTINCT user_id FROM subscriber_preferences")
                
                # Als dat ook niet werkt, gebruik een hardcoded test gebruiker
                if not users:
                    logger.warning("No users found in subscriber_preferences, using test user")
                    return [{'user_id': 2004519703}]  # Vervang met je eigen user ID
            
            return users
        except Exception as e:
            logger.error(f"Error getting users: {str(e)}")
            # Fallback naar test gebruiker
            return [{'user_id': 2004519703}]  # Vervang met je eigen user ID 
