import os
import logging
import aiohttp
import json
import random
import time
from typing import Dict, Any, Optional
import asyncio
import socket
import re
import ssl
import sys

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
            
        # Initialize sentiment cache
        self.sentiment_cache = {}
        self.cache_expiry = 20 * 60  # Cache items expire after 20 minutes
            
    def _build_search_query(self, instrument: str, market_type: str) -> str:
        """
        Build a search query for the given instrument and market type.
        
        Args:
            instrument: The instrument to analyze (e.g., 'EURUSD')
            market_type: Market type (e.g., 'forex', 'crypto')
            
        Returns:
            str: A formatted search query for news and market data
        """
        # Optimalisatie: verwijder logging om tijd te besparen
        # logger.info(f"Building search query for {instrument} ({market_type})")
        
        # Optimalisatie: maak de zoekopdracht veel korter en gerichter voor snellere resultaten
        base_query = f"{instrument} {market_type} sentiment"
        
        # Voeg specifieke context toe op basis van markttype
        if market_type == 'forex':
            currency_pair = instrument[:3] + "/" + instrument[3:] if len(instrument) == 6 else instrument
            base_query = f"{currency_pair} analysis current"
        elif market_type == 'crypto':
            crypto_name = instrument.replace('USD', '') if instrument.endswith('USD') else instrument
            base_query = f"{crypto_name} price sentiment"
        elif market_type == 'commodities':
            commodity_name = {
                'XAUUSD': 'gold',
                'XAGUSD': 'silver',
                'USOIL': 'crude oil',
                'BRENT': 'brent oil'
            }.get(instrument, instrument)
            base_query = f"{commodity_name} price sentiment"
        elif market_type == 'indices':
            index_name = {
                'US30': 'Dow Jones',
                'US500': 'S&P 500',
                'US100': 'Nasdaq',
                'GER30': 'DAX',
                'UK100': 'FTSE 100'
            }.get(instrument, instrument)
            base_query = f"{index_name} market sentiment"
        
        # Voeg huidige datum toe om de nieuwste info te krijgen
        base_query += " latest today"
        
        # Optimalisatie: geen logging van eindresultaat
        return base_query
            
    async def get_sentiment(self, instrument: str, market_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get sentiment for a given instrument. This function is used by the TelegramService.
        Returns a dictionary with sentiment data or formatted text.
        """
        logger.info(f"get_sentiment called for {instrument}")
        
        try:
            # Get sentiment text directly
            logger.info(f"Calling get_market_sentiment_text for {instrument}...")
            sentiment_text = await self.get_market_sentiment_text(instrument, market_type)
            logger.info(f"Received sentiment_text for {instrument}, length: {len(sentiment_text) if sentiment_text else 0}")
            
            # Make sure we have appropriate sentiment format. If not, use default.
            if not "<b>🎯" in sentiment_text or "Market Sentiment Analysis</b>" not in sentiment_text:
                logger.warning(f"Sentiment text doesn't have proper title format, using default format")
                sentiment_text = self._get_default_sentiment_text(instrument)
            
            # Check for required sections before continuing
            required_sections = [
                "<b>Overall Sentiment:</b>",
                "<b>Market Sentiment Breakdown:</b>",
                "🟢 Bullish:",
                "🔴 Bearish:",
                "<b>📊 Market Sentiment Analysis:</b>",
                "<b>📰 Key Sentiment Drivers:</b>",
                "<b>📅 Important Events & News:</b>"
            ]
            
            for section in required_sections:
                if section not in sentiment_text:
                    logger.warning(f"Missing required section: {section}, using default format")
                    sentiment_text = self._get_default_sentiment_text(instrument)
                    break
            
            # Check for disallowed sections before continuing
            disallowed_sections = [
                "Market Direction:",
                "Technical Outlook:",
                "Support & Resistance:",
                "Conclusion:"
            ]
            
            for section in disallowed_sections:
                if section in sentiment_text:
                    logger.warning(f"Found disallowed section: {section}, using default format")
                    sentiment_text = self._get_default_sentiment_text(instrument)
                    break
            
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
                text_snippet = sentiment_text[:300] + "..." if len(sentiment_text) > 300 else sentiment_text
                logger.warning(f"Text snippet: {text_snippet}")
                
                # If we can't extract the percentages, use the default format
                sentiment_text = self._get_default_sentiment_text(instrument)
                # Try again with the default format
                bullish_match = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', sentiment_text)
                bearish_match = re.search(r'(?:Bearish:|🔴\s*Bearish:)\s*(\d+)\s*%', sentiment_text)
                
            if bearish_match:
                logger.info(f"get_sentiment found bearish percentage for {instrument}: {bearish_match.group(1)}%")
            else:
                logger.warning(f"get_sentiment could not find bearish percentage in text for {instrument}")
                # If we can't extract the percentages, use the default format
                sentiment_text = self._get_default_sentiment_text(instrument)
                # Try again with the default format
                bullish_match = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', sentiment_text)
                bearish_match = re.search(r'(?:Bearish:|🔴\s*Bearish:)\s*(\d+)\s*%', sentiment_text)
                
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
                
                result = {
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
                
                # Log the final result dictionary
                logger.info(f"Final sentiment result for {instrument}: {overall_sentiment}, score: {sentiment_score:.2f}, bullish: {bullish}%, bearish: {bearish}%, neutral: {neutral}%")
                return result
            else:
                # If we can't extract percentages, use default values from default text
                logger.warning(f"Extracting percentages failed even with default text, using hardcoded defaults")
                
                result = {
                    'bullish': 50,
                    'bearish': 50,
                    'neutral': 0,
                    'sentiment_score': 0,
                    'technical_score': 'Based on market analysis',
                    'news_score': '50% positive',
                    'social_score': '50% negative',
                    'trend_strength': 'Moderate',
                    'volatility': 'Moderate',
                    'volume': 'Normal',
                    'news_headlines': [],
                    'overall_sentiment': 'neutral',
                    'analysis': self._get_default_sentiment_text(instrument)
                }
                
                # Log the fallback result
                logger.warning(f"Using hardcoded defaults for {instrument}: neutral, score: 0.00")
                return result
            
        except Exception as e:
            logger.error(f"Error in get_sentiment: {str(e)}")
            logger.exception(e)
            # Return a basic analysis message
            error_result = {
                'bullish': 50,
                'bearish': 50,
                'neutral': 0,
                'sentiment_score': 0,
                'technical_score': 'N/A',
                'news_score': 'N/A',
                'social_score': 'N/A',
                'trend_strength': 'Moderate',
                'volatility': 'Normal',
                'volume': 'Normal',
                'news_headlines': [],
                'overall_sentiment': 'neutral',
                'analysis': self._get_default_sentiment_text(instrument)
            }
            logger.error(f"Returning error result for {instrument} due to exception")
            return error_result
    
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
            
            # Build search query based on market type
            search_query = self._build_search_query(instrument, market_type)
            logger.info(f"Built search query: {search_query}")
            
            # Optimalisatie: gebruik een kortere zoekterm voor snellere resultaten
            simplified_query = f"{instrument} market analysis sentiment"
            
            # Get news data using Tavily
            news_content = await self._get_tavily_news(simplified_query)
            if not news_content:
                logger.error(f"Failed to retrieve Tavily news content for {instrument}")
                # Snelle terugval op standaardantwoord
                return self._create_quick_sentiment_response(instrument)
            
            # Optimalisatie: sla complexe formatting over
            # Process and format the news content
            formatted_content = self._format_data_manually(news_content, instrument)
            
            # Use DeepSeek to analyze the sentiment
            final_analysis = await self._format_with_deepseek(instrument, market_type, formatted_content)
            if not final_analysis:
                logger.error(f"Failed to format DeepSeek analysis for {instrument}")
                # Snelle terugval op standaardantwoord
                return self._create_quick_sentiment_response(instrument)
            
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
                
                # Try to extract bearish and neutral directly
                bearish_match = re.search(r'(?:Bearish:|🔴\s*Bearish:)\s*(\d+)\s*%', final_analysis)
                neutral_match = re.search(r'(?:Neutral:|⚪️\s*Neutral:)\s*(\d+)\s*%', final_analysis)
                
                if bearish_match:
                    bearish_percentage = int(bearish_match.group(1))
                    logger.info(f"Found bearish percentage for {instrument}: {bearish_percentage}%")
                else:
                    bearish_percentage = 100 - bullish_percentage
                    logger.warning(f"Could not find bearish percentage, using complement: {bearish_percentage}%")
                
                if neutral_match:
                    neutral_percentage = int(neutral_match.group(1))
                    logger.info(f"Found neutral percentage for {instrument}: {neutral_percentage}%")
                    
                    # Adjust percentages to ensure they sum to 100%
                    total = bullish_percentage + bearish_percentage + neutral_percentage
                    if total != 100:
                        logger.warning(f"Sentiment percentages sum to {total}, adjusting...")
                        # Scale proportionally
                        bullish_percentage = int((bullish_percentage / total) * 100)
                        bearish_percentage = int((bearish_percentage / total) * 100)
                        neutral_percentage = 100 - bullish_percentage - bearish_percentage
                else:
                    neutral_percentage = 0
                    logger.warning(f"Could not find neutral percentage, using default: {neutral_percentage}%")
                
                logger.info(f"Extracted sentiment values for {instrument}: Bullish {bullish_percentage}%, Bearish {bearish_percentage}%, Neutral {neutral_percentage}%")
                
                # Determine sentiment
                overall_sentiment = 'bullish' if bullish_percentage > bearish_percentage else 'bearish' if bearish_percentage > bullish_percentage else 'neutral'
                
                # Calculate the sentiment score (-1.0 to 1.0)
                sentiment_score = (bullish_percentage - bearish_percentage) / 100
                
                # Determine trend strength based on how far from neutral
                trend_strength = 'Strong' if abs(bullish_percentage - 50) > 15 else 'Moderate' if abs(bullish_percentage - 50) > 5 else 'Weak'
                
                logger.info(f"Returning complete sentiment data for {instrument}: {overall_sentiment} (score: {sentiment_score:.2f})")
                
                return {
                    'bullish': bullish_percentage,
                    'bearish': bearish_percentage,
                    'neutral': neutral_percentage,
                    'sentiment_score': sentiment_score,
                    'technical_score': 'Based on market analysis',
                    'news_score': f"{bullish_percentage}% positive",
                    'social_score': f"{bearish_percentage}% negative",
                    'trend_strength': trend_strength,
                    'volatility': 'Moderate',
                    'volume': 'Normal',
                    'news_headlines': [],
                    'overall_sentiment': overall_sentiment,
                    'analysis': final_analysis
                }
            else:
                logger.warning(f"Could not find bullish percentage in DeepSeek response for {instrument}. Using keyword analysis.")
                # Fallback: Calculate sentiment through keyword analysis
                bullish_keywords = ['bullish', 'optimistic', 'uptrend', 'positive', 'strong', 'upside', 'buy', 'growth']
                bearish_keywords = ['bearish', 'pessimistic', 'downtrend', 'negative', 'weak', 'downside', 'sell', 'decline']
                
                bullish_count = sum(final_analysis.lower().count(keyword) for keyword in bullish_keywords)
                bearish_count = sum(final_analysis.lower().count(keyword) for keyword in bearish_keywords)
                
                total_count = bullish_count + bearish_count
                if total_count > 0:
                    bullish_percentage = int((bullish_count / total_count) * 100)
                    bearish_percentage = 100 - bullish_percentage
                    neutral_percentage = 0
                else:
                    bullish_percentage = 50
                    bearish_percentage = 50
                    neutral_percentage = 0
                
                # Calculate sentiment score same as above
                sentiment_score = (bullish_percentage - bearish_percentage) / 100
                overall_sentiment = 'bullish' if bullish_percentage > bearish_percentage else 'bearish' if bearish_percentage > bullish_percentage else 'neutral'
                trend_strength = 'Strong' if abs(bullish_percentage - 50) > 15 else 'Moderate' if abs(bullish_percentage - 50) > 5 else 'Weak'
                
                logger.warning(f"Using keyword analysis for {instrument}: Bullish {bullish_percentage}%, Bearish {bearish_percentage}%, Sentiment: {overall_sentiment}")
                
                return {
                    'bullish': bullish_percentage,
                    'bearish': bearish_percentage,
                    'neutral': neutral_percentage,
                    'sentiment_score': sentiment_score,
                    'technical_score': 'Based on keyword analysis',
                    'news_score': f"{bullish_percentage}% positive",
                    'social_score': f"{bearish_percentage}% negative",
                    'trend_strength': trend_strength,
                    'volatility': 'Moderate',
                    'volume': 'Normal',
                    'news_headlines': [],
                    'overall_sentiment': overall_sentiment,
                    'analysis': final_analysis
                }
            
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
                # Create a default sentiment data structure with proper percentages for parsing
                sentiment_data = {
                    'overall_sentiment': 'neutral',
                    'bullish': 50,
                    'bearish': 50,
                    'neutral': 0,
                    'trend_strength': 'Weak',
                    'volatility': 'Moderate',
                    'analysis': f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> Neutral ➡️

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 50%
🔴 Bearish: 50%
⚪️ Neutral: 0%

<b>📰 Key Sentiment Drivers:</b>
• Market conditions appear normal with mixed signals
• No clear directional bias at this time
• Standard market activity observed

<b>📊 Market Mood:</b>
{instrument} is currently showing mixed signals with no clear sentiment bias.

<b>📅 Important Events & News:</b>
• Normal market activity with no major catalysts
• No significant economic releases impacting the market
• General news and global trends affecting sentiment

<b>🔮 Sentiment Outlook:</b>
The market shows balanced sentiment for {instrument} with no strong directional bias at this time.

<i>Error details: {str(e)[:100]}</i>
"""
                }
                logger.info(f"Created fallback sentiment data with proper format for {instrument}")
            
            # Convert sentiment_data to a string result
            result = None
            
            # Extract the analysis text if it exists
            if isinstance(sentiment_data, dict) and 'analysis' in sentiment_data:
                logger.info(f"Using 'analysis' field from sentiment data for {instrument}")
                result = sentiment_data['analysis']
                
                # Verify that the result contains proper sentiment percentages
                bullish_match = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', result)
                if not bullish_match:
                    logger.warning(f"Analysis field does not contain proper Bullish percentage format for {instrument}")
                    
                    # Check if we have bullish percentage in sentiment_data
                    bullish_percentage = sentiment_data.get('bullish', 50)
                    bearish_percentage = sentiment_data.get('bearish', 50)
                    
                    # Try to find where to insert the sentiment breakdown section
                    if "<b>Market Sentiment Breakdown:</b>" in result:
                        # Replace the entire section
                        pattern = r'<b>Market Sentiment Breakdown:</b>.*?(?=<b>)'
                        replacement = f"""<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish_percentage}%
🔴 Bearish: {bearish_percentage}%
⚪️ Neutral: 0%

"""
                        result = re.sub(pattern, replacement, result, flags=re.DOTALL)
                        logger.info(f"Replaced Market Sentiment section with percentages from sentiment_data")
                    else:
                        # Try to insert after the first section
                        pattern = r'(<b>🎯.*?</b>\s*\n\s*\n)'
                        replacement = f"""$1<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish_percentage}%
🔴 Bearish: {bearish_percentage}%
⚪️ Neutral: 0%

"""
                        new_result = re.sub(pattern, replacement, result, flags=re.DOTALL)
                        
                        if new_result != result:
                            result = new_result
                            logger.info(f"Inserted Market Sentiment section after title")
                        else:
                            logger.warning(f"Could not find place to insert Market Sentiment section")
            
            # If there's no analysis text, generate one from the sentiment data
            if not result and isinstance(sentiment_data, dict):
                logger.info(f"Generating formatted text from sentiment data for {instrument}")
                
                bullish = sentiment_data.get('bullish', 50)
                bearish = sentiment_data.get('bearish', 50)
                neutral = sentiment_data.get('neutral', 0)
                
                sentiment = sentiment_data.get('overall_sentiment', 'neutral')
                trend_strength = sentiment_data.get('trend_strength', 'Moderate')
                
                result = f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> {sentiment.capitalize()} {'📈' if sentiment == 'bullish' else '📉' if sentiment == 'bearish' else '➡️'}

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: {bullish}%
🔴 Bearish: {bearish}%
⚪️ Neutral: {neutral}%

<b>📰 Key Sentiment Drivers:</b>
• Market sentiment driven by technical and fundamental factors
• Recent market developments shaping trader perception
• Evolving economic conditions influencing outlook

<b>📊 Market Mood:</b>
The {instrument} is currently showing {sentiment} sentiment with {trend_strength.lower()} momentum.

<b>📅 Important Events & News:</b>
• Regular trading activity observed
• No major market-moving events at this time
• Standard economic influences in effect

<b>🔮 Sentiment Outlook:</b>
{sentiment_data.get('recommendation', 'Monitor market conditions and manage risk appropriately.')}
"""
                logger.info(f"Generated complete formatted text with percentages for {instrument}")
            
            # Fallback to a simple message if we still don't have a result
            if not result or not isinstance(result, str) or len(result.strip()) == 0:
                logger.warning(f"Using complete fallback sentiment message for {instrument}")
                result = f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> Neutral ➡️

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 50%
🔴 Bearish: 50%
⚪️ Neutral: 0%

<b>📰 Key Sentiment Drivers:</b>
• Regular market activity with no major catalysts
• General economic factors influencing market mood
• No significant news events driving sentiment

<b>📊 Market Mood:</b>
{instrument} is trading with a balanced sentiment pattern with no clear sentiment bias.

<b>📅 Important Events & News:</b>
• Standard market updates with limited impact
• No major economic releases affecting sentiment
• Regular market fluctuations within expected ranges

<b>🔮 Sentiment Outlook:</b>
Current sentiment for {instrument} is neutral with balanced perspectives from market participants.
"""
            
            logger.info(f"Returning sentiment text for {instrument} (length: {len(result) if result else 0})")
            
            # Final check - verify the result has the correct format for bullish/bearish percentages
            bullish_check = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', result)
            if bullish_check:
                logger.info(f"Final text contains bullish percentage: {bullish_check.group(1)}%")
            else:
                logger.warning(f"Final text does NOT contain bullish percentage pattern, fixing format")
                
                # Add proper sentiment breakdown section if missing
                pattern = r'(<b>🎯.*?</b>\s*\n\s*\n)'
                replacement = f"""$1<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 50%
🔴 Bearish: 50%
⚪️ Neutral: 0%

"""
                new_result = re.sub(pattern, replacement, result, flags=re.DOTALL)
                
                if new_result != result:
                    result = new_result
                    logger.info(f"Fixed: inserted Market Sentiment section with percentages")
            
            # Ensure the result has the expected sections with emojis
            expected_sections = [
                ('<b>📰 Key Sentiment Drivers:</b>', '<b>Key Sentiment Drivers:</b>'),
                ('<b>📊 Market Mood:</b>', '<b>Market Mood:</b>'),
                ('<b>📅 Important Events & News:</b>', '<b>Important Events & News:</b>'),
                ('<b>🔮 Sentiment Outlook:</b>', '<b>Sentiment Outlook:</b>')
            ]
            
            for emoji_section, plain_section in expected_sections:
                if emoji_section not in result and plain_section in result:
                    logger.info(f"Converting {plain_section} to {emoji_section}")
                    result = result.replace(plain_section, emoji_section)
            
            return result if result else f"Sentiment analysis for {instrument}: Currently neutral"
            
        except Exception as e:
            logger.error(f"Uncaught error in get_market_sentiment_text: {str(e)}")
            logger.exception(e)
            # Return a valid response even in case of errors, with correct percentages format
            return f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> Neutral ➡️

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 50%
🔴 Bearish: 50%
⚪️ Neutral: 0%

<b>⚠️ Service Note:</b>
The sentiment analysis service encountered an error while processing data for {instrument}.
Please try again later or choose a different instrument.

<b>📰 Key Sentiment Drivers:</b>
• Market conditions appear normal with mixed signals
• No clear directional bias at this time
• Standard risk factors in the current market

<b>📊 Market Mood:</b>
Market mood is currently balanced with no strong signals.

<b>📅 Important Events & News:</b>
• No major market-moving events detected
• Regular market activity continues
• Standard economic factors in play

<b>🔮 Sentiment Outlook:</b>
Standard risk management practices recommended until clearer sentiment emerges.
"""

    def _format_data_manually(self, news_content: str, instrument: str) -> str:
        """Format market data manually for further processing"""
        try:
            # Skip logging to save time
            # logger.info(f"Manually formatting market data for {instrument}")
            
            # Extract key phrases and content from news_content
            formatted_text = f"# Market Sentiment Data for {instrument}\n\n"
            
            # Add news content sections
            if "Market Sentiment Analysis" in news_content or "Market Analysis" in news_content:
                formatted_text += news_content
            else:
                # Optimalisatie: verwerk niet teveel content, neem alleen de eerste paar secties
                sections = news_content.split("\n\n")
                for section in sections[:5]:  # Beperk tot eerste 5 secties voor snelheid
                    if len(section.strip()) > 0:
                        formatted_text += section.strip() + "\n\n"
            
            # Make sure it's not too long
            # Verkort maximale lengte voor snellere verwerking
            if len(formatted_text) > 4000:  # Was 6000
                formatted_text = formatted_text[:4000] + "...\n\n(content truncated for processing)"
                
            return formatted_text
            
        except Exception as e:
            # Geef minimale foutmelding terug om tijd te besparen
            return f"# Market Sentiment Data for {instrument}\n\nBrief market analysis for {instrument}"
    
    async def _get_tavily_news(self, search_query: str) -> str:
        """Use Tavily API to get latest news and market data"""
        # Check if API key is configured
        if not self.tavily_api_key:
            return None
            
        # Use our Tavily client to make the API call
        try:
            response = await self.tavily_client.search(
                query=search_query,
                search_depth="basic",
                include_answer=True,
                max_results=2  # Verlaagd van 3 naar 2 voor nog snellere verwerking
            )
            
            if response:
                return self._process_tavily_response(json.dumps(response))
            else:
                return None
                
        except Exception as e:
            logger.error(f"Error calling Tavily API: {str(e)}")
            return None
            
    def _process_tavily_response(self, response_text: str) -> str:
        """Process the Tavily API response and extract useful information"""
        try:
            data = json.loads(response_text)
            
            # Vereenvoudigde verwerking - alleen antwoord en eerste resultaat
            formatted_text = "Market Analysis:\n\n"
            
            # Extract answer from Tavily (belangrijkste deel)
            if data and "answer" in data and data["answer"]:
                answer = data["answer"]
                formatted_text += f"{answer}\n\n"
                
            # Voeg alleen het eerste resultaat toe, indien beschikbaar
            if "results" in data and data["results"] and len(data["results"]) > 0:
                result = data["results"][0]
                title = result.get("title", "")
                content = result.get("content", "").strip()
                
                # Limiteer content lengte voor snellere verwerking
                formatted_text += f"{title}\n"
                formatted_text += f"{content[:300]}...\n" if len(content) > 300 else f"{content}\n"
                
            return formatted_text
                
        except json.JSONDecodeError:
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
            prompt = f"""Analyze the following market data for {instrument} and provide a market sentiment analysis focused ONLY on news, events, and broader market sentiment. 

**IMPORTANT**: 
1. You MUST include explicit percentages for bullish, bearish, and neutral sentiment in EXACTLY the format shown below. The percentages MUST be integers that sum to 100%.
2. DO NOT include ANY specific price levels, exact numbers, technical analysis, support/resistance levels, or price targets. 
3. DO NOT include ANY specific trading recommendations or strategies like "buy at X" or "sell at Y".
4. DO NOT mention any specific trading indicators like RSI, EMA, MACD, or specific numerical values like percentages of price movement.
5. Focus ONLY on general news events, market sentiment, and fundamental factors that drive sentiment.
6. DO NOT include sections named "Market Direction", "Technical Outlook", "Support & Resistance", "Conclusion", or anything related to technical analysis.

Market Data:
{market_data}

Your response MUST follow this EXACT format with EXACTLY this HTML formatting (keep the exact formatting with the <b> tags):

<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> [Bullish/Bearish/Neutral] [Emoji]

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: XX%
🔴 Bearish: YY%
⚪️ Neutral: ZZ%

<b>📊 Market Sentiment Analysis:</b>
[Brief description of the current market sentiment and outlook without specific price targets]

<b>📰 Key Sentiment Drivers:</b>
• [Key sentiment factor 1]
• [Key sentiment factor 2]
• [Key sentiment factor 3]

<b>📅 Important Events & News:</b>
• [News event 1]
• [News event 2]
• [News event 3]

DO NOT mention any specific price levels, numeric values, resistance/support levels, or trading recommendations. Focus ONLY on NEWS, EVENTS, and SENTIMENT information.

The sentiment percentages (Overall Sentiment, Bullish, Bearish, Neutral percentages) MUST be clearly indicated EXACTLY as shown in the format.

I will check your output to ensure you have followed the EXACT format required. DO NOT add any additional sections beyond the ones shown above.
"""

            # Make the API call with custom timeout
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(
                        self.deepseek_url,
                        headers=headers,
                        json={
                            "model": "deepseek-chat",
                            "messages": [
                                {"role": "system", "content": "You are a professional market analyst specializing in quantitative sentiment analysis. You ALWAYS follow the EXACT format requested."},
                                {"role": "user", "content": prompt}
                            ],
                            "temperature": 0.2,
                            "max_tokens": 1024
                        },
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            response_content = data['choices'][0]['message']['content']
                            logger.info(f"DeepSeek raw response for {instrument} (first 200 chars): {response_content[:200]}...")
                            
                            # Ensure the title is correctly formatted
                            if not "<b>🎯" in response_content:
                                response_content = f"<b>🎯 {instrument} Market Sentiment Analysis</b>\n\n" + response_content
                            
                            # Ensure the title uses "Market Sentiment Analysis" not just "Market Analysis"
                            response_content = response_content.replace("Market Analysis</b>", "Market Sentiment Analysis</b>")
                            
                            # Check for required sections and add them if missing
                            required_sections = [
                                ("<b>Overall Sentiment:</b>", f"<b>Overall Sentiment:</b> Neutral ➡️\n\n"),
                                ("<b>Market Sentiment Breakdown:</b>", f"<b>Market Sentiment Breakdown:</b>\n🟢 Bullish: 50%\n🔴 Bearish: 50%\n⚪️ Neutral: 0%\n\n"),
                                ("<b>📊 Market Sentiment Analysis:</b>", f"<b>📊 Market Sentiment Analysis:</b>\n{instrument} is currently showing mixed signals with no clear sentiment bias. The market shows balanced sentiment with no strong directional bias at this time.\n\n"),
                                ("<b>📰 Key Sentiment Drivers:</b>", f"<b>📰 Key Sentiment Drivers:</b>\n• Market conditions appear normal with mixed signals\n• No clear directional bias at this time\n• Standard market activity observed\n\n"),
                                ("<b>📅 Important Events & News:</b>", f"<b>📅 Important Events & News:</b>\n• Normal market activity with no major catalysts\n• No significant economic releases impacting the market\n• General news and global trends affecting sentiment\n")
                            ]
                            
                            for section, default_content in required_sections:
                                if section not in response_content:
                                    # Find where to insert the missing section
                                    insert_position = len(response_content)
                                    for next_section, _ in required_sections:
                                        if next_section in response_content and response_content.find(next_section) > response_content.find(section) if section in response_content else True:
                                            insert_position = min(insert_position, response_content.find(next_section))
                                    
                                    # Insert the section
                                    response_content = response_content[:insert_position] + default_content + response_content[insert_position:]
                                    logger.info(f"Added missing section: {section}")
                            
                            # Remove disallowed sections
                            disallowed_sections = [
                                ("<b>📈 Market Direction:</b>", "<b>Market Direction:</b>", "Market Direction:"),
                                ("<b>Technical Outlook:</b>", "Technical Outlook:"),
                                ("<b>Support & Resistance:</b>", "Support & Resistance:"),
                                ("<b>💡 Conclusion:</b>", "<b>Conclusion:</b>", "Conclusion:")
                            ]
                            
                            for section_variants in disallowed_sections:
                                for variant in section_variants:
                                    if variant in response_content:
                                        # Find start and end of section
                                        start_idx = response_content.find(variant)
                                        end_idx = len(response_content)
                                        
                                        # Try to find the next section that starts with <b>
                                        next_section = response_content.find("<b>", start_idx + 1)
                                        if next_section != -1:
                                            end_idx = next_section
                                        
                                        # Remove the section
                                        response_content = response_content[:start_idx] + response_content[end_idx:]
                                        logger.info(f"Removed disallowed section: {variant}")
                            
                            # Fix section titles to ensure correct emoji
                            response_content = response_content.replace("<b>Key Sentiment Drivers:</b>", "<b>📰 Key Sentiment Drivers:</b>")
                            response_content = response_content.replace("<b>Market Mood:</b>", "<b>📊 Market Sentiment Analysis:</b>")
                            response_content = response_content.replace("<b>Important Events & News:</b>", "<b>📅 Important Events & News:</b>")
                            
                            # Extract and validate sentiment percentages
                            bullish_match = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', response_content)
                            bearish_match = re.search(r'(?:Bearish:|🔴\s*Bearish:)\s*(\d+)\s*%', response_content)
                            neutral_match = re.search(r'(?:Neutral:|⚪️\s*Neutral:)\s*(\d+)\s*%', response_content)
                            
                            if bullish_match and bearish_match:
                                bullish = int(bullish_match.group(1))
                                bearish = int(bearish_match.group(1))
                                
                                if neutral_match:
                                    neutral = int(neutral_match.group(1))
                                    total = bullish + bearish + neutral
                                else:
                                    neutral = 0
                                    total = bullish + bearish
                                
                                # Ensure percentages sum to 100%
                                if total != 100:
                                    logger.warning(f"Sentiment percentages sum to {total}, adjusting to 100%")
                                    # Adjust to ensure sum is 100%
                                    if total > 0:
                                        bullish = int((bullish / total) * 100)
                                        bearish = int((bearish / total) * 100)
                                        neutral = 0
                                    else:
                                        bullish = 50
                                        bearish = 50
                                        neutral = 0
                                    
                                    # Update the sentiment values in the text
                                    response_content = re.sub(
                                        r'(🟢\s*Bullish:)\s*\d+\s*%', 
                                        f'🟢 Bullish: {bullish}%', 
                                        response_content
                                    )
                                    response_content = re.sub(
                                        r'(🔴\s*Bearish:)\s*\d+\s*%', 
                                        f'🔴 Bearish: {bearish}%', 
                                        response_content
                                    )
                                    if neutral_match:
                                        response_content = re.sub(
                                            r'(⚪️\s*Neutral:)\s*\d+\s*%', 
                                            f'⚪️ Neutral: {neutral}%', 
                                            response_content
                                        )
                            else:
                                # Add default values if percentages are missing
                                logger.warning(f"Sentiment percentages missing, adding defaults")
                                if "<b>Market Sentiment Breakdown:</b>" in response_content:
                                    # Replace existing section
                                    response_content = re.sub(
                                        r'<b>Market Sentiment Breakdown:</b>.*?(?=<b>|$)',
                                        "<b>Market Sentiment Breakdown:</b>\n🟢 Bullish: 50%\n🔴 Bearish: 50%\n⚪️ Neutral: 0%\n\n",
                                        response_content,
                                        flags=re.DOTALL
                                    )
                                else:
                                    # Add section after title
                                    title_end = response_content.find("</b>", response_content.find("<b>🎯")) + 4
                                    sentiment_section = "\n\n<b>Market Sentiment Breakdown:</b>\n🟢 Bullish: 50%\n🔴 Bearish: 50%\n⚪️ Neutral: 0%\n\n"
                                    response_content = response_content[:title_end] + sentiment_section + response_content[title_end:]
                            
                            # Final checks for format
                            if "<b>Overall Sentiment:</b>" in response_content:
                                # Make sure Overall Sentiment matches the percentages
                                if bullish_match and bearish_match:
                                    bullish = int(bullish_match.group(1))
                                    bearish = int(bearish_match.group(1))
                                    
                                    if bullish > bearish:
                                        overall = "Bullish 📈"
                                    elif bearish > bullish:
                                        overall = "Bearish 📉"
                                    else:
                                        overall = "Neutral ➡️"
                                        
                                    response_content = re.sub(
                                        r'<b>Overall Sentiment:</b>.*?\n',
                                        f'<b>Overall Sentiment:</b> {overall}\n',
                                        response_content
                                    )
                            
                            return response_content
                        else:
                            logger.error(f"DeepSeek API request failed with status {response.status}")
                            error_message = await response.text()
                            logger.error(f"DeepSeek API error: {error_message}")
                            # Fall back to default sentiment text
                            return self._get_default_sentiment_text(instrument)
                except asyncio.TimeoutError:
                    logger.error(f"Timeout occurred with DeepSeek API call for {instrument}")
                    return self._get_default_sentiment_text(instrument)
                except Exception as e:
                    logger.error(f"Error in DeepSeek API call: {str(e)}")
                    return self._get_default_sentiment_text(instrument)
        except Exception as e:
            logger.error(f"Error in DeepSeek formatting: {str(e)}")
            logger.exception(e)
            # Return a default sentiment text
            return self._get_default_sentiment_text(instrument)

    async def _check_deepseek_connectivity(self) -> bool:
        """Check if the DeepSeek API is reachable with minimal checks"""
        try:
            # Gebruik een zeer korte timeout voor de HTTP check
            timeout = aiohttp.ClientTimeout(total=2)
            ssl_context = ssl.create_default_context()
            
            # Gebruik host override om DNS problemen te omzeilen
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.head(
                    self.deepseek_url,
                    timeout=timeout
                ) as response:
                    # Zelfs 401 of 403 betekent dat de API toegankelijk is
                    return response.status in (200, 401, 403, 404)
        except Exception:
            # Alle fouten betekenen dat de API niet bereikbaar is
            return False

    def _get_default_sentiment_text(self, instrument: str) -> str:
        """Return a default sentiment text for a given instrument"""
        return f"""<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> Neutral ➡️

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 50%
🔴 Bearish: 50%
⚪️ Neutral: 0%

<b>📰 Key Sentiment Drivers:</b>
• Market conditions appear normal with mixed signals
• No clear directional bias at this time
• Standard market activity observed

<b>📊 Market Mood:</b>
{instrument} is currently showing mixed signals with no clear sentiment bias.

<b>📅 Important Events & News:</b>
• Normal market activity with no major catalysts
• No significant economic releases impacting the market
• General news and global trends affecting sentiment

<b>🔮 Sentiment Outlook:</b>
The market shows balanced sentiment for {instrument} with no strong directional bias at this time.
"""

    def _create_quick_sentiment_response(self, instrument: str) -> dict:
        """Create a quick sentiment response for a given instrument"""
        return {
            'overall_sentiment': 'neutral',
            'sentiment_score': 0.5,
            'bullish': 50,
            'bearish': 50,
            'neutral': 0,
            'trend_strength': 'Moderate',
            'volatility': 'Moderate',
            'analysis': self._get_default_sentiment_text(instrument)
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
