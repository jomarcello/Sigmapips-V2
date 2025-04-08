import os
import logging
import re
import base64
import json
import aiohttp
from typing import Dict, Any, Optional, List
import random

logger = logging.getLogger(__name__)

class ChartOCRProcessor:
    """Process chart images using OCR to extract price and indicator data"""
    
    def __init__(self):
        """Initialize the OCR processor"""
        self.api_key = os.environ.get("OCR_SPACE_API_KEY")
        if not self.api_key:
            logger.warning("No OCR.space API key found in environment variables, using default key")
            self.api_key = "K89271717488957"  # Using the provided API key
        
        logger.info(f"ChartOCRProcessor initialized with OCR.space API")
        
    async def process_chart_image(self, image_path: str) -> Dict[str, Any]:
        """
        Process a chart image to extract price and indicator data using OCR.space API
        
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
            
            # Get OCR text using OCR.space API
            ocr_result = await self._get_ocr_text_from_image(image_path)
            
            if not ocr_result:
                logger.warning("OCR returned no result, cannot extract data")
                return {}
            
            ocr_text = ocr_result.get('text', '')
            if not ocr_text:
                logger.warning("OCR returned empty text, cannot extract data")
                return {}
                
            lines_with_coords = ocr_result.get('lines_with_coords', [])
            
            logger.info(f"OCR text extracted: {ocr_text[:200]}...")
            
            # Extract data from OCR text and coordinates
            data = self._extract_data_from_ocr_result(ocr_text, lines_with_coords)
            
            if not data:
                logger.warning("Failed to extract data from OCR text")
                return {}
                
            logger.info(f"Extracted data: {data}")
            return data
            
        except Exception as e:
            logger.error(f"Error processing chart image: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
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
            
            for line in lines_with_coords:
                line_text = line.get('text', '')
                price_match = re.search(r'(\d+\.\d+)', line_text)
                if price_match:
                    price_value = float(price_match.group(1))
                    price_levels.append({
                        'value': price_value,
                        'text': line_text,
                        'y_pos': line.get('y1', 0)  # Use top Y coordinate
                    })
            
            # Sort price levels by Y position (top to bottom)
            price_levels.sort(key=lambda x: x['y_pos'])
            
            logger.info(f"Extracted price levels with positions: {json.dumps(price_levels)}")
            
            if price_levels:
                # Analyze price levels to identify:
                # 1. Current price (typically green or in the middle)
                # 2. Support levels (below current price)
                # 3. Resistance levels (above current price)
                # 4. Key levels (may be highlighted in red)
                
                # Identify current price (we'll assume it's in the middle or has special formatting)
                # For simplicity, we'll use a heuristic approach
                if len(price_levels) >= 3:
                    # First detect unique prices (avoid duplicates)
                    unique_prices = []
                    for p in price_levels:
                        if not any(abs(p['value'] - up['value']) < 0.0001 for up in unique_prices):
                            unique_prices.append(p)
                    
                    # Sort by value
                    sorted_prices = sorted(unique_prices, key=lambda x: x['value'])
                    
                    # If we have enough price levels, find middle one as current price
                    middle_idx = len(sorted_prices) // 2
                    current_price = sorted_prices[middle_idx]['value']
                    data['current_price'] = current_price
                    logger.info(f"Selected current price: {current_price}")
                    
                    # Find support and resistance levels
                    support_levels = [p['value'] for p in sorted_prices if p['value'] < current_price]
                    resistance_levels = [p['value'] for p in sorted_prices if p['value'] > current_price]
                    
                    # If we have enough levels, use them
                    if support_levels:
                        data['support_levels'] = support_levels
                        logger.info(f"Support levels: {support_levels}")
                    
                    if resistance_levels:
                        data['resistance_levels'] = resistance_levels
                        logger.info(f"Resistance levels: {resistance_levels}")
                    
                    # Try to detect key levels (may be the highest or lowest values)
                    if len(sorted_prices) >= 2:
                        data['key_levels'] = [sorted_prices[0]['value'], sorted_prices[-1]['value']]
                        logger.info(f"Key levels: {data['key_levels']}")
                else:
                    # If we don't have enough price levels, use the first one as current price
                    data['current_price'] = price_levels[0]['value']
                    logger.info(f"Only one price level, using as current price: {data['current_price']}")
            
            # Extract other indicators if present
            # RSI
            rsi_match = re.search(r'RSI[:\s]+(\d+\.?\d*)', ocr_text, re.IGNORECASE)
            if rsi_match:
                rsi = float(rsi_match.group(1))
                logger.info(f"RSI extracted from OCR: {rsi}")
                data['rsi'] = rsi
            
            # MACD
            macd_pattern = r'MACD[:\s]+([-+]?\d+\.?\d*)'
            macd_match = re.search(macd_pattern, ocr_text, re.IGNORECASE)
            if macd_match:
                macd = float(macd_match.group(1))
                logger.info(f"MACD extracted from OCR: {macd}")
                data['macd'] = macd
            
            # Extract MA/EMA values
            ma_pattern = r'(?:MA|EMA)[:\s]*(\d+)[:\s]+(\d+\.?\d*)'
            for ma_match in re.finditer(ma_pattern, ocr_text, re.IGNORECASE):
                period = ma_match.group(1)
                value = float(ma_match.group(2))
                key = f"ma_{period}"
                data[key] = value
                logger.info(f"MA/EMA {period} extracted: {value}")
            
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
