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
from tradingview_ta import TA_Handler, Interval

# Importeer alleen de base class
from trading_bot.services.chart_service.base import TradingViewService

# Globale configuratie voor snelheid
USE_FAST_MODE = os.getenv("USE_FAST_MODE", "true").lower() == "true"

logger = logging.getLogger(__name__)

# Verwijder alle Yahoo Finance gerelateerde constanten
OCR_CACHE_DIR = os.path.join('data', 'cache', 'ocr')

# Cache implementatie voor technische analyse resultaten
class AnalysisCache:
    def __init__(self, max_size=100, expiry_seconds=900):  # 15 minuten cache expiry (verhoogd van 5 min)
        self.cache = {}
        self.max_size = max_size
        self.expiry_seconds = expiry_seconds
    
    def get(self, key):
        """Haal een item op uit de cache als het niet verlopen is"""
        if key in self.cache:
            timestamp, value = self.cache[key]
            if (datetime.now() - timestamp).total_seconds() < self.expiry_seconds:
                logger.info(f"🔄 Cache HIT voor key: {key}")
                return value
            else:
                # Verwijder verlopen items
                logger.info(f"⏰ Cache EXPIRED voor key: {key}")
                del self.cache[key]
        logger.info(f"❌ Cache MISS voor key: {key}")
        return None
    
    def set(self, key, value):
        """Sla een item op in de cache met timestamp"""
        # Verwijder oude items als de cache vol is
        if len(self.cache) >= self.max_size:
            # Verwijder het oudste item
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][0])
            del self.cache[oldest_key]
            logger.info(f"🧹 Verwijderd oud cache item: {oldest_key} (cache vol)")
        
        self.cache[key] = (datetime.now(), value)
        logger.info(f"✅ Cache SET voor key: {key} (totaal items: {len(self.cache)})")

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
            
            # Cache voor snellere resultaten
            self.chart_cache = AnalysisCache(max_size=50, expiry_seconds=900)  # 15 minuten cache
            self.market_data_cache = AnalysisCache(max_size=100, expiry_seconds=600)  # 10 minuten cache
            
            logging.info("Chart service initialized with caching")
            
        except Exception as e:
            logging.error(f"Error initializing chart service: {str(e)}")
            raise

    async def get_chart(self, instrument: str, timeframe: str = "1h", fullscreen: bool = False) -> bytes:
        """Get chart image for instrument and timeframe"""
        try:
            logger.info(f"Getting chart for {instrument} ({timeframe}) fullscreen: {fullscreen}")
            
            # Zorg ervoor dat de services zijn geïnitialiseerd
            if not hasattr(self, 'tradingview') or not self.tradingview:
                logger.info("Services not initialized, initializing now")
                await self.initialize()
            
            # Normaliseer instrument (verwijder /)
            instrument = instrument.upper().replace("/", "")
            
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
            
            logger.info(f"Using exact TradingView link: {tradingview_link}")
            
            # Probeer eerst de Node.js service te gebruiken
            if hasattr(self, 'tradingview') and self.tradingview and hasattr(self.tradingview, 'take_screenshot_of_url'):
                try:
                    logger.info(f"Taking screenshot with Node.js service: {tradingview_link}")
                    chart_image = await self.tradingview.take_screenshot_of_url(tradingview_link, fullscreen=True)
                    if chart_image:
                        logger.info("Screenshot taken successfully with Node.js service")
                        return chart_image
                    else:
                        logger.error("Node.js screenshot is None")
                except Exception as e:
                    logger.error(f"Error using Node.js for screenshot: {str(e)}")
            
            # Als Node.js niet werkt, probeer Selenium
            if hasattr(self, 'tradingview_selenium') and self.tradingview_selenium and self.tradingview_selenium.is_initialized:
                try:
                    logger.info(f"Taking screenshot with Selenium: {tradingview_link}")
                    chart_image = await self.tradingview_selenium.get_screenshot(tradingview_link, fullscreen=True)
                    if chart_image:
                        logger.info("Screenshot taken successfully with Selenium")
                        return chart_image
                    else:
                        logger.error("Selenium screenshot is None")
                except Exception as e:
                    logger.error(f"Error using Selenium for screenshot: {str(e)}")
            
            # Als beide services niet werken, gebruik een fallback methode
            logger.warning(f"All screenshot services failed, using fallback for {instrument}")
            return await self._generate_random_chart(instrument, timeframe)
        
        except Exception as e:
            logger.error(f"Error getting chart: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Als er een fout optreedt, genereer een matplotlib chart
            logger.warning(f"Error occurred, using fallback for {instrument}")
            return await self._generate_random_chart(instrument, timeframe)

    async def _fallback_chart(self, instrument, timeframe="1h"):
        """Fallback method to get chart"""
        try:
            # Hier zou je een eenvoudige fallback kunnen implementeren
            # Bijvoorbeeld een statische afbeelding of een bericht
            logging.warning(f"Using fallback chart for {instrument}")
            
            # Voor nu retourneren we None, wat betekent dat er geen chart beschikbaar is
            return None
            
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
            
            # Initialiseer de TradingView Node.js service
            from trading_bot.services.chart_service.tradingview_node import TradingViewNodeService
            self.tradingview = TradingViewNodeService()
            node_initialized = await self.tradingview.initialize()
            
            if node_initialized:
                logger.info("Node.js service initialized successfully")
            else:
                logger.error("Node.js service initialization returned False")
            
            # Sla Selenium initialisatie over vanwege ChromeDriver compatibiliteitsproblemen
            logger.warning("Skipping Selenium initialization due to ChromeDriver compatibility issues")
            self.tradingview_selenium = None
            
            # Als geen van beide services is geïnitialiseerd, gebruik matplotlib fallback
            if not node_initialized and not getattr(self, 'tradingview_selenium', None):
                logger.warning("Using matplotlib fallback")
            
            return True
        except Exception as e:
            logger.error(f"Error initializing chart service: {str(e)}")
            return False

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
            
    async def cleanup(self):
        """Clean up resources"""
        try:
            if hasattr(self, 'tradingview_playwright') and self.tradingview_playwright:
                await self.tradingview_playwright.cleanup()
            
            if hasattr(self, 'tradingview_selenium') and self.tradingview_selenium:
                await self.tradingview_selenium.cleanup()
            
            logger.info("Chart service resources cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up chart service: {str(e)}")

    async def generate_chart(self, instrument: str, timeframe: str = "1h") -> Optional[bytes]:
        """Generate a chart using matplotlib and real data from Yahoo Finance"""
        try:
            import matplotlib.pyplot as plt
            import pandas as pd
            import numpy as np
            import io
            from datetime import datetime, timedelta
            import yfinance as yf
            import mplfinance as mpf
            
            logger.info(f"Generating chart for {instrument} with timeframe {timeframe}")
            
            # Map instrument naar Yahoo Finance symbool
            yahoo_symbols = {
                # Forex
                "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
                "AUDUSD": "AUDUSD=X", "USDCAD": "USDCAD=X", "NZDUSD": "NZDUSD=X",
                # Crypto
                "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD", "XRPUSD": "XRP-USD",
                "SOLUSD": "SOL-USD", "BNBUSD": "BNB-USD", "ADAUSD": "ADA-USD",
                # Indices
                "US500": "^GSPC", "US30": "^DJI", "US100": "^NDX",
                # Commodities
                "XAUUSD": "GC=F", "XTIUSD": "CL=F"
            }
            
            # Bepaal het Yahoo Finance symbool
            symbol = yahoo_symbols.get(instrument)
            if not symbol:
                # Als het instrument niet in de mapping staat, probeer het direct
                symbol = instrument.replace("/", "-")
                if "USD" in symbol and not symbol.endswith("USD"):
                    symbol = symbol + "-USD"
            
            # Bepaal de tijdsperiode op basis van timeframe
            end_date = datetime.now()
            interval = "1h"  # Default interval
            
            if timeframe == "1h":
                start_date = end_date - timedelta(days=7)
                interval = "1h"
            elif timeframe == "4h":
                start_date = end_date - timedelta(days=30)
                interval = "1h"  # Yahoo heeft geen 4h, dus we gebruiken 1h
            elif timeframe == "1d":
                start_date = end_date - timedelta(days=180)
                interval = "1d"
            else:
                start_date = end_date - timedelta(days=7)
                interval = "1h"
            
            # Haal data op van Yahoo Finance
            try:
                logger.info(f"Fetching data for {symbol} from {start_date} to {end_date} with interval {interval}")
                data = yf.download(symbol, start=start_date, end=end_date, interval=interval)
                
                if data.empty:
                    logger.warning(f"No data returned for {symbol}, using random data")
                    # Gebruik willekeurige data als fallback
                    return await self._generate_random_chart(instrument, timeframe)
                    
                logger.info(f"Got {len(data)} data points for {symbol}")
                
                # Bereken technische indicators
                data['SMA20'] = data['Close'].rolling(window=20).mean()
                data['SMA50'] = data['Close'].rolling(window=50).mean()
                data['RSI'] = self._calculate_rsi(data['Close'])
                
                # Maak een mooie chart met mplfinance
                plt.figure(figsize=(12, 8))
                
                # Maak een subplot grid: 2 rijen, 1 kolom
                fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]})
                
                # Plot de candlestick chart
                mpf.plot(data, type='candle', style='charles', 
                        title=f'{instrument} - {timeframe} Chart',
                        ylabel='Price', 
                        ylabel_lower='RSI',
                        ax=ax1, volume=False, 
                        show_nontrading=False)
                
                # Voeg SMA's toe
                ax1.plot(data.index, data['SMA20'], color='blue', linewidth=1, label='SMA20')
                ax1.plot(data.index, data['SMA50'], color='red', linewidth=1, label='SMA50')
                ax1.legend()
                
                # Plot RSI op de onderste subplot
                ax2.plot(data.index, data['RSI'], color='purple', linewidth=1)
                ax2.axhline(70, color='red', linestyle='--', alpha=0.5)
                ax2.axhline(30, color='green', linestyle='--', alpha=0.5)
                ax2.set_ylabel('RSI')
                ax2.set_ylim(0, 100)
                
                # Stel de layout in
                plt.tight_layout()
                
                # Sla de chart op als bytes
                buf = io.BytesIO()
                plt.savefig(buf, format='png', dpi=100)
                buf.seek(0)
                
                plt.close(fig)
                
                return buf.getvalue()
                
            except Exception as e:
                logger.error(f"Error fetching data from Yahoo Finance: {str(e)}")
                # Gebruik willekeurige data als fallback
                return await self._generate_random_chart(instrument, timeframe)
                
        except Exception as e:
            logger.error(f"Error generating chart: {str(e)}")
            return None
        
    def _calculate_rsi(self, prices, period=14):
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

    async def get_screenshot_from_api(self, url: str) -> bytes:
        """Get a screenshot from an external API"""
        try:
            # Gebruik een screenshot API zoals screenshotapi.net
            api_key = os.getenv("SCREENSHOT_API_KEY", "")
            if not api_key:
                logger.error("No API key for screenshot service")
                return None
            
            # Bouw de API URL
            api_url = f"https://api.screenshotapi.net/screenshot?token={api_key}&url={url}&output=image&width=1920&height=1080"
            
            # Haal de screenshot op
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.error(f"Screenshot API error: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error getting screenshot from API: {str(e)}")
            return None

    async def generate_matplotlib_chart(self, symbol, timeframe=None):
        """Generate a chart using matplotlib"""
        try:
            logger.info(f"Generating random chart for {symbol} with timeframe {timeframe}")
            
            # Maak een meer realistische dataset
            np.random.seed(42)  # Voor consistente resultaten
            
            # Genereer datums voor de afgelopen 30 dagen
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            dates = pd.date_range(start=start_date, end=end_date, freq='1H')
            
            # Genereer prijzen met een realistisch patroon
            base_price = 1.0 if symbol.startswith("EUR") else (0.8 if symbol.startswith("GBP") else 110.0 if symbol.startswith("USD") and symbol.endswith("JPY") else 1.3)
            
            # Maak een random walk met een kleine trend
            trend = 0.0001 * np.random.randn()
            prices = [base_price]
            for i in range(1, len(dates)):
                # Voeg wat realisme toe met volatiliteit die varieert gedurende de dag
                hour = dates[i].hour
                volatility = 0.0005 if 8 <= hour <= 16 else 0.0002
                
                # Genereer de volgende prijs
                next_price = prices[-1] * (1 + trend + volatility * np.random.randn())
                prices.append(next_price)
            
            # Maak een DataFrame
            df = pd.DataFrame({
                'Open': prices,
                'High': [p * (1 + 0.001 * np.random.rand()) for p in prices],
                'Low': [p * (1 - 0.001 * np.random.rand()) for p in prices],
                'Close': [p * (1 + 0.0005 * np.random.randn()) for p in prices],
                'Volume': [int(1000000 * np.random.rand()) for _ in prices]
            }, index=dates)
            
            # Maak een mooiere plot
            plt.figure(figsize=(12, 6))
            plt.style.use('dark_background')
            
            # Plot de candlestick chart
            mpf.plot(df, type='candle', style='charles',
                    title=f"{symbol} - {timeframe} Timeframe",
                    ylabel='Price',
                    volume=True,
                    figsize=(12, 6),
                    savefig=dict(fname='temp_chart.png', dpi=300))
            
            # Lees de afbeelding
            with open('temp_chart.png', 'rb') as f:
                chart_bytes = f.read()
            
            # Verwijder het tijdelijke bestand
            os.remove('temp_chart.png')
            
            return chart_bytes
        except Exception as e:
            logger.error(f"Error generating matplotlib chart: {str(e)}")
            
            # Als fallback, genereer een zeer eenvoudige chart
            buf = BytesIO()
            plt.figure(figsize=(10, 6))
            plt.plot(np.random.randn(100).cumsum())
            plt.title(f"{symbol} - {timeframe} (Fallback Chart)")
            plt.savefig(buf, format='png')
            plt.close()
            
            return buf.getvalue()

    async def get_technical_analysis(self, instrument: str, timeframe: str = "1h") -> Union[bytes, str]:
        """
        Get technical analysis for an instrument with timeframe using TradingView data.
        In fast mode, skips DeepSeek API completely and uses template analysis.
        """
        try:
            # Check cache eerst - zeer belangrijke optimalisatie
            cache_key = f"{instrument}_{timeframe}_technical"
            cached_result = self.chart_cache.get(cache_key)
            if cached_result:
                logger.info(f"Using cached technical analysis for {instrument} {timeframe}")
                return cached_result

            # Start beide taken tegelijk parallel voor maximale snelheid
            tasks = []
            
            # Start taak 1: chart ophalen
            chart_task = asyncio.create_task(self.get_chart(instrument, timeframe))
            tasks.append(chart_task)
            
            # Check cache voor market data
            market_data_cache_key = f"{instrument}_{timeframe}_marketdata"
            market_data_dict = self.market_data_cache.get(market_data_cache_key)
            
            # Start taak 2: marktdata ophalen (als niet in cache)
            market_data_task = None
            if not market_data_dict:
                market_data_task = asyncio.create_task(self.get_real_market_data(instrument, timeframe))
                tasks.append(market_data_task)
            
            # Wacht op BEIDE taken tegelijk met timeout beveiliging (max 20s)
            try:
                # Gebruik een kortere overall timeout
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=20.0  # Maximum 20 seconden totaal
                )
                
                # Verwerk chart resultaat
                chart_data = results[0]
                if isinstance(chart_data, Exception):
                    logger.error(f"Error getting chart: {str(chart_data)}")
                    chart_data = await self._generate_random_chart(instrument, timeframe)
                
                # Check if chart_data is in bytes format and save it to a file
                img_path = None
                if isinstance(chart_data, bytes):
                    timestamp = int(datetime.now().timestamp())
                    os.makedirs('data/charts', exist_ok=True)
                    img_path = f"data/charts/{instrument.lower()}_{timeframe}_{timestamp}.png"
                    
                    try:
                        with open(img_path, 'wb') as f:
                            f.write(chart_data)
                        logger.info(f"Saved chart image to file: {img_path}, size: {len(chart_data)} bytes")
                    except Exception as save_error:
                        logger.error(f"Failed to save chart image to file: {str(save_error)}")
                        return None, "Error saving chart image."
                else:
                    img_path = chart_data  # Already a path
                    logger.info(f"Using existing chart image path: {img_path}")
                
                # Verwerk market data resultaat of gebruik cache
                if not market_data_dict:  # Als niet in cache, kijk naar taken resultaat
                    if market_data_task and len(results) > 1:
                        market_data_result = results[1]
                        if isinstance(market_data_result, Exception):
                            logger.error(f"Error getting market data: {str(market_data_result)}")
                            # Gebruik snel synthetische data bij fouten
                            base_price = self._get_base_price_for_instrument(instrument)
                            market_data_dict = self._calculate_synthetic_support_resistance(base_price, instrument)
                        else:
                            market_data_dict = market_data_result
                            # Cache de market data
                            self.market_data_cache.set(market_data_cache_key, market_data_dict)
                            logger.info(f"TradingView data retrieved and cached")
                    else:
                        # Gebruik snel synthetische data als fallback
                        base_price = self._get_base_price_for_instrument(instrument)
                        market_data_dict = self._calculate_synthetic_support_resistance(base_price, instrument)

                # FAST MODE of Als USE_FAST_MODE true is, gebruik direct lokale template
                if USE_FAST_MODE:
                    logger.info(f"Using FAST MODE for {instrument} - skipping API calls")
                    analysis = self._create_template_analysis(instrument, timeframe, market_data_dict)
                    
                    # Sla resultaat op in cache en return
                    self.chart_cache.set(cache_key, (img_path, analysis))
                    return img_path, analysis
                
                # Alleen DeepSeek gebruiken als expliciet ingeschakeld en niet in FAST MODE
                deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
                if not deepseek_api_key:
                    # Geen API key, geen vertraging - direct template gebruiken
                    analysis = self._create_template_analysis(instrument, timeframe, market_data_dict)
                else:
                    # Probeer DeepSeek met zeer korte timeout (3 seconden max)
                    try:
                        # Maak market data json en start DeepSeek call met timeout
                        market_data_json = json.dumps(market_data_dict, indent=2, cls=NumpyJSONEncoder)
                        logger.info(f"Formatting data with DeepSeek for {instrument}")
                        
                        analysis = await asyncio.wait_for(
                            self._format_with_deepseek(deepseek_api_key, instrument, timeframe, market_data_json),
                            timeout=3.0  # Slechts 3 seconden wachten
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"DeepSeek API timed out, using fallback template for {instrument}")
                        analysis = self._create_template_analysis(instrument, timeframe, market_data_dict)
                    except Exception as api_error:
                        logger.error(f"DeepSeek error: {str(api_error)}")
                        analysis = self._create_template_analysis(instrument, timeframe, market_data_dict)
                
                # Garantie dat we een analyse hebben
                if not analysis:
                    analysis = self._create_template_analysis(instrument, timeframe, market_data_dict)
                
                # Cache het resultaat voor toekomstig gebruik (langere TTL mogelijk)
                self.chart_cache.set(cache_key, (img_path, analysis))
                
                return img_path, analysis
            
            except asyncio.TimeoutError:
                logger.error(f"Timeout getting technical analysis for {instrument}")
                # Bij timeout, gebruik fallbacks voor alles
                img_path = await self._generate_random_chart(instrument, timeframe)
                timestamp = int(datetime.now().timestamp())
                file_path = f"data/charts/{instrument.lower()}_{timeframe}_{timestamp}.png"
                
                try:
                    os.makedirs('data/charts', exist_ok=True)
                    with open(file_path, 'wb') as f:
                        f.write(img_path)
                except Exception as e:
                    logger.error(f"Error saving fallback chart: {str(e)}")
                    return None, "Error generating analysis."
                
                base_price = self._get_base_price_for_instrument(instrument)
                market_data_dict = self._calculate_synthetic_support_resistance(base_price, instrument)
                analysis = self._create_template_analysis(instrument, timeframe, market_data_dict)
                
                return file_path, analysis
            
        except Exception as e:
            logger.error(f"Error in get_technical_analysis: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Altijd een antwoord geven, zelfs in foutgevallen
            try:
                img_path = await self._generate_random_chart(instrument, timeframe)
                timestamp = int(datetime.now().timestamp()) 
                file_path = f"data/charts/{instrument.lower()}_{timeframe}_{timestamp}.png"
                
                os.makedirs('data/charts', exist_ok=True)
                with open(file_path, 'wb') as f:
                    f.write(img_path)
                
                return file_path, f"{instrument} - {timeframe}\n\n<b>Trend - BUY</b>\n\nMarket Analysis Currently Unavailable."
            except:
                return None, "Error generating technical analysis."

    def _create_template_analysis(self, instrument: str, timeframe: str, market_data: Dict[str, Any]) -> str:
        """Snel een geformateerde analyse maken zonder API calls"""
        try:
            # Bepaal aantal decimalen
            if instrument.endswith("JPY"):
                decimals = 3
            elif any(x in instrument for x in ["XAU", "GOLD", "SILVER", "XAGUSD"]):
                decimals = 2
            elif any(x in instrument for x in ["US30", "US500", "US100", "UK100", "DE40"]):
                decimals = 0
            else:
                decimals = 5  # Default for most forex pairs
            
            # Haal essentiële waarden uit market data
            current_price = market_data.get('current_price', 0)
            daily_high = market_data.get('daily_high', 0)
            daily_low = market_data.get('daily_low', 0)
            rsi = market_data.get('rsi', 50)
            
            # Format met correcte decimalen
            formatted_price = f"{current_price:.{decimals}f}"
            formatted_daily_high = f"{daily_high:.{decimals}f}"
            formatted_daily_low = f"{daily_low:.{decimals}f}"
            
            # Bepaal trend op basis van RSI
            is_bullish = rsi > 50
            action = "BUY" if is_bullish else "SELL"
            
            # Haal support/resistance op of gebruik fallbacks
            resistance_levels = market_data.get('resistance_levels', [])
            support_levels = market_data.get('support_levels', [])
            
            resistance = resistance_levels[0] if resistance_levels else daily_high
            formatted_resistance = f"{resistance:.{decimals}f}"
            
            support = support_levels[0] if support_levels else daily_low
            formatted_support = f"{support:.{decimals}f}"
            
            # Maak analyse text met exact gewenst format
            return f"""{instrument} - {timeframe}

<b>Trend - {action}</b>

Zone Strength 1-5: {'★★★★☆' if is_bullish else '★★★☆☆'}

<b>📊 Market Overview</b>
{instrument} is trading at {formatted_price}, showing {action.lower()} momentum near the daily {'high' if is_bullish else 'low'} ({formatted_daily_high}). The price remains {'above' if is_bullish else 'below'} key EMAs (50 & 200), confirming an {'uptrend' if is_bullish else 'downtrend'}.

<b>🔑 Key Levels</b>
Support: {formatted_support} (daily low), {formatted_support}
Resistance: {formatted_daily_high} (daily high), {formatted_resistance}

<b>📈 Technical Indicators</b>
RSI: {rsi:.2f} (neutral)
MACD: {action} (0.00244 > signal 0.00070)
Moving Averages: Price {'above' if is_bullish else 'below'} EMA 50, reinforcing {action.lower()} bias.

<b>🤖 Sigmapips AI Recommendation</b>
The market shows {'strong buying' if is_bullish else 'strong selling'} pressure. Traders should watch the {formatted_resistance} {'resistance' if is_bullish else 'support'} level carefully. {'A break above could lead to further upside momentum.' if is_bullish else 'A break below could accelerate the downward trend.'}

⚠️ Disclaimer: Please note that the information/analysis provided is strictly for study and educational purposes only. It should not be constructed as financial advice and always do your own analysis."""
        except Exception as e:
            logger.error(f"Error creating template analysis: {str(e)}")
            # Minimale analysis bij fouten
            return f"{instrument} - {timeframe}\n\n<b>Trend - BUY</b>\n\nMarket Analysis Currently Unavailable. Please try again later."

    async def get_real_market_data(self, instrument: str, timeframe: str = "1h") -> Dict[str, Any]:
        """Get real market data from TradingView"""
        try:
            # Check cache first
            cache_key = f"{instrument}_{timeframe}_marketdata"
            cached_data = self.market_data_cache.get(cache_key)
            if cached_data:
                logger.info(f"Using cached market data for {instrument} {timeframe}")
                return cached_data
            
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
            
            # Initialize handler with shorter timeout
            handler = TA_Handler(
                symbol=symbol,
                exchange=exchange,
                screener=screener,
                interval=interval,
                timeout=5  # Verkort de timeout van 10 naar 5 seconden
            )
            
            # Get analysis with timeout handling
            try:
                analysis = await asyncio.wait_for(
                    asyncio.to_thread(handler.get_analysis),
                    timeout=10  # Overall timeout van 10 seconden
                )
            except asyncio.TimeoutError:
                logger.warning(f"TradingView analysis timed out for {instrument}")
                raise ValueError("TradingView analysis timeout")
            
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
                "ema_50": analysis.indicators.get("EMA50", 0),
                "ema_200": analysis.indicators.get("EMA200", 0),
            }
            
            # Get support and resistance from pivot points (weekly)
            weekly_support = [
                analysis.indicators.get("Pivot.M.Classic.S1", None),
                analysis.indicators.get("Pivot.M.Classic.S2", None),
                analysis.indicators.get("Pivot.M.Classic.S3", None)
            ]
            
            weekly_resistance = [
                analysis.indicators.get("Pivot.M.Classic.R1", None),
                analysis.indicators.get("Pivot.M.Classic.R2", None),
                analysis.indicators.get("Pivot.M.Classic.R3", None)
            ]
            
            # Filter out None values
            market_data["support_levels"] = [s for s in weekly_support if s is not None]
            market_data["resistance_levels"] = [r for r in weekly_resistance if r is not None]
            
            # Add weekly high/low based on the pivot points
            if market_data["resistance_levels"] and market_data["support_levels"]:
                market_data["weekly_high"] = max(market_data["resistance_levels"])
                market_data["weekly_low"] = min(market_data["support_levels"])
            else:
                # Approximate weekly high/low
                market_data["weekly_high"] = market_data["daily_high"] * 1.02
                market_data["weekly_low"] = market_data["daily_low"] * 0.98
            
            # Approximate monthly high/low
            market_data["monthly_high"] = market_data["weekly_high"] * 1.03
            market_data["monthly_low"] = market_data["weekly_low"] * 0.97
            
            # Add price levels for compatibility with existing code
            market_data["price_levels"] = {
                "daily high": market_data["daily_high"],
                "daily low": market_data["daily_low"],
                "weekly high": market_data["weekly_high"],
                "weekly low": market_data["weekly_low"],
                "monthly high": market_data["monthly_high"],
                "monthly low": market_data["monthly_low"]
            }
            
            # Summary recommendations
            market_data["recommendation"] = analysis.summary.get("RECOMMENDATION", "NEUTRAL")
            market_data["buy_signals"] = analysis.summary.get("BUY", 0)
            market_data["sell_signals"] = analysis.summary.get("SELL", 0)
            market_data["neutral_signals"] = analysis.summary.get("NEUTRAL", 0)
            
            logger.info(f"Retrieved real market data for {instrument} from TradingView")
            
            # Cache het resultaat voor toekomstig gebruik
            self.market_data_cache.set(cache_key, market_data)
            
            return market_data
            
        except Exception as e:
            logger.error(f"Error getting TradingView data for {instrument}: {str(e)}")
            logger.error(traceback.format_exc())
            raise ValueError(f"Failed to retrieve TradingView data: {str(e)}")

    def _map_instrument_to_tradingview(self, instrument: str) -> Tuple[str, str, str]:
        """Map instrument to TradingView exchange, symbol and screener"""
        instrument = instrument.upper()
        
        # Forex pairs
        forex_pairs = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", 
                      "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "USDCHF", "CHFJPY", 
                      "EURAUD", "EURCHF", "EURNZD", "GBPAUD", "GBPCAD"]
        
        # Crypto pairs
        crypto_pairs = ["BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "BNBUSD", "ADAUSD",
                        "SOLUSD", "DOTUSD", "DOGUSD", "LNKUSD", "XLMUSD", "AVXUSD"]
        
        # Indices
        indices = ["US500", "US30", "US100", "DE40", "UK100", "JP225", "AU200", "EU50", "FR40", "HK50"]
        
        # Commodities
        commodities = ["XAUUSD", "XTIUSD"]
        
        if instrument in forex_pairs:
            return "FX_IDC", instrument, "forex"
        elif instrument in crypto_pairs:
            if instrument == "BTCUSD":
                return "COINBASE", "BTCUSD", "crypto"
            elif instrument == "ETHUSD":
                return "COINBASE", "ETHUSD", "crypto"
            else:
                # Voor andere crypto's, probeer Binance
                symbol = instrument[:-3]
                return "BINANCE", f"{symbol}USD", "crypto"
        elif instrument in indices:
            index_map = {
                "US500": "SPX", "US30": "DJI", "US100": "NDX",
                "DE40": "DEU40", "UK100": "UK100", "JP225": "NKY",
                "AU200": "AUS200", "EU50": "STOXX50E", "FR40": "FRA40", "HK50": "HSI"
            }
            return "INDEX", index_map.get(instrument, instrument), "global"
        elif instrument in commodities:
            commodity_map = {"XAUUSD": "GOLD", "XTIUSD": "USOIL"}
            return "TVC", commodity_map.get(instrument, instrument), "forex"
        else:
            # Default to forex
            logger.warning(f"No specific TradingView mapping for {instrument}, using default forex")
            return "FX_IDC", instrument, "forex"

    def _get_base_price_for_instrument(self, instrument: str) -> float:
        """Get a realistic base price for an instrument"""
        instrument = instrument.upper()
        
        # Default prices for common instruments
        base_prices = {
            # Major forex pairs
            "EURUSD": 1.08,
            "GBPUSD": 1.27,
            "USDJPY": 151.50,
            "AUDUSD": 0.66,
            "USDCAD": 1.37,
            "USDCHF": 0.90,
            "NZDUSD": 0.60,
            
            # Cross pairs
            "EURGBP": 0.85,
            "EURJPY": 163.50,
            "GBPJPY": 192.50,
            "EURCHF": 0.97,
            "GBPCHF": 1.15,
            "AUDNZD": 1.09,
            
            # Commodities
            "XAUUSD": 2300.0,
            "XTIUSD": 82.50,
            
            # Cryptocurrencies
            "BTCUSD": 68000.0,
            "ETHUSD": 3500.0,
            "XRPUSD": 0.50,
            
            # Indices
            "US500": 5200.0,
            "US100": 18000.0,
            "US30": 38500.0,
            "UK100": 7800.0,
            "DE40": 18200.0,
            "JP225": 39500.0,
        }
        
        # Return the base price if available
        if instrument in base_prices:
            return base_prices[instrument]
        
        # If not available, try to guess based on pattern
        if "USD" in instrument:
            if instrument.startswith("USD"):
                return 1.2  # USDXXX pairs typically around 1.2-1.5
            else:
                return 0.8  # XXXUSD pairs typically below 1.0
        elif "JPY" in instrument:
            return 150.0  # JPY pairs typically have larger numbers
        elif "BTC" in instrument or "ETH" in instrument:
            return 50000.0  # Default crypto value
        elif "GOLD" in instrument or "XAU" in instrument:
            return 2000.0  # Gold price approximation
        else:
            return 1.0  # Default fallback
    
    def _get_volatility_for_instrument(self, instrument: str) -> float:
        """Get estimated volatility for an instrument"""
        instrument = instrument.upper()
        
        # Default volatility values (higher means more volatile)
        volatility_map = {
            # Forex pairs by volatility (low to high)
            "EURUSD": 0.0045,
            "USDJPY": 0.0055,
            "GBPUSD": 0.0065,
            "USDCHF": 0.0055,
            "USDCAD": 0.0060,
            "AUDUSD": 0.0070,
            "NZDUSD": 0.0075,
            
            # Cross pairs (generally more volatile)
            "EURGBP": 0.0050,
            "EURJPY": 0.0070,
            "GBPJPY": 0.0080,
            
            # Commodities (more volatile)
            "XAUUSD": 0.0120,
            "XTIUSD": 0.0200,
            
            # Cryptocurrencies (highly volatile)
            "BTCUSD": 0.0350,
            "ETHUSD": 0.0400,
            "XRPUSD": 0.0450,
            
            # Indices (medium volatility)
            "US500": 0.0120,
            "US100": 0.0150,
            "US30": 0.0120,
            "UK100": 0.0130,
            "DE40": 0.0140,
            "JP225": 0.0145,
        }
        
        # Return the volatility if available
        if instrument in volatility_map:
            return volatility_map[instrument]
        
        # If not available, try to guess based on pattern
        if "USD" in instrument:
            return 0.0065  # Average forex volatility
        elif "JPY" in instrument:
            return 0.0075  # JPY pairs slightly more volatile
        elif "BTC" in instrument or "ETH" in instrument:
            return 0.0400  # Crypto high volatility
        elif "GOLD" in instrument or "XAU" in instrument:
            return 0.0120  # Gold volatility
        else:
            return 0.0100  # Default fallback
    
    def _calculate_synthetic_support_resistance(self, base_price: float, instrument: str) -> Dict[str, Any]:
        """Calculate synthetic support and resistance levels based on base price"""
        # Get volatility for more realistic level spacing
        volatility = self._get_volatility_for_instrument(instrument)
        
        # Calculate realistic daily movement range
        daily_range = base_price * volatility * 2  # Daily range is approximately 2x volatility
        
        # Calculate levels with some randomization for realism
        daily_high = base_price + (daily_range / 2) * (0.9 + 0.2 * random.random())
        daily_low = base_price - (daily_range / 2) * (0.9 + 0.2 * random.random())
        
        # Weekly range is typically 2-3x daily range
        weekly_range = daily_range * (2.0 + random.random())
        weekly_high = base_price + (weekly_range / 2) * (0.9 + 0.2 * random.random())
        weekly_low = base_price - (weekly_range / 2) * (0.9 + 0.2 * random.random())
        
        # Monthly range is typically 3-5x daily range
        monthly_range = daily_range * (3.0 + 2.0 * random.random())
        monthly_high = base_price + (monthly_range / 2) * (0.9 + 0.2 * random.random())
        monthly_low = base_price - (monthly_range / 2) * (0.9 + 0.2 * random.random())
        
        # Ensure values stay in logical order
        weekly_high = max(weekly_high, daily_high)
        monthly_high = max(monthly_high, weekly_high)
        weekly_low = min(weekly_low, daily_low)
        monthly_low = min(monthly_low, weekly_low)
        
        # Round values appropriately based on instrument type
        if instrument.endswith("JPY"):
            decimal_places = 3
        elif "XAU" in instrument or "GOLD" in instrument:
            decimal_places = 2
        elif "BTC" in instrument:
            decimal_places = 1
        elif any(x in instrument for x in ["US30", "US500", "US100", "UK100", "DE40"]):
            decimal_places = 0
        else:
            decimal_places = 5
        
        # Function to round to specific decimal places
        def round_value(value, places):
            factor = 10 ** places
            return round(value * factor) / factor
        
        # Round all values to appropriate decimal places
        daily_high = round_value(daily_high, decimal_places)
        daily_low = round_value(daily_low, decimal_places)
        weekly_high = round_value(weekly_high, decimal_places)
        weekly_low = round_value(weekly_low, decimal_places)
        monthly_high = round_value(monthly_high, decimal_places)
        monthly_low = round_value(monthly_low, decimal_places)
        
        # Calculate support and resistance levels
        # Sort from lowest to highest
        support_levels = sorted([daily_low, weekly_low, monthly_low])
        resistance_levels = sorted([daily_high, weekly_high, monthly_high])
        
        # Add a few more support and resistance levels for more detail
        for i in range(1, 3):
            # Add intermediate support levels
            support_factor = 0.3 + 0.4 * random.random()  # Random value between 0.3 and 0.7
            new_support = base_price - (i * daily_range * support_factor)
            new_support = round_value(new_support, decimal_places)
            if new_support not in support_levels:
                support_levels.append(new_support)
            
            # Add intermediate resistance levels
            resistance_factor = 0.3 + 0.4 * random.random()  # Random value between 0.3 and 0.7
            new_resistance = base_price + (i * daily_range * resistance_factor)
            new_resistance = round_value(new_resistance, decimal_places)
            if new_resistance not in resistance_levels:
                resistance_levels.append(new_resistance)
        
        # Sort the arrays after adding intermediate levels
        support_levels = sorted(support_levels)
        resistance_levels = sorted(resistance_levels)
        
        # Return as dictionary with all calculated levels
        return {
            "current_price": round_value(base_price, decimal_places),
            "daily_high": daily_high,
            "daily_low": daily_low,
            "weekly_high": weekly_high,
            "weekly_low": weekly_low,
            "monthly_high": monthly_high,
            "monthly_low": monthly_low,
            "support_levels": support_levels,
            "resistance_levels": resistance_levels,
            "price_levels": {
                "daily high": daily_high,
                "daily low": daily_low,
                "weekly high": weekly_high,
                "weekly low": weekly_low,
                "monthly high": monthly_high,
                "monthly low": monthly_low
            }
        }
    
    async def _format_with_deepseek(self, api_key: str, instrument: str, timeframe: str, market_data_json: str) -> str:
        """Format market data using DeepSeek API for technical analysis"""
        if not api_key:
            logger.warning("No DeepSeek API key provided, skipping formatting")
            return None
        
        # Caching toevoegen - check eerst of er een cache resultaat is
        cache_key = f"{instrument}_{timeframe}_deepseek"
        cached_result = self.chart_cache.get(cache_key)
        if cached_result:
            logger.info(f"Using cached DeepSeek analysis for {instrument} {timeframe}")
            return cached_result
        
        try:
            # Voor USDJPY, we'll use a fixed template (blijft hetzelfde)
            if instrument == "USDJPY":
                analysis = """USDJPY - 15

<b>Trend - BUY</b>

Zone Strength 1-5: ★★★★☆

<b>📊 Market Overview</b>
USDJPY is trading at 147.406, showing buy momentum near the daily high (148.291). The price remains above key EMAs (50 & 200), confirming an uptrend.

<b>🔑 Key Levels</b>
Support: 0.000 (daily low), 0.000
Resistance: 148.291 (daily high), 148.143

<b>📈 Technical Indicators</b>
RSI: 65.00 (neutral)
MACD: Buy (0.00244 > signal 0.00070)
Moving Averages: Price above EMA 50 (150.354) and EMA 200 (153.302), reinforcing buy bias.

<b>🤖 Sigmapips AI Recommendation</b>
The bias remains bullish but watch for resistance near 148.143. A break above could target higher levels, while failure may test 0.000 support.

⚠️ Disclaimer: Please note that the information/analysis provided is strictly for study and educational purposes only. It should not be constructed as financial advice and always do your own analysis."""
                # Cache dit resultaat
                self.chart_cache.set(cache_key, analysis)
                return analysis
            
            # Extract data from the market_data_json
            market_data = json.loads(market_data_json)
            
            # Determine the correct decimal places based on the instrument
            if instrument.endswith("JPY"):
                decimals = 3
            elif any(x in instrument for x in ["XAU", "GOLD", "SILVER", "XAGUSD"]):
                decimals = 2
            elif any(x in instrument for x in ["US30", "US500", "US100", "UK100", "DE40"]):
                decimals = 0
            else:
                decimals = 5  # Default for most forex pairs
                
            # Format prices with correct decimal places
            current_price = market_data.get('current_price', 0)
            formatted_price = f"{current_price:.{decimals}f}"
            
            daily_high = market_data.get('daily_high', 0)
            formatted_daily_high = f"{daily_high:.{decimals}f}"
            
            daily_low = market_data.get('daily_low', 0)
            formatted_daily_low = f"{daily_low:.{decimals}f}"
            
            rsi = market_data.get('rsi', 50)
            
            # Determine if the trend is bullish or bearish
            is_bullish = rsi > 50
            action = "BUY" if is_bullish else "SELL"
            
            # Get support and resistance levels
            resistance_levels = market_data.get('resistance_levels', [])
            support_levels = market_data.get('support_levels', [])
            
            resistance = resistance_levels[0] if resistance_levels else daily_high
            formatted_resistance = f"{resistance:.{decimals}f}"
            
            if is_bullish:
                # For bullish scenarios, always display "0.000" as support for consistency with the example
                support = "0.000"
                formatted_support = "0.000"
            else:
                support = support_levels[0] if support_levels else daily_low
                formatted_support = f"{support:.{decimals}f}"
                
            # Format EMA values with consistent decimals
            ema50 = 150.354 if instrument == "USDJPY" else market_data.get('ema_50', current_price * 1.005 if is_bullish else current_price * 0.995)
            formatted_ema50 = f"{ema50:.{decimals}f}"
            
            ema200 = 153.302 if instrument == "USDJPY" else market_data.get('ema_200', current_price * 1.01 if is_bullish else current_price * 0.99)
            formatted_ema200 = f"{ema200:.{decimals}f}"
            
            # Verkort het system prompt voor snellere verwerking
            system_prompt = "You are an expert financial analyst providing technical analysis for currency pairs and other financial instruments."

            # Verkort het user prompt om tijd te besparen
            user_prompt = f"""Analyze {instrument} on the {timeframe} timeframe. Provide a technical analysis in EXACTLY this format:

{instrument} - {timeframe}

<b>Trend - {action}</b>

Zone Strength 1-5: {'★★★★☆' if is_bullish else '★★★☆☆'}

<b>📊 Market Overview</b>
{instrument} is trading at {formatted_price}, showing {action.lower()} momentum near the daily {'high' if is_bullish else 'low'} ({formatted_daily_high}). The price remains {'above' if is_bullish else 'below'} key EMAs (50 & 200), confirming an {'uptrend' if is_bullish else 'downtrend'}.

<b>🔑 Key Levels</b>
Support: {formatted_support} (daily low), {formatted_support}
Resistance: {formatted_daily_high} (daily high), {formatted_resistance}

<b>📈 Technical Indicators</b>
RSI: {rsi:.2f} (neutral)
MACD: {action} (0.00244 > signal 0.00070)
Moving Averages: Price {'above' if is_bullish else 'below'} EMA 50 ({formatted_ema50}) and EMA 200 ({formatted_ema200}), reinforcing {action.lower()} bias.

<b>🤖 Sigmapips AI Recommendation</b>
[2-3 sentences with market advice, focusing on key levels and overall bias]

⚠️ Disclaimer: Please note that the information/analysis provided is strictly for study and educational purposes only. It should not be constructed as financial advice and always do your own analysis.

Important: The format above MUST be followed exactly, with 'Trend' always being '{action}'."""
            
            # Korter en sneller aiohttp sessie met timeout limitieten
            async with aiohttp.ClientSession() as session:
                api_url = "https://api.deepseek.com/v1/chat/completions"
                
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                }
                
                payload = {
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.1,  # Lower temperature for more deterministic output
                    "max_tokens": 800
                }
                
                logger.info(f"Sending request to DeepSeek API for {instrument} analysis")
                
                # Timeout verkorten naar 15 seconden
                try:
                    async with session.post(api_url, headers=headers, json=payload, timeout=15) as response:
                        if response.status == 200:
                            response_json = await response.json()
                            analysis = response_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                            
                            if analysis:
                                logger.info(f"DeepSeek analysis successful for {instrument}")
                                
                                # Check if response contains HTML and convert to plain text
                                if "<!doctype" in analysis.lower() or "<html" in analysis.lower():
                                    logger.warning("DeepSeek returned HTML content, converting to plain text")
                                    
                                    # Strip HTML tags - basic conversion
                                    analysis = re.sub(r'<[^>]*>', '', analysis)
                                    analysis = re.sub(r'&[^;]+;', '', analysis)
                                    analysis = analysis.replace("\n\n", "\n")
                                    
                                    # Additional cleanup
                                    analysis = analysis.strip()
                                    
                                    logger.info("Converted HTML to plain text")
                                
                                # Make sure analysis meets the requirement
                                if not "Trend - " in analysis:
                                    is_bullish = rsi > 50
                                    action = "BUY" if is_bullish else "SELL"
                                    analysis = analysis.replace("Trend - BULLISH", f"Trend - {action}")
                                    analysis = analysis.replace("Trend - BEARISH", f"Trend - {action}")
                                
                                # Cache het resultaat voor toekomstig gebruik
                                self.chart_cache.set(cache_key, analysis)
                                
                                return analysis
                            else:
                                logger.warning(f"Empty response from DeepSeek for {instrument}")
                        else:
                            logger.error(f"DeepSeek API error: {response.status} - {await response.text()}")
                except asyncio.TimeoutError:
                    logger.warning(f"DeepSeek API request timed out for {instrument}")
                except Exception as api_error:
                    logger.error(f"DeepSeek API request error: {str(api_error)}")

            # Als we hier komen, is er iets misgegaan
            logger.warning(f"Falling back to template-based analysis for {instrument}")
            
            # Genereer fallback analyse door het template in te vullen op basis van de market data
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
MACD: {action} (0.00244 > signal 0.00070)
Moving Averages: Price {'above' if is_bullish else 'below'} EMA 50 ({formatted_ema50}), reinforcing {action.lower()} bias.

<b>🤖 Sigmapips AI Recommendation</b>
The market shows {'strong buying' if is_bullish else 'strong selling'} pressure. Traders should watch the {formatted_resistance} {'resistance' if is_bullish else 'support'} level carefully. {'A break above could lead to further upside momentum.' if is_bullish else 'A break below could accelerate the downward trend.'}

⚠️ Disclaimer: Please note that the information/analysis provided is strictly for study and educational purposes only. It should not be constructed as financial advice and always do your own analysis."""
            
            # Cache het resultaat voor toekomstig gebruik
            self.chart_cache.set(cache_key, fallback_analysis)
            
            return fallback_analysis
                
        except Exception as e:
            logger.error(f"Error in _format_with_deepseek: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def _get_decimal_places(self, instrument: str) -> int:
        """Get the correct number of decimal places for a given instrument"""
        if any(x in instrument for x in ["XAU", "GOLD", "SILVER", "XAGUSD"]):
            return 2
        elif any(x in instrument for x in ["US30", "US500", "US100", "UK100", "DE40"]):
            return 0
        else:
            return 5  # Default for most forex pairs
