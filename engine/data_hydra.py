import time

def get_market_sentiment():
    """
    Fallback Hydra sentiment provider.
    Returns mock data when the real Hydra module is unavailable.
    """
    return {
        "summary": "Neutral",
        "fear_greed": "45 (Fear)",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }

