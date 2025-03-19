--- a/Users/jovannitilborg/Downloads/sentiment.py
+++ b/Users/jovannitilborg/Downloads/sentiment.py
@@ -144,7 +144,7 @@
             }
 
     async def get_market_sentiment_html(self, instrument: str) -> str:
-      #... rest of the class
+        pass # this is a placeholder, add code here when ready
     def _get_mock_sentiment(self, instrument):
         #... rest of the class
 
@@ -170,127 +170,127 @@
             retuimport os
             import ssl
             import asyncio
-            import logging
-            import aiohttp
-            import re
-            import random
-            
-            logger = logging.getLogger(__name__)
-            
-            class MarketSentimentService:
-                def __init__(self):
-                    """Initialize the MarketSentimentService."""
-                    self.session = None  # Initialize session to None
-            
-                async def _initialize_session(self):
-                    """Initialize aiohttp session if not already initialized."""
-                    if self.session is None:
-                        ssl_context = ssl.create_default_context()
-                        ssl_context.check_hostname = False
-                        ssl_context.verify_mode = ssl.CERT_NONE
-                        self.session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context))
-            
-                async def close_session(self):
-                    """Close the aiohttp session."""
-                    if self.session:
-                        await self.session.close()
-                        self.session = None
-            
-                async def get_market_sentiment(self, instrument: str) -> dict:
-                    """Get market sentiment data for a specific instrument."""
-                    await self._initialize_session()  # Ensure session is initialized
-                    instrument = instrument.upper()
-            
-                    # Define instrument-specific URLs and selectors (adjust as needed)
-                    url_mapping = {
-                        "EURUSD": ("https://www.dailyfx.com/eur-usd", ".dfx-market-sentiment-article-content"),
-                        "GBPUSD": ("https://www.dailyfx.com/gbp-usd", ".dfx-market-sentiment-article-content"),
-                        "USDJPY": ("https://www.dailyfx.com/usd-jpy", ".dfx-market-sentiment-article-content"),
-                        "XAUUSD": ("https://www.dailyfx.com/gold-xau-usd", ".dfx-market-sentiment-article-content"),
-                        "XAGUSD": ("https://www.dailyfx.com/silver-xag-usd", ".dfx-market-sentiment-article-content"),
-                        "AUDUSD":("https://www.dailyfx.com/aud-usd", ".dfx-market-sentiment-article-content"),
-                        "USDCAD":("https://www.dailyfx.com/usd-cad", ".dfx-market-sentiment-article-content"),
-                        "USDCHF":("https://www.dailyfx.com/usd-chf", ".dfx-market-sentiment-article-content"),
-                        "EURGBP":("https://www.dailyfx.com/eur-gbp", ".dfx-market-sentiment-article-content"),
-                        "EURJPY":("https://www.dailyfx.com/eur-jpy", ".dfx-market-sentiment-article-content")
-            
-                    }
-            
-                    if instrument in url_mapping:
-                        url, selector = url_mapping[instrument]
-                        try:
-                            html = await self.get_market_sentiment_html(url)
-                            if html:
-                                sentiment_data = self._parse_sentiment_data(html, selector, instrument)
-                                return sentiment_data
-                            else:
-                                return self._get_mock_sentiment(instrument)
-                        except Exception as e:
-                            logger.error(f"Error fetching/parsing market sentiment for {instrument}: {e}")
-                            return self._get_mock_sentiment(instrument)
-                    else:
-                        logger.warning(f"No sentiment data found for instrument: {instrument}")
-                        return self._get_mock_sentiment(instrument)
-            
-                async def get_market_sentiment_html(self, url: str) -> str:
-                    """Fetch the HTML content of a URL."""
-                    try:
-                        async with self.session.get(url) as response:
-                            response.raise_for_status()  # Raise an exception for bad status codes
-                            return await response.text()
-                    except aiohttp.ClientError as e:
-                        logger.error(f"Error fetching URL {url}: {e}")
-                        return None
-                
-                def _parse_sentiment_data(self, html: str, selector: str, instrument: str) -> dict:
-                    """Parse sentiment data from HTML content."""
-                    if not html:
-                        return self._get_mock_sentiment(instrument)
-            
-                    # Extract relevant text using regex
-                    text_match = re.search(r"<div class=\"dfx-market-sentiment-article-content\">(.+?)</div>", html, re.DOTALL)
-                    if text_match:
-                        text_content = text_match.group(1)
-                        cleaned_text = re.sub(r"<[^>]+>", "", text_content).strip()
-                    else:
-                        return self._get_mock_sentiment(instrument)
-                    
-                    # Parse bullish/bearish sentiment (adjust regex patterns as needed)
-                    bullish_match = re.search(r"Bullish\s*(\d+%?)", cleaned_text)
-                    bearish_match = re.search(r"Bearish\s*(\d+%?)", cleaned_text)
-            
-                    # Get the recommendation using the parse_recommendation method
-                    recommendation = self._parse_recommendation(cleaned_text)
-            
-                    bullish_percentage = int(bullish_match.group(1).replace('%', '')) if bullish_match else 50
-                    bearish_percentage = int(bearish_match.group(1).replace('%', '')) if bearish_match else 50
-                    overall_sentiment = "bullish" if bullish_percentage > bearish_percentage else "bearish" if bearish_percentage > bullish_percentage else "neutral"
-                    sentiment_score = bullish_percentage - bearish_percentage
-            
-                    # Parse additional information (adjust regex patterns as needed)
-                    trend_strength_match = re.search(r"(Strong|Moderate|Weak)\s+Trend", cleaned_text)
-                    trend_strength = trend_strength_match.group(1) if trend_strength_match else "Moderate"
-                    volatility_match = re.search(r"(High|Moderate|Low)\s+Volatility", cleaned_text)
-                    volatility = volatility_match.group(1) if volatility_match else "Moderate"
-            
-                    support_level = "Not available"
-                    resistance_level = "Not available"
-            
-                    # Create the sentiment data dictionary
-                    sentiment_data = {
-                        "instrument": instrument,
-                        "bullish_percentage": bullish_percentage,
-                        "bearish_percentage": bearish_percentage,
-                        "overall_sentiment": overall_sentiment,
-                        "sentiment_score": sentiment_score,
-                        "trend_strength": trend_strength,
-                        "volatility": volatility,
-                        "support_level": support_level,
-                        "resistance_level": resistance_level,
-                        "recommendation": recommendation,
-                        "analysis": self._parse_analysis(cleaned_text),
-                    }
-            
-                    return sentiment_data
-            
-                def _get_mock_sentiment(self, instrument):
-                    """Generate mock sentiment data for testing."""
-                    overall_sentiments = ["bullish", "bearish", "neutral"]
-                    mock_overall_sentiment = random.choice(overall_sentiments)
-            
-                    if mock_overall_sentiment == "bullish":
-                        bullish_percentage = random.randint(60, 90)
-                        bearish_percentage = 100 - bullish_percentage
-                    elif mock_overall_sentiment == "bearish":
-                        bearish_percentage = random.randint(60, 90)
-                        bullish_percentage = 100 - bearish_percentage
-                    else:
-                        bullish_percentage = random.randint(30, 70)
-                        bearish_percentage = 100 - bullish_percentage
-                    
-                    mock_data = {
-                        "instrument": instrument,
-                        "bullish_percentage": bullish_percentage,
-                        "bearish_percentage": bearish_percentage,
-                        "overall_sentiment": mock_overall_sentiment,
-                        "sentiment_score": bullish_percentage - bearish_percentage,
-                        "trend_strength": random.choice(["Strong", "Moderate", "Weak"]),
-                        "volatility": random.choice(["High", "Moderate", "Low"]),
-                        "support_level": "Not available",
-                        "resistance_level": "Not available",
-                        "recommendation": random.choice(["Consider buying opportunities.", "Consider selling or shorting opportunities.", "Wait for clearer market signals."]),
-                        "analysis": "Detailed analysis not available"
-                    }
-            
-                    return mock_data
-                
-                def _parse_analysis(self, text: str) -> str:
-                    """Parse detailed analysis from text."""
-                    if "bullish" in text.lower():
-                         analysis = "The market sentiment is generally bullish, suggesting potential buying opportunities."
-                    elif "bearish" in text.lower() or "short" in text.lower():
-                        analysis = "The market sentiment is generally bearish, indicating potential selling or shorting opportunities."
-                    else:
-                        analysis = "The market sentiment is neutral, suggesting a wait-and-see approach."
-            
-                    return analysis
-                
-                def _parse_recommendation(self, text: str) -> str:
-                    """Parse trading recommendation from text."""
-                    if "buy" in text.lower():
-                        return "Consider buying opportunities."
-                    elif "sell" in text.lower() or "short" in text.lower():
-                        return "Consider selling or shorting opportunities."
-                    else:
-                        return "Wait for clearer market signals."
-            rn "Low"
- 
-     def _parse_recommendation(self, text: str) -> str:
-+            import logging
+            import aiohttp
+            import re
+            import random
+
+
+logger = logging.getLogger(__name__)
+
+class MarketSentimentService:
+    def __init__(self):
+        """Initialize the MarketSentimentService."""
+        self.session = None  # Initialize session to None
+
+    async def _initialize_session(self):
+        """Initialize aiohttp session if not already initialized."""
+        if self.session is None:
+            ssl_context = ssl.create_default_context()
+            ssl_context.check_hostname = False
+            ssl_context.verify_mode = ssl.CERT_NONE
+            self.session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context))
+
+    async def close_session(self):
+        """Close the aiohttp session."""
+        if self.session:
+            await self.session.close()
+            self.session = None
+
+    async def get_market_sentiment(self, instrument: str) -> dict:
+        """Get market sentiment data for a specific instrument."""
+        await self._initialize_session()  # Ensure session is initialized
+        instrument = instrument.upper()
+
+        # Define instrument-specific URLs and selectors (adjust as needed)
+        url_mapping = {
+            "EURUSD": ("https://www.dailyfx.com/eur-usd", ".dfx-market-sentiment-article-content"),
+            "GBPUSD": ("https://www.dailyfx.com/gbp-usd", ".dfx-market-sentiment-article-content"),
+            "USDJPY": ("https://www.dailyfx.com/usd-jpy", ".dfx-market-sentiment-article-content"),
+            "XAUUSD": ("https://www.dailyfx.com/gold-xau-usd", ".dfx-market-sentiment-article-content"),
+            "XAGUSD": ("https://www.dailyfx.com/silver-xag-usd", ".dfx-market-sentiment-article-content"),
+            "AUDUSD": ("https://www.dailyfx.com/aud-usd", ".dfx-market-sentiment-article-content"),
+            "USDCAD": ("https://www.dailyfx.com/usd-cad", ".dfx-market-sentiment-article-content"),
+            "USDCHF": ("https://www.dailyfx.com/usd-chf", ".dfx-market-sentiment-article-content"),
+            "EURGBP": ("https://www.dailyfx.com/eur-gbp", ".dfx-market-sentiment-article-content"),
+            "EURJPY": ("https://www.dailyfx.com/eur-jpy", ".dfx-market-sentiment-article-content")
+
+        }
+
+        if instrument in url_mapping:
+            url, selector = url_mapping[instrument]
+            try:
+                html = await self.get_market_sentiment_html(url)
+                if html:
+                    sentiment_data = self._parse_sentiment_data(html, selector, instrument)
+                    return sentiment_data
+                else:
+                    return self._get_mock_sentiment(instrument)
+            except Exception as e:
+                logger.error(f"Error fetching/parsing market sentiment for {instrument}: {e}")
+                return self._get_mock_sentiment(instrument)
+        else:
+            logger.warning(f"No sentiment data found for instrument: {instrument}")
+            return self._get_mock_sentiment(instrument)
+
+    async def get_market_sentiment_html(self, url: str) -> str:
+        """Fetch the HTML content of a URL."""
+        try:
+            async with self.session.get(url) as response:
+                response.raise_for_status()  # Raise an exception for bad status codes
+                return await response.text()
+        except aiohttp.ClientError as e:
+            logger.error(f"Error fetching URL {url}: {e}")
+            return None
+
+    def _parse_sentiment_data(self, html: str, selector: str, instrument: str) -> dict:
+        """Parse sentiment data from HTML content."""
+        if not html:
+            return self._get_mock_sentiment(instrument)
+
+        # Extract relevant text using regex
+        text_match = re.search(r"<div class=\"dfx-market-sentiment-article-content\">(.+?)</div>", html, re.DOTALL)
+        if text_match:
+            text_content = text_match.group(1)
+            cleaned_text = re.sub(r"<[^>]+>", "", text_content).strip()
+        else:
+            return self._get_mock_sentiment(instrument)
+
+        # Parse bullish/bearish sentiment (adjust regex patterns as needed)
+        bullish_match = re.search(r"Bullish\s*(\d+%?)", cleaned_text)
+        bearish_match = re.search(r"Bearish\s*(\d+%?)", cleaned_text)
+
+        # Get the recommendation using the parse_recommendation method
+        recommendation = self._parse_recommendation(cleaned_text)
+
+        bullish_percentage = int(bullish_match.group(1).replace('%', '')) if bullish_match else 50
+        bearish_percentage = int(bearish_match.group(1).replace('%', '')) if bearish_match else 50
+        overall_sentiment = "bullish" if bullish_percentage > bearish_percentage else "bearish" if bearish_percentage > bullish_percentage else "neutral"
+        sentiment_score = bullish_percentage - bearish_percentage
+
+        # Parse additional information (adjust regex patterns as needed)
+        trend_strength_match = re.search(r"(Strong|Moderate|Weak)\s+Trend", cleaned_text)
+        trend_strength = trend_strength_match.group(1) if trend_strength_match else "Moderate"
+        volatility_match = re.search(r"(High|Moderate|Low)\s+Volatility", cleaned_text)
+        volatility = volatility_match.group(1) if volatility_match else "Moderate"
+
+        support_level = "Not available"
+        resistance_level = "Not available"
+
+        # Create the sentiment data dictionary
+        sentiment_data = {
+            "instrument": instrument,
+            "bullish_
