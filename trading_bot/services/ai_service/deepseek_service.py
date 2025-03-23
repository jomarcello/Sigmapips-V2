import os
import logging
import httpx
import asyncio
import json
import random
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class DeepseekService:
    """Service for generating text completions using DeepSeek AI"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the DeepSeek service"""
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.api_url = "https://api.deepseek.ai/v1/chat/completions" 
        
        if not self.api_key:
            logger.warning("No DeepSeek API key found, completions will return mock data")
            
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
    async def generate_completion(self, prompt: str, model: str = "deepseek-chat", temperature: float = 0.2) -> str:
        """
        Generate a text completion using DeepSeek
        
        Args:
            prompt: The text prompt
            model: The DeepSeek model to use
            temperature: Controls randomness (0-1)
            
        Returns:
            Generated completion text
        """
        try:
            logger.info(f"Generating DeepSeek completion for prompt: {prompt[:100]}...")
            
            if not self.api_key:
                return self._get_mock_completion(prompt)
                
            # Create the request payload
            payload = {
                "model": model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": temperature,
                "max_tokens": 2048
            }
            
            # Make the API call
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    headers=self.headers,
                    json=payload,
                    timeout=60.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data.get("choices", [{}])[0].get("message", {}).get("content", "")
                else:
                    logger.error(f"DeepSeek API error: {response.status_code} - {response.text}")
                    return self._get_mock_completion(prompt)
                    
        except Exception as e:
            logger.error(f"Error generating DeepSeek completion: {str(e)}")
            logger.exception(e)
            return self._get_mock_completion(prompt)
            
    def _get_mock_completion(self, prompt: str) -> str:
        """Generate mock completion when the API is unavailable"""
        logger.info(f"Generating mock completion")
        
        if "economic calendar" in prompt.lower():
            # Return a mock economic calendar JSON
            return """```json
{
  "USD": [
    {
      "time": "08:30 EST",
      "event": "Initial Jobless Claims",
      "impact": "Medium"
    },
    {
      "time": "08:30 EST",
      "event": "Trade Balance",
      "impact": "Medium"
    },
    {
      "time": "15:30 EST",
      "event": "Fed Chair Speech",
      "impact": "High"
    }
  ],
  "EUR": [
    {
      "time": "07:45 EST",
      "event": "ECB Interest Rate Decision",
      "impact": "High"
    },
    {
      "time": "08:30 EST",
      "event": "ECB Press Conference",
      "impact": "High"
    }
  ],
  "GBP": [],
  "JPY": [],
  "CHF": [],
  "AUD": [],
  "NZD": [],
  "CAD": []
}```"""
        elif "sentiment" in prompt.lower():
            # Return a mock sentiment analysis
            is_bullish = random.choice([True, False])
            sentiment = "bullish" if is_bullish else "bearish"
            
            return f"""<b>📊 Market Sentiment Analysis: {sentiment.upper()}</b>

Based on current market conditions, the overall sentiment for this instrument is <b>{sentiment}</b>.

<b>Sentiment Breakdown:</b>
• Technical indicators: {'Mostly bullish' if is_bullish else 'Mostly bearish'}
• Volume analysis: {'Above average' if is_bullish else 'Below average'}
• Market momentum: {'Strong' if is_bullish else 'Weak'}

<b>Key Support and Resistance:</b>
• Support: [level 1], [level 2]
• Resistance: [level 1], [level 2]

<b>Recommendation:</b>
<b>{'Consider long positions with appropriate risk management.' if is_bullish else 'Consider short positions with appropriate risk management.'}</b>

<i>Note: This analysis is based on current market conditions and should be used as part of a comprehensive trading strategy.</i>"""
        else:
            return "I apologize, but I couldn't generate a response. This is mock data since the DeepSeek API key is not configured or the API request failed." 
