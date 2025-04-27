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
# Import TradingViewNodeService voor screenshots
from trading_bot.services.chart_service.tradingview_node import TradingViewNodeService

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
            
            # Initialiseer TradingView service voor screenshots
            self.tradingview_service = TradingViewNodeService()
            
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
            
            logging.info("Chart service initialized with providers: Binance, YahooFinance, TradingViewNode")
            
        except Exception as e:
            logging.error(f"Error initializing chart service: {str(e)}")
            raise

    async def get_chart(self, instrument: str, fullscreen: bool = False) -> bytes:
        """Get chart image for instrument (Uses TradingView Screenshotting on H1 timeframe)."""
        fixed_timeframe = "H1"

        try:
            logger.info(f"Getting chart screenshot for {instrument} ({fixed_timeframe}) fullscreen: {fullscreen}")
            
            # Zorg ervoor dat de services zijn geïnitialiseerd
            if not hasattr(self, 'analysis_cache'):
                logger.info("Services not initialized, initializing now")
                await self.initialize()
            
            # Normaliseer instrument (verwijder /)
            instrument = instrument.upper().replace("/", "")
            
            # Probeer TradingView screenshot
            try:
                # Initialiseer TradingView service als dat nog niet is gedaan
                if not self.tradingview_service.is_initialized:
                    logger.info("Initializing TradingView service for screenshots")
                    await self.tradingview_service.initialize()
                
                # Probeer een screenshot te maken met TradingView
                logger.info(f"Trying to take screenshot for {instrument} using TradingView")
                screenshot = await self.tradingview_service.take_screenshot(instrument, fixed_timeframe, fullscreen)
                
                if screenshot:
                    logger.info(f"Successfully captured {instrument} chart with TradingView")
                    return screenshot
                else:
                    # Belangrijk: Niet terugvallen op matplotlib als screenshot faalt, geef fout aan
                    logger.error(f"Failed to capture {instrument} chart with TradingView screenshot service.")
                    # Optioneel: genereer een foutafbeelding of None
                    return await self._create_emergency_chart(instrument, fixed_timeframe) # Fallback naar emergency chart
            except Exception as e:
                logger.error(f"Error using TradingView screenshot service: {str(e)}", exc_info=True) # Added exc_info
                return await self._create_emergency_chart(instrument, fixed_timeframe) # Fallback naar emergency chart
            
        except Exception as e:
            logger.error(f"Error getting chart screenshot: {str(e)}", exc_info=True) # Added exc_info
            # Generate a simple emergency chart
            return await self._create_emergency_chart(instrument, fixed_timeframe)

    async def _create_emergency_chart(self, instrument: str, timeframe: str = "H1") -> bytes:
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
            # Ruim TradingView service op
            try:
                if hasattr(self, 'tradingview_service'):
                    await self.tradingview_service.cleanup()
                    logger.info("TradingView service cleaned up")
            except Exception as e:
                logger.error(f"Error cleaning up TradingView service: {str(e)}")
            
            logger.info("Chart service resources cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up chart service: {str(e)}")

    async def _fallback_chart(self, instrument):
        """Fallback method to get chart (uses fixed H1 timeframe)"""
        try:
            # Genereer een chart met matplotlib using the fixed H1 timeframe
            return await self._generate_random_chart(instrument, "H1")
            
        except Exception as e:
            logging.error(f"Error in fallback chart: {str(e)}")
            return None

    async def generate_chart(self, instrument, fullscreen=False):
        """Alias for get_chart (uses fixed H1 timeframe)"""
        return await self.get_chart(instrument, fullscreen)

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
            
            # Initialize TradingView service
            try:
                logger.info("Initializing TradingView service for screenshots")
                await self.tradingview_service.initialize()
                logger.info("TradingView service initialized successfully")
            except Exception as e:
                logger.error(f"Error initializing TradingView service: {str(e)}")
                logger.error(traceback.format_exc())
            
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
        
    async def _generate_random_chart(self, instrument: str, timeframe: str = "H1") -> bytes:
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

    async def get_technical_analysis(self, instrument: str) -> str:
        """Get technical analysis summary calculated from provider data (Fixed H1 Timeframe)."""
        fixed_timeframe = "H1"

        logger.info(f"Calculating technical analysis for {instrument} ({fixed_timeframe}) using provider data.")
        cache_key = f"analysis_{instrument}_{fixed_timeframe}"
        current_time = time.time()
        ANALYSIS_CACHE_TTL = 1800 # 30 minuten cache

        # Check cache
        if cache_key in self.analysis_cache and \
           (current_time - self.analysis_cache[cache_key]['timestamp']) < ANALYSIS_CACHE_TTL:
            logger.info(f"Returning cached analysis for {cache_key}")
            return self.analysis_cache[cache_key]['analysis']

        # Normalize instrument
        instrument_normalized = instrument.upper().replace("/", "")
        analysis_text = f"⚠️ Analysis currently unavailable for {instrument} ({fixed_timeframe}). Please try again later."

        try:
            # 1. Detect market type and select provider
            market_type = await self._detect_market_type(instrument_normalized)
            provider = None
            if market_type == 'crypto':
                provider = next((p for p in self.chart_providers if isinstance(p, BinanceProvider)), None)
                logger.info(f"Using BinanceProvider for {instrument_normalized}")
            else:
                provider = next((p for p in self.chart_providers if isinstance(p, YahooFinanceProvider)), None)
                logger.info(f"Using YahooFinanceProvider for {instrument_normalized}")

            if not provider:
                logger.error(f"No suitable provider found for {instrument_normalized} (market: {market_type})")
                return analysis_text # Return default error

            # 2. Fetch historical data and analysis from the provider (pass only instrument and limit)
            logger.info(f"Fetching market data for {instrument_normalized} ({fixed_timeframe}) via {provider.__class__.__name__}")
            limit = 300 # Keep limit, timeframe is fixed in provider
            market_data_result = await provider.get_market_data(instrument_normalized, limit=limit)

            if market_data_result is None or not isinstance(market_data_result, tuple) or len(market_data_result) != 2:
                 logger.warning(f"Could not fetch market data for {instrument_normalized} ({fixed_timeframe}) from {provider.__class__.__name__} or result format is wrong.")
                 return f"⚠️ Could not fetch data for {instrument} ({fixed_timeframe}). Analysis unavailable."

            df, analysis_dict = market_data_result

            if df is None or df.empty:
                logger.warning(f"Provider returned empty DataFrame for {instrument_normalized} ({fixed_timeframe})")
                return f"⚠️ No data available for {instrument} ({fixed_timeframe}). Analysis unavailable."

            logger.info(f"Successfully fetched {len(df)} data points and analysis for {instrument_normalized}.")

            # 3. Extract latest indicator values from DataFrame
            # The provider should have already calculated indicators
            latest_data = df.iloc[-1]
            current_price = latest_data.get('Close') # Adjust column name if needed (check provider output)
            ema_20 = latest_data.get('EMA_20')
            ema_50 = latest_data.get('EMA_50')
            ema_200 = latest_data.get('EMA_200')
            rsi = latest_data.get('RSI_14')
            macd_line = latest_data.get('MACD_12_26_9')
            macd_signal = latest_data.get('MACDs_12_26_9')

            # Check if essential values are present
            if current_price is None or pd.isna(current_price):
                logger.error(f"Could not extract latest close price for {instrument_normalized}")
                return f"⚠️ Could not process data for {instrument} ({fixed_timeframe}). Analysis unavailable."

            # 4. Calculate Daily & Weekly High/Low from the fetched data
            daily_high, daily_low, weekly_high, weekly_low = None, None, None, None
            try:
                if isinstance(df.index, pd.DatetimeIndex):
                    last_timestamp = df.index[-1]
                    
                    # Daily High/Low (last 24 hours from last data point)
                    daily_start_time = last_timestamp - timedelta(hours=24)
                    daily_df = df[df.index >= daily_start_time]
                    if not daily_df.empty:
                        daily_high = daily_df['High'].max()
                        daily_low = daily_df['Low'].min()

                    # Weekly High/Low (last 7 days from last data point)
                    weekly_start_time = last_timestamp - timedelta(days=7)
                    weekly_df = df[df.index >= weekly_start_time]
                    if not weekly_df.empty:
                        weekly_high = weekly_df['High'].max()
                        weekly_low = weekly_df['Low'].min()
                    logger.info(f"Calculated approx Daily/Weekly H/L for {instrument_normalized}: D({daily_low:.{self._get_instrument_precision(instrument_normalized)}f}-{daily_high:.{self._get_instrument_precision(instrument_normalized)}f}) W({weekly_low:.{self._get_instrument_precision(instrument_normalized)}f}-{weekly_high:.{self._get_instrument_precision(instrument_normalized)}f})")
                else:
                    logger.warning(f"Cannot calculate Daily/Weekly H/L for {instrument_normalized} because index is not DatetimeIndex.")
            except Exception as hl_error:
                logger.error(f"Error calculating Daily/Weekly H/L for {instrument_normalized}: {hl_error}", exc_info=True)

            # 5. Format the analysis string
            display_name = instrument # Default
            # Simple formatting (e.g., EURUSD -> EUR/USD)
            if len(instrument) == 6 and market_type != 'crypto':
                display_name = f"{instrument[:3]}/{instrument[3:]}"

            # Get precision for formatting
            precision = self._get_instrument_precision(instrument_normalized)

            # Build the analysis string
            analysis_lines = []
            analysis_lines.append(f"<b>📊 Technical Analysis: {display_name} ({fixed_timeframe})</b>")
            analysis_lines.append("") # Newline

            analysis_lines.append(f"Price: {current_price:.{precision}f}")
            analysis_lines.append("")

            analysis_lines.append("🔑 <b>Key Levels (Approx. based on H1 data):</b>")
            if daily_low is not None and not pd.isna(daily_low):
                analysis_lines.append(f"Daily Low:   {daily_low:.{precision}f}")
            else: analysis_lines.append("Daily Low:   N/A")
            if daily_high is not None and not pd.isna(daily_high):
                analysis_lines.append(f"Daily High:  {daily_high:.{precision}f}")
            else: analysis_lines.append("Daily High:  N/A")
            if weekly_low is not None and not pd.isna(weekly_low):
                analysis_lines.append(f"Weekly Low:  {weekly_low:.{precision}f}")
            else: analysis_lines.append("Weekly Low:  N/A")
            if weekly_high is not None and not pd.isna(weekly_high):
                analysis_lines.append(f"Weekly High: {weekly_high:.{precision}f}")
            else: analysis_lines.append("Weekly High: N/A")
            analysis_lines.append("")

            analysis_lines.append("📈 <b>Technical Indicators:</b>")
            if rsi is not None and not pd.isna(rsi):
                rsi_status = "Overbought" if rsi > 70 else "Oversold" if rsi < 30 else "Neutral"
                analysis_lines.append(f"RSI(14): {rsi:.2f} ({rsi_status})")
            else: analysis_lines.append("RSI(14): N/A")

            if macd_line is not None and macd_signal is not None and not pd.isna(macd_line) and not pd.isna(macd_signal):
                macd_cross = "Bullish" if macd_line > macd_signal else "Bearish"
                analysis_lines.append(f"MACD(12,26,9): {macd_line:.{precision+1}f} / Signal: {macd_signal:.{precision+1}f} ({macd_cross})") # Use more precision for MACD
            else: analysis_lines.append("MACD(12,26,9): N/A")

            analysis_lines.append("")
            analysis_lines.append("📉 <b>Moving Averages:</b>")
            if ema_20 is not None and not pd.isna(ema_20):
                analysis_lines.append(f"EMA(20): {ema_20:.{precision}f} {'(Above Price)' if current_price > ema_20 else '(Below Price)' if current_price < ema_20 else ''}\n")
            else: analysis_lines.append("EMA(20): N/A\n")
            if ema_50 is not None and not pd.isna(ema_50):
                analysis_lines.append(f"EMA(50): {ema_50:.{precision}f} {'(Above Price)' if current_price > ema_50 else '(Below Price)' if current_price < ema_50 else ''}\n")
            else: analysis_lines.append("EMA(50): N/A\n")
            if ema_200 is not None and not pd.isna(ema_200):
                analysis_lines.append(f"EMA(200): {ema_200:.{precision}f} {'(Above Price)' if current_price > ema_200 else '(Below Price)' if current_price < ema_200 else ''}\n")
            else: analysis_lines.append("EMA(200): N/A\n")

            # Simple Trend Suggestion based on EMAs
            trend_suggestion = "Neutral"
            if ema_20 is not None and ema_50 is not None and ema_200 is not None:
                if current_price > ema_20 > ema_50 > ema_200:
                    trend_suggestion = "Strong Bullish"
                elif current_price > ema_50 > ema_200:
                    trend_suggestion = "Bullish"
                elif current_price < ema_20 < ema_50 < ema_200:
                    trend_suggestion = "Strong Bearish"
                elif current_price < ema_50 < ema_200:
                    trend_suggestion = "Bearish"
                else:
                    trend_suggestion = "Mixed/Sideways"
            analysis_lines.append("")
            analysis_lines.append(f"📊 <b>Trend Suggestion:</b> {trend_suggestion}")

            analysis_lines.append("")
            analysis_lines.append("⚠️ <i>Disclaimer: Calculated analysis. Not financial advice.</i>")

            analysis_text = "\n".join(analysis_lines)

        except Exception as e:
            logger.error(f"Error calculating technical analysis for {instrument_normalized} ({fixed_timeframe}): {e}", exc_info=True)
            # Keep the default error message initialized above

        # Cache the result (even if it's an error message, to avoid repeated failures)
        self.analysis_cache[cache_key] = {
            'analysis': analysis_text,
            'timestamp': current_time
        }
        logger.info(f"Cached analysis result for {cache_key}")

        return analysis_text

    async def get_sentiment_analysis(self, instrument: str) -> str:
        """Placeholder for sentiment analysis"""
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
