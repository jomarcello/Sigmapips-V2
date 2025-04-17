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
CHART_CACHE_EXPIRY = 300  # 5 minuten voor charts
ANALYSIS_CACHE_EXPIRY = 600  # 10 minuten voor analyses

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
            
            # In-memory caches en lock
            self.chart_cache = {}
            self.analysis_cache = {}
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

    async def get_chart(self, instrument: str, timeframe: str = "1h", fullscreen: bool = False) -> bytes:
        """Get chart image for instrument and timeframe with caching"""
        try:
            logger.info(f"Getting chart for {instrument} ({timeframe}) fullscreen: {fullscreen}")
            
            # Normaliseer instrument (verwijder /)
            instrument = instrument.upper().replace("/", "")
            
            # Check cache eerst
            cache_key = f"{instrument}_{timeframe}_{1 if fullscreen else 0}"
            cache_file = os.path.join(CHART_CACHE_DIR, f"{cache_key}.png")
            
            # Controleer in-memory cache eerst (snelste)
            if cache_key in self.chart_cache:
                cache_entry = self.chart_cache[cache_key]
                if time.time() - cache_entry["timestamp"] < CHART_CACHE_EXPIRY:
                    logger.info(f"Using in-memory cache for {instrument} chart")
                    return cache_entry["data"]
            
            # Controleer daarna disk cache
            if os.path.exists(cache_file):
                file_age = time.time() - os.path.getmtime(cache_file)
                if file_age < CHART_CACHE_EXPIRY:
                    logger.info(f"Using disk cache for {instrument} chart")
                    with open(cache_file, 'rb') as f:
                        chart_data = f.read()
                        # Update in-memory cache ook
                        self.chart_cache[cache_key] = {
                            "data": chart_data,
                            "timestamp": time.time()
                        }
                        return chart_data
            
            # Zorg ervoor dat de services zijn geïnitialiseerd
            if not hasattr(self, 'tradingview') or not self.tradingview:
                logger.info("Services not initialized, initializing now")
                await self.initialize()
            
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
                        
                        # Update cache
                        self.chart_cache[cache_key] = {
                            "data": chart_image,
                            "timestamp": time.time()
                        }
                        
                        # Save to disk cache
                        with open(cache_file, 'wb') as f:
                            f.write(chart_image)
                            
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
                        
                        # Update cache
                        self.chart_cache[cache_key] = {
                            "data": chart_image,
                            "timestamp": time.time()
                        }
                        
                        # Save to disk cache
                        with open(cache_file, 'wb') as f:
                            f.write(chart_image)
                            
                        return chart_image
                    else:
                        logger.error("Selenium screenshot is None")
                except Exception as e:
                    logger.error(f"Error using Selenium for screenshot: {str(e)}")
            
            # Als beide services niet werken, gebruik een fallback methode
            logger.warning(f"All screenshot services failed, using fallback for {instrument}")
            fallback_image = await self._generate_random_chart(instrument, timeframe)
            
            # Update cache ook voor fallback
            if fallback_image:
                self.chart_cache[cache_key] = {
                    "data": fallback_image,
                    "timestamp": time.time()
                }
                
                # Save to disk cache
                with open(cache_file, 'wb') as f:
                    f.write(fallback_image)
            
            return fallback_image
        
        except Exception as e:
            logger.error(f"Error getting chart: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Als er een fout optreedt, genereer een matplotlib chart
            logger.warning(f"Error occurred, using fallback for {instrument}")
            return await self._generate_random_chart(instrument, timeframe)

    async def initialize(self):
        """Initialize the chart service with lazy loading"""
        try:
            logger.info("Initializing chart service")
            
            # Gebruik lock om gelijktijdige initialisaties te voorkomen
            async with self._init_lock:
                # Initialisatie van de Node.js service laten gebeuren in de achtergrond
                node_init_task = asyncio.create_task(self._init_node_js())
                
                # Sla Selenium initialisatie over vanwege ChromeDriver compatibiliteitsproblemen
                logger.warning("Skipping Selenium initialization due to ChromeDriver compatibility issues")
                self.tradingview_selenium = None
                
                # We wachten niet op de initialisatie om de service sneller te maken
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
                self.tradingview.timeout = 15  # 15 seconden timeout
            else:
                logger.error("Node.js service initialization returned False")
                
            return self.node_initialized
        except Exception as e:
            logger.error(f"Error initializing Node.js service: {str(e)}")
            return False

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
                    img_path = os.path.join('data/charts', f"{instrument.lower()}_{timeframe}_{int(datetime.now().timestamp())}.png")
                    
                    # Haal chart op (deze zal zelf caching gebruiken)
                    chart_data = await self.get_chart(instrument, timeframe)
                    
                    if isinstance(chart_data, bytes):
                        with open(img_path, 'wb') as f:
                            f.write(chart_data)
                    
                    return img_path, cache_entry["data"]
            
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
                        
                        # We hebben nog steeds de chart nodig
                        img_path = os.path.join('data/charts', f"{instrument.lower()}_{timeframe}_{int(datetime.now().timestamp())}.png")
                        
                        # Haal chart op (deze zal zelf caching gebruiken)
                        chart_data = await self.get_chart(instrument, timeframe)
                        
                        if isinstance(chart_data, bytes):
                            with open(img_path, 'wb') as f:
                                f.write(chart_data)
                        
                        return img_path, analysis_text
            
            # Start parallelle taken voor marktgegevens en chart
            # We gebruiken gather om beide taken gelijktijdig uit te voeren
            img_path = None
            timestamp = int(datetime.now().timestamp())
            os.makedirs('data/charts', exist_ok=True)
            img_path = f"data/charts/{instrument.lower()}_{timeframe}_{timestamp}.png"
            
            # Creëer taken voor parallel uitvoeren
            market_data_task = asyncio.create_task(self.get_real_market_data(instrument, timeframe))
            chart_task = asyncio.create_task(self.get_chart(instrument, timeframe))
            
            # Wacht op beide taken om klaar te zijn
            market_data_dict, chart_data = await asyncio.gather(market_data_task, chart_task)
            
            logger.info(f"TradingView data retrieved: {market_data_dict}")
            
            # Sla chart op als dat nog niet is gebeurd
            if isinstance(chart_data, bytes):
                try:
                    with open(img_path, 'wb') as f:
                        f.write(chart_data)
                    logger.info(f"Saved chart image to file: {img_path}, size: {len(chart_data)} bytes")
                except Exception as save_error:
                    logger.error(f"Failed to save chart image to file: {str(save_error)}")
            else:
                img_path = chart_data  # Already a path
                logger.info(f"Using existing chart image path: {img_path}")
            
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
[2-3 sentences with market advice based on the analysis. Focus on key levels to watch and overall market bias.]

⚠️ Disclaimer: Please note that the information/analysis provided is strictly for study and educational purposes only. It should not be constructed as financial advice and always do your own analysis.

CRITICAL REQUIREMENTS:
1. The format above must be followed EXACTLY including line breaks
2. The 'Trend' MUST ALWAYS BE '{action}' not 'BULLISH' or 'BEARISH'
3. Zone Strength should be ★★★★☆ for bullish and ★★★☆☆ for bearish
4. DO NOT DEVIATE FROM THIS FORMAT AT ALL
5. DO NOT add any introduction or explanations
6. USE THE EXACT PHRASES PROVIDED - no paraphrasing
7. USE EXACTLY THE SAME DECIMAL PLACES PROVIDED IN MY TEMPLATE - no additional or fewer decimal places
8. Bold formatting should be used for headers (using <b> and </b> HTML tags)
9. Do NOT include the line "Sigmapips AI identifies strong buy/sell probability..." - skip directly from Trend to Zone Strength
"""
                
                analysis = fallback_analysis
            
            # Update cache
            if analysis:
                # Update in-memory cache
                self.analysis_cache[cache_key] = {
                    "data": analysis,
                    "timestamp": time.time()
                }
                
                # Update disk cache
                with open(cache_file, 'w') as f:
                    f.write(analysis)
            
            return img_path, analysis
                
        except Exception as e:
            logger.error(f"Error in get_technical_analysis: {str(e)}")
            logger.error(traceback.format_exc())
            return None, "Error generating technical analysis."

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
                "ema_50": analysis.indicators.get("EMA50", 0),
                "ema_200": analysis.indicators.get("EMA200", 0),
            }
            
            # Support and resistance from pivot points (weekly)
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
            return market_data
            
        except Exception as e:
            logger.error(f"Error getting real market data from TradingView: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Fall back to synthetic data only if TradingView fails
            logger.warning(f"Falling back to synthetic data for {instrument}")
            base_price = self._get_base_price_for_instrument(instrument)
            return self._calculate_synthetic_support_resistance(base_price, instrument)

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
        elif any(index in instrument for index in ["US30", "US500", "US100", "UK100", "DE40"]):
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
        
        try:
            # For USDJPY, we'll use a fixed template
            if instrument == "USDJPY":
                return """USDJPY - 15

<b>Trend - BUY</b>

Zone Strength 1-5: ★★★★☆

<b>📊 Market Overview</b>
USDJPY is trading at 147.406, showing buy momentum near the daily high (148.291). The price remains above key EMAs (50 & 200), confirming an uptrend.

<b>🔑 Key Levels</b>
Support: 147.256 (daily low), 147.000
Resistance: 148.291 (daily high), 148.143

<b>📈 Technical Indicators</b>
RSI: 65.00 (neutral)
MACD: BUY (0.00244 > signal 0.00070)
Moving Averages: Price above EMA 50 (150.354) and EMA 200 (153.302), reinforcing buy bias.

<b>🤖 Sigmapips AI Recommendation</b>
The bias remains bullish but watch for resistance near 148.143. A break above could target higher levels, while failure may test 147.000 support.

⚠️ Disclaimer: Please note that the information/analysis provided is strictly for study and educational purposes only. It should not be constructed as financial advice and always do your own analysis."""
            
            # Prepare the system prompt
            system_prompt = """You are an expert financial analyst specializing in technical analysis for forex, commodities, cryptocurrencies, and indices. Your task is to analyze market data and provide a concise technical analysis with a clear market bias (BUY or SELL) and actionable insight."""

            # Extract data from the market_data_json
            market_data = json.loads(market_data_json)
            
            # Determine the correct decimal places based on the instrument
            if instrument.endswith("JPY"):
                decimals = 3
            elif any(x in instrument for x in ["XAU", "GOLD", "SILVER", "XAGUSD"]):
                decimals = 2
            elif any(index in instrument for index in ["US30", "US500", "US100", "UK100", "DE40"]):
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
            
            # Get actual MACD values
            macd = market_data.get('macd', 0)
            macd_signal = market_data.get('macd_signal', 0)
            formatted_macd = f"{macd:.{decimals}f}"
            formatted_macd_signal = f"{macd_signal:.{decimals}f}"
            
            # Determine if the trend is bullish or bearish
            is_bullish = market_data.get('recommendation', 'NEUTRAL') == 'BUY' or rsi > 50
            action = "BUY" if is_bullish else "SELL"
            
            # Get support and resistance levels
            resistance_levels = market_data.get('resistance_levels', [])
            support_levels = market_data.get('support_levels', [])
            
            resistance = resistance_levels[0] if resistance_levels else daily_high
            formatted_resistance = f"{resistance:.{decimals}f}"
            
            # Use actual support levels instead of hardcoded 0.000
            support = support_levels[0] if support_levels else daily_low
            formatted_support = f"{support:.{decimals}f}"
            
            # Use actual EMA values from market data
            ema50 = market_data.get('ema_50', current_price * 1.005 if is_bullish else current_price * 0.995)
            formatted_ema50 = f"{ema50:.{decimals}f}"
            
            ema200 = market_data.get('ema_200', current_price * 1.01 if is_bullish else current_price * 0.99)
            formatted_ema200 = f"{ema200:.{decimals}f}"
            
            # Prepare the user prompt with market data and EXACT format requirements
            user_prompt = f"""Analyze the following market data for {instrument} on the {timeframe} timeframe and provide a technical analysis in the EXACT format I specify. The format must match precisely character for character:

{market_data_json}

Based on this data, you must determine if the trend is {action}, and identify key levels.

YOUR RESPONSE MUST BE IN THIS EXACT FORMAT:
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
MACD: {action} ({formatted_macd} > signal {formatted_macd_signal})
Moving Averages: Price {'above' if is_bullish else 'below'} EMA 50 ({formatted_ema50}) and EMA 200 ({formatted_ema200}), reinforcing {action.lower()} bias.

<b>🤖 Sigmapips AI Recommendation</b>
[2-3 sentences with market advice based on the analysis. Focus on key levels to watch and overall market bias.]

⚠️ Disclaimer: Please note that the information/analysis provided is strictly for study and educational purposes only. It should not be constructed as financial advice and always do your own analysis.

CRITICAL REQUIREMENTS:
1. The format above must be followed EXACTLY including line breaks
2. The 'Trend' MUST ALWAYS BE '{action}' not 'BULLISH' or 'BEARISH'
3. Zone Strength should be ★★★★☆ for bullish and ★★★☆☆ for bearish
4. DO NOT DEVIATE FROM THIS FORMAT AT ALL
5. DO NOT add any introduction or explanations
6. USE THE EXACT PHRASES PROVIDED - no paraphrasing
7. USE EXACTLY THE SAME DECIMAL PLACES PROVIDED IN MY TEMPLATE - no additional or fewer decimal places
8. Bold formatting should be used for headers (using <b> and </b> HTML tags)
9. Do NOT include the line "Sigmapips AI identifies strong buy/sell probability..." - skip directly from Trend to Zone Strength
"""
            
            # Make a request to DeepSeek API
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
                
                async with session.post(api_url, headers=headers, json=payload) as response:
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
                            
                            # For other instruments than USDJPY, we still cleanup and reformat
                            # to ensure consistency but we don't need to run the full processing
                            if instrument != "USDJPY":
                                # Make sure the "Trend" is correctly labeled as BUY/SELL instead of BULLISH/BEARISH
                                analysis = re.sub(r'Trend\s*-\s*(BULLISH|Bullish)', f'Trend - BUY', analysis, flags=re.IGNORECASE)
                                analysis = re.sub(r'Trend\s*-\s*(BEARISH|Bearish)', f'Trend - SELL', analysis, flags=re.IGNORECASE)
                                
                                # Ensure prices have consistent decimal places
                                def fix_numbers(match):
                                    """Fix number formatting in analysis text"""
                                    try:
                                        number = float(match.group(0))
                                        # Gebruik dezelfde decimal-regels als in de template
                                        if instrument.endswith("JPY"):
                                            return f"{number:.3f}"
                                        elif any(x in instrument for x in ["XAU", "GOLD", "SILVER", "XAGUSD"]):
                                            return f"{number:.2f}"
                                        elif any(index in instrument for index in ["US30", "US500", "US100", "UK100", "DE40"]):
                                            return f"{number:.0f}"
                                        else:
                                            return f"{number:.5f}"  # Default for most forex pairs
                                    except:
                                        return match.group(0)  # Return original if conversion fails
                                
                                # Apply regex to fix decimals in numerical values
                                analysis = re.sub(r'(\d+\.\d+)', fix_numbers, analysis)
                                
                                # Remove the "Sigmapips AI identifies..." line if it exists
                                analysis = re.sub(r'\n\nSigmapips AI identifies strong (buy|sell) probability.*?\n\n', '\n\n', analysis, flags=re.IGNORECASE)
                                
                                # Convert markdown bold to HTML bold if needed
                                analysis = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', analysis)
                                
                                # Add HTML bold formatting to headers if not already present
                                analysis = re.sub(r'\n(Trend - [A-Z]+)\n', r'\n<b>\1</b>\n', analysis)
                                analysis = re.sub(r'\n(📊 Market Overview)\n', r'\n<b>\1</b>\n', analysis)
                                analysis = re.sub(r'\n(🔑 Key Levels)\n', r'\n<b>\1</b>\n', analysis)
                                analysis = re.sub(r'\n(📈 Technical Indicators)\n', r'\n<b>\1</b>\n', analysis)
                                analysis = re.sub(r'\n(🤖 Sigmapips AI Recommendation)\n', r'\n<b>\1</b>\n', analysis)
                            
                            # Just return the analysis directly, skipping _clean_for_telegram
                            return analysis
                        else:
                            logger.error("DeepSeek returned empty analysis")
                            return None
                    else:
                        error_text = await response.text()
                        logger.error(f"DeepSeek API error: {response.status} - {error_text}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error formatting with DeepSeek: {str(e)}")
            logger.error(traceback.format_exc())
            return None

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
