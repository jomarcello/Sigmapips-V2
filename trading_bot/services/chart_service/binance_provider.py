import logging
import traceback
import asyncio
import os
import aiohttp
from typing import Optional, Dict, Any, List
from collections import namedtuple
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class BinanceProvider:
    """Provider class for Binance API integration for cryptocurrency data"""
    
    # Base URLs for Binance API
    BASE_URL = "https://api.binance.com"
    
    # Track API usage
    _last_api_call = 0
    _api_call_count = 0
    _max_calls_per_minute = 20  # Binance rate limits
    
    @staticmethod
    async def get_market_data(instrument: str, timeframe: str = "1h") -> Optional[Dict[str, Any]]:
        """
        Get market data from Binance API for technical analysis.
        
        Args:
            instrument: Trading instrument (e.g., BTCUSD, ETHUSDT)
            timeframe: Timeframe for analysis (1h, 4h, 1d)
            
        Returns:
            Optional[Dict]: Technical analysis data or None if failed
        """
        try:
            # Implement basic rate limiting
            current_time = time.time()
            minute_passed = current_time - BinanceProvider._last_api_call >= 60
            
            if minute_passed:
                # Reset counter if a minute has passed
                BinanceProvider._api_call_count = 0
                BinanceProvider._last_api_call = current_time
            elif BinanceProvider._api_call_count >= BinanceProvider._max_calls_per_minute:
                # If we hit the rate limit, wait until the minute is up
                logger.warning(f"Binance API rate limit reached ({BinanceProvider._api_call_count} calls). Waiting before retry.")
                await asyncio.sleep(5)  # Wait a bit before retrying
            
            # Increment the API call counter
            BinanceProvider._api_call_count += 1
            
            # Format symbol for Binance API
            formatted_symbol = BinanceProvider._format_symbol(instrument)
            
            logger.info(f"Fetching {formatted_symbol} data from Binance. API call #{BinanceProvider._api_call_count} this minute.")
            
            # Map timeframe to Binance interval
            binance_interval = {
                "1m": "1m", 
                "5m": "5m", 
                "15m": "15m", 
                "30m": "30m",
                "1h": "1h", 
                "2h": "2h", 
                "4h": "4h", 
                "1d": "1d",
                "1w": "1w",
                "1M": "1M"
            }.get(timeframe, "1h")
            
            # Determine the number of candles to fetch based on timeframe
            limit = 100
            if binance_interval in ["1h", "2h", "4h"]:
                limit = 120  # Get more data for better indicator calculation
                
            # Fetch klines (candlestick data)
            endpoint = f"/api/v3/klines"
            params = {
                "symbol": formatted_symbol,
                "interval": binance_interval,
                "limit": limit
            }
            
            # Get candlestick data
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{BinanceProvider.BASE_URL}{endpoint}", params=params) as response:
                    if response.status != 200:
                        logger.error(f"Binance API error: {response.status}")
                        return None
                    
                    klines = await response.json()
                    if not klines or not isinstance(klines, list):
                        logger.error(f"Binance API returned invalid kline data: {klines}")
                        return None
            
            # Convert klines to dataframe
            df = BinanceProvider._klines_to_dataframe(klines)
            
            # Calculate technical indicators
            df = BinanceProvider._calculate_indicators(df)
            
            # Get the latest data point
            latest = df.iloc[-1]
            
            # Create analysis result object
            MarketData = namedtuple('MarketData', ['instrument', 'indicators'])
            
            # Extract indicators for return
            indicators = {
                "close": float(latest["close"]),
                "open": float(latest["open"]),
                "high": float(latest["high"]),
                "low": float(latest["low"]),
                "volume": float(latest["volume"]),
                "EMA50": float(latest["EMA50"]),
                "EMA200": float(latest["EMA200"]),
                "RSI": float(latest["RSI"]),
                "MACD.macd": float(latest["MACD"]),
                "MACD.signal": float(latest["MACD_signal"]),
                "MACD.hist": float(latest["MACD_hist"]),
            }
            
            # Add weekly high/low if available
            if "weekly_high" in latest and "weekly_low" in latest:
                indicators["weekly_high"] = float(latest["weekly_high"])
                indicators["weekly_low"] = float(latest["weekly_low"])
            else:
                # Calculate approximate weekly high/low from available data
                week_data = df.tail(168 if binance_interval == "1h" else 
                                   42 if binance_interval == "4h" else 
                                   7 if binance_interval == "1d" else df.shape[0])
                indicators["weekly_high"] = float(week_data["high"].max())
                indicators["weekly_low"] = float(week_data["low"].min())
                
            result = MarketData(instrument=instrument, indicators=indicators)
            return result
            
        except Exception as e:
            logger.error(f"Error getting market data from Binance: {str(e)}")
            logger.error(traceback.format_exc())
            return None
    
    @staticmethod
    def _klines_to_dataframe(klines: List) -> pd.DataFrame:
        """Convert Binance klines to pandas DataFrame"""
        # Binance kline format: 
        # [Open time, Open, High, Low, Close, Volume, Close time, Quote asset volume, 
        # Number of trades, Taker buy base asset volume, Taker buy quote asset volume, Ignore]
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume', 
            'close_time', 'quote_volume', 'trades', 'taker_base_volume', 
            'taker_quote_volume', 'ignore'
        ])
        
        # Convert types
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['open'] = pd.to_numeric(df['open'])
        df['high'] = pd.to_numeric(df['high'])
        df['low'] = pd.to_numeric(df['low'])
        df['close'] = pd.to_numeric(df['close'])
        df['volume'] = pd.to_numeric(df['volume'])
        
        # Set timestamp as index
        df.set_index('timestamp', inplace=True)
        
        return df
    
    @staticmethod
    def _calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """Calculate technical indicators"""
        # Calculate EMAs
        df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        # Calculate RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        
        rs = avg_gain / avg_loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # Calculate MACD
        df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = df['EMA12'] - df['EMA26']
        df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_hist'] = df['MACD'] - df['MACD_signal']
        
        # Clean NaN values
        df.fillna(0, inplace=True)
        
        return df
    
    @staticmethod
    def _format_symbol(instrument: str) -> str:
        """Format instrument symbol for Binance API"""
        instrument = instrument.upper().replace("/", "")
        
        # Ensure proper format for Binance (BTCUSD -> BTCUSDT)
        if instrument.endswith("USD") and not instrument.endswith("USDT"):
            instrument = instrument.replace("USD", "USDT")
        
        return instrument 
