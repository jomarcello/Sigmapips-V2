import importlib.util
import os
import sys
import logging

logger = logging.getLogger(__name__)

# Direct import approach that avoids circular imports
try:
    # Create a module spec directly from the file path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    bot_py_path = os.path.join(current_dir, 'bot.py')
    
    if os.path.exists(bot_py_path):
        # Define a unique module name that won't conflict
        module_name = "trading_bot.services.telegram_service.bot_direct"
        
        # Create and load the module spec
        spec = importlib.util.spec_from_file_location(module_name, bot_py_path)
        telegram_bot_module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = telegram_bot_module
        
        # Execute the module
        spec.loader.exec_module(telegram_bot_module)
        
        # Import TelegramService class from the module
        if hasattr(telegram_bot_module, 'TelegramService'):
            # Create a proxy class to avoid any potential circular imports
            class TelegramService:
                def __init__(self, db, stripe_service=None, bot_token=None, proxy_url=None, lazy_init=False):
                    # Forward to the real implementation
                    self._real_service = telegram_bot_module.TelegramService(
                        db=db, 
                        stripe_service=stripe_service,
                        bot_token=bot_token,
                        proxy_url=proxy_url,
                        lazy_init=lazy_init
                    )
                
                # Required methods that are explicitly checked for
                async def run(self):
                    return await self._real_service.run()
                    
                async def initialize_services(self):
                    return await self._real_service.initialize_services()
                
                def __getattr__(self, name):
                    # Proxy all other attribute access to the real service
                    return getattr(self._real_service, name)
                
                def __setattr__(self, name, value):
                    # Special case for _real_service
                    if name == "_real_service":
                        super().__setattr__(name, value)
                    else:
                        # Forward all other attribute assignments to the real service
                        setattr(self._real_service, name, value)
            
            logger.info("Successfully loaded TelegramService from bot.py")
        else:
            logger.error("TelegramService class not found in bot.py module")
            raise ImportError("TelegramService class not found in bot.py module")
    else:
        logger.error(f"bot.py file not found at {bot_py_path}")
        raise ImportError(f"bot.py file not found at {bot_py_path}")

except Exception as e:
    logger.error(f"Failed to import TelegramService: {str(e)}")
    raise ImportError(f"Failed to import TelegramService: {str(e)}")

__all__ = ['TelegramService']
