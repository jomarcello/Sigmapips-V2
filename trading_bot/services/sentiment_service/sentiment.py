import logging
import aiohttp
import os
import json
import random
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MarketSentimentService:
    """Service for retrieving market sentiment data"""
    
    def __init__(self):
        """Initialize the market sentiment service"""
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.perplexity_api_key = os.getenv("PERPLEXITY_API_KEY", "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")
        
        self.deepseek_url = "https://api.deepseek.ai/v1/chat/completions"
        self.perplexity_url = "https://api.perplexity.ai/chat/completions"
        
        self.deepseek_headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json"
        }
        
        self.perplexity_headers = {
            "Authorization": f"Bearer {self.perplexity_api_key}",
            "Content-Type": "application/json"
        }
        
        # If no DeepSeek API key is provided, we'll use mock data
        self.use_mock = not self.deepseek_api_key
        if self.use_mock:
            logger.warning("No DeepSeek API key found, using mock data")
    
    async def get_market_sentiment(self, instrument_or_signal) -> Dict[str, Any]:
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
                # Generate more dynamic mock data based on instrument type
                market = self._guess_market_from_instrument(instrument)
                
                # Generate sentiment based on market type
                if market == 'crypto':
                    sentiment_score = random.uniform(0.6, 0.8)  # Crypto tends to be more bullish
                elif market == 'commodities':
                    sentiment_score = random.uniform(0.4, 0.7)  # Commodities can be volatile
                else:
                    sentiment_score = random.uniform(0.3, 0.7)  # Forex and indices more balanced
                
                bullish_percentage = int(sentiment_score * 100)
                trend_strength = 'Strong' if abs(sentiment_score - 0.5) > 0.3 else 'Moderate' if abs(sentiment_score - 0.5) > 0.1 else 'Weak'
                
                return {
                    'overall_sentiment': 'bullish' if sentiment_score > 0.6 else 'bearish' if sentiment_score < 0.4 else 'neutral',
                    'sentiment_score': round(sentiment_score, 2),
                    'bullish_percentage': bullish_percentage,
                    'trend_strength': trend_strength,
                    'volatility': random.choice(['High', 'Moderate', 'Low']),
                    'support_level': 'See analysis for details',
                    'resistance_level': 'See analysis for details',
                    'recommendation': 'See analysis for detailed trading recommendations',
                    'analysis': self._get_mock_sentiment(instrument),
                    'source': 'mock_data'
                }
            
            # First, get market data from Perplexity Sonar
            perplexity_prompt = f"""Analyze {instrument} and provide:
1. Current price, trend direction and key technical levels
2. Latest economic data and central bank actions affecting the pair
3. Recent significant news and market-moving events
4. Key risk factors and market positioning

Provide factual, data-driven analysis with specific numbers and dates."""

            perplexity_payload = {
                "model": "sonar-medium-online",
                "messages": [{
                    "role": "system",
                    "content": "You are a professional market analyst. Provide factual, data-driven analysis with specific numbers, levels and recent events."
                }, {
                    "role": "user",
                    "content": perplexity_prompt
                }],
                "temperature": 0.1
            }

            market_data = ""
            async with aiohttp.ClientSession() as session:
                async with session.post(self.perplexity_url, json=perplexity_payload, headers=self.perplexity_headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        market_data = data['choices'][0]['message']['content']
                    else:
                        logger.error(f"Perplexity API error: {response.status}")
                        return self._get_fallback_sentiment(signal)

            # Then format with DeepSeek
            deepseek_prompt = f"""Using the following market data, create a structured market analysis for {instrument}:

{market_data}

Format the analysis as follows:

🎯 {instrument} Market Analysis

📈 Market Direction:
[Current trend, momentum and price action analysis]

📡 Latest News & Events:
• [Key market-moving news and events]
• [Important economic data]
• [Central bank actions]
• [Other significant developments]

🎯 Key Levels:
• Support Levels:
  - [Current support levels with context]
  - [Major historical support levels]
• Resistance Levels:
  - [Current resistance levels with context]
  - [Major historical resistance levels]

⚠️ Risk Factors:
• Economic: [Key economic risks]
• Political: [Political risk factors]
• Technical: [Technical risks and warnings]
• Market: [Market positioning risks]

💡 Conclusion:
[Trading recommendation based on analysis]"""

            payload = {
                "model": "deepseek-chat",
                "messages": [{
                    "role": "system",
                    "content": """You are a professional forex market analyst. Format the provided market data into a clear, structured analysis. Keep the original data but improve readability and organization.
                    Do not make up data - use only the information provided.
                    Do not include any HTML tags or formatting marks in your response."""
                }, {
                    "role": "user",
                    "content": deepseek_prompt
                }],
                "temperature": 0.7
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.deepseek_url, json=payload, headers=self.deepseek_headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data['choices'][0]['message']['content']
                        # Determine sentiment from content
                        sentiment_score = 0.5  # Default neutral
                        if 'bullish' in content.lower():
                            sentiment_score = 0.7
                        elif 'bearish' in content.lower():
                            sentiment_score = 0.3
                        
                        # Convert sentiment score to bullish percentage
                        bullish_percentage = int(sentiment_score * 100)
                        
                        # Extract trend and volatility from content
                        trend_strength = 'Strong' if abs(sentiment_score - 0.5) > 0.3 else 'Moderate' if abs(sentiment_score - 0.5) > 0.1 else 'Weak'
                        volatility = 'High' if 'volatil' in content.lower() else 'Moderate'
                        
                        # Extract support and resistance levels
                        support_level = 'Current market level' if 'support' not in content.lower() else 'See analysis for details'
                        resistance_level = 'Current market level' if 'resistance' not in content.lower() else 'See analysis for details'
                        
                        return {
                            'overall_sentiment': 'bullish' if sentiment_score > 0.6 else 'bearish' if sentiment_score < 0.4 else 'neutral',
                            'sentiment_score': sentiment_score,
                            'bullish_percentage': bullish_percentage,
                            'trend_strength': trend_strength,
                            'volatility': volatility,
                            'support_level': support_level,
                            'resistance_level': resistance_level,
                            'recommendation': 'See analysis for detailed trading recommendations',
                            'analysis': content,
                            'source': 'deepseek'
                        }
                    else:
                        logger.error(f"DeepSeek API error: {response.status}")
                        fallback = self._get_fallback_sentiment(signal)
                        return {
                            'overall_sentiment': 'neutral',
                            'sentiment_score': 0.5,
                            'bullish_percentage': 50,
                            'trend_strength': 'Weak',
                            'volatility': 'Moderate',
                            'support_level': 'See analysis for details',
                            'resistance_level': 'See analysis for details',
                            'recommendation': 'See analysis for detailed trading recommendations',
                            'analysis': fallback,
                            'source': 'fallback'
                        }
        
        except Exception as e:
            logger.error(f"Error getting sentiment: {str(e)}")
            fallback = self._get_fallback_sentiment(instrument_or_signal if isinstance(instrument_or_signal, dict) else {'instrument': instrument_or_signal})
            return {
                'overall_sentiment': 'neutral',
                'sentiment_score': 0.5,
                'bullish_percentage': 50,
                'trend_strength': 'Weak',
                'volatility': 'Moderate',
                'support_level': 'See analysis for details',
                'resistance_level': 'See analysis for details',
                'recommendation': 'See analysis for detailed trading recommendations',
                'analysis': fallback,
                'source': 'error_fallback'
            }
    
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
        market = self._guess_market_from_instrument(instrument)
        sentiment_score = random.uniform(0.3, 0.7)
        trend = 'upward' if sentiment_score > 0.5 else 'downward'
        volatility = random.choice(['high', 'moderate', 'low'])
        
        analysis = f"""<b>{instrument} Market Analysis</b>

<b>Market Direction:</b>
The {instrument} is showing a {trend} trend with {volatility} volatility. Price action indicates {'momentum building' if sentiment_score > 0.6 else 'potential reversal' if sentiment_score < 0.4 else 'consolidation'}.

<b>Key Factors:</b>
• Market Type: {market.capitalize()}
• Trend Strength: {'Strong' if abs(sentiment_score - 0.5) > 0.3 else 'Moderate' if abs(sentiment_score - 0.5) > 0.1 else 'Weak'}
• Volatility: {volatility.capitalize()}

<b>Trading Recommendation:</b>
{'Consider long positions with tight stops' if sentiment_score > 0.6 else 'Watch for short opportunities' if sentiment_score < 0.4 else 'Wait for clearer directional signals'}

Remember to always use proper risk management and follow your trading plan."""
        
        return analysis
    
    def _get_fallback_sentiment(self, signal: Dict[str, Any]) -> str:
        """Fallback sentiment analysis"""
        symbol = signal.get('instrument', 'Unknown')
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
