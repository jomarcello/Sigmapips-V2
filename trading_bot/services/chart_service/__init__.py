# Leeg bestand om de map als een Python-pakket te markeren
# Vermijd ALLE imports hier om circulaire imports te voorkomen

# Import hack voor backward compatibility
from trading_bot.services.chart_service.tradingview_selenium import TradingViewSeleniumService
from trading_bot.services.chart_service.tradingview_playwright import TradingViewPlaywrightService

# Voor backward compatibility
TradingViewPuppeteerService = TradingViewPlaywrightService

# Leeg bestand of minimale imports
# Vermijd het importeren van ChartService en TradingViewSeleniumService hier

# Exporteer de ChartService klasse
from trading_bot.services.chart_service.chart import ChartService as _ChartService

# Maak een alias voor eenvoudige import
ChartService = _ChartService

# This file can be empty, it just marks the directory as a Python package

# Eenvoudige versie zonder circulaire imports
from trading_bot.services.chart_service.chart import ChartService

# Vermijd het importeren van andere services hier om circulaire imports te voorkomen



