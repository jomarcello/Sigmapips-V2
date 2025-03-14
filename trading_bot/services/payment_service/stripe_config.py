import os
import stripe
import logging

logger = logging.getLogger(__name__)

# Stripe API configuration
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")  # Use your real secret key in .env
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Constants for Stripe products and prices
SUBSCRIPTION_PRICES = {
    "monthly": "price_1R2RNYFKZxUuVABSpzqFQPrD",  # Je echte Stripe Price ID
}

# Product features for the subscription
SUBSCRIPTION_FEATURES = {
    "monthly": {
        "name": "Trading Signals",
        "price": "$29.99/month",
        "trial_days": 14,
        "signals": ["Forex", "Crypto", "Commodities", "Indices"],
        "analysis": True,
        "timeframes": ["1m", "15m", "1h", "4h"]
    }
}

def get_price_id(plan_type=None):
    """Get the Stripe price ID for the subscription"""
    return SUBSCRIPTION_PRICES.get("monthly")

def get_subscription_features(plan_type=None):
    """Get the features for the subscription"""
    return SUBSCRIPTION_FEATURES.get("monthly") 
