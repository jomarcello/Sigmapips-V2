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
            
            # Get image properties for color analysis
            logger.info("Requesting image properties from Google Vision...")
            properties_response = self.vision_client.image_properties(image=image)
            
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
            
            # Analyze dominant colors for potential indicator colors
            dominant_colors = []
            if properties_response.image_properties_annotation.dominant_colors:
                colors = properties_response.image_properties_annotation.dominant_colors.colors
                for color in colors:
                    r, g, b = color.color.red, color.color.green, color.color.blue
                    score = color.score
                    pixel_fraction = color.pixel_fraction
                    dominant_colors.append((r, g, b, score, pixel_fraction))
                    logger.info(f"Dominant color: RGB({r},{g},{b}) - Score: {score:.2f}, Fraction: {pixel_fraction:.2f}")
            
            # Identify potential support and resistance color indicators
            # Common colors: Red often for resistance, Green often for support
            support_color_candidates = []
            resistance_color_candidates = []
            
            for r, g, b, score, fraction in dominant_colors:
                # Check for green-like colors (potential support)
                if g > max(r, b) and g > 100 and score > 0.05:
                    support_color_candidates.append((r, g, b))
                    logger.info(f"Potential support color: RGB({r},{g},{b})")
                
                # Check for red-like colors (potential resistance)
                if r > max(g, b) and r > 100 and score > 0.05:
                    resistance_color_candidates.append((r, g, b))
                    logger.info(f"Potential resistance color: RGB({r},{g},{b})")
            
            # Calculate chart height first
            chart_height = 0
            for text in texts:
                for vertex in text.bounding_poly.vertices:
                    chart_height = max(chart_height, vertex.y)
            
            logger.info(f"Chart height: {chart_height}")
            
            # Extract all prices from the image
            all_prices = []
            current_price = None
            
            # First pass - identify all price texts including the current price
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
                    vertices = text.bounding_poly.vertices
                    x_coords = [vertex.x for vertex in vertices]
                    y_coords = [vertex.y for vertex in vertices]
                    x1 = min(x_coords)
                    y1 = min(y_coords)
                    x2 = max(x_coords)
                    y2 = max(y_coords)
                    
                    # Calculate center of the text box
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                    
                    # Check if there's a timestamp below this price
                    has_timestamp = self._has_timestamp_below(texts, x1, x2, y2)
                    
                    # Check text color context based on the colors in the bounding box area
                    # This uses the dominant colors identified earlier to make an educated guess
                    is_support_colored = False
                    is_resistance_colored = False
                    
                    # For now, we'll approximate by looking at text position relative to chart height
                    # In a full implementation, you'd sample the image pixels in the text area
                    
                    # We can use the position of the text and the dominant colors to infer if this 
                    # might be a support or resistance level based on color
                    # A more accurate approach would be to extract the specific pixels around each text
                    
                    # For now, let's base it on chart position and see if we can detect the current price
                    
                    price_info = {
                        'value': price_value,
                        'has_timestamp': has_timestamp,
                        'x1': x1,
                        'y1': y1,
                        'x2': x2,
                        'y2': y2,
                        'center_x': center_x,
                        'center_y': center_y,
                        'is_support_colored': is_support_colored,
                        'is_resistance_colored': is_resistance_colored
                    }
                    
                    # If this has a timestamp, it's likely the current price
                    if has_timestamp:
                        logger.info(f"Found current price candidate: {price_value}")
                        current_price = price_info
                    
                    # Add to our list of all prices
                    all_prices.append(price_info)
                    
                except Exception as e:
                    logger.error(f"Error in first pass processing price: {str(e)}")
                    continue
            
            # If we couldn't find a current price with timestamp, try to estimate it
            if not current_price and all_prices:
                # Sort prices by y-position and use the middle one as an estimate
                all_prices.sort(key=lambda p: p['y1'])
                middle_index = len(all_prices) // 2
                current_price = all_prices[middle_index]
                logger.info(f"Using estimated current price: {current_price['value']}")
            
            if not current_price:
                logger.error("No current price found")
                return {}
                
            logger.info(f"Current price: {current_price['value']}")
            
            # Extract support and resistance levels
            support_levels = []
            resistance_levels = []
            
            # Process all detected prices to find support and resistance levels
            for price in all_prices:
                # Skip if it's the current price
                if price['value'] == current_price['value']:
                    continue
                
                # Log all price levels for debugging
                logger.info(f"Evaluating price: {price['value']} at position ({price['x1']}, {price['y1']})")
                
                # Now we'll use both position and color context to determine support/resistance
                # If a text has a color matching our support_color_candidates, it's likely support
                # If a text has a color matching our resistance_color_candidates, it's likely resistance
                
                # For now we'll use position as a fallback since we don't have per-text color analysis
                is_likely_support = price['is_support_colored'] or price['value'] < current_price['value']
                is_likely_resistance = price['is_resistance_colored'] or price['value'] > current_price['value']
                
                if is_likely_resistance:
                    resistance_levels.append(price['value'])
                    logger.info(f"Added resistance level: {price['value']}")
                
                if is_likely_support:
                    support_levels.append(price['value'])
                    logger.info(f"Added support level: {price['value']}")
            
            # Process the collected data
            data = {}
            data['current_price'] = current_price['value']
            
            # Sort and filter support and resistance levels
            if support_levels:
                # Sort support levels in descending order (highest first) and take up to 3
                supports = sorted(set(support_levels), reverse=True)[:3]
                data['support_levels'] = supports
                logger.info(f"Support levels: {supports}")
            
            if resistance_levels:
                # Sort resistance levels in ascending order (lowest first) and take up to 3
                resistances = sorted(set(resistance_levels))[:3]
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
