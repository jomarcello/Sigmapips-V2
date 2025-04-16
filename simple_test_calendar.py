import asyncio
import logging
import aiohttp
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

async def test_tradingview_calendar():
    """Test the TradingView calendar API directly"""
    try:
        # Create session
        async with aiohttp.ClientSession() as session:
            # Calculate date range
            start_date = datetime.now()
            end_date = start_date + timedelta(days=0)
            
            # Prepare request parameters
            params = {
                "from": start_date.strftime("%Y-%m-%d"),
                "to": end_date.strftime("%Y-%m-%d"),
                "countries": ["US", "EU", "GB", "JP", "CH", "AU", "NZ", "CA"],
                "importance": ["high", "medium", "low"],
                "limit": 1000,
                "timezone": "UTC"
            }
            
            # Add headers
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://www.tradingview.com",
                "Referer": "https://www.tradingview.com/economic-calendar/",
                "X-Requested-With": "XMLHttpRequest",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive"
            }
            
            # Make request
            url = "https://www.tradingview.com/economic-calendar/api/events"
            logger.info(f"Making request to: {url}")
            logger.info(f"With params: {params}")
            
            async with session.get(url, params=params, headers=headers) as response:
                logger.info(f"Response status: {response.status}")
                logger.info(f"Response headers: {dict(response.headers)}")
                
                if response.status != 200:
                    text = await response.text()
                    logger.error(f"Error response: {text}")
                    return
                    
                data = await response.json()
                logger.info(f"Got {len(data) if isinstance(data, list) else 'non-list'} items")
                logger.info(f"Response data: {data}")
                
    except Exception as e:
        logger.error(f"Error testing calendar: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(test_tradingview_calendar()) 