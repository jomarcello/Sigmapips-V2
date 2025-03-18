import os
import stripe
import logging

logger = logging.getLogger(__name__)

# Stripe API configuration
stripe.api_key = os.getenv("STRIPE_LIVE_SECRET_KEY", "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")  # Live secret key
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_LIVE_WEBHOOK_SECRET", "whsec_S2YNWS0GYZGDVoCEy0B94vvhqGaOmKoR")  # Live webhook secret

# Constants for Stripe products and prices
SUBSCRIPTION_PRICES = {
    "monthly": os.getenv("STRIPE_LIVE_PRICE_ID", "price_1R2RNYFKZxUuVABSpzqFQPrD"),  # Live price ID
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
