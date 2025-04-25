import logging
import traceback
import asyncio
import os
from typing import Optional, Dict, Any
from collections import namedtuple
import time
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class YahooFinanceProvider:
    """Provider class for Yahoo Finance API integration"""
    
    # Track API usage
    _last_api_call = 0
    _api_call_count = 0
    _max_calls_per_minute = 15  # Adjust based on Yahoo Finance limits
    
    @staticmethod
    async def get_market_data(instrument: str, timeframe: str = "1h") -> Optional[Dict[str, Any]]:
        """
        Get market data from Yahoo Finance API for technical analysis.
        
        Args:
            instrument: Trading instrument (e.g., EURUSD, BTCUSD, US500)
            timeframe: Timeframe for analysis (1h, 4h, 1d)
            
        Returns:
            Optional[Dict]: Technical analysis data or None if failed
        """
        try:
            # Implement basic rate limiting
            current_time = time.time()
            minute_passed = current_time - YahooFinanceProvider._last_api_call >= 60
            
            if minute_passed:
                # Reset counter if a minute has passed
                YahooFinanceProvider._api_call_count = 0
                YahooFinanceProvider._last_api_call = current_time
            elif YahooFinanceProvider._api_call_count >= YahooFinanceProvider._max_calls_per_minute:
                # If we hit the rate limit, wait until the minute is up
                logger.warning(f"Yahoo Finance API rate limit reached ({YahooFinanceProvider._api_call_count} calls). Waiting before retry.")
                await asyncio.sleep(5)  # Wait a bit before retrying
            
            # Increment the API call counter
            YahooFinanceProvider._api_call_count += 1
            
            # Format symbol for Yahoo Finance API
            formatted_symbol = YahooFinanceProvider._format_symbol(instrument)
            
            logger.info(f"Fetching {formatted_symbol} data from Yahoo Finance. API call #{YahooFinanceProvider._api_call_count} this minute.")
            
            # Map timeframe to Yahoo Finance interval
            yf_interval = {
                "1m": "1m", 
                "5m": "5m", 
                "15m": "15m", 
                "30m": "30m",
                "1h": "1h", 
                "2h": "2h", 
                "4h": "4h", 
                "1d": "1d",
                "1w": "1wk",
                "1M": "1mo"
            }.get(timeframe, "1h")
            
            # Determine appropriate period based on the interval
            if yf_interval in ["1m", "5m", "15m", "30m"]:
                period = "1d"  # For intraday data, get 1 day
            elif yf_interval in ["1h", "2h", "4h"]:
                period = "7d"  # For hourly data, get 7 days
            elif yf_interval == "1d":
                period = "3mo"  # For daily data, get 3 months
            else:
                period = "1y"  # For weekly/monthly data, get 1 year
                
            # For intervals like 4h that might need more history for indicators
            if yf_interval == "4h":
                period = "60d"  # Get more data for better indicator calculation
            
            # Use a thread pool executor to run the blocking yfinance call
            loop = asyncio.get_event_loop()
            
            try:
                # Get historical data from Yahoo Finance
                df = await loop.run_in_executor(
                    None,
                    lambda: yf.download(
                        formatted_symbol,
                        period=period,
                        interval=yf_interval,
                        auto_adjust=True,
                        progress=False
                    )
                )
                
                # Check if we got valid data
                if df is None or df.empty:
                    logger.warning(f"No data returned from Yahoo Finance for {instrument} ({formatted_symbol})")
                    return None
                
                # Calculate technical indicators
                df = YahooFinanceProvider._calculate_indicators(df)
                
                # Extract the latest data point
                latest = df.iloc[-1]
                
                # Safe conversion to float to handle Series objects
                def safe_float(val):
                    if hasattr(val, 'iloc'):
                        return float(val.iloc[0])
                    return float(val)
                
                # Calculate trend based on EMAs
                close_price = safe_float(latest['Close'])
                ema50 = safe_float(latest['EMA50'])
                ema200 = safe_float(latest['EMA200'])
                
                trend = "BUY" if close_price > ema50 > ema200 else \
                       "SELL" if close_price < ema50 < ema200 else \
                       "NEUTRAL"
                
                # Structure for compatibility with existing code
                AnalysisResult = namedtuple('AnalysisResult', ['summary', 'indicators', 'oscillators', 'moving_averages'])
                
                # Create indicators dictionary
                indicators = {
                    'close': safe_float(latest['Close']),
                    'open': safe_float(latest['Open']),
                    'high': safe_float(latest['High']),
                    'low': safe_float(latest['Low']),
                    'RSI': safe_float(latest['RSI']),
                    'MACD.macd': safe_float(latest['MACD']),
                    'MACD.signal': safe_float(latest['MACD_signal']),
                    'MACD.hist': safe_float(latest['MACD_hist']),
                    'EMA50': safe_float(latest['EMA50']),
                    'EMA200': safe_float(latest['EMA200']),
                    'volume': safe_float(latest.get('Volume', 0)),
                    'weekly_high': float(df['High'].max()),
                    'weekly_low': float(df['Low'].min())
                }
                
                # Create result object compatible with existing code
                analysis = AnalysisResult(
                    summary={'recommendation': trend},
                    indicators=indicators,
                    oscillators={},  # Can be expanded later with additional oscillators
                    moving_averages={}  # Can be expanded with more moving averages
                )
                
                return analysis
                
            except Exception as e:
                logger.error(f"Error in Yahoo Finance data download: {str(e)}")
                logger.error(traceback.format_exc())
                return None
                
        except Exception as e:
            logger.error(f"Error fetching data from Yahoo Finance: {str(e)}")
            logger.error(traceback.format_exc())
            return None
    
    @staticmethod
    def _calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """Calculate technical indicators for the dataframe"""
        # EMA calculations
        df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
        df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
        
        # RSI calculation
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        
        # Initialize with SMA for first 14 periods, then use EMA
        for i in range(14, len(df)):
            avg_gain.iloc[i] = (avg_gain.iloc[i-1] * 13 + gain.iloc[i]) / 14
            avg_loss.iloc[i] = (avg_loss.iloc[i-1] * 13 + loss.iloc[i]) / 14
            
        rs = avg_gain / avg_loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # MACD calculation
        df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
        df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = df['EMA12'] - df['EMA26']
        df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_hist'] = df['MACD'] - df['MACD_signal']
        
        # Clean NaN values
        df.fillna(0, inplace=True)
        
        return df
    
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
                
        # Default: return as is (for cryptocurrencies we'll use Binance API)
        return instrument

    # Instance method wrapper for backward compatibility
    def get_market_data(self, instrument, timeframe="1h"):
        """Instance method wrapper around the static method for backward compatibility"""
        return asyncio.run(self.get_market_data(instrument, timeframe)) 
