import os
import logging
import httpx
import asyncio
import json
import socket
import ssl
import aiohttp
from typing import Dict, List, Any, Optional
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

class TavilyService:
    """Service for interacting with the Tavily API"""
    
    def __init__(self, api_key=None, timeout=30):
        """Initialize the Tavily service"""
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = None
        self.timeout = timeout
        self.base_url = "https://api.tavily.com"
        self.mock_sleep_time = 0.1
        
        # Nieuwe API key instellen
        default_api_key = "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"
        
        # Set API key if provided
        if api_key:
            # Ensure the API key has the correct format
            api_key = api_key.strip().replace('\n', '').replace('\r', '')
            
            # Zorg ervoor dat de API key het "tvly-" prefix bevat voor Bearer token authenticatie
            if not api_key.startswith("tvly-"):
                api_key = f"tvly-{api_key}"
                self.logger.info("Added 'tvly-' prefix to API key for Bearer token authentication")
                
            self.api_key = api_key
            masked_key = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else f"{api_key[:4]}..."
            self.logger.info(f"Initialized TavilyService with API key: {masked_key}")
        else:
            # Try to get from environment or use default
            env_api_key = os.environ.get("TAVILY_API_KEY", default_api_key).strip()
            if env_api_key:
                # Ensure the API key has the correct format
                env_api_key = env_api_key.replace('\n', '').replace('\r', '')
                
                # Zorg ervoor dat de API key het "tvly-" prefix bevat voor Bearer token authenticatie
                if not env_api_key.startswith("tvly-"):
                    env_api_key = f"tvly-{env_api_key}"
                    self.logger.info("Added 'tvly-' prefix to API key from environment for Bearer token authentication")
                    
                self.api_key = env_api_key
                masked_key = f"{env_api_key[:8]}...{env_api_key[-4:]}" if len(env_api_key) > 12 else f"{env_api_key[:4]}..."
                self.logger.info(f"Using Tavily API key from environment: {masked_key}")
            else:
                self.api_key = default_api_key
                self.logger.info("Using default Tavily API key")
        
        # Check connectivity (but don't fail if not available)
        self._check_connectivity()
        
    def _check_connectivity(self):
        """Check if we can connect to the Tavily API servers"""
        try:
            self.logger.debug("Checking Tavily API connectivity...")
            resp = requests.head(self.base_url, timeout=2)
            if resp.status_code < 500:
                self.logger.info("Tavily API connection established")
            else:
                self.logger.warning(f"Tavily API returned status code {resp.status_code}")
        except Exception as e:
            self.logger.error(f"Could not connect to Tavily API: {str(e)}")
        
    def _get_headers(self):
        """Get headers for the API request"""
        if not self.api_key:
            self.logger.warning("No API key available for Tavily API request")
            return {}
        
        # Gebruik Bearer authenticatie zoals bewezen werkt in de tests
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        self.logger.info(f"Using Authorization Bearer format for Tavily API")
        return headers
        
    def _handle_response(self, response, return_raw=False):
        """Handle the API response"""
        if response.status_code == 200:
            try:
                data = response.json()
                return data
            except Exception as e:
                self.logger.error(f"Error parsing Tavily API response: {str(e)}")
                if return_raw:
                    return response.text
                return None
        elif response.status_code == 401:
            self.logger.error(f"Unauthorized access to Tavily API. Check API key (status: {response.status_code})")
            # Log additional details about the API key being used
            if self.api_key:
                masked_key = f"{self.api_key[:7]}...{self.api_key[-4:]}" if len(self.api_key) > 11 else f"{self.api_key[:4]}..."
                self.logger.error(f"Using API key: {masked_key}, Key has 'tvly-' prefix: {self.api_key.startswith('tvly-')}")
            else:
                self.logger.error("No API key is set for Tavily service")
            return None
        else:
            self.logger.error(f"Error from Tavily API: {response.status_code} - {response.text}")
            return None
        
    async def search(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Search the web using Tavily API and return the results"""
        try:
            self.logger.info(f"Searching Tavily for: {query}")
            
            # Always reload API key from environment for better testing
            env_api_key = os.environ.get("TAVILY_API_KEY", "")
            if env_api_key and env_api_key != self.api_key:
                self.logger.info(f"Found API key in environment - Current length: {len(env_api_key)}")
                
                # Ensure the API key has the correct format
                env_api_key = env_api_key.strip().replace('\n', '').replace('\r', '')
                
                # Add tvly- prefix if needed for Bearer authentication
                if not env_api_key.startswith("tvly-"):
                    env_api_key = f"tvly-{env_api_key}"
                    self.logger.info("Added 'tvly-' prefix to API key for Bearer authentication")
                
                self.api_key = env_api_key
                masked_key = f"{env_api_key[:8]}...{env_api_key[-4:]}" if len(env_api_key) > 12 else f"{env_api_key[:4]}..."
                self.logger.info(f"Updated Tavily API key from environment: {masked_key}")
            
            # Check API key availability
            if not self.api_key:
                self.logger.warning("No Tavily API key found - using mock data")
                return self._generate_mock_results(query)
            
            # Create a more optimized payload for economic calendar searches
            search_depth = "advanced"
            include_domains = []
            exclude_domains = []
            
            if "economic calendar" in query.lower():
                search_depth = "advanced"
                include_domains = [
                    "forexfactory.com", 
                    "investing.com", 
                    "tradingeconomics.com",
                    "bloomberg.com",
                    "fxstreet.com",
                    "babypips.com"
                ]
            
            payload = {
                "query": query,
                "search_depth": search_depth,
                "include_domains": include_domains,
                "exclude_domains": exclude_domains,
                "max_results": max_results,
                "include_answer": True,
                "include_raw_content": True
            }
            
            # Log the payload for debugging
            self.logger.info(f"Tavily API payload: {json.dumps(payload)}")
            
            # Log headers (masking the API key)
            headers = self._get_headers()
            safe_headers = headers.copy()
            if 'Authorization' in safe_headers:
                auth = safe_headers['Authorization']
                token = auth.split("Bearer ")[1]
                safe_headers['Authorization'] = f"Bearer {token[:8]}...{token[-4:]}" if len(token) > 12 else f"Bearer {token[:4]}..."
            self.logger.info(f"Request headers: {json.dumps(safe_headers)}")
            
            # Try with httpx
            search_url = f"{self.base_url}/search"
            self.logger.info(f"Sending request to Tavily API at {search_url} using httpx")
            
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        search_url,
                        headers=headers,
                        json=payload
                    )
                    
                    self.logger.info(f"Tavily API response status: {response.status_code}")
                    
                    if response.status_code == 200:
                        result = response.json()
                        self.logger.info("Successfully retrieved data from Tavily API")
                        
                        # For debugging, log some of the content
                        if "economic calendar" in query.lower() and result.get("results"):
                            self.logger.info(f"Retrieved {len(result.get('results', []))} results")
                            for idx, item in enumerate(result.get("results", [])[:2]):
                                self.logger.info(f"Result {idx+1} title: {item.get('title')}")
                                content_preview = item.get('content', '')[:100] + "..." if item.get('content') else ""
                                self.logger.info(f"Content preview: {content_preview}")
                        
                        return result.get("results", [])
                    else:
                        self.logger.error(f"Tavily API error: {response.status_code} - {response.text}")
                        
                        # Fall back to mock data on error
                        self.logger.info("Falling back to mock data")
                        return self._generate_mock_results(query)
            except Exception as e:
                self.logger.error(f"Error connecting to Tavily API: {str(e)}")
                self.logger.exception(e)
                self.logger.info(f"Falling back to mock data due to connection error")
                return self._generate_mock_results(query)
                
        except Exception as e:
            self.logger.error(f"Error in Tavily search: {str(e)}")
            self.logger.exception(e)
            return self._generate_mock_results(query)
            
    def _generate_mock_results(self, query: str) -> List[Dict[str, Any]]:
        """Generate mock search results when the API is unavailable"""
        self.logger.info(f"Generating structured mock results for query: {query}")
        
        # Extract meaningful parts from query to generate better mock data
        today = datetime.now().strftime("%B %d, %Y")
        
        # For economic calendar queries, generate structured data
        if "economic calendar" in query.lower():
            # Extract currencies from query if present
            currencies = []
            currency_patterns = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"]
            
            for currency in currency_patterns:
                if currency in query:
                    currencies.append(currency)
            
            if not currencies:
                currencies = ["USD", "EUR", "GBP"]  # Default to major currencies
                
            # Generate appropriate mock data
            return [
                {
                    "title": f"Economic Calendar for {', '.join(currencies)} - {today}",
                    "url": "https://www.forexfactory.com/calendar",
                    "content": self._generate_mock_calendar_text(currencies, today)
                },
                {
                    "title": f"Major Economic Events for {', '.join(currencies)} - {today}",
                    "url": "https://www.investing.com/economic-calendar/",
                    "content": self._generate_mock_event_text(currencies, today)
                }
            ]
        else:
            # For other queries, generate generic results
            return [
                {
                    "title": f"Search Results for {query}",
                    "url": "https://www.example.com/search",
                    "content": f"Mock search results for query: {query}. This is placeholder content used during development."
                }
            ]
    
    def _generate_mock_calendar_text(self, currencies, date):
        """Generate realistic mock economic calendar data"""
        result = f"Economic Calendar for {', '.join(currencies)} on {date}:\n\n"
        
        # Common economic events
        events = {
            "USD": [
                {"time": "08:30", "event": "Non-Farm Payrolls", "impact": "High"},
                {"time": "10:00", "event": "ISM Manufacturing PMI", "impact": "High"},
                {"time": "14:00", "event": "FOMC Statement", "impact": "High"},
                {"time": "12:30", "event": "Retail Sales m/m", "impact": "Medium"}
            ],
            "EUR": [
                {"time": "09:00", "event": "CPI y/y", "impact": "High"},
                {"time": "10:00", "event": "ECB Press Conference", "impact": "High"},
                {"time": "08:30", "event": "Manufacturing PMI", "impact": "Medium"}
            ],
            "GBP": [
                {"time": "09:30", "event": "BOE Interest Rate Decision", "impact": "High"},
                {"time": "11:00", "event": "Manufacturing PMI", "impact": "Medium"},
                {"time": "07:00", "event": "GDP m/m", "impact": "High"}
            ],
            "JPY": [
                {"time": "00:30", "event": "Tokyo Core CPI y/y", "impact": "Medium"},
                {"time": "01:00", "event": "BOJ Policy Rate", "impact": "High"}
            ],
            "AUD": [
                {"time": "02:30", "event": "RBA Interest Rate Decision", "impact": "High"},
                {"time": "01:30", "event": "Employment Change", "impact": "High"}
            ],
            "CAD": [
                {"time": "13:30", "event": "Employment Change", "impact": "High"},
                {"time": "15:00", "event": "BOC Rate Statement", "impact": "High"}
            ],
            "CHF": [
                {"time": "08:30", "event": "CPI m/m", "impact": "Medium"},
                {"time": "09:30", "event": "SNB Monetary Policy Assessment", "impact": "High"}
            ],
            "NZD": [
                {"time": "03:00", "event": "RBNZ Interest Rate Decision", "impact": "High"},
                {"time": "22:45", "event": "GDP q/q", "impact": "High"}
            ]
        }
        
        # Add calendar data for each currency
        for currency in currencies:
            if currency in events:
                result += f"\n{currency} Events:\n"
                for event in events[currency]:
                    result += f"{event['time']} - {event['event']} - Impact: {event['impact']}\n"
        
        return result
    
    def _generate_mock_event_text(self, currencies, date):
        """Generate detailed mock event descriptions"""
        result = f"Major Economic Events and Analysis for {', '.join(currencies)} on {date}:\n\n"
        
        # Common analyses
        analyses = {
            "USD": "The USD faces significant volatility today with the release of Non-Farm Payrolls data. Analysts expect a figure around 180K new jobs, which could strengthen the dollar if exceeded. The FOMC statement later in the day will be closely watched for hints about future rate decisions.",
            "EUR": "The Euro will be focused on inflation data and the ECB Press Conference. Any indication of continued high inflation could suggest further rate hikes, potentially strengthening the currency against its peers.",
            "GBP": "The Bank of England's interest rate decision is the key event for the GBP today. Markets have priced in a hold, but comments about future policy direction will be crucial for sterling's performance.",
            "JPY": "The Japanese Yen may see movement based on Tokyo CPI data, which serves as a leading indicator for nationwide trends. The BOJ remains dovish compared to other central banks, keeping pressure on the currency.",
            "AUD": "The RBA's policy stance will drive AUD movement today. Labor market data remains strong, though concerns about China's economic slowdown continue to weigh on the currency's outlook.",
            "CAD": "Canadian employment figures will be crucial for CAD direction today. The Bank of Canada's commentary on inflation and economic growth will also impact the loonie's performance against major peers.",
            "CHF": "The Swiss Franc continues to act as a safe haven amid global uncertainty. The SNB's assessment will provide insight into how officials view current economic conditions and inflation trends.",
            "NZD": "The New Zealand dollar faces volatility with the RBNZ decision. Recent economic data has been mixed, creating uncertainty about the central bank's future policy path."
        }
        
        # Add detailed analysis for each currency
        for currency in currencies:
            if currency in analyses:
                result += f"\n{currency} Analysis:\n{analyses[currency]}\n"
        
        return result

    async def search_internet(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """Search the internet using Tavily API and return the results"""
        try:
            self.logger.info(f"Searching internet with Tavily for: {query}")
            
            # Refresh API key from environment
            env_api_key = os.environ.get("TAVILY_API_KEY", "")
            if env_api_key and env_api_key != self.api_key:
                self.logger.info(f"Found new API key in environment for internet search - Current length: {len(env_api_key)}")
                
                # Ensure the API key has the correct format
                env_api_key = env_api_key.strip().replace('\n', '').replace('\r', '')
                
                # Add tvly- prefix if needed for Bearer authentication
                if not env_api_key.startswith("tvly-"):
                    env_api_key = f"tvly-{env_api_key}"
                    self.logger.info("Added 'tvly-' prefix to API key for Bearer authentication")
                
                self.api_key = env_api_key
                masked_key = f"{env_api_key[:8]}...{env_api_key[-4:]}" if len(env_api_key) > 12 else f"{env_api_key[:4]}..."
                self.logger.info(f"Updated Tavily API key from environment for internet search: {masked_key}")
            
            # Check API key availability
            if not self.api_key:
                self.logger.warning("No Tavily API key found - using mock data for internet search")
                return {"results": self._generate_mock_results(query)}
            
            # Create a payload specifically for internet search
            payload = {
                "query": query,
                "search_depth": "advanced",
                "include_domains": [],
                "exclude_domains": [],
                "max_results": max_results,
                "include_answer": True,
                "include_raw_content": True
            }
            
            # Log the payload for debugging
            self.logger.info(f"Tavily internet search payload: {json.dumps(payload)}")
            
            # Log headers (masking the API key)
            headers = self._get_headers()
            safe_headers = headers.copy()
            if 'Authorization' in safe_headers:
                auth = safe_headers['Authorization']
                token = auth.split("Bearer ")[1]
                safe_headers['Authorization'] = f"Bearer {token[:8]}...{token[-4:]}" if len(token) > 12 else f"Bearer {token[:4]}..."
            self.logger.info(f"Internet search request headers: {json.dumps(safe_headers)}")
            
            try:
                search_url = f"{self.base_url}/search"
                self.logger.info(f"Sending request to Tavily API at {search_url} for internet search")
                
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        search_url,
                        headers=headers,
                        json=payload
                    )
                    
                    self.logger.info(f"Tavily internet search response status: {response.status_code}")
                    
                    if response.status_code == 200:
                        result = response.json()
                        self.logger.info(f"Successfully retrieved results from Tavily internet search")
                        
                        # Log example results
                        if result and result.get('results'):
                            self.logger.info(f"Found {len(result.get('results', []))} results")
                            for idx, item in enumerate(result.get('results', [])[:2]):
                                self.logger.info(f"Result {idx+1} title: {item.get('title', 'No title')}")
                                content_preview = item.get('content', '')[:100] + "..." if item.get('content') else ""
                                self.logger.info(f"Content preview: {content_preview}")
                                
                        return result
                    else:
                        self.logger.error(f"Tavily internet search API error: {response.status_code}")
                        self.logger.error(f"Error response: {response.text[:300]}...")
                        
                        # Fall back to mock data on error
                        self.logger.info("Falling back to mock data for internet search")
                        return {"results": self._generate_mock_results(query)}
                        
            except Exception as e:
                self.logger.error(f"Error connecting to Tavily internet search API: {str(e)}")
                self.logger.exception(e)
                return {"results": self._generate_mock_results(query)}
                
        except Exception as e:
            self.logger.error(f"Error in Tavily internet search: {str(e)}")
            self.logger.exception(e)
            return {"results": self._generate_mock_results(query)} 
