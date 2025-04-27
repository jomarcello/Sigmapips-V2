import logging
import traceback
import asyncio
import os
from typing import Optional, Dict, Any, Tuple
import time
import pandas as pd
from datetime import datetime, timedelta
import random
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tenacity import retry, stop_after_attempt, wait_exponential
import yfinance as yf
import numpy as np
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Configure retry mechanism
# ... (retry decorator setup remains the same) ...

# --- Cache Configuration ---
# Cache for raw downloaded data (symbol, interval) -> DataFrame
# Cache for 5 minutes (300 seconds)
data_download_cache = TTLCache(maxsize=100, ttl=300) 
# Cache for processed market data (symbol, timeframe, limit) -> DataFrame with indicators
market_data_cache = TTLCache(maxsize=100, ttl=300) 

class YahooFinanceProvider:
    """Provider class for Yahoo Finance API integration"""
    
    # Cache data to minimize API calls
    _cache = {}
    _cache_timeout = 3600  # Cache timeout in seconds (1 hour)
    _last_api_call = 0
    _min_delay_between_calls = 1  # Reduced delay slightly to 1 second
    _session = None

    @staticmethod
    def _get_session():
        """Get or create a requests session with retry logic"""
        if YahooFinanceProvider._session is None:
            session = requests.Session()
            
            # Rotating user agents to avoid blocking
            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 11.5; rv:90.0) Gecko/20100101 Firefox/90.0',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36 Edg/92.0.902.55',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 11_5_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Safari/605.1.15'
            ]
            
            retries = Retry(
                total=5,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "POST", "OPTIONS"]
            )
            adapter = HTTPAdapter(max_retries=retries, pool_maxsize=10)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            
            # Use a random user agent
            session.headers.update({
                'User-Agent': random.choice(user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Pragma': 'no-cache',
                'Cache-Control': 'no-cache',
            })
            
            # For Railway environment: try to use proxies if available
            if os.environ.get('ENVIRONMENT') == 'production' or os.environ.get('RAILWAY_ENVIRONMENT') is not None:
                try:
                    # Check if HTTP_PROXY or HTTPS_PROXY environment variables are set
                    http_proxy = os.environ.get('HTTP_PROXY')
                    https_proxy = os.environ.get('HTTPS_PROXY')
                    
                    if http_proxy or https_proxy:
                        proxies = {}
                        if http_proxy:
                            proxies['http'] = http_proxy
                        if https_proxy:
                            proxies['https'] = https_proxy
                            
                        session.proxies.update(proxies)
                        logger.info(f"Using proxy settings for Yahoo Finance requests: {proxies}")
                except Exception as e:
                    logger.error(f"Error setting up proxies: {str(e)}")
            
            YahooFinanceProvider._session = session
        return YahooFinanceProvider._session
    
    @staticmethod
    async def _wait_for_rate_limit():
        """Wait if we've hit the rate limit"""
        current_time = time.time()
        if YahooFinanceProvider._last_api_call > 0:
            time_since_last_call = current_time - YahooFinanceProvider._last_api_call
            if time_since_last_call < YahooFinanceProvider._min_delay_between_calls:
                delay = YahooFinanceProvider._min_delay_between_calls - time_since_last_call + random.uniform(0.1, 0.5)
                logger.info(f"Rate limiting: Waiting {delay:.2f} seconds before next call")
                await asyncio.sleep(delay)
        YahooFinanceProvider._last_api_call = time.time()

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30), # Adjusted retry wait
        reraise=True
    )
    async def _download_data(symbol: str, start_date: datetime, end_date: datetime, interval: str, timeout: int = 30, original_symbol: str = None, period: str = None) -> pd.DataFrame:
        """Download data using yfinance with retry logic and caching."""
        # --- Caching Logic ---
        # Cache key should ideally represent the actual request made
        if period:
            # Use period and interval for intraday caching
            cache_key = (symbol, interval, period)
        elif start_date and end_date:
            # Use start/end date and interval for daily+ caching
            cache_key = (symbol, interval, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        else:
            # Fallback cache key if parameters are weird (should not happen often)
            logger.warning("Could not determine proper cache key, using fallback.")
            cache_key = (symbol, interval, datetime.now().strftime('%Y-%m-%d'))

        if cache_key in data_download_cache:
            logger.info(f"[Yahoo Cache] HIT for download: Key={cache_key}")
            return data_download_cache[cache_key].copy() # Return a copy to prevent mutation
        logger.info(f"[Yahoo Cache] MISS for download: Key={cache_key}")
        # --- End Caching Logic ---

        logger.info(f"[Yahoo] Attempting direct download method with yf.download for {symbol} (Interval: {interval}, Period: {period}, Start: {start_date.date() if start_date else 'N/A'}, End: {end_date.date() if end_date else 'N/A'})")
        
        # Ensure session exists
        session = YahooFinanceProvider._get_session()
        
        # Function to perform the download (runs in executor)
        def download():
            try:
                # Check if set_tz_session_for_downloading exists (handle different yfinance versions)
                if hasattr(yf.multi, 'set_tz_session_for_downloading'):
                     yf.multi.set_tz_session_for_downloading(session)
                else:
                     logger.warning("[Yahoo] Function set_tz_session_for_downloading not available in this yfinance version")

                # Construct download arguments
                download_kwargs = {
                    'tickers': symbol,
                    'interval': interval,
                    'progress': False,
                    'session': session,
                    'timeout': timeout,
                    'ignore_tz': False
                }
                # Use period OR start/end, not both
                if period:
                     download_kwargs['period'] = period
                else:
                     download_kwargs['start'] = start_date
                     download_kwargs['end'] = end_date

                # Download data
                df = yf.download(**download_kwargs)
                return df
            except Exception as e:
                 logger.error(f"[Yahoo] Error during yf.download for {symbol}: {str(e)}")
                 # Add more specific error checks if needed (e.g., connection errors)
                 if "No data found" in str(e) or "symbol may be delisted" in str(e):
                     logger.warning(f"[Yahoo] No data found for {symbol} in range {start_date} to {end_date}")
                     return pd.DataFrame() # Return empty DataFrame on no data
                 raise # Reraise other exceptions for tenacity

        # Run the download in a separate thread to avoid blocking asyncio event loop
        loop = asyncio.get_event_loop()
        try:
             # Use default executor (ThreadPoolExecutor)
             df = await loop.run_in_executor(None, download) 
        except Exception as e:
             logger.error(f"[Yahoo] Download failed for {symbol} after retries: {e}")
             df = None # Ensure df is None on failure

        if df is not None and not df.empty:
             logger.info(f"[Yahoo] Direct download successful for {symbol}, got {len(df)} rows")
             # --- Cache Update ---
             data_download_cache[cache_key] = df.copy() # Store a copy in cache
             # --- End Cache Update ---
        elif df is not None and df.empty:
             logger.warning(f"[Yahoo] Download returned empty DataFrame for {symbol}")
             # Cache the empty result too, to avoid repeated failed attempts for a short period
             data_download_cache[cache_key] = df.copy()
        else:
             logger.warning(f"[Yahoo] Download returned None for {symbol}")
             # Optionally cache None or handle differently if needed

        return df
    
    @staticmethod
    def _validate_and_clean_data(df: pd.DataFrame, instrument: str = None) -> pd.DataFrame:
        """
        Validate and clean the market data
        
        Args:
            df: DataFrame with market data
            instrument: The instrument symbol to determine appropriate decimal precision
        """
        if df is None or df.empty:
            logger.warning("[Validation] Input DataFrame is None or empty, no validation possible")
            return df
            
        try:
            # Initial diagnostics (Keep basic shape log)
            logger.info(f"[Validation] Starting data validation with shape: {df.shape}")
            # logger.info(f"[Validation] Original columns: {df.columns}")
            # logger.info(f"[Validation] Index type: {type(df.index).__name__}")
            # logger.info(f"[Validation] Index range: {df.index[0]} to {df.index[-1]}" if len(df) > 0 else "[Validation] Empty index")

            # Check for NaN values in the original data
            nan_counts = df.isna().sum()
            # if nan_counts.sum() > 0:
            #     logger.warning(f"[Validation] Found NaN values in original data: {nan_counts.to_dict()}")

            # Check if we have a multi-index dataframe from yfinance
            if isinstance(df.columns, pd.MultiIndex):
                # logger.info(f"[Validation] Detected MultiIndex columns with levels: {[name for name in df.columns.names]}")
                # logger.info(f"[Validation] First level values: {df.columns.get_level_values(0).unique().tolist()}")
                # logger.info(f"[Validation] Second level values: {df.columns.get_level_values(1).unique().tolist()}")
                
                # Convert multi-index format to standard format
                result = pd.DataFrame()
                
                # Extract each price column
                for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    if (col, df.columns.get_level_values(1)[0]) in df.columns:
                        result[col] = df[(col, df.columns.get_level_values(1)[0])]
                        # logger.info(f"[Validation] Extracted {col} from MultiIndex")
                    # else: # Log errors only if column is truly missing
                    #     logger.error(f"[Validation] Column {col} not found in multi-index")
                        
                # Replace original dataframe with converted one
                if not result.empty:
                    # logger.info(f"[Validation] Successfully converted multi-index to: {result.columns}")
                    df = result
                else:
                    logger.error("[Validation] Failed to convert multi-index dataframe, returning empty DataFrame")
                    return pd.DataFrame()
            
            # Ensure we have the required columns
            required_columns = ['Open', 'High', 'Low', 'Close']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                logger.error(f"[Validation] Required columns missing: {missing_columns}")
                logger.info(f"[Validation] Available columns: {df.columns}")
                return pd.DataFrame()
            
            # Report initial data statistics (COMMENTED OUT)
            # logger.info(f"[Validation] Data statistics before cleaning:")
            # for col in required_columns:
            #     try:
            #         stats = {
            #             'min': df[col].min(),
            #             'max': df[col].max(),
            #             'mean': df[col].mean(),
            #             'null_count': df[col].isnull().sum()
            #         }
            #         logger.info(f"[Validation] {col}: {stats}")
            #     except Exception as stats_e:
            #         logger.error(f"[Validation] Error calculating stats for {col}: {str(stats_e)}")
            
            # Remove any duplicate indices
            dupes_count = df.index.duplicated().sum()
            if dupes_count > 0:
                # logger.warning(f"[Validation] Found {dupes_count} duplicate indices, removing duplicates")
                df = df[~df.index.duplicated(keep='last')]
            # else:
                # logger.info("[Validation] No duplicate indices found")
            
            # Forward fill missing values (max 2 periods)
            null_before = df.isnull().sum().sum()
            df = df.ffill(limit=2)
            null_after = df.isnull().sum().sum()
            # if null_before > 0:
                # logger.info(f"[Validation] Forward-filled {null_before - null_after} NaN values (limit=2)")
            
            # Remove rows with any remaining NaN values
            row_count_before_nan = len(df)
            df = df.dropna()
            row_count_after_nan = len(df)
            # if row_count_after_nan < row_count_before_nan:
                # logger.warning(f"[Validation] Dropped {row_count_before_nan - row_count_after_nan} rows with NaN values")
            
            # Ensure all numeric columns are float
            for col in df.columns:
                try:
                    # Use recommended approach to avoid SettingWithCopyWarning if possible
                    # df[col] = pd.to_numeric(df[col], errors='coerce')
                    # If direct assignment causes issues, use the original approach with warning suppression
                    with pd.option_context('mode.chained_assignment', None):
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                    nan_after_conversion = df[col].isna().sum()
                    # if nan_after_conversion > 0:
                        # logger.warning(f"[Validation] Converting {col} to numeric created {nan_after_conversion} NaN values")
                except Exception as conv_e:
                    logger.error(f"[Validation] Error converting {col} to numeric: {str(conv_e)}")
            
            # Check for remaining NaN values after numeric conversion
            if df.isna().sum().sum() > 0:
                # logger.warning(f"[Validation] Still have NaN values after numeric conversion: {df.isna().sum().to_dict()}")
                # Drop rows with NaN values again
                row_count_before_nan2 = len(df)
                df = df.dropna()
                row_count_after_nan2 = len(df)
                # logger.warning(f"[Validation] Dropped additional {row_count_before_nan2 - row_count_after_nan2} rows with NaN values")
            
            # Validate price relationships - only keep rows with valid OHLC relationships (COMMENTED OUT)
            # row_count_before_ohlc = len(df)
            # valid_rows = (
            #     (df['High'] >= df['Low']) &
            #     (df['High'] >= df['Open']) &
            #     (df['High'] >= df['Close']) &
            #     (df['Low'] <= df['Open']) &
            #     (df['Low'] <= df['Close'])
            # )

            # Log invalid row counts by condition (COMMENTED OUT)
            # if not valid_rows.all():
                # invalid_count = (~valid_rows).sum()
                # logger.warning(f"[Validation] Found {invalid_count} rows with invalid OHLC relationships")
                
                # Detailed diagnostics of invalid rows (COMMENTED OUT)
                # condition_results = {
                #     'High < Low': (df['High'] < df['Low']).sum(),
                #     'High < Open': (df['High'] < df['Open']).sum(),
                #     'High < Close': (df['High'] < df['Close']).sum(),
                #     'Low > Open': (df['Low'] > df['Open']).sum(),
                #     'Low > Close': (df['Low'] > df['Close']).sum()
                # }
                # logger.warning(f"[Validation] Invalid relationship details: {condition_results}")
                
                # Show an example of an invalid row (COMMENTED OUT)
                # if invalid_count > 0:
                    # try:
                        # invalid_idx = (~valid_rows).idxmax()
                        # logger.warning(f"[Validation] Example invalid row at {invalid_idx}: {df.loc[invalid_idx, ['Open', 'High', 'Low', 'Close']].to_dict()}")
                    # except Exception as e:
                        # logger.error(f"[Validation] Error showing invalid row example: {str(e)}")
            
            # df = df[valid_rows] # Keep the filter commented out for now
            # row_count_after_ohlc = len(df)
            # if row_count_after_ohlc < row_count_before_ohlc:
                # logger.warning(f"[Validation] Removed {row_count_before_ohlc - row_count_after_ohlc} rows with invalid OHLC relationships")
            
            # Also validate Volume if it exists
            if 'Volume' in df.columns:
                row_count_before_vol = len(df)
                df = df[df['Volume'] >= 0]
                row_count_after_vol = len(df)
                # if row_count_after_vol < row_count_before_vol:
                    # logger.warning(f"[Validation] Removed {row_count_before_vol - row_count_after_vol} rows with negative Volume")
            
            # Apply correct decimal precision based on instrument type if provided
            if instrument:
                try:
                    # Get the appropriate precision for this instrument
                    precision = YahooFinanceProvider._get_instrument_precision(instrument)
                    # logger.info(f"[Validation] Using {precision} decimal places for {instrument}")
                    
                    # Apply precision to price columns
                    price_columns = ['Open', 'High', 'Low', 'Close']
                    for col in price_columns:
                        if col in df.columns:
                            # Round the values to the appropriate precision
                            # This ensures the data is displayed with the correct number of decimal places
                            # Use recommended approach to avoid SettingWithCopyWarning if possible
                            # df[col] = df[col].round(precision)
                            # If direct assignment causes issues, use the original approach with warning suppression
                            with pd.option_context('mode.chained_assignment', None):
                                 df[col] = df[col].round(precision)
                except Exception as e:
                    logger.error(f"[Validation] Error applying precision for {instrument}: {str(e)}")
            
            # Final data statistics (COMMENTED OUT)
            # logger.info(f"[Validation] Final validated DataFrame shape: {df.shape}")
            # if len(df) > 0:
                # logger.info(f"[Validation] Date range: {df.index[0]} to {df.index[-1]}")
                
                # Log final statistics for key columns (COMMENTED OUT)
                # for col in required_columns:
                    # if col in df.columns:
                        # try:
                            # stats = {
                                # 'min': df[col].min(),
                                # 'max': df[col].max(),
                                # 'mean': df[col].mean(),
                            # }
                            # logger.info(f"[Validation] Final {col} statistics: {stats}")
                        # except Exception as stats_e:
                            # logger.error(f"[Validation] Error calculating final stats for {col}: {str(stats_e)}")
            
            return df
            
        except Exception as e:
            logger.error(f"[Validation] Error in data validation: {str(e)}")
            logger.error(f"[Validation] Error type: {type(e).__name__}")
            logger.error(traceback.format_exc())
            return df # Return original df on validation error? Or None? Consider implications.

    @staticmethod
    def _map_timeframe_to_yfinance(timeframe: str) -> Optional[str]:
        """Maps internal timeframe notation (e.g., H1, M15) to yfinance interval."""
        mapping = {
            # Intraday
            'M1': '1m',
            'M5': '5m',
            'M15': '15m',
            'M30': '30m',
            'H1': '1h', # Correct mapping for 1 hour
            'H4': '4h', # yfinance does not support 4h, needs resampling from 1h or 1d?
                       # For now, let's try requesting 1h and maybe resample later if needed
                       # Or fallback to 1d if 1h fails?
                       # Simplest for now: map H4 to 1d, but log warning
            # Daily/Weekly/Monthly
            'D1': '1d',
            'W1': '1wk',
            'MN1': '1mo'
        }
        # Case-insensitive matching
        input_tf_upper = timeframe.upper()

        if input_tf_upper == 'H4':
             logger.warning("yfinance does not directly support 4h interval. Mapping H4 to '1d'. Consider resampling 1h data if needed.")
             return '1d' # Fallback H4 to 1d for now

        # Try direct mapping first (e.g., '1h' -> '1h')
        if timeframe in mapping.values():
             return timeframe

        # Try mapping from internal notation (e.g., 'H1' -> '1h')
        yf_interval = mapping.get(input_tf_upper)

        if not yf_interval:
            logger.warning(f"Unsupported timeframe '{timeframe}' for Yahoo Finance. Defaulting to '1d'.")
            return '1d' # Default to daily if mapping fails
        
        # Additional check for valid intraday intervals (max 60 days history)
        # yfinance intraday intervals < 1d are limited to 60 days of history
        # Longer intervals like 1h might be limited to 730 days.
        # We might need to adjust start_date based on interval.
        return yf_interval

    @staticmethod
    def _calculate_period_for_interval(interval: str, limit: int) -> str:
         """Calculate appropriate yfinance period based on interval and limit."""
         # Simple estimation: try to get slightly more than needed
         days_needed = 1 # Default
         try:
             if 'm' in interval or 'h' in interval:
                 minutes = 0
                 if 'm' in interval:
                     minutes = int(interval.replace('m', ''))
                 elif 'h' in interval:
                     minutes = int(interval.replace('h', '')) * 60
                 
                 if minutes > 0:
                     # Estimate days needed, adding buffer
                     days_needed = max(1, int((minutes * limit / (24 * 60)) * 1.5) + 2) # Buffer added
                 else: # Default for 1h or invalid intraday
                      days_needed = max(10, int(limit / 24 * 1.5) + 2) # e.g. 300/24 * 1.5 + 2 = ~21 days for 1h

                 # Intraday data limits for yfinance
                 # 1m: max 7 days
                 # <1h: max 60 days
                 # 1h: max 730 days
                 if interval == '1m': days_needed = min(days_needed, 7)
                 elif 'm' in interval: days_needed = min(days_needed, 60)
                 elif interval == '1h': days_needed = min(days_needed, 729) # Limit to 729 days for 1h

             elif 'd' in interval:
                  days_needed = int(limit * 1.5) + 5 # Need ~455 days for 300 limit
             elif 'wk' in interval:
                  days_needed = int(limit * 7 * 1.5) + 30
             elif 'mo' in interval:
                  days_needed = int(limit * 30 * 1.5) + 90
             else: # Default case
                  days_needed = 60

         except Exception as e:
             logger.warning(f"Error calculating days needed for interval {interval}: {e}. Defaulting to 60d.")
             days_needed = 60

         # Ensure minimum period
         days_needed = max(days_needed, 2)
         # Return integer days for start/end calculation, or string period for yfinance period param
         # Correction: Let's return the yfinance compatible period string directly
         if 'm' in interval or 'h' in interval:
              period_str = f"{days_needed}d"
              logger.info(f"Calculated yfinance download period '{period_str}' for interval '{interval}' and limit {limit}")
              return period_str
         else: # For daily or longer, just return the number of days needed for start_date calculation
              logger.info(f"Calculated days needed {days_needed} for interval '{interval}' and limit {limit} (for start_date)")
              return str(days_needed) # Return as string for consistency before ValueError check

    @staticmethod
    async def get_market_data(symbol: str, limit: int = 100) -> Optional[Tuple[pd.DataFrame, Dict]]:
        """
        Fetches market data from Yahoo Finance for a FIXED timeframe (H1), validates it, and calculates indicators.
        Returns a tuple: (DataFrame with indicators, analysis_info dictionary)
        """
        # <<< FIXED TIMEFRAME >>>
        fixed_timeframe = "H1" 
        # <<< END FIXED TIMEFRAME >>>

        cache_key = (symbol, fixed_timeframe, limit) # Use fixed_timeframe in cache key
        if cache_key in market_data_cache:
            logger.info(f"[Yahoo Cache] HIT for market data: {symbol} timeframe {fixed_timeframe} limit {limit}")
            cached_df, cached_info = market_data_cache[cache_key]
            return cached_df.copy(), cached_info.copy() # Return copies
        logger.info(f"[Yahoo Cache] MISS for market data: {symbol} timeframe {fixed_timeframe} limit {limit}")

        logger.info(f"[Yahoo] Getting market data for {symbol} on fixed {fixed_timeframe} timeframe") # Log fixed timeframe
        df = None
        analysis_info = {}

        try:
            # 1. Format symbol and map timeframe
            formatted_symbol = YahooFinanceProvider._format_symbol(symbol, is_crypto=False, is_commodity=False) # Assume not crypto/commodity unless detected
            yf_interval = YahooFinanceProvider._map_timeframe_to_yfinance(fixed_timeframe) # Use fixed_timeframe

            if not yf_interval:
                 logger.error(f"[Yahoo] Could not map fixed timeframe '{fixed_timeframe}' to yfinance interval.")
                 return None

            # 2. Determine date range or period and download data
            end_date = datetime.now()
            yf_period = None
            start_date = None

            # Use 'period' for intraday intervals (< 1d) for better reliability
            if 'm' in yf_interval or 'h' in yf_interval:
                # Calculate period string (e.g., '729d' for 1h to stay within limit)
                yf_period = YahooFinanceProvider._calculate_period_for_interval(yf_interval, limit)
                logger.info(f"[Yahoo] Using period='{yf_period}' for interval '{yf_interval}'")
            elif yf_interval: # For daily or longer, use start/end date
                approx_days_str = YahooFinanceProvider._calculate_period_for_interval(yf_interval, limit) # Use helper to get approx days needed
                try:
                     required_days = int(approx_days_str) # Period calculation now returns days as int
                except ValueError:
                     logger.warning(f"Could not parse days from {approx_days_str}, defaulting to 365")
                     required_days = 365
                start_date = end_date - timedelta(days=required_days)
                logger.info(f"[Yahoo] Using start='{start_date.date()}', end='{end_date.date()}' for interval '{yf_interval}'")
            else: # Fallback if interval mapping failed
                 logger.error(f"[Yahoo] Invalid yfinance interval '{yf_interval}'. Cannot fetch data.")
                 market_data_cache[cache_key] = None # Cache None result
                 return None, None # Return tuple

            # Wait for rate limit
            await YahooFinanceProvider._wait_for_rate_limit()
            
            try:
                # Download the data from Yahoo Finance using the cached downloader
                df = await YahooFinanceProvider._download_data(
                    formatted_symbol, 
                    start_date,
                    end_date,
                    yf_interval,
                    timeout=30,
                    original_symbol=symbol
                )
                
                if df is None or df.empty:
                    logger.warning(f"[Yahoo] No data returned for {symbol} ({formatted_symbol}) after download attempt.")
                    market_data_cache[cache_key] = None # Cache None result
                    return None, None # Return tuple
                    
                # Log success and data shape before validation
                logger.info(f"[Yahoo] Successfully downloaded data for {symbol} with shape {df.shape}")
                
                # Validate and clean the data
                df_validated = YahooFinanceProvider._validate_and_clean_data(df.copy(), symbol) # Validate a copy

                if df_validated is None or df_validated.empty:
                     logger.warning(f"[Yahoo] Data validation failed or resulted in empty DataFrame for {symbol}")
                     market_data_cache[cache_key] = None # Cache None result
                     return None, None # Return tuple

                # For 4h timeframe, resample from 1h
                if fixed_timeframe == "4h" and yf_interval == "1h": # Ensure we fetched 1h data
                    logger.info(f"[Yahoo] Resampling 1h data to 4h for {symbol}")
                    try:
                        # Ensure index is datetime before resampling
                        if not isinstance(df_validated.index, pd.DatetimeIndex):
                             df_validated.index = pd.to_datetime(df_validated.index)
                             
                        # Ensure timezone information exists (UTC is common) for resampling
                        if df_validated.index.tz is None:
                           df_validated = df_validated.tz_localize('UTC')
                        else:
                           df_validated = df_validated.tz_convert('UTC') # Convert to UTC if needed

                        # Define resampling logic
                        resample_logic = {
                            'Open': 'first',
                            'High': 'max',
                            'Low': 'min',
                            'Close': 'last',
                            'Volume': 'sum'
                        }
                        # Filter out columns not present in df_validated
                        resample_logic = {k: v for k, v in resample_logic.items() if k in df_validated.columns}

                        df_resampled = df_validated.resample('4H', label='right', closed='right').agg(resample_logic)
                        df_resampled.dropna(inplace=True) # Drop rows where any value is NaN (often first row after resample)
                        
                        if df_resampled.empty:
                             logger.warning(f"[Yahoo] Resampling to 4h resulted in empty DataFrame for {symbol}. Using 1h data instead.")
                             # Stick with df_validated (1h) if resampling fails
                        else:
                             df_validated = df_resampled # Use the resampled data
                             logger.info(f"[Yahoo] Successfully resampled to 4h with shape {df_validated.shape}")
                             
                    except Exception as resample_e:
                        logger.error(f"[Yahoo] Error resampling to 4h: {str(resample_e)}")
                        # Continue with 1h data (df_validated) if resampling fails
                
                # Ensure we have enough data *before* limiting for indicators
                if len(df_validated) < limit: # Check if we have enough historical data
                     logger.warning(f"[Yahoo] Insufficient data after cleaning/resampling for {symbol} (got {len(df_validated)}, needed ~{limit}). Indicators might be inaccurate.")
                     # Potentially return None or handle differently if strict data requirement
                     # For now, proceed but log warning.

                # --- Calculate indicators BEFORE limiting ---
                df_with_indicators = df_validated.copy() # Work on a copy
                indicators = {}
                
                try:
                    # Ensure required columns exist
                    required_cols = ['Open', 'High', 'Low', 'Close']
                    if not all(col in df_with_indicators.columns for col in required_cols):
                         logger.error(f"[Yahoo] Missing required columns {required_cols} for indicator calculation in {symbol}. Skipping indicators.")
                    else:
                         # Safely access last row data
                         last_row = df_with_indicators.iloc[-1]
                         indicators = {
                              'open': float(last_row['Open']),
                              'high': float(last_row['High']),
                              'low': float(last_row['Low']),
                              'close': float(last_row['Close']),
                              'volume': float(last_row['Volume']) if 'Volume' in df_with_indicators.columns and pd.notna(last_row['Volume']) else 0
                         }

                         # 4. Calculate Technical Indicators using plain pandas
                         logger.info(f"[Yahoo] Calculating indicators for {symbol} manually using pandas")
                         try:
                             close = df_with_indicators['Close'] # Use validated column name

                             # EMA
                             df_with_indicators['EMA_20'] = close.ewm(span=20, adjust=False).mean()
                             df_with_indicators['EMA_50'] = close.ewm(span=50, adjust=False).mean()
                             df_with_indicators['EMA_200'] = close.ewm(span=200, adjust=False).mean()

                             # RSI
                             delta = close.diff()
                             gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                             loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                             rs = gain / loss
                             df_with_indicators['RSI_14'] = 100 - (100 / (1 + rs))

                             # MACD
                             ema_12 = close.ewm(span=12, adjust=False).mean()
                             ema_26 = close.ewm(span=26, adjust=False).mean()
                             df_with_indicators['MACD_12_26_9'] = ema_12 - ema_26
                             df_with_indicators['MACDs_12_26_9'] = df_with_indicators['MACD_12_26_9'].ewm(span=9, adjust=False).mean()
                             df_with_indicators['MACDh_12_26_9'] = df_with_indicators['MACD_12_26_9'] - df_with_indicators['MACDs_12_26_9'] # Histogram
                             logger.info(f"[Yahoo] Indicators calculated. DataFrame columns: {df_with_indicators.columns.tolist()}")

                         except Exception as ta_error:
                             logger.error(f"[Yahoo] Error calculating technical indicators for {symbol}: {ta_error}", exc_info=True)
                             # Return dataframe without indicators if calculation fails

                except Exception as indicator_e:
                     logger.error(f"[Yahoo] Error calculating indicators for {symbol}: {indicator_e}")
                     # Continue without indicators or with partial indicators if possible
                # --- End Indicator Calculation ---

                # --- Limit the number of candles AFTER calculations ---
                df_limited = df_with_indicators.iloc[-limit:]
                
                # --- Prepare result and cache --- 
                # Return the limited DataFrame AND the separate indicators dict
                result_df = df_limited.copy()
                # REMOVED: result_df.indicators = indicators # Avoid UserWarning by not setting attribute (FIXED WARNING)
                
                # Cache the final result tuple (DataFrame, indicators_dict)
                market_data_cache[cache_key] = (result_df.copy(), indicators.copy()) # Cache copies
                # Log the shape being returned
                logger.info(f"[Yahoo] Returning market data for {symbol} with shape {result_df.shape}")

                return result_df, indicators # Return tuple
                
            except Exception as download_e:
                logger.error(f"[Yahoo] Error processing market data for {symbol}: {str(download_e)}")
                if isinstance(download_e, KeyError) and 'Open' in str(download_e):
                     logger.error(f"[Yahoo] Likely issue with column names after download for {symbol}. Raw columns: {df.columns if 'df' in locals() and df is not None else 'N/A'}")
                logger.error(traceback.format_exc()) # Log full traceback for download errors
                market_data_cache[cache_key] = None # Cache None result on error
                raise download_e
                
        except Exception as e:
            logger.error(f"[Yahoo] Unexpected error in get_market_data for {symbol}: {str(e)}")
            logger.error(traceback.format_exc()) # Log full traceback for unexpected errors
            # Ensure None is cached on unexpected error before returning
            market_data_cache[cache_key] = None 
            return None, None # Return tuple

    @staticmethod
    async def get_stock_info(symbol: str) -> Optional[Dict]:
        """Get detailed information about a stock"""
        try:
            formatted_symbol = YahooFinanceProvider._format_symbol(symbol)
            
            # Wait for rate limit
            await YahooFinanceProvider._wait_for_rate_limit()
            
            loop = asyncio.get_event_loop()
            
            # Get stock info with yfinance
            def get_info():
                try:
                    ticker = yf.Ticker(formatted_symbol)
                    info = ticker.info
                    return info
                except Exception as e:
                    logger.error(f"Error getting stock info: {str(e)}")
                    raise e
            
            info = await loop.run_in_executor(None, get_info)
            return info
            
        except Exception as e:
            logger.error(f"Error getting stock info from Yahoo Finance: {str(e)}")
            return None
    
    @staticmethod
    def _get_instrument_precision(instrument: str) -> int:
        """Get the appropriate decimal precision for an instrument
        
        Args:
            instrument: The trading instrument symbol
            
        Returns:
            int: Number of decimal places to use
        """
        instrument = instrument.upper().replace("/", "")
        
        # JPY pairs use 3 decimal places
        if instrument.endswith("JPY") or "JPY" in instrument:
            return 3
            
        # Most forex pairs use 5 decimal places
        if len(instrument) == 6 and all(c.isalpha() for c in instrument):
            return 5
            
        # Crypto typically uses 2 decimal places for major coins, more for smaller ones
        if any(crypto in instrument for crypto in ["BTC", "ETH", "LTC", "XRP"]):
            return 2
            
        # Gold typically uses 2 decimal places
        if instrument in ["XAUUSD", "GC=F"]:
            return 2
            
        # Silver typically uses 3 decimal places
        if instrument in ["XAGUSD", "SI=F"]:
            return 3
            
        # Indices typically use 2 decimal places
        if any(index in instrument for index in ["US30", "US500", "US100", "UK100", "DE40", "JP225"]):
            return 2
            
        # Default to 4 decimal places as a safe value
        return 4
    
    @staticmethod
    def _format_symbol(instrument: str, is_crypto: bool, is_commodity: bool) -> str:
        """Format instrument symbol for Yahoo Finance API"""
        instrument = instrument.upper().replace("/", "")
        
        # For forex (EURUSD -> EUR=X)
        if len(instrument) == 6 and all(c.isalpha() for c in instrument):
            base = instrument[:3]
            quote = instrument[3:]
            return f"{base}{quote}=X"
            
        # For commodities - using correct futures contract symbols
        if instrument == "XAUUSD":
            return "GC=F"  # Gold futures
        elif instrument == "XAGUSD":
            return "SI=F"  # Silver futures (not SL=F)
        elif instrument in ["XTIUSD", "WTIUSD"]:
            return "CL=F"  # WTI Crude Oil futures
        elif instrument == "XBRUSD":
            return "BZ=F"  # Brent Crude Oil futures
        elif instrument == "XPDUSD":
            return "PA=F"  # Palladium futures
        elif instrument == "XPTUSD":
            return "PL=F"  # Platinum futures
        elif instrument == "NATGAS":
            return "NG=F"  # Natural Gas futures
        elif instrument == "COPPER":
            return "HG=F"  # Copper futures
        
        # For indices
        if any(index in instrument for index in ["US30", "US500", "US100", "UK100", "DE40", "JP225"]):
            indices_map = {
                "US30": "^DJI",     # Dow Jones
                "US500": "^GSPC",   # S&P 500
                "US100": "^NDX",    # Nasdaq 100
                "UK100": "^FTSE",   # FTSE 100
                "DE40": "^GDAXI",   # DAX
                "JP225": "^N225",   # Nikkei 225
                "AU200": "^AXJO",   # ASX 200
                "EU50": "^STOXX50E", # Euro Stoxx 50
                "FR40": "^FCHI",    # CAC 40
                "HK50": "^HSI"      # Hang Seng
            }
            return indices_map.get(instrument, instrument)
                
        # Default: return as is
        return instrument 
