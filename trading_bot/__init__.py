# Import hack voor backward compatibility
from trading_bot.services.chart_service.tradingview_selenium import TradingViewSeleniumService
from trading_bot.services.chart_service.tradingview_playwright import TradingViewPlaywrightService
from trading_bot.services.telegram_service.bot import TelegramService

# Voor backward compatibility
TradingViewPuppeteerService = TradingViewPlaywrightService

# Leeg bestand of minimale imports
# Vermijd het importeren van ChartService en TradingViewSeleniumService hier

__all__ = ['TelegramService', 'TradingViewSeleniumService']
