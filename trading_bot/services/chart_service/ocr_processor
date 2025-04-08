import os
import logging
import re
import base64
import json
import aiohttp
from typing import Dict, Any, Optional
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
            ocr_text = await self._get_ocr_text_from_image(image_path)
            
            if not ocr_text:
                logger.warning("OCR returned no text, cannot extract data")
                return {}
            
            logger.info(f"OCR text extracted: {ocr_text[:200]}...")
            
            # Extract data from OCR text
            data = self._extract_data_from_ocr_text(ocr_text)
            
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
    
    async def _get_ocr_text_from_image(self, image_path: str) -> str:
        """
        Extract text from image using OCR.space API
        
        Args:
            image_path: Path to image file
            
        Returns:
            Extracted text
        """
        try:
            # Check if we should use the OCR.space API
            if not self.api_key:
                logger.warning("No OCR.space API key available")
                return ""
                
            logger.info(f"Reading image file: {image_path}")
            
            # Read image as base64
            try:
                with open(image_path, 'rb') as image_file:
                    image_data = image_file.read()
                    file_size = len(image_data)
                    logger.info(f"Image file size: {file_size} bytes")
                    
                    if file_size > 1024 * 1024:
                        logger.warning(f"Image file is large ({file_size/1024/1024:.2f} MB), may exceed API limits")
                    
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    logger.info(f"Image successfully encoded to base64, length: {len(base64_image)}")
            except Exception as file_error:
                logger.error(f"Error reading image file: {str(file_error)}")
                return ""
            
            # Send to OCR.space API
            url = 'https://api.ocr.space/parse/image'
            
            try:
                # Try a direct file upload first - more reliable for larger images
                # First try with file upload
                logger.info(f"Sending image to OCR.space API via file upload")
                form_data = aiohttp.FormData()
                form_data.add_field('apikey', self.api_key)
                form_data.add_field('language', 'eng')
                form_data.add_field('OCREngine', '2')  # Use more advanced engine
                form_data.add_field('scale', 'true')
                form_data.add_field('isOverlayRequired', 'false')
                form_data.add_field('file', image_data, 
                                   filename=os.path.basename(image_path),
                                   content_type='image/png')
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data=form_data) as response:
                        logger.info(f"OCR.space API response status: {response.status}")
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"OCR.space API error: {response.status}, Response: {error_text}")
                            return ""
                        
                        try:
                            result = await response.json()
                            logger.info(f"OCR.space API response: {json.dumps(result)[:200]}...")
                        except Exception as json_error:
                            logger.error(f"Error parsing JSON response: {str(json_error)}")
                            response_text = await response.text()
                            logger.error(f"Raw response: {response_text[:500]}")
                            return ""
                        
                        if result.get('IsErroredOnProcessing'):
                            logger.error(f"OCR processing error: {result.get('ErrorMessage', 'Unknown error')}")
                            logger.error(f"Full error details: {json.dumps(result)}")
                            return ""
                        
                        parsed_results = result.get('ParsedResults', [])
                        if not parsed_results:
                            logger.warning("No OCR results returned")
                            return ""
                        
                        ocr_text = parsed_results[0].get('ParsedText', '')
                        logger.info(f"OCR.space API returned {len(ocr_text)} chars of text")
                        return ocr_text
            
            except Exception as api_error:
                logger.error(f"Error calling OCR.space API: {str(api_error)}")
                import traceback
                logger.error(f"API call traceback: {traceback.format_exc()}")
                return ""
        
        except Exception as e:
            logger.error(f"Error in OCR processing: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return ""
    
    def _extract_data_from_ocr_text(self, ocr_text: str) -> Dict[str, Any]:
        """
        Extract price and indicator data from OCR text
        
        Args:
            ocr_text: Text extracted from chart image
            
        Returns:
            Dict with extracted data
        """
        data = {}
        
        try:
            # Log the full OCR text for debugging
            logger.info(f"Full OCR text for extraction:\n{ocr_text}")
            
            # Extract price
            price_patterns = [
                r'(?:price|current)[:\s]+?(\d+\.\d+)',  # "price: 1.2345" or "current: 1.2345"
                r'(\d+\.\d{4,5})(?:\s|$)',              # Any 4-5 decimal number like "1.2345"
                r'[^\d](\d\.\d{4,5})(?:\s|$)'           # Single digit with 4-5 decimals
            ]
            
            for pattern in price_patterns:
                price_match = re.search(pattern, ocr_text, re.IGNORECASE)
                if price_match:
                    price = float(price_match.group(1))
                    logger.info(f"Price extracted from OCR: {price}")
                    data['current_price'] = price
                    break
            
            # Extract RSI
            rsi_match = re.search(r'RSI[:\s]+(\d+\.?\d*)', ocr_text, re.IGNORECASE)
            if rsi_match:
                rsi = float(rsi_match.group(1))
                logger.info(f"RSI extracted from OCR: {rsi}")
                data['rsi'] = rsi
            
            # Extract MACD
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
