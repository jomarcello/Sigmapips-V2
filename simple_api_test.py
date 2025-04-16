#!/usr/bin/env python3
"""
Eenvoudig testscript dat direct naar de API endpoints maakt zonder afhankelijkheden
"""

import os
import asyncio
import json
import time
import aiohttp
import logging

# Logging configureren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_api_connectivity():
    """Test de connectiviteit met de APIs zonder complexe code"""
    
    # API sleutels ophalen uit omgevingsvariabelen
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    
    # De API endpoints
    deepseek_url = "https://api.deepseek.com/v1/chat/completions"
    tavily_url = "https://api.tavily.com/search"
    
    results = {
        "deepseek": {"working": False, "response": None, "error": None},
        "tavily": {"working": False, "response": None, "error": None}
    }
    
    # Test DeepSeek API
    logger.info("DeepSeek API test starten...")
    headers_deepseek = {
        "Authorization": f"Bearer {deepseek_api_key}",
        "Content-Type": "application/json"
    }
    payload_deepseek = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "U bent een marktanalist die EURUSD forex analyseert."},
            {"role": "user", "content": "Geef een bullish/bearish analyse voor EURUSD in dit format:\n\nBullish: XX%\nBearish: YY%\nNeutraal: ZZ%"}
        ],
        "temperature": 0.7,
        "max_tokens": 500
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                deepseek_url,
                headers=headers_deepseek,
                json=payload_deepseek,
                timeout=30
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                    results["deepseek"]["working"] = True
                    results["deepseek"]["response"] = content
                    logger.info(f"DeepSeek API test geslaagd: {content[:100]}...")
                else:
                    error_text = await response.text()
                    results["deepseek"]["error"] = f"Status {response.status}: {error_text[:100]}"
                    logger.error(f"DeepSeek API fout: {response.status} - {error_text[:100]}")
    except Exception as e:
        results["deepseek"]["error"] = str(e)
        logger.error(f"DeepSeek API fout: {str(e)}")
    
    # Test Tavily API
    logger.info("Tavily API test starten...")
    headers_tavily = {
        "Authorization": f"Bearer {tavily_api_key}",
        "Content-Type": "application/json"
    }
    payload_tavily = {
        "query": "EURUSD forex market analysis",
        "search_depth": "basic",
        "include_answer": True,
        "max_results": 3
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                tavily_url,
                headers=headers_tavily,
                json=payload_tavily,
                timeout=30
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    answer = result.get('answer', '')
                    results["tavily"]["working"] = True
                    results["tavily"]["response"] = answer
                    logger.info(f"Tavily API test geslaagd: {answer[:100]}...")
                else:
                    error_text = await response.text()
                    results["tavily"]["error"] = f"Status {response.status}: {error_text[:100]}"
                    logger.error(f"Tavily API fout: {response.status} - {error_text[:100]}")
    except Exception as e:
        results["tavily"]["error"] = str(e)
        logger.error(f"Tavily API fout: {str(e)}")
    
    # Resultaten printen
    logger.info("\nAPI Test Resultaten:")
    logger.info(f"DeepSeek API: {'WERKT' if results['deepseek']['working'] else 'MISLUKT'}")
    if results["deepseek"]["working"]:
        logger.info(f"DeepSeek Antwoord: {results['deepseek']['response'][:200]}...")
    else:
        logger.info(f"DeepSeek Fout: {results['deepseek']['error']}")
    
    logger.info(f"\nTavily API: {'WERKT' if results['tavily']['working'] else 'MISLUKT'}")
    if results["tavily"]["working"]:
        logger.info(f"Tavily Antwoord: {results['tavily']['response'][:200]}...")
    else:
        logger.info(f"Tavily Fout: {results['tavily']['error']}")
    
    # Als beide APIs werken, voer een combinatie-test uit
    if results["deepseek"]["working"] and results["tavily"]["working"]:
        logger.info("\nBeide APIs werken correct! Sentimentanalyse is mogelijk.")
        
        # Genereer een geprompt antwoord met een goede sentimentanalyse
        logger.info("\nGenereren van correct geformatteerde sentimentanalyse...")
        prompt = f"""
        Analyseer de volgende marktgegevens voor EURUSD en geef een duidelijke sentimentanalyse.

        Marktgegevens:
        {results['tavily']['response']}

        Je MOET het volgende formaat EXACT volgen:

        <b>🎯 EURUSD Market Analysis</b>

        <b>Market Sentiment Breakdown:</b>
        🟢 Bullish: XX%
        🔴 Bearish: YY%
        ⚪️ Neutral: ZZ%

        <b>📈 Market Direction:</b>
        [Gedetailleerde trendanalyse met specifieke prijsniveaus en momentum]

        <b>📰 Latest News & Events:</b>
        • [Belangrijk punt 1]
        • [Belangrijk punt 2]
        • [Belangrijk punt 3]

        <b>⚠️ Risk Factors:</b>
        • [Risico 1]
        • [Risico 2]
        • [Risico 3]

        <b>💡 Conclusion:</b>
        [Duidelijke handelsaanbeveling met specifieke instappunten, doelen en stopniveaus]

        Vervang XX, YY, ZZ door precieze percentages die samen optellen tot 100%.
        """
        
        new_payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "U bent een professionele marktanalist gespecialiseerd in kwantitatieve sentimentanalyse."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 1024
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    deepseek_url,
                    headers=headers_deepseek,
                    json=new_payload,
                    timeout=30
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                        logger.info(f"\nGegenereerde sentimentanalyse met correct formaat:\n{content}")
                        
                        # Check of het formaat correct is met percentages
                        if "Bullish:" in content and "%" in content:
                            logger.info("\nDe sentimentanalyse bevat de juiste percentages formaat!")
                            
                            # Extraheer percentages met regex
                            import re
                            bullish_match = re.search(r'(?:Bullish:|🟢\s*Bullish:)\s*(\d+)\s*%', content)
                            if bullish_match:
                                logger.info(f"Gedetecteerde bullish percentage: {bullish_match.group(1)}%")
                                logger.info("Dit bevestigt dat het formaat correct is voor gebruik in de bot!")
                            else:
                                logger.warning("Bullish percentage kon niet worden geextraheerd met regex.")
                        else:
                            logger.warning("De sentimentanalyse bevat niet het juiste formaat met percentages.")
                    else:
                        error_text = await response.text()
                        logger.error(f"Fout bij genereren sentimentanalyse: {response.status} - {error_text[:100]}")
        except Exception as e:
            logger.error(f"Fout bij genereren sentimentanalyse: {str(e)}")
    
    return results

if __name__ == "__main__":
    logger.info("Eenvoudige API test gestart")
    start_time = time.time()
    
    results = asyncio.run(test_api_connectivity())
    
    logger.info(f"\nTest voltooid in {time.time() - start_time:.2f} seconden") 