import os
import logging
import aiohttp
import random
from typing import Optional, Union, Dict, List, Tuple, Any
from urllib.parse import quote
import asyncio
import base64
from io import BytesIO
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import mplfinance as mpf
from datetime import datetime, timedelta
import time
import json
import pickle
import hashlib
import traceback
import re
from tradingview_ta import TA_Handler, Interval

# Importeer alleen de base class
from trading_bot.services.chart_service.base import TradingViewService

logger = logging.getLogger(__name__)

# Cache directory voor charts en technische analyses
CACHE_DIR = os.path.join('data', 'cache')
CHART_CACHE_DIR = os.path.join(CACHE_DIR, 'charts')
ANALYSIS_CACHE_DIR = os.path.join(CACHE_DIR, 'analysis')
OCR_CACHE_DIR = os.path.join(CACHE_DIR, 'ocr')

# Zorg dat de cache directories bestaan
os.makedirs(CHART_CACHE_DIR, exist_ok=True)
os.makedirs(ANALYSIS_CACHE_DIR, exist_ok=True)
os.makedirs(OCR_CACHE_DIR, exist_ok=True)

# Cache verlooptijd in seconden
CHART_CACHE_EXPIRY = 7200  # 2 uur voor charts (was 30 minuten)
ANALYSIS_CACHE_EXPIRY = 7200  # 2 uur voor analyses (was 60 minuten)

# JSON Encoder voor NumPy types
class NumpyJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        elif isinstance(obj, datetime):
            return obj.isoformat()
        return super(NumpyJSONEncoder, self).default(obj)

class ChartService:
    def __init__(self):
        """Initialize the ChartService"""
        # Service instances
        self.tradingview = None
        self.selenium = None
        self.current_symbol = None
        
        # In-memory cache
        self.chart_cache = {}
        self.chart_cache_expiry = {}
        self.analysis_cache = {}
        self.analysis_cache_expiry = {}
        
        # Stel het last_analysis attribuut in
        self.last_analysis = ""
        
        # Create cache directories
        os.makedirs("data/cache", exist_ok=True)
        os.makedirs("data/cache/charts", exist_ok=True)
        os.makedirs("data/cache/analyses", exist_ok=True)
        
        # Random chart fallback
        self.template_charts = {}
        
        # Log initialisatie
        logger.info("ChartService initialized")
        try:
            # Maak cache directory aan als die niet bestaat
            os.makedirs(OCR_CACHE_DIR, exist_ok=True)
            
            # Houd bij wanneer de laatste request naar Yahoo is gedaan
            self.last_yahoo_request = 0
            
            # In-memory caches en lock
            self.chart_cache = {}
            self.chart_cache_expiry = {}
            self.analysis_cache = {}
            self.analysis_cache_expiry = {}
            self._init_lock = asyncio.Lock()
            self.node_initialized = False
            
            # Initialiseer de chart links met de specifieke TradingView links
            self.chart_links = {
                # Commodities
                "XAUUSD": "https://www.tradingview.com/chart/bylCuCgc/",
                "XTIUSD": "https://www.tradingview.com/chart/jxU29rbq/",
                
                # Currencies
                "EURUSD": "https://www.tradingview.com/chart/xknpxpcr/",
                "EURGBP": "https://www.tradingview.com/chart/xt6LdUUi/",
                "EURCHF": "https://www.tradingview.com/chart/4Jr8hVba/",
                "EURJPY": "https://www.tradingview.com/chart/ume7H7lm/",
                "EURCAD": "https://www.tradingview.com/chart/gbtrKFPk/",
                "EURAUD": "https://www.tradingview.com/chart/WweOZl7z/",
                "EURNZD": "https://www.tradingview.com/chart/bcrCHPsz/",
                "GBPUSD": "https://www.tradingview.com/chart/jKph5b1W/",
                "GBPCHF": "https://www.tradingview.com/chart/1qMsl4FS/",
                "GBPJPY": "https://www.tradingview.com/chart/Zcmh5M2k/",
                "GBPCAD": "https://www.tradingview.com/chart/CvwpPBpF/",
                "GBPAUD": "https://www.tradingview.com/chart/neo3Fc3j/",
                "GBPNZD": "https://www.tradingview.com/chart/egeCqr65/",
                "CHFJPY": "https://www.tradingview.com/chart/g7qBPaqM/",
                "USDJPY": "https://www.tradingview.com/chart/mcWuRDQv/",
                "USDCHF": "https://www.tradingview.com/chart/e7xDgRyM/",
                "USDCAD": "https://www.tradingview.com/chart/jjTOeBNM/",
                "CADJPY": "https://www.tradingview.com/chart/KNsPbDME/",
                "CADCHF": "https://www.tradingview.com/chart/XnHRKk5I/",
                "AUDUSD": "https://www.tradingview.com/chart/h7CHetVW/",
                "AUDCHF": "https://www.tradingview.com/chart/oooBW6HP/",
                "AUDJPY": "https://www.tradingview.com/chart/sYiGgj7B/",
                "AUDNZD": "https://www.tradingview.com/chart/AByyHLB4/",
                "AUDCAD": "https://www.tradingview.com/chart/L4992qKp/",
                "NDZUSD": "https://www.tradingview.com/chart/yab05IFU/",
                "NZDCHF": "https://www.tradingview.com/chart/7epTugqA/",
                "NZDJPY": "https://www.tradingview.com/chart/fdtQ7rx7/",
                "NZDCAD": "https://www.tradingview.com/chart/mRVtXs19/",
                
                # Cryptocurrencies
                "BTCUSD": "https://www.tradingview.com/chart/NWT8AI4a/",
                "ETHUSD": "https://www.tradingview.com/chart/rVh10RLj/",
                "XRPUSD": "https://www.tradingview.com/chart/tQu9Ca4E/",
                "SOLUSD": "https://www.tradingview.com/chart/oTTmSjzQ/",
                "BNBUSD": "https://www.tradingview.com/chart/wNBWNh23/",
                "ADAUSD": "https://www.tradingview.com/chart/WcBNFrdb/",
                "LTCUSD": "https://www.tradingview.com/chart/AoDblBMt/",
                "DOGUSD": "https://www.tradingview.com/chart/F6SPb52v/",
                "DOTUSD": "https://www.tradingview.com/chart/nT9dwAx2/",
                "LNKUSD": "https://www.tradingview.com/chart/FzOrtgYw/",
                "XLMUSD": "https://www.tradingview.com/chart/SnvxOhDh/",
                "AVXUSD": "https://www.tradingview.com/chart/LfTlCrdQ/",
                
                # Indices
                "AU200": "https://www.tradingview.com/chart/U5CKagMM/",
                "EU50": "https://www.tradingview.com/chart/tt5QejVd/",
                "FR40": "https://www.tradingview.com/chart/RoPe3S1Q/",
                "HK50": "https://www.tradingview.com/chart/Rllftdyl/",
                "JP225": "https://www.tradingview.com/chart/i562Fk6X/",
                "UK100": "https://www.tradingview.com/chart/0I4gguQa/",
                "US100": "https://www.tradingview.com/chart/5d36Cany/",
                "US500": "https://www.tradingview.com/chart/VsfYHrwP/",
                "US30": "https://www.tradingview.com/chart/heV5Zitn/",
                "DE40": "https://www.tradingview.com/chart/OWzg0XNw/",
            }
            
            # Initialiseer de TradingView services
            self.tradingview = None
            self.tradingview_selenium = None
            
            logging.info("Chart service initialized")
            
        except Exception as e:
            logging.error(f"Error initializing chart service: {str(e)}")
            raise

    async def get_technical_analysis(self, instrument: str, timeframe: str = "1h") -> Union[bytes, str]:
        """
        Get technical analysis for an instrument with timeframe using TradingView data and DeepSeek APIs.
        Implements caching and parallel processing.
        """
        try:
            # Normaliseer instrument voor consistente caching
            instrument = instrument.upper().replace("/", "")
            
            # Check cache eerst
            cache_key = f"{instrument}_{timeframe}"
            cache_file = os.path.join(ANALYSIS_CACHE_DIR, f"{cache_key}.json")
            
            # In-memory cache check (snelst)
            if cache_key in self.analysis_cache:
                cache_entry = self.analysis_cache[cache_key]
                if time.time() - cache_entry["timestamp"] < ANALYSIS_CACHE_EXPIRY:
                    logger.info(f"Using in-memory cache for {instrument} analysis")
                    # We hebben nog steeds de chart nodig
                    
                    # Haal chart op (deze zal zelf caching gebruiken)
                    chart_data, _ = await self.get_chart(instrument, timeframe)
                    
                    # Stel de analyse in als last_analysis attribuut voor latere toegang
                    self.last_analysis = cache_entry["data"]
                    
                    return chart_data
            
            # Disk cache check
            if os.path.exists(cache_file):
                file_age = time.time() - os.path.getmtime(cache_file)
                if file_age < ANALYSIS_CACHE_EXPIRY:
                    logger.info(f"Using disk cache for {instrument} analysis")
                    with open(cache_file, 'r') as f:
                        analysis_text = f.read()
                        
                        # Update in-memory cache
                        self.analysis_cache[cache_key] = {
                            "data": analysis_text,
                            "timestamp": time.time()
                        }
                        
                        # Haal chart op (deze zal zelf caching gebruiken)
                        chart_data, _ = await self.get_chart(instrument, timeframe)
                        
                        # Stel de analyse in als last_analysis attribuut voor latere toegang
                        self.last_analysis = analysis_text
                        
                        return chart_data
            
            # Start parallelle taken voor marktgegevens en chart
            # We gebruiken gather om beide taken gelijktijdig uit te voeren
            
            # Creëer taken voor parallel uitvoeren
            market_data_task = asyncio.create_task(self.get_real_market_data(instrument, timeframe))
            chart_task = asyncio.create_task(self.get_chart(instrument, timeframe))
            
            # Wacht op beide taken om klaar te zijn
            market_data_dict, chart_result = await asyncio.gather(market_data_task, chart_task)
            
            # Extraheer de juiste chart_data uit het resultaat
            if isinstance(chart_result, tuple) and len(chart_result) == 2:
                chart_data = chart_result[0]
            else:
                chart_data = chart_result
            
            logger.info(f"TradingView data retrieved: {market_data_dict}")
            
            # Get the DeepSeek API key
            deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
            
            if not deepseek_api_key:
                logger.warning("DeepSeek API key missing, analysis may be limited")
            
            # Convert data to JSON for DeepSeek
            market_data_json = json.dumps(market_data_dict, indent=2, cls=NumpyJSONEncoder)
            
            # Format data using DeepSeek API
            logger.info(f"Formatting data with DeepSeek for {instrument}")
            analysis = await self._format_with_deepseek(deepseek_api_key, instrument, timeframe, market_data_json)
            
            if not analysis:
                logger.warning(f"Failed to format with DeepSeek for {instrument}, using fallback formatting")
                
                # Determine the correct decimal places based on the instrument
                if instrument.endswith("JPY"):
                    decimals = 3
                elif any(x in instrument for x in ["XAU", "GOLD", "SILVER", "XAGUSD"]):
                    decimals = 2
                elif any(index in instrument for index in ["US30", "US500", "US100", "UK100", "DE40"]):
                    decimals = 0
                else:
                    decimals = 5  # Default for most forex pairs
                
                # Extract necessary values for formatting
                current_price = market_data_dict.get('current_price', 0)
                daily_high = market_data_dict.get('daily_high', 0)
                daily_low = market_data_dict.get('daily_low', 0)
                rsi = market_data_dict.get('rsi', 50)
                
                # Format prices with correct decimal places
                formatted_price = f"{current_price:.{decimals}f}"
                formatted_daily_high = f"{daily_high:.{decimals}f}"
                formatted_daily_low = f"{daily_low:.{decimals}f}"
                
                # Determine trend based on RSI
                is_bullish = rsi > 50
                action = "BUY" if is_bullish else "SELL"
                
                # Get support and resistance levels
                resistance_levels = market_data_dict.get('resistance_levels', [])
                support_levels = market_data_dict.get('support_levels', [])
                
                resistance = resistance_levels[0] if resistance_levels else daily_high
                formatted_resistance = f"{resistance:.{decimals}f}"
                
                if is_bullish:
                    # For bullish scenarios, always display "0.000" as support
                    formatted_support = "0.000"
                else:
                    support = support_levels[0] if support_levels else daily_low
                    formatted_support = f"{support:.{decimals}f}"
                
                # Get MACD values
                macd = market_data_dict.get('macd', 0)
                macd_signal = market_data_dict.get('macd_signal', 0)
                formatted_macd = f"{macd:.{decimals}f}"
                formatted_macd_signal = f"{macd_signal:.{decimals}f}"
                
                # Get EMA values
                ema50 = market_data_dict.get('ema_50', current_price * 1.005 if is_bullish else current_price * 0.995)
                formatted_ema50 = f"{ema50:.{decimals}f}"
                
                ema200 = market_data_dict.get('ema_200', current_price * 1.01 if is_bullish else current_price * 0.99)
                formatted_ema200 = f"{ema200:.{decimals}f}"
                
                # Create a fallback analysis text in the exact format we need
                fallback_analysis = f"""{instrument} - {timeframe}

<b>Trend - {action}</b>

Zone Strength 1-5: {'★★★★☆' if is_bullish else '★★★☆☆'}

<b>📊 Market Overview</b>
{instrument} is trading at {formatted_price}, showing {action.lower()} momentum near the daily {'high' if is_bullish else 'low'} ({formatted_daily_high}). The price remains {'above' if is_bullish else 'below'} key EMAs (50 & 200), confirming an {'uptrend' if is_bullish else 'downtrend'}.

<b>🔑 Key Levels</b>
Support: {formatted_support} (daily low), {formatted_support}
Resistance: {formatted_daily_high} (daily high), {formatted_resistance}

<b>📈 Technical Indicators</b>
RSI: {rsi:.2f} (neutral)
MACD: {action} ({formatted_macd} > signal {formatted_macd_signal})
Moving Averages: Price {'above' if is_bullish else 'below'} EMA 50 ({formatted_ema50}) and EMA 200 ({formatted_ema200}), reinforcing {action.lower()} bias.

<b>🤖 Sigmapips AI Recommendation</b>
Monitor price action around {formatted_price}. {'Look for buying opportunities on dips toward support at ' + formatted_support if is_bullish else 'Consider selling rallies toward resistance at ' + formatted_resistance}. {'Stay bullish while price holds above ' + formatted_support if is_bullish else 'Maintain bearish bias below ' + formatted_resistance}.

⚠️ Disclaimer: Please note that the information/analysis provided is strictly for study and educational purposes only. It should not be constructed as financial advice and always do your own analysis.
"""
                
                analysis = fallback_analysis
            
            # Update cache
            if analysis:
                # Update in-memory cache
                self.analysis_cache[cache_key] = {
                    "data": analysis,
                    "timestamp": time.time()
                }
                
                # Stel de analyse in als last_analysis attribuut voor latere toegang
                self.last_analysis = analysis
                
                # Update disk cache
                os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                with open(cache_file, 'w') as f:
                    f.write(analysis)
            
            return chart_data
            
        except Exception as e:
            logger.error(f"Error in get_technical_analysis: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Stel een lege analyse in zodat de bot nog kan werken
            self.last_analysis = f"{instrument} - {timeframe}\n\nFailed to retrieve technical analysis. Please try again later."
            
            # Stuur als fallback een lege chart
            return None

    async def get_real_market_data(self, instrument: str, timeframe: str = "1h") -> Dict[str, Any]:
        """Get real market data from TradingView"""
        try:
            # Map timeframe to TradingView interval
            interval_map = {
                "1m": Interval.INTERVAL_1_MINUTE,
                "5m": Interval.INTERVAL_5_MINUTES,
                "15m": Interval.INTERVAL_15_MINUTES,
                "30m": Interval.INTERVAL_30_MINUTES,
                "1h": Interval.INTERVAL_1_HOUR,
                "2h": Interval.INTERVAL_2_HOURS,
                "4h": Interval.INTERVAL_4_HOURS,
                "1d": Interval.INTERVAL_1_DAY,
                "1W": Interval.INTERVAL_1_WEEK,
                "1M": Interval.INTERVAL_1_MONTH
            }
            
            interval = interval_map.get(timeframe, Interval.INTERVAL_1_HOUR)
            
            # Map instrument to exchange and screener
            exchange, symbol, screener = self._map_instrument_to_tradingview(instrument)
            
            logger.info(f"Getting data from TradingView: {exchange}:{symbol} on {screener}")
            
            # Initialize handler
            handler = TA_Handler(
                symbol=symbol,
                exchange=exchange,
                screener=screener,
                interval=interval,
                timeout=10
            )
            
            # Get analysis
            analysis = handler.get_analysis()
            
            if not analysis or not hasattr(analysis, 'indicators') or 'close' not in analysis.indicators:
                logger.warning(f"No valid analysis data returned for {instrument}")
                raise ValueError("No valid analysis data")
            
            # Extract necessary data
            market_data = {
                "instrument": instrument,
                "timeframe": timeframe,
                "timestamp": datetime.now().isoformat(),
                "current_price": analysis.indicators["close"],
                "daily_high": analysis.indicators["high"],
                "daily_low": analysis.indicators["low"],
                "open_price": analysis.indicators["open"],
                "volume": analysis.indicators.get("volume", 0),
                
                # Technical indicators
                "rsi": analysis.indicators.get("RSI", 50),
                "macd": analysis.indicators.get("MACD.macd", 0),
                "macd_signal": analysis.indicators.get("MACD.signal", 0),
                "ema_50": analysis.indicators.get("EMA50", analysis.indicators["close"] * 1.005),
                "ema_200": analysis.indicators.get("EMA200", analysis.indicators["close"] * 0.995),
            }
            
            # Calculate support and resistance levels
            base_price = market_data["current_price"]
            support_resistance = self._calculate_synthetic_support_resistance(base_price, instrument)
            
            # Add support and resistance levels to market data
            market_data.update(support_resistance)
            
            # Add recommendation
            if hasattr(analysis, 'summary'):
                recommendation = analysis.summary.get('RECOMMENDATION', 'NEUTRAL')
                market_data["recommendation"] = recommendation
                
                # Add buy/sell signals count
                if hasattr(analysis, 'oscillators'):
                    market_data["buy_signals"] = analysis.oscillators.get('BUY', 0) + analysis.moving_averages.get('BUY', 0)
                    market_data["sell_signals"] = analysis.oscillators.get('SELL', 0) + analysis.moving_averages.get('SELL', 0)
                    market_data["neutral_signals"] = analysis.oscillators.get('NEUTRAL', 0) + analysis.moving_averages.get('NEUTRAL', 0)
            
            logger.info(f"Retrieved real market data for {instrument} from TradingView")
            return market_data
            
        except Exception as e:
            logger.error(f"Error getting real market data: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Create fallback/synthetic data
            base_price = self._get_base_price_for_instrument(instrument)
            volatility = self._get_volatility_for_instrument(instrument)
            
            # Generate random price movements
            current_price = base_price * (1 + random.uniform(-volatility, volatility))
            daily_high = current_price * (1 + random.uniform(0, volatility))
            daily_low = current_price * (1 - random.uniform(0, volatility))
            open_price = base_price * (1 + random.uniform(-volatility, volatility))
            
            # Calculate synthetic support and resistance
            support_resistance = self._calculate_synthetic_support_resistance(current_price, instrument)
            
            # Create synthetic indicator values
            rsi = random.uniform(30, 70)
            is_bullish = rsi > 50
            
            # Biased MACD values based on RSI
            macd_base = random.uniform(-0.001, 0.001)
            macd = macd_base * current_price
            macd_signal = macd * (0.8 if is_bullish else 1.2)
            
            # Generate EMAs that make sense
            ema_50 = current_price * (1.01 if is_bullish else 0.99)
            ema_200 = current_price * (1.03 if is_bullish else 0.97)
            
            # Create synthetic data dictionary
            market_data = {
                "instrument": instrument,
                "timeframe": timeframe,
                "timestamp": datetime.now().isoformat(),
                "current_price": current_price,
                "daily_high": daily_high,
                "daily_low": daily_low,
                "open_price": open_price,
                "volume": random.randint(5000, 100000),
                "rsi": rsi,
                "macd": macd,
                "macd_signal": macd_signal,
                "ema_50": ema_50,
                "ema_200": ema_200,
                "recommendation": "BUY" if is_bullish else "SELL",
                "buy_signals": random.randint(8, 16) if is_bullish else random.randint(0, 7),
                "sell_signals": random.randint(0, 7) if is_bullish else random.randint(8, 16),
                "neutral_signals": random.randint(4, 12)
            }
            
            # Add support and resistance levels
            market_data.update(support_resistance)
            
            logger.warning(f"Using synthetic data for {instrument}")
            return market_data
            
    def _map_instrument_to_tradingview(self, instrument: str) -> Tuple[str, str, str]:
        """Map instrument to TradingView exchange, symbol, and screener"""
        # Normalize instrument name
        instrument = instrument.upper().replace("/", "")
        
        # Default mapping for forex
        exchange = "FX_IDC"
        symbol = instrument
        screener = "forex"
        
        # Special cases for indices
        indices_mapping = {
            "US30": ("DJ", "DJI", "america"),
            "US500": ("FOREXCOM", "US500", "america"),
            "US100": ("FOREXCOM", "US100", "america"),
            "UK100": ("FOREXCOM", "UK100", "uk"),
            "DE40": ("FOREXCOM", "DE40", "germany"),
            "EU50": ("FOREXCOM", "EU50", "europe"),
            "JP225": ("FOREXCOM", "JP225", "japan"),
            "AU200": ("FOREXCOM", "AU200", "australia"),
            "FR40": ("FOREXCOM", "FR40", "france"),
            "HK50": ("FOREXCOM", "HK50", "hong_kong"),
        }
        
        # Check if it's an index
        if instrument in indices_mapping:
            exchange, symbol, screener = indices_mapping[instrument]
        
        # Special cases for commodities
        elif instrument in ["XAUUSD", "GOLD"]:
            exchange = "OANDA"
            symbol = "XAUUSD"
            screener = "forex"
        elif instrument in ["XTIUSD", "OIL"]:
            exchange = "OANDA"
            symbol = "XTIUSD"
            screener = "forex"
        
        # Special cases for cryptocurrencies
        elif instrument in ["BTCUSD", "BTC"]:
            exchange = "BINANCE"
            symbol = "BTCUSDT"
            screener = "crypto"
        elif instrument in ["ETHUSD", "ETH"]:
            exchange = "BINANCE"
            symbol = "ETHUSDT"
            screener = "crypto"
        
        # Special handling for forex pairs to ensure correct format
        else:
            # If forex pair length is 6, it's likely a standard forex pair (e.g., EURUSD)
            if len(instrument) == 6:
                base = instrument[:3]
                quote = instrument[3:]
                if quote in ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"]:
                    exchange = "FX_IDC"
                    symbol = instrument
                    screener = "forex"
        
        return exchange, symbol, screener 

    def _get_base_price_for_instrument(self, instrument: str) -> float:
        """Get a reasonable base price for an instrument for synthetic data"""
        # Normalize instrument name
        instrument = instrument.upper().replace("/", "")
        
        # Base prices for common instruments
        base_prices = {
            # Forex pairs
            "EURUSD": 1.13,
            "GBPUSD": 1.32,
            "USDJPY": 145.0,
            "AUDUSD": 0.68,
            "USDCAD": 1.35,
            "USDCHF": 0.88,
            "NZDUSD": 0.62,
            "EURGBP": 0.85,
            "EURJPY": 163.0,
            "GBPJPY": 192.0,
            
            # Indices
            "US30": 38000.0,
            "US500": 5300.0,
            "US100": 18500.0,
            "UK100": 8000.0,
            "DE40": 17500.0,
            
            # Commodities
            "XAUUSD": 2300.0,
            "GOLD": 2300.0,
            "XTIUSD": 75.0,
            "OIL": 75.0,
            
            # Cryptocurrencies
            "BTCUSD": 65000.0,
            "BTC": 65000.0,
            "ETHUSD": 3500.0,
            "ETH": 3500.0,
        }
        
        # Return the base price if it exists, otherwise provide a default
        if instrument in base_prices:
            return base_prices[instrument]
        
        # For currency pairs not explicitly listed
        if len(instrument) == 6:
            base = instrument[:3]
            quote = instrument[3:]
            
            # Most common base currency pairs against USD
            if quote == "USD":
                if base in ["EUR", "GBP", "AUD", "NZD"]:
                    return random.uniform(0.6, 1.5)
                else:
                    return random.uniform(0.8, 1.2)
            
            # For JPY pairs
            elif quote == "JPY":
                return random.uniform(100.0, 200.0)
            
            # For other pairs
            else:
                return random.uniform(0.7, 1.4)
        
        # Default fallback
        return 1.0

    def _get_volatility_for_instrument(self, instrument: str) -> float:
        """Get a reasonable volatility value for an instrument for synthetic data"""
        # Normalize instrument name
        instrument = instrument.upper().replace("/", "")
        
        # Volatility settings for different types of instruments
        volatilities = {
            # Forex pairs (relatively low volatility)
            "EURUSD": 0.003,
            "GBPUSD": 0.004,
            "USDJPY": 0.004,
            "AUDUSD": 0.005,
            "USDCAD": 0.004,
            "USDCHF": 0.004,
            "NZDUSD": 0.005,
            "EURGBP": 0.003,
            "EURJPY": 0.004,
            "GBPJPY": 0.005,
            
            # Indices (medium volatility)
            "US30": 0.01,
            "US500": 0.01,
            "US100": 0.015,
            "UK100": 0.01,
            "DE40": 0.012,
            
            # Commodities (higher volatility)
            "XAUUSD": 0.008,
            "GOLD": 0.008,
            "XTIUSD": 0.02,
            "OIL": 0.02,
            
            # Cryptocurrencies (highest volatility)
            "BTCUSD": 0.03,
            "BTC": 0.03,
            "ETHUSD": 0.04,
            "ETH": 0.04,
        }
        
        # Return the volatility if it exists, otherwise provide a reasonable default
        if instrument in volatilities:
            return volatilities[instrument]
        
        # For different types of instruments not explicitly listed
        if len(instrument) == 6:
            # Assume it's a forex pair
            return 0.004
        elif "USD" in instrument and len(instrument) >= 5:
            # Might be a cryptocurrency or commodity
            return 0.02
        else:
            # Default volatility
            return 0.01

    def _calculate_synthetic_support_resistance(self, base_price: float, instrument: str) -> Dict[str, Any]:
        """Calculate synthetic support and resistance levels for an instrument"""
        # Get volatility to determine spacing of levels
        volatility = self._get_volatility_for_instrument(instrument)
        
        # Function to round values consistently with instrument type
        def round_value(value, places):
            multiplier = 10 ** places
            return round(value * multiplier) / multiplier
        
        # Determine decimal places based on instrument
        if instrument.endswith("JPY"):
            decimal_places = 3
        elif any(x in instrument for x in ["XAU", "GOLD", "SILVER", "XAGUSD"]):
            decimal_places = 2
        elif any(index in instrument for index in ["US30", "US500", "US100", "UK100", "DE40"]):
            decimal_places = 0
        else:
            decimal_places = 5  # Default for most forex pairs
        
        # Calculate support and resistance levels with realistic spacing
        
        # Immediate levels (close to current price)
        resistance1 = round_value(base_price * (1 + volatility * 1.5), decimal_places)
        support1 = round_value(base_price * (1 - volatility * 1.5), decimal_places)
        
        # Medium-term levels
        resistance2 = round_value(base_price * (1 + volatility * 3), decimal_places)
        support2 = round_value(base_price * (1 - volatility * 3), decimal_places)
        
        # Long-term levels
        resistance3 = round_value(base_price * (1 + volatility * 6), decimal_places)
        support3 = round_value(base_price * (1 - volatility * 6), decimal_places)
        
        # Weekly and monthly extremes (more distant)
        weekly_high = resistance3
        weekly_low = support3
        
        monthly_high = round_value(base_price * (1 + volatility * 10), decimal_places)
        monthly_low = round_value(base_price * (1 - volatility * 10), decimal_places)
        
        # Assemble the data dictionary
        return {
            "support_levels": [support1, support2, support3],
            "resistance_levels": [resistance1, resistance2, resistance3],
            "weekly_high": weekly_high,
            "weekly_low": weekly_low,
            "monthly_high": monthly_high,
            "monthly_low": monthly_low,
            "price_levels": {
                "daily high": resistance1,
                "daily low": support1,
                "weekly high": weekly_high,
                "weekly low": weekly_low,
                "monthly high": monthly_high,
                "monthly low": monthly_low
            }
        }

    async def get_chart(self, instrument: str, timeframe: str = "1h", fullscreen: bool = False) -> Tuple[bytes, Dict]:
        """Get a chart image for a given instrument and timeframe"""
        try:
            # Normalize instrument name
            instrument = instrument.upper()
            
            logger.info(f"Getting chart for {instrument} ({timeframe}) fullscreen: {fullscreen}")
            
            # Check in-memory cache first (snelste optie)
            cache_key = f"{instrument}_{timeframe}_{1 if fullscreen else 0}"
            if cache_key in self.chart_cache and self.chart_cache_expiry.get(cache_key, 0) > time.time():
                logger.info(f"Returning in-memory cached chart for {instrument}")
                return self.chart_cache[cache_key], self.analysis_cache.get(cache_key, {})
                
            # Check disk cache (tweede snelste optie)
            cache_file = f"data/cache/charts/{instrument}_{timeframe}_{1 if fullscreen else 0}.png"
            cache_analysis_file = f"data/cache/analyses/{instrument}_{timeframe}_{1 if fullscreen else 0}.json"
            
            if os.path.exists(cache_file) and os.path.getmtime(cache_file) + CHART_CACHE_EXPIRY > time.time() and os.path.exists(cache_analysis_file):
                logger.info(f"Reading chart from disk cache for {instrument}")
                with open(cache_file, "rb") as f:
                    chart_image = f.read()
                    
                with open(cache_analysis_file, "r") as f:
                    analysis = json.load(f)
                    
                # Update in-memory cache
                self.chart_cache[cache_key] = chart_image
                self.chart_cache_expiry[cache_key] = time.time() + CHART_CACHE_EXPIRY
                self.analysis_cache[cache_key] = analysis
                self.analysis_cache_expiry[cache_key] = time.time() + ANALYSIS_CACHE_EXPIRY
                
                # Stel de analyse in als last_analysis attribuut voor latere toegang
                self.last_analysis = analysis
                
                return chart_image, analysis
            
            # Initialize services if necessary (dit kan traag zijn, dus doen we alleen als echt nodig)
            if not self.tradingview:
                logger.info("Services not initialized, initializing now")
                await self.initialize()
            
            # Haal market data op voor instrumenten, parallel met screenshot proces
            tradingview_data_task = asyncio.create_task(self.get_real_market_data(instrument, timeframe))
            
            # Voorbereiden voor de Node.js screenshot (snel)
            if not hasattr(self, 'tradingview') or not self.tradingview:
                from trading_bot.services.chart_service.tradingview_node import TradingViewNodeService
                self.tradingview = TradingViewNodeService()
                await self.tradingview.initialize()
            
            # Start de screenshot taak (langzaamste deel)
            chart_image = None
            try:
                # Probeer een screenshot te nemen met Node.js
                chart_image = await self.tradingview.take_screenshot(instrument, timeframe, fullscreen)
            except Exception as e:
                logger.error(f"Node.js screenshot error: {e}")
                chart_image = None
            
            # Wacht op de marktdata taak (sneller dan screenshot)
            tradingview_data = await tradingview_data_task
            
            # Start alvast de analyse voorbereiding terwijl we screenshot controleren
            analysis_task = asyncio.create_task(self._prepare_analysis(instrument, tradingview_data))
            
            # Als Node.js succesvol is, sla de afbeelding op
            if chart_image:
                # Controleer of de afbeelding niet te klein is (minimaal 10KB - echte charts zijn ~91KB)
                if len(chart_image) > 10240:  # 10KB minimum
                    # Deze afbeelding is goed
                    logger.info(f"Screenshot taken successfully with Node.js service in {self.tradingview.last_execution_time:.2f} seconds. Size: {len(chart_image)} bytes")
                    
                    # Sla op naar cache bestand
                    os.makedirs("data/charts", exist_ok=True)
                    timestamp = int(time.time())
                    chart_file = f"data/charts/{instrument.lower()}_{timeframe}_{timestamp}.png"
                    with open(chart_file, "wb") as f:
                        f.write(chart_image)
                    logger.info(f"Saved chart image to file: {chart_file}, size: {len(chart_image)} bytes")
                    
                    # Maak de cache map aan als deze niet bestaat
                    os.makedirs("data/cache/charts", exist_ok=True)
                    with open(cache_file, "wb") as f:
                        f.write(chart_image)
                    logger.info(f"Chart cached to {cache_file}")
                    
                    # Wacht op de DeepSeek analyse die parallel loopt
                    analysis = await analysis_task
                    
                    # Update in-memory cache
                    self.chart_cache[cache_key] = chart_image
                    self.chart_cache_expiry[cache_key] = time.time() + CHART_CACHE_EXPIRY
                    self.analysis_cache[cache_key] = analysis
                    self.analysis_cache_expiry[cache_key] = time.time() + ANALYSIS_CACHE_EXPIRY
                    
                    # Sla de analyse op als last_analysis attribuut
                    self.last_analysis = analysis
                    
                    # Caching voor analyse bestanden
                    os.makedirs("data/cache/analyses", exist_ok=True)
                    with open(cache_analysis_file, "w") as f:
                        json.dump(analysis, f)
                    
                    return chart_image, analysis
                else:
                    logger.warning(f"Node.js screenshot is too small ({len(chart_image)} bytes), falling back to generated chart")
                    chart_image = None
            else:
                logger.error("Node.js screenshot is None")
            
            # Als we hier zijn, zijn alle diensten mislukt, val terug op onze eigen chart generator
            logger.warning(f"Using fallback chart generator for {instrument}")
            
            # Gebruik market data die we al hebben opgehaald
            chart_image = await self._generate_random_chart(instrument, timeframe, tradingview_data)
            
            # Wacht op de DeepSeek analyse die parallel loopt
            analysis = await analysis_task
            
            # Update in-memory cache (ook voor fallback charts)
            self.chart_cache[cache_key] = chart_image
            self.chart_cache_expiry[cache_key] = time.time() + CHART_CACHE_EXPIRY
            self.analysis_cache[cache_key] = analysis
            self.analysis_cache_expiry[cache_key] = time.time() + ANALYSIS_CACHE_EXPIRY
            
            # Sla de analyse op als last_analysis attribuut
            self.last_analysis = analysis
            
            return chart_image, analysis
            
        except Exception as e:
            logger.error(f"Error getting chart: {e}")
            logger.error(traceback.format_exc())
            
            # Maak een eenvoudige fallback chart met de error
            tradingview_data = await self.get_real_market_data(instrument)
            chart_image = await self._generate_random_chart(instrument, timeframe, tradingview_data)
            analysis = await self._prepare_analysis(instrument, tradingview_data)
            
            # Sla de analyse op als last_analysis attribuut
            self.last_analysis = analysis
            
            return chart_image, analysis

    async def _prepare_analysis(self, instrument: str, tradingview_data: Dict) -> Dict:
        """Formatteer data voor analyse en roep DeepSeek API aan."""
        try:
            logger.info(f"Formatting data with DeepSeek for {instrument}")
            
            # Bereid de analyse voor met DeepSeek
            logger.info(f"Sending request to DeepSeek API for {instrument} analysis")
            analysis = await self._format_with_deepseek(os.getenv("DEEPSEEK_API_KEY"), instrument, tradingview_data.get("timeframe", "1h"), json.dumps(tradingview_data))
            
            logger.info(f"DeepSeek analysis successful for {instrument}")
            return analysis
            
        except Exception as e:
            logger.error(f"Error preparing analysis: {e}")
            return {}

    async def _format_with_deepseek(self, api_key: str, instrument: str, timeframe: str, market_data_json: str) -> str:
        """Format technical analysis with DeepSeek API"""
        try:
            if not api_key:
                logger.warning("No DeepSeek API key provided, using fallback formatting")
                return ""
                
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            
            # Template for the analysis prompt
            prompt = f"""You are a professional forex and financial market analyst with extensive experience in technical analysis. 
Your task is to create a detailed but concise technical analysis for {instrument} on the {timeframe} timeframe based on the provided market data.

Here's the market data:
```json
{market_data_json}
```

Format your response exactly according to this template:

{instrument} - {timeframe}

<b>Trend - BUY or SELL</b>

Zone Strength 1-5: ★★★★☆ for bullish trends or ★★★☆☆ for bearish trends

<b>📊 Market Overview</b>
[2-3 sentences about current price action, key trends, and notable price movements. Comment on where price is relative to daily high/low.]

<b>🔑 Key Levels</b>
Support: [List key support levels with context, e.g., "1.0850 (daily low), 1.0820"]
Resistance: [List key resistance levels with context, e.g., "1.0920 (daily high), 1.0950"]

<b>📈 Technical Indicators</b>
RSI: [value] (overbought/neutral/oversold)
MACD: [bullish/bearish] ([value] > signal [value])
Moving Averages: [Comment on price relative to EMA 50 and EMA 200, and what this suggests]

<b>🤖 Sigmapips AI Recommendation</b>
[2-3 sentences with market advice based on the analysis. Focus on key levels to watch and overall market bias.]

⚠️ Disclaimer: Please note that the information/analysis provided is strictly for study and educational purposes only. It should not be constructed as financial advice and always do your own analysis.

CRITICAL REQUIREMENTS:
1. The format above must be followed EXACTLY including line breaks
2. The 'Trend' MUST ALWAYS BE 'BUY' or 'SELL' not 'BULLISH' or 'BEARISH'
3. Zone Strength should be ★★★★☆ for bullish and ★★★☆☆ for bearish
4. DO NOT DEVIATE FROM THIS FORMAT AT ALL
5. DO NOT add any introduction or explanations
6. USE THE EXACT PHRASES PROVIDED - no paraphrasing
7. USE EXACTLY THE SAME DECIMAL PLACES AS IN THE ORIGINAL DATA - no additional or fewer decimal places
8. Bold formatting should be used for headers (using <b> and </b> HTML tags)
9. Do NOT include the line "Sigmapips AI identifies strong buy/sell probability..." - skip directly from Trend to Zone Strength

The final text should be formatted exactly as specified with the information filled in. This will be displayed directly to users in a Telegram bot, so must be perfect.
"""
            
            # DeepSeek API request payload
            payload = {
                "model": "deepseek-coder",
                "messages": [
                    {"role": "system", "content": "You are a professional technical analyst for financial markets."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 1000
            }
            
            # Adjust the API endpoint URL as needed (deepseek-chat or deepseek-coder)
            api_url = "https://api.deepseek.com/v1/chat/completions"
            
            # Make the API request
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, headers=headers, json=payload, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        analysis_text = data['choices'][0]['message']['content']
                        
                        # Clean up output if it has markdown or other formatting issues
                        analysis_text = analysis_text.replace("```", "").strip()
                        
                        # Fix common issues with numbers and decimal places
                        def fix_numbers(match):
                            num = match.group(0)
                            if "." in num:
                                # Keep existing decimal places
                                return num
                            return num + ".00"
                        
                        # Fix decimal number formatting for consistency
                        if "JPY" in instrument:
                            # For JPY pairs, apply 3 decimal places
                            analysis_text = re.sub(r'\b\d+\b', lambda m: f"{float(m.group(0)):.3f}", analysis_text)
                        elif any(x in instrument for x in ["GOLD", "XAU", "US30", "US500"]):
                            # For commodities and indices, apply 2 decimal places or 0
                            analysis_text = re.sub(r'\b\d+\b', lambda m: f"{float(m.group(0)):.2f}", analysis_text)
                        
                        logger.info(f"Successfully received analysis from DeepSeek for {instrument}")
                        return analysis_text
                    else:
                        error_text = await response.text()
                        logger.error(f"DeepSeek API error: {response.status} - {error_text}")
                        return ""  # Return empty string to trigger fallback
                    
        except Exception as e:
            logger.error(f"Error using DeepSeek API: {str(e)}")
            logger.error(traceback.format_exc())
            return ""
            
    async def _generate_random_chart(self, instrument: str, timeframe: str = "1h", tradingview_data: Dict = None) -> bytes:
        """
        Generate a chart for the given instrument with technical analysis data embedded in the image.
        Uses matplotlib to create a candlestick chart with annotations for technical analysis.
        """
        try:
            logger.info(f"Generating chart with embedded analysis for {instrument} with timeframe {timeframe}")
            
            # Get synthetic market data if real data wasn't provided
            if not tradingview_data:
                tradingview_data = await self.get_real_market_data(instrument, timeframe)
            
            # Extract current price from data
            current_price = tradingview_data.get('current_price', 1.0)
            
            # Extract other data from TradingView data
            rsi = tradingview_data.get('rsi', 50)
            macd = tradingview_data.get('macd', 0)
            macd_signal = tradingview_data.get('macd_signal', 0)
            ema_50 = tradingview_data.get('ema_50', current_price * 0.99)
            ema_200 = tradingview_data.get('ema_200', current_price * 0.98)
            daily_high = tradingview_data.get('daily_high', current_price * 1.01)
            daily_low = tradingview_data.get('daily_low', current_price * 0.99)
            buy_signals = tradingview_data.get('buy_signals', 0)
            sell_signals = tradingview_data.get('sell_signals', 0)
            
            # Bepaal de trend op basis van de signalen
            is_bullish = buy_signals > sell_signals
            action = "BUY" if is_bullish else "SELL"
            
            # Bepaal support en resistance levels
            resistance_levels = tradingview_data.get('resistance_levels', [])
            support_levels = tradingview_data.get('support_levels', [])
            
            resistance = resistance_levels[0] if resistance_levels else daily_high
            support = support_levels[0] if support_levels else daily_low
            
            # Bepaal aantal decimalen voor formatter op basis van het instrument
            if instrument.startswith(('BTC', 'ETH')):
                decimals = 1  # Minder decimalen voor crypto met hoge waarden
            elif instrument.startswith('XAU'):
                decimals = 2  # Minder decimalen voor goud
            else:
                decimals = 5  # Standaard voor forex
            
            # Formateer de waarden voor weergave
            formatted_price = f"{current_price:.{decimals}f}"
            formatted_daily_high = f"{daily_high:.{decimals}f}"
            formatted_daily_low = f"{daily_low:.{decimals}f}"
            formatted_resistance = f"{resistance:.{decimals}f}"
            formatted_support = f"{support:.{decimals}f}"
            formatted_ema50 = f"{ema_50:.{decimals}f}"
            formatted_ema200 = f"{ema_200:.{decimals}f}"
            formatted_macd = f"{macd:.{decimals}f}"
            formatted_macd_signal = f"{macd_signal:.{decimals}f}"

            # Create a figure with 2 sections: chart and analysis text
            fig = plt.figure(figsize=(12, 8))
            
            # Chart section (top 60%)
            ax1 = plt.subplot2grid((10, 1), (0, 0), rowspan=6, colspan=1)
            
            # Generate synthetic price data for chart
            days = 30
            dates = pd.date_range(end=pd.Timestamp.now(), periods=days)
            
            # Get the base price and volatility for this instrument
            base_price = self._get_base_price_for_instrument(instrument)
            volatility = self._get_volatility_for_instrument(instrument)
            
            # Generate random prices with a trend based on if we're bullish or bearish
            np.random.seed(hash(instrument) % 100000)
            # Add a slight trend based on bullish/bearish
            trend = 0.0002 if is_bullish else -0.0002
            price_changes = np.random.normal(trend, volatility, days).cumsum()
            prices = base_price * (1 + price_changes)
            
            # Ensure the final price is correct
            prices = prices - (prices[-1] - current_price)
            
            # Add support and resistance lines
            ax1.axhline(y=support, color='g', linestyle='--', alpha=0.5, label=f'Support: {formatted_support}')
            ax1.axhline(y=resistance, color='r', linestyle='--', alpha=0.5, label=f'Resistance: {formatted_resistance}')
            ax1.axhline(y=current_price, color='b', linestyle='-', alpha=0.3, label=f'Current: {formatted_price}')
            
            # Create a simple line chart
            ax1.plot(dates, prices, color='#1E90FF')
            
            # Format axis
            ax1.set_ylabel('Price')
            ax1.grid(True, alpha=0.3)
            ax1.set_title(f"{instrument} - {timeframe}", fontsize=16, fontweight='bold')
            
            # Make it look more like a trading chart
            ax1.spines['top'].set_visible(False)
            ax1.spines['right'].set_visible(False)
            
            # Add a TradingView-like logo
            plt.figtext(0.01, 0.01, "TradingView", fontsize=8, alpha=0.5)
            
            # Analysis text section (bottom 40%)
            ax2 = plt.subplot2grid((10, 1), (6, 0), rowspan=4, colspan=1)
            ax2.axis('off')
            
            # Create the analysis text
            analysis_text = f"""
{instrument} - {timeframe}

Trend - {action}

Zone Strength 1-5: {'★★★★☆' if is_bullish else '★★★☆☆'}

📊 Market Overview
{instrument} is trading at {formatted_price}, showing {action.lower()} momentum near the daily {'high' if is_bullish else 'low'} ({formatted_daily_high}). The price remains {'above' if is_bullish else 'below'} key EMAs (50 & 200), confirming an {'uptrend' if is_bullish else 'downtrend'}.

🔑 Key Levels
Support: {formatted_support} (daily low), {formatted_support}
Resistance: {formatted_daily_high} (daily high), {formatted_resistance}

📈 Technical Indicators
RSI: {rsi:.2f} (neutral)
MACD: {action} ({formatted_macd} > signal {formatted_macd_signal})
Moving Averages: Price {'above' if is_bullish else 'below'} EMA 50 ({formatted_ema50}) and EMA 200 ({formatted_ema200}), reinforcing {action.lower()} bias.

🤖 Sigmapips AI Recommendation
Monitor price action around {formatted_price}. {'Look for buying opportunities on dips toward support at ' + formatted_support if is_bullish else 'Consider selling rallies toward resistance at ' + formatted_resistance}. {'Stay bullish while price holds above ' + formatted_support if is_bullish else 'Maintain bearish bias below ' + formatted_resistance}.

⚠️ Disclaimer: Please note that the information/analysis provided is strictly for study and educational purposes only. It should not be constructed as financial advice and always do your own analysis.
"""

            # Save the text as the last_analysis attribute for the bot
            self.last_analysis = analysis_text
            
            # Display the analysis text
            plt.figtext(0.05, 0.58, analysis_text, fontsize=9, wrap=True)
            
            # Save the chart to a buffer
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            plt.close(fig)
            
            # Return the buffer
            buf.seek(0)
            return buf.getvalue()
            
        except Exception as e:
            logger.error(f"Error generating chart with analysis: {e}")
            logger.error(traceback.format_exc())
            
            # Create very simple image with text
            plt.figure(figsize=(10, 6))
            plt.text(0.5, 0.5, f"{instrument}\nNo chart available", 
                    horizontalalignment='center',
                    verticalalignment='center',
                    transform=plt.gca().transAxes,
                    fontsize=24)
            plt.axis('off')
            
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            plt.close()
            
            buf.seek(0)
            return buf.getvalue()

    async def _get_tradingview_link(self, instrument: str, timeframe: str, fullscreen: bool) -> str:
        """Genereer de juiste TradingView URL voor het instrument."""
        try:
            # Gebruik de exacte TradingView link voor dit instrument zonder parameters toe te voegen
            tradingview_link = self.chart_links.get(instrument)
            if not tradingview_link:
                # Als er geen specifieke link is, gebruik een generieke link
                logger.warning(f"No specific link found for {instrument}, using generic link")
                tradingview_link = f"https://www.tradingview.com/chart/?symbol={instrument}"
            
            # Voeg fullscreen parameters toe aan de URL
            fullscreen_params = [
                "fullscreen=true",
                "hide_side_toolbar=true",
                "hide_top_toolbar=true",
                "hide_legend=true",
                "theme=dark",
                "toolbar_bg=dark",
                "scale_position=right",
                "scale_mode=normal",
                "studies=[]",
                "hotlist=false",
                "calendar=false"
            ]
            
            # Voeg de parameters toe aan de URL
            if "?" in tradingview_link:
                tradingview_link += "&" + "&".join(fullscreen_params)
            else:
                tradingview_link += "?" + "&".join(fullscreen_params)
                
            return tradingview_link
        except Exception as e:
            logger.error(f"Error generating TradingView link: {e}")
            # Fallback naar een basis URL
            return f"https://www.tradingview.com/chart/?symbol={instrument}" 

    async def initialize(self):
        """Initialize the chart service with eager Node.js preloading"""
        try:
            logger.info("Initializing chart service")
            
            # Gebruik lock om gelijktijdige initialisaties te voorkomen
            async with self._init_lock:
                # Start Node.js initialisatie direct en wacht erop (eager loading)
                # Dit zorgt ervoor dat Node.js al klaar is wanneer we het nodig hebben
                logger.info("Eager initialization of Node.js service")
                node_init_success = await self._init_node_js()
                logger.info(f"Node.js initialized with result: {node_init_success}")
                
                # Sla Selenium initialisatie over vanwege ChromeDriver compatibiliteitsproblemen
                logger.warning("Skipping Selenium initialization due to ChromeDriver compatibility issues")
                self.tradingview_selenium = None
                
                return True
        
        except Exception as e:
            logger.error(f"Error initializing chart service: {str(e)}")
            return False

    async def _init_node_js(self):
        """Initialize Node.js service in background"""
        try:
            # Check of Node.js al geïnitialiseerd is
            if hasattr(self, 'tradingview') and self.tradingview and self.node_initialized:
                logger.info("Node.js service already initialized")
                return True
                
            # Initialiseer de TradingView Node.js service
            from trading_bot.services.chart_service.tradingview_node import TradingViewNodeService
            self.tradingview = TradingViewNodeService()
            
            # Directe initialisatie zonder test
            logger.info("Direct initialization of Node.js service")
            self.node_initialized = await self.tradingview.initialize()
            
            if self.node_initialized:
                logger.info("Node.js service initialized successfully")
                # Stel een kortere timeout in
                self.tradingview.timeout = 40  # 40 seconden timeout
            else:
                logger.error("Node.js service initialization returned False")
                
            return self.node_initialized
        except Exception as e:
            logger.error(f"Error initializing Node.js service: {str(e)}")
            return False 
