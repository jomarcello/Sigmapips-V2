import logging
import random
import os
import httpx
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class MarketSentimentService:
    """Service for analyzing market sentiment"""
    
    def __init__(self):
        """Initialize the market sentiment service"""
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.api_url = "https://api.deepseek.ai/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # If no API key is provided, we'll use mock data
        self.use_mock = not self.api_key
        if self.use_mock:
            logger.warning("No DeepSeek API key found, using mock data")
    
    async def get_market_sentiment(self, instrument):
        """Get market sentiment for a specific instrument"""
        try:
            logger.info(f"Getting market sentiment for {instrument}")
            
            if self.use_mock:
                # Generate sentiment based on instrument type (Mock Data)
                if instrument.startswith(('BTC', 'ETH')):
                    sentiment_score = random.uniform(0.6, 0.8)  # Crypto tends to be bullish
                elif instrument.startswith(('XAU', 'GOLD')):
                    sentiment_score = random.uniform(0.4, 0.7)  # Commodities can be volatile
                elif instrument.endswith(('USD', 'JPY','EUR', 'GBP')): # check for forex
                     sentiment_score = random.uniform(0.3, 0.7)
                elif instrument.isdigit() or any(char in instrument for char in ['US', 'UK', 'DE']):
                    sentiment_score = random.uniform(0.3, 0.7)
                
                else:
                    sentiment_score = random.uniform(0.3, 0.7)  # Forex and indices more balanced
                
                bullish_percentage = int(sentiment_score * 100)
                trend_strength = 'Strong' if abs(sentiment_score - 0.5) > 0.3 else 'Moderate' if abs(sentiment_score - 0.5) > 0.1 else 'Weak'
                
                # determine overall sentiment based on score
                if sentiment_score > 0.6:
                    overall_sentiment = "bullish"
                elif sentiment_score < 0.4:
                     overall_sentiment = "bearish"
                else:
                    overall_sentiment = "neutral"

                # Determine recommendation based on overall sentiment
                if overall_sentiment == "bullish":
                    recommendation = "Consider buying opportunities."
                elif overall_sentiment == "bearish":
                    recommendation = "Consider selling or shorting opportunities."
                else:
                    recommendation = "Wait for clearer market signals."

                return {
                    'overall_sentiment': overall_sentiment,
                    'sentiment_score': round(sentiment_score, 2),
                    'bullish_percentage': bullish_percentage,
                    'trend_strength': trend_strength,
                    'volatility': random.choice(['High', 'Moderate', 'Low']),
                    'support_level': 'See analysis for details',
                    'resistance_level': 'See analysis for details',
                    'recommendation': recommendation,
                    'analysis': self._get_mock_sentiment(instrument),
                    'source': 'mock_data'
                }
            else:
              # Real Deepseek API Call
                async with httpx.AsyncClient() as client:
                    prompt = f"Analyze the market sentiment for {instrument}. Please include the overall sentiment, bullish/bearish percentages, trend strength, volatility, support, resistance and a trading recommendation."
                    payload = {
                        "model": "deepseek-chat",  # Or the model you are using
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 300
                    }
                    
                    response = await client.post(self.api_url, headers=self.headers, json=payload)
                    response.raise_for_status()  # Raise an exception for bad status codes

                    # Extract data from Deepseek's response
                    response_data = response.json()
                    content = response_data["choices"][0]["message"]["content"]
                   
                    # Parse the response (this will depend on how Deepseek formats its data)
                    # You'll need to implement a proper parsing logic based on Deepseek's output format
                    # This is just an example of how to extract some data, you need to finetune this
                    # parse the data
                    try:
                         overall_sentiment = self._parse_sentiment(content)
                         bullish_percentage = self._parse_percentage(content, "bullish")
                         trend_strength = self._parse_trend_strength(content)
                         volatility = self._parse_volatility(content)
                         recommendation = self._parse_recommendation(content)
                         analysis = content # add the full response as analysis for now

                         return {
                            "overall_sentiment": overall_sentiment,
                            "bullish_percentage": bullish_percentage,
                            "trend_strength": trend_strength,
                            "volatility": volatility,
                            "recommendation": recommendation,
                            "analysis": analysis,
                           "source": "deepseek",
                           "sentiment_score": 0.5
                        }

                    except ValueError as e:
                         logger.error(f"Error parsing Deepseek response: {e}")
                         logger.debug(f"Raw response: {content}")
                         # fall back to mock data
                         return {
                         'overall_sentiment': 'neutral',
                          'sentiment_score': 0.5,
                           'source': 'fallback'
                         }

        except httpx.HTTPError as e:
            logger.error(f"HTTP error when calling Deepseek: {e}")
            return {
                'overall_sentiment': 'neutral',
                'sentiment_score': 0.5,
                'source': 'fallback'
            }

        except Exception as e:
            logger.error(f"Error getting market sentiment: {str(e)}")
            logger.exception(e)
            # Fallback naar neutraal sentiment
            return {
                'overall_sentiment': 'neutral',
                'sentiment_score': 0.5,
                'source': 'fallback'
            }

    async def get_market_sentiment_html(self, instrument: str) -> str:
      #... rest of the class
    def _get_mock_sentiment(self, instrument):
        #... rest of the class

    def _parse_sentiment(self, text: str) -> str:
        """Parse overall sentiment from text."""
        if "bullish" in text.lower():
            return "bullish"
        elif "bearish" in text.lower():
            return "bearish"
        else:
            return "neutral"
    
    def _parse_percentage(self, text: str, type: str) -> int:
        """Parse percentage from text."""
        import re
        match = re.search(rf"{type}[: ]*(\d+)%", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return 50  # Default value

    def _parse_trend_strength(self, text: str) -> str:
        """Parse trend strength from text."""
        if "strong" in text.lower():
            return "Strong"
        elif "moderate" in text.lower():
            return "Moderate"
        else:
            return "Weak"

    def _parse_volatility(self, text: str) -> str:
      """Parse volatility from text."""
      if "high" in text.lower():
            return "High"
      elif "moderate" in text.lower():
          return "Moderate"
      else:
           return "Low"

    def _parse_recommendation(self, text: str) -> str:
      """Parse trading recommendation from text."""
      if "buy" in text.lower():
          return "Consider buying opportunities."
      elif "sell" in text.lower() or "short" in text.lower():
          return "Consider selling or shorting opportunities."
      else:
           return "Wait for clearer market signals."
