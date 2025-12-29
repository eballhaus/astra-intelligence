# --- Astra Dashboard API Router (Clean Version v2025.12.27) ---
import random
from api_keys import API_POOLS

def get_best(api_subset=None):
    """
    Intelligent, specialized API routing for Astra Intelligence.
    Each category uses the API best suited for that data type.
    """
    routes = {
        "price": ["POLYGON", "TWELVEDATA", "EODHD"],
        "historical": ["EODHD", "ALPHAVANTAGE", "SIMFIN"],
        "fundamental": ["SIMFIN", "ALPHAVANTAGE", "EODHD"],
        "sentiment": ["FINNHUB", "DATAJOCKEY"],
        "crypto": ["MORALIS", "DATAJOCKEY"],
        "index": ["NASDAQ", "POLYGON"]
    }

    # If a subset is specified and recognized, use that group
    if api_subset in routes:
        chosen_group = api_subset
    else:
        chosen_group = random.choice(list(routes.keys()))

    chosen_api = random.choice(routes[chosen_group])
    return chosen_api
# --- End of File ---
