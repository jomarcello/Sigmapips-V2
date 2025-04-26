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

logger = logging.getLogger(__name__)

class YahooFinanceProvider:
    """Provider class for Yahoo Finance API integration"""
    
    # Cache data to minimize API calls
    _cache = {}
    _cache_timeout = 3600  # Cache timeout in seconds (1 hour)
    _last_api_call = 0
    _min_delay_between_calls = 2  # Minimum delay between calls in seconds
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
        wait=wait_exponential(multiplier=2, min=4, max=60),
        reraise=True
    )
    async def _download_data(symbol: str, start_date: datetime, end_date: datetime, interval: str, timeout: int = 30, original_symbol: str = None) -> pd.DataFrame:
        """Download data directly from Yahoo Finance using yfinance"""
        loop = asyncio.get_event_loop()
        
        def download():
            try:
                # Config for yfinance to use our session with headers
                session = YahooFinanceProvider._get_session()
                logger.info(f"[Yahoo] Using requests session with headers: User-Agent={session.headers.get('User-Agent', 'Unknown')[:30]}...")
                
                # Conditioneel de set_tz_session_for_downloading gebruiken als deze beschikbaar is
                try:
                    if hasattr(yf, 'set_tz_session_for_downloading'):
                        yf.set_tz_session_for_downloading(session=session)
                        logger.info("[Yahoo] Successfully set custom session for yfinance")
                    else:
                        logger.warning("[Yahoo] Function set_tz_session_for_downloading not available in this yfinance version")
                        # Voor oudere versies van yfinance kunnen we proberen de session direct te gebruiken
                except Exception as e:
                    logger.warning(f"[Yahoo] Error setting custom session: {str(e)}")
                
                # Log the exact download parameters
                logger.info(f"[Yahoo] Download parameters - Symbol: {symbol}, Start: {start_date}, End: {end_date}, Interval: {interval}, Timeout: {timeout}s")
                
                # Method 1: Use direct download which works better for most tickers
                logger.info(f"[Yahoo] Attempting direct download method with yf.download for {symbol}")
                try:
                    df = yf.download(
                        symbol, 
                        start=start_date,
                        end=end_date,
                        interval=interval,
                        progress=False,  # Turn off progress output
                        timeout=timeout  # Increase timeout for Railway
                    )
                    
                    if df is None:
                        logger.warning(f"[Yahoo] Direct download returned None for {symbol}")
                    elif df.empty:
                        logger.warning(f"[Yahoo] Direct download returned empty DataFrame for {symbol}")
                    else:
                        logger.info(f"[Yahoo] Direct download successful for {symbol}, got {len(df)} rows")
                        logger.info(f"[Yahoo] DataFrame columns: {df.columns.tolist()}")
                    
                except Exception as direct_e:
                    logger.error(f"[Yahoo] Direct download exception: {str(direct_e)}")
                    logger.error(f"[Yahoo] Error type: {type(direct_e).__name__}")
                    df = None
                
                # If direct download failed, try the Ticker method
                if df is None or df.empty:
                    logger.info(f"[Yahoo] Direct download failed for {symbol}, trying Ticker method")
                    try:
                        ticker = yf.Ticker(symbol, session=session)
                        logger.info(f"[Yahoo] Created Ticker object for {symbol}")
                        
                        # Try to get some ticker info to check if it's valid
                        try:
                            info_keys = list(ticker.info.keys())[:5] if hasattr(ticker, 'info') and ticker.info else []
                            logger.info(f"[Yahoo] Ticker info available: {len(info_keys)} keys")
                        except Exception as info_e:
                            logger.warning(f"[Yahoo] Could not retrieve ticker info: {str(info_e)}")
                        
                        # Get history
                        logger.info(f"[Yahoo] Getting history for {symbol} with Ticker method")
                        df = ticker.history(
                            start=start_date,
                            end=end_date,
                            interval=interval
                        )
                        
                        if df is None:
                            logger.warning(f"[Yahoo] Ticker method returned None for {symbol}")
                        elif df.empty:
                            logger.warning(f"[Yahoo] Ticker method returned empty DataFrame for {symbol}")
                        else:
                            logger.info(f"[Yahoo] Ticker method successful for {symbol}, got {len(df)} rows")
                            logger.info(f"[Yahoo] DataFrame columns: {df.columns.tolist()}")
                            
                    except Exception as ticker_e:
                        logger.error(f"[Yahoo] Ticker method exception: {str(ticker_e)}")
                        logger.error(f"[Yahoo] Error type: {type(ticker_e).__name__}")
                        df = None
                
                # If yfinance methods all failed, throw an exception
                if df is None or df.empty:
                    logger.warning(f"[Yahoo] All Yahoo Finance methods failed for {symbol}")
                    raise Exception(f"No data available for {symbol} from Yahoo Finance API after trying multiple methods")
                
                return df
                        
            except Exception as e:
                logger.error(f"[Yahoo] Error downloading data from Yahoo Finance: {str(e)}")
                raise e
        
        return await loop.run_in_executor(None, download)
    
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
            # Initial diagnostics
            logger.info(f"[Validation] Starting data validation with shape: {df.shape}")
            logger.info(f"[Validation] Original columns: {df.columns}")
            logger.info(f"[Validation] Index type: {type(df.index).__name__}")
            logger.info(f"[Validation] Index range: {df.index[0]} to {df.index[-1]}" if len(df) > 0 else "[Validation] Empty index")
            
            # Check for NaN values in the original data
            nan_counts = df.isna().sum()
            if nan_counts.sum() > 0:
                logger.warning(f"[Validation] Found NaN values in original data: {nan_counts.to_dict()}")
            
            # Check if we have a multi-index dataframe from yfinance
            if isinstance(df.columns, pd.MultiIndex):
                logger.info(f"[Validation] Detected MultiIndex columns with levels: {[name for name in df.columns.names]}")
                logger.info(f"[Validation] First level values: {df.columns.get_level_values(0).unique().tolist()}")
                logger.info(f"[Validation] Second level values: {df.columns.get_level_values(1).unique().tolist()}")
                
                # Convert multi-index format to standard format
                result = pd.DataFrame()
                
                # Extract each price column
                for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    if (col, df.columns.get_level_values(1)[0]) in df.columns:
                        result[col] = df[(col, df.columns.get_level_values(1)[0])]
                        logger.info(f"[Validation] Extracted {col} from MultiIndex")
                    else:
                        logger.error(f"[Validation] Column {col} not found in multi-index")
                        
                # Replace original dataframe with converted one
                if not result.empty:
                    logger.info(f"[Validation] Successfully converted multi-index to: {result.columns}")
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
            
            # Report initial data statistics
            logger.info(f"[Validation] Data statistics before cleaning:")
            for col in required_columns:
                try:
                    stats = {
                        'min': df[col].min(),
                        'max': df[col].max(),
                        'mean': df[col].mean(),
                        'null_count': df[col].isnull().sum()
                    }
                    logger.info(f"[Validation] {col}: {stats}")
                except Exception as stats_e:
                    logger.error(f"[Validation] Error calculating stats for {col}: {str(stats_e)}")
            
            # Remove any duplicate indices
            dupes_count = df.index.duplicated().sum()
            if dupes_count > 0:
                logger.warning(f"[Validation] Found {dupes_count} duplicate indices, removing duplicates")
                df = df[~df.index.duplicated(keep='last')]
            else:
                logger.info("[Validation] No duplicate indices found")
            
            # Forward fill missing values (max 2 periods)
            null_before = df.isnull().sum().sum()
            df = df.ffill(limit=2)
            null_after = df.isnull().sum().sum()
            if null_before > 0:
                logger.info(f"[Validation] Forward-filled {null_before - null_after} NaN values (limit=2)")
            
            # Remove rows with any remaining NaN values
            row_count_before = len(df)
            df = df.dropna()
            row_count_after = len(df)
            if row_count_after < row_count_before:
                logger.warning(f"[Validation] Dropped {row_count_before - row_count_after} rows with NaN values")
            
            # Ensure all numeric columns are float
            for col in df.columns:
                try:
                    with pd.option_context('mode.chained_assignment', None):
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                    nan_after_conversion = df[col].isna().sum()
                    if nan_after_conversion > 0:
                        logger.warning(f"[Validation] Converting {col} to numeric created {nan_after_conversion} NaN values")
                except Exception as conv_e:
                    logger.error(f"[Validation] Error converting {col} to numeric: {str(conv_e)}")
            
            # Check for remaining NaN values after numeric conversion
            if df.isna().sum().sum() > 0:
                logger.warning(f"[Validation] Still have NaN values after numeric conversion: {df.isna().sum().to_dict()}")
                # Drop rows with NaN values again
                row_count_before = len(df)
                df = df.dropna()
                row_count_after = len(df)
                logger.warning(f"[Validation] Dropped additional {row_count_before - row_count_after} rows with NaN values")
            
            # Validate price relationships - only keep rows with valid OHLC relationships
            row_count_before = len(df)
            valid_rows = (
                (df['High'] >= df['Low']) & 
                (df['High'] >= df['Open']) & 
                (df['High'] >= df['Close']) &
                (df['Low'] <= df['Open']) & 
                (df['Low'] <= df['Close'])
            )
            
            # Log invalid row counts by condition
            if not valid_rows.all():
                invalid_count = (~valid_rows).sum()
                logger.warning(f"[Validation] Found {invalid_count} rows with invalid OHLC relationships")
                
                # Detailed diagnostics of invalid rows
                condition_results = {
                    'High < Low': (df['High'] < df['Low']).sum(),
                    'High < Open': (df['High'] < df['Open']).sum(),
                    'High < Close': (df['High'] < df['Close']).sum(),
                    'Low > Open': (df['Low'] > df['Open']).sum(),
                    'Low > Close': (df['Low'] > df['Close']).sum()
                }
                logger.warning(f"[Validation] Invalid relationship details: {condition_results}")
                
                # Show an example of an invalid row
                if invalid_count > 0:
                    try:
                        invalid_idx = (~valid_rows).idxmax()
                        logger.warning(f"[Validation] Example invalid row at {invalid_idx}: {df.loc[invalid_idx, ['Open', 'High', 'Low', 'Close']].to_dict()}")
                    except Exception as e:
                        logger.error(f"[Validation] Error showing invalid row example: {str(e)}")
            
            df = df[valid_rows]
            row_count_after = len(df)
            if row_count_after < row_count_before:
                logger.warning(f"[Validation] Removed {row_count_before - row_count_after} rows with invalid OHLC relationships")
            
            # Also validate Volume if it exists
            if 'Volume' in df.columns:
                row_count_before = len(df)
                df = df[df['Volume'] >= 0]
                row_count_after = len(df)
                if row_count_after < row_count_before:
                    logger.warning(f"[Validation] Removed {row_count_before - row_count_after} rows with negative Volume")
            
            # Apply correct decimal precision based on instrument type if provided
            if instrument:
                try:
                    # Get the appropriate precision for this instrument
                    precision = YahooFinanceProvider._get_instrument_precision(instrument)
                    logger.info(f"[Validation] Using {precision} decimal places for {instrument}")
                    
                    # Apply precision to price columns
                    price_columns = ['Open', 'High', 'Low', 'Close']
                    for col in price_columns:
                        if col in df.columns:
                            # Round the values to the appropriate precision
                            # This ensures the data is displayed with the correct number of decimal places
                            df[col] = df[col].round(precision)
                except Exception as e:
                    logger.error(f"[Validation] Error applying precision for {instrument}: {str(e)}")
            
            # Final data statistics
            logger.info(f"[Validation] Final validated DataFrame shape: {df.shape}")
            if len(df) > 0:
                logger.info(f"[Validation] Date range: {df.index[0]} to {df.index[-1]}")
                
                # Log final statistics for key columns
                for col in required_columns:
                    if col in df.columns:
                        try:
                            stats = {
                                'min': df[col].min(),
                                'max': df[col].max(),
                                'mean': df[col].mean(),
                            }
                            logger.info(f"[Validation] Final {col} statistics: {stats}")
                        except Exception as stats_e:
                            logger.error(f"[Validation] Error calculating final stats for {col}: {str(stats_e)}")
            
            return df
            
        except Exception as e:
            logger.error(f"[Validation] Error in data validation: {str(e)}")
            logger.error(f"[Validation] Error type: {type(e).__name__}")
            logger.error(traceback.format_exc())
            return df

    @staticmethod
    async def get_market_data(symbol: str, timeframe: str = "1d", limit: int = 100) -> Optional[pd.DataFrame]:
        """
        Get market data for a specific instrument and timeframe.
        
        Args:
            symbol: The instrument symbol (e.g., EURUSD, BTCUSD)
            timeframe: Timeframe for the data (e.g., 1h, 4h, 1d)
            limit: Maximum number of candles to return
            
        Returns:
            Optional[pd.DataFrame]: DataFrame with market data or None if failed
        """
        try:
            logger.info(f"[Yahoo] Getting market data for {symbol} on {timeframe} timeframe")
            
            # Format the symbol for Yahoo Finance
            formatted_symbol = YahooFinanceProvider._format_symbol(symbol)
            logger.info(f"[Yahoo] Formatted symbol: {formatted_symbol}")
            
            # Is this a commodity?
            is_commodity = any(commodity in symbol for commodity in ["XAUUSD", "XAGUSD", "XTIUSD", "WTIUSD", "XBRUSD"])
            
            # Convert timeframe to Yahoo Finance interval
            if timeframe == "1m":
                interval = "1m"
            elif timeframe == "5m":
                interval = "5m"
            elif timeframe == "15m":
                interval = "15m"
            elif timeframe == "30m":
                interval = "30m"
            elif timeframe == "1h":
                interval = "1h"
            elif timeframe == "4h":
                interval = "1h"  # Use 1h and aggregate later
            elif timeframe == "1d":
                interval = "1d"
            else:
                interval = "1d"  # Default to daily
            
            # Calculate start and end dates based on the requested timeframe and limit
            end_date = datetime.now()
            
            # For 4h timeframe, we need to fetch more 1h candles
            multiplier = 4 if timeframe == "4h" else 1
            
            # Get more data than needed for indicators calculation
            extra_periods = 200  # Extra periods for calculating indicators like EMA200
            
            # Calculate the start date based on the timeframe
            if interval == "1m":
                # Yahoo only provides 7 days of 1m data
                days_to_fetch = min(7, limit * multiplier / 24 / 60)
                start_date = end_date - timedelta(days=days_to_fetch)
            elif interval == "5m":
                # Yahoo provides 60 days of 5m data
                days_to_fetch = min(60, limit * multiplier * 5 / 24 / 60)
                start_date = end_date - timedelta(days=days_to_fetch)
            elif interval == "15m":
                # Yahoo provides 60 days of 15m data
                days_to_fetch = min(60, limit * multiplier * 15 / 24 / 60)
                start_date = end_date - timedelta(days=days_to_fetch)
            elif interval == "30m":
                # Yahoo provides 60 days of 30m data
                days_to_fetch = min(60, limit * multiplier * 30 / 24 / 60)
                start_date = end_date - timedelta(days=days_to_fetch)
            elif interval == "1h":
                # Get enough days based on limit and possibly 4h timeframe
                days_to_fetch = (limit + extra_periods) * multiplier / 24
                start_date = end_date - timedelta(days=days_to_fetch + 10)  # Add some buffer
            elif interval == "1d":
                # For daily data, simply get enough days
                days_to_fetch = limit + extra_periods
                start_date = end_date - timedelta(days=days_to_fetch + 50)  # Add buffer for weekends/holidays
            else:
                # Default fallback
                start_date = end_date - timedelta(days=365)
            
            logger.info(f"[Yahoo] Requesting data for {formatted_symbol} from {start_date} to {end_date} with interval {interval}")
            
            # Wait for rate limit
            await YahooFinanceProvider._wait_for_rate_limit()
            
            try:
                # Download the data from Yahoo Finance
                df = await YahooFinanceProvider._download_data(
                    formatted_symbol, 
                    start_date,
                    end_date,
                    interval,
                    timeout=30,  # Longer timeout for potentially slow connections
                    original_symbol=symbol  # Pass original for reference
                )
                
                if df is None or df.empty:
                    logger.warning(f"[Yahoo] No data returned for {symbol} ({formatted_symbol})")
                    
                    # Special debug message for commodities
                    if is_commodity:
                        logger.warning(f"[Yahoo] Commodity data failed for {symbol}. Yahoo Finance may have changed their API for commodity futures.")
                        
                    return None
                    
                # Log success and data shape
                logger.info(f"[Yahoo] Successfully downloaded data for {symbol} with shape {df.shape}")
                
                # Validate and clean the data
                df = YahooFinanceProvider._validate_and_clean_data(df, symbol)
                
                # For 4h timeframe, resample from 1h
                if timeframe == "4h":
                    logger.info(f"[Yahoo] Resampling 1h data to 4h for {symbol}")
                    try:
                        # Resample to 4h
                        df = df.resample('4H').agg({
                            'Open': 'first',
                            'High': 'max',
                            'Low': 'min',
                            'Close': 'last',
                            'Volume': 'sum'
                        })
                        df.dropna(inplace=True)
                        logger.info(f"[Yahoo] Successfully resampled to 4h with shape {df.shape}")
                    except Exception as resample_e:
                        logger.error(f"[Yahoo] Error resampling to 4h: {str(resample_e)}")
                        # Continue with 1h data if resampling fails
                
                # Limit the number of candles
                df = df.iloc[-limit:]
                
                # Calculate indicators and return as a special object
                result = pd.DataFrame(df)
                
                # Add indicators
                indicators = {
                    'open': float(df['Open'].iloc[-1]),
                    'high': float(df['High'].iloc[-1]),
                    'low': float(df['Low'].iloc[-1]),
                    'close': float(df['Close'].iloc[-1]),
                    'volume': float(df['Volume'].iloc[-1]) if 'Volume' in df.columns else 0
                }
                
                # Add EMAs if we have enough data
                if len(df) >= 20:
                    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
                    indicators['EMA20'] = float(df['EMA20'].iloc[-1])
                
                if len(df) >= 50:
                    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
                    indicators['EMA50'] = float(df['EMA50'].iloc[-1])
                    
                if len(df) >= 200:
                    df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
                    indicators['EMA200'] = float(df['EMA200'].iloc[-1])
                
                # Calculate RSI
                if len(df) >= 14:
                    delta = df['Close'].diff()
                    gain = delta.where(delta > 0, 0)
                    loss = -delta.where(delta < 0, 0)
                    avg_gain = gain.rolling(window=14).mean()
                    avg_loss = loss.rolling(window=14).mean()
                    rs = avg_gain / avg_loss
                    df['RSI'] = 100 - (100 / (1 + rs))
                    indicators['RSI'] = float(df['RSI'].iloc[-1])
                
                # Calculate MACD
                if len(df) >= 26:
                    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
                    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
                    df['MACD'] = df['EMA12'] - df['EMA26']
                    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
                    indicators['MACD'] = float(df['MACD'].iloc[-1])
                    indicators['MACD_signal'] = float(df['MACD_signal'].iloc[-1])
                    indicators['MACD_hist'] = float(df['MACD'].iloc[-1]) - float(df['MACD_signal'].iloc[-1])
                
                # Store indicators as an attribute of the DataFrame
                result.indicators = indicators
                
                return result
                
            except Exception as download_e:
                logger.error(f"Error downloading market data for {symbol}: {str(download_e)}")
                logger.error(f"Error type: {type(download_e).__name__}")
                
                # Special debug message for commodities
                if is_commodity:
                    logger.error(f"Commodity data failed for {symbol}. This is a common issue as Yahoo Finance periodically changes their API for futures contracts.")
                    logger.error(f"The system will use fallback data for this commodity.")
                
                raise download_e
                
        except Exception as e:
            logger.error(f"Error getting market data from Yahoo Finance: {str(e)}")
            logger.error(traceback.format_exc())
            return None

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
    def _format_symbol(instrument: str) -> str:
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
