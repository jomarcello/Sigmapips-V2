import os
import logging
import aiohttp
from typing import Dict, Any
from openai import AsyncOpenAI
from datetime import datetime

logger = logging.getLogger(__name__)

class MarketSentimentService:
    def __init__(self):
        """Initialize sentiment service"""
        self.openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.perplexity_key = os.getenv("PERPLEXITY_API_KEY")
        if not self.perplexity_key:
            raise ValueError("Missing PERPLEXITY_API_KEY")
        
        # Perplexity API setup
        self.perplexity_headers = {
            "Authorization": f"Bearer {self.perplexity_key}",
            "Content-Type": "application/json"
        }
        
    async def get_perplexity_analysis(self, instrument: str) -> str:
        """Get market analysis from Perplexity"""
        try:
            url = "https://api.perplexity.ai/chat/completions"
            
            payload = {
                "model": "sonar-pro",
                "messages": [{
                    "role": "system",
                    "content": "You are a financial analyst focused on providing recent market analysis."
                }, {
                    "role": "user",
                    "content": f"Find the most recent economic and financial news related to the {instrument} currency pair. Focus on key events, market sentiment, and potential impact on price."
                }]
            }
            
            logger.info(f"Calling Perplexity API for {instrument}")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=self.perplexity_headers) as response:
                    logger.info(f"Perplexity API response status: {response.status}")
                    response_text = await response.text()
                    logger.info(f"Perplexity API response: {response_text}")
                    
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content']
                    else:
                        logger.error(f"Perplexity API error: {response.status} - {response_text}")
                        return None
                    
        except Exception as e:
            logger.error(f"Error getting Perplexity analysis: {str(e)}")
            logger.exception(e)
            return None

    async def format_sentiment_with_ai(self, perplexity_output: str) -> str:
        """Format sentiment analysis using OpenAI"""
        try:
            prompt = f"""
            Format the following market analysis in this structured style, in English:

            🔍 Market Impact Analysis

            • ECB's latest decision: ...

            • Market implications: ...

            • Current trend: ...


            📊 Market Sentiment

            • Direction: ...

            • Strength: ...

            • Key driver: ...


            💡 Trading Implications

            • Short-term outlook: ...

            • Risk assessment: ...

            • Key levels: ...


            ⚠️ Risk Factors

            • ...

            Use bullet points and ensure a concise, professional summary tailored for traders. Add a blank line between each bullet point for better readability. Here is the raw input:

            {perplexity_output}
            """

            response = await self.openai.chat.completions.create(
                model="gpt-4",
                messages=[{
                    "role": "system",
                    "content": "You are a professional market analyst. Format market analysis in a structured way with clear sections and bullet points. Add a blank line between each bullet point for better readability."
                }, {
                    "role": "user",
                    "content": prompt
                }],
                temperature=0
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Error formatting sentiment with AI: {str(e)}")
            return "Error analyzing market sentiment"

    async def get_market_sentiment(self, instrument: str) -> str:
        """Get complete market sentiment analysis"""
        try:
            logger.info(f"Getting market sentiment for {instrument}")
            
            # Get raw analysis from Perplexity
            perplexity_output = await self.get_perplexity_analysis(instrument)
            logger.info(f"Perplexity output: {perplexity_output}")
            
            if not perplexity_output:
                return "Could not fetch market analysis"
            
            # Format with OpenAI
            formatted_sentiment = await self.format_sentiment_with_ai(perplexity_output)
            logger.info(f"Formatted sentiment: {formatted_sentiment}")
            
            return formatted_sentiment
            
        except Exception as e:
            logger.error(f"Error in market sentiment analysis: {str(e)}")
            logger.exception(e)
            return "Error analyzing market sentiment" 
