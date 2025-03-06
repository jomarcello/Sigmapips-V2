# Import hack voor backward compatibility
from trading_bot.services.chart_service.tradingview_selenium import TradingViewSeleniumService
from trading_bot.services.chart_service.tradingview_playwright import TradingViewPlaywrightService

# Voor backward compatibility
TradingViewPuppeteerService = TradingViewPlaywrightService

# Leeg bestand of minimale imports
# Vermijd het importeren van ChartService en TradingViewSeleniumService hier

# This file can be empty, it just marks the directory as a Python package



