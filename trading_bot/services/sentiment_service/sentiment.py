import os
import logging
import aiohttp
import json
from typing import Dict, Any

logger = logging.getLogger(__name__)

class MarketSentimentService:
    def __init__(self):
        """Initialize sentiment service"""
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "sk-274ea5952e7e4b87aba4b14de3990c7d")
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def get_market_sentiment(self, signal: Dict[str, Any]) -> str:
        """Get market sentiment analysis"""
        try:
            symbol = signal.get('symbol', '')
            market = 'crypto' if any(crypto in symbol for crypto in ['BTC', 'ETH', 'XRP']) else 'forex'
            logger.info(f"Getting market sentiment for {symbol} ({market})")

            # Tijdelijk direct fallback gebruiken voor testing
            return self._get_fallback_sentiment(signal)

        except Exception as e:
            logger.error(f"Error getting sentiment: {str(e)}")
            return self._get_fallback_sentiment(signal)

    def _format_sentiment_html(self, symbol: str, data: Dict[str, Any]) -> str:
        """Format sentiment data in HTML"""
        return f"""<b>{symbol} Market Analysis</b>

<b>Market Direction:</b>
{data['direction']}

<b>Key Levels:</b>
• Support Levels:
{chr(10).join(f"  - {level}" for level in data['support_levels'])}
• Resistance Levels:
{chr(10).join(f"  - {level}" for level in data['resistance_levels'])}

<b>Risk Factors:</b>
{chr(10).join(f"• {risk}" for risk in data['risks'])}

<b>Trading Strategy:</b>
• Short Term: {data['short_term']}
• Long Term: {data['long_term']}
• Risk Management: {data['risk_management']}

<b>Conclusion:</b>
{data['conclusion']}"""

    def _get_fallback_sentiment(self, signal: Dict[str, Any]) -> str:
        """Fallback sentiment analysis"""
        symbol = signal.get('symbol', 'Unknown')
        return f"""<b>{symbol} Market Analysis</b>

<b>Market Direction:</b>
The market is showing neutral sentiment with mixed signals. Current price action suggests a consolidation phase.

<b>Key Levels:</b>
• Support Levels:
  - Previous low (Historical support zone)
  - Technical support level
• Resistance Levels:
  - Previous high (Technical resistance)
  - Psychological level

<b>Risk Factors:</b>
• Market Volatility: Increased uncertainty in current conditions
• Technical Signals: Mixed indicators showing conflicting signals
• Data Availability: Limited market data affecting analysis
• External Factors: General market conditions remain uncertain

<b>Trading Strategy:</b>
• Short Term: Wait for clearer signals before entering positions
• Long Term: Monitor key levels for potential trend changes
• Risk Management: Use proper position sizing and tight stops

<b>Conclusion:</b>
Maintain cautious approach until market direction becomes clearer.""" 
