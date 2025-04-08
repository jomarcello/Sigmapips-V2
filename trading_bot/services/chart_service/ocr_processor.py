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
            
        # Fallback to OCR.space if Google Vision fails
        self.api_key = os.environ.get("OCR_SPACE_API_KEY")
        if not self.api_key:
            logger.warning("No OCR.space API key found in environment variables, using default key")
            self.api_key = "K89271717488957"  # Using the provided API key
        
        logger.info(f"ChartOCRProcessor initialized with Google Vision and OCR.space API")
        
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
            
            # Perform multiple detections in parallel
            response = self.vision_client.annotate_image({
                'image': image,
                'features': [
                    {'type_': vision.Feature.Type.TEXT_DETECTION},
                    {'type_': vision.Feature.Type.IMAGE_PROPERTIES}
                ]
            })
            
            if not response:
                logger.warning("Google Vision returned no result, falling back to OCR.space")
                return await self._fallback_to_ocr_space(image_path)
            
            # Extract text and color information
            text_annotations = response.text_annotations
            color_info = response.image_properties_annotation.dominant_colors.colors
            
            if not text_annotations:
                logger.warning("No text detected in image")
                return {}
            
            # Get the full text
            ocr_text = text_annotations[0].description
            
            # Extract price levels with their colors
            price_levels = []
            for annotation in text_annotations[1:]:  # Skip the first one as it contains all text
                text = annotation.description
                price_match = re.search(r'(\d+\.\d+)', text)
                if price_match:
                    price_value = float(price_match.group(1))
                    if price_value > 10:  # Skip unrealistic forex prices
                        continue
                    
                    # Get the bounding box
                    vertices = annotation.bounding_box.vertices
                    x1 = min(v.x for v in vertices)
                    y1 = min(v.y for v in vertices)
                    x2 = max(v.x for v in vertices)
                    y2 = max(v.y for v in vertices)
                    
                    # Find dominant color in this region
                    region_color = self._get_dominant_color_in_region(
                        color_info, x1, y1, x2, y2
                    )
                    
                    price_info = {
                        'value': price_value,
                        'text': text,
                        'x1': x1,
                        'y1': y1,
                        'x2': x2,
                        'y2': y2,
                        'color': region_color
                    }
                    
                    price_levels.append(price_info)
            
            # Process the extracted data
            data = self._extract_data_from_vision_result(price_levels, ocr_text)
            
            if not data:
                logger.warning("Failed to extract data from Vision result")
                return {}
                
            logger.info(f"Extracted data: {data}")
            return data
            
        except Exception as e:
            logger.error(f"Error processing chart image: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
    
    def _get_dominant_color_in_region(self, color_info, x1, y1, x2, y2):
        """Get the dominant color in a specific region of the image"""
        try:
            # Find colors that are in the region
            region_colors = []
            for color in color_info:
                # Check if color is in the region
                if (x1 <= color.pixel_fraction * 100 <= x2 and 
                    y1 <= color.color.red <= y2):
                    region_colors.append({
                        'color': color.color,
                        'score': color.score
                    })
            
            if not region_colors:
                return None
            
            # Return the color with highest score
            return max(region_colors, key=lambda x: x['score'])['color']
            
        except Exception as e:
            logger.error(f"Error getting dominant color: {str(e)}")
            return None
    
    def _extract_data_from_vision_result(self, price_levels: List[Dict], ocr_text: str) -> Dict[str, Any]:
        """Extract data from Google Vision result"""
        data = {}
        
        try:
            # Sort price levels by value
            price_levels.sort(key=lambda x: x['value'], reverse=True)
            
            if price_levels:
                # Find current price (usually the one with green color)
                green_prices = [p for p in price_levels if self._is_green_color(p.get('color'))]
                if green_prices:
                    data['current_price'] = green_prices[0]['value']
                else:
                    # Fallback: use middle price
                    price_values = [p['value'] for p in price_levels]
                    min_price = min(price_values)
                    max_price = max(price_values)
                    mid_price = (min_price + max_price) / 2
                    current_price = min(price_levels, key=lambda x: abs(x['value'] - mid_price))['value']
                    data['current_price'] = current_price
                
                # Classify support and resistance levels
                supports = []
                resistances = []
                key_levels = []
                
                current_price = data['current_price']
                
                for price in price_levels:
                    value = price['value']
                    color = price.get('color')
                    
                    # Add to key levels if it's a colored price
                    if color and (self._is_green_color(color) or 
                                self._is_orange_color(color) or 
                                self._is_red_color(color)):
                        key_levels.append(value)
                    
                    # Support/Resistance classification
                    if value < current_price:
                        supports.append(value)
                    elif value > current_price:
                        resistances.append(value)
                
                # Sort levels
                supports.sort(reverse=True)  # Highest support first
                resistances.sort()  # Lowest resistance first
                key_levels.sort()
                
                if supports:
                    data['support_levels'] = supports
                    logger.info(f"Support levels: {supports}")
                
                if resistances:
                    data['resistance_levels'] = resistances
                    logger.info(f"Resistance levels: {resistances}")
                
                if key_levels:
                    data['key_levels'] = key_levels
                    logger.info(f"Key levels: {key_levels}")
            
            # Extract other indicators if present
            # RSI
            rsi_match = re.search(r'RSI[:\s]+(\d+\.?\d*)', ocr_text, re.IGNORECASE)
            if rsi_match:
                rsi = float(rsi_match.group(1))
                logger.info(f"RSI extracted from OCR: {rsi}")
                data['rsi'] = rsi
            
            return data
            
        except Exception as e:
            logger.error(f"Error extracting data from Vision result: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
    
    def _is_green_color(self, color) -> bool:
        """Check if a color is green"""
        if not color:
            return False
        # Green colors have high green component and lower red/blue
        return (color.green > 150 and 
                color.red < 100 and 
                color.blue < 100)
    
    def _is_orange_color(self, color) -> bool:
        """Check if a color is orange"""
        if not color:
            return False
        # Orange colors have high red and green components
        return (color.red > 150 and 
                color.green > 100 and 
                color.blue < 100)
    
    def _is_red_color(self, color) -> bool:
        """Check if a color is red"""
        if not color:
            return False
        # Red colors have high red component and lower green/blue
        return (color.red > 150 and 
                color.green < 100 and 
                color.blue < 100)
    
    async def _fallback_to_ocr_space(self, image_path: str) -> Dict[str, Any]:
        """Fallback to OCR.space API if Google Vision fails"""
        try:
            # Get OCR text using OCR.space API
            ocr_result = await self._get_ocr_text_from_image(image_path)
            
            if not ocr_result:
                logger.warning("OCR.space returned no result")
                return {}
            
            ocr_text = ocr_result.get('text', '')
            if not ocr_text:
                logger.warning("OCR.space returned empty text")
                return {}
                
            lines_with_coords = ocr_result.get('lines_with_coords', [])
            
            # Extract data using the existing method
            return self._extract_data_from_ocr_result(ocr_text, lines_with_coords)
            
        except Exception as e:
            logger.error(f"Error in OCR.space fallback: {str(e)}")
            return {}
    
    async def _get_ocr_text_from_image(self, image_path: str) -> Dict[str, Any]:
        """
        Extract text from image using OCR.space API
        
        Args:
            image_path: Path to image file
            
        Returns:
            Dict with extracted text and coordinate information
        """
        try:
            # Check if we should use the OCR.space API
            if not self.api_key:
                logger.warning("No OCR.space API key available")
                return {}
                
            logger.info(f"Reading image file: {image_path}")
            
            # Read image as binary data
            try:
                with open(image_path, 'rb') as image_file:
                    image_data = image_file.read()
                    file_size = len(image_data)
                    logger.info(f"Image file size: {file_size} bytes")
                    
                    if file_size > 1024 * 1024:
                        logger.warning(f"Image file is large ({file_size/1024/1024:.2f} MB), may exceed API limits")
            except Exception as file_error:
                logger.error(f"Error reading image file: {str(file_error)}")
                return {}
            
            # Send to OCR.space API
            url = 'https://api.ocr.space/parse/image'
            
            try:
                # Send file directly with overlay option enabled to get word positions
                logger.info(f"Sending image to OCR.space API via file upload")
                form_data = aiohttp.FormData()
                form_data.add_field('apikey', self.api_key)
                form_data.add_field('language', 'eng')
                form_data.add_field('OCREngine', '2')  # Use more advanced engine
                form_data.add_field('scale', 'true')
                form_data.add_field('isOverlayRequired', 'true')  # Get word positions
                form_data.add_field('file', image_data, 
                                   filename=os.path.basename(image_path),
                                   content_type='image/png')
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data=form_data) as response:
                        logger.info(f"OCR.space API response status: {response.status}")
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"OCR.space API error: {response.status}, Response: {error_text}")
                            return {}
                        
                        try:
                            result = await response.json()
                            logger.info(f"OCR.space API response received: {len(str(result))} chars")
                        except Exception as json_error:
                            logger.error(f"Error parsing JSON response: {str(json_error)}")
                            response_text = await response.text()
                            logger.error(f"Raw response: {response_text[:500]}")
                            return {}
                        
                        if result.get('IsErroredOnProcessing'):
                            logger.error(f"OCR processing error: {result.get('ErrorMessage', 'Unknown error')}")
                            return {}
                        
                        parsed_results = result.get('ParsedResults', [])
                        if not parsed_results:
                            logger.warning("No OCR results returned")
                            return {}
                        
                        # Extract text and overlay data (contains word positions)
                        ocr_text = parsed_results[0].get('ParsedText', '')
                        overlay_data = parsed_results[0].get('TextOverlay', {})
                        lines = overlay_data.get('Lines', [])
                        
                        # Extract lines with their coordinates
                        lines_with_coords = []
                        for line in lines:
                            line_text = ''
                            min_x = float('inf')
                            min_y = float('inf')
                            max_x = 0
                            max_y = 0
                            
                            # Extract words and merge them into line text
                            for word in line.get('Words', []):
                                word_text = word.get('WordText', '')
                                line_text += word_text + ' '
                                
                                # Get word bounding box
                                left = word.get('Left', 0)
                                top = word.get('Top', 0)
                                width = word.get('Width', 0)
                                height = word.get('Height', 0)
                                
                                # Update bounding box for the line
                                min_x = min(min_x, left)
                                min_y = min(min_y, top)
                                max_x = max(max_x, left + width)
                                max_y = max(max_y, top + height)
                            
                            if line_text.strip():
                                lines_with_coords.append({
                                    'text': line_text.strip(),
                                    'x1': min_x,
                                    'y1': min_y,
                                    'x2': max_x,
                                    'y2': max_y
                                })
                        
                        logger.info(f"OCR.space API extracted {len(lines_with_coords)} text lines with coordinates")
                        
                        return {
                            'text': ocr_text,
                            'lines_with_coords': lines_with_coords
                        }
            
            except Exception as api_error:
                logger.error(f"Error calling OCR.space API: {str(api_error)}")
                import traceback
                logger.error(f"API call traceback: {traceback.format_exc()}")
                return {}
            
        except Exception as e:
            logger.error(f"Error in OCR processing: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
    
    def _extract_data_from_ocr_result(self, ocr_text: str, lines_with_coords: List[Dict]) -> Dict[str, Any]:
        """
        Extract price and indicator data from OCR text and coordinate information
        
        Args:
            ocr_text: Text extracted from chart image
            lines_with_coords: List of text lines with their coordinates
            
        Returns:
            Dict with extracted data
        """
        data = {}
        
        try:
            # Log the full OCR text for debugging
            logger.info(f"Full OCR text for extraction:\n{ocr_text}")
            logger.info(f"Lines with coordinates: {json.dumps(lines_with_coords)}")
            
            # Extract numeric values (price levels) with positions
            price_levels = []
            
            # Find the chart boundaries
            min_y = float('inf')
            max_y = 0
            for line in lines_with_coords:
                min_y = min(min_y, line.get('y1', float('inf')))
                max_y = max(max_y, line.get('y2', 0))
            
            # Calculate chart height and key zones
            chart_height = max_y - min_y
            top_zone = min_y + (chart_height * 0.2)  # Top 20%
            bottom_zone = max_y - (chart_height * 0.2)  # Bottom 20%
            
            for line in lines_with_coords:
                line_text = line.get('text', '')
                price_match = re.search(r'(\d+\.\d+)', line_text)
                if price_match:
                    price_value = float(price_match.group(1))
                    # Filter out obviously wrong values (like 11.98426)
                    if price_value > 10:  # Skip unrealistic forex prices
                        continue
                    
                    # Get line position
                    y_pos = line.get('y1', 0)
                    
                    # Determine if this is a key level based on position and context
                    is_key_level = False
                    
                    # Check if price is in top or bottom zone
                    if y_pos <= top_zone or y_pos >= bottom_zone:
                        is_key_level = True
                    
                    # Check for special price patterns (like round numbers)
                    if re.match(r'\d+\.\d{2}0{2,3}', str(price_value)):
                        is_key_level = True
                    
                    # Check for price levels near important text
                    important_texts = ['Daily High', 'SUP', 'RES', 'Key', 'Level']
                    if any(text.lower() in line_text.lower() for text in important_texts):
                        is_key_level = True
                    
                    price_info = {
                        'value': price_value,
                        'text': line_text,
                        'y_pos': y_pos,
                        'is_key_level': is_key_level
                    }
                    
                    price_levels.append(price_info)
            
            # Sort price levels by value
            price_levels.sort(key=lambda x: x['value'], reverse=True)
            
            if price_levels:
                # Find current price (middle of the chart)
                price_values = [p['value'] for p in price_levels]
                min_price = min(price_values)
                max_price = max(price_values)
                mid_price = (min_price + max_price) / 2
                current_price = min(price_levels, key=lambda x: abs(x['value'] - mid_price))['value']
                data['current_price'] = current_price
                
                # Classify support and resistance levels
                supports = []
                resistances = []
                key_levels = []
                
                for price in price_levels:
                    value = price['value']
                    
                    # Add to key levels if marked as important
                    if price['is_key_level']:
                        key_levels.append(value)
                    
                    # Support/Resistance classification
                    if value < current_price:
                        supports.append(value)
                    elif value > current_price:
                        resistances.append(value)
                
                # Sort levels
                supports.sort(reverse=True)  # Highest support first
                resistances.sort()  # Lowest resistance first
                key_levels.sort()
                
                if supports:
                    data['support_levels'] = supports
                    logger.info(f"Support levels: {supports}")
                
                if resistances:
                    data['resistance_levels'] = resistances
                    logger.info(f"Resistance levels: {resistances}")
                
                if key_levels:
                    data['key_levels'] = key_levels
                    logger.info(f"Key levels: {key_levels}")
            
            # Extract other indicators if present
            # RSI
            rsi_match = re.search(r'RSI[:\s]+(\d+\.?\d*)', ocr_text, re.IGNORECASE)
            if rsi_match:
                rsi = float(rsi_match.group(1))
                logger.info(f"RSI extracted from OCR: {rsi}")
                data['rsi'] = rsi
            
            return data
            
        except Exception as e:
            logger.error(f"Error extracting data from OCR text: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {}


# Voorbeeld gebruik:
# ocr_processor = ChartOCRProcessor()
# ocr_data = ocr_processor.process_chart_image("path/to/chart.png")
# enhanced_data = ocr_processor.enhance_market_data(api_data, ocr_data) 
