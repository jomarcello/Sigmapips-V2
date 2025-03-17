async def get_chart(self, instrument: str, timeframe: str = "1h", fullscreen: bool = False) -> bytes:
    """Get chart image for instrument and timeframe"""
    try:
        logger.info(f"Getting chart for {instrument} ({timeframe}) fullscreen: {fullscreen}")
        
        # Zorg ervoor dat de services zijn geïnitialiseerd
        if not hasattr(self, 'tradingview') or not self.tradingview:
            logger.info("Services not initialized, initializing now")
            await self.initialize()
        
        # Normaliseer instrument (verwijder /)
        instrument = instrument.upper().replace("/", "")
        
        # Gebruik de TradingView link voor dit instrument
        tradingview_link = self.chart_links.get(instrument)
        if not tradingview_link:
            # Als er geen specifieke link is, gebruik een generieke link
            logger.warning(f"No specific link found for {instrument}, using generic link")
            tradingview_link = f"https://www.tradingview.com/chart/?symbol={instrument}"
        
        # Voeg fullscreen parameter toe aan de URL als dat nodig is
        if fullscreen:
            if "?" in tradingview_link:
                tradingview_link += "&fullscreen=true&hide_side_toolbar=true&hide_top_toolbar=true"
            else:
                tradingview_link += "?fullscreen=true&hide_side_toolbar=true&hide_top_toolbar=true"
        
        logger.info(f"Using TradingView link: {tradingview_link}")
        
        # Probeer eerst de Node.js service te gebruiken
        if hasattr(self, 'tradingview') and self.tradingview and hasattr(self.tradingview, 'take_screenshot_of_url'):
            try:
                logger.info(f"Taking screenshot with Node.js service: {tradingview_link}")
                chart_image = await self.tradingview.take_screenshot_of_url(tradingview_link)
                if chart_image:
                    logger.info("Screenshot taken successfully with Node.js service")
                    return chart_image
                else:
                    logger.error("Node.js screenshot is None")
            except Exception as e:
                logger.error(f"Error using Node.js for screenshot: {str(e)}")
        
        # Als Node.js niet werkt, probeer Selenium
        if hasattr(self, 'tradingview_selenium') and self.tradingview_selenium and self.tradingview_selenium.is_initialized:
            try:
                logger.info(f"Taking screenshot with Selenium: {tradingview_link}")
                chart_image = await self.tradingview_selenium.get_screenshot(tradingview_link, fullscreen)
                if chart_image:
                    logger.info("Screenshot taken successfully with Selenium")
                    return chart_image
                else:
                    logger.error("Selenium screenshot is None")
            except Exception as e:
                logger.error(f"Error using Selenium for screenshot: {str(e)}")
        
        # Als beide services niet werken, gebruik een fallback methode
        logger.warning(f"All screenshot services failed, using fallback for {instrument}")
        return await self._generate_random_chart(instrument, timeframe)
    
    except Exception as e:
        logger.error(f"Error getting chart: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Als er een fout optreedt, genereer een matplotlib chart
        logger.warning(f"Error occurred, using fallback for {instrument}")
        return await self._generate_random_chart(instrument, timeframe)
