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
            retries = Retry(
                total=5,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "POST", "OPTIONS"]
            )
            adapter = HTTPAdapter(max_retries=retries, pool_maxsize=10)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            })
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
    async def _download_data(symbol: str, start_date: datetime, end_date: datetime, interval: str) -> pd.DataFrame:
        """Download data directly from Yahoo Finance using yfinance"""
        loop = asyncio.get_event_loop()
        
        def download():
            try:
                # Method 1: Use direct download which works better for most tickers
                df = yf.download(
                    symbol, 
                    start=start_date,
                    end=end_date,
                    interval=interval,
                    progress=False  # Turn off progress output
                )
                
                # If direct download failed, try the Ticker method
                if df is None or df.empty:
                    logger.info(f"Direct download failed for {symbol}, trying Ticker method")
                    ticker = yf.Ticker(symbol)
                    df = ticker.history(
                        start=start_date,
                        end=end_date,
                        interval=interval
                    )
                
                return df
                        
            except Exception as e:
                logger.error(f"Error downloading data from Yahoo Finance: {str(e)}")
                raise e
        
        return await loop.run_in_executor(None, download)
    
    @staticmethod
    def _validate_and_clean_data(df: pd.DataFrame) -> pd.DataFrame:
        """
        Validate and clean the market data
        """
        if df is None or df.empty:
            return df
            
        try:
            # Print the original columns for debugging
            logger.info(f"Original columns: {df.columns}")
            
            # Check if we have a multi-index dataframe from yfinance
            if isinstance(df.columns, pd.MultiIndex):
                # Convert multi-index format to standard format
                result = pd.DataFrame()
                
                # Extract each price column
                for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    if (col, df.columns.get_level_values(1)[0]) in df.columns:
                        result[col] = df[(col, df.columns.get_level_values(1)[0])]
                    else:
                        logger.error(f"Column {col} not found in multi-index")
                        
                # Replace original dataframe with converted one
                if not result.empty:
                    logger.info(f"Successfully converted multi-index to: {result.columns}")
                    df = result
                else:
                    logger.error("Failed to convert multi-index dataframe")
                    return pd.DataFrame()
            
            # Ensure we have the required columns
            required_columns = ['Open', 'High', 'Low', 'Close']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                logger.error(f"Required columns missing: {missing_columns}")
                logger.info(f"Available columns: {df.columns}")
                return pd.DataFrame()
            
            # Remove any duplicate indices
            df = df[~df.index.duplicated(keep='last')]
            
            # Forward fill missing values (max 2 periods)
            df = df.ffill(limit=2)
            
            # Remove rows with any remaining NaN values
            df = df.dropna()
            
            # Ensure all numeric columns are float
            for col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Validate price relationships - only keep rows with valid OHLC relationships
            df = df[
                (df['High'] >= df['Low']) & 
                (df['High'] >= df['Open']) & 
                (df['High'] >= df['Close']) &
                (df['Low'] <= df['Open']) & 
                (df['Low'] <= df['Close'])
            ]
            
            # Also validate Volume if it exists
            if 'Volume' in df.columns:
                df = df[df['Volume'] >= 0]
            
            return df
            
        except Exception as e:
            logger.error(f"Error in data validation: {str(e)}")
            logger.error(traceback.format_exc())
            return df

    @staticmethod
    async def get_market_data(symbol: str, timeframe: str = "1d", limit: int = 100) -> Optional[pd.DataFrame]:
        """
        Get market data for a symbol with caching and error handling
        """
        try:
            # Format the symbol for Yahoo Finance
            formatted_symbol = YahooFinanceProvider._format_symbol(symbol)
            
            # Check cache first
            cache_key = f"{formatted_symbol}_{timeframe}_{limit}"
            current_time = time.time()
            
            if cache_key in YahooFinanceProvider._cache:
                cached_data, cache_time = YahooFinanceProvider._cache[cache_key]
                if current_time - cache_time < YahooFinanceProvider._cache_timeout:
                    return cached_data

            # Convert timeframe to yfinance interval
            interval_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "30m": "30m",
                "1h": "60m", # yfinance uses 60m instead of 1h
                "1d": "1d",
                "1wk": "1wk",
                "1mo": "1mo"
            }
            
            interval = interval_map.get(timeframe, "1d")
            
            # Calculate date range based on limit and interval
            end_date = datetime.now()
            if interval in ["1m", "5m", "15m", "30m", "60m"]:
                # For intraday data, yahoo only provides limited history
                # 1m - 7 days, 5m - 60 days, 15m/30m/60m - 730 days
                if interval == "1m":
                    days_back = 7
                elif interval == "5m":
                    days_back = 60
                else:
                    days_back = 730
                # Ensure we don't request too much data
                days_back = min(days_back, limit)
                start_date = end_date - timedelta(days=days_back)
            else:
                # For other intervals, calculate based on limit with some buffer
                days_map = {
                    "1d": 1,
                    "1wk": 7,
                    "1mo": 30
                }
                multiplier = days_map.get(interval, 1)
                start_date = end_date - timedelta(days=limit * multiplier * 2)  # Double the days to ensure we get enough data

            # Wait for rate limit
            await YahooFinanceProvider._wait_for_rate_limit()
            
            # Download data from Yahoo Finance
            logger.info(f"Downloading data for {formatted_symbol} from {start_date} to {end_date}")
            df = await YahooFinanceProvider._download_data(
                formatted_symbol,
                start_date,
                end_date,
                interval
            )
            
            if df is None or df.empty:
                logger.error(f"No data returned from Yahoo Finance for {symbol}")
                return None
            
            # Ensure datetime index
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            
            # Validate and clean data
            df = YahooFinanceProvider._validate_and_clean_data(df)
            
            if df is None or df.empty:
                logger.error(f"No valid data after cleaning for {symbol}")
                return None
                
            # Sort by date and limit rows
            df = df.sort_index().tail(limit)
            
            # Cache the result
            YahooFinanceProvider._cache[cache_key] = (df, current_time)
            
            return df
            
        except Exception as e:
            logger.error(f"Error fetching market data for {symbol}: {str(e)}")
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
    def _format_symbol(instrument: str) -> str:
        """Format instrument symbol for Yahoo Finance API"""
        instrument = instrument.upper().replace("/", "")
        
        # For forex (EURUSD -> EUR=X)
        if len(instrument) == 6 and all(c.isalpha() for c in instrument):
            base = instrument[:3]
            quote = instrument[3:]
            return f"{base}{quote}=X"
            
        # For commodities - using direct futures symbols
        if instrument == "XAUUSD":
            return "GC=F"  # Gold futures
        elif instrument == "XAGUSD":
            return "SI=F"  # Silver futures
        
        # For crude oil
        if instrument in ["XTIUSD", "WTIUSD"]:
            return "CL=F"  # WTI Crude Oil futures
            
        # For indices
        if any(index in instrument for index in ["US30", "US500", "US100", "UK100", "DE40", "JP225"]):
            indices_map = {
                "US30": "^DJI",    # Dow Jones
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
