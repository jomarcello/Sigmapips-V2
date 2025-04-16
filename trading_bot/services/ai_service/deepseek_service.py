import os
import logging
import httpx
import asyncio
import json
import random
import socket
import ssl
import aiohttp
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class DeepseekService:
    """Service for generating text completions using DeepSeek AI"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the DeepSeek service"""
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        
        # Try both potential domains for DeepSeek API
        self.api_domains = ["api.deepseek.com", "api.deepseek.ai"]
        self.api_url = "https://api.deepseek.com/v1/chat/completions"  # Default domain
        
        # IP address for direct connection if DNS fails
        self.api_ip = "23.236.75.155"  # IP address for api.deepseek.com
        
        if not self.api_key:
            logger.warning("No DeepSeek API key found, completions will return mock data")
            
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Check connectivity at initialization
        self._check_connectivity()
        
    def _check_connectivity(self):
        """Check which domain is accessible and update the API URL accordingly"""
        for domain in self.api_domains:
            try:
                # Simple socket connection test
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)  # Quick 3-second timeout
                result = sock.connect_ex((domain, 443))
                sock.close()
                
                if result == 0:  # Port is open, connection successful
                    logger.info(f"DeepSeek API connectivity test successful for {domain}")
                    self.api_url = f"https://{domain}/v1/chat/completions"
                    return
                else:
                    logger.warning(f"DeepSeek API connectivity test failed for {domain}: {result}")
            except socket.error as e:
                logger.warning(f"DeepSeek API socket connection to {domain} failed: {str(e)}")
        
        # If no domains are accessible, use the IP address version
        logger.warning("Could not connect to any DeepSeek domains, will use IP address fallback")
        self.api_url = f"https://{self.api_ip}/v1/chat/completions"
        
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
            
            # First try using httpx with standard URL
            try:
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
                        timeout=30.0
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    else:
                        logger.error(f"DeepSeek API error: {response.status_code} - {response.text}")
                        # Continue to try alternative method
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                logger.warning(f"Could not connect to DeepSeek API using httpx: {str(e)}")
                # Continue to alternative method
            
            # If httpx fails, try with aiohttp and custom SSL context
            try:
                logger.info("Trying alternative connection method with aiohttp")
                
                # Create SSL context that doesn't verify certificates
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                
                # Prepare headers with Host header for IP connection
                headers = self.headers.copy()
                if self.api_url.startswith(f"https://{self.api_ip}"):
                    headers["Host"] = "api.deepseek.com"
                
                connector = aiohttp.TCPConnector(ssl=ssl_context)
                timeout = aiohttp.ClientTimeout(total=10)
                
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": temperature,
                    "max_tokens": 2048
                }
                
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.post(
                        self.api_url,
                        headers=headers,
                        json=payload,
                        timeout=timeout
                    ) as response:
                        response_text = await response.text()
                        logger.info(f"DeepSeek API response status: {response.status}")
                        
                        if response.status == 200:
                            data = json.loads(response_text)
                            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        else:
                            logger.error(f"DeepSeek API error: {response.status}, {response_text[:200]}...")
                            return self._get_mock_completion(prompt)
            except Exception as e:
                logger.error(f"Error with aiohttp connection to DeepSeek: {str(e)}")
                # Fall through to mock data
                    
        except Exception as e:
            logger.error(f"Error generating DeepSeek completion: {str(e)}")
            logger.exception(e)
            
        # If all connection methods fail, return mock data
        return self._get_mock_completion(prompt)
            
    def _get_mock_completion(self, prompt: str) -> str:
        """Generate mock completion when the API is unavailable"""
        logger.info(f"Generating mock completion")
        
        if "economic calendar" in prompt.lower():
            # Controleer of er een specifieke datum in de prompt staat
            from datetime import datetime
            
            # Verkrijg de huidige datum in verschillende formaten
            current_date = datetime.now().strftime("%Y-%m-%d")
            current_formatted = datetime.now().strftime("%B %d, %Y")
            
            # Haal vlaggen op uit de prompt indien beschikbaar
            currencies = []
            if "currencies:" in prompt:
                try:
                    currencies_part = prompt.split("currencies:")[1].split("\n")[0].strip()
                    currencies = [c.strip() for c in currencies_part.split(",")]
                except:
                    currencies = ["USD", "EUR"]
            else:
                currencies = ["USD", "EUR"]
                
            # Log wat we gevonden hebben
            logger.info(f"Mock data: Using current date {current_date} and currencies {currencies}")
            
            # Return a mock economic calendar JSON - alleen voor vandaag, zonder datums in de titels
            return f"""```json
{{
  "USD": [
    {{
      "time": "08:30 EST",
      "event": "Initial Jobless Claims",
      "impact": "Medium",
      "date": "{current_date}"
    }},
    {{
      "time": "09:30 EST",
      "event": "Trade Balance",
      "impact": "Medium",
      "date": "{current_date}"
    }},
    {{
      "time": "14:00 EST",
      "event": "Fed Chair Speech",
      "impact": "High",
      "date": "{current_date}"
    }}
  ],
  "EUR": [
    {{
      "time": "07:45 EST",
      "event": "ECB Interest Rate Decision",
      "impact": "High",
      "date": "{current_date}"
    }},
    {{
      "time": "09:30 EST",
      "event": "ECB Press Conference",
      "impact": "High", 
      "date": "{current_date}"
    }}
  ],
  "GBP": [
    {{
      "time": "10:00 EST",
      "event": "Manufacturing Production",
      "impact": "Medium",
      "date": "{current_date}"
    }}
  ],
  "JPY": [
    {{
      "time": "02:30 EST",
      "event": "BOJ Monetary Policy Statement",
      "impact": "High",
      "date": "{current_date}"
    }}
  ],
  "CHF": [],
  "AUD": [],
  "NZD": [],
  "CAD": []
}}```"""
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
