import os
import logging
import aiohttp
from typing import Dict, Any
from openai import AsyncOpenAI

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
            # Hier zou de Perplexity API call komen
            # Voor nu simuleren we het met een template
            prompt = f"Find the most recent economic and financial news related to the {instrument} currency pair. Focus on key events."
            
            # TODO: Implementeer echte Perplexity API call
            # Voor nu returnen we dummy data
            return f"""
            Recent news for {instrument}:
            1. Central bank announced interest rate decision
            2. Economic data shows strong GDP growth
            3. Political developments affecting currency markets
            4. Market volatility increased due to global factors
            """
            
        except Exception as e:
            logger.error(f"Error getting Perplexity analysis: {str(e)}")
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

            Use bullet points and ensure a concise, professional summary tailored for traders. Here is the raw input:

            {perplexity_output}
            """

            response = await self.openai.chat.completions.create(
                model="gpt-4",
                messages=[{
                    "role": "system",
                    "content": "You are a professional market analyst. Format market analysis in a structured way with clear sections and bullet points."
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

    async def get_market_sentiment(self, signal: Dict[str, Any]) -> str:
        """Get complete market sentiment analysis"""
        try:
            # Get raw analysis from Perplexity
            perplexity_output = await self.get_perplexity_analysis(signal['symbol'])
            if not perplexity_output:
                return "Could not fetch market analysis"
                
            # Format with OpenAI
            formatted_sentiment = await self.format_sentiment_with_ai(perplexity_output)
            return formatted_sentiment
            
        except Exception as e:
            logger.error(f"Error in market sentiment analysis: {str(e)}")
            return "Error analyzing market sentiment" 
