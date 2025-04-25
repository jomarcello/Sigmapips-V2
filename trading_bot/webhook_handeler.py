"""
Webhook handler for Telegram bot API.
This is a standalone module to handle webhook requests.
"""

import logging
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WebhookHandler:
    """Handler for Telegram webhooks"""
    
    def __init__(self):
        """Initialize the webhook handler"""
        self.logger = logging.getLogger(__name__)
    
    async def handle_webhook(self, request: Request):
        """Handle a webhook request"""
        try:
            # Log the incoming request
            body = await request.body()
            self.logger.info(f"Received webhook payload: {body.decode('utf-8')[:100]}...")
            
            # Parse JSON data
            try:
                data = await request.json()
            except json.JSONDecodeError:
                self.logger.error("Invalid JSON in request body")
                return JSONResponse(content={"status": "error", "message": "Invalid JSON"}, status_code=400)
            
            # Log the parsed data
            self.logger.info(f"Webhook data: {data}")
            
            # Return success
            return JSONResponse(content={"status": "success", "message": "Webhook received"})
        except Exception as e:
            self.logger.error(f"Error processing webhook: {str(e)}")
            return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)
            
    async def register_routes(self, app: FastAPI):
        """Register webhook routes to the FastAPI app"""
        
        @app.post("/webhook")
        async def webhook(request: Request):
            """Main webhook endpoint"""
            return await self.handle_webhook(request)
            
        @app.post("/webhook/webhook")
        async def webhook_doubled(request: Request):
            """Handle doubled webhook path"""
            self.logger.info("Received request on doubled webhook path")
            return await self.handle_webhook(request)
            
        self.logger.info("Webhook routes registered")
        
# Create a singleton instance
webhook_handler = WebhookHandler() 
