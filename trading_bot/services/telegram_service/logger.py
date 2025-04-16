"""
Logger configuration for the Telegram bot service
"""

import logging
import sys

# Create logger
logger = logging.getLogger('trading_bot.services.telegram_service')
logger.setLevel(logging.INFO)

# Create console handler and set level to debug
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

# Create formatter
formatter = logging.Formatter('%(levelname)s: %(name)s: %(message)s')

# Add formatter to console handler
console_handler.setFormatter(formatter)

# Add console handler to logger
logger.addHandler(console_handler)

# Prevent log messages from being propagated to the root logger
logger.propagate = False 
