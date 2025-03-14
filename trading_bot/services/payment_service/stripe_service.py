import stripe
import logging
import datetime
from typing import Dict, Any, Optional, Tuple
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from trading_bot.services.payment_service.stripe_config import stripe, get_price_id, get_subscription_features
from trading_bot.services.database.db import Database

logger = logging.getLogger(__name__)

class StripeService:
    def __init__(self, db: Database):
        self.db = db
    
    async def create_checkout_session(self, user_id: int, plan_type: str = 'monthly', success_url: str = None, cancel_url: str = None) -> Optional[str]:
        """Create a Stripe Checkout session for a subscription"""
        try:
            # Check if the user already has a stripe_customer_id
            user_subscription = await self.db.get_user_subscription(user_id)
            customer_id = user_subscription.get('stripe_customer_id') if user_subscription else None
            
            # Use the correct price_id based on the plan
            price_id = get_price_id(plan_type)
            
            # Set the success and cancel URLs
            if not success_url:
                success_url = f"https://t.me/SignapipsAI_bot?start=success_{plan_type}"
            if not cancel_url:
                cancel_url = f"https://t.me/SignapipsAI_bot?start=cancel"
            
            # Haal trial periode op uit configuratie
            subscription_features = get_subscription_features(plan_type)
            trial_days = subscription_features.get('trial_days', 14)
            
            # Create the checkout session
            checkout_session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=['card'],
                line_items=[
                    {
                        'price': price_id,
                        'quantity': 1,
                    },
                ],
                mode='subscription',
                subscription_data={
                    'trial_period_days': trial_days  # 14-daagse proefperiode
                },
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=str(user_id),  # Use Telegram user_id as reference
                metadata={
                    'user_id': str(user_id),
                    'plan_type': plan_type
                }
            )
            
            logger.info(f"Created checkout session for user {user_id}, plan {plan_type}: {checkout_session.id}")
            return checkout_session.url
            
        except Exception as e:
            logger.error(f"Error creating checkout session: {str(e)}")
            return None
    
    async def handle_subscription_created(self, event_data: Dict[str, Any]) -> bool:
        """Verwerk een subscription.created event van Stripe"""
        try:
            subscription = event_data['object']
            customer_id = subscription.get('customer')
            subscription_id = subscription.get('id')
            status = subscription.get('status')
            
            # Haal de user_id op uit de metadata van de checkout session
            if 'metadata' in subscription and 'user_id' in subscription['metadata']:
                user_id = int(subscription['metadata']['user_id'])
            else:
                # Als de user_id niet in de metadata staat, moeten we de checkout session opzoeken
                checkout_session_id = subscription.get('metadata', {}).get('checkout_session_id')
                if checkout_session_id:
                    session = stripe.checkout.Session.retrieve(checkout_session_id)
                    user_id = int(session.get('client_reference_id', 0))
                else:
                    logger.error(f"Could not find user_id for subscription {subscription_id}")
                    return False
            
            # Bepaal het abonnementstype op basis van het product
            plan_type = 'basic'  # Standaard
            if 'items' in subscription and 'data' in subscription['items']:
                for item in subscription['items']['data']:
                    if 'price' in item:
                        price_id = item['price']['id']
                        # Hier zou je een mapping moeten hebben van price_id naar plan_type
                        if price_id == get_price_id('premium'):
                            plan_type = 'premium'
                        elif price_id == get_price_id('pro'):
                            plan_type = 'pro'
            
            # Bereken de einddatum van de periode
            current_period_end = datetime.datetime.fromtimestamp(
                subscription.get('current_period_end', 0), 
                tz=datetime.timezone.utc
            )
            
            # Update de database
            success = await self.db.create_or_update_subscription(
                user_id=user_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                status=status,
                subscription_type=plan_type,
                current_period_end=current_period_end
            )
            
            if success:
                logger.info(f"Updated subscription for user {user_id}: {status}")
                return True
            else:
                logger.error(f"Failed to update subscription for user {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error handling subscription created: {str(e)}")
            return False
    
    async def handle_subscription_updated(self, event_data: Dict[str, Any]) -> bool:
        """Verwerk een subscription.updated event van Stripe"""
        # Vergelijkbare logica als handle_subscription_created
        try:
            subscription = event_data['object']
            subscription_id = subscription.get('id')
            status = subscription.get('status')
            
            # Haal het abonnement op uit de database op basis van stripe_subscription_id
            # In een echte implementatie zou je hier een query moeten doen
            # Voor nu doen we een dummyrequest naar de Stripe API om de klant te vinden
            user_subscription = None
            
            # Haal de user_id op uit de metadata van de abonnement
            if 'metadata' in subscription and 'user_id' in subscription['metadata']:
                user_id = int(subscription['metadata']['user_id'])
            else:
                # Als alternatief, zoek in de database op subscription_id
                # Dit is een dummy-implementatie; in werkelijkheid zou je hier een database-query doen
                logger.warning(f"User ID not found in metadata for subscription {subscription_id}")
                return False
            
            # Bereken de einddatum van de periode
            current_period_end = datetime.datetime.fromtimestamp(
                subscription.get('current_period_end', 0), 
                tz=datetime.timezone.utc
            )
            
            # Update de database
            await self.db.create_or_update_subscription(
                user_id=user_id,
                stripe_subscription_id=subscription_id,
                status=status,
                current_period_end=current_period_end
            )
            
            logger.info(f"Updated subscription {subscription_id} status to {status}")
            return True
            
        except Exception as e:
            logger.error(f"Error handling subscription updated: {str(e)}")
            return False
    
    async def handle_payment_failed(self, event_data: Dict[str, Any]) -> bool:
        """Verwerk een payment_intent.payment_failed of invoice.payment_failed event"""
        try:
            # Haal de klant-ID op
            customer_id = event_data.get('customer')
            if not customer_id:
                logger.error("Geen customer ID in payment failed event")
                return False
            
            # Zoek de gebruiker op basis van stripe_customer_id
            user_subscriptions = await self.db.get_users_by_customer_id(customer_id)
            
            for user_id in user_subscriptions:
                # Update de abonnementsstatus naar 'past_due'
                await self.db.create_or_update_subscription(
                    user_id=user_id,
                    status='past_due',
                    stripe_customer_id=customer_id
                )
                
                # Stuur een bericht naar de gebruiker over de mislukte betaling
                try:
                    # Controleer of telegram_service beschikbaar is
                    if hasattr(self, 'telegram_service') and self.telegram_service:
                        message = """
⚠️ <b>Betalingswaarschuwing</b> ⚠️

Je betaling voor het SigmaPips abonnement kon niet worden verwerkt.

Om je toegang te behouden, update je betalingsgegevens binnen 3 dagen.

🔄 Klik hier om je betalingsgegevens bij te werken:
                        """
                        # Maak een betaal-update URL
                        update_url = await self.create_update_payment_session(user_id)
                        
                        # Stuur het bericht
                        await self.telegram_service.send_message_to_user(
                            user_id, 
                            message, 
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("💳 Update betaalgegevens", url=update_url)
                            ]])
                        )
                except Exception as msg_error:
                    logger.error(f"Error sending payment failed message: {str(msg_error)}")
            
            logger.info(f"Payment failed verwerkt voor klant {customer_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error handling payment failed: {str(e)}")
            return False
    
    async def cancel_subscription(self, user_id: int) -> bool:
        """Annuleer een abonnement voor een gebruiker"""
        try:
            # Haal het abonnement op
            subscription_data = await self.db.get_user_subscription(user_id)
            
            if not subscription_data or not subscription_data.get('stripe_subscription_id'):
                logger.warning(f"No active subscription found for user {user_id}")
                return False
            
            subscription_id = subscription_data['stripe_subscription_id']
            
            # Annuleer het abonnement in Stripe
            stripe.Subscription.delete(subscription_id)
            
            # Update de database
            await self.db.create_or_update_subscription(
                user_id=user_id,
                status='canceled'
            )
            
            logger.info(f"Canceled subscription for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error canceling subscription: {str(e)}")
            return False
    
    async def handle_webhook_event(self, event):
        """Handle different types of Stripe webhook events"""
        event_type = event['type']
        event_data = event['data']['object']
        
        logger.info(f"Processing Stripe webhook event: {event_type}")
        
        try:
            if event_type == 'checkout.session.completed':
                # Een checkout sessie is voltooid
                await self.handle_checkout_completed(event_data)
                
            elif event_type == 'customer.subscription.created':
                # Nieuw abonnement aangemaakt
                await self.handle_subscription_updated(event_data)
                
            elif event_type == 'customer.subscription.updated':
                # Abonnement gewijzigd
                await self.handle_subscription_updated(event_data)
                
            elif event_type == 'customer.subscription.deleted':
                # Abonnement beëindigd
                await self.handle_subscription_deleted(event_data)
                
            elif event_type == 'invoice.payment_succeeded':
                # Succesvolle betaling
                await self.handle_payment_succeeded(event_data)
                
            elif event_type == 'invoice.payment_failed':
                # Mislukte betaling
                await self.handle_payment_failed(event_data)
                
        except Exception as e:
            logger.error(f"Error processing {event_type} event: {str(e)}")
            raise
    
    async def handle_checkout_completed(self, session_data):
        """Process a completed checkout session"""
        # Haal gebruikers-ID op uit metadata of client reference
        user_id = session_data.get('client_reference_id')
        if not user_id:
            if session_data.get('metadata') and session_data['metadata'].get('user_id'):
                user_id = session_data['metadata']['user_id']
        
        if not user_id:
            logger.error("No user_id found in checkout session data")
            return
        
        # Convert to int if needed
        user_id = int(user_id)
        
        # Registreer customer ID als dit een nieuwe klant is
        customer_id = session_data.get('customer')
        if customer_id:
            # Update user_subscriptions table
            await self.db.update_user_subscription_customer(user_id, customer_id)
        
        logger.info(f"Checkout completed for user {user_id}")

    async def simulate_payment_event(self, event_type="payment_intent.succeeded"):
        """Simuleer een Stripe betaalgebeurtenis"""
        # Simuleer de payload van de gebeurtenis
        event_data = {
            "id": f"evt_test_{int(time.time())}",
            "type": event_type,
            "data": {
                "object": {
                    "id": f"pi_test_{int(time.time())}",
                    "customer": "cus_test123",
                    "amount": 2999,  # €29.99 in centen
                    "status": "succeeded",
                    "metadata": {
                        "user_id": "123456789"  # Voeg hier een echte gebruikers-ID in
                    }
                }
            }
        }
        
        # Verwerk de gesimuleerde gebeurtenis
        db = Database()
        success = await self.process_payment_event(event_data, db)
        
        return success, event_data

    async def create_update_payment_session(self, user_id: int) -> str:
        """Maak een sessie om betalingsgegevens bij te werken"""
        try:
            # Haal gebruikersabonnement op
            subscription = await self.db.get_user_subscription(user_id)
            if not subscription:
                logger.error(f"Geen abonnement gevonden voor gebruiker {user_id}")
                return ""
            
            # Haal stripe customer ID en subscription ID op
            customer_id = subscription.get('stripe_customer_id')
            subscription_id = subscription.get('stripe_subscription_id')
            
            if not customer_id or not subscription_id:
                logger.error(f"Ontbrekende Stripe IDs voor gebruiker {user_id}")
                return ""
            
            # Maak een update payment session
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=f"https://t.me/SignapipsAI_bot?start=return_from_payment"
            )
            
            return session.url
        except Exception as e:
            logger.error(f"Error creating update payment session: {str(e)}")
            return ""

    # Implementeer de andere handler methodes... 
