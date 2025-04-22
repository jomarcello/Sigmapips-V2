try:
    from .bot import TelegramService
except ImportError:
    import os
    import sys
    import logging
    import importlib.util
    
    logger = logging.getLogger(__name__)
    logger.warning("Could not import TelegramService directly, using fallback mechanism")
    
    # Path to the bot.py file - finding the absolute path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    bot_py_path = os.path.join(current_dir, 'bot.py')
    
    if os.path.exists(bot_py_path):
        logger.info(f"Loading TelegramService from {bot_py_path}")
        
        # Load the module from the file path
        try:
            # First try - direct spec load
            spec = importlib.util.spec_from_file_location("telegram_service_bot", bot_py_path)
            telegram_bot_module = importlib.util.module_from_spec(spec)
            sys.modules["telegram_service_bot"] = telegram_bot_module
            spec.loader.exec_module(telegram_bot_module)
            
            # Check if TelegramService exists in the module
            if hasattr(telegram_bot_module, 'TelegramService'):
                logger.info("Successfully loaded TelegramService from bot.py")
                TelegramService = telegram_bot_module.TelegramService
            else:
                # Try to find any class that could be TelegramService
                logger.warning("No TelegramService found in module, looking for matching class")
                for name in dir(telegram_bot_module):
                    item = getattr(telegram_bot_module, name)
                    if isinstance(item, type) and ("telegram" in name.lower() or "service" in name.lower()):
                        logger.info(f"Found possible match: {name}")
                        TelegramService = item
                        # Also add it to the module for consistency
                        telegram_bot_module.TelegramService = item
                        break
        except Exception as e:
            logger.error(f"Error importing TelegramService: {str(e)}")
            raise

__all__ = ['TelegramService']
