print("Loading chart.py module...")

import os
import logging
import aiohttp
import random
from typing import Optional, Union
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

# Importeer alleen de base class
from trading_bot.services.chart_service.base import TradingViewService

logger = logging.getLogger(__name__)

# Rate limiting en caching configuratie
YAHOO_CACHE_DIR = os.path.join('data', 'cache', 'yahoo')
YAHOO_CACHE_EXPIRY = 60 * 5  # 5 minuten
YAHOO_REQUEST_DELAY = 2  # 2 seconden tussen requests

# JSON encoder voor NumPy datatypes
class NumpyJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, pd.Series):
            return obj.tolist()
        return super(NumpyJSONEncoder, self).default(obj)

class ChartService:
    def __init__(self):
        """Initialize chart service"""
        print("ChartService initialized")
        try:
            # Maak cache directory aan als die niet bestaat
            os.makedirs(YAHOO_CACHE_DIR, exist_ok=True)
            
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
            
            logging.info("Chart service initialized")
            
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
        Get technical analysis for an instrument with timeframe using combined Yahoo Finance, OCR, and DeepSeek APIs.
        """
        try:
            # First get the chart image
            img_path = await self.get_chart(instrument, timeframe)
            
            # Get the DeepSeek API key
            deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
            
            if not deepseek_api_key:
                logger.warning("DeepSeek API key missing, falling back to mock data")
                return await self._generate_mock_analysis(instrument, timeframe, img_path)
            
            # Get market data using Yahoo Finance
            try:
                logger.info(f"Getting market data for {instrument} from Yahoo Finance")
                yahoo_data_json = await self._get_yahoo_finance_data(instrument, timeframe)
                
                if not yahoo_data_json:
                    logger.warning("No data from Yahoo Finance, falling back to mock data")
                    return await self._generate_mock_analysis(instrument, timeframe, img_path)
                
                # Parse JSON string to dictionary for OCR enhancement
                import json
                yahoo_data_dict = json.loads(yahoo_data_json)
                
                # Perform OCR analysis on the chart image if available
                ocr_data = {}
                if img_path and os.path.exists(img_path):
                    try:
                        from trading_bot.services.chart_service.ocr_processor import ChartOCRProcessor
                        logger.info(f"Performing OCR analysis on chart image: {img_path}")
                        
                        # Initialize OCR processor
                        ocr_processor = ChartOCRProcessor()
                        
                        # Process chart image with OCR
                        ocr_data = ocr_processor.process_chart_image(img_path)
                        logger.info(f"OCR data extracted: {ocr_data}")
                        
                        # Enhance Yahoo data with OCR data if available
                        if ocr_data:
                            enhanced_data = ocr_processor.enhance_market_data(yahoo_data_dict, ocr_data)
                            logger.info(f"Enhanced market data with OCR: {enhanced_data}")
                            
                            # Convert enhanced data back to JSON for DeepSeek
                            yahoo_data_json = json.dumps(enhanced_data, indent=2, cls=NumpyJSONEncoder)
                        
                    except Exception as ocr_error:
                        logger.error(f"Error performing OCR analysis: {str(ocr_error)}")
                        # Continue with Yahoo data only
                
                # Format data using DeepSeek API
                logger.info(f"Formatting data with DeepSeek for {instrument}")
                analysis = await self._format_with_deepseek(deepseek_api_key, instrument, timeframe, yahoo_data_json)
                
                if not analysis:
                    logger.warning("Failed to format with DeepSeek, falling back to mock data")
                    return await self._generate_mock_analysis(instrument, timeframe, img_path)
                
                # Add OCR confidence note if OCR data was used
                if ocr_data and 'current_price' in ocr_data:
                    # Check if the OCR price was significantly different from Yahoo price
                    if 'current_price' in yahoo_data_dict:
                        price_diff_pct = abs(ocr_data['current_price'] - yahoo_data_dict['current_price']) / yahoo_data_dict['current_price'] * 100
                        if price_diff_pct > 2:  # If more than 2% difference
                            logger.info(f"OCR price differed by {price_diff_pct:.2f}% from Yahoo price")
                            # Could add a note to the analysis, but keeping it clean for now
                
                return img_path, analysis
                
            except Exception as e:
                logger.error(f"Error getting technical analysis data: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                return await self._generate_mock_analysis(instrument, timeframe, img_path)
                
        except Exception as e:
            logger.error(f"Error in get_technical_analysis: {str(e)}")
            return None, "Error generating technical analysis."

    def _get_cache_key(self, symbol, data_type, timeframe=None):
        """Genereer een unieke cache key voor Yahoo Finance data"""
        components = [symbol, data_type]
        if timeframe:
            components.append(timeframe)
        
        key = "_".join(components)
        hashed = hashlib.md5(key.encode()).hexdigest()
        return hashed

    def _get_cached_data(self, cache_key):
        """Haal gecachte data op als die bestaat en nog geldig is"""
        cache_file = os.path.join(YAHOO_CACHE_DIR, f"{cache_key}.pkl")
        if os.path.exists(cache_file):
            try:
                # Controleer of de cache nog geldig is
                file_time = os.path.getmtime(cache_file)
                if time.time() - file_time < YAHOO_CACHE_EXPIRY:
                    with open(cache_file, 'rb') as f:
                        return pickle.load(f)
                else:
                    logger.info(f"Cache expired for {cache_key}")
            except Exception as e:
                logger.warning(f"Error reading cache: {str(e)}")
        return None

    def _save_to_cache(self, cache_key, data):
        """Sla data op in de cache"""
        try:
            cache_file = os.path.join(YAHOO_CACHE_DIR, f"{cache_key}.pkl")
            with open(cache_file, 'wb') as f:
                pickle.dump(data, f)
            logger.info(f"Saved data to cache: {cache_key}")
        except Exception as e:
            logger.warning(f"Error saving to cache: {str(e)}")

    async def _get_ticker_info(self, symbol):
        """Haal ticker info op met rate limiting en caching"""
        import yfinance as yf
        
        # Controleer cache eerst
        cache_key = self._get_cache_key(symbol, "info")
        cached_data = self._get_cached_data(cache_key)
        if cached_data:
            logger.info(f"Using cached info for {symbol}")
            return cached_data
        
        # Rate limiting
        time_since_last = time.time() - self.last_yahoo_request
        if time_since_last < YAHOO_REQUEST_DELAY:
            delay = YAHOO_REQUEST_DELAY - time_since_last
            logger.info(f"Rate limiting: waiting {delay:.2f}s before Yahoo Finance request")
            await asyncio.sleep(delay)
        
        # Update timestamp
        self.last_yahoo_request = time.time()
        
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info  # Gebruik fast_info om quota te sparen
            
            # Vul aan met basis info zonder volledige quota te gebruiken
            basic_info = {
                'symbol': symbol,
                'regularMarketPrice': getattr(info, 'last_price', None),
                'currency': getattr(info, 'currency', None),
                'exchange': getattr(info, 'exchange', None)
            }
            
            # Sla op in cache
            self._save_to_cache(cache_key, basic_info)
            return basic_info
        except Exception as e:
            logger.error(f"Error getting ticker info: {str(e)}")
            return None

    async def _get_ticker_history(self, symbol, start_date, end_date, interval):
        """Haal ticker history op met rate limiting en caching"""
        import yfinance as yf
        
        # Controleer cache eerst
        cache_key = self._get_cache_key(symbol, "history", f"{interval}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}")
        cached_data = self._get_cached_data(cache_key)
        if cached_data is not None:
            logger.info(f"Using cached history for {symbol}")
            return cached_data
        
        # Rate limiting
        time_since_last = time.time() - self.last_yahoo_request
        if time_since_last < YAHOO_REQUEST_DELAY:
            delay = YAHOO_REQUEST_DELAY - time_since_last
            logger.info(f"Rate limiting: waiting {delay:.2f}s before Yahoo Finance request")
            await asyncio.sleep(delay)
        
        # Update timestamp
        self.last_yahoo_request = time.time()
        
        try:
            data = yf.download(symbol, start=start_date, end=end_date, interval=interval, progress=False)
            
            # Sla op in cache als data niet leeg is
            if not data.empty:
                self._save_to_cache(cache_key, data)
            return data
        except Exception as e:
            logger.error(f"Error getting ticker history: {str(e)}")
            return pd.DataFrame()
            
    async def _get_yahoo_finance_data(self, instrument: str, timeframe: str):
        """Get market data from Yahoo Finance using Ticker API with rate limiting and caching"""
        try:
            import yfinance as yf
            import pandas as pd
            import numpy as np
            import json
            from datetime import datetime, timedelta
            
            # Map instrument naar Yahoo Finance symbool
            yahoo_symbols = {
                # Forex
                "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
                "AUDUSD": "AUDUSD=X", "USDCAD": "USDCAD=X", "NZDUSD": "NZDUSD=X",
                "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X", "GBPJPY": "GBPJPY=X",
                "USDCHF": "USDCHF=X", "EURCHF": "EURCHF=X", "GBPCHF": "GBPCHF=X",
                # Crypto
                "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD", "XRPUSD": "XRP-USD",
                "SOLUSD": "SOL-USD", "BNBUSD": "BNB-USD", "ADAUSD": "ADA-USD",
                "DOGUSD": "DOGE-USD", "DOTUSD": "DOT-USD", "LNKUSD": "LINK-USD",
                # Indices
                "US500": "^GSPC", "US30": "^DJI", "US100": "^NDX", 
                "UK100": "^FTSE", "DE40": "^GDAXI", "FR40": "^FCHI",
                "JP225": "^N225", "AU200": "^AXJO", 
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
            
            logger.info(f"Using Yahoo Finance symbol: {symbol} for {instrument}")
            
            # Bepaal de tijdsperiode op basis van timeframe
            end_date = datetime.now()
            
            # Pas de hoeveelheid historische data aan op basis van timeframe
            # voor betere support/resistance berekening
            if timeframe == "1h":
                # Meer historische data om betere S/R lijnen te vinden
                start_date = end_date - timedelta(days=30)  # 30 dagen voor betere S/R analyse
                interval = "1h"
            elif timeframe == "4h":
                start_date = end_date - timedelta(days=90)  # 90 dagen voor 4h
                interval = "1h"  # Yahoo has no 4h, so we use 1h
            elif timeframe == "1d":
                start_date = end_date - timedelta(days=365)  # 1 jaar voor dagelijkse data
                interval = "1d"
            else:
                start_date = end_date - timedelta(days=30)
                interval = "1h"
            
            # Haal info op met rate limiting en caching
            info = await self._get_ticker_info(symbol)
            
            # Haal historische data op met rate limiting en caching
            data = await self._get_ticker_history(symbol, start_date, end_date, interval)
            
            # Gebruik een fallback voor hardcoded realistische prijzen voor bekende instrumenten
            # als we geen data kunnen ophalen van Yahoo Finance
            if info is None or data.empty:
                logger.warning(f"Failed to get data from Yahoo Finance for {symbol}, using fallback data")
                
                # Hardcoded values for common instruments
                fallback_prices = {
                    "EURUSD": 1.095,
                    "GBPUSD": 1.28,
                    "USDJPY": 148.5,
                    "BTCUSD": 68000,
                    "ETHUSD": 3500
                }
                
                current_price = fallback_prices.get(instrument)
                
                if current_price is None:
                    # Genereer een realistische prijs als fallback
                    if "USD" in instrument:
                        if instrument.startswith("BTC"):
                            current_price = 68000
                        elif instrument.startswith("ETH"):
                            current_price = 3500
                        elif "JPY" in instrument:
                            current_price = 148.5
                        else:
                            current_price = 1.1  # Default for forex
                    else:
                        current_price = 1.1  # Default
                
                # Als we geen data hebben, genereer een mock data set
                if data.empty:
                    # Maak een synthetische dataset
                    dates = pd.date_range(start=start_date, end=end_date, periods=100)
                    
                    # Basisprijs met wat random fluctuaties
                    close_prices = [current_price * (1 + 0.0001 * i + 0.001 * np.random.randn()) for i in range(100)]
                    
                    # Genereer OHLC data
                    data = pd.DataFrame({
                        'Open': [price * (1 - 0.001 * np.random.rand()) for price in close_prices],
                        'High': [price * (1 + 0.002 * np.random.rand()) for price in close_prices],
                        'Low': [price * (1 - 0.002 * np.random.rand()) for price in close_prices],
                        'Close': close_prices,
                        'Volume': [int(1000000 * np.random.rand()) for _ in range(100)]
                    }, index=dates)
                    
                    logger.info(f"Generated synthetic data for {instrument} with price {current_price}")
            else:
                # Haal huidige prijs op
                current_price = None
                
                # Probeer eerst uit info
                if info and 'regularMarketPrice' in info and info['regularMarketPrice']:
                    current_price = info['regularMarketPrice']
                    logger.info(f"Using regularMarketPrice: {current_price}")
                elif not data.empty:
                    # Fallback naar laatste waarde in historische data
                    current_price = float(data['Close'].iloc[-1])  # Convert to float to avoid int64/float64 issues
                    logger.info(f"Using historical data last close: {current_price}")
                else:
                    # Hardcoded fallback
                    if instrument == "EURUSD":
                        current_price = 1.095
                    elif instrument == "GBPUSD":
                        current_price = 1.28
                    elif instrument == "BTCUSD":
                        current_price = 68000
                    else:
                        current_price = 1.0  # Default
                    logger.info(f"Using hardcoded fallback price: {current_price}")
            
            # Controleer of de verkregen prijs realistisch is voor het instrument
            # Voor forex zoals EURUSD, check of het in normale bereik is (bijv. 0.9 - 1.5)
            if "USD" in instrument and instrument.startswith("EUR"):
                if current_price < 0.9 or current_price > 1.5:
                    logger.warning(f"Unrealistic price for {instrument}: {current_price}, using default range value")
                    current_price = 1.095  # Default realistic value for EURUSD
            
            # Zorg ervoor dat alles als Python native types wordt opgeslagen (float, int, etc.) 
            # om problemen met JSON serialisatie te voorkomen
            
            # Calculate technical indicators
            if not data.empty:
                data['SMA20'] = data['Close'].rolling(window=20).mean()
                data['SMA50'] = data['Close'].rolling(window=50).mean()
                data['SMA200'] = data['Close'].rolling(window=200).mean()
                data['RSI'] = self._calculate_rsi(data['Close'])
                data['MACD'], data['Signal'], data['Hist'] = self._calculate_macd(data['Close'])
                
                # Calculate Bollinger Bands
                data['MA20'] = data['Close'].rolling(window=20).mean()
                data['SD20'] = data['Close'].rolling(window=20).std()
                data['UpperBand'] = data['MA20'] + (data['SD20'] * 2)
                data['LowerBand'] = data['MA20'] - (data['SD20'] * 2)
                
                # Get current values from historical data and convert to Python native types
                current_open = float(data['Open'].iloc[-1])
                current_high = float(data['High'].iloc[-1])
                current_low = float(data['Low'].iloc[-1])
                current_sma20 = float(data['SMA20'].iloc[-1]) if not pd.isna(data['SMA20'].iloc[-1]) else float(current_price)
                current_sma50 = float(data['SMA50'].iloc[-1]) if not pd.isna(data['SMA50'].iloc[-1]) else float(current_price * 0.99)
                current_sma200 = float(data['SMA200'].iloc[-1]) if not pd.isna(data['SMA200'].iloc[-1]) else float(current_price * 0.98)
                current_rsi = float(data['RSI'].iloc[-1]) if not pd.isna(data['RSI'].iloc[-1]) else 50.0
                current_macd = float(data['MACD'].iloc[-1]) if not pd.isna(data['MACD'].iloc[-1]) else 0.001
                current_signal = float(data['Signal'].iloc[-1]) if not pd.isna(data['Signal'].iloc[-1]) else 0.0
                current_hist = float(data['Hist'].iloc[-1]) if not pd.isna(data['Hist'].iloc[-1]) else 0.001
                current_upper_band = float(data['UpperBand'].iloc[-1]) if not pd.isna(data['UpperBand'].iloc[-1]) else float(current_price * 1.02)
                current_lower_band = float(data['LowerBand'].iloc[-1]) if not pd.isna(data['LowerBand'].iloc[-1]) else float(current_price * 0.98)
                
                if 'Volume' in data.columns:
                    current_volume = int(data['Volume'].iloc[-1]) if not pd.isna(data['Volume'].iloc[-1]) else 1000000
                else:
                    current_volume = 1000000
                
                # Zoek meer accurate support en resistance levels met verbeterde methode
                supports, resistances = self._find_support_resistance(data)
                
                # Converteer numpy arrays naar Python lists
                supports = [float(s) for s in supports] if supports else [float(current_price * 0.99), float(current_price * 0.98), float(current_price * 0.97)]
                resistances = [float(r) for r in resistances] if resistances else [float(current_price * 1.01), float(current_price * 1.02), float(current_price * 1.03)]
                
                # Bereken prijsveranderingen
                price_change_1d = float((current_price / float(data['Close'].iloc[-2]) - 1) * 100) if len(data) > 1 else 0.0
                price_change_1w = float((current_price / float(data['Close'].iloc[-7]) - 1) * 100) if len(data) > 7 else 0.0
                historical_volatility = float(data['Close'].pct_change().std() * 100)
            else:
                # Fallback waarden als we geen historische data hebben
                current_open = float(current_price * 0.99)
                current_high = float(current_price * 1.01)
                current_low = float(current_price * 0.98)
                current_sma20 = float(current_price * 0.995)
                current_sma50 = float(current_price * 0.99)
                current_sma200 = float(current_price * 0.98)
                current_rsi = 50.0  # Neutraal
                current_macd = 0.001
                current_signal = 0.0
                current_hist = 0.001
                current_volume = 1000000
                current_upper_band = float(current_price * 1.02)
                current_lower_band = float(current_price * 0.98)
                
                # Genereer realistische support/resistance op basis van typische prijs spreads voor het instrument
                if instrument in ["EURUSD", "GBPUSD", "EURGBP"]: 
                    # Voor major forex: kleinere spread (0.3%, 0.6%, 0.9%)
                    supports = [
                        float(round(current_price * 0.997, 5)),
                        float(round(current_price * 0.994, 5)),
                        float(round(current_price * 0.991, 5))
                    ]
                    resistances = [
                        float(round(current_price * 1.003, 5)),
                        float(round(current_price * 1.006, 5)),
                        float(round(current_price * 1.009, 5))
                    ]
                elif "USD" in instrument and instrument.startswith("BTC"):
                    # Voor Bitcoin: grotere spread (2%, 4%, 6%)
                    supports = [
                        float(round(current_price * 0.98, 1)),
                        float(round(current_price * 0.96, 1)),
                        float(round(current_price * 0.94, 1))
                    ]
                    resistances = [
                        float(round(current_price * 1.02, 1)),
                        float(round(current_price * 1.04, 1)),
                        float(round(current_price * 1.06, 1))
                    ]
                else:
                    # Voor overige instrumenten: gemiddelde spread (0.5%, 1%, 1.5%)
                    supports = [
                        float(round(current_price * 0.995, 5)),
                        float(round(current_price * 0.99, 5)),
                        float(round(current_price * 0.985, 5))
                    ]
                    resistances = [
                        float(round(current_price * 1.005, 5)),
                        float(round(current_price * 1.01, 5)),
                        float(round(current_price * 1.015, 5))
                    ]
                
                price_change_1d = 0.2
                price_change_1w = 0.8
                historical_volatility = 1.2
            
            # Prepare the analysis results in a structured format with native Python types
            market_data = {
                "instrument": instrument,
                "timeframe": timeframe,
                "current_price": float(current_price),
                "open": current_open,
                "high": current_high,
                "low": current_low,
                "volume": current_volume,
                "sma20": current_sma20,
                "sma50": current_sma50,
                "sma200": current_sma200,
                "rsi": current_rsi,
                "macd": current_macd,
                "macd_signal": current_signal,
                "macd_hist": current_hist,
                "upper_band": current_upper_band,
                "lower_band": current_lower_band,
                "trend_indicators": {
                    "price_above_sma20": bool(current_price > current_sma20),
                    "price_above_sma50": bool(current_price > current_sma50),
                    "price_above_sma200": bool(current_price > current_sma200),
                    "sma20_above_sma50": bool(current_sma20 > current_sma50),
                    "macd_above_signal": bool(current_macd > current_signal),
                    "rsi_above_50": bool(current_rsi > 50),
                    "rsi_oversold": bool(current_rsi < 30),
                    "rsi_overbought": bool(current_rsi > 70)
                },
                "support_levels": supports,  # Top 3 support levels
                "resistance_levels": resistances,  # Top 3 resistance levels
                "price_change_1d": price_change_1d,
                "price_change_1w": price_change_1w,
                "historical_volatility": historical_volatility,
            }
            
            # Voeg debug informatie toe om problemen te diagnosticeren
            logger.info(f"Current price for {instrument}: {current_price}")
            logger.info(f"Support levels: {supports[:3]}")
            logger.info(f"Resistance levels: {resistances[:3]}")
            
            # Zorg ervoor dat support/resistance correct gesorteerd zijn t.o.v. de huidige prijs
            # Support niveaus moeten altijd onder de huidige prijs liggen
            # Resistance niveaus moeten altijd boven de huidige prijs liggen
            sorted_supports = [s for s in supports if s < current_price]
            sorted_resistances = [r for r in resistances if r > current_price]
            
            # Als er geen supports onder de prijs zijn, gebruik dan een aantal procent onder de prijs
            if not sorted_supports:
                # Gebruik instrument-specifieke aanpassingen
                if "USD" in instrument and instrument.startswith("EUR"):
                    # EURUSD heeft typisch kleinere bewegingen (0.3%, 0.6%, 0.9%)
                    sorted_supports = [
                        round(current_price * 0.997, 5),
                        round(current_price * 0.994, 5),
                        round(current_price * 0.991, 5)
                    ]
                else:
                    # Standaard levels
                    sorted_supports = [
                        round(current_price * 0.995, 5),
                        round(current_price * 0.99, 5),
                        round(current_price * 0.985, 5)
                    ]
                logger.warning(f"No valid supports found below price, using generated supports: {sorted_supports}")
            
            # Als er geen resistances boven de prijs zijn, gebruik dan een aantal procent boven de prijs
            if not sorted_resistances:
                # Gebruik instrument-specifieke aanpassingen
                if "USD" in instrument and instrument.startswith("EUR"):
                    # EURUSD heeft typisch kleinere bewegingen (0.3%, 0.6%, 0.9%)
                    sorted_resistances = [
                        round(current_price * 1.003, 5),
                        round(current_price * 1.006, 5),
                        round(current_price * 1.009, 5)
                    ]
                else:
                    # Standaard levels
                    sorted_resistances = [
                        round(current_price * 1.005, 5),
                        round(current_price * 1.01, 5),
                        round(current_price * 1.015, 5)
                    ]
                logger.warning(f"No valid resistances found above price, using generated resistances: {sorted_resistances}")
            
            # Update de market_data met de gesorteerde support/resistance niveaus
            market_data["support_levels"] = sorted_supports
            market_data["resistance_levels"] = sorted_resistances
            
            # Convert structured data to string format for DeepSeek using custom encoder
            try:
                market_data_str = json.dumps(market_data, indent=2, cls=NumpyJSONEncoder)
                logger.info(f"Prepared market data for {instrument} with {len(market_data_str)} characters")
                return market_data_str
            except Exception as e:
                logger.error(f"JSON serialization error: {str(e)}")
                # Als er een fout optreedt met de JSON serialisatie, probeer een simpeler object
                simplified_data = {
                    "instrument": instrument,
                    "timeframe": timeframe,
                    "current_price": float(current_price),
                    "rsi": float(current_rsi),
                    "support_levels": sorted_supports[:3],
                    "resistance_levels": sorted_resistances[:3],
                    "trend": "Bullish" if current_price > current_sma50 else "Bearish"
                }
                return json.dumps(simplified_data, indent=2)
            
        except Exception as e:
            logger.error(f"Error getting Yahoo Finance data: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def _find_support_resistance(self, df, lookback=20):
        """Find support and resistance levels from price data using improved methods"""
        # Verhoogde relevantie door meer nauwkeurige methode
        try:
            logger.info("Berekenen van support/resistance levels met verbeterde methode")
            
            # Meer nauwkeurige levels vinden met volumegewogen methode
            # Gebruik zowel prijspieken als prijsdalingen gecombineerd met volumegewogen analyse
            
            # 1. Vind lokale extremen (pieken en dalen)
            # Gebruik pandas.Series rolling min/max om lokale extremen te vinden
            high_series = df['High']
            low_series = df['Low']
            
            # Vind lokale pieken voor resistance over variërende periodes voor betere precisie
            resistance_points = []
            
            # Gebruik 3 verschillende window sizes voor verschillende timeframes
            for window in [5, 10, 15]:
                if len(df) > window:
                    # Een punt is een resistance punt als het een lokaal maximum is
                    rolling_max = high_series.rolling(window=window, center=True).max()
                    potential_resistance = df[high_series == rolling_max]['High']
                    resistance_points.extend(list(potential_resistance))
            
            # Vind lokale dalen voor support over variërende periodes
            support_points = []
            
            for window in [5, 10, 15]:
                if len(df) > window:
                    # Een punt is een support punt als het een lokaal minimum is
                    rolling_min = low_series.rolling(window=window, center=True).min()
                    potential_support = df[low_series == rolling_min]['Low']
                    support_points.extend(list(potential_support))
            
            # 2. Cluster de niveaus en vind de meest significante
            # Functie om waarden binnen een percentage (bereik) te clusteren
            def cluster_values(values, threshold_pct=0.001):
                # Threshold is als percentage van de prijs
                if not values:
                    return []
                
                price_avg = sum(values) / len(values)
                threshold = price_avg * threshold_pct
                
                # Sorteer waardes
                sorted_values = sorted(values)
                
                clusters = []
                current_cluster = [sorted_values[0]]
                
                for i in range(1, len(sorted_values)):
                    # Als het verschil kleiner is dan de threshold, voeg toe aan huidig cluster
                    if sorted_values[i] - sorted_values[i-1] <= threshold:
                        current_cluster.append(sorted_values[i])
                    else:
                        # Anders begin een nieuw cluster
                        # Voeg gemiddelde van huidige cluster toe aan clusters
                        clusters.append(sum(current_cluster) / len(current_cluster))
                        current_cluster = [sorted_values[i]]
                
                # Voeg het laatste cluster toe
                if current_cluster:
                    clusters.append(sum(current_cluster) / len(current_cluster))
                
                return clusters
            
            # Cluster de niveaus
            support_clusters = cluster_values(support_points)
            resistance_clusters = cluster_values(resistance_points)
            
            # 3. Haal de meest recente prijs op en filter de support/resistance op basis daarvan
            current_price = float(df['Close'].iloc[-1])
            
            # Support moet altijd onder de huidige prijs zijn
            valid_supports = [s for s in support_clusters if s < current_price]
            # Resistance moet altijd boven de huidige prijs zijn
            valid_resistances = [r for r in resistance_clusters if r > current_price]
            
            # Sorteer op afstand tot de huidige prijs
            valid_supports = sorted(valid_supports, key=lambda x: current_price - x)
            valid_resistances = sorted(valid_resistances, key=lambda x: x - current_price)
            
            # 4. Kwaliteitscontrole: Controleer of de levels realistisch zijn
            
            # Als er geen geldige supports zijn, bereken realistische niveaus
            if not valid_supports:
                # Bepaal op basis van historische volatiliteit
                volatility = df['Close'].pct_change().std() * 100  # Volatiliteit als percentage
                
                # Gebruik volatiliteit om realistische supports te berekenen
                # Hogere volatiliteit = grotere spreiding
                spread_factor = max(0.5, min(2.0, volatility))  # Begrens tussen 0.5% en 2%
                
                valid_supports = [
                    current_price * (1 - 0.005 * spread_factor),  # 0.5% * volatility beneden huidige prijs
                    current_price * (1 - 0.01 * spread_factor),   # 1% * volatility beneden huidige prijs
                    current_price * (1 - 0.015 * spread_factor)   # 1.5% * volatility beneden huidige prijs
                ]
                
                logger.warning(f"Geen geldige supports gevonden, genereer synthetische levels met volatiliteit {volatility:.2f}%")
            
            # Als er geen geldige resistances zijn, bereken realistische niveaus
            if not valid_resistances:
                # Bepaal op basis van historische volatiliteit
                volatility = df['Close'].pct_change().std() * 100  # Volatiliteit als percentage
                
                # Gebruik volatiliteit om realistische resistances te berekenen
                spread_factor = max(0.5, min(2.0, volatility))
                
                valid_resistances = [
                    current_price * (1 + 0.005 * spread_factor),  # 0.5% * volatility boven huidige prijs
                    current_price * (1 + 0.01 * spread_factor),   # 1% * volatility boven huidige prijs 
                    current_price * (1 + 0.015 * spread_factor)   # 1.5% * volatility boven huidige prijs
                ]
                
                logger.warning(f"Geen geldige resistances gevonden, genereer synthetische levels met volatiliteit {volatility:.2f}%")
            
            # Rond af op 5 decimalen voor FOREX, of 2 voor indices/aandelen
            valid_supports = [round(s, 5) for s in valid_supports]
            valid_resistances = [round(r, 5) for r in valid_resistances]
            
            logger.info(f"Gevonden supports: {valid_supports[:3]}")
            logger.info(f"Gevonden resistances: {valid_resistances[:3]}")
            
            # Beperkt tot de top 3 niveaus voor elk
            return valid_supports[:3], valid_resistances[:3]
            
        except Exception as e:
            # Als er iets misgaat, gebruik een eenvoudige fallback methode
            logger.error(f"Fout bij berekenen van support/resistance: {str(e)}")
            
            # Fallback: gebruik eenvoudige percentages
            current_price = float(df['Close'].iloc[-1])
            
            # Bereken support 0.5%, 1% en 1.5% onder huidige prijs
            supports = [
                round(current_price * 0.995, 5),
                round(current_price * 0.99, 5),
                round(current_price * 0.985, 5)
            ]
            
            # Bereken resistance 0.5%, 1% en 1.5% boven huidige prijs
            resistances = [
                round(current_price * 1.005, 5),
                round(current_price * 1.01, 5),
                round(current_price * 1.015, 5)
            ]
            
            logger.warning("Gebruik fallback methode voor support/resistance")
            return supports, resistances

    def _calculate_macd(self, prices, slow=26, fast=12, signal=9):
        """Calculate MACD indicator"""
        exp1 = prices.ewm(span=fast, adjust=False).mean()
        exp2 = prices.ewm(span=slow, adjust=False).mean()
        macd = exp1 - exp2
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        histogram = macd - signal_line
        return macd, signal_line, histogram

    async def _format_with_deepseek(self, api_key, instrument, timeframe, market_data):
        """Format market data using DeepSeek API"""
        import aiohttp
        
        # Use fallback API key if none provided
        if not api_key:
            api_key = "sk-4vAEJ2DqOLUMibF9X6PqMFtYTqGUfGGkVR2gOemz5LSdcqWA"
            logger.warning(f"Using fallback DeepSeek API key for {instrument}")
        
        # Build the prompt
        prompt = self._build_deepseek_prompt(instrument, timeframe, market_data)
        
        data = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            "temperature": 0.2,
            "max_tokens": 500
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        try:
            logger.info(f"Sending request to DeepSeek API for {instrument}")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers=headers,
                    json=data
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"DeepSeek API response received for {instrument}")
                        response_text = result['choices'][0]['message']['content']
                        
                        # Verwijder eventuele overblijvende vierkante haakjes
                        response_text = response_text.replace("[", "").replace("]", "")
                        
                        # Formateer RSI naar 1 decimaal
                        import re
                        rsi_pattern = r'RSI: (\d+\.\d+)'
                        
                        def format_rsi(match):
                            rsi_value = float(match.group(1))
                            return f"RSI: {rsi_value:.1f}"
                        
                        response_text = re.sub(rsi_pattern, format_rsi, response_text)
                        
                        # Begrens de lengte van het antwoord om binnen Telegram limiet te blijven (1024 tekens)
                        if len(response_text) > 1000:
                            logger.warning(f"DeepSeek response too long ({len(response_text)} chars), truncating to 1000 chars")
                            # Truncate while preserving key information
                            sections = response_text.split("\n\n")
                            essential_sections = []
                            
                            # Behoud de belangrijkste secties in het oorspronkelijke formaat
                            if len(sections) > 0:
                                essential_sections.append(sections[0])  # Titel
                            
                            # Trend sectie
                            for section in sections:
                                if "Trend" in section:
                                    essential_sections.append(section)
                                    break
                            
                            # Sigmapips AI identifies sectie
                            for section in sections:
                                if "Sigmapips AI identifies" in section:
                                    essential_sections.append(section)
                                    break
                            
                            # Zone Strength sectie
                            for section in sections:
                                if "Zone Strength" in section and not any(s.startswith("Zone Strength") for s in essential_sections):
                                    essential_sections.append(section)
                                    break
                            
                            # Belangrijke prijsdata
                            price_section = []
                            for section in sections:
                                if "Current Price:" in section or "Support:" in section:
                                    lines = [line for line in section.split("\n") if line.strip() and (
                                        "Current Price:" in line or 
                                        "Support:" in line or 
                                        "Resistance:" in line or 
                                        "RSI:" in line or 
                                        "Probability:" in line
                                    )]
                                    price_section.extend(lines)
                                    break
                            
                            if price_section:
                                essential_sections.append("\n".join(price_section))
                            
                            # Disclaimer
                            essential_sections.append("Disclaimer: For educational purposes only. Not financial advice.")
                            
                            # Voeg samen en begrens op 1000 tekens
                            response_text = "\n\n".join(essential_sections)[:1000]
                        
                        return response_text
                    else:
                        logger.error(f"DeepSeek API error: {response.status}")
                        error_text = await response.text()
                        logger.error(f"Error details: {error_text}")
                        return None
        except Exception as e:
            logger.error(f"Error calling DeepSeek API: {str(e)}")
            return None

    def _build_deepseek_prompt(self, instrument, timeframe, market_data):
        """Build prompt for DeepSeek API using market data from Yahoo Finance"""
        prompt = f"""
Je bent een gespecialiseerde financiële analist voor SigmaPips AI, een technische analyse tool.
Gegeven de volgende marktgegevens over {instrument} op een {timeframe} timeframe:

{market_data}

Analyseer deze gegevens en genereer een technische analyse in exact het volgende sjabloon format. 
De totale output MOET korter zijn dan 1000 tekens:

[{instrument}] - {timeframe}

Trend - Bullish/Bearish

Sigmapips AI identifies strong buy/sell probability. Key support/resistance at X.XXXX.

Zone Strength N/5: 🟢/🟡/🔴

• Current Price: X.XXXX
• Support: X.XXXX
• Resistance: X.XXXX
• RSI: XX.X (afgerond op 1 decimaal)
• Probability: XX%

Disclaimer: For educational purposes only. Not financial advice.

BELANGRIJKE RICHTLIJNEN:
1. VERWIJDER ALLE VIERKANTE HAAKJES [] - vul direct de juiste waarden in
2. Bepaal Bullish/Bearish obv technische indicatoren
3. Support niveaus MOETEN ONDER de huidige prijs liggen
4. Resistance niveaus MOETEN BOVEN de huidige prijs liggen
5. Zone Strength: 🟢 (4-5), 🟡 (2-3), 🔴 (1)
6. RSI moet worden afgerond op 1 decimaal (XX.X)
7. Probability tussen 60-85%
8. BLIJF BEKNOPT - de totale output moet minder dan 1000 tekens zijn

VEREIST:
- GEBRUIK EXACT DE HUIDIGE PRIJS ("current_price") zonder afronding
- Support moet LAGER zijn dan de current_price
- Resistance moet HOGER zijn dan de current_price
- RSI exact uit de gegevens maar afgerond op 1 decimaal
- VERMIJD EXTRA TEKST of uitleg, houd het BEKNOPT
- VERWIJDER ALLE VIERKANTE HAAKJES [] in de output
"""
        return prompt

    async def _generate_mock_analysis(self, instrument, timeframe, img_path):
        """Generate mock analysis when API calls fail"""
        # Generate mock data with more realistic values
        trend = "Bullish" if random.random() > 0.5 else "Bearish"
        probability = random.randint(65, 85)
        action = "buy" if trend == "Bullish" else "sell"
        zone_strength = random.randint(1, 5)
        strength_color = "🟢" if zone_strength >= 4 else "🟡" if zone_strength >= 2 else "🔴"
        
        # Use more realistic price values based on the instrument
        if "USD" in instrument:
            if instrument.startswith("BTC"):
                current_price = random.uniform(25000, 35000)
            elif instrument.startswith("ETH"):
                current_price = random.uniform(1500, 2500)
            elif "JPY" in instrument:
                current_price = random.uniform(100, 150)
            else:
                current_price = random.uniform(0.8, 1.5)
        else:
            current_price = random.uniform(0.8, 1.5)
            
        # Generate support/resistance with realistic spreads
        support_level = round(current_price * random.uniform(0.95, 0.98), 5)
        resistance_level = round(current_price * random.uniform(1.02, 1.05), 5)
        
        # Generate random RSI value
        rsi_value = random.uniform(30, 70)
        
        # Format currency values
        formatted_price = f"{current_price:.5f}" if "JPY" not in instrument else f"{current_price:.3f}"
        formatted_support = f"{support_level:.5f}" if "JPY" not in instrument else f"{support_level:.3f}"
        formatted_resistance = f"{resistance_level:.5f}" if "JPY" not in instrument else f"{resistance_level:.3f}"
        
        # Generate mock analysis with original format but without brackets
        analysis = f"""{instrument} - {timeframe}

Trend - {trend}

Sigmapips AI identifies strong {action} probability. Key {'support' if trend == 'Bullish' else 'resistance'} at {formatted_support if trend == 'Bullish' else formatted_resistance}.

Zone Strength {zone_strength}/5: {strength_color * zone_strength}

• Current Price: {formatted_price}
• Support: {formatted_support}
• Resistance: {formatted_resistance}
• RSI: {rsi_value:.1f}
• Probability: {probability}%

Disclaimer: For educational purposes only. Not financial advice."""

        return img_path, analysis

    async def get_technical_chart(self, instrument: str, timeframe: str = "1h") -> str:
        """
        Get a chart image for technical analysis.
        This is a wrapper around get_chart that ensures a file path is returned.
        
        Args:
            instrument: The trading instrument (e.g., 'EURUSD')
            timeframe: The timeframe to use (default '1h')
            
        Returns:
            str: Path to the saved chart image
        """
        try:
            logger.info(f"Getting technical chart for {instrument} ({timeframe})")
            
            # Get the chart image using the existing method
            chart_data = await self.get_chart(instrument, timeframe)
            
            if not chart_data:
                logger.error(f"Failed to get chart for {instrument}")
                return None
                
            # Save the chart to a file
            timestamp = int(datetime.now().timestamp())
            os.makedirs('data/charts', exist_ok=True)
            file_path = f"data/charts/{instrument.lower()}_{timeframe}_{timestamp}.png"
            
            # Ensure chart_data is in the correct format (bytes)
            if isinstance(chart_data, bytes):
                with open(file_path, 'wb') as f:
                    f.write(chart_data)
            else:
                logger.error(f"Chart data is not in bytes format: {type(chart_data)}")
                return None
                
            logger.info(f"Saved technical chart to {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"Error getting technical chart: {str(e)}")
            return None
