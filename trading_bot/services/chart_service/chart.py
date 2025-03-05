import os
import logging
import aiohttp
from typing import Optional
from urllib.parse import quote
import asyncio
import base64
from io import BytesIO
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import mplfinance as mpf
from datetime import datetime, timedelta

# Voeg deze import toe
from trading_bot.services.chart_service.tradingview_selenium import TradingViewSeleniumService
from trading_bot.services.chart_service.tradingview_playwright import TradingViewPlaywrightService

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
        self.tradingview_selenium = None
        self.tradingview_playwright = None

    async def initialize(self):
        """Initialize the chart service"""
        try:
            logger.info("Initializing chart service")
            
            # Definieer de chart links
            self.chart_links = {
                # Commodities
                "XAUUSD": "https://www.tradingview.com/chart/bylCuCgc/",
                "WTIUSD": "https://www.tradingview.com/chart/jxU29rbq/",
                
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
                "NZDUSD": "https://www.tradingview.com/chart/yab05IFU/",
                "NZDCHF": "https://www.tradingview.com/chart/7epTugqA/",
                "NZDJPY": "https://www.tradingview.com/chart/fdtQ7rx7/",
                "NZDCAD": "https://www.tradingview.com/chart/mRVtXs19/",
                
                # Cryptocurrencies
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
            
            # Probeer eerst de TradingView Session service
            try:
                from trading_bot.services.chart_service.tradingview_session import TradingViewSessionService
                logger.info("Initializing TradingView Session service")
                self.tradingview_session = TradingViewSessionService(chart_links=self.chart_links)
                session_success = await self.tradingview_session.initialize()
                
                if session_success:
                    logger.info("TradingView Session service initialized successfully")
                    self.tradingview = self.tradingview_session
                    return True
                else:
                    logger.warning("TradingView Session service initialization failed")
            except Exception as e:
                logger.error(f"Error initializing TradingView Session service: {str(e)}")
            
            # Probeer Node.js als Session service faalt
            try:
                from trading_bot.services.chart_service.tradingview_node import TradingViewNodeService
                self.tradingview_node = TradingViewNodeService()
                node_success = await self.tradingview_node.initialize()
                
                if node_success:
                    logger.info("Chart service initialized with Node.js successfully")
                    self.tradingview = self.tradingview_node
                    return True
                else:
                    logger.warning("Failed to initialize Node.js, trying Puppeteer")
            except Exception as node_error:
                logger.error(f"Error initializing Node.js: {str(node_error)}")
                logger.warning("Failed to initialize Node.js, trying Puppeteer")
            
            # Probeer Puppeteer als Node.js faalt
            try:
                from trading_bot.services.chart_service.tradingview_puppeteer import TradingViewPuppeteerService
                self.tradingview_puppeteer = TradingViewPuppeteerService()
                puppeteer_success = await self.tradingview_puppeteer.initialize()
                
                if puppeteer_success:
                    logger.info("Chart service initialized with Puppeteer successfully")
                    self.tradingview = self.tradingview_puppeteer
                    return True
                else:
                    logger.warning("Failed to initialize Puppeteer, trying Playwright")
            except Exception as puppeteer_error:
                logger.error(f"Error initializing Puppeteer: {str(puppeteer_error)}")
                logger.warning("Failed to initialize Puppeteer, trying Playwright")
            
            # Probeer Playwright als Puppeteer faalt
            try:
                from trading_bot.services.chart_service.tradingview_playwright import TradingViewPlaywrightService
                self.tradingview_playwright = TradingViewPlaywrightService()
                playwright_success = await self.tradingview_playwright.initialize()
                
                if playwright_success:
                    logger.info("Chart service initialized with Playwright successfully")
                    self.tradingview = self.tradingview_playwright
                    return True
                else:
                    logger.warning("Failed to initialize Playwright, trying Selenium")
            except Exception as playwright_error:
                logger.error(f"Error initializing Playwright: {str(playwright_error)}")
                logger.warning("Failed to initialize Playwright, trying Selenium")
            
            # Probeer Selenium als Playwright faalt
            try:
                from trading_bot.services.chart_service.tradingview_selenium import TradingViewSeleniumService
                self.tradingview_selenium = TradingViewSeleniumService()
                selenium_success = await self.tradingview_selenium.initialize()
                
                if selenium_success:
                    logger.info("Chart service initialized with Selenium successfully")
                    self.tradingview = self.tradingview_selenium
                    return True
                else:
                    logger.warning("Failed to initialize Selenium, using fallback methods")
            except Exception as selenium_error:
                logger.error(f"Error initializing Selenium: {str(selenium_error)}")
                logger.warning("Failed to initialize Selenium, using fallback methods")
            
            # Als alle methoden falen, gebruik fallback
            logger.info("Using fallback methods for chart service")
            self.tradingview = None
            return False
        except Exception as e:
            logger.error(f"Error initializing chart service: {str(e)}")
            self.tradingview = None
            return False
        
    async def get_chart(self, instrument: str, timeframe: str = None) -> Optional[bytes]:
        """Get a chart for the given instrument and timeframe"""
        try:
            logger.info(f"Getting chart for {instrument} with timeframe {timeframe}")
            
            # Controleer of we een TradingView service hebben
            if self.tradingview:
                logger.info(f"Using TradingView service: {type(self.tradingview).__name__}")
                
                # Gebruik de TradingView service om een screenshot te maken
                screenshot = await self.tradingview.take_screenshot(instrument, timeframe)
                
                if screenshot:
                    logger.info(f"Got screenshot for {instrument}")
                    return screenshot
                else:
                    logger.warning(f"Failed to get screenshot for {instrument} using TradingView service")
            else:
                logger.warning("No TradingView service available")
            
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
                
                # Gebruik een screenshot service om de publieke chart te renderen
                screenshot = await self.make_screenshot(public_url)
                if screenshot:
                    return screenshot
            
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
                
                # Gebruik een screenshot service om de chart te renderen
                screenshot = await self.make_screenshot(investing_url)
                if screenshot:
                    return screenshot
            
            # 4. Als alles mislukt, genereer een chart met matplotlib
            logger.info(f"All external chart services failed, generating chart with matplotlib")
            return await self.generate_chart(instrument, timeframe)
            
        except Exception as e:
            logger.error(f"Error getting chart: {str(e)}")
            return None
    
    async def make_screenshot(self, url: str) -> Optional[bytes]:
        """Make a screenshot of a URL using a screenshot service"""
        try:
            logger.info(f"Making screenshot of URL: {url}")
            
            # Lijst van screenshot services
            services = [
                f"https://image.thum.io/get/width/1280/crop/800/png/{quote(url)}",
                f"https://api.screenshotmachine.com/capture.php?key=your_api_key&url={quote(url)}&dimension=1280x800",
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
