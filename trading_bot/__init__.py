# Trading Bot Package
# Minimize imports here to prevent circular dependencies

# Define version
__version__ = '2.0.0'

# Import hack voor backward compatibility
from trading_bot.services.chart_service.tradingview_selenium import TradingViewSeleniumService
from trading_bot.services.chart_service.tradingview_playwright import TradingViewPlaywrightService
from trading_bot.services.calendar_service.calendar import EconomicCalendarService

# Voor backward compatibility
TradingViewPuppeteerService = TradingViewPlaywrightService

# Leeg bestand of minimale imports
# Vermijd het importeren van ChartService en TradingViewSeleniumService hier
