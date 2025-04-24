import logging
import traceback
import asyncio
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from twelvedata import TDClient
from collections import namedtuple

logger = logging.getLogger(__name__)

class TwelveDataProvider:
    """Provider class for TwelveData API integration"""
    
    # API key
    API_KEY = "2d14e67c389f4ee09cb5d377139f6297"
    
    @staticmethod
    async def get_market_data(instrument: str, timeframe: str = "1h") -> Optional[Dict[str, Any]]:
        """
        Get market data from TwelveData API for technical analysis.
        
        Args:
            instrument: Trading instrument (e.g., EURUSD, BTCUSD, US500)
            timeframe: Timeframe for analysis (1h, 4h, 1d)
            
        Returns:
            Optional[Dict]: Technical analysis data or None if failed
        """
        try:
            # Format symbol for TwelveData API
            formatted_symbol = TwelveDataProvider._format_symbol(instrument)
            
            logger.info(f"Fetching {formatted_symbol} data from TwelveData")
            
            # Map timeframe to TwelveData format
            td_timeframe = {
                "1m": "1min", 
                "5m": "5min", 
                "15m": "15min", 
                "30m": "30min",
                "1h": "1h", 
                "2h": "2h", 
                "4h": "4h", 
                "1d": "1day",
                "1w": "1week"
            }.get(timeframe, "1h")
            
            # Initialize TwelveData client
            td = TDClient(apikey=TwelveDataProvider.API_KEY)
            
            # Create time series object with technical indicators
            ts = td.time_series(
                symbol=formatted_symbol,
                interval=td_timeframe,
                outputsize=100,  # Sufficient data for indicators
                timezone="UTC",
                order="desc",
            )
            
            # Add technical indicators
            time_series_with_indicators = ts.with_ema(time_period=50)\
                                           .with_ema(time_period=200)\
                                           .with_rsi()\
                                           .with_macd()
            
            # Get data as pandas DataFrame with timeout
            with ThreadPoolExecutor() as executor:
                df_future = asyncio.get_event_loop().run_in_executor(
                    executor, 
                    time_series_with_indicators.as_pandas
                )
                
                df = await asyncio.wait_for(df_future, timeout=10.0)
                
                if df is None or df.empty:
                    logger.warning(f"No data returned from TwelveData for {instrument}")
                    return None
                
                logger.info(f"Retrieved data from TwelveData for {instrument}: {len(df)} rows")
                
                # Extract latest data
                latest = df.iloc[0]  # First row due to 'desc' order
                
                # Calculate trend based on EMAs
                trend = "BUY" if latest['close'] > latest['ema1'] > latest['ema2'] else \
                       "SELL" if latest['close'] < latest['ema1'] < latest['ema2'] else \
                       "NEUTRAL"
                
                # Structure for TradingView API compatibility
                AnalysisResult = namedtuple('AnalysisResult', ['summary', 'indicators', 'oscillators', 'moving_averages'])
                
                # Calculate weekly high/low from available data
                weekly_high = df['high'].max()
                weekly_low = df['low'].min()
                
                # Create indicators dictionary
                indicators = {
                    'close': float(latest['close']),
                    'open': float(latest['open']),
                    'high': float(latest['high']),
                    'low': float(latest['low']),
                    'RSI': float(latest['rsi']),
                    'MACD.macd': float(latest['macd']),
                    'MACD.signal': float(latest['macd_signal']),
                    'MACD.hist': float(latest['macd_hist']),
                    'EMA50': float(latest['ema1']),
                    'EMA200': float(latest['ema2']),
                    'volume': float(latest.get('volume', 0)),
                    'weekly_high': float(weekly_high),
                    'weekly_low': float(weekly_low)
                }
                
                # Create result object compatible with existing code
                analysis = AnalysisResult(
                    summary={'recommendation': trend},
                    indicators=indicators,
                    oscillators={},
                    moving_averages={}
                )
                
                return analysis
                
        except asyncio.TimeoutError:
            logger.error(f"TwelveData API request timed out for {instrument}")
            return None
        except Exception as e:
            logger.error(f"Error fetching data from TwelveData: {str(e)}")
            logger.error(traceback.format_exc())
            return None
    
    @staticmethod
    def _format_symbol(instrument: str) -> str:
        """Format instrument symbol for TwelveData API"""
        instrument = instrument.upper().replace("/", "")
        
        # For crypto (BTCUSD -> BTC/USD)
        if any(crypto in instrument for crypto in ["BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "LTC", "DOG", "DOT", "XLM", "AVX"]):
            if instrument.endswith("USD"):
                symbol = instrument.replace("USD", "")
                return f"{symbol}/USD"
            else:
                return instrument
                
        # For forex (EURUSD -> EUR/USD)
        elif len(instrument) == 6 and all(c.isalpha() for c in instrument):
            return f"{instrument[:3]}/{instrument[3:]}"
            
        # For indices (US30, US500, etc.)
        elif any(index in instrument for index in ["US30", "US500", "US100", "UK100", "DE40", "JP225"]):
            # TwelveData uses different index names for some markets
            index_map = {
                "US30": "DJI",
                "US500": "SPX",
                "US100": "NDX"
            }
            return index_map.get(instrument, instrument)
            
        # For commodities
        elif any(commodity in instrument for commodity in ["XAUUSD", "XAGUSD"]):
            if instrument == "XAUUSD":
                return "XAU/USD"
            elif instrument == "XAGUSD":
                return "XAG/USD"
            else:
                return instrument
                
        # Default: return as is
        return instrument

    def get_market_data(self, instrument, timeframe="15min", limit=288, indicators=None):
        """
        Get market data from TwelveData API for technical analysis.
        
        Args:
            instrument (str): The trading instrument symbol (e.g., "EURUSD")
            timeframe (str, optional): The timeframe for the data. Defaults to "15min".
            limit (int, optional): The number of data points to retrieve. Defaults to 288.
            indicators (list, optional): List of indicators to include. Defaults to None.
            
        Returns:
            dict: Market data with standardized field names
        """
        try:
            logger.info(f"Getting market data for {instrument} on {timeframe} timeframe")
            
            # Format symbol for TwelveData API
            formatted_symbol = self._format_symbol(instrument)
            
            # Initialize TwelveData client
            td = TDClient(apikey=self.API_KEY)
            
            # Define which indicators to request
            indicator_params = {
                "ema": {"time_period": [50, 200]},
                "rsi": {"time_period": 14},
                "macd": {"fast_period": 12, "slow_period": 26, "signal_period": 9}
            }
            
            # Create time series object
            ts = td.time_series(
                symbol=formatted_symbol,
                interval=timeframe,
                outputsize=limit,
                timezone="UTC",
                order="desc",
            )
            
            # Add requested indicators
            time_series = ts.with_ema(time_period=50).with_ema(time_period=200).with_rsi().with_macd()
            
            # Get data as pandas DataFrame
            with ThreadPoolExecutor() as executor:
                df_future = asyncio.get_event_loop().run_in_executor(
                    executor, time_series.as_pandas
                )
                
                df = asyncio.run(asyncio.wait_for(df_future, timeout=10.0))
            
            if df is None or df.empty:
                logger.warning(f"No data returned from TwelveData for {instrument}")
                return {"success": False, "error": "No data available", "data": None}
            
            # Extract market data points
            market_data = []
            for index, row in df.iterrows():
                market_data.append({
                    "datetime": index.isoformat(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0))
                })
            
            # Extract latest indicators
            latest = df.iloc[0]  # First row due to 'desc' order
            
            # Create field mapping between TwelveData field names and our expected field names
            field_mapping = {
                "close": "close",
                "open": "open",
                "high": "high",
                "low": "low",
                "volume": "volume",
                "ema1": "EMA50",  # TwelveData names the first EMA as ema1
                "ema2": "EMA200", # TwelveData names the second EMA as ema2
                "rsi": "RSI",
                "macd": "MACD.macd",
                "macd_signal": "MACD.signal",
                "macd_hist": "MACD.hist"
            }
            
            # Calculate weekly high/low
            weekly_high = df["high"].max()
            weekly_low = df["low"].min()
            
            # Extract indicators using the field mapping
            indicators_data = {}
            for td_field, expected_field in field_mapping.items():
                if td_field in latest:
                    indicators_data[expected_field] = float(latest.get(td_field, 0))
            
            # Add weekly high/low
            indicators_data["weekly_high"] = float(weekly_high)
            indicators_data["weekly_low"] = float(weekly_low)
            
            # Calculate trend
            trend = "BUY" if latest["close"] > latest["ema1"] > latest["ema2"] else \
                   "SELL" if latest["close"] < latest["ema1"] < latest["ema2"] else \
                   "NEUTRAL"
            
            # Build the response structure
            response = {
                "success": True,
                "data": {
                    "market_data": market_data,
                    "indicators": indicators_data,
                    "analysis": trend
                },
                "error": None
            }
            
            return response
            
        except Exception as e:
            logger.error(f"Error in get_market_data: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "data": None,
                "error": str(e)
            } 
