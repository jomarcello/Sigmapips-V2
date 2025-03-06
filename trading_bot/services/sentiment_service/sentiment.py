import logging
import aiohttp
import os
import json
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MarketSentimentService:
    """Service for retrieving market sentiment data"""
    
    def __init__(self):
        """Initialize the market sentiment service"""
        self.api_key = os.getenv("SENTIMENT_API_KEY")
        self.base_url = os.getenv("SENTIMENT_API_URL", "https://api.example.com/sentiment")
        
        # If no API key is provided, we'll use mock data
        self.use_mock = not self.api_key
        if self.use_mock:
            logger.warning("No sentiment API key found, using mock data")
    
    async def get_market_sentiment(self, instrument_or_signal) -> str:
        """Get market sentiment analysis"""
        try:
            # Handle both string and dictionary input
            if isinstance(instrument_or_signal, str):
                # Convert instrument string to signal dictionary
                signal = {
                    'instrument': instrument_or_signal,
                    'market': self._guess_market_from_instrument(instrument_or_signal)
                }
            else:
                signal = instrument_or_signal
            
            instrument = signal.get('instrument', '')
            market = signal.get('market', 'forex')
            logger.info(f"Getting market sentiment for {instrument} ({market})")
            
            if self.use_mock:
                return self._get_mock_sentiment(instrument)
            
            # Make API request to get sentiment data
            async with aiohttp.ClientSession() as session:
                params = {
                    "api_key": self.api_key,
                    "instrument": instrument
                }
                
                async with session.get(self.base_url, params=params) as response:
                    if response.status != 200:
                        logger.error(f"Error getting sentiment data: {response.status}")
                        return self._get_mock_sentiment(instrument)
                    
                    data = await response.json()
                    return self._format_sentiment_data(instrument, data)
        
        except Exception as e:
            logger.error(f"Error getting sentiment: {str(e)}")
            if isinstance(instrument_or_signal, str):
                return self._get_fallback_sentiment({'instrument': instrument_or_signal})
            return self._get_fallback_sentiment(instrument_or_signal)
    
    def _guess_market_from_instrument(self, instrument: str) -> str:
        """Guess market type from instrument symbol"""
        if instrument.startswith(('XAU', 'XAG', 'OIL', 'USOIL', 'BRENT')):
            return 'commodities'
        elif instrument.endswith('USD') and len(instrument) <= 6:
            return 'forex'
        elif instrument in ('US30', 'US500', 'US100', 'GER30', 'UK100'):
            return 'indices'
        elif instrument in ('BTCUSD', 'ETHUSD', 'XRPUSD'):
            return 'crypto'
        else:
            return 'forex'  # Default to forex
    
    def _get_mock_sentiment(self, instrument: str) -> str:
        """Generate mock sentiment data for testing"""
        # Create realistic mock data based on the instrument
        sentiment_data = {
            "instrument": instrument,
            "overall": "bullish",
            "strength": 65,  # 0-100 scale
            "change": 3.5,   # percentage change
            "time_frame": {
                "short_term": "bullish",
                "medium_term": "neutral",
                "long_term": "bullish"
            },
            "indicators": {
                "moving_averages": "buy",
                "oscillators": "neutral",
                "pivot_points": "buy"
            },
            "volume": {
                "current": "high",
                "change": 12.3  # percentage change
            },
            "key_levels": {
                "support": [1.0750, 1.0680, 1.0620],
                "resistance": [1.0850, 1.0920, 1.0980]
            }
        }
        
        return self._format_sentiment_data(instrument, sentiment_data)
    
    def _format_sentiment_data(self, instrument: str, data: Dict[str, Any]) -> str:
        """Format sentiment data into a readable message"""
        try:
            # Create a nicely formatted HTML message
            message = f"<b>📊 Market Sentiment: {instrument}</b>\n\n"
            
            # Overall sentiment
            sentiment = data.get("overall", "neutral").upper()
            strength = data.get("strength", 50)
            
            # Add emoji based on sentiment
            if sentiment == "BULLISH":
                emoji = "🟢"
            elif sentiment == "BEARISH":
                emoji = "🔴"
            else:
                emoji = "⚪"
            
            message += f"{emoji} <b>Overall Sentiment:</b> {sentiment} (Strength: {strength}%)\n"
            
            # Add change
            change = data.get("change", 0)
            change_emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
            message += f"{change_emoji} <b>Change:</b> {change:+.1f}%\n\n"
            
            # Time frames
            message += "<b>Time Frame Analysis:</b>\n"
            time_frames = data.get("time_frame", {})
            for tf, value in time_frames.items():
                tf_name = tf.replace("_", " ").title()
                message += f"• {tf_name}: {value.title()}\n"
            
            message += "\n<b>Technical Indicators:</b>\n"
            indicators = data.get("indicators", {})
            for ind, value in indicators.items():
                ind_name = ind.replace("_", " ").title()
                message += f"• {ind_name}: {value.title()}\n"
            
            # Key levels
            message += "\n<b>Key Price Levels:</b>\n"
            key_levels = data.get("key_levels", {})
            
            # Support levels
            support = key_levels.get("support", [])
            if support:
                message += "• Support: "
                message += ", ".join([f"{level:.4f}" for level in support])
                message += "\n"
            
            # Resistance levels
            resistance = key_levels.get("resistance", [])
            if resistance:
                message += "• Resistance: "
                message += ", ".join([f"{level:.4f}" for level in resistance])
                message += "\n"
            
            # Volume
            volume = data.get("volume", {})
            if volume:
                message += f"\n<b>Volume:</b> {volume.get('current', 'normal').title()}"
                vol_change = volume.get("change", 0)
                if vol_change != 0:
                    message += f" ({vol_change:+.1f}%)"
            
            # Add disclaimer
            message += "\n\n<i>Note: This sentiment analysis is for informational purposes only and should not be considered as financial advice.</i>"
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting sentiment data: {str(e)}")
            return f"<b>📊 Market Sentiment: {instrument}</b>\n\nUnable to format sentiment data. Please try again later." 
