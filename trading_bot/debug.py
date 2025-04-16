import sys
import os
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("debug")

def debug_imports():
    logger.debug("Python version: %s", sys.version)
    logger.debug("Python path: %s", sys.path)
    logger.debug("Current directory: %s", os.getcwd())
    
    # Probeer de imports handmatig
    try:
        logger.debug("Importing chart module...")
        import trading_bot.services.chart_service.chart
        logger.debug("Chart module imported successfully")
        
        # Controleer of ChartService bestaat in de module
        if hasattr(trading_bot.services.chart_service.chart, 'ChartService'):
            logger.debug("ChartService class found in chart module")
        else:
            logger.debug("ChartService class NOT found in chart module")
            
        # Toon alle attributen in de module
        logger.debug("Chart module attributes: %s", dir(trading_bot.services.chart_service.chart))
        
    except Exception as e:
        logger.error("Error importing chart module: %s", str(e))
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    debug_imports() 
