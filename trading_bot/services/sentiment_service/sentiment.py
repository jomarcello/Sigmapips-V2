import logging
import aiohttp
import os
import json
import random
from typing import Dict, Any, Optional
import asyncio
import socket
import re
import ssl

logger = logging.getLogger("market_sentiment")

class MarketSentimentService:
    """Service for retrieving market sentiment data"""
    
    def __init__(self):
        """Initialize the market sentiment service"""
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.tavily_api_key = os.getenv("TAVILY_API_KEY")
        
        self.deepseek_url = "https://api.deepseek.com/v1/chat/completions"
        
        # Initialize the Tavily client
        self.tavily_client = TavilyClient(self.tavily_api_key)
        
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
    
    async def get_market_sentiment(self, instrument: str, market_type: Optional[str] = None) -> Optional[str]:
        """Get market sentiment for a given instrument"""
        logger.info(f"Getting market sentiment for {instrument} ({market_type or 'unknown'})")
        
        if market_type is None:
            # Determine market type from instrument if not provided
            market_type = self._guess_market_from_instrument(instrument)
        
        search_query = None
        market_type = market_type.lower()
        
        if market_type == "forex":
            search_query = f"latest financial news affecting {instrument} forex rate economic factors interest rates central bank decisions"
        elif market_type == "crypto":
            search_query = f"latest cryptocurrency news affecting {instrument} price market developments regulations adoption"
        elif market_type == "indices":
            search_query = f"latest economic news affecting {instrument} index market sector trends company earnings economic data"
        elif market_type == "commodities":
            search_query = f"latest news affecting {instrument} commodity prices supply demand geopolitical factors market trends"
        else:
            search_query = f"latest financial news affecting {instrument} price economic factors market trends"
        
        # Try to get data from Tavily first
        tavily_data = await self._get_tavily_news(search_query)
        
        # If Tavily fails, try alternative news sources
        if not tavily_data:
            logger.warning(f"Tavily search failed, trying alternative news sources for {instrument}")
            alternative_data = await self._get_alternative_news(instrument, market_type)
            
            if alternative_data:
                tavily_data = alternative_data
            else:
                # If both Tavily and alternative news fail, use fallback
                return self._get_fallback_sentiment(instrument)
        
        # Try to use DeepSeek first, regardless of connectivity check
        try:
            logger.info(f"Attempting to process sentiment with DeepSeek for {instrument}")
            deepseek_result = await self._try_deepseek_with_fallback(tavily_data, instrument)
            if deepseek_result:
                return deepseek_result
        except Exception as e:
            logger.error(f"Error processing sentiment with DeepSeek: {str(e)}")
            logger.exception(e)
        
        # If DeepSeek fails, do manual formatting
        logger.info(f"Manually formatting market data for {instrument}")
        return self._format_data_manually(tavily_data, instrument)
            
    def _format_data_manually(self, news_content: str, instrument: str) -> Dict[str, Any]:
        """Format market data manually when DeepSeek API fails"""
        try:
            logger.info(f"Manually formatting market data for {instrument}")
            
            # Extract key phrases and content
            news_lines = news_content.split('\n')
            
            # Create a more structured analysis
            analysis = f"<b>🎯 {instrument} Market Analysis</b>\n\n"
            
            # Create a simple sentiment analysis based on keywords in the news content
            positive_keywords = [
                'bullish', 'gain', 'up', 'rise', 'growth', 'positive', 'surge', 
                'rally', 'outperform', 'increase', 'higher', 'strong', 'advance',
                'recovery', 'support', 'buy', 'long', 'optimistic', 'upward'
            ]
            
            negative_keywords = [
                'bearish', 'loss', 'down', 'fall', 'decline', 'negative', 'drop', 
                'plunge', 'underperform', 'decrease', 'lower', 'weak', 'retreat',
                'resistance', 'sell', 'short', 'pessimistic', 'downward'
            ]
            
            # Count instances of positive and negative keywords
            positive_count = sum(1 for word in positive_keywords if word.lower() in news_content.lower())
            negative_count = sum(1 for word in negative_keywords if word.lower() in news_content.lower())
            
            # Determine sentiment based on keyword counts
            if positive_count > negative_count:
                sentiment = "Bullish"
                sentiment_score = min(90, 50 + (positive_count - negative_count) * 5)
            elif negative_count > positive_count:
                sentiment = "Bearish"
                sentiment_score = max(10, 50 - (negative_count - positive_count) * 5)
            else:
                sentiment = "Neutral"
                sentiment_score = 50
            
            # Add sentiment analysis to the output
            analysis += f"<b>📈 Market Direction:</b>\n"
            analysis += f"The {instrument} is showing {sentiment.lower()} sentiment with a {sentiment_score}% probability. "
            
            if sentiment == "Bullish":
                analysis += "Price action suggests potential for upward movement based on recent news and market factors.\n\n"
            elif sentiment == "Bearish":
                analysis += "Price action suggests potential for downward movement based on recent news and market factors.\n\n"
            else:
                analysis += "Price action shows mixed signals with no clear directional bias at this time.\n\n"
            
            # Extract key news from the content
            analysis += f"<b>📰 Latest News & Events:</b>\n"
            
            # Find key news points
            news_points = []
            for line in news_lines:
                line = line.strip()
                # Skip empty lines and headers
                if not line or line.startswith('Market Analysis') or line.startswith('Detailed Market'):
                    continue
                    
                # If it's a numbered point or looks like a news title, add it
                if (line.startswith(('•', '1.', '2.', '3.', '4.', '5.')) or 
                    (len(line) > 20 and len(line) < 150 and not line.startswith('Source:'))):
                    # Clean up the line
                    cleaned_line = re.sub(r'^[0-9]+\.\s*', '• ', line)
                    cleaned_line = re.sub(r'^•\s*', '• ', cleaned_line)
                    
                    if not cleaned_line.startswith('• '):
                        cleaned_line = f"• {cleaned_line}"
                        
                    news_points.append(cleaned_line)
            
            # Add up to 3 news points
            for point in news_points[:3]:
                analysis += f"{point}\n"
                
            if not news_points:
                analysis += "• No specific news events driving current price action\n"
                analysis += "• Market is currently responding to broader economic factors\n"
                analysis += "• Technical analysis may be more reliable in current conditions\n"
            
            analysis += "\n"
            
            # Add key levels section
            analysis += f"<b>🎯 Key Levels:</b>\n"
            analysis += "• Support Levels:\n"
            analysis += "  - Previous low (Historical support zone)\n"
            analysis += "• Resistance Levels:\n"
            analysis += "  - Previous high (Technical resistance)\n\n"
            
            # Add risk factors section
            analysis += f"<b>⚠️ Risk Factors:</b>\n"
            analysis += "• Market Volatility: Increased uncertainty in current conditions\n"
            analysis += "• News Events: Watch for unexpected announcements\n\n"
            
            # Add a conclusion based on sentiment
            analysis += f"<b>💡 Conclusion:</b>\n"
            if sentiment_score > 65:
                analysis += "Current news suggests favorable market conditions. <b>Consider long positions</b> with risk management strategies in place."
            elif sentiment_score < 35:
                analysis += "Economic data and market factors suggest possible downward pressure. <b>Watch for short opportunities</b>."
            else:
                analysis += "The market shows mixed signals. <b>Wait for clearer signals</b> before taking new positions."
            
            # Clean up any markdown formatting that might be in the analysis
            analysis = re.sub(r'^```html\s*', '', analysis)
            analysis = re.sub(r'\s*```$', '', analysis)
            
            # Return a dictionary similar to what _get_mock_sentiment_data returns
            return {
                'overall_sentiment': sentiment.lower(),
                'sentiment_score': sentiment_score / 100,
                'bullish_percentage': sentiment_score,
                'trend_strength': 'Strong' if abs(sentiment_score - 50) > 20 else 'Moderate' if abs(sentiment_score - 50) > 10 else 'Weak',
                'volatility': 'Moderate',
                'support_level': 'See analysis for details',
                'resistance_level': 'See analysis for details',
                'recommendation': 'Consider long positions' if sentiment_score > 60 else 'Watch for shorts' if sentiment_score < 40 else 'Wait for signals',
                'analysis': analysis,
                'source': 'tavily_data'
            }
            
        except Exception as e:
            logger.error(f"Error formatting market data manually: {str(e)}")
            logger.exception(e)
            return self._get_fallback_sentiment(instrument)
    
    async def _get_tavily_news(self, search_query: str) -> str:
        """Use Tavily API to get latest news and market data"""
        logger.info(f"Searching for news using Tavily API")
        
        # Check if API key is configured
        if not self.tavily_api_key:
            logger.error("Tavily API key is not configured")
            return None
            
        # Use our Tavily client to make the API call
        try:
            response = await self.tavily_client.search(
                query=search_query,
                search_depth="basic",
                include_answer=True,
                max_results=5
            )
            
            if response:
                return self._process_tavily_response(json.dumps(response))
            else:
                logger.error("Tavily search returned no results")
                return None
                
        except Exception as e:
            logger.error(f"Error calling Tavily API: {str(e)}")
            logger.exception(e)
            return None
            
    def _process_tavily_response(self, response_text: str) -> str:
        """Process the Tavily API response and extract useful information"""
        try:
            data = json.loads(response_text)
            
            # Structure for the formatted response
            formatted_text = f"Market Analysis:\n\n"
            
            # Extract the generated answer if available
            if data and "answer" in data and data["answer"]:
                answer = data["answer"]
                formatted_text += f"Summary: {answer}\n\n"
                logger.info("Successfully received answer from Tavily")
                
            # Extract results for more comprehensive information
            if "results" in data and data["results"]:
                formatted_text += "Detailed Market Information:\n"
                for idx, result in enumerate(data["results"][:5]):  # Limit to top 5 results
                    title = result.get("title", "No Title")
                    content = result.get("content", "No Content").strip()
                    url = result.get("url", "")
                    score = result.get("score", 0)
                    
                    formatted_text += f"\n{idx+1}. {title}\n"
                    formatted_text += f"{content[:500]}...\n" if len(content) > 500 else f"{content}\n"
                    formatted_text += f"Source: {url}\n"
                    formatted_text += f"Relevance: {score:.2f}\n"
                
                logger.info(f"Successfully processed {len(data['results'])} results from Tavily")
                return formatted_text
            
            # If no answer and no results but we have response content
            if response_text and len(response_text) > 20:
                logger.warning(f"Unusual Tavily response format, but using raw content")
                return f"Market data:\n\n{response_text[:2000]}"
                
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
            # Check DeepSeek API connectivity first - use IP address instead of hostname
            deepseek_available = False
            try:
                # Use IP address instead of hostname to avoid DNS issues
                deepseek_ip = "23.236.75.155"
                
                # Simple socket connection test
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)  # Quick 3-second timeout
                # Try to connect to DeepSeek IP on port 443 (HTTPS)
                result = sock.connect_ex((deepseek_ip, 443))
                sock.close()
                
                if result == 0:  # Port is open, connection successful
                    logger.info("DeepSeek API connectivity test successful")
                    deepseek_available = True
                else:
                    logger.warning(f"DeepSeek API connectivity test failed with result: {result}")
            except socket.error as e:
                logger.warning(f"DeepSeek API socket connection failed: {str(e)}")
            
            if not deepseek_available:
                logger.warning("DeepSeek API is unreachable, using manual formatting")
                return self._format_data_manually(market_data, instrument)
            
            # Prepare headers with authentication - sanitize API key first
            sanitized_api_key = self.deepseek_api_key.strip()
            deepseek_headers = {
                "Authorization": f"Bearer {sanitized_api_key}",
                "Content-Type": "application/json"
            }
            
            # Create SSL context that doesn't verify certificates
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            # Use the original domain name in URL to match certificate domain
            # This is critical for proper TLS handshake
            deepseek_url = "https://api.deepseek.com/v1/chat/completions"
            
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                prompt = f"""Using the following market data, create a structured market analysis for {instrument} to be displayed in a Telegram bot:

{market_data}

Format the analysis as follows:

🎯 {instrument} Market Analysis

📈 Market Direction:
[Current trend, momentum and price action analysis]

📰 Latest News & Events:
• [Key market-moving news item 1 - remove the news source name]
• [Key market-moving news item 2 - remove the news source name]
• [Key market-moving news item 3 - remove the news source name]

🎯 Key Levels:
• Support Levels:
  - [Current support levels with context]
• Resistance Levels:
  - [Current resistance levels with context]

⚠️ Risk Factors:
• [Key risk factor 1]
• [Key risk factor 2]

💡 Conclusion:
[Trading recommendation based on analysis. Always include a specific recommendation for either <b>long positions</b> or <b>short positions</b> in bold. If uncertain, recommend <b>wait for clearer signals</b> in bold.]

Use HTML formatting for Telegram: <b>bold</b>, <i>italic</i>, etc.
Keep the analysis concise but informative, focusing on actionable insights.
If certain information is not available in the market data, make reasonable assumptions based on what is provided.
DO NOT include any references to where the data came from (no "This analysis is based on data from Tavily API" or similar).
DO NOT include news source names like "FXStreet", "Reuters", etc. Just include the news content.
IMPORTANT: Always include a clear trading recommendation (long positions, short positions, or waiting) in the conclusion section and make sure it's in bold tags.
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
                    
                    # Set Host header to api.deepseek.com while connecting to the IP
                    custom_headers = deepseek_headers.copy()
                    custom_headers["Host"] = "api.deepseek.com"
                    
                    async with session.post(
                        deepseek_url, 
                        headers=custom_headers, 
                        json=payload, 
                        timeout=timeout
                    ) as response:
                        response_text = await response.text()
                        logger.info(f"DeepSeek API response status: {response.status}")
                        
                        if response.status == 200:
                            data = json.loads(response_text)
                            content = data['choices'][0]['message']['content']
                            
                            # Clean up any markdown formatting that might be in the content
                            content = re.sub(r'^```html\s*', '', content)
                            content = re.sub(r'\s*```$', '', content)
                            
                            logger.info(f"Successfully formatted market data for {instrument}")
                            return content
                        
                        # Log the specific error for debugging
                        logger.error(f"DeepSeek API error: {response.status}, details: {response_text}")
                        return self._format_data_manually(market_data, instrument)
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.error(f"DeepSeek API client/timeout error: {str(e)}")
                    return self._format_data_manually(market_data, instrument)
                    
        except Exception as e:
            logger.error(f"Error calling DeepSeek API: {str(e)}")
            logger.exception(e)
            return self._format_data_manually(market_data, instrument)
            
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
{f"Market conditions suggest momentum may continue. <b>Consider long positions</b> with appropriate stop losses." if sentiment_score > 0.6 else f"Current technical signals indicate potential downside. <b>Consider short positions</b> with tight risk management." if sentiment_score < 0.4 else f"Current market conditions lack clear direction. <b>Wait for clearer signals</b> before taking new positions."}"""
        
        # Clean up any markdown formatting that might be in the analysis
        analysis = re.sub(r'^```html\s*', '', analysis)
        analysis = re.sub(r'\s*```$', '', analysis)
        
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
    
    def _get_fallback_sentiment(self, instrument: str) -> Dict[str, Any]:
        """Fallback sentiment analysis"""
        analysis = f"""<b>🎯 {instrument} Market Analysis</b>

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
<b>Wait for clearer signals</b> before taking new positions."""

        # Clean up any markdown formatting that might be in the analysis
        analysis = re.sub(r'^```html\s*', '', analysis)
        analysis = re.sub(r'\s*```$', '', analysis)

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

    async def _get_alternative_news(self, instrument: str, market: str) -> str:
        """Alternative news source when Tavily API fails"""
        logger.info(f"Using alternative news source for {instrument}")
        
        try:
            # Construct appropriate URLs based on market and instrument
            urls = []
            
            if market == 'forex':
                # Common forex news sources
                urls = [
                    f"https://www.forexlive.com/tag/{instrument}/",
                    f"https://www.fxstreet.com/rates-charts/{instrument.lower()}-chart",
                    f"https://finance.yahoo.com/quote/{instrument}=X/"
                ]
            elif market == 'crypto':
                # Crypto news sources
                crypto_symbol = instrument.replace('USD', '')
                urls = [
                    f"https://finance.yahoo.com/quote/{crypto_symbol}-USD/",
                    f"https://www.coindesk.com/price/{crypto_symbol.lower()}/",
                    f"https://www.tradingview.com/symbols/CRYPTO-{crypto_symbol}USD/"
                ]
            elif market == 'indices':
                # Indices news sources
                index_map = {
                    'US30': 'DJI',
                    'US500': 'GSPC',
                    'US100': 'NDX'
                }
                index_symbol = index_map.get(instrument, instrument)
                urls = [
                    f"https://finance.yahoo.com/quote/^{index_symbol}/",
                    f"https://www.marketwatch.com/investing/index/{index_symbol.lower()}"
                ]
            elif market == 'commodities':
                # Commodities news sources
                commodity_map = {
                    'XAUUSD': 'gold',
                    'GOLD': 'gold',
                    'XAGUSD': 'silver',
                    'SILVER': 'silver',
                    'USOIL': 'oil',
                    'OIL': 'oil'
                }
                commodity = commodity_map.get(instrument, instrument.lower())
                urls = [
                    f"https://www.marketwatch.com/investing/commodity/{commodity}",
                    f"https://finance.yahoo.com/quote/{instrument}/"
                ]
            
            # Fetch data from each URL
            result_text = f"Market Analysis for {instrument}:\n\n"
            successful_fetches = 0
            
            async with aiohttp.ClientSession() as session:
                fetch_tasks = []
                for url in urls:
                    fetch_tasks.append(self._fetch_url_content(session, url))
                
                results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                
                for i, content in enumerate(results):
                    if isinstance(content, Exception):
                        logger.warning(f"Failed to fetch {urls[i]}: {str(content)}")
                        continue
                    
                    if content:
                        result_text += f"Source: {urls[i]}\n"
                        result_text += f"{content}\n\n"
                        successful_fetches += 1
            
            if successful_fetches == 0:
                logger.warning(f"No alternative sources available for {instrument}")
                return None
                
            return result_text
            
        except Exception as e:
            logger.error(f"Error getting alternative news: {str(e)}")
            logger.exception(e)
            return None
            
    async def _fetch_url_content(self, session, url):
        """Fetch content from a URL and extract relevant text"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            }
            
            timeout = aiohttp.ClientTimeout(total=10)
            async with session.get(url, headers=headers, timeout=timeout) as response:
                if response.status != 200:
                    return None
                
                html = await response.text()
                
                # Extract the most relevant content based on the URL
                if "yahoo.com" in url:
                    return self._extract_yahoo_content(html, url)
                elif "forexlive.com" in url:
                    return self._extract_forexlive_content(html)
                elif "fxstreet.com" in url:
                    return self._extract_fxstreet_content(html)
                elif "marketwatch.com" in url:
                    return self._extract_marketwatch_content(html)
                elif "coindesk.com" in url:
                    return self._extract_coindesk_content(html)
                else:
                    # Basic content extraction
                    return self._extract_basic_content(html)
                    
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            return None
            
    def _extract_yahoo_content(self, html, url):
        """Extract relevant content from Yahoo Finance"""
        try:
            # Extract price information
            price_match = re.search(r'data-symbol="[^"]+" data-field="regularMarketPrice" value="([^"]+)"', html)
            change_match = re.search(r'data-symbol="[^"]+" data-field="regularMarketChange" value="([^"]+)"', html)
            change_percent_match = re.search(r'data-symbol="[^"]+" data-field="regularMarketChangePercent" value="([^"]+)"', html)
            
            content = "Current Market Data:\n"
            
            if price_match:
                content += f"Price: {price_match.group(1)}\n"
            
            if change_match and change_percent_match:
                change = float(change_match.group(1))
                change_percent = float(change_percent_match.group(1))
                direction = "▲" if change > 0 else "▼"
                content += f"Change: {direction} {abs(change):.4f} ({abs(change_percent):.2f}%)\n"
            
            # Extract news headlines
            news_matches = re.findall(r'<h3 class="Mb\(5px\)">(.*?)</h3>', html)
            if news_matches:
                content += "\nRecent News:\n"
                for i, headline in enumerate(news_matches[:3]):
                    # Clean up HTML tags
                    headline = re.sub(r'<[^>]+>', '', headline).strip()
                    content += f"• {headline}\n"
            
            return content
        except Exception as e:
            logger.error(f"Error extracting Yahoo content: {str(e)}")
            return "Price and market data available at Yahoo Finance"
            
    def _extract_forexlive_content(self, html):
        """Extract relevant content from ForexLive"""
        try:
            # Extract article titles
            article_matches = re.findall(r'<h2 class="article-title">(.*?)</h2>', html)
            
            if not article_matches:
                return "Latest forex news and analysis available at ForexLive."
                
            content = "Recent Forex News:\n"
            for i, article in enumerate(article_matches[:3]):
                # Clean up HTML tags
                article = re.sub(r'<[^>]+>', '', article).strip()
                content += f"• {article}\n"
                
            return content
        except Exception as e:
            logger.error(f"Error extracting ForexLive content: {str(e)}")
            return "Latest forex news and analysis available at ForexLive."
    
    def _extract_fxstreet_content(self, html):
        """Extract relevant content from FXStreet"""
        try:
            # Extract price information
            price_match = re.search(r'<span class="price">(.*?)</span>', html)
            change_match = re.search(r'<span class="change-points[^"]*">(.*?)</span>', html)
            
            content = "Current Market Data:\n"
            
            if price_match:
                content += f"Price: {price_match.group(1).strip()}\n"
            
            if change_match:
                content += f"Change: {change_match.group(1).strip()}\n"
            
            # Extract technical indicators if available
            if '<div class="technical-indicators">' in html:
                content += "\nTechnical Indicators Summary:\n"
                if "bullish" in html.lower():
                    content += "• Overall trend appears bullish\n"
                elif "bearish" in html.lower():
                    content += "• Overall trend appears bearish\n"
                else:
                    content += "• Mixed technical signals\n"
            
            return content
        except Exception as e:
            logger.error(f"Error extracting FXStreet content: {str(e)}")
            return "Currency charts and analysis available at FXStreet."
    
    def _extract_marketwatch_content(self, html):
        """Extract relevant content from MarketWatch"""
        try:
            # Extract price information
            price_match = re.search(r'<bg-quote[^>]*>([^<]+)</bg-quote>', html)
            change_match = re.search(r'<bg-quote[^>]*field="change"[^>]*>([^<]+)</bg-quote>', html)
            change_percent_match = re.search(r'<bg-quote[^>]*field="percentchange"[^>]*>([^<]+)</bg-quote>', html)
            
            content = "Current Market Data:\n"
            
            if price_match:
                content += f"Price: {price_match.group(1).strip()}\n"
            
            if change_match and change_percent_match:
                content += f"Change: {change_match.group(1).strip()} ({change_percent_match.group(1).strip()})\n"
            
            # Extract news headlines
            news_matches = re.findall(r'<h3 class="article__headline">(.*?)</h3>', html)
            if news_matches:
                content += "\nRecent News:\n"
                for i, headline in enumerate(news_matches[:3]):
                    # Clean up HTML tags
                    headline = re.sub(r'<[^>]+>', '', headline).strip()
                    content += f"• {headline}\n"
            
            return content
        except Exception as e:
            logger.error(f"Error extracting MarketWatch content: {str(e)}")
            return "Market data and news available at MarketWatch."
    
    def _extract_coindesk_content(self, html):
        """Extract relevant content from CoinDesk"""
        try:
            # Extract price information
            price_match = re.search(r'<span class="price-large">([^<]+)</span>', html)
            change_match = re.search(r'<span class="percent-change-medium[^"]*">([^<]+)</span>', html)
            
            content = "Current Cryptocurrency Data:\n"
            
            if price_match:
                content += f"Price: {price_match.group(1).strip()}\n"
            
            if change_match:
                content += f"24h Change: {change_match.group(1).strip()}\n"
            
            # Extract news headlines
            news_matches = re.findall(r'<h4 class="heading">(.*?)</h4>', html)
            if news_matches:
                content += "\nRecent News:\n"
                for i, headline in enumerate(news_matches[:3]):
                    # Clean up HTML tags
                    headline = re.sub(r'<[^>]+>', '', headline).strip()
                    content += f"• {headline}\n"
            
            return content
        except Exception as e:
            logger.error(f"Error extracting CoinDesk content: {str(e)}")
            return "Cryptocurrency data and news available at CoinDesk."
    
    def _extract_basic_content(self, html):
        """Basic content extraction for other sites"""
        try:
            # Remove scripts, styles and other tags that don't contain useful content
            html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
            
            # Extract title
            title_match = re.search(r'<title[^>]*>(.*?)</title>', html)
            title = title_match.group(1).strip() if title_match else "Market Information"
            
            # Find paragraphs with relevant financial keywords
            financial_keywords = ['market', 'price', 'trend', 'analysis', 'forecast', 'technical', 'support', 'resistance']
            paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, flags=re.DOTALL)
            
            content = f"{title}\n\n"
            
            relevant_paragraphs = []
            for p in paragraphs:
                p_text = re.sub(r'<[^>]+>', '', p).strip()
                if p_text and any(keyword in p_text.lower() for keyword in financial_keywords):
                    relevant_paragraphs.append(p_text)
            
            if relevant_paragraphs:
                for i, p in enumerate(relevant_paragraphs[:3]):
                    content += f"{p}\n\n"
            else:
                content += "Visit the page for detailed market information and analysis."
            
            return content
        except Exception as e:
            logger.error(f"Error extracting basic content: {str(e)}")
            return "Market information available. Visit the source for details."

    async def _check_deepseek_connectivity(self) -> bool:
        """Check if the DeepSeek API is reachable"""
        logger.info("Checking DeepSeek API connectivity")
        try:
            # Try to connect to the new DeepSeek API endpoint
            deepseek_host = "api.deepseek.com"
            
            # Socket check (basic connectivity)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((deepseek_host, 443))
            sock.close()
            
            if result != 0:
                logger.warning(f"DeepSeek API socket connection failed with result: {result}")
                return False
                
            # If socket connects, try an HTTP HEAD request to verify API is responding
            # Create SSL context that doesn't verify certificates
            ssl_context = ssl.create_default_context()
            
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            # Use a shorter timeout for the HTTP check
            timeout = aiohttp.ClientTimeout(total=5)
            
            try:
                async with aiohttp.ClientSession(connector=connector) as session:
                    # Use the new domain
                    async with session.head(
                        "https://api.deepseek.com/v1/chat/completions",
                        timeout=timeout
                    ) as response:
                        status = response.status
                        logger.info(f"DeepSeek API HTTP check status: {status}")
                        
                        # Even if we get a 401 (Unauthorized) or 403 (Forbidden), 
                        # that means the API is accessible
                        if status in (200, 401, 403, 404):
                            logger.info("DeepSeek API is accessible")
                            return True
                            
                        logger.warning(f"DeepSeek API HTTP check failed with status: {status}")
                        return False
                        
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"DeepSeek API HTTP check failed: {str(e)}")
                return False
                
        except Exception as e:
            logger.warning(f"DeepSeek API connectivity check failed: {str(e)}")
            return False

    async def _try_deepseek_with_fallback(self, market_data: str, instrument: str) -> Dict[str, Any]:
        """Try to use DeepSeek API and fall back to manual formatting if needed"""
        # Skip early if no API key
        if not self.deepseek_api_key:
            logger.warning("No DeepSeek API key available, using manual formatting")
            return None
        
        try:
            # Use the existing _format_with_deepseek method which has the complete prompt
            market_type = self._guess_market_from_instrument(instrument)
            formatted_content = await self._format_with_deepseek(instrument, market_type, market_data)
            
            if formatted_content:
                return await self._get_deepseek_sentiment(market_data, instrument, formatted_content)
            else:
                logger.warning(f"DeepSeek formatting failed for {instrument}, using manual formatting")
                return None
            
        except Exception as e:
            logger.error(f"Error in DeepSeek processing: {str(e)}")
            logger.exception(e)
            return None
            
    async def _get_deepseek_sentiment(self, market_data: str, instrument: str, formatted_content: str = None) -> Dict[str, Any]:
        """Use DeepSeek to analyze market sentiment and return structured data"""
        try:
            # If formatted_content is not provided, try to get it
            if not formatted_content:
                formatted_content = await self._format_with_deepseek(instrument, 
                                                                  self._guess_market_from_instrument(instrument), 
                                                                  market_data)
            
            if not formatted_content:
                logger.warning(f"DeepSeek formatting failed for {instrument}, using manual formatting")
                return None
                
            # Extract sentiment information from the formatted content
            sentiment_score = 50  # Default neutral
            
            # Determine sentiment based on content analysis
            content_lower = formatted_content.lower()
            
            # More comprehensive sentiment detection
            bullish_terms = ['bullish', 'upward', 'positive', 'higher', 'upside', 'rise', 'gain', 'strong', 'breakout', 'rally']
            bearish_terms = ['bearish', 'downward', 'negative', 'lower', 'downside', 'fall', 'loss', 'weak', 'breakdown', 'decline']
            
            # Calculate sentiment based on term frequency and strength
            bullish_score = 0
            bearish_score = 0
            
            for term in bullish_terms:
                if term in content_lower:
                    # Weight certain terms more heavily
                    if term in ['bullish', 'positive', 'strong']:
                        bullish_score += 2
                    else:
                        bullish_score += 1
                        
            for term in bearish_terms:
                if term in content_lower:
                    # Weight certain terms more heavily
                    if term in ['bearish', 'negative', 'weak']:
                        bearish_score += 2
                    else:
                        bearish_score += 1
            
            # Determine overall sentiment
            if bullish_score > bearish_score:
                overall_sentiment = "bullish"
                # Calculate sentiment score (50-100 range for bullish)
                sentiment_strength = min(bullish_score, 10) / 10
                sentiment_score = 50 + (sentiment_strength * 50)
            elif bearish_score > bullish_score:
                overall_sentiment = "bearish" 
                # Calculate sentiment score (0-50 range for bearish)
                sentiment_strength = min(bearish_score, 10) / 10
                sentiment_score = 50 - (sentiment_strength * 50)
            else:
                overall_sentiment = "neutral"
                sentiment_score = 50
            
            # Round to nearest integer
            sentiment_score = round(sentiment_score)
            
            # Identify support and resistance from the content
            support_level = "See analysis for details"
            resistance_level = "See analysis for details"
            
            support_match = re.search(r'support[:\s]+([0-9.,]+)', content_lower)
            if support_match:
                support_level = support_match.group(1)
                
            resistance_match = re.search(r'resistance[:\s]+([0-9.,]+)', content_lower)
            if resistance_match:
                resistance_level = resistance_match.group(1)
                
            # Return structured data
            return {
                'overall_sentiment': overall_sentiment,
                'sentiment_score': sentiment_score / 100,
                'bullish_percentage': sentiment_score,
                'trend_strength': 'Strong' if abs(sentiment_score - 50) > 20 else 'Moderate' if abs(sentiment_score - 50) > 10 else 'Weak',
                'volatility': 'Moderate',
                'support_level': support_level,
                'resistance_level': resistance_level,
                'recommendation': 'Consider long positions' if sentiment_score > 60 else 'Watch for shorts' if sentiment_score < 40 else 'Wait for signals',
                'analysis': formatted_content,
                'source': 'deepseek'
            }
            
        except Exception as e:
            logger.error(f"Error analyzing DeepSeek sentiment: {str(e)}")
            logger.exception(e)
            return None

class TavilyClient:
    """A simple wrapper for the Tavily API that handles errors properly"""
    
    def __init__(self, api_key):
        """Initialize with the API key"""
        self.api_key = api_key
        self.base_url = "https://api.tavily.com"
        
    async def search(self, query, search_depth="basic", include_answer=True, 
                   include_images=False, max_results=5):
        """
        Search the Tavily API with the given query
        """
        if not self.api_key:
            logger.error("No Tavily API key provided")
            return None
            
        # Sanitize the API key
        api_key = self.api_key.strip() if self.api_key else ""
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "query": query,
            "search_depth": search_depth,
            "include_answer": include_answer,
            "include_images": include_images,
            "max_results": max_results
        }
        
        logger.info(f"Calling Tavily API with query: {query}")
        timeout = aiohttp.ClientTimeout(total=20)
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.base_url}/search", 
                    headers=headers,
                    json=payload,
                    timeout=timeout
                ) as response:
                    response_text = await response.text()
                    
                    if response.status == 200:
                        try:
                            return json.loads(response_text)
                        except json.JSONDecodeError:
                            logger.error(f"Invalid JSON response: {response_text[:200]}...")
                            return None
                    
                    logger.error(f"Tavily API error: {response.status}, {response_text[:200]}...")
                    return None
            except Exception as e:
                logger.error(f"Error in Tavily API call: {str(e)}")
                logger.exception(e)
                return None
