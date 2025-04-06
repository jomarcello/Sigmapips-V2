# Trading Bot Package
# Minimize imports here to prevent circular dependencies

# Define version
__version__ = '2.0.0'

# Import hack for backward compatibility only, do not use these imports in new code
from trading_bot.services.chart_service.tradingview_selenium import TradingViewSeleniumService
from trading_bot.services.chart_service.tradingview_playwright import TradingViewPlaywrightService

# For backward compatibility
TradingViewPuppeteerService = TradingViewPlaywrightService

# DO NOT import other services here to avoid circular dependencies
# Import directly from the specific modules instead
