import os
import logging
import httpx
import asyncio
import json
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class TavilyService:
    """Service for performing web searches using Tavily AI"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Tavily service"""
        self.api_key = api_key or os.getenv("TAVILY_API_KEY", "")
        self.api_url = "https://api.tavily.com/search"
        
        if not self.api_key:
            logger.warning("No Tavily API key found, searches will return mock data")
            
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
    async def search(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Perform a web search using Tavily
        
        Args:
            query: The search query
            max_results: Maximum number of results to return
            
        Returns:
            List of search results
        """
        try:
            logger.info(f"Searching Tavily for: {query}")
            
            if not self.api_key:
                return self._get_mock_search_results(query)
                
            # Create the request payload
            payload = {
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_answer": False,
                "include_sources": True,
                "include_images": False
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
                    return data.get("results", [])
                else:
                    logger.error(f"Tavily API error: {response.status_code} - {response.text}")
                    return self._get_mock_search_results(query)
                    
        except Exception as e:
            logger.error(f"Error searching Tavily: {str(e)}")
            logger.exception(e)
            return self._get_mock_search_results(query)
            
    def _get_mock_search_results(self, query: str) -> List[Dict[str, Any]]:
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
