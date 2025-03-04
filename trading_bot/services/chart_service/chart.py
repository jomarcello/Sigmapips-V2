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
            
            # Controleer of we een link hebben voor dit instrument
            if instrument in self.chart_links:
                chart_url = self.chart_links[instrument]
                
                # Probeer eerst de directe TradingView snapshot API
                chart_id = chart_url.split("/")[-2]
                snapshot_url = f"https://s3.tradingview.com/snapshots/{chart_id}.png"
                
                logger.info(f"Getting snapshot from TradingView: {snapshot_url}")
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(snapshot_url) as response:
                        if response.status == 200:
                            return await response.read()
                        else:
                            logger.error(f"TradingView snapshot error: {response.status}")
                
                # Probeer een screenshot service
                return await self.make_screenshot(chart_url)
            else:
                logger.error(f"No chart link found for instrument: {instrument}")
                return await self.get_fallback_chart()
                
        except Exception as e:
            logger.error(f"Error getting chart: {str(e)}")
            return await self.get_fallback_chart()
    
    async def make_screenshot(self, url: str) -> Optional[bytes]:
        """Make a screenshot of the given URL using a screenshot service"""
        try:
            # Gebruik een screenshot service
            screenshot_url = f"https://mini.s-shot.ru/1280x800/JPEG/1280/Z100/?{quote(url)}"
            
            logger.info(f"Getting screenshot from: {screenshot_url}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(screenshot_url) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.error(f"Screenshot service error: {response.status}")
                        return await self.try_alternative_service(url)
        except Exception as e:
            logger.error(f"Error making screenshot: {str(e)}")
            return await self.try_alternative_service(url)
    
    async def try_alternative_service(self, url: str) -> Optional[bytes]:
        """Try alternative screenshot services"""
        services = [
            f"https://image.thum.io/get/width/1280/crop/800/png/{quote(url)}",
            f"https://api.urlbox.io/v1/render?url={quote(url)}&width=1280&height=800&format=png&ttl=86400&token=demo",
            f"https://render-tron.appspot.com/screenshot/{quote(url)}",
            f"https://www.screenshotmachine.com/capture.php?url={quote(url)}&size=1280x800"
        ]
        
        for service_url in services:
            try:
                logger.info(f"Trying screenshot service: {service_url}")
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(service_url) as response:
                        if response.status == 200:
                            return await response.read()
                        else:
                            logger.error(f"Screenshot service error: {response.status}")
            except Exception as e:
                logger.error(f"Error with screenshot service: {str(e)}")
        
        # Als alle services mislukken, probeer een directe link naar de TradingView chart afbeelding
        try:
            chart_id = url.split("/")[-2]
            direct_url = f"https://www.tradingview.com/x/{chart_id}/"
            
            logger.info(f"Trying direct TradingView chart image: {direct_url}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(direct_url) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.error(f"Direct TradingView chart image error: {response.status}")
        except Exception as e:
            logger.error(f"Error with direct TradingView chart image: {str(e)}")
        
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
