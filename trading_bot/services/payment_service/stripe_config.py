import os
import stripe
import logging

logger = logging.getLogger(__name__)

# Stripe API configuratie
stripe.api_key = os.getenv("STRIPE_LIVE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_LIVE_WEBHOOK_SECRET")

# Constants voor Stripe producten en prijzen
SUBSCRIPTION_PRICES = {
    "monthly": os.getenv("STRIPE_LIVE_PRICE_ID"),
}

# Product features for the subscription
SUBSCRIPTION_FEATURES = {
    "monthly": {
        "name": "Trading Signals",
        "price": "$29.99/month",
        "trial_days": 14,
        "signals": ["Forex", "Crypto", "Commodities", "Indices"],
        "analysis": True,
        "timeframes": ["1m", "15m", "1h", "4h"],
        "payment_link": "https://buy.stripe.com/3cs3eF9Hu9256NW9AA"  # Nieuwe subscriptions
    }
}

def get_price_id(plan_type=None):
    """Get the Stripe price ID for the subscription"""
    return SUBSCRIPTION_PRICES.get("monthly")

def get_subscription_features(plan_type=None):
    """Get the features for the subscription"""
    return SUBSCRIPTION_FEATURES.get("monthly")
