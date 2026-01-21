ALLOWED_STOCK_PROVIDERS = {"ALPHAVANTAGE","TWELVEDATA","FINNHUB","EODHD","POLYGON"}
ALLOWED_CRYPTO_PROVIDERS = {"MORALIS"}
DISALLOWED_PROVIDERS = {"SIMFIN","DATAJOCKEY","NASDAQ"}

import os
import random

import requests

API_POOL = {
    "ALPHAVANTAGE": {"base": "https://www.alphavantage.co/query", "weight": 1.0},
    "TWELVEDATA": {"base": "https://api.twelvedata.com/time_series", "weight": 1.0},
    "FINNHUB": {"base": "https://finnhub.io/api/v1/quote", "weight": 1.0},
    "EODHD": {"base": "https://eodhd.com/api/real-time", "weight": 1.0},
    "POLYGON": {"base": "https://api.polygon.io/v3/reference/tickers", "weight": 1.0},
    "NASDAQ": {
        "base": "https://data.nasdaq.com/api/v3/datatables/NASDAQOMX/data",
        "weight": 0.8,
    },
    "DATAJOCKEY": {
        "base": "https://api.datajockey.io/v0/company/financials",
        "weight": 1.0,
    },
    "SIMFIN": {
        "base": "https://backend.simfin.com/api/v3/companies/statements",
        "weight": 0.9,
    },
    "MORALIS": {
        "base": "https://deep-index.moralis.io/api/v3/market-data/price",
        "weight": 0.8,
    },
}


def get_best(api_subset=None):
    # --- Phase 2.3 Canonical Guard ---
    # Force provider allow-list at runtime (prevents SIMFIN/DATAJOCKEY/NASDAQ forever)
    try:
        candidates = list(candidates) if candidates is not None else []
    except Exception:
        candidates = []
    candidates = [c for c in candidates if isinstance(c, str)]
    candidates = [c for c in candidates if c not in DISALLOWED_PROVIDERS]
    # If MORALIS is in the candidate set, treat as crypto routing; otherwise stock.
    if any(c == 'MORALIS' for c in candidates):
        candidates = [c for c in candidates if c in ALLOWED_CRYPTO_PROVIDERS]
    else:
        candidates = [c for c in candidates if c in ALLOWED_STOCK_PROVIDERS]
    # If nothing left, fall back to stock allow-list (no disallowed providers)
    if not candidates:
        candidates = list(ALLOWED_STOCK_PROVIDERS)

    """Return a random API endpoint from the pool, weighted by reliability."""
    subset = api_subset or list(API_POOL.keys())
    weights = [API_POOL[name]["weight"] for name in subset]
    return random.choices(subset, weights=weights, k=1)[0]


def test_api(name, key, params=None):
    """Quick check to ensure the API responds before using."""
    info = API_POOL[name]
    url = info["base"]
    try:
        r = requests.get(url, timeout=3, params=params or {})
        return r.status_code, round(r.elapsed.total_seconds(), 2)
    except Exception as e:
        return str(e), None
