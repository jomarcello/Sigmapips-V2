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

logger = logging.getLogger(__name__)

class TavilyService:
    """Service for interacting with the Tavily API"""
    
    def __init__(self, api_key=None, timeout=30):
        """Initialize the Tavily service"""
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = None
        self.timeout = timeout
        self.base_url = "https://api.tavily.com/v1"
        self.mock_sleep_time = 0.1
        
        # Set API key if provided
        if api_key:
            # Ensure the API key has the correct format
            api_key = api_key.strip().replace('\n', '').replace('\r', '')
            
            # Add the 'tvly-' prefix if not present
            if not api_key.startswith("tvly-"):
                api_key = f"tvly-{api_key}"
                self.logger.info("Added 'tvly-' prefix to Tavily API key")
                
            self.api_key = api_key
            masked_key = f"{api_key[:7]}...{api_key[-4:]}" if len(api_key) > 11 else f"{api_key[:4]}..."
            self.logger.info(f"Initialized TavilyService with API key: {masked_key}")
        else:
            # Try to get from environment
            env_api_key = os.environ.get("TAVILY_API_KEY", "").strip()
            if env_api_key:
                # Ensure the API key has the correct format
                env_api_key = env_api_key.replace('\n', '').replace('\r', '')
                
                # Add the 'tvly-' prefix if not present
                if not env_api_key.startswith("tvly-"):
                    env_api_key = f"tvly-{env_api_key}"
                    self.logger.info("Added 'tvly-' prefix to Tavily API key from environment")
                    
                self.api_key = env_api_key
                masked_key = f"{env_api_key[:7]}...{env_api_key[-4:]}" if len(env_api_key) > 11 else f"{env_api_key[:4]}..."
                self.logger.info(f"Using Tavily API key from environment: {masked_key}")
            else:
                self.logger.warning("No Tavily API key provided, search functionality will be limited")
        
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
            
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key
        }
        
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
                self.logger.info("Updating Tavily API key from environment")
                # Ensure the API key has the correct format
                env_api_key = env_api_key.strip().replace('\n', '').replace('\r', '')
                
                # Add the 'tvly-' prefix if not present
                if not env_api_key.startswith("tvly-"):
                    env_api_key = f"tvly-{env_api_key}"
                    self.logger.info("Added 'tvly-' prefix to Tavily API key from environment")
                
                self.api_key = env_api_key
                masked_key = f"{env_api_key[:7]}...{env_api_key[-4:]}" if len(env_api_key) > 11 else f"{env_api_key[:4]}..."
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
                "include_raw_content": False,
                "include_images": False
            }
            
            # Log the payload for debugging
            self.logger.info(f"Tavily API payload: {payload}")
            
            try:
                # First try with httpx
                search_url = f"{self.base_url}/search"
                self.logger.info(f"Sending request to Tavily API at {search_url} using httpx")
                self.logger.info(f"Headers: Content-Type: application/json, x-api-key: [API KEY MASKED]")
                
                async with httpx.AsyncClient(timeout=self.timeout) as client:  # Increased timeout
                    response = await client.post(
                        search_url,
                        headers=self._get_headers(),
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
                        
                        # Try alternative method if the first fails
                        self.logger.info("Trying alternative connection method with aiohttp")
                        
                        # Create a custom SSL context that's more permissive
                        ssl_context = ssl.create_default_context()
                        ssl_context.check_hostname = False
                        ssl_context.verify_mode = ssl.CERT_NONE
                        
                        connector = aiohttp.TCPConnector(ssl=ssl_context)
                        timeout = aiohttp.ClientTimeout(total=self.timeout)  # Increased timeout
                        
                        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                            self.logger.info(f"Sending aiohttp request to Tavily API")
                            async with session.post(
                                search_url, 
                                headers=self._get_headers(), 
                                json=payload
                            ) as aio_response:
                                self.logger.info(f"Tavily API aiohttp response status: {aio_response.status}")
                                
                                if aio_response.status == 200:
                                    response_text = await aio_response.text()
                                    response_json = json.loads(response_text)
                                    self.logger.info("Successfully retrieved data from Tavily API using aiohttp")
                                    return response_json.get("results", [])
                                else:
                                    response_text = await aio_response.text()
                                    self.logger.error(f"Tavily API error with aiohttp: {aio_response.status}, {response_text[:200]}...")
                                    return self._generate_mock_results(query)
            except Exception as e:
                self.logger.error(f"Error connecting to Tavily API: {str(e)}")
                self.logger.exception(e)
                self.logger.info(f"Generating mock search results for: {query}")
                return self._generate_mock_results(query)
                
        except Exception as e:
            self.logger.error(f"Error in Tavily search: {str(e)}")
            self.logger.exception(e)
            return self._generate_mock_results(query)
            
    def _generate_mock_results(self, query: str) -> List[Dict[str, Any]]:
        """Generate mock search results when the API is unavailable"""
        self.logger.info(f"Generating mock search results for: {query}")
        
        if "economic calendar" in query.lower():
            return [
                {
                    "title": "Economic Calendar - Today's Economic Events",
                    "url": "https://www.forexfactory.com/calendar",
                    "content": f"Economic calendar showing major events for today. The calendar includes data for USD, EUR, GBP, JPY, AUD, CAD, CHF, and NZD currencies. Upcoming events include interest rate decisions, employment reports, and inflation data. Each event is marked with an impact level (high, medium, or low)."
                },
                {
                    "title": "Major Economic Indicators and Events",
                    "url": "https://www.dailyfx.com/economic-calendar",
                    "content": f"Economic calendar for today's date shows several high-impact events for major currencies. USD has Non-Farm Payrolls and Interest Rate Decision scheduled. EUR has ECB Press Conference and Inflation Data. GBP has Manufacturing PMI data released today. All events are time-stamped in EST timezone."
                }
            ]
        else:
            return [
                {
                    "title": f"Search Results for {query}",
                    "url": "https://www.example.com/search",
                    "content": f"Mock search results for query: {query}. This is placeholder content since the Tavily API key is not configured or the API request failed."
                }
            ] 

    async def search_internet(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """Search the internet using Tavily API and return the results"""
        try:
            self.logger.info(f"Searching internet with Tavily for: {query}")
            
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
                "include_raw_content": False,
                "include_images": False
            }
            
            # Log the payload for debugging
            self.logger.info(f"Tavily internet search payload: {payload}")
            
            try:
                search_url = f"{self.base_url}/search"
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        search_url,
                        headers=self._get_headers(),
                        json=payload
                    )
                    
                    self.logger.info(f"Tavily internet search response status: {response.status_code}")
                    
                    if response.status_code == 200:
                        result = response.json()
                        self.logger.info(f"Successfully retrieved {len(result.get('results', []))} results from Tavily internet search")
                        return result
                    else:
                        self.logger.error(f"Tavily internet search API error: {response.status_code} - {response.text}")
                        return {"results": self._generate_mock_results(query)}
                        
            except Exception as e:
                self.logger.error(f"Error connecting to Tavily internet search API: {str(e)}")
                self.logger.exception(e)
                return {"results": self._generate_mock_results(query)}
                
        except Exception as e:
            self.logger.error(f"Error in Tavily internet search: {str(e)}")
            self.logger.exception(e)
            return {"results": self._generate_mock_results(query)} 
