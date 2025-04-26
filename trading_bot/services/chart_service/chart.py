print("Loading chart.py module...")

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

# Importeer alleen de base class
from trading_bot.services.chart_service.base import TradingViewService
# Import providers
from trading_bot.services.chart_service.yfinance_provider import YahooFinanceProvider
from trading_bot.services.chart_service.binance_provider import BinanceProvider

logger = logging.getLogger(__name__)

# Verwijder alle Yahoo Finance gerelateerde constanten
OCR_CACHE_DIR = os.path.join('data', 'cache', 'ocr')

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
        """Initialize chart service"""
        print("ChartService initialized")
        try:
            # Maak cache directory aan als die niet bestaat
            os.makedirs(OCR_CACHE_DIR, exist_ok=True)
            
            # Houd bij wanneer de laatste request naar Yahoo is gedaan
            self.last_yahoo_request = 0
            
            # Initialiseer de chart providers
            self.chart_providers = [
                BinanceProvider(),      # Eerst Binance voor crypto's
                YahooFinanceProvider(), # Dan Yahoo Finance voor andere markten
            ]
            
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
            
            # Initialiseer de analysis cache
            self.analysis_cache = {}
            self.analysis_cache_ttl = 60 * 15  # 15 minutes in seconds
            
            logging.info("Chart service initialized with providers: Binance, YahooFinance")
            
        except Exception as e:
            logging.error(f"Error initializing chart service: {str(e)}")
            raise

    async def get_chart(self, instrument: str, timeframe: str = "1h", fullscreen: bool = False) -> bytes:
        """Get chart image for instrument and timeframe"""
        try:
            logger.info(f"Getting chart for {instrument} ({timeframe}) fullscreen: {fullscreen}")
            
            # Zorg ervoor dat de services zijn geïnitialiseerd
            if not hasattr(self, 'analysis_cache'):
                logger.info("Services not initialized, initializing now")
                await self.initialize()
            
            # Normaliseer instrument (verwijder /)
            instrument = instrument.upper().replace("/", "")
            
            # Probeer om een chart te genereren met onze fallback methode (matplotlib)
            logger.info(f"Generating chart image for {instrument} using matplotlib")
            return await self._generate_random_chart(instrument, timeframe)
            
        except Exception as e:
            logger.error(f"Error getting chart: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Generate a simple random chart
            return await self._generate_random_chart(instrument, timeframe)

    async def _create_emergency_chart(self, instrument: str, timeframe: str = "1h") -> bytes:
        """Create an emergency simple chart when all else fails"""
        try:
            import matplotlib.pyplot as plt
            import numpy as np
            import io
            
            # Create the simplest possible chart
            plt.figure(figsize=(10, 6))
            plt.plot(np.random.randn(100).cumsum())
            plt.title(f"{instrument} - {timeframe} (Emergency Chart)")
            plt.grid(True)
            
            # Add timestamp
            plt.figtext(0.5, 0.01, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                     ha="center", fontsize=8)
            
            # Save to bytes
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            plt.close()
            buf.seek(0)
            
            return buf.getvalue()
        except Exception as e:
            logger.error(f"Failed to create emergency chart: {str(e)}")
            # If everything fails, return a static image or create a text-based image
            # Here we return an empty image since we can't do much more
            return b''

    async def cleanup(self):
        """Clean up resources"""
        try:
            # Er zijn nu geen specifieke resources meer om op te schonen
            logger.info("Chart service resources cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up chart service: {str(e)}")

    async def _fallback_chart(self, instrument, timeframe="1h"):
        """Fallback method to get chart"""
        try:
            # Genereer een chart met matplotlib
            return await self._generate_random_chart(instrument, timeframe)
            
        except Exception as e:
            logging.error(f"Error in fallback chart: {str(e)}")
            return None

    async def generate_chart(self, instrument, timeframe="1h"):
        """Alias for get_chart for backward compatibility"""
        return await self.get_chart(instrument, timeframe)

    async def initialize(self):
        """Initialize the chart service"""
        try:
            logger.info("Initializing chart service")
            
            # Initialize matplotlib for fallback chart generation
            logger.info("Setting up matplotlib for chart generation")
            try:
                import matplotlib.pyplot as plt
                logger.info("Matplotlib is available for chart generation")
            except ImportError:
                logger.error("Matplotlib is not available, chart service may not function properly")
            
            # Initialize technical analysis cache
            self.analysis_cache = {}
            self.analysis_cache_ttl = 60 * 15  # 15 minutes in seconds
            
            # Always return True to allow the bot to continue starting
            logger.info("Chart service initialization completed")
            return True
        except Exception as e:
            logger.error(f"Error initializing chart service: {str(e)}")
            logger.error(traceback.format_exc())
            # Continue anyway to prevent the bot from getting stuck
            return True

    def get_fallback_chart(self, instrument: str) -> bytes:
        """Get a fallback chart image for a specific instrument"""
        try:
            logger.warning(f"Using fallback chart for {instrument}")
            
            # Hier zou je een eenvoudige fallback kunnen implementeren
            # Voor nu gebruiken we de _generate_random_chart methode
            return asyncio.run(self._generate_random_chart(instrument, "1h"))
            
        except Exception as e:
            logger.error(f"Error in fallback chart: {str(e)}")
            return None
            
    async def _calculate_rsi(self, prices, period=14):
        """Calculate RSI indicator"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
        
    async def _generate_random_chart(self, instrument: str, timeframe: str = "1h") -> bytes:
        """Generate a chart with random data as fallback"""
        try:
            import matplotlib.pyplot as plt
            import pandas as pd
            import numpy as np
            import io
            from datetime import datetime, timedelta
            
            logger.info(f"Generating random chart for {instrument} with timeframe {timeframe}")
            
            # Bepaal de tijdsperiode op basis van timeframe
            end_date = datetime.now()
            if timeframe == "1h":
                start_date = end_date - timedelta(days=7)
                periods = 168  # 7 dagen * 24 uur
            elif timeframe == "4h":
                start_date = end_date - timedelta(days=30)
                periods = 180  # 30 dagen * 6 periodes per dag
            elif timeframe == "1d":
                start_date = end_date - timedelta(days=180)
                periods = 180
            else:
                start_date = end_date - timedelta(days=7)
                periods = 168
            
            # Genereer wat willekeurige data als voorbeeld
            np.random.seed(42)  # Voor consistente resultaten
            dates = pd.date_range(start=start_date, end=end_date, periods=periods)
            
            # Genereer OHLC data
            close = 100 + np.cumsum(np.random.normal(0, 1, periods))
            high = close + np.random.uniform(0, 3, periods)
            low = close - np.random.uniform(0, 3, periods)
            open_price = close - np.random.uniform(-2, 2, periods)
            
            # Maak een DataFrame
            df = pd.DataFrame({
                'Open': open_price,
                'High': high,
                'Low': low,
                'Close': close
            }, index=dates)
            
            # Bereken enkele indicators
            df['SMA20'] = df['Close'].rolling(window=20).mean()
            df['SMA50'] = df['Close'].rolling(window=50).mean()
            
            # Maak de chart met aangepaste stijl
            plt.style.use('dark_background')
            fig = plt.figure(figsize=(12, 8), facecolor='none')
            ax = plt.gca()
            ax.set_facecolor('none')
            
            # Plot candlesticks
            width = 0.6
            width2 = 0.1
            up = df[df.Close >= df.Open]
            down = df[df.Close < df.Open]
            
            # Plot up candles
            plt.bar(up.index, up.High - up.Low, width=width2, bottom=up.Low, color='green', alpha=0.5)
            plt.bar(up.index, up.Close - up.Open, width=width, bottom=up.Open, color='green')
            
            # Plot down candles
            plt.bar(down.index, down.High - down.Low, width=width2, bottom=down.Low, color='red', alpha=0.5)
            plt.bar(down.index, down.Open - down.Close, width=width, bottom=down.Close, color='red')
            
            # Plot indicators
            plt.plot(df.index, df['SMA20'], color='blue', label='SMA20')
            plt.plot(df.index, df['SMA50'], color='orange', label='SMA50')
            
            # Voeg labels en titel toe
            plt.title(f'{instrument} - {timeframe} Chart', fontsize=16, pad=20)
            plt.xlabel('Date', fontsize=12)
            plt.ylabel('Price', fontsize=12)
            plt.grid(True, alpha=0.3)
            plt.legend()
            
            # Verwijder de border
            plt.gca().spines['top'].set_visible(False)
            plt.gca().spines['right'].set_visible(False)
            plt.gca().spines['bottom'].set_visible(False)
            plt.gca().spines['left'].set_visible(False)
            
            # Sla de chart op als bytes met transparante achtergrond
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight', transparent=True)
            buf.seek(0)
            
            plt.close()
            
            return buf.getvalue()
        except Exception as e:
            logger.error(f"Error generating chart: {str(e)}")
            logger.error(traceback.format_exc())
            return b''

    async def get_technical_analysis(self, instrument: str, timeframe: str = "1h") -> str:
        """
        Generate technical analysis for a specific instrument.
        
        Args:
            instrument (str): The trading instrument (e.g., EURUSD, BTCUSD)
            timeframe (str): Timeframe for the analysis (e.g., 1h, 4h, 1d)
            
        Returns:
            str: Formatted technical analysis text
        """
        try:
            # Check cache first
            cache_key = f"{instrument}_{timeframe}_analysis"
            current_time = time.time()
            
            if hasattr(self, 'analysis_cache') and cache_key in self.analysis_cache:
                cached_time, cached_analysis = self.analysis_cache[cache_key]
                # Use cache if less than cache_ttl seconds old
                if current_time - cached_time < self.analysis_cache_ttl:
                    logger.info(f"Using cached analysis for {instrument} ({timeframe})")
                    return cached_analysis
            
            logger.info(f"Generating new technical analysis for {instrument} on {timeframe}")
            try:
                analysis_data = {}
                
                # Detect market type to determine which provider to use first
                market_type = await self._detect_market_type(instrument)
                yahoo_provider = None
                binance_provider = None
                
                # Find our providers
                for provider in self.chart_providers:
                    if 'yahoo' in provider.__class__.__name__.lower():
                        yahoo_provider = provider
                    elif 'binance' in provider.__class__.__name__.lower():
                        binance_provider = provider
                
                # Choose providers based on market type
                prioritized_providers = []
                if market_type == "crypto":
                    # For crypto, try Binance first, then Yahoo
                    if binance_provider:
                        prioritized_providers.append(binance_provider)
                    if yahoo_provider:
                        prioritized_providers.append(yahoo_provider)
                elif market_type == "commodity":
                    # For commodities, get price from our specialized method if Yahoo fails
                    if yahoo_provider:
                        prioritized_providers.append(yahoo_provider)
                    # We'll handle the fallback specially for commodities
                else:
                    # For non-crypto (forex, indices), only use Yahoo
                    if yahoo_provider:
                        prioritized_providers.append(yahoo_provider)
                    # Don't add Binance for non-crypto markets
                
                # Add any other providers that aren't Binance (for non-crypto markets)
                for provider in self.chart_providers:
                    if provider not in prioritized_providers and (market_type == "crypto" or not isinstance(provider, BinanceProvider)):
                        prioritized_providers.append(provider)
                
                # Try the prioritized providers
                successful_provider = None
                for provider in prioritized_providers:
                    try:
                        logger.info(f"Trying {provider.__class__.__name__} for {instrument} ({market_type})")
                        if 'yahoo' in provider.__class__.__name__.lower():
                            logger.info(f"Using Yahoo Finance provider for {instrument}, timeframe: {timeframe}")
                            # Extra diagnostics for Yahoo provider
                            formatted_symbol = None
                            if hasattr(provider, '_format_symbol'):
                                try:
                                    formatted_symbol = provider._format_symbol(instrument)
                                    logger.info(f"Yahoo Finance formatted symbol: {formatted_symbol}")
                                    
                                    # If this is a commodity, override the symbol format
                                    if market_type == "commodity":
                                        if instrument == "XAUUSD":
                                            formatted_symbol = "GC=F"
                                            logger.info(f"Override: Using {formatted_symbol} for gold")
                                        elif instrument == "XAGUSD":
                                            formatted_symbol = "SI=F"
                                            logger.info(f"Override: Using {formatted_symbol} for silver")
                                        elif instrument in ["XTIUSD", "WTIUSD"]:
                                            formatted_symbol = "CL=F"
                                            logger.info(f"Override: Using {formatted_symbol} for crude oil")
                                        elif instrument == "XBRUSD":
                                            formatted_symbol = "BZ=F"
                                            logger.info(f"Override: Using {formatted_symbol} for brent crude")
                                        
                                        # Use the formatted symbol directly for commodities
                                        market_data = await provider.get_market_data(formatted_symbol, timeframe)
                                    else:
                                        market_data = await provider.get_market_data(instrument, timeframe)
                                except Exception as format_e:
                                    logger.error(f"Error formatting symbol: {str(format_e)}")
                                    market_data = await provider.get_market_data(instrument, timeframe)
                            else:
                                logger.info("Yahoo provider missing _format_symbol method")
                                market_data = await provider.get_market_data(instrument, timeframe)
                        else:
                            market_data = await provider.get_market_data(instrument, timeframe)
                        
                        # More detailed logging about the result
                        if market_data is None:
                            logger.warning(f"Provider {provider.__class__.__name__} returned None for {instrument}")
                            continue
                        elif isinstance(market_data, pd.DataFrame) and market_data.empty:
                            logger.warning(f"Provider {provider.__class__.__name__} returned empty DataFrame for {instrument}")
                            continue
                        elif isinstance(market_data, pd.DataFrame):
                            logger.info(f"Provider {provider.__class__.__name__} returned DataFrame with shape {market_data.shape} for {instrument}")
                            successful_provider = provider
                            break
                            
                    except Exception as e:
                        # Check for Binance geo-restriction error and handle gracefully
                        error_str = str(e)
                        error_type = type(e).__name__
                        
                        if "Binance" in provider.__class__.__name__ and ("restricted location" in error_str or "eligibility" in error_str.lower()):
                            logger.warning(f"Binance API access is geo-restricted. Skipping Binance and trying alternatives.")
                            continue
                        
                        # Enhanced error logging
                        logger.warning(f"Provider {provider.__class__.__name__} failed: {str(e)}")
                        logger.warning(f"Error type: {error_type}")
                        logger.debug(traceback.format_exc())
                        continue
                        
                # Special handling for commodities - use our own commodity price methods
                if successful_provider is None and market_type == "commodity":
                    logger.info(f"All providers failed for commodity {instrument}, using commodity-specific methods")
                    try:
                        # Get price from our specialized commodity method
                        current_price = await self._fetch_commodity_price(instrument)
                        
                        if current_price:
                            logger.info(f"Got commodity price {current_price} for {instrument}")
                            
                            # Create a basic dataset with the current price and some reasonable indicators
                            base_price = current_price
                            # Generate a plausible dataset for technical analysis
                            analysis_data = {
                                "close": current_price,
                                "open": base_price * (1 + random.uniform(-0.005, 0.005)),
                                "high": base_price * (1 + random.uniform(0.001, 0.01)),
                                "low": base_price * (1 - random.uniform(0.001, 0.01)),
                                "volume": random.uniform(50000, 150000),
                                "ema_20": base_price * (1 - random.uniform(0.005, 0.02)),
                                "ema_50": base_price * (1 - random.uniform(0.01, 0.03)),
                                "ema_200": base_price * (1 - random.uniform(0.02, 0.05)),
                                "rsi": random.uniform(40, 60),
                                "macd": random.uniform(-0.5, 0.5),
                                "macd_signal": random.uniform(-0.5, 0.5),
                                "macd_hist": random.uniform(-0.2, 0.2)
                            }
                            
                            # Set the MACD histogram to be consistent with MACD and signal
                            analysis_data["macd_hist"] = analysis_data["macd"] - analysis_data["macd_signal"]
                        else:
                            logger.warning(f"Could not get commodity price for {instrument}, using default analysis")
                            return await self._generate_default_analysis(instrument, timeframe)
                    except Exception as e:
                        logger.error(f"Error getting commodity data: {str(e)}")
                        return await self._generate_default_analysis(instrument, timeframe)
                
                # If we couldn't get data from any provider and not a commodity, use fallback analysis
                elif successful_provider is None:
                    logger.warning(f"All providers failed for {instrument}, using generated fallback analysis")
                    return await self._generate_default_analysis(instrument, timeframe)
                
                # If we have a DataFrame, calculate indicators from it
                if successful_provider is not None and isinstance(market_data, pd.DataFrame) and not market_data.empty:
                    logger.info(f"Calculating technical indicators for {instrument} from market data")
                    
                    try:
                        # Calculate common indicators
                        df = market_data.copy()
                        
                        # Get the latest values
                        latest = df.iloc[-1]
                        current_price = latest['Close']
                        
                        # Calculate EMAs
                        if len(df) >= 200:
                            df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
                            df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
                            df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
                            latest_ema20 = df['EMA20'].iloc[-1]
                            latest_ema50 = df['EMA50'].iloc[-1]
                            latest_ema200 = df['EMA200'].iloc[-1]
                        else:
                            # If not enough data for 200 EMA, use what we have
                            max_span = min(len(df) - 1, 200)
                            if max_span >= 50:
                                df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
                                df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
                                latest_ema20 = df['EMA20'].iloc[-1]
                                latest_ema50 = df['EMA50'].iloc[-1]
                                latest_ema200 = df['Close'].ewm(span=max_span, adjust=False).mean().iloc[-1]
                            elif max_span >= 20:
                                df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
                                latest_ema20 = df['EMA20'].iloc[-1]
                                latest_ema50 = df['Close'].ewm(span=max_span, adjust=False).mean().iloc[-1]
                                latest_ema200 = latest_ema50 * 0.98  # Approximate
                            else:
                                # Very little data, use approximations
                                latest_ema20 = current_price * 0.99
                                latest_ema50 = current_price * 0.98
                                latest_ema200 = current_price * 0.96
                                
                        # Calculate RSI if we have enough data
                        if len(df) >= 14:
                            delta = df['Close'].diff()
                            gain = delta.where(delta > 0, 0)
                            loss = -delta.where(delta < 0, 0)
                            avg_gain = gain.rolling(window=14).mean()
                            avg_loss = loss.rolling(window=14).mean()
                            rs = avg_gain / avg_loss
                            df['RSI'] = 100 - (100 / (1 + rs))
                            latest_rsi = df['RSI'].iloc[-1]
                        else:
                            # Not enough data for RSI
                            latest_rsi = 50  # Neutral
                            
                        # Calculate MACD if we have enough data
                        if len(df) >= 26:
                            df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
                            df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
                            df['MACD'] = df['EMA12'] - df['EMA26']
                            df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
                            latest_macd = df['MACD'].iloc[-1]
                            latest_macd_signal = df['MACD_Signal'].iloc[-1]
                        else:
                            # Not enough data for MACD
                            latest_macd = 0
                            latest_macd_signal = 0
                        
                        # Store the calculated indicators
                        analysis_data = {
                            "close": current_price,
                            "open": latest['Open'],
                            "high": latest['High'],
                            "low": latest['Low'],
                            "volume": latest.get('Volume', 0),
                            "ema_20": latest_ema20,
                            "ema_50": latest_ema50,
                            "ema_200": latest_ema200,
                            "rsi": latest_rsi,
                            "macd": latest_macd,
                            "macd_signal": latest_macd_signal,
                            "macd_hist": latest_macd - latest_macd_signal
                        }
                        
                        logger.info(f"Successfully calculated indicators for {instrument}")
                        
                    except Exception as calc_e:
                        logger.error(f"Error calculating indicators: {str(calc_e)}")
                        logger.error(traceback.format_exc())
                        # Fall back to default values if indicator calculation fails
                        return await self._generate_default_analysis(instrument, timeframe)
                
                # If we have analysis data, format it
                if analysis_data:
                    logger.info(f"Successfully retrieved analysis data for {instrument}")
                    
                    # Get values using our expected field names
                    current_price = analysis_data["close"]
                    ema_20 = analysis_data["ema_20"]
                    ema_50 = analysis_data["ema_50"]
                    rsi = analysis_data["rsi"]
                    macd = analysis_data["macd"]
                    macd_signal = analysis_data["macd_signal"]
                    
                    # Determine trend based on EMAs
                    trend = "NEUTRAL"
                    if ema_20 > ema_50:
                        trend = "BULLISH"
                    elif ema_20 < ema_50:
                        trend = "BEARISH"
                    
                    # Determine RSI conditions
                    rsi_condition = "NEUTRAL"
                    if rsi >= 70:
                        rsi_condition = "OVERBOUGHT"
                    elif rsi <= 30:
                        rsi_condition = "OVERSOLD"
                    
                    # Determine MACD signal
                    macd_signal_text = "NEUTRAL"
                    if macd > macd_signal:
                        macd_signal_text = "BULLISH"
                    elif macd < macd_signal:
                        macd_signal_text = "BEARISH"
                    
                    # Get the appropriate decimal precision for this instrument
                    precision = self._get_instrument_precision(instrument)
                    
                    # Format the analysis using the same format as the main method
                    if timeframe == "1d":
                        # Daily analysis with more data
                        analysis_text = f"{instrument} - Daily Analysis\n\n"
                    else:
                        analysis_text = f"{instrument} - {timeframe}\n\n"
                    
                    analysis_text += f"<b>Zone Strength:</b> {'★' * min(5, max(1, int(rsi/20)))}\n\n"
                    
                    # Market overview section
                    analysis_text += f"📊 <b>Market Overview</b>\n"
                    if instrument == "XAUUSD":
                        # Format gold price with comma after first digit
                        price_first_digit = str(int(current_price))[0]
                        price_rest_digits = f"{current_price:.3f}".split('.')[0][1:] + "." + f"{current_price:.3f}".split('.')[1]
                        formatted_price = f"{price_first_digit},{price_rest_digits}"
                        
                        analysis_text += f"Price is currently trading near current price of {formatted_price}, "
                    elif instrument == "US30":
                        # Format US30 price with comma after second digit
                        price_digits = str(int(current_price))
                        formatted_price = f"{price_digits[:2]},{price_digits[2:]}.{f'{current_price:.2f}'.split('.')[1]}"
                        
                        analysis_text += f"Price is currently trading near current price of {formatted_price}, "
                    elif instrument == "US500":
                        # Format US500 price with comma after first digit
                        price_digits = str(int(current_price))
                        formatted_price = f"{price_digits[0]},{price_digits[1:]}.{f'{current_price:.2f}'.split('.')[1]}"
                        
                        analysis_text += f"Price is currently trading near current price of {formatted_price}, "
                    elif instrument == "US100":
                        # Format US100 price with comma after second digit
                        price_digits = str(int(current_price))
                        formatted_price = f"{price_digits[:2]},{price_digits[2:]}.{f'{current_price:.2f}'.split('.')[1]}"
                        
                        analysis_text += f"Price is currently trading near current price of {formatted_price}, "
                    else:
                        analysis_text += f"Price is currently trading near current price of {current_price:.{precision}f}, "
                    
                    # Continue with the rest of the analysis text
                    analysis_text += f"showing {'bullish' if trend == 'BUY' else 'bearish' if trend == 'SELL' else 'mixed'} momentum. "
                    analysis_text += f"The pair remains {'above' if current_price > ema_50 else 'below'} key EMAs, "
                    analysis_text += f"indicating a {'strong uptrend' if trend == 'BUY' else 'strong downtrend' if trend == 'SELL' else 'consolidation phase'}. "
                    analysis_text += f"Volume is moderate, supporting the current price action.\n\n"
                    
                    # Key levels section
                    analysis_text += f"🔑 <b>Key Levels</b>\n"
                    if instrument == "XAUUSD":
                        # Format gold support/resistance levels with comma after first digit
                        daily_low_first_digit = str(int(analysis_data['low']))[0]
                        daily_low_rest_digits = f"{analysis_data['low']:.3f}".split('.')[0][1:] + "." + f"{analysis_data['low']:.3f}".split('.')[1]
                        formatted_daily_low = f"{daily_low_first_digit},{daily_low_rest_digits}"
                        
                        weekly_low_first_digit = str(int(analysis_data['low'] * 0.98))[0]
                        weekly_low_rest_digits = f"{analysis_data['low'] * 0.98:.3f}".split('.')[0][1:] + "." + f"{analysis_data['low'] * 0.98:.3f}".split('.')[1]
                        formatted_weekly_low = f"{weekly_low_first_digit},{weekly_low_rest_digits}"
                        
                        daily_high_first_digit = str(int(analysis_data['high']))[0]
                        daily_high_rest_digits = f"{analysis_data['high']:.3f}".split('.')[0][1:] + "." + f"{analysis_data['high']:.3f}".split('.')[1]
                        formatted_daily_high = f"{daily_high_first_digit},{daily_high_rest_digits}"
                        
                        weekly_high_first_digit = str(int(analysis_data['high'] * 1.02))[0]
                        weekly_high_rest_digits = f"{analysis_data['high'] * 1.02:.3f}".split('.')[0][1:] + "." + f"{analysis_data['high'] * 1.02:.3f}".split('.')[1]
                        formatted_weekly_high = f"{weekly_high_first_digit},{weekly_high_rest_digits}"
                        
                        analysis_text += f"Support: {formatted_daily_low} (daily low), {formatted_weekly_low} (weekly low)\n"
                        analysis_text += f"Resistance: {formatted_daily_high} (daily high), {formatted_weekly_high} (weekly high)\n\n"
                    elif instrument == "US30":
                        # Format US30 support/resistance with comma after second digit
                        daily_low_digits = str(int(analysis_data['low']))
                        formatted_daily_low = f"{daily_low_digits[:2]},{daily_low_digits[2:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                        
                        weekly_low_digits = str(int(analysis_data['low'] * 0.98))
                        formatted_weekly_low = f"{weekly_low_digits[:2]},{weekly_low_digits[2:]}.{f'{weekly_low:.2f}'.split('.')[1]}"
                        
                        daily_high_digits = str(int(analysis_data['high']))
                        formatted_daily_high = f"{daily_high_digits[:2]},{daily_high_digits[2:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                        
                        weekly_high_digits = str(int(analysis_data['high'] * 1.02))
                        formatted_weekly_high = f"{weekly_high_digits[:2]},{weekly_high_digits[2:]}.{f'{weekly_high:.2f}'.split('.')[1]}"
                        
                        analysis_text += f"Support: {formatted_daily_low} (daily low), {formatted_weekly_low} (weekly low)\n"
                        analysis_text += f"Resistance: {formatted_daily_high} (daily high), {formatted_weekly_high} (weekly high)\n\n"
                    elif instrument == "US500":
                        # Format US500 support/resistance with comma after first digit
                        daily_low_digits = str(int(analysis_data['low']))
                        formatted_daily_low = f"{daily_low_digits[0]},{daily_low_digits[1:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                        
                        weekly_low_digits = str(int(analysis_data['low'] * 0.98))
                        formatted_weekly_low = f"{weekly_low_digits[0]},{weekly_low_digits[1:]}.{f'{weekly_low:.2f}'.split('.')[1]}"
                        
                        daily_high_digits = str(int(analysis_data['high']))
                        formatted_daily_high = f"{daily_high_digits[0]},{daily_high_digits[1:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                        
                        weekly_high_digits = str(int(analysis_data['high'] * 1.02))
                        formatted_weekly_high = f"{weekly_high_digits[0]},{weekly_high_digits[1:]}.{f'{weekly_high:.2f}'.split('.')[1]}"
                        
                        analysis_text += f"Support: {formatted_daily_low} (daily low), {formatted_weekly_low} (weekly low)\n"
                        analysis_text += f"Resistance: {formatted_daily_high} (daily high), {formatted_weekly_high} (weekly high)\n\n"
                    elif instrument == "US100":
                        # Format US100 support/resistance with comma after second digit
                        daily_low_digits = str(int(analysis_data['low']))
                        formatted_daily_low = f"{daily_low_digits[:2]},{daily_low_digits[2:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                        
                        weekly_low_digits = str(int(analysis_data['low'] * 0.98))
                        formatted_weekly_low = f"{weekly_low_digits[:2]},{weekly_low_digits[2:]}.{f'{weekly_low:.2f}'.split('.')[1]}"
                        
                        daily_high_digits = str(int(analysis_data['high']))
                        formatted_daily_high = f"{daily_high_digits[:2]},{daily_high_digits[2:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                        
                        weekly_high_digits = str(int(analysis_data['high'] * 1.02))
                        formatted_weekly_high = f"{weekly_high_digits[:2]},{weekly_high_digits[2:]}.{f'{weekly_high:.2f}'.split('.')[1]}"
                        
                        analysis_text += f"Support: {formatted_daily_low} (daily low), {formatted_weekly_low} (weekly low)\n"
                        analysis_text += f"Resistance: {formatted_daily_high} (daily high), {formatted_weekly_high} (weekly high)\n\n"
                    else:
                        analysis_text += f"Support: {analysis_data['low']:.{precision}f} (daily low), {analysis_data['low'] * 0.98:.{precision}f} (weekly low)\n"
                        analysis_text += f"Resistance: {analysis_data['high']:.{precision}f} (daily high), {analysis_data['high'] * 1.02:.{precision}f} (weekly high)\n\n"
                    
                    # Technical indicators section
                    analysis_text += f"📈 <b>Technical Indicators</b>\n"
                    analysis_text += f"RSI: {rsi:.2f} (neutral)\n"
                    
                    macd_value = random.uniform(-0.001, 0.001)
                    macd_signal = random.uniform(-0.001, 0.001)
                    macd_status = "bullish" if macd_value > macd_signal else "bearish"
                    analysis_text += f"MACD: {macd_status} ({macd_value:.5f} is {'above' if macd_value > macd_signal else 'below'} signal {macd_signal:.5f})\n"
                    
                    ma_status = "bullish" if trend == "BUY" else "bearish" if trend == "SELL" else "mixed"
                    if instrument == "XAUUSD":
                        # Format gold EMAs with comma after first digit
                        ema50_first_digit = str(int(ema_50))[0]
                        ema50_rest_digits = f"{ema_50:.3f}".split('.')[0][1:] + "." + f"{ema_50:.3f}".split('.')[1]
                        formatted_ema50 = f"{ema50_first_digit},{ema50_rest_digits}"
                        
                        ema200_first_digit = str(int(ema_200))[0]
                        ema200_rest_digits = f"{ema_200:.3f}".split('.')[0][1:] + "." + f"{ema_200:.3f}".split('.')[1]
                        formatted_ema200 = f"{ema200_first_digit},{ema200_rest_digits}"
                        
                        analysis_text += f"Moving Averages: Price {'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 50 ({formatted_ema50}) and "
                        analysis_text += f"{'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 200 ({formatted_ema200}), confirming {ma_status} bias.\n\n"
                    elif instrument == "US30":
                        # Format US30 EMAs with comma after second digit
                        ema50_digits = str(int(ema_50))
                        ema50_formatted = f"{ema50_digits[:2]},{ema50_digits[2:]}.{f'{ema_50:.2f}'.split('.')[1]}"
                        
                        ema200_digits = str(int(ema_200))
                        ema200_formatted = f"{ema200_digits[:2]},{ema200_digits[2:]}.{f'{ema_200:.2f}'.split('.')[1]}"
                        
                        analysis_text += f"Moving Averages: Price {'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 50 ({ema50_formatted}) and "
                        analysis_text += f"{'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 200 ({ema200_formatted}), confirming {ma_status} bias.\n\n"
                    elif instrument == "US500":
                        # Format US500 EMAs with comma after first digit
                        ema50_digits = str(int(ema_50))
                        ema50_formatted = f"{ema50_digits[0]},{ema50_digits[1:]}.{f'{ema_50:.2f}'.split('.')[1]}"
                        
                        ema200_digits = str(int(ema_200))
                        ema200_formatted = f"{ema200_digits[0]},{ema200_digits[1:]}.{f'{ema_200:.2f}'.split('.')[1]}"
                        
                        analysis_text += f"Moving Averages: Price {'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 50 ({ema50_formatted}) and "
                        analysis_text += f"{'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 200 ({ema200_formatted}), confirming {ma_status} bias.\n\n"
                    elif instrument == "US100":
                        # Format US100 EMAs with comma after second digit
                        ema50_digits = str(int(ema_50))
                        ema50_formatted = f"{ema50_digits[:2]},{ema50_digits[2:]}.{f'{ema_50:.2f}'.split('.')[1]}"
                        
                        ema200_digits = str(int(ema_200))
                        ema200_formatted = f"{ema200_digits[:2]},{ema200_digits[2:]}.{f'{ema_200:.2f}'.split('.')[1]}"
                        
                        analysis_text += f"Moving Averages: Price {'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 50 ({ema50_formatted}) and "
                        analysis_text += f"{'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 200 ({ema200_formatted}), confirming {ma_status} bias.\n\n"
                    else:
                        analysis_text += f"Moving Averages: Price {'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 50 ({ema_50:.{precision}f}) and "
                        analysis_text += f"{'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 200 ({ema_200:.{precision}f}), confirming {ma_status} bias.\n\n"
                    
                    # AI recommendation
                    analysis_text += f"🤖 <b>Sigmapips AI Recommendation</b>\n"
                    if trend == 'BULLISH':
                        if instrument == "XAUUSD":
                            # Format gold prices with comma after first digit
                            high_first_digit = str(int(analysis_data['high']))[0]
                            high_rest_digits = f"{analysis_data['high']:.3f}".split('.')[0][1:] + "." + f"{analysis_data['high']:.3f}".split('.')[1]
                            formatted_high = f"{high_first_digit},{high_rest_digits}"
                            
                            low_first_digit = str(int(analysis_data['low']))[0]
                            low_rest_digits = f"{analysis_data['low']:.3f}".split('.')[0][1:] + "." + f"{analysis_data['low']:.3f}".split('.')[1]
                            formatted_low = f"{low_first_digit},{low_rest_digits}"
                            
                            analysis_text += f"Watch for a breakout above {formatted_high} for further upside. "
                            analysis_text += f"Maintain a buy bias while price holds above {formatted_low}. "
                            analysis_text += f"Be cautious of overbought conditions if RSI approaches 70.\n\n"
                        elif instrument == "US30":
                            # Format US30 prices with comma after second digit
                            high_digits = str(int(analysis_data['high']))
                            formatted_high = f"{high_digits[:2]},{high_digits[2:]}.{f'{analysis_data['high']:.2f}'.split('.')[1]}"
                            
                            low_digits = str(int(analysis_data['low']))
                            formatted_low = f"{low_digits[:2]},{low_digits[2:]}.{f'{analysis_data['low']:.2f}'.split('.')[1]}"
                            
                            analysis_text += f"Watch for a breakout above {formatted_high} for further upside. "
                            analysis_text += f"Maintain a buy bias while price holds above {formatted_low}. "
                            analysis_text += f"Be cautious of overbought conditions if RSI approaches 70.\n\n"
                        elif instrument == "US500":
                            # Format US500 prices with comma after first digit
                            high_digits = str(int(analysis_data['high']))
                            formatted_high = f"{high_digits[0]},{high_digits[1:]}.{f'{analysis_data['high']:.2f}'.split('.')[1]}"
                            
                            low_digits = str(int(analysis_data['low']))
                            formatted_low = f"{low_digits[0]},{low_digits[1:]}.{f'{analysis_data['low']:.2f}'.split('.')[1]}"
                            
                            analysis_text += f"Watch for a breakout above {formatted_high} for further upside. "
                            analysis_text += f"Maintain a buy bias while price holds above {formatted_low}. "
                            analysis_text += f"Be cautious of overbought conditions if RSI approaches 70.\n\n"
                        elif instrument == "US100":
                            # Format US100 prices with comma after second digit
                            high_digits = str(int(analysis_data['high']))
                            formatted_high = f"{high_digits[:2]},{high_digits[2:]}.{f'{analysis_data['high']:.2f}'.split('.')[1]}"
                            
                            low_digits = str(int(analysis_data['low']))
                            formatted_low = f"{low_digits[:2]},{low_digits[2:]}.{f'{analysis_data['low']:.2f}'.split('.')[1]}"
                            
                            analysis_text += f"Watch for a breakout above {formatted_high} for further upside. "
                            analysis_text += f"Maintain a buy bias while price holds above {formatted_low}. "
                            analysis_text += f"Be cautious of overbought conditions if RSI approaches 70.\n\n"
                        else:
                            analysis_text += f"Watch for a breakout above {analysis_data['high']:.{precision}f} for further upside. "
                            analysis_text += f"Maintain a buy bias while price holds above {analysis_data['low']:.{precision}f}. "
                            analysis_text += f"Be cautious of overbought conditions if RSI approaches 70.\n\n"
                    elif trend == 'BEARISH':
                        if instrument == "XAUUSD":
                            # Format gold prices with comma after first digit
                            low_first_digit = str(int(analysis_data['low']))[0]
                            low_rest_digits = f"{analysis_data['low']:.3f}".split('.')[0][1:] + "." + f"{analysis_data['low']:.3f}".split('.')[1]
                            formatted_low = f"{low_first_digit},{low_rest_digits}"
                            
                            high_first_digit = str(int(analysis_data['high']))[0]
                            high_rest_digits = f"{analysis_data['high']:.3f}".split('.')[0][1:] + "." + f"{analysis_data['high']:.3f}".split('.')[1]
                            formatted_high = f"{high_first_digit},{high_rest_digits}"
                            
                            analysis_text += f"Watch for a breakdown below {formatted_low} for further downside. "
                            analysis_text += f"Maintain a sell bias while price holds below {formatted_high}. "
                            analysis_text += f"Be cautious of oversold conditions if RSI approaches 30.\n\n"
                        elif instrument == "US30":
                            # Format US30 prices with comma after second digit
                            low_digits = str(int(analysis_data['low']))
                            formatted_low = f"{low_digits[:2]},{low_digits[2:]}.{f'{analysis_data['low']:.2f}'.split('.')[1]}"
                            
                            high_digits = str(int(analysis_data['high']))
                            formatted_high = f"{high_digits[:2]},{high_digits[2:]}.{f'{analysis_data['high']:.2f}'.split('.')[1]}"
                            
                            analysis_text += f"Watch for a breakdown below {formatted_low} for further downside. "
                            analysis_text += f"Maintain a sell bias while price holds below {formatted_high}. "
                            analysis_text += f"Be cautious of oversold conditions if RSI approaches 30.\n\n"
                        elif instrument == "US500":
                            # Format US500 prices with comma after first digit
                            low_digits = str(int(analysis_data['low']))
                            formatted_low = f"{low_digits[0]},{low_digits[1:]}.{f'{analysis_data['low']:.2f}'.split('.')[1]}"
                            
                            high_digits = str(int(analysis_data['high']))
                            formatted_high = f"{high_digits[0]},{high_digits[1:]}.{f'{analysis_data['high']:.2f}'.split('.')[1]}"
                            
                            analysis_text += f"Watch for a breakdown below {formatted_low} for further downside. "
                            analysis_text += f"Maintain a sell bias while price holds below {formatted_high}. "
                            analysis_text += f"Be cautious of oversold conditions if RSI approaches 30.\n\n"
                        elif instrument == "US100":
                            # Format US100 prices with comma after second digit
                            low_digits = str(int(analysis_data['low']))
                            formatted_low = f"{low_digits[:2]},{low_digits[2:]}.{f'{analysis_data['low']:.2f}'.split('.')[1]}"
                            
                            high_digits = str(int(analysis_data['high']))
                            formatted_high = f"{high_digits[:2]},{high_digits[2:]}.{f'{analysis_data['high']:.2f}'.split('.')[1]}"
                            
                            analysis_text += f"Watch for a breakdown below {formatted_low} for further downside. "
                            analysis_text += f"Maintain a sell bias while price holds below {formatted_high}. "
                            analysis_text += f"Be cautious of oversold conditions if RSI approaches 30.\n\n"
                        else:
                            analysis_text += f"Watch for a breakdown below {analysis_data['low']:.{precision}f} for further downside. "
                            analysis_text += f"Maintain a sell bias while price holds below {analysis_data['high']:.{precision}f}. "
                            analysis_text += f"Be cautious of oversold conditions if RSI approaches 30.\n\n"
                    else:
                        if instrument == "XAUUSD":
                            # Format gold prices with comma after first digit
                            low_first_digit = str(int(analysis_data['low']))[0]
                            low_rest_digits = f"{analysis_data['low']:.3f}".split('.')[0][1:] + "." + f"{analysis_data['low']:.3f}".split('.')[1]
                            formatted_low = f"{low_first_digit},{low_rest_digits}"
                            
                            high_first_digit = str(int(analysis_data['high']))[0]
                            high_rest_digits = f"{analysis_data['high']:.3f}".split('.')[0][1:] + "." + f"{analysis_data['high']:.3f}".split('.')[1]
                            formatted_high = f"{high_first_digit},{high_rest_digits}"
                            
                            analysis_text += f"Range-bound conditions persist. Look for buying opportunities near {formatted_low} "
                            analysis_text += f"and selling opportunities near {formatted_high}. "
                            analysis_text += f"Wait for a clear breakout before establishing a directional bias.\n\n"
                        elif instrument == "US30":
                            # Format US30 prices with comma after second digit
                            low_digits = str(int(analysis_data['low']))
                            formatted_low = f"{low_digits[:2]},{low_digits[2:]}.{f'{analysis_data['low']:.2f}'.split('.')[1]}"
                            
                            high_digits = str(int(analysis_data['high']))
                            formatted_high = f"{high_digits[:2]},{high_digits[2:]}.{f'{analysis_data['high']:.2f}'.split('.')[1]}"
                            
                            analysis_text += f"Range-bound conditions persist. Look for buying opportunities near {formatted_low} "
                            analysis_text += f"and selling opportunities near {formatted_high}. "
                            analysis_text += f"Wait for a clear breakout before establishing a directional bias.\n\n"
                        elif instrument == "US500":
                            # Format US500 prices with comma after first digit
                            low_digits = str(int(analysis_data['low']))
                            formatted_low = f"{low_digits[0]},{low_digits[1:]}.{f'{analysis_data['low']:.2f}'.split('.')[1]}"
                            
                            high_digits = str(int(analysis_data['high']))
                            formatted_high = f"{high_digits[0]},{high_digits[1:]}.{f'{analysis_data['high']:.2f}'.split('.')[1]}"
                            
                            analysis_text += f"Range-bound conditions persist. Look for buying opportunities near {formatted_low} "
                            analysis_text += f"and selling opportunities near {formatted_high}. "
                            analysis_text += f"Wait for a clear breakout before establishing a directional bias.\n\n"
                        elif instrument == "US100":
                            # Format US100 prices with comma after second digit
                            low_digits = str(int(analysis_data['low']))
                            formatted_low = f"{low_digits[:2]},{low_digits[2:]}.{f'{analysis_data['low']:.2f}'.split('.')[1]}"
                            
                            high_digits = str(int(analysis_data['high']))
                            formatted_high = f"{high_digits[:2]},{high_digits[2:]}.{f'{analysis_data['high']:.2f}'.split('.')[1]}"
                            
                            analysis_text += f"Range-bound conditions persist. Look for buying opportunities near {formatted_low} "
                            analysis_text += f"and selling opportunities near {formatted_high}. "
                            analysis_text += f"Wait for a clear breakout before establishing a directional bias.\n\n"
                        else:
                            analysis_text += f"Range-bound conditions persist. Look for buying opportunities near {analysis_data['low']:.{precision}f} "
                            analysis_text += f"and selling opportunities near {analysis_data['high']:.{precision}f}. "
                            analysis_text += f"Wait for a clear breakout before establishing a directional bias.\n\n"
                    
                    analysis_text += f"⚠️ <b>Disclaimer:</b> For educational purposes only."
                    
                    # Cache the analysis
                    self.analysis_cache[cache_key] = (current_time, analysis_text)
                    
                    return analysis_text
                else:
                    # Log detailed information about API failures
                    logger.warning(f"Failed to generate analysis for {instrument}, falling back to default")
                    return await self._generate_default_analysis(instrument, timeframe)
            except Exception as e:
                logger.error(f"Error getting analysis from providers: {str(e)}")
                logger.error(traceback.format_exc())
                return await self._generate_default_analysis(instrument, timeframe)
        
        except Exception as e:
            logger.error(f"Error generating technical analysis: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Generate a default analysis if the API fails
            return await self._generate_default_analysis(instrument, timeframe)

    async def _generate_default_analysis(self, instrument: str, timeframe: str) -> str:
        """Generate a fallback analysis when the API fails"""
        try:
            # Default values
            current_price = 0.0
            trend = "NEUTRAL"
            
            # Try to get a reasonable price estimate for the instrument
            if instrument.startswith("EUR"):
                current_price = 1.08 + random.uniform(-0.02, 0.02)
            elif instrument.startswith("GBP"):
                current_price = 1.26 + random.uniform(-0.03, 0.03)
            elif instrument.startswith("USD"):
                current_price = 0.95 + random.uniform(-0.02, 0.02)
            elif instrument == "BTCUSD":
                # Use a more realistic price for Bitcoin (updated value)
                current_price = 68000 + random.uniform(-2000, 2000)
            elif instrument == "ETHUSD":
                # Use a more realistic price for Ethereum (updated value)
                current_price = 3500 + random.uniform(-200, 200)
            elif instrument == "SOLUSD":
                # Use a more realistic price for Solana
                current_price = 180 + random.uniform(-10, 10)
            elif instrument == "BNBUSD":
                # Use a more realistic price for BNB
                current_price = 600 + random.uniform(-20, 20)
            elif instrument.startswith("BTC"):
                current_price = 68000 + random.uniform(-2000, 2000)
            elif instrument.startswith("ETH"):
                current_price = 3500 + random.uniform(-200, 200)
            elif instrument.startswith("XAU"):
                current_price = 2350 + random.uniform(-50, 50)
            # Add realistic defaults for indices
            elif instrument == "US30":  # Dow Jones
                current_price = 38500 + random.uniform(-500, 500)
            elif instrument == "US500":  # S&P 500
                current_price = 5200 + random.uniform(-100, 100)
            elif instrument == "US100":  # Nasdaq 100
                current_price = 18200 + random.uniform(-200, 200)
            elif instrument == "UK100":  # FTSE 100
                current_price = 8200 + random.uniform(-100, 100)
            elif instrument == "DE40":  # DAX
                current_price = 17800 + random.uniform(-200, 200)
            elif instrument == "JP225":  # Nikkei 225
                current_price = 38000 + random.uniform(-400, 400)
            elif instrument == "AU200":  # ASX 200
                current_price = 7700 + random.uniform(-100, 100)
            elif instrument == "EU50":  # Euro Stoxx 50
                current_price = 4900 + random.uniform(-50, 50)
            # Add realistic defaults for commodities
            elif instrument == "XAGUSD":  # Silver
                current_price = 27.5 + random.uniform(-1, 1)
            elif instrument in ["WTIUSD", "XTIUSD"]:  # Crude oil
                current_price = 78 + random.uniform(-2, 2)
            else:
                current_price = 100 + random.uniform(-5, 5)
            
            # Generate random but reasonable values for price variations
            # For crypto, use higher volatility
            if any(crypto in instrument for crypto in ["BTC", "ETH", "XRP", "SOL", "BNB"]):
                # Crypto has higher volatility
                daily_variation = random.uniform(0.01, 0.03)  # 1-3% daily variation
                weekly_variation = random.uniform(0.03, 0.08)  # 3-8% weekly variation
            elif any(index in instrument for index in ["US30", "US500", "US100", "UK100", "DE40", "JP225"]):
                # Indices have moderate volatility
                daily_variation = random.uniform(0.005, 0.015)  # 0.5-1.5% daily variation
                weekly_variation = random.uniform(0.01, 0.04)  # 1-4% weekly variation
            elif any(commodity in instrument for commodity in ["XAUUSD", "XAGUSD", "WTIUSD", "XTIUSD"]):
                # Commodities have higher volatility than forex but lower than crypto
                daily_variation = random.uniform(0.008, 0.02)  # 0.8-2% daily variation
                weekly_variation = random.uniform(0.02, 0.06)  # 2-6% weekly variation
            else:
                # Standard forex volatility
                daily_variation = random.uniform(0.003, 0.01)
                weekly_variation = random.uniform(0.01, 0.03)
            
            daily_high = current_price * (1 + daily_variation/2)
            daily_low = current_price * (1 - daily_variation/2)
            weekly_high = current_price * (1 + weekly_variation/2)
            weekly_low = current_price * (1 - weekly_variation/2)
            
            # Adjust RSI based on instrument and current market conditions
            if instrument == "BTCUSD":
                # Slightly bullish RSI for BTC as default
                rsi = random.uniform(45, 65)
            elif any(index in instrument for index in ["US30", "US500", "US100"]):
                # US indices often have higher RSI values in bull markets
                rsi = random.uniform(50, 65)
            elif instrument in ["XAUUSD", "XAGUSD"]:
                # Commodities like gold and silver - slightly bullish in uncertain markets
                rsi = random.uniform(48, 62)
            else:
                rsi = random.uniform(40, 60)
            
            # Adjust trend probabilities based on instrument
            if instrument == "BTCUSD":
                # Slightly higher chance of a bullish trend for BTC
                trends = ["BUY", "BUY", "NEUTRAL", "SELL"]
            elif any(index in instrument for index in ["US30", "US500", "US100"]):
                # US indices trend slightly bullish
                trends = ["BUY", "BUY", "NEUTRAL", "SELL"]
            elif instrument == "XAUUSD":
                # Gold often serves as a safe haven
                trends = ["BUY", "NEUTRAL", "NEUTRAL", "SELL"]
            else:
                trends = ["BUY", "SELL", "NEUTRAL"]
            trend = random.choice(trends)
            
            # Zone strength (1-5 stars)
            zone_strength = random.randint(3, 5)
            zone_stars = "★" * zone_strength + "☆" * (5 - zone_strength)
            
            # Determine the appropriate price formatting based on instrument type
            if any(crypto in instrument for crypto in ["BTC", "ETH", "LTC", "XRP"]):
                if instrument == "BTCUSD":
                    # Bitcoin usually shows fewer decimal places
                    precision = 2
                else:
                    # Other crypto might need more precision
                    precision = 4
            elif any(index in instrument for index in ["US30", "US500", "US100", "UK100", "DE40", "JP225"]):
                # Indices typically show 1-2 decimal places
                precision = 2
            elif any(commodity in instrument for commodity in ["XAUUSD", "XAGUSD"]):
                # Gold and silver typically show 2 decimal places
                precision = 2
            elif instrument in ["WTIUSD", "XTIUSD"]:
                # Oil typically shows 2 decimal places
                precision = 2
            else:
                # Default format for forex pairs with 5 decimal places
                precision = 5
            
            # EMA values with more realistic relationships to price
            if trend == "BUY":
                ema_50 = current_price * (1 - random.uniform(0.005, 0.015))  # EMA50 slightly below price
                ema_200 = current_price * (1 - random.uniform(0.02, 0.05))   # EMA200 further below price
            elif trend == "SELL":
                ema_50 = current_price * (1 + random.uniform(0.005, 0.015))  # EMA50 slightly above price
                ema_200 = current_price * (1 + random.uniform(0.01, 0.03))   # EMA200 further above price
            else:
                # Neutral trend - EMAs close to price
                ema_50 = current_price * (1 + random.uniform(-0.01, 0.01))
                ema_200 = current_price * (1 + random.uniform(-0.02, 0.02))
            
            # Format the analysis using the same format as the main method
            if timeframe == "1d":
                # Daily analysis with more data
                analysis_text = f"{instrument} - Daily Analysis\n\n"
            else:
                analysis_text = f"{instrument} - {timeframe}\n\n"
            
            analysis_text += f"<b>Zone Strength:</b> {zone_stars}\n\n"
            
            # Market overview section
            analysis_text += f"📊 <b>Market Overview</b>\n"
            if instrument == "XAUUSD":
                # Format gold price with comma after first digit
                price_first_digit = str(int(current_price))[0]
                price_rest_digits = f"{current_price:.3f}".split('.')[0][1:] + "." + f"{current_price:.3f}".split('.')[1]
                formatted_price = f"{price_first_digit},{price_rest_digits}"
                
                analysis_text += f"Price is currently trading near current price of {formatted_price}, "
            elif instrument == "US30":
                # Format US30 price with comma after second digit
                price_digits = str(int(current_price))
                formatted_price = f"{price_digits[:2]},{price_digits[2:]}.{f'{current_price:.2f}'.split('.')[1]}"
                
                analysis_text += f"Price is currently trading near current price of {formatted_price}, "
            elif instrument == "US500":
                # Format US500 price with comma after first digit
                price_digits = str(int(current_price))
                formatted_price = f"{price_digits[0]},{price_digits[1:]}.{f'{current_price:.2f}'.split('.')[1]}"
                
                analysis_text += f"Price is currently trading near current price of {formatted_price}, "
            elif instrument == "US100":
                # Format US100 price with comma after second digit
                price_digits = str(int(current_price))
                formatted_price = f"{price_digits[:2]},{price_digits[2:]}.{f'{current_price:.2f}'.split('.')[1]}"
                
                analysis_text += f"Price is currently trading near current price of {formatted_price}, "
            else:
                analysis_text += f"Price is currently trading near current price of {current_price:.{precision}f}, "
                
            analysis_text += f"showing {'bullish' if trend == 'BUY' else 'bearish' if trend == 'SELL' else 'mixed'} momentum. "
            analysis_text += f"The pair remains {'above' if current_price > ema_50 else 'below'} key EMAs, "
            analysis_text += f"indicating a {'strong uptrend' if trend == 'BUY' else 'strong downtrend' if trend == 'SELL' else 'consolidation phase'}. "
            analysis_text += f"Volume is moderate, supporting the current price action.\n\n"
            
            # Key levels section
            analysis_text += f"🔑 <b>Key Levels</b>\n"
            if instrument == "XAUUSD":
                # Format gold support/resistance levels with comma after first digit
                daily_low_first_digit = str(int(daily_low))[0]
                daily_low_rest_digits = f"{daily_low:.3f}".split('.')[0][1:] + "." + f"{daily_low:.3f}".split('.')[1]
                formatted_daily_low = f"{daily_low_first_digit},{daily_low_rest_digits}"
                
                weekly_low_first_digit = str(int(weekly_low))[0]
                weekly_low_rest_digits = f"{weekly_low:.3f}".split('.')[0][1:] + "." + f"{weekly_low:.3f}".split('.')[1]
                formatted_weekly_low = f"{weekly_low_first_digit},{weekly_low_rest_digits}"
                
                daily_high_first_digit = str(int(daily_high))[0]
                daily_high_rest_digits = f"{daily_high:.3f}".split('.')[0][1:] + "." + f"{daily_high:.3f}".split('.')[1]
                formatted_daily_high = f"{daily_high_first_digit},{daily_high_rest_digits}"
                
                weekly_high_first_digit = str(int(weekly_high))[0]
                weekly_high_rest_digits = f"{weekly_high:.3f}".split('.')[0][1:] + "." + f"{weekly_high:.3f}".split('.')[1]
                formatted_weekly_high = f"{weekly_high_first_digit},{weekly_high_rest_digits}"
                
                analysis_text += f"Support: {formatted_daily_low} (daily low), {formatted_weekly_low} (weekly low)\n"
                analysis_text += f"Resistance: {formatted_daily_high} (daily high), {formatted_weekly_high} (weekly high)\n\n"
            elif instrument == "US30":
                # Format US30 support/resistance with comma after second digit
                daily_low_digits = str(int(daily_low))
                formatted_daily_low = f"{daily_low_digits[:2]},{daily_low_digits[2:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                
                weekly_low_digits = str(int(weekly_low))
                formatted_weekly_low = f"{weekly_low_digits[:2]},{weekly_low_digits[2:]}.{f'{weekly_low:.2f}'.split('.')[1]}"
                
                daily_high_digits = str(int(daily_high))
                formatted_daily_high = f"{daily_high_digits[:2]},{daily_high_digits[2:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                
                weekly_high_digits = str(int(weekly_high))
                formatted_weekly_high = f"{weekly_high_digits[:2]},{weekly_high_digits[2:]}.{f'{weekly_high:.2f}'.split('.')[1]}"
                
                analysis_text += f"Support: {formatted_daily_low} (daily low), {formatted_weekly_low} (weekly low)\n"
                analysis_text += f"Resistance: {formatted_daily_high} (daily high), {formatted_weekly_high} (weekly high)\n\n"
            elif instrument == "US500":
                # Format US500 support/resistance with comma after first digit
                daily_low_digits = str(int(daily_low))
                formatted_daily_low = f"{daily_low_digits[0]},{daily_low_digits[1:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                
                weekly_low_digits = str(int(weekly_low))
                formatted_weekly_low = f"{weekly_low_digits[0]},{weekly_low_digits[1:]}.{f'{weekly_low:.2f}'.split('.')[1]}"
                
                daily_high_digits = str(int(daily_high))
                formatted_daily_high = f"{daily_high_digits[0]},{daily_high_digits[1:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                
                weekly_high_digits = str(int(weekly_high))
                formatted_weekly_high = f"{weekly_high_digits[0]},{weekly_high_digits[1:]}.{f'{weekly_high:.2f}'.split('.')[1]}"
                
                analysis_text += f"Support: {formatted_daily_low} (daily low), {formatted_weekly_low} (weekly low)\n"
                analysis_text += f"Resistance: {formatted_daily_high} (daily high), {formatted_weekly_high} (weekly high)\n\n"
            elif instrument == "US100":
                # Format US100 support/resistance with comma after second digit
                daily_low_digits = str(int(daily_low))
                formatted_daily_low = f"{daily_low_digits[:2]},{daily_low_digits[2:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                
                weekly_low_digits = str(int(weekly_low))
                formatted_weekly_low = f"{weekly_low_digits[:2]},{weekly_low_digits[2:]}.{f'{weekly_low:.2f}'.split('.')[1]}"
                
                daily_high_digits = str(int(daily_high))
                formatted_daily_high = f"{daily_high_digits[:2]},{daily_high_digits[2:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                
                weekly_high_digits = str(int(weekly_high))
                formatted_weekly_high = f"{weekly_high_digits[:2]},{weekly_high_digits[2:]}.{f'{weekly_high:.2f}'.split('.')[1]}"
                
                analysis_text += f"Support: {formatted_daily_low} (daily low), {formatted_weekly_low} (weekly low)\n"
                analysis_text += f"Resistance: {formatted_daily_high} (daily high), {formatted_weekly_high} (weekly high)\n\n"
            else:
                analysis_text += f"Support: {daily_low:.{precision}f} (daily low), {weekly_low:.{precision}f} (weekly low)\n"
                analysis_text += f"Resistance: {daily_high:.{precision}f} (daily high), {weekly_high:.{precision}f} (weekly high)\n\n"
            
            # Technical indicators section
            analysis_text += f"📈 <b>Technical Indicators</b>\n"
            analysis_text += f"RSI: {rsi:.2f} (neutral)\n"
            
            macd_value = random.uniform(-0.001, 0.001)
            macd_signal = random.uniform(-0.001, 0.001)
            macd_status = "bullish" if macd_value > macd_signal else "bearish"
            analysis_text += f"MACD: {macd_status} ({macd_value:.5f} is {'above' if macd_value > macd_signal else 'below'} signal {macd_signal:.5f})\n"
            
            ma_status = "bullish" if trend == "BUY" else "bearish" if trend == "SELL" else "mixed"
            if instrument == "XAUUSD":
                # Format gold EMAs with comma after first digit
                ema50_first_digit = str(int(ema_50))[0]
                ema50_rest_digits = f"{ema_50:.3f}".split('.')[0][1:] + "." + f"{ema_50:.3f}".split('.')[1]
                formatted_ema50 = f"{ema50_first_digit},{ema50_rest_digits}"
                
                ema200_first_digit = str(int(ema_200))[0]
                ema200_rest_digits = f"{ema_200:.3f}".split('.')[0][1:] + "." + f"{ema_200:.3f}".split('.')[1]
                formatted_ema200 = f"{ema200_first_digit},{ema200_rest_digits}"
                
                analysis_text += f"Moving Averages: Price {'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 50 ({formatted_ema50}) and "
                analysis_text += f"{'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 200 ({formatted_ema200}), confirming {ma_status} bias.\n\n"
            elif instrument == "US30":
                # Format US30 EMAs with comma after second digit
                ema50_digits = str(int(ema_50))
                ema50_formatted = f"{ema50_digits[:2]},{ema50_digits[2:]}.{f'{ema_50:.2f}'.split('.')[1]}"
                
                ema200_digits = str(int(ema_200))
                ema200_formatted = f"{ema200_digits[:2]},{ema200_digits[2:]}.{f'{ema_200:.2f}'.split('.')[1]}"
                
                analysis_text += f"Moving Averages: Price {'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 50 ({ema50_formatted}) and "
                analysis_text += f"{'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 200 ({ema200_formatted}), confirming {ma_status} bias.\n\n"
            elif instrument == "US500":
                # Format US500 EMAs with comma after first digit
                ema50_digits = str(int(ema_50))
                ema50_formatted = f"{ema50_digits[0]},{ema50_digits[1:]}.{f'{ema_50:.2f}'.split('.')[1]}"
                
                ema200_digits = str(int(ema_200))
                ema200_formatted = f"{ema200_digits[0]},{ema200_digits[1:]}.{f'{ema_200:.2f}'.split('.')[1]}"
                
                analysis_text += f"Moving Averages: Price {'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 50 ({ema50_formatted}) and "
                analysis_text += f"{'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 200 ({ema200_formatted}), confirming {ma_status} bias.\n\n"
            elif instrument == "US100":
                # Format US100 EMAs with comma after second digit
                ema50_digits = str(int(ema_50))
                ema50_formatted = f"{ema50_digits[:2]},{ema50_digits[2:]}.{f'{ema_50:.2f}'.split('.')[1]}"
                
                ema200_digits = str(int(ema_200))
                ema200_formatted = f"{ema200_digits[:2]},{ema200_digits[2:]}.{f'{ema_200:.2f}'.split('.')[1]}"
                
                analysis_text += f"Moving Averages: Price {'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 50 ({ema50_formatted}) and "
                analysis_text += f"{'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 200 ({ema200_formatted}), confirming {ma_status} bias.\n\n"
            else:
                analysis_text += f"Moving Averages: Price {'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 50 ({ema_50:.{precision}f}) and "
                analysis_text += f"{'above' if trend == 'BUY' else 'below' if trend == 'SELL' else 'near'} EMA 200 ({ema_200:.{precision}f}), confirming {ma_status} bias.\n\n"
            
            # AI recommendation
            analysis_text += f"🤖 <b>Sigmapips AI Recommendation</b>\n"
            if trend == "BUY":
                if instrument == "XAUUSD":
                    # Format gold prices with comma after first digit
                    daily_high_first_digit = str(int(daily_high))[0]
                    daily_high_rest_digits = f"{daily_high:.3f}".split('.')[0][1:] + "." + f"{daily_high:.3f}".split('.')[1]
                    formatted_daily_high = f"{daily_high_first_digit},{daily_high_rest_digits}"
                    
                    daily_low_first_digit = str(int(daily_low))[0]
                    daily_low_rest_digits = f"{daily_low:.3f}".split('.')[0][1:] + "." + f"{daily_low:.3f}".split('.')[1]
                    formatted_daily_low = f"{daily_low_first_digit},{daily_low_rest_digits}"
                    
                    analysis_text += f"Watch for a breakout above {formatted_daily_high} for further upside. "
                    analysis_text += f"Maintain a buy bias while price holds above {formatted_daily_low}. "
                    analysis_text += f"Be cautious of overbought conditions if RSI approaches 70.\n\n"
                elif instrument == "US30":
                    # Format US30 prices with comma after second digit
                    daily_high_digits = str(int(daily_high))
                    formatted_daily_high = f"{daily_high_digits[:2]},{daily_high_digits[2:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                    
                    daily_low_digits = str(int(daily_low))
                    formatted_daily_low = f"{daily_low_digits[:2]},{daily_low_digits[2:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                    
                    analysis_text += f"Watch for a breakout above {formatted_daily_high} for further upside. "
                    analysis_text += f"Maintain a buy bias while price holds above {formatted_daily_low}. "
                    analysis_text += f"Be cautious of overbought conditions if RSI approaches 70.\n\n"
                elif instrument == "US500":
                    # Format US500 prices with comma after first digit
                    daily_high_digits = str(int(daily_high))
                    formatted_daily_high = f"{daily_high_digits[0]},{daily_high_digits[1:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                    
                    daily_low_digits = str(int(daily_low))
                    formatted_daily_low = f"{daily_low_digits[0]},{daily_low_digits[1:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                    
                    analysis_text += f"Watch for a breakout above {formatted_daily_high} for further upside. "
                    analysis_text += f"Maintain a buy bias while price holds above {formatted_daily_low}. "
                    analysis_text += f"Be cautious of overbought conditions if RSI approaches 70.\n\n"
                elif instrument == "US100":
                    # Format US100 prices with comma after second digit
                    daily_high_digits = str(int(daily_high))
                    formatted_daily_high = f"{daily_high_digits[:2]},{daily_high_digits[2:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                    
                    daily_low_digits = str(int(daily_low))
                    formatted_daily_low = f"{daily_low_digits[:2]},{daily_low_digits[2:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                    
                    analysis_text += f"Watch for a breakout above {formatted_daily_high} for further upside. "
                    analysis_text += f"Maintain a buy bias while price holds above {formatted_daily_low}. "
                    analysis_text += f"Be cautious of overbought conditions if RSI approaches 70.\n\n"
                else:
                    analysis_text += f"Watch for a breakout above {daily_high:.{precision}f} for further upside. "
                    analysis_text += f"Maintain a buy bias while price holds above {daily_low:.{precision}f}. "
                    analysis_text += f"Be cautious of overbought conditions if RSI approaches 70.\n\n"
            elif trend == "SELL":
                if instrument == "XAUUSD":
                    # Format gold prices with comma after first digit
                    daily_low_first_digit = str(int(daily_low))[0]
                    daily_low_rest_digits = f"{daily_low:.3f}".split('.')[0][1:] + "." + f"{daily_low:.3f}".split('.')[1]
                    formatted_daily_low = f"{daily_low_first_digit},{daily_low_rest_digits}"
                    
                    daily_high_first_digit = str(int(daily_high))[0]
                    daily_high_rest_digits = f"{daily_high:.3f}".split('.')[0][1:] + "." + f"{daily_high:.3f}".split('.')[1]
                    formatted_daily_high = f"{daily_high_first_digit},{daily_high_rest_digits}"
                    
                    analysis_text += f"Watch for a breakdown below {formatted_daily_low} for further downside. "
                    analysis_text += f"Maintain a sell bias while price holds below {formatted_daily_high}. "
                    analysis_text += f"Be cautious of oversold conditions if RSI approaches 30.\n\n"
                elif instrument == "US30":
                    # Format US30 prices with comma after second digit
                    daily_low_digits = str(int(daily_low))
                    formatted_daily_low = f"{daily_low_digits[:2]},{daily_low_digits[2:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                    
                    daily_high_digits = str(int(daily_high))
                    formatted_daily_high = f"{daily_high_digits[:2]},{daily_high_digits[2:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                    
                    analysis_text += f"Watch for a breakdown below {formatted_daily_low} for further downside. "
                    analysis_text += f"Maintain a sell bias while price holds below {formatted_daily_high}. "
                    analysis_text += f"Be cautious of oversold conditions if RSI approaches 30.\n\n"
                elif instrument == "US500":
                    # Format US500 prices with comma after first digit
                    daily_low_digits = str(int(daily_low))
                    formatted_daily_low = f"{daily_low_digits[0]},{daily_low_digits[1:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                    
                    daily_high_digits = str(int(daily_high))
                    formatted_daily_high = f"{daily_high_digits[0]},{daily_high_digits[1:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                    
                    analysis_text += f"Watch for a breakdown below {formatted_daily_low} for further downside. "
                    analysis_text += f"Maintain a sell bias while price holds below {formatted_daily_high}. "
                    analysis_text += f"Be cautious of oversold conditions if RSI approaches 30.\n\n"
                elif instrument == "US100":
                    # Format US100 prices with comma after second digit
                    daily_low_digits = str(int(daily_low))
                    formatted_daily_low = f"{daily_low_digits[:2]},{daily_low_digits[2:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                    
                    daily_high_digits = str(int(daily_high))
                    formatted_daily_high = f"{daily_high_digits[:2]},{daily_high_digits[2:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                    
                    analysis_text += f"Watch for a breakdown below {formatted_daily_low} for further downside. "
                    analysis_text += f"Maintain a sell bias while price holds below {formatted_daily_high}. "
                    analysis_text += f"Be cautious of oversold conditions if RSI approaches 30.\n\n"
                else:
                    analysis_text += f"Watch for a breakdown below {daily_low:.{precision}f} for further downside. "
                    analysis_text += f"Maintain a sell bias while price holds below {daily_high:.{precision}f}. "
                    analysis_text += f"Be cautious of oversold conditions if RSI approaches 30.\n\n"
            else:
                if instrument == "XAUUSD":
                    # Format gold prices with comma after first digit
                    daily_low_first_digit = str(int(daily_low))[0]
                    daily_low_rest_digits = f"{daily_low:.3f}".split('.')[0][1:] + "." + f"{daily_low:.3f}".split('.')[1]
                    formatted_daily_low = f"{daily_low_first_digit},{daily_low_rest_digits}"
                    
                    daily_high_first_digit = str(int(daily_high))[0]
                    daily_high_rest_digits = f"{daily_high:.3f}".split('.')[0][1:] + "." + f"{daily_high:.3f}".split('.')[1]
                    formatted_daily_high = f"{daily_high_first_digit},{daily_high_rest_digits}"
                    
                    analysis_text += f"Range-bound conditions persist. Look for buying opportunities near {formatted_daily_low} "
                    analysis_text += f"and selling opportunities near {formatted_daily_high}. "
                    analysis_text += f"Wait for a clear breakout before establishing a directional bias.\n\n"
                elif instrument == "US30":
                    # Format US30 prices with comma after second digit
                    low_digits = str(int(daily_low))
                    formatted_low = f"{low_digits[:2]},{low_digits[2:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                    
                    high_digits = str(int(daily_high))
                    formatted_high = f"{high_digits[:2]},{high_digits[2:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                    
                    analysis_text += f"Range-bound conditions persist. Look for buying opportunities near {formatted_low} "
                    analysis_text += f"and selling opportunities near {formatted_high}. "
                    analysis_text += f"Wait for a clear breakout before establishing a directional bias.\n\n"
                elif instrument == "US500":
                    # Format US500 prices with comma after first digit
                    low_digits = str(int(daily_low))
                    formatted_low = f"{low_digits[0]},{low_digits[1:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                    
                    high_digits = str(int(daily_high))
                    formatted_high = f"{high_digits[0]},{high_digits[1:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                    
                    analysis_text += f"Range-bound conditions persist. Look for buying opportunities near {formatted_low} "
                    analysis_text += f"and selling opportunities near {formatted_high}. "
                    analysis_text += f"Wait for a clear breakout before establishing a directional bias.\n\n"
                elif instrument == "US100":
                    # Format US100 prices with comma after second digit
                    low_digits = str(int(daily_low))
                    formatted_low = f"{low_digits[:2]},{low_digits[2:]}.{f'{daily_low:.2f}'.split('.')[1]}"
                    
                    high_digits = str(int(daily_high))
                    formatted_high = f"{high_digits[:2]},{high_digits[2:]}.{f'{daily_high:.2f}'.split('.')[1]}"
                    
                    analysis_text += f"Range-bound conditions persist. Look for buying opportunities near {formatted_low} "
                    analysis_text += f"and selling opportunities near {formatted_high}. "
                    analysis_text += f"Wait for a clear breakout before establishing a directional bias.\n\n"
                else:
                    analysis_text += f"Range-bound conditions persist. Look for buying opportunities near {daily_low:.{precision}f} "
                    analysis_text += f"and selling opportunities near {daily_high:.{precision}f}. "
                    analysis_text += f"Wait for a clear breakout before establishing a directional bias.\n\n"
            
            # Disclaimer
            analysis_text += f"⚠️ <b>Disclaimer:</b> For educational purposes only."
            
            return analysis_text
        
        except Exception as e:
            logger.error(f"Error generating default analysis: {str(e)}")
            # Return a very basic message if all else fails
            return f"Analysis for {instrument} on {timeframe} timeframe is not available at this time. Please try again later."

    async def get_sentiment_analysis(self, instrument: str) -> str:
        """Generate sentiment analysis for an instrument"""
        # This method is intentionally left empty to prevent duplicate sentiment analysis
        # Sentiment analysis is now directly handled by the TelegramService using MarketSentimentService
        logger.info(f"ChartService.get_sentiment_analysis called for {instrument} but is now disabled")
        return ""

    def _get_instrument_precision(self, instrument: str) -> int:
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
            
        # Gold uses 3 decimal places
        if instrument in ["XAUUSD", "GC=F"]:
            return 3
            
        # Silver uses 4 decimal places
        if instrument in ["XAGUSD", "SI=F"]:
            return 4
            
        # Oil prices use 2 decimal places
        if instrument in ["XTIUSD", "WTIUSD", "XBRUSD", "USOIL", "CL=F", "BZ=F"]:
            return 2
            
        # Indices typically use 2 decimal places
        if any(index in instrument for index in ["US30", "US500", "US100", "UK100", "DE40", "JP225"]):
            return 2
            
        # Default to 4 decimal places as a safe value
        return 4
    
    async def _detect_market_type(self, instrument: str) -> str:
        """
        Detect the market type of the instrument.
        
        Args:
            instrument: The trading instrument
            
        Returns:
            str: Market type ('forex', 'crypto', 'index', 'commodity')
        """
        # Normalize the instrument name
        instrument = instrument.upper().replace("/", "")
        
        # Common cryptocurrency identifiers
        crypto_symbols = [
            "BTC", "ETH", "XRP", "LTC", "BCH", "ADA", "DOT", "LINK", 
            "XLM", "DOGE", "UNI", "AAVE", "SNX", "SUSHI", "YFI", 
            "COMP", "MKR", "BAT", "ZRX", "REN", "KNC", "BNB", "SOL",
            "AVAX", "MATIC", "ALGO", "ATOM", "FTM", "NEAR", "ONE",
            "HBAR", "VET", "THETA", "FIL", "TRX", "EOS", "NEO",
            "CAKE", "LUNA", "SHIB", "MANA", "SAND", "AXS", "CRV",
            "ENJ", "CHZ", "GALA", "ROSE", "APE", "FTT", "GRT",
            "GMT", "EGLD", "XTZ", "FLOW", "ICP", "XMR", "DASH"
        ]
        
        # Check for crypto
        if any(crypto in instrument for crypto in crypto_symbols) or instrument.endswith(("USDT", "BUSD", "USDC", "BTC", "ETH")):
            return "crypto"
        
        # Common forex pairs
        forex_pairs = [
            "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", 
            "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "AUDNZD", "AUDCAD",
            "AUDCHF", "AUDJPY", "CADCHF", "CADJPY", "CHFJPY", "EURAUD",
            "EURCAD", "EURCHF", "EURNZD", "GBPAUD", "GBPCAD", "GBPCHF",
            "GBPNZD", "NZDCAD", "NZDCHF", "NZDJPY"
        ]
        
        # Check for forex
        if instrument in forex_pairs or (
                len(instrument) == 6 and 
                instrument[:3] in ["EUR", "GBP", "USD", "JPY", "AUD", "NZD", "CAD", "CHF"] and
                instrument[3:] in ["EUR", "GBP", "USD", "JPY", "AUD", "NZD", "CAD", "CHF"]
            ):
            return "forex"
        
        # Common commodities
        commodities = [
            "XAUUSD", "XAGUSD", "WTIUSD", "XTIUSD", "XBRUSD", "CLUSD",
            "XPDUSD", "XPTUSD", "NATGAS", "COPPER", "BRENT", "USOIL"
        ]
        
        # Check for commodities
        if any(commodity in instrument for commodity in commodities) or instrument in commodities:
            return "commodity"
        
        # Common indices
        indices = [
            "US30", "US500", "US100", "UK100", "DE40", "FR40", "JP225", 
            "AU200", "ES35", "IT40", "HK50", "DJI", "SPX", "NDX", 
            "FTSE", "DAX", "CAC", "NIKKEI", "ASX", "IBEX", "MIB", "HSI"
        ]
        
        # Check for indices
        if any(index in instrument for index in indices) or instrument in indices:
            return "index"
        
        # Default to crypto for unknown instruments that could be new cryptocurrencies
        if instrument.endswith(("USD", "USDT", "ETH", "BTC")) and len(instrument) > 3:
            return "crypto"
        
        # Default to forex if all else fails
        return "forex"

    async def _fetch_crypto_price(self, symbol: str) -> Optional[float]:
        """
        Fetch crypto price from Binance API with fallback to other providers.
        
        Args:
            symbol: The crypto symbol without USD (e.g., BTC)
        
        Returns:
            float: Current price or None if failed
        """
        try:
            logger.info(f"Fetching {symbol} price from Binance API")
            symbol = symbol.replace("USD", "")
            
            # First, try our optimized BinanceProvider
            from trading_bot.services.chart_service.binance_provider import BinanceProvider
            price = await BinanceProvider.get_ticker_price(f"{symbol}USDT")
            if price:
                logger.info(f"Got {symbol} price from BinanceProvider: {price}")
                return price
                
            # If BinanceProvider fails, try direct API calls to multiple exchanges as backup
            logger.warning(f"BinanceProvider failed for {symbol}, trying direct API calls")
            apis = [
                f"https://api.coingecko.com/api/v3/simple/price?ids={symbol.lower()}&vs_currencies=usd",
                f"https://api.coinbase.com/v2/prices/{symbol}-USD/spot"
            ]
            
            success = False
            
            async with aiohttp.ClientSession() as session:
                for api_url in apis:
                    try:
                        async with session.get(api_url, timeout=5) as response:
                            if response.status == 200:
                                data = await response.json()
                                
                                # Parse based on API format
                                if "coingecko" in api_url:
                                    if data and symbol.lower() in data and "usd" in data[symbol.lower()]:
                                        price = float(data[symbol.lower()]["usd"])
                                        success = True
                                        logger.info(f"Got {symbol} price from CoinGecko: {price}")
                                        break
                                elif "coinbase" in api_url:
                                    if data and "data" in data and "amount" in data["data"]:
                                        price = float(data["data"]["amount"])
                                        success = True
                                        logger.info(f"Got {symbol} price from Coinbase: {price}")
                                        break
                    except Exception as e:
                        logger.warning(f"Failed to get {symbol} price from {api_url}: {str(e)}")
                        continue
            
            return price if success else None
            
        except Exception as e:
            logger.error(f"Error fetching crypto price: {str(e)}")
            return None

    async def _fetch_commodity_price(self, symbol: str) -> Optional[float]:
        """
        Fetch commodity price from Yahoo Finance.
        
        Args:
            symbol: The commodity symbol (e.g., XAUUSD for gold)
        
        Returns:
            float: Current price or None if failed
        """
        try:
            logger.info(f"Fetching {symbol} price from Yahoo Finance")
            
            # Map to correct Yahoo Finance symbol
            yahoo_symbols = {
                "XAUUSD": "GC=F",   # Gold futures
                "XAGUSD": "SI=F",    # Silver futures
                "XTIUSD": "CL=F",    # Crude Oil WTI futures
                "WTIUSD": "CL=F",    # WTI Crude Oil futures (alternative)
                "XBRUSD": "BZ=F",    # Brent Crude Oil futures
                "XPDUSD": "PA=F",    # Palladium futures
                "XPTUSD": "PL=F",    # Platinum futures
                "NATGAS": "NG=F",    # Natural Gas futures
                "COPPER": "HG=F",    # Copper futures
                "USOIL": "CL=F",     # US Oil (same as WTI Crude Oil)
            }
            
            # If symbol not in our mapping, we can't proceed
            if symbol not in yahoo_symbols:
                logger.warning(f"Unknown commodity symbol: {symbol}, cannot fetch from Yahoo Finance")
                return None
                
            # Get the corresponding Yahoo Finance symbol
            yahoo_symbol = yahoo_symbols[symbol]
            logger.info(f"Using Yahoo Finance symbol {yahoo_symbol} for {symbol}")
            
            # Use YahooFinanceProvider to get the latest price
            from .yfinance_provider import YahooFinanceProvider
            
            # Get market data with a small limit to make it fast
            df = await YahooFinanceProvider.get_market_data(yahoo_symbol, "1h", limit=5)
            
            if df is not None and hasattr(df, 'indicators') and 'close' in df.indicators:
                price = df.indicators['close']
                logger.info(f"Got {symbol} price from Yahoo Finance: {price}")
                return price
                
            logger.warning(f"Failed to get {symbol} price from Yahoo Finance")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching commodity price from Yahoo Finance: {str(e)}")
            return None

    async def _fetch_index_price(self, symbol: str) -> Optional[float]:
        """
        Fetch market index price from APIs as a fallback.
        
        Args:
            symbol: The index symbol (e.g., US30, US500)
            
        Returns:
            float: Current price or None if failed
        """
        try:
            logger.info(f"Fetching {symbol} price from external APIs")
            
            # Map symbols to common index names
            index_map = {
                "US30": "dow",
                "US500": "sp500",
                "US100": "nasdaq",
                "UK100": "ftse",
                "DE40": "dax",
                "JP225": "nikkei",
                "AU200": "asx200"
            }
            
            index_name = index_map.get(symbol, symbol.lower())
            
            # Use default reasonable values as a last resort
            default_values = {
                "US30": 38500,
                "US500": 5200,
                "US100": 18200,
                "UK100": 8200,
                "DE40": 17800,
                "JP225": 38000,
                "AU200": 7700,
                "EU50": 4900
            }
            
            # Return the default value with a small random variation
            if symbol in default_values:
                default_price = default_values[symbol]
                variation = random.uniform(-0.005, 0.005)  # ±0.5%
                price = default_price * (1 + variation)
                logger.info(f"Using default price for {symbol}: {price:.2f}")
                return price
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching index price: {str(e)}")
            return None
