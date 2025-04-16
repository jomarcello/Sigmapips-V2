#!/usr/bin/env python3
# Test script voor MarketSentimentService

import asyncio
import logging
import sys
from trading_bot.services.sentiment_service.sentiment import MarketSentimentService

# Configureer logging voor meer informatie
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler(sys.stdout)])

async def test_sentiment():
    print("===== Test MarketSentimentService =====")
    
    # Initialiseer de service
    service = MarketSentimentService()
    
    # Test instrumenten
    instruments = ["EURUSD", "BTCUSD", "XAUUSD", "US500"]
    
    for instrument in instruments:
        print(f"\n----- Sentimentsanalyse voor {instrument} -----")
        
        # Haal sentiment op
        try:
            sentiment_data = await service.get_sentiment(instrument)
            
            # Toon belangrijke waarden
            print(f"Bullish: {sentiment_data.get('bullish', 'N/A')}%")
            print(f"Bearish: {sentiment_data.get('bearish', 'N/A')}%")
            print(f"Neutral: {sentiment_data.get('neutral', 'N/A')}%")
            print(f"Sentiment Score: {sentiment_data.get('sentiment_score', 'N/A')}")
            print(f"Technical Score: {sentiment_data.get('technical_score', 'N/A')}")
            print(f"News Score: {sentiment_data.get('news_score', 'N/A')}")
            print(f"Social Score: {sentiment_data.get('social_score', 'N/A')}")
            
            # Toon een deel van de analyse (de eerste 150 tekens)
            analysis = sentiment_data.get('analysis', 'Geen analyse beschikbaar')
            print(f"Analyse snippet: {analysis[:150]}..." if len(analysis) > 150 else analysis)
            
        except Exception as e:
            print(f"Error bij testen van {instrument}: {str(e)}")
    
    print("\n===== Test Voltooid =====")

# Voer de test uit
if __name__ == "__main__":
    asyncio.run(test_sentiment()) 