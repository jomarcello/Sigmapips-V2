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
CHART_CACHE_EXPIRY = 1800  # 30 minuten voor charts (was 5 minuten)
ANALYSIS_CACHE_EXPIRY = 3600  # 60 minuten voor analyses (was 10 minuten)

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
            self.chart_cache_expiry = {}
            self.analysis_cache = {}
            self.analysis_cache_expiry = {}
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
                
                # Get MACD values
                macd = market_data_dict.get('macd', 0)
                macd_signal = market_data_dict.get('macd_signal', 0)
                formatted_macd = f"{macd:.{decimals}f}"
                formatted_macd_signal = f"{macd_signal:.{decimals}f}"
                
                # Get EMA values
                ema50 = market_data_dict.get('ema_50', current_price * 1.005 if is_bullish else current_price * 0.995)
                formatted_ema50 = f"{ema50:.{decimals}f}"
                
                ema200 = market_data_dict.get('ema_200', current_price * 1.01 if is_bullish else current_price * 0.99)
                formatted_ema200 = f"{ema200:.{decimals}f}"
                
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
