import logging
import aiohttp
import os
import json
import random
from typing import Dict, Any, Optional
import asyncio

logger = logging.getLogger("market_sentiment")

class MarketSentimentService:
    """Service for retrieving market sentiment data"""
    
    def __init__(self):
        """Initialize the market sentiment service"""
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.tavily_api_key = os.getenv("TAVILY_API_KEY")
        
        self.deepseek_url = "https://api.deepseek.ai/v1/chat/completions"
        self.tavily_url = "https://api.tavily.com/v1/search"
        
        self.deepseek_headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json"
        }
        
        self.tavily_headers = {
            "Authorization": f"Bearer {self.tavily_api_key}",
            "Content-Type": "application/json"
        }
        
        # Log API key status (without revealing full keys)
        if self.tavily_api_key:
            masked_key = self.tavily_api_key[:6] + "..." + self.tavily_api_key[-4:] if len(self.tavily_api_key) > 10 else "***"
            logger.info(f"Tavily API key is configured: {masked_key}")
        else:
            logger.warning("No Tavily API key found")
        
        # If no DeepSeek API key is provided, we'll use mock data
        if self.deepseek_api_key:
            masked_key = self.deepseek_api_key[:6] + "..." + self.deepseek_api_key[-4:] if len(self.deepseek_api_key) > 10 else "***"
            logger.info(f"DeepSeek API key is configured: {masked_key}")
        else:
            logger.warning("No DeepSeek API key found, using mock data")
            
        self.use_mock = not self.deepseek_api_key
    
    async def get_market_sentiment(self, instrument_or_signal) -> Dict[str, Any]:
        """Get market sentiment analysis using Tavily for news search and DeepSeek for formatting"""
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
            
            # First step: Use Tavily to search for recent news and market data
            market_data = await self._get_tavily_news(instrument, market)
            if not market_data:
                logger.warning(f"Failed to get Tavily news for {instrument}, using fallback")
                return self._get_fallback_sentiment(signal)
            
            # Second step: Use DeepSeek to format the news into a structured message
            formatted_analysis = await self._format_with_deepseek(instrument, market, market_data)
            if not formatted_analysis:
                logger.warning(f"Failed to format with DeepSeek for {instrument}, using Tavily raw data")
                # Use the Tavily data directly with minimal formatting
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
                    'source': 'tavily_only'
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
                'source': 'tavily_deepseek'
            }
        
        except Exception as e:
            logger.error(f"Error getting sentiment: {str(e)}")
            return self._get_fallback_sentiment(instrument_or_signal if isinstance(instrument_or_signal, dict) else {'instrument': instrument_or_signal})
    
    async def _get_tavily_news(self, instrument: str, market: str) -> str:
        """Use Tavily API to get latest news and market data"""
        logger.info(f"Searching for {instrument} news using Tavily API")
        
        # Check if API key is configured
        if not self.tavily_api_key:
            logger.error("Tavily API key is not configured")
            return None
            
        # Create search query based on market type
        if market == 'forex':
            search_query = f"recent news about {instrument} forex currency pair market analysis price movement"
        elif market == 'crypto':
            search_query = f"recent news about {instrument} cryptocurrency price analysis market trends"
        elif market == 'indices':
            search_query = f"recent news about {instrument} stock index market analysis trends"
        elif market == 'commodities':
            search_query = f"recent news about {instrument} commodity price analysis market trends"
        else:
            search_query = f"recent news about {instrument} market analysis price trends"
        
        try:
            async with aiohttp.ClientSession() as session:
                # Updated payload structure for Tavily API
                payload = {
                    "api_key": self.tavily_api_key,  # Include API key in the payload
                    "query": search_query,
                    "search_depth": "advanced",
                    "include_answer": True,
                    "include_domains": ["bloomberg.com", "reuters.com", "investing.com", "cnbc.com", "forexlive.com", "fxstreet.com"],
                    "exclude_domains": [],
                    "max_tokens": 8000,
                    "max_results": 10
                }
                
                logger.info(f"Calling Tavily API with query: {search_query}")
                
                # Try with API key in the header first
                headers = {"Content-Type": "application/json"}
                if self.tavily_api_key:
                    headers["X-Api-Key"] = self.tavily_api_key
                
                timeout = aiohttp.ClientTimeout(total=15)
                
                # First attempt: Try with X-Api-Key header 
                try:
                    async with session.post(
                        self.tavily_url, 
                        headers=headers,
                        json={"query": search_query, "search_depth": "advanced", "include_answer": True},
                        timeout=timeout
                    ) as response:
                        response_text = await response.text()
                        logger.info(f"Tavily API response status (header auth): {response.status}")
                        
                        if response.status == 200:
                            return self._process_tavily_response(response_text, instrument)
                        else:
                            logger.warning(f"First attempt with X-Api-Key header failed: {response.status}")
                except Exception as e:
                    logger.warning(f"Error in first attempt: {str(e)}")
                
                # Second attempt: Try with Authorization header
                try:
                    async with session.post(
                        self.tavily_url, 
                        headers={"Authorization": f"Bearer {self.tavily_api_key}", "Content-Type": "application/json"},
                        json={"query": search_query, "search_depth": "advanced", "include_answer": True},
                        timeout=timeout
                    ) as response:
                        response_text = await response.text()
                        logger.info(f"Tavily API response status (bearer auth): {response.status}")
                        
                        if response.status == 200:
                            return self._process_tavily_response(response_text, instrument)
                        else:
                            logger.warning(f"Second attempt with Bearer token failed: {response.status}")
                except Exception as e:
                    logger.warning(f"Error in second attempt: {str(e)}")
                
                # Third attempt: Try with API key in payload
                try:
                    del headers["X-Api-Key"]
                    payload = {
                        "api_key": self.tavily_api_key,
                        "query": search_query,
                        "search_depth": "advanced",
                        "include_answer": True
                    }
                    
                    async with session.post(
                        self.tavily_url, 
                        headers={"Content-Type": "application/json"},
                        json=payload,
                        timeout=timeout
                    ) as response:
                        response_text = await response.text()
                        logger.info(f"Tavily API response status (payload auth): {response.status}")
                        
                        if response.status == 200:
                            return self._process_tavily_response(response_text, instrument)
                        else:
                            logger.error(f"All Tavily API auth methods failed. Final status: {response.status}, details: {response_text}")
                            return None
                except Exception as e:
                    logger.error(f"Error in third attempt: {str(e)}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error calling Tavily API: {str(e)}")
            logger.exception(e)
            return None
            
    def _process_tavily_response(self, response_text: str, instrument: str) -> str:
        """Process the Tavily API response and extract useful information"""
        try:
            data = json.loads(response_text)
            
            # Extract the generated answer
            if data and "answer" in data:
                answer = data["answer"]
                logger.info(f"Successfully received answer from Tavily for {instrument}")
                
                # Also extract results for more comprehensive information
                if "results" in data:
                    results_text = "\n\nMore details from search results:\n"
                    for idx, result in enumerate(data["results"][:5]):  # Limit to top 5 results
                        title = result.get("title", "No Title")
                        content = result.get("content", "No Content").strip()
                        url = result.get("url", "")
                        
                        results_text += f"\n{idx+1}. {title}\n"
                        results_text += f"{content[:300]}...\n"  # Limit content length
                        results_text += f"Source: {url}\n"
                    
                    combined_text = answer + results_text
                    return combined_text
                
                return answer
            
            # If no answer but we have search results
            elif data and "results" in data and data["results"]:
                results_text = "Recent market information:\n\n"
                for idx, result in enumerate(data["results"][:8]):  # Get top 8 results
                    title = result.get("title", "No Title")
                    content = result.get("content", "No Content").strip()
                    url = result.get("url", "")
                    
                    results_text += f"{idx+1}. {title}\n"
                    results_text += f"{content[:300]}...\n"  # Limit content length
                    results_text += f"Source: {url}\n\n"
                
                logger.info(f"Successfully received search results from Tavily for {instrument}")
                return results_text
                
            logger.error(f"Unexpected Tavily API response format: {response_text[:200]}...")
            return None
                
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON response from Tavily: {response_text[:200]}...")
            return None
    
    async def _format_with_deepseek(self, instrument: str, market: str, market_data: str) -> str:
        """Use DeepSeek to format the news into a structured Telegram message"""
        if not self.deepseek_api_key:
            logger.warning("No DeepSeek API key available, skipping formatting")
            return None
            
        logger.info(f"Formatting market data for {instrument} using DeepSeek API")
        
        try:
            # First attempt to check if DeepSeek API is reachable
            deepseek_available = True
            try:
                import socket
                # Try DNS resolution first - if this fails, we know the host is unreachable
                socket.gethostbyname('api.deepseek.ai')
                logger.info("DeepSeek API DNS resolution successful")
            except socket.gaierror:
                logger.warning("DeepSeek API DNS resolution failed - host unreachable")
                deepseek_available = False
            
            if not deepseek_available:
                logger.warning("DeepSeek API is unreachable, using manual formatting")
                return self._format_data_manually(instrument, market_data)
            
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
                
                try:
                    # Use a shorter timeout to avoid long waits when service is unreachable
                    timeout = aiohttp.ClientTimeout(total=10)
                    async with session.post(
                        self.deepseek_url, 
                        headers=self.deepseek_headers, 
                        json=payload, 
                        timeout=timeout
                    ) as response:
                        response_text = await response.text()
                        logger.info(f"DeepSeek API response status: {response.status}")
                        logger.info(f"DeepSeek API response: {response_text[:200]}...")  # Log first 200 chars
                        
                        if response.status == 200:
                            data = json.loads(response_text)
                            content = data['choices'][0]['message']['content']
                            logger.info(f"Successfully formatted market data for {instrument}")
                            return content
                        
                        logger.error(f"DeepSeek API error: {response.status}, details: {response_text}")
                        return self._format_data_manually(instrument, market_data)
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.error(f"DeepSeek API client/timeout error: {str(e)}")
                    return self._format_data_manually(instrument, market_data)
                    
        except Exception as e:
            logger.error(f"Error calling DeepSeek API: {str(e)}")
            logger.exception(e)
            return self._format_data_manually(instrument, market_data)
            
    def _format_data_manually(self, instrument: str, market_data: str) -> str:
        """Format the market data manually when DeepSeek API fails"""
        logger.info(f"Formatting market data manually for {instrument}")
        
        # Extract key information from the market data
        lines = market_data.strip().split('\n')
        title_line = f"<b>🎯 {instrument} Market Analysis</b>"
        
        # Improved sentiment detection with keyword counting and weighting
        bullish_keywords = ["bullish", "uptrend", "upward", "rise", "increase", "gains", "strengthen", "higher", "positive", "up"]
        bearish_keywords = ["bearish", "downtrend", "downward", "fall", "decrease", "retreating", "weaken", "lower", "negative", "down"]
        
        # Count occurrences with context
        bullish_count = 0
        bearish_count = 0
        
        # Check for keywords in context
        for keyword in bullish_keywords:
            bullish_count += market_data.lower().count(keyword)
        
        for keyword in bearish_keywords:
            bearish_count += market_data.lower().count(keyword)
        
        # Determine sentiment based on keyword counts
        if bullish_count > bearish_count * 1.5:
            sentiment = "bullish"
        elif bearish_count > bullish_count * 1.5:
            sentiment = "bearish"
        else:
            # Check for specific phrases that strongly indicate direction
            if "downward trend" in market_data.lower() or "under pressure" in market_data.lower():
                sentiment = "bearish"
            elif "upward trend" in market_data.lower() or "gaining strength" in market_data.lower():
                sentiment = "bullish"
            else:
                sentiment = "neutral"
        
        # Look for explicit sentiment statements
        if "bearish momentum" in market_data.lower() or "likely to remain under pressure" in market_data.lower():
            sentiment = "bearish"
        elif "bullish momentum" in market_data.lower() or "likely to strengthen" in market_data.lower():
            sentiment = "bullish"
        
        # Log the sentiment detection
        logger.info(f"Detected sentiment for {instrument}: {sentiment} (bullish count: {bullish_count}, bearish count: {bearish_count})")
        
        # Prepare the analysis
        analysis = f"{title_line}\n\n"
        analysis += f"<b>📈 Market Direction:</b>\n"
        analysis += f"The {instrument} is currently showing {sentiment} sentiment based on recent market data and analysis.\n\n"
        
        analysis += "<b>📰 Latest News & Events:</b>\n"
        
        # Try to extract 2-3 bullet points from the raw data
        news_items = []
        for line in lines:
            line = line.strip()
            # Look for sentences that contain market-related terms
            if (line and len(line) > 20 and "." in line and 
                not line.startswith(("Source:", "http", "www")) and
                any(term in line.lower() for term in ["market", "price", "trading", "economy", "dollar", "euro", "rate", "fed", "ecb"])):
                news_items.append(f"• {line}")
                if len(news_items) >= 3:
                    break
        
        # If we couldn't extract enough news items, use the raw data
        if len(news_items) < 2:
            # Just use the first 3 paragraphs as bullet points
            news_text = " ".join(lines)
            paragraphs = [p.strip() for p in news_text.split('.') if len(p.strip()) > 20]
            for i, para in enumerate(paragraphs[:3]):
                news_items.append(f"• {para}.")
                if len(news_items) >= 3:
                    break
        
        analysis += "\n".join(news_items) + "\n\n"
        
        # Extract potential support and resistance levels from the text
        support_level = None
        resistance_level = None
        
        # Look for specific numeric levels mentioned in the text
        import re
        price_pattern = r'(\d+\.\d{4})'
        matches = re.findall(price_pattern, market_data)
        
        if matches and len(matches) >= 2:
            # Sort prices to get potential support and resistance
            prices = sorted([float(p) for p in matches])
            mid_price = sum(prices) / len(prices)
            
            # Use mentioned levels if they exist
            if "support" in market_data.lower() and "resistance" in market_data.lower():
                for i in range(len(lines)):
                    if "support" in lines[i].lower():
                        support_matches = re.findall(price_pattern, lines[i])
                        if support_matches:
                            support_level = support_matches[0]
                    if "resistance" in lines[i].lower():
                        resistance_matches = re.findall(price_pattern, lines[i])
                        if resistance_matches:
                            resistance_level = resistance_matches[0]
            
            # Default to lowest and highest found prices if specific levels not mentioned
            if not support_level:
                support_level = f"{prices[0]:.4f}"
            if not resistance_level:
                resistance_level = f"{prices[-1]:.4f}"
        
        # Add key levels section with real data when possible
        analysis += "<b>🎯 Key Levels:</b>\n"
        analysis += "• Support Levels:\n"
        if support_level:
            analysis += f"  - {support_level} (Mentioned in analysis)\n"
        else:
            analysis += "  - Check recent lows for potential support\n"
            
        analysis += "• Resistance Levels:\n"
        if resistance_level:
            analysis += f"  - {resistance_level} (Mentioned in analysis)\n"
        else:
            analysis += "  - Check recent highs for potential resistance\n\n"
        
        # Extract risk factors when available
        analysis += "<b>⚠️ Risk Factors:</b>\n"
        risk_factors_found = False
        
        for i in range(len(lines)):
            if any(term in lines[i].lower() for term in ["risk", "uncertainty", "tension", "concern"]):
                analysis += f"• {lines[i].strip()}\n"
                risk_factors_found = True
                break
        
        if not risk_factors_found:
            analysis += "• Market volatility could increase with upcoming economic data releases\n"
            analysis += "• Global events and central bank decisions may impact price action\n\n"
        else:
            analysis += "\n"
        
        # Add conclusion based on sentiment
        analysis += "<b>💡 Conclusion:</b>\n"
        if sentiment == "bullish":
            analysis += "Consider potential long opportunities with appropriate risk management.\n"
        elif sentiment == "bearish":
            analysis += "Watch for possible short opportunities while managing risk carefully.\n"
        else:
            analysis += "Monitor the market for clearer directional signals before taking positions.\n"
        
        analysis += "\n<i>Analysis generated based on recent market data.</i>"
        
        return analysis
    
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
