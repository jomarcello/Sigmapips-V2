# Trading Bot Package
# Minimize imports here to prevent circular dependencies

# Define version
__version__ = '2.0.0'

# DO NOT import app here - it causes circular dependencies
# Comment out this problematic import
"""
try:
    from trading_bot.main import app
except ImportError:
    # Provide fallback for testing or when main isn't available
    import logging
    logging.warning("Could not import app from trading_bot.main")
"""
# No direct app import to avoid circular dependencies

# Import hack for backward compatibility only, do not use these imports in new code
from trading_bot.services.chart_service.tradingview_selenium import TradingViewSeleniumService
from trading_bot.services.chart_service.tradingview_playwright import TradingViewPlaywrightService

# For backward compatibility
TradingViewPuppeteerService = TradingViewPlaywrightService

# DO NOT import other services here to avoid circular dependencies
# Import directly from the specific modules instead
