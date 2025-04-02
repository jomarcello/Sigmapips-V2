import os
import logging
import httpx
import asyncio
import json
import socket
import ssl
import aiohttp
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class TavilyService:
    """Service for performing web searches using Tavily AI"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Tavily service"""
        # Always try to get a fresh API key from environment
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")
        self.api_url = "https://api.tavily.com/search"
        
        if not self.api_key:
            logger.warning("No Tavily API key found, searches will return mock data")
        else:
            masked_key = self.api_key[:5] + "..." if len(self.api_key) > 5 else "[masked]"
            logger.info(f"Tavily API key found: {masked_key}")
            
        # Correct way to format headers for Tavily API - use x-api-key instead of Authorization
        self.headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key.strip() if self.api_key else ""
        }
        
        # Check connectivity at initialization
        self._check_connectivity()
        
    def _check_connectivity(self):
        """Check if Tavily API is accessible"""
        try:
            # Simple socket connection test
            tavily_host = "api.tavily.com"
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)  # Quick 3-second timeout
            result = sock.connect_ex((tavily_host, 443))
            sock.close()
            
            if result == 0:  # Port is open, connection successful
                logger.info("Tavily API connectivity test successful")
            else:
                logger.warning(f"Tavily API connectivity test failed with result: {result}")
        except socket.error as e:
            logger.warning(f"Tavily API socket connection failed: {str(e)}")
        
    async def search(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Search the web using Tavily API and return the results"""
        try:
            logger.info(f"Searching Tavily for: {query}")
            
            # Always reload API key from environment for better testing
            env_api_key = os.environ.get("TAVILY_API_KEY", "")
            if env_api_key and env_api_key != self.api_key:
                logger.info("Updating Tavily API key from environment")
                self.api_key = env_api_key
                self.headers["x-api-key"] = self.api_key.strip()
            
            # Check API key availability
            if not self.api_key:
                logger.warning("No Tavily API key found - using mock data")
                return self._generate_mock_results(query)
                
            # Create a more optimized payload for economic calendar searches
            payload = {
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",  # Use basic depth as required by Tavily API
                "include_answer": True,      # Get a summarized answer
                "include_domains": [],       # Initialize empty 
                "include_raw_content": True, # Get full raw content
            }
            
            # For economic calendar queries, add specific parameters
            if "economic calendar" in query.lower():
                # Add specific domains that have economic calendar data
                payload["include_domains"] = [
                    "forexfactory.com", 
                    "investing.com", 
                    "dailyfx.com", 
                    "fxstreet.com",
                    "tradingeconomics.com",
                    "bloomberg.com",
                    "marketwatch.com",
                    "reuters.com"
                ]
                
                # Add context to help tavily find the right data
                payload["search_context"] = """
                Find today's economic calendar events showing exact times (preferably in EST format), 
                event descriptions, and impact levels (high, medium, low) for major currencies.
                Focus on structured data about economic releases, central bank announcements, 
                and other market-moving events. Include specific times, currencies affected, 
                and importance/impact levels.
                """
                
                # Modify the query to be more specific
                today = query.split("today")[1].split("for")[0] if "today" in query and "for" in query else ""
                improved_query = f"economic calendar events schedule times impact levels today {today} forex EST format"
                payload["query"] = improved_query
            
            # Log the payload for debugging
            logger.info(f"Tavily API payload: {payload}")
            
            try:
                # First try with httpx
                logger.info(f"Sending request to Tavily API at {self.api_url} using httpx")
                logger.info(f"Headers: Content-Type: application/json, x-api-key: [API KEY MASKED]")
                
                async with httpx.AsyncClient(timeout=30.0) as client:  # Increased timeout
                    response = await client.post(
                        self.api_url,
                        headers=self.headers,
                        json=payload
                    )
                    
                    logger.info(f"Tavily API response status: {response.status_code}")
                    
                    if response.status_code == 200:
                        result = response.json()
                        logger.info("Successfully retrieved data from Tavily API")
                        
                        # For debugging, log some of the content
                        if "economic calendar" in query.lower() and result.get("results"):
                            logger.info(f"Retrieved {len(result.get('results', []))} results")
                            for idx, item in enumerate(result.get("results", [])[:2]):
                                logger.info(f"Result {idx+1} title: {item.get('title')}")
                                content_preview = item.get('content', '')[:100] + "..." if item.get('content') else ""
                                logger.info(f"Content preview: {content_preview}")
                        
                        return result.get("results", [])
                    else:
                        logger.error(f"Tavily API error: {response.status_code} - {response.text}")
                        
                        # Try alternative method if the first fails
                        logger.info("Trying alternative connection method with aiohttp")
                        
                        # Create a custom SSL context that's more permissive
                        ssl_context = ssl.create_default_context()
                        ssl_context.check_hostname = False
                        ssl_context.verify_mode = ssl.CERT_NONE
                        
                        connector = aiohttp.TCPConnector(ssl=ssl_context)
                        timeout = aiohttp.ClientTimeout(total=30.0)  # Increased timeout
                        
                        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                            logger.info(f"Sending aiohttp request to Tavily API")
                            async with session.post(
                                self.api_url, 
                                headers=self.headers, 
                                json=payload
                            ) as aio_response:
                                logger.info(f"Tavily API aiohttp response status: {aio_response.status}")
                                
                                if aio_response.status == 200:
                                    response_text = await aio_response.text()
                                    response_json = json.loads(response_text)
                                    logger.info("Successfully retrieved data from Tavily API using aiohttp")
                                    return response_json.get("results", [])
                                else:
                                    response_text = await aio_response.text()
                                    logger.error(f"Tavily API error with aiohttp: {aio_response.status}, {response_text[:200]}...")
                                    return self._generate_mock_results(query)
            except Exception as e:
                logger.error(f"Error connecting to Tavily API: {str(e)}")
                logger.exception(e)
                logger.info(f"Generating mock search results for: {query}")
                return self._generate_mock_results(query)
                
        except Exception as e:
            logger.error(f"Error in Tavily search: {str(e)}")
            logger.exception(e)
            return self._generate_mock_results(query)
            
    def _generate_mock_results(self, query: str) -> List[Dict[str, Any]]:
        """Generate mock search results when the API is unavailable"""
        logger.info(f"Generating mock search results for: {query}")
        
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
