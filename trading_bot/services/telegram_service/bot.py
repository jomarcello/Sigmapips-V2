from typing import List

class TelegramBot:
    async def _get_signal_subscribers(self, market: str, instrument: str) -> List[int]:
        """Get list of subscribers for a specific market and instrument"""
        try:
            # Haal alle subscribers op
            response = await self.db.get_subscribers()
            
            # Check if the response is valid and has data
            if not hasattr(response, 'data') or not response.data:
                logger.info(f"No subscribers found in database")
                return []
                
            all_subscribers = response.data
            logger.info(f"Found {len(all_subscribers)} total subscribers in database")
            
            # Filter subscribers op basis van market en instrument
            matching_subscribers = []
            
            for subscriber in all_subscribers:
                try:
                    # Haal preferences op voor deze subscriber
                    user_id = subscriber['user_id']
                    preferences_response = await self.db.get_subscriber_preferences(user_id)
                    
                    logger.info(f"Checking preferences for user {user_id}")
                    
                    # Log each preference for debugging
                    for pref in preferences_response:
                        pref_market = pref.get('market', '').lower()
                        pref_instrument = pref.get('instrument', '').upper()
                        logger.info(f"User {user_id} has preference: market={pref_market}, instrument={pref_instrument}")
                        
                        # Check if this preference matches our signal
                        is_market_match = pref_market == market.lower()
                        is_instrument_match = pref_instrument == instrument.upper() or pref_instrument == 'ALL'
                        
                        if is_market_match and is_instrument_match:
                            logger.info(f"Found matching preference for user {user_id}: {pref}")
                            matching_subscribers.append(user_id)
                            break
                        else:
                            logger.info(f"No match for user {user_id}: Signal({market.lower()},{instrument.upper()}) vs Pref({pref_market},{pref_instrument})")
                            
                except Exception as inner_e:
                    logger.error(f"Error processing subscriber {subscriber}: {str(inner_e)}")
            
            logger.info(f"Found {len(matching_subscribers)} subscribers matching {market}/{instrument}")
            return matching_subscribers
            
        except Exception as e:
            logger.error(f"Error getting signal subscribers: {str(e)}")
            return []
