import os
import logging
import aiohttp
import json
import random
from typing import Dict, Any, Optional
import asyncio
import socket
import re
import ssl

logger = logging.getLogger(__name__)

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
        
        # Log DeepSeek API key status
        if self.deepseek_api_key:
            masked_key = self.deepseek_api_key[:6] + "..." + self.deepseek_api_key[-4:] if len(self.deepseek_api_key) > 10 else "***"
            logger.info(f"DeepSeek API key is configured: {masked_key}")
        else:
            logger.warning("No DeepSeek API key found")
            
    async def get_sentiment(self, instrument: str, market_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get sentiment for a given instrument. This function is used by the TelegramService.
        Returns a dictionary with sentiment data or formatted text.
        """
        logger.info(f"get_sentiment called for {instrument}")
        
        try:
            # Get sentiment text directly
            sentiment_text = await self.get_market_sentiment_text(instrument, market_type)
            
            # Extract sentiment values from the text if possible
            # Updated regex to better match the emoji format with more flexible whitespace handling
            bullish_match = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', sentiment_text)
            bearish_match = re.search(r'(?:Bearish:|🔴\s*Bearish:)\s*(\d+)\s*%', sentiment_text)
            
            # Log regex matches for debugging
            if bullish_match:
                logger.info(f"get_sentiment found bullish percentage for {instrument}: {bullish_match.group(1)}%")
            else:
                logger.warning(f"get_sentiment could not find bullish percentage in text for {instrument}")
                # Log a small snippet of the text for debugging
                text_snippet = sentiment_text[:200] + "..." if len(sentiment_text) > 200 else sentiment_text
                logger.warning(f"Text snippet: {text_snippet}")
                
            if bearish_match:
                logger.info(f"get_sentiment found bearish percentage for {instrument}: {bearish_match.group(1)}%")
            else:
                logger.warning(f"get_sentiment could not find bearish percentage in text for {instrument}")
                
            if bullish_match and bearish_match:
                bullish = int(bullish_match.group(1))
                bearish = int(bearish_match.group(1))
                neutral = 100 - (bullish + bearish)
                neutral = max(0, neutral)  # Ensure it's not negative
                
                # Calculate the sentiment score (-1.0 to 1.0)
                sentiment_score = (bullish - bearish) / 100
                
                # Determine trend strength based on how far from neutral
                trend_strength = 'Strong' if abs(bullish - 50) > 15 else 'Moderate' if abs(bullish - 50) > 5 else 'Weak'
                
                # Determine sentiment
                overall_sentiment = 'bullish' if bullish > bearish else 'bearish' if bearish > bullish else 'neutral'
                
                logger.info(f"Returning complete sentiment data for {instrument}: {overall_sentiment} (score: {sentiment_score:.2f})")
                
                return {
                    'bullish': bullish,
                    'bearish': bearish,
                    'neutral': neutral,
                    'sentiment_score': sentiment_score,
                    'technical_score': 'Based on market analysis',
                    'news_score': f"{bullish}% positive",
                    'social_score': f"{bearish}% negative",
                    'trend_strength': trend_strength,
                    'volatility': 'Moderate',
                    'volume': 'Normal',
                    'news_headlines': [],
                    'overall_sentiment': overall_sentiment,
                    'analysis': sentiment_text
                }
            else:
                # If we can't extract percentages, just return the text with default values
                logger.warning(f"Returning sentiment data without percentages for {instrument}")
                
                return {
                    'analysis': sentiment_text,
                    'sentiment_score': 0,
                    'technical_score': 'N/A',
                    'news_score': 'N/A',
                    'social_score': 'N/A',
                    'trend_strength': 'Moderate',
                    'volatility': 'Normal',
                    'volume': 'Normal',
                    'news_headlines': []
                }
            
        except Exception as e:
            logger.error(f"Error in get_sentiment: {str(e)}")
            logger.exception(e)
            # Return a basic analysis message
            return {
                'analysis': f"<b>🎯 {instrument} Market Analysis</b>\n\nSorry, there was an error analyzing the market sentiment. Please try again later.",
                'sentiment_score': 0,
                'technical_score': 'N/A',
                'news_score': 'N/A',
                'social_score': 'N/A',
                'trend_strength': 'Moderate',
                'volatility': 'Normal',
                'volume': 'Normal',
                'news_headlines': []
            }
    
    async def get_market_sentiment(self, instrument: str, market_type: Optional[str] = None) -> Optional[dict]:
        """
        Get market sentiment for a given instrument.
        
        Args:
            instrument: The instrument to analyze (e.g., 'EURUSD')
            market_type: Optional market type if known (e.g., 'forex', 'crypto')
            
        Returns:
            dict: A dictionary containing sentiment data, or a string with formatted analysis
        """
        try:
            logger.info(f"Getting market sentiment for {instrument} ({market_type or 'unknown'})")
            
            if market_type is None:
                # Determine market type from instrument if not provided
                market_type = self._guess_market_from_instrument(instrument)
            
            # Check if API keys are available
            if not self.tavily_api_key:
                logger.warning(f"Tavily API key not available for sentiment analysis of {instrument}, using mock data")
                return self._get_mock_sentiment_data(instrument)
                
            if not self.deepseek_api_key:
                logger.warning(f"DeepSeek API key not available for sentiment analysis of {instrument}, using mock data")
                return self._get_mock_sentiment_data(instrument)
            
            # Build search query based on market type
            search_query = self._build_search_query(instrument, market_type)
            
            # Get news data using Tavily
            news_content = await self._get_tavily_news(search_query)
            if not news_content:
                raise ValueError(f"Failed to retrieve news content for {instrument}")
            
            # Process and format the news content
            formatted_content = self._format_data_manually(news_content, instrument)
            
            # Use DeepSeek to analyze the sentiment
            final_analysis = await self._format_with_deepseek(instrument, market_type, formatted_content)
            if not final_analysis:
                raise ValueError(f"Failed to format DeepSeek analysis for {instrument}")
            
            logger.info(f"Looking for bullish percentage in response for {instrument}")
            
            # Try to extract sentiment values from the text
            # Updated regex to better match the emoji format with more flexible whitespace handling
            bullish_match = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', final_analysis)
            
            # Log the bullish match result for debugging
            if bullish_match:
                logger.info(f"Found bullish percentage for {instrument}: {bullish_match.group(1)}%")
            else:
                logger.warning(f"Could not find bullish percentage in response for {instrument}")
                logger.debug(f"Response snippet: {final_analysis[:300]}...")
            
            # If we couldn't find bullish percentage in the DeepSeek response, look for keywords
            # to determine sentiment direction and assign reasonable default values
            bullish_percentage = None
            bearish_percentage = None
            
            if bullish_match:
                # Normal path - extract directly from regex match
                bullish_percentage = int(bullish_match.group(1))
                bearish_percentage = 100 - bullish_percentage
                logger.info(f"Extracted sentiment values for {instrument}: Bullish {bullish_percentage}%, Bearish {bearish_percentage}%")
            else:
                logger.warning(f"Could not find bullish percentage in DeepSeek response for {instrument}. Using keyword analysis.")
                
                # Count sentiment-related keywords to determine bullish/bearish bias
                bullish_keywords = ['bullish', 'upward', 'positive', 'increase', 'higher', 'rise', 'growth', 'gain']
                bearish_keywords = ['bearish', 'downward', 'negative', 'decrease', 'lower', 'fall', 'decline', 'drop']
                
                # Count occurrences (case-insensitive)
                bullish_count = sum(final_analysis.lower().count(keyword) for keyword in bullish_keywords)
                bearish_count = sum(final_analysis.lower().count(keyword) for keyword in bearish_keywords)
                
                logger.info(f"Keyword analysis for {instrument}: Bullish terms {bullish_count}, Bearish terms {bearish_count}")
                
                # Determine sentiment based on keyword frequency
                if bullish_count > bearish_count:
                    # More bullish than bearish mentions
                    ratio = min(3, max(1.2, bullish_count / max(1, bearish_count)))
                    bullish_percentage = min(85, int(50 * ratio))
                elif bearish_count > bullish_count:
                    # More bearish than bullish mentions
                    ratio = min(3, max(1.2, bearish_count / max(1, bearish_count)))
                    bullish_percentage = max(15, int(50 / ratio))
                else:
                    # Neutral if equal counts or no mentions
                    bullish_percentage = 50
                
                bearish_percentage = 100 - bullish_percentage
                
                logger.info(f"Calculated sentiment from keywords for {instrument}: Bullish {bullish_percentage}%, Bearish {bearish_percentage}%")
                
                # Add the percentages to the analysis text for future reference
                final_analysis = final_analysis.replace("<b>Market Sentiment Breakdown:</b>", 
                    f"<b>Market Sentiment Breakdown:</b>\n🟢 Bullish: {bullish_percentage}%\n🔴 Bearish: {bearish_percentage}%\n⚪️ Neutral: 0%")
                
                # If we can't find the Market Sentiment Breakdown section, add it
                if "<b>Market Sentiment Breakdown:</b>" not in final_analysis:
                    logger.info(f"Adding Market Sentiment Breakdown section to response for {instrument}")
                    sentiment_section = f"""

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish_percentage}%
🔴 Bearish: {bearish_percentage}%
⚪️ Neutral: 0%

"""
                    # Insert after Market Direction section if it exists
                    if "<b>📈 Market Direction:</b>" in final_analysis:
                        parts = final_analysis.split("<b>📈 Market Direction:</b>", 1)
                        direction_section = parts[1].split("<b>", 1)
                        final_analysis = f"{parts[0]}<b>📈 Market Direction:</b>{direction_section[0]}{sentiment_section}<b>{direction_section[1]}"
                    else:
                        # Or add after the title
                        final_analysis += sentiment_section
            
            sentiment = 'bullish' if bullish_percentage > 50 else 'bearish' if bullish_percentage < 50 else 'neutral'
            
            # Create dictionary result with all data
            result = {
                'overall_sentiment': sentiment,
                'sentiment_score': bullish_percentage / 100,
                'bullish': bullish_percentage,
                'bearish': bearish_percentage,
                'neutral': 0,
                'bullish_percentage': bullish_percentage,
                'bearish_percentage': bearish_percentage,
                'technical_score': 'Based on market analysis',
                'news_score': f"{bullish_percentage}% positive",
                'social_score': f"{bearish_percentage}% negative",
                'trend_strength': 'Strong' if abs(bullish_percentage - 50) > 15 else 'Moderate' if abs(bullish_percentage - 50) > 5 else 'Weak',
                'volatility': 'Moderate',  # Default value as this is hard to extract reliably
                'volume': 'Normal',
                'support_level': 'Not available',  # Would need more sophisticated analysis
                'resistance_level': 'Not available',  # Would need more sophisticated analysis
                'recommendation': 'See analysis for details',
                'analysis': final_analysis,
                'news_headlines': []  # We don't have actual headlines from the API
            }
            
            logger.info(f"Returning sentiment data for {instrument}: {sentiment} (score: {bullish_percentage/100:.2f})")
            return result
                
        except Exception as e:
            logger.error(f"Error in market sentiment analysis: {str(e)}")
            logger.exception(e)
            raise ValueError(f"Failed to analyze market sentiment for {instrument}: {str(e)}")
    
    async def get_market_sentiment_text(self, instrument: str, market_type: Optional[str] = None) -> str:
        """
        Get market sentiment as formatted text for a given instrument.
        This is a wrapper around get_market_sentiment that ensures a string is returned.
        
        Args:
            instrument: The instrument to analyze (e.g., 'EURUSD')
            market_type: Optional market type if known (e.g., 'forex', 'crypto')
            
        Returns:
            str: Formatted sentiment analysis text
        """
        logger.info(f"Getting market sentiment text for {instrument} ({market_type or 'unknown'})")
        
        try:
            if market_type is None:
                # Determine market type from instrument if not provided
                market_type = self._guess_market_from_instrument(instrument)
                logger.info(f"Market type guessed as {market_type} for {instrument}")
            else:
                # Normalize to lowercase
                market_type = market_type.lower()
            
            # Get sentiment data as dictionary
            try:
                logger.info(f"Calling get_market_sentiment for {instrument} ({market_type})")
                sentiment_data = await self.get_market_sentiment(instrument, market_type)
                logger.info(f"Got sentiment data: {type(sentiment_data)}")
                
                # Log part of the analysis text for debugging
                if isinstance(sentiment_data, dict) and 'analysis' in sentiment_data:
                    analysis_snippet = sentiment_data['analysis'][:300] + "..." if len(sentiment_data['analysis']) > 300 else sentiment_data['analysis']
                    logger.info(f"Analysis snippet for {instrument}: {analysis_snippet}")
                else:
                    logger.warning(f"No 'analysis' field in sentiment data for {instrument}")
                
            except Exception as e:
                logger.error(f"Error in get_market_sentiment call: {str(e)}")
                logger.exception(e)
                # Create a default sentiment data structure in case of error
                sentiment_data = {
                    'overall_sentiment': 'neutral',
                    'bullish_percentage': 50,
                    'bearish_percentage': 50,
                    'trend_strength': 'Weak',
                    'volatility': 'Moderate',
                    'analysis': f"Error getting sentiment analysis for {instrument}. Please try again later."
                }
            
            # Convert sentiment_data to a string result
            result = None
            
            # Extract the analysis text if it exists
            if isinstance(sentiment_data, dict) and 'analysis' in sentiment_data:
                logger.info(f"Using 'analysis' field from sentiment data for {instrument}")
                result = sentiment_data['analysis']
            
            # If there's no analysis text, generate one from the sentiment data
            if not result and isinstance(sentiment_data, dict):
                logger.info(f"Generating formatted text from sentiment data for {instrument}")
                
                bullish = sentiment_data.get('bullish_percentage', 50)
                sentiment = sentiment_data.get('overall_sentiment', 'neutral')
                trend_strength = sentiment_data.get('trend_strength', 'Moderate')
                
                result = f"""<b>🎯 {instrument} Market Analysis</b>

<b>📈 Market Direction:</b>
The {instrument} is currently showing {sentiment} sentiment with {trend_strength.lower()} momentum. 
Overall sentiment is {bullish}% {sentiment}.

<b>📰 Latest News & Events:</b>
• Market sentiment driven by technical factors
• Regular trading activity observed
• No major market-moving events at this time

<b>⚠️ Risk Factors:</b>
• Market Volatility: {sentiment_data.get('volatility', 'Moderate')}
• Watch for unexpected news events
• Monitor broader market conditions

<b>💡 Conclusion:</b>
{sentiment_data.get('recommendation', 'Monitor price action and manage risk appropriately')}
"""
            
            # Fallback to a simple message if we still don't have a result
            if not result or not isinstance(result, str) or len(result.strip()) == 0:
                logger.warning(f"Using fallback sentiment message for {instrument}")
                result = f"""<b>🎯 {instrument} Market Analysis</b>

<b>📈 Market Direction:</b>
The {instrument} is currently showing neutral sentiment with moderate momentum.
Market conditions are stable at the moment.

<b>📰 Latest News & Events:</b>
• Standard market activity with no major movements
• Technical factors are the primary drivers
• No significant economic releases impacting the market

<b>⚠️ Risk Factors:</b>
• Market Volatility: Moderate
• Normal trading conditions apply
• Standard risk management recommended

<b>💡 Conclusion:</b>
Monitor price action and manage risk appropriately.
"""
            
            logger.info(f"Returning sentiment text for {instrument} (length: {len(result) if result else 0})")
            # Check if the result contains bullish/bearish percentages
            bullish_check = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', result)
            if bullish_check:
                logger.info(f"Final text contains bullish percentage: {bullish_check.group(1)}%")
            else:
                logger.warning(f"Final text does NOT contain bullish percentage pattern")
                
            return result if result else f"Sentiment analysis for {instrument}: Currently neutral"
            
        except Exception as e:
            logger.error(f"Uncaught error in get_market_sentiment_text: {str(e)}")
            logger.exception(e)
            # Return a valid response even in case of errors
            return f"""<b>🎯 {instrument} Market Analysis</b>

<b>⚠️ Service Note:</b>
The sentiment analysis service encountered an error while processing data for {instrument}.
Please try again later or choose a different instrument.

<b>Default Analysis:</b>
• Market conditions appear normal with mixed trading patterns
• No clear directional bias at this time
• Standard risk management practices recommended
"""
    
    def _format_data_manually(self, news_content: str, instrument: str) -> str:
        """Format market data manually for further processing"""
        try:
            logger.info(f"Manually formatting market data for {instrument}")
            
            # Extract key phrases and content from news_content
            formatted_text = f"# Market Data for {instrument}\n\n"
            
            # Add news content sections
            if "Market Analysis" in news_content:
                formatted_text += news_content
            else:
                # Extract key parts of the news content
                sections = news_content.split("\n\n")
                for section in sections:
                    if len(section.strip()) > 0:
                        formatted_text += section.strip() + "\n\n"
            
            # Make sure it's not too long
            if len(formatted_text) > 6000:
                formatted_text = formatted_text[:6000] + "...\n\n(content truncated for processing)"
                
            return formatted_text
            
        except Exception as e:
            logger.error(f"Error formatting market data manually: {str(e)}")
            return f"# Market Data for {instrument}\n\nError formatting data: {str(e)}\n\nRaw content: {news_content[:500]}..."
    
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
            logger.warning("No DeepSeek API key available, using manual formatting")
            return self._format_data_manually(market_data, instrument)
            
        logger.info(f"Formatting market data for {instrument} using DeepSeek API")
        
        try:
            # Check DeepSeek API connectivity first
            deepseek_available = await self._check_deepseek_connectivity()
            if not deepseek_available:
                logger.warning("DeepSeek API is unreachable, using manual formatting")
                return self._format_data_manually(market_data, instrument)
            
            # Prepare the API call
            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key.strip()}",
                "Content-Type": "application/json"
            }
            
            # Create prompt for sentiment analysis
            prompt = f"""Analyze the following market data for {instrument} and provide a structured sentiment analysis. 

**IMPORTANT**: You MUST include explicit percentages for bullish and bearish sentiment in EXACTLY the format shown below. The percentages MUST be integers that sum to 100. This format is required for further processing.

Market Data:
{market_data}

Your response MUST follow this EXACT format (keep the exact formatting with the <b> tags):

<b>🎯 {instrument} Market Analysis</b>

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: XX%
🔴 Bearish: YY%
⚪️ Neutral: 0%

<b>📈 Market Direction:</b>
[Current trend analysis and momentum]

<b>📰 Latest News & Events:</b>
• [Key point 1]
• [Key point 2]
• [Key point 3]

<b>⚠️ Risk Factors:</b>
• [Risk 1]
• [Risk 2]
• [Risk 3]

<b>💡 Conclusion:</b>
[Trading recommendation]

DO NOT omit any sections, especially the Market Sentiment Breakdown section with the percentage values. The bullish and bearish percentages MUST be clearly indicated as integers."""

            # Make the API call
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.deepseek_url,
                    headers=headers,
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": "You are a professional market analyst specializing in quantitative sentiment analysis."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.3,
                        "max_tokens": 1024
                    }
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        response_content = data['choices'][0]['message']['content']
                        logger.info(f"DeepSeek raw response for {instrument}: {response_content[:200]}...")
                        
                        # Check if the response contains the expected Market Sentiment section
                        if "Market Sentiment" in response_content and "Bullish:" in response_content:
                            logger.info(f"DeepSeek response contains Market Sentiment section")
                        else:
                            logger.warning(f"DeepSeek response does not contain expected Market Sentiment section")
                            logger.info(f"Let's add default sentiment section")
                            
                            # Add a default sentiment section if missing
                            if "<b>🎯" in response_content:
                                parts = response_content.split("<b>🎯", 1)
                                sentiment_section = f"""<b>🎯{parts[1].split("<b>", 1)[0]}
<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 50%
🔴 Bearish: 50%
⚪️ Neutral: 0%

"""
                                response_content = f"{parts[0]}{sentiment_section}<b>{parts[1].split('<b>', 1)[1]}"
                            
                        return response_content
                    else:
                        logger.error(f"DeepSeek API error: {response.status}")
                        return None
                    
        except Exception as e:
            logger.error(f"Error in DeepSeek formatting: {str(e)}")
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
        """Generate mock sentiment data for an instrument"""
        logger.warning(f"Using mock sentiment data for {instrument} because API keys are not available or valid")
        
        # Determine sentiment randomly but biased by instrument type
        if instrument.startswith(('BTC', 'ETH')):
            is_bullish = random.random() > 0.3  # 70% chance of bullish for crypto
        elif instrument.startswith(('XAU', 'GOLD')):
            is_bullish = random.random() > 0.4  # 60% chance of bullish for gold
        else:
            is_bullish = random.random() > 0.5  # 50% chance for other instruments
        
        # Generate random percentage values
        bullish_percentage = random.randint(60, 85) if is_bullish else random.randint(15, 40)
        bearish_percentage = 100 - bullish_percentage
        neutral_percentage = 0  # We don't use neutral in this mockup
        
        # Calculate sentiment score from -1.0 to 1.0
        sentiment_score = (bullish_percentage - bearish_percentage) / 100
        
        # Generate random news headlines
        headlines = []
        if is_bullish:
            headlines = [
                f"Positive economic outlook boosts {instrument}",
                f"Institutional investors increase {instrument} positions",
                f"Technical indicators suggest upward momentum for {instrument}"
            ]
        else:
            headlines = [
                f"Economic concerns weigh on {instrument}",
                f"Profit taking leads to {instrument} pressure",
                f"Technical resistance level limits {instrument} upside"
            ]
        
        # Generate mock analysis text
        analysis_text = f"""<b>🎯 {instrument} Market Analysis</b>

<b>Market Sentiment:</b>
Bullish: {bullish_percentage}%
Bearish: {bearish_percentage}%
Neutral: 0%

<b>📈 Market Direction:</b>
The {instrument} is currently showing a {"bullish" if is_bullish else "bearish"} trend. Technical indicators suggest {"upward momentum" if is_bullish else "downward pressure"} in the near term.

<b>📰 Latest News & Events:</b>
• {"Positive economic data supporting price" if is_bullish else "Recent economic indicators adding pressure"}
• {"Increased buying interest from institutional investors" if is_bullish else "Technical resistance levels limiting upside potential"}
• Regular market fluctuations in line with broader market conditions

<b>⚠️ Risk Factors:</b>
• Market Volatility: {random.choice(['High', 'Moderate', 'Low'])}
• Watch for unexpected news events
• Monitor broader market conditions

<b>💡 Conclusion:</b>
Based on current market conditions, the outlook for {instrument} appears {"positive" if is_bullish else "cautious"}. Traders should consider {"buy opportunities on dips" if is_bullish else "sell positions on rallies"} while maintaining proper risk management.

<i>Note: This is mock data for demonstration purposes only. Real trading decisions should be based on comprehensive analysis.</i>"""
        
        # Determine strength based on how far from neutral (50%)
        trend_strength = 'Strong' if abs(bullish_percentage - 50) > 15 else 'Moderate' if abs(bullish_percentage - 50) > 5 else 'Weak'
        
        # Create dictionary result with all data
        return {
            'overall_sentiment': 'bullish' if is_bullish else 'bearish',
            'sentiment_score': sentiment_score,
            'bullish': bullish_percentage,
            'bearish': bearish_percentage,
            'neutral': neutral_percentage,
            'bullish_percentage': bullish_percentage,
            'bearish_percentage': bearish_percentage,
            'technical_score': f"{random.randint(60, 80)}% {'bullish' if is_bullish else 'bearish'}",
            'news_score': f"{random.randint(55, 75)}% {'positive' if is_bullish else 'negative'}",
            'social_score': f"{random.randint(50, 70)}% {'bullish' if is_bullish else 'bearish'}",
            'trend_strength': trend_strength,
            'volatility': random.choice(['High', 'Moderate', 'Low']),
            'volume': random.choice(['Above Average', 'Normal', 'Below Average']),
            'support_level': 'Not available',
            'resistance_level': 'Not available',
            'recommendation': f"{'Consider long positions with appropriate risk management.' if is_bullish else 'Consider short positions with appropriate risk management.'}",
            'analysis': analysis_text,
            'news_headlines': headlines,
            'source': 'mock_data'
        }
    
    def _get_fallback_sentiment(self, instrument: str) -> Dict[str, Any]:
        """Generate fallback sentiment data when APIs fail"""
        logger.warning(f"Using fallback sentiment data for {instrument} due to API errors")
        
        # Default neutral headlines
        headlines = [
            f"Market awaits clear direction for {instrument}",
            "Economic data shows mixed signals",
            "Traders taking cautious approach"
        ]
        
        # Create a neutral sentiment analysis
        analysis_text = f"""<b>🎯 {instrument} Market Analysis</b>

<b>Market Sentiment:</b>
Bullish: 50%
Bearish: 50%
Neutral: 0%

<b>📈 Market Direction:</b>
The {instrument} is currently showing a neutral trend with balanced buy and sell interest.

<b>📰 Latest News & Events:</b>
• Standard market activity with no major developments
• Technical factors are the primary drivers
• Normal trading conditions observed

<b>⚠️ Risk Factors:</b>
• Market Volatility: Moderate
• Standard market risks apply
• Always use proper risk management

<b>💡 Conclusion:</b>
The market sentiment for {instrument} is currently neutral with balanced indicators.
Monitor price action and wait for clearer signals before taking positions.

<i>Note: This is fallback data due to API issues. Please try again later for updated analysis.</i>"""
        
        # Return a balanced neutral sentiment
        return {
            'overall_sentiment': 'neutral',
            'sentiment_score': 0,
            'bullish': 50,
            'bearish': 50,
            'neutral': 0,
            'bullish_percentage': 50,
            'bearish_percentage': 50,
            'technical_score': 'N/A',
            'news_score': 'N/A',
            'social_score': 'N/A',
            'trend_strength': 'Weak',
            'volatility': 'Moderate',
            'volume': 'Normal',
            'support_level': 'Not available',
            'resistance_level': 'Not available',
            'recommendation': 'Wait for clearer signals before taking positions.',
            'analysis': analysis_text,
            'news_headlines': headlines,
            'source': 'fallback_data'
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

    async def _try_deepseek_with_fallback(self, market_data: str, instrument: str) -> str:
        """Try to use DeepSeek API and fall back to manual formatting if needed"""
        # Skip early if no API key
        if not self.deepseek_api_key:
            logger.warning("No DeepSeek API key available, using manual formatting")
            return self._format_data_manually(market_data, instrument)
        
        try:
            # Use the existing _format_with_deepseek method which has the complete prompt
            market_type = self._guess_market_from_instrument(instrument)
            formatted_content = await self._format_with_deepseek(instrument, market_type, market_data)
            
            if formatted_content:
                return await self._get_deepseek_sentiment(market_data, instrument, formatted_content)
            else:
                logger.warning(f"DeepSeek formatting failed for {instrument}, using manual formatting")
                return self._format_data_manually(market_data, instrument)
            
        except Exception as e:
            logger.error(f"Error in DeepSeek processing: {str(e)}")
            logger.exception(e)
            return self._format_data_manually(market_data, instrument)
            
    async def _get_deepseek_sentiment(self, market_data: str, instrument: str, formatted_content: str = None) -> str:
        """Use DeepSeek to analyze market sentiment and return formatted analysis"""
        try:
            # If formatted_content is not provided, try to get it
            if not formatted_content:
                formatted_content = await self._format_with_deepseek(instrument, 
                                                                  self._guess_market_from_instrument(instrument), 
                                                                  market_data)
            
            if not formatted_content:
                logger.warning(f"DeepSeek formatting failed for {instrument}, using manual formatting")
                return self._format_data_manually(market_data, instrument)
            
            # Return the formatted content directly
            return formatted_content
            
        except Exception as e:
            logger.error(f"Error analyzing DeepSeek sentiment: {str(e)}")
            logger.exception(e)
            return self._format_data_manually(market_data, instrument)

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
