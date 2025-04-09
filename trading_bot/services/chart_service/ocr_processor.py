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
            
            # Calculate chart dimensions
            chart_height = 0
            chart_width = 0
            for text in texts:
                for vertex in text.bounding_poly.vertices:
                    chart_height = max(chart_height, vertex.y)
                    chart_width = max(chart_width, vertex.x)
            
            logger.info(f"Chart dimensions: {chart_width}x{chart_height}")
            
            # First, we'll identify all the price texts on the left side
            price_texts = []
            
            # Identify candidate price texts (usually on the left side of the chart)
            for text in texts:
                description = text.description.strip()
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
                    
                    # Check if it's on the left side (first quarter of the image width)
                    if x2 < chart_width / 4:
                        price_texts.append({
                            'value': price_value,
                            'text': description,
                            'x1': x1,
                            'y1': y1,
                            'x2': x2,
                            'y2': y2,
                            'center_y': (y1 + y2) // 2
                        })
                        logger.info(f"Found price text: {price_value} at y={y1}")
                except Exception as e:
                    logger.error(f"Error processing price text: {str(e)}")
            
            # Now, identify all label texts (likely on the right side of the chart)
            label_texts = []
            important_labels = ['daily high', 'daily low', 'weekly high', 'weekly low', 
                              'monthly high', 'monthly low', 'support', 'resistance',
                              'pivot', 's1', 's2', 's3', 'r1', 'r2', 'r3', 'pp',
                              'supply', 'demand', 'zone', 'buy', 'sell', 'poi']
            
            # First, collect all non-price text elements
            raw_labels = []
            for text in texts:
                description = text.description.lower().strip()
                
                # Skip if it's a price
                if re.match(r'^\d*\.?\d+$', description):
                    continue
                
                # Get bounding box
                vertices = text.bounding_poly.vertices
                x_coords = [vertex.x for vertex in vertices]
                y_coords = [vertex.y for vertex in vertices]
                x1 = min(x_coords)
                y1 = min(y_coords)
                x2 = max(x_coords)
                y2 = max(y_coords)
                
                # Check if it's likely a label
                is_right_side = x1 > chart_width * 0.6
                is_important_label = any(label in description for label in important_labels)
                
                if is_right_side or is_important_label:
                    raw_labels.append({
                        'text': description,
                        'x1': x1,
                        'y1': y1,
                        'x2': x2,
                        'y2': y2,
                        'center_y': (y1 + y2) // 2
                    })
                    logger.info(f"Found raw label: '{description}' at position ({x1},{y1})")
            
            # Sort raw labels by y position and then x position (to handle labels on the same line)
            raw_labels.sort(key=lambda l: (l['center_y'], l['x1']))
            
            # Combine adjacent labels that are likely part of the same label (e.g., "daily" + "high")
            i = 0
            while i < len(raw_labels) - 1:
                current = raw_labels[i]
                next_label = raw_labels[i + 1]
                
                # Check if labels are on same horizontal line (within 20 pixels)
                y_diff = abs(current['center_y'] - next_label['center_y'])
                
                # Check if labels are horizontally adjacent (within 50 pixels)
                x_diff = next_label['x1'] - current['x2']
                
                if y_diff < 20 and x_diff < 50 and x_diff > 0:  # Close horizontally and on same line
                    # Combine the two labels
                    combined_text = f"{current['text']} {next_label['text']}"
                    logger.info(f"Combining labels: '{current['text']}' + '{next_label['text']}' = '{combined_text}'")
                    
                    # Create new combined label
                    combined_label = {
                        'text': combined_text,
                        'x1': current['x1'],
                        'y1': min(current['y1'], next_label['y1']),
                        'x2': next_label['x2'],
                        'y2': max(current['y2'], next_label['y2']),
                        'center_y': (current['center_y'] + next_label['center_y']) // 2
                    }
                    
                    # Replace current with combined, remove next
                    raw_labels[i] = combined_label
                    raw_labels.pop(i + 1)
                else:
                    i += 1
            
            # Process the combined labels
            for label in raw_labels:
                label_text = label['text']
                is_important = any(important in label_text for important in important_labels)
                is_right_side = label['x1'] > chart_width * 0.6
                
                if is_important or is_right_side:
                    label_texts.append(label)
                    logger.info(f"Found processed label: '{label_text}' at y={label['y1']}")
            
            # Find the current price (often has a timestamp below or is in the middle of price scale)
            current_price = None
            for price in price_texts:
                # Check if there's a timestamp below this price
                has_timestamp = self._has_timestamp_below(texts, price['x1'], price['x2'], price['y2'])
                
                if has_timestamp:
                    current_price = price['value']
                    logger.info(f"Found current price with timestamp: {current_price}")
                    break
            
            # If we didn't find a current price with timestamp, estimate it
            if not current_price:
                # If we have price texts, take the middle one as estimate
                if price_texts:
                    # Sort by y position
                    sorted_prices = sorted(price_texts, key=lambda p: p['y1'])
                    middle_index = len(sorted_prices) // 2
                    current_price = sorted_prices[middle_index]['value']
                    logger.info(f"Estimated current price from middle of scale: {current_price}")
                else:
                    logger.error("No prices found to estimate current price")
                    return {}
            
            # Match labels with corresponding prices based on y-coordinate
            price_levels = {}
            
            for label in label_texts:
                label_text = label['text']
                
                # Find the closest price text by y-coordinate
                closest_price = None
                min_distance = float('inf')
                
                for price in price_texts:
                    distance = abs(label['center_y'] - price['center_y'])
                    if distance < min_distance:
                        min_distance = distance
                        closest_price = price
                
                # Only match if the distance is reasonable (within 10% of chart height)
                if min_distance < chart_height * 0.1 and closest_price:
                    price_value = closest_price['value']
                    
                    logger.info(f"Matched label '{label_text}' with price {price_value} (distance: {min_distance}px)")
                    
                    # Categorize the price level based on the combined label
                    if any(term in label_text for term in ['resistance', 'r1', 'r2', 'r3', 'high', 'supply']):
                        price_levels[label_text] = {'value': price_value, 'type': 'resistance'}
                    elif any(term in label_text for term in ['support', 's1', 's2', 's3', 'low', 'demand']):
                        price_levels[label_text] = {'value': price_value, 'type': 'support'}
                    else:
                        price_levels[label_text] = {'value': price_value, 'type': 'other'}
            
            # Process the collected data
            data = {}
            
            if current_price:
                data['current_price'] = current_price
            
            # Extract support and resistance levels
            support_levels = []
            resistance_levels = []
            
            for label, info in price_levels.items():
                if info['type'] == 'resistance':
                    resistance_levels.append(info['value'])
                    logger.info(f"Added resistance level: {label} = {info['value']}")
                elif info['type'] == 'support':
                    support_levels.append(info['value'])
                    logger.info(f"Added support level: {label} = {info['value']}")
            
            # If we don't have any labeled support/resistance levels, 
            # use price comparison as fallback
            if not support_levels and not resistance_levels and price_texts:
                logger.info("No labeled levels found, using price comparison as fallback")
                
                for price in price_texts:
                    if price['value'] > current_price:
                        resistance_levels.append(price['value'])
                    elif price['value'] < current_price:
                        support_levels.append(price['value'])
            
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
            
            # Also add all the named price levels for reference
            if price_levels:
                data['price_levels'] = {k: v['value'] for k, v in price_levels.items()}
                logger.info(f"Named price levels: {data['price_levels']}")
            
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
