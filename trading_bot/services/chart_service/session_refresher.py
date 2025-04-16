import asyncio
import os
import logging
from datetime import datetime, timedelta
from trading_bot.services.chart_service.tradingview_session import TradingViewSessionService

logger = logging.getLogger(__name__)

class SessionRefresher:
    def __init__(self, refresh_interval_hours=12):
        """Initialize the session refresher"""
        self.refresh_interval = timedelta(hours=refresh_interval_hours)
        self.last_refresh = datetime.now()
        self.username = os.getenv("TRADINGVIEW_USERNAME", "")
        self.password = os.getenv("TRADINGVIEW_PASSWORD", "")
        self.session_id = os.getenv("TRADINGVIEW_SESSION_ID", "")
        self.is_running = False
    
    async def start(self):
        """Start the session refresher"""
        self.is_running = True
        while self.is_running:
            # Controleer of de session ID moet worden vernieuwd
            if datetime.now() - self.last_refresh >= self.refresh_interval:
                await self.refresh_session()
            
            # Wacht een uur voordat we opnieuw controleren
            await asyncio.sleep(3600)
    
    async def refresh_session(self):
        """Refresh the session ID"""
        try:
            logger.info("Refreshing TradingView session ID")
            
            # Maak een nieuwe TradingViewSessionService
            service = TradingViewSessionService()
            
            # Initialiseer de service
            initialized = await service.initialize()
            
            if initialized and service.is_logged_in and service.session_id:
                # Update de session ID
                self.session_id = service.session_id
                self.last_refresh = datetime.now()
                
                # Update de omgevingsvariabele
                os.environ["TRADINGVIEW_SESSION_ID"] = self.session_id
                
                # Update het .env bestand
                env_file = ".env"
                
                if os.path.exists(env_file):
                    # Lees het bestaande .env bestand
                    with open(env_file, "r") as f:
                        lines = f.readlines()
                    
                    # Controleer of TRADINGVIEW_SESSION_ID al bestaat
                    session_id_exists = False
                    
                    for i, line in enumerate(lines):
                        if line.startswith("TRADINGVIEW_SESSION_ID="):
                            lines[i] = f"TRADINGVIEW_SESSION_ID={self.session_id}\n"
                            session_id_exists = True
                            break
                    
                    # Voeg TRADINGVIEW_SESSION_ID toe als het niet bestaat
                    if not session_id_exists:
                        lines.append(f"TRADINGVIEW_SESSION_ID={self.session_id}\n")
                    
                    # Schrijf terug naar het .env bestand
                    with open(env_file, "w") as f:
                        f.writelines(lines)
                
                logger.info(f"Session ID refreshed: {self.session_id[:10]}...")
            else:
                logger.error("Failed to refresh session ID")
            
            # Ruim de service op
            await service.cleanup()
            
        except Exception as e:
            logger.error(f"Error refreshing session ID: {str(e)}")
    
    async def stop(self):
        """Stop the session refresher"""
        self.is_running = False 
