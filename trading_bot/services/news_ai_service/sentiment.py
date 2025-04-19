#!/usr/bin/env python3
# Test script voor MarketSentimentService

import asyncio
import logging
import sys
from trading_bot.services.sentiment_service.sentiment import MarketSentimentService
import os
import aiohttp
import json

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

async def test_sentiment_analysis():
    """Test de nieuws-gerichte sentimentanalyse voor EURUSD"""
    deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')
    if not deepseek_api_key:
        print('Geen DeepSeek API key gevonden in omgevingsvariabelen')
        return False

    print(f'DeepSeek API key aanwezig: {deepseek_api_key[:4]}...{deepseek_api_key[-4:]}')
    
    # Voorbeeld van nieuws-data die we van Tavily zouden krijgen
    news_data = """
    EUR/USD Analysis: The euro rose versus the US dollar following dovish comments from Federal Reserve officials suggesting potential rate cuts. ECB President Lagarde maintained a more hawkish stance regarding European rates. Economic data showed stronger-than-expected manufacturing numbers from Germany but weaker retail sales in the eurozone.
    
    The US dollar faced pressure after weaker-than-expected jobs data raised concerns about economic growth, while the euro was supported by reduced political uncertainty in France. Market participants are closely watching upcoming inflation readings from both regions, with analysts expecting the ECB to keep rates higher for longer compared to the Fed's anticipated cutting cycle.
    
    Institutional sentiment surveys show increasing euro-positive positions among large investors, while retail traders remain more evenly divided. The upcoming US employment report (NFP) and European PMI data will be critical for determining the short-term direction of the pair.
    """
    
    # API URL en headers
    api_url = "https://api.deepseek.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {deepseek_api_key}",
        "Content-Type": "application/json"
    }
    
    # Creëer prompt voor nieuws-gerichte sentimentanalyse
    instrument = "EURUSD"
    prompt = f"""Analyze the following market data for {instrument} and provide a market sentiment analysis focused ONLY on news, events, and broader market sentiment. 

**IMPORTANT**: 
1. You MUST include explicit percentages for bullish, bearish, and neutral sentiment in EXACTLY the format shown below. The percentages MUST be integers that sum to 100%.
2. DO NOT include any specific price levels, technical analysis, support/resistance levels, or price targets.
3. Focus ONLY on news events, market sentiment, and fundamental factors that drive sentiment.

Market Data:
{news_data}

Your response MUST follow this EXACT format with EXACTLY this HTML formatting (keep the exact formatting with the <b> tags):

<b>🎯 {instrument} Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> [Bullish/Bearish/Neutral] [Emoji]

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: XX%
🔴 Bearish: YY%
⚪️ Neutral: ZZ%

<b>📰 Key Sentiment Drivers:</b>
• [Key sentiment factor 1]
• [Key sentiment factor 2]
• [Key sentiment factor 3]

<b>📊 Market Mood:</b>
[Brief description of the current market mood and sentiment]

<b>📅 Important Events & News:</b>
• [News event 1]
• [News event 2]
• [News event 3]

<b>🔮 Sentiment Outlook:</b>
[General sentiment outlook without specific price targets]

DO NOT mention any specific price levels, technical support/resistance levels, or exact price targets. Focus ONLY on NEWS, EVENTS, and SENTIMENT information.

The sentiment percentages (Overall Sentiment, Bullish, Bearish, Neutral percentages) MUST be clearly indicated EXACTLY as shown in the format.
"""
    
    print("\nVersturen van de nieuws-gerichte prompt naar DeepSeek API...")
    
    try:
        # DeepSeek API aanroepen
        async with aiohttp.ClientSession() as session:
            async with session.post(
                api_url,
                headers=headers,
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "You are a professional market analyst specializing in news-based sentiment analysis."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1024
                }
            ) as response:
                print(f'DeepSeek API response status: {response.status}')
                
                if response.status == 200:
                    data = await response.json()
                    response_content = data['choices'][0]['message']['content']
                    
                    print("\nNieuws-gerichte sentimentanalyse van DeepSeek:")
                    print(response_content)
                    return True
                else:
                    error_text = await response.text()
                    print(f'Fout bij API-aanroep: {response.status}')
                    print(f'Foutbericht: {error_text}')
                    return False
    except Exception as e:
        print(f'Fout bij het aanroepen van DeepSeek API: {str(e)}')
        return False

# Mock data voor als de echte API niet beschikbaar is
def show_mock_sentiment_response():
    print("\nMock nieuws-gerichte sentimentanalyse voor EURUSD:")
    
    mock_response = """<b>🎯 EURUSD Market Sentiment Analysis</b>

<b>Overall Sentiment:</b> Bullish 📈

<b>Market Sentiment Breakdown:</b>
🟢 Bullish: 65%
🔴 Bearish: 20%
⚪️ Neutral: 15%

<b>📰 Key Sentiment Drivers:</b>
• Dovish Fed comments suggesting potential rate cuts
• ECB's hawkish stance on maintaining higher rates
• Weaker US jobs data putting pressure on USD

<b>📊 Market Mood:</b>
The market mood is predominantly optimistic toward EUR against USD, driven by diverging central bank policies. Institutional investors are increasingly taking euro-positive positions while retail sentiment remains more divided.

<b>📅 Important Events & News:</b>
• Fed officials hinting at potential rate cuts
• Stronger-than-expected German manufacturing data
• Upcoming US employment report (NFP) and European PMI data

<b>🔮 Sentiment Outlook:</b>
The sentiment outlook favors the euro in the medium term due to the divergence in monetary policy between the ECB and Fed. The ECB is expected to maintain higher rates for longer, while the Fed appears more likely to begin a cutting cycle sooner.
"""
    print(mock_response)

# Draai de tests
if __name__ == "__main__":
    print("Testen van de nieuws-gerichte sentimentanalyse...\n")
    try:
        success = asyncio.run(test_sentiment_analysis())
        if not success:
            # Als de echte API niet werkt, toon dan de mock data
            show_mock_sentiment_response()
    except Exception as e:
        print(f"Fout bij uitvoeren van sentiment analyse test: {str(e)}")
        # Toon altijd de mock data bij fouten
        show_mock_sentiment_response() 
