"""
Instrument Manager for handling instrument and market selections.
"""
import logging
from typing import Dict, List, Optional, Tuple

from utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)

# Global instance of config manager
_config_manager = None

def _get_config():
    """Get or create the global config manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager

class InstrumentManager:
    """
    Manages instrument and market selections for the trading bot.
    """
    
    def __init__(self, supported_instruments: List[str], supported_markets: Dict[str, List[str]]):
        """
        Initialize the instrument manager.
        
        Args:
            supported_instruments: List of supported instrument codes
            supported_markets: Dictionary mapping instruments to supported markets
        """
        self._supported_instruments = supported_instruments
        self._supported_markets = supported_markets
        self._user_selections: Dict[int, Dict[str, str]] = {}  # user_id -> {instrument, market}
        
    def get_supported_instruments(self) -> List[str]:
        """Get the list of supported instruments."""
        return self._supported_instruments
    
    def get_supported_markets(self, instrument: str) -> List[str]:
        """
        Get the supported markets for a given instrument.
        
        Args:
            instrument: The instrument code (e.g., 'eurusd')
            
        Returns:
            List of supported market names
        """
        instrument = instrument.lower()
        return self._supported_markets.get(instrument, [])
    
    def set_user_selection(self, user_id: int, instrument: str, market: str):
        """
        Set the instrument and market selection for a user.
        
        Args:
            user_id: Telegram user ID
            instrument: The selected instrument
            market: The selected market
        """
        self._user_selections[user_id] = {
            'instrument': instrument.lower(),
            'market': market.lower()
        }
        logger.info(f"User {user_id} selected {instrument}/{market}")
    
    def get_user_selection(self, user_id: int) -> Optional[Dict[str, str]]:
        """
        Get the current instrument and market selection for a user.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Dictionary with 'instrument' and 'market' keys, or None if not set
        """
        return self._user_selections.get(user_id)
    
    def clear_user_selection(self, user_id: int):
        """
        Clear the instrument and market selection for a user.
        
        Args:
            user_id: Telegram user ID
        """
        if user_id in self._user_selections:
            del self._user_selections[user_id]
            logger.info(f"Cleared selection for user {user_id}")
            
    def is_valid_selection(self, instrument: str, market: str) -> bool:
        """
        Check if the given instrument and market combination is valid.
        
        Args:
            instrument: The instrument code
            market: The market name
            
        Returns:
            True if valid, False otherwise
        """
        instrument = instrument.lower()
        market = market.lower()
        
        if instrument not in self._supported_instruments:
            return False
            
        supported_markets = self._supported_markets.get(instrument, [])
        return market in supported_markets

# Helper functions used by the bot
def get_instruments() -> List[str]:
    """
    Get a list of all supported instruments.
    
    Returns:
        List of instrument codes
    """
    config = _get_config()
    return config.SUPPORTED_INSTRUMENTS

def get_markets_for_instrument(instrument: str) -> List[str]:
    """
    Get a list of supported markets for a given instrument.
    
    Args:
        instrument: The instrument code (e.g., 'eurusd')
        
    Returns:
        List of supported market names
    """
    config = _get_config()
    instrument = instrument.lower()
    markets = config.SUPPORTED_MARKETS.get(instrument, [])
    return markets 
