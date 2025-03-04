import os
import logging
import aiohttp
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

class ChartService:
    def __init__(self):
        """Initialize chart service"""
        # TradingView chart links mapping
        self.chart_links = {
            # Forex
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
            "NZDUSD": "https://www.tradingview.com/chart/yab05IFU/",
            "NZDCHF": "https://www.tradingview.com/chart/7epTugqA/",
            "NZDJPY": "https://www.tradingview.com/chart/fdtQ7rx7/",
            "NZDCAD": "https://www.tradingview.com/chart/mRVtXs19/",
            
            # Commodities
            "XAUUSD": "https://www.tradingview.com/chart/bylCuCgc/",
            "XTIUSD": "https://www.tradingview.com/chart/jxU29rbq/",
            
            # Crypto
            "BTCUSD": "https://www.tradingview.com/chart/Nroi4EqI/",
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
            "DE40": "https://www.tradingview.com/chart/OWzg0XNw/"
        }
        
        # Statische chart URLs als fallback
        self.static_chart_urls = [
            "https://www.tradingview.com/x/heV5Zitn/",
            "https://www.tradingview.com/x/xknpxpcr/",
            "https://www.tradingview.com/x/VsfYHrwP/",
            "https://www.tradingview.com/x/Nroi4EqI/"
        ]
        
        self.tradingview = None
        
    async def initialize(self):
        """Initialize chart service"""
        try:
            # Importeer TradingViewService vanuit dezelfde map
            from trading_bot.services.chart_service.tradingview import TradingViewService
            self.tradingview = TradingViewService()
            await self.tradingview.initialize()
            
            logger.info("Chart service initialized")
            return True
        except Exception as e:
            logger.error(f"Error initializing chart service: {str(e)}")
            return False
        
    async def get_chart(self, instrument: str, timeframe: str = "1h") -> Optional[bytes]:
        """Get chart image for the given instrument"""
        try:
            # Normaliseer instrument (verwijder /)
            instrument = instrument.upper().replace("/", "")
            
            # Probeer eerst TradingView (als het werkt)
            if self.tradingview and self.tradingview.is_logged_in and instrument in self.chart_links:
                chart_url = self.chart_links[instrument]
                screenshot = await self.tradingview.get_chart_screenshot(chart_url)
                if screenshot:
                    return screenshot
            
            # Als TradingView niet werkt, probeer alternatieve chart services
            
            # 1. Probeer TradingView publieke snapshots
            if instrument in self.chart_links:
                chart_url = self.chart_links[instrument]
                chart_id = chart_url.split("/")[-2]
                
                # Probeer de directe snapshot URL
                snapshot_url = f"https://s3.tradingview.com/snapshots/{chart_id}.png"
                logger.info(f"Getting snapshot from TradingView: {snapshot_url}")
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(snapshot_url) as response:
                        if response.status == 200:
                            return await response.read()
            
                # Probeer de publieke snapshot URL
                public_url = f"https://www.tradingview.com/x/{chart_id}/"
                logger.info(f"Getting public snapshot from TradingView: {public_url}")
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(public_url) as response:
                        if response.status == 200:
                            return await response.read()
            
            # 2. Probeer Finviz voor aandelen
            if instrument in ["SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA"]:
                finviz_url = f"https://finviz.com/chart.ashx?t={instrument}&ty=c&ta=1&p=d&s=l"
                logger.info(f"Getting chart from Finviz: {finviz_url}")
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(finviz_url) as response:
                        if response.status == 200:
                            return await response.read()
            
            # 3. Probeer Investing.com
            # Map instrument naar Investing.com formaat
            investing_map = {
                "EURUSD": "eur-usd", "GBPUSD": "gbp-usd", "USDJPY": "usd-jpy",
                "BTCUSD": "btc-usd", "ETHUSD": "eth-usd", "XAUUSD": "xau-usd"
            }
            
            if instrument in investing_map:
                investing_symbol = investing_map[instrument]
                investing_url = f"https://www.investing.com/currencies/{investing_symbol}-chart"
                logger.info(f"Getting chart from Investing.com: {investing_url}")
                
                async with aiohttp.ClientSession() as session:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                    }
                    async with session.get(investing_url, headers=headers) as response:
                        if response.status == 200:
                            # Gebruik een screenshot service om de chart te renderen
                            return await self.make_screenshot(investing_url)
            
            # 4. Probeer een screenshot service voor TradingView
            if instrument in self.chart_links:
                chart_url = self.chart_links[instrument]
                return await self.make_screenshot(chart_url)
            
            # 5. Als alles mislukt, genereer een eigen chart
            return await self.generate_chart(instrument, timeframe)
            
        except Exception as e:
            logger.error(f"Error getting chart: {str(e)}")
            return await self.get_fallback_chart()
    
    async def make_screenshot(self, url: str) -> Optional[bytes]:
        """Make a screenshot of a URL using a screenshot service"""
        try:
            logger.info(f"Making screenshot of URL: {url}")
            
            # Lijst van screenshot services
            services = [
                f"https://image.thum.io/get/width/1280/crop/800/png/{quote(url)}",
                f"https://www.screenshotmachine.com/capture.php?url={quote(url)}&size=1280x800",
                f"https://api.apiflash.com/v1/urltoimage?access_key=your_api_key&url={quote(url)}&width=1280&height=800",
                f"https://api.screenshotlayer.com/api/capture?access_key=your_api_key&url={quote(url)}&width=1280&height=800"
            ]
            
            # Probeer elke service
            for service_url in services:
                logger.info(f"Trying screenshot service: {service_url}")
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(service_url) as response:
                        if response.status == 200:
                            return await response.read()
                        else:
                            logger.error(f"Screenshot service error: {response.status}")
            
            # Als alle services mislukken, return None
            logger.error("All screenshot services failed")
            return None
        except Exception as e:
            logger.error(f"Error making screenshot: {str(e)}")
            return None
    
    async def get_fallback_chart(self) -> Optional[bytes]:
        """Get a fallback chart image"""
        try:
            # Probeer alle statische chart URLs
            for url in self.static_chart_urls:
                logger.info(f"Trying static chart URL: {url}")
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            return await response.read()
                        else:
                            logger.error(f"Static chart error: {response.status}")
            
            # Als alle URLs mislukken, probeer een andere aanpak
            fallback_url = "https://finviz.com/chart.ashx?t=AAPL&ty=c&ta=1&p=d&s=l"
            logger.info(f"Trying fallback URL: {fallback_url}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(fallback_url) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.error(f"Fallback chart error: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error getting fallback chart: {str(e)}")
            return None
            
    async def cleanup(self):
        """Clean up resources"""
        try:
            if self.tradingview:
                await self.tradingview.cleanup()
        except Exception as e:
            logger.error(f"Error cleaning up chart service: {str(e)}")

    async def generate_chart(self, instrument: str, timeframe: str = "1h") -> Optional[bytes]:
        """Generate a chart using matplotlib"""
        try:
            import matplotlib.pyplot as plt
            import pandas as pd
            import numpy as np
            import io
            from datetime import datetime, timedelta
            
            logger.info(f"Generating chart for {instrument} with timeframe {timeframe}")
            
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
            # In een echte implementatie zou je hier data ophalen van een API
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
        except Exception as e:
            logger.error(f"Error generating chart: {str(e)}")
            return None
