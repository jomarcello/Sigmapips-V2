from supabase import create_client, Client
import redis
import logging
import os
from typing import Dict, List, Any
import re
import stripe
import datetime
from datetime import timezone

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
        self.VALID_STYLES = ['test', 'scalp', 'scalp30', 'intraday', 'swing']
        self.STYLE_TIMEFRAME_MAP = {
            'test': '1m',
            'scalp': '15m',
            'scalp30': '30m',
            'intraday': '1h',
            'swing': '4h'
        }
        
    async def match_subscribers(self, signal):
        """Match subscribers to a signal"""
        try:
            # Zorg ervoor dat we altijd dictionary-keys gebruiken
            if isinstance(signal, str):
                logger.warning(f"Signal is a string instead of a dictionary: {signal}")
                return []
            
            market = signal.get('market', '')
            # Als er geen market is, probeer deze af te leiden van het instrument
            if not market:
                instrument = signal.get('symbol', '') or signal.get('instrument', '')
                market = self._detect_market(instrument)
                logger.info(f"Detected market for {instrument}: {market}")
            
            instrument = signal.get('symbol', '') or signal.get('instrument', '')
            timeframe = signal.get('interval', '1h')  # Gebruik interval indien aanwezig
            
            logger.info(f"Matching subscribers for: market={market}, instrument={instrument}, timeframe={timeframe}")
            
            # Haal alle abonnees op
            all_preferences = await self.get_all_preferences()
            if not all_preferences:
                logger.warning("No preferences found in database")
                return []
            
            # Normaliseer de timeframe voor vergelijking
            normalized_timeframe = self._normalize_timeframe(timeframe)
            logger.info(f"Normalized timeframe: {normalized_timeframe}")
            
            # Filter handmatig op basis van de signaalgegevens
            matched_subscribers = []
            seen_user_ids = set()  # Bijhouden welke gebruikers we al hebben toegevoegd
            
            for pref in all_preferences:
                # Sla ongeldige voorkeuren over
                if not isinstance(pref, dict):
                    logger.warning(f"Skipping invalid preference (not a dict): {pref}")
                    continue
                
                # Normaliseer de timeframe in de voorkeur
                pref_timeframe = self._normalize_timeframe(pref.get('timeframe', '1h'))
                
                # Debug logging
                logger.info(f"Checking preference: market={pref.get('market')}, instrument={pref.get('instrument')}, timeframe={pref.get('timeframe')} (normalized: {pref_timeframe})")
                
                # Controleer of de voorkeuren overeenkomen met het signaal
                if (pref.get('market') == market and 
                    pref.get('instrument') == instrument and 
                    pref_timeframe == normalized_timeframe):
                    
                    user_id = pref.get('user_id')
                    
                    # Controleer of we deze gebruiker al hebben toegevoegd
                    if user_id not in seen_user_ids:
                        # Voeg de gebruiker toe aan de lijst met matches
                        matched_subscribers.append(pref)
                        seen_user_ids.add(user_id)  # Markeer deze gebruiker als gezien
                        logger.info(f"Matched subscriber: user_id={user_id}, market={pref.get('market')}, instrument={pref.get('instrument')}, timeframe={pref.get('timeframe')}")
                    else:
                        logger.info(f"Skipping duplicate subscriber: user_id={user_id}, already matched")
            
            # Log het resultaat
            logger.info(f"Found {len(matched_subscribers)} unique matching subscribers")
            
            return matched_subscribers
        except Exception as e:
            logger.error(f"Error matching subscribers: {str(e)}")
            logger.exception(e)
            return []

    def _normalize_timeframe(self, timeframe):
        """Normalize timeframe for comparison (e.g., '1' and '1m' should match)"""
        if not timeframe:
            return '1h'  # Default
        
        try:
            # Als het een dict is, probeer de waarde op te halen
            if isinstance(timeframe, dict) and 'timeframe' in timeframe:
                timeframe = timeframe['timeframe']
        except:
            # Als er iets misgaat, gebruik de default
            return '1h'
        
        # Converteer naar string
        tf_str = str(timeframe).lower()
        
        # Verwijder spaties en aanhalingstekens
        tf_str = tf_str.strip().strip('"\'')
        
        # Normaliseer minuten
        if tf_str in ['1', '1m', '"1m"', "'1m'"]:
            return '1m'
        if tf_str in ['5', '5m', '"5m"', "'5m'"]:
            return '5m'
        if tf_str in ['15', '15m', '"15m"', "'15m'"]:
            return '15m'
        if tf_str in ['30', '30m', '"30m"', "'30m'"]:
            return '30m'
        
        # Normaliseer uren
        if tf_str in ['60', '1h', '"1h"', "'1h'"]:
            return '1h'
        if tf_str in ['120', '2h', '"2h"', "'2h'"]:
            return '2h'
        if tf_str in ['240', '4h', '"4h"', "'4h'"]:
            return '4h'
        
        # Normaliseer dagen
        if tf_str in ['1440', '1d', '"1d"', "'1d'"]:
            return '1d'
        
        # Als geen match, geef de originele waarde terug
        return tf_str

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

    async def get_user_subscription(self, user_id: int):
        """Get subscription status for a user"""
        try:
            response = self.supabase.table('user_subscriptions').select('*').eq('user_id', user_id).limit(1).execute()
            
            if response.data and len(response.data) > 0:
                return response.data[0]
            else:
                return None
        except Exception as e:
            logger.error(f"Error getting user subscription: {str(e)}")
            return None
    
    async def create_or_update_subscription(self, user_id: int, stripe_customer_id: str = None, 
                                           stripe_subscription_id: str = None, status: str = 'inactive',
                                           subscription_type: str = 'basic', current_period_end: datetime.datetime = None):
        """Maak of update een gebruikersabonnement"""
        try:
            # Controleer of gebruiker al een abonnement heeft
            existing = await self.get_user_subscription(user_id)
            
            subscription_data = {
                'user_id': user_id,
                'subscription_status': status,
                'subscription_type': subscription_type,
                'updated_at': datetime.datetime.now().isoformat()
            }
            
            if stripe_customer_id:
                subscription_data['stripe_customer_id'] = stripe_customer_id
                
            if stripe_subscription_id:
                subscription_data['stripe_subscription_id'] = stripe_subscription_id
                
            if current_period_end:
                subscription_data['current_period_end'] = current_period_end.isoformat()
            
            if existing:
                # Update bestaand abonnement
                response = self.supabase.table('user_subscriptions').update(subscription_data).eq('user_id', user_id).execute()
            else:
                # Maak nieuw abonnement
                response = self.supabase.table('user_subscriptions').insert(subscription_data).execute()
            
            if response.data:
                logger.info(f"Subscription updated for user {user_id}: {status}")
                return True
            else:
                logger.error(f"Failed to update subscription: {response}")
                return False
        except Exception as e:
            logger.error(f"Error updating subscription: {str(e)}")
            return False
    
    async def is_user_subscribed(self, user_id: int) -> bool:
        """Check if user has an active subscription"""
        try:
            # Add debugging
            logger.info(f"Checking subscription for user {user_id}")
            
            # Retrieve the user's subscription
            subscription = await self.get_user_subscription(user_id)
            logger.info(f"Subscription data: {subscription}")
            
            if not subscription:
                logger.info(f"User {user_id} has no subscription record")
                return False
            
            # Check if status is active or trialing
            status = subscription.get('subscription_status')
            logger.info(f"Subscription status: {status}")
            
            # Consider any of these statuses as active
            if status in ['active', 'trialing', 'past_due']:
                # For debugging: skip end date check temporarily
                logger.info(f"User {user_id} has active status: {status}")
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Error checking subscription status: {str(e)}")
            return False
            
    async def get_user_subscription_type(self, user_id: int):
        """Haal het type abonnement op voor een gebruiker"""
        try:
            subscription = await self.get_user_subscription(user_id)
            
            if subscription and subscription.get('subscription_status') in ['active', 'trialing']:
                return subscription.get('subscription_type', 'basic')
            else:
                return None
        except Exception as e:
            logger.error(f"Error getting subscription type: {str(e)}")
            return None

    async def save_user(self, user_id: int, first_name: str, last_name: str = None, username: str = None) -> bool:
        """Sla een gebruiker op in de database"""
        try:
            logger.info(f"Gebruiker opslaan: {user_id} ({first_name})")
            # Hier zou je code komen om de gebruiker op te slaan in je database
            # Voor nu implementeren we een lege placeholder
            return True
        except Exception as e:
            logger.error(f"Fout bij opslaan gebruiker: {str(e)}")
            return False

    def _detect_market(self, symbol: str) -> str:
        """Detecteer market type gebaseerd op symbol"""
        if not symbol:
            return "forex"  # Default
        
        symbol = str(symbol).upper()
        
        # Commodities eerst checken
        commodities = [
            "XAUUSD",  # Gold
            "XAGUSD",  # Silver
            "WTIUSD",  # Oil WTI
            "BCOUSD",  # Oil Brent
        ]
        if symbol in commodities:
            return "commodities"
        
        # Crypto pairs
        crypto_base = ["BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "DOT", "LINK"]
        if any(c in symbol for c in crypto_base):
            return "crypto"
        
        # Major indices
        indices = [
            "US30", "US500", "US100",  # US indices
            "UK100", "DE40", "FR40",   # European indices
            "JP225", "AU200", "HK50"   # Asian indices
        ]
        if symbol in indices:
            return "indices"
        
        # Forex pairs als default
        return "forex" 
