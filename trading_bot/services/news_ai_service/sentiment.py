import os
import logging
import aiohttp
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
            logger.info(f"Getting market sentiment for {signal}")
            
            # Create prompt for market analysis
            prompt = f"""Analyze the current market sentiment for {signal['symbol']} considering:
            1. Current price action
            2. Technical indicators
            3. Market trends
            4. Trading volume
            5. Key support/resistance levels
            
            Format the response with:
            - Market direction
            - Key levels
            - Risk factors
            - Trading implications
            """
            
            payload = {
                "model": "deepseek-chat",
                "messages": [{
                    "role": "system",
                    "content": "You are a professional market analyst."
                }, {
                    "role": "user",
                    "content": prompt
                }],
                "temperature": 0.7
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content']
                    else:
                        logger.error(f"DeepSeek API error: {response.status}")
                        return self._get_fallback_sentiment(signal)

        except Exception as e:
            logger.error(f"Error getting sentiment: {str(e)}")
            return self._get_fallback_sentiment(signal)

    def _get_fallback_sentiment(self, signal: Dict[str, Any]) -> str:
        # Implementation of _get_fallback_sentiment method
        # This method should return a fallback sentiment analysis
        # For now, we'll use a placeholder return
        return "Fallback sentiment analysis" 
