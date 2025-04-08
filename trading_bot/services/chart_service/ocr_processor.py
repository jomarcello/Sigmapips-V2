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
        """Process chart image to extract specific price levels based on color and context"""
        if not os.path.exists(image_path):
            logger.error(f"Image file not found: {image_path}")
            return {}
            
        try:
            logger.info(f"Processing chart image: {image_path}")
            
            # Read the image file
            with open(image_path, 'rb') as image_file:
                content = image_file.read()
            
            logger.info(f"Image size: {len(content)} bytes")
            
            # Create image object for Google Vision
            image = vision.Image(content=content)
            
            # Get text detection
            logger.info("Requesting text detection from Google Vision...")
            text_response = self.vision_client.text_detection(image=image)
            
            # Log the raw text detection response
            if text_response.text_annotations:
                full_text = text_response.text_annotations[0].description
                logger.info(f"Raw detected text:\n{full_text}")
            else:
                logger.error("No text annotations found in the response")
                if text_response.error:
                    logger.error(f"Vision API error: {text_response.error.message}")
            
            if not text_response.text_annotations:
                logger.warning("No text detected in image")
                return {}
            
            # Get all detected text blocks with their positions
            texts = text_response.text_annotations[1:]  # Skip first one as it contains all text
            
            logger.info(f"Found {len(texts)} text blocks")
            
            # Calculate chart height first
            chart_height = 0
            for text in texts:
                for vertex in text.bounding_poly.vertices:
                    chart_height = max(chart_height, vertex.y)
            
            logger.info(f"Chart height: {chart_height}")
            
            # Extract price levels with their context
            price_levels = []
            current_price = None
            key_levels = []
            support_resistance = []
            
            # Track seen prices to avoid duplicates
            seen_prices = set()
            
            # Track min/max valid prices to filter outliers
            valid_prices = []
            
            # First pass - collect valid prices and find current price
            for text in texts:
                description = text.description
                price_match = re.search(r'(\d*\.?\d+)', description)
                if not price_match:
                    continue
                    
                try:
                    price_value = float(price_match.group(1))
                    if price_value > 10:  # Skip unrealistic forex prices
                        continue
                        
                    # Get bounding box
                    x_coords = [vertex.x for vertex in text.bounding_poly.vertices]
                    y_coords = [vertex.y for vertex in text.bounding_poly.vertices]
                    x1 = min(x_coords)
                    y1 = min(y_coords)
                    x2 = max(x_coords)
                    y2 = max(y_coords)
                    
                    # Check if there's a timestamp below this price
                    has_timestamp = self._has_timestamp_below(texts, x1, x2, y2)
                    
                    # If this is a current price (has timestamp), use it to validate other prices
                    if has_timestamp:
                        logger.info(f"Found current price candidate: {price_value}")
                        if current_price is None or abs(price_value - 1.95) < abs(current_price['value'] - 1.95):
                            current_price = {
                                'value': price_value,
                                'has_timestamp': True,
                                'y_pos': y1 / chart_height if chart_height > 0 else 0
                            }
                    else:
                        valid_prices.append(price_value)
                        
                except Exception as e:
                    logger.error(f"Error in first pass processing price: {str(e)}")
                    continue
            
            if not current_price:
                logger.error("No current price found with timestamp")
                return {}
                
            # Calculate valid price range based on current price
            current_value = current_price['value']
            max_deviation = 0.05  # Maximum 5% deviation from current price
            min_valid_price = current_value * (1 - max_deviation)
            max_valid_price = current_value * (1 + max_deviation)
            
            logger.info(f"Valid price range: {min_valid_price:.5f} - {max_valid_price:.5f}")
            
            # Second pass - classify valid prices
            for text in texts:
                description = text.description
                price_match = re.search(r'(\d*\.?\d+)', description)
                if not price_match:
                    continue
                    
                try:
                    price_value = float(price_match.group(1))
                    
                    # Skip if price is outside valid range or already seen
                    if (price_value > max_valid_price or 
                        price_value < min_valid_price or 
                        price_value in seen_prices):
                        continue
                    
                    seen_prices.add(price_value)
                    
                    # Get bounding box
                    x_coords = [vertex.x for vertex in text.bounding_poly.vertices]
                    y_coords = [vertex.y for vertex in text.bounding_poly.vertices]
                    x1 = min(x_coords)
                    y1 = min(y_coords)
                    x2 = max(x_coords)
                    y2 = max(y_coords)
                    
                    logger.info(f"Analyzing price {price_value} at position ({x1}, {y1}) to ({x2}, {y2})")
                    
                    # Calculate relative position on chart
                    y_position = y1 / chart_height if chart_height > 0 else 0
                    
                    price_info = {
                        'value': price_value,
                        'y_pos': y_position
                    }
                    
                    # Classify the price based on position
                    if 0.3 <= y_position <= 0.7:  # Middle of chart
                        logger.info(f"Found key level: {price_value}")
                        key_levels.append(price_info)
                    else:  # Top or bottom of chart
                        logger.info(f"Found support/resistance: {price_value}")
                        support_resistance.append(price_info)
                
                except Exception as e:
                    logger.error(f"Error in second pass processing price: {str(e)}")
                    continue
            
            # Process the collected data
            data = {}
            
            if current_price:
                data['current_price'] = current_price['value']
                logger.info(f"Current price: {current_price['value']}")
                
                # Classify support/resistance levels based on current price
                supports = []
                resistances = []
                
                # Add key levels (middle of chart)
                for level in key_levels:
                    if level['value'] < current_price['value']:
                        supports.append(level['value'])
                    else:
                        resistances.append(level['value'])
                
                # Add support/resistance levels (edges of chart)
                for level in support_resistance:
                    if level['value'] < current_price['value']:
                        supports.append(level['value'])
                    else:
                        resistances.append(level['value'])
                
                # Sort and deduplicate levels
                if supports:
                    supports = sorted(set(supports), reverse=True)
                    data['support_levels'] = supports
                    logger.info(f"Support levels: {supports}")
                
                if resistances:
                    resistances = sorted(set(resistances))
                    data['resistance_levels'] = resistances
                    logger.info(f"Resistance levels: {resistances}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error processing chart image: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return {}
    
    def _has_timestamp_below(self, texts, x1, x2, y2, max_distance=20):
        """Check if there's a timestamp-like text below the price"""
        try:
            for text in texts:
                # Get text position
                x_coords = [vertex.x for vertex in text.bounding_poly.vertices]
                y_coords = [vertex.y for vertex in text.bounding_poly.vertices]
                text_x1 = min(x_coords)
                text_x2 = max(x_coords)
                text_y1 = min(y_coords)
                
                # Check if text is below the price and horizontally aligned
                if (text_y1 > y2 and text_y1 <= y2 + max_distance and
                    text_x1 >= x1 - max_distance and text_x2 <= x2 + max_distance):
                    # Check if text matches timestamp pattern (e.g., "32:49")
                    if re.match(r'\d{2}:\d{2}', text.description):
                        logger.debug(f"Found timestamp: {text.description} below price at y={y2}")
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking for timestamp: {str(e)}")
            return False


# Voorbeeld gebruik:
# ocr_processor = ChartOCRProcessor()
# ocr_data = ocr_processor.process_chart_image("path/to/chart.png")
# enhanced_data = ocr_processor.enhance_market_data(api_data, ocr_data) 
