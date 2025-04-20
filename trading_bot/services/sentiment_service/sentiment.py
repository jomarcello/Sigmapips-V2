import time
import tavily
import json
import os
from datetime import datetime, timedelta

# Cache storage
sentiment_cache = {}

def get_sentiment_analysis(instrument, use_cache=True):
    current_time = datetime.now()
    
    # Check if we have a valid cached result
    if use_cache and instrument in sentiment_cache:
        cached_data = sentiment_cache[instrument]
        # Check if the cache is still valid (less than 30 minutes old)
        if current_time - cached_data['timestamp'] < timedelta(minutes=30):
            print(f"Using cached sentiment analysis for {instrument}")
            return cached_data['result']
    
    print(f"Performing new sentiment analysis for {instrument}")
    
    # If no valid cache, perform the analysis as before
    tavily.api_key = os.environ.get('TAVILY_API_KEY', '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')
    
    try:
        # Determine search query based on instrument
        search_query = f"{instrument} recent market news, trading sentiment, price forecast"
        
        # Use Tavily to perform a search
        tavily_response = tavily.search(
            query=search_query,
            search_depth="advanced",
            include_answer=True,
            include_raw_content=False,
            include_images=False,
        )
        
        # Extract the answer from Tavily's response
        tavily_answer = tavily_response.get('answer', '')
        
        # Now we use DeepSeek for sentiment analysis on Tavily's answer
        from deepseek import deepseek

        # Construct the prompt for DeepSeek
        sentiment_prompt = f"""
        Based on the following text about {instrument}, please provide:
        1. Overall market sentiment (bullish, bearish, or neutral)
        2. Key factors influencing the sentiment
        3. Short-term price outlook (1-2 weeks)
        4. Medium-term outlook (1-3 months)
        5. Important support and resistance levels if mentioned
        
        Here's the text:
        {tavily_answer}
        
        Format your response as a clear summary that a trader can quickly understand.
        """
        
        # Get sentiment analysis from DeepSeek
        sentiment_result = deepseek.completion(
            messages=[{"role": "user", "content": sentiment_prompt}],
            max_tokens=1000
        )
        
        # Extract just the content from the response
        sentiment_analysis = sentiment_result.choices[0].message.content
        
        # Cache the result with timestamp
        sentiment_cache[instrument] = {
            'result': sentiment_analysis,
            'timestamp': current_time
        }
        
        return sentiment_analysis
    
    except Exception as e:
        error_message = f"Error performing sentiment analysis: {str(e)}"
        print(error_message)
        return error_message
