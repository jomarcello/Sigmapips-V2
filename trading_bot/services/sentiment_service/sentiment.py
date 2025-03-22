import logging
import aiohttp
import os
import json
import random
from typing import Dict, Any, Optional

logger = logging.getLogger("market_sentiment")

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
        """Get market sentiment analysis using Perplexity for news search and DeepSeek for formatting"""
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
                logger.info("Using mock data for sentiment analysis")
                return self._get_mock_sentiment_data(instrument)
            
            # First step: Use Perplexity to search for recent news and market data
            market_data = await self._get_perplexity_news(instrument, market)
            if not market_data:
                logger.warning(f"Failed to get Perplexity news for {instrument}, using fallback")
                return self._get_fallback_sentiment(signal)
            
            # Second step: Use DeepSeek to format the news into a structured message
            formatted_analysis = await self._format_with_deepseek(instrument, market, market_data)
            if not formatted_analysis:
                logger.warning(f"Failed to format with DeepSeek for {instrument}, using perplexity raw data")
                # Use the Perplexity data directly with minimal formatting
                sentiment_score = 0.5  # Default neutral
                if "bullish" in market_data.lower() or "positive" in market_data.lower():
                    sentiment_score = 0.7
                elif "bearish" in market_data.lower() or "negative" in market_data.lower():
                    sentiment_score = 0.3
                
                bullish_percentage = int(sentiment_score * 100)
                
                return {
                    'overall_sentiment': 'bullish' if sentiment_score > 0.6 else 'bearish' if sentiment_score < 0.4 else 'neutral',
                    'sentiment_score': sentiment_score,
                    'bullish_percentage': bullish_percentage,
                    'trend_strength': 'Moderate',
                    'volatility': 'Moderate',
                    'support_level': 'See analysis for details',
                    'resistance_level': 'See analysis for details',
                    'recommendation': 'See analysis for trading recommendations',
                    'analysis': market_data,
                    'source': 'perplexity_only'
                }
            
            # Extract sentiment metrics from the formatted analysis
            sentiment_score = 0.5  # Default neutral
            if "bullish" in formatted_analysis.lower():
                sentiment_score = 0.7
            elif "bearish" in formatted_analysis.lower():
                sentiment_score = 0.3
            
            bullish_percentage = int(sentiment_score * 100)
            trend_strength = 'Strong' if abs(sentiment_score - 0.5) > 0.3 else 'Moderate' if abs(sentiment_score - 0.5) > 0.1 else 'Weak'
            
            return {
                'overall_sentiment': 'bullish' if sentiment_score > 0.6 else 'bearish' if sentiment_score < 0.4 else 'neutral',
                'sentiment_score': sentiment_score,
                'bullish_percentage': bullish_percentage,
                'trend_strength': trend_strength,
                'volatility': 'High' if 'volatil' in formatted_analysis.lower() else 'Moderate',
                'support_level': 'See analysis for details',
                'resistance_level': 'See analysis for details',
                'recommendation': 'See analysis for detailed trading recommendations',
                'analysis': formatted_analysis,
                'source': 'perplexity_deepseek'
            }
        
        except Exception as e:
            logger.error(f"Error getting sentiment: {str(e)}")
            return self._get_fallback_sentiment(instrument_or_signal if isinstance(instrument_or_signal, dict) else {'instrument': instrument_or_signal})
    
    async def _get_perplexity_news(self, instrument: str, market: str) -> str:
        """Use Perplexity API to get latest news and market data"""
        logger.info(f"Searching for {instrument} news using Perplexity API")
        
        # Create search queries based on market type
        if market == 'forex':
            search_query = f"Latest forex news and analysis for {instrument}. Current price, technical levels, and market sentiment."
        elif market == 'crypto':
            search_query = f"Latest cryptocurrency news for {instrument}. Current price, market trends, and future outlook."
        elif market == 'indices':
            search_query = f"Latest market news for {instrument} index. Current price, technical analysis, and market sentiment."
        elif market == 'commodities':
            search_query = f"Latest commodities market news for {instrument}. Current price, supply/demand factors, and market sentiment."
        else:
            search_query = f"Latest market news and analysis for {instrument}. Current price, technical levels, and trading outlook."
        
        try:
            async with aiohttp.ClientSession() as session:
                # Updated payload with proper model parameter for Perplexity API
                payload = {
                    "model": "sonar-medium-online",
                    "messages": [{"role": "user", "content": search_query}],
                    "temperature": 0.2,
                    "max_tokens": 1024
                }
                
                logger.info(f"Calling Perplexity API with model: {payload['model']}")
                
                async with session.post(self.perplexity_url, headers=self.perplexity_headers, json=payload) as response:
                    response_text = await response.text()
                    logger.info(f"Perplexity API response status: {response.status}")
                    logger.info(f"Perplexity API response: {response_text[:200]}...")  # Log first 200 chars
                    
                    if response.status == 200:
                        data = await response.json()
                        if data and "choices" in data and len(data["choices"]) > 0:
                            content = data["choices"][0]["message"]["content"]
                            logger.info(f"Successfully received news data for {instrument}")
                            return content
                    
                    logger.error(f"Perplexity API error: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error calling Perplexity API: {str(e)}")
            logger.exception(e)  # Add stack trace for more detailed error information
            return None
    
    async def _format_with_deepseek(self, instrument: str, market: str, market_data: str) -> str:
        """Use DeepSeek to format the news into a structured Telegram message"""
        if not self.deepseek_api_key:
            logger.warning("No DeepSeek API key available, skipping formatting")
            return None
            
        logger.info(f"Formatting market data for {instrument} using DeepSeek API")
        
        try:
            async with aiohttp.ClientSession() as session:
                prompt = f"""Using the following market data, create a structured market analysis for {instrument} to be displayed in a Telegram bot:

{market_data}

Format the analysis as follows:

🎯 {instrument} Market Analysis

📈 Market Direction:
[Current trend, momentum and price action analysis]

📰 Latest News & Events:
• [Key market-moving news item 1]
• [Key market-moving news item 2]
• [Key market-moving news item 3]

🎯 Key Levels:
• Support Levels:
  - [Current support levels with context]
• Resistance Levels:
  - [Current resistance levels with context]

⚠️ Risk Factors:
• [Key risk factor 1]
• [Key risk factor 2]

💡 Conclusion:
[Trading recommendation based on analysis]

Use HTML formatting for Telegram: <b>bold</b>, <i>italic</i>, etc.
Keep the analysis concise but informative, focusing on actionable insights.
If certain information is not available in the market data, make reasonable assumptions based on what is provided.
"""
                
                payload = {
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "You are an expert financial analyst creating market analysis summaries for traders."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1024
                }
                
                async with session.post(self.deepseek_url, headers=self.deepseek_headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data['choices'][0]['message']['content']
                        logger.info(f"Successfully formatted market data for {instrument}")
                        return content
                    
                    logger.error(f"DeepSeek API error: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error calling DeepSeek API: {str(e)}")
            return None
    
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
    
    def _get_mock_sentiment_data(self, instrument: str) -> Dict[str, Any]:
        """Generate mock sentiment data for testing"""
        market = self._guess_market_from_instrument(instrument)
        sentiment_score = random.uniform(0.3, 0.7)
        trend = 'upward' if sentiment_score > 0.5 else 'downward'
        volatility = random.choice(['high', 'moderate', 'low'])
        bullish_percentage = int(sentiment_score * 100)
        
        analysis = f"""<b>🎯 {instrument} Market Analysis</b>

<b>📈 Market Direction:</b>
The {instrument} is showing a {trend} trend with {volatility} volatility. Price action indicates {'momentum building' if sentiment_score > 0.6 else 'potential reversal' if sentiment_score < 0.4 else 'consolidation'}.

<b>📰 Latest News & Events:</b>
• No significant market-moving news at this time
• Regular market fluctuations based on supply and demand
• Technical factors are the primary price drivers currently

<b>🎯 Key Levels:</b>
• Support Levels:
  - Technical support at previous low
• Resistance Levels:
  - Technical resistance at previous high

<b>⚠️ Risk Factors:</b>
• Market volatility could increase with upcoming economic data releases
• Low liquidity periods may cause price spikes

<b>💡 Conclusion:</b>
{'Consider long positions with tight stops' if sentiment_score > 0.6 else 'Watch for short opportunities' if sentiment_score < 0.4 else 'Wait for clearer directional signals'}

<i>This is a simulated analysis for demonstration purposes.</i>"""
        
        return {
            'overall_sentiment': 'bullish' if sentiment_score > 0.6 else 'bearish' if sentiment_score < 0.4 else 'neutral',
            'sentiment_score': round(sentiment_score, 2),
            'bullish_percentage': bullish_percentage,
            'trend_strength': 'Strong' if abs(sentiment_score - 0.5) > 0.3 else 'Moderate' if abs(sentiment_score - 0.5) > 0.1 else 'Weak',
            'volatility': volatility.capitalize(),
            'support_level': 'See analysis for details',
            'resistance_level': 'See analysis for details',
            'recommendation': 'Consider long positions' if sentiment_score > 0.6 else 'Watch for shorts' if sentiment_score < 0.4 else 'Wait for signals',
            'analysis': analysis,
            'source': 'mock_data'
        }
    
    def _get_fallback_sentiment(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback sentiment analysis"""
        symbol = signal.get('instrument', 'Unknown')
        analysis = f"""<b>🎯 {symbol} Market Analysis</b>

<b>📈 Market Direction:</b>
The market is showing neutral sentiment with mixed signals. Current price action suggests a consolidation phase.

<b>📰 Latest News & Events:</b>
• No significant market-moving news available at this time
• Regular market fluctuations based on technical factors
• Waiting for clearer directional catalysts

<b>🎯 Key Levels:</b>
• Support Levels:
  - Previous low (Historical support zone)
• Resistance Levels:
  - Previous high (Technical resistance)

<b>⚠️ Risk Factors:</b>
• Market Volatility: Increased uncertainty in current conditions
• News Events: Watch for unexpected announcements

<b>💡 Conclusion:</b>
Wait for clearer market signals before taking new positions.

<i>This is a fallback analysis as we could not retrieve real-time data.</i>"""

        return {
            'overall_sentiment': 'neutral',
            'sentiment_score': 0.5,
            'bullish_percentage': 50,
            'trend_strength': 'Weak',
            'volatility': 'Moderate',
            'support_level': 'See analysis for details',
            'resistance_level': 'See analysis for details',
            'recommendation': 'Wait for clearer market signals',
            'analysis': analysis,
            'source': 'fallback'
        }
