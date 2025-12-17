import random

def get_market_sentiment():
    """Mock function returning simple market sentiment data."""
    sentiments = ["Bullish", "Bearish", "Neutral"]
    confidence = round(random.uniform(0.5, 0.95), 2)
    return {
        "sentiment": random.choice(sentiments),
        "confidence": confidence
    }
