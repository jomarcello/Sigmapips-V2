import logging
import traceback
import asyncio
import os
import aiohttp
import json
from typing import Optional, Dict, Any
from collections import namedtuple
import time

logger = logging.getLogger(__name__)

class AllTickProvider:
    """Provider class for AllTick API integration"""
    
    # Base URLs for AllTick API
    BASE_URL = "https://api.alltick.co"
    WS_URL = "wss://ws.alltick.co"
    
    # API token (free tokens available via their website)
    API_TOKEN = os.getenv("ALLTICK_API_TOKEN", "free_token")
    
    # Track API usage
    _last_api_call = 0
    _api_call_count = 0
    _max_calls_per_minute = 30  # Adjust based on AllTick limits
    
    @staticmethod
    async def get_market_data(instrument: str, timeframe: str = "1h") -> Optional[Dict[str, Any]]:
        """
        Get market data from AllTick API for technical analysis.
        
        Args:
            instrument: Trading instrument (e.g., EURUSD, BTCUSD, US500)
            timeframe: Timeframe for analysis (1h, 4h, 1d)
            
        Returns:
            Optional[Dict]: Technical analysis data or None if failed
        """
        try:
            # Implement basic rate limiting
            current_time = time.time()
            minute_passed = current_time - AllTickProvider._last_api_call >= 60
            
            if minute_passed:
                # Reset counter if a minute has passed
                AllTickProvider._api_call_count = 0
                AllTickProvider._last_api_call = current_time
            elif AllTickProvider._api_call_count >= AllTickProvider._max_calls_per_minute:
                # If we hit the rate limit, wait until the minute is up
                logger.warning(f"AllTick API rate limit reached ({AllTickProvider._api_call_count} calls). Waiting before retry.")
                return None
            
            # Increment the API call counter
            AllTickProvider._api_call_count += 1
            
            # Format symbol for AllTick API
            formatted_symbol = AllTickProvider._format_symbol(instrument)
            
            logger.info(f"Fetching {formatted_symbol} data from AllTick. API call #{AllTickProvider._api_call_count} this minute.")
            
            # Map timeframe to AllTick format
            alltick_timeframe = {
                "1m": "1min", 
                "5m": "5min", 
                "15m": "15min", 
                "30m": "30min",
                "1h": "1hour", 
                "4h": "4hour", 
                "1d": "1day",
                "1w": "1week"
            }.get(timeframe, "1hour")
            
            # Prepare API endpoint URL for quotes
            endpoint = f"/api/v1/quote/latest"
            params = {
                "token": AllTickProvider.API_TOKEN,
                "code": formatted_symbol
            }
            
            # Get latest quote
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{AllTickProvider.BASE_URL}{endpoint}", params=params) as response:
                    if response.status != 200:
                        logger.error(f"AllTick API error: {response.status}")
                        return None
                    
                    data = await response.json()
                    if not data or "data" not in data:
                        logger.error(f"AllTick API returned invalid data: {data}")
                        return None
                    
                    quote_data = data["data"]
                    
            # Now get some kline data for technical indicators
            endpoint = f"/api/v1/kline"
            params = {
                "token": AllTickProvider.API_TOKEN,
                "code": formatted_symbol,
                "period": alltick_timeframe,
                "count": 50  # Get enough data for indicators
            }
            
            # Get kline data
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{AllTickProvider.BASE_URL}{endpoint}", params=params) as response:
                    if response.status != 200:
                        logger.error(f"AllTick API error getting klines: {response.status}")
                        return None
                    
                    data = await response.json()
                    if not data or "data" not in data or not data["data"]:
                        logger.error(f"AllTick API returned invalid kline data: {data}")
                        return None
                    
                    kline_data = data["data"]
            
            # Calculate some basic indicators
            close_prices = [float(k["close"]) for k in kline_data]
            
            # Simple moving averages
            ema50 = sum(close_prices[:20]) / min(20, len(close_prices))
            ema200 = sum(close_prices[:50]) / min(50, len(close_prices))
            
            # Basic RSI calculation
            gains = []
            losses = []
            for i in range(1, min(15, len(close_prices))):
                change = close_prices[i-1] - close_prices[i]
                if change >= 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))
            
            avg_gain = sum(gains) / max(1, len(gains))
            avg_loss = sum(losses) / max(1, len(losses))
            
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            
            # Current price is the latest close
            current_price = float(quote_data.get("last", close_prices[0]))
            
            # Structure for compatibility with existing code
            AnalysisResult = namedtuple('AnalysisResult', ['summary', 'indicators', 'oscillators', 'moving_averages'])
            
            # Create indicators dictionary
            indicators = {
                'close': current_price,
                'open': float(quote_data.get("open", current_price)),
                'high': float(quote_data.get("high", current_price)),
                'low': float(quote_data.get("low", current_price)),
                'RSI': rsi,
                'MACD.macd': 0,  # Simple placeholder
                'MACD.signal': 0,  # Simple placeholder
                'MACD.hist': 0,  # Simple placeholder
                'EMA50': ema50,
                'EMA200': ema200,
                'volume': float(quote_data.get("volume", 0)),
                'weekly_high': max(close_prices),
                'weekly_low': min(close_prices)
            }
            
            # Calculate trend based on EMAs
            trend = "BUY" if current_price > ema50 > ema200 else "SELL" if current_price < ema50 < ema200 else "NEUTRAL"
            
            # Create result object compatible with existing code
            analysis = AnalysisResult(
                summary={'recommendation': trend},
                indicators=indicators,
                oscillators={},
                moving_averages={}
            )
            
            return analysis
                
        except Exception as e:
            logger.error(f"Error fetching data from AllTick: {str(e)}")
            logger.error(traceback.format_exc())
            return None
    
    @staticmethod
    def _format_symbol(instrument: str) -> str:
        """Format instrument symbol for AllTick API"""
        instrument = instrument.upper().replace("/", "")
        
        # For cryptocurrencies
        if any(crypto in instrument for crypto in ["BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "LTC", "DOG", "DOT", "XLM"]):
            if instrument.endswith("USD") or instrument.endswith("USDT"):
                # AllTick uses crypto.quote format
                symbol = instrument
                if instrument.endswith("USD") and not instrument.endswith("USDT"):
                    symbol = instrument.replace("USD", "USDT")
                return f"crypto.{symbol}"
            else:
                return f"crypto.{instrument}"
                
        # For forex
        elif len(instrument) == 6 and all(c.isalpha() for c in instrument):
            base = instrument[:3]
            quote = instrument[3:]
            return f"forex.{base}{quote}"
            
        # For commodities
        elif instrument in ["XAUUSD", "XAGUSD"]:
            if instrument == "XAUUSD":
                return "metals.XAUUSD"
            elif instrument == "XAGUSD":
                return "metals.XAGUSD"
                
        # For indices
        elif any(index in instrument for index in ["US30", "US500", "US100", "UK100", "DE40", "JP225"]):
            # Map common indices to AllTick codes
            index_map = {
                "US30": "indices.US30",
                "US500": "indices.SPX500",
                "US100": "indices.NDX100",
                "UK100": "indices.UK100",
                "DE40": "indices.GER40",
                "JP225": "indices.JP225"
            }
            return index_map.get(instrument, f"indices.{instrument}")
                
        # Default: return as is
        return instrument

    def get_market_data(self, instrument, timeframe="1h"):
        """Instance method wrapper around the static method for backward compatibility"""
        return asyncio.run(self.get_market_data(instrument, timeframe)) 
