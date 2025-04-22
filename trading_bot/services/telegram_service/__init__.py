try:
    from .bot import TelegramService
except ImportError:
    import os
    import sys
    import logging
    import importlib.util
    import inspect
    
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
                # Try to find any class that could be TelegramService, but be more specific
                logger.warning("No TelegramService found in module, looking for matching class")
                
                # Try to find by actually looking at the source code of the module
                with open(bot_py_path, 'r') as f:
                    source_code = f.read()
                
                # Look for class definition pattern
                if 'class TelegramService:' in source_code or 'class TelegramService(' in source_code:
                    logger.info("Found TelegramService class definition in source code")
                    
                    # Now look for classes defined in the module that might match our criteria
                    service_class = None
                    for name in dir(telegram_bot_module):
                        item = getattr(telegram_bot_module, name)
                        
                        # Skip obvious non-matches
                        if not isinstance(item, type):
                            continue
                        
                        # Skip exception classes and imported telegram API classes
                        if name.endswith('Error') or name in ['Bot', 'Update', 'CallbackQuery']:
                            continue
                            
                        # Check class attributes to see if it's likely our service class
                        # Look for common TelegramService methods
                        service_methods = ['run', 'initialize_services', 'process_signal', 'update_message']
                        method_count = 0
                        
                        for method in service_methods:
                            if hasattr(item, method) and callable(getattr(item, method)):
                                method_count += 1
                        
                        # If class has at least 2 of our expected methods, it's likely the one
                        if method_count >= 2:
                            service_class = item
                            logger.info(f"Found matching service class: {name} with {method_count} matching methods")
                            break
                            
                        # Alternatively check for __init__ method with our expected parameters
                        try:
                            init_params = list(inspect.signature(item.__init__).parameters.keys())
                            if 'db' in init_params and ('stripe_service' in init_params or len(init_params) >= 3):
                                service_class = item
                                logger.info(f"Found matching class by __init__ params: {name}")
                                break
                        except (ValueError, TypeError):
                            pass
                    
                    # If found a match, use it
                    if service_class:
                        TelegramService = service_class
                        # Also add it to the module for consistency
                        telegram_bot_module.TelegramService = service_class
                    else:
                        raise ImportError("Could not identify TelegramService class in module")
                else:
                    raise ImportError("Could not find TelegramService class definition in source code")
        except Exception as e:
            logger.error(f"Error importing TelegramService: {str(e)}")
            raise

__all__ = ['TelegramService']
