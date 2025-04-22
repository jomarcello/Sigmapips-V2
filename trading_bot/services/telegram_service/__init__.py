import importlib.util
import os
import sys
import logging

logger = logging.getLogger(__name__)

# First try the direct import
try:
    from .bot import TelegramService
    logger.info("Successfully imported TelegramService through normal import")
except ImportError:
    # Direct import failed, load the module from file
    logger.warning("Could not import TelegramService directly, using fallback mechanism")
    
    # Path to the bot.py file - finding the absolute path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    bot_py_path = os.path.join(current_dir, 'bot.py')
    
    if os.path.exists(bot_py_path):
        logger.info(f"Loading TelegramService from {bot_py_path}")
        
        # Load the module from the file path
        try:
            # Define a module name that won't conflict with existing modules
            module_name = "trading_bot.services.telegram_service.bot_direct"
            
            # Create and load the module spec
            spec = importlib.util.spec_from_file_location(module_name, bot_py_path)
            telegram_bot_module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = telegram_bot_module
            spec.loader.exec_module(telegram_bot_module)
            
            # Look for the TelegramService class in the file content
            with open(bot_py_path, 'r') as f:
                content = f.read()
                
            if "class TelegramService:" in content or "class TelegramService(" in content:
                # Class definition exists in the file
                
                # Define TelegramService manually based on what's in the file
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
                    
                    def __getattr__(self, name):
                        # Proxy all attribute access to the real service
                        return getattr(self._real_service, name)
                
                logger.info("Successfully loaded TelegramService via proxy class")
            else:
                logger.error("TelegramService class definition not found in source code")
                raise ImportError("Could not find TelegramService class definition in source code")
        except Exception as e:
            logger.error(f"Error importing TelegramService: {str(e)}")
            raise ImportError(f"Could not import TelegramService: {str(e)}")
    else:
        logger.error(f"bot.py file not found at {bot_py_path}")
        raise ImportError("bot.py file not found")

__all__ = ['TelegramService']
