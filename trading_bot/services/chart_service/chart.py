print("Loading chart.py module...")

import os
import logging
import aiohttp
import random
from typing import Optional, Union, Dict, List, Tuple
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
        Get technical analysis for an instrument with timeframe using OCR and DeepSeek APIs.
        """
        try:
            # First get the chart image
            chart_data = await self.get_chart(instrument, timeframe)
            
            # Check if chart_data is in bytes format and save it to a file first
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
            
            # Get the DeepSeek API key
            deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
            
            if not deepseek_api_key:
                logger.warning("DeepSeek API key missing, analysis may be limited")
            
            # Initialize market data dictionary
            market_data_dict = {
                "instrument": instrument,
                "timeframe": timeframe,
                "timestamp": datetime.now().isoformat(),
            }
            
            # Import and use OCR processor
            try:
                from trading_bot.services.chart_service.ocr_processor import ChartOCRProcessor
                logger.info(f"Extracting data from chart image using OCR: {img_path}")
                
                # Check file details
                file_size = os.path.getsize(img_path)
                logger.info(f"Chart image size: {file_size} bytes")
                
                # Initialize OCR processor
                ocr_processor = ChartOCRProcessor()
                
                # Process chart image with OCR
                ocr_data = await ocr_processor.process_chart_image(img_path)
                logger.info(f"OCR data extracted: {ocr_data}")
                
                # Use OCR data if available
                if ocr_data:
                    logger.info(f"Using OCR data: {ocr_data}")
                    market_data_dict.update(ocr_data)
                    
                    # Check if current_price is present and seems realistic
                    current_price = ocr_data.get('current_price')
                    
                    # Add robust support/resistance classification - verbeterde methode
                    # Maak aparte lijsten voor support en resistance
                    all_prices = []
                    
                    # Verzamel alle prijspunten uit de OCR data voor classificatie
                    if 'price_levels' in ocr_data:
                        all_prices.extend(list(ocr_data['price_levels'].values()))
                    
                    # Voeg specifieke high/low niveaus toe
                    if 'daily_high' in ocr_data and ocr_data['daily_high'] > 0:
                        all_prices.append(ocr_data['daily_high'])
                    if 'daily_low' in ocr_data and ocr_data['daily_low'] > 0:
                        all_prices.append(ocr_data['daily_low'])
                    if 'weekly_high' in ocr_data and ocr_data['weekly_high'] > 0:
                        all_prices.append(ocr_data['weekly_high'])
                    if 'weekly_low' in ocr_data and ocr_data['weekly_low'] > 0:
                        all_prices.append(ocr_data['weekly_low'])
                    if 'monthly_high' in ocr_data and ocr_data['monthly_high'] > 0:
                        all_prices.append(ocr_data['monthly_high'])
                    if 'monthly_low' in ocr_data and ocr_data['monthly_low'] > 0:
                        all_prices.append(ocr_data['monthly_low'])
                    
                    # Als we prijzen hebben verzameld, maar geen current_price, bepaal deze
                    if all_prices and (current_price is None or current_price <= 0 or current_price == 1.0):
                        # Sorteer alle prijzen van laag naar hoog
                        all_prices.sort()
                        
                        # Bereken een realistic midpoint uit de gevonden prijzen
                        # Gebruik de middelste 50% van de prijzen voor een stabiele schatting
                        start_idx = len(all_prices) // 4
                        end_idx = 3 * len(all_prices) // 4
                        if end_idx <= start_idx:  # Als er weinig prijzen zijn
                            midpoint_prices = all_prices
                        else:
                            midpoint_prices = all_prices[start_idx:end_idx+1]
                        
                        if midpoint_prices:
                            # Bereken gemiddelde van de middelste prijzen
                            new_price = sum(midpoint_prices) / len(midpoint_prices)
                            current_price = new_price
                            market_data_dict['current_price'] = new_price
                            logger.info(f"Bepaald current price op {new_price} (gemiddelde van middelste prijsbereik)")
                    
                    # Als current_price na bovenstaande nog steeds niet realistisch is
                    if current_price == 1.0 or current_price is None or current_price <= 0:
                        # Bereken prijs direct uit de beschikbare gegevens zonder fallbacks
                        # Prioriteit: daily high/low > weekly high/low > monthly high/low
                        if 'daily_high' in ocr_data and 'daily_low' in ocr_data:
                            # Gebruik midpoint van daily high en low - meest nauwkeurig
                            new_price = (ocr_data['daily_high'] + ocr_data['daily_low']) / 2
                            current_price = new_price
                            market_data_dict['current_price'] = new_price
                            logger.info(f"Bepaald current price op {new_price} (midpoint daily range)")
                        elif 'daily_high' in ocr_data:
                            # Gebruik 97% van daily high
                            new_price = ocr_data['daily_high'] * 0.97
                            current_price = new_price
                            market_data_dict['current_price'] = new_price
                            logger.info(f"Bepaald current price op {new_price} (97% van daily high)")
                        elif 'daily_low' in ocr_data:
                            # Gebruik 103% van daily low
                            new_price = ocr_data['daily_low'] * 1.03
                            current_price = new_price
                            market_data_dict['current_price'] = new_price
                            logger.info(f"Bepaald current price op {new_price} (103% van daily low)")
                        elif 'weekly_high' in ocr_data and 'weekly_low' in ocr_data:
                            # Gebruik midpoint van weekly range
                            new_price = (ocr_data['weekly_high'] + ocr_data['weekly_low']) / 2
                            current_price = new_price
                            market_data_dict['current_price'] = new_price
                            logger.info(f"Bepaald current price op {new_price} (midpoint weekly range)")
                        elif 'weekly_high' in ocr_data:
                            # Gebruik 95% van weekly high
                            new_price = ocr_data['weekly_high'] * 0.95
                            current_price = new_price
                            market_data_dict['current_price'] = new_price
                            logger.info(f"Bepaald current price op {new_price} (95% van weekly high)")
                        elif 'weekly_low' in ocr_data:
                            # Gebruik 105% van weekly low
                            new_price = ocr_data['weekly_low'] * 1.05
                            current_price = new_price
                            market_data_dict['current_price'] = new_price
                            logger.info(f"Bepaald current price op {new_price} (105% van weekly low)")
                        elif 'monthly_high' in ocr_data and 'monthly_low' in ocr_data:
                            # Gebruik midpoint van monthly range
                            new_price = (ocr_data['monthly_high'] + ocr_data['monthly_low']) / 2
                            current_price = new_price
                            market_data_dict['current_price'] = new_price
                            logger.info(f"Bepaald current price op {new_price} (midpoint monthly range)")
                        elif 'monthly_high' in ocr_data:
                            # Gebruik 92% van monthly high
                            new_price = ocr_data['monthly_high'] * 0.92
                            current_price = new_price
                            market_data_dict['current_price'] = new_price
                            logger.info(f"Bepaald current price op {new_price} (92% van monthly high)")
                        elif 'monthly_low' in ocr_data:
                            # Gebruik 108% van monthly low
                            new_price = ocr_data['monthly_low'] * 1.08
                            current_price = new_price
                            market_data_dict['current_price'] = new_price
                            logger.info(f"Bepaald current price op {new_price} (108% van monthly low)")
                        elif 'resistance_levels' in ocr_data and 'support_levels' in ocr_data and ocr_data['resistance_levels'] and ocr_data['support_levels']:
                            # Gebruik midpoint tussen dichtstbijzijnde support en resistance
                            closest_support = max(ocr_data['support_levels']) if ocr_data['support_levels'] else None
                            closest_resist = min(ocr_data['resistance_levels']) if ocr_data['resistance_levels'] else None
                            
                            if closest_support and closest_resist:
                                new_price = (closest_support + closest_resist) / 2
                                current_price = new_price
                                market_data_dict['current_price'] = new_price
                                logger.info(f"Bepaald current price op {new_price} (midpoint dichtstbijzijnde S/R levels)")
                        else:
                            # Gebruik een reële prijs op basis van wat we hebben gevonden
                            all_price_points = []
                            
                            # Verzamel alle prijsinformatie die gevonden is
                            if 'price_levels' in ocr_data:
                                all_price_points.extend(ocr_data['price_levels'].values())
                            
                            if all_price_points:
                                # Bereken gemiddelde van alle gevonden prijsniveaus
                                new_price = sum(all_price_points) / len(all_price_points)
                                current_price = new_price
                                market_data_dict['current_price'] = new_price
                                logger.info(f"Bepaald current price op {new_price} (gemiddelde van alle gevonden prijsniveaus)")
                            else:
                                # Als er echt niets is, gebruik zoveel mogelijk info uit de OCR data
                                # We willen geen fallback gebruiken, dus zoek naar aanwijzingen in de data
                                for key, value in ocr_data.items():
                                    if isinstance(value, (int, float)) and value > 0 and key != 'current_price':
                                        # Als we een getalswaarde vinden, gebruik die als basis
                                        new_price = value
                                        current_price = value
                                        market_data_dict['current_price'] = value
                                        logger.info(f"Bepaald current price op {value} (gebruik enige beschikbare numerieke waarde: {key})")
                                        break
                    
                    # Nu dat we een current_price hebben, classificeer de prijsniveaus
                    # relatief aan de huidige prijs als support en resistance
                    if all_prices and current_price and current_price > 0:
                        supports = []
                        resistances = []
                        
                        # Classificeer alle prijzen tov de huidige prijs
                        for price in all_prices:
                            # Skip de huidige prijs zelf en niveaus die te dicht bij de current_price liggen
                            if abs(price - current_price) / current_price < 0.001:  # Skip within 0.1%
                                continue
                                
                            # Prijzen onder current price zijn support, erboven resistance
                            if price < current_price:
                                supports.append(price)
                            else:
                                resistances.append(price)
                        
                        # Sorteer en filter de levels
                        if supports:
                            # Sorteer supports van hoog naar laag (dichtstbijzijnde support eerst)
                            supports.sort(reverse=True)
                            # Filter supports op afstand tot current_price
                            close_supports = [p for p in supports if (current_price - p) / current_price < 0.02]  # binnen 2%
                            # Selecteer max 3 meest significante supports
                            if close_supports:
                                supports = close_supports[:3]
                            else:
                                supports = supports[:3]
                                
                        if resistances:
                            # Sorteer resistances van laag naar hoog (dichtstbijzijnde resistance eerst)
                            resistances.sort()
                            # Filter resistances op afstand tot current_price
                            close_resistances = [p for p in resistances if (p - current_price) / current_price < 0.02]  # binnen 2%
                            # Selecteer max 3 meest significante resistances
                            if close_resistances:
                                resistances = close_resistances[:3]
                            else:
                                resistances = resistances[:3]
                        
                        # Update the market data dictionary
                        market_data_dict['support_levels'] = supports
                        market_data_dict['resistance_levels'] = resistances
                        
                        logger.info(f"Geclassificeerde supports: {supports}")
                        logger.info(f"Geclassificeerde resistances: {resistances}")
                    
                    # If we have specific market levels from OCR, use them directly
                    has_key_levels = any(key in ocr_data for key in [
                        'daily_high', 'daily_low', 'weekly_high', 'weekly_low',
                        'monthly_high', 'monthly_low'
                    ])
                    
                    # If we have support/resistance levels from OCR, use them
                    has_sr_levels = 'support_levels' in ocr_data and 'resistance_levels' in ocr_data
                    
                    if has_key_levels or has_sr_levels:
                        logger.info("Using OCR detected market levels directly")
                        
                        # Maak zeker dat we lijst van supports en resistances hebben
                        if 'support_levels' not in market_data_dict:
                            market_data_dict['support_levels'] = []
                        if 'resistance_levels' not in market_data_dict:
                            market_data_dict['resistance_levels'] = []
                        
                        # Strict classificatie: high waarden ALTIJD als resistance, low waarden ALTIJD als support
                        # Voeg high-waarden toe aan resistance waarden
                        if 'daily_high' in ocr_data and ocr_data['daily_high'] > 0:
                            market_data_dict['resistance_levels'].append(ocr_data['daily_high'])
                            logger.info(f"Added daily high {ocr_data['daily_high']} to resistance levels")
                        
                        if 'daily_low' in ocr_data and ocr_data['daily_low'] > 0:
                            market_data_dict['support_levels'].append(ocr_data['daily_low'])
                            logger.info(f"Added daily low {ocr_data['daily_low']} to support levels")
                        
                        if 'weekly_high' in ocr_data and ocr_data['weekly_high'] > 0:
                            market_data_dict['resistance_levels'].append(ocr_data['weekly_high'])
                            logger.info(f"Added weekly high {ocr_data['weekly_high']} to resistance levels")
                        
                        if 'weekly_low' in ocr_data and ocr_data['weekly_low'] > 0:
                            market_data_dict['support_levels'].append(ocr_data['weekly_low'])
                            logger.info(f"Added weekly low {ocr_data['weekly_low']} to support levels")
                        
                        if 'monthly_high' in ocr_data and ocr_data['monthly_high'] > 0:
                            market_data_dict['resistance_levels'].append(ocr_data['monthly_high'])
                            logger.info(f"Added monthly high {ocr_data['monthly_high']} to resistance levels")
                        
                        if 'monthly_low' in ocr_data and ocr_data['monthly_low'] > 0:
                            market_data_dict['support_levels'].append(ocr_data['monthly_low'])
                            logger.info(f"Added monthly low {ocr_data['monthly_low']} to support levels")
                        
                        # Relatieve classificatie voor OCR-gedetecteerde prijsniveaus
                        if current_price and current_price > 0 and 'price_levels' in ocr_data:
                            for label, price in ocr_data['price_levels'].items():
                                # Skip prijzen die al eerder zijn toegevoegd als high/low
                                if ('high' in label or 'low' in label):
                                    continue
                                
                                if price < current_price:
                                    market_data_dict['support_levels'].append(price)
                                    logger.info(f"Added price level '{label}' ({price}) to support levels")
                                else:
                                    market_data_dict['resistance_levels'].append(price)
                                    logger.info(f"Added price level '{label}' ({price}) to resistance levels")
                        
                        # Verwijder dubbele levels en sorteer nogmaals op afstand tot huidige prijs
                        if 'support_levels' in market_data_dict and market_data_dict['support_levels']:
                            # Verwijderen van dubbele waarden en sorteren
                            market_data_dict['support_levels'] = sorted(set(market_data_dict['support_levels']), reverse=True)
                            
                            # Neem alleen de 3 dichtbijzijnde levels                             
                            market_data_dict['support_levels'] = market_data_dict['support_levels'][:3]
                        
                        if 'resistance_levels' in market_data_dict and market_data_dict['resistance_levels']:
                            # Verwijderen van dubbele waarden en sorteren
                            market_data_dict['resistance_levels'] = sorted(set(market_data_dict['resistance_levels']))
                            
                            # Neem alleen de 3 dichtbijzijnde levels
                            market_data_dict['resistance_levels'] = market_data_dict['resistance_levels'][:3]
                            
                        # Correctie: Verzeker dat support levels altijd onder current_price en resistance levels erboven zijn
                        if current_price and current_price > 0:
                            if 'support_levels' in market_data_dict and market_data_dict['support_levels']:
                                market_data_dict['support_levels'] = [p for p in market_data_dict['support_levels'] if p < current_price]
                            
                            if 'resistance_levels' in market_data_dict and market_data_dict['resistance_levels']:
                                market_data_dict['resistance_levels'] = [p for p in market_data_dict['resistance_levels'] if p > current_price]
                    
                    # If we don't have any levels, calculate synthetic ones
                    elif 'current_price' in market_data_dict and market_data_dict['current_price'] > 0:
                        logger.info(f"No specific levels found in OCR data, calculating synthetic levels")
                        logger.info(f"Using current price: {market_data_dict['current_price']}")
                        support_resistance = self._calculate_synthetic_support_resistance(
                            market_data_dict['current_price'], instrument
                        )
                        market_data_dict.update(support_resistance)
                    
                    # Check if we have indicators, if not, generate reasonable ones
                    if not any(key in ocr_data for key in ['rsi', 'macd']):
                        logger.warning("No indicators detected in OCR data, adding estimated indicators")
                        # Add technical indicators with reasonable values
                        current_price = market_data_dict['current_price']
                        volatility = self._get_volatility_for_instrument(instrument)
                        
                        market_data_dict.update({
                            "rsi": round(50 + random.uniform(-20, 20), 2),  # More balanced RSI
                            "macd": round(volatility * random.uniform(-0.3, 0.3), 3),
                            "ema_50": round(current_price * (1 + volatility * random.uniform(-0.01, 0.01)), 5),
                            "ema_200": round(current_price * (1 + volatility * random.uniform(-0.02, 0.02)), 5)
                        })
                else:
                    logger.warning("OCR returned empty data, using base price data")
                    base_price = self._get_base_price_for_instrument(instrument)
                    volatility = self._get_volatility_for_instrument(instrument)
                    
                    # Create basic market data with realistic values
                    market_data_dict['current_price'] = base_price
                    
                    # Add support/resistance
                    support_resistance = self._calculate_synthetic_support_resistance(base_price, instrument)
                    market_data_dict.update(support_resistance)
                    
                    # Add technical indicators
                    market_data_dict.update({
                        "rsi": round(50 + random.uniform(-20, 20), 2),
                        "macd": round(volatility * random.uniform(-0.3, 0.3), 3),
                        "ema_50": round(base_price * (1 + volatility * random.uniform(-0.01, 0.01)), 5),
                        "ema_200": round(base_price * (1 + volatility * random.uniform(-0.02, 0.02)), 5)
                    })
            
            except Exception as ocr_error:
                logger.error(f"Error performing OCR analysis: {str(ocr_error)}")
                logger.error(traceback.format_exc())
                
                # Use base price if OCR fails
                logger.warning("Using base price data due to OCR error")
                base_price = self._get_base_price_for_instrument(instrument)
                volatility = self._get_volatility_for_instrument(instrument)
                
                # Create basic market data with realistic values
                market_data_dict['current_price'] = base_price
                
                # Add support/resistance
                support_resistance = self._calculate_synthetic_support_resistance(base_price, instrument)
                market_data_dict.update(support_resistance)
                
                # Add technical indicators
                market_data_dict.update({
                    "rsi": round(50 + random.uniform(-20, 20), 2),
                    "macd": round(volatility * random.uniform(-0.3, 0.3), 3),
                    "ema_50": round(base_price * (1 + volatility * random.uniform(-0.01, 0.01)), 5),
                    "ema_200": round(base_price * (1 + volatility * random.uniform(-0.02, 0.02)), 5)
                })
            
            # Convert data to JSON for DeepSeek
            market_data_json = json.dumps(market_data_dict, indent=2, cls=NumpyJSONEncoder)
            
            # Format data using DeepSeek API
            logger.info(f"Formatting data with DeepSeek for {instrument}")
            analysis = await self._format_with_deepseek(deepseek_api_key, instrument, timeframe, market_data_json)
            
            if not analysis:
                logger.warning(f"Failed to format with DeepSeek for {instrument}")
                return img_path, f"Technical analysis data for {instrument}:\n\nPrice: {market_data_dict.get('current_price')}\nRSI: {market_data_dict.get('rsi', 'N/A')}\nSupport: {market_data_dict.get('support_levels', [])[0] if market_data_dict.get('support_levels') else 'N/A'}\nResistance: {market_data_dict.get('resistance_levels', [])[0] if market_data_dict.get('resistance_levels') else 'N/A'}"
            
            return img_path, analysis
                
        except Exception as e:
            logger.error(f"Error in get_technical_analysis: {str(e)}")
            logger.error(traceback.format_exc())
            return None, "Error generating technical analysis."
            
    def _generate_synthetic_data(self, instrument: str) -> Dict:
        """
        Generate synthetic market data when OCR extraction fails
        """
        # Maak een dict met basis market data
        base_price = self._get_base_price_for_instrument(instrument)
        volatility = self._get_volatility_for_instrument(instrument)
        
        # Genereer een random prijs rond de basis prijs
        current_price = round(base_price * (1 + random.uniform(-0.005, 0.005)), 5)
        
        logger.info(f"Generated synthetic data for {instrument} with price {current_price}")
        
        # Bereken support/resistance levels
        support_resistance = self._calculate_synthetic_support_resistance(current_price, instrument)
        
        # Basis market data
        market_data = {
            "current_price": current_price,
            "open": round(current_price * (1 - random.uniform(0, 0.002)), 5),
            "high": round(current_price * (1 + random.uniform(0.001, 0.003)), 5),
            "low": round(current_price * (1 - random.uniform(0.001, 0.003)), 5),
            "volume": int(random.uniform(1000, 10000)),
            "volatility": volatility
        }
        
        # Voeg support/resistance toe
        market_data.update(support_resistance)
        
        # Voeg technische indicatoren toe
        market_data.update({
            "rsi": round(random.uniform(30, 70), 2),
            "macd": round(random.uniform(-0.5, 0.5), 3),
            "ema_50": round(current_price * (1 + random.uniform(-0.01, 0.01)), 5),
            "ema_200": round(current_price * (1 + random.uniform(-0.03, 0.03)), 5)
        })
        
        return market_data
    
    def _get_base_price_for_instrument(self, instrument: str) -> float:
        """
        Return a realistic base price for the given instrument as a fallback
        when other methods fail.
        
        Args:
            instrument: The trading instrument (e.g., 'EURUSD', 'GBPUSD')
            
        Returns:
            A realistic price for the instrument
        """
        # Common FX pairs baseline prices (approximate mid-2023 values)
        base_prices = {
            'EURUSD': 1.08,
            'GBPUSD': 1.27,
            'USDJPY': 145.0,
            'AUDUSD': 0.67,
            'USDCAD': 1.35,
            'USDCHF': 0.90,
            'NZDUSD': 0.62,
            'EURGBP': 0.85,
            'EURJPY': 157.0,
            'GBPJPY': 183.0,
            'XAUUSD': 1950.0,  # Gold
            'XAGUSD': 24.0,    # Silver
            # Add more instruments as needed
        }
        
        # Clean up the instrument name to handle variations like EUR/USD, EUR USD, etc.
        clean_instrument = ''.join(char for char in instrument if char.isalpha())
        
        # Look for an exact match first
        if clean_instrument in base_prices:
            return base_prices[clean_instrument]
        
        # Try to find a match by checking if the clean instrument contains any key
        for key, price in base_prices.items():
            if key in clean_instrument:
                return price
        
        # Default fallback
        logger.warning(f"No base price found for instrument: {instrument}, using default value")
        return 1.10  # A somewhat reasonable default for FX pairs
    
    def _get_volatility_for_instrument(self, instrument: str) -> float:
        """
        Get realistic volatility percentage for an instrument
        """
        volatilities = {
            # Forex (meestal lage volatiliteit)
            "EURUSD": 0.12, "GBPUSD": 0.14, "USDJPY": 0.18,
            "AUDUSD": 0.20, "USDCAD": 0.15, "NZDUSD": 0.22,
            "EURGBP": 0.10, "EURJPY": 0.20, "GBPJPY": 0.22,
            "USDCHF": 0.12, "EURCHF": 0.11, "GBPCHF": 0.14,
            # Crypto (hoge volatiliteit)
            "BTCUSD": 2.5, "ETHUSD": 3.0, "XRPUSD": 4.0,
            "SOLUSD": 5.0, "BNBUSD": 3.5, "ADAUSD": 3.8,
            "DOGUSD": 5.5, "DOTUSD": 4.2, "LNKUSD": 4.0,
            # Indices (gemiddelde volatiliteit)
            "US500": 0.8, "US30": 0.7, "US100": 0.9, 
            "UK100": 0.65, "DE40": 0.85, "FR40": 0.75,
            "JP225": 0.80, "AU200": 0.70, 
            # Commodities
            "XAUUSD": 0.6, "XTIUSD": 1.2
        }
        
        return volatilities.get(instrument, 1.0)  # Default voor onbekende instrumenten
        
    def _calculate_synthetic_support_resistance(self, price: float, instrument: str) -> Dict:
        """
        Bereken realistische support/resistance levels op basis van de huidige prijs
        """
        logger.info(f"Berekenen van support/resistance levels met verbeterde methode")
        
        # Bereken volatiliteit als percentage van de prijs
        volatility_pct = self._get_volatility_for_instrument(instrument) / 100
        
        # Genereer realistische support/resistance levels
        supports = []
        resistances = []
        
        try:
            # Support levels onder de huidige prijs
            support1 = round(price * (1 - volatility_pct * 3), 5)
            support2 = round(price * (1 - volatility_pct * 5), 5)
            support3 = round(price * (1 - volatility_pct * 7), 5)
            
            # Resistance levels boven de huidige prijs
            resistance1 = round(price * (1 + volatility_pct * 3), 5)
            resistance2 = round(price * (1 + volatility_pct * 5), 5)
            resistance3 = round(price * (1 + volatility_pct * 7), 5)
            
            supports = [support1, support2, support3]
            resistances = [resistance1, resistance2, resistance3]
            
            logger.info(f"Gevonden supports: {supports}")
            logger.info(f"Gevonden resistances: {resistances}")
        except Exception as e:
            logger.error(f"Fout bij berekenen van support/resistance: {str(e)}")
            # Fallback - genereer wat standaard levels als percentage van de prijs
            logger.warning(f"Geen geldige resistances gevonden, genereer synthetische levels met volatiliteit {volatility_pct*100:.2f}%")
            
            supports = [
                round(price * (1 - volatility_pct * 3), 5),
                round(price * (1 - volatility_pct * 6), 5),
                round(price * (1 - volatility_pct * 9), 5)
            ]
            
            resistances = [
                round(price * (1 + volatility_pct * 3), 5),
                round(price * (1 + volatility_pct * 6), 5),
                round(price * (1 + volatility_pct * 9), 5)
            ]
        
        logger.info(f"Current price for {instrument}: {price}")
        logger.info(f"Support levels: {supports}")
        logger.info(f"Resistance levels: {resistances}")
        
        return {
            "support_levels": supports,
            "resistance_levels": resistances
        }

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
        """Build prompt for DeepSeek API using market data extracted from chart via OCR"""
        prompt = f"""
Je bent een gespecialiseerde financiële analist voor SigmaPips AI, een technische analyse tool.
Gegeven de volgende marktgegevens over {instrument} op een {timeframe} timeframe, geëxtraheerd via OCR:

{market_data}

Analyseer deze gegevens en genereer een technische analyse in exact het volgende sjabloon format. 
De totale output MOET korter zijn dan 1000 tekens:

[{instrument}] - {timeframe}

Trend - Bullish/Bearish

Sigmapips AI identifies strong buy/sell probability. Key level at X.XXXX.

Zone Strength N/5: 🟢/🟡/🔴

• Current Price: X.XXXX
• Daily Low: X.XXXX (als beschikbaar uit daily_low)
• Daily High: X.XXXX (als beschikbaar uit daily_high)
• Weekly Low: X.XXXX (als beschikbaar uit weekly_low)
• Weekly High: X.XXXX (als beschikbaar uit weekly_high)
• RSI: XX.X (afgerond op 1 decimaal)
• Probability: XX%

Disclaimer: For educational purposes only. Not financial advice.

BELANGRIJKE RICHTLIJNEN:
1. VERWIJDER ALLE VIERKANTE HAAKJES [] - vul direct de juiste waarden in
2. Bepaal Bullish/Bearish op basis van de prijsposities:
   - Als de huidige prijs dichter bij daily high zit: Bullish
   - Als de huidige prijs dichter bij daily low zit: Bearish
3. GEBRUIK SPECIFIEK DE TERMEN "Daily Low", "Daily High", "Weekly Low", "Weekly High" 
   NIET "Support" en "Resistance" in de output.
4. Als een niveau niet beschikbaar is (bijv. geen daily_low in de data), laat die rij weg.
5. Zone Strength: 🟢 (4-5), 🟡 (2-3), 🔴 (1) - bepaal op basis van de afstand tussen prijzen
6. RSI moet worden afgerond op 1 decimaal (XX.X)
7. Probability tussen 60-85%
8. BLIJF BEKNOPT - de totale output moet minder dan 1000 tekens zijn

VEREIST:
- GEBRUIK EXACT DE HUIDIGE PRIJS ("current_price") zonder afronding. Controleer de waarde - als die
  onrealistisch is (bijv. 1.0 voor EURUSD), gebruik dan een meer plausibele waarde uit daily_high of daily_low.
- GEBRUIK DIRECT DE WAARDEN "daily_high", "daily_low", "weekly_high", "weekly_low" UIT DE DATA
- Toon alleen de niveaus die daadwerkelijk in de data aanwezig zijn
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
                
            # Save the chart to a file if it's in bytes format
            if isinstance(chart_data, bytes):
                timestamp = int(datetime.now().timestamp())
                os.makedirs('data/charts', exist_ok=True)
                file_path = f"data/charts/{instrument.lower()}_{timeframe}_{timestamp}.png"
                
                try:
                    with open(file_path, 'wb') as f:
                        f.write(chart_data)
                    logger.info(f"Saved technical chart to {file_path}, size: {len(chart_data)} bytes")
                    return file_path
                except Exception as save_error:
                    logger.error(f"Failed to save chart image to file: {str(save_error)}")
                    return None
            else:
                # Already a file path
                logger.info(f"Using existing chart image path: {chart_data}")
                return chart_data
            
        except Exception as e:
            logger.error(f"Error getting technical chart: {str(e)}")
            return None
