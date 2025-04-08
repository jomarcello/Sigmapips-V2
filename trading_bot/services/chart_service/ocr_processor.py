import os
import logging
import re
import base64
import json
import aiohttp
from typing import Dict, Any, Optional, List
import random
from google.cloud import vision
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

class ChartOCRProcessor:
    """Process chart images using OCR to extract price and indicator data"""
    
    def __init__(self):
        """Initialize the OCR processor"""
        # Initialize Google Vision client
        try:
            # First check if credentials are provided as env var JSON
            credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
            credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "google_vision_credentials.json")
            
            logger.info(f"GOOGLE_APPLICATION_CREDENTIALS path: {credentials_path}")
            
            # If we have JSON credentials in env var, write them to a file
            if credentials_json:
                logger.info("Found Google credentials in environment variable, writing to file")
                try:
                    os.makedirs(os.path.dirname(credentials_path), exist_ok=True)
                    with open(credentials_path, 'w') as f:
                        f.write(credentials_json)
                    logger.info(f"Credentials file created at: {credentials_path}")
                except Exception as write_error:
                    logger.error(f"Failed to write credentials file: {str(write_error)}")
                    logger.error(f"Current working directory: {os.getcwd()}")
                    logger.error(f"Directory listing of /app: {os.listdir('/app')}")
            else:
                logger.warning("No GOOGLE_CREDENTIALS_JSON environment variable found")
            
            logger.info(f"Checking if credentials file exists at: {credentials_path}")
            if os.path.exists(credentials_path):
                logger.info(f"Credentials file found, size: {os.path.getsize(credentials_path)} bytes")
                with open(credentials_path, 'r') as f:
                    logger.info(f"First few characters of credentials file: {f.read()[:50]}...")
                
                credentials = service_account.Credentials.from_service_account_file(
                    credentials_path,
                    scopes=['https://www.googleapis.com/auth/cloud-platform']
                )
                self.vision_client = vision.ImageAnnotatorClient(credentials=credentials)
                logger.info("Google Vision client initialized successfully")
            else:
                logger.error(f"Google Vision credentials file not found at: {credentials_path}")
                logger.error(f"Current working directory: {os.getcwd()}")
                logger.error(f"Directory listing of current directory: {os.listdir('.')}")
                self.vision_client = None
        except Exception as e:
            logger.error(f"Failed to initialize Google Vision client: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            self.vision_client = None
            
        # We'll only use Google Vision, no fallback needed
        self.api_key = None
        
        logger.info(f"ChartOCRProcessor initialized with Google Vision API")

    async def process_chart_image(self, image_path: str) -> Dict[str, Any]:
        """
        Process a chart image to extract price and indicator data using Google Vision API
        
        Args:
            image_path: Path to the chart image
            
        Returns:
            Dict with extracted data (price, indicators, etc.)
        """
        if not os.path.exists(image_path):
            logger.error(f"Image file not found: {image_path}")
            return {}
            
        try:
            logger.info(f"Processing chart image: {image_path}")
            
            # Read the image file
            with open(image_path, 'rb') as image_file:
                content = image_file.read()
            
            # Create image object for Google Vision
            image = vision.Image(content=content)
            
            # Perform text detection
            response = self.vision_client.text_detection(image=image)
            texts = response.text_annotations

            if not texts:
                logger.warning("No text detected in image")
                return {}
            
            # Get the full text
            ocr_text = texts[0].description
            logger.info(f"Full OCR text: {ocr_text}")
            
            # Extract price levels
            price_levels = []
            for text in texts[1:]:  # Skip the first one as it contains all text
                description = text.description
                price_match = re.search(r'(\d+\.\d+)', description)
                if price_match:
                    price_value = float(price_match.group(1))
                    if price_value > 10:  # Skip unrealistic forex prices
                        continue
                    
                    # Get the bounding box vertices
                    vertices = [(vertex.x, vertex.y) for vertex in text.bounding_poly.vertices]
                    x1 = min(v[0] for v in vertices)
                    y1 = min(v[1] for v in vertices)
                    x2 = max(v[0] for v in vertices)
                    y2 = max(v[1] for v in vertices)
                    
                    price_info = {
                        'value': price_value,
                        'text': description,
                        'x1': x1,
                        'y1': y1,
                        'x2': x2,
                        'y2': y2
                    }
                    
                    price_levels.append(price_info)
            
            # Sort price levels by value
            price_levels.sort(key=lambda x: x['value'], reverse=True)
            
            # Process the extracted data
            data = {}
            
            if price_levels:
                # Find current price (usually in the middle)
                price_values = [p['value'] for p in price_levels]
                min_price = min(price_values)
                max_price = max(price_values)
                mid_price = (min_price + max_price) / 2
                current_price = min(price_levels, key=lambda x: abs(x['value'] - mid_price))['value']
                data['current_price'] = current_price
                
                # Classify support and resistance levels
                supports = []
                resistances = []
                
                for price in price_levels:
                    value = price['value']
                    if value < current_price:
                        supports.append(value)
                    elif value > current_price:
                        resistances.append(value)
                
                # Sort levels
                supports.sort(reverse=True)  # Highest support first
                resistances.sort()  # Lowest resistance first
                
                if supports:
                    data['support_levels'] = supports[:3]  # Take top 3
                    logger.info(f"Support levels: {supports[:3]}")
                
                if resistances:
                    data['resistance_levels'] = resistances[:3]  # Take top 3
                    logger.info(f"Resistance levels: {resistances[:3]}")
            
            # Extract RSI if present
            rsi_match = re.search(r'RSI[:\s]+(\d+\.?\d*)', ocr_text, re.IGNORECASE)
            if rsi_match:
                rsi = float(rsi_match.group(1))
                logger.info(f"RSI extracted from OCR: {rsi}")
                data['rsi'] = rsi
            
            return data
            
        except Exception as e:
            logger.error(f"Error processing chart image: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return {}


# Voorbeeld gebruik:
# ocr_processor = ChartOCRProcessor()
# ocr_data = ocr_processor.process_chart_image("path/to/chart.png")
# enhanced_data = ocr_processor.enhance_market_data(api_data, ocr_data) 
