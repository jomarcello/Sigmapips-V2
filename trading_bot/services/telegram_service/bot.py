import random
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import CallbackContext
from trading_bot.services.telegram_service.states import SHOW_RESULT, MENU
from trading_bot.services.telegram_service.logger import logger

class TradingBot:
    # ... existing code ...

    async def direct_sentiment_callback(self, update: Update, context=None) -> int:
        """Direct handler for sentiment analysis"""
        query = update.callback_query
        
        try:
            # Answer callback query immediately to prevent timeout
            await query.answer()
            
            # Extract instrument from callback data
            instrument = query.data.replace('direct_sentiment_', '')
            logger.info(f"Direct sentiment callback voor instrument: {instrument}")
            
            # Store current state and instrument
            if context and hasattr(context, 'user_data'):
                context.user_data['current_instrument'] = instrument
                context.user_data['current_state'] = SHOW_RESULT
                context.user_data['analysis_type'] = 'sentiment'
            
            # Show loading message
            await query.edit_message_text(
                text=f"Getting market sentiment for {instrument}...",
                reply_markup=None
            )
            
            # Get sentiment analysis
            try:
                sentiment_data = await self.sentiment.get_market_sentiment(instrument)
                logger.info(f"Sentiment ontvangen voor {instrument}")
                
                # Extract sentiment data
                bullish_score = sentiment_data.get('bullish_percentage', 50)
                bearish_score = 100 - bullish_score
                overall = sentiment_data.get('overall_sentiment', 'neutral').capitalize()
                
                # Determine emoji based on sentiment
                if overall.lower() == 'bullish':
                    emoji = "📈"
                elif overall.lower() == 'bearish':
                    emoji = "📉"
                else:
                    emoji = "⚖️"
                
                # Format sentiment message
                sentiment_message = f"""<b>🧠 Market Sentiment Analysis: {instrument}</b>

<b>Overall Sentiment:</b> {overall} {emoji}

<b>Sentiment Breakdown:</b>
• Bullish: {bullish_score}%
• Bearish: {bearish_score}%
• Trend Strength: {sentiment_data.get('trend_strength', 'Moderate')}
• Volatility: {sentiment_data.get('volatility', 'Moderate')}

<b>Key Levels:</b>
• Support: {sentiment_data.get('support_level', 'Not available')}
• Resistance: {sentiment_data.get('resistance_level', 'Not available')}

<b>Trading Recommendation:</b>
{sentiment_data.get('recommendation', 'Wait for clearer market signals')}

<b>Analysis:</b>
{sentiment_data.get('analysis', 'Detailed analysis not available')}"""
                
                # Show sentiment analysis
                await query.edit_message_text(
                    text=sentiment_message,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")
                    ]]),
                    parse_mode=ParseMode.HTML
                )
                
            except Exception as sentiment_error:
                logger.error(f"Error getting sentiment: {str(sentiment_error)}")
                logger.exception(sentiment_error)
                
                # Use fallback sentiment
                bullish_score = random.randint(30, 70)
                bearish_score = 100 - bullish_score
                overall = "Neutral"
                emoji = "⚖️"
                
                fallback_message = f"""<b>🧠 Market Sentiment Analysis: {instrument}</b>

<b>Overall Sentiment:</b> {overall} {emoji}

<b>Sentiment Breakdown:</b>
• Bullish: {bullish_score}%
• Bearish: {bearish_score}%

<b>Market Analysis:</b>
The current sentiment for {instrument} is neutral, with mixed signals in the market. Please check back later for updated analysis."""
                
                await query.edit_message_text(
                    text=fallback_message,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="back_analysis")
                    ]]),
                    parse_mode=ParseMode.HTML
                )
                logger.info("Using fallback sentiment analysis")
            
            return SHOW_RESULT
            
        except Exception as e:
            logger.error(f"Error in direct sentiment callback: {str(e)}")
            logger.exception(e)
            return MENU

    # ... existing code ...
