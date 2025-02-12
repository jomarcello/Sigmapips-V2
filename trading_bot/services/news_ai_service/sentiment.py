import os
import time
import asyncio
import logging
from openai import AsyncOpenAI
from trading_bot.services.database.db import Database

logger = logging.getLogger(__name__)

class NewsAIService:
    def __init__(self, db):
        self.db = db
        self.openai_client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            max_retries=3,
            timeout=30.0
        )
        self.last_api_call = 0
        self.min_delay = 3.0  # Verhoogd naar 3 seconden
        
    async def analyze_sentiment(self, symbol: str) -> str:
        try:
            # First check cache
            cached = await self.db.get_cached_sentiment(symbol)
            if cached:
                return cached
                
            # Rate limiting
            current_time = time.time()
            time_since_last_call = current_time - self.last_api_call
            if time_since_last_call < self.min_delay:
                delay = self.min_delay - time_since_last_call
                logger.info(f"Rate limiting: waiting {delay:.2f} seconds")
                await asyncio.sleep(delay)
            
            # Try OpenAI
            try:
                completion = await self.openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "You are a market analyst providing brief sentiment analysis."},
                        {"role": "user", "content": f"Analyze current market sentiment for {symbol} briefly"}
                    ],
                    max_tokens=150,
                    temperature=0.7
                )
                self.last_api_call = time.time()
                sentiment = completion.choices[0].message.content
                
            except Exception as e:
                logger.error(f"OpenAI API error: {str(e)}")
                return None
            
            # Cache the result
            if sentiment:
                await self.db.cache_sentiment(symbol, sentiment)
            return sentiment
            
        except Exception as e:
            logger.error(f"Error analyzing sentiment: {str(e)}")
            return None 