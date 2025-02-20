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

    async def get_market_sentiment(self, signal: Dict[str, Any]) -> Dict[str, str]:
        """Get market sentiment analysis"""
        try:
            symbol = signal.get('symbol', '')
            market = signal.get('market', 'forex')
            logger.info(f"Getting market sentiment for {symbol} ({market})")
            
            # Create prompt for market analysis
            prompt = f"""Analyze the current market sentiment for {symbol} and provide a concise analysis with these exact sections:
            1. Market direction (1-2 sentences)
            2. Support and resistance levels (key levels only)
            3. Main risk factors (bullet points)
            4. Trading implications (2-3 key points)
            
            Format the response as a JSON object with these exact keys:
            {{
                "direction": "market direction text",
                "support": "support levels",
                "resistance": "resistance levels",
                "risks": "bullet points of risks",
                "implications": "trading implications"
            }}
            """
            
            payload = {
                "model": "deepseek-chat",
                "messages": [{
                    "role": "system",
                    "content": "You are a professional market analyst. Provide concise, structured analysis."
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
                        sentiment = json.loads(data['choices'][0]['message']['content'])
                        logger.info("Successfully retrieved market sentiment")
                        return sentiment
                    else:
                        logger.error(f"DeepSeek API error: {response.status}")
                        return self._get_fallback_sentiment(signal)

        except Exception as e:
            logger.error(f"Error getting sentiment: {str(e)}")
            return self._get_fallback_sentiment(signal)

    def _get_fallback_sentiment(self, signal: Dict[str, Any]) -> Dict[str, str]:
        """Fallback sentiment analysis"""
        symbol = signal.get('symbol', 'Unknown')
        return {
            "direction": "Market direction is currently neutral with mixed signals",
            "support": "Previous low",
            "resistance": "Previous high",
            "risks": "• Market volatility\n• Limited data availability\n• Uncertain conditions",
            "implications": "• Exercise caution\n• Wait for clearer signals\n• Use proper risk management"
        } 
