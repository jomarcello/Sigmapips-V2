from supabase import create_client, Client
import redis
import logging
import os
from typing import Dict, List, Any
import re
import stripe
import datetime
from datetime import timezone
import traceback

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        """Initialize the database connection."""
        # Get environment variables
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_KEY")
        self.redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
        
        # Local caching
        self.cache = {}
        self.cache_expiry = {}
        self.default_cache_ttl = 3600  # Default cache TTL in seconds
        
        # Flags
        self.use_mock_data = os.getenv("USE_MOCK_DATA", "false").lower() == "true"
        self.using_redis = False
        self.subscriber_cache = {}
        
        try:
            # Initialize Supabase client if credentials are provided
            if self.supabase_url and self.supabase_key:
                self.supabase = create_client(self.supabase_url, self.supabase_key)
                
                # Test connection - will raise an exception if it fails
                try:
                    # Test Supabase connection
                    data = self.supabase.table("subscriber_preferences").select("*").limit(1).execute()
                    logger.info(f"Supabase connection test successful: data={data.data} count={data.count}")
                    logger.info("Successfully connected to Supabase")
                    
                    # Mark that we should not use mock data even if the USE_MOCK_DATA flag is set
                    self.use_mock_data = False
                except Exception as e:
                    logger.error(f"Error connecting to Supabase: {str(e)}")
                    if not self.use_mock_data:
                        # Only fall back to mock data if explicitly enabled
                        raise
                    logger.warning("Falling back to mock data due to Supabase connection failure")
                    self._setup_mock_data()
            else:
                if not self.use_mock_data:
                    logger.warning("Missing Supabase credentials, using mock data")
                    self.use_mock_data = True
                self._setup_mock_data()
                
            # Initialize Redis connection for caching if available
            try:
                self.redis = redis.from_url(self.redis_url, decode_responses=True)
                self.redis.ping()  # Test connection
                self.using_redis = True
                logger.info("Successfully connected to Redis")
            except Exception as e:
                logger.warning(f"Redis connection failed: {str(e)}. Using local caching.")
                self.redis = None
                
            # Setup mock data if needed
            if self.use_mock_data:
                self._setup_mock_data()
                
        except Exception as e:
            logger.error(f"Error initializing database: {str(e)}")
            # Setup mock data as fallback
            self._setup_mock_data()
        
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
        
    def _setup_mock_data(self):
        """Set up mock data for development and testing"""
        logger.info("Setting up mock data for database")
        
        # Mock subscribers
        self.mock_subscribers = [
            {
                "id": 1,
                "user_id": 12345,
                "market": "forex",
                "instrument": "EURUSD",
                "timeframe": "1h",
                "is_active": True,
                "created_at": "2023-01-01T00:00:00"
            },
            {
                "id": 2,
                "user_id": 67890,
                "market": "forex",
                "instrument": "ALL",
                "timeframe": "ALL",
                "is_active": True,
                "created_at": "2023-01-01T00:00:00"
            },
            {
                "id": 3,
                "user_id": 54321,
                "market": "crypto",
                "instrument": "BTCUSD",
                "timeframe": "1h",
                "is_active": True,
                "created_at": "2023-01-01T00:00:00"
            }
        ]
        
        # Mock users
        self.mock_users = [
            {
                "id": 12345,
                "first_name": "John",
                "last_name": "Doe",
                "username": "johndoe",
                "is_active": True,
                "created_at": "2023-01-01T00:00:00"
            },
            {
                "id": 67890,
                "first_name": "Jane",
                "last_name": "Smith",
                "username": "janesmith",
                "is_active": True,
                "created_at": "2023-01-01T00:00:00"
            },
            {
                "id": 54321,
                "first_name": "Bob",
                "last_name": "Johnson",
                "username": "bobjohnson",
                "is_active": True,
                "created_at": "2023-01-01T00:00:00"
            }
        ]
        
        # Mock subscriptions
        self.mock_subscriptions = [
            {
                "id": 1,
                "user_id": 12345,
                "subscription_type": "premium",
                "status": "active",
                "current_period_end": (datetime.datetime.now() + datetime.timedelta(days=30)).isoformat(),
                "created_at": "2023-01-01T00:00:00"
            },
            {
                "id": 2,
                "user_id": 67890,
                "subscription_type": "premium",
                "status": "active",
                "current_period_end": (datetime.datetime.now() + datetime.timedelta(days=30)).isoformat(),
                "created_at": "2023-01-01T00:00:00"
            },
            {
                "id": 3,
                "user_id": 54321,
                "subscription_type": "basic",
                "status": "active",
                "current_period_end": (datetime.datetime.now() + datetime.timedelta(days=30)).isoformat(),
                "created_at": "2023-01-01T00:00:00"
            }
        ]
        
        logger.info("Mock data setup complete")
        
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
                # Check for market match
                market_match = pref.get('market', '').lower() == market.lower()
                
                # Check for instrument match - either exact match or 'ALL'
                instrument_match = (pref.get('instrument', '') == instrument) or (pref.get('instrument', '') == 'ALL')
                
                # Check for timeframe match - optional matching
                timeframe_match = pref_timeframe == normalized_timeframe
                
                # If timeframe preference is 'ALL', it matches any signal timeframe
                if pref.get('timeframe', '') == 'ALL':
                    timeframe_match = True
                    
                # Log match details for debugging
                logger.info(f"Match results: market={market_match}, instrument={instrument_match}, timeframe={timeframe_match}")
                
                # A subscriber matches if market AND (instrument OR ALL) AND (timeframe OR ALL)
                if market_match and instrument_match:
                    # Optionally add timeframe matching if needed
                    # For now we'll consider a match even without matching timeframe
                    
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
            if self.use_mock_data:
                logger.info("Using mock data for get_all_preferences")
                return self.mock_subscribers
                
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
        if self.redis:
            return self.redis.get(f"sentiment:{symbol}")
        return None
        
    async def cache_sentiment(self, symbol: str, sentiment: str) -> None:
        """Cache sentiment analysis"""
        try:
            if self.redis:
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
            
            # Normalize the timeframe for database storage
            normalized_timeframe = self._normalize_timeframe_for_db(timeframe)
            
            data = {
                'user_id': user_id,
                'market': market,
                'instrument': instrument,
                'timeframe': normalized_timeframe,
                'style': style  # Keep style as database still requires it
            }
            
            response = self.supabase.table('subscriber_preferences').insert(data).execute()
            return response
            
        except Exception as e:
            logger.error(f"Error saving preferences: {str(e)}")
            raise 

    async def get_subscribers(self, instrument: str = None, timeframe: str = None):
        """Get all subscribers for an instrument and timeframe"""
        # If no instrument is provided, get all subscribers
        if not instrument:
            query = self.supabase.table('subscribers').select('*')
            return query.execute()
            
        # Filter by instrument if provided
        query = self.supabase.table('subscriber_preferences')\
            .select('*')\
            .eq('instrument', instrument)
        
        # Als er een timeframe is meegegeven, filteren op timeframe
        if timeframe:
            # Normaliseer het timeframe voor een consistente vergelijking
            normalized_timeframe = self._normalize_timeframe_for_db(timeframe)
            query = query.eq('timeframe', normalized_timeframe)
        
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

    async def save_preference(self, user_id: int, market: str, instrument: str, timeframe: str) -> bool:
        """Save user preference to database"""
        try:
            # Normalize the timeframe for database storage
            normalized_timeframe = self._normalize_timeframe_for_db(timeframe)
            
            # Map the timeframe to a style for style column
            style = self._map_timeframe_to_style(timeframe)
            
            # Maak een nieuwe voorkeur
            new_preference = {
                'user_id': user_id,
                'market': market,
                'instrument': instrument,
                'timeframe': normalized_timeframe,
                'style': style  # Add style back as the database requires it
            }
            
            # Sla op in de database
            response = self.supabase.table('subscriber_preferences').insert(new_preference).execute()
            
            if response.data:
                logger.info(f"Saved preference for user {user_id}: {instrument} ({timeframe}, style: {style})")
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
        """Delete a specific preference by ID"""
        try:
            response = self.supabase.table('subscriber_preferences').delete().eq('id', preference_id).execute()
            
            # Check if any rows were affected
            if response and response.data:
                logger.info(f"Successfully deleted preference with ID {preference_id}")
                return True
            else:
                logger.warning(f"No preference found with ID {preference_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error deleting preference by ID: {str(e)}")
            return False
            
    async def get_subscriber_preferences(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all signal preferences for a specific user"""
        try:
            response = self.supabase.table('subscriber_preferences').select('*').eq('user_id', user_id).execute()
            
            if response and response.data:
                logger.info(f"Found {len(response.data)} preferences for user {user_id}")
                return response.data
            else:
                logger.info(f"No preferences found for user {user_id}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting subscriber preferences: {str(e)}")
            return []
            
    async def add_subscriber_preference(self, user_id: int, market: str, instrument: str, timeframe: str = None) -> bool:
        """Add a new signal preference for a user
        
        Arguments:
            user_id: Telegram user ID
            market: Market type (forex, crypto, indices, commodities)
            instrument: Trading instrument/symbol (e.g., EURUSD, BTCUSD)
            timeframe: Timeframe (optional, if not provided will use the instrument's default from INSTRUMENT_TIMEFRAME_MAP)
        
        Returns:
            bool: Success indicator
        """
        try:
            # Check if preference already exists
            existing = self.supabase.table('subscriber_preferences').select('*').eq('user_id', user_id).eq('instrument', instrument).execute()
            
            if existing and existing.data:
                logger.info(f"User {user_id} already has a preference for {instrument}")
                return True
            
            # Import here to avoid circular imports
            from trading_bot.services.telegram_service.bot import INSTRUMENT_TIMEFRAME_MAP, STYLE_TIMEFRAME_MAP
            
            # Get the instrument's default timeframe from the mapping if not provided
            if timeframe is None or timeframe.upper() == "ALL":
                instrument_timeframe = INSTRUMENT_TIMEFRAME_MAP.get(instrument)
                if instrument_timeframe:
                    timeframe = instrument_timeframe
                    logger.info(f"Using instrument's default timeframe: {timeframe} for {instrument}")
                else:
                    # Default to 1h if not found in the map
                    timeframe = "1h"
                    logger.info(f"Instrument {instrument} not found in INSTRUMENT_TIMEFRAME_MAP, using default '1h'")
            
            # Log the original timeframe for reference
            logger.info(f"Original timeframe for {instrument}: {timeframe}")
            
            # ALWAYS use '1h' for database to avoid 'valid_timeframe' constraint issues
            # Regardless of the input or instrument timeframe
            fixed_timeframe = '1h'
            logger.info(f"Using fixed timeframe '1h' for database to comply with constraint")
            
            # Map the timeframe to a style for style column (which still has a not-null constraint)
            style = self._map_timeframe_to_style(timeframe)
            
            # Create new preference with fixed timeframe
            current_time = datetime.datetime.now(timezone.utc).isoformat()
            
            new_preference = {
                'user_id': int(user_id),
                'market': str(market),
                'instrument': str(instrument),
                'timeframe': fixed_timeframe,  # ALWAYS use fixed timeframe of '1h'
                'style': str(style),
                'created_at': current_time
            }
            
            # Log the data being inserted for debugging
            logger.info(f"Inserting preference data: {new_preference}")
            
            # Insert new preference
            response = self.supabase.table('subscriber_preferences').insert(new_preference).execute()
            
            if response and response.data:
                logger.info(f"Successfully added preference for user {user_id}: {instrument} (original timeframe: {timeframe}, stored as: {fixed_timeframe}, style: {style})")
                return True
            else:
                logger.warning(f"Failed to add preference for user {user_id}")
                logger.warning(f"Response: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Error adding subscriber preference: {str(e)}")
            traceback.print_exc()  # Print the full traceback for better debugging
            return False
    
    def _normalize_timeframe_for_db(self, timeframe: str) -> str:
        """
        Normalize timeframe for database storage.
        
        Always returns '1h' to satisfy the database constraint 'valid_timeframe'.
        According to our testing, the database only accepts '1h' for new records.
        
        Arguments:
            timeframe: De timeframe (bijv. 'M30', '1h', '4h')
            
        Returns:
            str: Always returns '1h'
        """
        # Log the original timeframe for reference
        logger.info(f"Original timeframe '{timeframe}' will be stored as '1h' to comply with database constraint")
        return '1h'

    def _map_timeframe_to_style(self, timeframe: str) -> str:
        """
        Map a timeframe to a trading style.
        
        Arguments:
            timeframe: The timeframe to map (e.g., 'M15', 'M30', 'H1', 'H4', '15m', '30m', '1h', '4h')
        
        Returns:
            str: The corresponding trading style ('test', 'scalp', 'intraday', 'swing')
        """
        if not timeframe:
            return 'intraday'  # Default
        
        # Normalize the input by removing spaces and converting to lowercase
        tf_str = str(timeframe).strip().lower()
        
        # Handle M15 format (MT4/MT5 style)
        if tf_str in ['m15'] or timeframe in ['M15']:
            return 'scalp'
        
        # Handle M30 format (MT4/MT5 style)
        if tf_str in ['m30'] or timeframe in ['M30']:
            return 'intraday'
        
        # Handle H1 format (MT4/MT5 style)
        if tf_str in ['h1'] or timeframe in ['H1']:
            return 'intraday'
        
        # Handle H4 format (MT4/MT5 style)
        if tf_str in ['h4'] or timeframe in ['H4']:
            return 'swing'
        
        # Handle 15m format (TradingView style)
        if tf_str in ['15m', '15min']:
            return 'scalp'
        
        # Handle 30m format (TradingView style)
        if tf_str in ['30m', '30min']:
            return 'intraday'
        
        # Handle 1h format (TradingView style)
        if tf_str in ['1h', '60m']:
            return 'intraday'
        
        # Handle 4h format (TradingView style)
        if tf_str in ['4h', '240m']:
            return 'swing'
        
        # Special case - test timeframe (1m)
        if tf_str in ['1m', 'm1']:
            return 'test'
        
        # If no match found, default to 'intraday'
        logger.warning(f"Could not map timeframe '{timeframe}' to a style, defaulting to 'intraday'")
        return 'intraday'

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
        """Get user subscription information"""
        try:
            if self.use_mock_data:
                logger.info(f"Using mock data for get_user_subscription: {user_id}")
                for subscription in self.mock_subscriptions:
                    if subscription["user_id"] == user_id:
                        return subscription
                return None
                
            response = self.supabase.table('user_subscriptions').select('*').eq('user_id', user_id).execute()
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
        """Check if a user has an active subscription"""
        try:
            if self.use_mock_data:
                logger.info(f"Using mock data for is_user_subscribed: {user_id}")
                for subscription in self.mock_subscriptions:
                    if subscription["user_id"] == user_id and subscription["status"] == "active":
                        # Check if subscription is still valid
                        end_date = datetime.datetime.fromisoformat(subscription["current_period_end"])
                        if end_date > datetime.datetime.now():
                            return True
                return False
                
            subscription = await self.get_user_subscription(user_id)
            if not subscription:
                return False
                
            # Check if subscription is active
            if subscription.get('subscription_status') != 'active':
                return False
            
            # Check if subscription has not expired
            current_period_end = subscription.get('current_period_end')
            if not current_period_end:
                return False
                
            # Convert to datetime if it's a string
            if isinstance(current_period_end, str):
                try:
                    current_period_end = datetime.datetime.fromisoformat(current_period_end.replace('Z', '+00:00'))
                except:
                    # If parsing fails, assume subscription is expired
                    return False
            
            # Compare with current time
            current_time = datetime.datetime.now(timezone.utc)
            if current_period_end < current_time:
                return False
                
            # All checks passed, user is subscribed
            return True
        except Exception as e:
            logger.error(f"Error checking if user is subscribed: {str(e)}")
            return False
            
    async def has_payment_failed(self, user_id: int) -> bool:
        """Check if user's subscription payment has failed"""
        try:
            # Retrieve the user's subscription
            subscription = await self.get_user_subscription(user_id)
            
            if not subscription:
                return False
            
            # Check if status indicates a payment failure
            status = subscription.get('subscription_status')
            
            # Check for payment failure status
            return status in ['past_due', 'unpaid', 'incomplete', 'incomplete_expired']
            
        except Exception as e:
            logger.error(f"Error checking payment failure status: {str(e)}")
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
            logger.error(f"Error saving user: {str(e)}")
            return False

    async def save_user_subscription(self, user_id: int, subscription_type: str, start_date: datetime.datetime, end_date: datetime.datetime) -> bool:
        """Save a user subscription with custom start and end dates"""
        try:
            logger.info(f"Saving subscription for user {user_id} with start date {start_date} and end date {end_date}")
            
            # Determine subscription status based on end date
            now = datetime.datetime.now()
            status = 'active' if end_date > now else 'inactive'
            
            subscription_data = {
                'user_id': user_id,
                'subscription_status': status,
                'subscription_type': subscription_type,
                'updated_at': now.isoformat(),
                'created_at': start_date.isoformat() if start_date else now.isoformat(),
                'current_period_end': end_date.isoformat() if end_date else None
            }
            
            # Check if user already has a subscription
            existing = await self.get_user_subscription(user_id)
            
            if existing:
                # Update existing subscription
                response = self.supabase.table('user_subscriptions').update(subscription_data).eq('user_id', user_id).execute()
            else:
                # Create new subscription
                response = self.supabase.table('user_subscriptions').insert(subscription_data).execute()
            
            if response.data:
                logger.info(f"Subscription saved for user {user_id}: {status}")
                return True
            else:
                logger.error(f"Failed to save subscription: {response}")
                return False
        except Exception as e:
            logger.error(f"Error saving subscription: {str(e)}")
            return False

    async def set_payment_failed(self, user_id: int) -> bool:
        """Set a user's subscription status to payment failed (past_due)"""
        try:
            logger.info(f"Setting payment failed state for user {user_id}")
            
            now = datetime.datetime.now()
            subscription_data = {
                'user_id': user_id,
                'subscription_status': 'past_due',
                'subscription_type': 'monthly',
                'updated_at': now.isoformat(),
                'current_period_end': (now + datetime.timedelta(days=30)).isoformat()
            }
            
            # Check if user already has a subscription
            existing = await self.get_user_subscription(user_id)
            
            if existing:
                # Update existing subscription
                response = self.supabase.table('user_subscriptions').update(subscription_data).eq('user_id', user_id).execute()
            else:
                # Create new subscription
                response = self.supabase.table('user_subscriptions').insert(subscription_data).execute()
            
            if response.data:
                logger.info(f"Payment failed status set for user {user_id}")
                return True
            else:
                logger.error(f"Failed to set payment failed status: {response}")
                return False
        except Exception as e:
            logger.error(f"Error setting payment failed status: {str(e)}")
            return False

    def _detect_market(self, instrument: str) -> str:
        """Detect market type from instrument name"""
        instrument = instrument.upper()
         
        # Common forex pairs
        forex_pairs = ["EUR", "USD", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"]
         
        # Check if it's a forex pair (contains two currency codes)
        for base in forex_pairs:
            if instrument.startswith(base):
                for quote in forex_pairs:
                    if instrument == base + quote:
                        return "forex"
         
        # Check if it's a crypto pair
        crypto_pairs = ["BTC", "ETH", "XRP", "LTC", "BCH", "EOS", "BNB", "XLM", "ADA", "TRX"]
        for crypto in crypto_pairs:
            if crypto in instrument:
                return "crypto"
         
        # Check if it's an index
        indices = ["SPX", "NDX", "DJI", "FTSE", "DAX", "CAC", "NIKKEI", "HSI"]
        for index in indices:
            if index in instrument:
                return "indices"
         
        # Check if it's a commodity
        commodities = ["GOLD", "SILVER", "OIL", "GAS", "XAU", "XAG"]
        for commodity in commodities:
            if commodity in instrument:
                return "commodities"
         
        # Default to forex if we can't determine
        return "forex" 

    async def subscribe_to_instrument(self, user_id: int, instrument: str, timeframe: str = None) -> bool:
        """Subscribe a user to receive signals for a specific instrument
        
        Arguments:
            user_id: Telegram user ID
            instrument: Trading instrument/symbol (e.g., EURUSD, BTCUSD)
            timeframe: Timeframe (optional, if not provided will use the instrument's default from INSTRUMENT_TIMEFRAME_MAP)
            
        Returns:
            bool: Success indicator
        """
        try:
            # Auto-detect market type based on the instrument
            market = self._detect_market(instrument)
            logger.info(f"Market auto-detected as {market} for instrument {instrument}")
            
            # Use the new signal_subscriptions table instead of subscriber_preferences
            return await self.add_signal_subscription(user_id, market, instrument, timeframe)
            
        except Exception as e:
            logger.error(f"Error in subscribe_to_instrument: {str(e)}")
            return False
            
    async def get_subscribers_for_instrument(self, instrument: str, timeframe: str = None) -> List[int]:
        """Get list of user IDs subscribed to a specific instrument and timeframe"""
        try:
            if self.use_mock_data:
                logger.info(f"Using mock data for get_subscribers_for_instrument: {instrument}, {timeframe}")
                subscribers = []
                for pref in self.mock_subscribers:
                    if (pref["instrument"] == instrument or pref["instrument"] == "ALL") and \
                       (timeframe is None or pref["timeframe"] == timeframe or pref["timeframe"] == "ALL"):
                        subscribers.append(pref["user_id"])
                return subscribers
            
            # Get subscribers from database
            query = self.supabase.table('subscriber_preferences').select('user_id')
            
            # Filter by instrument (either specific instrument or ALL)
            query = query.or_(f"instrument.eq.{instrument},instrument.eq.ALL")
            
            # Filter by timeframe if specified
            if timeframe:
                normalized_timeframe = self._normalize_timeframe(timeframe)
                query = query.or_(f"timeframe.eq.{normalized_timeframe},timeframe.eq.ALL")
                
            response = query.execute()
            
            # Extract user IDs
            subscribers = []
            if response.data:
                for pref in response.data:
                    subscribers.append(pref.get('user_id'))
                    
            return list(set(subscribers))  # Return unique user IDs
        except Exception as e:
            logger.error(f"Error getting subscribers for instrument: {str(e)}")
            return []

    async def add_signal_subscription(self, user_id: int, market: str, instrument: str, timeframe: str = None) -> bool:
        """Add a new signal subscription using the new signal_subscriptions table
        
        Arguments:
            user_id: Telegram user ID
            market: Market type (forex, crypto, indices, commodities)
            instrument: Trading instrument/symbol (e.g., EURUSD, BTCUSD)
            timeframe: Timeframe (optional, if not provided will use the instrument's default from INSTRUMENT_TIMEFRAME_MAP)
        
        Returns:
            bool: Success indicator
        """
        try:
            # Check if subscription already exists
            existing = self.supabase.table('signal_subscriptions').select('*').eq('user_id', user_id).eq('instrument', instrument).execute()
            
            if existing and existing.data:
                logger.info(f"User {user_id} already has a subscription for {instrument}")
                return True
            
            # Import here to avoid circular imports
            from trading_bot.services.telegram_service.bot import INSTRUMENT_TIMEFRAME_MAP
            
            # Get the instrument's default timeframe from the mapping if not provided
            if timeframe is None or timeframe.upper() == "ALL":
                instrument_timeframe = INSTRUMENT_TIMEFRAME_MAP.get(instrument)
                if instrument_timeframe:
                    timeframe = instrument_timeframe
                    logger.info(f"Using instrument's default timeframe: {timeframe} for {instrument}")
                else:
                    # Default to 1h if not found in the map
                    timeframe = "1h"
                    logger.info(f"Instrument {instrument} not found in INSTRUMENT_TIMEFRAME_MAP, using default '1h'")
            
            # Log the original timeframe for reference
            logger.info(f"Using timeframe for {instrument}: {timeframe}")
            
            # Create new subscription entry
            current_time = datetime.datetime.now(timezone.utc).isoformat()
            
            new_subscription = {
                'user_id': int(user_id),
                'market': str(market),
                'instrument': str(instrument),
                'timeframe': str(timeframe),  # Use the actual timeframe as is
                'created_at': current_time
            }
            
            # Log the data being inserted for debugging
            logger.info(f"Inserting subscription data: {new_subscription}")
            
            # Insert new subscription
            response = self.supabase.table('signal_subscriptions').insert(new_subscription).execute()
            
            if response and response.data:
                logger.info(f"Successfully added subscription for user {user_id}: {instrument} with timeframe: {timeframe}")
                return True
            else:
                logger.warning(f"Failed to add subscription for user {user_id}")
                logger.warning(f"Response: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Error adding signal subscription: {str(e)}")
            traceback.print_exc()  # Print the full traceback for better debugging
            return False

    async def get_signal_subscriptions(self, instrument: str, timeframe: str = None) -> List[Dict]:
        """Get all signal subscriptions for a specific instrument, ignoring timeframe
        
        Arguments:
            instrument: Trading instrument/symbol (e.g., EURUSD, BTCUSD)
            timeframe: Timeframe (not used - kept for compatibility)
            
        Returns:
            List[Dict]: List of subscription records with user_id, instrument, timeframe, etc.
        """
        try:
            result = []
            
            # Only get subscriptions from the signal_subscriptions table matching instrument
            query = self.supabase.table('signal_subscriptions').select('*').eq('instrument', instrument)
            
            response = query.execute()
            
            if response and response.data:
                result.extend(response.data)
                logger.info(f"Found {len(response.data)} subscriptions for instrument {instrument} in signal_subscriptions table")
            else:
                logger.info(f"No subscriptions found for instrument {instrument} in signal_subscriptions table")
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting signal subscriptions for instrument {instrument}: {str(e)}")
            traceback.print_exc()
            return []

    async def get_all_active_users(self) -> List[Dict]:
        """Get all active users from the database
        
        Returns:
            List[Dict]: List of user records
        """
        try:
            # Get users from the users table
            response = self.supabase.table('users').select('*').execute()
            
            if response and response.data:
                logger.info(f"Found {len(response.data)} users in the database")
                return response.data
            else:
                logger.info("No users found in the database")
                return []
                
        except Exception as e:
            logger.error(f"Error getting all active users: {str(e)}")
            traceback.print_exc()
            return []
