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
            
            # Get both text detection and image properties
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
            
            logger.info("Requesting color analysis from Google Vision...")
            color_response = self.vision_client.image_properties(image=image)
            
            # Log color analysis results
            if color_response.image_properties_annotation.dominant_colors:
                colors = color_response.image_properties_annotation.dominant_colors.colors
                logger.info("Dominant colors found:")
                for color in colors[:3]:  # Log top 3 dominant colors
                    logger.info(f"Color: R:{color.color.red} G:{color.color.green} B:{color.color.blue} Score:{color.score}")
            else:
                logger.error("No color properties found in the response")
            
            if not text_response.text_annotations:
                logger.warning("No text detected in image")
                return {}
            
            # Get all detected text blocks with their positions
            texts = text_response.text_annotations[1:]  # Skip first one as it contains all text
            
            logger.info(f"Found {len(texts)} text blocks")
            
            # Extract price levels with their context
            price_levels = []
            current_price = None
            key_levels = []
            support_resistance = []
            
            for text in texts:
                description = text.description
                logger.debug(f"Analyzing text block: {description}")
                # Updated regex to handle more number formats
                price_match = re.search(r'(\d*\.?\d+)', description)
                if not price_match:
                    continue
                    
                try:
                    price_value = float(price_match.group(1))
                    logger.debug(f"Found potential price value: {price_value}")
                    if price_value > 10:  # Skip unrealistic forex prices
                        logger.debug(f"Skipping unrealistic forex price: {price_value}")
                        continue
                
                    # Get bounding box
                    vertices = [(vertex.x, vertex.y) for vertex in text.bounding_poly.vertices]
                    x1 = min(v[0] for v in vertices)
                    y1 = min(v[1] for v in vertices)
                    x2 = max(v[0] for v in vertices)
                    y2 = max(v[1] for v in vertices)
                    
                    logger.info(f"Analyzing price {price_value} at position ({x1}, {y1}) to ({x2}, {y2})")
                    
                    # Get the dominant color in this region
                    region_color = self._get_dominant_color(colors, x1, y1, x2, y2)
                    if not region_color:
                        logger.warning(f"No color found for price {price_value}")
                        continue
                    
                    # Check if there's a timestamp below this price
                    has_timestamp = self._has_timestamp_below(texts, x1, x2, y2)
                    logger.info(f"Price {price_value} - Has timestamp: {has_timestamp}")
                    
                    price_info = {
                        'value': price_value,
                        'color': region_color,
                        'has_timestamp': has_timestamp,
                        'y_pos': y1
                    }
                    
                    # Classify the price based on color and timestamp
                    if has_timestamp and (self._is_red_color(region_color) or self._is_green_color(region_color)):
                        logger.info(f"Found current price: {price_value}")
                        current_price = price_info
                    elif self._is_red_color(region_color) and not has_timestamp:
                        logger.info(f"Found key level: {price_value}")
                        key_levels.append(price_info)
                    elif self._is_yellow_color(region_color):
                        logger.info(f"Found support/resistance: {price_value}")
                        support_resistance.append(price_info)
                
                except Exception as e:
                    logger.error(f"Error processing price: {str(e)}")
                    continue
            
            # Process the collected data
            data = {}
            
            if current_price:
                data['current_price'] = current_price['value']
                logger.info(f"Current price: {current_price['value']}")
                
                # Classify support/resistance levels based on current price
                supports = []
                resistances = []
                
                # Add key levels (red without timestamp)
                for level in key_levels:
                    if level['value'] < current_price['value']:
                        supports.append(level['value'])
                    else:
                        resistances.append(level['value'])
                
                # Add yellow support/resistance levels
                for level in support_resistance:
                    if level['value'] < current_price['value']:
                        supports.append(level['value'])
                    else:
                        resistances.append(level['value'])
                
                # Sort and store the levels
                if supports:
                    supports.sort(reverse=True)
                    data['support_levels'] = supports
                    logger.info(f"Support levels: {supports}")
                
                if resistances:
                    resistances.sort()
                    data['resistance_levels'] = resistances
                    logger.info(f"Resistance levels: {resistances}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error processing chart image: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return {}
    
    def _get_dominant_color(self, colors, x1, y1, x2, y2):
        """Get the dominant color in a specific region"""
        try:
            # Instead of using pixel_fraction, we'll just use the dominant colors
            # and their scores to determine the most likely color for the text
            if not colors:
                logger.warning("No colors found in the image")
                return None
                
            # Get the top 5 most dominant colors
            top_colors = sorted(colors, key=lambda x: x.score, reverse=True)[:5]
            
            # Log the colors we're considering
            for idx, color in enumerate(top_colors):
                logger.debug(f"Color {idx + 1}: R:{color.color.red} G:{color.color.green} B:{color.color.blue} Score:{color.score}")
            
            # Use the most dominant color that matches our criteria
            for color in top_colors:
                if (self._is_red_color(color.color) or 
                    self._is_green_color(color.color) or 
                    self._is_yellow_color(color.color)):
                    logger.info(f"Found matching color - R:{color.color.red} G:{color.color.green} B:{color.color.blue}")
                    return color.color
            
            # If no color matches our criteria, use the most dominant color
            logger.info(f"Using most dominant color - R:{top_colors[0].color.red} G:{top_colors[0].color.green} B:{top_colors[0].color.blue}")
            return top_colors[0].color
            
        except Exception as e:
            logger.error(f"Error getting dominant color: {str(e)}")
            return None
    
    def _has_timestamp_below(self, texts, x1, x2, y2, max_distance=20):
        """Check if there's a timestamp-like text below the price"""
        try:
            for text in texts:
                # Get text position
                vertices = [(vertex.x, vertex.y) for vertex in text.bounding_poly.vertices]
                text_x1 = min(v[0] for v in vertices)
                text_x2 = max(v[0] for v in vertices)
                text_y1 = min(v[1] for v in vertices)
                
                # Check if text is below the price and horizontally aligned
                if (text_y1 > y2 and text_y1 <= y2 + max_distance and
                    text_x1 >= x1 - max_distance and text_x2 <= x2 + max_distance):
                    # Check if text matches timestamp pattern (e.g., "32:49")
                    if re.match(r'\d{2}:\d{2}', text.description):
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking for timestamp: {str(e)}")
            return False
    
    def _is_red_color(self, color):
        """Check if a color is red"""
        is_red = (color.red > 120 and 
                color.green < 120 and 
                color.blue < 120 and
                color.red > max(color.green, color.blue))
        if is_red:
            logger.info(f"Detected RED color - R:{color.red} G:{color.green} B:{color.blue}")
        return is_red
    
    def _is_green_color(self, color):
        """Check if a color is green"""
        is_green = (color.green > 120 and 
                color.red < 120 and 
                color.blue < 120 and
                color.green > max(color.red, color.blue))
        if is_green:
            logger.info(f"Detected GREEN color - R:{color.red} G:{color.green} B:{color.blue}")
        return is_green
    
    def _is_yellow_color(self, color):
        """Check if a color is yellow/orange"""
        is_yellow = (color.red > 120 and 
                color.green > 120 and 
                color.blue < 100 and
                abs(color.red - color.green) < 50)  # Yellow should have similar red and green values
        if is_yellow:
            logger.info(f"Detected YELLOW color - R:{color.red} G:{color.green} B:{color.blue}")
        return is_yellow


# Voorbeeld gebruik:
# ocr_processor = ChartOCRProcessor()
# ocr_data = ocr_processor.process_chart_image("path/to/chart.png")
# enhanced_data = ocr_processor.enhance_market_data(api_data, ocr_data) 
