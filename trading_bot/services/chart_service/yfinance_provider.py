import logging
import traceback
import asyncio
import os
from typing import Optional, Dict, Any
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
    async def _download_data(symbol: str, start_date: datetime, end_date: datetime, interval: str, timeout: int = 30, original_symbol: str = None) -> pd.DataFrame:
        """Download data using yfinance with retry logic and caching."""
        # --- Caching Logic ---
        cache_key = (symbol, interval, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        if cache_key in data_download_cache:
            logger.info(f"[Yahoo Cache] HIT for download: {symbol} interval {interval}")
            return data_download_cache[cache_key].copy() # Return a copy to prevent mutation
        logger.info(f"[Yahoo Cache] MISS for download: {symbol} interval {interval}")
        # --- End Caching Logic ---

        logger.info(f"[Yahoo] Attempting direct download method with yf.download for {symbol}")
        
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

                # Download data
                df = yf.download(
                    tickers=symbol,
                    start=start_date,
                    end=end_date,
                    interval=interval,
                    progress=False, # Disable progress bar
                    session=session,
                    timeout=timeout,
                    ignore_tz=False # Keep timezone info initially
                )
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
    async def get_market_data(symbol: str, timeframe: str = "1d", limit: int = 100) -> Optional[Tuple[pd.DataFrame, Dict]]:
        """
        Get market data for a symbol and timeframe using Yahoo Finance.
        Includes data fetching optimization and caching.
        """
        # --- Caching Logic for Processed Data ---
        market_cache_key = (symbol, timeframe, limit)
        if market_cache_key in market_data_cache:
            logger.info(f"[Yahoo Cache] HIT for market data: {symbol} timeframe {timeframe} limit {limit}")
            # Return a copy to prevent modification of cached object
            cached_result = market_data_cache[market_cache_key]
            # Expecting a tuple (df, indicators_dict)
            if isinstance(cached_result, tuple) and len(cached_result) == 2 and isinstance(cached_result[0], pd.DataFrame):
                df_copy = cached_result[0].copy()
                indicators_copy = cached_result[1].copy() if isinstance(cached_result[1], dict) else {}
                return df_copy, indicators_copy
            else: # Handle potential non-tuple cached items (e.g., None)
                 # If None was cached, return (None, None)
                 if cached_result is None:
                     return None, None
                 # Otherwise, log unexpected cache content
                 logger.warning(f"[Yahoo Cache] Unexpected cached item type for {market_cache_key}: {type(cached_result)}")
                 # Attempt to clear the invalid cache entry
                 del market_data_cache[market_cache_key]
                 # Fall through to re-fetch

        logger.info(f"[Yahoo Cache] MISS for market data: {symbol} timeframe {timeframe} limit {limit}")
        # --- End Caching Logic ---

        try:
            logger.info(f"[Yahoo] Getting market data for {symbol} on {timeframe} timeframe")
            is_crypto = any(c in symbol for c in ["BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "LTC", "DOGE", "DOT", "LINK", "XLM", "AVAX"])
            is_commodity = any(c in symbol for c in ["XAU", "XAG", "CL", "NG", "ZC", "ZS", "ZW", "HG", "SI", "PL"]) or "OIL" in symbol
            
            formatted_symbol = YahooFinanceProvider._format_symbol(symbol, is_crypto, is_commodity)
            
            # Map timeframe to Yahoo Finance interval
            interval_map = {
                "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                "1h": "1h", "4h": "1h", # Fetch 1h for 4h resampling
                "1d": "1d", "1w": "1wk", "1M": "1mo"
            }
            interval = interval_map.get(timeframe, "1d")
            
            # --- Optimized Data Period Calculation ---
            # Fetch slightly more data than limit + max indicator period (e.g., EMA200)
            periods_needed = limit + 210 # Need ~200 for EMA200 + buffer
            
            # Estimate duration based on interval (simplified)
            if interval == "1m": days_to_fetch = min(7, periods_needed / (60*24)) # Max 7 days for 1m
            elif interval == "5m": days_to_fetch = min(60, periods_needed * 5 / (60*24)) # Max 60 days
            elif interval == "15m": days_to_fetch = min(60, periods_needed * 15 / (60*24)) # Max 60 days
            elif interval == "30m": days_to_fetch = min(60, periods_needed * 30 / (60*24)) # Max 60 days
            elif interval == "1h": days_to_fetch = min(730, periods_needed / 24) # Max 730 days
            elif interval == "1d": days_to_fetch = periods_needed * 1.5 # Add buffer for non-trading days
            elif interval == "1wk": days_to_fetch = periods_needed * 7 * 1.2 # Add buffer
            elif interval == "1mo": days_to_fetch = periods_needed * 31 * 1.1 # Add buffer
            else: days_to_fetch = 365 # Default fallback

            days_to_fetch = max(days_to_fetch, 2) # Ensure at least 2 days
            
            end_date = datetime.now()
            # Add a small buffer (e.g., 1 day) to ensure enough data points are captured
            start_date = end_date - timedelta(days=days_to_fetch + 1) 
            
            logger.info(f"[Yahoo] Requesting data for {formatted_symbol} from {start_date} to {end_date} with interval {interval} (estimated days: {days_to_fetch:.2f})")
            # --- End Optimized Data Period Calculation ---

            # Wait for rate limit
            await YahooFinanceProvider._wait_for_rate_limit()
            
            try:
                # Download the data from Yahoo Finance using the cached downloader
                df = await YahooFinanceProvider._download_data(
                    formatted_symbol, 
                    start_date,
                    end_date,
                    interval,
                    timeout=30,
                    original_symbol=symbol
                )
                
                if df is None or df.empty:
                    logger.warning(f"[Yahoo] No data returned for {symbol} ({formatted_symbol}) after download attempt.")
                    market_data_cache[market_cache_key] = None # Cache None result
                    return None, None # Return tuple
                    
                # Log success and data shape before validation
                logger.info(f"[Yahoo] Successfully downloaded data for {symbol} with shape {df.shape}")
                
                # Validate and clean the data
                df_validated = YahooFinanceProvider._validate_and_clean_data(df.copy(), symbol) # Validate a copy

                if df_validated is None or df_validated.empty:
                     logger.warning(f"[Yahoo] Data validation failed or resulted in empty DataFrame for {symbol}")
                     market_data_cache[market_cache_key] = None # Cache None result
                     return None, None # Return tuple

                # For 4h timeframe, resample from 1h
                if timeframe == "4h" and interval == "1h": # Ensure we fetched 1h data
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
                if len(df_validated) < periods_needed - limit: # Check if we have enough historical data
                     logger.warning(f"[Yahoo] Insufficient data after cleaning/resampling for {symbol} (got {len(df_validated)}, needed ~{periods_needed}). Indicators might be inaccurate.")
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

                         min_len_ema20 = 20
                         min_len_ema50 = 50
                         min_len_ema200 = 200
                         min_len_rsi = 15 # Need 14 periods + 1 for diff
                         min_len_macd = 26 + 9 # Need 26 for slow EMA, 9 for signal line

                         if len(df_with_indicators) >= min_len_ema20:
                              df_with_indicators['EMA20'] = df_with_indicators['Close'].ewm(span=20, adjust=False).mean()
                              indicators['EMA20'] = float(df_with_indicators['EMA20'].iloc[-1])
                         
                         if len(df_with_indicators) >= min_len_ema50:
                              df_with_indicators['EMA50'] = df_with_indicators['Close'].ewm(span=50, adjust=False).mean()
                              indicators['EMA50'] = float(df_with_indicators['EMA50'].iloc[-1])
                              
                         if len(df_with_indicators) >= min_len_ema200:
                              df_with_indicators['EMA200'] = df_with_indicators['Close'].ewm(span=200, adjust=False).mean()
                              indicators['EMA200'] = float(df_with_indicators['EMA200'].iloc[-1])
                         
                         # Calculate RSI safely
                         if len(df_with_indicators) >= min_len_rsi:
                              delta = df_with_indicators['Close'].diff()
                              gain = delta.where(delta > 0, 0.0).fillna(0.0)
                              loss = -delta.where(delta < 0, 0.0).fillna(0.0)

                              # Use simple moving average for initial values
                              # avg_gain = gain.rolling(window=14, min_periods=14).mean()
                              # avg_loss = loss.rolling(window=14, min_periods=14).mean()

                              # Calculate Wilder's smoothing for subsequent values (alternative: use ewm)
                              # Using ewm is often preferred and simpler
                              avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
                              avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()

                              rs = avg_gain / avg_loss.replace(0, np.nan) # Avoid division by zero, replace with NaN
                              df_with_indicators['RSI'] = 100 - (100 / (1 + rs))
                              # df_with_indicators['RSI'].fillna(method='bfill', inplace=True) # Backfill initial NaNs <- FIX WARNING
                              df_with_indicators['RSI'] = df_with_indicators['RSI'].bfill() # Use direct method (FIXED WARNING)

                              
                              # Handle potential NaN in the last value if avg_loss was 0 persistently
                              last_rsi = df_with_indicators['RSI'].iloc[-1]
                              indicators['RSI'] = float(last_rsi) if pd.notna(last_rsi) else None

                         # Calculate MACD safely
                         if len(df_with_indicators) >= min_len_macd:
                              df_with_indicators['EMA12'] = df_with_indicators['Close'].ewm(span=12, adjust=False).mean()
                              df_with_indicators['EMA26'] = df_with_indicators['Close'].ewm(span=26, adjust=False).mean()
                              df_with_indicators['MACD'] = df_with_indicators['EMA12'] - df_with_indicators['EMA26']
                              df_with_indicators['MACD_signal'] = df_with_indicators['MACD'].ewm(span=9, adjust=False).mean()
                              df_with_indicators['MACD_hist'] = df_with_indicators['MACD'] - df_with_indicators['MACD_signal']

                              indicators['MACD'] = float(df_with_indicators['MACD'].iloc[-1])
                              indicators['MACD_signal'] = float(df_with_indicators['MACD_signal'].iloc[-1])
                              indicators['MACD_hist'] = float(df_with_indicators['MACD_hist'].iloc[-1])

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
                market_data_cache[market_cache_key] = (result_df.copy(), indicators.copy()) # Cache copies
                # Log the shape being returned
                logger.info(f"[Yahoo] Returning market data for {symbol} with shape {result_df.shape}")

                return result_df, indicators # Return tuple
                
            except Exception as download_e:
                logger.error(f"[Yahoo] Error processing market data for {symbol}: {str(download_e)}")
                if isinstance(download_e, KeyError) and 'Open' in str(download_e):
                     logger.error(f"[Yahoo] Likely issue with column names after download for {symbol}. Raw columns: {df.columns if 'df' in locals() and df is not None else 'N/A'}")
                logger.error(traceback.format_exc()) # Log full traceback for download errors
                market_data_cache[market_cache_key] = None # Cache None result on error
                raise download_e
                
        except Exception as e:
            logger.error(f"[Yahoo] Unexpected error in get_market_data for {symbol}: {str(e)}")
            logger.error(traceback.format_exc()) # Log full traceback for unexpected errors
            # Ensure None is cached on unexpected error before returning
            market_data_cache[market_cache_key] = None 
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
