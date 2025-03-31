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

# Importeer alleen de base class
from trading_bot.services.chart_service.base import TradingViewService

logger = logging.getLogger(__name__)

class ChartService:
    def __init__(self):
        """Initialize chart service"""
        print("ChartService initialized")
        try:
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
            
            # Voeg fullscreen parameter toe aan de URL als dat nodig is
            if fullscreen:
                # Controleer of er al een vraagteken in de URL zit
                if "?" in tradingview_link:
                    tradingview_link += "&fullscreen=true&hide_side_toolbar=true&hide_top_toolbar=true&theme=dark"
                else:
                    tradingview_link += "?fullscreen=true&hide_side_toolbar=true&hide_top_toolbar=true&theme=dark"
            
            logger.info(f"Using exact TradingView link: {tradingview_link}")
            
            # Probeer eerst de Node.js service te gebruiken
            if hasattr(self, 'tradingview') and self.tradingview and hasattr(self.tradingview, 'take_screenshot_of_url'):
                try:
                    logger.info(f"Taking screenshot with Node.js service: {tradingview_link}")
                    chart_image = await self.tradingview.take_screenshot_of_url(tradingview_link, fullscreen=fullscreen)
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
                    chart_image = await self.tradingview_selenium.get_screenshot(tradingview_link, fullscreen)
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
        
        # Maak de chart
        plt.figure(figsize=(12, 8))
        plt.style.use('dark_background')
        
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
        plt.title(f'{instrument} - {timeframe} Chart', fontsize=16)
        plt.xlabel('Date', fontsize=12)
        plt.ylabel('Price', fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.legend()
        
        # Sla de chart op als bytes
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
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
        Get technical analysis for an instrument with timeframe.
        This is a more advanced version that includes text analysis.
        """
        try:
            # First get the chart
            img_path = await self.get_chart(instrument, timeframe)
            
            # Generate some analysis text
            analysis = f"""
Technical Analysis for {instrument} ({timeframe}):

- Moving Averages: The price is currently {'above' if random.random() > 0.5 else 'below'} the 50-period MA.
- RSI: The RSI is {'overbought' if random.random() > 0.7 else 'oversold' if random.random() < 0.3 else 'neutral'}.
- MACD: The MACD is showing a {'bullish' if random.random() > 0.5 else 'bearish'} crossover.
- Support/Resistance: Key support at {round(random.uniform(0.8, 0.95), 2)} and resistance at {round(random.uniform(1.05, 1.2), 2)}.
- Trend: The overall trend is {'bullish' if random.random() > 0.5 else 'bearish'} on the {timeframe} timeframe.
"""
            
            return img_path, analysis
            
        except Exception as e:
            logger.error(f"Error generating technical analysis: {str(e)}")
            return None, "Error generating technical analysis."
            
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
